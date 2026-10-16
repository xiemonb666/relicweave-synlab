from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

import cv2
from PIL import Image, ImageDraw, ImageFont

from synlab.observe.imaging import ImagingSpec, apply_imaging_chain
from synlab.observe.render import (
    BACKEND_SOFTWARE,
    LightSpec,
    MaterialSpec,
    RenderSpec,
    Scene,
    _scaled_frame,
    render_view,
)
from synlab.schemas.runtime import ViewFrame


OUT = Path(__file__).resolve().parent
MESH_PATH = ROOT / "data/a12_trainable/negatives/meshes/mesh_LIN0100_V17_M02_PAT08_E01-p.npz"
WIDTH, HEIGHT, FACTOR = 320, 240, 2
CAMERA_DISTANCE_MM = 620.0
FOCAL_PX = 460.0
ERROR_FULL_SCALE_MM = 40e-6
MM_TO_UM = 1000.0
MM_TO_NM = 1_000_000.0


def look_at_frame(center: np.ndarray, camera_direction: np.ndarray) -> ViewFrame:
    d = np.asarray(camera_direction, dtype=np.float64)
    d /= np.linalg.norm(d)
    position = np.asarray(center, dtype=np.float64) + d * CAMERA_DISTANCE_MM
    forward = (center - position) / np.linalg.norm(center - position)
    up = np.array([0.0, 1.0, 0.0], dtype=np.float64)
    if abs(float(up @ forward)) > 0.95:
        up = np.array([1.0, 0.0, 0.0], dtype=np.float64)
    right = np.cross(forward, up)
    right /= np.linalg.norm(right)
    down = np.cross(forward, right)
    rotation = np.column_stack([right, down, forward])
    T_WC = np.eye(4, dtype=np.float64)
    T_WC[:3, :3] = rotation
    T_WC[:3, 3] = position
    K = np.array([[FOCAL_PX, 0.0, (WIDTH - 1) / 2.0],
                  [0.0, FOCAL_PX, (HEIGHT - 1) / 2.0],
                  [0.0, 0.0, 1.0]], dtype=np.float64)
    return ViewFrame(view_id="mesh_depth_noise_visual", K=K, T_WC=T_WC,
                     image_size=(WIDTH, HEIGHT), profile_id="review_pinhole",
                     tier="GLOBAL", u_position_mm=CAMERA_DISTANCE_MM,
                     working_distance_mm=CAMERA_DISTANCE_MM, focus_setting="FIXED",
                     source_kind="SENSOR_SIM", camera_model="PINHOLE", dist=np.zeros(0),
                     meta={"focal_length_mm": 6.0, "f_number": 8.0})


def exact_candidate_depths(vertices_cam: np.ndarray, faces: np.ndarray,
                           frame_hi: ViewFrame, width: int, height: int,
                           near_mm: float, far_mm: float) -> tuple[np.ndarray, np.ndarray]:
    """Open3D candidate primitive IDs followed by independent float64 Moller-Trumbore."""
    import open3d as o3d

    tri = vertices_cam[faces]
    normals = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    front = np.einsum("ij,ij->i", normals, tri[:, 0]) < 0.0
    front_faces = np.flatnonzero(front)
    mesh = o3d.t.geometry.TriangleMesh(
        o3d.core.Tensor(np.ascontiguousarray(vertices_cam, dtype=np.float32)),
        o3d.core.Tensor(np.ascontiguousarray(faces[front_faces], dtype=np.int32)),
    )
    scene = o3d.t.geometry.RaycastingScene()
    scene.add_triangles(mesh)
    yy, xx = np.mgrid[0:height, 0:width]
    K = np.asarray(frame_hi.K, dtype=np.float64)
    rx = (xx.ravel().astype(np.float64) + 0.5 - K[0, 2]) / K[0, 0]
    ry = (yy.ravel().astype(np.float64) + 0.5 - K[1, 2]) / K[1, 1]
    directions = np.column_stack([rx, ry, np.ones_like(rx)])
    rays = np.zeros((len(directions), 6), dtype=np.float32)
    rays[:, 3:] = directions.astype(np.float32)
    hit = scene.cast_rays(o3d.core.Tensor(rays))
    primitive = hit["primitive_ids"].numpy().astype(np.int64)
    candidate_valid = primitive < len(front_faces)
    depth = np.full(len(directions), np.inf, dtype=np.float64)
    exact_hit = np.zeros(len(directions), dtype=bool)
    indexes = np.flatnonzero(candidate_valid)
    if indexes.size:
        source_faces = faces[front_faces[primitive[indexes]]]
        v0, v1, v2 = vertices_cam[source_faces[:, 0]], vertices_cam[source_faces[:, 1]], \
            vertices_cam[source_faces[:, 2]]
        e1, e2 = v1 - v0, v2 - v0
        p = np.cross(directions[indexes], e2)
        det = np.einsum("ij,ij->i", e1, p)
        nonsingular = np.abs(det) > 1e-14
        invdet = np.zeros_like(det)
        invdet[nonsingular] = 1.0 / det[nonsingular]
        tvec = -v0
        u = np.einsum("ij,ij->i", p, tvec) * invdet
        q = np.cross(tvec, e1)
        v = np.einsum("ij,ij->i", directions[indexes], q) * invdet
        t = np.einsum("ij,ij->i", e2, q) * invdet
        valid = (nonsingular & (u >= -1e-11) & (v >= -1e-11)
                 & (u + v <= 1.0 + 1e-11) & (t > near_mm) & (t < far_mm))
        depth[indexes[valid]] = t[valid]
        exact_hit[indexes[valid]] = True
    return depth.reshape(height, width), exact_hit.reshape(height, width)


def srgb_preview(linear: np.ndarray) -> np.ndarray:
    x = np.clip(np.asarray(linear, dtype=np.float64), 0.0, 1.0)
    y = np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1.0 / 2.4) - 0.055)
    return np.rint(np.clip(y, 0.0, 1.0) * 255.0).astype(np.uint8)


def save_rgb(path: Path, rgb: np.ndarray) -> None:
    Image.fromarray(np.asarray(rgb, dtype=np.uint8), mode="RGB").save(path)


with np.load(MESH_PATH, allow_pickle=False) as archive:
    vertices = np.asarray(archive["vertices"], dtype=np.float64)
    faces = np.asarray(archive["faces"], dtype=np.int32)

center = (vertices.min(axis=0) + vertices.max(axis=0)) / 2.0
tri = vertices[faces]
cross = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
normals = cross / np.maximum(np.linalg.norm(cross, axis=1, keepdims=True), 1e-30)
areas = 0.5 * np.linalg.norm(cross, axis=1)
axis_directions = np.vstack([np.eye(3), -np.eye(3)])
scores = [float(areas[np.einsum("ij,j->i", normals, direction) > 0.0].sum())
          for direction in axis_directions]
camera_direction = axis_directions[int(np.argmax(scores))]
frame = look_at_frame(center, camera_direction)
light_direction = -camera_direction
light = LightSpec(direction=light_direction / np.linalg.norm(light_direction),
                  color=np.array([0.8, 0.76, 0.70]),
                  ambient=np.array([0.28, 0.28, 0.30]))
albedo = np.tile(np.array([0.58, 0.50, 0.41], dtype=np.float32), (len(faces), 1))
scene = Scene(name="stored_small_mesh_visual", vertices=vertices, faces=faces,
              surface_tag=np.ones(len(faces), dtype=np.int16),
              material=MaterialSpec(albedo, np.full(len(faces), 0.55, dtype=np.float32),
                                    source_kind="REVIEW_NEUTRAL_LINEAR"))
render_spec = RenderSpec(supersample=FACTOR, near_mm=1.0, far_mm=10000.0,
                         max_pixels=4_000_000,
                         background_linear=(0.035, 0.04, 0.05), coc_px_threshold=1000.0)
render = render_view(scene, frame, light=light, spec=render_spec, backend=BACKEND_SOFTWARE)

noise_specs = {
    "noise_off_v2_default": ImagingSpec(response="LINEAR", encode="NONE"),
    "noise_low_explicit": ImagingSpec(response="LINEAR", encode="NONE",
                                       sensor_noise_enabled=True, effective_gain=10000.0,
                                       read_noise_sigma=0.003),
    "noise_high_explicit": ImagingSpec(response="LINEAR", encode="NONE",
                                        sensor_noise_enabled=True, effective_gain=500.0,
                                        read_noise_sigma=0.01),
}
valid_pixels = np.asarray(render.id_map) >= 0
if not valid_pixels.any():
    raise RuntimeError("selected stored mesh produced no visible pixels")
imaging_results = {}
image_stats = {}
for index, (name, imaging_spec) in enumerate(noise_specs.items()):
    result = apply_imaging_chain(
        render.rgb_linear, K=frame.K, dist=frame.dist,
        uncertain_mask=render.uncertain_mask, depth_z=render.depth_z,
        focus_distance_mm=frame.working_distance_mm,
        rng=np.random.default_rng(915 + index), spec=imaging_spec,
        camera_model=frame.camera_model or "PINHOLE",
    )
    imaging_results[name] = result
    preview = srgb_preview(result.linear)
    save_rgb(OUT / f"mesh_{name}.png", preview)
    delta = np.asarray(result.linear, dtype=np.float64) - np.asarray(render.rgb_linear,
                                                                      dtype=np.float64)
    values = delta[valid_pixels]
    g = float(imaging_spec.effective_gain)
    sigma_read = float(imaging_spec.read_noise_sigma)
    theory_std = (float(np.sqrt(np.mean(np.maximum(render.rgb_linear[valid_pixels], 0.0) / g
                                      + sigma_read ** 2)))
                  if imaging_spec.resolved_sensor_noise_enabled() else 0.0)
    image_stats[name] = {
        "version": imaging_spec.version,
        "sensor_noise_enabled": imaging_spec.resolved_sensor_noise_enabled(),
        "effective_gain": g,
        "read_noise_sigma": sigma_read,
        "valid_pixels": int(values.size // 3),
        "delta_mean": float(values.mean()),
        "delta_std_observed": float(values.std()),
        "delta_abs_p95": float(np.percentile(np.abs(values), 95)),
        "delta_max_abs": float(np.max(np.abs(values))),
        "delta_std_theory_preclip": theory_std,
        "scene_linear_mean": [float(x) for x in render.rgb_linear[valid_pixels].mean(axis=0)],
        "stages": result.stages,
    }

# Independent mesh ray oracle at the renderer's supersample centers, then reduce using the
# renderer contract: all subpixels must hit and output depth is their minimum z.
frame_hi = _scaled_frame(frame, FACTOR)
T_CW = np.asarray(frame.T_CW, dtype=np.float64)
vertices_cam = vertices @ T_CW[:3, :3].T + T_CW[:3, 3][None, :]
depth_hi, hit_hi = exact_candidate_depths(
    vertices_cam, faces, frame_hi, WIDTH * FACTOR, HEIGHT * FACTOR,
    render_spec.near_mm, render_spec.far_mm,
)
truth_blocks = depth_hi.reshape(HEIGHT, FACTOR, WIDTH, FACTOR)
hit_blocks = hit_hi.reshape(HEIGHT, FACTOR, WIDTH, FACTOR)
truth_all_hit = hit_blocks.all(axis=(1, 3))
truth_out = np.min(np.where(hit_blocks, truth_blocks, np.inf), axis=(1, 3))
measured_depth = np.asarray(render.depth_z, dtype=np.float64)
render_hit = np.isfinite(measured_depth)
compare = render_hit & truth_all_hit
depth_error = np.full((HEIGHT, WIDTH), np.nan, dtype=np.float64)
depth_error[compare] = np.abs(measured_depth[compare] - truth_out[compare])
error_values = depth_error[np.isfinite(depth_error)]

valid_depth = np.asarray(render.depth_z, dtype=np.float64)
depth_vis = np.zeros((HEIGHT, WIDTH), dtype=np.uint8)
depth_sel = np.isfinite(valid_depth)
if depth_sel.any():
    lo, hi = np.percentile(valid_depth[depth_sel], [2.0, 98.0])
    normalized = np.zeros_like(valid_depth)
    normalized[depth_sel] = np.clip((valid_depth[depth_sel] - lo) / max(hi - lo, 1e-12),
                                    0.0, 1.0)
    depth_vis = np.rint(normalized * 255.0).astype(np.uint8)
depth_color = cv2.applyColorMap(depth_vis, cv2.COLORMAP_TURBO)
depth_color[~depth_sel] = (10, 10, 10)
cv2.imwrite(str(OUT / "mesh_depth_z_visual.png"), depth_color)

# 40e-6 mm converts to 0.04 um (40 nm); keep the data division in millimetres.
error_vis = np.zeros((HEIGHT, WIDTH), dtype=np.uint8)
error_vis[np.isfinite(depth_error)] = np.rint(np.clip(depth_error[np.isfinite(depth_error)]
                                                       / ERROR_FULL_SCALE_MM, 0.0, 1.0)
                                                   * 255.0).astype(np.uint8)
error_color = cv2.applyColorMap(error_vis, cv2.COLORMAP_TURBO)
error_color[~np.isfinite(depth_error)] = (10, 10, 10)
error_rgb = cv2.cvtColor(error_color, cv2.COLOR_BGR2RGB)
error_panel = Image.new("RGB", (WIDTH + 80, HEIGHT), (20, 20, 24))
error_panel.paste(Image.fromarray(error_rgb, mode="RGB"), (0, 0))
bar_idx = np.linspace(255, 0, HEIGHT, dtype=np.uint8)[:, None]
bar_bgr = cv2.applyColorMap(np.repeat(bar_idx, 20, axis=1), cv2.COLORMAP_TURBO)
bar_rgb = cv2.cvtColor(bar_bgr, cv2.COLOR_BGR2RGB)
error_panel.paste(Image.fromarray(bar_rgb, mode="RGB"), (WIDTH + 4, 0))
error_draw = ImageDraw.Draw(error_panel)
error_draw.text((WIDTH + 27, 2), "0.04 um", fill=(245, 245, 245))
error_draw.text((WIDTH + 27, HEIGHT // 2 - 8), "0.02 um", fill=(245, 245, 245))
error_draw.text((WIDTH + 27, HEIGHT - 36), "0 um", fill=(245, 245, 245))
error_draw.text((WIDTH + 27, HEIGHT - 17), "40 nm FS", fill=(245, 245, 245))
error_panel.save(OUT / "mesh_depth_abs_error_40nm_scale.png")

panels = []
for title, filename in (
    ("v2 default: sensor noise OFF", "mesh_noise_off_v2_default.png"),
    ("explicit low noise", "mesh_noise_low_explicit.png"),
    ("explicit high noise", "mesh_noise_high_explicit.png"),
):
    panel = Image.open(OUT / filename).convert("RGB")
    panels.append((title, panel))
panels.extend([
    ("depth z (camera mm)", Image.open(OUT / "mesh_depth_z_visual.png").convert("RGB")),
    ("abs depth error (0.04 um = 40 nm full scale)", error_panel),
])
cell_w, cell_h, label_h = WIDTH + 80, HEIGHT, 24
columns = 3
rows = int(np.ceil(len(panels) / columns))
sheet = Image.new("RGB", (columns * cell_w, rows * (cell_h + label_h)), (28, 28, 32))
draw = ImageDraw.Draw(sheet)
for index, (title, panel) in enumerate(panels):
    x = (index % columns) * cell_w
    y = (index // columns) * (cell_h + label_h)
    image_x = x if panel.width > WIDTH else x + 40
    sheet.paste(panel, (image_x, y + label_h))
    draw.text((x + 6, y + 5), title, fill=(245, 245, 245))
sheet.save(OUT / "mesh_depth_noise_contact_sheet.png")

sha = hashlib.sha256(MESH_PATH.read_bytes()).hexdigest()
report = {
    "scope": "one existing small A12 stored mesh; depth/noise measurement only; not a realism review",
    "source_mesh": str(MESH_PATH),
    "source_mesh_sha256": sha,
    "mesh_vertices": int(len(vertices)),
    "mesh_faces": int(len(faces)),
    "mesh_bounds_mm": {"min": vertices.min(axis=0).tolist(),
                        "max": vertices.max(axis=0).tolist()},
    "camera": {"size": [WIDTH, HEIGHT], "supersample": FACTOR,
               "focal_px": FOCAL_PX, "camera_direction_world": camera_direction.tolist(),
               "distance_mm": CAMERA_DISTANCE_MM, "K": frame.K.tolist()},
    "render": {"backend": render.backend, "visible_output_pixels": int(render_hit.sum()),
               "visible_fraction": float(render_hit.mean()),
               "uncertain_fraction": float(np.asarray(render.uncertain_mask).mean()),
               "analytic_ray_support_pixels": int(truth_all_hit.sum()),
               "support_mismatch_pixels": int(np.count_nonzero(render_hit != truth_all_hit)),
               "compared_depth_pixels": int(compare.sum()),
               "abs_depth_error_mm": {
                   "mean": float(error_values.mean()),
                   "p95": float(np.percentile(error_values, 95)),
                   "max": float(error_values.max()),
               },
               "abs_depth_error_um": {
                   "conversion_mm_to_um": MM_TO_UM,
                   "mean": float(error_values.mean() * MM_TO_UM),
                   "p95": float(np.percentile(error_values, 95) * MM_TO_UM),
                   "max": float(error_values.max() * MM_TO_UM),
               },
               "abs_depth_error_nm": {
                   "conversion_mm_to_nm": MM_TO_NM,
                   "mean": float(error_values.mean() * MM_TO_NM),
                   "p95": float(np.percentile(error_values, 95) * MM_TO_NM),
                   "max": float(error_values.max() * MM_TO_NM),
               },
               "error_heatmap": {
                   "file": "mesh_depth_abs_error_40nm_scale.png",
                   "full_scale_mm": ERROR_FULL_SCALE_MM,
                   "full_scale_um": ERROR_FULL_SCALE_MM * MM_TO_UM,
                   "full_scale_nm": ERROR_FULL_SCALE_MM * MM_TO_NM,
                   "colormap": "OpenCV TURBO; colorbar labels are um",
               },
               "float32_spacing_at_mean_depth_mm": float(np.spacing(
                   np.float32(np.mean(valid_depth[render_hit])))),
               "float32_spacing_at_mean_depth_um": float(np.spacing(
                   np.float32(np.mean(valid_depth[render_hit]))) * MM_TO_UM),
               "unit_conversions": {"mm_to_um": MM_TO_UM, "mm_to_nm": MM_TO_NM}},
    "sensor_noise": image_stats,
    "visual_files": [
        "mesh_noise_off_v2_default.png", "mesh_noise_low_explicit.png",
        "mesh_noise_high_explicit.png", "mesh_depth_z_visual.png",
        "mesh_depth_abs_error_40nm_scale.png", "mesh_depth_noise_contact_sheet.png",
    ],
    "visual_note": "RGB previews use an sRGB display transform of post-sensor linear values. "
                   "Depth error heatmap uses 40e-6 mm = 0.04 um = 40 nm full range and a labeled "
                   "colorbar. These images validate only "
                   "depth/noise behavior, not material or fracture realism.",
}
(OUT / "mesh_depth_noise_visuals.json").write_text(json.dumps(report, indent=2),
                                                      encoding="utf-8")
print(json.dumps(report, indent=2))
