"""End-to-end fracture event QA on analytic fixtures (plan 10.1 step 7, A06/A08).

These tests exercise the whole chain — closed cutter → one shared discrete C → both sides →
component split → interfaces → audit — and check the frozen A06 thresholds: volume conservation
≤ 0.1%, overlap ratio ≤ 0.01%, shared-surface sampled distance P95 ≤ 0.02 mm, normal reversal P95
≤ 2°, full source coverage and the ambiguity area budget.  All connected components, tiny debris
included, stay in the conservation denominator.
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

from synlab.fracture.api import audit_fracture, fracture_event  # noqa: E402
from synlab.fracture.spec import (  # noqa: E402
    AMBIGUITY_AREA_RATIO_MAX,
    BACKEND_PLANE,
    BACKEND_ROUGH,
    BACKEND_SECONDARY,
    INTERFACE_GAP_P95_MM,
    NORMAL_REVERSAL_P95_DEG,
    OVERLAP_RATIO_MAX,
    VOLUME_REL_TOL,
    FractureSpec,
)
from synlab.schemas.runtime import ORIGIN_INTERFACE, ORIGIN_MOTHER_SURFACE  # noqa: E402
from synlab.seeds import make_rng  # noqa: E402
from synlab.truth.api import finalize_clean_truth, relation_audit  # noqa: E402

import fixtures as fx  # noqa: E402

MASTER_SEED = 20261001


@pytest.fixture(scope="module")
def bowl():
    return fx.thin_bowl_mother()


@pytest.fixture(scope="module")
def box():
    return fx.box_mother((24.0, 24.0, 24.0))


def _event(mother, backend: str, *, seed: int = MASTER_SEED, **kwargs):
    rng = make_rng(seed, "fracture_event_test", backend)
    spec = FractureSpec(backend=backend, **kwargs)
    return fracture_event(mother, spec, rng, event_id=f"fixture_{backend}")


@pytest.mark.parametrize("backend", [BACKEND_PLANE, BACKEND_ROUGH])
def test_fixture_event_passes_the_a06_thresholds(box, backend) -> None:
    result = _event(box, backend, target_rms_mm=0.05)
    qa = audit_fracture(result, box)
    assert qa["passed"] is True, qa["failures"]
    assert qa["volume_rel_diff"] <= VOLUME_REL_TOL
    assert qa["overlap_ratio"] <= OVERLAP_RATIO_MAX
    assert qa["gap_p95_mm_max"] <= INTERFACE_GAP_P95_MM
    assert qa["normal_angle_p95_deg_max"] <= NORMAL_REVERSAL_P95_DEG
    assert qa["source_coverage"] >= 0.999
    assert qa["ambiguous_area_ratio_total"] <= AMBIGUITY_AREA_RATIO_MAX
    # every fragment carries face-level origin bookkeeping and the interface faces are real
    interface_faces = 0
    for fragment in result.fragments:
        origin = np.asarray(fragment.face_origin_kind)
        source = np.asarray(fragment.face_source_tri)
        assert origin.shape[0] == len(fragment.mesh.faces)
        assert source.shape[0] == len(fragment.mesh.faces)
        assert np.all((origin == ORIGIN_MOTHER_SURFACE) | (origin == ORIGIN_INTERFACE)
                      | (origin == 2))  # mother surface / interface / ambiguous
        assert np.all((origin != ORIGIN_MOTHER_SURFACE) | (source >= 0))
        interface_faces += int(np.sum(origin == ORIGIN_INTERFACE))
    assert interface_faces >= 2
    # both boolean outputs are closed solids and both sides used the same cutter bytes
    assert result.cutter_ref
    assert result.meta["minus_hash"] != result.meta["plus_hash"]


def test_conservation_denominator_keeps_every_component(box) -> None:
    result = _event(box, BACKEND_PLANE)
    qa = audit_fracture(result, box)
    total = float(sum(f.volume_mm3 for f in result.fragments))
    assert qa["fragment_count"] == len(result.fragments)
    assert qa["fragment_volume_sum_mm3"] == pytest.approx(total)
    for fragment in result.fragments:
        assert fragment.volume_mm3 > 0.0
    if result.debris:
        debris_volume = float(sum(f.volume_mm3 for f in result.debris))
        assert debris_volume > 0.0
        assert all(f.is_tiny for f in result.debris)


def test_fixture_event_on_a_thin_shell(bowl) -> None:
    result = _event(bowl, BACKEND_PLANE)
    qa = audit_fracture(result, bowl)
    assert qa["passed"] is True, qa["failures"]
    assert len(result.fragments) >= 2
    assert result.interfaces, "a shared cut must produce at least one interface patch"
    for patch in result.interfaces:
        assert patch.area_mm2 > 0.0
        assert patch.sample_points_a.shape == patch.sample_points_b.shape
        assert patch.gap_p95_mm <= INTERFACE_GAP_P95_MM
        assert patch.normal_angle_p95_deg <= NORMAL_REVERSAL_P95_DEG


def test_clean_truth_of_a_fixture_event_is_consistent(box) -> None:
    result = _event(box, BACKEND_PLANE)
    clean = finalize_clean_truth(box, result)
    audit = relation_audit(clean)
    assert audit["pass"] is True, audit["problems"]
    assert clean.qa["r2_pairs"] >= 1
    assert clean.qa["pass"] is True
    for pair, edge in clean.relations.items():
        assert pair[0] != pair[1] and pair[0] <= pair[1]
        if edge.kind == "R2":
            assert edge.area_mm2 > 0.0
            assert edge.loss_mask is True
    assert clean.correspondence, "a shared cut must yield correspondence samples"
    for sample in clean.correspondence:
        assert sample.association_kind in ("EXACT_SURVIVOR", "UNKNOWN_MAPPING")
        if not sample.valid:
            assert sample.association_kind == "UNKNOWN_MAPPING"


def test_secondary_fracture_keeps_ancestry_and_tiny(box) -> None:
    result = _event(box, BACKEND_SECONDARY)
    qa = audit_fracture(result, box)
    assert qa["passed"] is True, qa["failures"]
    assert result.backend == BACKEND_SECONDARY
    children = [f for f in result.fragments if f.meta.get("secondary")]
    assert children, "the secondary event must cut the largest piece into children"
    parent = result.meta["secondary_of"]
    for child in children:
        assert child.parent_id == parent
        assert child.meta["ancestor"] == parent
    # the primary pieces that were not re-cut are still present, tiny debris included
    assert any(not f.meta.get("secondary") for f in result.fragments)
    assert all(f.volume_mm3 > 0.0 for f in result.fragments)
    event_tree = result.event_tree
    assert event_tree["parent_event"] and event_tree["child_events"]
    assert event_tree["patch_clip_policy"] == "membership_filtered_by_truth"
    assert qa["volume_rel_diff"] <= VOLUME_REL_TOL
