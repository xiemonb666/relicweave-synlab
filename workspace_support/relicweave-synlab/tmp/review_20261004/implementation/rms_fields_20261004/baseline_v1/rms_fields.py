"""Deterministic RMS conditioning for frozen scalar displacement fields.

The calibration is a single scalar rescale of an already sampled field. It never
draws random values and never mutates the input. RMS uses the existing G01
definition, ``sqrt(mean(delta ** 2))`` (uncentered), over requested finite mask
samples. This is a conditioned exact-RMS field, not a claim of strict independent
Gaussian noise or real-phone calibration.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any

import numpy as np


_RMS_DEFINITION = (
    "sqrt(mean(displacement_mm ** 2)); uncentered scalar displacement over "
    "requested mask samples that are finite"
)
_DISTRIBUTION_NOTE = (
    "Conditioned exact RMS comes from deterministic scalar rescaling of this frozen field; "
    "it does not preserve a strict independent-Gaussian model. Real-phone noise calibration "
    "is not claimed."
)


@dataclass(frozen=True)
class RMSFieldCalibration:
    """A calibrated copy plus raw field, mask and independently measured statistics."""

    raw_field_mm: np.ndarray
    calibrated_field_mm: np.ndarray
    mask: np.ndarray
    raw_field_sha256: str
    mask_sha256: str
    status: str
    target_rms_mm: float
    scale_factor: float | None
    raw_rms_mm: float | None
    actual_rms_mm: float | None
    actual_mean_mm: float | None
    actual_peak_abs_mm: float | None
    requested_count: int
    finite_count: int

    def to_metadata(self) -> dict[str, Any]:
        """Return compact JSON-safe provenance and measurements."""
        return {
            "status": self.status,
            "target_rms_mm": self.target_rms_mm,
            "scale_factor": self.scale_factor,
            "raw_rms_mm": self.raw_rms_mm,
            "actual_rms_mm": self.actual_rms_mm,
            "actual_mean_mm": self.actual_mean_mm,
            "actual_peak_abs_mm": self.actual_peak_abs_mm,
            "requested_denominator": self.requested_count,
            "finite_denominator": self.finite_count,
            "nonfinite_requested_count": self.requested_count - self.finite_count,
            "raw_field_sha256": self.raw_field_sha256,
            "mask_sha256": self.mask_sha256,
            "rms_definition": _RMS_DEFINITION,
            "conditioned_exact_rms": self.status == "EXACT",
            "distribution_note": _DISTRIBUTION_NOTE,
            "real_phone_noise_calibration": "NOT_CLAIMED",
        }


def _array_sha256(array: np.ndarray, *, kind: str) -> str:
    """Hash shape and canonical little-endian contents for stable field provenance."""
    header = json.dumps(
        {"kind": kind, "shape": list(array.shape)}, sort_keys=True, separators=(",", ":")
    ).encode("ascii")
    payload = np.ascontiguousarray(array).tobytes(order="C")
    digest = hashlib.sha256()
    digest.update(header)
    digest.update(b"\0")
    digest.update(payload)
    return digest.hexdigest()


def _measure(values: np.ndarray) -> tuple[float, float, float] | None:
    """Measure uncentered RMS, signed mean and absolute peak on finite samples."""
    if values.size == 0:
        return None
    with np.errstate(over="ignore", invalid="ignore"):
        rms = float(np.sqrt(np.mean(values ** 2)))
        mean = float(np.mean(values))
        peak = float(np.max(np.abs(values)))
    if not (np.isfinite(rms) and np.isfinite(mean) and np.isfinite(peak)):
        return None
    return rms, mean, peak


def calibrate_rms_field(
    raw_field_mm: np.ndarray,
    mask: np.ndarray,
    target_rms_mm: float,
) -> RMSFieldCalibration:
    """Condition a frozen mm displacement field to one target RMS in one pass.

    ``mask`` is mandatory and must match the field shape. Samples outside the mask
    are copied unchanged. Missing/nonfinite selected samples are never filled with
    zero: the result is marked UNKNOWN and a positive-target calibration is refused.
    A zero target sets finite selected displacements to zero, the identity displacement
    on the requested region, while retaining nonfinite values and samples outside it.

    ``raw_field_mm`` contains scalar signed displacement values in millimetres. The
    output carries a separate raw copy and SHA-256 so this function can be inserted
    after an existing field has been frozen without re-sampling its random source.
    """
    source = np.asarray(raw_field_mm)
    if source.ndim == 0 or source.dtype.kind not in "iuf":
        raise TypeError("raw_field_mm must be a non-scalar real numeric array")
    raw = np.array(source, dtype=np.float64, copy=True)

    selected_mask = np.asarray(mask)
    if selected_mask.dtype.kind != "b" or selected_mask.shape != raw.shape:
        raise ValueError("mask must be a boolean array with the same shape as raw_field_mm")
    selected_mask = np.array(selected_mask, dtype=bool, copy=True)

    try:
        target = float(target_rms_mm)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("target_rms_mm must be a finite nonnegative scalar") from exc
    if not np.isfinite(target) or target < 0.0:
        raise ValueError("target_rms_mm must be a finite nonnegative scalar")

    requested_count = int(np.count_nonzero(selected_mask))
    selected = raw[selected_mask]
    finite_mask = np.isfinite(selected)
    finite_values = selected[finite_mask]
    finite_count = int(finite_values.size)
    raw_measure = _measure(finite_values)

    output = raw.copy()
    raw_hash = _array_sha256(raw, kind="rms-field-f64-mm-v1")
    mask_hash = _array_sha256(selected_mask, kind="rms-mask-bool-v1")

    def result(status: str, scale: float | None) -> RMSFieldCalibration:
        actual_values = output[selected_mask]
        actual_values = actual_values[np.isfinite(actual_values)]
        actual_measure = _measure(actual_values)
        return RMSFieldCalibration(
            raw_field_mm=raw.copy(),
            calibrated_field_mm=output.copy(),
            mask=selected_mask.copy(),
            raw_field_sha256=raw_hash,
            mask_sha256=mask_hash,
            status=status,
            target_rms_mm=target,
            scale_factor=scale,
            raw_rms_mm=None if raw_measure is None else raw_measure[0],
            actual_rms_mm=None if actual_measure is None else actual_measure[0],
            actual_mean_mm=None if actual_measure is None else actual_measure[1],
            actual_peak_abs_mm=None if actual_measure is None else actual_measure[2],
            requested_count=requested_count,
            finite_count=finite_count,
        )

    if requested_count == 0:
        return result("UNKNOWN_EMPTY_MASK", None)

    if target == 0.0:
        # Zero displacement is the identity transform over the selected finite samples.
        output[selected_mask] = np.where(finite_mask, 0.0, selected)
        if finite_count != requested_count:
            return result("UNKNOWN_NONFINITE_INPUT", 0.0)
        return result("EXACT", 0.0)

    if finite_count != requested_count:
        return result("UNKNOWN_NONFINITE_INPUT", None)
    if raw_measure is None:
        return result("UNKNOWN_NONFINITE_METRIC", None)
    raw_rms = raw_measure[0]
    if raw_rms == 0.0:
        return result("UNKNOWN_DEGENERATE_ZERO_FIELD", None)

    with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
        scale = float(target / raw_rms)
        scaled = finite_values * scale
    if not np.isfinite(scale) or not np.all(np.isfinite(scaled)):
        return result("UNKNOWN_NONFINITE_SCALE", None)

    output[selected_mask] = scaled
    actual_measure = _measure(output[selected_mask])
    if actual_measure is None:
        output[selected_mask] = selected
        return result("UNKNOWN_NONFINITE_METRIC", None)
    return result("EXACT", scale)

