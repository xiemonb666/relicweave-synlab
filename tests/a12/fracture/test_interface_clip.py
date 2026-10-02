"""Plan 30.5 interface contracts on the real boolean pipeline (A06 / A08 / A27).

These tests pin the *measurements*, not the implementation: a 12 mm box cut has a hand-computed
new fracture surface of exactly 12 x 12 = 144 mm^2 and two halves of exactly 864 mm^3, so every
number below is either analytic or printed in the failure message.  ``build_interface`` is
exercised through ``fracture_event`` (the production path); the wrapper only records the shared
cutter mesh so the same interface can be asked for a degenerate face set.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
TESTS_A12 = Path(__file__).resolve().parents[2]
for _path in (str(REPO_ROOT), str(TESTS_A12), str(Path(__file__).resolve().parent)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from synlab.fracture import event as event_mod  # noqa: E402
from synlab.fracture import fragment as fragment_mod  # noqa: E402
from synlab.fracture.api import audit_fracture, fracture_event  # noqa: E402
from synlab.fracture.spec import R2_AREA_ABS_MM2, R2_AREA_REL, FractureSpec  # noqa: E402
from synlab.schemas.runtime import RELATION_R2, RELATION_TINY  # noqa: E402
from synlab.truth.api import finalize_clean_truth  # noqa: E402

from fixtures import box_mother  # noqa: E402

HAND_COMPUTED_AREA_MM2 = 144.0
HAND_COMPUTED_HALF_VOLUME_MM3 = 864.0


def _plane_event(extent: float = 12.0, *, capture: bool = False):
    """Run one plane cut; optionally capture the shared cutter mesh used by the event."""
    captured: dict = {}
    original = fragment_mod.build_interface

    def wrapper(**kwargs):
        captured.setdefault("cutter", kwargs["cutter_mesh"])
        captured.setdefault("fragments", (kwargs["fragment_a"], kwargs["fragment_b"]))
        captured.setdefault("faces_a", list(kwargs["faces_a"]))
        captured.setdefault("faces_b", list(kwargs["faces_b"]))
        captured.setdefault("ids", (kwargs["interface_id"], kwargs["source_tri"]))
        return original(**kwargs)

    if capture:
        fragment_mod.build_interface = wrapper
        event_mod.build_interface = wrapper
    try:
        mother = box_mother((extent, extent, extent), mother_id=f"box{extent:g}")
        spec = FractureSpec(backend="plane_shared_cut", plane_point=np.zeros(3),
                            plane_normal=np.array([1.0, 0.0, 0.0]))
        result = fracture_event(mother, spec, np.random.default_rng(4), event_id="E_clip")
    finally:
        fragment_mod.build_interface = original
        event_mod.build_interface = original
    return mother, result, captured


def test_common_clip_is_the_hand_computed_shared_area() -> None:
    """The pair's measured common clipped coverage is the analytic 12 x 12 mm^2 surface."""
    mother, result, _ = _plane_event(12.0)
    qa = audit_fracture(result, mother)
    assert qa["interface_pair_common_clip_area_mm2"] == pytest.approx(
        HAND_COMPUTED_AREA_MM2, rel=1e-6), qa
    assert qa["interface_pair_clip_method"] == "shared_plane", qa
    for patch in result.interfaces:
        assert patch.meta["pair_common_clip_area_mm2"] == pytest.approx(
            HAND_COMPUTED_AREA_MM2, rel=1e-6), patch.meta
        assert patch.meta["common_clip_area_mm2"] > 0.0
        # the measured coverage can never exceed the region its own faces span
        assert patch.meta["common_clip_area_mm2"] <= patch.meta["area_a_mm2"] + 1e-9
        assert patch.meta["common_clip_area_mm2"] <= patch.meta["area_b_mm2"] + 1e-9
    volumes = sorted(round(f.volume_mm3, 6) for f in result.fragments)
    assert volumes == [pytest.approx(HAND_COMPUTED_HALF_VOLUME_MM3, rel=1e-9)] * 2, volumes


def test_pair_measurement_is_reported_next_to_the_chunk_sum() -> None:
    """The pair-level measurement and the sampled chunk sum are *different* numbers, both kept.

    The event splits one interface into sampling chunks whose face pairing leaves part of the
    sheet unpaired (``unmatched_interface_area_mm2``); the pair-level measurement is the physical
    quantity, the chunk sum is what was actually sampled, and neither is silently substituted
    for the other.
    """
    mother, result, _ = _plane_event(12.0)
    qa = audit_fracture(result, mother)
    chunk_sum = qa["interface_common_clip_area_mm2"]
    pair_area = qa["interface_pair_common_clip_area_mm2"]
    assert pair_area == pytest.approx(HAND_COMPUTED_AREA_MM2, rel=1e-6), qa
    assert 0.0 < chunk_sum < pair_area, (chunk_sum, pair_area)
    # the deficit is the part of the shared sheet whose faces the event's greedy pairing never
    # accepted; the event reports it itself and this test keeps both numbers visible
    assert result.meta["unmatched_interface_area_mm2"] > 0.0, result.meta
    assert pair_area - chunk_sum > result.meta["unmatched_interface_area_mm2"], (
        pair_area, chunk_sum, result.meta["unmatched_interface_area_mm2"])
    assert "ok" in qa and "passed" in qa and qa["ok"] == qa["passed"] == (not qa["failures"])


def test_ambiguity_counts_only_unattributable_points() -> None:
    """A clean planar cut has no ambiguous sample and no barycentric escape."""
    mother, result, _ = _plane_event(12.0)
    qa = audit_fracture(result, mother)
    assert qa["ambiguous_area_ratio_max"] == 0.0, qa
    assert qa["ambiguous_area_ratio_total"] == 0.0, qa
    for patch in result.interfaces:
        assert patch.ambiguity_area_ratio == 0.0, patch.meta
        assert patch.ambiguous_area_mm2 == 0.0, patch.meta
        assert patch.meta["bary_min_a"] >= 0.0, patch.meta
        assert patch.meta["bary_min_b"] >= 0.0, patch.meta
        assert patch.meta["barycentric_clamp_total"] == 0.0, patch.meta
        assert patch.meta["ambiguous_reasons"] == {}, patch.meta
        # both sides' reconstructions agree: the shared surface is the same discrete surface
        assert patch.gap_p95_mm <= 1e-9, patch.meta
        assert patch.meta["snapped_area_mm2"] <= 1e-4, patch.meta


def test_no_fake_interface_when_one_side_has_no_shared_face() -> None:
    """One-sided coverage must produce an empty patch, never a fabricated interface."""
    mother, result, captured = _plane_event(12.0, capture=True)
    assert captured, "the event must call build_interface at least once"
    fragment_a, fragment_b = captured["fragments"]
    patch, rows = fragment_mod.build_interface(
        interface_id=999, fragment_a=fragment_a, fragment_b=fragment_b,
        faces_a=list(captured["faces_a"]), faces_b=[], source_tri=int(captured["ids"][1]),
        cutter_mesh=captured["cutter"], sample_target=24)
    assert rows == []
    assert patch.area_mm2 == 0.0
    assert patch.sample_points_a.shape[0] == 0
    assert patch.meta["empty_patch"] is True
    assert "no_common_clipped_coverage" in patch.meta["reason"]
    clean = finalize_clean_truth(mother, result)
    evidence = clean.meta["patch_evidence"]
    assert all(row["area_mm2"] > 0.0 for row in evidence.values()), evidence


def test_r2_area_verdict_is_taken_per_fragment_pair_not_per_patch() -> None:
    """The frozen thresholds apply to the pair's common fracture area (plan 11.1 / 30.5).

    One interface is recorded as several sampling chunks; every chunk here is *below* the
    threshold used in this test while the pair total is above it, so a per-patch verdict would
    silently turn a real R2 into a grey zone.
    """
    mother, result, _ = _plane_event(12.0)
    per_patch = [patch.meta["common_clip_area_mm2"] for patch in result.interfaces]
    threshold = 100.0
    assert max(per_patch) < threshold < sum(per_patch)
    clean = finalize_clean_truth(mother, result, area_abs_mm2=threshold, area_rel=0.0)
    pair = next(iter(clean.relations))
    edge = clean.relations[pair]
    assert edge.kind == RELATION_R2, edge
    assert edge.area_mm2 == pytest.approx(HAND_COMPUTED_AREA_MM2, rel=1e-6), edge
    assert clean.qa["r2_area_level"].startswith("fragment_pair")

    # above the pair total the same geometry is a measured grey zone, never a negative
    grey = finalize_clean_truth(mother, result, area_abs_mm2=1.0e6, area_rel=0.0)
    grey_edge = grey.relations[pair]
    assert grey_edge.kind == RELATION_TINY, grey_edge
    assert grey_edge.valid is True and grey_edge.loss_mask is False, grey_edge
    assert grey_edge.area_mm2 == pytest.approx(HAND_COMPUTED_AREA_MM2, rel=1e-6), grey_edge
    assert grey.qa["tiny_pairs"] == 1 and grey.qa["r2_pairs"] == 0

    # and the frozen defaults still classify the honest box cut as R2
    default = finalize_clean_truth(mother, result)
    assert default.relations[pair].kind == RELATION_R2, default.meta["patch_evidence"]
    assert R2_AREA_ABS_MM2 == 0.1 and R2_AREA_REL == 1.0e-4
