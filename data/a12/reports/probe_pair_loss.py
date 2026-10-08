"""Localise where ``_pair_common_clip_area`` loses area on the 12 mm box (read-only probe)."""

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
from synlab.fracture import fragment as frag  # noqa: E402
from synlab.fracture.api import fracture_event  # noqa: E402
from synlab.fracture.spec import FractureSpec  # noqa: E402

from fixtures import box_mother  # noqa: E402

CAPTURED: list[dict] = []
_ORIGINAL = frag.build_interface


def _wrapped(**kwargs):
    patch, rows = _ORIGINAL(**kwargs)
    if not CAPTURED:
        CAPTURED.append({"cutter": kwargs["cutter_mesh"]})
    return patch, rows


def main() -> int:
    frag.build_interface = _wrapped
    event_mod.build_interface = _wrapped
    try:
        mother = box_mother((12.0, 12.0, 12.0), mother_id="box12")
        spec = FractureSpec(backend="plane_shared_cut", plane_point=np.zeros(3),
                            plane_normal=np.array([1.0, 0.0, 0.0]))
        result = fracture_event(mother, spec, np.random.default_rng(4), event_id="E_plane")
    finally:
        frag.build_interface = _ORIGINAL
        event_mod.build_interface = _ORIGINAL
    cutter = CAPTURED[0]["cutter"]
    a, b = result.fragments[0], result.fragments[1]

    from scipy.spatial import cKDTree

    faces_a, source_a, centres_a, radius_a = frag._cut_face_table(a, cutter)
    faces_b, source_b, centres_b, radius_b = frag._cut_face_table(b, cutter)
    tree_a, tree_b = cKDTree(centres_a), cKDTree(centres_b)
    tri_a = np.asarray(a.mesh.triangles, dtype=np.float64)
    tri_b = np.asarray(b.mesh.triangles, dtype=np.float64)
    shared = sorted({int(s) for s in source_a} & {int(s) for s in source_b})
    rows = []
    region_total = cover_a_total = cover_b_total = common_total = 0.0
    empty_a = empty_b = 0
    for source in shared:
        frame = frag._cutter_frame(cutter, source)
        triangle = np.asarray(cutter.triangles[int(source)], dtype=np.float64)
        centre = triangle.mean(axis=0)
        span = float(np.max(np.linalg.norm(triangle - centre, axis=1)))
        region = shapely.polygons(frag._project(triangle[None, :, :], frame)[0])
        near_a = tree_a.query_ball_point(centre, span + radius_a)
        near_b = tree_b.query_ball_point(centre, span + radius_b)
        ua = frag._union_2d(frag._project(tri_a[np.asarray(sorted(near_a), np.int64)], frame)) \
            if near_a else None
        ub = frag._union_2d(frag._project(tri_b[np.asarray(sorted(near_b), np.int64)], frame)) \
            if near_b else None
        cover_a = region if ua is None else shapely.intersection(ua, region)
        cover_b = region if ub is None else shapely.intersection(ub, region)
        if cover_a.is_empty:
            empty_a += 1
        if cover_b.is_empty:
            empty_b += 1
        area_region = float(shapely.area(region))
        area_a = float(shapely.area(cover_a))
        area_b = float(shapely.area(cover_b))
        piece = shapely.intersection(cover_a, cover_b)
        area_common = 0.0 if piece.is_empty else float(shapely.area(
            shapely.set_precision(piece, frag.CLIP_SNAP_TOL_MM)))
        region_total += area_region
        cover_a_total += area_a
        cover_b_total += area_b
        common_total += area_common
        if area_common < 0.5 * area_region:
            rows.append({"source": int(source), "region": area_region, "cover_a": area_a,
                         "cover_b": area_b, "common": area_common,
                         "near_a": len(near_a), "near_b": len(near_b)})
    out = {
        "shared_sources": len(shared),
        "region_total_mm2": region_total,
        "cover_a_total_mm2": cover_a_total,
        "cover_b_total_mm2": cover_b_total,
        "common_total_mm2": common_total,
        "empty_cover_a": empty_a, "empty_cover_b": empty_b,
        "low_common_sources": len(rows), "low_common_area_mm2": float(sum(
            r["region"] - r["common"] for r in rows)),
        "worst": sorted(rows, key=lambda r: r["common"] - r["region"])[:8],
    }
    target = Path(__file__).with_suffix(".json")
    target.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
