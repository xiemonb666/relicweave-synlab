"""Probe the 12 mm box plane cut and dump the raw interface numbers (read-only)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tests" / "a12" / "fracture"))
sys.path.insert(0, str(REPO_ROOT / "tests" / "a12"))

from synlab.fracture.api import audit_fracture, fracture_event  # noqa: E402
from synlab.fracture.spec import FractureSpec  # noqa: E402

from fixtures import box_mother  # noqa: E402


def main() -> int:
    mother = box_mother((12.0, 12.0, 12.0), mother_id="box12")
    spec = FractureSpec(backend="plane_shared_cut", plane_point=np.zeros(3),
                        plane_normal=np.array([1.0, 0.0, 0.0]))
    result = fracture_event(mother, spec, np.random.default_rng(4), event_id="E_plane")
    audit = audit_fracture(result, mother)
    out = {
        "fragments": [{"id": f.fragment_id, "volume": f.volume_mm3, "area": f.area_mm2,
                       "side": int(f.face_side[0]),
                       "cut_area": float(np.sum(np.asarray(f.mesh.area_faces)[
                           np.asarray(f.face_origin_kind) == 1]))}
                      for f in result.fragments],
        "interface_count": len(result.interfaces),
        "total_area": float(sum(p.area_mm2 for p in result.interfaces)),
        "audit": {k: v for k, v in audit.items() if k != "failures"},
        "audit_failures": audit["failures"],
        "event_meta": {k: v for k, v in result.meta.items()
                       if k in ("unmatched_interface_faces", "unmatched_interface_area_mm2",
                                "matched_interface_overlap_area_mm2",
                                "unmatched_interface_area_ratio")},
        "patches": [{
            "id": p.interface_id,
            "a": p.fragment_a, "b": p.fragment_b,
            "area": p.area_mm2,
            "area_a": p.meta.get("area_a_mm2"), "area_b": p.meta.get("area_b_mm2"),
            "area_rel_error": p.meta.get("area_rel_error"),
            "build_interface_area_mm2": p.meta.get("build_interface_area_mm2"),
            "pair_common_clip_area_mm2": p.meta.get("pair_common_clip_area_mm2"),
            "pair_common_clip_sources": p.meta.get("pair_common_clip_sources"),
            "common_clip_area_mm2": p.meta.get("common_clip_area_mm2"),
            "only_a_area_mm2": p.meta.get("only_a_area_mm2"),
            "only_b_area_mm2": p.meta.get("only_b_area_mm2"),
            "one_sided_source_triangles": len(p.meta.get("one_sided_source_triangles", [])),
            "snapped_area_mm2": p.meta.get("snapped_area_mm2"),
            "barycentric_clamp_total": p.meta.get("barycentric_clamp_total"),
            "ambiguous_reasons": p.meta.get("ambiguous_reasons"),
            "source_triangle_count": len(p.meta.get("source_triangles", [])),
            "pair_overlap_area_mm2": p.meta.get("pair_overlap_area_mm2"),
            "faces_a": len(p.meta.get("faces_a", [])),
            "faces_b": len(p.meta.get("faces_b", [])),
            "samples": int(p.sample_points_a.shape[0]),
            "ambiguous_samples": p.meta.get("ambiguous_samples"),
            "ambiguity_area_ratio": p.ambiguity_area_ratio,
            "ambiguous_area_mm2": p.ambiguous_area_mm2,
            "bary_min_a": p.meta.get("bary_min_a"), "bary_min_b": p.meta.get("bary_min_b"),
            "gap_p95": p.gap_p95_mm, "gap_max": p.meta.get("gap_max_mm"),
            "normal_p95": p.normal_angle_p95_deg,
            "source_triangles": p.meta.get("source_triangles"),
        } for p in result.interfaces],
    }
    target = Path(__file__).with_suffix(".json")
    target.write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
