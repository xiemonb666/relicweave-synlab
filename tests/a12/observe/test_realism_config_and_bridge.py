"""Realism tests: the capture-style config, its bridge and the tags it produces.

Everything asserted here is either (a) a property of the *registered* degradation axes, (b) a
property of a real render/product produced in the test, or (c) a property of a committed
realistic-library asset when that library exists on this host.  Nothing is asserted from a
claim that is not checkable on the spot.
"""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import trimesh

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from synlab.cameras.api import camera_profiles  # noqa: E402
from synlab.config import compile_spec, load_generation_spec  # noqa: E402
from synlab.degrade.registry import get_operator  # noqa: E402
from synlab.degrade.sources import KIND_IMAGE, SourceBundle  # noqa: E402
from synlab.errors import ErrorCode, SynLabError  # noqa: E402
from synlab.observe.imaging import ImagingSpec, apply_imaging_chain  # noqa: E402
from synlab.observe.quality import estimate_quality  # noqa: E402
from synlab.observe.realism import (  # noqa: E402
    APPLIED_AXES,
    AXIS_LEVELS,
    DELIVERY_ENCODE,
    DELIVERY_RESPONSE,
    IDEAL_REFERENCE_GAIN,
    LEVEL_IDENTITY,
    LEVEL_REALISTIC,
    MASK_POLICIES,
    MASK_POLICY_FOREGROUND,
    MASK_POLICY_PIPELINE_COC,
    degradation_report,
    imaging_spec_for,
    is_realistic_capture,
    level_parameters,
    normalise_levels,
    observe_spec_from_config,
    realism_tags,
    realised_levels,
    resolve_distortion_policy,
)
from synlab.observe.render import BACKEND_BLENDER, BACKEND_SOFTWARE  # noqa: E402
from synlab.observe.routes import (  # noqa: E402
    ObsSpec,
    render_views,
    resolve_render_backend,
    resolve_target,
)
from synlab.seeds import make_rng  # noqa: E402

CONFIG = ROOT / "configs" / "a12" / "realistic.yaml"
REALISTIC_ROOT = ROOT / "data" / "a12_realistic"
IDENTITY_LEVELS = {axis: LEVEL_IDENTITY for axis in APPLIED_AXES}
REALISTIC_LEVELS = {axis: LEVEL_REALISTIC for axis in APPLIED_AXES}


def _blender_available() -> bool:
    from synlab.observe.blender import find_blender_binary

    return find_blender_binary() is not None


needs_blender = pytest.mark.skipif(not _blender_available(),
                                   reason="no Blender binary on this host")


def _provenanced_box(extents: tuple[float, float, float]) -> trimesh.Trimesh:
    """A box carrying the face provenance a real fragment has (origin_kind/interface_id).

    ``observe.routes.resolve_target`` refuses an unlabeled target (``OBS_TARGET_PROVENANCE_
    MISSING``) unless ``allow_unlabeled=True`` is passed; the fixtures therefore attach the
    channels instead of opting out, so the tests exercise the strict path.
    """
    from synlab.schemas.runtime import ORIGIN_INTERFACE, ORIGIN_MOTHER_SURFACE
    from synlab.storage.mesh_io import with_face_attrs

    mesh = trimesh.creation.box(extents=extents)
    n = len(mesh.faces)
    origin = np.full(n, ORIGIN_MOTHER_SURFACE, dtype=np.uint8)
    origin[: max(n // 2, 1)] = ORIGIN_INTERFACE
    return with_face_attrs(mesh, origin_kind=origin,
                           interface_id=np.arange(n, dtype=np.int32))


# --------------------------------------------------------------------------------------
# 1. the config itself
# --------------------------------------------------------------------------------------
def test_realistic_config_compiles_and_declares_the_capture_route():
    spec = load_generation_spec(CONFIG)
    compiled = compile_spec(spec)
    assert compiled.errors == [], compiled.errors
    assert spec.observation.routes[0].value == "photo_mvs"
    assert spec.observation_route.value == "photo_mvs"
    assert spec.observation.renderer == "blender"
    assert spec.observation.input_profile.value == "PHONE_RGB"
    assert spec.input_profile.value == "PHONE_RGB"
    # a new library: the frozen one is never written by this configuration
    assert spec.storage.root == "data/a12_realistic"
    assert spec.dataset.target_mothers == 120  # same plan as next_experiment.yaml


def test_realistic_config_keeps_the_frozen_dataset_and_fracture_blocks():
    """Same-scene comparison with the frozen batch needs identical generation inputs."""
    realistic = load_generation_spec(CONFIG)
    frozen = load_generation_spec(ROOT / "configs" / "a12" / "next_experiment.yaml")
    assert realistic.master_seed == frozen.master_seed
    assert realistic.dataset.model_dump() == frozen.dataset.model_dump()
    assert realistic.fracture.model_dump() == frozen.fracture.model_dump()
    assert realistic.physical.model_dump() == frozen.physical.model_dump()


# --------------------------------------------------------------------------------------
# 2. level ladders == the registered axes, level 0 == true identity
# --------------------------------------------------------------------------------------
def test_level_ladders_are_the_registered_axis_ladders():
    for axis in APPLIED_AXES:
        operator = get_operator(axis)
        for level in range(5):
            declared = level_parameters(axis, level)
            if axis == "I03":
                registered = operator.VARIANT_LEVELS["camera_noise_profile"][f"L{level}"]
            else:
                registered = operator.level_parameters(level)
            for name, value in declared.items():
                assert float(registered[name]) == pytest.approx(float(value)), (
                    axis, level, name)


def test_level_zero_is_a_true_identity_imaging_chain():
    identity = imaging_spec_for(IDENTITY_LEVELS)
    assert identity.is_identity() is True
    assert identity.encode == "PNG"
    assert identity.response == "LINEAR"
    assert identity.defocus_sigma_px == 0.0
    assert identity.read_noise_sigma == 0.0
    realistic = imaging_spec_for(REALISTIC_LEVELS)
    assert realistic.is_identity() is False
    assert realistic.defocus_sigma_px == pytest.approx(0.5)
    assert realistic.effective_gain == pytest.approx(16000.0)
    assert realistic.read_noise_sigma == pytest.approx(0.002)
    assert realistic.exposure_ev == pytest.approx(0.5)
    assert realistic.encode == DELIVERY_ENCODE == "JPEG"
    assert realistic.jpeg_quality == 90
    assert realistic.response == DELIVERY_RESPONSE == "SRGB"


def test_registered_operators_are_identity_at_level_zero_and_realized_at_level_one():
    """The ladder claim is checked on the registered operators, not on the bridge."""
    rng = np.random.default_rng(7)
    rgb = (rng.random((24, 32, 3)) * 255).astype(np.uint8)
    frame = {"view_id": "v0", "rgb": rgb, "rgb_linear": rgb.astype(np.float32) / 255.0,
             "encoding": "LINEAR",
             "K": np.array([[60.0, 0.0, 15.5], [0.0, 60.0, 11.5], [0.0, 0.0, 1.0]]),
             "T_WC": np.eye(4), "valid": np.ones((24, 32), dtype=bool)}
    source = SourceBundle(source_kind=KIND_IMAGE, payload={"frames": [frame]})
    context = {"lineage_id": "lin", "fragment_id": "frag", "master_seed": 11}
    for axis in ("I01", "I03", "I04", "I05", "I10"):
        operator = get_operator(axis)
        basis = operator.sample_basis(context, np.random.default_rng(3))
        level0 = operator.apply(source, 0, basis)
        assert level0.content_hash() == source.content_hash(), axis
        assert np.array_equal(np.asarray(level0.get("frames")[0]["rgb"]),
                             np.asarray(source.get("frames")[0]["rgb"])), axis
        level1 = operator.apply(source, 1, basis)
        if axis == "I03":
            # shot noise is drawn: the payload must differ in content
            assert not np.array_equal(np.asarray(level1.get("frames")[0]["rgb_linear"]),
                                      np.asarray(frame["rgb_linear"])), axis
        else:
            assert level1.content_hash() != source.content_hash(), axis


def test_realistic_levels_are_recorded_in_the_declared_parameters():
    report = degradation_report(REALISTIC_LEVELS)
    assert report["levels"] == {axis: LEVEL_REALISTIC for axis in APPLIED_AXES}
    assert report["declared_parameters"]["I01"] == {"psf_sigma_px": 0.5}
    assert report["declared_parameters"]["I03"] == {"photon_gain": 16000.0,
                                                    "read_sigma": 0.002}
    assert report["delivery_encode"] == "JPEG"
    assert report["delivery_response"] == "SRGB"
    assert report["imaging_identity"] is False
    assert degradation_report(IDENTITY_LEVELS)["imaging_identity"] is True


def test_photon_gain_override_is_reported_not_hidden():
    report = degradation_report(IDENTITY_LEVELS, photon_gain=IDEAL_REFERENCE_GAIN)
    assert report["photon_gain"] == pytest.approx(IDEAL_REFERENCE_GAIN)
    assert report["photon_gain_overridden"] is True
    spec = imaging_spec_for(IDENTITY_LEVELS, photon_gain=IDEAL_REFERENCE_GAIN)
    # documented frozen-code edge: ``is_identity()`` does not test effective_gain, which is
    # exactly why the override is reported separately instead of trusting that flag
    assert spec.is_identity() is True
    assert spec.effective_gain == pytest.approx(IDEAL_REFERENCE_GAIN)


# --------------------------------------------------------------------------------------
# 3. distortion handling is explicit
# --------------------------------------------------------------------------------------
def test_distorted_profile_on_blender_is_never_silently_accepted():
    profile = camera_profiles()[1]
    assert float(np.abs(np.asarray(profile.dist)).max()) > 0.0
    with pytest.raises(SynLabError) as excinfo:
        resolve_distortion_policy(profile, BACKEND_BLENDER, policy=None)
    assert excinfo.value.code == ErrorCode.EXPERIMENT_PROTOCOL_VIOLATION
    refused = resolve_distortion_policy(profile, BACKEND_BLENDER, policy="error")
    assert refused["decision"] == "refused"
    undistort = resolve_distortion_policy(profile, BACKEND_BLENDER, policy="undistort")
    assert undistort["decision"] == "undistorted_pinhole"
    ignored = resolve_distortion_policy(profile, BACKEND_BLENDER, policy="ignore")
    assert ignored["decision"] == "rendered_as_pinhole_coefficients_recorded"
    raster = resolve_distortion_policy(profile, BACKEND_SOFTWARE, policy=None)
    assert raster["decision"] == "applied_by_backend"


def test_distortion_policy_error_really_refuses_a_blender_render(tmp_path):
    """The refusal path must be reachable (not just declared)."""
    if not _blender_available():
        pytest.skip("no Blender binary on this host")
    box = _provenanced_box((30.0, 24.0, 16.0))
    target = resolve_target(box, fragment_id="distortion_fixture")
    profile = camera_profiles()[1]
    spec = _small_spec(renderer="blender", levels=REALISTIC_LEVELS)
    spec.distortion_policy = "error"
    with pytest.raises(SynLabError) as excinfo:
        render_views(target, profile, spec, make_rng(1, "lin", "sensor"), backend="blender")
    assert excinfo.value.code in (ErrorCode.ENV_CAPABILITY_MISSING,
                                  ErrorCode.SCHEMA_INVALID)
    assert "distortion" in str(excinfo.value).lower()


# --------------------------------------------------------------------------------------
# 4. the renderer really is selected (and a real render proves it)
# --------------------------------------------------------------------------------------
def _small_spec(*, renderer: str, levels: dict[str, int],
                route_params: dict | None = None) -> ObsSpec:
    from synlab.observe.realism import observe_spec_from_config

    spec = load_generation_spec(CONFIG)
    plan = observe_spec_from_config(
        spec, store_root=ROOT / "data" / "a12_realistic", lineage_id="pytest_realism",
        route="ideal_visible", renderer=renderer, levels=levels,
        distortion_policy=("undistort" if renderer == "blender" else None),
        view_count=1)
    obs = plan.obs_spec
    obs.delivered_size = (128, 96)
    obs.max_render_pixels = 128 * 96
    obs.render_spec.supersample = 1
    return obs


def test_blender_request_is_resolved_to_the_blender_backend():
    if not _blender_available():
        pytest.skip("no Blender binary on this host")
    assert resolve_render_backend("blender") == BACKEND_BLENDER
    assert resolve_render_backend("auto") == BACKEND_SOFTWARE


def test_missing_blender_binary_refuses_instead_of_falling_back(monkeypatch):
    from synlab.observe import blender as bl
    from synlab.observe import routes as routes_module

    monkeypatch.setattr(bl, "_env_blender_bin", lambda: None)
    monkeypatch.setattr(bl, "_user_env_blender_bin", lambda: None)
    monkeypatch.setattr(bl, "_portable_candidates", lambda: [])
    monkeypatch.setattr(bl.shutil, "which", lambda name: None)
    monkeypatch.setattr(bl, "_SELFTEST_CACHE", {})
    with pytest.raises(SynLabError) as excinfo:
        routes_module.resolve_render_backend("blender")
    assert excinfo.value.code == ErrorCode.ENV_CAPABILITY_MISSING


@needs_blender
def test_observation_reports_blender_as_the_backend_that_produced_it():
    """A real Cycles render of a real fragment-shaped target, through ``render_views``."""
    box = _provenanced_box((40.0, 30.0, 18.0))
    target = resolve_target(box, fragment_id="blender_fixture")
    profile = camera_profiles()[1]
    spec = _small_spec(renderer="blender", levels=REALISTIC_LEVELS)
    bundles = render_views(target, profile, spec, make_rng(11, "lin", "sensor"),
                           backend="blender")
    assert len(bundles) == 1
    bundle = bundles[0]
    assert bundle.backend == BACKEND_BLENDER
    meta = bundle.render.meta
    assert meta["engine"] == "CYCLES"
    assert meta["samples_used"] == int(meta["samples_requested"]) >= 1
    assert meta["blender_version"]
    # the distorted profile was handled by the declared policy, and the delivered frame says so
    assert bundle.distortion["distortion_policy"] == "undistort"
    assert bundle.distortion["distortion_undistorted"] is True
    assert float(np.abs(np.asarray(bundle.distortion["distortion_coefficients"])).max()) > 0
    from synlab.observe.routes import _frame_for_delivered

    delivered = _frame_for_delivered(bundle, spec)
    assert delivered.dist is None
    assert delivered.camera_model == "PINHOLE"


# --------------------------------------------------------------------------------------
# 5. the delivered products carry the declared noise / blur / compression
# --------------------------------------------------------------------------------------
@needs_blender
def test_realistic_products_carry_noise_blur_and_jpeg():
    box = _provenanced_box((40.0, 30.0, 18.0))
    target = resolve_target(box, fragment_id="product_fixture")
    profile = camera_profiles()[1]
    identity = _small_spec(renderer="blender", levels=IDENTITY_LEVELS)
    bundle_id = render_views(target, profile, identity, make_rng(5, "lin", "sensor"),
                             backend="blender")[0]
    realistic = _small_spec(renderer="blender", levels=REALISTIC_LEVELS)
    bundle_re = render_views(target, profile, realistic, make_rng(5, "lin", "sensor"),
                             backend="blender")[0]
    # labels: only the realistic delivery is an ISP/JPEG proxy
    assert "JPEG_PROXY" in bundle_re.imaging.labels
    assert "ISP_PROXY" in bundle_re.imaging.labels
    assert "JPEG_PROXY" not in bundle_id.imaging.labels
    # measured sensor noise against the chain's own ground truth (scene_linear is kept)
    mask = np.asarray(bundle_re.deploy_mask, dtype=bool)
    assert mask.any(), "the deployed mask must not be empty"
    def sigma(bundle: object) -> float:
        scene = np.asarray(bundle.imaging.scene_linear, dtype=np.float64)
        linear = np.asarray(bundle.imaging.linear, dtype=np.float64)
        return float(np.std((linear - scene)[mask]))
    assert sigma(bundle_re) > 1e-3
    assert sigma(bundle_id) > 1e-3          # documented: gain 1.0 still shot-noise limits
    stages = {s["op"]: s for s in bundle_re.imaging.stages}
    # the depth-dependent defocus variant records the near/far PSF pair; the flat variant a
    # single sigma.  Either way the declared level-1 value (0.5 px) must appear.
    if "sigma_px" in stages["psf_applied"]:
        assert stages["psf_applied"]["sigma_px"] == pytest.approx(0.5)
    else:
        assert stages["psf_applied"]["sigma_near_px"] == pytest.approx(0.5)
        assert stages["psf_applied"]["sigma_far_px"] == pytest.approx(0.8)
    assert stages["poisson_read_noise"]["effective_gain"] == pytest.approx(16000.0)
    assert stages["quantise_encode"]["encode"] == "JPEG"
    assert stages["quantise_encode"]["jpeg_quality"] == 90
    assert stages["camera_response"]["response"].startswith("SRGB")
    # the realised ladder is read back from the observation's own stage list
    view = SimpleNamespace(meta={"imaging_stages": bundle_re.imaging.stages})
    obs_like = SimpleNamespace(views=[view], meta={}, backend_report={})
    assert realised_levels(obs_like)["identity"] is False


def test_identity_chain_still_shot_noise_limits_the_render():
    """Measured property of the frozen chain: level 0 is not photon-free at gain 1.0."""
    rng = np.random.default_rng(2)
    scene = (rng.random((48, 64, 3)) * 0.4).astype(np.float32)
    K = np.array([[50.0, 0.0, 31.5], [0.0, 50.0, 23.5], [0.0, 0.0, 1.0]])
    identity = apply_imaging_chain(scene, K=K, dist=None, uncertain_mask=None, depth_z=None,
                                   focus_distance_mm=200.0,
                                   rng=np.random.default_rng(4), spec=ImagingSpec())
    assert identity.labels == ["LINEAR_SENSOR_MODEL"]
    residual = np.asarray(identity.linear, dtype=np.float64) - scene.astype(np.float64)
    assert float(np.std(residual)) > 0.05        # ~Poisson(sqrt(x)) at x ~ 0.2


# --------------------------------------------------------------------------------------
# 6. the quality estimator is complete for an empty cloud (photo_mvs STOP_SFM)
# --------------------------------------------------------------------------------------
def test_quality_block_exposes_every_key_for_an_empty_cloud():
    view = SimpleNamespace(rgb=np.zeros((8, 8, 3), dtype=np.uint8),
                           depth_z=np.full((8, 8), np.nan, dtype=np.float32),
                           roi=None)
    obs = SimpleNamespace(views=[view], points=np.zeros((0, 3), dtype=np.float32),
                          point_valid=np.zeros(0, dtype=bool), route="photo_mvs",
                          scale_valid=False, fused_mesh=None)
    quality = estimate_quality(obs)
    for key in ("nn_spacing_median", "nn_spacing_p95", "point_count",
                "view_coverage_mean", "hole_ratio_max"):
        assert key in quality, key
    assert quality["nn_spacing_p95"]["valid"] is False
    from synlab.observe.features import _quality_features

    features = _quality_features(obs)
    assert features["values"].shape == features["valid"].shape
    assert not features["valid"].all()


# --------------------------------------------------------------------------------------
# 7. the bridge's plan and the masks it declares
# --------------------------------------------------------------------------------------
def test_observe_spec_from_config_matches_the_config_and_declares_its_policy():
    spec = load_generation_spec(CONFIG)
    plan = observe_spec_from_config(spec, store_root=ROOT / "data" / "a12_realistic",
                                    lineage_id="LIN0002_pytest")
    assert plan.route == "photo_mvs"
    assert plan.renderer == "blender"
    assert plan.obs_spec.renderer == "blender"
    assert plan.obs_spec.distortion_policy == "undistort"
    assert plan.distortion["decision"] == "undistorted_pinhole"
    assert plan.obs_spec.delivered_size == (1024, 768)
    assert plan.obs_spec.view_count == 12
    assert plan.obs_spec.imaging.is_identity() is False
    assert plan.workdir.endswith("realistic") or "realistic" in plan.workdir
    assert plan.extra["mask_policy"] in MASK_POLICIES
    assert plan.as_dict()["pipeline_ignored_config_keys"]
    # the declared mask policy changes the CoC mark-out that the routes apply
    with_coc = observe_spec_from_config(
        spec, store_root=ROOT / "data" / "a12_realistic", lineage_id="L",
        mask_policy=MASK_POLICY_PIPELINE_COC)
    assert with_coc.obs_spec.render_spec.coc_px_threshold == pytest.approx(0.75 * 2.2)
    silhouette = observe_spec_from_config(
        spec, store_root=ROOT / "data" / "a12_realistic", lineage_id="L",
        mask_policy=MASK_POLICY_FOREGROUND)
    assert silhouette.obs_spec.render_spec.coc_px_threshold > 1.0e5
    with pytest.raises(SynLabError):
        observe_spec_from_config(spec, store_root=ROOT / "data" / "a12_realistic",
                                 lineage_id="L", mask_policy="whatever")


def test_realism_tags_are_derived_from_measured_fields_not_claims():
    view = SimpleNamespace(meta={"imaging_labels": ["LINEAR_SENSOR_MODEL", "ISP_PROXY",
                                                    "JPEG_PROXY"],
                                 "render_backend": "BLENDER_CYCLES",
                                 "imaging_stages": [
                                     {"op": "exposure_gain_before_photons", "exposure_ev": 0.5},
                                     {"op": "psf_applied", "sigma_px": 0.5},
                                     {"op": "poisson_read_noise", "effective_gain": 16000.0,
                                      "read_noise_sigma": 0.002},
                                     {"op": "white_balance", "gains": [1.025, 1.0, 0.975]},
                                     {"op": "camera_response", "response": "SRGB(BT709_OETF)"},
                                     {"op": "quantise_encode", "encode": "JPEG",
                                      "jpeg_quality": 90},
                                 ]})
    obs = SimpleNamespace(views=[view], route="photo_mvs", scale_valid=False,
                          meta={"renderer": "BLENDER_CYCLES", "renderer_requested": "blender",
                                "renderer_class": "ADAPTER", "distortion_policy": "undistort",
                                "obs_semantics": "physical_side_v2",
                                "data_semantics": {"mask_semantics": "coc_units_v2"}},
                          backend_report={"route": "photo_mvs"})
    tags = realism_tags(obs)
    assert tags["route"] == "photo_mvs"
    assert tags["renderer"] == "BLENDER_CYCLES"
    assert tags["realised_levels"]["I01"] == LEVEL_REALISTIC
    assert tags["realised_levels"]["I03"] == LEVEL_REALISTIC
    assert tags["realised_levels"]["I04"] == LEVEL_REALISTIC
    assert tags["realised_levels"]["I05"] == LEVEL_REALISTIC
    assert tags["realised_levels"]["I10"] == LEVEL_REALISTIC
    ok, reasons = is_realistic_capture(obs)
    assert ok, reasons
    # and it must fail closed when one measured property is missing
    view.meta["render_backend"] = "SOFTWARE_RASTERIZER"
    obs.meta["renderer"] = "SOFTWARE_RASTERIZER"
    ok, reasons = is_realistic_capture(obs)
    assert not ok and reasons


# --------------------------------------------------------------------------------------
# 8. the committed library (only when this host has produced it)
# --------------------------------------------------------------------------------------
def _committed_observations(root: Path) -> list:
    from synlab.roles import ROLE_OBS_RESULT
    from synlab.storage.store import AssetStore

    if not (root / "metadata.sqlite").exists():
        return []
    store = AssetStore(root)
    return list(store.list_assets(role=ROLE_OBS_RESULT, limit=200))


def test_committed_realistic_library_is_capture_style_when_present():
    records = _committed_observations(REALISTIC_ROOT)
    if not records:
        pytest.skip("data/a12_realistic has no committed observation on this host")
    from synlab.observe.api import load_observation
    from synlab.storage.store import AssetStore

    store = AssetStore(REALISTIC_ROOT)
    checked = 0
    for record in records:
        obs = load_observation(store, record.asset_id)
        tags = realism_tags(obs)
        assert tags["route"] == "photo_mvs"
        assert tags["renderer"] == "BLENDER_CYCLES"
        assert tags["renderer_requested"] == "blender"
        assert "JPEG_PROXY" in tags["imaging_labels"]
        assert tags["realised_levels"]["I10"] == LEVEL_REALISTIC
        assert tags["realised_levels"]["I01"] == LEVEL_REALISTIC
        assert tags["data_semantics"] is not None
        assert tags["obs_semantics"] == "physical_side_v2"
        ok, reasons = is_realistic_capture(obs)
        assert ok, reasons
        checked += 1
        if checked >= 2:
            break
    assert checked >= 1


def test_run_record_carries_the_realism_tag_when_the_library_exists():
    from synlab.storage.store import AssetStore

    if not (REALISTIC_ROOT / "metadata.sqlite").exists():
        pytest.skip("data/a12_realistic does not exist on this host")
    store = AssetStore(REALISTIC_ROOT)
    # ``AssetStore.get_run`` returns the raw row: the meta block is JSON text in ``meta_json``
    runs = [json.loads(store.get_run(run_id).get("meta_json") or "{}")
            for run_id in _run_ids(store)]
    tagged = [run for run in runs
              if str((run.get("realism") or {}).get("realism", "")) == "realistic_capture_style"]
    if not tagged:
        pytest.skip("no realistic run record on this host")
    plan = tagged[0]["realism"]["realism_plan"]
    assert plan["route"] == "photo_mvs"
    assert plan["renderer_requested"] == "blender"
    assert plan["degradation"]["levels"]["I10"] == LEVEL_REALISTIC
    assert plan["distortion"]["policy"] == "undistort"


def _run_ids(store: object) -> list[str]:
    with store.connect() as conn:  # type: ignore[attr-defined]
        return [str(row["run_id"]) for row in
                conn.execute("SELECT run_id FROM runs ORDER BY created_at DESC LIMIT 20")]


def test_report_records_the_same_scene_proof_when_it_exists():
    """The A/B report must carry the geometry hashes that prove both legs share a scene."""
    report_path = ROOT / "data" / "a12" / "reports" / "realistic_pilot.json"
    if not report_path.exists():
        pytest.skip("no realistic pilot report on this host")
    document = json.loads(report_path.read_text(encoding="utf-8"))
    legs = document.get("legs") or {}
    if "realistic" not in legs or "control" not in legs:
        pytest.skip("both legs have not run on this host")
    comparison = document.get("comparison") or {}
    assert comparison, "two legs are present but no comparison block was written"
    for lineage_id, row in comparison.items():
        assert row["same_scene_geometry_hashes_equal"] is True, lineage_id
        realistic_hashes = (legs["realistic"]["lineages"][lineage_id]
                            ["fragment_geometry_hashes"])
        control_hashes = (legs["control"]["lineages"][lineage_id]["fragment_geometry_hashes"])
        assert realistic_hashes and realistic_hashes == control_hashes
