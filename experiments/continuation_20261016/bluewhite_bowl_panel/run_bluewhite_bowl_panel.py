"""Build an auditable photo-proxy blue-white panel on the actual VF bowl chart.

This is a synthetic appearance design. Its Met 50899 mask comes from an already-fired
photo, and its bowl meridian is a size-reference candidate, not a source scan or exact
profile reconstruction. Additional spread is a fixed, uncalibrated design control.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parents[3]
ROOT = REPO.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from synlab.integrations.reference_generator import load_reference_mother  # noqa: E402
from synlab.mothers.tagging import TAG_INDEX  # noqa: E402
from synlab.patterns.bluewhite_panel import (  # noqa: E402
    BlueWhitePanelResult,
    build_bluewhite_panel,
    normalized_density_sha256,
)
from synlab.patterns.underglaze import blue_white_appearance, sample_periodic_field  # noqa: E402


OUT = (REPO / "experiments" / "continuation_20261016"
       / "bluewhite_bowl_panel" / "outputs_v2")
REFERENCE_ASSET = (
    ROOT / "vesselforge" / "experiments" / "continuation_20261015"
    / "reference_forms" / "outputs" / "daily_aberdeen_108x53_v6_final"
)
RESOURCE_ROOT = (
    REPO / "synlab" / "patterns" / "resources" / "bluewhite_20261015"
)
PHOTO_PATH = RESOURCE_ROOT / "source" / "met_50899_O2_original.jpg"
PROJECTION_PATH = RESOURCE_ROOT / "derived" / "met_50899_O2_dragon_projection_crop.png"
MASK_PATH = RESOURCE_ROOT / "derived" / "met_50899_O2_dragon_cobalt_fired_photo_mask.png"
COLLECTION_URL = "https://www.metmuseum.org/art/collection/search/50899"

PANEL_WIDTH_MM = 45.0
PANEL_HEIGHT_MM = 26.0
MOBILE_FRACTION = 0.25
DIFFUSIVITY_S_MM2_PER_UNIT = 0.02
DIFFUSIVITY_THETA_MM2_PER_UNIT = 0.08
DURATION = 1.0
GRID_LEVELS = {
    "coarse": (128, 512),
    "fine": (240, 1024),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_float64(values: np.ndarray) -> str:
    canonical = np.ascontiguousarray(np.asarray(values, dtype="<f8"))
    return hashlib.sha256(canonical.tobytes(order="C")).hexdigest()


def _load_reference_and_source() -> tuple[Any, np.ndarray, np.ndarray, np.ndarray,
                                           dict[str, str], dict[str, Any]]:
    for path in (PHOTO_PATH, PROJECTION_PATH, MASK_PATH):
        if not path.is_file():
            raise FileNotFoundError(f"required retained source asset is missing: {path}")
    mother = load_reference_mother(REFERENCE_ASSET)
    chart = mother.chart_for_tag(TAG_INDEX["outer_wall"])
    profile_rzs = np.asarray(chart.meta["arrays"]["profile_rzs"], dtype=np.float64)
    if (profile_rzs.ndim != 2 or profile_rzs.shape[1] != 3
            or profile_rzs.shape[0] < 3 or np.any(profile_rzs[:, 0] <= 0.0)):
        raise RuntimeError("the requested positive-radius outer meridian chart is unavailable")
    segment_lengths = np.linalg.norm(np.diff(profile_rzs[:, :2], axis=0), axis=1)
    if np.any(segment_lengths <= 0.0):
        raise RuntimeError("outer meridian chart contains a zero-length segment")
    s_profile = np.r_[0.0, np.cumsum(segment_lengths, dtype=np.float64)]

    with Image.open(MASK_PATH) as image:
        mask_image = image.convert("L")
        normalized_density = np.asarray(mask_image, dtype=np.float64) / 255.0
    if normalized_density.shape != (1160, 2000) or not np.ptp(normalized_density):
        raise RuntimeError("continuous source mask shape or tonal-variation assumption failed")

    source_metadata = {
        "source_id": "met-50899-o2-dragon-continuous-cobalt-chroma",
        "title": "Vase with dragon, already-fired O2 photo-derived crop",
        "source_url": COLLECTION_URL,
        "source_mask_path": str(MASK_PATH.relative_to(ROOT)),
        "source_mask_sha256": _sha256(MASK_PATH),
        "normalized_density_sha256": normalized_density_sha256(normalized_density),
        "mask_semantics": (
            "continuous blue-excess chroma proxy from an already-fired photo; "
            "tonal values retained; not recovered pre-fire pigment"),
        "photo_state": "already_fired_photo",
    }
    geometry_metadata = {
        "reference_asset_path": str(REFERENCE_ASSET.relative_to(ROOT)),
        "reference_object": mother.meta.get("source_record", {}),
        "candidate_status": mother.meta.get("candidate_status"),
        "candidate_geometry_status": mother.meta.get("candidate_geometry_status"),
        "source_profile_fidelity": mother.meta.get("source_profile_fidelity"),
        "geometry_source_sha256": mother.meta.get("geometry_source_sha256"),
        "geometry_array_sha256": mother.meta.get("geometry_array_sha256"),
        "outer_profile_rzs_sha256": _sha256_float64(profile_rzs),
        "chart_name": chart.meta.get("spec", {}).get("name"),
        "chart_declared_s_definition_metadata": chart.meta.get("spec", {}).get(
            "meta", {}).get("s_definition"),
        "chart_s_total_mm": chart.meta.get("spec", {}).get("s_total_mm"),
        "profile_shape": list(profile_rzs.shape),
        "profile_order_first_rz_mm": profile_rzs[0, :2].tolist(),
        "profile_order_last_rz_mm": profile_rzs[-1, :2].tolist(),
        "panel_s_origin": "first stored profile sample; this actual profile runs from outer rim toward foot",
        "profile_arclength_recomputed_from_rz_mm": float(s_profile[-1]),
        "profile_sampling_status": chart.meta.get("reference_curve_sampling", {}).get(
            "arclength_status"),
    }
    return mother, profile_rzs, s_profile, normalized_density, source_metadata, geometry_metadata


def _build_grid(profile_rzs: np.ndarray, s_profile: np.ndarray,
                source_density: np.ndarray, source_metadata: dict[str, str],
                n_s: int, n_theta: int) -> tuple[BlueWhitePanelResult, dict[str, Any]]:
    result = build_bluewhite_panel(
        profile_rzs,
        source_density,
        source_metadata=source_metadata,
        panel_width_mm=PANEL_WIDTH_MM,
        panel_height_mm=PANEL_HEIGHT_MM,
        center_s_mm=float(0.5 * s_profile[-1]),
        center_theta_rad=np.pi,
        diffusivity_s_mm2_per_unit=DIFFUSIVITY_S_MM2_PER_UNIT,
        diffusivity_theta_mm2_per_unit=DIFFUSIVITY_THETA_MM2_PER_UNIT,
        duration=DURATION,
        mobile_fraction=MOBILE_FRACTION,
        n_s=n_s,
        n_theta=n_theta,
        boundary_halo_mm=2.0,
        image_top_toward="lower_s",
    )
    initial_rgb = blue_white_appearance(
        result.initial_density,
        glaze_white_linear_rgb=result.glaze_white_linear_rgb,
        tau_rgb=result.tau_rgb,
    )
    area = result.cell_area_mm2[:, None]
    initial_mass = float(np.sum(area * result.initial_density, dtype=np.float64))
    final_mass = float(np.sum(area * result.total_density, dtype=np.float64))
    support = result.initial_density > 0.0
    support_rows, support_cols = np.nonzero(support)
    wrapped_delta = (
        result.theta_centers_rad[None, :] - result.receipt["panel"]["center_theta_rad"]
        + np.pi) % (2.0 * np.pi) - np.pi
    physical_x = result.radius_mm[:, None] * wrapped_delta
    support_area = float(np.sum(area * support, dtype=np.float64))
    support_receipt = {
        "initial_nonzero_cell_count": int(np.count_nonzero(support)),
        "initial_nonzero_area_mm2_discrete": support_area,
        "initial_nonzero_area_threshold": 0.0,
        "initial_area_weighted_loading_mass": initial_mass,
        "panel_footprint_area_mm2_continuum": PANEL_WIDTH_MM * PANEL_HEIGHT_MM,
        "initial_support_s_bounds_mm": [
            float(result.s_centers_mm[support_rows].min()),
            float(result.s_centers_mm[support_rows].max())],
        "initial_support_local_x_bounds_mm": [
            float(physical_x[support].min()), float(physical_x[support].max())],
        "blank_meridian_halo_to_outer_chart_ends_mm": result.receipt["panel"][
            "actual_s_halo_mm"],
        "initial_support_inside_panel_only": True,
        "support_area_is_discrete_grid_measure": True,
    }
    statistics = {
        "initial_area_weighted_mass": initial_mass,
        "final_area_weighted_mass": final_mass,
        "relative_mass_drift": abs(final_mass - initial_mass) / max(initial_mass, 1e-300),
        "mobile_bleed_peak_outside_initial_support": float(
            np.max(result.total_density[~support]) if np.any(~support) else 0.0),
        "bound_core_peak": float(np.max(result.bound_density)),
        "total_peak": float(np.max(result.total_density)),
        "initial_fraction_of_panel_area_nonzero": support_area / (PANEL_WIDTH_MM * PANEL_HEIGHT_MM),
    }
    return result, {
        "initial_linear_rgb": initial_rgb,
        "support": support_receipt,
        "statistics": statistics,
    }


def _spectrum_to_srgb(linear: np.ndarray) -> np.ndarray:
    values = np.clip(np.asarray(linear, dtype=np.float64), 0.0, 1.0)
    encoded = np.where(values <= 0.0031308, 12.92 * values,
                       1.055 * np.power(values, 1.0 / 2.4) - 0.055)
    return np.asarray(np.round(255.0 * np.clip(encoded, 0.0, 1.0)), dtype=np.uint8)


def _font(size: int) -> ImageFont.ImageFont:
    for candidate in ("C:/Windows/Fonts/arial.ttf", "arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _render_unwrapped(result: BlueWhitePanelResult, s_profile: np.ndarray,
                      profile_rzs: np.ndarray, *, component: str,
                      width_px: int = 900, height_px: int = 520) -> np.ndarray:
    panel = result.receipt["panel"]
    x = np.linspace(-PANEL_WIDTH_MM / 2.0, PANEL_WIDTH_MM / 2.0,
                    width_px, dtype=np.float64)
    s = np.linspace(panel["s_bounds_mm"][0], panel["s_bounds_mm"][1],
                    height_px, dtype=np.float64)
    radius = np.interp(s, s_profile, profile_rzs[:, 0])
    theta = panel["center_theta_rad"] + x[None, :] / radius[:, None]
    s_queries = np.broadcast_to(s[:, None], theta.shape)
    if component == "initial":
        density = sample_periodic_field(
            result.initial_density, result.s_centers_mm, result.operator.n_theta,
            s_queries, theta)
    elif component == "spread":
        density = result.sample_density(s_queries, theta, component="total")
    else:
        raise ValueError("component must be initial or spread")
    linear = blue_white_appearance(
        density, glaze_white_linear_rgb=result.glaze_white_linear_rgb,
        tau_rgb=result.tau_rgb)
    return _spectrum_to_srgb(linear)


def _write_preview(result: BlueWhitePanelResult, s_profile: np.ndarray,
                   profile_rzs: np.ndarray) -> None:
    panel_w, panel_h = 900, 520
    margin, gap, header = 28, 24, 96
    footer = 70
    canvas = Image.new("RGB", (2 * panel_w + 2 * margin + gap,
                                header + panel_h + footer), (248, 247, 243))
    draw = ImageDraw.Draw(canvas)
    draw.text((margin, 14), "MET 50899 photo-derived blue chroma on VF bowl candidate",
              fill=(33, 47, 63), font=_font(26))
    draw.text((margin, 53), "One finite 45 × 26 mm sourced panel · no angular tiling · lower-s follows image top",
              fill=(72, 81, 90), font=_font(17))
    labels = (("No added spread · sampled source field", "initial"),
              ("Empirical mobile-phase spread · m=0.25, K=(0.02, 0.08) mm²", "spread"))
    for index, (label, component) in enumerate(labels):
        x0 = margin + index * (panel_w + gap)
        draw.text((x0, 78), label, fill=(48, 56, 66), font=_font(15))
        pixels = _render_unwrapped(result, s_profile, profile_rzs,
                                   component=component, width_px=panel_w,
                                   height_px=panel_h)
        canvas.paste(Image.fromarray(pixels, mode="RGB"), (x0, header))
        draw.rectangle((x0, header, x0 + panel_w - 1,
                        header + panel_h - 1), outline=(166, 168, 168), width=1)
    draw.text((margin, header + panel_h + 18),
              "Already-fired-photo normalized appearance proxy; added spread is stylized, not firing chemistry. "
              "Vase-derived panel on bowl is a new synthetic design.",
              fill=(77, 82, 87), font=_font(14))
    canvas.save(OUT / "bluewhite_panel_unwrapped.png", optimize=True)


def _sample_physical_panel(result: BlueWhitePanelResult, s_profile: np.ndarray,
                           profile_rzs: np.ndarray, s_values: np.ndarray,
                           x_values_mm: np.ndarray, *, component: str) -> np.ndarray:
    radius = np.interp(s_values, s_profile, profile_rzs[:, 0])
    theta = result.receipt["panel"]["center_theta_rad"] + x_values_mm[None, :] / radius[:, None]
    s_query = np.broadcast_to(s_values[:, None], theta.shape)
    field = result.initial_density if component == "initial" else result.total_density
    return sample_periodic_field(field, result.s_centers_mm,
                                 result.operator.n_theta, s_query, theta)


def _write_cross_section_csv_and_plot(s_values: dict[str, dict[str, np.ndarray]],
                                      x_mm: np.ndarray) -> None:
    csv_path = OUT / "density_cross_section_mm.csv"
    center_index = len(next(iter(s_values.values()))["s_mm"]) // 2
    series = [
        ("coarse_initial", "coarse", "initial"),
        ("coarse_spread", "coarse", "spread"),
        ("fine_initial", "fine", "initial"),
        ("fine_spread", "fine", "spread"),
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        stream.write("x_mm," + ",".join(item[0] for item in series) + "\n")
        for j, x in enumerate(x_mm):
            row = [f"{x:.9g}"]
            for _, resolution, component in series:
                row.append(f"{s_values[resolution][component][center_index, j]:.12g}")
            stream.write(",".join(row) + "\n")

    width, height = 1400, 560
    left, right, top, bottom = 92, 30, 46, 84
    image = Image.new("RGB", (width, height), (252, 251, 248))
    draw = ImageDraw.Draw(image)
    draw.text((left, 10), "Centerline density across the physical panel width",
              fill=(35, 47, 61), font=_font(24))
    plot_w = width - left - right
    plot_h = height - top - bottom
    draw.rectangle((left, top, left + plot_w, top + plot_h), outline=(86, 93, 99), width=2)
    for tick in range(6):
        fraction = tick / 5.0
        y = top + int(plot_h * (1.0 - fraction))
        draw.line((left, y, left + plot_w, y), fill=(224, 224, 219), width=1)
        draw.text((left - 52, y - 8), f"{fraction:.1f}", fill=(70, 77, 84), font=_font(13))
    for tick in range(7):
        fraction = tick / 6.0
        x = left + int(plot_w * fraction)
        value = -PANEL_WIDTH_MM / 2.0 + PANEL_WIDTH_MM * fraction
        draw.line((x, top + plot_h, x, top + plot_h + 6), fill=(86, 93, 99), width=1)
        draw.text((x - 18, top + plot_h + 11), f"{value:.0f}", fill=(70, 77, 84), font=_font(13))
    colors = {
        "coarse_initial": (95, 112, 126),
        "coarse_spread": (169, 111, 47),
        "fine_initial": (40, 88, 137),
        "fine_spread": (38, 137, 163),
    }
    labels = {
        "coarse_initial": "coarse · zero spread",
        "coarse_spread": "coarse · m=0.25 spread",
        "fine_initial": "fine · zero spread",
        "fine_spread": "fine · m=0.25 spread",
    }
    for key, resolution, component in series:
        line = s_values[resolution][component][center_index]
        px = left + np.linspace(0, plot_w, len(x_mm))
        py = top + plot_h * (1.0 - np.clip(line, 0.0, 1.0))
        draw.line(list(zip(px.astype(int), py.astype(int))), fill=colors[key], width=3)
    draw.text((left + 5, height - 42), "local arc distance X (mm)",
              fill=(55, 63, 72), font=_font(15))
    legend_x = left + 300
    for index, (key, _, _) in enumerate(series):
        x0 = legend_x + index * 245
        draw.line((x0, height - 30, x0 + 28, height - 30), fill=colors[key], width=3)
        draw.text((x0 + 35, height - 39), labels[key],
                  fill=(61, 67, 74), font=_font(12))
    image.save(OUT / "density_cross_section_mm.png", optimize=True)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    mother, profile_rzs, s_profile, source_density, source_metadata, geometry_metadata = \
        _load_reference_and_source()
    center_s = float(0.5 * s_profile[-1])
    panel_s_low = center_s - PANEL_HEIGHT_MM / 2.0
    panel_s_high = center_s + PANEL_HEIGHT_MM / 2.0

    results: dict[str, BlueWhitePanelResult] = {}
    auxiliary: dict[str, dict[str, Any]] = {}
    for resolution, (n_s, n_theta) in GRID_LEVELS.items():
        result, extras = _build_grid(profile_rzs, s_profile, source_density,
                                     source_metadata, n_s, n_theta)
        results[resolution] = result
        auxiliary[resolution] = extras
        no_spread_rgb = extras["initial_linear_rgb"]
        np.savez_compressed(
            OUT / f"bluewhite_panel_{resolution}.npz",
            profile_rzs_mm=profile_rzs,
            profile_s_recomputed_mm=s_profile,
            s_centers_mm=result.s_centers_mm,
            radius_centers_mm=result.radius_mm,
            theta_centers_rad=result.theta_centers_rad,
            cell_area_mm2_per_theta_cell=result.cell_area_mm2,
            initial_density=result.initial_density,
            bound_density=result.bound_density,
            mobile_density=result.mobile_density,
            total_density=result.total_density,
            zero_spread_linear_rgb=no_spread_rgb,
            spread_linear_rgb=result.linear_rgb,
        )
        (OUT / f"bluewhite_panel_{resolution}_receipt.json").write_text(
            json.dumps({
                "schema": "shardforge.bluewhite_panel_grid_receipt.v2",
                "resolution": resolution,
                "panel_receipt_schema": result.receipt["schema"],
                "source": result.receipt["source"],
                "surface": result.receipt["surface"],
                "panel": result.receipt["panel"],
                "appearance_controls": result.receipt["appearance_controls"],
                "mass": result.receipt["mass"],
                "support_and_halo": extras["support"],
                "statistics": extras["statistics"],
                "grid": result.receipt["grid"],
                "solver_receipt": result.spread_result.receipt,
            }, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8")
        print(f"built {resolution}: grid={n_s}x{n_theta}, "
              f"mass_drift={extras['statistics']['relative_mass_drift']:.3e}")

    fine = results["fine"]
    _write_preview(fine, s_profile, profile_rzs)

    common_s = np.linspace(panel_s_low, panel_s_high, 101, dtype=np.float64)
    common_x = np.linspace(-PANEL_WIDTH_MM / 2.0, PANEL_WIDTH_MM / 2.0,
                           221, dtype=np.float64)
    common_fields: dict[str, dict[str, np.ndarray]] = {}
    for resolution, result in results.items():
        common_fields[resolution] = {
            "s_mm": common_s,
            "initial": _sample_physical_panel(result, s_profile, profile_rzs,
                                               common_s, common_x, component="initial"),
            "spread": _sample_physical_panel(result, s_profile, profile_rzs,
                                              common_s, common_x, component="spread"),
        }
    _write_cross_section_csv_and_plot(common_fields, common_x)

    coarse = results["coarse"]
    coarse_initial = common_fields["coarse"]["initial"]
    fine_initial = common_fields["fine"]["initial"]
    coarse_spread = common_fields["coarse"]["spread"]
    fine_spread = common_fields["fine"]["spread"]
    grid_sensitivity = {
        "comparison_domain": "same physical X/s sample raster over declared panel bounds",
        "sample_shape": list(coarse_initial.shape),
        "initial_density_mean_absolute_difference": float(np.mean(np.abs(coarse_initial - fine_initial))),
        "initial_density_root_mean_square_difference": float(np.sqrt(np.mean((coarse_initial - fine_initial) ** 2))),
        "spread_density_mean_absolute_difference": float(np.mean(np.abs(coarse_spread - fine_spread))),
        "spread_density_root_mean_square_difference": float(np.sqrt(np.mean((coarse_spread - fine_spread) ** 2))),
        "initial_mass_relative_difference_coarse_vs_fine": abs(
            auxiliary["coarse"]["statistics"]["initial_area_weighted_mass"]
            - auxiliary["fine"]["statistics"]["initial_area_weighted_mass"])
            / max(auxiliary["fine"]["statistics"]["initial_area_weighted_mass"], 1e-300),
        "spread_mass_relative_difference_coarse_vs_fine": abs(
            auxiliary["coarse"]["statistics"]["final_area_weighted_mass"]
            - auxiliary["fine"]["statistics"]["final_area_weighted_mass"])
            / max(auxiliary["fine"]["statistics"]["final_area_weighted_mass"], 1e-300),
        "fine_grid_maximum_cells": 256_000,
        "fine_grid_estimated_peak_sparse_working_bytes": fine.receipt["grid"][
            "estimated_peak_working_bytes"],
        "fine_grid_memory_budget_bytes": 512 * 1024 * 1024,
    }

    receipt = {
        "schema": "shardforge.bluewhite_bowl_sourced_panel_study.v2",
        "purpose": "finite photo-derived blue-white appearance panel on the actual sampled VF bowl outer meridian",
        "design_status": "NEW_SYNTHETIC_DESIGN_ON_BOWL_CANDIDATE; vase-derived source panel is not a historical bowl pattern",
        "interpretation_limits": {
            "source_is_already_fired_photo_normalized_appearance_proxy": True,
            "prefire_pigment_recovered": False,
            "camera_lighting_glaze_projection_and_vase_curvature_removed": False,
            "unseen_source_geometry_or_symbolism_inferred": False,
            "complete_circumferential_motif_reconstructed": False,
            "additional_spread_is_stylized_and_may_double_count_original_fired_spread": True,
            "firing_chemistry_or_optical_coefficients_calibrated": False,
            "bowl_candidate_is_source_scan_or_exact_cad_reconstruction": False,
            "bowl_geometry_or_material_mechanics_modified": False,
        },
        "source": {
            "institution": "The Metropolitan Museum of Art",
            "object_id": 50899,
            "title": "Vase with dragon",
            "collection_url": COLLECTION_URL,
            "source_photo_path": str(PHOTO_PATH.relative_to(ROOT)),
            "source_photo_sha256": _sha256(PHOTO_PATH),
            "projection_crop_path": str(PROJECTION_PATH.relative_to(ROOT)),
            "projection_crop_sha256": _sha256(PROJECTION_PATH),
            "mask_path": str(MASK_PATH.relative_to(ROOT)),
            "mask_sha256": _sha256(MASK_PATH),
            "normalized_density_sha256": normalized_density_sha256(source_density),
            "normalized_density_hash_schema": fine.receipt["source"][
                "normalized_density_hash_schema"],
            "normalized_density_hash_input_dtype": fine.receipt["source"][
                "normalized_density_hash_input_dtype"],
            "normalized_density_hash_canonical_dtype": fine.receipt["source"][
                "normalized_density_hash_canonical_dtype"],
            "normalized_density_hash_binds_shape_and_dtype": True,
            "mask_shape_px": list(source_density.shape),
            "mask_semantics": source_metadata["mask_semantics"],
            "mask_pixel_value_range": [float(np.min(source_density)), float(np.max(source_density))],
            "mask_tonal_standard_deviation": float(np.std(source_density)),
            "partial_photo_crop_preserved_without_inpainting_or_repair": True,
        },
        "geometry": geometry_metadata,
        "panel_design": {
            "source_mapping": "X=r(s)*wrapped(theta-theta0), Y=s-s0",
            "metric": "dell^2=(dX-a*dY)^2+dY^2; determinant is one but the map shears",
            "placement_center_s_mm": center_s,
            "placement_center_theta_rad": float(np.pi),
            "physical_arc_width_mm": PANEL_WIDTH_MM,
            "meridian_height_mm": PANEL_HEIGHT_MM,
            "image_top_toward": "lower_s",
            "panel_s_bounds_mm": [panel_s_low, panel_s_high],
            "declared_halo_minimum_mm": 2.0,
            "panel_width_is_less_than_2pi_min_radius": fine.receipt["panel"][
                "panel_band_minimum_radius_mm"] * 2.0 * np.pi > PANEL_WIDTH_MM,
            "piecewise_polyline_max_abs_shear_a_bound": fine.receipt["panel"][
                "piecewise_polyline_max_abs_shear_a_bound"],
            "shear_bound_convention": fine.receipt["panel"]["shear_bound_convention"],
            "azimuthal_seam_away_from_panel": fine.receipt["panel"][
                "periodic_seam_away_from_panel"],
            "one_finite_partial_panel_no_repeat": True,
            "mapping_distortion": fine.receipt["panel"]["curvature_mapping_distortion"],
        },
        "appearance_model": {
            "equation": "total=(1-m)*c0 + exp(duration*A^-1*L)*(m*c0)",
            "solver": "SciPy expm_multiply on conservative metric-aware surface-of-revolution FV graph",
            "diffusivity_s_mm2_per_effective_unit": DIFFUSIVITY_S_MM2_PER_UNIT,
            "diffusivity_theta_mm2_per_effective_unit": DIFFUSIVITY_THETA_MM2_PER_UNIT,
            "effective_s_diffusion_mm2": DURATION * DIFFUSIVITY_S_MM2_PER_UNIT,
            "effective_theta_diffusion_mm2": DURATION * DIFFUSIVITY_THETA_MM2_PER_UNIT,
            "duration_dimensionless_effective_process_index": DURATION,
            "mobile_fraction": MOBILE_FRACTION,
            "bound_fraction": 1.0 - MOBILE_FRACTION,
            "controls_are_empirical_not_measured_material_chemistry": True,
            "boundary_conditions": {"meridian": "no flux at outer chart ends",
                                    "azimuth": "periodic"},
            "post_pde_blur_or_sharpening": False,
            "color_law": "white_linear_rgb * exp(-dimensionless_tau_rgb * normalized_density)",
            "glaze_white_linear_rgb": [0.94, 0.91, 0.84],
            "dimensionless_tau_rgb": [3.04, 2.56, 0.93],
            "color_coefficients_are_calibrated_optical_constants": False,
        },
        "grid_levels": {
            name: {
                "shape_n_s_n_theta": list(result.operator.shape),
                "cells": result.operator.n_cells,
                "ds_mm": result.operator.ds_mm,
                "dtheta_rad": result.operator.dtheta_rad,
                "minimum_radius_mm": float(np.min(result.radius_mm)),
                "maximum_radius_mm": float(np.max(result.radius_mm)),
                "area_weighted_mass": auxiliary[name]["statistics"],
                "support_and_halo": auxiliary[name]["support"],
                "mass_receipt": result.receipt["mass"],
                "budget": result.operator.budget,
                "field_archive": f"bluewhite_panel_{name}.npz",
                "grid_receipt": f"bluewhite_panel_{name}_receipt.json",
            }
            for name, result in results.items()
        },
        "grid_sensitivity": grid_sensitivity,
        "outputs": {
            "unwrapped_preview": "bluewhite_panel_unwrapped.png",
            "density_cross_section_plot": "density_cross_section_mm.png",
            "density_cross_section_csv": "density_cross_section_mm.csv",
        },
    }
    (OUT / "receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8")
    print(json.dumps({
        "output_dir": str(OUT),
        "fine_grid": list(fine.operator.shape),
        "coarse_mass_drift": auxiliary["coarse"]["statistics"]["relative_mass_drift"],
        "fine_mass_drift": auxiliary["fine"]["statistics"]["relative_mass_drift"],
        "grid_sensitivity": grid_sensitivity,
        "preview": str(OUT / "bluewhite_panel_unwrapped.png"),
        "receipt": str(OUT / "receipt.json"),
    }, indent=2))


if __name__ == "__main__":
    main()

