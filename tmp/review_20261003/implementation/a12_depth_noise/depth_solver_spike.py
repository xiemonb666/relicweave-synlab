from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import open3d as o3d

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from synlab.observe.render import _project_with_distortion
from synlab.cameras.projection import undistort_normalized

OUT = Path(__file__).resolve().parent
W, H = 96, 72
FX, FY = 150.0, 145.0
CX, CY = (W - 1) / 2.0, (H - 1) / 2.0
BASE, A, B = 500.0, 0.28, -0.16
HALF_X, HALF_Y = 130.0, 105.0
VERTICES = np.array([
    [-HALF_X, -HALF_Y, BASE + A * -HALF_X + B * -HALF_Y],
    [ HALF_X, -HALF_Y, BASE + A *  HALF_X + B * -HALF_Y],
    [ HALF_X,  HALF_Y, BASE + A *  HALF_X + B *  HALF_Y],
    [-HALF_X,  HALF_Y, BASE + A * -HALF_X + B *  HALF_Y],
], dtype=np.float64)
FACES = np.array([[0, 2, 1], [0, 3, 2]], dtype=np.int32)
DISTORTION = np.array([0.12, -0.025, 0.0015, -0.001, 0.0], dtype=np.float64)


def opencv_k() -> np.ndarray:
    return np.array([[FX, 0.0, CX], [0.0, FY, CY], [0.0, 0.0, 1.0]], dtype=np.float64)


def cell_affine(k: np.ndarray, factor: int) -> np.ndarray:
    """Independent center-to-cell-coordinate affine for +0.5 raster samples."""
    out = np.asarray(k, dtype=np.float64).copy()
    out[:2, :] *= factor
    out[0, 2] += factor / 2.0
    out[1, 2] += factor / 2.0
    out[2, 2] = 1.0
    return out


def ray_grid(model: str, dist: np.ndarray | None, factor: int):
    width, height = W * factor, H * factor
    k_hi = cell_affine(opencv_k(), factor)
    gy, gx = np.mgrid[0:height, 0:width]
    u, v = gx.ravel().astype(np.float64) + 0.5, gy.ravel().astype(np.float64) + 0.5
    xd = (u - k_hi[0, 2]) / k_hi[0, 0]
    yd = (v - k_hi[1, 2]) / k_hi[1, 1]
    x, y = undistort_normalized(xd, yd, dist, model)
    dirs = np.column_stack([x, y, np.ones_like(x)])
    z = BASE / (1.0 - A * x - B * y)
    hit = ((z > 0.0) & (np.abs(x * z) <= HALF_X) & (np.abs(y * z) <= HALF_Y))
    return k_hi, dirs, z, hit, width, height


def ray_triangle(dirs: np.ndarray, face: np.ndarray):
    """Double-precision Moller-Trumbore rays from camera origin to one triangle."""
    v0, v1, v2 = VERTICES[face]
    e1, e2 = v1 - v0, v2 - v0
    p = np.cross(dirs, e2)
    det = p @ e1
    ok_det = np.abs(det) > 1e-14
    invdet = np.zeros_like(det)
    invdet[ok_det] = 1.0 / det[ok_det]
    tvec = -v0
    u = (p @ tvec) * invdet
    q = np.cross(tvec, e1)
    v = (dirs @ q) * invdet
    t = float(e2 @ q) * invdet
    hit = ok_det & (u >= -1e-12) & (v >= -1e-12) & (u + v <= 1.0 + 1e-12) & (t > 0.0)
    return t, hit


def stats(values: np.ndarray) -> dict:
    if not values.size:
        return {"n": 0, "mean_abs_mm": None, "p95_abs_mm": None, "max_abs_mm": None}
    a = np.abs(values.astype(np.float64))
    return {"n": int(a.size), "mean_abs_mm": float(np.mean(a)),
            "p95_abs_mm": float(np.percentile(a, 95)), "max_abs_mm": float(np.max(a))}


def one_case(model: str, dist: np.ndarray | None, factor: int) -> dict:
    k_hi, dirs, oracle_z, oracle_hit, width, height = ray_grid(model, dist, factor)
    uv, vert_z = _project_with_distortion(VERTICES, k_hi, dist, model)
    gy, gx = np.mgrid[0:height, 0:width]
    px, py = gx.ravel().astype(np.float64) + 0.5, gy.ravel().astype(np.float64) + 0.5
    screen_invz = np.full(px.shape, np.nan, dtype=np.float64)
    screen_linear_z = np.full(px.shape, np.nan, dtype=np.float64)
    raster_inside = np.zeros(px.shape, dtype=bool)
    for face_id, face in enumerate(FACES):
        p0, p1, p2 = uv[face]
        area = ((p1[0] - p0[0]) * (p2[1] - p0[1])
                - (p2[0] - p0[0]) * (p1[1] - p0[1]))
        w0 = ((p1[0] - px) * (p2[1] - py) - (p2[0] - px) * (p1[1] - py)) / area
        w1 = ((p2[0] - px) * (p0[1] - py) - (p0[0] - px) * (p2[1] - py)) / area
        w2 = 1.0 - w0 - w1
        inside = (w0 >= -1e-9) & (w1 >= -1e-9) & (w2 >= -1e-9)
        first = inside & ~raster_inside
        if not first.any():
            continue
        raster_inside[first] = True
        z = vert_z[face]
        screen_linear_z[first] = (w0[first] * z[0] + w1[first] * z[1] + w2[first] * z[2])
        screen_invz[first] = 1.0 / (w0[first] / z[0] + w1[first] / z[1] + w2[first] / z[2])

    exact_t = np.full(len(dirs), np.nan, dtype=np.float64)
    exact_hit = np.zeros(len(dirs), dtype=bool)
    for face in FACES:
        t, h = ray_triangle(dirs, face)
        use = h & (~exact_hit | (t < exact_t))
        exact_t[use], exact_hit[use] = t[use], True

    mesh = o3d.t.geometry.TriangleMesh(
        o3d.core.Tensor(VERTICES.astype(np.float32)),
        o3d.core.Tensor(FACES.astype(np.int32)),
    )
    ray_scene = o3d.t.geometry.RaycastingScene()
    ray_scene.add_triangles(mesh)
    rays = np.zeros((len(dirs), 6), dtype=np.float32)
    rays[:, 3:] = dirs.astype(np.float32)
    start = time.perf_counter()
    hit_result = ray_scene.cast_rays(o3d.core.Tensor(rays))
    cast_seconds = time.perf_counter() - start
    o3d_t = hit_result["t_hit"].numpy().astype(np.float64)
    o3d_primitive = hit_result["primitive_ids"].numpy()
    o3d_hit = np.isfinite(o3d_t) & (o3d_primitive != 0xFFFFFFFF)
    refined_t = np.full(len(dirs), np.nan, dtype=np.float64)
    refined_hit = np.zeros(len(dirs), dtype=bool)
    for face_id, face in enumerate(FACES):
        use = o3d_hit & (o3d_primitive == face_id)
        if use.any():
            t, h = ray_triangle(dirs[use], face)
            refined_t[use] = t
            refined_hit[use] = h

    # Keep edge/support mismatches separate from interior depth accuracy.
    boundary = np.ones(len(dirs), dtype=bool)
    stats_mask = oracle_hit & exact_hit
    return {
        "camera_model": model,
        "supersample": factor,
        "affine_K_hi": k_hi.tolist(),
        "pixel_center_offset_from_opencv_centers_px": 0.0,
        "analytic_patch_samples": int(oracle_hit.sum()),
        "software_screen_triangle_samples": int(raster_inside.sum()),
        "software_screen_support_fp": int(np.count_nonzero(raster_inside & ~oracle_hit)),
        "software_screen_support_fn": int(np.count_nonzero(oracle_hit & ~raster_inside)),
        "software_linear_z_interior": stats(screen_linear_z[stats_mask] - oracle_z[stats_mask]),
        "software_inverse_z_interior": stats(screen_invz[stats_mask] - oracle_z[stats_mask]),
        "double_ray_triangle_interior": stats(exact_t[stats_mask] - oracle_z[stats_mask]),
        "double_ray_triangle_support_fp": int(np.count_nonzero(exact_hit & ~oracle_hit)),
        "double_ray_triangle_support_fn": int(np.count_nonzero(oracle_hit & ~exact_hit)),
        "open3d_float32_ray_interior": stats(o3d_t[stats_mask] - oracle_z[stats_mask]),
        "open3d_refined_double_ray_triangle_interior": stats(refined_t[stats_mask] - oracle_z[stats_mask]),
        "open3d_support_fp": int(np.count_nonzero(o3d_hit & ~oracle_hit)),
        "open3d_support_fn": int(np.count_nonzero(oracle_hit & ~o3d_hit)),
        "open3d_refine_face_mismatch_on_interior": int(np.count_nonzero(stats_mask & ~refined_hit)),
        "open3d_cast_seconds_2_triangles_bounded_image": cast_seconds,
    }


cases = []
for model, dist in (("PINHOLE", None), ("OPENCV", DISTORTION)):
    for factor in (1, 2):
        cases.append(one_case(model, dist, factor))

report = {
    "scope": "bounded analytic ray-plane/ray-triangle spike; no production edits in this run",
    "reference": {
        "plane": f"z={BASE}+{A}x+({B})y",
        "patch_half_extent_mm": [HALF_X, HALF_Y],
        "image_size": [W, H], "fx": FX, "fy": FY,
        "opencv_principal_point": [CX, CY],
        "distortion": DISTORTION.tolist(),
        "reference_precision": "double; analytic pinhole rays and OpenCV undistort_normalized rays",
    },
    "notes": [
        "The candidate center-to-cell affine is measured independently: scale pixel rows then add factor/2 to each principal point.",
        "The screen-linear and screen-inverse-z alternatives use projected triangle barycentrics; their distorted results are measured rather than assumed exact.",
        "Double ray-triangle is bounded to a two-triangle plane and tests internal depth and silhouette support separately.",
        "Open3D RaycastingScene requires Float32 vertices/rays on this installed 0.19.0 build; exact double refinement is separately measured.",
        "The two-triangle cast timing is not a renderer throughput benchmark.",
    ],
    "cases": cases,
}
(OUT / "depth_solver_spike.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report, indent=2))
