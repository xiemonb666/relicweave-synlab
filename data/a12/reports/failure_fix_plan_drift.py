"""Is the plan the running batch uses still the plan my 48-row snapshot validated?

``LIN0016_V19_M04_PAT08`` was built by the other writer's process with parameters that differ
from my 11:05 snapshot although the (vessel, material, pattern) triple is the same.  This script
re-plans the *full* 120-target plan with the current working tree and compares, for a few
lineages, the parameters against (a) the batch's committed mother assets and (b) my snapshot.

Usage::

    python data/a12/reports/failure_fix_plan_drift.py [vessel-index ...]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from synlab.config import load_generation_spec  # noqa: E402
from synlab.pipeline import plan_generation  # noqa: E402
from synlab.registry import load_all  # noqa: E402
from synlab.storage.store import AssetStore  # noqa: E402

SPEC = ROOT / "configs" / "a12" / "next_experiment.yaml"
SNAPSHOT = ROOT / "data" / "a12" / "reports" / "failure_class1_param_validation.json"
OUT = ROOT / "data" / "a12" / "reports" / "failure_fix_plan_drift.json"


def main() -> int:
    load_all()
    spec = load_generation_spec(SPEC)
    plan = plan_generation(spec)
    snapshot = {row["lineage_id"]: row for row in
                json.loads(SNAPSHOT.read_text(encoding="utf-8"))["rows"]}
    store = AssetStore(ROOT / "data" / "a12")
    committed: dict[str, dict] = {}
    for asset in store.list_assets(limit=500000):
        if asset.role != "mother_mesh":
            continue
        lineage = getattr(asset, "lineage_id", None)
        if lineage and lineage not in committed:
            committed[lineage] = dict((asset.meta or {}).get("params") or {})

    rows = []
    for lineage in plan.lineages:
        snap = snapshot.get(lineage.lineage_id)
        batch = committed.get(lineage.lineage_id)
        rows.append({
            "index": lineage.mother_index,
            "lineage_id": lineage.lineage_id,
            "vessel_id": lineage.vessel_id,
            "material_id": lineage.material_id,
            "pattern_id": lineage.pattern_id,
            "params_now": lineage.params,
            "params_snapshot_equal": (snap or {}).get("params") == lineage.params,
            "snapshot_triple_equal": snap is None or (
                snap["vessel_id"], snap["material_id"], snap["pattern_id"])
            == (lineage.vessel_id, lineage.material_id, lineage.pattern_id),
            "batch_params_equal": None if batch is None else (batch == lineage.params),
        })
    differing = [r for r in rows if r["params_snapshot_equal"] is False]
    batch_rows = [r for r in rows if r["batch_params_equal"] is not None]
    report = {
        "planned": len(plan.lineages),
        "lineages_with_a_snapshot": sum(1 for r in rows if r["params_snapshot_equal"] is not None),
        "params_matching_the_snapshot": sum(1 for r in rows if r["params_snapshot_equal"]),
        "params_differing_from_the_snapshot": len(differing),
        "first_differing_index": differing[0]["index"] if differing else None,
        "lineages_with_a_committed_batch_mother": len(batch_rows),
        "batch_params_matching_the_current_plan": sum(
            1 for r in batch_rows if r["batch_params_equal"]),
        "batch_params_differing_from_the_current_plan": sum(
            1 for r in batch_rows if not r["batch_params_equal"]),
        "triples_matching_the_snapshot": sum(1 for r in rows if r["snapshot_triple_equal"]),
        "rows": rows,
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    for key, value in report.items():
        if key != "rows":
            print(f"{key}: {value}")
    for index in (0, 4, 16, 30, 60):
        row = next((r for r in rows if r["index"] == index), None)
        if row:
            print(f"  #{index} {row['lineage_id']:26s} snapshot_equal={row['params_snapshot_equal']} "
                  f"batch_equal={row['batch_params_equal']}")
    print(f"written {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
