"""Regression tests for the two pattern-stage defects measured in the next-experiment batch.

Class 2 of ``data/a12/reports/next_experiment_batches.json``:

* ``TypeError: float() argument must be a string or a real number, not 'NoneType'`` - raised by
  ``field_context`` for every mother whose chart is **open** (``x_period_mm = None``), i.e. the
  planar charts of the sheet/composite families (V21 ``panel_plane``, V23 ``figurine_plane``);
* ``ValueError: operands could not be broadcast together with shapes (685,984) (685,985)`` -
  ``build_glyph`` compared its frozen raster canvases with a text layout re-derived from
  millimetres, and the snapped texel made ``tile_width_mm * px_per_mm`` exceed the frozen
  integer column count by one ulp.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from synlab.errors import ErrorCode, SynLabError
from synlab.patterns import api
from synlab.patterns.builders import effective_x_period_mm, field_context
from synlab.patterns.fields import WarpField
from synlab.patterns.glyphs import layout_text_run, resolve_font


# ---------------------------------------------------------------------------------------
# open (planar) charts
# ---------------------------------------------------------------------------------------
def test_effective_x_period_uses_the_declared_period_when_there_is_one():
    assert effective_x_period_mm({"x_period_mm": 12.5, "s_range_mm": [0.0, 3.0]}) == 12.5


def test_effective_x_period_falls_back_to_the_profile_span_of_an_open_chart():
    """``ChartFrame.as_dict()`` writes ``x_period_mm = None`` for a planar chart."""
    assert effective_x_period_mm({"name": "figurine_plane", "kind": "planar",
                                  "x_period_mm": None, "s_range_mm": [-44.112084880287796,
                                                                       41.372227459995585]}) == \
        pytest.approx(85.48431234028338, rel=1e-12)


def test_effective_x_period_refuses_a_chart_without_any_scale():
    with pytest.raises(SynLabError) as info:
        effective_x_period_mm({"name": "broken", "x_period_mm": None, "s_range_mm": None})
    assert info.value.code == ErrorCode.SCHEMA_INVALID


def test_field_context_reads_a_frozen_open_chart():
    """The exact call that raised ``float(None)`` in ``patterns.api.evaluate``."""
    meta = {"chart": {"name": "panel_plane", "kind": "planar", "x_period_mm": None,
                      "s_range_mm": [-75.6, 158.8], "s_periodic": False},
            "regions": [{"s_min_mm": -70.0, "s_max_mm": 150.0}], "footprint_mm": 0.29}
    palette = {"body": [0.5, 0.5, 0.5], "body_roughness": 0.6,
               "paints": [[0.2, 0.2, 0.2]], "paint_roughness": 0.4}
    ctx = field_context(meta, palette, WarpField())
    assert ctx.x_period_mm == pytest.approx(234.4, abs=1e-6)
    assert (ctx.s_min_mm, ctx.s_max_mm) == (-70.0, 150.0)
    assert ctx.s_periodic is False


def test_open_chart_recipe_builds_and_evaluates(small_mother, rng_factory):
    """A recipe frozen on the fixture's planar chart must survive ``evaluate``."""
    recipe = api.build_pattern(
        small_mother,
        {"family": "PAT01", "surface_tag": "base", "allow_aux_layers": False},
        rng_factory("planar-chart"))
    assert recipe.meta["chart"]["x_period_mm"] is None, "the fixture chart is open"
    channels = api.evaluate(recipe, small_mother,
                            np.asarray(small_mother.mesh.vertices, dtype=np.float64), "base")
    assert channels.albedo.shape[0] == len(small_mother.mesh.vertices)
    assert np.all(np.isfinite(channels.albedo))
    assert np.all(np.isfinite(channels.roughness))
    assert np.all(np.isfinite(channels.height_mm))


# ---------------------------------------------------------------------------------------
# glyph raster width
# ---------------------------------------------------------------------------------------
#: measured on ``LIN0002_V23_M07_PAT12`` (V23/M07, PAT12): the frozen raster plan
V23_TILE_WIDTH_MM = 122.92036697484887
V23_PX_PER_MM = 8.00518273917405
V23_PLAN_WIDTH_PX = 984
V23_PLAN_HEIGHT_PX = 685


def test_snapped_texel_exceeds_the_frozen_column_count_by_one_ulp():
    product = V23_TILE_WIDTH_MM * V23_PX_PER_MM
    assert product > V23_PLAN_WIDTH_PX
    assert product - V23_PLAN_WIDTH_PX == pytest.approx(1.1368683772161603e-13, rel=1e-3)
    assert math.ceil(product) == V23_PLAN_WIDTH_PX + 1, "the artefact the fix removes"


def test_glyph_layout_matches_the_frozen_plan_width():
    font = resolve_font(None, None)
    layout = layout_text_run(text="A", font=font, font_size_mm=10.0, letter_spacing_mm=1.0,
                             px_per_mm=V23_PX_PER_MM, tile_width_mm=V23_TILE_WIDTH_MM,
                             run_gap_mm=6.0, baseline_s_mm=17.3, s0_mm=-44.1,
                             height_px=V23_PLAN_HEIGHT_PX, width_px=V23_PLAN_WIDTH_PX)
    assert layout.mask.shape == (V23_PLAN_HEIGHT_PX, V23_PLAN_WIDTH_PX)
    # and the mm-derived path (no frozen plan) must land on the same integer
    derived = layout_text_run(text="A", font=font, font_size_mm=10.0, letter_spacing_mm=1.0,
                              px_per_mm=V23_PX_PER_MM, tile_width_mm=V23_TILE_WIDTH_MM,
                              run_gap_mm=6.0, baseline_s_mm=17.3, s0_mm=-44.1,
                              height_px=V23_PLAN_HEIGHT_PX)
    assert derived.mask.shape == (V23_PLAN_HEIGHT_PX, V23_PLAN_WIDTH_PX)


def test_glyph_tile_has_the_shape_of_its_frozen_raster_plan(small_mother, rng_factory):
    recipe = api.build_pattern(small_mother,
                               {"family": "PAT12", "allow_aux_layers": False,
                                "params": {"text": "AB", "font_size_mm": 12.0}},
                               rng_factory("glyph-shape"))
    plan = recipe.params["raster_plan"]
    raster = recipe.params["raster"]
    assert list(raster["shape"]) == [int(plan["height_px"]), int(plan["width_px"])]
    assert raster["shape"][1] == int(plan["width_px"])
    assert raster["x_period_mm"] == pytest.approx(plan["width_px"] / plan["px_per_mm"], rel=1e-12)
    assert raster["meta"]["plan"]["period_exact"] is True
