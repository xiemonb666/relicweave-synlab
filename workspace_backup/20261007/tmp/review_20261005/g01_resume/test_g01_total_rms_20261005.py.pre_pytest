"""Opt-in G01 total-field RMS conditioning and legacy preservation checks."""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

import numpy as np
import pytest

from synlab.degrade import ops_geometry as OG
from synlab.degrade.api import apply_axis
from synlab.degrade.axes import G01
from synlab.degrade.registry import basis_rng
from synlab.degrade.sources import KIND_GEOMETRY, SourceBundle
from synlab.errors import ErrorCode, SynLabError
from synlab.schemas.runtime import DegradationBasis


_FROZEN_DEPTH_ERROR_AST_SHA256 = (
    "073fa1e77270ba55074dddb6814333171da15da525b05d535f88174fb4ed9be2"
)


def _legacy_depth_error_oracle(points, normals, coarse, weight, *, target, probability, rng):
    """The pre-conditioning G01 implementation, retained as a bitwise audit oracle."""
    base = coarse * weight
    base_rms = float(np.sqrt(np.mean(base ** 2)))
    delta = base * (target / base_rms)
    outlier_mask = np.zeros(len(points), dtype=bool)
    if probability > 0 and len(points):
        draw = rng.random(len(points)) < probability
        if draw.any():
            magnitude = target * rng.uniform(2.0, 5.0, size=int(draw.sum()))
            sign = np.where(rng.random(int(draw.sum())) < 0.5, -1.0, 1.0)
            delta = delta.copy()
            delta[draw] += magnitude * sign
            outlier_mask = draw
    perturbed = points + delta[:, None] * normals
    info = {
        "inlier_rms_mm": float(np.sqrt(np.mean(delta[~outlier_mask] ** 2)))
        if (~outlier_mask).any() else 0.0,
        "realized_rms_mm": float(np.sqrt(np.mean(delta ** 2))),
        "max_abs_error_mm": float(np.max(np.abs(delta))) if delta.size else 0.0,
        "outlier_fraction": float(np.mean(outlier_mask)) if len(points) else 0.0,
        "outlier_probability_declared": float(probability),
        "outlier_mean_mm": float(np.mean(np.abs(delta[outlier_mask])))
        if outlier_mask.any() else 0.0,
    }
    return perturbed.astype(np.float64), info


def _basis(coarse, weight, *, probability=0.0, variant="conditioned_total_rms"):
    return DegradationBasis(
        axis_id="G01",
        variant=variant,
        basis_id="0000000000000042",
        seed_ref="g01-total-rms-test",
        payload={"coarse_field": coarse, "weight": weight,
                 "outlier_probability": probability},
    )


def _source(points, normals, *, reference_points=None):
    payload = {"points": points, "normals": normals, "frames": []}
    if reference_points is not None:
        payload["reference_points"] = reference_points
    return SourceBundle(source_kind=KIND_GEOMETRY, payload=payload)


def test_legacy_depth_error_ast_and_output_remain_frozen() -> None:
    module = ast.parse(Path(OG.__file__).read_text(encoding="utf-8"))
    function = next(node for node in module.body
                    if isinstance(node, ast.FunctionDef) and node.name == "depth_error")
    fingerprint = hashlib.sha256(ast.dump(function, include_attributes=False).encode("utf-8"))
    assert fingerprint.hexdigest() == _FROZEN_DEPTH_ERROR_AST_SHA256

    points = np.array([[0.0, 0.0, 2.0], [1.0, -1.0, 3.0], [2.0, 1.0, -4.0],
                       [-2.0, 3.0, 1.0]], dtype=np.float64)
    normals = np.tile([0.0, 0.0, 1.0], (len(points), 1))
    coarse = np.array([-1.0, -0.25, 0.5, 1.0])
    weight = np.array([1.0, 0.75, 1.25, 0.5])
    actual = OG.depth_error(points, normals, coarse, weight, target_rms_mm=0.2,
                            outlier_probability=0.5, rng=np.random.default_rng(17))
    expected = _legacy_depth_error_oracle(
        points, normals, coarse, weight, target=0.2, probability=0.5,
        rng=np.random.default_rng(17))
    np.testing.assert_array_equal(actual[0], expected[0])
    assert actual[1] == expected[1]
    np.testing.assert_array_equal(points, np.array(
        [[0.0, 0.0, 2.0], [1.0, -1.0, 3.0], [2.0, 1.0, -4.0], [-2.0, 3.0, 1.0]]))


def test_all_three_legacy_g01_variants_keep_the_frozen_application_path() -> None:
    n = 12
    points = np.column_stack((np.arange(n, dtype=np.float64),
                              np.arange(n, dtype=np.float64) * -0.5,
                              np.arange(n, dtype=np.float64) * 0.25))
    normals = np.tile([0.0, 0.0, 1.0], (n, 1))
    coarse = np.linspace(-1.0, 1.0, n)
    weight = np.linspace(0.75, 1.25, n)
    source = _source(points, normals)
    operator = G01()

    for variant in ("correlated_depth_error", "outlier_only", "lowfreq_only"):
        basis = _basis(coarse, weight, probability=0.5, variant=variant)
        expected_coarse = coarse.copy()
        expected_weight = weight.copy()
        probability = 0.5
        if variant == "lowfreq_only":
            expected_weight = np.ones_like(expected_weight)
            probability = 0.0
        elif variant == "outlier_only":
            expected_coarse = np.ones_like(expected_coarse)
            expected_weight = np.ones_like(expected_weight)
        expected_points, expected_info = _legacy_depth_error_oracle(
            points, normals, expected_coarse, expected_weight, target=0.1,
            probability=probability, rng=basis_rng(basis, 1, "depth_error"))

        result = operator.apply(source, 1, basis, parameters={"target_rms_mm": 0.1})
        np.testing.assert_array_equal(result.get("points"), expected_points)
        measured = result.meta["measured"]
        assert measured == {
            "target_rms_mm": 0.1,
            "applied_rms_mm": expected_info["realized_rms_mm"],
            "inlier_rms_mm": expected_info["inlier_rms_mm"],
            "max_abs_error_mm": expected_info["max_abs_error_mm"],
            "outlier_fraction": expected_info["outlier_fraction"],
            "audit_reference_available": 0.0,
        }


def test_new_variant_is_opt_in_and_conditions_the_full_outlier_field_once() -> None:
    operator = G01()
    assert operator.default_variant == "correlated_depth_error"
    assert operator.variants() == ["correlated_depth_error", "outlier_only", "lowfreq_only",
                                   "conditioned_total_rms"]

    n = 16
    points = np.zeros((n, 3), dtype=np.float64)
    normals = np.tile([0.0, 0.0, 1.0], (n, 1))
    coarse = np.linspace(-1.0, 1.0, n)
    weight = np.linspace(0.75, 1.25, n)
    target = 0.2
    seed = 81

    reference_rng = np.random.default_rng(seed)
    base = coarse * weight
    raw_delta = base * (target / np.sqrt(np.mean(base ** 2)))
    draw = reference_rng.random(n) < 1.0
    magnitude = target * reference_rng.uniform(2.0, 5.0, size=int(draw.sum()))
    sign = np.where(reference_rng.random(int(draw.sum())) < 0.5, -1.0, 1.0)
    raw_delta = raw_delta.copy()
    raw_delta[draw] += magnitude * sign
    expected_next_rng_value = reference_rng.random()

    apply_rng = np.random.default_rng(seed)
    perturbed, info = OG.conditioned_depth_error(
        points, normals, coarse, weight, target_rms_mm=target,
        outlier_probability=1.0, rng=apply_rng)
    assert info["status"] == "EXACT"
    assert info["outlier_fraction"] == 1.0
    assert info["conditioned_field_rms_mm"] == pytest.approx(target, rel=1e-14)
    assert info["actual_delivered_point_coordinate_rms_mm"] == pytest.approx(target, rel=1e-14)
    assert info["raw_field_sha256"] == info["calibration"]["raw_field_sha256"]
    assert info["mask_sha256"] == info["calibration"]["mask_sha256"]
    assert info["scale_factor"] == info["calibration"]["scale_factor"]
    assert info["condition_mask_scope"] == "all_points"
    assert info["outlier_count"] == n
    assert len(info["outlier_mask_sha256"]) == 64
    assert info["outlier_mask_sha256"] != info["mask_sha256"]
    ratios = perturbed[:, 2] / raw_delta
    np.testing.assert_allclose(ratios, info["scale_factor"], rtol=1e-13, atol=0.0)
    assert apply_rng.random() == expected_next_rng_value


def test_g01_apply_reports_delivered_coordinate_rms_and_keeps_reference_audit_only() -> None:
    n = 24
    points = np.column_stack((np.arange(n, dtype=np.float64) * 0.2,
                              np.arange(n, dtype=np.float64) * -0.1,
                              np.zeros(n, dtype=np.float64)))
    normals = np.tile([0.0, 0.0, 1.0], (n, 1))
    coarse = np.linspace(-1.0, 1.0, n)
    weight = np.ones(n)
    basis = _basis(coarse, weight)
    operator = G01()
    source_with_ref = _source(points, normals, reference_points=points.copy())
    source_without_ref = _source(points, normals)

    with_reference = operator.apply(source_with_ref, 1, basis,
                                    parameters={"target_rms_mm": 0.05})
    without_reference = operator.apply(source_without_ref, 1, basis,
                                       parameters={"target_rms_mm": 0.05})
    np.testing.assert_array_equal(with_reference.get("points"), without_reference.get("points"))
    measured = with_reference.meta["measured"]
    extra = with_reference.meta["extra"]["conditioned_total_rms"]
    assert measured["applied_rms_mm"] == pytest.approx(0.05, rel=1e-12)
    assert "target_rms_mm" not in measured
    assert extra["actual_delivered_point_coordinate_rms_mm"] == measured["applied_rms_mm"]
    assert extra["delivered_minus_target_rms_mm"] == pytest.approx(0.0, abs=1e-12)
    assert extra["delivery_status"] == "EXACT"
    assert len(extra["raw_field_sha256"]) == 64
    assert len(extra["mask_sha256"]) == 64
    assert extra["condition_mask_scope"] == "all_points"
    assert extra["outlier_count"] == 0
    assert len(extra["outlier_mask_sha256"]) == 64
    assert extra["outlier_mask_sha256"] != extra["mask_sha256"]
    assert "before weighting" in with_reference.meta["extra"]["depth_error_field_semantics"]
    assert with_reference.meta["measured"]["audit_reference_available"] == 1.0
    assert without_reference.meta["measured"]["audit_reference_available"] == 0.0


@pytest.mark.parametrize("target", [True, np.bool_(True), np.nan])
def test_conditioned_g01_rejects_nonfinite_or_boolean_targets(target) -> None:
    points = np.zeros((4, 3), dtype=np.float64)
    normals = np.tile([0.0, 0.0, 1.0], (4, 1))
    source = _source(points, normals)
    operator = G01()
    basis = _basis(np.array([-1.0, 0.0, 0.5, 1.0]), np.ones(4))
    with pytest.raises(SynLabError) as caught:
        operator.apply(source, 1, basis, parameters={"target_rms_mm": target})
    assert caught.value.code == ErrorCode.OPERATOR_NOT_REALIZED
    if isinstance(target, (bool, np.bool_)):
        with pytest.raises(SynLabError) as api_caught:
            apply_axis("G01", 1, source, variant="conditioned_total_rms", basis=basis,
                       parameters={"target_rms_mm": target}, commit=False)
        assert api_caught.value.code == ErrorCode.OPERATOR_NOT_REALIZED


def test_conditioned_g01_rejects_nonunit_normals_and_shape_mismatches() -> None:
    points = np.zeros((4, 3), dtype=np.float64)
    coarse = np.array([-1.0, 0.0, 0.5, 1.0])
    basis = _basis(coarse, np.ones(4))
    operator = G01()
    nonunit = np.tile([0.0, 0.0, 2.0], (4, 1))
    with pytest.raises(SynLabError, match="unit normals"):
        operator.apply(_source(points, nonunit), 1, basis,
                       parameters={"target_rms_mm": 0.1})
    malformed = np.ones((4, 2), dtype=np.float64)
    with pytest.raises(SynLabError, match="shape"):
        operator.apply(_source(points, malformed), 1, basis,
                       parameters={"target_rms_mm": 0.1})


def test_conditioned_g01_requires_finite_point_field_and_weight_inputs() -> None:
    normals = np.tile([0.0, 0.0, 1.0], (4, 1))
    coarse = np.array([-1.0, 0.0, 0.5, 1.0])
    weight = np.ones(4)
    cases = (
        (np.zeros((4, 2)), normals, coarse, weight),
        (np.array([[0.0, 0.0, np.nan]] * 4), normals, coarse, weight),
        (np.zeros((4, 3)), np.array([[0.0, 0.0, np.inf]] * 4), coarse, weight),
        (np.zeros((4, 3)), normals, np.array([-1.0, 0.0, np.inf, 1.0]), weight),
        (np.zeros((4, 3)), normals, coarse, np.array([1.0, 1.0, np.nan, 1.0])),
    )
    for points, sample_normals, sample_coarse, sample_weight in cases:
        with pytest.raises(SynLabError, match="G01 conditioned_total_rms"):
            OG.conditioned_depth_error(
                points, sample_normals, sample_coarse, sample_weight,
                target_rms_mm=0.1, outlier_probability=0.0,
                rng=np.random.default_rng(3))
    with pytest.raises(SynLabError, match="below 1e-12 mm"):
        OG.conditioned_depth_error(
            np.zeros((4, 3)), normals, np.full(4, 1e-13), weight,
            target_rms_mm=0.1, outlier_probability=0.0,
            rng=np.random.default_rng(3))


def test_unknown_field_calibration_reports_only_measured_delivered_geometry() -> None:
    points = np.zeros((4, 3), dtype=np.float64)
    normals = np.tile([0.0, 0.0, 1.0], (4, 1))
    perturbed, info = OG.conditioned_depth_error(
        points, normals, np.zeros(4), np.ones(4), target_rms_mm=0.1,
        outlier_probability=1.0, rng=np.random.default_rng(3))

    assert info["field_conditioning_status"] == "UNKNOWN_DEGENERATE_ZERO_FIELD"
    assert info["status"] == "UNKNOWN_OPERATOR_NOT_REALIZED"
    assert info["actual_delivered_point_coordinate_rms_mm"] == 0.0
    assert info["delivered_minus_target_rms_mm"] == -0.1
    assert info["outlier_count"] == 0
    assert "inlier_rms_mm" not in info
    assert "max_abs_error_mm" not in info
    assert info["calibration"]["delivery_status"] == "UNKNOWN_OPERATOR_NOT_REALIZED"
    np.testing.assert_array_equal(perturbed, points)


def test_coordinate_precision_loss_is_unknown_and_never_reported_as_target() -> None:
    n = 8
    points = np.full((n, 3), 1e16, dtype=np.float64)
    normals = np.tile([0.0, 0.0, 1.0], (n, 1))
    coarse = np.array([-1.0, 1.0] * (n // 2))
    perturbed, info = OG.conditioned_depth_error(
        points, normals, coarse, np.ones(n), target_rms_mm=0.05,
        outlier_probability=0.0, rng=np.random.default_rng(9))

    assert info["field_conditioning_status"] == "EXACT"
    assert info["conditioned_field_rms_mm"] == pytest.approx(0.05)
    assert info["status"] == "UNKNOWN_OPERATOR_NOT_REALIZED"
    assert info["actual_delivered_point_coordinate_rms_mm"] == 0.0
    assert info["delivered_minus_target_rms_mm"] == -0.05
    np.testing.assert_array_equal(perturbed, points)

    source = _source(points, normals)
    with pytest.raises(SynLabError) as caught:
        apply_axis("G01", 1, source, variant="conditioned_total_rms",
                   basis=_basis(coarse, np.ones(n)),
                   parameters={"target_rms_mm": 0.05}, commit=False)
    assert caught.value.code == ErrorCode.OPERATOR_NOT_REALIZED
    assert caught.value.measurements["applied_rms_mm"] == 0.0
    assert "target_rms_mm" not in caught.value.measurements
