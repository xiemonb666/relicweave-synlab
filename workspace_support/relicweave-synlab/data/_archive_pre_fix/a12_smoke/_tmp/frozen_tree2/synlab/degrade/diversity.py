"""Config-driven **degradation diversity**: turn a generated lineage into real 轴×档位 assets.

Why this module exists
----------------------
The 31 degradation axes were fully implemented and audited at *module* level
(``audit_all_axes`` → 31/31 axes, 155/155 levels), but the **materialised** data was thin: the
demo set covered a subset of axes and the generation config carried two axes per group.  A12's
first job is synthetic volume, so the axes have to produce **assets inside the generation
pipeline**, for the lineage that was just built, on that lineage's own geometry and observation.

What it guarantees (all of it measured, none of it asserted)
------------------------------------------------------------
* **level 0 is a true identity**: it commits nothing and hands back the *source asset record*
  (``asset_id`` unchanged, ``result_hash == source_hash``); the caller can verify both.
* **one basis per axis**: the basis is frozen once (``sample_basis``) and handed to every level,
  so ``basis_id`` is identical across the five levels and the levels stay *paired*.
* **each level is its own asset** under :data:`ROLE_DEGRADE_VARIANT` -- never
  ``feature_bundle``.  The metadata of a variant carries ``axis_id``/``level``/``variant`` (the
  answer side of the factor experiment) and ``roles.FORBIDDEN_FEATURE_FIELDS`` forbids exactly
  those keys inside a feature bundle, so committing a variant as a feature would be a leak.
* **NA keeps its denominator**: an axis that does not apply (material, missing modality, ...)
  is recorded as ``NA`` with the operator's own reason, and the level is still counted in
  ``levels_planned``.  A declared effect that was not measured is recorded as ``FAILED`` with
  the operator's failure code -- neither is dropped and neither is upgraded to a pass.
* **every step is flushed to disk**: ``progress_path`` is rewritten after every level, because
  this host kills long-running Python processes without a traceback.

Source assets (one per axis family, per lineage)
------------------------------------------------
``P``
    The lineage's **target fragment mesh asset** (``ROLE_FRAGMENT_MESH``, the fragment the
    declared damage recipe was applied to), read back through :func:`load_source` so the
    interface face bookkeeping (``origin_kind``/``interface_id``) that the P axes' ROI needs
    travels with it.  Nothing is re-committed: level 0 of a P axis references that asset.
``I``/``G``/``X``
    The lineage's **primary observation** (the damaged target fragment) projected through
    :func:`synlab.degrade.api.bundles_from_observation` and committed under
    :data:`ROLE_DEGRADE_SOURCE`; the committed asset is read back and the *reloaded* bundle is
    the degradation source, so ``source_hash`` describes exactly the bytes level 0 references.

Neighbour-retrieval role of the variants (documented contract, see ``docs/a12/degrade_axes.md``
§9.6): two variants of the same source asset are the *same physical fragment* under two
degradation levels.  They are therefore **same-instance positives** (degradation invariance /
query-side augmentation) and must never be pushed into the mate-task negative pool; across
different sources they are the hard negative candidates of the robustness evaluation.  The
variant metadata carries ``source_asset_id`` + ``axis_id``/``level``/``variant`` so a pool
builder can form those pairs without guessing.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..canonical import hash_file
from ..errors import ErrorCode, SynLabError
from ..roles import SCHEMA_MEASUREMENT, SCHEMA_OBS, SCHEMA_PHYSICAL
from ..schemas.spec import AXIS_IDS
from ..seeds import make_rng
from .api import IN_MEMORY_KEYS, bundles_from_observation
from .registry import get_operator
from .sources import OutputRef, SourceBundle, commit_source, load_source

#: Role of a committed per-family degradation **source** (I/G/X families).
ROLE_DEGRADE_SOURCE = "degrade_source"

#: Role of a committed per-level degradation **variant**.
#:
#: Deliberately *not* ``feature_bundle``: a variant's metadata carries ``axis_id``/``level``/
#: ``variant``, and those keys are exactly what ``roles.FORBIDDEN_FEATURE_FIELDS`` forbids in a
#: feature bundle (the factor answer must not be readable off the asset a model embeds).
ROLE_DEGRADE_VARIANT = "degrade_variant"

#: Schema written for each axis family's variant assets (a degraded bundle keeps the semantic
#: type of its family: physical body / observation / observation estimate).
FAMILY_SCHEMA: dict[str, str] = {
    "P": SCHEMA_PHYSICAL,
    "I": SCHEMA_OBS,
    "G": SCHEMA_OBS,
    "X": SCHEMA_MEASUREMENT,
}

#: Unit written for each axis family (the axes themselves declare their own unit).
FAMILY_UNIT: dict[str, str] = {"P": "mm", "I": "px", "G": "mm", "X": "1"}

#: Semantic tag stored in ``meta.data_semantics`` of every source/variant asset.
DATA_SEMANTICS_TAG = "degrade_diversity_v1"

REPORT_SCHEMA = "synlab.degrade_diversity.report.v1"

DEFAULT_CONFIG_PATH = (Path(__file__).resolve().parents[2] / "configs" / "a12"
                       / "degrade_diversity.yaml")

SELECTIONS = ("declared", "rotate")

#: Metadata keys every variant asset carries (also the export field list).
VARIANT_FIELDS = (
    "axis_id", "family", "stage", "substage", "variant", "level", "factor_kind",
    "basis_id", "basis_seed_ref", "planned", "measured", "units", "realized", "identity",
    "source_hash", "result_hash", "source_asset_id", "source_kind", "status",
    "label_invalidations", "label_status", "calibration_status",
)


# ======================================================================================
# configuration
# ======================================================================================
@dataclass(frozen=True)
class AxisSpec:
    """One declared axis of the diversity config."""

    axis_id: str
    family: str
    variant: str
    levels: tuple[int, ...]
    stage: str
    substage: str
    factor_kind: str
    note: str = ""

    @property
    def source_key(self) -> str:
        return self.family

    def as_dict(self) -> dict[str, Any]:
        return {"axis_id": self.axis_id, "family": self.family, "variant": self.variant,
                "levels": list(self.levels), "stage": self.stage, "substage": self.substage,
                "factor_kind": self.factor_kind, "note": self.note}


@dataclass(frozen=True)
class DiversityConfig:
    """Parsed degradation-diversity config (validated against the live axis registry)."""

    path: Path | None
    enabled: bool
    levels: tuple[int, ...]
    axes: tuple[AxisSpec, ...]
    max_axes_per_lineage: int
    selection: str
    data_semantics: str
    roles: dict[str, str] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    def axes_for_lineage(self, lineage_index: int) -> tuple[AxisSpec, ...]:
        """The axes this lineage materialises (deterministic; declared order or rotation)."""
        total = len(self.axes)
        if total == 0:
            return ()
        count = min(max(int(self.max_axes_per_lineage), 1), total)
        if self.selection == "rotate":
            start = int(lineage_index) % total
            return tuple(self.axes[(start + i) % total] for i in range(count))
        return tuple(self.axes[:count])

    def as_dict(self) -> dict[str, Any]:
        return {"path": (str(self.path) if self.path else None), "enabled": self.enabled,
                "levels": list(self.levels), "axes": [a.as_dict() for a in self.axes],
                "max_axes_per_lineage": self.max_axes_per_lineage,
                "selection": self.selection, "data_semantics": self.data_semantics,
                "roles": dict(self.roles)}


def _read_yaml(path: Path) -> dict[str, Any]:
    import yaml

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"degradation-diversity config not found: {path}",
                          stage="degrade.diversity.config") from exc
    if not isinstance(data, dict):
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"degradation-diversity config {path} is not a mapping "
                          f"({type(data).__name__})", stage="degrade.diversity.config")
    return data


def load_diversity_config(path: str | Path | None = None) -> DiversityConfig:
    """Load and **validate** the diversity config against the live 31-axis registry.

    Every declared axis is resolved through :func:`synlab.degrade.registry.get_operator`, so an
    unknown axis id, a family/stage that disagrees with the registry, an unknown variant or a
    level outside the operator's ``LEVEL_COUNT`` is a hard error instead of a silently skipped
    axis (which would shrink the denominator without saying so).
    """
    target = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    data = _read_yaml(target)
    schema = str(data.get("schema", ""))
    if schema != "synlab.degrade_diversity.v1":
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"{target}: schema {schema!r} is not 'synlab.degrade_diversity.v1'",
                          stage="degrade.diversity.config")
    enabled = bool(data.get("enabled", True))
    default_levels = tuple(int(v) for v in (data.get("levels") or (0, 1, 2, 3, 4)))
    per_lineage = dict(data.get("per_lineage") or {})
    max_axes = int(per_lineage.get("max_axes", 0) or 0)
    selection = str(per_lineage.get("selection", "declared"))
    if selection not in SELECTIONS:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"{target}: per_lineage.selection {selection!r} not in {SELECTIONS}",
                          stage="degrade.diversity.config")
    declared_axes = list(data.get("axes") or [])
    if not declared_axes:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"{target}: no axes declared; a diversity config without axes would "
                          f"materialise nothing", stage="degrade.diversity.config")
    if max_axes <= 0:
        max_axes = len(declared_axes)
    axes: list[AxisSpec] = []
    seen: set[str] = set()
    for index, item in enumerate(declared_axes):
        if not isinstance(item, Mapping):
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              f"{target}: axes[{index}] is not a mapping", stage="degrade.diversity.config")
        axis_id = str(item.get("axis_id", "")).strip()
        if axis_id not in AXIS_IDS:
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              f"{target}: axes[{index}] axis_id {axis_id!r} is not one of the "
                              f"31 declared axes", stage="degrade.diversity.config")
        if axis_id in seen:
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              f"{target}: axis {axis_id} is declared twice; a duplicated axis "
                              f"would double its level denominator",
                              stage="degrade.diversity.config")
        seen.add(axis_id)
        operator = get_operator(axis_id)
        family = str(item.get("family", axis_id[0]))
        if family != axis_id[0]:
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              f"{target}: axis {axis_id} declares family {family!r} but its id "
                              f"belongs to family {axis_id[0]!r}", stage="degrade.diversity.config")
        stage = str(item.get("stage", operator.STAGE))
        if stage != operator.STAGE:
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              f"{target}: axis {axis_id} declares stage {stage!r} but the "
                              f"registry says {operator.STAGE!r}",
                              stage="degrade.diversity.config")
        variant = operator.resolve_variant(str(item.get("variant", "")) or None)
        levels = tuple(int(v) for v in (item.get("levels") or default_levels))
        outside = [lvl for lvl in levels if lvl not in operator.levels()]
        if outside:
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              f"{target}: axis {axis_id} declares levels {outside} outside "
                              f"0..{operator.LEVEL_COUNT - 1}", stage="degrade.diversity.config")
        if 0 not in levels:
            raise SynLabError(ErrorCode.SCHEMA_INVALID,
                              f"{target}: axis {axis_id} does not declare level 0; the identity "
                              f"level is the anchor every other level is paired against",
                              stage="degrade.diversity.config")
        axes.append(AxisSpec(axis_id=axis_id, family=family, variant=variant, levels=levels,
                             stage=operator.STAGE, substage=operator.SUBSTAGE,
                             factor_kind=operator.factor_kind_for(variant),
                             note=str(item.get("note", ""))))
    roles = {str(k): str(v) for k, v in dict(data.get("roles") or {}).items()}
    return DiversityConfig(path=target, enabled=enabled, levels=default_levels, axes=tuple(axes),
                           max_axes_per_lineage=max_axes, selection=selection,
                           data_semantics=str(data.get("data_semantics", DATA_SEMANTICS_TAG)),
                           roles=roles, raw=data)


# ======================================================================================
# helpers
# ======================================================================================
def _jsonable(value: Any) -> Any:
    import numpy as np

    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        return value.tolist() if value.size <= 64 else f"<array {list(value.shape)}>"
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return f"<{type(value).__name__}>"


def asset_bytes(store: Any, record: Any) -> int:
    """Bytes on disk of one committed asset (sum of the files the store registered)."""
    total = 0
    root = Path(store.root)
    for relative in dict(getattr(record, "files", None) or {}).values():
        try:
            total += int((root / str(relative)).stat().st_size)
        except OSError:  # pragma: no cover - a file that vanished is not counted
            continue
    return total


def directory_bytes(root: str | Path) -> int:
    """Total size of a directory tree (store growth measurement, per lineage)."""
    total = 0
    for path in Path(root).rglob("*"):
        try:
            if path.is_file():
                total += int(path.stat().st_size)
        except OSError:  # pragma: no cover
            continue
    return total


def _write_json(path: str | Path, payload: Any) -> None:
    """Atomic-enough incremental flush: write a ``.part`` then replace."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".part")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                   encoding="utf-8")
    tmp.replace(target)


def _error_code(exc: SynLabError) -> str:
    return exc.code.value if isinstance(exc.code, ErrorCode) else str(exc.code)


def _status_of(code: str, *, level_status_na: Sequence[str]) -> str:
    return "NA" if code in level_status_na else "FAILED"


#: SynLabError codes that mean "this axis/level does not apply here" (kept in the denominator).
NA_CODES = (ErrorCode.NA_NOT_APPLICABLE.value,
            ErrorCode.DEPENDENCY_CAPABILITY_MISSING.value)


# ======================================================================================
# sources
# ======================================================================================
def load_p_family_source(store: Any, fragment_asset_id: str, *, fragment_id: str = "",
                         material_id: str = "", mother_id: str = "", master_seed: int = 0,
                         lineage_id: str = "") -> SourceBundle:
    """Read the lineage's target-fragment mesh back as the P-family degradation source."""
    bundle = load_source(store, fragment_asset_id)
    meta = dict(bundle.meta or {})
    meta.update({"fragment_id": fragment_id or str(meta.get("fragment_id", "")),
                 "material_id": material_id, "mother_id": mother_id,
                 "master_seed": int(master_seed), "lineage_id": lineage_id,
                 "provenance": f"LINEAGE_FRAGMENT_ASSET:{fragment_asset_id}",
                 "degrade_source_role": ROLE_DEGRADE_SOURCE,
                 "degrade_source_origin": "REUSED_LINEAGE_ASSET"})
    bundle.meta = meta
    bundle.lineage_id = lineage_id or bundle.lineage_id
    return bundle


def commit_observation_sources(store: Any, observation: Any, *, lineage_id: str, split: str,
                               material_id: str = "", mother_id: str = "",
                               master_seed: int = 0,
                               data_semantics: Mapping[str, Any] | None = None,
                               observation_asset_id: str = "") -> dict[str, SourceBundle]:
    """Commit the lineage observation's I/G/X bundles and read them back as sources.

    The *reloaded* bundle is returned, so ``source_hash`` is the hash of exactly the bytes the
    level-0 identity references.  ``round_trip_hash_ok`` records whether the reload reproduced
    the in-memory hash (a dtype-changing round trip would show up here instead of silently
    changing what "the same source" means).

    No run id is written into the asset metadata: a degradation source is a pure function of the
    observation, and keeping it content-addressed means a re-run of the same lineage **dedupes**
    instead of duplicating the whole degradation set.  The run linkage lives in the per-lineage
    report and in the coverage row.
    """
    built = bundles_from_observation(observation)
    out: dict[str, SourceBundle] = {}
    for key in ("I", "G", "X"):
        bundle = built.get(key)
        if bundle is None:  # pragma: no cover - bundles_from_observation always returns all three
            continue
        bundle.meta = {**dict(bundle.meta or {}), "material_id": material_id, "mother_id": mother_id,
                       "master_seed": int(master_seed), "lineage_id": lineage_id,
                       "provenance": (f"LINEAGE_OBSERVATION:"
                                      f"{getattr(observation, 'observation_id', '')}"),
                       "degrade_source_role": ROLE_DEGRADE_SOURCE,
                       "data_semantics": dict(data_semantics or {})}
        in_memory_hash = bundle.content_hash()
        record = commit_source(store, bundle.without(*IN_MEMORY_KEYS), role=ROLE_DEGRADE_SOURCE,
                               schema=FAMILY_SCHEMA[key],
                               lineage_id=lineage_id, split=split,
                               qa={"role": ROLE_DEGRADE_SOURCE, "family": key,
                                   "content_hash": in_memory_hash,
                                   "data_semantics": dict(data_semantics or {})},
                               meta={"family": key, "source_kind": bundle.source_kind,
                                     "content_hash": in_memory_hash,
                                     "round_trip_hash_ok": None,
                                     "data_semantics": dict(data_semantics or {}),
                                     "degrade_diversity": DATA_SEMANTICS_TAG},
                               ancestry=([observation_asset_id] if observation_asset_id else []))
        reloaded = load_source(store, record.asset_id)
        reloaded.meta = {**dict(reloaded.meta or {}), **dict(bundle.meta or {}),
                         "provenance": bundle.meta.get("provenance", ""),
                         "degrade_source_origin": "COMMITTED_DEGRADE_SOURCE",
                         "source_asset_id": record.asset_id,
                         "round_trip_hash_ok": bool(reloaded.content_hash() == in_memory_hash)}
        reloaded.lineage_id = lineage_id
        out[key] = reloaded
    return out


# ======================================================================================
# materialisation
# ======================================================================================
def materialize_lineage_diversity(
    store: Any,
    *,
    config: DiversityConfig,
    sources: Mapping[str, SourceBundle],
    lineage_id: str,
    split: str,
    master_seed: int,
    lineage_index: int = 0,
    run_id: str | None = None,
    data_semantics: Mapping[str, Any] | None = None,
    progress_path: str | Path | None = None,
    mother_id: str = "",
    fragment_id: str = "",
) -> dict[str, Any]:
    """Materialise the configured axis × level variants of one lineage against ``store``.

    Never raises for a single axis/level: an inapplicable axis is recorded as ``NA`` with the
    operator's reason and a level whose declared effect was not measured is recorded as
    ``FAILED`` with its failure code, both inside the planned denominator.  The report is
    flushed to ``progress_path`` after **every level**.
    """
    started = time.perf_counter()
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "config": config.as_dict(),
        "config_hash": (hash_file(config.path) if config.path and Path(config.path).exists()
                        else None),
        "lineage_id": lineage_id, "split": split, "run_id": run_id,
        "master_seed": int(master_seed), "lineage_index": int(lineage_index),
        "mother_id": mother_id, "fragment_id": fragment_id,
        "roles": {"source": ROLE_DEGRADE_SOURCE, "variant": ROLE_DEGRADE_VARIANT},
        "data_semantics": dict(data_semantics or {}),
        "data_semantics_tag": config.data_semantics,
        "sources": {key: {"asset_id": bundle.asset_id, "source_kind": bundle.source_kind,
                          "content_hash": bundle.content_hash(),
                          "role": bundle.role, "unit": bundle.unit, "frame": bundle.frame,
                          "payload_keys": sorted(bundle.payload),
                          "provenance": (bundle.meta or {}).get("provenance"),
                          "origin": (bundle.meta or {}).get("degrade_source_origin"),
                          "round_trip_hash_ok": (bundle.meta or {}).get("round_trip_hash_ok"),
                          "bytes": (asset_bytes(store, store.get_asset(bundle.asset_id))
                                    if bundle.asset_id else 0)}
                     for key, bundle in sorted(sources.items())},
        "axes": [], "asset_ids": [], "variant_asset_ids": [],
        "seconds": 0.0, "status": "RUNNING",
    }
    flush = (lambda: _write_json(progress_path, report)) if progress_path else (lambda: None)

    for spec in config.axes_for_lineage(lineage_index):
        axis_entry = _materialize_axis(
            store, spec=spec, sources=sources, lineage_id=lineage_id, split=split,
            master_seed=master_seed, data_semantics=data_semantics,
            config=config, mother_id=mother_id, fragment_id=fragment_id, flush=flush)
        report["axes"].append(axis_entry)
        for level in axis_entry["levels"]:
            if level.get("asset_id") and level.get("asset_committed"):
                report["variant_asset_ids"].append(level["asset_id"])
            if level.get("asset_id"):
                report["asset_ids"].append(level["asset_id"])
        report["summary"] = summarize_report(report)
        flush()

    report["axes_planned"] = len(config.axes_for_lineage(lineage_index))
    report["summary"] = summarize_report(report)
    report["seconds"] = time.perf_counter() - started
    report["status"] = ("OK" if report["summary"]["levels_failed"] == 0
                        and report["summary"]["axes_failed"] == 0 else "PARTIAL")
    flush()
    return report


def _materialize_axis(store: Any, *, spec: AxisSpec, sources: Mapping[str, SourceBundle],
                      lineage_id: str, split: str, master_seed: int,
                      data_semantics: Mapping[str, Any] | None, config: DiversityConfig,
                      mother_id: str, fragment_id: str, flush: Any) -> dict[str, Any]:
    operator = get_operator(spec.axis_id)
    started = time.perf_counter()
    entry: dict[str, Any] = {
        **spec.as_dict(), "source_key": spec.source_key, "levels": [],
        "basis_id": None, "basis_seed_ref": None, "seconds": 0.0, "status": "RUNNING",
    }
    source = sources.get(spec.source_key)
    if source is None:
        reason = (f"no {spec.source_key}-family source bundle for lineage {lineage_id}; the axis "
                  f"cannot be applied and stays in the denominator as NA")
        entry.update({"status": "NA", "na_reason": reason,
                      "levels": [{"level": lvl, "status": "NA", "variant": spec.variant,
                                  "na_reason": reason, "planned": None, "measured": {},
                                  "identity": False, "realized": False, "asset_id": None,
                                  "asset_committed": False} for lvl in spec.levels],
                      "seconds": time.perf_counter() - started})
        return entry

    context = {
        "axis_id": spec.axis_id,
        "lineage_id": lineage_id,
        "fragment_id": fragment_id or str((source.meta or {}).get("fragment_id", "fragment")),
        "mother_id": mother_id or str((source.meta or {}).get("mother_id", "")),
        "master_seed": int(master_seed),
        "variant": spec.variant,
        "source": source,
        "source_kind": source.source_kind,
    }
    rng = make_rng(int(master_seed), lineage_id, "degrade", spec.axis_id, spec.variant)
    basis = operator.sample_basis(context, rng, spec.variant)
    entry.update({"basis_id": basis.basis_id, "basis_seed_ref": basis.seed_ref,
                  "basis_payload_keys": sorted(basis.payload or {}),
                  "source_asset_id": source.asset_id})

    level_entries: list[dict[str, Any]] = []
    for level in spec.levels:
        level_entry = _materialize_level(
            store, spec=spec, level=int(level), operator=operator, source=source, basis=basis,
            lineage_id=lineage_id, split=split, data_semantics=data_semantics,
            config=config, mother_id=mother_id, fragment_id=context["fragment_id"])
        level_entries.append(level_entry)
        entry["levels"] = level_entries
        entry["seconds"] = time.perf_counter() - started
        flush()

    statuses = [str(item["status"]) for item in level_entries]
    if "FAILED" in statuses:
        entry["status"] = "FAILED"
    elif all(item == "NA" for item in statuses):
        entry["status"] = "NA"
    else:
        entry["status"] = "OK"
    entry["levels_planned"] = len(level_entries)
    entry["levels_ok"] = sum(1 for s in statuses if s in ("OK", "IDENTITY"))
    entry["levels_na"] = statuses.count("NA")
    entry["levels_failed"] = statuses.count("FAILED")
    entry["variants_committed"] = sum(1 for item in level_entries if item["asset_committed"])
    entry["bytes"] = int(sum(int(item.get("bytes", 0) or 0) for item in level_entries))
    entry["seconds"] = time.perf_counter() - started
    return entry


def _materialize_level(store: Any, *, spec: AxisSpec, level: int, operator: Any,
                       source: SourceBundle, basis: Any, lineage_id: str, split: str,
                       data_semantics: Mapping[str, Any] | None,
                       config: DiversityConfig, mother_id: str,
                       fragment_id: str) -> dict[str, Any]:
    started = time.perf_counter()
    entry: dict[str, Any] = {
        "level": int(level), "variant": spec.variant, "axis_id": spec.axis_id,
        "family": spec.family, "status": "RUNNING", "identity": False, "realized": False,
        "planned": _jsonable(operator.params_for(level, spec.variant)),
        "measured": {}, "units": {}, "basis_id": basis.basis_id,
        "source_hash": source.content_hash(), "result_hash": None, "asset_id": None,
        "role": None, "asset_committed": False, "bytes": 0, "seconds": 0.0,
        "na_reason": None, "failure_code": None,
    }
    try:
        ref, measurement = _apply_axis(store, spec, level, source, basis, lineage_id, split)
        entry.update({
            "identity": bool(measurement.identity),
            "realized": bool(measurement.realized),
            "measured": _jsonable(measurement.measured), "units": _jsonable(measurement.units),
            "source_hash": measurement.source_hash, "result_hash": measurement.result_hash,
            "planned": _jsonable(measurement.planned),
            "factor_kind": measurement.factor_kind,
            "label_status": measurement.extra.get("label_status"),
            "label_invalidations": list(operator.LABEL_INVALIDATIONS),
            "calibration_status": measurement.calibration_status,
        })
        asset_id = getattr(ref, "asset_id", None)
        if measurement.identity:
            # ---------------------------------------------------------- level 0 (identity)
            entry.update({"status": "IDENTITY", "asset_id": asset_id,
                          "role": getattr(ref, "role", None) or source.role,
                          "identity_reference_ok": bool(asset_id is not None
                                                        and asset_id == source.asset_id),
                          "bytes_unchanged": bool(measurement.result_hash
                                                  == measurement.source_hash),
                          "identity_contract": ("level 0 returns the source asset reference; "
                                                "no asset is committed and no byte is rewritten")})
            if not (entry["identity_reference_ok"] and entry["bytes_unchanged"]):
                entry.update({"status": "FAILED", "failure_code": "IDENTITY_BROKEN"})
        else:
            # ---------------------------------------------------------- level > 0 (committed)
            record = _commit_variant(store, ref=ref, spec=spec, level=level, operator=operator,
                                     measurement=measurement, source=source, basis=basis,
                                     lineage_id=lineage_id, split=split,
                                     data_semantics=data_semantics, config=config,
                                     fragment_id=fragment_id)
            entry.update({"status": "OK" if measurement.realized else "FAILED",
                          "asset_id": record.asset_id, "role": record.role,
                          "asset_committed": True, "bytes": asset_bytes(store, record),
                          "schema": record.schema, "qa_status": record.qa_status,
                          "source_asset_id": source.asset_id})
            if not measurement.realized:
                entry["failure_code"] = str(measurement.failure_code
                                            or ErrorCode.OPERATOR_NOT_REALIZED.value)
    except SynLabError as exc:
        code = _error_code(exc)
        entry.update({"status": _status_of(code, level_status_na=NA_CODES),
                      "failure_code": code, "error": exc.message[:400],
                      "na_reason": (exc.message[:400] if code in NA_CODES else None)})
        if code in NA_CODES:
            entry["measured"] = _jsonable(exc.measurements)
    except Exception as exc:  # noqa: BLE001 - one level must not kill the lineage
        entry.update({"status": "FAILED", "failure_code": "UNEXPECTED",
                      "error": f"{type(exc).__name__}: {exc}"[:400]})
    entry["seconds"] = time.perf_counter() - started
    return entry


def _apply_axis(store: Any, spec: AxisSpec, level: int, source: SourceBundle, basis: Any,
                lineage_id: str, split: str) -> tuple[Any, Any]:
    """``apply_axis`` with ``commit=False``: this module owns the commit and its role."""
    from .api import apply_axis

    return apply_axis(spec.axis_id, int(level), source, store, variant=spec.variant, basis=basis,
                      lineage_id=lineage_id, split=split, commit=False)


def _commit_variant(store: Any, *, ref: Any, spec: AxisSpec, level: int, operator: Any,
                    measurement: Any, source: SourceBundle, basis: Any, lineage_id: str,
                    split: str, data_semantics: Mapping[str, Any] | None,
                    config: DiversityConfig, fragment_id: str) -> Any:
    """Commit one degraded bundle under :data:`ROLE_DEGRADE_VARIANT` with the full factor record.

    ``run_id`` is deliberately **not** part of the committed metadata: a variant is a pure
    function of ``(source asset, axis, variant, level, basis)``, and keeping the metadata free of
    run bookkeeping lets a re-run of the same lineage dedupe through the content-addressed store
    instead of duplicating every variant.  The run linkage is recorded in the per-lineage report
    (``<store>/reports/degrade_diversity/<lineage>.json``) and in the coverage row.
    """
    if isinstance(ref, OutputRef):
        bundle = ref.as_bundle()
    else:  # pragma: no cover - commit=False returns an OutputRef for level > 0
        payload = dict(getattr(ref, "payload", {}) or {})
        bundle = SourceBundle(source_kind=getattr(ref, "source_kind", source.source_kind),
                              payload=payload, unit=getattr(ref, "unit", source.unit),
                              frame=getattr(ref, "frame", source.frame))
    bundle = bundle.without(*IN_MEMORY_KEYS)
    bundle.meta = {**dict(bundle.meta or {}), "axis_id": spec.axis_id, "level": int(level),
                   "variant": spec.variant, "fragment_id": fragment_id,
                   "lineage_id": lineage_id}
    meta = {
        "axis_id": spec.axis_id, "family": spec.family, "stage": spec.stage,
        "substage": spec.substage, "variant": spec.variant, "level": int(level),
        "factor_kind": measurement.factor_kind, "basis_id": basis.basis_id,
        "basis_seed_ref": basis.seed_ref, "planned": _jsonable(measurement.planned),
        "measured": _jsonable(measurement.measured), "units": _jsonable(measurement.units),
        "realized": bool(measurement.realized), "identity": False,
        "source_hash": measurement.source_hash, "result_hash": measurement.result_hash,
        "source_asset_id": source.asset_id, "source_kind": source.source_kind,
        "status": "REALIZED" if measurement.realized else "NOT_REALIZED",
        "label_invalidations": list(operator.LABEL_INVALIDATIONS),
        "label_status": measurement.extra.get("label_status"),
        "calibration_status": measurement.calibration_status,
        "role_contract": ("degrade_variant carries axis_id/level/variant (factor answer side) and "
                          "must never be committed as feature_bundle "
                          "(roles.FORBIDDEN_FEATURE_FIELDS)"),
        "export_fields": list(VARIANT_FIELDS),
        "data_semantics": dict(data_semantics or {}),
        "degrade_diversity": config.data_semantics,
    }
    qa = {"axis_id": spec.axis_id, "variant": spec.variant, "level": int(level),
          "identity": False, "realized": bool(measurement.realized),
          "basis_id": basis.basis_id, "source_hash": measurement.source_hash,
          "result_hash": measurement.result_hash,
          "data_semantics": dict(data_semantics or {}),
          "degrade_diversity": config.data_semantics}
    return commit_source(store, bundle, role=ROLE_DEGRADE_VARIANT, schema=FAMILY_SCHEMA[spec.family],
                         lineage_id=lineage_id, split=split, qa=qa, meta=meta,
                         ancestry=([source.asset_id] if source.asset_id else []))


# ======================================================================================
# summary
# ======================================================================================
def summarize_report(report: Mapping[str, Any]) -> dict[str, Any]:
    """Denominator-honest summary of one lineage's diversity report (planned vs real)."""
    axes = list(report.get("axes") or [])
    levels = [level for axis in axes for level in (axis.get("levels") or [])]
    statuses = [str(level.get("status")) for level in levels]
    basis_ids: dict[str, set[str]] = {}
    for axis in axes:
        basis_ids.setdefault(str(axis.get("axis_id")), set()).add(str(axis.get("basis_id")))
    return {
        "axes_planned": len(axes),
        "axes_ok": sum(1 for a in axes if a.get("status") == "OK"),
        "axes_na": sum(1 for a in axes if a.get("status") == "NA"),
        "axes_failed": sum(1 for a in axes if a.get("status") == "FAILED"),
        "levels_planned": len(levels),
        "levels_ok": sum(1 for s in statuses if s in ("OK", "IDENTITY")),
        "levels_identity": statuses.count("IDENTITY"),
        "levels_na": statuses.count("NA"),
        "levels_failed": statuses.count("FAILED"),
        "variant_assets": sum(1 for level in levels if level.get("asset_committed")),
        "identity_reference_ok": sum(1 for level in levels
                                     if level.get("identity_reference_ok") is True),
        "identity_bytes_unchanged": sum(1 for level in levels
                                        if level.get("bytes_unchanged") is True),
        "basis_ids": {axis: sorted(ids) for axis, ids in sorted(basis_ids.items())},
        "basis_shared_per_axis": all(len(ids) == 1 for ids in basis_ids.values()),
        "bytes": int(sum(int(level.get("bytes", 0) or 0) for level in levels)),
        "axes": {str(axis.get("axis_id")): axis.get("status") for axis in axes},
        "levels_by_axis": {str(axis.get("axis_id")): len(axis.get("levels") or []) for axis in axes},
    }


__all__ = [
    "ROLE_DEGRADE_SOURCE", "ROLE_DEGRADE_VARIANT", "FAMILY_SCHEMA", "FAMILY_UNIT",
    "DATA_SEMANTICS_TAG", "DEFAULT_CONFIG_PATH", "REPORT_SCHEMA", "VARIANT_FIELDS", "NA_CODES",
    "AxisSpec", "DiversityConfig", "load_diversity_config", "load_p_family_source",
    "commit_observation_sources", "materialize_lineage_diversity", "summarize_report",
    "asset_bytes", "directory_bytes",
]
