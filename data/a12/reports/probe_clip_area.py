"""Measure, per interface chunk, the true 2D common clipped coverage (read-only probe).

For every patch produced by the current pipeline the probe recomputes the plan 30.5 quantity:
project the patch's own A faces and B faces into one local 2D basis and take
``area(union(A) & union(B))``.  It also reports the per-chunk ``union`` areas and whether the
chunks tile the hand-computed 144 mm^2 plane.
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

from synlab.fracture.api import fracture_event  # noqa: E402
from synlab.fracture.spec import FractureSpec  # noqa: E402

from fixtures import box_mother  # noqa: E402


def _basis(triangles: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Orthonormal (origin, e1, e2, n) for a set of near-coplanar triangles."""
    points = triangles.reshape(-1, 3)
    origin = points.mean(axis=0)
    centred = points - origin
    _u, _s, vt = np.linalg.svd(centred, full_matrices=False)
    e1, e2 = vt[0], vt[1]
    n = np.cross(e1, e2)
    return origin, e1, e2, n


def _clip_area(triangles_a: np.ndarray, triangles_b: np.ndarray) -> dict[str, float]:
    origin, e1, e2, _n = _basis(np.concatenate([triangles_a, triangles_b], axis=0))

    def project(triangles: np.ndarray) -> np.ndarray:
        rel = triangles - origin
        return np.stack([rel @ e1, rel @ e2], axis=-1)

    polys_a = shapely.polygons(project(triangles_a))
    polys_b = shapely.polygons(project(triangles_b))
    union_a = shapely.union_all(polys_a)
    union_b = shapely.union_all(polys_b)
    common = shapely.intersection(union_a, union_b)
    return {
        "union_a_mm2": float(shapely.area(union_a)),
        "union_b_mm2": float(shapely.area(union_b)),
        "common_mm2": float(shapely.area(common)),
        "sum_a_mm2": float(np.sum(shapely.area(polys_a))),
        "sum_b_mm2": float(np.sum(shapely.area(polys_b))),
    }


def main() -> int:
    mother = box_mother((12.0, 12.0, 12.0), mother_id="box12")
    spec = FractureSpec(backend="plane_shared_cut", plane_point=np.zeros(3),
                        plane_normal=np.array([1.0, 0.0, 0.0]))
    result = fracture_event(mother, spec, np.random.default_rng(4), event_id="E_plane")
    by_id = {f.fragment_id: f for f in result.fragments}
    rows = []
    for patch in result.interfaces:
        fa = np.asarray(patch.meta["faces_a"], dtype=np.int64)
        fb = np.asarray(patch.meta["faces_b"], dtype=np.int64)
        ta = np.asarray(by_id[patch.fragment_a].mesh.triangles, dtype=np.float64)[fa]
        tb = np.asarray(by_id[patch.fragment_b].mesh.triangles, dtype=np.float64)[fb]
        row = {"id": patch.interface_id, "faces_a": int(fa.size), "faces_b": int(fb.size),
               "pipeline_area_mm2": float(patch.area_mm2),
               "chunk_overlap_mm2": float(patch.meta.get("pair_overlap_area_mm2", 0.0))}
        row.update(_clip_area(ta, tb))
        row["centroid_a"] = np.asarray(ta.reshape(-1, 3).mean(axis=0)).tolist()
        row["centroid_b"] = np.asarray(tb.reshape(-1, 3).mean(axis=0)).tolist()
        rows.append(row)
    out = {
        "patch_rows": rows,
        "sum_common_mm2": float(sum(r["common_mm2"] for r in rows)),
        "sum_union_a_mm2": float(sum(r["union_a_mm2"] for r in rows)),
        "sum_union_b_mm2": float(sum(r["union_b_mm2"] for r in rows)),
        "sum_pipeline_area_mm2": float(sum(r["pipeline_area_mm2"] for r in rows)),
        "hand_computed_mm2": 144.0,
    }
    target = Path(__file__).with_suffix(".json")
    target.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "patch_rows"}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
