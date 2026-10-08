"""Probe the real fracture chain for one mother and print the full audit (diagnostic)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from synlab.config import load_generation_spec  # noqa: E402
from synlab.mothers.api import audit_mother, create_mother, default_params  # noqa: E402
from synlab.seeds import derive_named_rngs  # noqa: E402


def main() -> None:
    vessel = sys.argv[1] if len(sys.argv) > 1 else "V01"
    material = sys.argv[2] if len(sys.argv) > 2 else "M01"
    spec = load_generation_spec("configs/a12/closed_loop.yaml")
    rngs = derive_named_rngs(spec.master_seed, f"probe_{vessel}")
    mother = create_mother(vessel, material, default_params(vessel), rngs["shape"],
                           mother_id=f"probe_{vessel}")
    print("mother audit ok:", audit_mother(mother).get("ok"))
    from synlab.fracture.api import audit_fracture, fracture_event

    fracture = fracture_event(mother, spec.fracture, rngs["cut"], event_id="probe_E01")
    report = audit_fracture(fracture, mother)
    keep = {k: v for k, v in report.items()
            if not isinstance(v, (list, dict)) or k in ("failures", "checks")}
    print(json.dumps(keep, ensure_ascii=False, indent=1, default=str)[:6000])
    print("fragments:", len(fracture.fragments))
    for frag in fracture.fragments:
        print("  ", frag.fragment_id, "vol", round(float(frag.volume_mm3), 2),
              "area", round(float(frag.area_mm2), 2), "tiny", bool(frag.is_tiny),
              "faces", len(frag.mesh.faces))
    from synlab.truth.api import finalize_clean_truth

    clean = finalize_clean_truth(mother, fracture)
    qa = dict(clean.qa or {})
    print("clean qa:", json.dumps({k: v for k, v in qa.items()
                                   if k in ("pass", "failures", "r2_pairs", "r1_pairs",
                                            "tiny_pairs", "unknown_pairs",
                                            "r2_area_mm2_total", "ambiguity_area_ratio_max",
                                            "ambiguity_tolerance")},
                                  ensure_ascii=False, indent=1))
    evidence = qa.get("patch_evidence") or {}
    reasons: dict[str, int] = {}
    for row in evidence.values():
        reasons[str(row.get("reason", "?"))] = reasons.get(str(row.get("reason", "?")), 0) + 1
    print("patch reasons:", json.dumps(reasons, ensure_ascii=False))
    for key in sorted(evidence)[:6]:
        print("  patch", key, json.dumps(evidence[key], ensure_ascii=False, default=str)[:320])


if __name__ == "__main__":
    main()
