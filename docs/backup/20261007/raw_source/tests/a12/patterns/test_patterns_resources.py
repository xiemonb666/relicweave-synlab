"""Resource honesty: fonts and SVG symbols are real files or structured errors.

Plan 9.5 / 2.4: a missing font or SVG must be an error, never a silent substitution; the
font and SVG hashes are frozen into the recipe; the SVG loader accepts only a restricted
element/attribute set and refuses scripts, external references and oversized files.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest

from synlab.errors import SynLabError
from synlab.patterns import api
from synlab.patterns.glyphs import layout_text_run, resolve_font
from synlab.patterns.symbols import (PROGRAMMATIC_SYMBOLS, build_programmatic_symbol,
                                     load_svg_symbol, svg_restrictions)

VALID_SVG = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">
  <path d="M 1,1 L 9,1 L 9,9 L 1,9 Z"/>
  <path d="M 3,5 C 4,8 6,8 7,5"/>
</svg>
"""


def test_missing_font_is_a_structured_error(small_mother, rng_factory):
    with pytest.raises(SynLabError) as excinfo:
        api.build_pattern(small_mother,
                          {"family": "PAT12", "params": {"font_id": "definitely_absent"}},
                          rng_factory("font-missing"))
    assert excinfo.value.code == "INPUT_UNAVAILABLE"
    with pytest.raises(SynLabError) as excinfo:
        api.build_pattern(small_mother,
                          {"family": "PAT12",
                           "params": {"font_path": str(Path("no") / "such" / "font.ttf")}},
                          rng_factory("font-path-missing"))
    assert excinfo.value.code == "INPUT_UNAVAILABLE"


def test_unreadable_font_file_is_rejected(tmp_path, small_mother, rng_factory):
    bogus = tmp_path / "not_a_font.ttf"
    bogus.write_bytes(b"this is not a font at all" * 8)
    with pytest.raises(SynLabError) as excinfo:
        api.build_pattern(small_mother,
                          {"family": "PAT12", "params": {"font_path": str(bogus)}},
                          rng_factory("font-bogus"))
    assert excinfo.value.code == "INPUT_UNAVAILABLE"


def test_glyph_recipe_freezes_the_real_font(small_mother, rng_factory):
    recipe = api.build_pattern(small_mother,
                               {"family": "PAT12", "allow_aux_layers": False,
                                "params": {"text": "AB", "font_size_mm": 12.0}},
                               rng_factory("glyph-real"))
    font = recipe.params["font"]
    path = Path(font["path"])
    assert path.is_file(), "the frozen font must be a real file"
    digest = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    assert font["sha256"] == digest
    assert font["license_ref"]
    assert recipe.params["layout_frozen_once"] is True
    assert recipe.params["raster"]["rgb_png_b64"]
    assert recipe.params["rings"][0]["copies"] >= 1
    assert recipe.params["rings"][0]["tile_wrap_exact"] is True
    assert recipe.params["raster_plan"]["px_per_mm"] > 0
    assert recipe.params["edt_scale_check"]["max_abs_error_mm"] < 1.0


def test_font_registry_reports_its_sources():
    font = resolve_font(None, None)
    assert Path(font.path).is_file()
    assert font.sha256.startswith("sha256:")
    assert font.source
    assert font.license_ref


def test_layout_upholds_pillow_metrics():
    font = resolve_font(None, None)
    layout = layout_text_run(text="ABC", font=font, font_size_mm=8.0, letter_spacing_mm=1.0,
                             px_per_mm=8.0, tile_width_mm=60.0, run_gap_mm=4.0,
                             baseline_s_mm=10.0, s0_mm=0.0, height_px=200, copies_hint=0)
    metrics = layout.metrics
    assert metrics["copies"] >= 1
    assert metrics["pitch_mm"] > 0
    assert metrics["run_width_mm"] > 0
    assert metrics["tile_wrap_exact"] is True
    assert metrics["layout_api"].startswith("PIL.ImageFont")
    assert layout.mask.max() > 0


def test_svg_symbol_loads_and_is_restricted(tmp_path):
    svg = tmp_path / "symbol.svg"
    svg.write_text(VALID_SVG, encoding="utf-8")
    shape = load_svg_symbol(str(svg), license_ref="CC0-1.0 (test fixture)",
                            max_file_bytes=4096, max_elements=4, max_segments=64)
    assert shape.source == "svg_path"
    assert shape.resource_hash.startswith("sha256:")
    assert len(shape.outlines) >= 2
    restrictions = shape.meta["restrictions"]
    assert restrictions["allowed_elements"] == ["path", "svg"]
    assert restrictions["path_parser"] == "svgpathtools.parse_path"
    assert "rejected" in restrictions["external_references"]


def test_svg_with_script_is_rejected(tmp_path):
    svg = tmp_path / "evil.svg"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script>'
                   '<path d="M0,0 L1,1"/></svg>', encoding="utf-8")
    with pytest.raises(SynLabError) as excinfo:
        load_svg_symbol(str(svg), license_ref="unknown")
    assert excinfo.value.code == "SCHEMA_INVALID"
    assert "script" in excinfo.value.message


def test_svg_with_external_reference_is_rejected(tmp_path):
    svg = tmp_path / "href.svg"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" '
                   'xmlns:xlink="http://www.w3.org/1999/xlink">'
                   '<use xlink:href="http://example.com/x.svg#a"/></svg>', encoding="utf-8")
    with pytest.raises(SynLabError) as excinfo:
        load_svg_symbol(str(svg), license_ref="unknown")
    assert excinfo.value.code == "SCHEMA_INVALID"


def test_svg_with_entity_and_oversize_are_rejected(tmp_path):
    entity = tmp_path / "entity.svg"
    entity.write_text('<!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
                      '<svg xmlns="http://www.w3.org/2000/svg"><path d="M0,0 L1,1"/></svg>',
                      encoding="utf-8")
    with pytest.raises(SynLabError) as excinfo:
        load_svg_symbol(str(entity), license_ref="unknown")
    assert excinfo.value.code == "SCHEMA_INVALID"
    big = tmp_path / "big.svg"
    big.write_text("<!--" + "x" * 5000 + "-->"
                   + VALID_SVG, encoding="utf-8")
    with pytest.raises(SynLabError) as excinfo:
        load_svg_symbol(str(big), license_ref="unknown", max_file_bytes=1024)
    assert excinfo.value.code == "SCHEMA_INVALID"
    assert "byte limit" in excinfo.value.message


def test_svg_missing_file_is_an_input_error():
    with pytest.raises(SynLabError) as excinfo:
        load_svg_symbol("absolutely/not/here.svg", license_ref="x")
    assert excinfo.value.code == "INPUT_UNAVAILABLE"


def test_svg_symbol_needs_a_licence(small_mother, tmp_path, rng_factory):
    svg = tmp_path / "symbol.svg"
    svg.write_text(VALID_SVG, encoding="utf-8")
    with pytest.raises(SynLabError):
        api.build_pattern(small_mother,
                          {"family": "PAT11",
                           "params": {"source": "svg_path", "svg_path": str(svg)}},
                          rng_factory("svg-no-license"))
    recipe = api.build_pattern(
        small_mother,
        {"family": "PAT11", "allow_aux_layers": False,
         "params": {"source": "svg_path", "svg_path": str(svg),
                    "license_ref": "CC0-1.0 (test fixture)", "size_mm": 12.0,
                    "count_around": 4, "max_file_bytes": 4096, "max_segments": 64}},
        rng_factory("svg-with-license"))
    assert recipe.params["symbol_source"] == "svg_path"
    assert recipe.params["license_ref"] == "CC0-1.0 (test fixture)"
    assert recipe.params["resource_hash"].startswith("sha256:")
    assert recipe.params["shape_validity"]["n_outlines"] >= 2


@pytest.mark.parametrize("symbol_id", sorted(PROGRAMMATIC_SYMBOLS))
def test_programmatic_symbols_are_real_vector_geometry(symbol_id):
    shape = build_programmatic_symbol(symbol_id)
    assert shape.outlines
    assert shape.resource_hash.startswith("sha256:")
    assert shape.meta["n_points"] > 8
    assert all(length > 0 for length in shape.meta["path_lengths"])
    assert shape.license_ref


def test_symbol_recipe_records_source_and_validity(small_mother, rng_factory):
    recipe = api.build_pattern(small_mother,
                               {"family": "PAT11", "allow_aux_layers": False,
                                "params": {"symbol_id": "rosette", "count_around": 6,
                                           "size_mm": 14.0}},
                               rng_factory("symbol-programmatic"))
    assert recipe.params["symbol_source"] == "programmatic"
    validity = recipe.params["shape_validity"]
    assert validity["fill_area_mm2"] > 0
    assert validity["size_mm"] == 14.0
    assert abs(validity["bbox_width_mm"] - 14.0) < 1.0
    assert len(recipe.params["placements"]) == 6
    assert recipe.params["shape_validity"]["n_closed_polygons"] >= 1


def test_symbol_fill_uses_shapely_containment(small_mother, rng_factory):
    recipe = api.build_pattern(small_mother,
                               {"family": "PAT11", "allow_aux_layers": False,
                                "params": {"symbol_id": "lozenge_trefoil", "fill": True,
                                           "stroke": True, "count_around": 2, "size_mm": 16.0}},
                               rng_factory("symbol-fill"))
    placement = recipe.params["placements"][0]
    period = recipe.meta["chart"]["x_period_mm"]
    from synlab.patterns.api import pattern_field
    from synlab.patterns.symbols import SymbolShape, outline_polygons

    shape = SymbolShape.from_payload(recipe.params["shape"])
    polygons = outline_polygons(shape)
    assert polygons
    # a point that Shapely reports inside the outline must be painted once it is moved to
    # the chart frame of the placement
    point = polygons[0].representative_point()
    x_mm = (placement["x_mm"] + point.x * placement["scale"]) % period
    s_mm = placement["s_mm"] + point.y * placement["scale"]
    field = pattern_field(recipe, np.array([x_mm]), np.array([s_mm]))
    assert field.coverage[0] > 0.5


def test_svg_restrictions_are_documented():
    restrictions = svg_restrictions(max_file_bytes=1024, max_elements=2, max_segments=8)
    assert restrictions["max_file_bytes"] == 1024
    assert restrictions["max_elements"] == 2
    assert restrictions["max_segments"] == 8
    assert "on" in restrictions["forbidden_attribute_prefixes"]
    assert "xml.etree.ElementTree" in restrictions["xml_parser"]
