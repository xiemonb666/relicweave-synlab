"""Geometry: PAT14/PAT15 really displace the complete mother, appearance-only families do not.

The checks are existence *and* honesty: the volume must move in the direction the policy
claims, no face may flip, the body stays watertight, the mesh hash changes, and a
``normal map`` is never substituted (``appearance_only_normal_map`` stays ``False``).
"""

from __future__ import annotations

import numpy as np
import pytest
import trimesh

from synlab.errors import SynLabError
from synlab.patterns import api
from synlab.patterns.serialize import geometry_hash


def _hash(mother) -> str:
    return geometry_hash(np.asarray(mother.mesh.vertices), np.asarray(mother.mesh.faces))


def test_relief_adds_material(small_mother, rng_factory):
    spec = {"family": "PAT14", "allow_aux_layers": False,
            "params": {"motif": "blobs", "height_mm": 0.6, "mask_feather_mm": 1.5}}
    recipe = api.build_pattern(small_mother, spec, rng_factory("geom-relief"))
    assert recipe.params["wall_guard"]["feasible"] is True
    before_hash = _hash(small_mother)
    out = api.apply_pattern_geometry(small_mother, recipe, np.random.default_rng(3),
                                     max_faces=200_000)
    evidence = out.meta["pattern_geometry"]
    assert out is not small_mother
    assert _hash(out) != before_hash
    assert evidence["applied"] is True
    assert evidence["mode"] == "relief"
    assert evidence["vertex_displacement_max_mm"] > 0.0
    assert evidence["n_vertices_displaced"] > 0
    assert evidence["volume_delta_mm3"] > 0.0, "relief must add material"
    assert evidence["flipped_faces"] == 0
    assert evidence["watertight_after"] is True
    assert evidence["appearance_only_normal_map"] is False
    assert evidence["refinement"]["refined"] is True
    assert evidence["refinement"]["target_edge_mm"] < evidence["refinement"]["edge_before"]["p50_mm"]
    assert np.asarray(out.face_surface_tag).shape[0] == out.mesh.faces.shape[0]
    assert out.mesh.is_watertight


def test_engraving_removes_material(small_mother, rng_factory):
    spec = {"family": "PAT15", "allow_aux_layers": False,
            "params": {"curve_family": "stripe", "depth_mm": 0.6, "line_width_mm": 1.5}}
    recipe = api.build_pattern(small_mother, spec, rng_factory("geom-engrave"))
    before_hash = _hash(small_mother)
    out = api.apply_pattern_geometry(small_mother, recipe, np.random.default_rng(4),
                                     max_faces=200_000)
    evidence = out.meta["pattern_geometry"]
    assert _hash(out) != before_hash
    assert evidence["mode"] == "engrave"
    assert evidence["vertex_displacement_max_mm"] > 0.0
    assert evidence["volume_delta_mm3"] < 0.0, "engraving must remove material"
    assert evidence["flipped_faces"] == 0
    assert evidence["watertight_after"] is True
    assert recipe.params["crossing_policy"] == "max_not_sum"
    assert "NOT_IMPLEMENTED" in evidence["boolean_tool_route"]


def test_engraving_crossing_does_not_double_the_depth(small_mother, rng_factory):
    spec = {"family": "PAT15", "allow_aux_layers": False,
            "params": {"curve_family": "grid", "depth_mm": 0.5, "line_width_mm": 1.5,
                       "spacing_mm": 12.0}}
    recipe = api.build_pattern(small_mother, spec, rng_factory("geom-grid"))
    points = np.asarray(small_mother.mesh.vertices, dtype=np.float64)
    channels = api.evaluate(recipe, small_mother, points, "outer_wall")
    depth = float(recipe.meta["height"]["amplitude_mm"])
    assert np.isclose(np.abs(channels.height_mm).min(), 0.0, atol=1e-6)
    assert np.abs(channels.height_mm).max() <= depth + 1e-6
    assert float(channels.height_mm.min()) >= -depth - 1e-6


def test_appearance_only_families_do_not_touch_the_geometry(small_mother, recipe_factory):
    before = _hash(small_mother)
    for family_id in ("PAT01", "PAT03", "PAT06", "PAT11", "PAT13"):
        recipe = recipe_factory(small_mother, family_id, 1, allow_aux_layers=False)
        out = api.apply_pattern_geometry(small_mother, recipe, np.random.default_rng(5))
        assert out is small_mother, f"{family_id} must return the identical mother object"
    assert _hash(small_mother) == before


def test_engraving_on_a_thin_wall_is_rejected(thin_wall_mother, rng_factory):
    # a wide groove keeps the feature representable at the sample density below, so the
    # rejection that fires is the wall-thickness guard and not the resolution guard
    spec = {"family": "PAT15", "allow_aux_layers": False,
            "params": {"curve_family": "stripe", "depth_mm": 2.0, "line_width_mm": 2.5,
                       "spacing_mm": 20.0}}
    recipe = api.build_pattern(thin_wall_mother, spec, rng_factory("geom-thin"))
    with pytest.raises(SynLabError) as excinfo:
        api.apply_pattern_geometry(thin_wall_mother, recipe, np.random.default_rng(6),
                                   sample_density=0.5, max_faces=200_000)
    assert excinfo.value.code == "TARGET_INFEASIBLE"
    measurements = excinfo.value.measurements
    assert measurements["max_abs_height_mm"] > measurements["allowed_mm"]
    assert measurements["wall_thickness_mm"] > 0


def test_relief_beyond_the_wall_fraction_is_rejected(small_mother, rng_factory):
    spec = {"family": "PAT14", "allow_aux_layers": False,
            "params": {"motif": "blobs", "height_mm": 1.4}}
    recipe = api.build_pattern(small_mother, spec, rng_factory("geom-too-deep"))
    assert recipe.params["wall_guard"]["feasible"] is False
    audit = api.audit_pattern(recipe, small_mother, n_pairs=16, geometry_probe=True,
                              scale_samples=0)
    geometry = audit["geometry"]
    assert geometry["status"] == "GUARD_REJECTED"
    assert geometry["pass"] is True
    assert geometry["guard_code"] == "TARGET_INFEASIBLE"


def test_refinement_can_be_disabled_and_then_reports_a_precision_error(coarse_mother,
                                                                      rng_factory):
    spec = {"family": "PAT15", "allow_aux_layers": False,
            "params": {"curve_family": "stripe", "depth_mm": 0.4, "line_width_mm": 1.0,
                       "spacing_mm": 8.0}}
    recipe = api.build_pattern(coarse_mother, spec, rng_factory("geom-coarse"))
    with pytest.raises(SynLabError) as excinfo:
        api.apply_pattern_geometry(coarse_mother, recipe, np.random.default_rng(7),
                                   allow_refine=False)
    assert excinfo.value.code == "PRECISION_NOT_REALIZED"
    assert excinfo.value.measurements["edge_p50_mm"] > 0


def test_sample_density_controls_the_refinement_rule(small_mother, rng_factory):
    spec = {"family": "PAT15", "allow_aux_layers": False,
            "params": {"curve_family": "stripe", "depth_mm": 0.4, "line_width_mm": 1.2}}
    recipe = api.build_pattern(small_mother, spec, rng_factory("geom-density"))
    out = api.apply_pattern_geometry(small_mother, recipe, np.random.default_rng(8),
                                     sample_density=0.5, max_faces=200_000)
    rule = out.meta["pattern_geometry"]["refinement"]["rule"]
    assert "sample_density" in rule
    assert out.meta["pattern_geometry"]["appearance_only_normal_map"] is False


def test_geometry_is_applied_to_the_complete_body(small_mother, rng_factory):
    """The displaced vertex set spans the whole body, not just a picked fragment."""
    spec = {"family": "PAT14", "allow_aux_layers": False,
            "params": {"motif": "bands", "height_mm": 0.5}}
    recipe = api.build_pattern(small_mother, spec, rng_factory("geom-complete"))
    out = api.apply_pattern_geometry(small_mother, recipe, np.random.default_rng(9),
                                     max_faces=100_000)
    evidence = out.meta["pattern_geometry"]
    assert evidence["n_vertices_total"] == evidence["refinement"].get(
        "vertices_after", evidence["n_vertices_total"])
    assert evidence["n_vertices_total"] > small_mother.mesh.vertices.shape[0]
    assert 0 < evidence["n_vertices_displaced"] <= evidence["n_vertices_total"]
    assert evidence["per_tag"], "per surface tag displacement statistics must be recorded"
    assert all(entry["n_vertices"] > 0 for entry in evidence["per_tag"].values())
    assert trimesh.Trimesh(vertices=out.mesh.vertices, faces=out.mesh.faces).is_watertight
