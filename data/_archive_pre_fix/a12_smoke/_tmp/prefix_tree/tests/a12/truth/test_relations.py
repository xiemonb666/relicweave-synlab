"""A08 relation fixtures: hand-known 2/3/4-block events must match exactly.

Every expectation here is analytic (axis-aligned boxes, known shared areas), and every
negative case from plan §11.1 has its own fixture: point/edge contact, cavity adjacency,
original assembly contact and outer-surface proximity must never become R2.
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

from synlab.schemas.runtime import RELATION_R1, RELATION_R2, RELATION_TINY, RELATION_UNKNOWN
from synlab.truth.api import finalize_clean_truth, relation_audit

from truth_fixtures import (  # noqa: E402  (tests/a12/truth is on sys.path)
    ambiguous_event,
    assembly_contact_event,
    cavity_adjacency_event,
    four_block_event,
    point_contact_event,
    three_block_event,
    two_block_event,
)


def _pair(clean, a: str, b: str):
    key = (a, b) if a <= b else (b, a)
    return clean.relations[key]


def test_two_block_event_is_exactly_one_r2() -> None:
    mother, event = two_block_event()
    clean = finalize_clean_truth(mother, event)
    assert len(clean.relations) == 1
    edge = _pair(clean, "A", "B")
    assert edge.kind == RELATION_R2
    assert edge.area_mm2 == pytest.approx(400.0)
    assert edge.loss_mask is True and edge.valid is True
    assert edge.interface_id == 0
    assert clean.qa["pass"] is True
    assert relation_audit(clean)["pass"] is True


def test_three_block_event_is_a_chain_not_a_triangle() -> None:
    mother, event = three_block_event()
    clean = finalize_clean_truth(mother, event)
    assert _pair(clean, "A", "B").kind == RELATION_R2
    assert _pair(clean, "B", "C").kind == RELATION_R2
    # A and C never share a fracture surface: R2 is not transitive
    diagonal = _pair(clean, "A", "C")
    assert diagonal.kind == RELATION_R1
    assert diagonal.area_mm2 == 0.0
    assert diagonal.loss_mask is False
    assert relation_audit(clean)["transitively_closed"] is False
    assert clean.qa["r2_pairs"] == 2 and clean.qa["r1_pairs"] == 1


def test_four_block_event_matches_hand_computed_relations() -> None:
    mother, event = four_block_event()
    clean = finalize_clean_truth(mother, event)
    expected_r2 = {("A", "B"), ("C", "D"), ("A", "C"), ("B", "D")}
    expected_r1 = {("A", "D"), ("B", "C")}
    got_r2 = {pair for pair, edge in clean.relations.items() if edge.kind == RELATION_R2}
    got_r1 = {pair for pair, edge in clean.relations.items() if edge.kind == RELATION_R1}
    assert got_r2 == expected_r2
    assert got_r1 == expected_r1
    assert len(clean.relations) == 6
    for pair in expected_r2:
        assert clean.relations[pair].area_mm2 == pytest.approx(400.0)
    assert relation_audit(clean)["pass"] is True


def test_cavity_adjacency_is_never_r2() -> None:
    mother, event = cavity_adjacency_event()
    clean = finalize_clean_truth(mother, event)
    edge = _pair(clean, "A", "B")
    assert edge.kind == RELATION_UNKNOWN
    assert edge.loss_mask is False
    assert edge.valid is False
    assert "cavity" in edge.reason or "outside_material" in edge.reason
    evidence = clean.meta["patch_evidence"]["0"]
    assert evidence["material_inside_fraction"] is not None
    assert evidence["material_inside_fraction"] < 0.9


def test_assembly_contact_is_never_r2() -> None:
    mother, event = assembly_contact_event()
    clean = finalize_clean_truth(mother, event)
    edge = _pair(clean, "A", "B")
    assert edge.kind == RELATION_R1
    assert edge.area_mm2 == 0.0
    assert "not_a_new_fracture_surface" in edge.reason


def test_point_contact_is_tiny_contact_with_measured_area() -> None:
    mother, event = point_contact_event()
    clean = finalize_clean_truth(mother, event)
    edge = _pair(clean, "A", "B")
    assert edge.kind == RELATION_TINY
    assert edge.area_mm2 == pytest.approx(0.02)
    assert edge.loss_mask is False  # the grey zone is not used as a negative


def test_ambiguous_patch_is_unknown_without_loss_mask() -> None:
    mother, event = ambiguous_event()
    clean = finalize_clean_truth(mother, event)
    edge = _pair(clean, "A", "B")
    assert edge.kind == RELATION_UNKNOWN
    assert edge.loss_mask is False
    assert edge.reason


def test_relations_are_symmetric_without_self_loops() -> None:
    mother, event = four_block_event()
    clean = finalize_clean_truth(mother, event)
    for (a, b), edge in clean.relations.items():
        assert a != b
        assert a <= b                       # canonical key: one entry per unordered pair
        assert edge.fragment_a == a and edge.fragment_b == b
        # the mirrored lookup must return the very same edge (symmetric relation)
        assert clean.relations[(b, a) if b <= a else (a, b)] is edge
    # neighbour sets are symmetric too
    for fragment_id in clean.meta["fragment_ids"]:
        for mate in clean.r2_neighbours(fragment_id):
            assert fragment_id in clean.r2_neighbours(mate)


def test_material_area_threshold_scales_with_the_mother() -> None:
    """Both the absolute (0.1 mm²) and the relative (1e-4) threshold must hold."""
    mother, event = two_block_event(area=0.05)  # below the absolute candidate
    clean = finalize_clean_truth(mother, event)
    edge = _pair(clean, "A", "B")
    assert edge.kind == RELATION_TINY
    assert clean.qa["r2_area_threshold_mm2"] >= 0.1
    assert "1e-4" in clean.qa["r2_area_threshold_rule"]
