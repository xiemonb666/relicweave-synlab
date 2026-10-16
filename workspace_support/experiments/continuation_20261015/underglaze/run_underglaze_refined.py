"""Build an auditable, design-scale blue-white dragon-head spread comparison.

The cropped source is a high-chroma proxy from an already-fired Met photograph. The
additional spread is a stylized appearance variation, not reconstructed brushwork or
measured firing chemistry. All reported millimetres describe this comparison's declared
design scale, not measured dimensions on the photographed vase.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from synlab.patterns.underglaze import (
    blue_white_appearance,
    build_surface_of_revolution_operator,
    diffuse_two_fraction_appearance,
)


ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent / "outputs_v2"
RESOURCE_ROOT = (ROOT / "relicweave-synlab" / "synlab" / "patterns" /
                 "resources" / "bluewhite_20261015")
SOURCE_PHOTO = RESOURCE_ROOT / "source" / "met_50899_O2_original.jpg"
SOURCE_PROJECTION = RESOURCE_ROOT / "derived" / "met_50899_O2_dragon_projection_crop.png"
SOURCE_MASK = RESOURCE_ROOT / "derived" / "met_50899_O2_dragon_strong_cobalt_support_proxy.png"

# This aspect-matched crop covers the dragon's horn, eye and jaw brush forms.
SOURCE_CROP_XYXY = (970, 80, 1810, 640)
SOURCE_CROP_MM = (30.0, 20.0)  # azimuthal arc width, meridian height; design scale only
MOBILE_FRACTION = 0.25
BOUND_FRACTION = 1.0 - MOBILE_FRACTION
DOMAIN_ARC_MM = 60.0
DOMAIN_S_MM = 32.0
N_S = 400
N_THETA = 512
DS_MM = DOMAIN_S_MM / N_S
RADIUS_MM = DOMAIN_ARC_MM / (2.0 * np.pi)
ARC_STEP_MM = DOMAIN_ARC_MM / N_THETA
PATCH_S_START_MM = 6.0
PATCH_ARC_START_MM = 15.0
PATCH_S_CELLS = int(round(SOURCE_CROP_MM[1] / DS_MM))
PATCH_THETA_CELLS = int(round(SOURCE_CROP_MM[0] / ARC_STEP_MM))
PATCH_PROFILE_SOURCE_ROW = 80

SPREAD_LEVELS = {
    "no_added_spread": (0.0, 0.0),
    "low": (0.005, 0.02),
    "medium": (0.02, 0.08),
    "high": (0.08, 0.32),
}
GLAZE_WHITE_LINEAR_RGB = (0.94, 0.91, 0.84)
TAU_RGB = (3.04, 2.56, 0.93)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _font(size: int):
    for candidate in ("arial.ttf", "C:/Windows/Fonts/arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _linear_to_srgb(linear: np.ndarray) -> np.ndarray:
    values = np.asarray(linear, dtype=np.float64)
    return np.where(values <= 0.0031308, 12.92 * values,
                    1.055 * np.power(values, 1.0 / 2.4) - 0.055)


def _display_rgb(linear: np.ndarray, size: tuple[int, int]) -> Image.Image:
    rgb = np.clip(_linear_to_srgb(linear), 0.0, 1.0)
    pixels = np.asarray(np.round(255.0 * rgb), dtype=np.uint8)
    return Image.fromarray(pixels, mode="RGB").resize(size, Image.Resampling.NEAREST)


def _place_source_mask(s_centers_mm: np.ndarray) -> tuple[np.ndarray, dict[str, int]]:
    x0, y0, x1, y1 = SOURCE_CROP_XYXY
    source = Image.open(SOURCE_MASK).convert("L")
    if source.size != (2000, 1160):
        raise RuntimeError(f"unexpected source mask dimensions {source.size}")
    crop = source.crop((x0, y0, x1, y1))
    patch = crop.resize((PATCH_THETA_CELLS, PATCH_S_CELLS), Image.Resampling.LANCZOS)
    mask = np.asarray(patch, dtype=np.float64) / 255.0

    s_start = int(round(PATCH_S_START_MM / DS_MM))
    theta_start = int(round(PATCH_ARC_START_MM / ARC_STEP_MM))
    theta_end = theta_start + PATCH_THETA_CELLS
    if s_start + PATCH_S_CELLS > s_centers_mm.size or theta_end > N_THETA:
        raise RuntimeError("design-scale motif patch does not fit the surface chart")
    field = np.zeros((N_S, N_THETA), dtype=np.float64)
    # Source image rows run top-to-bottom; the surface meridian coordinate increases.
    field[s_start:s_start + PATCH_S_CELLS, theta_start:theta_end] = np.flipud(mask)
    return field, {"s_start_cell": s_start, "theta_start_cell": theta_start,
                   "source_crop_width_px": x1 - x0,
                   "source_crop_height_px": y1 - y0}


def _profile_plot(profile: dict[str, np.ndarray], profile_s_mm: float,
                  output_path: Path) -> None:
    width, height = 1280, 430
    margin_left, margin_right, margin_top, margin_bottom = 86, 34, 105, 76
    chart_left, chart_top = margin_left, margin_top
    chart_width = width - margin_left - margin_right
    chart_height = height - margin_top - margin_bottom
    chart_bottom = chart_top + chart_height
    canvas = Image.new("RGB", (width, height), (250, 249, 245))
    draw = ImageDraw.Draw(canvas)
    title_font, body_font, small_font = _font(23), _font(16), _font(13)
    draw.text((margin_left, 16), "Density profile across a dragon-head stroke edge",
              fill=(29, 43, 63), font=title_font)
    draw.text((margin_left, 42),
              f"Fired-photo support proxy · one row at s={profile_s_mm:.2f} design-scale mm · no post-PDE blur or sharpening",
              fill=(75, 82, 91), font=small_font)

    for tick in (0.0, 0.25, 0.5, 0.75, 1.0):
        y = chart_bottom - tick * chart_height
        draw.line((chart_left, y, chart_left + chart_width, y),
                  fill=(220, 220, 216), width=1)
        draw.text((18, y - 8), f"{tick:.2f}", fill=(67, 73, 80), font=small_font)
    x_max = 10.0
    for tick in range(0, 11, 2):
        x = chart_left + tick / x_max * chart_width
        draw.line((x, chart_top, x, chart_bottom), fill=(235, 234, 230), width=1)
        draw.text((x - 8, chart_bottom + 10), str(tick),
                  fill=(67, 73, 80), font=small_font)
    draw.rectangle((chart_left, chart_top, chart_left + chart_width, chart_bottom),
                   outline=(135, 140, 144), width=1)
    draw.text((chart_left + chart_width // 2 - 143, height - 34),
              "Distance from crop left edge (mm; 0–10 mm shown)",
              fill=(45, 51, 58), font=body_font)
    draw.text((18, chart_top - 24), "density", fill=(45, 51, 58), font=small_font)

    series = (
        ("no_added_spread", "No added spread", (88, 94, 101)),
        ("low", "Low", (99, 147, 208)),
        ("medium", "Medium", (35, 112, 189)),
        ("high", "High", (21, 53, 113)),
    )
    legend_x = chart_left + 8
    for index, (name, label, color) in enumerate(series):
        values = np.clip(profile[name], 0.0, 1.0)
        points = [
            (chart_left + float(x) / x_max * chart_width,
             chart_bottom - float(value) * chart_height)
            for x, value in zip(profile["arc_distance_mm"], values)
            if float(x) <= x_max
        ]
        draw.line(points, fill=color, width=3 if name == "high" else 2)
        lx = legend_x + index * 205
        draw.line((lx, chart_top - 30, lx + 24, chart_top - 30), fill=color, width=3)
        draw.text((lx + 31, chart_top - 39), label, fill=(45, 51, 58), font=small_font)
    # The plotted stroke edge is at source-mask transition x=52/256, about 6.1 mm.
    edge_x_mm = 52.0 * SOURCE_CROP_MM[0] / PATCH_THETA_CELLS
    edge_x = chart_left + edge_x_mm / x_max * chart_width
    draw.line((edge_x, chart_top, edge_x, chart_bottom), fill=(174, 70, 53), width=1)
    draw.text((edge_x + 5, chart_top + 5), f"source edge ≈{edge_x_mm:.1f} mm",
              fill=(147, 61, 48), font=small_font)
    canvas.save(output_path, optimize=True)


def _comparison_image(fields: dict[str, np.ndarray], colors: dict[str, np.ndarray],
                      patch_rows: slice, patch_columns: slice,
                      zoom_row_display: int, output_path: Path) -> None:
    width, margin, gap = 1984, 24, 16
    column_width = 466
    whole_size = (450, 300)
    zoom_size = (450, 360)
    header_y = 102
    whole_y = 143
    zoom_title_y = whole_y + whole_size[1] + 57
    zoom_y = zoom_title_y + 38
    canvas_height = zoom_y + zoom_size[1] + 54
    canvas = Image.new("RGB", (width, canvas_height), (250, 249, 245))
    draw = ImageDraw.Draw(canvas)
    draw.text((margin, 17), "MET 50899 · dragon head · blue-white pigment spread",
              fill=(29, 43, 63), font=_font(27))
    draw.text((margin, 56),
              "Fired-photo high-chroma support proxy · 30 × 20 mm design-scale patch · 25% mobile / 75% bound",
              fill=(75, 82, 91), font=_font(15))
    draw.text((margin, 83),
              "Additional spread is stylized; the mm scale is not measured UV geometry or reconstructed firing chemistry.",
              fill=(75, 82, 91), font=_font(13))

    labels = {
        "no_added_spread": "No added spread · Kₛ=0, Kθ=0 mm²",
        "low": "Low · Kₛ=0.005, Kθ=0.02 mm²",
        "medium": "Medium · Kₛ=0.02, Kθ=0.08 mm²",
        "high": "High · Kₛ=0.08, Kθ=0.32 mm²",
    }
    stages = tuple(SPREAD_LEVELS)
    for index, stage in enumerate(stages):
        x = margin + index * (column_width + gap)
        draw.text((x, header_y), labels[stage], fill=(41, 51, 64), font=_font(14))
        patch_rgb = np.flipud(colors[stage][patch_rows, :])[:, patch_columns]
        whole = _display_rgb(patch_rgb, whole_size)
        canvas.paste(whole, (x, whole_y))
        draw.rectangle((x, whole_y, x + whole_size[0] - 1,
                        whole_y + whole_size[1] - 1), outline=(168, 170, 169), width=1)

        draw.text((x, zoom_title_y), "RGB edge zoom · same source stroke in each field",
                  fill=(41, 51, 64), font=_font(13))
        # This local crop is display-enlarged with nearest-neighbour only. The raw PDE
        # densities saved beside the preview are untouched.
        display = np.flipud(fields[stage][patch_rows, patch_columns])
        zoom = display[40:120, 28:96]
        zoom_rgb = blue_white_appearance(zoom)
        canvas.paste(_display_rgb(zoom_rgb, zoom_size), (x, zoom_y))
        draw.rectangle((x, zoom_y, x + zoom_size[0] - 1,
                        zoom_y + zoom_size[1] - 1), outline=(168, 170, 169), width=1)
        profile_y = zoom_y + int((zoom_row_display - 40) *
                                 zoom_size[1] / (120 - 40))
        draw.line((x, profile_y, x + zoom_size[0] - 1, profile_y),
                  fill=(194, 87, 66), width=1)

    note_y = canvas_height - 29
    draw.text((margin, note_y),
              "RGB uses the dimensionless absorption proxy; nearest-neighbour display scaling only; no extra blur or sharpening.",
              fill=(75, 82, 91), font=_font(13))
    canvas.save(output_path, optimize=True)


def main() -> None:
    missing = [str(path) for path in (SOURCE_PHOTO, SOURCE_PROJECTION, SOURCE_MASK)
               if not path.is_file()]
    if missing:
        raise FileNotFoundError("required sourced motif resources are missing: " + ", ".join(missing))
    if N_S * N_THETA > 256_000:
        raise RuntimeError("refined grid exceeds the declared finite-volume cell budget")

    OUT.mkdir(parents=True, exist_ok=True)
    s_centers = (np.arange(N_S, dtype=np.float64) + 0.5) * DS_MM
    radius = np.full(N_S, RADIUS_MM, dtype=np.float64)
    dtheta = 2.0 * np.pi / N_THETA
    exact_cell_area = np.full(N_S, RADIUS_MM * DS_MM * dtheta, dtype=np.float64)
    initial, placement = _place_source_mask(s_centers)
    operator = build_surface_of_revolution_operator(
        s_centers, radius, N_THETA,
        diffusivity_s_mm2_per_unit=0.0,
        diffusivity_theta_mm2_per_unit=0.0,
        cell_area_mm2=exact_cell_area,
    )

    results = {}
    fields: dict[str, np.ndarray] = {}
    colors: dict[str, np.ndarray] = {}
    receipts: dict[str, dict] = {}
    for stage, (k_s, k_theta) in SPREAD_LEVELS.items():
        stage_operator = operator
        if stage != "no_added_spread":
            stage_operator = build_surface_of_revolution_operator(
                s_centers, radius, N_THETA,
                diffusivity_s_mm2_per_unit=k_s,
                diffusivity_theta_mm2_per_unit=k_theta,
                cell_area_mm2=exact_cell_area,
            )
        result = diffuse_two_fraction_appearance(
            stage_operator, initial, duration=1.0, mobile_fraction=MOBILE_FRACTION)
        results[stage] = result
        fields[stage] = result.total_density
        colors[stage] = blue_white_appearance(
            result.total_density,
            glaze_white_linear_rgb=GLAZE_WHITE_LINEAR_RGB,
            tau_rgb=TAU_RGB,
        )
        receipts[stage] = result.receipt

    s_start = placement["s_start_cell"]
    theta_start = placement["theta_start_cell"]
    patch_rows = slice(s_start, s_start + PATCH_S_CELLS)
    patch_columns = slice(theta_start, theta_start + PATCH_THETA_CELLS)
    profile_row_local = PATCH_S_CELLS - 1 - PATCH_PROFILE_SOURCE_ROW
    profile_row = s_start + profile_row_local
    profile_distance = (np.arange(PATCH_THETA_CELLS, dtype=np.float64) + 0.5) * ARC_STEP_MM
    profile = {"arc_distance_mm": profile_distance}
    profile["no_added_spread"] = initial[profile_row, patch_columns].copy()
    for stage in SPREAD_LEVELS:
        profile[stage] = fields[stage][profile_row, patch_columns].copy()
    profile_s_mm = float(s_centers[profile_row])

    profile_csv = OUT / "dragon_head_density_profile_mm.csv"
    with profile_csv.open("w", newline="", encoding="utf-8") as target:
        writer = csv.writer(target)
        writer.writerow(("azimuthal_arc_distance_mm", "source_density",
                         "no_added_spread_density", "low_density", "medium_density",
                         "high_density"))
        for index, arc_distance in enumerate(profile_distance):
            writer.writerow((float(arc_distance), float(profile["no_added_spread"][index]),
                             float(profile["no_added_spread"][index]),
                             float(profile["low"][index]), float(profile["medium"][index]),
                             float(profile["high"][index])))
    _profile_plot(profile, profile_s_mm, OUT / "dragon_head_density_profile_mm.png")
    _comparison_image(fields, colors, patch_rows, patch_columns,
                      PATCH_PROFILE_SOURCE_ROW, OUT / "dragon_head_spread_comparison.png")

    arrays = {
        "initial_density": initial,
        "s_centers_mm": s_centers,
        "radius_mm": radius,
        "cell_area_mm2": np.broadcast_to(exact_cell_area[:, None], (N_S, N_THETA)),
        "azimuth_centers_rad": (np.arange(N_THETA, dtype=np.float64) + 0.5) * dtheta,
    }
    for stage, result in results.items():
        arrays[f"{stage}_bound_density"] = result.bound_density
        arrays[f"{stage}_mobile_density"] = result.mobile_density
        arrays[f"{stage}_total_density"] = result.total_density
        arrays[f"{stage}_linear_rgb"] = colors[stage]
    np.savez_compressed(OUT / "dragon_head_density_fields.npz", **arrays)

    area_grid = np.broadcast_to(operator.cell_area_mm2, operator.shape)
    original_blank = initial <= 1e-12
    stats = {}
    for stage, result in results.items():
        stats[stage] = {
            "weighted_mass_initial": float(np.sum(area_grid * initial)),
            "weighted_mass_final": float(np.sum(area_grid * result.total_density)),
            "relative_weighted_mass_drift": float(
                result.receipt["mass"]["relative_final_total_drift"]),
            "nonzero_bleed_cells_outside_initial_support": int(
                np.count_nonzero(result.total_density[original_blank] > 1e-12)),
            "maximum_density_outside_initial_support": float(
                np.max(result.total_density[original_blank])),
        }

    source_info = {
        "institution": "The Metropolitan Museum of Art",
        "object_id": 50899,
        "title": "Vase with dragon",
        "collection_url": "https://www.metmuseum.org/art/collection/search/50899",
        "source_photo_path": str(SOURCE_PHOTO.relative_to(ROOT)),
        "source_photo_sha256": _sha256(SOURCE_PHOTO),
        "derived_projection_path": str(SOURCE_PROJECTION.relative_to(ROOT)),
        "derived_projection_sha256": _sha256(SOURCE_PROJECTION),
        "active_mask_path": str(SOURCE_MASK.relative_to(ROOT)),
        "active_mask_sha256": _sha256(SOURCE_MASK),
        "active_mask_semantics": "binary high-chroma support proxy thresholded from an already-fired O2 photograph",
        "crop_xyxy_px_on_2000_by_1160_source_mask": list(SOURCE_CROP_XYXY),
        "crop_width_height_px": [SOURCE_CROP_XYXY[2] - SOURCE_CROP_XYXY[0],
                                  SOURCE_CROP_XYXY[3] - SOURCE_CROP_XYXY[1]],
        "resampling_to_surface_cells": "Pillow Lanczos remap of the selected crop; fractional boundary cells retained",
        "interpretation": "projected fired-photo appearance proxy; not recovered pre-firing brushwork or measured pigment concentration",
    }
    receipt = {
        "schema": "shardforge.underglaze_dragon_head_design_scale.v2",
        "purpose": "higher-resolution local blue-white appearance sensitivity study with a retained brushwork core",
        "source": source_info,
        "appearance_limits": {
            "additional_spread": "stylized post-firing appearance transformation",
            "double_diffusion_risk": True,
            "firing_reconstruction": False,
            "measured_firing_chemistry": False,
            "measured_optical_constants": False,
            "source_photo_lighting_glaze_camera_effects_removed": False,
            "source_photo_curvature_and_local_surface_coordinates_known": False,
            "unseen_surface_wrap_reconstruction": False,
        },
        "design_scale_patch": {
            "meaning": "declared local comparison scale, not measured Met vase UV dimensions",
            "patch_arc_width_mm": SOURCE_CROP_MM[0],
            "patch_meridian_height_mm": SOURCE_CROP_MM[1],
            "blank_meridian_halo_each_side_mm": PATCH_S_START_MM,
            "blank_azimuthal_arc_each_side_mm": (DOMAIN_ARC_MM - SOURCE_CROP_MM[0]) / 2.0,
            "initial_field_fractional_boundary_cells": True,
        },
        "surface_grid": {
            "geometry": "positive-radius cylinder used only as a local metric chart",
            "radius_mm": RADIUS_MM,
            "circumference_arc_mm": DOMAIN_ARC_MM,
            "meridian_chart_length_mm": DOMAIN_S_MM,
            "n_s": N_S,
            "n_theta": N_THETA,
            "grid_cells": N_S * N_THETA,
            "grid_cell_budget": 256000,
            "ds_mm": DS_MM,
            "dtheta_rad": dtheta,
            "azimuthal_arc_cell_width_mm": ARC_STEP_MM,
            "cell_area_mm2": float(exact_cell_area[0]),
            "cell_area_method": "exact cylindrical annular area r * ds * dtheta",
            "first_band_excludes_axis": True,
            "boundary_conditions": {"meridian": "no_flux_at_both_domain_ends",
                                    "azimuth": "periodic_exactly_n_theta_cells"},
            "chart_geometry_is_measured_met_vase_geometry": False,
        },
        "appearance_model": {
            "formulation": "total = bound + diffuse(mobile_fraction * initial_density)",
            "mobile_fraction": MOBILE_FRACTION,
            "bound_fraction": BOUND_FRACTION,
            "mobile_fraction_basis": "fixed empirical normalized appearance phase parameter; not a measured material fraction",
            "duration": 1.0,
            "duration_is": "dimensionless effective process index",
            "effective_diffusion_levels_mm2": {
                stage: {"K_s": k_s, "K_theta": k_theta}
                for stage, (k_s, k_theta) in SPREAD_LEVELS.items()
            },
            "level_selection": "fixed sensitivity probes, not fitted to measured bleed width",
            "diffusion_solver": "SciPy expm_multiply on positive conservative metric-aware finite-volume graph",
            "raw_fields_have_no_post_pde_blur_or_sharpening": True,
            "color_mapping": "white_linear_rgb * exp(-tau_rgb * normalized_density)",
            "glaze_white_linear_rgb": list(GLAZE_WHITE_LINEAR_RGB),
            "dimensionless_tau_rgb": list(TAU_RGB),
            "tau_basis": "uncalibrated art-direction coefficients, not optical path constants",
            "display_encoding": "linear RGB to sRGB transfer function only",
        },
        "profile": {
            "source_crop_row_from_top_px": PATCH_PROFILE_SOURCE_ROW,
            "surface_s_center_mm": profile_s_mm,
            "series": ["source", "no_added_spread", "low", "medium", "high"],
            "horizontal_axis": "azimuthal arc distance in design-scale millimetres",
            "edge_feature": "thresholded support transition near local arc x=6.1 mm",
            "csv": "dragon_head_density_profile_mm.csv",
            "plot": "dragon_head_density_profile_mm.png",
        },
        "statistics": stats,
        "solver_receipts_by_level": receipts,
        "outputs": {
            "comparison_preview": "dragon_head_spread_comparison.png",
            "raw_density_fields_and_linear_rgb": "dragon_head_density_fields.npz",
            "density_profile_csv": "dragon_head_density_profile_mm.csv",
            "density_profile_plot": "dragon_head_density_profile_mm.png",
        },
    }
    (OUT / "receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8")
    (OUT / "README.md").write_text(
        "# Refined underglaze appearance proxy\n\n"
        "Run `run_underglaze_refined.py` from the workspace root with the `relicweave-synlab` "
        "virtual environment. This v2 output uses a 30 × 20 mm **design-scale** local crop "
        "of the Met 50899 fired-photo dragon-head support proxy. It keeps 75% of the "
        "projected brush field bound and diffuses 25% with the metric-aware FV operator. "
        "All coefficients and the local cylindrical chart are sensitivity-study controls, "
        "not measured glaze or vessel parameters. See `receipt.json` for hashes, controls, "
        "limits, numerical receipts, and output semantics. The original experiment receipt "
        "and preview in the parent folder are unchanged.\n",
        encoding="utf-8")
    print(json.dumps({
        "comparison": str(OUT / "dragon_head_spread_comparison.png"),
        "profile": str(OUT / "dragon_head_density_profile_mm.png"),
        "receipt": str(OUT / "receipt.json"),
        "grid": [N_S, N_THETA],
        "grid_cells": N_S * N_THETA,
        "mass_relative_drift": {
            stage: stats[stage]["relative_weighted_mass_drift"] for stage in SPREAD_LEVELS
        },
        "bleed_cells": {
            stage: stats[stage]["nonzero_bleed_cells_outside_initial_support"]
            for stage in SPREAD_LEVELS
        },
    }, indent=2))


if __name__ == "__main__":
    main()
