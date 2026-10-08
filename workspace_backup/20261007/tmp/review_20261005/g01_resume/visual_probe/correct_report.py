"""Correct reporting fields from the frozen JSON receipt and read-only NPZ."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np


OUT = Path(__file__).resolve().parent
SOURCE_JSON = OUT / "g01_conditioned_total_rms_fixture_original.json"
TARGET_JSON = OUT / "g01_conditioned_total_rms_fixture.json"
NPZ = OUT / "g01_conditioned_total_rms_fixture.npz"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def array_sha256(array: np.ndarray, *, kind: str = "fixture-f64-mm-v1") -> str:
    values = np.asarray(array)
    header = json.dumps(
        {"kind": kind, "shape": list(values.shape)}, sort_keys=True, separators=(",", ":")
    ).encode("ascii")
    contents = (np.ascontiguousarray(values, dtype="<f8") if values.dtype.kind == "f"
                else np.ascontiguousarray(values, dtype="<i8"))
    digest = hashlib.sha256()
    digest.update(header)
    digest.update(b"\0")
    digest.update(contents.tobytes(order="C"))
    return digest.hexdigest()


def quantiles(values: np.ndarray) -> dict[str, float]:
    return {
        f"p{label}": float(np.quantile(values, q))
        for label, q in (("00", 0.0), ("50", 0.50), ("90", 0.90),
                         ("95", 0.95), ("99", 0.99), ("99_9", 0.999), ("100", 1.0))
    }


def main() -> None:
    original_hash = sha256(SOURCE_JSON)
    report = json.loads(SOURCE_JSON.read_text(encoding="utf-8"))
    with np.load(NPZ, allow_pickle=False) as archive:
        points = archive["points_before_mm"].copy()
        normals = archive["normals_unit"].copy()
        count_points = len(points)
        suffix_by_level = {"005": 0.05, "050": 0.5}
        for suffix, target in suffix_by_level.items():
            after = archive[f"points_after_{suffix}_mm"].copy()
            stored_delta = archive[f"delta_xyz_{suffix}_mm"].copy()
            stored_signed = archive[f"signed_normal_displacement_{suffix}_mm"].copy()
            delta = after - points
            signed = np.einsum("ij,ij->i", delta, normals)
            if not np.array_equal(delta, stored_delta):
                raise RuntimeError(f"NPZ delta verification failed for level {suffix}")
            if not np.array_equal(signed, stored_signed):
                raise RuntimeError(f"NPZ signed displacement verification failed for level {suffix}")

            level = report["levels"][suffix]
            actual_vector_rms = float(np.sqrt(np.mean(np.sum(delta ** 2, axis=1))))
            actual_signed_rms = float(np.sqrt(np.mean(signed ** 2)))
            api_reported_rms = float(level["api_measured"]["applied_rms_mm"])
            if abs(actual_vector_rms - target) > 1e-10:
                raise RuntimeError(f"NPZ coordinate RMS does not meet fixture target for {suffix}")
            level["coordinate_vector_rms_mm_independent"] = actual_vector_rms
            level["signed_normal_rms_mm_independent"] = actual_signed_rms
            level["actual_delivered_point_coordinate_rms_mm_api"] = api_reported_rms
            level["actual_delivered_coordinate_rms_mm_npz_independent"] = actual_vector_rms
            level["delivered_minus_target_rms_mm_api"] = api_reported_rms - target
            level["delivered_minus_target_rms_mm_npz_independent"] = actual_vector_rms - target
            level["signed_displacement_quantiles_mm"] = quantiles(signed)
            level["absolute_displacement_quantiles_mm"] = quantiles(np.abs(signed))
            level["absolute_peak_mm"] = float(np.max(np.abs(signed)))

            tails = {}
            for multiplier in (1.0, 2.0, 3.0, 5.0):
                selected = np.abs(signed) > multiplier * target
                tails[f"abs_gt_{multiplier:g}_target"] = {
                    "count": int(np.count_nonzero(selected)),
                    "fraction": float(np.mean(selected)),
                }
            level["tail_counts"] = tails

            conditioning = level["conditioning"]
            raw_field = level["raw_field"]
            outlier_count = int(conditioning["outlier_count"])
            api_fraction = float(level["api_measured"]["outlier_fraction"])
            conditioning.pop("outlier_fraction", None)
            conditioning["outlier_fraction_count_over_points"] = outlier_count / count_points
            conditioning["outlier_fraction_reported_by_api"] = api_fraction
            conditioning["outlier_labels_exported"] = False
            raw_field["peak_abs_mm"] = None
            raw_field["peak_abs_status"] = "UNKNOWN_NOT_EXPORTED"
            raw_field["full_values_exported"] = False
            raw_field["outlier_labels_exported"] = False
            raw_peak = raw_field.pop("peak_abs_mm_from_calibration", None)
            if raw_peak is not None:
                conditioning["conditioned_field_peak_abs_mm"] = raw_peak
            raw_field["meaning"] = "full pre-conditioning scalar delta, including sampled outliers; hash/statistics only"

    report["artifact_hashes"]["npz_sha256"] = sha256(NPZ)
    report["report_correction"] = {
        "source_receipt": SOURCE_JSON.name,
        "source_receipt_sha256": original_hash,
        "correction_method": "read-only NPZ coordinate recomputation; no operator invocation",
        "actual_coordinate_rms_independently_recomputed": True,
        "outlier_fraction_corrected_from_count_over_point_count_and_api_measurement": True,
        "raw_peak_relabelled_as_unknown_because_raw_values_were_not_exported": True,
    }
    limits = report["interpretation_limits"]
    limits.append(
        "The visible spatial bands come from the fixed analytical sine fixture; they are not a model of real reconstruction or sensor noise."
    )
    TARGET_JSON.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps({
        "source_receipt_sha256": original_hash,
        "corrected_json_sha256": sha256(TARGET_JSON),
        "npz_sha256": sha256(NPZ),
        "point_count": count_points,
        "levels": {
            key: {
                "target_rms_mm": report["levels"][key]["target_rms_mm"],
                "coordinate_vector_rms_mm": report["levels"][key]["coordinate_vector_rms_mm_independent"],
                "outlier_count": report["levels"][key]["conditioning"]["outlier_count"],
                "outlier_fraction_count_over_points": report["levels"][key]["conditioning"]["outlier_fraction_count_over_points"],
                "outlier_fraction_reported_by_api": report["levels"][key]["conditioning"]["outlier_fraction_reported_by_api"],
                "raw_peak": report["levels"][key]["raw_field"]["peak_abs_mm"],
            }
            for key in suffix_by_level
        },
        "operator_rerun": False,
    }, sort_keys=True, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
