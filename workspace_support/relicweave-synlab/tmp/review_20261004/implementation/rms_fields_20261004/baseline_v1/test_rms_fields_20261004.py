"""Small mathematical checks for the direct frozen-field RMS conditioner."""

from __future__ import annotations

import math

import numpy as np
import pytest

from synlab.degrade.rms_fields import calibrate_rms_field


def test_single_scale_hits_uncentered_mask_rms_and_preserves_roi_exterior() -> None:
    raw = np.array([[3.0, 4.0, 99.0, 0.0],
                    [-3.0, 4.0, -9.0, 0.0],
                    [6.0, 8.0, 42.0, 0.0]])
    original = raw.copy()
    mask = np.array([[True, True, False, False],
                     [True, True, False, False],
                     [True, True, False, False]])

    result = calibrate_rms_field(raw, mask, 10.0)

    requested_values = [3.0, 4.0, -3.0, 4.0, 6.0, 8.0]
    raw_rms = math.sqrt(sum(value * value for value in requested_values) / 6)
    expected_scale = 10.0 / raw_rms
    expected = np.array([value * expected_scale for value in requested_values])
    actual_values = result.calibrated_field_mm[mask].tolist()
    actual_rms = math.sqrt(sum(value * value for value in actual_values) / len(actual_values))
    actual_mean = sum(actual_values) / len(actual_values)
    actual_peak = max(abs(value) for value in actual_values)

    assert result.status == "EXACT"
    assert result.scale_factor == pytest.approx(expected_scale)
    assert result.raw_rms_mm == pytest.approx(raw_rms)
    assert result.actual_rms_mm == pytest.approx(10.0)
    assert result.actual_rms_mm == pytest.approx(actual_rms)
    assert result.actual_mean_mm == pytest.approx(actual_mean)
    assert result.actual_peak_abs_mm == pytest.approx(actual_peak)
    assert result.requested_count == result.finite_count == 6
    assert result.to_metadata()["requested_denominator"] == 6
    assert result.to_metadata()["finite_denominator"] == 6
    assert result.to_metadata()["conditioned_exact_rms"] is True
    assert "independent-Gaussian" in result.to_metadata()["distribution_note"]
    assert result.to_metadata()["real_phone_noise_calibration"] == "NOT_CLAIMED"
    np.testing.assert_allclose(result.calibrated_field_mm[mask], expected)
    np.testing.assert_array_equal(result.calibrated_field_mm[~mask], original[~mask])
    np.testing.assert_array_equal(result.raw_field_mm, original)
    np.testing.assert_array_equal(raw, original)


def test_zero_target_makes_selected_displacement_the_identity() -> None:
    raw = np.array([2.0, -3.0, 8.0, 11.0])
    mask = np.array([True, True, False, False])

    result = calibrate_rms_field(raw, mask, 0.0)

    assert result.status == "EXACT"
    assert result.scale_factor == 0.0
    assert result.actual_rms_mm == 0.0
    np.testing.assert_array_equal(result.calibrated_field_mm, [0.0, 0.0, 8.0, 11.0])
    np.testing.assert_array_equal(result.raw_field_mm, raw)


def test_missing_selected_samples_are_unknown_and_never_filled_with_zero() -> None:
    raw = np.array([3.0, np.nan, 4.0, 100.0])
    mask = np.array([True, True, True, False])

    result = calibrate_rms_field(raw, mask, 2.0)

    assert result.status == "UNKNOWN_NONFINITE_INPUT"
    assert result.scale_factor is None
    assert result.requested_count == 3
    assert result.finite_count == 2
    assert result.to_metadata()["nonfinite_requested_count"] == 1
    assert result.raw_rms_mm == pytest.approx(math.sqrt((9.0 + 16.0) / 2))
    assert result.actual_rms_mm == pytest.approx(result.raw_rms_mm)
    assert np.isnan(result.calibrated_field_mm[1])
    np.testing.assert_array_equal(result.calibrated_field_mm, raw)


def test_empty_mask_and_positive_target_on_zero_field_are_unknown() -> None:
    raw = np.zeros(3, dtype=np.float64)
    empty = calibrate_rms_field(raw, np.zeros(3, dtype=bool), 1.0)
    zero = calibrate_rms_field(raw, np.ones(3, dtype=bool), 1.0)

    assert empty.status == "UNKNOWN_EMPTY_MASK"
    assert empty.requested_count == empty.finite_count == 0
    assert empty.actual_rms_mm is None
    assert zero.status == "UNKNOWN_DEGENERATE_ZERO_FIELD"
    assert zero.scale_factor is None
    assert zero.raw_rms_mm == zero.actual_rms_mm == 0.0
    np.testing.assert_array_equal(zero.calibrated_field_mm, raw)


@pytest.mark.parametrize("target", [-1.0, np.nan, np.inf])
def test_invalid_target_is_rejected(target: float) -> None:
    with pytest.raises(ValueError, match="target_rms_mm"):
        calibrate_rms_field(np.array([1.0, 2.0]), np.array([True, True]), target)


def test_mask_must_be_boolean_and_match_field_shape() -> None:
    raw = np.array([1.0, 2.0])
    with pytest.raises(ValueError, match="mask"):
        calibrate_rms_field(raw, np.array([1, 1]), 1.0)
    with pytest.raises(ValueError, match="mask"):
        calibrate_rms_field(raw, np.array([True]), 1.0)

