"""Blender render backend tests (plan 13.2 / 30.1 / R7).

The worker is a real external process: these tests either drive the portable Blender
installation that is present on this host, or they assert the *structured error* that the
backend must produce when it is absent or broken.  Nothing here silently falls back to the
software rasteriser.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pytest

import trimesh

from synlab.errors import ErrorCode, SynLabError
from synlab.observe import blender as bl
from synlab.observe.render import (
    BACKEND_BLENDER,
    BACKEND_BLENDER_EEVEE,
    BACKEND_SOFTWARE,
    LightSpec,
    RenderSpec,
    build_scene,
    capability_probe,
    render_view,
)
from synlab.schemas.runtime import ViewFrame

WIDTH, HEIGHT = 96, 72
F_PX = 200.0
CUBE_MM = 100.0
CAM_Z = -400.0
PLATE_Z = -150.0
CUBE_FRONT_MM = abs(CAM_Z) - CUBE_MM / 2.0          # 350 mm
PLATE_FRONT_MM = abs(PLATE_Z - 1.0 - CAM_Z)          # 249 mm

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


# --------------------------------------------------------------------------------------
# fixture
# --------------------------------------------------------------------------------------
def make_frame(dist=None) -> ViewFrame:
    K = np.array([[F_PX, 0.0, (WIDTH - 1) / 2.0],
                  [0.0, F_PX, (HEIGHT - 1) / 2.0],
                  [0.0, 0.0, 1.0]], dtype=np.float64)
    T_WC = np.array([[-1.0, 0.0, 0.0, 0.0],
                     [0.0, -1.0, 0.0, 0.0],
                     [0.0, 0.0, 1.0, CAM_Z],
                     [0.0, 0.0, 0.0, 1.0]], dtype=np.float64)
    return ViewFrame(view_id="test_front", K=K, T_WC=T_WC, image_size=(WIDTH, HEIGHT),
                     profile_id="pinhole_fx200", tier="GLOBAL", u_position_mm=0.0,
                     working_distance_mm=abs(CAM_Z), focus_setting="FIXED",
                     source_kind="SENSOR_SIM", camera_model="PINHOLE", dist=dist)


def make_scene():
    """100 mm cube (target) plus a 40 mm occluder plate in front of it."""
    box = trimesh.creation.box(extents=(CUBE_MM, CUBE_MM, CUBE_MM))
    plate = trimesh.creation.box(extents=(40.0, 40.0, 2.0))
    plate.apply_translation((0.0, 0.0, PLATE_Z))
    mesh = trimesh.util.concatenate([box, plate])
    n_box = len(box.faces)
    n_tot = len(mesh.faces)
    surface_tag = np.zeros(n_tot, dtype=np.int16)
    surface_tag[n_box:] = 2
    is_target = np.ones(n_tot, dtype=np.uint8)
    is_target[n_box:] = 0
    scene = build_scene(mesh, surface_tag=surface_tag, face_id=np.arange(n_tot),
                        is_target=is_target, name="test_fixture")
    light = LightSpec(direction=np.array([-0.35, -0.62, -0.70]) /
                      np.linalg.norm([-0.35, -0.62, -0.70]),
                      color=np.array([2.35, 2.25, 2.10]),
                      ambient=np.array([0.30, 0.30, 0.33]))
    return scene, light


def blender_available() -> bool:
    return bl.find_blender_binary() is not None


needs_blender = pytest.mark.skipif(not blender_available(),
                                   reason="no Blender binary on this host")


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    """One real Blender render of the fixture, reused by the channel tests."""
    if not blender_available():
        pytest.skip("no Blender binary on this host")
    scene, light = make_scene()
    frame = make_frame()
    workdir = tmp_path_factory.mktemp("blender_backend")
    render = render_view(scene, frame, light=light, spec=RenderSpec(),
                         backend=BACKEND_BLENDER,
                         focus_distance_mm=CUBE_FRONT_MM,
                         blender_config=bl.BlenderBackendConfig(
                             samples=32, filter_width=1.5, f_number=1.0,
                             raycast_samples=400, run_label="pytest",
                             workdir=str(workdir)))
    return scene, frame, light, render


# --------------------------------------------------------------------------------------
# 1. binary probe / structured errors
# --------------------------------------------------------------------------------------
def test_binary_discovery_finds_the_portable_build():
    exe = bl.find_blender_binary()
    if exe is None:
        pytest.skip("no Blender binary on this host")
    assert Path(exe).is_file()
    assert Path(exe).name.lower().startswith("blender")
    assert bl.probe_is_ok(bl.selftest()) is True
    report = bl.capability_probe()
    assert report["status"] == "OK"
    assert report["returncode"] == 0
    assert report["version"]


def test_missing_binary_reports_missing_and_names_the_replacement(monkeypatch):
    monkeypatch.setattr(bl, "_env_blender_bin", lambda: None)
    monkeypatch.setattr(bl, "_user_env_blender_bin", lambda: None)
    monkeypatch.setattr(bl, "_portable_candidates", lambda: [])
    monkeypatch.setattr(bl.shutil, "which", lambda name: None)
    monkeypatch.setattr(bl, "_SELFTEST_CACHE", {})
    assert bl.find_blender_binary() is None
    report = bl.selftest()
    assert report["status"] == "MISSING"
    assert report["replacement"] == BACKEND_SOFTWARE
    assert report["argv"] is None
    # a render request must not fall back to the rasteriser
    render = capability_probe(refresh=True)
    assert render["blender"]["status"] == "MISSING"


def test_blender_request_without_binary_raises_env_capability_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(bl, "_env_blender_bin", lambda: None)
    monkeypatch.setattr(bl, "_user_env_blender_bin", lambda: None)
    monkeypatch.setattr(bl, "_portable_candidates", lambda: [])
    monkeypatch.setattr(bl.shutil, "which", lambda name: None)
    scene, light = make_scene()
    with pytest.raises(SynLabError) as excinfo:
        render_view(scene, make_frame(), light=light, spec=RenderSpec(),
                    backend=BACKEND_BLENDER,
                    blender_config=bl.BlenderBackendConfig(
                        samples=1, workdir=str(tmp_path / "nope")))
    assert excinfo.value.code == ErrorCode.ENV_CAPABILITY_MISSING
    assert "BLENDER_BIN" in str(excinfo.value)


def test_nonzero_worker_exit_is_a_structured_error(monkeypatch, tmp_path):
    """A present-but-broken 'Blender' must surface the return code and the stderr tail."""
    decoy = Path(sys.executable)               # a real executable, but not Blender
    monkeypatch.setattr(bl, "_env_blender_bin", lambda: str(decoy))
    monkeypatch.setattr(bl, "_user_env_blender_bin", lambda: None)
    monkeypatch.setattr(bl, "_portable_candidates", lambda: [])
    assert bl.find_blender_binary() == str(decoy)
    scene, light = make_scene()
    with pytest.raises(SynLabError) as excinfo:
        render_view(scene, make_frame(), light=light, spec=RenderSpec(),
                    backend=BACKEND_BLENDER,
                    blender_config=bl.BlenderBackendConfig(
                        samples=1, timeout_s=120.0, workdir=str(tmp_path / "bad")))
    err = excinfo.value
    assert err.code in (ErrorCode.OPERATOR_NOT_REALIZED, ErrorCode.ENV_CAPABILITY_MISSING)
    assert err.measurements.get("returncode") not in (None, 0)
    assert err.evidence_refs, "the argv/stderr evidence must be attached"
    assert any("render_worker.py" in ref for ref in err.evidence_refs)


def test_unknown_backend_string_is_refused():
    scene, light = make_scene()
    with pytest.raises(SynLabError) as excinfo:
        render_view(scene, make_frame(), light=light, spec=RenderSpec(),
                    backend="definitely_not_a_renderer")
    assert excinfo.value.code == ErrorCode.ENV_CAPABILITY_MISSING


def test_eevee_is_refused_with_a_reason():
    scene, light = make_scene()
    with pytest.raises(SynLabError) as excinfo:
        render_view(scene, make_frame(), light=light, spec=RenderSpec(),
                    backend=BACKEND_BLENDER_EEVEE)
    assert excinfo.value.code == ErrorCode.ENV_CAPABILITY_MISSING
    assert "EEVEE" in str(excinfo.value)


def test_distorted_frame_is_refused_unless_explicitly_ignored(tmp_path):
    scene, light = make_scene()
    frame = make_frame(dist=np.array([-0.041, 0.011, 0.0008, -0.0006, -0.0025]))
    frame.camera_model = "OPENCV"
    with pytest.raises(SynLabError) as excinfo:
        render_view(scene, frame, light=light, spec=RenderSpec(),
                    backend=BACKEND_BLENDER,
                    blender_config=bl.BlenderBackendConfig(
                        samples=1, workdir=str(tmp_path / "dist")))
    assert excinfo.value.code == ErrorCode.ENV_CAPABILITY_MISSING
    assert "distortion" in str(excinfo.value).lower()


# --------------------------------------------------------------------------------------
# 2. real render: products, dtype, units
# --------------------------------------------------------------------------------------
@needs_blender
def test_render_products_and_dtypes(rendered):
    _scene, _frame, _light, render = rendered
    assert render.backend == BACKEND_BLENDER
    assert render.rgb_linear.shape == (HEIGHT, WIDTH, 3)
    assert render.rgb_linear.dtype == np.float32
    assert render.depth_z.shape == (HEIGHT, WIDTH)
    assert render.depth_z.dtype == np.float32
    assert np.issubdtype(render.id_map.dtype, np.integer)
    assert np.issubdtype(render.surface_tag.dtype, np.integer)
    assert render.visibility.dtype == np.uint8
    assert render.uncertain_mask.dtype == bool
    # additive float radiance: values above 1.0 are legal and no gamma is baked in
    bg = ~np.isfinite(render.depth_z)
    assert bg.any()
    assert np.allclose(np.median(render.rgb_linear[bg], axis=0), [0.02, 0.02, 0.025],
                       atol=1e-4)


@needs_blender
def test_depth_is_camera_frame_mm(rendered):
    _scene, _frame, _light, render = rendered
    depth = render.depth_z
    valid = np.isfinite(depth)
    assert valid.any()
    # the occluder plate sits 249 mm in front of the camera, the cube face at 350 mm
    assert float(np.nanmin(depth)) == pytest.approx(PLATE_FRONT_MM, abs=0.05)
    center = depth[HEIGHT // 2, WIDTH // 2]
    assert float(center) == pytest.approx(PLATE_FRONT_MM, abs=0.05)
    front = valid & (np.abs(depth - CUBE_FRONT_MM) < 1.0)
    assert front.sum() > 100
    assert float(np.abs(depth[front] - CUBE_FRONT_MM).max()) < 1e-3
    # invalid depth is an explicit NaN, never 0 or a sentinel
    assert not np.any(depth[~valid] == 0.0)


@needs_blender
def test_id_and_surface_tag_are_integers(rendered):
    _scene, _frame, _light, render = rendered
    vis = render.visibility.astype(bool)
    depth = render.depth_z
    bg = ~np.isfinite(depth)
    assert vis.any() and bg.any()
    # background is exactly -1 in both integer channels, never 0 or a fractional value
    assert np.unique(render.id_map[bg]).tolist() == [-1]
    assert np.unique(render.surface_tag[bg]).tolist() == [-1]
    ids = render.id_map[vis]
    assert ids.size and np.all(ids >= 0)
    # every delivered class is a real per-face label of the input mesh (cube 0..11,
    # occluder plate 12..23); visibility covers any scene geometry, as in the rasteriser
    assert set(int(v) for v in np.unique(ids)) <= set(range(24))
    target = geom_ids = render.id_map[np.isfinite(depth) &
                                      (np.abs(depth - CUBE_FRONT_MM) < 1.0)]
    assert set(int(v) for v in np.unique(target)) <= set(range(12))
    tags = set(int(v) for v in np.unique(render.surface_tag[vis]))
    # the occluder carries tag 2, the cube tag 0, and both are integers
    assert tags <= {0, 2}, tags
    assert 2 in tags and 0 in tags


@needs_blender
def test_occlusion_and_uncertain_mask(rendered):
    _scene, _frame, _light, render = rendered
    occlusion = render.occlusion
    assert occlusion.dtype == np.uint8
    # the 40 mm plate at 249 mm projects to ((40 * fx) / 249)^2 pixels
    expected_px = (40.0 * F_PX / PLATE_FRONT_MM) ** 2
    assert 0.85 * expected_px < float(occlusion.sum()) < 1.15 * expected_px
    assert render.meta["occluded_fraction"] > 0.1
    assert render.meta["target_visible_fraction"] > 0.1
    uncertain = render.uncertain_mask
    depth = render.depth_z
    geom = np.isfinite(depth)
    import cv2

    silhouette = geom & ~cv2.erode(geom.astype(np.uint8),
                                   np.ones((3, 3), np.uint8)).astype(bool)
    assert silhouette.any()
    # the mask must cover the real mixing borders ...
    assert float(uncertain[silhouette].mean()) > 0.95
    # ... and stay out of the flat, in-focus target face, away from the label boundary
    # between the two coplanar triangles of that face (a real mixing border)
    id_map = render.id_map
    label_edge = ((id_map != np.roll(id_map, 1, axis=0))
                  | (id_map != np.roll(id_map, 1, axis=1)))
    near = np.ones((7, 7), np.uint8)
    target_face = geom & (np.abs(depth - CUBE_FRONT_MM) < 1.0)
    interior = (target_face
                & ~cv2.dilate(silhouette.astype(np.uint8), near).astype(bool)
                & ~cv2.dilate(label_edge.astype(np.uint8), near).astype(bool))
    assert interior.sum() > 100
    assert float(uncertain[interior].mean()) < 0.02


@needs_blender
def test_manifest_records_measured_not_requested(rendered):
    _scene, _frame, _light, render = rendered
    manifest_path = Path(render.meta["manifest_path"])
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["render"]["samples_requested"] == 32
    assert manifest["render"]["samples_used"] == 32
    assert manifest["blender"]["version"].startswith("5.2")
    assert "blender.exe" in manifest["blender"]["binary"].lower()
    assert manifest["elapsed_seconds"] > 0
    assert manifest["argv"], "the full argv must be recorded"
    for name, entry in manifest["outputs"].items():
        assert len(entry["sha256"]) == 64, name
    checks = manifest["checks"]
    assert checks["camera_model"]["max_uv_error_px"] < 0.1
    assert checks["exact_pass_integrality"]["face_id_non_integral"] == 0
    assert checks["exact_pass_integrality"]["surface_tag_non_integral"] == 0
    ray = checks["raycast_vs_exact_pass"]
    assert ray["status"] == "OK"
    assert ray["max_depth_error_interior_mm"] < 0.01
    assert ray["face_id_mismatch_interior"] == 0
    assert checks["rgb_background_linearity"]["status"] == "OK"
    # measured pass semantics of this Blender build
    aa = checks["pass_aa_behaviour"]
    assert aa["shader_aov_pass_filtered"] is True
    assert aa["z_pass_filtered"] is False
    assert aa["material_index_pass_usable"] is False


# --------------------------------------------------------------------------------------
# 3. software comparison
# --------------------------------------------------------------------------------------
@needs_blender
def test_software_and_blender_agree_on_geometry(rendered):
    scene, frame, light, render = rendered
    software = render_view(scene, frame, light=light,
                           spec=RenderSpec(supersample=2),
                           focus_distance_mm=CUBE_FRONT_MM,
                           backend=BACKEND_SOFTWARE)
    # identical camera-frame depth at the image centre
    assert float(render.depth_z[HEIGHT // 2, WIDTH // 2]) == pytest.approx(
        float(software.depth_z[HEIGHT // 2, WIDTH // 2]), abs=1e-3)
    bl_valid = np.isfinite(render.depth_z)
    sw_valid = np.isfinite(software.depth_z)
    # compare only pixels that neither backend flags as a mixed/defocused border: the two
    # backends rasterise the silhouette differently (supersample disagreement vs a filtered
    # AOV pass), which is exactly what the uncertain masks report
    clean = bl_valid & sw_valid & (~render.uncertain_mask) & (~software.uncertain_mask)
    assert clean.sum() > 1000
    assert float(np.abs(render.depth_z[clean] - software.depth_z[clean]).max()) < 1e-3
    # the integer id classes cover the same faces
    bl_ids = set(int(v) for v in np.unique(render.id_map[bl_valid]))
    sw_ids = set(int(v) for v in np.unique(software.id_map[sw_valid]))
    assert bl_ids <= sw_ids
    # front-face extent within two pixels of the analytic projection in both backends
    expected = CUBE_MM * F_PX / CUBE_FRONT_MM
    for r in (render, software):
        mask = np.isfinite(r.depth_z) & (np.abs(r.depth_z - CUBE_FRONT_MM) < 1.0)
        ys, xs = np.nonzero(mask)
        assert xs.size
        assert abs((xs.max() - xs.min() + 1) - expected) <= 2.0
    assert render.meta["elapsed_seconds"] > 0
    assert software.meta["backend"] == BACKEND_SOFTWARE


@needs_blender
def test_denoise_does_not_touch_geometry_channels(tmp_path):
    scene, light = make_scene()
    frame = make_frame()
    common = dict(samples=8, filter_width=1.5, f_number=1.0)
    plain = render_view(scene, frame, light=light, spec=RenderSpec(),
                        backend=BACKEND_BLENDER, focus_distance_mm=CUBE_FRONT_MM,
                        blender_config=bl.BlenderBackendConfig(
                            run_label="plain", workdir=str(tmp_path / "plain"), **common))
    denoised = render_view(scene, frame, light=light, spec=RenderSpec(),
                           backend=BACKEND_BLENDER, focus_distance_mm=CUBE_FRONT_MM,
                           blender_config=bl.BlenderBackendConfig(
                               denoise=True, run_label="denoised",
                               workdir=str(tmp_path / "denoised"), **common))
    assert not np.array_equal(plain.rgb_linear, denoised.rgb_linear)
    assert np.array_equal(plain.depth_z, denoised.depth_z, equal_nan=True)
    assert np.array_equal(plain.id_map, denoised.id_map)
    assert np.array_equal(plain.surface_tag, denoised.surface_tag)
    assert np.array_equal(plain.visibility, denoised.visibility)
    assert np.array_equal(plain.uncertain_mask, denoised.uncertain_mask)
    assert denoised.meta["denoise"] is True
    assert "RGB only" in denoised.meta["denoise_applies_to"]


# --------------------------------------------------------------------------------------
# 4. doctor wiring
# --------------------------------------------------------------------------------------
@needs_blender
def test_doctor_reports_the_blender_backend_as_pass():
    from synlab.doctor import _blender_check

    check = _blender_check()
    assert check.name == "backend:blender_render"
    assert check.status == "PASS"
    assert check.detail["version"].startswith("5.2")
    assert check.detail["cycles_engine"] == "CYCLES"
