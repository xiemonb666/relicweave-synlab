from __future__ import annotations
import json
from pathlib import Path
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from synlab.observe.render import Scene, MaterialSpec, LightSpec, RenderSpec, _rasterise_buffers, _scaled_frame, _project_with_distortion, render_view, BACKEND_SOFTWARE
from synlab.schemas.runtime import ViewFrame
from synlab.cameras.projection import undistort_normalized

OUT = Path(__file__).resolve().parent
W, H = 96, 72
FX, FY = 150.0, 145.0
CX, CY = (W - 1) / 2.0, (H - 1) / 2.0
BASE = 500.0
SLOPE_X, SLOPE_Y = 0.28, -0.16
HALF_X, HALF_Y = 130.0, 105.0

# A bounded, front-facing, two-triangle planar patch. Plane is z=BASE+a*x+b*y.
vertices = np.array([
    [-HALF_X, -HALF_Y, BASE + SLOPE_X*(-HALF_X) + SLOPE_Y*(-HALF_Y)],
    [ HALF_X, -HALF_Y, BASE + SLOPE_X*( HALF_X) + SLOPE_Y*(-HALF_Y)],
    [ HALF_X,  HALF_Y, BASE + SLOPE_X*( HALF_X) + SLOPE_Y*( HALF_Y)],
    [-HALF_X,  HALF_Y, BASE + SLOPE_X*(-HALF_X) + SLOPE_Y*( HALF_Y)],
], dtype=np.float64)
scene = Scene(
    name='analytic_slanted_plane', vertices=vertices,
    faces=np.array([[0, 2, 1], [0, 3, 2]], dtype=np.int32),
    surface_tag=np.array([1, 1], dtype=np.int16),
    material=MaterialSpec(np.full((2, 3), 0.5, dtype=np.float32),
                          np.full(2, 0.5, dtype=np.float32)),
)
light = LightSpec(direction=np.array([0.0, 0.0, -1.0]),
                  color=np.ones(3), ambient=np.full(3, 0.2))


def make_frame(model: str, dist: np.ndarray | None) -> ViewFrame:
    K = np.array([[FX, 0.0, CX], [0.0, FY, CY], [0.0, 0.0, 1.0]], dtype=np.float64)
    return ViewFrame(view_id='depth_spike', K=K, T_WC=np.eye(4), image_size=(W, H),
                     profile_id='depth_spike', tier='GLOBAL', u_position_mm=0.0,
                     working_distance_mm=BASE, focus_setting='FIXED', source_kind='SENSOR_SIM',
                     camera_model=model, dist=dist)


def oracle_for_raster_grid(frame_hi: ViewFrame, width: int, height: int):
    # The current rasterizer tests at grid index + 0.5. Use that same UV sample first,
    # so this comparison isolates its depth interpolation from the center-affine issue.
    gy, gx = np.mgrid[0:height, 0:width]
    u = gx.ravel().astype(np.float64) + 0.5
    v = gy.ravel().astype(np.float64) + 0.5
    K = np.asarray(frame_hi.K, dtype=np.float64)
    xd = (u - K[0, 2]) / K[0, 0]
    yd = (v - K[1, 2]) / K[1, 1]
    x, y = undistort_normalized(xd, yd, frame_hi.dist,
                                str(frame_hi.camera_model or 'OPENCV'))
    denom = 1.0 - SLOPE_X*x - SLOPE_Y*y
    z = BASE / denom
    px, py = x*z, y*z
    in_patch = ((denom > 0.0) & (np.abs(px) <= HALF_X) & (np.abs(py) <= HALF_Y))
    return z.reshape(height, width), in_patch.reshape(height, width)


def inverse_z_interpolation(frame_hi: ViewFrame, width: int, height: int):
    """Perspective-correct triangle depth for a pinhole projection at current samples."""
    uv, z = _project_with_distortion(vertices, frame_hi.K, frame_hi.dist,
                                     str(frame_hi.camera_model or 'PINHOLE'))
    gy, gx = np.mgrid[0:height, 0:width]
    px = gx.astype(np.float64) + 0.5
    py = gy.astype(np.float64) + 0.5
    predicted = np.full((height, width), np.nan, dtype=np.float64)
    for face in scene.faces:
        p0, p1, p2 = uv[face]
        z0, z1, z2 = z[face]
        area = ((p1[0]-p0[0])*(p2[1]-p0[1])
                - (p2[0]-p0[0])*(p1[1]-p0[1]))
        w0 = ((p1[0]-px)*(p2[1]-py) - (p2[0]-px)*(p1[1]-py)) / area
        w1 = ((p2[0]-px)*(p0[1]-py) - (p0[0]-px)*(p2[1]-py)) / area
        w2 = 1.0 - w0 - w1
        inside = (w0 >= -1e-9) & (w1 >= -1e-9) & (w2 >= -1e-9)
        inv_z = w0/z0 + w1/z1 + w2/z2
        valid = inside & (inv_z > 0.0) & ~np.isfinite(predicted)
        predicted[valid] = 1.0 / inv_z[valid]
    return predicted


def case(model: str, dist: np.ndarray | None, factor: int):
    frame = make_frame(model, dist)
    frame_hi = _scaled_frame(frame, factor)
    hi_w, hi_h = W*factor, H*factor
    spec = RenderSpec(supersample=factor, near_mm=100.0, far_mm=1000.0,
                      max_pixels=hi_w*hi_h + 10)
    buffers = _rasterise_buffers(scene, frame_hi, hi_w, hi_h, light, spec)
    actual_hi = buffers['depth']
    truth_hi, patch_hi = oracle_for_raster_grid(frame_hi, hi_w, hi_h)
    actual_hit = np.isfinite(actual_hi)
    common = actual_hit & patch_hi
    error = np.abs(actual_hi[common] - truth_hi[common])
    invz_error = None
    if model == 'PINHOLE':
        invz = inverse_z_interpolation(frame_hi, hi_w, hi_h)
        invz_common = np.isfinite(invz) & patch_hi
        invz_vals = np.abs(invz[invz_common] - truth_hi[invz_common])
        invz_error = {'n': int(invz_vals.size),
                      'mean_abs_mm': float(np.mean(invz_vals)) if invz_vals.size else None,
                      'p95_abs_mm': float(np.percentile(invz_vals, 95)) if invz_vals.size else None,
                      'max_abs_mm': float(np.max(invz_vals)) if invz_vals.size else None}
    expected_coverage = patch_hi
    fp = int(np.count_nonzero(actual_hit & ~expected_coverage))
    fn = int(np.count_nonzero(expected_coverage & ~actual_hit))

    rendered = render_view(scene, frame, light=light, spec=spec, backend=BACKEND_SOFTWARE)
    out_depth = np.asarray(rendered.depth_z, dtype=np.float64)
    # The renderer's documented supersample depth reducer is min, but it also requires
    # every subpixel to hit. Compare against the min of exact ray-plane supersample depths.
    truth_blocks = truth_hi.reshape(H, factor, W, factor)
    patch_blocks = patch_hi.reshape(H, factor, W, factor)
    actual_blocks = actual_hit.reshape(H, factor, W, factor)
    truth_complete = patch_blocks.all(axis=(1, 3))
    actual_complete = actual_blocks.all(axis=(1, 3))
    expected_out = truth_blocks.min(axis=(1, 3))
    compare_out = np.isfinite(out_depth) & truth_complete
    out_error = np.abs(out_depth[compare_out] - expected_out[compare_out])

    # The ViewFrame contract is OpenCV pixel centers: output (x,y) represents integer
    # coordinates. The cell-based raster samples x_hi+0.5 and currently scales K by f.
    xx = np.arange(hi_w, dtype=np.float64) + 0.5
    current_u_in_output_coords = xx / factor
    j = np.arange(hi_w) % factor
    i = np.arange(hi_w) // factor
    intended_subpixel_u = i + (j + 0.5) / factor - 0.5
    pixel_offset = current_u_in_output_coords - intended_subpixel_u

    def stats(vals):
        if vals.size == 0:
            return {'n': 0, 'mean_abs_mm': None, 'p95_abs_mm': None, 'max_abs_mm': None}
        return {'n': int(vals.size), 'mean_abs_mm': float(np.mean(vals)),
                'p95_abs_mm': float(np.percentile(vals, 95)),
                'max_abs_mm': float(np.max(vals))}
    return {
        'camera_model': model,
        'distortion': None if dist is None else dist.tolist(),
        'supersample': factor,
        'raster_sample_vs_ray_plane': stats(error),
        'pinhole_inverse_z_interpolation_vs_ray_plane': invz_error,
        'output_depth_vs_exact_supersample_min': stats(out_error),
        'raster_hit_samples': int(actual_hit.sum()),
        'analytic_patch_samples': int(expected_coverage.sum()),
        'common_interior_samples': int(common.sum()),
        'raster_false_positive_samples_vs_patch': fp,
        'raster_false_negative_samples_vs_patch': fn,
        'output_all_hit_pixels': int(actual_complete.sum()),
        'output_pixels_with_exact_all_subsamples_on_patch': int(truth_complete.sum()),
        'output_comparable_pixels': int(compare_out.sum()),
        'opencv_center_affine': {
            'current_effective_sample_u_formula': '(x_hi + 0.5) / factor',
            'expected_subsample_u_formula': 'x + (j + 0.5) / factor - 0.5',
            'offset_px_min': float(pixel_offset.min()),
            'offset_px_max': float(pixel_offset.max()),
            'offset_px_mean': float(pixel_offset.mean()),
            'offset_in_camera_normalized_x_mean': float(pixel_offset.mean()/FX),
            'current_scaled_cx': float(frame_hi.K[0, 2]),
            'center_to_center_affine_cx': float((factor*frame.K[0, 2]) + (factor-1)/2),
            'cell_sample_affine_cx': float(factor*frame.K[0, 2] + factor/2),
        },
    }

cases = []
for model, dist in [
    ('PINHOLE', None),
    ('OPENCV', np.array([0.12, -0.025, 0.0015, -0.001, 0.0], dtype=np.float64)),
]:
    for factor in (1, 2):
        cases.append(case(model, dist, factor))

report = {
    'generated_at_local': '2026-10-03',
    'scope': 'read-only software rasterizer measurement; no production files changed',
    'plane': {'equation': 'z = base + a*x + b*y', 'base_mm': BASE,
              'a': SLOPE_X, 'b': SLOPE_Y, 'half_extent_mm': [HALF_X, HALF_Y],
              'analytic_ray_z': 'base / (1 - a*x_ray - b*y_ray)',
              'normal': [-SLOPE_X, -SLOPE_Y, 1.0]},
    'camera': {'image_size': [W, H], 'fx': FX, 'fy': FY,
               'principal_point_opencv': [CX, CY]},
    'notes': [
        'Depth comparison uses the current raster sample locations first, isolating per-triangle depth interpolation.',
        'Expected support is computed from the undistorted camera ray intersected with the bounded analytic plane.',
        'OpenCV center offset is a separate measurement; projected distorted triangle edges are not claimed exact.',
        'Supersampled output is compared to the min of exact per-subsample intersections, respecting current all-hit output rule.',
    ],
    'cases': cases,
}
(OUT/'render_depth_spike.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps(report, indent=2))
