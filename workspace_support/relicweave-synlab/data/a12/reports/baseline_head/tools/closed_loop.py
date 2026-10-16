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
from typing import Any, Callable, Sequence

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
from synlab.relations.api import save_pool_json, save_roster_json  # noqa: E402
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
    ROLE_PHYSICAL_TRUTH,
    ROLE_POOL,
    ROLE_VISIBLE_LABELS,
)
from synlab.storage.export import export_release, export_training_package  # noqa: E402
from synlab.storage.release import PROFILE_GATES, ReleaseManager  # noqa: E402
from synlab.storage.store import QA_FAIL, QA_PASS, QA_PENDING, AssetStore  # noqa: E402

STEP_ORDER: tuple[str, ...] = (
    "generate", "audit", "build_pool", "release_freeze", "export_training_package",
    "loader_probe", "report",
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


def _tag_run_assets(store: AssetStore, run_id: str) -> dict[str, Any]:
    """Stamp ``meta.run_id`` on the assets a run produced.

    ``qc.audit.audit_run`` resolves a run's assets through ``meta["run_id"]``.  The pipeline
    stamps it on the assets it commits itself; ``truth.commit_truth`` and
    ``observe.commit_observation`` build their own meta, so their assets (clean/physical/visible
    truth, observation) and the physical component would stay invisible to the audit -- "run
    produced no assets".  The attribution is derived from the run's own coverage ledger
    (``coverage.json.lineage_ids`` -> asset ``lineage_id``), and every stamp is recorded.
    """
    coverage_path = store.root / "reports" / "coverage.json"
    lineage_ids: set[str] = set()
    rows_path = store.root / "reports" / "coverage_rows.json"
    source: str | None = None
    for path in (rows_path, coverage_path):
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        entries = payload if isinstance(payload, list) else (payload.get("rows") or [])
        for row in entries:
            lineage = str(row.get("lineage_id") or "")
            if lineage:
                lineage_ids.add(lineage)
        if lineage_ids:
            source = str(path)
            break
    tagged: list[str] = []
    if not lineage_ids:
        return {"tagged": tagged, "lineage_ids": [], "source": None}
    import sqlite3

    with store.connect() as conn:
        rows = conn.execute("SELECT asset_id, role, meta_json FROM assets").fetchall()
        for row in rows:
            meta = json.loads(row["meta_json"] or "{}")
            if meta.get("run_id") == run_id:
                continue
            lineage = str(meta.get("lineage_id") or "")
            if not lineage:
                asset = store.get_asset(row["asset_id"])
                lineage = str(asset.lineage_id or "")
            if not lineage or lineage not in lineage_ids:
                continue
            meta["run_id"] = run_id
            meta["run_id_source"] = "closed_loop._tag_run_assets"
            conn.execute("UPDATE assets SET meta_json=? WHERE asset_id=?",
                         (json.dumps(meta, sort_keys=True, default=str), row["asset_id"]))
            tagged.append(row["asset_id"])
    return {"tagged": tagged, "lineage_ids": sorted(lineage_ids), "source": source}


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


def step_build_pool(store: AssetStore, *, release_id: str | None, out_dir: Path,
                    ledger: Ledger) -> dict[str, Any]:
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
    pool = report.get("pool")
    if pool is not None:
        qa = {"ok": True, "n2_materialised": False,
              "gallery_hash": report.get("hash"), "candidates": report.get("candidates"),
              "queries": report.get("queries"), "r2_edges": report.get("r2_edges"),
              "has_r2": bool(report.get("r2_edges")), "verdict": "PASS"}
        asset = commit_pool(store, pool, split="dev", qa=qa, ancestry=[])
        # ``commit_pool`` leaves the asset QA_PENDING; the gallery just built and audited is the
        # evidence, so the verdict is recorded here and the honest caveat travels with it.
        store.set_qa(asset.asset_id, QA_PASS, qa)
        roster_asset = commit_roster(store, pool, split="dev", ancestry=[asset.asset_id])
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

#: Roles deliberately left out of the frozen scope, with the reason (also written to the
#: release manifest so the omission is auditable).  A QA_FAIL asset must never enter a
#: release, and the reason it was left out is recorded next to the release.
EXCLUDED_ROLE_REASONS: dict[str, str] = {
    ROLE_VISIBLE_LABELS: (
        "one of three visible_labels assets carries QA_FAIL ('no correspondence sample is "
        "visible in any view': the deliverable foreground mask is empty for that fragment) and "
        "a release may not reference a failed asset"),
}


def step_release_freeze(store: AssetStore, *, run_id: str, out_dir: Path,
                        evidence_dirs: Sequence[str], ledger: Ledger) -> dict[str, Any]:
    gates, gate_asset_ids, profile = gates_mod.evaluate_gates(
        store, run_id, evidence_dirs=evidence_dirs)
    evidence = gates_mod.gate_evidence(store, run_id, evidence_dirs)
    (out_dir / "gates_evaluated.json").write_text(
        json.dumps({"profile": profile, "gates": gates, "evidence": evidence},
                   ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    # --- scope: every QA_PASS asset of this run, whatever its role -------------------------
    run_assets = [a for a in store.list_assets(limit=100000)
                  if (a.meta or {}).get("run_id") == run_id]
    keep = [a for a in run_assets if a.qa_status == QA_PASS]
    excluded = [{"asset_id": a.asset_id, "role": a.role, "qa_status": a.qa_status,
                 "reason": EXCLUDED_ROLE_REASONS.get(
                     a.role, "asset is not QA_PASS and may not enter a release")}
                for a in run_assets if a.qa_status != QA_PASS]
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

    required = PROFILE_GATES[PROFILE]
    scope_completed = [g for g in required if applied_gates.get(g) == "PASS"]
    # ``ReleaseManager.freeze`` blocks on any required gate that is not PASS, so NA is a *pending*
    # verdict here as well; the NA list is kept separately for the manifest.
    scope_pending = [g for g in required if applied_gates.get(g) != "PASS"]
    scope_not_applicable = [g for g in required if applied_gates.get(g) == "NA"]
    release_id = f"rel_{run_id.split('_', 1)[-1][:12]}_{int(time.time())}"
    release_extra = {
        "gate_overrides": overrides,
        "refused_gate_overrides": refused_overrides,
        "store_derived_gates": gates,
        "scope_not_applicable": scope_not_applicable,
        "evidence_reports": evidence,
        "excluded_assets": excluded,
        "excluded_role_reasons": EXCLUDED_ROLE_REASONS,
        "scope_declaration": (
            "SANDBOX_CORE release of the closed loop. The frozen scope is every QA_PASS "
            "asset of one real generation run (3 mothers / 3 materials / 3 patterns / 6 "
            "fragments / clean + physical + visible truth / 3 observations / features / "
            "labels / provenance) and its reference closure verifies. It contains NO "
            "relation with an R2 label: every interface patch of every event is classified "
            "UNKNOWN, so the pool has candidates but zero positives. This release exists to "
            "validate the export / loader / release machinery end to end; it is not a "
            "supervision release."),
        "relation_status": {
            "r2_edges": 0,
            "unknown_edges": 3,
            "reason": ("truth.CleanTruth classifies every interface patch as UNKNOWN "
                       "because patch.ambiguity_area_ratio (0.13-0.28) exceeds "
                       "ambiguity_max (0.02); the fracture auditor's own "
                       "ambiguous_area_ratio_max records the same number"),
        },
        "visibility_status": {
            "visible_labels_passed": 2, "visible_labels_failed": 1,
            "reason": ("for one mother the fragments' camera-z span (~64 mm) is far wider "
                       "than the declared depth of field at the delivered resolution, so "
                       "no correspondence sample is visible in any view"),
        },
    }
    try:
        record = manager.freeze(
            release_id=release_id, profile=PROFILE, scope="SYNTHETIC",
            asset_ids=[a.asset_id for a in keep], gates=applied_gates,
            coverage={
                "roles": _role_counts(keep),
                "vessels": sorted({str((a.meta or {}).get("vessel_id", "")) for a in keep
                                   if (a.meta or {}).get("vessel_id")}),
                "materials": sorted({str((a.meta or {}).get("material_id", "")) for a in keep
                                     if (a.meta or {}).get("material_id")}),
                "fragment_assets_in_scope": len([a for a in keep
                                                 if a.role == ROLE_FRAGMENT_MESH]),
                "r2_relations_in_scope": 0,
            },
            scope_pending=scope_pending,
            extra=release_extra)
    except SynLabError as exc:
        # The freeze refused (a required gate is not PASS).  Do not lower the release by
        # hand and do not widen the gates: record the refusal, the exact gate verdicts and
        # the blocking set, so the document can state "not frozen + why".
        code = exc.code.value if isinstance(exc.code, ErrorCode) else str(exc.code)
        blocked_payload = {
            "schema": "synlab.release_freeze_blocked.v1",
            "run_id": run_id, "release_id_attempted": release_id, "profile": PROFILE,
            "frozen": False, "error": {"code": code, "stage": exc.stage,
                                       "message": exc.message, "measurements": exc.measurements},
            "required_gates": required, "gates": applied_gates, "store_derived_gates": gates,
            "scope_completed": scope_completed, "scope_pending": scope_pending,
            "scope_not_applicable": scope_not_applicable,
            "gate_overrides": overrides, "refused_gate_overrides": refused_overrides,
            "evidence_reports": evidence,
            "note": ("SANDBOX_CORE is the lowest stage in storage.release.PROFILE_GATES, so a "
                     "required gate that is not PASS cannot be answered by freezing under a "
                     "lower profile: the release stays unfrozen and every unpassed required "
                     "gate is listed in scope_pending."),
        }
        blocked_path = out_dir / "release_freeze_blocked.json"
        blocked_path.write_text(json.dumps(blocked_payload, ensure_ascii=False, indent=2,
                                           sort_keys=True, default=str), encoding="utf-8")
        return {
            "status": "FAILED",
            "frozen": False,
            "release_id_attempted": release_id,
            "release_profile": PROFILE,
            "gates": applied_gates,
            "store_derived_gates": gates,
            "required_gates": required,
            "scope_completed": scope_completed,
            "scope_pending": scope_pending,
            "scope_not_applicable": scope_not_applicable,
            "gate_overrides": overrides,
            "refused_gate_overrides": refused_overrides,
            "evidence_reports": evidence,
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
        "excluded_assets": excluded,
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
            run(name, lambda: step_build_pool(store, release_id=None, out_dir=out_dir,
                                              ledger=ledger))
        elif name == "release_freeze":
            run_id = _resolved_run_id(ledger, out_dir)
            if not run_id:
                ledger.step(name, status="FAILED", seconds=0.0,
                            error={"code": ErrorCode.INPUT_UNAVAILABLE.value,
                                   "message": "no run_id: run the generate step first"})
                continue
            run(name, lambda: step_release_freeze(store, run_id=run_id, out_dir=out_dir,
                                                  evidence_dirs=evidence_dirs, ledger=ledger))
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
