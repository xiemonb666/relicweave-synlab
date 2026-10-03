"""Focused regression checks for the audited P05/P06 appearance contract."""

from __future__ import annotations

import copy
import math
import runpy
from pathlib import Path

import numpy as np
import pytest

from synlab.degrade.api import apply_axis
from synlab.degrade.sources import mesh_geometry_hash
from synlab.physical import fields as F
from synlab.physical.operators import crack_or_coat_loss, dirt_cover, remove_paint
from synlab.physical.recipe import DamageRecipe
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


def _whole_group_oracle(scores, fraction, weights, tail):
    """Exhaustively compare every whole-score-group prefix, independent of production code."""
    groups = sorted(set(float(value) for value in scores), reverse=(tail == "upper"))
    boundaries = [0.0]
    selected_groups = []
    for score in groups:
        selected_groups.append(score)
        selected_area = math.fsum(float(weight) for value, weight in zip(scores, weights)
                                  if float(value) in selected_groups)
        boundaries.append(selected_area)
    total = math.fsum(float(weight) for weight in weights)
    target = float(fraction) * total
    # Enumerating every possible group boundary makes this an independent nearest-boundary oracle.
    prefix = min(range(len(boundaries)), key=lambda index: (abs(boundaries[index] - target), index))
    chosen = set(groups[:prefix])
    return np.asarray([float(value) in chosen for value in scores], dtype=bool), boundaries[prefix]


def test_rank_masks_choose_whole_equal_score_groups_and_ignore_input_order() -> None:
    scores = np.array([0.1, 0.1, 0.8], dtype=np.float64)
    areas = np.array([1.0, 1.0, 8.0], dtype=np.float64)
    masks = []
    details = []
    for fraction in (0.0, 0.1, 0.2, 0.4, 0.6, 1.0):
        mask, report = F.rank_mask_for_area_fraction(scores, fraction, areas, tail="lower")
        expected, expected_area = _whole_group_oracle(scores, fraction, areas, "lower")
        assert np.array_equal(mask, expected)
        assert report["selected_area"] == pytest.approx(expected_area)
        assert report["boundary_tie_split"] is False
        masks.append(mask)
        details.append(report)

    assert not masks[0].any()
    assert not masks[1].any()  # nearest-boundary tie chooses zero, never half of an equal-score group
    assert masks[2].tolist() == [True, True, False]
    assert np.all(~masks[0] | masks[1])
    assert all(np.all(~before | after) for before, after in zip(masks, masks[1:]))
    assert details[1]["realized_fraction"] == pytest.approx(0.0)
    assert details[1]["quantized"] is True
    assert details[1]["largest_score_group_area_fraction"] == pytest.approx(0.8)
    assert details[4]["quantized"] is True

    permutation = np.array([2, 0, 1])
    inverse = np.argsort(permutation)
    for tail in ("lower", "upper"):
        for fraction in (0.0, 0.15, 0.5, 0.95, 1.0):
            original, _ = F.rank_mask_for_area_fraction(scores, fraction, areas, tail=tail)
            shuffled, report = F.rank_mask_for_area_fraction(
                scores[permutation], fraction, areas[permutation], tail=tail)
            expected, _ = _whole_group_oracle(scores, fraction, areas, tail)
            assert np.array_equal(original, expected)
            assert np.array_equal(shuffled[inverse], original)
            assert report["boundary_tie_split"] is False


def test_rank_mask_reports_large_constant_score_quantization() -> None:
    scores = np.full(7, 0.5)
    areas = np.array([1.0, 2.0, 1.0, 3.0, 1.0, 2.0, 1.0])
    mask, report = F.rank_mask_for_area_fraction(scores, 0.5, areas)
    assert not mask.any()  # equal-distance tie chooses the smaller whole-group boundary
    assert report["score_group_count"] == 1
    assert report["largest_score_group_area_fraction"] == pytest.approx(1.0)
    assert report["absolute_fraction_error"] == pytest.approx(0.5)
    assert report["quantized"] is True


@pytest.mark.parametrize("tail", ["lower", "upper"])
def test_rank_mask_is_nested_on_whole_groups_for_both_tails(tail) -> None:
    scores = np.array([0.0, 0.0, 0.3, 0.3, 0.9, 0.9, 0.9])
    areas = np.array([1.0, 5.0, 2.0, 1.0, 1.0, 2.0, 4.0])
    fractions = np.linspace(0.0, 1.0, 51)
    masks = [F.rank_mask_for_area_fraction(scores, fraction, areas, tail=tail)[0]
             for fraction in fractions]
    assert not masks[0].any()
    assert masks[-1].all()
    assert all(np.all(~before | after) for before, after in zip(masks, masks[1:]))


def _appearance_payload(count=4):
    return {
        "texel_albedo": np.tile(np.array([[0.7, 0.4, 0.3]], dtype=np.float32), (count, 1)),
        "texel_substrate_albedo": np.tile(
            np.array([[0.5, 0.45, 0.4]], dtype=np.float32), (count, 1)),
        "texel_area_mm2": np.ones(count, dtype=np.float64),
        "texel_layer": np.array([1, 0, 1, 0][:count], dtype=np.int32),
        "texel_roughness": np.full(count, 0.6, dtype=np.float32),
        "texel_positions": np.column_stack((np.arange(count), np.zeros((count, 2)))),
        "pattern_region": np.array([True, False, True, False][:count]),
        "interface_region": np.array([True, True, False, False][:count]),
    }


def _operator_recipe(axis_id, appearance, *, seed=3, fraction=0.5, dirt_color=None,
                    dirt_roughness=None):
    field_name = "rank_field" if axis_id == "P05" else "dirt_field"
    field = F.FourierField.sample_frozen(np.random.default_rng(seed), scale_mm=2.0,
                                         n_components=3, field_id=f"{axis_id}_test").payload()
    basis = {field_name: field, "appearance": appearance}
    if dirt_color is not None:
        basis["dirt_color"] = dirt_color
    if dirt_roughness is not None:
        basis["dirt_roughness"] = dirt_roughness
    params = ({"retained_fraction": 1.0 - fraction} if axis_id == "P05"
              else {"coverage": fraction})
    return DamageRecipe(axis_id=axis_id, variant="paint_removal" if axis_id == "P05"
                        else "dirt_appearance", params=params, basis=basis)


@pytest.mark.parametrize("axis_id", ["P05", "P06"])
@pytest.mark.parametrize("bad_area", [np.nan, 0.0, -1.0, np.inf])
def test_appearance_operators_reject_invalid_area_on_any_texel(axis_id, bad_area) -> None:
    import trimesh

    appearance = _appearance_payload()
    appearance["texel_area_mm2"][1] = bad_area  # texel 1 has no paint layer
    recipe = _operator_recipe(axis_id, appearance)
    operator = remove_paint if axis_id == "P05" else dirt_cover
    with pytest.raises(ValueError, match="texel_area_mm2"):
        operator(trimesh.creation.box(), recipe)


@pytest.mark.parametrize(
    ("axis_id", "key", "value", "message"),
    [
        ("P05", "texel_albedo", np.array(0.5), "shape"),
        ("P05", "texel_albedo", np.zeros((4, 4)), "shape"),
        ("P06", "texel_albedo", np.array(0.5), "shape"),
        ("P06", "texel_albedo", np.zeros((4, 4)), "shape"),
        ("P05", "texel_albedo", np.full((4, 3), np.nan), "finite"),
        ("P06", "texel_albedo", np.full((4, 3), 1.01), "finite"),
        ("P05", "texel_substrate_albedo", np.full((4, 2), 0.5), "substrate"),
        ("P05", "texel_substrate_albedo", np.full((4, 3), 1.01), "substrate"),
        ("P05", "texel_positions", np.full((4, 3), np.inf), "positions"),
        ("P06", "texel_positions", np.full((4, 3), np.nan), "positions"),
        ("P06", "texel_roughness", np.full(4, -0.01), "roughness"),
    ],
)
def test_appearance_operators_reject_invalid_rgb_position_and_roughness(
        axis_id, key, value, message) -> None:
    import trimesh

    appearance = _appearance_payload()
    appearance[key] = value
    operator = remove_paint if axis_id == "P05" else dirt_cover
    with pytest.raises(ValueError, match=message):
        operator(trimesh.creation.box(), _operator_recipe(axis_id, appearance))


@pytest.mark.parametrize(
    ("axis_id", "key", "value"),
    [
        ("P05", "paint_mask_removed", np.zeros(4, dtype=np.uint8)),
        ("P06", "pattern_region", np.zeros(4, dtype=np.uint8)),
        ("P06", "paint_mask_removed", np.zeros(3, dtype=bool)),
    ],
)
def test_appearance_operators_require_well_shaped_boolean_masks(axis_id, key, value) -> None:
    import trimesh

    appearance = _appearance_payload()
    appearance[key] = value
    operator = remove_paint if axis_id == "P05" else dirt_cover
    with pytest.raises(ValueError, match="boolean mask|masks must"):
        operator(trimesh.creation.box(), _operator_recipe(axis_id, appearance))


@pytest.mark.parametrize(
    ("basis_update", "message"),
    [
        ({"dirt_color": [0.2, 0.3]}, "dirt_color"),
        ({"dirt_color": [0.2, float("nan"), 0.3]}, "dirt_color"),
        ({"dirt_color": [0.2, 1.01, 0.3]}, "dirt_color"),
        ({"dirt_roughness": 1.1}, "dirt_roughness"),
        ({"dirt_roughness": float("nan")}, "dirt_roughness"),
    ],
)
def test_p06_rejects_invalid_dirt_material_values(basis_update, message) -> None:
    import trimesh

    appearance = _appearance_payload()
    recipe = _operator_recipe("P06", appearance)
    recipe.basis.update(basis_update)
    with pytest.raises(ValueError, match=message):
        dirt_cover(trimesh.creation.box(), recipe)


def test_p05_cumulative_loss_mask_never_restores_removed_paint() -> None:
    import trimesh

    appearance = _appearance_payload()
    mesh = trimesh.creation.box()
    first = remove_paint(mesh, _operator_recipe("P05", appearance, seed=4, fraction=0.5))
    first_mask = first.appearance["paint_mask_removed"].copy()
    second = remove_paint(mesh, _operator_recipe("P05", first.appearance, seed=9,
                                                fraction=0.5))
    second_mask = second.appearance["paint_mask_removed"]
    assert np.all(~first_mask | second_mask)
    assert np.array_equal(second.appearance["texel_albedo"][first_mask],
                          appearance["texel_substrate_albedo"][first_mask])


def test_p06_reports_no_surviving_pattern_as_not_applicable(audit_source) -> None:
    _mesh, source, clean_truth = audit_source
    p05, _ = apply_axis("P05", 4, source, None,
                        lineage_id="appearance_full_pattern_loss", commit=False)
    p06, _ = apply_axis("P06", 1, p05.as_bundle(), None,
                        lineage_id="appearance_full_pattern_loss", commit=False)
    result = p06.as_bundle().get("physical_result")
    measured = result.meta["measured"]
    assert measured["visible_pattern_area_mm2"] == pytest.approx(0.0)
    assert measured["cumulative_pattern_loss_area_mm2"] == pytest.approx(
        measured["original_pattern_area_mm2"])
    assert "pattern_visibility_reduction" not in measured
    assert result.meta["details"]["pattern_visibility_status"] == (
        "NOT_APPLICABLE_NO_SURVIVING_PATTERN")
    assert p06.as_bundle().get("clean_truth") is clean_truth


@pytest.mark.parametrize(("affected", "expected_removed"), [(0.0, 0), (1.0, 2)])
def test_p08_paint_coat_loss_threshold_uses_lower_tail(affected, expected_removed) -> None:
    import trimesh

    appearance = _appearance_payload()
    field = F.FourierField.sample_frozen(np.random.default_rng(30), scale_mm=2.0,
                                         n_components=3, field_id="P08_test").payload()
    recipe = DamageRecipe(axis_id="P08", variant="paint_coat_loss",
                          params={"affected_area": affected},
                          basis={"rank_field": field, "appearance": appearance,
                                 "coat_layer_id": 1})
    outcome = crack_or_coat_loss(trimesh.creation.box(), recipe)
    assert int(outcome.appearance["coat_mask_removed"].sum()) == expected_removed


def test_rank_masks_are_area_weighted_nested_and_report_quantization() -> None:
    scores = np.array([0.1, 0.1, 0.8], dtype=np.float64)
    areas = np.array([1.0, 1.0, 8.0], dtype=np.float64)
    masks = []
    details = []
    for fraction in (0.0, 0.1, 0.2, 0.6, 1.0):
        mask, report = F.rank_mask_for_area_fraction(scores, fraction, areas, tail="lower")
        masks.append(mask)
        details.append(report)

    assert not masks[0].any()
    assert not masks[1].any()
    assert masks[2].tolist() == [True, True, False]
    assert masks[-1].all()
    for before, after in zip(masks, masks[1:]):
        assert np.all(~before | after)
    assert details[1]["realized_fraction"] == pytest.approx(0.0)
    assert details[1]["boundary_tie_split"] is False
    assert details[3]["quantized"] is True
    assert details[3]["absolute_fraction_error"] == pytest.approx(
        abs(details[3]["realized_fraction"] - 0.6))


@pytest.mark.parametrize(
    ("values", "fraction", "weights", "tail"),
    [
        ([0.1, 0.2], 0.5, [1.0], "lower"),
        ([0.1, float("nan")], 0.5, [1.0, 1.0], "lower"),
        ([0.1, 0.2], 0.5, [1.0, 0.0], "lower"),
        ([0.1, 0.2], 0.5, [1e308, 1e308], "lower"),
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
        if axes[0][0] == "P05":
            area = np.asarray(appearance["texel_area_mm2"], dtype=np.float64)
            pattern = np.asarray(appearance["pattern_region"], dtype=bool)
            paint_removed = np.asarray(appearance["paint_mask_removed"], dtype=bool)
            dirt = np.asarray(appearance["dirt_mask"], dtype=bool)
            visible_pattern = pattern & ~paint_removed
            visible_area = float(area[visible_pattern].sum())
            measured = output.get("physical_result").meta["measured"]
            assert measured["original_pattern_area_mm2"] == pytest.approx(
                float(area[pattern].sum()))
            assert measured["cumulative_pattern_loss_area_mm2"] == pytest.approx(
                float(area[pattern & paint_removed].sum()))
            assert measured["visible_pattern_area_mm2"] == pytest.approx(visible_area)
            if visible_area > 0.0:
                assert measured["pattern_visibility_reduction"] == pytest.approx(
                    float(area[dirt & visible_pattern].sum()) / visible_area)

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

