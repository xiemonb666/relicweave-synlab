"""Focused regression checks for the audited P05/P06 appearance contract."""

from __future__ import annotations

import copy
import runpy
from pathlib import Path

import numpy as np
import pytest

from synlab.degrade.api import apply_axis
from synlab.degrade.sources import mesh_geometry_hash
from synlab.physical import fields as F
from synlab.schemas.runtime import CleanTruth


AUDIT_SCRIPT = (Path(__file__).resolve().parents[3] / "tmp" / "review_20261003" /
                "implementation" / "degradation_audit" / "probe_degradation_axes.py")


def _clean_truth(fragment_id: str) -> CleanTruth:
    return CleanTruth(
        mother_id="degradation_audit_mother",
        event_id="degradation_audit_event",
        version=1,
        relations={},
        interfaces=[],
        correspondence=[],
        event_tree={"event_id": "degradation_audit_event", "events": []},
        qa={"pass": True, "truth_incomplete": False},
        meta={"truth_hash": "sha256:appearance-repair-clean-truth",
              "fragment_ids": [fragment_id], "truth_incomplete": False},
    )


@pytest.fixture(scope="module")
def audit_source():
    audit = runpy.run_path(str(AUDIT_SCRIPT), run_name="appearance_probe_fixture")
    mesh, _top, source = audit["small_box"]()
    clean_truth = _clean_truth(source.get("fragment").fragment_id)
    source = source.with_payload(
        clean_truth=clean_truth,
        physical_truth={"version": "stale"},
        visible_labels={"version": "stale"},
        features={"version": "stale"},
    )
    source.meta.update({"physical_truth": {"version": "stale"},
                        "visible_labels": {"version": "stale"},
                        "features": {"version": "stale"}})
    source.get("fragment").meta.update({"physical_truth": {"version": "stale"},
                                         "visible_labels": {"version": "stale"},
                                         "features": {"version": "stale"}})
    source.get("fragment").meta.update({"physical_truth": {"version": "stale"},
                                         "visible_labels": {"version": "stale"},
                                         "features": {"version": "stale"}})
    appearance = source.get("appearance")
    appearance["custom_annotation"] = {"history": ["source", "semantic"]}
    # The fragment and top-level appearance intentionally point at the same source mapping.
    source.get("fragment").meta["appearance"] = appearance
    return mesh, source, clean_truth


def _run_chain(source, clean_truth, axes):
    current = source
    measurements = []
    for axis_id, level in axes:
        output, measurement = apply_axis(
            axis_id, level, current, None,
            lineage_id="degradation_audit_small_probe_20261003", commit=False)
        current = output.as_bundle()
        measurements.append(measurement)
        assert current.get("clean_truth") is clean_truth
        assert "physical_truth" not in current.payload
        assert "visible_labels" not in current.payload
        assert "features" not in current.payload
        assert "physical_truth" not in current.meta
        assert "visible_labels" not in current.meta
        assert "features" not in current.meta
        for stale_key in ("physical_truth", "visible_labels", "features"):
            assert stale_key not in current.get("fragment").meta
        for stale_key in ("physical_truth", "visible_labels", "features"):
            assert stale_key not in current.get("fragment").meta
    return current, measurements


def test_rank_masks_are_area_weighted_stable_nested_and_report_quantization() -> None:
    scores = np.array([0.1, 0.1, 0.8], dtype=np.float64)
    areas = np.array([1.0, 1.0, 8.0], dtype=np.float64)
    masks = []
    details = []
    for fraction in (0.0, 0.1, 0.2, 0.6, 1.0):
        mask, report = F.rank_mask_for_area_fraction(scores, fraction, areas, tail="lower")
        masks.append(mask)
        details.append(report)

    assert not masks[0].any()
    assert masks[1].tolist() == [True, False, False]  # exact 1 mm² target; stable tie order
    assert masks[2].tolist() == [True, True, False]
    assert masks[-1].all()
    for before, after in zip(masks, masks[1:]):
        assert np.all(~before | after)
    assert details[1]["realized_fraction"] == pytest.approx(0.1)
    assert details[1]["boundary_tie_split"] is True
    assert details[3]["quantized"] is True
    assert details[3]["absolute_fraction_error"] == pytest.approx(
        abs(details[3]["realized_fraction"] - 0.6))


@pytest.mark.parametrize(
    ("values", "fraction", "weights", "tail"),
    [
        ([0.1, 0.2], 0.5, [1.0], "lower"),
        ([0.1, float("nan")], 0.5, [1.0, 1.0], "lower"),
        ([0.1, 0.2], 0.5, [1.0, 0.0], "lower"),
        ([0.1], 1.1, [1.0], "lower"),
        ([0.1], 0.5, [1.0], "middle"),
    ],
)
def test_rank_mask_rejects_bad_inputs(values, fraction, weights, tail) -> None:
    with pytest.raises(ValueError):
        F.rank_mask_for_area_fraction(values, fraction, weights, tail=tail)


def test_empty_target_is_an_exact_empty_mask_and_legacy_threshold_is_compatible() -> None:
    mask, detail = F.rank_mask_for_area_fraction([], 0.0, [], tail="lower")
    assert mask.size == 0
    assert detail["realized_fraction"] == 0.0
    with pytest.raises(ValueError):
        F.rank_mask_for_area_fraction([], 0.2, [], tail="lower")

    values = np.arange(5, dtype=np.float64)
    assert F.threshold_for_fraction(values, 0.2) == pytest.approx(np.quantile(values, 0.8))
    assert F.threshold_for_fraction(values, 0.0) == pytest.approx(values.min() - 1e-9)
    assert F.threshold_for_fraction(values, 1.0) == pytest.approx(values.max() + 1e-9)


def test_p06_and_p08_lower_tail_cutoffs_have_matching_direction() -> None:
    # Independent numerical oracle for callers that pair the cutoff with values <= threshold.
    # P06 surface samples are finite and P08 face-centre anchors are equally weighted; these
    # cutoff checks establish direction, not exact physical-area weighting or full geometry.
    values = np.linspace(0.0, 1.0, 101)
    for fraction in (0.2, 0.6):
        cutoff = F.threshold_for_fraction(values, fraction, tail="lower")
        assert cutoff == pytest.approx(np.quantile(values, fraction))
        selected = values <= cutoff
        assert selected.mean() >= fraction
        assert selected.mean() - fraction <= (1.0 / len(values)) + 1e-12


def test_p05_p06_preserve_channels_truth_and_both_chain_orders(audit_source) -> None:
    mesh, source, clean_truth = audit_source
    source_hash = source.content_hash()
    truth_snapshot = copy.deepcopy(clean_truth.__dict__)
    source_appearance = source.get("appearance")
    source_arrays = {key: value.copy() for key, value in source_appearance.items()
                     if isinstance(value, np.ndarray)}
    source_mesh_hash = mesh_geometry_hash(mesh)

    chains = (
        (("P05", 1), ("P06", 1)),
        (("P06", 1), ("P05", 1)),
    )
    for axes in chains:
        output, measurements = _run_chain(source, clean_truth, axes)
        appearance = output.get("appearance")
        fragment = output.get("fragment")
        assert mesh_geometry_hash(output.get("mesh")) == source_mesh_hash
        assert fragment.mesh is output.get("mesh")
        assert np.array_equal(fragment.face_origin_kind,
                              source.get("fragment").face_origin_kind)
        assert np.array_equal(fragment.face_interface_id,
                              source.get("fragment").face_interface_id)
        assert "paint_mask_removed" in appearance
        assert "paint_mask_retained" in appearance
        assert "dirt_mask" in appearance
        assert np.array_equal(appearance["texel_layer"], source_appearance["texel_layer"])
        assert np.array_equal(appearance["pattern_region"], source_appearance["pattern_region"])
        assert np.array_equal(appearance["interface_region"], source_appearance["interface_region"])
        assert appearance["custom_annotation"] == source_appearance["custom_annotation"]
        assert appearance["custom_annotation"] is not source_appearance["custom_annotation"]
        for key in ("texel_substrate_albedo", "texel_area_mm2", "texel_positions",
                    "texel_layer", "pattern_region", "interface_region"):
            assert np.array_equal(appearance[key], source_arrays[key])
            assert not np.shares_memory(appearance[key], source_appearance[key])
        assert measurements[-1].extra.get("label_status")
        physical_truth = output.get("physical_result").physical_truth
        assert physical_truth is not None
        assert physical_truth is not clean_truth
        assert physical_truth.clean_truth_ref == clean_truth.meta["truth_hash"]
        assert physical_truth.version == clean_truth.version + 1

    assert source.content_hash() == source_hash
    assert clean_truth.__dict__ == truth_snapshot
    for key, value in source_arrays.items():
        assert np.array_equal(source_appearance[key], value)


def test_p05_and_p06_level_masks_nest_on_the_frozen_basis(audit_source) -> None:
    _mesh, source, _truth = audit_source
    expected_source_hash = source.content_hash()
    for axis_id, mask_key, fraction_metric in (
        ("P05", "paint_mask_removed", "paint_removed_area_mm2"),
        ("P06", "dirt_mask", "covered_area_mm2"),
    ):
        prior_mask = np.zeros(len(source.get("appearance")["texel_albedo"]), dtype=bool)
        measured_areas = []
        basis_ids = []
        for level in range(5):
            output, measurement = apply_axis(
                axis_id, level, source, None,
                lineage_id="degradation_audit_small_probe_20261003", commit=False)
            bundle = output.as_bundle()
            current_mask = (np.zeros_like(prior_mask) if level == 0 else
                            np.asarray(bundle.get("appearance")[mask_key], dtype=bool))
            assert np.all(~prior_mask | current_mask)
            prior_mask = current_mask
            measured_areas.append(float(measurement.measured.get(fraction_metric, 0.0)))
            basis_ids.append(measurement.extra["basis_id"])
        assert measured_areas == sorted(measured_areas)
        assert len(set(basis_ids)) == 1
    assert source.content_hash() == expected_source_hash

