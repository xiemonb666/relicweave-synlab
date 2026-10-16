from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image, ImageDraw

REPO = Path(__file__).resolve().parents[5]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from synlab.cameras.projection import look_at_T_WC
from synlab.integrations.forge_asset import load_forge_asset, render_forge_asset_preview
from synlab.observe.render import LightSpec, RenderSpec
from synlab.roles import SOURCE_SENSOR_SIM
from synlab.schemas.runtime import ViewFrame


ARTIFACT = REPO / "tmp/review_20261003/implementation/vf/artifacts/four_bands_canonical1"
OUT = Path(__file__).resolve().parent / "actual_four_bands_canonical1"
OUT.mkdir(parents=True, exist_ok=True)


def linear_to_u8_srgb(value: np.ndarray) -> np.ndarray:
    x = np.clip(np.asarray(value, dtype=np.float64), 0.0, 1.0)
    y = np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1.0 / 2.4) - 0.055)
    return np.rint(y * 255.0).astype(np.uint8)


asset = load_forge_asset(ARTIFACT)
target = np.asarray([0.0, 0.0, 28.0], dtype=np.float64)
eye = np.asarray([100.0, -160.0, 94.0], dtype=np.float64)
distance = float(np.linalg.norm(eye - target))
frame = ViewFrame(
    view_id="forge-canonical1-preview",
    K=np.asarray([[700.0, 0.0, 255.5], [0.0, 700.0, 255.5], [0.0, 0.0, 1.0]],
                 dtype=np.float64),
    T_WC=look_at_T_WC(eye, target, up=np.asarray([0.0, 0.0, 1.0])),
    image_size=(512, 512), profile_id="", tier="REVIEW",
    u_position_mm=0.0, working_distance_mm=distance, focus_setting="review",
    source_kind=SOURCE_SENSOR_SIM, camera_model="PINHOLE", dist=None,
    meta={"focal_length_mm": 35.0, "f_number": 5.6},
)
light = LightSpec(direction=np.asarray([0.2, -0.5, -1.0], dtype=np.float64),
                  color=np.asarray([1.0, 0.94, 0.86], dtype=np.float64),
                  ambient=np.asarray([0.16, 0.16, 0.18], dtype=np.float64))
spec = RenderSpec(supersample=1, near_mm=2.0, far_mm=1000.0,
                  max_pixels=512 * 512, shade="LAMBERT_AMBIENT")

bound = render_forge_asset_preview(asset, frame, light=light, spec=spec,
                                   allow_prototype_preview=True)
base_rgb = np.asarray([0.66, 0.49, 0.34], dtype=np.float32)
counterfactual = render_forge_asset_preview(
    asset, frame, light=light, spec=spec, allow_prototype_preview=True,
    albedo_override=np.broadcast_to(base_rgb, (asset.n_faces, 3)).copy(),
    appearance_variant="unpatterned_manifest_base_counterfactual",
)

if not np.array_equal(bound.id_map, counterfactual.id_map):
    raise AssertionError("counterfactual changed geometry IDs")
if not np.array_equal(bound.surface_tag, counterfactual.surface_tag):
    raise AssertionError("counterfactual changed mapped tags")
if not np.array_equal(bound.depth_z, counterfactual.depth_z, equal_nan=True):
    raise AssertionError("counterfactual changed depth")
if np.array_equal(bound.rgb_linear, counterfactual.rgb_linear):
    raise AssertionError("face-material binding did not alter rendered RGB")

bound_u8 = linear_to_u8_srgb(bound.rgb_linear)
counter_u8 = linear_to_u8_srgb(counterfactual.rgb_linear)
Image.fromarray(bound_u8, mode="RGB").save(OUT / "vf_bound_face_fields.png")
Image.fromarray(counter_u8, mode="RGB").save(OUT / "unpatterned_base_counterfactual.png")

valid = (bound.id_map >= 0) & np.isfinite(bound.depth_z)
depth = bound.depth_z.astype(np.float64)
depth_visual = np.zeros(depth.shape, dtype=np.uint8)
if np.any(valid):
    lo, hi = np.percentile(depth[valid], [2.0, 98.0])
    depth_visual[valid] = np.rint(255.0 * (depth[valid] - lo) / max(hi - lo, 1e-12)) \
        .clip(0, 255).astype(np.uint8)
Image.fromarray(depth_visual, mode="L").save(OUT / "geometry_depth.png")

diff = np.abs(bound_u8.astype(np.int16) - counter_u8.astype(np.int16)).max(axis=2)
diff_rgb = np.zeros((*diff.shape, 3), dtype=np.uint8)
diff_rgb[..., 0] = np.clip(diff * 4, 0, 255).astype(np.uint8)
diff_rgb[..., 1] = np.clip(diff, 0, 255).astype(np.uint8)
Image.fromarray(diff_rgb, mode="RGB").save(OUT / "appearance_counterfactual_difference.png")

panels = [bound_u8, counter_u8, np.repeat(depth_visual[..., None], 3, axis=2), diff_rgb]
titles = ["VF face fields (approx.)", "Unpatterned counterfactual", "Shared geometry depth",
          "RGB difference x4"]
sheet = Image.new("RGB", (512 * 2, 512 * 2 + 56), (245, 245, 245))
draw = ImageDraw.Draw(sheet)
for idx, (panel, title) in enumerate(zip(panels, titles)):
    x = (idx % 2) * 512
    y = (idx // 2) * 512 + 28
    sheet.paste(Image.fromarray(panel, mode="RGB"), (x, y))
    draw.text((x + 8, y - 19), title, fill=(0, 0, 0))
sheet.save(OUT / "forge_asset_preview_contact_sheet.png")

report = {
    "purpose": "read-only VF->A12 Scene/material binding smoke preview",
    "input_schema": "forge.asset.v1",
    "input_manifest_sha256": asset.manifest_sha256,
    "input_geometry_status": asset.geometry_status,
    "input_validation_scope": asset.validation_scope,
    "geometry_validation_basis": "HASHED_PRODUCER_REPORT_VERIFIED_NOT_INDEPENDENTLY_REMEASURED",
    "material_calibration_status": asset.material_calibration_status,
    "historical_style_validation": asset.historical_style_validation,
    "appearance_sampling": "FACE_SAMPLE_APPROXIMATION",
    "red_band_realism_claim": False,
    "production_physical_pass": False,
    "production_visual_pass": False,
    "renderer": bound.backend,
    "image_size_px": [512, 512],
    "input_vertex_count": int(asset.vertices_mm.shape[0]),
    "input_face_count": int(asset.faces.shape[0]),
    "vf_face_region_counts_truth_side": {
        str(int(code)): int(count) for code, count in zip(*np.unique(
            asset.face_region, return_counts=True))
    },
    "a12_surface_tag_counts": {
        str(int(code)): int(count) for code, count in zip(*np.unique(
            bound.surface_tag, return_counts=True))
    },
    "fracture_or_r2_output": "NONE",
    "visible_pixel_count": int(np.count_nonzero(valid)),
    "same_geometry_ids": bool(np.array_equal(bound.id_map, counterfactual.id_map)),
    "same_surface_tags": bool(np.array_equal(bound.surface_tag, counterfactual.surface_tag)),
    "same_depth_all_pixels_nan_equal": bool(np.array_equal(bound.depth_z,
                                                            counterfactual.depth_z,
                                                            equal_nan=True)),
    "depth_max_abs_difference_mm": float(np.max(
        np.abs(bound.depth_z[valid] - counterfactual.depth_z[valid]), initial=0.0)),
    "rgb_changed": bool(not np.array_equal(bound.rgb_linear, counterfactual.rgb_linear)),
    "rgb_changed_pixel_count_u8": int(np.count_nonzero(np.any(bound_u8 != counter_u8, axis=2))),
    "rgb_max_abs_difference_linear": float(np.max(
        np.abs(bound.rgb_linear - counterfactual.rgb_linear), initial=0.0)),
    "counterfactual_semantics": "test-only unpatterned base-albedo override; not an alternate historical pattern",
    "panels": [
        "vf_bound_face_fields.png", "unpatterned_base_counterfactual.png",
        "geometry_depth.png", "appearance_counterfactual_difference.png",
        "forge_asset_preview_contact_sheet.png",
    ],
}
(OUT / "preview_evidence.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report, indent=2))
