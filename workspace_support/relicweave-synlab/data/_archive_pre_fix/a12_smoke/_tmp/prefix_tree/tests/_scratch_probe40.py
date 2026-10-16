"""Scratch probe 40: does the current synlab.truth work end to end on an analytic fixture?"""
from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.a12.fracture.fixtures import box_mother  # noqa: E402


def main() -> None:
    import numpy as np

    t0 = time.perf_counter()
    from synlab.fracture.api import audit_fracture, fracture_event
    from synlab.fracture.spec import FractureSpec
    from synlab.truth.api import build_labels, finalize_clean_truth

    print("imports", round(time.perf_counter() - t0, 2), flush=True)
    mother = box_mother((12.0, 12.0, 12.0), mother_id="box12")
    spec = FractureSpec(backend="plane_shared_cut", plane_point=np.zeros(3),
                        plane_normal=np.array([1.0, 0.0, 0.0]))
    t0 = time.perf_counter()
    result = fracture_event(mother, spec, np.random.default_rng(4), event_id="E1")
    print("fracture", round(time.perf_counter() - t0, 2), "frags", len(result.fragments),
          "interfaces", len(result.interfaces), flush=True)
    audit = audit_fracture(result, mother)
    print("audit ok?", audit.get("ok"), {k: audit.get(k) for k in
                                         ("volume_rel_diff", "overlap_ratio", "gap_p95_mm_max",
                                          "normal_angle_p95_deg_max", "source_coverage",
                                          "ambiguous_area_ratio_max")}, flush=True)
    t0 = time.perf_counter()
    clean = finalize_clean_truth(mother, result)
    print("clean truth", round(time.perf_counter() - t0, 2), "version", clean.version,
          "correspondence", len(clean.correspondence), flush=True)
    kinds: dict[str, int] = {}
    for (a, b), edge in clean.relations.items():
        if a < b:
            kinds[edge.kind] = kinds.get(edge.kind, 0) + 1
    print("relation kinds", kinds, flush=True)
    print("clean qa keys", sorted(clean.qa)[:14], flush=True)
    print("r2 neighbours of first fragment",
          clean.r2_neighbours(result.fragments[0].fragment_id), flush=True)
    del build_labels


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
