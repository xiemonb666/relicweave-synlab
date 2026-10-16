"""Smoke test for the PhysicalPack result producer (fast, no full pipeline run).

Builds one real physical outcome in memory (a cube + the audit + the same meta keys
``apply_damage`` fills), commits it through ``physical.commit_physical`` /
``physical.commit_physical_result`` into a throwaway store and prints what really landed.
Catches payload/ancestry/QA-verdict errors without paying for a full generation.

Usage: python data/a12/reports/smoke_physical_result.py [--out <json>]
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import trimesh

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synlab.physical.api import (  # noqa: E402
    audit_physical,
    commit_physical,
    commit_physical_result,
    register_components,
)
from synlab.roles import ROLE_CLEAN_TRUTH, ROLE_PHYSICAL_COMPONENT, ROLE_PHYSICAL_RESULT  # noqa: E402
from synlab.schemas.runtime import PhysicalResult  # noqa: E402
from synlab.storage.store import QA_FAIL, QA_PASS, AssetStore  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="data/a12/reports/physical_result_smoke.json")
    args = parser.parse_args()

    root = Path(tempfile.mkdtemp(prefix="physical_result_smoke_")) / "store"
    store = AssetStore(root)

    cube = trimesh.creation.box(extents=(20.0, 20.0, 20.0))
    clean_asset = store.commit_asset(
        role=ROLE_CLEAN_TRUTH, schema="synlab.truth.clean.v1", unit="mm", frame="W_mm",
        payload={"relations_json": "[]"}, meta={"mother_id": "M_smoke"}, qa={"ok": True},
        qa_status=QA_PASS, lineage_id="LIN_smoke", split="train")

    components, representative_map, ledger = register_components(
        [cube], clean_fragment_id="F_smoke", source_volume_mm3=float(abs(cube.volume)))
    result = PhysicalResult(
        mother_id="M_smoke", clean_ref="M_smoke:E01:v1", event_id="E01",
        recipe_id="P03:depth_mm:L1", version=1, components=components,
        lost_volume_mm3=float(ledger["lost_volume_mm3"]),
        lost_volume_ratio=float(ledger["lost_volume_mm3"] / max(abs(cube.volume), 1e-12)),
        representative_map=representative_map, qa={"result_geometry_hash": "sha256:deadbeef"},
        meta={"declared": {"axis_id": "P03", "variant": "depth_mm", "level": 1,
                           "touches_geometry": True},
              "axis_id": "P03", "variant": "depth_mm", "level": 1, "identity": True,
              "ledger": ledger, "measured": {"depth_mm": 0.0}, "measurement_units": {"depth_mm": "mm"},
              "frozen": {"recipe_id": "P03:depth_mm:L1", "basis_source": "degrade.registry"},
              "source_geometry_hash": "sha256:cafe"})

    audit = audit_physical(result, cube)
    component_asset = commit_physical(store, result, lineage_id="LIN_smoke", split="train")
    result_asset = commit_physical_result(
        store, result, audit=audit, clean_asset_id=clean_asset.asset_id,
        clean_asset_hash=clean_asset.blob_hash, component_asset_id=component_asset.asset_id,
        lineage_id="LIN_smoke", split="train", run_id="run_smoke")

    out = {
        "store": str(root),
        "audit_status": audit.get("status"),
        "audit_failure_codes": audit.get("failure_codes"),
        "component_asset": {"asset_id": component_asset.asset_id,
                            "role": component_asset.role, "qa": component_asset.qa_status},
        "result_asset": {
            "asset_id": result_asset.asset_id, "role": result_asset.role,
            "schema": result_asset.schema, "unit": result_asset.unit, "frame": result_asset.frame,
            "qa_status": result_asset.qa_status, "ancestry": result_asset.ancestry,
            "expected_qa_status": QA_PASS if audit.get("status") == "PASS" else QA_FAIL,
            "files": sorted(result_asset.files),
            "arrays": {k: [list(v.shape), str(v.dtype)]
                       for k, v in store.load_arrays(result_asset.asset_id).items()},
            "meta": {k: result_asset.meta[k] for k in sorted(result_asset.meta or {})},
        },
        "roles": sorted({a.role for a in store.list_assets(limit=100)}),
        "checks": {},
    }
    meta = result_asset.meta
    out["checks"] = {
        "verdict_is_audit_status": result_asset.qa_status == out["result_asset"]["expected_qa_status"],
        "lost_volume_matches_audit": abs(meta["lost_volume_mm3"]
                                         - audit["measured"]["lost_volume_mm3"]) <= 1e-9,
        "lost_is_real_measurement": abs(meta["lost_volume_mm3"] - float(abs(cube.volume))) > 0.0,
        "source_hash_is_clean_asset": meta["source_hash"] == clean_asset.blob_hash,
        "representative_map_present": bool(meta["representative_map"]),
        "component_count_matches": meta["components"]["count"] == len(components),
        "measurement_names_match_values": len(meta["measurement_names"])
        == len(store.load_arrays(result_asset.asset_id)["measurement_values"]),
        "qa_block_is_audit": result_asset.qa == meta["qa"],
    }
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("audit_status", "audit_failure_codes", "checks")},
                     ensure_ascii=False, indent=2))
    print(json.dumps(out["result_asset"], ensure_ascii=False, indent=2, default=str)[:2500])
    print(f"wrote {target}")
    return 0 if all(out["checks"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
