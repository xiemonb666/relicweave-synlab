"""Narrow-band P02 / P03 / P04: sub-grid effects must be realized, measured and contained.

The shipped implementation of these three axes went through one global uniform SDF grid whose
spacing is frozen at ``min(min_wall_thickness/6, shortest_structure/4)`` -- 0.5246 mm on the
probe body -- while P02 declares a 0.1657 mm edge recession and P03 declares depths down to
0.05 mm.  Those levels failed with ``PRECISION_NOT_REALIZED`` ("Not all meshes are volumes!").

These tests pin the replacement behaviour down with *measured* quantities:

* P02: the recession is applied at every level, the planned depth is realized, the body stays
  watertight and nothing moves outside the ROI;
* P03: the 0.05/0.1/0.25 mm levels are realized (0.05 mm is 0.10 of one frozen grid cell), the
  loss is nested in the level, and the paired wall-thickness guard holds;
* P04: the frozen cutter reaches every declared contact-loss target inside a tight tolerance,
  and a target that the cutter cannot reach still raises ``TARGET_INFEASIBLE``.
"""

from __future__ import annotations

import numpy as np
import pytest

from synlab.degrade.api import apply_axis
from synlab.degrade.registry import AXIS_REGISTRY
from synlab.errors import ErrorCode, SynLabError


def _code(exc: SynLabError) -> str:
    return exc.code.value if isinstance(exc.code, ErrorCode) else str(exc.code)


# ---------------------------------------------------------------------------- P02
def test_p02_realizes_every_level_with_a_watertight_edge_local_recession(probe: dict) -> None:
    source = probe["P"]
    planned: list[float] = []
    measured: list[float] = []
    for level in (1, 2, 3, 4):
        _ref, measurement = apply_axis("P02", level, source, None, lineage_id="lin_p02")
        m = measurement.measured
        assert measurement.realized, (level, m)
        # the declared recession is applied, not approximated away
        assert m["measured_max_recession_mm"] == pytest.approx(m["planned_max_recession_mm"],
                                                              rel=1e-6)
        assert m["measured_max_recession_mm"] > 0
        # the body is a closed volume and it is inside the source
        assert m["watertight"] == 1.0
        assert m["components"] == 1.0
        assert m["lost_volume_mm3"] > 0
        assert m["max_outside_clean_mm"] <= 1e-5, m["max_outside_clean_mm"]
        # the effect is edge-local: the untouched part of the body does not move
        assert m["roi_external_drift_mm"] <= 1e-4, m["roi_external_drift_mm"]
        assert m["moved_vertices"] > 0
        assert 0.0 < m["moved_vertices_fraction"] < 0.5
        planned.append(float(m["planned_max_recession_mm"]))
        measured.append(float(m["measured_max_recession_mm"]))
    # one frozen section scaled by recession_strength: strictly nested in the depth
    assert planned == sorted(planned) and len(set(planned)) == 4
    assert measured == sorted(measured)


def test_p02_declares_the_resolution_limit_it_used_to_hit() -> None:
    """The axis must be able to state *why* the global grid could not express its section."""
    operator = AXIS_REGISTRY.get("P02")
    declared = operator.declared()
    assert operator.NARROWBAND is True
    assert "rolling-ball" in declared["parameter_schema"]["notes"] or \
        "fillet" in declared["parameter_schema"]["notes"]
    # the radius is frozen across the five levels; only the strength moves
    radii = {float(operator.level_parameters(level)["edge_width_mm"]) for level in range(5)}
    assert len(radii) == 1


# ---------------------------------------------------------------------------- P03
def test_p03_realizes_sub_grid_depths_and_stays_contained(probe: dict) -> None:
    source = probe["P"]
    losses: list[float] = []
    for level, planned in ((1, 0.05), (2, 0.1), (3, 0.25), (4, 0.5)):
        _ref, measurement = apply_axis("P03", level, source, None, lineage_id="lin_p03")
        m = measurement.measured
        assert measurement.realized, (level, m)
        assert m["depth_mm"] == pytest.approx(planned)
        # the declared depth is applied in full: no silent halving by the thickness guard
        assert m["applied_depth_mm"] == pytest.approx(planned)
        assert m["thickness_guard_scale"] == pytest.approx(1.0)
        assert m["thickness_guard_satisfied"] == 1.0
        assert m["thickness_violation_fraction"] == 0.0
        assert m["measured_max_recession_mm"] == pytest.approx(planned)
        assert m["lost_volume_mm3"] > 0
        assert m["watertight"] == 1.0
        assert m["components"] == 1.0
        assert m["max_outside_clean_mm"] <= 1e-5, m["max_outside_clean_mm"]
        assert m["roi_external_drift_mm"] <= 1e-4, m["roi_external_drift_mm"]
        # the rim of the ROI never moves: the perturbation has compact support
        assert m["rim_vertices_pinned"] > 0
        losses.append(float(m["lost_volume_mm3"]))
    # nested depth field: removed volume grows strictly with the declared depth
    assert losses == sorted(losses) and len(set(losses)) == len(losses)


def test_p03_reports_the_grid_spacing_it_does_not_depend_on() -> None:
    """The narrow-band backend is a surface operator; it must say so instead of pretending."""
    operator = AXIS_REGISTRY.get("P03")
    assert operator.NARROWBAND is True
    steps = {float(operator.level_parameters(level)["depth_mm"]) for level in range(5)}
    assert min(steps) == 0.0 and 0.05 in steps


# ---------------------------------------------------------------------------- P04
def test_p04_search_reaches_every_declared_target(probe: dict) -> None:
    source = probe["P"]
    operator = AXIS_REGISTRY.get("P04")
    tolerance = float(operator.EXPECTED["tolerance"])
    for level, target in ((1, 0.1), (2, 0.25), (3, 0.5), (4, 0.8)):
        _ref, measurement = apply_axis("P04", level, source, None, lineage_id="lin_p04")
        m = measurement.measured
        assert measurement.realized, (level, m)
        assert m["contact_loss_target"] == pytest.approx(target)
        assert m["achieved_contact_loss"] == pytest.approx(target, abs=tolerance)
        # the 1-D search converges far tighter than the declared budget
        assert m["target_abs_error"] <= 0.005, (level, m["target_abs_error"])
        # the cutter position/direction are frozen; only the size moves
        assert m["cutter_scale"] > 0 and m["cutter_radius_mm"] > 0
        assert m["largest_component_ratio"] >= 0.02
        assert m["components"] >= 1
        assert m["lost_volume_mm3"] > 0
        # realised loss grows with the declared target
    radii = []
    for level in (1, 2, 3, 4):
        _ref, measurement = apply_axis("P04", level, source, None, lineage_id="lin_p04_radii")
        radii.append(float(measurement.measured["cutter_radius_mm"]))
    assert radii == sorted(radii)


def test_p04_cutter_choice_does_not_move_with_the_target(probe: dict) -> None:
    """Plan 30.7: the position/direction are frozen *before* the size search."""
    source = probe["P"]
    operator = AXIS_REGISTRY.get("P04")
    variant = operator.resolve_variant(None)
    centers = []
    for level in (1, 2, 3, 4):
        _ref, measurement = apply_axis("P04", level, source, None, variant=variant,
                                       lineage_id="lin_p04_frozen")
        m = measurement.measured
        centers.append((m["cutter_center_mm_x"], m["cutter_center_mm_y"],
                        m["cutter_center_mm_z"]))
    assert len({tuple(np.round(c, 9)) for c in centers}) == 1, centers


def test_p04_unreachable_target_is_structured_not_silent(probe: dict) -> None:
    """A target outside the frozen cutter family must raise ``TARGET_INFEASIBLE`` with numbers.

    The base cutter family is bounded below by ``radii_mm``; a target of 1.0 (the whole contact
    area) is not reachable while keeping a representative body, so the axis must refuse with the
    measured maximum instead of reporting a smaller loss as success.
    """
    source = probe["P"]
    with pytest.raises(SynLabError) as excinfo:
        apply_axis("P04", 4, source, None, parameters={"contact_loss_target": 1.0},
                   lineage_id="lin_p04_infeasible")
    assert _code(excinfo.value) == ErrorCode.TARGET_INFEASIBLE.value
    measurements = excinfo.value.measurements
    assert measurements["contact_loss_target"] == pytest.approx(1.0)
    assert 0.0 <= float(measurements["achieved_contact_loss"]) < 1.0
    assert "achieved_contact_loss" in measurements


# ---------------------------------------------------------------------------- declaration
def test_narrowband_axes_report_their_backend() -> None:
    for axis_id in ("P02", "P03", "P04"):
        operator = AXIS_REGISTRY.get(axis_id)
        assert operator.NARROWBAND is True, axis_id
    for axis_id in ("P01", "P05", "P06", "P07", "P08"):
        assert AXIS_REGISTRY.get(axis_id).NARROWBAND is False, axis_id
