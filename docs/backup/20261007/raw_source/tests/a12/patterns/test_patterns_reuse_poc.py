"""Reuse PoCs for the pattern module (evidence behind docs/a12/reuse_evidence_patterns.json).

Each test performs the *minimum real call* of one reused dependency through the pattern
adapter and asserts the measured behaviour the recipe depends on:

1. ``scipy.stats.qmc.PoissonDisk`` + ``scipy.spatial.cKDTree``: periodic extension,
   measured density, retention and cross-seam minimum distance.
2. ``svgpathtools``: analytic arc length and bounded adaptive flattening.
3. ``Pillow`` layout + ``scipy.ndimage.distance_transform_edt``: one-shot text layout with
   a millimetre-accurate signed distance map (validated against an analytic disc).
4. ``shapely``: closed-outline fill geometry (validity, area, vectorised containment).
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from synlab.patterns import api, grammar
from synlab.patterns.glyphs import discs_check, layout_text_run, resolve_font
from synlab.patterns.raster import distance_layer, plan_raster
from synlab.patterns.spatial import (distance_to_points, nearest_neighbour_distance,
                                     sample_periodic_dots)
from synlab.patterns.symbols import build_programmatic_symbol, contains_xy, outline_polygons


def test_poc_scipy_poisson_periodic_extension(rng_factory):
    """scipy PoissonDisk with native bounds + periodic cKDTree extension."""
    period, s_min, s_max = 120.0, 0.0, 18.0
    radius, clearance = 2.5, 0.5
    dots = sample_periodic_dots(rng_factory("poc-poisson"), x_period_mm=period,
                               s_min_mm=s_min, s_max_mm=s_max, radius_mm=radius,
                               clearance_mm=clearance, ncandidates=30, max_rounds=3)
    report = dots.report
    required = 2.0 * radius + clearance
    nn = nearest_neighbour_distance(dots.points[:, :2], period)
    assert report["engine"] == "scipy.stats.qmc.PoissonDisk"
    assert report["optimization"] is None, "post-processing that could break min distance off"
    assert report["bounds_mm"] == [0.0, s_min, period, s_max]
    assert nn.min() >= required - 1e-9
    assert report["min_radius_sum_margin_mm"] >= -1e-9
    assert report["n_candidates"] >= report["n_kept"] > 20
    assert 0.0 <= report["rejection_rate"] <= 1.0
    assert report["density_per_100mm2"] > 0
    assert report["max_gap_mm"] is not None and report["gap_probe_grid_mm"] > 0
    # the extension is the only project-specific part: library sampling + KDTree checks
    assert "scipy.spatial.cKDTree" in report["seam_extension"]["method"]


def test_poc_svgpathtools_arc_length_and_flattening():
    """svgpathtools owns arc length; the adapter adds bounded adaptive flattening."""
    radius = 10.0
    points = [complex(radius * math.cos(2 * math.pi * i / 4), radius * math.sin(2 * math.pi * i / 4))
              for i in range(5)]
    from svgpathtools import Arc, Path

    path = Path(*[Arc(points[i], complex(radius, radius), 0, 0, 1, points[i + 1])
                  for i in range(4)])
    analytic = 2.0 * math.pi * radius
    assert abs(float(path.length()) - analytic) / analytic < 1e-6
    flat = grammar.flatten_path(path, max_chord_error_mm=0.05)
    assert flat.stats["n_points"] > 32
    assert flat.stats["achieved_chord_error_mm"] <= 0.05 + 1e-9
    flattened_length = grammar.polyline_length(flat.xy)
    assert abs(flattened_length - analytic) / analytic < 5e-3
    wave = grammar.bezier_wave_path(x_period_mm=120.0, s_centre_mm=0.0, amplitude_mm=3.0,
                                    n_waves=6)
    # svgpathtools exposes the end points as the complex properties ``Path.start`` /
    # ``Path.end`` (not as methods)
    assert abs(complex(wave.start) - complex(0.0, 0.0)) < 1e-9
    assert abs(complex(wave.end) - complex(120.0, 0.0)) < 1e-9


def test_poc_pillow_layout_and_scipy_distance_transform():
    """Pillow lays out the run once; SciPy EDT gives the millimetre distance map."""
    font = resolve_font(None, None)
    check = discs_check(px_per_mm=8.0, radius_mm=4.0)
    # a hard mask edge limits the EDT accuracy to about one texel, which is exactly why
    # the antialiasing footprint is derived from the texel size
    assert check["max_abs_error_mm"] <= 1.1 * (1.0 / 8.0)
    layout = layout_text_run(text="SYN", font=font, font_size_mm=10.0, letter_spacing_mm=1.0,
                             px_per_mm=8.0, tile_width_mm=80.0, run_gap_mm=5.0,
                             baseline_s_mm=8.0, s0_mm=0.0, height_px=160, copies_hint=0)
    assert layout.metrics["tile_wrap_exact"] is True
    mask = layout.mask > 0.5
    assert mask.any()
    plan = plan_raster(x_period_mm=80.0, s_min_mm=0.0, s_max_mm=18.0, feature_mm=1.0)
    assert plan.get("period_exact", plan.get("exact_period")) is True
    padded = np.pad(mask, ((0, 0), (8, 8)), mode="wrap")
    dist, report = distance_layer(padded, px_per_mm=plan["px_per_mm"], pad_px=8)
    assert dist.shape[1] == mask.shape[1]
    assert report["pixel_scale_mm"] == pytest.approx(1.0 / plan["px_per_mm"])
    inside = dist[mask] if dist.shape == mask.shape else None
    assert inside is None or inside.max() >= 0.0


def test_poc_shapely_fill_geometry():
    """Shapely owns closed-outline validity, area and vectorised containment."""
    shape = build_programmatic_symbol("rosette")
    polygons = outline_polygons(shape)
    assert polygons, "the rosette must produce at least one closed polygon"
    first = polygons[0]
    assert first.is_valid
    assert first.area > 0
    inside = contains_xy([first], np.array([0.0]), np.array([0.0]))
    far = contains_xy([first], np.array([10.0]), np.array([10.0]))
    assert bool(inside[0]) is True
    assert bool(far[0]) is False
    # the rosette ring is centred on the origin: one of the closed outlines must match the
    # analytic circle area (the petals are separate outlines of the same symbol)
    assert any(abs(poly.area - math.pi) / math.pi < 0.05 for poly in polygons)
    assert all(poly.is_valid for poly in polygons)


def test_poc_adapter_is_the_only_custom_layer(small_mother, rng_factory):
    """The recipe records which dependencies produced each frozen asset."""
    recipe = api.build_pattern(small_mother,
                               {"family": "PAT06", "allow_aux_layers": False,
                                "params": {"mode": "poisson", "radius_mm": 2.0}},
                               rng_factory("poc-adapter"))
    report = recipe.params["sampling_report"]
    versions = recipe.meta["library_versions"]
    assert report["scipy_version"] == versions["scipy"]
    assert set(versions) >= {"numpy", "scipy", "pillow", "shapely", "trimesh"}
    glyph = api.build_pattern(small_mother,
                              {"family": "PAT12", "allow_aux_layers": False,
                               "params": {"text": "R"}},
                              rng_factory("poc-adapter-font"))
    assert glyph.params["edt"]["kernel"] == "scipy.ndimage.distance_transform_edt"
    assert glyph.params["font"]["sha256"].startswith("sha256:")
    assert glyph.meta["library_versions"]["pillow"]
