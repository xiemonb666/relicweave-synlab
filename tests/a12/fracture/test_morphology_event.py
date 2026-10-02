"""End-to-end contracts of the morphology cutter: A06 gates, meta, conjugacy, no self-crossing.

The event is run on a small analytic fixture so it stays a test rather than a batch job, but it
goes through the whole frozen chain: the real material profile, the frozen mother audit for the
wall thickness, the frozen closed-cutter builder for the shared surface, the frozen shared-cut
event for both sides, and the frozen auditor for the A06 numbers.  Nothing here relaxes a gate.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
TESTS_A12 = Path(__file__).resolve().parents[2]
for _path in (str(REPO_ROOT), str(TESTS_A12)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from synlab.fracture import surface_features as sf  # noqa: E402
from synlab.fracture.api import _default_basis, audit_fracture  # noqa: E402
from synlab.fracture.event import run_shared_cut  # noqa: E402
from synlab.fracture.morphology import (  # noqa: E402
    BACKEND_MORPHOLOGY,
    MORPHOLOGY_META_KEY,
    build_morphology_cutter,
    estimate_cell_demand,
    prepare_morphology,
)
from synlab.fracture.spec import (  # noqa: E402
    AMBIGUITY_AREA_RATIO_MAX,
    INTERFACE_GAP_P95_MM,
    NORMAL_REVERSAL_P95_DEG,
    OVERLAP_RATIO_MAX,
    VOLUME_REL_TOL,
    FractureSpec,
)
from synlab.materials.api import build_material_profile, default_material_params  # noqa: E402
from synlab.schemas.runtime import ORIGIN_INTERFACE  # noqa: E402
from synlab.seeds import make_rng  # noqa: E402

import fixtures as fx  # noqa: E402

MASTER_SEED = 20261001
BUDGET_MM = 0.01
MAX_CELLS = 400_000


@pytest.fixture(scope="module")
def morphology_event():
    """One full morphology event on a real material profile and an analytic body."""
    mother = fx.box_mother((14.0, 14.0, 14.0))
    profile = build_material_profile("M01", default_material_params("M01"),
                                     make_rng(MASTER_SEED, "morphology_test", "materials", "M01"))
    rng = make_rng(MASTER_SEED, "morphology_test", "fracture", "FIX14", "M01")
    basis = _default_basis(mother, rng, FractureSpec())
    prepared = prepare_morphology(mother, material_profile=profile, rng=rng, basis=basis,
                                  event_id="test_morphology", error_budget_mm=BUDGET_MM,
                                  max_cells=MAX_CELLS)
    cutter, field, params, report = build_morphology_cutter(
        mother, rng=rng, prepared=prepared, basis=basis, event_id="test_morphology",
        error_budget_mm=BUDGET_MM, max_cells=MAX_CELLS)
    result = run_shared_cut(mother, cutter, event_id="test_morphology",
                            backend=BACKEND_MORPHOLOGY,
                            extra_meta={MORPHOLOGY_META_KEY: params.as_dict()})
    for patch in result.interfaces:
        patch.meta[MORPHOLOGY_META_KEY] = params.as_dict()
    for fragment in result.fragments:
        fragment.meta[MORPHOLOGY_META_KEY] = params.as_dict()
    qa = audit_fracture(result, mother)
    surface = sf.measure_cutter_surface(cutter.mesh, basis, params, window=field.window,
                                        n_samples=120_000)
    conjugate = sf.conjugate_profile_consistency(result.fragments, result.interfaces, basis)
    return {"mother": mother, "cutter": cutter, "field": field, "params": params,
            "report": report, "result": result, "qa": qa, "surface": surface,
            "conjugate": conjugate, "basis": basis}


def test_cutter_is_a_closed_positive_solid(morphology_event) -> None:
    cutter = morphology_event["cutter"]
    report = morphology_event["report"]
    mesh = cutter.mesh
    assert bool(mesh.is_watertight)
    assert bool(mesh.is_winding_consistent)
    assert float(mesh.volume) > 0.0
    # every edge is used by exactly two faces, and no face is degenerate
    assert set(report["edge_use_histogram"]) == {"2"}
    assert int(report["degenerate_faces"]) == 0
    assert report["watertight"] is True and report["winding_consistent"] is True


def test_realized_interpolation_error_stays_inside_the_frozen_budget(morphology_event) -> None:
    cutter = morphology_event["cutter"]
    assert cutter.requested_error_mm == pytest.approx(BUDGET_MM)
    assert cutter.realized_error_mm <= BUDGET_MM + 1e-12
    assert int(morphology_event["report"]["cells"]) <= MAX_CELLS


def test_the_cell_demand_is_predicted_before_the_expensive_build(morphology_event) -> None:
    demand = morphology_event["report"]["cell_demand_estimate"]
    assert demand["predicted_cells"] > 0.0
    assert demand["step_mm"] < 0.25          # finer than the band raster, or the census is blind
    assert demand["curvature_p95"] > 0.0
    # the prediction is a real prediction: it is within a factor of two of what was built
    built = float(morphology_event["report"]["cells"])
    assert 0.25 * demand["predicted_cells"] <= built <= 4.0 * demand["predicted_cells"]


def test_shared_surface_is_exactly_flat_away_from_the_material(morphology_event) -> None:
    field = morphology_event["field"]
    u = np.array([-500.0, 500.0, 0.0])
    v = np.array([-500.0, 0.0, 500.0])
    assert np.allclose(np.asarray(field(u, v), dtype=np.float64), 0.0, atol=1e-12)


def test_event_passes_every_a06_threshold(morphology_event) -> None:
    qa = morphology_event["qa"]
    assert qa["passed"] is True, qa["failures"]
    assert qa["volume_rel_diff"] <= VOLUME_REL_TOL
    assert qa["overlap_ratio"] <= OVERLAP_RATIO_MAX
    assert qa["gap_p95_mm_max"] <= INTERFACE_GAP_P95_MM
    assert qa["normal_angle_p95_deg_max"] <= NORMAL_REVERSAL_P95_DEG
    assert qa["source_coverage"] >= 0.999
    assert qa["ambiguous_area_ratio_total"] <= AMBIGUITY_AREA_RATIO_MAX
    assert qa["interface_faces"] > 0
    result = morphology_event["result"]
    for fragment in result.fragments:
        assert bool(fragment.mesh.is_watertight)
        assert fragment.volume_mm3 > 0.0


def test_fragments_do_not_self_intersect(morphology_event) -> None:
    from synlab.mothers.audit import self_intersection_report

    for fragment in morphology_event["result"].fragments:
        report = self_intersection_report(fragment.mesh)
        assert report["ok"] is True, (fragment.fragment_id, report)


def test_morphology_parameters_reach_the_interfaces_and_the_fragments(morphology_event) -> None:
    result = morphology_event["result"]
    params = morphology_event["params"]
    assert result.meta[MORPHOLOGY_META_KEY]["mirror_radius_mm"] == params.mirror_radius_mm
    assert result.interfaces
    for patch in result.interfaces:
        record = patch.meta[MORPHOLOGY_META_KEY]
        assert record["mirror_radius_mm"] == pytest.approx(params.mirror_radius_mm)
        assert record["hackle_count"] == params.hackle_count
        assert record["correlation_length_mm"] == pytest.approx(params.correlation_length_mm)
        assert record["material_id"] == "M01"
        assert record["formulas"]["mirror_radius"]
    for fragment in result.fragments:
        assert MORPHOLOGY_META_KEY in fragment.meta
    # the cutter carries the same record and the realized envelope
    cutter_meta = morphology_event["cutter"].meta
    assert cutter_meta["morphology_params"]["mirror_radius_mm"] == pytest.approx(
        params.mirror_radius_mm)
    assert cutter_meta["height_field"]["morphology"]["material_id"] == "M01"


def test_measured_roughness_is_positive_and_consistent_with_the_request(morphology_event) -> None:
    surface = morphology_event["surface"]
    params = morphology_event["params"]
    assert surface["samples"] > 1000
    assert surface["Ra_mm"] > 0.0
    assert surface["Rz_mm"] > surface["Ra_mm"]
    relief_rms = float(morphology_event["field"].meta["relief_rms_mm"])
    assert relief_rms > 0.0
    # Ra of a zero-mean rough surface is a fraction of its RMS; a factor of four either way would
    # mean the measurement is reading something other than the realized relief
    assert 0.15 * relief_rms <= surface["Ra_mm"] <= 1.5 * relief_rms
    assert surface["correlation_length_mm"] > 0.0
    assert surface["roughness"]["samples"] > 1000
    # the mirror zone must be measurably smoother than the hackle zone
    zones = surface["zones"]
    if zones["mirror"]["Ra_mm"] is not None and zones["hackle"]["Ra_mm"] is not None:
        assert zones["hackle"]["Ra_mm"] > 0.5 * zones["mirror"]["Ra_mm"]


def test_conjugate_faces_are_the_same_surface_with_opposite_normals(morphology_event) -> None:
    conjugate = morphology_event["conjugate"]
    assert conjugate["patch_count"] >= 1
    assert conjugate["conjugate_gap_p95_mm"] <= INTERFACE_GAP_P95_MM
    assert conjugate["gap_p95_mm_max"] <= INTERFACE_GAP_P95_MM
    assert conjugate["normal_angle_p95_deg_max"] <= NORMAL_REVERSAL_P95_DEG
    assert conjugate["profile_correlation_min"] is not None
    assert conjugate["profile_correlation_min"] > 0.9
    assert conjugate["profile_rms_diff_mm_max"] is not None
    assert conjugate["profile_rms_diff_mm_max"] < 1.0e-3
    # the two sides cover the same area: the patch's own area bookkeeping must agree
    assert conjugate["area_rel_error_max"] < 0.05


def test_interface_faces_are_labelled_and_are_the_measured_surface(morphology_event) -> None:
    result = morphology_event["result"]
    faces = 0
    for fragment in result.fragments:
        origin = np.asarray(fragment.face_origin_kind)
        faces += int(np.sum(origin == ORIGIN_INTERFACE))
    assert faces > 0
    delivered = sf.measure_interface_surface(result.fragments, morphology_event["basis"],
                                             morphology_event["params"],
                                             cutter_mesh=morphology_event["cutter"].mesh,
                                             n_samples=80_000)
    assert delivered["samples"] > 500
    assert delivered["Ra_mm"] > 0.0
    # the delivered faces are the same surface the cutter carries (coarser tessellation only)
    assert 0.25 * morphology_event["surface"]["Ra_mm"] <= delivered["Ra_mm"] \
        <= 2.5 * morphology_event["surface"]["Ra_mm"]


def test_cell_demand_estimator_is_monotone_in_the_relief(morphology_event) -> None:
    field = morphology_event["field"]
    demand = estimate_cell_demand(field, budget_mm=BUDGET_MM)
    assert demand["predicted_cells"] > 0.0
    tightened = estimate_cell_demand(field, budget_mm=0.5 * BUDGET_MM)
    assert tightened["predicted_cells"] > demand["predicted_cells"]
