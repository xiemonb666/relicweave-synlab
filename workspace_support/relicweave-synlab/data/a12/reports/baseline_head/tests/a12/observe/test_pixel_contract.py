"""Pixel/display contract tests (plan 30.3, 20.14.1) - the evidence behind A25.

Every number asserted here comes from :func:`synlab.cameras.audit.audit_pixel_contract`,
which measures the real projection/EXIF/display code (and the installed ``pycolmap`` camera
model for the COLMAP round trip).  The report itself is written into a temporary store root,
so the test never touches ``data/a12``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from synlab.cameras.audit import audit_pixel_contract

pytestmark = pytest.mark.external


@pytest.fixture(scope="module")
def report(tmp_path_factory: pytest.TempPathFactory) -> dict:
    root = tmp_path_factory.mktemp("pixel_contract_store")
    return audit_pixel_contract(store=root)


def test_report_shape_and_paths(tmp_path: Path, report: dict) -> None:
    assert set(("ok", "status", "metrics")) <= set(report)
    assert report["status"] in ("PASS", "FAIL")
    assert isinstance(report["metrics"]["failing_checks"], list)
    # A25 reads <store_root>/reports/pixel_contract.json
    for path in report["report_paths"]:
        assert Path(path).name == "pixel_contract.json"
        assert Path(path).exists()


def test_colmap_pixel_centre_convention(report: dict) -> None:
    metrics = report["metrics"]["colmap_convention"]
    assert abs(metrics["cx_shift"] - 0.5) <= 1e-12
    assert abs(metrics["cy_shift"] - 0.5) <= 1e-12
    assert metrics["K_roundtrip_max_error"] <= 1e-12
    assert metrics["uv_roundtrip_max_error_px"] <= 1e-12
    assert report["checks"]["colmap_convention"]["ok"] is True


def test_colmap_real_library_roundtrip(report: dict) -> None:
    """The 0.5 px convention is checked against the installed pycolmap camera model."""
    real = report["metrics"]["colmap_real_library"]
    if not real.get("available"):
        pytest.skip(f"pycolmap unavailable: {real.get('error')}")
    thresholds = report["metrics"]["thresholds"]
    assert real["forward_max_error_px"] <= thresholds["max_px_error"]
    assert real["reverse_max_error_px"] <= thresholds["max_px_error"]
    assert real["principal_point_colmap"] == pytest.approx(
        real["principal_point_opencv_plus_half"], abs=0.0)


def test_pixel_transforms_resize_crop_letterbox(report: dict) -> None:
    transforms = report["metrics"]["pixel_transforms"]
    thresholds = report["metrics"]["thresholds"]
    assert transforms["max_px_error"] <= thresholds["max_px_error"]
    assert transforms["max_mm_error"] <= thresholds["max_mm_error"]
    cases = transforms["cases"]
    # non-integer scale, odd/even sizes, non-zero crop origin, letterbox, non-zero distortion
    for name in ("non_integer_scale", "odd_to_even", "crop_origin_odd", "crop_origin_even",
                 "crop_and_non_integer", "distorted_resize"):
        case = cases[name]
        assert case["ok"] is True, name
        assert case["K_new_matches_A_K"] is True or case["K_new_equals_A_K"] is True
        assert case["max_px_error"] <= thresholds["max_px_error"]
        assert case["max_mm_error"] <= thresholds["max_mm_error"]
    letterbox = cases["non_integer_scale"]["letterbox"]
    assert letterbox["translation_only"] is True
    assert letterbox["K_pad_matches_A_lb_K"] is True
    assert letterbox["max_px_error"] <= thresholds["max_px_error"]


def test_exif_is_applied_to_pixels_and_k(report: dict) -> None:
    exif = report["metrics"]["exif"]
    assert exif["all_orientations_ok"] is True
    ninety = exif["exif_90"]
    assert ninety["pixel_applied"] is True
    assert ninety["size_swapped"] is True
    assert ninety["K_new_equals_A_K"] is True
    assert ninety["metadata_only_would_fail"] is True
    for orientation, entry in exif["orientations"].items():
        assert entry["shape_ok"] is True, orientation
        assert entry["max_pixel_mismatch"] == 0, orientation
        assert entry["K_new_equals_A_K"] is True, orientation


def test_display_contract_100mm_cube(report: dict) -> None:
    """GLB metres/Y-up and the UI millimetre reading, each applied exactly once."""
    display = report["metrics"]["display"]
    thresholds = report["metrics"]["thresholds"]
    assert display["cube_edge_mm"] == 100.0
    assert display["n_edges"] == 12
    assert display["display_edge_max_error_m"] <= thresholds["display_max_error_m"]
    assert display["ui_measure_max_error_mm"] <= thresholds["display_max_error_mm"]
    assert display["roundtrip_identity"] is True
    assert display["roundtrip_max_error_mm"] <= thresholds["display_max_error_mm"]
    assert display["double_application_detected"] is True
    assert display["glb_and_ui_contract_ok"] is True
    assert display["frontend"]["ok"] is True


def test_display_helper_defect_is_recorded_not_hidden(report: dict) -> None:
    """The unused ``authority_to_display`` helper is off by 1e6; it must be reported.

    ``synlab/api/display.py`` is outside this task's write scope, so the audit reports the
    measured scale factor and the audit status follows it (A25 = FAIL until it is fixed).
    """
    display = report["metrics"]["display"]
    if display["authority_to_display_scale_ok"]:
        pytest.skip("synlab/api/display.py::authority_to_display has been fixed")
    defect = display["blocking_defect"]
    assert defect["function"] == "authority_to_display"
    assert defect["measured_scale_ratio"] == pytest.approx(1e6, rel=1e-9)
    assert defect["used_by_production_code"] is False
    assert display["glb_and_ui_contract_ok"] is True
    assert report["ok"] is False and report["status"] == "FAIL"
    assert report["metrics"]["failing_checks"] == ["display"]


def test_report_is_json_serialisable(tmp_path: Path, report: dict) -> None:
    paths = [Path(path) for path in report["report_paths"]]
    payload = json.loads(paths[0].read_text(encoding="utf-8"))
    assert payload["schema"] == "synlab.pixel_contract.v1"
    assert payload["metrics"]["thresholds"]["source"].endswith("qa_protocol_v1.json")
