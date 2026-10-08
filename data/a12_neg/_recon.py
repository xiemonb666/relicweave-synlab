"""Recon: which real run plan produced the LIN000x mothers, and how does plan_generation look."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

for path in sorted((REPO / "data/a12/reports").glob("run_spec_run_*.json")):
    raw = json.loads(path.read_text(encoding="utf-8"))
    plan = raw.get("plan") if isinstance(raw, dict) else None
    if not isinstance(plan, dict):
        continue
    lineages = plan.get("lineages") or []
    ids = [str(item.get("lineage_id")) for item in lineages]
    print(path.name, "job=", plan.get("job_id"), "lineages=", len(ids))
    print("   ", ids[:8])
    if "LIN0000_V01_M01_PAT01" in ids:
        print("   >>> HAS mother0; keys:", sorted(plan.keys()))
        print("   >>> first lineage:", json.dumps(lineages[0], ensure_ascii=False)[:600])
        print("   >>> config:", raw.get("config"), "hash:", raw.get("config_hash"))

print("=" * 30, "load_generation_spec")
from synlab.config import load_generation_spec  # noqa: E402
from synlab.pipeline import plan_generation  # noqa: E402

for cfg in ("configs/a12/next_experiment.yaml", "configs/a12/realistic.yaml"):
    try:
        spec = load_generation_spec(cfg)
        plan = plan_generation(spec)
    except Exception as exc:  # noqa: BLE001
        print(cfg, "FAILED", type(exc).__name__, exc)
        continue
    ids = [l.lineage_id for l in plan.lineages]
    print(cfg, "job=", plan.job_id, "n=", len(ids), ids[:6])
    print("   fracture cfg:", type(getattr(plan.compiled, "fracture", None)).__name__,
          "observation routes:", [r.value for r in spec.observation.routes])
