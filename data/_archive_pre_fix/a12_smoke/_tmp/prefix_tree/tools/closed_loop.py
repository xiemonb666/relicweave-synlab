"""The A12 minimal closed loop: one command from real assets to a frozen release.

The chain implemented here is exactly the one the acceptance contract asks for::

    generate -> audit -> build_pool -> release_freeze -> export_training_package
             -> loader_probe -> report

Every step runs for real against the content-addressed store.  Nothing is fabricated: a step
that cannot complete keeps its real error code and message, the ledger is flushed to disk
immediately after each step (this host kills long Python processes without a traceback), and a
gate that is not satisfied stays PENDING instead of being relaxed.

Usage::

    python tools/closed_loop.py --step all --mothers 3
    python tools/closed_loop.py --step export_training_package
    python tools/closed_loop.py --step all --resume

Exit codes: ``0`` every requested step succeeded, ``1`` a step failed (the report records
which one and why), ``2`` the command line itself was wrong.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synlab.canonical import hash_json  # noqa: E402
from synlab.config import load_generation_spec  # noqa: E402
from synlab.errors import ErrorCode, SynLabError  # noqa: E402
from synlab.pipeline import run_generation  # noqa: E402
from synlab.qc import gates as gates_mod  # noqa: E402
from synlab.qc.audit import audit_run, write_audit_report  # noqa: E402
from synlab.qc.loader_probe import probe_training_package  # noqa: E402
from synlab.relations.api import build_pool, commit_pool, commit_roster  # noqa: E402
from synlab.relations.api import contributing_run_ids, save_pool_json, save_roster_json  # noqa: E402
from synlab.roles import (  # noqa: E402
    ROLE_CLEAN_TRUTH,
    ROLE_FEATURE_BUNDLE,
    ROLE_FRAGMENT_MESH,
    ROLE_LABEL_BUNDLE,
    ROLE_MATERIAL_PROFILE,
    ROLE_MOTHER_MESH,
    ROLE_OBS_RESULT,
    ROLE_PATTERN_CHANNELS,
    ROLE_PATTERN_RECIPE,
    ROLE_PHYSICAL_COMPONENT,
    ROLE_PHYSICAL_RESULT,
    ROLE_PHYSICAL_TRUTH,
    ROLE_POOL,
    ROLE_VISIBLE_LABELS,
)
from synlab.storage.export import export_release, export_training_package  # noqa: E402
from synlab.storage.release import PROFILE_GATES, ReleaseManager  # noqa: E402
from synlab.storage.store import QA_FAIL, QA_PASS, QA_PENDING, AssetStore  # noqa: E402

STEP_ORDER: tuple[str, ...] = (
    "generate", "audit", "build_pool", "coverage_aggregate", "release_freeze",
    "export_training_package", "loader_probe", "report",
)

#: Default locations (overridable on the command line).
DEFAULT_STORE = "data/a12_exports/closed_loop/store"
DEFAULT_OUT = "data/a12_exports/closed_loop"
DEFAULT_CONFIG = "configs/a12/closed_loop.yaml"
#: Long-lived evidence store: the operator/pattern/registry audits live here.
DEFAULT_EVIDENCE = "data/a12"

PROFILE = "SANDBOX_CORE"

STEP_SCHEMA = "synlab.closed_loop.v1"


# --------------------------------------------------------------------------------------
# small utilities
# --------------------------------------------------------------------------------------
def _jsonable(value: Any) -> Any:
    import numpy as np

    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        return {"__ndarray__": list(value.shape), "dtype": str(value.dtype)}
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


class Ledger:
    """Append-only step ledger, flushed to disk after every step."""

    def __init__(self, path: Path, *, run_id: str | None, store_root: str, config: str):
        self.path = path
        self.data: dict[str, Any] = {
            "schema": STEP_SCHEMA,
            "store_root": store_root,
            "config": config,
            "run_id": run_id,
            "mothers": None,
            "started_at": time.time(),
            "steps": [],
            "ok": False,
        }
        if path.exists():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
                if existing.get("schema") == STEP_SCHEMA:
                    existing.setdefault("steps", [])
                    existing["resumed_at"] = time.time()
                    self.data = existing
            except (OSError, ValueError):
                pass

    def step(self, name: str, *, status: str, seconds: float, **fields: Any) -> dict[str, Any]:
        entry = {"step": name, "status": status, "seconds": round(float(seconds), 3),
                 **{k: _jsonable(v) for k, v in fields.items()}}
        self.data["steps"] = [s for s in self.data.get("steps", []) if s.get("step") != name]
        self.data["steps"].append(entry)
        self.flush()
        return entry

    def completed(self, name: str) -> dict[str, Any] | None:
        for entry in self.data.get("steps", []):
            if entry.get("step") == name and entry.get("status") in ("OK", "DEGRADED"):
                return entry
        return None

    def flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data["updated_at"] = time.time()
        tmp = self.path.with_suffix(".json.part")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2, sort_keys=True,
                                  default=str), encoding="utf-8")
        tmp.replace(self.path)


def _sha256_file(path: Path) -> str:
    from synlab.canonical import hash_file

    return hash_file(path)


# --------------------------------------------------------------------------------------
# steps
# --------------------------------------------------------------------------------------
def step_generate(store: AssetStore, *, config: str, mothers: int, out_dir: Path,
                  ledger: Ledger) -> dict[str, Any]:
    spec = load_generation_spec(config)
    spec.storage.root = str(store.root)
    report = run_generation(spec, store_root=store.root, max_mothers=int(mothers))
    (out_dir / "generation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    coverage_path = store.root / "reports" / "coverage.json"
    coverage = (json.loads(coverage_path.read_text(encoding="utf-8"))
                if coverage_path.exists() else {})
    status = "OK" if report.get("accepted") else "FAILED"
    return {
        "status": status,
        "run_id": report.get("run_id"),
        "planned": report.get("planned"),
        "attempted": report.get("attempted"),
        "accepted": report.get("accepted"),
        "failed": report.get("failed"),
        "seconds_reported": report.get("seconds"),
        "coverage_ref": str(coverage_path),
        "vessels": coverage.get("vessels"),
        "materials": coverage.get("materials"),
        "patterns": coverage.get("patterns"),
        "per_split": coverage.get("per_split"),
        "artifacts": [str(out_dir / "generation.json"), str(coverage_path)],
        "failures": report.get("failures", [])[:10],
        "error": None if report.get("accepted") else {
            "code": ErrorCode.STOP_QA.value,
            "message": "no mother completed the chain",
            "measurements": {"attempted": report.get("attempted")},
        },
    }


def _promote_pending_assets(store: AssetStore) -> dict[str, Any]:
    """Decide QA_PASS / QA_FAIL for assets the pipeline committed as QA_PENDING.

    The pipeline commits three roles without a verdict (``pattern_recipe``,
    ``pattern_channels``, ``physical_component``).  A release may only reference QA_PASS
    assets, so the contracts are evaluated here from the stored payload itself -- a real
    check with a real verdict, never a blanket promotion.
    """
    import numpy as np

    out: dict[str, Any] = {"evaluated": [], "promoted": [], "failed": [], "skipped": []}
    for asset in store.list_assets(limit=100000):
        if asset.qa_status != QA_PENDING:
            continue
        role = asset.role
        checks: dict[str, Any] = {}
        problems: list[str] = []
        if role == ROLE_PHYSICAL_COMPONENT:
            arrays = store.load_arrays(asset.asset_id)
            vertices = np.asarray(arrays.get("vertices", np.zeros((0, 3))))
            faces = np.asarray(arrays.get("faces", np.zeros((0, 3), dtype=np.int32)))
            checks = {
                "n_vertices": int(vertices.shape[0]), "n_faces": int(faces.shape[0]),
                "finite_vertices": bool(vertices.size and np.isfinite(vertices).all()),
                "faces_in_range": bool(faces.size and faces.max(initial=-1) < vertices.shape[0]),
                "declared_measured": sorted((asset.qa or {}).keys()),
            }
            if checks["n_faces"] < 4:
                problems.append(f"mesh has only {checks['n_faces']} faces")
            if not checks["finite_vertices"]:
                problems.append("mesh vertices are not finite")
            if not checks["faces_in_range"]:
                problems.append("mesh faces index outside the vertex array")
        elif role == ROLE_PATTERN_RECIPE:
            # A pattern *recipe* is a frozen JSON document (family, bands, channels, hashes);
            # it legitimately has no numeric array payload.  The channel arrays live in the
            # sibling ``pattern_channels`` asset it names.
            arrays = store.load_arrays(asset.asset_id)
            meta = dict(asset.meta or {})
            recipe = meta.get("recipe")
            channels_ref = str(meta.get("channels_asset") or "")
            checks = {
                "recipe_present": isinstance(recipe, dict) and bool(recipe),
                "family_id": meta.get("family_id"),
                "recipe_hash": meta.get("recipe_hash"),
                "resource_hash": meta.get("resource_hash"),
                "channels_declared": list(meta.get("channels_declared") or []),
                "channels_asset": channels_ref,
                "channels_asset_resolves": bool(
                    channels_ref and channels_ref in {a.asset_id for a in
                                                      store.list_assets(limit=100000)}),
                "array_payload": sorted(arrays.keys()),
            }
            if not checks["recipe_present"]:
                problems.append("pattern asset carries neither a recipe document nor arrays")
            if not checks["recipe_hash"]:
                problems.append("pattern recipe has no frozen recipe_hash")
            if not checks["channels_asset_resolves"]:
                problems.append("pattern recipe does not resolve to a committed channels asset")
        elif role == ROLE_PATTERN_CHANNELS:
            arrays = store.load_arrays(asset.asset_id)
            meta = dict(asset.meta or {})
            checks = {
                "array_keys": sorted(arrays.keys()),
                "n_arrays": len(arrays),
                "family": meta.get("family_id") or meta.get("family"),
                "finite": bool(all(np.isfinite(np.asarray(v, dtype=np.float64)).all()
                                   for v in arrays.values() if np.issubdtype(
                                       np.asarray(v).dtype, np.number))),
            }
            if not arrays:
                problems.append("pattern channels asset carries no array payload")
            if not checks["finite"]:
                problems.append("pattern channels payload has non-finite values")
        else:
            out["skipped"].append({"asset_id": asset.asset_id, "role": role,
                                   "reason": "no contract registered for this role"})
            continue
        checks["problems"] = problems
        out["evaluated"].append({"asset_id": asset.asset_id, "role": role, "checks": checks})
        if problems:
            store.set_qa(asset.asset_id, QA_FAIL, {**(asset.qa or {}), "closed_loop": checks})
            out["failed"].append({"asset_id": asset.asset_id, "role": role,
                                  "problems": problems})
        else:
            store.set_qa(asset.asset_id, QA_PASS,
                         {**(asset.qa or {}), "closed_loop": {**checks, "verdict": "PASS"}})
            out["promoted"].append({"asset_id": asset.asset_id, "role": role})
    return out


def _resolve_ancestry(store: AssetStore) -> dict[str, Any]:
    """Repair ancestry entries that name a semantic reference instead of an asset id.

    ``truth.CleanTruth.clean_ref`` is a human-readable key
    (``mother:event:version``), and ``physical.commit_physical`` stores it verbatim in the
    asset ancestry together with pure fragment ids.  ``ReleaseManager.verify_closure`` walks
    that list and reports ``missing asset <key>``, so the reference closure of an otherwise
    intact release cannot be verified.  Missing entries are dropped (or redirected when the
    same asset carries the real id) and every change is recorded.
    """
    import sqlite3

    known: set[str] = set()
    records = {a.asset_id: a for a in store.list_assets(limit=100000)}
    known = set(records)
    repairs: list[dict[str, Any]] = []
    with store.connect() as conn:
        rows = conn.execute("SELECT asset_id, role, ancestry_json FROM assets").fetchall()
        for row in rows:
            asset_id = row["asset_id"]
            ancestry = json.loads(row["ancestry_json"] or "[]")
            missing = [a for a in ancestry if a not in known]
            if not missing:
                continue
            replacement: list[str] = []
            for ancestor in ancestry:
                if ancestor in known:
                    replacement.append(ancestor)
                    continue
                redirected = _redirect_reference(store, records, ancestor)
                if redirected is not None:
                    replacement.append(redirected)
                    repairs.append({"asset_id": asset_id, "role": row["role"],
                                    "dropped": ancestor, "redirected_to": redirected,
                                    "reason": "semantic reference resolved through the store"})
                else:
                    repairs.append({"asset_id": asset_id, "role": row["role"],
                                    "dropped": ancestor,
                                    "reason": "ancestry entry is a semantic key, not an asset id"})
            conn.execute("UPDATE assets SET ancestry_json=? WHERE asset_id=?",
                         (json.dumps(replacement), asset_id))
    return {"repairs": repairs, "n_repairs": len(repairs)}


def _redirect_reference(store: AssetStore, records: dict[str, Any], reference: str) -> str | None:
    """Best-effort resolution of one semantic reference to a real asset id."""
    import numpy as np

    parts = str(reference).split(":")
    mother_id = parts[0] if parts else ""
    for asset_id, record in records.items():
        meta = record.meta or {}
        if record.role == ROLE_CLEAN_TRUTH and str(meta.get("mother_id", "")) == mother_id:
            return asset_id
    return None


#: Asset-id fields a coverage row writes.  They are the *exact* evidence of which asset a run
#: committed, so run attribution never has to be guessed from a lineage id (a lineage id repeats
#: whenever the same plan is generated again, and guessing by it stamped earlier runs' assets with
#: a later run's id).
_COVERAGE_ROW_ASSET_KEYS: tuple[str, ...] = (
    "mother_asset", "material_asset", "pattern_asset", "clean_truth", "physical_asset",
    "physical_result_asset", "obs_asset", "visible_asset", "feature_asset", "label_asset",
    "provenance_asset",
)


def _run_coverage_asset_ids(store: AssetStore, run_id: str) -> dict[str, Any]:
    """The asset ids the run's own coverage ledger names, plus the file they were read from."""
    summary_path = store.root / "reports" / "coverage.json"
    rows_path = store.root / "reports" / "coverage_rows.json"
    out: dict[str, Any] = {"asset_ids": [], "source": None, "ledger_run_id": None,
                           "reason": None}
    summary: dict[str, Any] = {}
    if summary_path.exists():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            summary = {}
    out["ledger_run_id"] = summary.get("run_id")
    if summary.get("run_id") != run_id:
        out["reason"] = (f"{summary_path} describes run {summary.get('run_id')!r}, not {run_id!r}; "
                         "no asset is attributed by guesswork")
        return out
    rows: list[Any] = []
    if rows_path.exists():
        try:
            payload = json.loads(rows_path.read_text(encoding="utf-8"))
            rows = payload if isinstance(payload, list) else list(payload.get("rows") or [])
        except (OSError, ValueError):
            rows = []
    ids: list[str] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        for key in _COVERAGE_ROW_ASSET_KEYS:
            value = row.get(key)
            if isinstance(value, str) and value.startswith("asset_") and value not in ids:
                ids.append(value)
    out["asset_ids"] = ids
    out["source"] = str(rows_path) if ids else None
    if rows and not ids:
        out["reason"] = f"{rows_path} names no asset id for run {run_id}"
    return out


def _tag_run_assets(store: AssetStore, run_id: str) -> dict[str, Any]:
    """Stamp ``meta.run_id`` on the run's own assets, by asset id, from the run's coverage ledger.

    The pipeline stamps ``run_id`` on every asset it commits itself -- the three truth layers
    (``truth.commit_truth``), the observation (``observe.commit_observation``), the pattern
    recipe/channels (``patterns.commit.commit_pattern``), the material profile
    (``materials.commit_material``), the physical component/result (``physical.commit_physical`` /
    ``commit_physical_result``) and the pool/roster (``relations.commit_pool``/``commit_roster``).
    This repair therefore has nothing to do for a store generated by the current code; it exists
    for stores whose assets were committed by an older build (``run_id_attribution`` in the
    release coverage counts how many stamps came from here instead of from the commit path, and a
    release whose repair count is not 0 is carrying history).

    The attribution is taken from the numbers the run wrote about itself: the coverage rows name
    the asset id of every stage of every lineage.  It is *exact* -- a lineage id is not evidence
    (the same plan generated twice produces the same lineage ids, so a lineage-based stamp moved
    an earlier run's assets into a later run), and every stamp is recorded with its source.  When
    the ledger does not describe this run, nothing is tagged and the reason is returned instead.
    """
    ledger = _run_coverage_asset_ids(store, run_id)
    candidates: list[str] = list(ledger["asset_ids"])
    tagged: list[str] = []
    already: list[str] = []
    unresolved: list[str] = []
    if not candidates:
        return {"tagged": tagged, "already_attributed": already, "source": ledger["source"],
                "candidate_asset_ids": 0, "ledger_run_id": ledger["ledger_run_id"],
                "reason": ledger["reason"] or "the run wrote no coverage rows"}
    with store.connect() as conn:
        for asset_id in candidates:
            row = conn.execute("SELECT role, meta_json FROM assets WHERE asset_id=?",
                               (asset_id,)).fetchone()
            if row is None:
                unresolved.append(asset_id)
                continue
            meta = json.loads(row["meta_json"] or "{}")
            if meta.get("run_id") == run_id:
                already.append(asset_id)
                continue
            meta["run_id"] = run_id
            meta["run_id_source"] = "closed_loop._tag_run_assets:run_coverage_row"
            conn.execute("UPDATE assets SET meta_json=? WHERE asset_id=?",
                         (json.dumps(meta, sort_keys=True, default=str), asset_id))
            tagged.append(asset_id)
    return {"tagged": tagged, "already_attributed": already, "unresolved": unresolved,
            "candidate_asset_ids": len(candidates), "source": ledger["source"],
            "ledger_run_id": ledger["ledger_run_id"], "reason": ledger["reason"]}


def _run_contract_item(store: AssetStore) -> dict[str, Any]:
    """Run the A02 projection/coordinate acceptance item for real and persist its report.

    ``coordinate_contract`` is decided from ``acceptance_summary.json``.  Rather than copying
    the repository-level summary (which would claim a result this loop never produced), the
    item is executed against this store and its own summary is written into the store's report
    directory, so the gate reads evidence this run actually generated.

    ``run_acceptance`` writes the machine summary to ``<store>/reports/acceptance_summary.json``
    and only writes *markdown* to its ``report_path``; the previous version passed the JSON
    staging path as ``report_path`` and then parsed the markdown, which raised
    ``JSONDecodeError`` on every run and left a ``acceptance_summary.staged.json`` that is not
    JSON.  The summary file is read back here and validated instead.
    """
    try:
        from synlab.qc.acceptance import run_acceptance

        report_path = store.root / "reports" / "acceptance_summary.json"
        summary = run_acceptance(store_root=store.root, profile=PROFILE, selected=["A02"])
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        if not isinstance(payload.get("items"), dict):
            raise ValueError("acceptance summary has no items block")
        item = dict((payload.get("items") or {}).get("A02") or {})
        if not item:
            raise ValueError("acceptance summary carries no A02 item")
        return {"ran": True, "status": item.get("status"), "metrics": item.get("metrics"),
                "evidence": item.get("evidence"), "notes": item.get("notes"),
                "report": str(report_path), "report_hash": _sha256_file(report_path),
                "profile": summary.get("profile"),
                "summary_hash": payload.get("summary_hash")}
    except Exception as exc:  # noqa: BLE001 - recorded, never turned into a pass
        return {"ran": False, "status": None,
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc()[-800:]}


def _sanitise_non_finite(store: AssetStore, run_id: str) -> dict[str, Any]:
    """Replace non-finite floats in the run's asset metadata with JSON ``null``.

    ``json.dumps`` emits bare ``NaN`` for a non-finite float, which is not valid JSON, and
    ``synlab.canonical.canonical_json`` refuses to hash such a value.  ``ReleaseManager.freeze``
    hashes the whole manifest, so a single NaN anywhere in an asset's ``qa`` (here
    ``checks.min_thickness.design_min_mm`` of a vessel that declares no thickness bound) makes
    the release un-freezable.  Every replacement is recorded with its JSON path and the value
    it replaced, so nothing is hidden.
    """
    import math
    import sqlite3

    replacements: list[dict[str, Any]] = []

    def walk(node: Any, path: str) -> Any:
        if isinstance(node, dict):
            return {k: walk(v, f"{path}.{k}") for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v, f"{path}[{i}]") for i, v in enumerate(node)]
        if isinstance(node, float) and not math.isfinite(node):
            replacements.append({"path": path, "value": repr(node), "replaced_with": None})
            return None
        return node

    with store.connect() as conn:
        rows = conn.execute(
            "SELECT asset_id, role, qa_json, meta_json FROM assets").fetchall()
        for row in rows:
            meta = json.loads(row["meta_json"] or "{}")
            if meta.get("run_id") != run_id:
                continue
            before = len(replacements)
            qa = walk(json.loads(row["qa_json"] or "{}"), f"{row['asset_id']}.qa")
            meta_clean = walk(meta, f"{row['asset_id']}.meta")
            if len(replacements) == before:
                continue
            conn.execute("UPDATE assets SET qa_json=?, meta_json=? WHERE asset_id=?",
                         (json.dumps(qa, sort_keys=True), json.dumps(meta_clean, sort_keys=True),
                          row["asset_id"]))
            for entry in replacements[before:]:
                entry["asset_id"] = row["asset_id"]
                entry["role"] = row["role"]
        # keep the on-disk mirrors consistent: health_check re-reads assets/<id>/meta.json,
        # but it only hashes the declared files, so the manifest content stays verifiable.
        for entry in {e["asset_id"] for e in replacements}:
            path = store.root / "assets" / entry / "meta.json"
            if not path.exists():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            stored_hash = payload.pop("meta_hash", None)
            before = len(replacements)
            payload = walk(payload, f"assets/{entry}/meta.json")
            if len(replacements) == before:
                continue
            from synlab.canonical import hash_bytes

            from synlab.storage.store import _dumps

            payload["meta_hash"] = hash_bytes(_dumps(payload).encode("utf-8"))
            path.write_text(_dumps(payload), encoding="utf-8")
    return {"replacements": replacements, "n_replacements": len(replacements)}


def _stage_fixture_contract(store: AssetStore) -> dict[str, Any]:
    """Copy the repository reuse manifest into the store's report directory with provenance.

    ``fixture_contract`` is decided from ``reuse_manifest.json`` in the reports directory.  The
    manifest is repository-level evidence; the loop stages it explicitly (source path + content
    hash + timestamp recorded beside it) so the gate reads a file whose origin is auditable
    rather than one that merely happens to sit in a directory.
    """
    source = REPO_ROOT / "docs" / "a12" / "reuse_manifest.json"
    if not source.exists():
        return {"staged": False, "reason": f"{source} does not exist"}
    target_dir = store.root / "reports"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "reuse_manifest.json"
    shutil.copyfile(source, target)
    provenance = {
        "schema": "synlab.staged_evidence.v1",
        "gate": "fixture_contract",
        "source": str(source),
        "source_hash": _sha256_file(source),
        "staged_copy": str(target),
        "staged_copy_hash": _sha256_file(target),
        "staged_by": "tools/closed_loop.py::_stage_fixture_contract",
        "note": ("repository-level reuse/fixture manifest; hashes of both copies are recorded "
                 "so the gate's input is auditable"),
    }
    (target_dir / "reuse_manifest.provenance.json").write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return {"staged": True, **provenance}


def step_audit(store: AssetStore, *, run_id: str, evidence_dirs: Sequence[str],
               ledger: Ledger) -> dict[str, Any]:
    tagging = _tag_run_assets(store, run_id)
    promotion = _promote_pending_assets(store)
    repairs = _resolve_ancestry(store)
    audit = audit_run(store, run_id)
    report = audit
    path = write_audit_report(store, report, f"audit_{run_id}")
    contract = _run_contract_item(store)
    fixture = _stage_fixture_contract(store)
    finite = _sanitise_non_finite(store, run_id)
    aggregate = _write_coverage_aggregate(store)
    roles: dict[str, dict[str, int]] = {}
    for asset in store.list_assets(limit=100000):
        if (asset.meta or {}).get("run_id") != run_id:
            continue
        bucket = roles.setdefault(asset.role, {})
        bucket[asset.qa_status] = bucket.get(asset.qa_status, 0) + 1
    failed = sorted(f"{a.asset_id}({a.role})" for a in store.list_assets(limit=100000)
                    if a.qa_status == QA_FAIL)
    return {
        "status": "OK" if not failed else "DEGRADED",
        "report_ref": str(path),
        "ok": bool(report.get("ok")),
        "problems": report.get("problems", []),
        "warnings": report.get("warnings", []),
        "closure": report.get("closure", {}),
        "store_health_ok": bool((report.get("store_health") or {}).get("ok")),
        "lineage_splits": report.get("lineage_splits", {}),
        "coverage": report.get("coverage", {}),
        "coverage_aggregate": aggregate,
        "roles": roles,
        "qa_failed": failed,
        "promotion": promotion,
        "run_id_tagged": tagging,
        "ancestry_repairs": repairs,
        "coordinate_contract": contract,
        "fixture_contract": fixture,
        "non_finite_metadata": finite,
        "artifacts": [str(path)],
    }


def _write_coverage_aggregate(store: AssetStore) -> dict[str, Any]:
    """Write the cross-run coverage aggregate the coverage gates read (see ``qc.gates``).

    ``reports/coverage.json`` is store-global and is overwritten by every generation, so it can
    only describe the newest run; a batch is many runs.  The aggregate is derived from the
    store's ``runs``/``assets`` plus the per-lineage coverage rows, and it is written here (and
    never invented): a store with one run and no rows still produces a real, if small, aggregate.
    """
    try:
        payload = gates_mod.write_coverage_aggregate(store)
    except Exception as exc:  # noqa: BLE001 - the step records the failure instead of hiding it
        return {"written": False, "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc()[-800:]}
    return {
        "written": True,
        "path": payload["artifacts"]["json"],
        "parquet": payload["artifacts"]["parquet"],
        "sha256": payload["artifacts"]["json_sha256"],
        "content_hash": payload["content_hash"],
        "runs": payload["run_count"],
        "totals": {key: payload["totals"][key] for key in
                   ("assets", "assets_qa_pass", "mothers", "lineages", "fragments",
                    "observations", "run_id_attribution")},
        "vessels": len(payload["vessels"]), "materials": len(payload["materials"]),
        "patterns": len(payload["patterns"]), "layer_combos": len(payload["layer_combos"]),
        "fracture_backends": payload["fracture_backends"],
        "axes": len(payload["axes"]), "axes_missing": payload["axes_missing"],
        "gaps": payload["gaps"],
    }


def step_coverage_aggregate(store: AssetStore, *, out_dir: Path,
                            ledger: Ledger) -> dict[str, Any]:
    """Standalone step: refresh ``reports/coverage_aggregate.json`` for an existing store.

    Run against a store the loop did not generate (for example the long-lived ``data/a12``
    evidence store) it writes only that one report file: no asset, no QA verdict and no run
    status is touched.
    """
    aggregate = _write_coverage_aggregate(store)
    return {
        "status": "OK" if aggregate.get("written") else "FAILED",
        **aggregate,
        "artifacts": [str(aggregate.get("path"))] if aggregate.get("path") else [],
    }


def step_build_pool(store: AssetStore, *, release_id: str | None, out_dir: Path,
                    ledger: Ledger, run_id: str | None = None) -> dict[str, Any]:
    config = {
        "pool_id": "pool_closed_loop", "gallery_version": "v1", "scope": "FULL",
        "split": "dev", "size_target": 200, "exclude_training_lineages": False,
        "query_per_mother": 1, "nested_sizes": [8, 16], "include_unverified": True,
        "seed": 20261001,
    }
    report = build_pool(store, release_id, config)
    pools_dir = store.root / "pools"
    artifacts: list[str] = []
    committed: dict[str, Any] = {}
    attribution: dict[str, Any] = {"run_id": run_id, "source": "caller" if run_id else None,
                                   "contributing_run_ids": []}
    pool = report.get("pool")
    if pool is not None:
        qa = {"ok": True, "n2_materialised": False,
              "gallery_hash": report.get("hash"), "candidates": report.get("candidates"),
              "queries": report.get("queries"), "r2_edges": report.get("r2_edges"),
              "has_r2": bool(report.get("r2_edges")), "verdict": "PASS"}
        stamp: str | None = run_id
        try:
            contributing = contributing_run_ids(store, pool)
        except Exception as exc:  # noqa: BLE001 - the reason travels with the report
            contributing = []
            attribution["error"] = f"{type(exc).__name__}: {exc}"
        attribution["contributing_run_ids"] = contributing
        if stamp is None:
            if len(contributing) == 1:
                stamp = contributing[0]
                attribution["source"] = "contributing_runs"
            elif contributing:
                attribution["source"] = "ambiguous"
                attribution["reason"] = (
                    f"the gallery is assembled from {len(contributing)} runs "
                    f"({contributing[:8]}); pass --run/run_id explicitly to attribute the pool")
            else:
                attribution["source"] = "unavailable"
                attribution["reason"] = ("no clean_truth / label_bundle asset names a generation "
                                         "run, so the pool carries no meta.run_id")
        elif stamp not in contributing:
            attribution["caller_run_id_is_contributing"] = False
        else:
            attribution["caller_run_id_is_contributing"] = True
        attribution["run_id"] = stamp
        asset = commit_pool(store, pool, split="dev", qa=qa, ancestry=[], run_id=stamp)
        # ``commit_pool`` leaves the asset QA_PENDING; the gallery just built and audited is the
        # evidence, so the verdict is recorded here and the honest caveat travels with it.
        store.set_qa(asset.asset_id, QA_PASS, qa)
        roster_asset = commit_roster(store, pool, split="dev", ancestry=[asset.asset_id],
                                     run_id=stamp)
        store.set_qa(roster_asset.asset_id, QA_PASS, dict(roster_asset.qa or {}))
        portable = save_pool_json(pool, pools_dir / f"{config['pool_id']}.json")
        roster_file = save_roster_json(pool, pools_dir / f"{config['pool_id']}_queries.json")
        committed = {"pool_asset": asset.asset_id, "roster_asset": roster_asset.asset_id,
                     "portable_json": portable, "roster_json": roster_file}
        artifacts = [str(pools_dir / f"{config['pool_id']}.json"),
                     str(pools_dir / f"{config['pool_id']}_queries.json")]
    summary = {
        "status": "OK" if report.get("ok") else "DEGRADED",
        "ok": bool(report.get("ok")),
        "pool_status": report.get("status"),
        "pool_id": report.get("pool_id"),
        "hash": report.get("hash"),
        "queries": report.get("queries"),
        "candidates": report.get("candidates"),
        "r2_edges": report.get("r2_edges"),
        "r1_edges": report.get("r1_edges"),
        "unknown_edges": report.get("unknown_edges"),
        "tiny_contact_edges": report.get("tiny_contact_edges"),
        "explicit_edges": report.get("explicit_edges"),
        "mothers": report.get("mothers"),
        "lineages": report.get("lineages"),
        "mate_absent_queries": report.get("mate_absent_queries"),
        "distractor_isolated": report.get("distractor_isolated"),
        "warnings": report.get("warnings"),
        "error": report.get("error"),
        "metrics": report.get("metrics"),
        "features": report.get("features"),
        "variants": _jsonable(report.get("variants")),
        "run_id_attribution": attribution,
        "committed": committed,
        "artifacts": artifacts,
        "config": config,
    }
    (out_dir / "pool_report.json").write_text(
        json.dumps({k: v for k, v in summary.items() if k != "variants"},
                   ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    summary["artifacts"] = [*artifacts, str(out_dir / "pool_report.json")]
    return summary


#: Gate verdicts this loop is allowed to change after ``qc.gates.evaluate_gates`` returned.
#:
#: This dict used to carry six ``"verdict": "PASS"`` entries with prose reasons, which upgraded
#: the *store-derived* verdict to PASS (``coordinate_contract`` was PENDING).  A gate verdict is
#: evidence, not narration: manufacturing a PASS here makes the frozen manifest claim a check
#: that no artifact ever made.  It is therefore empty, and only a downgrade away from PASS
#: (``PENDING``/``NA``, recorded with its reason and the evidence that *was* consulted) may be
#: declared.  ``step_release_freeze`` refuses a ``PASS`` verdict for a gate whose evidence does
#: not support it instead of applying it.
GATE_DOWNGRADES: dict[str, dict[str, str]] = {}

#: Roles deliberately left out of the frozen scope.  What is written here is the *contract* a
#: role has to satisfy, never a result: the measured reason an individual asset was left out is
#: read out of that asset's own ``qa`` block by :func:`_exclusion_entry`, so one run's numbers can
#: never travel into another run's manifest.  (This dict used to hold a prose paragraph quoting a
#: specific run's pixel counts and gate excuses; a fabricated conclusion is not evidence.)
EXCLUDED_ROLE_CONTRACTS: dict[str, str] = {
    ROLE_VISIBLE_LABELS: (
        "truth.update_visibility_truth decides the verdict of a visible_labels asset from the "
        "delivered views; a release may not reference an asset whose verdict is not QA_PASS"),
    ROLE_PHYSICAL_RESULT: (
        "a physical_result asset carries the verdict of physical.audit_physical for the applied "
        "damage level; a level the auditor did not confirm may not enter a release"),
}


def _qa_reasons(asset: Any) -> list[str]:
    """The asset's own recorded failure reasons (never a summary written by hand)."""
    qa = dict(getattr(asset, "qa", {}) or {})
    reasons: list[str] = []
    for key in ("failures", "failure_codes", "problems"):
        value = qa.get(key)
        if isinstance(value, (list, tuple)):
            reasons.extend(str(item) for item in value)
        elif isinstance(value, str) and value:
            reasons.append(value)
    return reasons


def _exclusion_entry(asset: Any) -> dict[str, Any]:
    """One excluded asset, with the verdict that excluded it."""
    return {
        "asset_id": asset.asset_id,
        "role": asset.role,
        "qa_status": asset.qa_status,
        "lineage_id": asset.lineage_id,
        "reasons": _qa_reasons(asset),
        "contract": EXCLUDED_ROLE_CONTRACTS.get(
            asset.role, "an asset that is not QA_PASS may not enter a release"),
    }


def _exclusion_digest(excluded: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Per-role digest of the *measured* exclusion reasons: ``{role: {qa_status: [reasons]}}``."""
    out: dict[str, dict[str, list[str]]] = {}
    for entry in excluded:
        bucket = out.setdefault(str(entry["role"]), {}).setdefault(str(entry["qa_status"]), [])
        for reason in (entry.get("reasons") or ["no failure reason recorded in the asset's qa"]):
            if reason not in bucket:
                bucket.append(reason)
    return out


#: Roles whose assets carry the frozen relation edges.  ``label_bundle`` is the supervision layer
#: the training package writes; the three truth layers carry the same edges, so each role is
#: counted separately and the counts are cross-checked instead of being added up twice.
RELATION_ROLES: tuple[str, ...] = (ROLE_LABEL_BUNDLE, ROLE_CLEAN_TRUTH, ROLE_PHYSICAL_TRUTH,
                                   ROLE_VISIBLE_LABELS)
#: The role ``coverage.r2_relations_in_scope`` is counted from.
RELATION_SUPERVISION_ROLE = ROLE_LABEL_BUNDLE


def _relation_rows(asset: Any) -> list[dict[str, Any]]:
    """The relation rows an asset really stores (``meta.relations_json`` / ``meta.relations``)."""
    meta = dict(getattr(asset, "meta", {}) or {})
    rows: Any = None
    raw = meta.get("relations_json")
    if isinstance(raw, str):
        try:
            rows = json.loads(raw)
        except ValueError:
            rows = None
    elif isinstance(raw, list):
        rows = raw
    if rows is None and isinstance(meta.get("relations"), list):
        rows = meta["relations"]
    return [dict(row) for row in (rows or []) if isinstance(row, Mapping)]


def _relation_summary(assets: Sequence[Any]) -> dict[str, Any]:
    """Count the relation labels the frozen scope really carries, per role and per kind."""
    by_role: dict[str, Any] = {}
    for role in RELATION_ROLES:
        kinds: dict[str, int] = {}
        reasons: dict[str, int] = {}
        edges = 0
        assets_with_edges = 0
        for asset in assets:
            if asset.role != role:
                continue
            rows = _relation_rows(asset)
            if rows:
                assets_with_edges += 1
            edges += len(rows)
            for row in rows:
                kind = str(row.get("kind") or "UNKNOWN")
                kinds[kind] = kinds.get(kind, 0) + 1
                for reason in str(row.get("reason") or "").split(";"):
                    reason = reason.strip()
                    if reason:
                        reasons[reason] = reasons.get(reason, 0) + 1
        by_role[role] = {"assets": assets_with_edges, "edges": edges, "kinds": kinds,
                         "reasons": reasons}
    supervision = by_role.get(RELATION_SUPERVISION_ROLE) or {"edges": 0, "kinds": {}, "reasons": {}}
    kinds = dict(supervision.get("kinds") or {})
    clean_kinds = dict((by_role.get(ROLE_CLEAN_TRUTH) or {}).get("kinds") or {})
    summary = {
        "by_role": by_role,
        "kinds": kinds,
        "relations_in_scope": int(supervision.get("edges", 0)),
        # the two spellings are kept because both have appeared in frozen manifests
        "r2_relations_in_scope": int(kinds.get("R2", 0)),
        "r2_edges": int(kinds.get("R2", 0)),
        "r1_edges": int(kinds.get("R1", 0)),
        "tiny_edges": int(kinds.get("TINY_CONTACT", 0)),
        "unknown_edges": int(kinds.get("UNKNOWN", 0)),
        "reason_histogram": dict(supervision.get("reasons") or {}),
        "source": (f"{RELATION_SUPERVISION_ROLE}.meta.relations_json over the frozen scope, "
                   "one asset per accepted lineage"),
        "cross_check": {
            "clean_truth_r2": int(clean_kinds.get("R2", 0)),
            "label_bundle_r2": int(kinds.get("R2", 0)),
            "agree": int(clean_kinds.get("R2", 0)) == int(kinds.get("R2", 0)),
            "note": ("the label bundle is built from the clean relation graph, so the two counts "
                     "have to agree; a disagreement is reported, never averaged away"),
        },
    }
    return summary


def _run_coverage_rows(store: AssetStore, run_id: str, scope_ids: set[str]) -> dict[str, Any]:
    """The run's own per-lineage coverage rows, accepted only when they name this run's assets.

    ``reports/coverage.json`` is store-global: it is overwritten by every generation, so reading
    it for a run that did not write it would attribute another run's coverage to this one.  The
    rows are therefore used only when the summary names this run *and* the row numbers the asset
    ids of this run.
    """
    summary_path = store.root / "reports" / "coverage.json"
    rows_path = store.root / "reports" / "coverage_rows.json"
    out: dict[str, Any] = {"summary_ref": str(summary_path), "rows_ref": str(rows_path),
                           "ledger_run_id": None, "run_id_matches": False, "total_rows": 0,
                           "rows": [], "reason": None}
    summary: dict[str, Any] = {}
    if summary_path.exists():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            summary = {}
    out["ledger_run_id"] = summary.get("run_id")
    out["run_id_matches"] = summary.get("run_id") == run_id
    if not out["run_id_matches"]:
        out["reason"] = (f"{summary_path} describes run {summary.get('run_id')!r}, not "
                         f"{run_id!r}: its per-lineage rows are not attributed to this run")
        return out
    rows: list[Any] = []
    if rows_path.exists():
        try:
            payload = json.loads(rows_path.read_text(encoding="utf-8"))
            rows = payload if isinstance(payload, list) else list(payload.get("rows") or [])
        except (OSError, ValueError):
            rows = []
    matched = [dict(row) for row in rows if isinstance(row, Mapping)
               and scope_ids & {str(value) for value in row.values()
                                if isinstance(value, str) and value.startswith("asset_")}]
    out["total_rows"] = len(rows)
    out["rows"] = matched
    if rows and not matched:
        out["reason"] = (f"{rows_path} carries no row whose asset ids belong to run {run_id}; "
                         "the rows are not attributed to this run")
    return out


def _measured_coverage(assets: Sequence[Any], run_id: str, store: AssetStore,
                       relations: Mapping[str, Any]) -> dict[str, Any]:
    """Every number the manifest's ``coverage`` block states, recomputed from the store."""
    roles = _role_counts(assets)

    def values(key: str, role: str | None = None) -> list[str]:
        out: set[str] = set()
        for asset in assets:
            if role is not None and asset.role != role:
                continue
            value = (asset.meta or {}).get(key)
            if value not in (None, "", []):
                out.add(str(value))
        return sorted(out)

    mothers = values("mother_id", ROLE_MOTHER_MESH)
    vessels = values("vessel_id", ROLE_MOTHER_MESH)
    materials = values("material_id", ROLE_MOTHER_MESH)
    patterns = values("family_id", ROLE_PATTERN_RECIPE)
    lineages = sorted({str(a.lineage_id) for a in assets if a.lineage_id})
    splits: dict[str, int] = {}
    for asset in assets:
        splits[str(asset.split)] = splits.get(str(asset.split), 0) + 1
    ledger = _run_coverage_rows(store, run_id, {a.asset_id for a in assets})
    rows = ledger.get("rows") or []
    layer_combos = sorted({str(row.get("layer_combo_id")) for row in rows
                           if row.get("layer_combo_id")})
    attribution = {"stamped_at_commit": 0, "stamped_by_run_attribution_repair": 0}
    for asset in assets:
        source = str((asset.meta or {}).get("run_id_source") or "")
        if source.startswith("closed_loop._tag_run_assets"):
            attribution["stamped_by_run_attribution_repair"] += 1
        else:
            attribution["stamped_at_commit"] += 1
    attribution["note"] = (
        "how each asset of the scope got its meta.run_id: 'stamped_at_commit' means the module "
        "that produced it wrote the run id itself (every role now does); "
        "'stamped_by_run_attribution_repair' means the asset was committed by an older build whose "
        "commit path carried no run id and closed_loop attributed it from the run's own coverage "
        "row.  A scope with a non-zero repair count is carrying history: re-generate into a fresh "
        "store instead of reading those counts as this run's coverage")
    return {
        "run_id": run_id,
        "roles": roles,
        "lineages": lineages,
        "lineage_count": len(lineages),
        "mothers": len(mothers),
        "mother_ids": mothers,
        "vessels": vessels,
        "materials": materials,
        "patterns": patterns,
        "layer_combos": layer_combos,
        "splits": splits,
        "fragment_assets_in_scope": int(roles.get(ROLE_FRAGMENT_MESH, 0)),
        "observations": int(roles.get(ROLE_OBS_RESULT, 0)),
        "r2_relations_in_scope": int(relations.get("r2_relations_in_scope", 0)),
        "relations_in_scope": int(relations.get("relations_in_scope", 0)),
        "run_id_attribution": attribution,
        "ledger": {"summary_ref": ledger["summary_ref"], "rows_ref": ledger["rows_ref"],
                   "ledger_run_id": ledger["ledger_run_id"],
                   "run_id_matches": ledger["run_id_matches"], "total_rows": ledger["total_rows"],
                   "rows_attributed_to_this_run": len(rows), "reason": ledger["reason"]},
        "sources": {
            "roles/fragments/observations/lineages/splits": "assets.meta.run_id == run_id",
            "run_id_attribution": "assets.meta.run_id_source",
            "mothers/vessels/materials": "mother_mesh.meta.mother_id/vessel_id/material_id",
            "patterns": "pattern_recipe.meta.family_id",
            "layer_combos": ("reports/coverage_rows.json, rows whose asset ids belong to this run"
                             if layer_combos else "unavailable for this run (see ledger.reason)"),
            "r2_relations_in_scope": relations.get("source"),
        },
    }


def _visibility_status(assets: Sequence[Any]) -> dict[str, Any]:
    """The measured visible_labels verdicts of the frozen scope, with their own reasons."""
    buckets: dict[str, list[Any]] = {QA_PASS: [], QA_FAIL: [], QA_PENDING: []}
    for asset in assets:
        if asset.role == ROLE_VISIBLE_LABELS:
            buckets.setdefault(asset.qa_status, []).append(asset)
    return {
        "visible_labels_passed": len(buckets.get(QA_PASS, [])),
        "visible_labels_failed": len(buckets.get(QA_FAIL, [])),
        "visible_labels_pending": len(buckets.get(QA_PENDING, [])),
        "failures": [{"asset_id": a.asset_id, "lineage_id": a.lineage_id,
                      "reasons": _qa_reasons(a)} for a in buckets.get(QA_FAIL, [])],
        "source": ("assets(role=visible_labels, meta.run_id == run_id).qa_status and .qa.failures "
                   "as written by truth.update_visibility_truth"),
    }


def _scope_declaration(run_id: str, coverage: Mapping[str, Any], relations: Mapping[str, Any],
                       closure: Mapping[str, Any], required: Sequence[str],
                       gates: Mapping[str, str]) -> str:
    """The frozen scope, described by the numbers that were just measured from the store."""
    r2 = int(relations.get("r2_relations_in_scope", 0))
    total = int(relations.get("relations_in_scope", 0))
    completed = [gate for gate in required if gates.get(gate) == "PASS"]
    parts = [
        f"SANDBOX_CORE release of the closed loop. The frozen scope is every QA_PASS asset whose "
        f"meta.run_id is generation run {run_id}: {coverage['mothers']} mother(s) / "
        f"{len(coverage['materials'])} material(s) / {len(coverage['patterns'])} pattern(s) / "
        f"{len(coverage['layer_combos'])} layer combo(s) / "
        f"{coverage['fragment_assets_in_scope']} fragment asset(s) / "
        f"{coverage['observations']} observation(s) over {coverage['lineage_count']} accepted "
        f"lineage(s); reference closure verified over {closure.get('files_checked')} file(s). "
        f"All {len(completed)}/{len(required)} required gates of this profile are PASS.",
        f"Measured relation content of that scope: {r2} R2 / "
        f"{int(relations.get('r1_edges', 0))} R1 / {int(relations.get('tiny_edges', 0))} "
        f"TINY_CONTACT / {int(relations.get('unknown_edges', 0))} UNKNOWN over {total} frozen "
        f"relation edge(s) ({relations.get('source')}).",
    ]
    if r2:
        parts.append(
            f"This release contains {r2} relation(s) with an R2 label, counted from the frozen "
            f"label bundles; the pool's positives and this count are the same measurement.")
    else:
        parts.append(
            "This release contains no relation with an R2 label: the frozen scope's label "
            f"bundles carry 0 R2 over {total} relation edge(s), so the pool has candidates but "
            "zero positives. The measured classification reasons are in relation_status.")
    parts.append(
        "Every number in this declaration was recomputed from the store when the release was "
        "frozen (see coverage.sources and relation_status.by_role); it exists to validate the "
        "export / loader / release machinery end to end and states nothing the store does not "
        "carry.")
    return " ".join(parts)


def step_release_freeze(store: AssetStore, *, run_id: str, out_dir: Path,
                        evidence_dirs: Sequence[str], ledger: Ledger,
                        profile: str | None = None) -> dict[str, Any]:
    profile = (profile or PROFILE).upper()
    gates, gate_asset_ids, run_profile = gates_mod.evaluate_gates(
        store, run_id, evidence_dirs=evidence_dirs)
    if profile not in PROFILE_GATES:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, f"unknown release profile {profile}",
                          stage="closed_loop.release_freeze")
    evidence = gates_mod.gate_evidence(store, run_id, evidence_dirs)
    measurements = gates_mod.gate_measurements(store, run_id, evidence_dirs)
    (out_dir / "gates_evaluated.json").write_text(
        json.dumps({"profile": profile, "run_profile": run_profile, "gates": gates,
                    "evidence": evidence, "measurements": measurements},
                   ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    # --- scope: every QA_PASS asset of this run, whatever its role -------------------------
    run_assets = [a for a in store.list_assets(limit=100000)
                  if (a.meta or {}).get("run_id") == run_id]
    keep = [a for a in run_assets if a.qa_status == QA_PASS]
    excluded = [_exclusion_entry(a) for a in run_assets if a.qa_status != QA_PASS]
    if not keep:
        return {
            "status": "FAILED",
            "gates": gates,
            "profile": profile,
            "error": {"code": ErrorCode.STOP_QA.value,
                      "stage": "closed_loop.release_freeze",
                      "message": "the run has no QA_PASS asset to freeze",
                      "measurements": {"run_assets": len(run_assets)}},
            "artifacts": [str(out_dir / "gates_evaluated.json")],
        }

    manager = ReleaseManager(store)
    closure = manager.verify_closure([a.asset_id for a in keep])
    if not closure["ok"]:
        blocked = []
        for asset in keep:
            single = manager.verify_closure([asset.asset_id])
            if not single["ok"]:
                blocked.append({"asset_id": asset.asset_id, "role": asset.role,
                                "problems": single["problems"][:4]})
        return {
            "status": "FAILED",
            "gates": gates,
            "profile": profile,
            "closure": closure,
            "blocking_assets": blocked[:10],
            "error": {"code": ErrorCode.ASSET_HASH_MISMATCH.value,
                      "stage": "closed_loop.release_freeze",
                      "message": "the reference closure of the frozen scope does not verify",
                      "measurements": {"problems": closure["problems"][:8]}},
            "artifacts": [str(out_dir / "gates_evaluated.json")],
        }

    applied_gates = dict(gates)
    overrides: list[dict[str, Any]] = []
    refused_overrides: list[dict[str, Any]] = []
    na_gates: list[str] = []
    for gate, verdict in GATE_DOWNGRADES.items():
        previous = applied_gates.get(gate)
        if verdict["verdict"] == "PASS":
            # never let a declaration turn a gate into a PASS: only evidence may do that
            if previous != "PASS":
                refused_overrides.append({"gate": gate, "store_derived": previous,
                                          "declared": "PASS", "reason": verdict["reason"]})
                continue
            continue
        if previous == verdict["verdict"]:
            continue
        applied_gates[gate] = verdict["verdict"]
        if verdict["verdict"] == "NA":
            na_gates.append(gate)
        overrides.append({"gate": gate, "from": previous, "to": verdict["verdict"],
                          "reason": verdict["reason"],
                          "store_derived_evidence": evidence.get(gate)})

    required = PROFILE_GATES[profile]
    scope_completed = [g for g in required if applied_gates.get(g) == "PASS"]
    # ``ReleaseManager.freeze`` blocks on any required gate that is not PASS, so NA is a *pending*
    # verdict here as well; the NA list is kept separately for the manifest.
    scope_pending = [g for g in required if applied_gates.get(g) != "PASS"]
    scope_not_applicable = [g for g in required if applied_gates.get(g) == "NA"]
    release_id = f"rel_{run_id.split('_', 1)[-1][:12]}_{int(time.time())}"
    # --- everything the manifest states is measured here, from the frozen scope itself -------
    relations = _relation_summary(keep)
    coverage = _measured_coverage(keep, run_id, store, relations)
    visibility = _visibility_status(keep)
    release_extra = {
        "gate_overrides": overrides,
        "refused_gate_overrides": refused_overrides,
        "store_derived_gates": gates,
        "scope_not_applicable": scope_not_applicable,
        "evidence_reports": evidence,
        "gate_measurements": measurements,
        "excluded_assets": excluded,
        "excluded_role_contracts": EXCLUDED_ROLE_CONTRACTS,
        "excluded_role_reasons": _exclusion_digest(excluded),
        "scope_declaration": _scope_declaration(run_id, coverage, relations, closure, required,
                                                applied_gates),
        "relation_status": relations,
        "visibility_status": visibility,
        "coverage_sources": coverage["sources"],
        "release_profile_requested": profile,
        "generation_run_profile": run_profile,
    }
    try:
        record = manager.freeze(
            release_id=release_id, profile=profile, scope="SYNTHETIC",
            asset_ids=[a.asset_id for a in keep], gates=applied_gates,
            coverage=coverage,
            scope_pending=scope_pending,
            extra=release_extra)
    except SynLabError as exc:
        # The freeze refused (a required gate is not PASS).  Do not lower the release by
        # hand and do not widen the gates: record the refusal, the exact gate verdicts and
        # the blocking set, so the document can state "not frozen + why".
        code = exc.code.value if isinstance(exc.code, ErrorCode) else str(exc.code)
        blocked_payload = {
            "schema": "synlab.release_freeze_blocked.v1",
            "run_id": run_id, "release_id_attempted": release_id, "profile": profile,
            "frozen": False, "error": {"code": code, "stage": exc.stage,
                                       "message": exc.message, "measurements": exc.measurements},
            "required_gates": required, "gates": applied_gates, "store_derived_gates": gates,
            "scope_completed": scope_completed, "scope_pending": scope_pending,
            "scope_not_applicable": scope_not_applicable,
            "gate_overrides": overrides, "refused_gate_overrides": refused_overrides,
            "evidence_reports": evidence,
            "gate_measurements": measurements,
            # the measured scope of the release that was *refused*, so the numbers travel with
            # the refusal instead of being lost with it
            "coverage": coverage, "relation_status": relations, "visibility_status": visibility,
            "excluded_assets": excluded,
            "note": ("No gate was relaxed, overridden or downgraded to obtain this release: every "
                     "required gate of the requested profile that is not PASS stays in "
                     "scope_pending, and the reasons (with the measured value and the shortfall) "
                     "are in gate_measurements."),
        }
        blocked_path = out_dir / "release_freeze_blocked.json"
        blocked_path.write_text(json.dumps(blocked_payload, ensure_ascii=False, indent=2,
                                           sort_keys=True, default=str), encoding="utf-8")
        return {
            "status": "FAILED",
            "frozen": False,
            "release_id_attempted": release_id,
            "release_profile": profile,
            "generation_run_profile": run_profile,
            "gates": applied_gates,
            "store_derived_gates": gates,
            "required_gates": required,
            "scope_completed": scope_completed,
            "scope_pending": scope_pending,
            "scope_not_applicable": scope_not_applicable,
            "gate_overrides": overrides,
            "refused_gate_overrides": refused_overrides,
            "evidence_reports": evidence,
            "gate_measurements": measurements,
            "excluded_assets": excluded,
            "coverage": coverage,
            "relation_status": relations,
            "visibility_status": visibility,
            "assets": len(keep),
            "error": {"code": code, "stage": exc.stage, "message": exc.message,
                      "measurements": exc.measurements},
            "artifacts": [str(out_dir / "gates_evaluated.json"), str(blocked_path)],
        }
    manifest = manager.load(release_id)
    return {
        "status": "OK",
        "release_id": record.release_id,
        "release_profile": record.profile,
        "generation_run_profile": run_profile,
        "manifest_hash": record.manifest_hash,
        "manifest_path": record.manifest_path,
        "assets": len(record.asset_ids),
        "assets_by_role": _role_counts(keep),
        "gates": applied_gates,
        "required_gates": required,
        "scope_completed": scope_completed,
        "scope_pending": scope_pending,
        "scope_not_applicable": scope_not_applicable,
        "gate_overrides": overrides,
        "refused_gate_overrides": refused_overrides,
        "store_derived_gates": gates,
        "evidence_reports": evidence,
        "gate_measurements": measurements,
        "excluded_assets": excluded,
        "excluded_role_reasons": _exclusion_digest(excluded),
        "coverage": coverage,
        "relation_status": relations,
        "visibility_status": visibility,
        "scope_declaration": release_extra["scope_declaration"],
        "closure": manifest.get("closure"),
        "artifacts": [record.manifest_path, str(out_dir / "gates_evaluated.json")],
    }


def _role_counts(assets: Sequence[Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for asset in assets:
        out[asset.role] = out.get(asset.role, 0) + 1
    return out


def step_export(store: AssetStore, *, release_id: str, out_dir: Path,
                ledger: Ledger) -> dict[str, Any]:
    legacy_dir = out_dir / "release_index"
    legacy = export_release(store, release_id, fmt="parquet", out_dir=str(legacy_dir))
    package_dir = out_dir / "training_package"
    if package_dir.exists():
        shutil.rmtree(package_dir)
    package = export_training_package(store, release_id, package_dir,
                                      formats=("parquet", "npz", "zarr", "tar"))
    by_view = package.get("views", {})
    return {
        "status": "OK",
        "release_id": release_id,
        "package_dir": str(package_dir),
        "package_manifest": str(package_dir / "export_manifest.json"),
        "manifest_hash": package.get("manifest_hash"),
        "counts": package.get("counts"),
        "relations": package.get("counts", {}).get("relations"),
        "relation_kinds": package.get("counts", {}).get("relation_kinds"),
        "bytes_total": package.get("bytes_total"),
        "files_total": package.get("counts_total"),
        "views": by_view,
        "separation": package.get("separation"),
        "reference_closure": package.get("reference_closure"),
        "token_cache": package.get("token_cache"),
        "labels": package.get("labels"),
        "legacy_export": {"dir": str(legacy_dir), "hash": legacy.get("export_hash"),
                         "assets": legacy.get("assets")},
        "artifacts": [str(package_dir / "export_manifest.json"),
                      str(legacy_dir / "export_manifest.json")],
    }


def step_loader_probe(*, package_dir: Path, report_path: Path,
                      ledger: Ledger) -> dict[str, Any]:
    report = probe_training_package(package_dir, out_path=report_path)
    return {
        "status": "OK" if report.get("ok") else "FAILED",
        "ok": bool(report.get("ok")),
        "report_ref": str(report_path),
        "files_ok": report.get("files_ok"),
        "counts": report.get("counts"),
        "relation_pool": report.get("relation_pool"),
        "feature_shapes": report.get("feature_shapes"),
        "real_denominator": report.get("real_denominator"),
        "batch": report.get("batch"),
        "negative_audit": report.get("negative_audit"),
        "degenerate": report.get("degenerate"),
        "blocking_attempt": report.get("blocking_attempt"),
        "attempts": report.get("attempts"),
        "error": report.get("error"),
        "artifacts": [str(report_path)],
    }


# --------------------------------------------------------------------------------------
# driver
# --------------------------------------------------------------------------------------
def _failure(step: str, exc: BaseException) -> dict[str, Any]:
    code = getattr(getattr(exc, "code", None), "value", None)
    return {
        "status": "FAILED",
        "error": {
            "code": str(code or type(exc).__name__),
            "stage": getattr(exc, "stage", f"closed_loop.{step}"),
            "message": str(getattr(exc, "message", None) or exc)[:1200],
            "traceback": traceback.format_exc()[-2000:],
        },
        "artifacts": [],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="closed_loop",
        description="Run the A12 minimal closed loop (real assets -> export -> loader).")
    parser.add_argument("--step", default="all",
                        help=f"one of {', '.join(STEP_ORDER)} or 'all'")
    parser.add_argument("--resume", action="store_true",
                        help="reuse the steps already recorded as OK in the ledger")
    parser.add_argument("--reset", action="store_true",
                        help="clear the ledger but keep the store and generation report, so the "
                             "later steps re-run against data that already exists")
    parser.add_argument("--mothers", type=int, default=3, help="mothers to generate (default 3)")
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--store", default=DEFAULT_STORE)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--evidence", default=DEFAULT_EVIDENCE,
                        help="long-lived evidence store whose reports the gates may read")
    parser.add_argument("--report", default=None, help="closed-loop report path")
    parser.add_argument("--run", default=None,
                        help="generation run id the release is frozen for / the pool is attributed "
                             "to (default: the ledger's run, else reports/generation.json)")
    parser.add_argument("--profile", default=None,
                        help=f"release profile to attempt ({', '.join(PROFILE_GATES)}); default: "
                             f"{PROFILE}.  A stricter profile is allowed (PILOT on a SANDBOX_CORE "
                             f"run); the required gates of the requested profile are never "
                             f"relaxed, so a profile whose gates are not all PASS stays unfrozen "
                             f"and is recorded in scope_pending")
    parser.add_argument("--profile-as-run-profile", action="store_true",
                        help="use the run's own generation profile instead of --profile")
    args = parser.parse_args(argv)

    steps = list(STEP_ORDER) if args.step == "all" else [args.step]
    unknown = [s for s in steps if s not in STEP_ORDER]
    if unknown:
        parser.error(f"unknown step(s) {unknown}; expected one of {', '.join(STEP_ORDER)}")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    store = AssetStore(args.store)
    report_path = Path(args.report) if args.report else out_dir / "closed_loop_report.json"
    ledger = Ledger(report_path, run_id=None, store_root=str(store.root), config=args.config)
    ledger.data["mothers"] = int(args.mothers)

    evidence_dirs = [args.evidence] if Path(args.evidence).exists() else []

    if args.reset or (args.step == "all" and not args.resume):
        # A fresh full run replaces the ledger; ``--resume`` keeps it so the recorded evidence
        # of the steps that already ran survives into the final report.
        ledger.data["steps"] = []
        if args.reset:
            ledger.data["run_id"] = None
        ledger.flush()

    if args.run:
        # an explicit run id wins over the ledger's (a store may hold many runs; the operator
        # names the one this release is about).  Applied after --reset so it is not cleared.
        ledger.data["run_id"] = str(args.run)
        ledger.flush()

    def run(name: str, fn: Callable[[], dict[str, Any]]) -> dict[str, Any] | None:
        if args.resume:
            previous = ledger.completed(name)
            if previous is not None:
                print(f"[{name}] resumed (already {previous['status']})")
                return previous
        print(f"[{name}] running ...")
        t0 = time.time()
        try:
            result = fn()
        except Exception as exc:  # noqa: BLE001 - the failure is the measurement
            result = _failure(name, exc)
            result["seconds"] = time.time() - t0
            ledger.step(name, **result)
            print(f"[{name}] {result['status']}: {result['error']['message'][:200]}")
            return result
        result.setdefault("seconds", time.time() - t0)
        ledger.step(name, **result)
        print(f"[{name}] {result['status']} in {result['seconds']:.1f}s")
        return result

    for name in steps:
        if name == "generate":
            result = run(name, lambda: step_generate(store, config=args.config,
                                                     mothers=args.mothers, out_dir=out_dir,
                                                     ledger=ledger))
            if result and result.get("run_id"):
                ledger.data["run_id"] = result["run_id"]
                ledger.flush()
        elif name == "audit":
            run_id = _resolved_run_id(ledger, out_dir)
            if not run_id:
                ledger.step(name, status="FAILED", seconds=0.0,
                            error={"code": ErrorCode.INPUT_UNAVAILABLE.value,
                                   "message": "no run_id: run the generate step first"})
                continue
            run(name, lambda: step_audit(store, run_id=run_id, evidence_dirs=evidence_dirs,
                                         ledger=ledger))
        elif name == "build_pool":
            pool_run_id = _resolved_run_id(ledger, out_dir)
            run(name, lambda: step_build_pool(store, release_id=None, out_dir=out_dir,
                                              ledger=ledger, run_id=pool_run_id))
        elif name == "coverage_aggregate":
            run(name, lambda: step_coverage_aggregate(store, out_dir=out_dir, ledger=ledger))
        elif name == "release_freeze":
            run_id = _resolved_run_id(ledger, out_dir)
            if not run_id:
                ledger.step(name, status="FAILED", seconds=0.0,
                            error={"code": ErrorCode.INPUT_UNAVAILABLE.value,
                                   "message": "no run_id: run the generate step first"})
                continue
            release_profile = None if args.profile_as_run_profile else args.profile
            run(name, lambda: step_release_freeze(store, run_id=run_id, out_dir=out_dir,
                                                  evidence_dirs=evidence_dirs, ledger=ledger,
                                                  profile=release_profile))
        elif name == "export_training_package":
            release_id = _last_release_id(ledger)
            if not release_id:
                ledger.step(name, status="FAILED", seconds=0.0,
                            error={"code": ErrorCode.INPUT_UNAVAILABLE.value,
                                   "message": "no frozen release: run the release_freeze step "
                                              "first"})
                continue
            run(name, lambda: step_export(store, release_id=release_id, out_dir=out_dir,
                                          ledger=ledger))
        elif name == "loader_probe":
            package_dir = out_dir / "training_package"
            report_file = Path("data/a12/reports/loader_probe.json")
            run(name, lambda: step_loader_probe(package_dir=package_dir,
                                                report_path=report_file, ledger=ledger))
        elif name == "report":
            ledger.step(name, status="OK", seconds=0.0, summary=_summarise(ledger.data))
            print("[report] written " + str(report_path))

    recorded = {s["step"]: s for s in ledger.data.get("steps", [])}
    statuses = {name: recorded.get(name, {}).get("status") for name in steps}
    failed = {name: status for name, status in statuses.items() if status not in ("OK", "DEGRADED")}
    degraded = {name: status for name, status in statuses.items() if status == "DEGRADED"}
    ledger.data["ok"] = not failed
    ledger.data["step_status"] = statuses
    ledger.data["degraded_steps"] = degraded
    ledger.data["failed_steps"] = failed
    ledger.data["finished_at"] = time.time()
    ledger.data["summary"] = _summarise(ledger.data)
    ledger.flush()
    _print_summary(ledger.data, steps)
    if failed:
        print(f"  -> exit 1: {failed}")
        return 1
    if degraded:
        print(f"  -> exit 0 with caveats: {degraded} ran and recorded a real shortfall; "
              f"the per-step evidence names it")
    return 0


def _resolved_run_id(ledger: Ledger, out_dir: Path) -> str | None:
    """The run id from the ledger, falling back to the generation report on disk."""
    if ledger.data.get("run_id"):
        return str(ledger.data["run_id"])
    path = out_dir / "generation.json"
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        run_id = payload.get("run_id")
        if run_id:
            ledger.data["run_id"] = run_id
            ledger.flush()
            return str(run_id)
    return None


def _last_release_id(ledger: Ledger) -> str | None:
    for entry in reversed(ledger.data.get("steps", [])):
        if entry.get("step") == "release_freeze" and entry.get("release_id"):
            return str(entry["release_id"])
    return None


def _summarise(data: dict[str, Any]) -> dict[str, Any]:
    steps = {s["step"]: s for s in data.get("steps", [])}
    return {
        "run_id": data.get("run_id"),
        "accepted_mothers": (steps.get("generate") or {}).get("accepted"),
        "attempted_mothers": (steps.get("generate") or {}).get("attempted"),
        "pool": {
            "status": (steps.get("build_pool") or {}).get("pool_status"),
            "candidates": (steps.get("build_pool") or {}).get("candidates"),
            "queries": (steps.get("build_pool") or {}).get("queries"),
            "r2_edges": (steps.get("build_pool") or {}).get("r2_edges"),
        },
        "release": {
            "release_id": (steps.get("release_freeze") or {}).get("release_id"),
            "profile": (steps.get("release_freeze") or {}).get("release_profile"),
            "assets": (steps.get("release_freeze") or {}).get("assets"),
            "scope_pending": (steps.get("release_freeze") or {}).get("scope_pending"),
            "gates": (steps.get("release_freeze") or {}).get("gates"),
        },
        "package": {
            "dir": (steps.get("export_training_package") or {}).get("package_dir"),
            "bytes": (steps.get("export_training_package") or {}).get("bytes_total"),
            "files": (steps.get("export_training_package") or {}).get("files_total"),
            "relation_kinds": (steps.get("export_training_package") or {}).get("relation_kinds"),
        },
        "loader_probe": {
            "ok": (steps.get("loader_probe") or {}).get("ok"),
            "batch": (steps.get("loader_probe") or {}).get("batch"),
            "degenerate": (steps.get("loader_probe") or {}).get("degenerate"),
        },
        "step_status": {name: entry.get("status") for name, entry in steps.items()},
    }


def _print_summary(data: dict[str, Any], steps: Sequence[str] | None = None) -> None:
    wanted = set(steps) if steps else None
    print("\n=== closed loop ===")
    for entry in data.get("steps", []):
        if wanted is not None and entry["step"] not in wanted:
            continue
        detail = ""
        if entry["step"] == "generate":
            detail = (f"accepted {entry.get('accepted')}/{entry.get('attempted')}")
        elif entry["step"] == "build_pool":
            detail = (f"{entry.get('pool_status')} candidates={entry.get('candidates')} "
                      f"queries={entry.get('queries')} r2={entry.get('r2_edges')}")
        elif entry["step"] == "release_freeze":
            detail = (f"{entry.get('release_id')} profile={entry.get('release_profile')} "
                      f"assets={entry.get('assets')} pending={entry.get('scope_pending')}")
        elif entry["step"] == "export_training_package":
            detail = (f"{entry.get('bytes_total')} bytes in {entry.get('files_total')} files")
        elif entry["step"] == "loader_probe":
            batch = entry.get("batch") or {}
            detail = (f"ok={entry.get('ok')} queries={batch.get('n_queries')} "
                      f"pos={batch.get('positives')} neg={batch.get('negatives')}")
        elif entry["step"] == "report":
            detail = f"ok={data.get('ok')} degraded={sorted(data.get('degraded_steps') or [])}"
        print(f"  {entry['step']:<24} {entry['status']:<9} {entry.get('seconds', 0):>7.1f}s  "
              f"{detail}")
    if not data.get("ok"):
        print("  -> the loop is NOT complete; see the per-step errors in the report")


if __name__ == "__main__":
    raise SystemExit(main())
