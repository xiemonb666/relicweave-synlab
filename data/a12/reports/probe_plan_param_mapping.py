"""Which vessel do the lineage parameters actually belong to? (plan/pipeline consistency check)

``plan_generation`` assigns ``param_samples[index]`` to the lineage it builds at ``index``.
``_sample_parameter_sets`` samples *per vessel* and then hands out
``vessels[index % len(vessels)]``.  As long as both sides walk the vessel list the same way the
two agree; a change to the lineage/vessel mapping in one place silently passes another vessel's
parameters to a mother (which then fails parameter validation).

Usage: python data/a12/reports/probe_plan_param_mapping.py --config configs/a12/sandbox.yaml
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synlab.config import load_generation_spec  # noqa: E402
from synlab.pipeline import _sample_parameter_sets, plan_generation  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/a12/sandbox.yaml")
    parser.add_argument("--out", default="data/a12/reports/plan_param_mapping_probe.json")
    args = parser.parse_args()
    spec = load_generation_spec(REPO_ROOT / args.config)
    plan = plan_generation(spec, max_mothers=4)
    vessels = list(spec.dataset.vessel_ids)
    # the sampler's own parameter keys per vessel: the only authoritative check of "does this
    # lineage carry the parameters of its own vessel"
    from synlab.mothers.api import sample_parameters
    from synlab.seeds import derive_named_rngs

    per_vessel: dict[str, Any] = {}
    for vessel in vessels:
        try:
            rng = derive_named_rngs(spec.master_seed, "planning")["sampler"]
            per_vessel[vessel] = sorted(list(sample_parameters(vessel, 1, rng))[0])
        except Exception as exc:  # noqa: BLE001 - recorded, never hidden
            per_vessel[vessel] = f"{type(exc).__name__}: {exc}"
    rows = []
    for lineage in plan.lineages:
        keys = sorted(lineage.params)
        expected = per_vessel.get(lineage.vessel_id)
        rows.append({
            "index": lineage.mother_index,
            "lineage_id": lineage.lineage_id,
            "vessel_id": lineage.vessel_id,
            "pattern_id": lineage.pattern_id,
            "material_id": lineage.material_id,
            "param_keys": keys,
            "vessel_param_keys": expected,
            "params_match_own_vessel": bool(keys) and keys == expected,
        })
    out = {"config": args.config, "vessel_ids": vessels, "lineages": rows,
           "sampler_param_keys_per_vessel": per_vessel,
           "mismatched": [r["lineage_id"] for r in rows if not r["params_match_own_vessel"]]}
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
