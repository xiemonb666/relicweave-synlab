"""Generate one small, auditable G01 conditioned-total-RMS visual fixture."""

from __future__ import annotations

import hashlib
import json
import math
import platform
from pathlib import Path
import sys

import numpy as np

from synlab.degrade.axes import G01 as G01Operator  # registers the public axis
from synlab.degrade.api import apply_axis
from synlab.degrade.sources import KIND_GEOMETRY, SourceBundle


OUT = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[4]
MASTER_SEED = 20261005
LINEAGE_ID = "a12-g01-visual-probe-20261005"
FRAGMENT_ID = "plane-grid-20x20-fixed"
VARIANT = "conditioned_total_rms"
TARGETS = ((1, 0.05, "005"), (3, 0.5, "050"))


def file_sha256(path: Path) -> str:
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
    if values.dtype.kind == "f":
        contents = np.ascontiguousarray(values, dtype="<f8")
    elif values.dtype.kind in "iu":
        contents = np.ascontiguousarray(values, dtype="<i8")
    else:
        contents = np.ascontiguousarray(values)
    digest = hashlib.sha256()
    digest.update(header)
    digest.update(b"\0")
    digest.update(contents.tobytes(order="C"))
    return digest.hexdigest()


def json_finite(value):
    if isinstance(value, dict):
        return {str(key): json_finite(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_finite(item) for item in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def quantile_map(values: np.ndarray) -> dict[str, float]:
    return {
        f"p{label}": float(np.quantile(values, q))
        for label, q in (("00", 0.0), ("50", 0.50), ("90", 0.90),
                         ("95", 0.95), ("99", 0.99), ("99_9", 0.999), ("100", 1.0))
    }


def build_fixture() -> tuple[SourceBundle, np.ndarray, np.ndarray, np.ndarray]:
    axis = np.linspace(-9.5, 9.5, 20, dtype=np.float64)
    xx, yy = np.meshgrid(axis, axis, indexing="xy")
    points = np.column_stack((xx.ravel(), yy.ravel(), np.zeros(xx.size, dtype=np.float64)))
    normals = np.zeros_like(points)
    normals[:, 2] = 1.0

    # Fixed low-frequency correlated field and deterministic nonuniform incidence weights.
    coarse = (np.sin((2.0 * np.pi * points[:, 0]) / 22.0)
              * np.cos((2.0 * np.pi * points[:, 1]) / 18.0)).astype(np.float64)
    weights = (0.70
               + 0.40 * (0.5 + 0.5 * np.cos((2.0 * np.pi * points[:, 0]) / 40.0))
               + 0.15 * (0.5 + 0.5 * np.sin((2.0 * np.pi * points[:, 1]) / 33.0)))
    weights = weights.astype(np.float64)

    source = SourceBundle(
        source_kind=KIND_GEOMETRY,
        payload={"points": points, "normals": normals, "frames": []},
        role="visual-probe-observed-geometry",
        schema="a12-g01-visual-fixture-v1",
        unit="mm",
        frame="world",
        lineage_id=LINEAGE_ID,
        fragment_id=FRAGMENT_ID,
        meta={"master_seed": MASTER_SEED, "fixture": "synthetic-only"},
    )
    return source, normals, coarse, weights


def main() -> None:
    source, normals, coarse, weights = build_fixture()
    points_before = np.asarray(source.payload["points"], dtype=np.float64)
    axis = G01Operator()
    context = {
        "axis_id": "G01",
        "lineage_id": LINEAGE_ID,
        "fragment_id": FRAGMENT_ID,
        "master_seed": MASTER_SEED,
        "source": source,
        "source_kind": source.source_kind,
    }

    # Sample the public frozen basis once. The controlled synthetic coarse field and
    # weights replace only its payload values; the same basis object is used at both levels.
    basis = axis.sample_basis(context, np.random.default_rng(MASTER_SEED), VARIANT)
    basis.payload = dict(basis.payload)
    basis.payload.update({
        "coarse_field": coarse.copy(),
        "weight": weights.copy(),
        "field_info": {
            "fixture": "fixed analytical sine coarse field and fixed analytical weights",
            "coarse_field_sha256": array_sha256(coarse),
            "weight_sha256": array_sha256(weights),
        },
        "outlier_probability": 0.02,
    })

    arrays: dict[str, np.ndarray] = {
        "points_before_mm": points_before,
        "normals_unit": normals,
        "coarse_field": coarse,
        "weights": weights,
    }
    levels: dict[str, object] = {}
    for level, target, suffix in TARGETS:
        # This is the public axis entry point; do not generate an alternate/noisy field here.
        record, measurement = apply_axis(
            "G01", level, source, variant=VARIANT, basis=basis,
            parameters={"target_rms_mm": target}, commit=False,
        )
        points_after = np.asarray(record.payload["points"], dtype=np.float64)
        delta_xyz = points_after - points_before
        signed_normal_mm = np.einsum("ij,ij->i", delta_xyz, normals)
        coordinate_vector_rms = float(np.sqrt(np.mean(np.sum(delta_xyz ** 2, axis=1))))
        signed_scalar_rms = float(np.sqrt(np.mean(signed_normal_mm ** 2)))
        actual_reported = measurement.extra.get("actual_delivered_point_coordinate_rms_mm")
        calibration = dict(measurement.extra.get("conditioned_total_rms") or {})
        outlier_count = int(calibration.get("outlier_count", 0))
        abs_disp = np.abs(signed_normal_mm)
        tails = {
            f"abs_gt_{multiplier:g}_target": {
                "count": int(np.count_nonzero(abs_disp > multiplier * target)),
                "fraction": float(np.mean(abs_disp > multiplier * target)),
            }
            for multiplier in (1.0, 2.0, 3.0, 5.0)
        }

        arrays[f"points_after_{suffix}_mm"] = points_after
        arrays[f"delta_xyz_{suffix}_mm"] = delta_xyz
        arrays[f"signed_normal_displacement_{suffix}_mm"] = signed_normal_mm

        levels[suffix] = {
            "level": level,
            "target_rms_mm": target,
            "api_realized": bool(measurement.realized),
            "api_measured": measurement.measured,
            "source_hash": measurement.source_hash,
            "result_hash": measurement.result_hash,
            "output_points_sha256": array_sha256(points_after),
            "delta_xyz_sha256": array_sha256(delta_xyz),
            "signed_normal_displacement_sha256": array_sha256(signed_normal_mm),
            "coordinate_vector_rms_mm_independent": coordinate_vector_rms,
            "signed_normal_rms_mm_independent": signed_scalar_rms,
            "actual_delivered_point_coordinate_rms_mm_api": actual_reported,
            "delivered_minus_target_rms_mm": (
                None if actual_reported is None else float(actual_reported) - target
            ),
            "signed_displacement_quantiles_mm": quantile_map(signed_normal_mm),
            "absolute_displacement_quantiles_mm": quantile_map(abs_disp),
            "absolute_peak_mm": float(np.max(abs_disp)),
            "tail_counts": tails,
            "raw_field": {
                "meaning": "full pre-conditioning scalar delta, including sampled outliers",
                "sha256_from_calibration": calibration.get("raw_field_sha256"),
                "rms_mm_from_calibration": calibration.get("raw_rms_mm"),
                "peak_abs_mm": None,
                "peak_abs_status": "UNKNOWN_NOT_EXPORTED",
                "full_values_exported": False,
                "outlier_labels_exported": False,
            },
            "conditioning": {
                "field_status": calibration.get("field_conditioning_status", calibration.get("status")),
                "delivery_status": calibration.get("delivery_status", measurement.extra.get("realization_status")),
                "conditioned_field_rms_mm": calibration.get("conditioned_field_rms_mm",
                                                               calibration.get("actual_rms_mm")),
                "conditioned_field_peak_abs_mm": calibration.get("actual_peak_abs_mm"),
                "condition_mask_scope": calibration.get("condition_mask_scope", "all_points"),
                "condition_mask_sha256": calibration.get("mask_sha256"),
                "scale_factor": calibration.get("scale_factor"),
                "outlier_count": outlier_count,
                "outlier_fraction_count_over_points": float(outlier_count / len(points_before)),
                "outlier_fraction_reported_by_api": measurement.measured.get("outlier_fraction"),
                "outlier_mask_sha256": calibration.get("outlier_mask_sha256"),
                "outlier_labels_exported": False,
                "point_count": int(len(points_before)),
                "rms_definition": calibration.get("rms_definition"),
                "distribution_note": calibration.get("distribution_note"),
                "real_phone_noise_calibration": calibration.get("real_phone_noise_calibration"),
            },
        }

    npz_path = OUT / "g01_conditioned_total_rms_fixture.npz"
    np.savez_compressed(npz_path, **arrays)

    source_paths = {
        "ops_geometry.py": ROOT / "relicweave-synlab/synlab/degrade/ops_geometry.py",
        "axes.py": ROOT / "relicweave-synlab/synlab/degrade/axes.py",
        "test_g01_total_rms_20261005.py": ROOT / "relicweave-synlab/tests/a12/degrade/test_g01_total_rms_20261005.py",
        "rms_fields.py": ROOT / "relicweave-synlab/synlab/degrade/rms_fields.py",
    }
    payload = {
        "artifact": "A12 G01 conditioned_total_rms synthetic visual probe",
        "scope": "small deterministic fixture; no real-phone calibration claim",
        "input_dictionary": {
            "source_bundle": {
                "source_kind": source.source_kind,
                "asset_id": source.asset_id,
                "role": source.role,
                "schema": source.schema,
                "unit": source.unit,
                "frame": source.frame,
                "lineage_id": source.lineage_id,
                "fragment_id": source.fragment_id,
                "meta": source.meta,
                "payload_keys": sorted(source.payload),
                "content_hash": source.content_hash(),
                "point_count": int(len(points_before)),
                "points_sha256": array_sha256(points_before),
                "normals_sha256": array_sha256(normals),
                "frames": [],
            },
            "context": {
                "axis_id": context["axis_id"],
                "lineage_id": context["lineage_id"],
                "fragment_id": context["fragment_id"],
                "master_seed": context["master_seed"],
                "source_kind": context["source_kind"],
                "source_content_hash": source.content_hash(),
            },
            "fixture_geometry": {
                "shape": "20x20 planar grid; z=0 mm; x,y=-9.5..9.5 mm at 1 mm spacing",
                "normal": [0.0, 0.0, 1.0],
                "coarse_field_formula": "sin(2*pi*x/22)*cos(2*pi*y/18)",
                "coarse_field_sha256": array_sha256(coarse),
                "weight_formula": "0.70+0.40*(0.5+0.5*cos(2*pi*x/40))+0.15*(0.5+0.5*sin(2*pi*y/33))",
                "weight_sha256": array_sha256(weights),
                "outlier_probability": 0.02,
                "field_payload_override": "analytical synthetic coarse_field and weights replace sampled basis payload values",
            },
            "basis": {
                "axis_id": basis.axis_id,
                "variant": basis.variant,
                "basis_id": basis.basis_id,
                "seed_ref": basis.seed_ref,
                "master_seed": MASTER_SEED,
                "same_basis_object_used_for_both_levels": True,
                "per_level_rng_note": "G01 derives apply randomness from basis id plus level; outlier realizations may differ by level",
                "basis_rng_outlier_sample_sha256_not_claimed": None,
            },
            "api_call": {
                "function": "synlab.degrade.api.apply_axis",
                "arguments_shared": {"axis_id": "G01", "variant": VARIANT, "commit": False},
                "levels_targets": [{"level": level, "target_rms_mm": target} for level, target, _ in TARGETS],
            },
        },
        "levels": levels,
        "artifact_hashes": {
            "npz_file": npz_path.name,
            "npz_sha256": file_sha256(npz_path),
            "input_output_hashes_use": "canonical little-endian float64 bytes with shape/kind prefix",
        },
        "runtime": {
            "python": sys.version,
            "python_executable": sys.executable,
            "python_implementation": platform.python_implementation(),
            "platform": platform.platform(),
            "numpy": np.__version__,
        },
        "source_sha256": {name: file_sha256(path) for name, path in source_paths.items()},
        "interpretation_limits": [
            "Conditioned exact scalar-field RMS is a deterministic rescale of a frozen full field, including sampled outliers.",
            "The two level RNG derivations can produce different outlier labels; these outputs do not establish same-field monotonic behavior.",
            "This synthetic fixture does not establish real-phone calibration or independent Gaussian noise.",
            "All 400 points are retained in NPZ and plots; plots do not interpolate or suppress tail points.",
        ],
        "plot_outputs": [
            "g01_conditioned_total_rms_3d.png",
            "g01_conditioned_total_rms_displacements.png",
        ],
    }
    json_path = OUT / "g01_conditioned_total_rms_fixture.json"
    with json_path.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(json_finite(payload), stream, ensure_ascii=False, sort_keys=True,
                  indent=2, allow_nan=False)
        stream.write("\n")

    print(json.dumps({
        "npz": str(npz_path),
        "json": str(json_path),
        "npz_sha256": file_sha256(npz_path),
        "json_sha256": file_sha256(json_path),
        "point_count": int(len(points_before)),
        "levels": {
            key: {
                "target_rms_mm": item["target_rms_mm"],
                "api_realized": item["api_realized"],
                "actual_coordinate_rms_mm": item["actual_delivered_point_coordinate_rms_mm_api"],
                "outlier_count": item["conditioning"]["outlier_count"],
                "outlier_mask_sha256": item["conditioning"]["outlier_mask_sha256"],
            }
            for key, item in levels.items()
        },
        "runtime": sys.executable,
    }, sort_keys=True, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
