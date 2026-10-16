from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
import sys
from typing import Any

import numpy as np
from PIL import Image


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synlab.cameras.projection import look_at_T_WC  # noqa: E402
from synlab.integrations.forge_asset import (  # noqa: E402
    load_forge_asset,
    render_forge_asset_preview,
)
from synlab.observe.render import LightSpec, RenderSpec  # noqa: E402
from synlab.roles import SOURCE_SENSOR_SIM  # noqa: E402
from synlab.schemas.runtime import ViewFrame  # noqa: E402


ARTIFACTS = REPO_ROOT / "tmp/review_20261003/implementation/vf/artifacts"
OUTPUT_DIR = SCRIPT_DIR / "actual_previews"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
PACKAGES = {
    "four_bands_narrow": ARTIFACTS / "four_bands_brep_semantics1_final",
    "three_bands_counterfactual": ARTIFACTS / "three_bands_brep_semantics1_final",
}
PALETTE_TOLERANCE = 2e-5
FORBIDDEN_OUTPUT_KEYS = {
    "face_region", "vertices_material_xyz_mm", "ornament_recipe_json", "appearance_sampler",
    "palette_linear_rgb", "pattern_id", "bands", "seed", "provenance", "producer",
    "fracture_label", "r2_label",
}


def _nested_mapping_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        keys = {str(key) for key in value}
        for nested in value.values():
            keys.update(_nested_mapping_keys(nested))
        return keys
    if isinstance(value, (list, tuple)):
        keys: set[str] = set()
        for nested in value:
            keys.update(_nested_mapping_keys(nested))
        return keys
    return set()


def _frame(size: int) -> ViewFrame:
    focal_px = 1.55 * size
    return ViewFrame(
        view_id=f"actual-vf-{size}",
        K=np.asarray([[focal_px, 0.0, (size - 1.0) / 2.0],
                      [0.0, focal_px, (size - 1.0) / 2.0], [0.0, 0.0, 1.0]],
                     dtype=np.float64),
        T_WC=look_at_T_WC(np.asarray([6.0, -170.0, 28.0]),
                          np.asarray([6.0, 0.0, 28.0]),
                          up=np.asarray([0.0, 0.0, 1.0])),
        image_size=(size, size), profile_id="", tier="A12_PREVIEW",
        u_position_mm=0.0, working_distance_mm=170.0,
        focus_setting="fixed_prototype_preview", source_kind=SOURCE_SENSOR_SIM,
        camera_model="PINHOLE", dist=None,
        meta={"focal_length_mm": 35.0, "f_number": 5.6},
    )


def _light() -> LightSpec:
    return LightSpec(direction=np.asarray([0.0, 0.0, 1.0]),
                     color=np.asarray([0.88, 0.82, 0.74]),
                     ambient=np.asarray([0.28, 0.28, 0.28]))


def _ray_hit(origin: np.ndarray, direction: np.ndarray,
             triangle: np.ndarray) -> tuple[float, np.ndarray] | None:
    # Independent scalar Möller–Trumbore intersection at the OpenCV pixel center.
    edge1 = triangle[1] - triangle[0]
    edge2 = triangle[2] - triangle[0]
    pvec = np.cross(direction, edge2)
    det = float(np.dot(edge1, pvec))
    if abs(det) < 1e-12:
        return None
    inv_det = 1.0 / det
    tvec = origin - triangle[0]
    b1 = float(np.dot(tvec, pvec) * inv_det)
    qvec = np.cross(tvec, edge1)
    b2 = float(np.dot(direction, qvec) * inv_det)
    distance = float(np.dot(edge2, qvec) * inv_det)
    b0 = 1.0 - b1 - b2
    if distance <= 0.0 or min(b0, b1, b2) < -1e-9:
        return None
    return distance, np.asarray([b0, b1, b2], dtype=np.float64)


def _normal_lighting(asset: Any, frame: ViewFrame, light: LightSpec) -> np.ndarray:
    camera_vertices = (asset.vertices_mm @ frame.T_CW[:3, :3].T
                       + frame.T_CW[:3, 3][None, :])
    tri = camera_vertices[asset.faces]
    normals = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-15)
    normals_camera = normals @ frame.T_WC[:3, :3]
    lambert = np.clip(-(normals_camera @ light.direction), 0.0, 1.0)
    return light.ambient[None, :] + light.color[None, :] * lambert[:, None]


def _linear_to_srgb(rgb: np.ndarray) -> np.ndarray:
    value = np.clip(np.asarray(rgb, dtype=np.float64), 0.0, 1.0)
    encoded = np.where(value <= 0.0031308, 12.92 * value,
                       1.055 * np.power(value, 1.0 / 2.4) - 0.055)
    return np.clip(np.rint(encoded * 255.0), 0, 255).astype(np.uint8)


def _render_and_report(asset: Any, package_dir: Path, name: str, size: int,
                       geometry_baseline: dict[str, np.ndarray] | None = None
                       ) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    manifest = json.loads((package_dir / "manifest.json").read_text(encoding="utf-8"))
    recipe = json.loads(asset.ornament_recipe_json)
    frame, light = _frame(size), _light()
    spec = RenderSpec(supersample=1, near_mm=1.0, far_mm=400.0,
                      max_pixels=size * size, background_linear=(0.02, 0.025, 0.03))
    output = render_forge_asset_preview(
        asset, frame, light=light, spec=spec, allow_prototype_preview=True,
        appearance_sampling="CONTINUOUS_REST_COORDINATE")
    legacy = render_forge_asset_preview(
        asset, frame, light=light, spec=spec, allow_prototype_preview=True,
        appearance_sampling="FACE_SAMPLE_APPROXIMATION")

    pixels = output.rgb_linear
    ids = output.id_map
    tags = output.surface_tag
    target_codes = set(int(code) for code in recipe["target_region_codes"])
    band_counts = [0 for _ in recipe["bands"]]
    base_count = 0
    target_hits = 0
    hits_checked = 0
    max_depth_error_mm = 0.0
    max_color_error = 0.0
    origin = frame.T_WC[:3, 3]
    rotation = frame.T_WC[:3, :3]
    lighting = _normal_lighting(asset, frame, light)
    width = height = size

    for row, col in zip(*np.nonzero(ids >= 0)):
        face_index = int(ids[row, col])
        if face_index < 0 or face_index >= asset.n_faces:
            raise AssertionError(f"render emitted out-of-range face id {face_index}")
        # SS1's high-grid K shifts its principal point by +0.5, so this sample corresponds
        # exactly to solving the original OpenCV K against the integer pixel coordinate.
        ray_camera = np.linalg.solve(frame.K, np.asarray([col, row, 1.0], dtype=np.float64))
        direction = rotation @ ray_camera
        hit = _ray_hit(origin, direction, asset.vertices_mm[asset.faces[face_index]])
        if hit is None:
            raise AssertionError(f"rendered pixel ({row},{col}) has no independent triangle hit")
        ray_t, bary = hit
        if float(np.min(bary)) < -1e-8 or float(np.max(bary)) > 1.0 + 1e-8 \
                or not np.isclose(float(np.sum(bary)), 1.0, rtol=0.0, atol=1e-8):
            raise AssertionError(f"independent oracle produced invalid barycentrics {bary}")
        depth_error = abs(float(output.depth_z[row, col]) - ray_t)
        max_depth_error_mm = max(max_depth_error_mm, depth_error)
        if depth_error > 2e-3:
            raise AssertionError(f"rendered depth differs from independent ray by {depth_error} mm")

        region = int(asset.face_region[face_index])
        expected_albedo = np.asarray(asset.albedo_linear_rgb[face_index], dtype=np.float64)
        if region in target_codes:
            target_hits += 1
            material_z = float(np.dot(bary, asset.vertices_material_xyz_mm[
                asset.faces[face_index], 2]))
            band_index = None
            for index, band in enumerate(recipe["bands"]):
                if abs(material_z - float(band["center_z_mm"])) <= float(band["width_mm"]) / 2.0:
                    band_index = index
                    expected_albedo = np.asarray(
                        recipe["palette_linear_rgb"][band["color"]], dtype=np.float64)
                    break
            if band_index is None:
                base_count += 1
                expected_albedo = np.asarray(recipe["palette_linear_rgb"]["base"],
                                             dtype=np.float64)
            else:
                band_counts[band_index] += 1
        expected_rgb = expected_albedo * lighting[face_index]
        color_error = float(np.max(np.abs(pixels[row, col] - expected_rgb)))
        max_color_error = max(max_color_error, color_error)
        if color_error > PALETTE_TOLERANCE:
            raise AssertionError(
                f"rendered sample ({row},{col}) differs from independent rest-z palette "
                f"oracle by {color_error}: actual={pixels[row, col]}, expected={expected_rgb}")
        hits_checked += 1

    if not target_hits:
        raise AssertionError("the camera produced no pixels on a declared painted target region")
    if len(band_counts) != len(recipe["bands"]) or any(count == 0 for count in band_counts):
        raise AssertionError(f"not every declared band is visibly sampled: {band_counts}")
    if base_count == 0:
        raise AssertionError("painted target region has no visible base-color sample")

    result_arrays = {
        "rgb_linear": output.rgb_linear,
        "depth_z": output.depth_z,
        "id_map": output.id_map,
        "surface_tag": output.surface_tag,
        "visibility": output.visibility,
        "uncertain_mask": output.uncertain_mask,
    }
    for key, value in result_arrays.items():
        if geometry_baseline is not None and not np.array_equal(
                value, geometry_baseline[key], equal_nan=(key == "depth_z")):
            if key == "rgb_linear":
                continue
            raise AssertionError(f"continuous sampling changed the {key} render pass")
    if np.array_equal(output.rgb_linear, legacy.rgb_linear):
        raise AssertionError("continuous appearance did not change any rendered RGB pixel")
    if not (np.array_equal(output.depth_z, legacy.depth_z, equal_nan=True)
            and np.array_equal(output.id_map, legacy.id_map)
            and np.array_equal(output.surface_tag, legacy.surface_tag)
            and np.array_equal(output.visibility, legacy.visibility)
            and np.array_equal(output.uncertain_mask, legacy.uncertain_mask)):
        raise AssertionError("continuous appearance changed a frozen geometry/depth pass")

    serialized_output = asdict(output)
    serialized_keys = sorted(serialized_output)
    leaked_keys = FORBIDDEN_OUTPUT_KEYS.intersection(_nested_mapping_keys(serialized_output))
    if leaked_keys \
            or set(np.unique(output.surface_tag)).difference({-1, 0}):
        raise AssertionError("render output contains a truth-side or VF-region channel")

    png_path = OUTPUT_DIR / f"{name}_{size}.png"
    Image.fromarray(_linear_to_srgb(output.rgb_linear), mode="RGB").save(png_path)
    png_hash = hashlib.sha256(png_path.read_bytes()).hexdigest()
    geom_file = manifest["geometry"]["surface_npz"]
    solid_file = manifest["geometry"].get("solid_step")
    inventory = manifest.get("provenance", {}).get("spec", {}).get("brep_face_inventory", [])
    report = {
        "preview": str(png_path),
        "preview_sha256": png_hash,
        "size_px": [width, height],
        "package": name,
        "geometry_validation": manifest["validation"],
        "surface_counts": {
            "vertices": int(asset.vertices_mm.shape[0]),
            "triangles": int(asset.faces.shape[0]),
            "visible_hit_pixels": hits_checked,
            "visible_target_region_pixels": target_hits,
            "visible_base_pixels": base_count,
            "visible_pixels_per_band": [
                {"index": i, "center_z_mm": float(band["center_z_mm"]),
                 "width_mm": float(band["width_mm"]), "color": str(band["color"]),
                 "pixels": int(band_counts[i])}
                for i, band in enumerate(recipe["bands"])
            ],
            "surface_tags": sorted(int(value) for value in np.unique(output.surface_tag)),
        },
        "independent_oracle": {
            "method": "Float64 scalar Moller-Trumbore, perspective ray through OpenCV pixel center, "
                      "barycentric rest z, then exact recipe interval/palette",
            "depth_max_abs_error_mm": max_depth_error_mm,
            "rgb_max_abs_error_linear": max_color_error,
            "palette_tolerance_linear": PALETTE_TOLERANCE,
        },
        "geometry_pass_parity_with_legacy": {
            "depth_z": bool(np.array_equal(output.depth_z, legacy.depth_z, equal_nan=True)),
            "id_map": bool(np.array_equal(output.id_map, legacy.id_map)),
            "surface_tag": bool(np.array_equal(output.surface_tag, legacy.surface_tag)),
            "visibility": bool(np.array_equal(output.visibility, legacy.visibility)),
            "uncertain_mask": bool(np.array_equal(output.uncertain_mask,
                                                   legacy.uncertain_mask)),
        },
        "output_schema_keys": serialized_keys,
        "output_metadata_keys": sorted(output.meta),
        "output_forbidden_keys_found": sorted(leaked_keys),
        "output_contains_truth_fields": False,
        "package_hashes": {
            "surface_npz": manifest["files"][geom_file]["sha256"],
            "solid_step": (manifest["files"][solid_file]["sha256"]
                           if solid_file else None),
        },
        "canonical_brep_face_count": len(inventory),
    }
    return report, result_arrays


def main() -> None:
    assets = {name: load_forge_asset(path) for name, path in PACKAGES.items()}
    four = assets["four_bands_narrow"]
    three = assets["three_bands_counterfactual"]
    same_vertices = np.array_equal(four.vertices_mm, three.vertices_mm)
    same_faces = np.array_equal(four.faces, three.faces)
    if not same_vertices or not same_faces:
        raise AssertionError("counterfactual VF packages do not have identical surface geometry")

    report: dict[str, Any] = {
        "environment": "SynLab software rasterizer; preview_only; linear RGB encoded as sRGB PNG",
        "same_geometry_between_packages": {
            "vertices_equal": same_vertices,
            "faces_equal": same_faces,
            "vertex_count": int(four.vertices_mm.shape[0]),
            "triangle_count": int(four.faces.shape[0]),
        },
        "previews": [],
    }
    for size in (320, 512):
        baseline: dict[str, np.ndarray] | None = None
        for name, package_dir in PACKAGES.items():
            per_preview, arrays = _render_and_report(assets[name], package_dir, name, size)
            if baseline is None:
                baseline = arrays
            else:
                for key, value in arrays.items():
                    if key == "rgb_linear":
                        continue
                    if not np.array_equal(value, baseline[key],
                                          equal_nan=(key == "depth_z")):
                        raise AssertionError(f"same geometry produced different {key} at {size}px")
            report["previews"].append(per_preview)

    output_path = SCRIPT_DIR / "actual_preview_report.json"
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    print(f"report_path={output_path}")


if __name__ == "__main__":
    main()
