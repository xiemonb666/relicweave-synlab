"""Create a sourced blue-white pigment-spread comparison and numerical receipt.

The input is a thresholded cobalt-support mask from a photographed, already-fired Met
vase.  The added diffusion is a stylized appearance transformation, not recovery of
pre-firing brushwork or a calibrated kiln process.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from synlab.patterns.underglaze import (
    blue_white_appearance,
    build_surface_of_revolution_operator,
    diffuse_pigment,
)


ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
RESOURCE_ROOT = (ROOT / "relicweave-synlab" / "synlab" / "patterns" /
                 "resources" / "bluewhite_20261015" / "derived")
MASK_PATHS = {
    "continuous_photo": RESOURCE_ROOT / "met_50899_O2_dragon_cobalt_fired_photo_mask.png",
    "strong_support": RESOURCE_ROOT / "met_50899_O2_dragon_strong_cobalt_support_proxy.png",
}


def _profile_radius_from_z(z_mm: np.ndarray) -> np.ndarray:
    """A deliberately illustrative vase meridian with a bulb and narrowing neck."""
    z = np.asarray(z_mm, dtype=np.float64)
    return 20.0 + 32.0 * np.exp(-((z - 55.0) / 42.0) ** 4)


def _build_profile_area_grid(n_s: int, ds_mm: float, n_theta: int):
    z_dense = np.linspace(0.0, 170.0, 80_001, dtype=np.float64)
    radius_dense = _profile_radius_from_z(z_dense)
    dr_dz = np.gradient(radius_dense, z_dense)
    metric = np.sqrt(1.0 + dr_dz ** 2)
    s_dense = np.zeros_like(z_dense)
    s_dense[1:] = np.cumsum(0.5 * (metric[:-1] + metric[1:]) * np.diff(z_dense))
    if s_dense[-1] <= n_s * ds_mm:
        raise RuntimeError("profile does not cover the selected meridian chart")
    s_centers = (np.arange(n_s, dtype=np.float64) + 0.5) * ds_mm
    s_faces = np.arange(n_s + 1, dtype=np.float64) * ds_mm
    radius_centers = np.interp(s_centers, s_dense, radius_dense)
    # Integrate r(s) at a dense meridian sampling, then difference its primitive at
    # the finite-volume cell faces.  Each angular wedge gets one dtheta fraction.
    radius_integral = np.zeros_like(s_dense)
    radius_integral[1:] = np.cumsum(
        0.5 * (radius_dense[:-1] + radius_dense[1:]) * np.diff(s_dense))
    face_integral = np.interp(s_faces, s_dense, radius_integral)
    cell_area_per_theta = (2.0 * np.pi / n_theta) * np.diff(face_integral)
    return s_centers, radius_centers, cell_area_per_theta


def _resize_photo_mask_to_chart(mask_path: Path, n_s: int, n_theta: int,
                                s_centers_mm: np.ndarray,
                                s_min_mm: float, s_max_mm: float) -> np.ndarray:
    source = Image.open(mask_path).convert("L")
    source_mask = np.asarray(source, dtype=np.uint8)
    selected = np.flatnonzero((s_centers_mm >= s_min_mm) & (s_centers_mm <= s_max_mm))
    if selected.size < 2:
        raise RuntimeError("motif placement leaves too few chart rows")
    target = Image.fromarray(source_mask).resize(
        (n_theta, int(selected.size)), Image.Resampling.LANCZOS)
    image_values = np.asarray(target, dtype=np.float64) / 255.0
    field = np.zeros((n_s, n_theta), dtype=np.float64)
    # Photo top maps to greater profile arclength; keep the rest of the physical band
    # as a genuinely blank halo so the motif does not touch the reflecting s ends.
    field[selected[0]:selected[-1] + 1] = image_values[::-1]
    return field


def _linear_to_srgb(linear: np.ndarray) -> np.ndarray:
    linear = np.asarray(linear, dtype=np.float64)
    return np.where(linear <= 0.0031308, 12.92 * linear,
                    1.055 * np.power(linear, 1.0 / 2.4) - 0.055)


def _font(size: int):
    candidates = ("arial.ttf", "C:/Windows/Fonts/arial.ttf", "DejaVuSans.ttf")
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            pass
    return ImageFont.load_default()


def _comparison_image(fields: dict[str, dict[str, np.ndarray]],
                      colors: dict[str, dict[str, np.ndarray]],
                      n_theta: int, s_centers_mm: np.ndarray) -> Image.Image:
    panel_w, whole_h, zoom_w, zoom_h = 460, 205, 190, 140
    gap, margin = 16, 24
    canvas_w = margin * 2 + 3 * panel_w + 2 * gap
    row_h = 45 + whole_h + 8 + zoom_h + 30
    canvas_h = 106 + 2 * row_h + 24
    canvas = Image.new("RGB", (canvas_w, canvas_h), (250, 249, 245))
    draw = ImageDraw.Draw(canvas)
    draw.text((margin, 17), "MET 50899 · dragon motif · metric-aware blue-white spread",
              fill=(29, 43, 63), font=_font(26))
    draw.text((margin, 51),
              "Each cell: whole motif in linear-RGB appearance; zoom below shows a dragon-head stroke edge in density",
              fill=(75, 82, 91), font=_font(15))
    stages = ("no_spread", "low", "high")
    stage_labels = {
        "no_spread": "no-spread control · K_s=0, K_theta=0 mm²",
        "low": "low spread · K_s=0.4, K_theta=2 mm²",
        "high": "higher spread · K_s=1.6, K_theta=8 mm²",
    }
    zoom_s = (s_centers_mm >= 68.0) & (s_centers_mm <= 106.0)
    row_titles = {
        "continuous_photo": "Continuous cobalt mask · fired-photo chroma projection",
        "strong_support": "Strong support mask · fired-photo high-chroma threshold",
    }
    for row, source_name in enumerate(("continuous_photo", "strong_support")):
        y0 = 86 + row * row_h
        draw.text((margin, y0), row_titles[source_name],
                  fill=(29, 43, 63), font=_font(17))
        for col, stage in enumerate(stages):
            x0 = margin + col * (panel_w + gap)
            draw.text((x0, y0 + 27), stage_labels[stage],
                      fill=(65, 70, 75), font=_font(13))
            whole = np.flipud(colors[source_name][stage])
            whole = np.clip(_linear_to_srgb(whole), 0.0, 1.0)
            color_view = Image.fromarray(
                np.asarray(np.round(255.0 * whole), dtype=np.uint8), mode="RGB")
            color_view = color_view.resize((panel_w, whole_h), Image.Resampling.LANCZOS)
            image_y = y0 + 45
            canvas.paste(color_view, (x0, image_y))
            draw.rectangle((x0, image_y, x0 + panel_w - 1,
                            image_y + whole_h - 1), outline=(173, 174, 171), width=1)

            field = fields[source_name][stage][zoom_s]
            theta_center = int(round(0.60 * n_theta))
            theta_columns = np.mod(np.arange(theta_center - 40, theta_center + 40),
                                   n_theta)
            local_edge = field[:, theta_columns]
            grey = np.asarray(np.round(255.0 * np.flipud(local_edge)), dtype=np.uint8)
            zoom_view = Image.fromarray(grey, mode="L").convert("RGB")
            zoom_view = zoom_view.resize((zoom_w, zoom_h), Image.Resampling.LANCZOS)
            zoom_y = image_y + whole_h + 8
            canvas.paste(zoom_view, (x0, zoom_y))
            draw.rectangle((x0, zoom_y, x0 + zoom_w - 1,
                            zoom_y + zoom_h - 1), outline=(173, 174, 171), width=1)
            draw.text((x0 + zoom_w + 14, zoom_y + 4), "local density zoom",
                      fill=(29, 43, 63), font=_font(15))
            draw.text((x0 + zoom_w + 14, zoom_y + 28), "curled dragon head edge",
                      fill=(75, 82, 91), font=_font(13))
            draw.text((x0 + zoom_w + 14, zoom_y + 49), "s = 68–106 mm",
                      fill=(75, 82, 91), font=_font(12))
            draw.text((x0 + zoom_w + 14, zoom_y + 68), "θ window = 80 cells",
                      fill=(75, 82, 91), font=_font(12))
    note_y = canvas_h - 27
    draw.text((margin, note_y),
              "Blank meridian halo · additional post-firing spread is stylized · geometry and roughness unchanged",
              fill=(75, 82, 91), font=_font(14))
    return canvas


def main() -> None:
    missing = [str(path) for path in MASK_PATHS.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError("motif masks not found: " + ", ".join(missing))
    OUT.mkdir(parents=True, exist_ok=True)
    n_s, n_theta, ds_mm = 160, 384, 0.8
    s, radius, exact_area = _build_profile_area_grid(n_s, ds_mm, n_theta)
    diffusivity_s, diffusivity_theta = 0.10, 0.50
    operator = build_surface_of_revolution_operator(
        s, radius, n_theta,
        diffusivity_s_mm2_per_unit=diffusivity_s,
        diffusivity_theta_mm2_per_unit=diffusivity_theta,
        cell_area_mm2=exact_area,
    )
    exposures = {"no_spread": 0.0, "low": 4.0, "high": 16.0}
    fields: dict[str, dict[str, np.ndarray]] = {}
    diffusion_receipts: dict[str, dict[str, dict]] = {}
    for source_name, mask_path in MASK_PATHS.items():
        initial = _resize_photo_mask_to_chart(
            mask_path, n_s, n_theta, s, s_min_mm=22.0, s_max_mm=106.0)
        fields[source_name] = {}
        diffusion_receipts[source_name] = {}
        for stage, duration in exposures.items():
            result = diffuse_pigment(operator, initial, duration=duration)
            fields[source_name][stage] = result.concentration
            diffusion_receipts[source_name][stage] = result.receipt

    colors = {
        source: {stage: blue_white_appearance(field)
                 for stage, field in source_fields.items()}
        for source, source_fields in fields.items()
    }
    _comparison_image(fields, colors, n_theta, s).save(
        OUT / "motif_spread_comparison.png", optimize=True)
    arrays = {}
    for source_name, source_fields in fields.items():
        for stage, field in source_fields.items():
            arrays[f"{source_name}_{stage}_density"] = field.astype(np.float32)
            arrays[f"{source_name}_{stage}_linear_rgb"] = \
                colors[source_name][stage].astype(np.float32)
    arrays["s_centers_mm"] = s.astype(np.float64)
    arrays["radius_mm"] = radius.astype(np.float64)
    arrays["cell_area_mm2_per_theta"] = exact_area.astype(np.float64)
    np.savez_compressed(OUT / "motif_spread_fields.npz", **arrays)

    source_records = {}
    for source_name, mask_path in MASK_PATHS.items():
        source_records[source_name] = {
            "mask_path_from_workspace": str(mask_path.relative_to(ROOT)),
            "mask_sha256": hashlib.sha256(mask_path.read_bytes()).hexdigest(),
            "mask_semantics": ("continuous cobalt-chroma mask from fired photo"
                               if source_name == "continuous_photo"
                               else "binary high-chroma support proxy thresholded from fired photo"),
            "interpretation": "projected layout seed; not pre-firing brushwork or physical pigment concentration",
        }
    receipt = {
        "schema": "shardforge.underglaze_motif_demo.v1",
        "purpose": "metric-aware surface pigment spread and uncalibrated appearance comparison",
        "source": {
            "institution": "The Metropolitan Museum of Art",
            "object_id": 50899,
            "title": "Vase with dragon",
            "collection_url": "https://www.metmuseum.org/art/collection/search/50899",
            "mask_variants": source_records,
        },
        "transform_limitations": {
            "additional_spread": "stylized post-firing appearance transformation",
            "double_diffusion_risk": True,
            "firing_reconstruction": False,
            "unseen_surface_wrap_reconstruction": False,
            "photo_lighting_glaze_camera_effects_removed": False,
        },
        "geometry": {
            "profile": "illustrative smooth bulb-and-neck surface of revolution",
            "meridian_coordinate": "dense profile-derived true arclength, in mm",
            "radius_profile_sampling": "interpolated from a 80001-point meridian evaluation",
            "exact_area_method": "high-resolution trapezoidal integral of r(s) over each cell, times dtheta",
            "first_band_excludes_axis": True,
            "body_band_s_bounds_mm": [0.0, 128.0],
            "initial_motif_s_bounds_mm": [22.0, 106.0],
            "blank_meridian_halo_mm_each_side": 22.0,
            "radius_range_mm": [float(np.min(radius)), float(np.max(radius))],
            "cell_area_range_mm2": [float(np.min(exact_area)), float(np.max(exact_area))],
            "cell_area_source": "high-resolution profile-integrated area per azimuth wedge",
            "local_edge_zoom_s_bounds_mm": [68.0, 106.0],
            "local_edge_zoom_azimuth_cells": 80,
            "geometry_modified_by_diffusion": False,
        },
        "diffusion": {
            "operator": "A dc/dt = L c; H = A^-1/2 L A^-1/2",
            "solver": "scipy.sparse.linalg.expm_multiply",
            "diffusivity_s_mm2_per_effective_unit": diffusivity_s,
            "diffusivity_theta_mm2_per_effective_unit": diffusivity_theta,
            "duration_is": "dimensionless effective process index, not temperature/time",
            "effective_diffusion_mm2": {
                stage: {"s": diffusivity_s * duration,
                        "theta": diffusivity_theta * duration}
                for stage, duration in exposures.items()},
            "spread_level_selection": "fixed display-sensitivity probes; not calibrated to measured fired width",
            "density": "dimensionless normalized mask support, initial range [0, 1]",
            "boundary_conditions": {"meridian": "no-flux at physical band ends",
                                    "azimuth": "periodic; exactly n_theta cells"},
            "stages_by_mask_variant": diffusion_receipts,
        },
        "appearance": {
            "mapping": "glaze_white_linear_rgb * exp(-tau_rgb * normalized_density)",
            "color_space": "linear RGB before display encoding",
            "glaze_white_linear_rgb": [0.94, 0.91, 0.84],
            "dimensionless_tau_rgb": [3.04, 2.56, 0.93],
            "coefficient_basis": "art-direction anchor toward the existing cobalt-white linear palette; not optical calibration",
            "display_encoding": "linear RGB converted to sRGB transfer function only",
            "status": "UNCALIBRATED_APPEARANCE_SURROGATE",
            "roughness_separate_and_unchanged": True,
            "geometry_height_or_material_thickness_changed": False,
        },
        "outputs": {
            "comparison_png": "motif_spread_comparison.png",
            "saved_scalar_and_linear_rgb_fields": "motif_spread_fields.npz",
            "fields_array_order": "(meridian_arclength_cell, periodic_azimuth_cell)",
        },
    }
    (OUT / "receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8")
    print(json.dumps({"comparison": str(OUT / "motif_spread_comparison.png"),
                      "fields": str(OUT / "motif_spread_fields.npz"),
                      "receipt": str(OUT / "receipt.json"),
                      "grid": operator.shape,
                      "mass_relative_drift": {
                          source: {
                              stage: stage_receipt["mass"]["relative_solver_drift"]
                              for stage, stage_receipt in source_receipts.items()}
                          for source, source_receipts in diffusion_receipts.items()}}, indent=2))


if __name__ == "__main__":
    main()
