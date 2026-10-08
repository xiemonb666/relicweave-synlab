"""Renderer dispatch wiring tests: software default, Blender opt-in (plan 13.2 / R3).

These tests cover the *route wiring* introduced for the 12-view cache:

* ``renderer: auto`` / ``software_rasterizer`` -> the in-process software rasteriser, i.e.
  the behaviour every existing caller had before a renderer could be selected at all;
* ``renderer: blender`` -> the real Blender Cycles subprocess worker, and a structured
  ``ENV_CAPABILITY_MISSING`` when this host has no usable Blender binary - never a
  rasterised frame that is labelled Blender;
* the OpenCV-distortion policy of a Blender frame: refusal by default, ``undistort`` and
  ``ignore`` only when they are declared.

A test that needs the real Blender binary is skipped when it is absent; nothing here is
relaxed to make a test pass on a host without Blender.
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from synlab.cameras.api import camera_profiles
from synlab.errors import ErrorCode, SynLabError
from synlab.mothers.api import create_mother, default_params
from synlab.observe import routes as rt
from synlab.observe.api import observe
from synlab.observe.blender import (
    BlenderBackendConfig,
    find_blender_binary,
)
from synlab.observe.render import (
    BACKEND_BLENDER,
    BACKEND_SOFTWARE,
    RenderSpec,
)
from synlab.seeds import make_rng

REPO_ROOT = Path(__file__).resolve().parents[3]
GENERATION_CONFIG = REPO_ROOT / "configs" / "a12" / "next_experiment.yaml"

#: Declared vocabulary that must keep meaning "the historical software path".
SOFTWARE_REQUESTS = ("auto", "software_rasterizer", "software", "auto_software",
                     BACKEND_SOFTWARE)


def blender_available() -> bool:
    return find_blender_binary() is not None


needs_blender = pytest.mark.skipif(not blender_available(),
                                   reason="no Blender binary on this host")


# --------------------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def mother():
    return create_mother("V13", "M01", default_params("V13"),
                         make_rng(7, "renderer_dispatch", "V13"), mother_id="V13-dispatch")


@pytest.fixture(scope="module")
def target(mother):
    return rt.resolve_target(mother, None)


@pytest.fixture(scope="module")
def profile():
    """The shipped GLOBAL profile: OPENCV camera model with real distortion."""
    return camera_profiles()[0]


@pytest.fixture(scope="module")
def pinhole_profile(profile):
    """Declared distortion-free twin of ``profile`` (same optics, ideal pinhole)."""
    return replace(profile, dist=np.zeros(5, dtype=np.float64),
                   meta={**profile.meta, "camera_model": "PINHOLE"})


def small_spec(**overrides) -> rt.ObsSpec:
    base = dict(view_count=1, delivered_size=(96, 72), max_render_pixels=96 * 72,
                render_spec=RenderSpec(supersample=1), master_seed=7,
                lineage_id="dispatch_test")
    base.update(overrides)
    return rt.ObsSpec(**base)


def blender_cfg(tmp_path: Path, name: str, samples: int = 8) -> BlenderBackendConfig:
    return BlenderBackendConfig(samples=samples, filter_width=1.5, f_number=8.0,
                                raycast_samples=200, run_label=name,
                                workdir=str(tmp_path / name))


@pytest.fixture()
def render_spy(monkeypatch):
    """Record the ``backend`` argument of every real ``render_view`` call."""
    calls: list[str] = []
    original = rt.render_view

    def wrapper(scene, frame, **kwargs):
        calls.append(str(kwargs.get("backend")))
        return original(scene, frame, **kwargs)

    monkeypatch.setattr(rt, "render_view", wrapper)
    return calls


# --------------------------------------------------------------------------------------
# 1. the default is unchanged
# --------------------------------------------------------------------------------------
def test_obs_spec_defaults_are_the_historical_ones():
    spec = rt.ObsSpec()
    assert spec.renderer == "auto"
    assert spec.distortion_policy == rt.DISTORTION_POLICY_ERROR
    assert spec.blender_config is None
    assert spec.view_count == 12
    assert spec.delivered_size == (512, 384)
    # no argument at all -> the software rasteriser, exactly as before
    assert rt.resolve_render_backend() == BACKEND_SOFTWARE
    assert rt.resolve_render_backend(None, spec=rt.ObsSpec()) == BACKEND_SOFTWARE
    assert rt.render_backend_name() == BACKEND_SOFTWARE
    assert rt.render_backend_class() == "CUSTOM_GAP"


@pytest.mark.parametrize("requested", SOFTWARE_REQUESTS)
def test_software_requests_resolve_to_the_rasterizer(requested):
    assert rt.resolve_render_backend(requested) == BACKEND_SOFTWARE
    assert rt.resolve_render_backend(requested, spec=small_spec(renderer="blender")) \
        == BACKEND_SOFTWARE


def test_auto_render_uses_the_software_rasterizer(target, profile, render_spy):
    spec = small_spec()
    obs, bundles = rt.route_ideal_visible(target, profile, spec,
                                          make_rng(7, "dispatch_test", "auto"))
    assert bundles and all(b.backend == BACKEND_SOFTWARE for b in bundles)
    assert all(b.render.backend == BACKEND_SOFTWARE for b in bundles)
    assert render_spy == [BACKEND_SOFTWARE] * len(bundles)
    assert obs.meta["renderer"] == BACKEND_SOFTWARE
    assert obs.meta["renderer_requested"] == "auto"
    assert obs.meta["renderer_class"] == "CUSTOM_GAP"
    assert obs.meta["renderer_backend"] == BACKEND_SOFTWARE
    for view in obs.views:
        assert view.meta["render_backend"] == BACKEND_SOFTWARE
        assert view.meta["render_backend_class"] == "CUSTOM_GAP"
        assert view.frame.meta["backend"] == BACKEND_SOFTWARE


def test_generation_config_projection_still_selects_the_software_rasterizer():
    """``configs/a12/next_experiment.yaml`` (``renderer: auto``) must not change meaning."""
    from synlab.config import load_generation_spec
    from synlab.pipeline import _resolve_observe_spec

    spec = load_generation_spec(str(GENERATION_CONFIG))
    assert str(spec.observation.renderer) == "auto"
    projected = _resolve_observe_spec(spec, None)
    assert projected.renderer == "auto"
    assert projected.distortion_policy == rt.DISTORTION_POLICY_ERROR
    assert projected.blender_config is None
    assert rt.resolve_render_backend(spec=projected) == BACKEND_SOFTWARE
    # the batch pipeline calls observe() without a renderer argument
    assert rt.resolve_render_backend(None, spec=projected) == BACKEND_SOFTWARE


def test_observe_without_renderer_stays_on_the_software_path(mother, render_spy):
    obs = observe(mother, None, make_rng(7, "dispatch_test", "observe_auto"),
                  route=rt.ROUTE_IDEAL_VISIBLE, spec=small_spec())
    assert obs.meta["renderer"] == BACKEND_SOFTWARE
    assert set(render_spy) == {BACKEND_SOFTWARE}
    assert {view.meta["render_backend"] for view in obs.views} == {BACKEND_SOFTWARE}


# --------------------------------------------------------------------------------------
# 2. renderer selection is explicit and honest
# --------------------------------------------------------------------------------------
def test_unknown_renderer_is_refused():
    with pytest.raises(SynLabError) as excinfo:
        rt.resolve_render_backend("definitely_not_a_renderer")
    assert excinfo.value.code == ErrorCode.SCHEMA_INVALID
    assert "unknown renderer" in str(excinfo.value)


def test_blender_request_without_a_binary_is_a_structured_error(monkeypatch, mother,
                                                                render_spy):
    """A missing Blender must raise, not silently rasterise and label it Blender."""
    monkeypatch.setattr(rt, "blender_binary", lambda: None)
    with pytest.raises(SynLabError) as excinfo:
        rt.resolve_render_backend("blender")
    err = excinfo.value
    assert err.code == ErrorCode.ENV_CAPABILITY_MISSING
    assert "NOT downgraded" in str(err)
    assert err.evidence_refs, "the probe record must be attached"

    with pytest.raises(SynLabError) as excinfo:
        rt.render_views(rt.resolve_target(mother, None), camera_profiles()[0],
                        small_spec(renderer="blender"),
                        make_rng(7, "dispatch_test", "missing"),
                        backend="blender")
    assert excinfo.value.code == ErrorCode.ENV_CAPABILITY_MISSING

    with pytest.raises(SynLabError) as excinfo:
        observe(mother, None, make_rng(7, "dispatch_test", "missing_api"),
                route=rt.ROUTE_IDEAL_VISIBLE, spec=small_spec(), renderer="blender")
    assert excinfo.value.code == ErrorCode.ENV_CAPABILITY_MISSING
    # no software frame was produced on the way out
    assert render_spy == []


@needs_blender
def test_blender_request_renders_with_the_real_worker(target, profile, tmp_path,
                                                      render_spy):
    spec = small_spec(renderer="blender", distortion_policy=rt.DISTORTION_POLICY_UNDISTORT,
                      blender_config=blender_cfg(tmp_path, "dispatch_undistort"))
    obs, bundles = rt.route_ideal_visible(target, profile, spec,
                                          make_rng(7, "dispatch_test", "blender"))
    assert render_spy == [BACKEND_BLENDER]
    bundle = bundles[0]
    render = bundle.render
    # a real Blender run, measured (this cannot be produced by the rasteriser)
    assert render.backend == BACKEND_BLENDER
    assert bundle.backend == BACKEND_BLENDER
    assert render.meta["backend_class"] == "ADAPTER"
    assert str(render.meta["blender_version"]).startswith("5.2")
    assert Path(render.meta["manifest_path"]).is_file()
    assert int(render.meta["samples_used"]) == 8
    # the undistorted pinhole frame is what was rendered and what is delivered
    assert bundle.render_frame.camera_model == "PINHOLE"
    assert bundle.render_frame.dist is None
    assert bundle.distortion["distortion_undistorted"] is True
    assert bundle.distortion["distortion_max_pixel_effect_px"] > 0.0
    assert np.asarray(bundle.distortion["distortion_coefficients"]).shape == (5,)
    # the observation records the Blender backend, not the rasteriser
    assert obs.meta["renderer"] == BACKEND_BLENDER
    assert obs.meta["renderer_requested"] == "blender"
    assert obs.meta["renderer_class"] == "ADAPTER"
    assert obs.meta["renderer_backend"] == BACKEND_BLENDER
    view = obs.views[0]
    assert view.meta["render_backend"] == BACKEND_BLENDER
    assert view.meta["render_backend_class"] == "ADAPTER"
    assert view.meta["distortion"]["distortion_policy"] == rt.DISTORTION_POLICY_UNDISTORT
    assert view.frame.camera_model == "PINHOLE"
    assert view.frame.dist is None
    assert view.frame.meta["backend"] == BACKEND_BLENDER


@needs_blender
def test_proxy_scan_route_can_select_blender(target, profile, tmp_path):
    spec = small_spec(renderer="blender", distortion_policy=rt.DISTORTION_POLICY_UNDISTORT,
                      blender_config=blender_cfg(tmp_path, "dispatch_proxy"))
    obs, bundles = rt.route_proxy_scan(target, profile, spec,
                                       make_rng(7, "dispatch_test", "proxy"))
    assert bundles[0].render.backend == BACKEND_BLENDER
    assert obs.meta["renderer"] == BACKEND_BLENDER
    assert obs.route == rt.ROUTE_PROXY_SCAN


@needs_blender
def test_photo_mvs_route_can_select_blender(target, profile, tmp_path, monkeypatch):
    """The RGB/MVS route renders with Blender; the SfM stage is stubbed out of this test.

    ``pycolmap`` is removed from ``sys.modules`` so the test cannot confuse a COLMAP
    outcome (or its cost) with the renderer wiring; the route must still stop
    *structurally* (``MVS_NOT_AVAILABLE``) after rendering with Blender.
    """
    monkeypatch.setitem(sys.modules, "pycolmap", None)
    spec = small_spec(renderer="blender", distortion_policy=rt.DISTORTION_POLICY_UNDISTORT,
                      blender_config=blender_cfg(tmp_path, "dispatch_mvs"),
                      route_params={"workdir": str(tmp_path / "mvs")})
    obs, bundles, report = rt.route_photo_mvs(target, profile, spec,
                                              make_rng(7, "dispatch_test", "mvs"))
    assert bundles[0].render.backend == BACKEND_BLENDER
    assert report["renderer_backend"] == BACKEND_BLENDER
    assert report["renderer_requested"] == "blender"
    assert report["failure_code"] == ErrorCode.MVS_NOT_AVAILABLE.value
    assert obs.meta["renderer"] == BACKEND_BLENDER
    assert obs.views[0].meta["render_backend"] == BACKEND_BLENDER


# --------------------------------------------------------------------------------------
# 3. OpenCV distortion policy (the Blender worker renders an ideal pinhole)
# --------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def distorted_frame(profile, target):
    from synlab.cameras.viewframes import make_view_frames

    frames = make_view_frames(profile, target.bbox, 1, make_rng(7, "dispatch_test", "frame"),
                              tiers=("GLOBAL", "MID", "LOCAL"), orbit=True)
    frame = frames[0]
    assert np.abs(np.asarray(frame.dist)).max() > 0.0, "fixture needs a distorted profile"
    assert frame.camera_model == "OPENCV"
    return frame


def test_distorted_blender_frame_is_refused_by_default(distorted_frame):
    spec = rt.ObsSpec()
    assert spec.distortion_policy == rt.DISTORTION_POLICY_ERROR
    with pytest.raises(SynLabError) as excinfo:
        rt.render_frame_for_backend(distorted_frame, backend=BACKEND_BLENDER, spec=spec)
    err = excinfo.value
    assert err.code == ErrorCode.ENV_CAPABILITY_MISSING
    assert "distortion" in str(err).lower()
    assert len(err.measurements["dist"]) == 5
    assert err.measurements["max_pixel_effect_px"] > 0.0


def test_distortion_is_never_silently_dropped_on_the_software_path(distorted_frame):
    frame, provenance = rt.render_frame_for_backend(
        distorted_frame, backend=BACKEND_SOFTWARE,
        spec=rt.ObsSpec(distortion_policy=rt.DISTORTION_POLICY_ERROR))
    assert provenance == {"distortion_policy": rt.DISTORTION_POLICY_ERROR}
    assert np.asarray(frame.dist).tolist() == np.asarray(distorted_frame.dist).tolist()


def test_undistort_policy_renders_the_undistorted_pinhole_camera(distorted_frame):
    frame, provenance = rt.render_frame_for_backend(
        distorted_frame, backend=BACKEND_BLENDER,
        spec=rt.ObsSpec(distortion_policy=rt.DISTORTION_POLICY_UNDISTORT))
    assert frame.dist is None
    assert frame.camera_model == "PINHOLE"
    assert frame.K.tolist() == np.asarray(distorted_frame.K).tolist()
    assert frame.meta["undistorted_from"]["dist"] == \
        np.asarray(distorted_frame.dist).tolist()
    assert provenance["distortion_undistorted"] is True
    assert provenance["distortion_coefficients"] == \
        np.asarray(distorted_frame.dist).tolist()
    assert provenance["distortion_max_pixel_effect_px"] > 0.0
    # the original frame is not mutated
    assert distorted_frame.dist is not None


def test_ignore_policy_records_the_dropped_coefficients(distorted_frame):
    spec = rt.ObsSpec(distortion_policy=rt.DISTORTION_POLICY_IGNORE)
    frame, provenance = rt.render_frame_for_backend(distorted_frame,
                                                    backend=BACKEND_BLENDER, spec=spec)
    assert np.asarray(frame.dist).tolist() == np.asarray(distorted_frame.dist).tolist()
    assert provenance["distortion_ignored"] is True
    assert provenance["distortion_coefficients"] == \
        np.asarray(distorted_frame.dist).tolist()
    assert provenance["distortion_max_pixel_effect_px"] > 0.0
    # the adapter is told to ignore as well, so its manifest records it
    config = rt.blender_config_for(spec, frame=frame)
    assert config.distortion_policy == rt.DISTORTION_POLICY_IGNORE


def test_undistorted_frames_are_not_touched_by_the_policy(distorted_frame):
    pinhole = replace(distorted_frame, dist=None, camera_model="PINHOLE")
    for policy in rt.DISTORTION_POLICIES:
        frame, provenance = rt.render_frame_for_backend(
            pinhole, backend=BACKEND_BLENDER, spec=rt.ObsSpec(distortion_policy=policy))
        assert frame is pinhole
        assert provenance == {"distortion_policy": policy}


def test_unknown_distortion_policy_is_refused(distorted_frame):
    with pytest.raises(SynLabError) as excinfo:
        rt.render_frame_for_backend(distorted_frame, backend=BACKEND_BLENDER,
                                    spec=rt.ObsSpec(distortion_policy="whatever"))
    assert excinfo.value.code == ErrorCode.SCHEMA_INVALID


@needs_blender
def test_ignore_policy_renders_anyway_and_records_it(target, profile, tmp_path):
    spec = small_spec(renderer="blender", distortion_policy=rt.DISTORTION_POLICY_IGNORE,
                      blender_config=blender_cfg(tmp_path, "dispatch_ignore"))
    obs, bundles = rt.route_ideal_visible(target, profile, spec,
                                          make_rng(7, "dispatch_test", "ignore"))
    render = bundles[0].render
    assert render.backend == BACKEND_BLENDER
    assert render.meta["distortion_ignored"] is True
    assert bundles[0].distortion["distortion_ignored"] is True
    # the delivered frame still declares the distortion that was *not* rendered
    assert obs.views[0].frame.dist is not None
    assert obs.views[0].meta["distortion"]["distortion_coefficients"] == \
        np.asarray(profile.dist).tolist()


def test_blender_config_type_is_checked():
    with pytest.raises(SynLabError) as excinfo:
        rt.blender_config_for(small_spec(renderer="blender", blender_config={"samples": 4}))
    assert excinfo.value.code == ErrorCode.SCHEMA_INVALID
    config = rt.blender_config_for(small_spec(renderer="blender"))
    assert isinstance(config, BlenderBackendConfig)
    assert config.samples == BlenderBackendConfig().samples


# --------------------------------------------------------------------------------------
# 4. the mother asset resolves into a renderable target (evidence path of the 1024 run)
# --------------------------------------------------------------------------------------
def test_resolve_target_accepts_a_mother(mother, target):
    assert target.n_faces == int(mother.n_faces)
    assert target.surface_tag.shape[0] == int(mother.n_faces)
    assert np.array_equal(np.asarray(target.surface_tag, dtype=np.int32),
                          np.asarray(mother.face_surface_tag, dtype=np.int32))
    assert target.fragment_id == mother.mother_id
    assert target.meta["surface_tag_source"] == "MOTHER_FACE_SURFACE_TAG"


def test_observation_metadata_round_trips_through_json(target, profile):
    obs, _ = rt.route_ideal_visible(target, profile, small_spec(),
                                    make_rng(7, "dispatch_test", "json"))
    payload = json.dumps(rt.observation_meta(obs), default=str)
    assert "SOFTWARE_RASTERIZER" in payload
    assert json.loads(payload)["meta"]["renderer"] == BACKEND_SOFTWARE
