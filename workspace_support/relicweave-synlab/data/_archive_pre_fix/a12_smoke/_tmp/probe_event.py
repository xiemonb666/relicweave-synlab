"""Fast fracture-stage check for a list of mother indices (no store, no observation).

Reports, per lineage: event ok/failed, fragment count, per-fragment watertightness, the
``audit_fracture_result`` verdict and its measurements.

Usage::

    python data/a12_smoke/_tmp/probe_event.py 0 51 2
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from synlab.config import load_generation_spec
from synlab.fracture.api import audit_fracture, fracture_event
from synlab.mothers.api import create_mother
from synlab.pipeline import derive_named_rngs, plan_generation


def main() -> int:
    spec = load_generation_spec("configs/a12/next_experiment.yaml")
    plan = plan_generation(spec)
    indices = [int(x) for x in sys.argv[1:]] or [0]
    rows = []
    for index in indices:
        lineage = next(l for l in plan.lineages if l.mother_index == index)
        rngs = derive_named_rngs(spec.master_seed, lineage.lineage_id)
        started = time.time()
        try:
            mother = create_mother(lineage.vessel_id, lineage.material_id, lineage.params,
                                   rngs["shape"], mother_id=lineage.lineage_id)
            event_id = lineage.event_ids[0] if lineage.event_ids else f"{lineage.lineage_id}_E01"
            result = fracture_event(mother, spec.fracture, rngs["cut"], event_id=event_id)
            audit = audit_fracture(result, mother)
            elapsed = time.time() - started
            row = {
                "lineage_id": lineage.lineage_id, "vessel": lineage.vessel_id,
                "ok": bool(audit.get("ok", audit.get("passed"))), "seconds": round(elapsed, 2),
                "fragments": len(result.fragments),
                "mother_components": len(mother.mesh.split(only_watertight=False)),
                "fragment_watertight": [bool(f.mesh.is_watertight) for f in result.fragments],
                "interfaces": len(result.interfaces),
                "overlap_ratio": audit.get("overlap_ratio"),
                "volume_rel_diff": audit.get("volume_rel_diff"),
                "source_coverage": audit.get("source_coverage"),
                "failures": audit.get("failures"),
                "gap_p95_mm_max": audit.get("gap_p95_mm_max"),
            }
        except Exception as exc:  # noqa: BLE001 - the probe reports the real failure
            row = {"lineage_id": lineage.lineage_id, "vessel": lineage.vessel_id, "ok": False,
                   "seconds": round(time.time() - started, 2),
                   "error": f"{type(exc).__name__}: {exc}"[:600],
                   "code": str(getattr(exc, "code", ""))}
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False, default=str), flush=True)
    Path("data/a12_smoke/_tmp/probe_event_out.json").write_text(
        json.dumps(rows, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    ok = sum(1 for r in rows if r["ok"])
    print(json.dumps({"checked": len(rows), "ok": ok, "failed": len(rows) - ok}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
