"""Finalize hashes and read-only verification evidence for the visual probe."""

from __future__ import annotations

import hashlib
import json
import platform
from pathlib import Path
import sys

import numpy as np


OUT = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[4]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def strict_json(path: Path):
    def reject_constant(value: str):
        raise ValueError(f"non-strict JSON constant: {value}")
    return json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_constant)


def main() -> None:
    npz_path = OUT / "g01_conditioned_total_rms_fixture.npz"
    corrected_json_path = OUT / "g01_conditioned_total_rms_fixture.json"
    original_json_path = OUT / "g01_conditioned_total_rms_fixture_original.json"
    report = strict_json(corrected_json_path)
    original_report = strict_json(original_json_path)
    with np.load(npz_path, allow_pickle=False) as archive:
        npz_keys = sorted(archive.files)
        npz_shapes = {key: list(archive[key].shape) for key in npz_keys}
        npz_dtypes = {key: str(archive[key].dtype) for key in npz_keys}
        before = archive["points_before_mm"].copy()
        normals = archive["normals_unit"].copy()
        point_count = len(before)
        level_checks = {}
        for suffix, target in (("005", 0.05), ("050", 0.5)):
            after = archive[f"points_after_{suffix}_mm"].copy()
            delta = after - before
            signed = np.einsum("ij,ij->i", delta, normals)
            vector_rms = float(np.sqrt(np.mean(np.sum(delta ** 2, axis=1))))
            signed_rms = float(np.sqrt(np.mean(signed ** 2)))
            level = report["levels"][suffix]
            if not np.array_equal(delta, archive[f"delta_xyz_{suffix}_mm"]):
                raise RuntimeError(f"coordinate delta mismatch for {suffix}")
            if not np.array_equal(signed, archive[f"signed_normal_displacement_{suffix}_mm"]):
                raise RuntimeError(f"signed displacement mismatch for {suffix}")
            if vector_rms != level["coordinate_vector_rms_mm_independent"]:
                raise RuntimeError(f"recorded independent RMS mismatch for {suffix}")
            if abs(vector_rms - target) > 1e-10 or not level["api_realized"]:
                raise RuntimeError(f"realized target/status check failed for {suffix}")
            cond = level["conditioning"]
            outlier_count = int(cond["outlier_count"])
            if cond["outlier_fraction_count_over_points"] != outlier_count / point_count:
                raise RuntimeError(f"outlier fraction count check failed for {suffix}")
            if level["raw_field"]["peak_abs_mm"] is not None:
                raise RuntimeError(f"raw field peak must remain unknown for {suffix}")
            if cond["outlier_labels_exported"]:
                raise RuntimeError(f"outlier labels must not be represented as exported for {suffix}")
            level_checks[suffix] = {
                "target_rms_mm": target,
                "api_reported_coordinate_rms_mm": level["actual_delivered_point_coordinate_rms_mm_api"],
                "npz_recomputed_coordinate_rms_mm": vector_rms,
                "npz_recomputed_signed_normal_rms_mm": signed_rms,
                "outlier_count": outlier_count,
                "outlier_fraction_count_over_points": cond["outlier_fraction_count_over_points"],
                "outlier_fraction_reported_by_api": cond["outlier_fraction_reported_by_api"],
                "outlier_mask_sha256": cond["outlier_mask_sha256"],
                "all_points_condition_mask_sha256": cond["condition_mask_sha256"],
                "raw_field_sha256": level["raw_field"]["sha256_from_calibration"],
                "raw_field_rms_mm": level["raw_field"]["rms_mm_from_calibration"],
                "raw_field_values_exported": level["raw_field"]["full_values_exported"],
                "raw_field_peak_abs_mm": level["raw_field"]["peak_abs_mm"],
                "scale_factor": cond["scale_factor"],
                "absolute_quantiles_mm": level["absolute_displacement_quantiles_mm"],
                "absolute_peak_mm": level["absolute_peak_mm"],
            }

    source_files = {
        "ops_geometry.py": ROOT / "relicweave-synlab/synlab/degrade/ops_geometry.py",
        "axes.py": ROOT / "relicweave-synlab/synlab/degrade/axes.py",
        "test_g01_total_rms_20261005.py": ROOT / "relicweave-synlab/tests/a12/degrade/test_g01_total_rms_20261005.py",
        "rms_fields.py": ROOT / "relicweave-synlab/synlab/degrade/rms_fields.py",
    }
    frozen_originals = {
        "ops_geometry.py.original": OUT.parent / "ops_geometry.py.original",
        "axes.py.original": OUT.parent / "axes.py.original",
    }
    png_names = ("g01_conditioned_total_rms_3d.png",
                 "g01_conditioned_total_rms_displacements.png")
    receipt = {
        "artifact": "A12 G01 visual probe execution receipt",
        "scope": "one synthetic 400-point fixture; production sources were read-only during this probe",
        "generation": {
            "command": "SynLab .venv/Scripts/python.exe -B generate_fixture.py",
            "exit_code": 0,
            "operator_calls": 2,
            "basis_sample_calls": 1,
            "basis_reused_for_both_levels": True,
            "runtime_python": r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\.venv\Scripts\python.exe",
            "generator_source_sha256_current_after_reporting_fix": sha256(OUT / "generate_fixture.py"),
            "note": "Reporting extraction was corrected after generation; NPZ was not regenerated.",
        },
        "report_correction": {
            "command": "SynLab .venv/Scripts/python.exe -B correct_report.py",
            "exit_code": 0,
            "operator_calls": 0,
            "method": "read original JSON receipt and read-only NPZ; recompute coordinate RMS and correct metadata extraction",
            "original_json_sha256": sha256(original_json_path),
            "original_json_npz_sha256": original_report["artifact_hashes"]["npz_sha256"],
        },
        "rendering": {
            "command": "Vesselforge runtime venv/Scripts/python.exe -B render_fixture.py",
            "exit_code": 0,
            "runtime_python": r"C:\Users\xiemo\Desktop\ShardForge\third_party\vesselforge-runtime\venv\Scripts\python.exe",
            "python": sys.version,
            "implementation": platform.python_implementation(),
            "numpy": np.__version__,
            "matplotlib": "3.11.2",
            "npz_access": "read-only allow_pickle=False",
            "plot_geometry": "equal world-unit axis ranges, no magnification, every fixture point shown",
        },
        "npz": {
            "file": npz_path.name,
            "sha256": sha256(npz_path),
            "point_count": point_count,
            "keys": npz_keys,
            "shapes": npz_shapes,
            "dtypes": npz_dtypes,
        },
        "levels": level_checks,
        "frozen_production_hashes_live_after_probe": {
            name: sha256(path) for name, path in source_files.items()
        },
        "frozen_original_snapshot_hashes": {
            name: sha256(path) for name, path in frozen_originals.items()
        },
        "plot_hashes": {name: sha256(OUT / name) for name in png_names},
        "artifact_hashes": {
            name: sha256(OUT / name)
            for name in (
                "g01_conditioned_total_rms_fixture.json",
                "g01_conditioned_total_rms_fixture_original.json",
                "g01_conditioned_total_rms_fixture.npz",
                "generate_fixture.py",
                "render_fixture.py",
                "correct_report.py",
            )
        },
        "validation_scope": {
            "read_only_npz_checks": True,
            "pytest_rerun": False,
            "full_suite_run": False,
            "CAD_or_full_data_generation": False,
            "real_phone_or_independent_gaussian_claim": False,
            "sine_fixture_is_synthetic_not_reconstruction_noise": True,
            "outlier_labels_exported": False,
            "raw_field_values_exported": False,
        },
    }
    receipt_path = OUT / "visual_probe_execution_receipt.json"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, sort_keys=True,
                                       indent=2, allow_nan=False) + "\n",
                            encoding="utf-8", newline="\n")
    print(json.dumps({
        "receipt": str(receipt_path),
        "receipt_sha256": sha256(receipt_path),
        "npz_sha256": sha256(npz_path),
        "json_sha256": sha256(corrected_json_path),
        "plot_hashes": receipt["plot_hashes"],
        "levels": level_checks,
        "production_hashes": receipt["frozen_production_hashes_live_after_probe"],
    }, sort_keys=True, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
