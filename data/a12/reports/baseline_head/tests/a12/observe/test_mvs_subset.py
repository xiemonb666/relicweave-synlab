"""Real-COLMAP subset tests (plan 14.4) - the evidence behind A14 and A24.

These tests run the actual pycolmap pipeline on frames rendered by the real software
rasteriser.  They are marked ``external`` (pycolmap) and ``slow``; the small configuration
(4 frames, 320x240) keeps one run at a few seconds on this host.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from synlab.observe.mvs_subset import (
    DEFAULT_REPORT_ROOT,
    MvsConfig,
    audit_source_dependency,
    run_mvs_subset,
)

ROOT = Path(__file__).resolve().parents[3]
DEMO_STORE = ROOT / "data" / "a12_demo" / "store"

pytestmark = pytest.mark.external

SMALL = dict(frames_per_fragment=4, delivered_size=(480, 360), render_pixels=480 * 360,
             max_image_size=480, max_num_features=4096, min_registered_frames=2)
#: the source-dependency audit needs a maximally overlapping cluster so that the run-to-run
#: band of the matcher stays small compared with a real input change (see the module doc).
AUDIT = dict(frames_per_fragment=4, delivered_size=(640, 480), render_pixels=640 * 480,
             max_image_size=640, max_num_features=8192)

REQUIRED_FIELDS = ("ok", "pipeline_ok", "attempted", "registered_frames", "sparse_points",
                   "dense_points", "reprojection_error_px", "seconds", "frames", "failures",
                   "real_calibration_ok")


def _has_pycolmap() -> bool:
    try:
        import pycolmap  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


def _abs(path: str) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return ROOT / candidate


def test_config_contract() -> None:
    config = MvsConfig()
    assert config.resolved_matcher(12) == "exhaustive"
    assert config.resolved_matcher(40) == "sequential"
    assert config.camera_model == "SIMPLE_RADIAL"
    assert config.camera_mode == "SINGLE"
    assert config.min_registered_frames >= 2


def test_capability_probe_reports_the_installed_build() -> None:
    from synlab.observe.mvs_subset import _capability_probe

    probe = _capability_probe()
    if not probe.get("import"):
        pytest.skip(f"pycolmap unavailable: {probe.get('error')}")
    assert probe["version"]
    assert probe["has_extract_features"] and probe["has_incremental_mapping"]
    assert probe["has_undistort_images"]
    # documented environment fact: no PatchMatch stereo symbol and no CUDA on this host
    assert isinstance(probe["has_patch_match_stereo"], bool)
    if not probe["has_patch_match_stereo"]:
        assert probe["has_cuda"] is False or probe.get("standalone_colmap_binary") is None


@pytest.mark.slow
def test_run_mvs_subset_writes_a_real_report(tmp_path: Path) -> None:
    if not _has_pycolmap():
        pytest.skip("pycolmap is not installed")
    report = run_mvs_subset(DEMO_STORE, limit_mothers=1, out_dir=tmp_path,
                            config=MvsConfig(**SMALL))
    for key in REQUIRED_FIELDS:
        assert key in report, key
    # provenance is never blended: rendered frames here, real capture has no data
    assert report["data_scope"] == "SYNTHETIC_RENDER"
    assert report["real_capture"] == "REAL_CAPTURE:PENDING"
    assert report["real_calibration_ok"] is False
    assert report["ok"] is False          # the full claim needs real calibration
    assert report["attempted"] == SMALL["frames_per_fragment"]
    assert len(report["frames"]) == report["attempted"]
    # mother came from the committed store asset (not a substitute mesh)
    assert report["mothers"] and report["mothers"][0]["source"] in (
        "COMMITTED_ASSET", "CREATED_IN_RUN")
    assert report["gt_inputs_used"] == {"poses": False, "depth": False, "scale": False}


@pytest.mark.slow
def test_run_mvs_subset_writes_real_images_and_stage_logs(tmp_path: Path) -> None:
    if not _has_pycolmap():
        pytest.skip("pycolmap is not installed")
    report = run_mvs_subset(DEMO_STORE, limit_mothers=1, out_dir=tmp_path,
                            config=MvsConfig(**SMALL))
    for frame in report["frames"]:
        image_path = _abs(frame["image_path"])
        mask_path = _abs(frame["mask_path"])
        assert image_path.exists() and image_path.stat().st_size > 0
        assert mask_path.exists()
        assert str(frame["source_kind"]).upper() == "SENSOR_SIM"
        assert "K" in frame and "T_WC" in frame
        assert len(frame["K"]) == 3 and len(frame["T_WC"]) == 4
        assert isinstance(frame["registered"], bool)
        assert frame["simulator_pose_is_label_only"] is True
    assert len(report["argv_log"]) >= 3
    for stage in report["argv_log"]:
        assert stage["argv"][0].startswith("pycolmap.")
        # every stage records the COLMAP CLI form of its call (db / input / workspace paths)
        assert any(item.startswith("--") and "=" in item for item in stage["argv"][1:])
        assert any(key in " ".join(stage["argv"])
                   for key in ("database_path", "input_path", "workspace_path"))
        assert stage["status"] in ("OK", "FAIL")
        assert stage["returncode"] in (0, 1)
        assert _abs(stage["log_path"]).exists()


@pytest.mark.slow
def test_dense_stage_is_never_faked(tmp_path: Path) -> None:
    """Without PatchMatch the dense stage must stop, not be back-filled with ideal depth."""
    if not _has_pycolmap():
        pytest.skip("pycolmap is not installed")
    report = run_mvs_subset(DEMO_STORE, limit_mothers=1, out_dir=tmp_path,
                            config=MvsConfig(**SMALL))
    dense = report.get("dense", {})
    if report["dense_points"] == 0:
        assert report["dense_status"] in ("MVS_NOT_AVAILABLE", "FAIL", "SKIPPED_BY_CONFIG")
        codes = [failure["code"] for failure in report["failures"]]
        assert "MVS_NOT_AVAILABLE" in codes or "MVS_FAILED" in codes
        assert dense.get("failure_reason") or report["failure_reason"]
    else:
        assert dense.get("fused_ply")


@pytest.mark.slow
def test_source_dependency_audit_is_a_real_experiment(tmp_path: Path) -> None:
    """Corrupted GT poses must not change the reconstruction; a mirrored control must."""
    if not _has_pycolmap():
        pytest.skip("pycolmap is not installed")
    audit = audit_source_dependency(DEMO_STORE, out_dir=tmp_path, frames=4,
                                    config=MvsConfig(**AUDIT))
    for key in ("ok", "metrics", "checks"):
        assert key in audit
    checks = audit["checks"]
    for name in ("frame_source_kind", "gt_pose_invariance", "control_is_sensitive",
                 "pose_priors_empty", "no_depth_or_scale_input"):
        assert name in checks, name
        assert checks[name]["ok"] is True, (name, checks[name].get("detail"))
    assert audit["metrics"]["pose_table_translation_delta_mm"] > 100.0
    assert audit["metrics"]["pose_table_rotation_delta_deg"] > 10.0
    assert audit["metrics"]["sfm_scale_source"]["kind"] == "NONE"
    baseline = audit["metrics"]["determinism_baseline"]
    assert baseline["n_identical_runs"] >= 2
    assert baseline["identical_keypoints_hash"] is True   # extraction is bit-repeatable
    assert audit["metrics"]["true_run"]["keypoints_hash"] == \
        audit["metrics"]["corrupted_run"]["keypoints_hash"]
    assert audit["ok"] is True and audit["status"] == "PASS"


def test_reports_land_where_the_acceptance_harness_reads_them() -> None:
    """A14/A24 read ``<store_root>/reports/*.json``; the canonical root always gets a copy."""
    from synlab.observe.mvs_subset import _report_roots

    roots = _report_roots(DEMO_STORE)
    assert DEFAULT_REPORT_ROOT in roots
    # the committed demo store is a read-only fixture and must never be written into
    demo = DEMO_STORE.resolve()
    for root in roots:
        resolved = root.resolve()
        assert resolved != demo
        assert demo not in resolved.parents
