"""Locate where the 12 mm box loses 23 mm^2 of the analytic 144 mm^2 shared plane.

The probe answers three questions with measurements only:

1. how much cut-surface area each fragment carries per cutter *sheet*;
2. how much of that area the event's face pairing (``patch.meta['faces_a']``) actually covers;
3. whether the chunk's source cutter triangles, expanded back to *all* faces of each fragment
   on those triangles, recover the missing coverage (the plan 30.5 "collect both sides' output
   triangles per source triangle" reading).
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


def _plane_project(triangles: np.ndarray) -> np.ndarray:
    """Project near-planar triangles (all with |normal_x| ~ 1) onto the YZ plane."""
    return np.stack([triangles[..., 1], triangles[..., 2]], axis=-1)


def _union_area(triangles: np.ndarray) -> float:
    if triangles.shape[0] == 0:
        return 0.0
    return float(shapely.area(shapely.union_all(shapely.polygons(_plane_project(triangles)))))


def main() -> int:
    mother = box_mother((12.0, 12.0, 12.0), mother_id="box12")
    spec = FractureSpec(backend="plane_shared_cut", plane_point=np.zeros(3),
                        plane_normal=np.array([1.0, 0.0, 0.0]))
    result = fracture_event(mother, spec, np.random.default_rng(4), event_id="E_plane")
    by_id = {f.fragment_id: f for f in result.fragments}
    cutter = None
    for key, value in result.meta.items():
        if "cutter" in key:
            cutter = key
    out: dict[str, object] = {"cutter_meta_keys": [k for k in result.meta], "sides": {}}

    sheets: dict[str, dict[str, object]] = {}
    for fragment in result.fragments:
        mesh = fragment.mesh
        origin = np.asarray(fragment.face_origin_kind)
        cut = origin == 1
        tri = np.asarray(mesh.triangles, dtype=np.float64)[cut]
        ids = np.nonzero(cut)[0]
        centres = np.asarray(mesh.triangles_center, dtype=np.float64)[cut]
        entry: dict[str, object] = {"cut_faces": int(cut.sum()), "cut_area_mm2": float(
            np.sum(np.asarray(mesh.area_faces)[cut]))}
        # split the cut faces by their x sheet (a plane cut produces one sheet per cutter face
        # that touches the mother)
        for label, mask in (("x=0", np.abs(centres[:, 0]) < 1e-6),
                            ("x=-6", np.abs(centres[:, 0] + 6.0) < 1e-6),
                            ("x=+6", np.abs(centres[:, 0] - 6.0) < 1e-6)):
            if not bool(np.any(mask)):
                continue
            entry[label] = {"faces": int(mask.sum()),
                            "sum_area_mm2": float(np.sum(np.asarray(mesh.area_faces)[cut][mask])),
                            "union_area_mm2": _union_area(tri[mask])}
        sheets[fragment.fragment_id] = entry
        ids_by_sheet = {label: ids[np.abs(centres[:, 0] - off) < 1e-6]
                        for label, off in (("x=0", 0.0), ("x=-6", -6.0), ("x=+6", 6.0))}
        entry["_ids"] = ids_by_sheet
    out["sides"] = sheets

    # true common coverage of the x = 0 sheet, both sides, all faces
    a = by_id["E_plane-m"]
    b = by_id["E_plane-p"]
    tri_a = np.asarray(a.mesh.triangles, dtype=np.float64)[sheets[a.fragment_id]["_ids"]["x=0"]]
    tri_b = np.asarray(b.mesh.triangles, dtype=np.float64)[sheets[b.fragment_id]["_ids"]["x=0"]]
    ua = shapely.union_all(shapely.polygons(_plane_project(tri_a)))
    ub = shapely.union_all(shapely.polygons(_plane_project(tri_b)))
    out["x0_full_common_mm2"] = float(shapely.area(shapely.intersection(ua, ub)))
    out["x0_full_union_a_mm2"] = float(shapely.area(ua))
    out["x0_full_union_b_mm2"] = float(shapely.area(ub))

    # what the pairing covered per chunk, and what each chunk's *source triangles* would give
    chunks = []
    paired_area = 0.0
    for patch in result.interfaces:
        fa = np.asarray(patch.meta["faces_a"], dtype=np.int64)
        fb = np.asarray(patch.meta["faces_b"], dtype=np.int64)
        ta = np.asarray(a.mesh.triangles, dtype=np.float64)[fa]
        tb = np.asarray(b.mesh.triangles, dtype=np.float64)[fb]
        on_plane = float(np.max(np.abs(np.concatenate([ta, tb]).reshape(-1, 3)[:, 0])))
        row = {"id": patch.interface_id, "faces_a": int(fa.size), "faces_b": int(fb.size),
               "max_abs_x": on_plane,
               "paired_common_mm2": _union_area(ta) if on_plane < 1e-6 else None}
        if on_plane < 1e-6:
            paired_area += float(shapely.area(shapely.intersection(
                shapely.union_all(shapely.polygons(_plane_project(ta))),
                shapely.union_all(shapely.polygons(_plane_project(tb))))))
        chunks.append(row)
    out["chunks"] = chunks
    out["paired_x0_area_mm2"] = paired_area

    target = Path(__file__).with_suffix(".json")
    target.write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "chunks"}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
