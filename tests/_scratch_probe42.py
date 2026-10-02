"""Scratch probe 42: which R2 check rejects a genuine shared fracture surface?"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from tests._scratch_probe41 import half_box, make_fragment, shared_plane_patch  # noqa: E402


def main() -> None:
    from tests.a12.fracture.fixtures import box_mother
    from synlab.truth import api as T

    mother = box_mother((12.0, 12.0, 12.0), mother_id="box12")
    left = half_box(1.0)
    right = half_box(-1.0)
    lf = np.where(np.abs(np.asarray(left.face_normals)[:, 0] + 1.0) < 1e-9)[0]
    rf = np.where(np.abs(np.asarray(right.face_normals)[:, 0] - 1.0) < 1e-9)[0]
    print("left interface faces", lf.tolist(), "right", rf.tolist(), flush=True)
    fa = make_fragment("A", left, side=-1, interface_faces=lf)
    fb = make_fragment("B", right, side=1, interface_faces=rf)
    patch = shared_plane_patch(fa, fb, area=144.0, ambiguity=0.0)
    print("new_first", T._new_fracture_fraction(fa, patch.meta.get("faces_a")),
          "new_second", T._new_fracture_fraction(fb, patch.meta.get("faces_b")), flush=True)
    inside = T._material_inside_fraction(patch.sample_points_a, patch.normals_a, mother)
    print("material_inside_fraction", inside, flush=True)
    print("mother contains sample[0]?", bool(mother.mesh.contains(patch.sample_points_a[:1])),
          flush=True)
    row = T._classify_patch(patch, ("A", "B"), {"A": fa, "B": fb}, mother,
                            0.1, 1e-3, gap_p95_mm=0.02, normal_p95_deg=2.0,
                            ambiguity_max=0.02, material_probe_mm=0.05)
    print("evidence", {k: row[k] for k in ("kind", "valid", "loss_mask", "reason",
                                           "new_fracture_fraction_first",
                                           "new_fracture_fraction_second",
                                           "material_inside_fraction")}, flush=True)
    print("thresholds R2_AREA_ABS", T.R2_AREA_ABS_MM2, "R2_AREA_REL", T.R2_AREA_REL,
          "AMBIG", T.AMBIGUITY_AREA_RATIO_MAX, "MATERIAL_INSIDE_MIN", T.MATERIAL_INSIDE_MIN,
          flush=True)


if __name__ == "__main__":
    main()
