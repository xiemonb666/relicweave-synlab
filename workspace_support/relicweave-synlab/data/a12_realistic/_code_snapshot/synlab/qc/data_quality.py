"""Read-only data-quality gate: "is this store / export package trainable?" as a *programmatic*
verdict instead of a memory of who fixed what when.

Why this module exists
----------------------
One night of semantics-changing fixes left the data cross-generational:

* ``mask_semantics = coc_units_v2`` (``synlab/observe/render.py::MASK_SEMANTICS``) -- the mask
  unit fix; before it the deployment mask covered 0.26-7.20 % of the object pixels;
* ``damage_semantics = subset_v2`` (``synlab/physical/api.py::DAMAGE_SEMANTICS``) -- A09 damage
  legality (subset / positive volume / watertight);
* the mother **geometry** fix (``synlab/mothers/vessels/common.py``): the climbing wall profile
  was clamped to a constant, so the rim height was truncated.  15 vessels were bumped to
  ``registry_version = 1.1`` and their ``geometry_hash`` changed
  (``docs/a12/mother_geometry_audit.md`` §4.1-4.5);
* observation-side ``obs_semantics`` (``synlab/pipeline.py::OBS_SEMANTICS_V2``) stamping the
  ``-p`` (damaged / physical variant) side of a fracture event so both ends of every R2 can be
  encoded.

A store that mixes assets from before and after those fixes yields a model nobody can interpret.
This module decides that **from the artefacts**, never by timestamp and never by assumption.

What it is not
--------------
* it **never writes to the store or the package** -- the SQLite file is opened ``mode=ro`` and
  every asset file is read, never committed, never re-stamped;
* it **never repairs** anything;
* a marker that is absent is reported as ``MISSING`` -- it is never treated as "probably fine";
* no threshold below was loosened to make any particular store pass.  Every threshold carries
  its source in ``thresholds[]`` of the check it belongs to.

Check ids, thresholds and sources
---------------------------------
============================  ==================================================  =========================
check id                      threshold                                           source
============================  ==================================================  =========================
semantics.mask_semantics      value == ``coc_units_v2``                           ``observe/render.py::MASK_SEMANTICS``
semantics.damage_semantics    value == ``subset_v2``                              ``physical/api.py::DAMAGE_SEMANTICS``
semantics.obs_semantics       value == ``physical_side_v2``                       ``pipeline.py::OBS_SEMANTICS_V2``
semantics.generation_uniform  exactly one generation bucket, zero mixed asset    ``docs/a12/data_semantics_versions.md`` §3
geometry.registry_version     == current registry entry version (1.1)             ``docs/a12/mother_geometry_audit.md`` §4.4
geometry.rim_consistency      ``|z_rim_target_mm - z_rim| <= 2.5 mm``             ``docs/a12/mother_geometry_audit.md`` §4.5
geometry.geometry_hash        mother ``qa.geometry_hash`` present and non-empty   ``mothers/api.py:384`` / ``mothers/audit.py``
qa.census_conservation        PASS + PENDING + FAIL == total assets               ``storage/store.py::QA_PASS/QA_PENDING/QA_FAIL``
qa.release_closure_pass       every asset in a release closure is QA_PASS         plan §30.18 / ``storage/release.py``
training.encodable_endpoints  encodable R2 ends / R2 pairs                        ``training/model.py:313``
training.legal_negatives      >= 1 eligible legal negative                        ``storage/export.py:80,581``
training.per_task_labels      every task has n_allowed > 0 or an explicit marker  ``training/trainer.py:364-442``
training.effective_queries    >= 1 query with encodable positive AND legal neg.   ``docs/a12/training_run.md`` §"训练有效性"
provenance.*                  report-only (git head / dirty / fingerprint)        task brief (e)
============================  ==================================================  =========================

Status vocabulary
-----------------
``PASS``
    the measured hits satisfy the threshold and the denominator is real (``denominator > 0``).
``FAIL``
    the denominator is real and the hits fall short of the threshold.
``MISSING``
    the quantity the check needs is **not recorded anywhere in the artefact**.  A missing marker
    is never a pass: an undecidable generation is exactly what this gate exists to catch.
``NOT_APPLICABLE``
    the check cannot exist for this kind of target (e.g. mother geometry inside an export
    package), with the reason recorded.
``UNREADABLE``
    the file/table exists but could not be read; the failing paths are listed in the check's
    evidence and in the report's top-level ``unreadable`` list.

``trainable`` is true only when every ``required`` check is ``PASS``.  ``verdict`` refines a
negative answer:

``trainable``
    every required check passed.
``partial``
    at least one task has usable supervision (≥1 encodable positive pair) but the target cannot
    train as a whole -- typically ``legal_negatives == 0``, so the ``rank`` task has no
    competition row while the view-level task still does.
``not_trainable``
    no task has usable supervision, or a structural check (generation / QA / provenance) failed.

Exit-code contract for :mod:`tools.check_data_quality`: ``0`` trainable, ``3`` anything else.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import subprocess
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

__all__ = [
    "SCHEMA",
    "CURRENT_GENERATION",
    "LEGACY_GENERATION",
    "MARKER_ROLES",
    "MARKER_FREE_ROLES",
    "RIM_ABSOLUTE_TOLERANCE_MM",
    "RIM_WARN_TOLERANCE_MM",
    "TASK_IDS",
    "QcInputError",
    "assess_target",
    "check_store",
    "check_package",
    "encodable_from_arrays",
    "view_counts_from_arrays",
    "rim_verdict",
    "report_slug",
    "default_report_dir",
    "write_report",
    "format_summary",
]

SCHEMA = "synlab.data_quality.v1"

# --------------------------------------------------------------------------- frozen vocabulary
#: The semantic generation this checkout produces.  A store whose assets are not *all* in this
#: generation cannot be trained on, because the numbers mean different things.
CURRENT_GENERATION: dict[str, str | None] = {
    "mask_semantics": "coc_units_v2",
    "damage_semantics": "subset_v2",
    "obs_semantics": "physical_side_v2",
    "registry_version": "1.1",
}

#: What the pre-fix generation looks like.  ``None`` means "the key does not exist at all",
#: which is how the pre-fix batches are recognised (``docs/a12/data_semantics_versions.md`` §3).
LEGACY_GENERATION: dict[str, str | None] = {
    "mask_semantics": "coc_units_v1_pixel_units",
    "damage_semantics": "subset_v1_as_shipped",
    "obs_semantics": None,
    "registry_version": "1.0",
}

#: Roles whose commit entry writes ``data_semantics`` (which carries ``mask_semantics``):
#: ``docs/a12/data_semantics_versions.md`` §3, first six rows.
DATA_SEMANTICS_ROLES: frozenset[str] = frozenset({
    "mother_mesh", "fragment_mesh", "feature_bundle", "label_bundle", "provenance", "obs_result",
})
#: ``damage_semantics`` additionally lands on the physical roles as a top-level key.
DAMAGE_MARKER_ROLES: frozenset[str] = DATA_SEMANTICS_ROLES | {"physical_result",
                                                              "physical_component"}
#: ``obs_semantics`` is stamped on the observation assets
#: (``synlab/pipeline.py::_stamp_obs_semantics``, asserted by
#: ``data/a12/reports/trainable_prereq_check.json`` on ``role == "obs_result"``).
OBS_MARKER_ROLES: frozenset[str] = frozenset({"obs_result"})

#: Roles whose commit entry writes a semantic marker (``docs/a12/data_semantics_versions.md``
#: §3 table + §6's "the 15 assets of one run, 9 of which carry markers").
MARKER_ROLES: frozenset[str] = DAMAGE_MARKER_ROLES

#: Roles that structurally cannot carry the marker today -- their commit entry is outside the
#: semantics write scope, so they must be judged by the run/role that does carry it
#: (``docs/a12/data_semantics_versions.md`` §3, last paragraph).
MARKER_FREE_ROLES: frozenset[str] = frozenset({
    "clean_truth", "physical_truth", "visible_labels", "pattern_recipe", "pattern_channels",
    "material_profile", "obs_view", "obs_fused_geometry", "degrade_measurement",
    "relation_pool", "query_roster", "qa_report", "display_lod_glb",
})

#: The five training tasks, with the exact skip marker each one raises when it has no
#: supervision (``synlab/training/trainer.py:364-442`` / ``synlab/training/losses.py:44-120``).
TASK_IDS: tuple[str, ...] = ("rank", "view", "correspondence", "quality", "contradiction")
TASK_RUNTIME_SKIP_REASON: dict[str, tuple[str, ...]] = {
    "rank": ("no_encodable_positive_pair",),
    "view": ("fewer_than_two_views", "no_valid_views", "no_positive_view_pair"),
    "correspondence": ("no_correspondence_label",),
    "quality": ("no_valid_quality_target",),
    "contradiction": ("no_contradiction_label",),
}

#: Where a *persisted* structural no-label marker may legitimately live.  Nothing writes these
#: today; the list is the gate's declared search space, so "no marker" is a measured statement.
TASK_MARKER_KEYS: tuple[str, ...] = (
    "task_markers", "label_availability", "labels_absent", "structural_no_label",
    "task_supervision", "no_label_tasks",
)

#: Relation vocabulary (``synlab/training/adapter.py:37-42``).
RELATION_CODES: dict[str, int] = {"R0": 0, "R1": 1, "R2": 2, "TINY_CONTACT": 3, "UNKNOWN": 4}
CODE_TO_KIND: dict[int, str] = {v: k for k, v in RELATION_CODES.items()}

#: A legal negative is ``kind in NEGATIVE_KINDS and valid and loss_mask``
#: (``synlab/storage/export.py:80`` and ``:581-583``).
NEGATIVE_KINDS: frozenset[str] = frozenset({"R0", "R1"})

#: The **signed** rule the geometry audit itself wrote down for "this body was truncated":
#: ``z_rim_target_mm - z_rim > max(2.0 mm, 1 % of the target)``
#: (``data/a12/reports/mother_geometry_audit.json:symptom_rules.S1_profile_truncated``,
#: quoted in ``docs/a12/mother_geometry_audit.md`` §2.1).  A *signed* rule is required, not
#: ``|shortfall| <= 2.5 mm``: the post-fix rim bulge legitimately overshoots, and a measured
#: good asset overshoots by more than 2.5 mm --
#: ``data/a12/reports/geom_fix/s14_frozen_after.json: LIN0006_V09_M09_PAT03.z_rim_shortfall_mm
#: = -3.487551118437068``.  A symmetric 2.5 mm gate would fail that correct asset.
RIM_ABSOLUTE_TOLERANCE_MM = 2.0
RIM_RELATIVE_TOLERANCE = 0.01
#: Reported as a *warning* only (``docs/a12/mother_geometry_audit.md`` §4.5), never a gate.
RIM_WARN_TOLERANCE_MM = 2.5

#: Read caps, so the gate stays a gate and not a full replay.  A cap that actually bites is
#: reported in the check evidence as ``capped: true`` -- never silently.
MAX_FEATURE_PAYLOADS = 512
MAX_RELATION_POOL_ASSETS = 64
MAX_JSON_BYTES = 32 * 1024 * 1024

_CHECK_ORDER = (
    "semantics.mask_semantics",
    "semantics.damage_semantics",
    "semantics.obs_semantics",
    "semantics.generation_uniform",
    "geometry.registry_version",
    "geometry.rim_consistency",
    "geometry.geometry_hash",
    "qa.census_conservation",
    "qa.release_closure_pass",
    "training.encodable_endpoints",
    "training.legal_negatives",
    "training.per_task_labels",
    "training.effective_queries",
    # the contracts added for the t088 context pack and the view channel policy.  They come after
    # the training checks on purpose: an existing target that already fails a training check keeps
    # reporting that failure as its first cause, so adding a check never rewrites a known verdict.
    "contract.declared_role_vocabulary",
    "context.pack_contract",
    "separation.deploy_channel_policy",
    "provenance.export_manifest_hash",
    "provenance.git_and_registry",
)


class QcInputError(RuntimeError):
    """The target is not a store and not an export package (or is unreadable as one)."""


# --------------------------------------------------------------------------------------- model
@dataclass
class Check:
    """One named, reproducible judgement with a real denominator and real hits."""

    id: str
    title: str
    status: str
    required: bool
    denominator: int | None
    hits: int | None
    detail: str = ""
    thresholds: list[dict[str, Any]] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    unreadable: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "required": bool(self.required),
            "denominator": self.denominator,
            "hits": self.hits,
            "detail": self.detail,
            "thresholds": list(self.thresholds),
            "evidence": self.evidence,
            "unreadable": list(self.unreadable),
        }


def _threshold(name: str, value: Any, source: str) -> dict[str, Any]:
    return {"name": name, "value": value, "source": source}


def _read_json(path: Path) -> Any:
    if path.stat().st_size > MAX_JSON_BYTES:
        raise QcInputError(f"{path} is larger than the {MAX_JSON_BYTES} byte json read cap")
    return json.loads(path.read_text(encoding="utf-8"))


def _norm_rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


# ------------------------------------------------------------------------- read-only sqlite view
class _RoStore:
    """Minimal read-only view of an ``AssetStore`` metadata database.

    ``AssetStore.__init__`` mkdirs ``blobs/assets/tmp/releases/reports`` and runs ``_init_db()``,
    so it can never be used by a read-only gate.  This opens the database with
    ``file:...?mode=ro`` instead and reads asset ``meta.json`` payloads as plain files.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.db_path = root / "metadata.sqlite"
        if not self.db_path.exists():
            raise QcInputError(f"{root} has no metadata.sqlite")
        self._conn = sqlite3.connect(f"file:{self.db_path.as_posix()}?mode=ro", uri=True)
        self._conn.row_factory = sqlite3.Row
        self.tables = {r[0] for r in
                       self._conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "assets" not in self.tables:
            raise QcInputError(f"{self.db_path} has no assets table "
                               f"(tables: {sorted(self.tables)})")

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:  # noqa: BLE001 - closing a read-only handle never fails loudly
            pass

    def __enter__(self) -> "_RoStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def rows(self, role: str | None = None) -> list[sqlite3.Row]:
        if role is None:
            return list(self._conn.execute("SELECT * FROM assets ORDER BY created_at, asset_id"))
        return list(self._conn.execute(
            "SELECT * FROM assets WHERE role=? ORDER BY created_at, asset_id", (role,)))

    def run_rows(self) -> list[sqlite3.Row]:
        if "runs" not in self.tables:
            return []
        return list(self._conn.execute("SELECT * FROM runs ORDER BY created_at, run_id"))

    def release_rows(self) -> list[sqlite3.Row]:
        if "releases" not in self.tables:
            return []
        return list(self._conn.execute(
            "SELECT * FROM releases ORDER BY frozen_at, release_id"))

    def arrays(self, row: sqlite3.Row) -> dict[str, Any]:
        import numpy as np

        files = json.loads(row["files_json"] or "{}")
        rel = files.get("arrays")
        if not rel:
            return {}
        path = self.root / Path(*str(rel).split("/"))
        if not path.exists():
            raise QcInputError(f"payload missing: {path}")
        with np.load(path, allow_pickle=False) as data:
            return {k: data[k] for k in data.files}


def _json_col(row: sqlite3.Row, column: str) -> dict[str, Any]:
    try:
        value = json.loads(row[column] or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


# ------------------------------------------------------------------------- marker extraction
def _marker_values(meta: Mapping[str, Any], qa: Mapping[str, Any]) -> dict[str, str]:
    """Resolve the semantic markers of one asset, following the documented key paths.

    ``docs/a12/data_semantics_versions.md`` §3 lists every location a marker is written to;
    this mirrors that table and adds ``qa`` because ``mother_mesh`` records ``geometry_hash``
    inside its audit payload (``synlab/pipeline.py::_commit_mother`` passes ``qa=audit``).
    """
    inner = meta.get("meta") if isinstance(meta.get("meta"), dict) else {}
    mother_meta = meta.get("mother_meta") if isinstance(meta.get("mother_meta"), dict) else {}
    ds_outer = meta.get("data_semantics") if isinstance(meta.get("data_semantics"), dict) else {}
    ds_inner = inner.get("data_semantics") if isinstance(inner.get("data_semantics"), dict) else {}
    ds_mother = (mother_meta.get("data_semantics")
                 if isinstance(mother_meta.get("data_semantics"), dict) else {})
    out: dict[str, str] = {}
    for key in ("mask_semantics", "damage_semantics", "obs_semantics", "registry_version",
                "subset_instrument"):
        for source in (meta, inner, mother_meta, ds_outer, ds_inner, ds_mother, qa):
            if not isinstance(source, Mapping):
                continue
            value = source.get(key)
            if isinstance(value, str) and value:
                out[key] = value
                break
    return out


def _generation_of(values: Mapping[str, str]) -> str:
    """Classify one asset's marker set: ``current`` / ``legacy`` / ``mixed`` / ``missing``."""
    seen: set[str] = set()
    for key, current in CURRENT_GENERATION.items():
        value = values.get(key)
        if value is None:
            continue
        if current is not None and value == current:
            seen.add("current")
        elif value == LEGACY_GENERATION.get(key):
            seen.add("legacy")
        else:
            seen.add(f"other:{key}={value}")
    if not seen:
        return "missing"
    if len(seen) == 1:
        return next(iter(seen))
    return "mixed"


def _rim_metrics(meta: Mapping[str, Any]) -> tuple[float | None, float | None, str]:
    """Return ``(target, realized_or_shortfall, source)`` for one mother asset's rim metrics.

    ``synlab/mothers/vessels/common.py:73-78`` writes ``z_rim_target_mm`` (the requested rim
    height) and ``z_rim_shortfall_mm = target - profile.z_rim`` into ``profile.metrics``; the
    vessel builders carry that mapping into the assembly meta as ``profile_metrics``
    (``synlab/mothers/vessels/group_revolve.py:141`` and friends).
    """
    candidates: list[tuple[Mapping[str, Any], str]] = []
    for key in ("profile_metrics", "metrics", "body", "mother_meta"):
        value = meta.get(key)
        if isinstance(value, Mapping):
            candidates.append((value, key))
            nested = value.get("profile_metrics")
            if isinstance(nested, Mapping):
                candidates.append((nested, f"{key}.profile_metrics"))
    inner = meta.get("meta")
    if isinstance(inner, Mapping) and isinstance(inner.get("profile_metrics"), Mapping):
        candidates.append((inner["profile_metrics"], "meta.profile_metrics"))
    for mapping, where in candidates:
        target = mapping.get("z_rim_target_mm")
        if target is None:
            continue
        shortfall = mapping.get("z_rim_shortfall_mm")
        if shortfall is None:
            realized = mapping.get("z_rim")
            if realized is None:
                continue
            shortfall = float(target) - float(realized)
        return float(target), float(shortfall), f"{where}.z_rim_shortfall_mm"
    return None, None, ""


def rim_verdict(target: float, shortfall: float) -> tuple[bool, str]:
    """Decide "was this body truncated?" with the audit's own **signed** S1 rule.

    Returns ``(ok, reason)``.  ``shortfall > max(RIM_ABSOLUTE_TOLERANCE_MM,
    RIM_RELATIVE_TOLERANCE * |target|)`` means the body stops below the rim its own parameters
    declare -- the pre-fix A2 truncation.  A negative shortfall (the rim bulge overshooting) is
    normal post-fix and is never a failure.  Non-finite values are ``ok=False`` with a distinct
    reason: an unmeasurable rim must not be read as "new".
    """
    if not (math.isfinite(target) and math.isfinite(shortfall)):
        return False, "non_finite_rim_metric"
    limit = max(RIM_ABSOLUTE_TOLERANCE_MM, RIM_RELATIVE_TOLERANCE * abs(target))
    if shortfall > limit:
        return False, f"truncated_below_declared_rim(shortfall={shortfall:.4f}>limit={limit:.4f})"
    return True, "rim_reaches_declared_target"


def _geometry_hash(meta: Mapping[str, Any], qa: Mapping[str, Any]) -> str:
    for source in (qa, meta):
        for key in ("geometry_hash", "stored_geometry_hash"):
            value = source.get(key) if isinstance(source, Mapping) else None
            if isinstance(value, str) and value:
                return value
    return ""


# --------------------------------------------------------------------------- encodability rule
def encodable_from_arrays(arrays: Mapping[str, Any]) -> tuple[bool, dict[str, bool]]:
    """Reconstruct ``synlab/training/model.py:313`` ``valid = (rgb_gate + geo_gate + tok_gate) > 0``.

    The encoder returns ``z_valid[f]``; a fragment is encodable when *any* modality gate is open:

    * ``rgb_gate   = global_valid.any(axis=-1)``                  (``model.py:279``)
    * ``geo_gate   = ((point_valid | normal_valid) & scale_valid).any(axis=-1)``  (``model.py:289-291``)
    * ``tok_gate   = token_valid.any(axis=-1)``                   (``model.py:294``)

    This is a numpy re-derivation, not a call into torch: the gate stays import-light and does
    not need a checkpoint.  ``tests/a12/qc/test_data_quality.py`` pins the mapping.
    """
    import numpy as np

    def _any(name: str) -> bool:
        value = arrays.get(name)
        if value is None:
            return False
        arr = np.asarray(value)
        return bool(arr.size and arr.astype(bool).any())

    rgb = _any("global_valid")
    scale = arrays.get("scale_valid")
    scale_ok = True if scale is None else bool(np.asarray(scale).astype(bool).all())
    geo = scale_ok and (_any("point_valid") or _any("normal_valid") or _any("point_cloud__valid")
                        or _any("normal_field__valid"))
    tok = _any("token_valid") or _any("view_tokens") or _any("token_index")
    return bool(rgb or geo or tok), {"rgb_gate": rgb, "geo_gate": geo, "tok_gate": tok,
                                     "scale_valid": scale_ok}


def view_counts_from_arrays(arrays: Mapping[str, Any]) -> int:
    """Views carrying at least one valid global pixel for the *best* fragment in the payload.

    ``global_valid`` is ``[F, V]`` (``synlab/training/adapter.py:277``); the per-fragment view
    count is the row sum, and the task-``view`` denominator wants the fragments that reach two
    views (``synlab/training/losses.py:82`` skips with ``fewer_than_two_views``).
    """
    import numpy as np

    value = arrays.get("global_valid")
    if value is None:
        return 0
    arr = np.asarray(value).astype(bool)
    if arr.ndim == 2 and arr.shape[0]:
        return int(arr.sum(axis=1).max())
    if arr.ndim == 1:
        return int(arr.sum())
    return 0


# --------------------------------------------------------------------------------- provenance
def _git(repo: Path, *args: str) -> tuple[int, str]:
    try:
        proc = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True,
                              timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:  # pragma: no cover - env dependent
        return 127, f"{type(exc).__name__}: {exc}"
    return proc.returncode, (proc.stdout or proc.stderr or "").strip()


def _registry_state(repo: Path) -> tuple[dict[str, str], str | None, str | None]:
    """Return ``(vessel -> version, REGISTRY.fingerprint(), error)``.

    ``load_all()`` returns per-module import statuses, not the registry; the registry itself is
    the module-level ``REGISTRY`` (``synlab/registry.py:57``, ``fingerprint`` at ``:120-121``).
    """
    try:
        from ..registry import REGISTRY, load_all

        load_all()
        versions = {entry.id: str(entry.version) for entry in REGISTRY.list("vessel")}
        return versions, REGISTRY.fingerprint(), None
    except Exception as exc:  # noqa: BLE001 - reported through the provenance check
        return {}, None, f"{type(exc).__name__}: {exc}"


def provenance(repo: Path) -> dict[str, Any]:
    """git HEAD, dirty state + differing file count, and ``REGISTRY.fingerprint()``.

    The dirty state is **reported, never gated**: the gate itself adds files, so a dirty tree
    is the normal state of a working checkout.  The brief requires the fact and the count.
    """
    out: dict[str, Any] = {"repo": str(repo)}
    code, head = _git(repo, "rev-parse", "HEAD")
    out["git_head"] = head if code == 0 else None
    out["git_head_error"] = None if code == 0 else head
    code, porcelain = _git(repo, "status", "--porcelain")
    if code == 0:
        lines = [ln for ln in porcelain.splitlines() if ln.strip()]
        out["git_dirty"] = bool(lines)
        out["git_dirty_file_count"] = len(lines)
        out["git_dirty_files"] = lines[:200]
        if len(lines) > 200:
            out["git_dirty_files_truncated"] = len(lines) - 200
    else:
        out["git_dirty"] = None
        out["git_dirty_file_count"] = None
        out["git_dirty_error"] = porcelain
    versions, fingerprint, error = _registry_state(repo)
    out["registry_fingerprint"] = fingerprint
    out["registry_versions"] = versions
    if error:
        out["registry_error"] = error
    return out


def _registry_versions(repo: Path) -> dict[str, str]:
    return _registry_state(repo)[0]


# ------------------------------------------------------------------------------ relation table
def _relation_rows_from_pool(store: _RoStore, rows: Sequence[sqlite3.Row],
                             notes: list[str]) -> list[dict[str, Any]]:
    """Rebuild the authoritative pair table exactly like ``storage/export.py::_pool_relations``.

    ``synlab/storage/export.py:821-858`` rebuilds ``{"a","b","kind",...}`` rows from a pool
    asset's sparse index arrays (``rel_a``/``rel_b``/``rel_kind``/``rel_valid``/``rel_loss_mask``
    over ``fragment_ids``).  The gate must not invent a second rule, so this mirrors it verbatim
    and cites it; ``R0`` rows are *never* stored (``relations/gallery.py:134-137``), so an absent
    R0 count is expected here and is reported as such.
    """
    out: list[dict[str, Any]] = []
    pool_rows = [r for r in rows if r["role"] == "relation_pool"]
    if len(pool_rows) > MAX_RELATION_POOL_ASSETS:
        notes.append(f"relation_pool assets capped at {MAX_RELATION_POOL_ASSETS} "
                     f"of {len(pool_rows)}")
        pool_rows = pool_rows[:MAX_RELATION_POOL_ASSETS]
    for row in pool_rows:
        try:
            arrays = store.arrays(row)
        except Exception as exc:  # noqa: BLE001 - recorded, not swallowed
            notes.append(f"{row['asset_id']}: {type(exc).__name__}: {exc}")
            continue
        ids = [str(x) for x in _as_list(arrays.get("fragment_ids"))]
        a = _as_list(arrays.get("rel_a"))
        b = _as_list(arrays.get("rel_b"))
        kind = _as_list(arrays.get("rel_kind"))
        area = _as_list(arrays.get("rel_area_mm2"))
        valid = _as_list(arrays.get("rel_valid"))
        loss = _as_list(arrays.get("rel_loss_mask"))
        for i in range(len(a)):
            ia, ib = int(a[i]), int(b[i])
            if ia >= len(ids) or ib >= len(ids) or ia == ib:
                continue
            out.append({
                "a": ids[ia], "b": ids[ib],
                "kind": CODE_TO_KIND.get(int(kind[i]), "UNKNOWN") if i < len(kind) else "UNKNOWN",
                "area_mm2": float(area[i]) if i < len(area) else 0.0,
                "valid": bool(valid[i]) if i < len(valid) else True,
                "loss_mask": bool(loss[i]) if i < len(loss) else True,
                "pool_asset": row["asset_id"],
            })
    return out


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return list(value)


def _relation_rows_from_labels(rows: Sequence[sqlite3.Row]) -> list[dict[str, Any]]:
    """Fallback source: ``label_bundle.meta.relations_json`` (one JSON array per fragment)."""
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        if row["role"] != "label_bundle":
            continue
        meta = _json_col(row, "meta_json")
        raw = meta.get("relations_json")
        if not isinstance(raw, str) or not raw:
            continue
        try:
            parsed = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(parsed, list):
            continue
        for item in parsed:
            if not isinstance(item, Mapping):
                continue
            a, b = str(item.get("a", "")), str(item.get("b", ""))
            kind = str(item.get("kind", "UNKNOWN"))
            if not a or not b:
                continue
            key = (a, b, kind)
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "a": a, "b": b, "kind": kind,
                "area_mm2": float(item.get("area_mm2") or 0.0),
                "valid": bool(item.get("valid", False)),
                "loss_mask": bool(item.get("loss_mask", False)),
                "pool_asset": "",
            })
    return out


def _eligible_negative(row: Mapping[str, Any]) -> bool:
    """``eligible_as_negative = kind in {R1,R0} and valid and loss_mask`` (export.py:581-583)."""
    return bool(row.get("kind") in NEGATIVE_KINDS and row.get("valid") and row.get("loss_mask"))


def _r2_positive(row: Mapping[str, Any]) -> bool:
    """A confirmed R2 positive (``synlab/qc/loader_probe.py:495-499``)."""
    return bool(row.get("kind") == "R2" and row.get("valid"))


# ------------------------------------------------------------------------------- check builders
def _census(rows: Sequence[sqlite3.Row]) -> dict[str, Any]:
    statuses = Counter(str(r["qa_status"]) for r in rows)
    known = {"QA_PASS", "QA_PENDING", "QA_FAIL"}
    return {
        "total": len(rows),
        "QA_PASS": int(statuses.get("QA_PASS", 0)),
        "QA_PENDING": int(statuses.get("QA_PENDING", 0)),
        "QA_FAIL": int(statuses.get("QA_FAIL", 0)),
        "other_statuses": {k: v for k, v in sorted(statuses.items()) if k not in known},
        "by_role": {role: dict(sorted(Counter(
            str(r["qa_status"]) for r in rows if r["role"] == role).items()))
            for role in sorted({str(r["role"]) for r in rows})},
    }


def _marker_check(marker: str, rows: Sequence[sqlite3.Row], roles: Iterable[str],
                  current: str | None, title: str, source: str) -> Check:
    role_set = set(roles)
    in_scope = [r for r in rows if str(r["role"]) in role_set]
    values: Counter = Counter()
    missing_ids: list[str] = []
    for row in in_scope:
        found = _marker_values(_json_col(row, "meta_json"), _json_col(row, "qa_json"))
        value = found.get(marker)
        if value is None:
            values["<missing>"] += 1
            missing_ids.append(str(row["asset_id"]))
        else:
            values[value] += 1
    hits = int(values.get(str(current), 0))
    denominator = len(in_scope)
    if denominator == 0:
        status, detail = "MISSING", f"no asset of roles {sorted(role_set)} exists in scope"
    elif hits == denominator:
        status, detail = "PASS", f"all {denominator} assets record {marker}={current}"
    else:
        status = "FAIL"
        detail = (f"{hits}/{denominator} assets record {marker}={current}; "
                  f"observed values {dict(values)}")
    return Check(
        id=f"semantics.{marker}", title=title, status=status, required=True,
        denominator=denominator, hits=hits, detail=detail,
        thresholds=[_threshold(marker, current, source)],
        evidence={"roles": sorted(role_set), "value_histogram": dict(values),
                  "missing_asset_ids": missing_ids[:50],
                  "missing_asset_ids_truncated": max(0, len(missing_ids) - 50)},
    )


def _semantics_checks(rows: Sequence[sqlite3.Row]) -> list[Check]:
    checks = [
        _marker_check("mask_semantics", rows, sorted(DATA_SEMANTICS_ROLES),
                      CURRENT_GENERATION["mask_semantics"],
                      "every data_semantics-bearing asset records the v2 mask semantics",
                      "synlab/observe/render.py::MASK_SEMANTICS"),
        _marker_check("damage_semantics", rows, sorted(DAMAGE_MARKER_ROLES),
                      CURRENT_GENERATION["damage_semantics"],
                      "every damage_semantics-bearing asset records the v2 damage semantics",
                      "synlab/physical/api.py::DAMAGE_SEMANTICS"),
        _marker_check("obs_semantics", rows, sorted(OBS_MARKER_ROLES),
                      CURRENT_GENERATION["obs_semantics"],
                      "every obs_result records the two-endpoint observation semantics",
                      "synlab/pipeline.py::OBS_SEMANTICS_V2"),
    ]

    buckets: Counter = Counter()
    per_generation_roles: dict[str, Counter] = defaultdict(Counter)
    mixed_ids: list[str] = []
    marked = [r for r in rows if str(r["role"]) in MARKER_ROLES]
    for row in marked:
        values = _marker_values(_json_col(row, "meta_json"), _json_col(row, "qa_json"))
        generation = _generation_of(values)
        buckets[generation] += 1
        per_generation_roles[generation][str(row["role"])] += 1
        if generation == "mixed":
            mixed_ids.append(str(row["asset_id"]))
    legacy = int(buckets.get("legacy", 0))
    mixed = int(buckets.get("mixed", 0))
    other = {k: v for k, v in buckets.items() if k.startswith("other:")}
    denominator = len(marked)
    missing = int(buckets.get("missing", 0))
    if denominator == 0:
        status, detail = "MISSING", "no marker-bearing asset exists in scope"
    elif legacy == 0 and mixed == 0 and not other:
        status = "PASS"
        detail = (f"one generation only: current={int(buckets.get('current', 0))}, "
                  f"missing={missing} (missing is reported separately, not assumed current)")
    else:
        status = "FAIL"
        detail = (f"mixed generations: current={int(buckets.get('current', 0))}, legacy={legacy}, "
                  f"mixed_within_asset={mixed}, other={other}, missing={missing}")
    checks.append(Check(
        id="semantics.generation_uniform",
        title="no asset mixes the pre-fix and post-fix semantic generations",
        status=status, required=True, denominator=denominator,
        hits=int(buckets.get("current", 0)), detail=detail,
        thresholds=[_threshold("allowed_generations", 1,
                               "docs/a12/data_semantics_versions.md §3")],
        evidence={"generation_buckets": dict(buckets),
                  "roles_per_generation": {k: dict(v) for k, v in per_generation_roles.items()},
                  "mixed_asset_ids": mixed_ids[:50]},
    ))
    return checks


def _geometry_checks(rows: Sequence[sqlite3.Row], registry_versions: Mapping[str, str],
                     repo: Path) -> list[Check]:
    mothers = [r for r in rows if str(r["role"]) == "mother_mesh"]
    checks: list[Check] = []

    # -- registry_version -------------------------------------------------------------------
    hits = 0
    values: Counter = Counter()
    mismatched: list[dict[str, str]] = []
    for row in mothers:
        meta = _json_col(row, "meta_json")
        found = _marker_values(meta, _json_col(row, "qa_json"))
        vessel = str(meta.get("vessel_id") or meta.get("vessel") or "")
        recorded = found.get("registry_version")
        expected = registry_versions.get(vessel)
        if recorded is None:
            values["<missing>"] += 1
            continue
        values[recorded] += 1
        if expected is None or recorded == expected:
            hits += 1
        else:
            mismatched.append({"asset_id": str(row["asset_id"]), "vessel_id": vessel,
                               "recorded": recorded, "current": str(expected)})
    denominator = len(mothers)
    if denominator == 0:
        status, detail = "MISSING", "no mother_mesh asset exists in scope"
    elif hits == denominator:
        status = "PASS"
        detail = f"all {denominator} mothers record the current registry version"
    else:
        status = "MISSING" if not values.get("1.1") and values.get("<missing>") == denominator \
            else "FAIL"
        detail = (f"{hits}/{denominator} mothers record their current registry version; "
                  f"observed {dict(values)}. A mother that does not record registry_version "
                  f"cannot be assigned to a geometry generation from the store alone.")
    checks.append(Check(
        id="geometry.registry_version",
        title="every mother records the registry version it was built with",
        status=status, required=True, denominator=denominator, hits=hits, detail=detail,
        thresholds=[_threshold("registry_version", CURRENT_GENERATION["registry_version"],
                               "docs/a12/mother_geometry_audit.md §4.4 step 1")],
        evidence={"value_histogram": dict(values),
                  "current_registry_versions": dict(sorted(registry_versions.items())),
                  "mismatched": mismatched[:50]},
    ))

    # -- rim consistency ---------------------------------------------------------------------
    rim_denominator = 0
    rim_hits = 0
    rim_rows: list[dict[str, Any]] = []
    rim_reasons: Counter = Counter()
    no_metrics = 0
    for row in mothers:
        meta = _json_col(row, "meta_json")
        target, shortfall, source = _rim_metrics(meta)
        if target is None or shortfall is None:
            no_metrics += 1
            continue
        rim_denominator += 1
        ok, reason = rim_verdict(target, shortfall)
        rim_hits += int(ok)
        rim_reasons[reason.split("(")[0]] += 1
        if len(rim_rows) < 50:
            rim_rows.append({"asset_id": str(row["asset_id"]),
                             "vessel_id": str(meta.get("vessel_id") or ""),
                             "z_rim_target_mm": target, "z_rim_shortfall_mm": shortfall,
                             "ok": ok, "reason": reason, "source": source})
    if rim_denominator == 0:
        rim_status = "MISSING"
        rim_detail = (f"0/{len(mothers)} mothers record profile_metrics.z_rim_target_mm; the "
                      f"parameter/geometry consistency column is not persisted in this target, "
                      f"so the rim generation is undecidable here")
    elif rim_hits == rim_denominator:
        rim_status = "PASS"
        rim_detail = (f"all {rim_denominator} mothers with rim metrics reach their declared rim "
                      f"(signed S1 rule)")
    else:
        rim_status = "FAIL"
        rim_detail = (f"{rim_hits}/{rim_denominator} mothers reach their declared rim; "
                      f"{rim_reasons.get('truncated_below_declared_rim', 0)} are truncated "
                      f"(pre-fix geometry), {rim_reasons.get('non_finite_rim_metric', 0)} are "
                      f"non-finite")
    checks.append(Check(
        id="geometry.rim_consistency",
        title="z_rim reaches z_rim_target_mm (the fix makes the two agree)",
        status=rim_status, required=True, denominator=rim_denominator, hits=rim_hits,
        detail=rim_detail,
        thresholds=[
            _threshold("z_rim_target_mm - z_rim <= mm", RIM_ABSOLUTE_TOLERANCE_MM,
                       "data/a12/reports/mother_geometry_audit.json:symptom_rules."
                       "S1_profile_truncated"),
            _threshold("relative allowance", RIM_RELATIVE_TOLERANCE,
                       "docs/a12/mother_geometry_audit.md §2.1 (max(2.0 mm, 1 % of target))"),
            _threshold("warning-only symmetric band (mm)", RIM_WARN_TOLERANCE_MM,
                       "docs/a12/mother_geometry_audit.md §4.5 -- NOT a gate; the post-fix "
                       "LIN0006_V09_M09_PAT03 overshoots by 3.4876 mm"),
        ],
        evidence={"mothers_without_rim_metrics": no_metrics,
                  "reason_histogram": dict(rim_reasons), "rows": rim_rows},
    ))

    # -- geometry hash recorded (+ cross-check against the recorded reference sets) ----------
    hashed = 0
    prefixes: Counter = Counter()
    reference = _load_reference_hashes(repo)
    hash_generation: Counter = Counter()
    for row in mothers:
        meta = _json_col(row, "meta_json")
        value = _geometry_hash(meta, _json_col(row, "qa_json"))
        if value:
            hashed += 1
            prefixes[str(value)[:12]] += 1
            vessel = str(meta.get("vessel_id") or meta.get("vessel") or "")
            if value in reference["post_fix"]:
                hash_generation["post_fix_reference"] += 1
            elif value in reference["pre_fix"]:
                hash_generation["pre_fix_reference"] += 1
            elif vessel:
                hash_generation["no_reference_for_this_parameter_set"] += 1
            else:
                hash_generation["no_vessel_id"] += 1
    if not mothers:
        hash_status, hash_detail = "MISSING", "no mother_mesh asset exists in scope"
    elif hashed < len(mothers):
        hash_status = "FAIL"
        hash_detail = f"{hashed}/{len(mothers)} mothers record a geometry_hash"
    elif hash_generation.get("pre_fix_reference"):
        hash_status = "FAIL"
        hash_detail = (f"{hash_generation['pre_fix_reference']} mother(s) carry a geometry_hash "
                       f"recorded in the pre-fix audit -- decidable old generation")
    else:
        hash_status = "PASS"
        hash_detail = (
            f"all {hashed} mothers record a geometry_hash; "
            f"{hash_generation.get('post_fix_reference', 0)} match a recorded post-fix reference, "
            f"{hash_generation.get('pre_fix_reference', 0)} a pre-fix reference, "
            f"{hash_generation.get('no_reference_for_this_parameter_set', 0)} have no reference "
            f"for their parameter set (a bare hash does not identify a generation on its own)")
    checks.append(Check(
        id="geometry.geometry_hash",
        title="every mother records its geometry_hash, cross-checked against the recorded audits",
        status=hash_status, required=True, denominator=len(mothers), hits=hashed,
        detail=hash_detail,
        thresholds=[
            _threshold("geometry_hash present", True,
                       "synlab/mothers/api.py:384 / synlab/mothers/audit.py:460"),
            _threshold("hash in a recorded pre-fix reference set", 0,
                       "data/a12/reports/mother_geometry_audit.json (pre-fix)"),
        ],
        evidence={"distinct_prefixes": len(prefixes),
                  "generation_cross_check": dict(hash_generation),
                  "reference_sets": reference["sources"],
                  "reference_size": {"pre_fix": len(reference["pre_fix"]),
                                     "post_fix": len(reference["post_fix"])},
                  "prefix_histogram_head": dict(prefixes.most_common(12))},
    ))
    return checks


def _load_reference_hashes(repo: Path) -> dict[str, Any]:
    """The two recorded geometry audits, as ``{sha256}`` sets keyed by generation.

    Pre-fix: ``data/a12/reports/mother_geometry_audit.json`` -> ``vessels.<VID>.geometry_hash``
    (``docs/a12/mother_geometry_audit.md`` §6, produced by ``s08_analyse.py``).
    Post-fix: ``data/a12/reports/geom_fix/s15_audit_all.json`` -> ``vessels.<VID>.geometry_hash``
    plus ``geom_fix/s14_frozen_after.json`` -> ``<lineage>.geometry_hash``
    (``docs/a12/mother_geometry_audit.md`` §4.2 table).
    """
    out: dict[str, Any] = {"pre_fix": set(), "post_fix": set(), "sources": []}
    reports = repo / "data" / "a12" / "reports"
    pre = reports / "mother_geometry_audit.json"
    if pre.exists():
        try:
            payload = _read_json(pre)
            vessels = payload.get("vessels") or {}
            out["pre_fix"] |= {str(v["geometry_hash"]) for v in vessels.values()
                               if isinstance(v, Mapping) and v.get("geometry_hash")}
            out["sources"].append(_norm_rel(pre, repo))
        except Exception:  # noqa: BLE001 - a reference set is optional evidence
            pass
    for name, kind in (("geom_fix/s15_audit_all.json", "post"),
                       ("geom_fix/s14_frozen_after.json", "post")):
        path = reports / name
        if not path.exists():
            continue
        try:
            payload = _read_json(path)
        except Exception:  # noqa: BLE001
            continue
        vessels = payload.get("vessels") if isinstance(payload, Mapping) else None
        if isinstance(vessels, Mapping):
            for value in vessels.values():
                if isinstance(value, Mapping) and value.get("geometry_hash"):
                    if kind == "post":
                        out["post_fix"].add(str(value["geometry_hash"]))
        lineages = payload.get("lineages") if isinstance(payload, Mapping) else None
        if isinstance(lineages, Mapping):
            for value in lineages.values():
                if isinstance(value, Mapping) and value.get("geometry_hash"):
                    out["post_fix"].add(str(value["geometry_hash"]))
        out["sources"].append(_norm_rel(path, repo))
    return out


def _qa_checks(rows: Sequence[sqlite3.Row], census: Mapping[str, Any],
               closure: Mapping[str, Any]) -> list[Check]:
    checks: list[Check] = []
    total = int(census["total"])
    states = [census.get("QA_PASS"), census.get("QA_PENDING"), census.get("QA_FAIL")]
    if any(value is None for value in states):
        status = "MISSING"
        hits: int | None = 0
        detail = ("this target does not record per-asset QA states, so the three-way "
                  "conservation has no denominator to be checked against")
    elif total == 0:
        status, hits = "MISSING", 0
        detail = "the target holds no assets, so the QA census has a zero denominator"
    else:
        hits = sum(int(value) for value in states)
        if hits == total and not census["other_statuses"]:
            status = "PASS"
            detail = (f"conservation holds: {census['QA_PASS']} + {census['QA_PENDING']} + "
                      f"{census['QA_FAIL']} = {total}")
        else:
            status = "FAIL"
            detail = (f"conservation broken: PASS+PENDING+FAIL = {hits} != total {total}; "
                      f"unknown statuses {census['other_statuses']}")
    checks.append(Check(
        id="qa.census_conservation",
        title="QA_PASS + QA_PENDING + QA_FAIL == total assets",
        status=status, required=True, denominator=total, hits=hits, detail=detail,
        thresholds=[_threshold("sum of the three QA states", "== total",
                               "synlab/storage/store.py QA_PASS/QA_PENDING/QA_FAIL")],
        evidence={"census": dict(census)},
    ))

    assets = int(closure.get("assets") or 0)
    problems = list(closure.get("problems") or [])
    pending = [p for p in problems if "QA_PENDING" in p]
    failed = [p for p in problems if "QA_FAIL" in p]
    other = [p for p in problems if "QA_PENDING" not in p and "QA_FAIL" not in p]
    if assets == 0:
        status = "MISSING"
        detail = (closure.get("note") or
                  "no release closure exists in this target, so no referenced asset can be "
                  "checked for QA_PASS")
        hits: int | None = None
    elif not problems:
        status, hits = "PASS", assets
        detail = f"all {assets} assets in the release closure are QA_PASS"
    else:
        status, hits = "FAIL", assets - len(problems)
        detail = (f"{len(problems)} closure problems: {len(pending)} QA_PENDING, "
                  f"{len(failed)} QA_FAIL, {len(other)} other")
    checks.append(Check(
        id="qa.release_closure_pass",
        title="every asset referenced by a release closure is QA_PASS",
        status=status, required=True, denominator=assets or None,
        hits=hits, detail=detail,
        thresholds=[_threshold("closure problems", 0,
                               "plan §30.18 / synlab/storage/release.py")],
        evidence={"source": closure.get("source", ""), "releases": closure.get("releases", []),
                  "problem_count": len(problems), "problems": problems[:100],
                  "problems_truncated": max(0, len(problems) - 100)},
        unreadable=list(closure.get("unreadable") or []),
    ))
    return checks


def _fragment_id_of(meta: Mapping[str, Any]) -> tuple[str, str]:
    """Resolve a feature bundle's fragment id and say which key it came from.

    ``synlab/pipeline.py::_commit_features`` writes ``fragment_id`` as a **feature** field, and
    the feature-leak repair removed identity fields from ``meta["feature_fields"]`` -- the
    bundles committed before that repair carry no ``fragment_id`` at all, only ``component_id``
    of the form ``<fragment_id>#c<k>`` (measured on ``data/a12``: 33/45 bundles have
    ``component_id`` and 0/45 have ``fragment_id``).  The prefix before ``#`` is the fragment id;
    the derivation and its source are recorded so the denominator stays auditable.
    """
    direct = meta.get("fragment_id")
    if isinstance(direct, str) and direct:
        return direct, "meta.fragment_id"
    component = meta.get("component_id")
    if isinstance(component, str) and "#" in component:
        return component.split("#", 1)[0], "meta.component_id (prefix before '#')"
    return "", ""


def _training_checks_store(store: _RoStore, rows: Sequence[sqlite3.Row],
                           relations: Sequence[Mapping[str, Any]],
                           relation_source: str,
                           notes: list[str]) -> list[Check]:
    # -- encodability of every fragment endpoint --------------------------------------------
    payloads: dict[str, dict[str, Any]] = {}
    unreadable: list[str] = []
    features = [r for r in rows if str(r["role"]) == "feature_bundle"]
    capped = len(features) > MAX_FEATURE_PAYLOADS
    fragment_id_sources: Counter = Counter()
    for row in features[:MAX_FEATURE_PAYLOADS]:
        meta = _json_col(row, "meta_json")
        fid, source = _fragment_id_of(meta)
        if not fid:
            unreadable.append(f"{row['asset_id']}: feature_bundle without meta.fragment_id "
                              f"(keys: {sorted(meta)[:12]})")
            continue
        fragment_id_sources[source] += 1
        try:
            arrays = store.arrays(row)
        except Exception as exc:  # noqa: BLE001 - reported, never assumed
            unreadable.append(f"{row['asset_id']}: {type(exc).__name__}: {exc}")
            continue
        encodable, gates = encodable_from_arrays(arrays)
        payloads[fid] = {"asset_id": str(row["asset_id"]), "encodable": encodable,
                         "gates": gates, "views": view_counts_from_arrays(arrays)}

    endpoints = sorted({str(r["a"]) for r in relations} | {str(r["b"]) for r in relations})
    missing_payload = [e for e in endpoints if e not in payloads]
    not_encodable = [e for e in endpoints if e in payloads and not payloads[e]["encodable"]]
    r2_pairs = [r for r in relations if _r2_positive(r)]
    r2_both = [r for r in r2_pairs
               if payloads.get(str(r["a"]), {}).get("encodable")
               and payloads.get(str(r["b"]), {}).get("encodable")]
    enc_denominator = len(endpoints)
    if enc_denominator == 0:
        enc_status, enc_detail = "MISSING", "no relation endpoint exists in this target"
    elif r2_pairs and len(r2_both) == len(r2_pairs):
        enc_status = "PASS"
        enc_detail = (f"all {len(r2_pairs)} confirmed R2 pairs have both ends encodable")
    else:
        enc_status = "FAIL"
        enc_detail = (f"{len(r2_both)}/{len(r2_pairs)} confirmed R2 pairs have both ends "
                      f"encodable; {len(missing_payload)} endpoints have no feature payload and "
                      f"{len(not_encodable)} have an empty valid mask")
    checks = [Check(
        id="training.encodable_endpoints",
        title="both ends of every confirmed R2 pair are encodable (z_valid / global_valid non-empty)",
        status=enc_status, required=True, denominator=len(r2_pairs) or None,
        hits=len(r2_both), detail=enc_detail,
        thresholds=[_threshold("valid = (rgb_gate + geo_gate + tok_gate) > 0", True,
                               "synlab/training/model.py:313")],
        evidence={"relation_source": relation_source, "endpoints": enc_denominator,
                  "feature_payloads": len(payloads), "capped": capped,
                  "fragment_id_sources": dict(fragment_id_sources),
                  "endpoints_without_payload": missing_payload[:50],
                  "endpoints_not_encodable": not_encodable[:50],
                  "view_counts_head": dict(sorted(
                      (fid, p["views"]) for fid, p in list(payloads.items())[:20]))},
        unreadable=unreadable,
    )]

    # -- legal negatives ---------------------------------------------------------------------
    eligible = [r for r in relations if _eligible_negative(r)]
    kinds = Counter(str(r["kind"]) for r in relations)
    if not relations:
        neg_status, neg_detail = "MISSING", "no relation rows can be reconstructed in this target"
    elif eligible:
        neg_status = "PASS"
        neg_detail = f"{len(eligible)} eligible legal negatives out of {len(relations)} relation rows"
    else:
        neg_status = "FAIL"
        neg_detail = (f"0 eligible legal negatives out of {len(relations)} relation rows; "
                      f"kind histogram {dict(kinds)}. A negative is legal only when "
                      f"kind in {{R1,R0}} and valid and loss_mask.")
    checks.append(Check(
        id="training.legal_negatives",
        title="at least one eligible legal negative exists",
        status=neg_status, required=True, denominator=len(relations) or None,
        hits=len(eligible), detail=neg_detail,
        thresholds=[_threshold("eligible_as_negative rows", ">= 1",
                               "synlab/storage/export.py:80,581-583")],
        evidence={"relation_source": relation_source, "kind_histogram": dict(kinds),
                  "r2_confirmed": len(r2_pairs),
                  "note": ("R0 is implicit and never stored (synlab/relations/gallery.py:134-137), "
                           "so an absent R0 row is a property of the store format, not of the data")
                  if "relation_pool" in relation_source else ""},
    ))

    # -- per task: n_allowed or explicit structural marker -----------------------------------
    task_rows: dict[str, dict[str, Any]] = {}
    task_rows["rank"] = {
        "n_allowed": len([r for r in relations
                          if (payloads.get(str(r["a"]), {}).get("encodable")
                              and payloads.get(str(r["b"]), {}).get("encodable"))]),
        "definition": "relation rows whose two endpoints are both encodable",
    }
    task_rows["view"] = {
        "n_allowed": len([p for p in payloads.values() if int(p["views"]) >= 2]),
        "definition": "fragments with >= 2 views carrying a valid global pixel",
    }
    quality_targets = 0
    for row in features[:MAX_FEATURE_PAYLOADS]:
        try:
            arrays = store.arrays(row)
        except Exception:  # noqa: BLE001 - already recorded by the encodability check
            continue
        value = arrays.get("quality__valid")
        if value is not None:
            import numpy as np

            quality_targets += int(np.asarray(value).astype(bool).sum())
    task_rows["quality"] = {"n_allowed": quality_targets,
                            "definition": "valid observation-only quality targets"}
    corr = 0
    for row in rows:
        if str(row["role"]) != "label_bundle":
            continue
        meta = _json_col(row, "meta_json")
        for key in ("correspondence_edges", "corr_edges", "correspondence_weight_sum"):
            value = meta.get(key)
            if isinstance(value, (int, float)) and float(value) > 0:
                corr += int(float(value))
                break
    task_rows["correspondence"] = {
        "n_allowed": corr,
        "definition": "label_bundle correspondence weight mass (meta.correspondence_edges)",
    }
    cont = 0
    for row in rows:
        if str(row["role"]) not in ("label_bundle", "physical_truth"):
            continue
        meta = _json_col(row, "meta_json")
        value = meta.get("contradiction_labels")
        if isinstance(value, (int, float)) and float(value) > 0:
            cont += int(value)
    task_rows["contradiction"] = {
        "n_allowed": cont,
        "definition": "contradiction labels (meta.contradiction_labels)",
    }

    markers = _scan_task_markers_store(rows)
    for task in TASK_IDS:
        task_rows[task]["structural_marker"] = markers.get(task)
        task_rows[task]["runtime_skip_reason"] = list(TASK_RUNTIME_SKIP_REASON.get(task, ()))
    unsupported = [t for t in TASK_IDS
                   if int(task_rows[t]["n_allowed"]) <= 0 and not task_rows[t]["structural_marker"]]
    checks.append(Check(
        id="training.per_task_labels",
        title="every task has n_allowed > 0 or an explicit structural no-label marker",
        status=("MISSING" if not relations else ("PASS" if not unsupported else "FAIL")),
        required=True, denominator=len(TASK_IDS), hits=len(TASK_IDS) - len(unsupported),
        detail=("every task has supervision or a persisted structural marker"
                if not unsupported else
                f"{len(unsupported)} task(s) have neither labels nor a persisted marker: "
                f"{unsupported}. The runtime skip reason exists only inside a training step "
                f"(trainer.py:364-442); nothing writes it into the store."),
        thresholds=[_threshold("n_allowed per task", "> 0 or explicit marker",
                               "task brief (d) / synlab/training/trainer.py:364-442")],
        evidence={"tasks": task_rows, "marker_keys_searched": list(TASK_MARKER_KEYS),
                  "markers_found": markers},
    ))

    # -- effective queries -------------------------------------------------------------------
    pos_by_query: dict[str, int] = defaultdict(int)
    neg_by_query: dict[str, int] = defaultdict(int)
    for row in relations:
        a, b = str(row["a"]), str(row["b"])
        both = (payloads.get(a, {}).get("encodable") and payloads.get(b, {}).get("encodable"))
        if not both:
            continue
        if _r2_positive(row):
            pos_by_query[a] += 1
        if _eligible_negative(row):
            neg_by_query[a] += 1
            neg_by_query[b] += 1
    effective = sorted(q for q in pos_by_query if neg_by_query.get(q))
    r2_positives_encodable = sum(pos_by_query.values())
    if effective:
        eff_status = "PASS"
        eff_detail = f"{len(effective)} queries have >=1 encodable positive and >=1 encodable legal negative"
    elif r2_positives_encodable and not eligible:
        eff_status = "FAIL"
        eff_detail = (f"0 effective queries: {r2_positives_encodable} encodable positive pairs "
                      f"exist but no legal negative does -- the positive-only tasks can train, "
                      f"the rank task cannot")
    else:
        eff_status = "FAIL"
        eff_detail = (f"0 effective queries: {r2_positives_encodable} encodable positive pairs, "
                      f"{len(eligible)} eligible legal negatives")
    checks.append(Check(
        id="training.effective_queries",
        title="at least one query has an encodable positive and an encodable legal negative",
        status=eff_status, required=True, denominator=len(pos_by_query) or None,
        hits=len(effective), detail=eff_detail,
        thresholds=[_threshold("effective_query_count()", ">= 1",
                               "docs/a12/training_run.md / synlab/training/batch.py:107-120")],
        evidence={"encodable_positive_pairs": r2_positives_encodable,
                  "eligible_legal_negatives": len(eligible),
                  "queries_with_positive": len(pos_by_query),
                  "effective_queries_head": effective[:50]},
    ))
    return checks


def _git_check(repo: Path, rows: Sequence[sqlite3.Row]) -> Check:
    """Report-only provenance: git HEAD, dirty state **with its differing-file count**, the
    registry fingerprint, and the ``run_id`` attribution census.

    ``required=False`` on purpose: this gate writes report files, so a dirty tree is the normal
    state of the checkout, and ``REGISTRY.fingerprint()`` is import-order dependent (measured:
    ``sha256:a96fd2d1…`` with only ``synlab.mothers.api`` imported vs ``sha256:05f69981…`` after
    ``load_all()``), so it can be *recorded* but must not gate a data verdict.
    """
    info = provenance(repo)
    attribution: Counter = Counter()
    for row in rows:
        meta = _json_col(row, "meta_json")
        source = str(meta.get("run_id_source") or "")
        if not source:
            attribution["run_id_absent"] += 1 if not meta.get("run_id") else 0
            attribution["commit_stamped" if meta.get("run_id") else "no_run_id"] += 1
        elif source.startswith("closed_loop._tag_run_assets"):
            attribution["back_stamped_by_run_attribution_repair"] += 1
        else:
            attribution["other_run_id_source"] += 1
    return Check(
        id="provenance.git_and_registry",
        title="git HEAD, dirty state and registry fingerprint (reported, never gating)",
        status="PASS", required=False, denominator=len(rows),
        hits=int(attribution.get("commit_stamped", 0)), detail=(
            f"git HEAD {info.get('git_head')}; dirty={info.get('git_dirty')} with "
            f"{info.get('git_dirty_file_count')} differing files; "
            f"REGISTRY.fingerprint()={info.get('registry_fingerprint')} (report-only: "
            f"import-order dependent)"),
        thresholds=[_threshold("git dirty", "reported, not gated",
                               "task brief (e): 'dirty 必须如实报告并给差异文件数'")],
        evidence={"git_head": info.get("git_head"), "git_dirty": info.get("git_dirty"),
                  "git_dirty_file_count": info.get("git_dirty_file_count"),
                  "git_dirty_files": info.get("git_dirty_files"),
                  "git_dirty_files_truncated": info.get("git_dirty_files_truncated"),
                  "registry_fingerprint": info.get("registry_fingerprint"),
                  "registry_fingerprint_caveat": (
                      "REGISTRY.fingerprint() covers whichever kinds were imported first; it is "
                      "not usable as a generation marker (synlab/registry.py:120-121)"),
                  "registry_versions": info.get("registry_versions"),
                  "run_id_attribution": dict(attribution),
                  "run_id_source_note": (
                      "run_id_source starting with 'closed_loop._tag_run_assets' means the stamp "
                      "was written by tools/closed_loop.py, not by the module that produced the "
                      "asset; there is no per-asset tombstone for the older lineage-based stamps")},
    )


def _scan_task_markers_store(rows: Sequence[sqlite3.Row]) -> dict[str, str]:
    """Look for a *persisted* per-task structural no-label marker; return what was found."""
    found: dict[str, str] = {}
    for row in rows:
        for column in ("meta_json", "qa_json"):
            meta = _json_col(row, column)
            for key in TASK_MARKER_KEYS:
                value = meta.get(key)
                if isinstance(value, Mapping):
                    for task, marker in value.items():
                        if str(task) in TASK_IDS and marker is not None:
                            found.setdefault(str(task), f"{row['role']}.{key}.{task}={marker}")
                elif isinstance(value, (list, tuple, set)):
                    for task in value:
                        if str(task) in TASK_IDS:
                            found.setdefault(str(task), f"{row['role']}.{key}")
    return found


# ------------------------------------------------------------------------------------ package
def _package_closure(manifest: Mapping[str, Any]) -> dict[str, Any]:
    ref = manifest.get("reference_closure")
    if not isinstance(ref, Mapping):
        return {"assets": 0, "problems": [],
                "note": "the export manifest carries no reference_closure block",
                "source": "export_manifest.json:reference_closure"}
    return {
        "assets": int(ref.get("assets") or 0),
        "problems": list(ref.get("problems") or []),
        "files_checked": ref.get("files_checked"),
        "ok": ref.get("ok"),
        "source": "export_manifest.json:reference_closure (measured by "
                  "synlab/storage/export.py at export time)",
        "releases": [str(manifest.get("release_id") or "")],
    }


def _package_relations(package: Path, manifest: Mapping[str, Any],
                       unreadable: list[str]) -> tuple[list[dict[str, Any]], str]:
    rel = package / "research" / "relations.parquet"
    if not rel.exists():
        return [], ""
    try:
        import pyarrow.parquet as pq

        table = pq.read_table(rel)
    except Exception as exc:  # noqa: BLE001 - recorded, not swallowed
        unreadable.append(f"{rel}: {type(exc).__name__}: {exc}")
        return [], ""
    rows = table.to_pylist()
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append({
            "a": str(row.get("query", "")), "b": str(row.get("candidate", "")),
            "kind": str(row.get("kind", "UNKNOWN")),
            "area_mm2": float(row.get("area_mm2") or 0.0),
            "valid": bool(row.get("valid", False)),
            "loss_mask": bool(row.get("loss_mask", False)),
            "eligible_as_negative": bool(row.get("eligible_as_negative", False)),
            "has_observation": bool(row.get("has_observation", False)),
            "pool_asset": "",
        })
    return out, "research/relations.parquet"


def _training_checks_package(package: Path, manifest: Mapping[str, Any],
                             relations: Sequence[Mapping[str, Any]], relation_source: str,
                             unreadable: list[str]) -> list[Check]:
    deploy = package / "deploy" / "deploy_index.json"
    index: dict[str, Any] = {}
    if deploy.exists():
        try:
            payload = _read_json(deploy)
            index = dict(payload.get("rows") or {})
        except Exception as exc:  # noqa: BLE001 - recorded
            unreadable.append(f"{deploy}: {type(exc).__name__}: {exc}")
    else:
        unreadable.append(f"{deploy}: missing")

    def has_payload(fid: str) -> bool:
        row = index.get(fid)
        if not isinstance(row, Mapping):
            return False
        return bool(row.get("obs_shard") or row.get("geometry_shard") or row.get("token_shard"))

    r2_pairs = [r for r in relations if _r2_positive(r)]
    r2_both = [r for r in r2_pairs if has_payload(str(r["a"])) and has_payload(str(r["b"]))]
    endpoints = sorted({str(r["a"]) for r in relations} | {str(r["b"]) for r in relations})
    without = [e for e in endpoints if not has_payload(e)]
    if not r2_pairs:
        enc_status = "MISSING" if not relations else "FAIL"
        enc_detail = "no confirmed R2 pair exists in the package"
    elif len(r2_both) == len(r2_pairs):
        enc_status, enc_detail = "PASS", f"all {len(r2_pairs)} confirmed R2 pairs have both ends shipped"
    else:
        enc_status = "FAIL"
        enc_detail = (f"{len(r2_both)}/{len(r2_pairs)} confirmed R2 pairs have both ends shipped; "
                      f"{len(without)} endpoints carry no deploy payload at all")
    checks = [Check(
        id="training.encodable_endpoints",
        title="both ends of every confirmed R2 pair ship an observation/geometry/token payload",
        status=enc_status, required=True, denominator=len(r2_pairs) or None, hits=len(r2_both),
        detail=enc_detail,
        thresholds=[_threshold("deploy payload present for both endpoints", True,
                               "synlab/training/model.py:313 (shard presence is the "
                               "package-level proxy; the package is not loaded into torch)")],
        evidence={"relation_source": relation_source, "endpoints": len(endpoints),
                  "endpoints_without_payload": without[:50],
                  "deploy_index_rows": len(index),
                  "counts": dict(manifest.get("counts") or {})},
        unreadable=list(unreadable),
    )]

    eligible = [r for r in relations
                if bool(r.get("eligible_as_negative"))
                or _eligible_negative(r)]
    kinds = Counter(str(r["kind"]) for r in relations)
    if not relations:
        neg_status, neg_detail = "MISSING", "the package ships no relations table"
    elif eligible:
        neg_status = "PASS"
        neg_detail = f"{len(eligible)} eligible legal negatives out of {len(relations)} relation rows"
    else:
        neg_status = "FAIL"
        neg_detail = (f"0 eligible legal negatives out of {len(relations)} relation rows; "
                      f"kind histogram {dict(kinds)}")
    checks.append(Check(
        id="training.legal_negatives",
        title="at least one eligible legal negative is shipped",
        status=neg_status, required=True, denominator=len(relations) or None,
        hits=len(eligible), detail=neg_detail,
        thresholds=[_threshold("eligible_as_negative rows", ">= 1",
                               "synlab/storage/export.py:80,581-583")],
        evidence={"relation_source": relation_source, "kind_histogram": dict(kinds),
                  "manifest_relation_kinds": (manifest.get("counts") or {}).get("relation_kinds")},
    ))

    tasks = {t: {"n_allowed": 0, "structural_marker": None,
                 "runtime_skip_reason": list(TASK_RUNTIME_SKIP_REASON.get(t, ()))}
             for t in TASK_IDS}
    tasks["rank"]["n_allowed"] = len([r for r in relations
                                      if has_payload(str(r["a"])) and has_payload(str(r["b"]))])
    tasks["rank"]["definition"] = "relation rows whose two endpoints ship a payload"
    tasks["view"]["n_allowed"] = int((manifest.get("counts") or {}).get("obs_views") or 0)
    tasks["view"]["definition"] = "counts.obs_views (views shipped in the deploy side)"
    tasks["quality"]["n_allowed"] = 0
    tasks["quality"]["definition"] = "quality targets are not summarised in the package manifest"
    tasks["correspondence"]["n_allowed"] = 0
    tasks["correspondence"]["definition"] = "correspondence weights are not summarised in the manifest"
    tasks["contradiction"]["n_allowed"] = 0
    tasks["contradiction"]["definition"] = "contradiction labels are not summarised in the manifest"
    markers: dict[str, str] = {}
    for key in TASK_MARKER_KEYS:
        value = manifest.get(key)
        if isinstance(value, Mapping):
            for task, marker in value.items():
                if str(task) in TASK_IDS and marker is not None:
                    markers.setdefault(str(task), f"manifest.{key}.{task}={marker}")
    for task in TASK_IDS:
        tasks[task]["structural_marker"] = markers.get(task)
    unsupported = [t for t in TASK_IDS
                   if int(tasks[t]["n_allowed"]) <= 0 and not tasks[t]["structural_marker"]]
    checks.append(Check(
        id="training.per_task_labels",
        title="every task has n_allowed > 0 or an explicit structural no-label marker",
        status=("PASS" if not unsupported else ("MISSING" if not relations else "FAIL")),
        required=True, denominator=len(TASK_IDS), hits=len(TASK_IDS) - len(unsupported),
        detail=("every task has supervision or a persisted structural marker" if not unsupported
                else f"{len(unsupported)} task(s) have neither labels nor a persisted marker: "
                     f"{unsupported}"),
        thresholds=[_threshold("n_allowed per task", "> 0 or explicit marker",
                               "task brief (d) / synlab/training/trainer.py:364-442")],
        evidence={"tasks": tasks, "marker_keys_searched": list(TASK_MARKER_KEYS),
                  "markers_found": markers},
    ))

    pos_by_query: dict[str, int] = defaultdict(int)
    neg_by_query: dict[str, int] = defaultdict(int)
    for row in relations:
        a, b = str(row["a"]), str(row["b"])
        both = has_payload(a) and has_payload(b)
        if not both:
            continue
        if _r2_positive(row):
            pos_by_query[a] += 1
        if _eligible_negative(row) or bool(row.get("eligible_as_negative")):
            neg_by_query[a] += 1
            neg_by_query[b] += 1
    effective = sorted(q for q in pos_by_query if neg_by_query.get(q))
    if effective:
        eff_status = "PASS"
        eff_detail = f"{len(effective)} queries have an encodable positive and an encodable legal negative"
    elif pos_by_query and not eligible:
        eff_status = "FAIL"
        eff_detail = (f"0 effective queries: {sum(pos_by_query.values())} shipped positive pairs, "
                      f"no legal negative")
    else:
        eff_status = "FAIL"
        eff_detail = (f"0 effective queries: {sum(pos_by_query.values())} shipped positive pairs, "
                      f"{len(eligible)} legal negatives")
    checks.append(Check(
        id="training.effective_queries",
        title="at least one query has an encodable positive and an encodable legal negative",
        status=eff_status, required=True, denominator=len(pos_by_query) or None,
        hits=len(effective), detail=eff_detail,
        thresholds=[_threshold("effective_query_count()", ">= 1",
                               "docs/a12/training_run.md / synlab/training/batch.py:107-120")],
        evidence={"encodable_positive_pairs": sum(pos_by_query.values()),
                  "eligible_legal_negatives": len(eligible),
                  "effective_queries_head": effective[:50]},
    ))
    return checks


# -------------------------------------------------------------------------------------
# simulated excavation context (plan t088) + deployment-view channel separation
# -------------------------------------------------------------------------------------
#: Roles whose metadata is expected to carry the batch identity of the simulated context.
CONTEXT_BEARING_ROLES: tuple[str, ...] = (
    "fragment_mesh", "obs_result", "clean_truth", "physical_truth", "visible_labels",
    "label_bundle", "provenance",
)
#: Roles that deliberately do **not** carry a bag (the mother and a pattern are the vessel, not
#: a sherd of one excavation bag).
CONTEXT_FREE_ROLES: tuple[str, ...] = ("mother_mesh", "pattern_recipe", "pattern_channels",
                                       "material_profile", "context_pack")
#: The names of a simulated context pack.  All of them are *generated* values: no element of this
#: contract may be read as an archaeological record (plan t088: "模拟出土区、层位、袋号/坑位等可控
#: 元数据"; p1146: a pit/stratum field may only be used when it is real and trustworthy).
CONTEXT_PACK_FIELDS: tuple[str, ...] = (
    "simulated", "excavation_area_id", "grid_ref", "stratum_id", "stratum_depth_mm",
    "bag_id", "pit_id", "context_id", "batch_id", "coexistents", "scale_reference",
    "session_id", "operator_id", "captured_at", "site_notes",
)
#: Requirement per pack field: ``("value",)`` means a non-empty scalar, ``("list",)`` a list.
CONTEXT_PACK_LIST_FIELDS: frozenset[str] = frozenset({"coexistents"})
CONTEXT_PACK_SCHEMA = "synlab.context.v1"


def _context_pack_checks(rows: Sequence[sqlite3.Row], *, required: bool,
                         source: str) -> Check:
    """The simulated context packs of a store: present, marked simulated, complete, addressable.

    Four judgements in one check, all measured: every pack declares ``simulated is True``; every
    field of :data:`CONTEXT_PACK_FIELDS` carries a real value; every fragment whose asset carries
    a ``context_id`` resolves to a pack that names it in ``coexistents`` (so "given a fragment,
    which batches are its candidates" is answerable from the store); and the pack holds no
    answer-side field (``lineage_id``/``mother_id``/``relation``/... anywhere in its document).
    """
    packs = [r for r in rows if str(r["role"]) == "context_pack"]
    census = Counter(str(r["role"]) for r in rows)
    denominators = {role: int(census.get(role, 0)) for role in CONTEXT_BEARING_ROLES}
    problems: list[str] = []
    incomplete: list[str] = []
    not_simulated: list[str] = []
    answer_fields: list[str] = []
    pack_meta: list[dict[str, Any]] = []
    batch_sizes: Counter = Counter()
    coexistents: list[int] = []
    scale_kinds: Counter = Counter()
    by_context: dict[str, sqlite3.Row] = {}
    for row in packs:
        meta = _json_col(row, "meta_json")
        asset_id = str(row["asset_id"])
        if meta.get("simulated") is not True:
            not_simulated.append(f"{asset_id}: simulated={meta.get('simulated')!r}")
        missing = [name for name in CONTEXT_PACK_FIELDS
                   if (not meta.get(name) and name not in CONTEXT_PACK_LIST_FIELDS)
                   or (name in CONTEXT_PACK_LIST_FIELDS
                       and not isinstance(meta.get(name), (list, tuple)))]
        if missing:
            incomplete.append(f"{asset_id}: {missing}")
        found = sorted(_leaked_context_fields(meta))
        if found:
            answer_fields.append(f"{asset_id}: {found}")
        for key in ("stratum_depth_mm",):
            if not isinstance(meta.get(key), int):
                incomplete.append(f"{asset_id}: {key} is not an integer depth in mm")
        scale = meta.get("scale_reference")
        if not isinstance(scale, Mapping) or not scale.get("scale_reference_kind"):
            incomplete.append(f"{asset_id}: scale_reference has no scale_reference_kind")
        else:
            scale_kinds[str(scale.get("scale_reference_kind"))] += 1
        batch_sizes[int(meta.get("batch_size") or 0)] += 1
        coexistents.append(len(meta.get("coexistents") or []))
        by_context[str(meta.get("context_id", ""))] = row
        pack_meta.append({"asset_id": asset_id, "context_id": meta.get("context_id"),
                          "batch_id": meta.get("batch_id"), "bag_id": meta.get("bag_id"),
                          "simulated": meta.get("simulated"),
                          "batch_size": meta.get("batch_size")})

    # addressability: every fragment carrying a context_id must be resolvable to its pack
    unresolvable: list[str] = []
    carriers = 0
    for row in rows:
        if str(row["role"]) != "fragment_mesh":
            continue
        meta = _json_col(row, "meta_json")
        context_id = str(meta.get("context_id", "") or "")
        if not context_id:
            continue
        carriers += 1
        pack = by_context.get(context_id)
        if pack is None:
            unresolvable.append(f"{row['asset_id']}: context_id {context_id!r} has no pack")
            continue
        pack_doc = _json_col(pack, "meta_json")
        members = {str(item.get("id", "")) for item in (pack_doc.get("coexistents") or [])
                   if isinstance(item, Mapping)}
        if str(meta.get("fragment_id", "")) not in members:
            unresolvable.append(
                f"{row['asset_id']}: fragment {meta.get('fragment_id')!r} is not a member of its "
                f"own pack {pack['asset_id']}")

    if not required and not packs:
        return Check(
            id="context.pack_contract",
            title="a simulated excavation context pack exists, is marked simulated and is complete",
            status="NOT_APPLICABLE", required=False, denominator=0, hits=0,
            detail=("this release declares no context_pack asset; the context contract belongs to "
                    "the store that produces one, so it is judged there"),
            evidence={"context_packs": 0, "source": source,
                      "roles_expected_to_carry_context": list(CONTEXT_BEARING_ROLES)},
        )
    if not packs:
        return Check(
            id="context.pack_contract",
            title="a simulated excavation context pack exists, is marked simulated and is complete",
            status="MISSING", required=True, denominator=1, hits=0,
            detail=("the release declares no context_pack asset, so 'a fragment's same-batch "
                    "candidate scope' cannot be answered from this data at all"),
            thresholds=[_threshold("context_pack assets in the release", ">= 1",
                                   "docs/a12/v144_project_core.md t088 / D3")],
            evidence={"roles_present": {k: v for k, v in sorted(census.items())}},
        )
    problems.extend(not_simulated)
    problems.extend(incomplete)
    problems.extend(answer_fields)
    problems.extend(unresolvable)
    status = "PASS" if not problems else "FAIL"
    detail = (f"{len(packs)} simulated context pack(s); every field present, simulated=true, and "
              f"{carriers} context-carrying fragment(s) resolve to their own pack"
              if not problems else
              f"{len(problems)} problem(s) across {len(packs)} pack(s): "
              f"{len(not_simulated)} not marked simulated, {len(incomplete)} incomplete, "
              f"{len(answer_fields)} carrying answer-side fields, {len(unresolvable)} unresolvable")
    return Check(
        id="context.pack_contract",
        title="a simulated excavation context pack exists, is marked simulated and is complete",
        status=status, required=True, denominator=len(packs), hits=len(packs) - len(
            {p.split(':', 1)[0] for p in problems}),
        detail=detail,
        thresholds=[
            _threshold("simulated", "True (mandatory: the fields are generated, not observed)",
                       "docs/a12/v144_project_core.md t088"),
            _threshold("fields present", list(CONTEXT_PACK_FIELDS), "t088 / D3 / D5"),
            _threshold("schema", CONTEXT_PACK_SCHEMA, "synlab/roles.py SCHEMA_CONTEXT"),
        ],
        evidence={"source": source, "packs": pack_meta[:50],
                  "batch_size_histogram": dict(sorted(batch_sizes.items())),
                  "coexistents_per_pack": sorted(coexistents),
                  "scale_reference_kinds": dict(sorted(scale_kinds.items())),
                  "context_carrying_fragments": carriers,
                  "not_simulated": not_simulated[:20],
                  "incomplete": incomplete[:20],
                  "answer_side_fields": answer_fields[:20],
                  "unresolvable": unresolvable[:20],
                  "roles_expected_to_carry_context": list(CONTEXT_BEARING_ROLES),
                  "roles_deliberately_without_a_bag": list(CONTEXT_FREE_ROLES),
                  "role_denominators": denominators},
    )


def _leaked_context_fields(meta: Mapping[str, Any]) -> set[str]:
    """Answer-side field names found anywhere inside a context document (recursive)."""
    forbidden = {"lineage_id", "mother_id", "fragment_id", "event_id", "split", "seed",
                 "seed_ref", "historical_R2", "mate_present", "relation", "relations",
                 "interface_id", "loss_mask", "kind"}
    out: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, Mapping):
            for key, value in node.items():
                if str(key) in forbidden:
                    out.add(str(key))
                walk(value)
        elif isinstance(node, (list, tuple)):
            for item in node:
                walk(item)

    walk(meta)
    return out


def _declared_store_values(rows: Sequence[sqlite3.Row]) -> tuple[set[str], set[str], set[str]]:
    return ({str(r["schema"]) for r in rows}, {str(r["unit"]) for r in rows},
            {str(r["frame"]) for r in rows})


def _contract_declaration_check(rows: Sequence[sqlite3.Row], repo: Path) -> Check:
    """The role vocabulary of ``synlab/roles.py`` covers every schema/unit/frame in the store.

    ``docs/a12/modality_census.md`` §6.1b measured three undeclared schema ids
    (``synlab.labels.v1``/``synlab.provenance.v1``/``synlab.display_glb.v1``) and three undeclared
    unit/frame values (``m``/``Y_up_m``/``none``) inside real products.  Declaring them fixed the
    *source*; this check keeps the whole product set covered, so the next asset that introduces a
    new schema id fails the gate instead of drifting silently.
    """
    from .. import roles as roles_module

    schemas, units, frames = _declared_store_values(rows)
    unknown_schemas = sorted(schemas - set(roles_module.DECLARED_SCHEMAS))
    unknown_units = sorted(units - set(roles_module.DECLARED_UNITS))
    unknown_frames = sorted(frames - set(roles_module.DECLARED_FRAMES))
    problems = ([f"schema {name}" for name in unknown_schemas]
                + [f"unit {name}" for name in unknown_units]
                + [f"frame {name}" for name in unknown_frames])
    return Check(
        id="contract.declared_role_vocabulary",
        title="every schema/unit/frame in the store is declared in synlab/roles.py",
        status=("PASS" if not problems else "FAIL"), required=True,
        denominator=len(schemas | units | frames), hits=len(schemas | units | frames)
        - len(problems),
        detail=(f"all {len(schemas)} schema id(s), {len(units)} unit(s) and {len(frames)} "
                f"frame(s) are declared"
                if not problems else f"undeclared values: {problems}"),
        thresholds=[_threshold("undeclared schema/unit/frame values", "0",
                               "synlab/roles.py DECLARED_SCHEMAS/DECLARED_UNITS/DECLARED_FRAMES")],
        evidence={"schemas": sorted(schemas), "units": sorted(units), "frames": sorted(frames),
                  "undeclared": problems,
                  "declaration_source": str(repo / "synlab" / "roles.py")},
    )


def _package_channel_check(package: Path, manifest: Mapping[str, Any],
                           unreadable: list[str]) -> Check:
    """The deployment view's channels against the channel policy, measured on the package.

    Two independent readings of the same package are compared: the exporter's own
    ``separation.channel_separation`` block and a fresh scan of ``deploy/`` performed here.  The
    check fails when a research-only channel appears in the deployment view, when a permitted
    channel is absent from the package *and* was not reported as missing, or when a channel file
    exists that the policy does not permit in that view.
    """
    from ..storage.export import (VIEW_DEPLOY, VIEW_RESEARCH, declared_channels,
                                  load_channel_policy, observed_channels)

    try:
        policy = load_channel_policy()
    except Exception as exc:  # noqa: BLE001 - an unreadable policy is a failure, not a skip
        return Check(
            id="separation.deploy_channel_policy",
            title="the deployment view carries exactly the channels the policy permits",
            status="UNREADABLE", required=True, denominator=1, hits=0,
            detail=f"the view channel policy could not be read: {type(exc).__name__}: {exc}",
            evidence={"manifest_separation": dict(manifest.get("separation") or {})},
            unreadable=[str(exc)],
        )
    deploy_scan = observed_channels(package / VIEW_DEPLOY)
    research_scan = observed_channels(package / VIEW_RESEARCH)
    deploy_declared = declared_channels(package / VIEW_DEPLOY)
    permitted = [str(item["key"]) for item in (policy.get("channels") or {}).get(VIEW_DEPLOY, [])]
    research_only = set(policy.get("research_only") or [])
    present = set(deploy_scan["counts"])
    leaks = sorted(present & research_only)
    unexpected = sorted(present - set(permitted))
    reported = ((manifest.get("separation") or {}).get("channel_separation") or {})
    reported_status = dict((reported.get(VIEW_DEPLOY) or {}).get("status") or {})
    per_fragment = _per_fragment_channels(manifest)
    missing = sorted(key for key in permitted
                     if deploy_scan["counts"].get(key, 0) == 0
                     and per_fragment.get(key, 0) == 0)
    # the exporter declares the channel set it wrote; a channel it declared but that no file
    # carries is a disagreement between the manifest and the bytes on disk
    disagreements = sorted(key for key in permitted
                           if reported_status.get(key) == "included"
                           and deploy_scan["counts"].get(key, 0) == 0
                           and per_fragment.get(key, 0) == 0)
    problems = leaks + unexpected + disagreements
    reason = ""
    if not problems and not manifest.get("separation"):
        reason = "the manifest carries no separation block to compare against"
    return Check(
        id="separation.deploy_channel_policy",
        title="the deployment view carries exactly the channels the policy permits",
        status=("PASS" if not problems else "FAIL"), required=True,
        denominator=len(permitted), hits=len(permitted) - len(missing),
        detail=(f"{len(permitted)} permitted channel(s); none of the "
                f"{len(research_only)} research-only channel(s) is present in deploy/"
                if not problems else
                f"problem(s): leaked={leaks} unexpected={unexpected} "
                f"reported_included_but_absent={disagreements}"
                + (f" ({reason})" if reason else "")),
        thresholds=[
            _threshold("research-only channels present in deploy/", "0",
                       "synlab/schemas/view_channels.json (views.research.channels)"),
            _threshold("channel files not permitted in deploy/", "0",
                       "synlab/schemas/view_channels.json (views.deploy.channels)"),
        ],
        evidence={
            "policy": {"path": policy.get("path"), "hash": policy.get("hash"),
                       "schema": policy.get("schema")},
            "deploy_channels_present": sorted(present),
            "deploy_channels_declared": deploy_declared.get("channels"),
            "deploy_files_by_channel": deploy_scan["channels"],
            "research_channels_present": sorted(research_scan["counts"]),
            "permitted_deploy": permitted,
            "permitted_research": [str(item["key"]) for item in
                                   (policy.get("channels") or {}).get(VIEW_RESEARCH, [])],
            "research_only_channels": sorted(research_only),
            "permitted_but_absent": missing,
            "leaked": leaks, "unexpected": unexpected,
            "reported_included_but_absent": disagreements,
            "exporter_report_status": reported_status,
            "deploy_channels_per_fragment_from_manifest": per_fragment,
            "truth_roles": dict(policy.get("truth_roles") or {}),
        },
        unreadable=list(unreadable),
    )


def _per_fragment_channels(manifest: Mapping[str, Any]) -> dict[str, int]:
    """How many fragments the manifest says carry each deployment channel.

    Read from ``counts.deploy_channels_per_fragment``, which the exporter fills from the shards it
    actually wrote; an absent key means "no fragment carried this channel".
    """
    counts = (manifest.get("counts") or {}).get("deploy_channels_per_fragment")
    if not isinstance(counts, Mapping):
        return {}
    return {str(key): int(value or 0) for key, value in counts.items()}


# ------------------------------------------------------------------------------------- driver
def _verdict(checks: Sequence[Check]) -> tuple[bool, str, dict[str, Any] | None]:
    """``trainable`` iff no required check is ``FAIL`` / ``MISSING`` / ``UNREADABLE``.

    ``NOT_APPLICABLE`` does not block: a check that cannot exist for this kind of target (mother
    geometry inside an export package) is not evidence of a defect -- it is evidence that the
    target must be paired with the artefact that *does* carry the quantity, which the check's
    own detail states.
    """
    blocking = {"FAIL", "MISSING", "UNREADABLE"}
    required = [c for c in checks if c.required]
    failing = [c for c in required if c.status in blocking]
    trainable = not failing
    first = None
    if failing:
        ordered = sorted(failing, key=lambda c: (_CHECK_ORDER.index(c.id)
                                                 if c.id in _CHECK_ORDER else 999, c.id))
        lead = ordered[0]
        first = {"check_id": lead.id, "status": lead.status, "detail": lead.detail}
    if trainable:
        return True, "trainable", None
    # ``partial`` has exactly one meaning: there is supervision, but there is no legal negative,
    # so the positive-only tasks can train while the ``rank`` task cannot.  It is the
    # intermediate verdict the brief asks for when ``negatives == 0`` but encodable positives
    # remain.  Any other blocking failure is a plain ``not_trainable``.
    negatives = next((c for c in checks if c.id == "training.legal_negatives"), None)
    effective = next((c for c in checks if c.id == "training.effective_queries"), None)
    if negatives is not None and negatives.status == "FAIL" and not negatives.hits:
        if effective is not None and int((effective.evidence or {}).get(
                "encodable_positive_pairs") or 0) > 0:
            return False, "partial", first
    return False, "not_trainable", first


def _assemble(target: Path, kind: str, checks: list[Check], census: Mapping[str, Any],
              repo: Path, extra: Mapping[str, Any]) -> dict[str, Any]:
    from ..canonical import hash_json

    ordered = sorted(checks, key=lambda c: (_CHECK_ORDER.index(c.id) if c.id in _CHECK_ORDER
                                            else 999, c.id))
    trainable, verdict, first_cause = _verdict(ordered)
    unreadable = sorted({item for c in ordered for item in c.unreadable})
    body = {
        "schema": SCHEMA,
        "target": {"path": _norm_rel(target, repo), "kind": kind,
                   "abs_path": str(target), "exists": target.exists()},
        "verdict": verdict,
        "trainable": trainable,
        "first_cause": first_cause,
        "counts": dict(census),
        "checks": [c.as_dict() for c in ordered],
        "provenance": provenance(repo),
        "unreadable": unreadable,
        "read_only": True,
        "honesty": {
            "mutates_data": False,
            "relaxed_thresholds": [],
            "missing_is_not_a_pass": True,
            "note": ("a marker that is absent is reported as MISSING and makes the target "
                     "untrainable; no threshold was loosened for any target"),
        },
    }
    body.update(dict(extra))
    body["report_hash"] = hash_json(body)
    return body


def check_store(root: str | Path, *, repo: str | Path | None = None,
                extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Assess an ``AssetStore`` root read-only and return the structured verdict."""
    root = Path(root)
    repo = Path(repo) if repo is not None else _guess_repo(root)
    with _RoStore(root) as store:
        rows = store.rows()
        census = _census(rows)
        registry_versions = _registry_versions(repo)
        checks: list[Check] = []
        checks += _semantics_checks(rows)
        checks += _geometry_checks(rows, registry_versions, repo)
        checks.append(_contract_declaration_check(rows, repo))
        # the simulated excavation context (plan t088) and its addressability from a fragment
        checks.append(_context_pack_checks(
            rows, required=True,
            source="assets table (role=context_pack) + meta_json of every fragment"))
        checks += _qa_checks(rows, census, _store_closure(store, rows, repo))
        checks.append(_git_check(repo, rows))
        notes: list[str] = []
        relations = _relation_rows_from_pool(store, rows, notes)
        source = "relation_pool sparse index (mirrors storage/export.py:821-858)"
        if not relations:
            relations = _relation_rows_from_labels(rows)
            source = ("label_bundle.meta.relations_json "
                      "(no relation_pool asset in this store)")
        unreadable = list(notes)
        training = _training_checks_store(store, rows, relations, source, notes)
        if notes:
            training[-1].unreadable.extend(notes)
        checks += training
    return _assemble(root, "store", checks, census, repo,
                     {"relation_rows": len(relations), "relation_source": source,
                      **(dict(extra) if extra else {})})


def _resolve_release_manifest(store_root: Path, repo: Path, rel_id: str,
                              raw: str) -> tuple[Path | None, list[str]]:
    """``releases.manifest_path`` is written relative to the *process* cwd (usually the repo
    root), not to the store, so every plausible base is tried and each miss is recorded."""
    tried: list[str] = []
    candidate = Path(raw)
    bases: list[Path] = []
    if candidate.is_absolute():
        bases.append(candidate)
    else:
        bases.append(repo / candidate)
        bases.append(store_root / candidate)
        bases.append(store_root / "releases" / rel_id / "manifest.json")
        bases.append(store_root / "releases" / f"{rel_id}.json")
    for base in bases:
        tried.append(str(base))
        if base.exists():
            return base, tried
    return None, tried


def _store_closure(store: _RoStore, rows: Sequence[sqlite3.Row],
                   repo: Path | None = None) -> dict[str, Any]:
    """QA status of every asset referenced by a frozen release manifest.

    ``releases.manifest_path`` points at a ``release_manifest.json`` whose ``assets`` list names
    every asset in the closure; an asset that is referenced but not QA_PASS makes the release
    unusable (plan §30.18).
    """
    release_rows = store.release_rows()
    if not release_rows:
        return {"assets": 0, "problems": [], "releases": [], "unreadable": [],
                "note": "this store has no frozen release, so there is no release closure to check"}
    by_id = {str(r["asset_id"]): str(r["qa_status"]) for r in rows}
    problems: list[str] = []
    unreadable: list[str] = []
    referenced: dict[str, str] = {}
    releases: list[dict[str, Any]] = []
    for row in release_rows:
        rel_id = str(row["release_id"])
        path, tried = _resolve_release_manifest(store.root, repo or store.root, rel_id,
                                                str(row["manifest_path"]))
        if path is None:
            unreadable.append(f"release {rel_id}: manifest not found; tried {tried}")
            continue
        try:
            manifest = _read_json(path)
        except Exception as exc:  # noqa: BLE001 - recorded
            unreadable.append(f"release {rel_id}: {type(exc).__name__}: {exc}")
            continue
        assets = manifest.get("assets") or []
        releases.append({"release_id": rel_id, "manifest": _norm_rel(path, store.root),
                         "assets": len(assets)})
        for item in assets:
            if not isinstance(item, Mapping):
                continue
            asset_id = str(item.get("asset_id") or item.get("id") or "")
            if not asset_id:
                continue
            status = by_id.get(asset_id)
            if status is None:
                problems.append(f"release {rel_id}: referenced asset {asset_id} is not in the store")
                continue
            referenced.setdefault(asset_id, status)
            if status != "QA_PASS":
                problems.append(f"release {rel_id}: asset {asset_id} qa_status={status}")
    return {"assets": len(referenced), "problems": problems, "releases": releases,
            "unreadable": unreadable,
            "source": "releases.manifest_path -> release_manifest.json assets[].asset_id vs "
                      "assets.qa_status"}


def check_package(package: str | Path, *, repo: str | Path | None = None,
                  extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Assess an exported training package read-only and return the structured verdict."""
    package = Path(package)
    repo = Path(repo) if repo is not None else _guess_repo(package)
    manifest_path = package / "export_manifest.json"
    if not manifest_path.exists():
        raise QcInputError(f"{package} has no export_manifest.json")
    manifest = _read_json(manifest_path)
    unreadable: list[str] = []
    census = {
        "total": int((manifest.get("assets") or {}).get("count") or 0),
        "QA_PASS": None, "QA_PENDING": None, "QA_FAIL": None,
        "by_role": dict((manifest.get("assets") or {}).get("by_role") or {}),
        "source": "export_manifest.json:assets (the package does not ship per-asset QA states)",
    }

    # (a) semantics -- the package schema carries no semantic marker at all.
    checks: list[Check] = []
    for marker, roles, source in (
        ("mask_semantics", MARKER_ROLES, "synlab/observe/render.py::MASK_SEMANTICS"),
        ("damage_semantics", MARKER_ROLES, "synlab/physical/api.py::DAMAGE_SEMANTICS"),
        ("obs_semantics", ["obs_result"], "synlab/pipeline.py::OBS_SEMANTICS_V2"),
    ):
        checks.append(Check(
            id=f"semantics.{marker}",
            title=f"the package states its {marker} generation",
            status="MISSING", required=True, denominator=0, hits=0,
            detail=("the export manifest contains no semantic marker and no per-asset meta, so "
                    "the generation of this package cannot be read from the package itself; "
                    "the package must be paired with a store whose markers are checked"),
            thresholds=[_threshold(marker, CURRENT_GENERATION[marker], source)],
            evidence={"searched": ["export_manifest.json (whole document)"],
                      "roles_that_would_carry_it": sorted(roles)},
        ))
    checks.append(Check(
        id="semantics.generation_uniform",
        title="no asset mixes the pre-fix and post-fix semantic generations",
        status="MISSING", required=True, denominator=0, hits=0,
        detail="no marker is available inside a package, so uniformity is undecidable here",
        thresholds=[_threshold("allowed_generations", 1,
                               "docs/a12/data_semantics_versions.md §3")],
        evidence={"generation_buckets": {}},
    ))

    # (b) geometry -- packages ship no mother metadata.
    checks.append(Check(
        id="geometry.registry_version",
        title="every mother records the registry version it was built with",
        status="NOT_APPLICABLE", required=True, denominator=0, hits=0,
        detail=("an export package carries no mother metadata; the geometry generation is a "
                "property of the source store and must be checked there"),
        thresholds=[_threshold("registry_version", CURRENT_GENERATION["registry_version"],
                               "docs/a12/mother_geometry_audit.md §4.4 step 1")],
        evidence={"expected_roles": ["mother_mesh"], "present_roles": sorted(census["by_role"])},
    ))
    for cid, title, tol, src in (
        ("geometry.rim_consistency",
         "z_rim reaches z_rim_target_mm (the fix makes the two agree)",
         RIM_ABSOLUTE_TOLERANCE_MM, "docs/a12/mother_geometry_audit.md §4.5"),
        ("geometry.geometry_hash", "every mother records its geometry_hash", True,
         "synlab/mothers/api.py:384"),
    ):
        checks.append(Check(
            id=cid, title=title, status="NOT_APPLICABLE", required=True,
            denominator=0, hits=0,
            detail="an export package carries no mother metadata to measure",
            thresholds=[_threshold("threshold", tol, src)],
            evidence={"expected_roles": ["mother_mesh"]},
        ))

    # (b2) a package carries role counts, not per-asset schema/unit/frame rows: the declared-
    # vocabulary check is reported as NOT_APPLICABLE here and judged on the source store.
    checks.append(Check(
        id="contract.declared_role_vocabulary",
        title="every schema/unit/frame in the store is declared in synlab/roles.py",
        status="NOT_APPLICABLE", required=True, denominator=0, hits=0,
        detail=("an export package ships role counts, not per-asset schema/unit/frame rows, so "
                "the vocabulary cannot be checked here; the source store is checked instead"),
        thresholds=[_threshold("undeclared schema/unit/frame values", "0",
                               "synlab/roles.py DECLARED_SCHEMAS/DECLARED_UNITS/DECLARED_FRAMES")],
        evidence={"by_role": dict(census["by_role"])},
    ))

    # (c) QA -- the package cannot verify the three-way census, so the check reports MISSING
    checks += _qa_checks([], census, _package_closure(manifest))

    relations, relation_source = _package_relations(package, manifest, unreadable)
    checks += _training_checks_package(package, manifest, relations, relation_source, unreadable)
    # (d) the two contracts added for the t088 context pack: the packs of the source store and the
    # deployment view's channel set.  Inside a package the context packs are judged from the
    # release's own asset roles (``assets.by_role``), so a release without one is MISSING here.
    checks.append(_context_pack_checks(
        [], required=int((manifest.get("assets") or {}).get("by_role", {})
                         .get("context_pack", 0) or 0) > 0,
        source="export_manifest.json:assets.by_role (a package ships role counts, not meta)"))
    checks.append(_package_channel_check(package, manifest, unreadable))

    # (e) manifest hash + provenance
    checks.append(_manifest_hash_check(package, manifest, repo))
    checks.append(_git_check(repo, []))
    return _assemble(package, "package", checks, census, repo,
                     {"relation_rows": len(relations), "relation_source": relation_source,
                      "package": {
                          "package_id": manifest.get("package_id"),
                          "release_id": manifest.get("release_id"),
                          "manifest_hash": manifest.get("manifest_hash"),
                          "counts": dict(manifest.get("counts") or {}),
                          "release_gates": manifest.get("release_gates"),
                      },
                      **(dict(extra) if extra else {})})


def _manifest_hash_check(package: Path, manifest: Mapping[str, Any], repo: Path) -> Check:
    """Recompute ``manifest_hash`` the way the exporter defines it and compare."""
    from ..canonical import hash_json

    stated = str(manifest.get("manifest_hash") or "")
    if not stated:
        return Check(id="provenance.export_manifest_hash",
                     title="export manifest hash is present and self-consistent",
                     status="MISSING", required=True, denominator=1, hits=0,
                     detail="the manifest records no manifest_hash",
                     thresholds=[_threshold("manifest_hash", "present and recomputable",
                                            "synlab/storage/export.py:807-808")],
                     evidence={"path": _norm_rel(package / "export_manifest.json", repo)})
    try:
        recomputed = hash_json({k: v for k, v in manifest.items() if k != "manifest_hash"})
    except Exception as exc:  # noqa: BLE001 - recorded
        return Check(id="provenance.export_manifest_hash",
                     title="export manifest hash is present and self-consistent",
                     status="UNREADABLE", required=True, denominator=1, hits=0,
                     detail=f"recomputation failed: {type(exc).__name__}: {exc}",
                     thresholds=[_threshold("manifest_hash", "present and recomputable",
                                            "synlab/storage/export.py:807-808")],
                     evidence={"stated": stated}, unreadable=[str(exc)])
    ok = recomputed == stated
    rebuild_note = manifest.get("build")
    return Check(
        id="provenance.export_manifest_hash",
        title="export manifest hash is present and self-consistent",
        status="PASS" if ok else "FAIL", required=True, denominator=1, hits=int(ok),
        detail=(f"manifest_hash recomputes to the stated value {stated}"
                if ok else f"manifest_hash mismatch: stated {stated}, recomputed {recomputed}"),
        thresholds=[_threshold("manifest_hash", "recomputed == stated",
                               "synlab/storage/export.py:807-808")],
        evidence={"stated": stated, "recomputed": recomputed, "build": rebuild_note},
    )


def _missing_manifest_check(store: Path, repo: Path) -> Check:
    return Check(
        id="provenance.export_manifest_hash",
        title="export manifest hash is present and self-consistent",
        status="NOT_APPLICABLE", required=True, denominator=0, hits=0,
        detail=("a store root has no export manifest; each export under data/a12_exports/** is "
                "checked separately by pointing this gate at the package directory"),
        thresholds=[_threshold("manifest_hash", "recomputed == stated",
                               "synlab/storage/export.py:807-808")],
        evidence={"target": _norm_rel(store, repo)},
    )


def assess_target(target: str | Path, *, repo: str | Path | None = None,
                  kind: str | None = None) -> dict[str, Any]:
    """Auto-detect a store root or an export package and return its quality report."""
    path = Path(target)
    if not path.exists():
        raise QcInputError(f"{path} does not exist")
    resolved = kind
    if resolved is None:
        if (path / "metadata.sqlite").exists():
            resolved = "store"
        elif (path / "export_manifest.json").exists():
            resolved = "package"
        else:
            raise QcInputError(
                f"{path} is neither a store (no metadata.sqlite) nor an export package "
                f"(no export_manifest.json)")
    if resolved == "store":
        report = check_store(path, repo=repo)
        report["checks"].append(_missing_manifest_check(path, Path(repo) if repo else
                                                        _guess_repo(path)).as_dict())
        report["checks"] = sorted(report["checks"],
                                  key=lambda c: (_CHECK_ORDER.index(c["id"])
                                                 if c["id"] in _CHECK_ORDER else 999, c["id"]))
        trainable, verdict, first = _verdict_from_dicts(report["checks"])
        report["trainable"] = trainable
        report["verdict"] = verdict
        report["first_cause"] = first
        from ..canonical import hash_json

        report.pop("report_hash", None)
        report["report_hash"] = hash_json(report)
        return report
    if resolved == "package":
        return check_package(path, repo=repo)
    raise QcInputError(f"unknown target kind {resolved!r}")


def _verdict_from_dicts(checks: Sequence[Mapping[str, Any]]) -> tuple[bool, str, dict | None]:
    objs = [Check(id=str(c["id"]), title=str(c.get("title", "")), status=str(c["status"]),
                  required=bool(c.get("required", True)),
                  denominator=c.get("denominator"), hits=c.get("hits"),
                  detail=str(c.get("detail", "")),
                  evidence=dict(c.get("evidence") or {}),
                  unreadable=list(c.get("unreadable") or []))
            for c in checks]
    return _verdict(objs)


def _guess_repo(target: Path) -> Path:
    current = target.resolve()
    for candidate in [current, *current.parents]:
        if (candidate / ".git").exists() or (candidate / "pyproject.toml").exists():
            return candidate
    return current


# -------------------------------------------------------------------------------------- output
def default_report_dir(repo: Path | None = None) -> Path:
    return (repo or _guess_repo(Path.cwd())) / "data" / "a12" / "reports"


def report_slug(target: str | Path, *, repo: str | Path | None = None) -> str:
    path = Path(target)
    repo_path = Path(repo) if repo is not None else _guess_repo(path)
    try:
        rel = path.resolve().relative_to(repo_path.resolve())
        text = str(rel).replace("\\", "/")
    except ValueError:
        text = path.name
    text = text.strip("/") or path.name
    slug = re.sub(r"[^0-9A-Za-z._-]+", "__", text).strip("_")
    return slug.replace("/", "__")


def write_report(report: Mapping[str, Any], target: str | Path, *,
                 repo: str | Path | None = None, out_dir: str | Path | None = None) -> Path:
    """Write ``data/a12/reports/data_quality_<store>.json`` (the only file this gate writes)."""
    directory = Path(out_dir) if out_dir is not None else default_report_dir(
        Path(repo) if repo is not None else None)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"data_quality_{report_slug(target, repo=repo)}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True,
                               default=str) + "\n", encoding="utf-8")
    return path


def format_summary(report: Mapping[str, Any]) -> str:
    """Human-readable one-screen summary: verdict, first cause, then every check."""
    lines: list[str] = []
    target = report.get("target") or {}
    lines.append(f"data quality gate -- {target.get('path')} ({target.get('kind')})")
    lines.append(f"  verdict : {report.get('verdict')}   trainable={report.get('trainable')}")
    first = report.get("first_cause")
    if first:
        lines.append(f"  first   : [{first['status']}] {first['check_id']} -- {first['detail']}")
    lines.append("  checks  :")
    for check in report.get("checks", []):
        denom = check.get("denominator")
        hits = check.get("hits")
        counts = "" if denom is None else f"  ({hits}/{denom})"
        flag = "" if check.get("required") else "  [report-only]"
        lines.append(f"    {check['status']:<14} {check['id']}{counts}{flag}")
        lines.append(f"        {check['detail']}")
    unreadable = report.get("unreadable") or []
    if unreadable:
        lines.append(f"  unreadable ({len(unreadable)}):")
        for item in unreadable[:20]:
            lines.append(f"    - {item}")
    return "\n".join(lines)
