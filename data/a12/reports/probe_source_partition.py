"""Validate the plan-30.5 per-source-triangle partition on the 12 mm box.

Assigns every cut face of both fragments to the cutter triangle nearest its centroid, then
computes ``area(union(A_t) & union(B_t))`` in that triangle's own local 2D basis.  Reports the
sum against the analytic 144 mm^2 and how much area falls on source triangles that only one side
covers (which must not become a fake interface).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import shapely

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tests" / "a12" / "fracture"))
sys.path.insert(0, str(REPO_ROOT / "tests" / "a12"))

from synlab.fracture import event as event_mod  # noqa: E402
from synlab.fracture import fragment as fragment_mod  # noqa: E402
from synlab.fracture.api import fracture_event  # noqa: E402
from synlab.fracture.spec import FractureSpec  # noqa: E402

from fixtures import box_mother  # noqa: E402

CAPTURED: list[dict] = []
_ORIGINAL = fragment_mod.build_interface


def _wrapped(**kwargs):
    patch, rows = _ORIGINAL(**kwargs)
    CAPTURED.append({"cutter_triangles": np.asarray(kwargs["cutter_mesh"].triangles,
                                                    dtype=np.float64),
                     "cutter_normals": np.asarray(kwargs["cutter_mesh"].face_normals,
                                                  dtype=np.float64)})
    return patch, rows


def main() -> int:
    fragment_mod.build_interface = _wrapped
    event_mod.build_interface = _wrapped
    try:
        mother = box_mother((12.0, 12.0, 12.0), mother_id="box12")
        spec = FractureSpec(backend="plane_shared_cut", plane_point=np.zeros(3),
                            plane_normal=np.array([1.0, 0.0, 0.0]))
        result = fracture_event(mother, spec, np.random.default_rng(4), event_id="E_plane")
    finally:
        fragment_mod.build_interface = _ORIGINAL
        event_mod.build_interface = _ORIGINAL

    cut_tri = CAPTURED[0]["cutter_triangles"]
    cut_nrm = CAPTURED[0]["cutter_normals"]
    per_side: dict[str, dict[int, np.ndarray]] = {}
    for fragment in result.fragments:
        origin = np.asarray(fragment.face_origin_kind)
        cut = np.nonzero(origin == 1)[0]
        mesh = fragment.mesh
        triangles = np.asarray(mesh.triangles, dtype=np.float64)[cut]
        centres = np.asarray(mesh.triangles_center, dtype=np.float64)[cut]
        # nearest cutter triangle per face centroid (KD-tree over triangle centres is enough for
        # a plane cutter; the production code uses nearest.on_surface)
        from scipy.spatial import cKDTree
        _d, nearest = cKDTree(np.asarray(
            [np.asarray(t).mean(axis=0) for t in cut_tri], dtype=np.float64)).query(centres, k=1)
        # refine with a real nearest-surface query
        _p, _dist, tid = fragment.mesh.nearest if False else (None, None, None)
        tree = cKDTree(np.asarray([np.asarray(t).mean(axis=0) for t in cut_tri], dtype=np.float64))
        groups: dict[int, list[int]] = {}
        for row, tri in enumerate(nearest):
            groups.setdefault(int(tri), []).append(row)
        per_side[fragment.fragment_id] = {
            int(t): np.asarray([triangles[r] for r in rows], dtype=np.float64)
            for t, rows in groups.items()}
        del tree, _d

    shared = sorted(set(per_side[result.fragments[0].fragment_id])
                    & set(per_side[result.fragments[1].fragment_id]))
    only_a = sorted(set(per_side[result.fragments[0].fragment_id]) - set(shared))
    only_b = sorted(set(per_side[result.fragments[1].fragment_id]) - set(shared))
    total = 0.0
    details = []
    key_a = per_side[result.fragments[0].fragment_id]
    key_b = per_side[result.fragments[1].fragment_id]
    for t in shared:
        tri = cut_tri[t]
        normal = cut_nrm[t]
        e1 = tri[1] - tri[0]
        e1 = e1 / max(float(np.linalg.norm(e1)), 1e-12)
        e2 = np.cross(normal, e1)
        origin = tri[0]

        def project(block: np.ndarray) -> np.ndarray:
            rel = block - origin
            return np.stack([rel @ e1, rel @ e2], axis=-1)

        ua = shapely.union_all(shapely.polygons(project(key_a[t])))
        ub = shapely.union_all(shapely.polygons(project(key_b[t])))
        common = shapely.intersection(ua, ub)
        area = float(shapely.area(common))
        total += area
        if area > 0:
            details.append({"source": int(t), "area_mm2": area,
                            "a_only": float(shapely.area(shapely.difference(ua, ub))),
                            "b_only": float(shapely.area(shapely.difference(ub, ua)))})
    out = {
        "shared_sources": len(shared),
        "one_sided_sources_a": len(only_a),
        "one_sided_sources_b": len(only_b),
        "sum_common_mm2": total,
        "hand_computed_mm2": 144.0,
        "nonzero_sources": len(details),
        "sample_details": details[:6],
    }
    target = Path(__file__).with_suffix(".json")
    target.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "sample_details"}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
