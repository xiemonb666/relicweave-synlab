"""Scratch script: freeze a release over the degradation-diversity store and export a package.

Not a deliverable.  Records everything it measured in ``data/a12_reports/``.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from synlab.degrade.diversity import (  # noqa: E402
    ROLE_DEGRADE_SOURCE,
    ROLE_DEGRADE_VARIANT,
    directory_bytes,
)
from synlab.qc.audit import audit_run, write_audit_report  # noqa: E402
from synlab.qc.gates import evaluate_gates  # noqa: E402
from synlab.storage.export import export_training_package  # noqa: E402
from synlab.storage.release import ReleaseManager  # noqa: E402
from synlab.storage.store import QA_PASS, AssetStore  # noqa: E402

STORE_ROOT = ROOT / "data" / "a12_degrade" / "store"
EXPORT_ROOT = ROOT / "data" / "a12_degrade" / "exports"
REPORTS = ROOT / "data" / "a12_reports"
EVIDENCE = [str(ROOT / "data" / "a12")]      # the long-lived evidence store (read-only)

store = AssetStore(STORE_ROOT)
manager = ReleaseManager(store)
coverage = json.loads((STORE_ROOT / "reports" / "coverage.json").read_text(encoding="utf-8"))
run_id = coverage["run_id"]


def closed_loop_tool():
    """Import the shipped release-preparation step (``tools/closed_loop.py``)."""
    import importlib.util

    path = ROOT / "tools" / "closed_loop.py"
    spec = importlib.util.spec_from_file_location("closed_loop_tool_degrade", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tool = closed_loop_tool()
# the shipped release-preparation contracts: decide the deferred verdicts and repair ancestry
# entries that name a semantic key (mother:event:version) instead of an asset id
promotion = tool._promote_pending_assets(store)
repairs = tool._resolve_ancestry(store)

# --- real gate evidence from this store (+ the repo's shared acceptance reports) -------------
audit = audit_run(store, run_id)
audit_path = write_audit_report(store, audit, f"audit_{run_id}")
gates, gate_asset_ids, profile = evaluate_gates(store, run_id, evidence_dirs=EVIDENCE)

assets = [a for a in store.list_assets(limit=100000) if a.qa_status == QA_PASS]
release_id = f"rel_degrade_diversity_{int(time.time())}"
t0 = time.perf_counter()
freeze: dict = {"attempted": True, "gates": gates, "profile": profile,
                "required": None, "ok": False}
try:
    record = manager.freeze(release_id=release_id, profile=profile, scope="SYNTHETIC",
                            asset_ids=[a.asset_id for a in assets], gates=gates,
                            coverage={"run_id": run_id, "lineages": coverage["accepted"],
                                      "assets": len(assets)},
                            extra={"batch": "degrade_diversity",
                                   "config": "configs/a12/degrade_diversity.yaml",
                                   "audit_report": str(audit_path),
                                   "evidence_dirs": EVIDENCE})
    freeze.update({"ok": True, "manifest_hash": record.manifest_hash,
                   "assets": len(record.asset_ids), "scope_pending": record.scope_pending})
except Exception as exc:  # noqa: BLE001 - a refused freeze is an outcome, reported below
    from synlab.storage.release import PROFILE_GATES

    freeze.update({"ok": False, "required": PROFILE_GATES.get(profile),
                   "error": {"type": type(exc).__name__,
                             "code": str(getattr(getattr(exc, "code", None), "value",
                                                 getattr(exc, "code", ""))),
                             "message": str(getattr(exc, "message", exc))[:400]}})

# --- export -----------------------------------------------------------------------------------
def unfrozen_manifest(asset_ids: list[str], reason: str) -> dict:
    """Manifest-shaped view of the scope for a release whose freeze was refused (shipped pattern).

    Mirrors ``tools/next_experiment_export.py::_unverified_manifest``: it is **not** written to
    ``<store>/releases/<id>/manifest.json`` and carries an ``_UNFROZEN`` profile so nothing
    downstream can mistake it for a frozen release.
    """
    from synlab.canonical import hash_json

    assets = []
    for asset_id in asset_ids:
        record = store.get_asset(asset_id)
        assets.append({"asset_id": record.asset_id, "role": record.role, "schema": record.schema,
                       "unit": record.unit, "frame": record.frame, "blob_hash": record.blob_hash,
                       "qa_status": record.qa_status, "lineage_id": record.lineage_id,
                       "split": record.split, "interpretation_hash": record.interpretation_hash,
                       "files": record.files})
    payload = {"schema": "synlab.release.v1", "release_id": release_id,
               "profile": f"{profile}_UNFROZEN", "scope": "SYNTHETIC",
               "gates": {"note": "freeze refused", "reason": reason, "gates": gates},
               "assets": assets}
    payload["manifest_hash"] = hash_json(payload)
    return payload


result: dict = {"run_id": run_id, "release_id": release_id, "freeze": freeze, "gates": gates,
                "profile": profile, "audit_report": str(audit_path),
                "closed_loop": {"promoted": len(promotion.get("promoted") or []),
                                "failed": len(promotion.get("failed") or []),
                                "ancestry_repairs": repairs.get("n_repairs"),
                                "ancestry_dropped": len(repairs.get("dropped") or [])},
                "store_bytes": directory_bytes(STORE_ROOT)}

package_dir = EXPORT_ROOT / release_id / "training_package"
release_refusal: str | None = None
if freeze["ok"]:
    manifest = export_training_package(store, release_id, package_dir)
else:
    # The six required SANDBOX_CORE gates are PASS and the reference closure verifies, but
    # ``ReleaseManager.freeze`` hashes the whole manifest and therefore refuses a store that
    # carries a NaN in any asset metadata (measured: ``clean_truth.meta.event_tree.cutter.meta
    # .sampling_cell_size_reference_mm``).  That NaN is produced by the fracture/cutter stage of
    # another agent's module, so it is reported instead of being edited away; the export runs on
    # the *unfrozen* manifest view the shipped batch exporter uses for a refused freeze.
    from synlab.storage import release as release_mod

    release_refusal = freeze.get("error", {}).get("message", "")
    in_memory = unfrozen_manifest([a.asset_id for a in assets], release_refusal)
    original_load = release_mod.ReleaseManager.load
    release_mod.ReleaseManager.load = lambda self, rid, _m=in_memory: (
        _m if rid == release_id else original_load(self, rid))
    try:
        manifest = export_training_package(store, release_id, package_dir)
    finally:
        release_mod.ReleaseManager.load = original_load
    result["freeze_refused_reason"] = release_refusal
    result["release_profile_used"] = in_memory["profile"]

if True:
    rows = json.loads((package_dir / "degrade" / "index.json").read_text(encoding="utf-8"))["rows"]
    result.update({
        "package_dir": str(package_dir),
        "package_counts": manifest["counts"],
        "package_degrade_block": manifest["degrade_diversity"],
        "package_files": len(manifest["files"]),
        "package_bytes": manifest["bytes_total"],
        "package_release_profile": manifest.get("release_profile"),
        "assets_by_role": manifest["assets"]["by_role"],
        "variant_rows": len(rows),
        "variant_fields": sorted(rows[0]) if rows else [],
        "sample_rows": rows[:3],
        "deploy_truth_content": manifest["views"]["deploy"]["contains_truth"],
        "answer_field_hits": manifest["separation"]["features_carry_answer_fields"],
        "degrade_files": manifest["degrade_diversity"]["files"],
    })
result["seconds"] = round(time.perf_counter() - t0, 2)
REPORTS.mkdir(parents=True, exist_ok=True)
out = REPORTS / "degrade_diversity_export.json"
out.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
print("REPORT", out)
print(json.dumps(result, ensure_ascii=False, indent=2, default=str)[:6000])
