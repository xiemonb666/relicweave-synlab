"""Independent end-to-end verification of the real fracture → truth path (A08/A27).

Written by a **verification** pass, not by the module author: every expectation is either an
analytic fact or a measurement that is printed in the failure message, so the file stays
useful when it fails.  The hand-built fixtures live in ``test_relations.py``; this file
exercises the actual boolean/interface pipeline.

The single remaining ``xfail(strict=True)`` test below is a *documented defect* of the fracture
event builder (``synlab/fracture/event.py``): it overwrites ``patch.area_mm2`` with the greedy
face-pairing overlap sum and its pairing leaves 8.25 mm^2 of the shared sheet unpaired, so the
sum over *sampling chunks* still cannot reach the analytic 144 mm^2 even though the pair-level
measurement (which the R2 verdict uses) is exact.  ``strict=True`` means fixing that defect turns
the test into XPASS, i.e. a failing test, so it cannot be silently ignored or deleted.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
TESTS_A12 = Path(__file__).resolve().parents[2]
TESTS_TRUTH = Path(__file__).resolve().parent
for _path in (str(REPO_ROOT), str(TESTS_A12), str(TESTS_TRUTH)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from synlab.fracture.api import audit_fracture, fracture_event  # noqa: E402
from synlab.fracture.spec import (  # noqa: E402
    AMBIGUITY_AREA_RATIO_MAX,
    INTERFACE_GAP_P95_MM,
    NORMAL_REVERSAL_P95_DEG,
    OVERLAP_RATIO_MAX,
    VOLUME_REL_TOL,
    FractureSpec,
)
from synlab.schemas.runtime import CleanTruth, RELATION_R2  # noqa: E402
from synlab.storage.store import AssetStore  # noqa: E402
from synlab.truth.api import (  # noqa: E402
    build_labels,
    commit_truth,
    finalize_clean_truth,
    load_truth,
)

from fracture.fixtures import box_mother  # noqa: E402  (tests/a12 is on sys.path)
from truth_fixtures import two_block_event  # noqa: E402

#: A27 in ``configs/a12/qa_protocol_v1.json`` — the ambiguity budget the QA protocol freezes.
PROTOCOL_AMBIGUITY_MAX = 0.05
PLANE = np.array([1.0, 0.0, 0.0])
ORIGIN = np.zeros(3)

#: a 12 mm box cut through its middle: the new fracture surface is exactly 12 x 12 mm^2
HAND_COMPUTED_INTERFACE_AREA = 144.0


def _plane_event(mother, *, event_id: str = "E_plane", seed: int = 4):
    spec = FractureSpec(backend="plane_shared_cut", plane_point=ORIGIN, plane_normal=PLANE)
    return fracture_event(mother, spec, np.random.default_rng(seed), event_id=event_id)


def _edge(clean: CleanTruth, a: str, b: str):
    """Look up one unordered pair (the store uses one canonical key per pair)."""
    return clean.relations.get((a, b)) or clean.relations.get((b, a))


def _patch_row(patch) -> str:
    meta = patch.meta
    return (f"patch {patch.interface_id}: area={patch.area_mm2:.4g} mm2 "
            f"samples={meta.get('samples')} faces_a={len(meta.get('faces_a', []))} "
            f"faces_b={len(meta.get('faces_b', []))} "
            f"ambiguous_samples={meta.get('ambiguous_samples')} "
            f"ambiguity_area_ratio={patch.ambiguity_area_ratio:.4g} "
            f"gap_p95={patch.gap_p95_mm:.3e} mm "
            f"normal_p95={patch.normal_angle_p95_deg:.3e} deg "
            f"bary_min_a={meta.get('bary_min_a')} bary_min_b={meta.get('bary_min_b')}")


# ---------------------------------------------------------------------------- geometry QA
def test_plane_event_meets_every_a06_threshold() -> None:
    """Volume, overlap, shared-face distance and normal reversal on a hand-known 2-block cut."""
    mother = box_mother((12.0, 12.0, 12.0), mother_id="box12")
    result = _plane_event(mother)
    audit = audit_fracture(result, mother)
    assert audit["volume_rel_diff"] <= VOLUME_REL_TOL, audit
    assert audit["overlap_ratio"] <= OVERLAP_RATIO_MAX, audit
    assert audit["gap_p95_mm_max"] <= INTERFACE_GAP_P95_MM, audit
    assert audit["normal_angle_p95_deg_max"] <= NORMAL_REVERSAL_P95_DEG, audit
    assert audit["source_coverage"] >= 0.999, audit
    volumes = sorted(round(f.volume_mm3, 6) for f in result.fragments)
    assert volumes == [pytest.approx(864.0, rel=1e-9)] * 2, volumes
    assert abs(sum(volumes) - abs(mother.mesh.volume)) / abs(mother.mesh.volume) <= VOLUME_REL_TOL


def test_plane_event_shared_surface_is_geometrically_exact() -> None:
    """Both sides of one event consume the same cutter, so the shared face is exact.

    The sampled gap and normal error are the accuracy claims; the patch *area* is checked
    separately below because ``build_interface`` currently over-counts it.
    """
    mother = box_mother((12.0, 12.0, 12.0), mother_id="box12")
    result = _plane_event(mother)
    assert len(result.interfaces) >= 1
    for patch in result.interfaces:
        assert patch.gap_p95_mm <= 1e-9, _patch_row(patch)
        assert patch.normal_angle_p95_deg <= 1e-6, _patch_row(patch)
        assert patch.sample_points_a.shape == patch.sample_points_b.shape


@pytest.mark.xfail(strict=True, reason=(
    "DEFECT (measured 2026-02, partially fixed): ``synlab/fracture/fragment.py::build_interface`` "
    "now reports the measured plan 30.5 common clipped coverage, so the patches of a 12 mm box "
    "cut sum to 121.45 mm^2 instead of the old 0.5*(area_a+area_b) pairing artefact (123.65 "
    "mm^2), and the *pair-level* measurement (which the R2 verdict and CleanTruth use) is "
    "144.000 mm^2.  This test sums ``patch.area_mm2`` over the *sampling chunks*, and that number "
    "cannot reach 144 yet for two reasons that both live in ``synlab/fracture/event.py``, which "
    "this task was not allowed to touch: (1) lines 276-281 overwrite ``patch.area_mm2`` with the "
    "greedy face-pairing overlap sum after ``build_interface`` returned; (2) "
    "``_match_faces_by_overlap`` leaves 48 cut faces (8.25 mm^2, its own "
    "``unmatched_interface_area_mm2``) unpaired and caps a face at 3 partners, so the chunk "
    "regions only tile 121.45 mm^2 of the 144 mm^2 sheet.  The analytic 144 mm^2 is asserted on "
    "the pair-level measurement in test_real_planar_cut_yields_exactly_one_r2_relation."))
def test_interface_area_equals_the_hand_computed_shared_area() -> None:
    mother = box_mother((12.0, 12.0, 12.0), mother_id="box12")
    result = _plane_event(mother)
    total = sum(patch.area_mm2 for patch in result.interfaces)
    assert total == pytest.approx(HAND_COMPUTED_INTERFACE_AREA, rel=1e-6), (
        "; ".join(_patch_row(p) for p in result.interfaces))


def test_audit_reports_the_keys_the_pipeline_reads() -> None:
    """``synlab/pipeline.py`` branches on ``audit.get("ok", True)``: that key must exist."""
    mother = box_mother((12.0, 12.0, 12.0), mother_id="box12")
    result = _plane_event(mother)
    audit = audit_fracture(result, mother)
    assert "ok" in audit, (
        "audit_fracture must expose 'ok' because synlab/pipeline.py does "
        "`if not fracture_audit.get('ok', True)`; keys="
        f"{sorted(audit)}")
    assert audit["ok"] == (not audit.get("failures", [])), audit


# ------------------------------------------------------- documented defect: ambiguity metric
def test_planar_cut_interface_ambiguity_is_within_budget() -> None:
    """The ambiguity metric must count unattributable points, not reconstruction defects.

    ``build_interface`` samples inside the *common clipped* polygon and rebuilds both sides by
    barycentric reconstruction, so a clean planar cut cannot produce a point outside the opposite
    triangle any more.
    """
    mother = box_mother((12.0, 12.0, 12.0), mother_id="box12")
    result = _plane_event(mother)
    worst = max(result.interfaces, key=lambda patch: patch.ambiguity_area_ratio)
    assert worst.ambiguity_area_ratio <= PROTOCOL_AMBIGUITY_MAX, _patch_row(worst)
    for patch in result.interfaces:
        assert patch.meta.get("bary_min_a", 0.0) >= 0.0, _patch_row(patch)
        assert patch.meta.get("bary_min_b", 0.0) >= 0.0, _patch_row(patch)
        assert patch.ambiguity_area_ratio == pytest.approx(0.0), _patch_row(patch)


def test_real_planar_cut_yields_exactly_one_r2_relation() -> None:
    """A08 on the real pipeline: a genuine two-block plane cut is exactly one R2 relation.

    The relation area is the pair's measured common fracture area (plan 30.5), i.e. the
    hand-computed 12 x 12 = 144 mm^2, not the sum of the sampling chunks.
    """
    mother = box_mother((12.0, 12.0, 12.0), mother_id="box12")
    result = _plane_event(mother)
    clean = finalize_clean_truth(mother, result)
    pairs = {pair: edge for pair, edge in clean.relations.items() if pair[0] < pair[1]}
    assert len(pairs) == 1, sorted(pairs)
    edge = next(iter(pairs.values()))
    detail = "; ".join(_patch_row(p) for p in result.interfaces)
    assert edge.kind == RELATION_R2, (
        f"kind={edge.kind} reason={edge.reason} area={edge.area_mm2}; {detail}; "
        f"evidence={clean.meta.get('patch_evidence')}")
    assert edge.area_mm2 == pytest.approx(HAND_COMPUTED_INTERFACE_AREA, rel=1e-6)
    assert edge.loss_mask is True and edge.valid is True
    assert clean.qa["r2_pairs"] == 1 and clean.qa["pass"] is True, clean.qa
    assert clean.meta["patch_evidence"][str(edge.interface_id)][
        "pair_common_area_source"] == "pair_common_clip_area_mm2"


# ------------------------------------------------------------------- truth-layer contracts
def test_relations_are_symmetric_and_grey_zones_are_not_negatives() -> None:
    mother, event = two_block_event()
    clean = finalize_clean_truth(mother, event)
    for (a, b), edge in clean.relations.items():
        assert a != b, "self loop"
        mirror = _edge(clean, b, a)
        assert mirror is not None and mirror.kind == edge.kind, (a, b)
        assert mirror.loss_mask == edge.loss_mask
        if edge.kind in ("TINY_CONTACT", "UNKNOWN"):
            assert edge.loss_mask is False, f"grey/unknown pair {a}|{b} is a negative"
    assert clean.r2_neighbours("A") == {"B"} and clean.r2_neighbours("B") == {"A"}


def test_clean_truth_never_carries_visible_labels() -> None:
    """Visible supervision requires a render; calling it with a clean object must not crash.

    ``synlab/pipeline.py`` only ever calls this with a ``PhysicalTruth``, but a hand-written
    caller can pass the wrong layer, and a public façade must answer with a structured error
    instead of an ``AttributeError``.
    """
    from synlab.errors import ErrorCode, SynLabError
    from synlab.truth.api import update_visibility_truth

    mother, event = two_block_event()
    clean = finalize_clean_truth(mother, event)
    assert clean.meta.get("visible_labels_generated", False) is False
    with pytest.raises(SynLabError) as info:
        update_visibility_truth(clean, None)
    assert info.value.code in (ErrorCode.SCHEMA_INVALID, ErrorCode.INPUT_UNAVAILABLE), info.value


def test_truth_round_trips_through_the_store(tmp_path: Path) -> None:
    mother, event = two_block_event()
    clean = finalize_clean_truth(mother, event)
    store = AssetStore(tmp_path / "store")
    record = commit_truth(store, clean, role="clean_truth", lineage_id="lin", split="dev")
    assert record.role == "clean_truth"
    again = load_truth(store, record.asset_id, role="clean_truth")
    assert isinstance(again, CleanTruth)
    assert again.mother_id == clean.mother_id and again.event_id == clean.event_id
    assert set(again.relations) == set(clean.relations)
    for pair, edge in clean.relations.items():
        assert again.relations[pair].kind == edge.kind
        assert again.relations[pair].area_mm2 == pytest.approx(edge.area_mm2)


def test_labels_and_features_stay_separate() -> None:
    """``build_labels`` must keep labels and features in separate objects (plan 4.4 / 30.10)."""
    mother, event = two_block_event()
    clean = finalize_clean_truth(mother, event)
    payload = build_labels(clean)
    assert set(payload) >= {"labels", "features", "separation"}, sorted(payload)
    labels = payload["labels"]
    features = payload["features"]
    separation = payload["separation"]
    assert isinstance(labels, dict) and isinstance(features, dict)
    forbidden = {"local_tokens", "global_rgb", "points", "normals", "descriptor",
                 "feature", "feature_vector", "embedding"}
    leaked = forbidden & set(labels)
    assert not leaked, f"labels leaked feature fields: {sorted(leaked)}; separation={separation}"
    assert separation.get("features_untouched") is True, separation
    assert separation.get("forbidden_present") == [], separation
    assert separation.get("shared_keys") == [], separation
    assert features is not labels
