"""Implicit-sheet event contract: conservation, conjugacy, gap/normal, coverage, ambiguity.

Run on the analytic box fixture, where the whole pipeline is fast enough for a test but the
geometry is real (an oblique plane cutting a closed solid).  Every threshold is the frozen A06 one.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixtures as fx  # noqa: E402

from synlab.fracture.api import audit_fracture  # noqa: E402
from synlab.fracture.implicit.assembler import assemble_implicit_event  # noqa: E402
from synlab.fracture.implicit.backend import build_implicit_cutter  # noqa: E402
from synlab.fracture.spec import (  # noqa: E402
    AMBIGUITY_AREA_RATIO_MAX,
    DEFAULT_ERROR_BUDGET_MM,
    INTERFACE_GAP_P95_MM,
    NORMAL_REVERSAL_P95_DEG,
    OVERLAP_RATIO_MAX,
    VOLUME_REL_TOL,
)
from synlab.materials.api import build_material_profile, default_material_params  # noqa: E402
from synlab.seeds import make_rng  # noqa: E402

LIN = "a12_fracture_implicit_test"


@pytest.fixture(scope="module")
def event():
    mother = fx.box_mother((12.0, 12.0, 12.0), mother_id="implicit_event")
    profile = build_material_profile("M01", default_material_params("M01"),
                                     make_rng(20261001, LIN, "material"))
    cutter, field, params, report = build_implicit_cutter(
        mother, material_profile=profile, rng=make_rng(20261001, LIN, "build"),
        event_id="contract", error_budget_mm=DEFAULT_ERROR_BUDGET_MM,
        options={"max_sheet_triangles": 60_000})
    result = assemble_implicit_event(mother, cutter, event_id="contract",
                                     backend="implicit_sheet_cut")
    audit = audit_fracture(result, mother)
    return mother, cutter, result, audit


def test_event_produces_two_positive_volume_halves(event) -> None:
    _mother, _cutter, result, _audit = event
    assert len(result.fragments) == 2
    for fragment in result.fragments:
        assert float(fragment.volume_mm3) > 0.0
        assert bool(fragment.mesh.is_watertight) is True
        assert bool(fragment.mesh.is_winding_consistent) is True
    sides = sorted(int(f.face_side[0]) for f in result.fragments)
    assert sides == [-1, 1]


def test_volume_is_conserved_and_the_halves_do_not_overlap(event) -> None:
    _mother, _cutter, _result, audit = event
    assert float(audit["volume_rel_diff"]) <= VOLUME_REL_TOL
    assert float(audit["overlap_ratio"]) <= OVERLAP_RATIO_MAX
    assert float(audit["mother_volume_mm3"]) == pytest.approx(
        float(audit["fragment_volume_sum_mm3"]), rel=VOLUME_REL_TOL)


def test_shared_surface_gap_and_normal_thresholds_hold(event) -> None:
    _mother, _cutter, _result, audit = event
    assert float(audit["gap_p95_mm_max"]) <= INTERFACE_GAP_P95_MM
    assert float(audit["normal_angle_p95_deg_max"]) <= NORMAL_REVERSAL_P95_DEG
    assert float(audit["interface_area_rel_error_max"]) <= 1.0e-3


def test_conjugate_points_are_bit_identical(event) -> None:
    """The two halves consume one sheet, so the conjugate points must coincide to round-off."""
    _mother, _cutter, result, _audit = event
    assert result.interfaces, "the event must record an interface patch"
    from synlab.fracture import surface_features as sf

    basis = result.meta["basis"]
    conjugate = sf.conjugate_profile_consistency(list(result.fragments), result.interfaces, basis)
    assert conjugate["patch_count"] >= 1
    assert float(conjugate["conjugate_gap_p95_mm"]) <= 1.0e-6
    assert float(conjugate["gap_p95_mm_max"]) <= INTERFACE_GAP_P95_MM
    assert float(conjugate["area_rel_error_max"]) <= 1.0e-6
    for patch in result.interfaces:
        gap = np.linalg.norm(patch.sample_points_a - patch.sample_points_b, axis=1)
        assert float(np.percentile(gap, 95)) <= 1.0e-6
        assert int(patch.meta["pair_count"]) > 0
        assert patch.sample_points_a.shape == patch.sample_points_b.shape


def test_provenance_coverage_and_ambiguity_are_inside_the_frozen_gates(event) -> None:
    _mother, _cutter, _result, audit = event
    assert float(audit["source_coverage"]) >= 0.999
    assert float(audit["ambiguous_area_ratio_total"]) <= AMBIGUITY_AREA_RATIO_MAX
    assert float(audit["ambiguous_area_ratio_max"]) <= AMBIGUITY_AREA_RATIO_MAX
    assert bool(audit["passed"]) is True, audit.get("failures")


def test_interface_faces_really_lie_on_the_sheet(event) -> None:
    """Every face the classifier calls INTERFACE is inside the realized interpolation budget."""
    _mother, cutter, result, _audit = event
    from synlab.fracture.implicit.assembler import sheet_distance

    budget = float(cutter.realized_error_mm) * (1.0 + 1e-6) + 1.0e-9
    checked = 0
    for fragment in result.fragments:
        origin = np.asarray(fragment.face_origin_kind)
        ids = np.nonzero(origin == 1)[0]
        assert ids.size > 0
        centroids = np.asarray(fragment.mesh.triangles_center, dtype=np.float64)[ids]
        distance, _local = sheet_distance(cutter.basis, cutter.h_fn, centroids)
        assert float(np.percentile(distance, 95)) <= budget
        checked += int(ids.size)
    assert checked > 0


def test_event_record_carries_the_frozen_hash_and_the_implicit_meta(event) -> None:
    _mother, cutter, result, _audit = event
    from synlab.fracture.booleans import mesh_hash

    assert result.cutter_ref == mesh_hash(cutter.mesh)
    assert result.event_tree["cutter"]["triangles"] == int(cutter.triangles)
    assert result.meta["basis_id"] == cutter.basis.basis_id
    for fragment in result.fragments:
        assert fragment.meta["cutter_hash"] == result.cutter_ref
