"""Class-1 verification: 48 lineages from the frozen config, every param set validated.

Runs the *real* planner (``synlab.pipeline.plan_generation`` with ``max_mothers=48`` on
``configs/a12/next_experiment.yaml``) and then, for every lineage, constructs the vessel's own
pydantic parameter model from the dictionary the lineage would really be built with.  The
result is written to ``data/a12/reports/failure_class1_param_validation.json`` so every number
can be recomputed.

The script only plans (no mother, no asset, no store write); planning itself runs the real
sampler gate (build + audit), which is the point of the exercise.
"""
from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

sys.path.insert(0, str(ROOT / "tools"))

from synlab.config import load_generation_spec  # noqa: E402
from synlab.mothers.api import declared_fields, params_model_ok  # noqa: E402
from synlab.pipeline import plan_generation  # noqa: E402
from synlab.registry import load_all  # noqa: E402

CONFIG = ROOT / "configs" / "a12" / "next_experiment.yaml"
LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 48
OUT = ROOT / "data" / "a12" / "reports" / "failure_class1_param_validation.json"


def main() -> int:
    load_all()
    spec = load_generation_spec(CONFIG)
    t0 = time.time()
    plan = plan_generation(spec, max_mothers=LIMIT)
    plan_seconds = time.time() - t0

    rows = []
    passed = 0
    for lineage in plan.lineages:
        ok, why = params_model_ok(lineage.vessel_id, lineage.params)
        declared = declared_fields(lineage.vessel_id)
        foreign = sorted(set(lineage.params) - set(declared))
        missing = sorted(set(declared) - set(lineage.params))
        rows.append({
            "lineage_id": lineage.lineage_id,
            "vessel_id": lineage.vessel_id,
            "material_id": lineage.material_id,
            "pattern_id": lineage.pattern_id,
            "params": lineage.params,
            "n_params": len(lineage.params),
            "declared_n": len(declared),
            "foreign_fields": foreign,
            "fields_not_in_params": missing,
            "model_ok": bool(ok),
            "model_error": why,
        })
        passed += int(ok)

    report = {
        "config": str(CONFIG.relative_to(ROOT)).replace("\\", "/"),
        "limit": LIMIT,
        "planned": len(plan.lineages),
        "validated": len(rows),
        "passed": passed,
        "pass_rate": (passed / len(rows)) if rows else 0.0,
        "foreign_field_rows": sum(1 for r in rows if r["foreign_fields"]),
        "plan_seconds": round(plan_seconds, 3),
        "spec_hash": plan.spec_hash,
        "job_id": plan.job_id,
        "vessels": dict(sorted(Counter(r["vessel_id"] for r in rows).items())),
        "validation": ("model_validate on the vessel's own pydantic params model "
                       "(extra=forbid), missing fields filled from schema midpoints"),
        "rows": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str),
                   encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "rows"},
                     ensure_ascii=False, indent=2))
    failures = [r for r in rows if not r["model_ok"]]
    for row in failures[:10]:
        print(f"FAILED {row['lineage_id']} {row['vessel_id']} "
              f"foreign={row['foreign_fields']} :: {row['model_error'][:300]}")
    return 0 if passed == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())

