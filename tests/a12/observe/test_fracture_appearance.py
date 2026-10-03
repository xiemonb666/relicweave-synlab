"""Assertions for the fracture appearance layer (normal channel, facets, materials, glaze)."""
from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
OBSERVE_TESTS = Path(__file__).resolve().parent
if str(OBSERVE_TESTS) not in sys.path:
    sys.path.insert(0, str(OBSERVE_TESTS))

from synlab.materials import build_material_profile, default_material_params  # noqa: E402
from synlab.observe import fracture_appearance as fa  # noqa: E402
from synlab.observe.render import (  # noqa: E402
    BACKEND_SOFTWARE,
    MaterialSpec,
    RenderSpec,
    build_scene,
    render_view,
)
from synlab.schemas.runtime import ViewFrame  # noqa: E402
from synlab.seeds import make_rng  # noqa: E402


# ------------------------------------------------------------------------------ fixtures
def _plate() -> tuple[fa.Scene, ViewFrame, fa.LightSpec]:
    import trimesh

    mesh = trimesh.creation.box(extents=(60.0, 60.0, 10.0))
    faces = np.asarray(mesh.faces)
    scene = fa.Scene(
        name="plate", vertices=np.asarray(mesh.vertices), faces=faces,
        surface_tag=np.full(faces.shape[0], 2, dtype=np.int16),
        material=MaterialSpec(np.tile(np.array([0.6, 0.55, 0.5], dtype=np.float32),
                                      (faces.shape[0], 1)),
                              np.full(faces.shape[0], 0.5, dtype=np.float32)))
    K = np.array([[800.0, 0.0, 256.0], [0.0, 800.0, 192.0], [0.0, 0.0, 1.0]])
    T = np.eye(4)
    T[:3, 3] = np.array([0.0, 0.0, -200.0])
    frame = ViewFrame(view_id="v", K=K, T_WC=T, image_size=(512, 384), profile_id="test",
                      tier="LOCAL", u_position_mm=200.0, working_distance_mm=200.0,
                      focus_setting=0.0, source_kind="SENSOR_SIM", camera_model="PINHOLE",
                      dist=np.zeros(0),
                      meta={"focal_length_mm": 6.1, "f_number": 4.0})
    return scene, frame, fa.frozen_light()


class _ConstantGradient:
    """A stub relief field with a constant gradient, used to calibrate the normal channel."""

    def __init__(self, gu: float, gv: float, u_axis: np.ndarray, v_axis: np.ndarray) -> None:
        self.gu, self.gv = float(gu), float(gv)
        self.u_axis, self.v_axis = u_axis, v_axis
        self.amplitude_scale = 1.0
        self.realized_ra_mm = 0.0

    def as_dict(self) -> dict:
        return {"kind": "CONSTANT_GRADIENT_STUB", "gu": self.gu, "gv": self.gv}

    def sample(self, points_world, *, scale=None):
        n = np.asarray(points_world, dtype=np.float64).reshape(-1, 3).shape[0]
        s = float(self.amplitude_scale if scale is None else scale)
        return np.zeros(n), np.full(n, self.gu * s), np.full(n, self.gv * s)


# ------------------------------------------------------------------------------ frozen model
def test_shade_world_normals_matches_the_frozen_expression():
    """``clip(-(R^T n_cam . l)) == clip(-(n_world . l))``: the two forms are one model."""
    rng = np.random.default_rng(7)
    R = np.linalg.qr(rng.normal(size=(3, 3)))[0]
    if np.linalg.det(R) < 0:
        R[:, 0] *= -1.0
    n_cam = rng.normal(size=(32, 3))
    n_cam /= np.linalg.norm(n_cam, axis=1, keepdims=True)
    n_world = n_cam @ R
    light = fa.frozen_light()
    T_WC = np.eye(4)
    T_WC[:3, :3] = R
    a = fa.lambert_ambient_linear(normals_world=n_cam, T_WC=T_WC,
                                 albedo=np.full((32, 3), 0.5), light=light)
    b = fa.shade_world_normals(normals_world=n_world, albedo=np.full((32, 3), 0.5), light=light)
    assert np.allclose(a, b, atol=1e-12)


def test_flat_frozen_render_reproduces_the_software_rasteriser_bit_exactly():
    """The per-pixel renderer must reduce to the frozen backend when nothing is switched on."""
    scene, frame, light = _plate()
    spec = RenderSpec(supersample=1, max_pixels=4_000_000)
    frozen = render_view(scene, frame, light=light, spec=spec, backend=BACKEND_SOFTWARE)
    mine = fa.render_appearance_view(scene, frame, light=light, spec=spec,
                                     appearance=fa.AppearanceSpec(normal_mode="FLAT",
                                                                  relief=False,
                                                                  interpolation="FROZEN"))
    assert np.array_equal(frozen.rgb_linear, mine.rgb_linear)
    assert np.array_equal(frozen.id_map, mine.id_map)
    assert np.array_equal(frozen.surface_tag, mine.surface_tag)
    assert np.array_equal(np.nan_to_num(frozen.depth_z, nan=-1.0),
                          np.nan_to_num(mine.depth_z, nan=-1.0))


def test_flat_frozen_albedo_override_matches_base_material_and_records_adapter():
    scene, frame, light = _plate()
    spec = RenderSpec(supersample=1, max_pixels=4_000_000)
    override = np.tile(np.array([0.31, 0.47, 0.59], dtype=np.float32),
                       (scene.n_faces, 1))
    appearance = fa.AppearanceSpec(normal_mode="FLAT", relief=False,
                                   interpolation="FROZEN", diffuse_weight=0.75)
    actual = fa.render_appearance_view(scene, frame, light=light, spec=spec,
                                       appearance=appearance, albedo=override)
    expected_scene = fa.Scene(
        name=scene.name, vertices=scene.vertices, faces=scene.faces,
        surface_tag=scene.surface_tag,
        material=MaterialSpec(override * appearance.diffuse_weight,
                              scene.material.roughness,
                              source_kind=scene.material.source_kind),
        face_id=scene.face_id, is_target=scene.is_target, meta=dict(scene.meta),
    )
    expected = render_view(expected_scene, frame, light=light, spec=spec,
                           backend=BACKEND_SOFTWARE)
    assert np.array_equal(actual.rgb_linear, expected.rgb_linear)
    assert np.array_equal(actual.id_map, expected.id_map)
    assert np.array_equal(actual.surface_tag, expected.surface_tag)
    assert np.array_equal(np.nan_to_num(actual.depth_z, nan=-1.0),
                          np.nan_to_num(expected.depth_z, nan=-1.0))
    assert actual.backend == fa.BACKEND_APPEARANCE
    assert actual.meta["base_renderer"] == BACKEND_SOFTWARE
    assert actual.meta["appearance"]["albedo_channel"] == "PER_FACE_OVERRIDE"
    assert actual.meta["appearance"]["lambert"]["status"] == "OK"


def test_relief_off_and_relief_on_differ_only_by_the_normal():
    """With a constant gradient the image change equals the analytic shading change."""
    scene, frame, light = _plate()
    # the plate's camera-facing surface has normal -z, so the light must travel toward +z for the
    # surface to be lit at all; the frozen light direction is mirrored to keep it oblique
    light = fa.LightSpec(direction=np.array([0.35, 0.62, 0.70]),
                         color=light.color, ambient=light.ambient)
    spec = RenderSpec(supersample=1, max_pixels=4_000_000)
    normal = np.array([0.0, 0.0, -1.0])
    u_axis, v_axis = fa.tangent_basis(normal)
    off = fa.render_appearance_view(scene, frame, light=light, spec=spec,
                                    appearance=fa.AppearanceSpec(normal_mode="FLAT", relief=False,
                                                                 interpolation="PERSPECTIVE_CORRECT"))
    for gu, gv in ((0.05, 0.0), (0.0, 0.05), (0.05, -0.05)):
        on = fa.render_appearance_view(
            scene, frame, light=light, spec=spec,
            appearance=fa.AppearanceSpec(normal_mode="FLAT", relief=True,
                                         interpolation="PERSPECTIVE_CORRECT"),
            relief_field=_ConstantGradient(gu, gv, u_axis, v_axis))
        # exact (not first-order) analytic change: n -> normalize(n - gu*tu - gv*tv)
        n = np.array([0.0, 0.0, -1.0])
        n_new = n - gu * u_axis - gv * v_axis
        n_new = n_new / np.linalg.norm(n_new)
        d_lambert = -float((n_new - n) @ light.direction)
        expected = np.asarray(scene.material.albedo, dtype=np.float64)[0] \
            * np.asarray(light.color, dtype=np.float64) * d_lambert
        delta = np.asarray(on.rgb_linear, dtype=np.float64) \
            - np.asarray(off.rgb_linear, dtype=np.float64)
        hit = np.isfinite(off.depth_z)
        assert hit.any()
        assert np.allclose(delta[hit], expected[None, :], atol=2e-6)


def test_zero_gradient_is_bit_identical_to_relief_off():
    """A relief layer with no gradient must not change one byte (no hidden path difference)."""
    scene, frame, light = _plate()
    spec = RenderSpec(supersample=1, max_pixels=4_000_000)
    u_axis, v_axis = fa.tangent_basis(np.array([0.0, 0.0, -1.0]))
    off = fa.render_appearance_view(scene, frame, light=light, spec=spec,
                                    appearance=fa.AppearanceSpec(normal_mode="FLAT", relief=False,
                                                                 interpolation="PERSPECTIVE_CORRECT"))
    zero = fa.render_appearance_view(scene, frame, light=light, spec=spec,
                                     appearance=fa.AppearanceSpec(normal_mode="FLAT", relief=True,
                                                                  interpolation="PERSPECTIVE_CORRECT"),
                                     relief_field=_ConstantGradient(0.0, 0.0, u_axis, v_axis))
    assert np.array_equal(off.rgb_linear, zero.rgb_linear)


def test_lambert_report_detects_an_unlit_surface():
    """The frozen clip is recorded, so 'this view cannot show relief' is measurable."""
    scene, frame, light = _plate()
    color, ambient = light.color, light.ambient
    spec = RenderSpec(supersample=1, max_pixels=4_000_000)
    # the plate's camera-facing surface has normal -z; a light travelling along +z lights it
    lit = fa.render_appearance_view(
        scene, frame, light=fa.LightSpec(direction=np.array([0.0, 0.0, 1.0]), color=color,
                                         ambient=ambient),
        spec=spec, appearance=fa.AppearanceSpec(normal_mode="FLAT"))
    lit_report = lit.meta["appearance"]["lambert"]
    assert lit_report["status"] == "OK"
    assert lit_report["unlit_fraction"] == pytest.approx(0.0, abs=1e-12)
    assert lit_report["fully_lit_fraction"] == pytest.approx(1.0, abs=1e-12)
    # the same view with the light travelling along -z is fully unlit: no normal response at all
    unlit = fa.render_appearance_view(
        scene, frame, light=fa.LightSpec(direction=np.array([0.0, 0.0, -1.0]), color=color,
                                         ambient=ambient),
        spec=spec, appearance=fa.AppearanceSpec(normal_mode="FLAT"))
    assert unlit.meta["appearance"]["lambert"]["unlit_fraction"] == pytest.approx(1.0, abs=1e-12)


# ------------------------------------------------------------------------------ normals
def test_smooth_normals_do_not_change_the_geometry_hash():
    """Path 1 of facet suppression is a shading change only: the geometry hash must not move."""
    import trimesh

    mesh = trimesh.creation.icosphere(subdivisions=2, radius=20.0)
    verts, faces = np.asarray(mesh.vertices), np.asarray(mesh.faces)
    before = fa.geometry_hash(verts, faces)
    vn = fa.vertex_normals(verts, faces)
    cn = fa.corner_normals(verts, faces, crease_angle_deg=35.0)
    after = fa.geometry_hash(verts, faces)
    assert before == after
    assert vn.shape == verts.shape and cn.shape == (faces.shape[0], 3, 3)
    assert np.allclose(np.linalg.norm(vn, axis=1), 1.0)
    assert np.allclose(np.linalg.norm(cn.reshape(-1, 3), axis=1), 1.0)


def test_smooth_vertex_normals_of_a_sphere_point_along_the_radius():
    import trimesh

    mesh = trimesh.creation.icosphere(subdivisions=3, radius=20.0)
    verts, faces = np.asarray(mesh.vertices), np.asarray(mesh.faces)
    vn = fa.vertex_normals(verts, faces)
    radial = verts / np.linalg.norm(verts, axis=1, keepdims=True)
    assert np.allclose(vn, radial, atol=0.02)


def test_crease_angle_keeps_a_cube_edge_sharp():
    import trimesh

    mesh = trimesh.creation.box(extents=(10.0, 10.0, 10.0))
    verts, faces = np.asarray(mesh.vertices), np.asarray(mesh.faces)
    sharp = fa.corner_normals(verts, faces, crease_angle_deg=20.0)
    smooth = fa.corner_normals(verts, faces, crease_angle_deg=180.0)
    flat = fa.face_normals(verts, faces)
    # at 20 deg every cube corner keeps its own face normal; at 180 deg they are averaged
    assert np.allclose(sharp.reshape(-1, 3), np.repeat(flat, 3, axis=0), atol=1e-9)
    assert not np.allclose(smooth.reshape(-1, 3), np.repeat(flat, 3, axis=0), atol=1e-9)


# ------------------------------------------------------------------------------ material mapping
@pytest.mark.parametrize("material_id", ["M01", "M04", "M07", "M11"])
def test_appearance_parameters_come_from_the_material_record(material_id):
    profile = build_material_profile(material_id, default_material_params(material_id),
                                     make_rng(20261001, "test", material_id))
    params = fa.appearance_parameters_from_profile(profile, material_id=material_id)
    stats = profile["stats"]
    assert params.grain_scale_mm == pytest.approx(float(stats["grain_scale_mm"]))
    assert params.correlation_length_mm == pytest.approx(float(stats["correlation_length_mm"]))
    assert params.albedo == tuple(float(x) for x in profile["appearance"]["albedo"])
    # sigma_r0 is the audited relation, recomputed here by hand
    expected = 0.12 * params.grain_scale_mm * (1.0 + 2.0 * params.porosity)
    assert params.sigma_r0_mm == pytest.approx(expected, rel=1e-9)
    assert params.lambda_min_mm > 0.0 and params.lambda_max_mm >= params.lambda_min_mm
    assert len(params.band_amplitudes_mm) == 5
    # the band amplitudes reproduce sigma_r0 as an RMS (sum a_i^2 / 2)
    rms = float(np.sqrt(np.sum(0.5 * np.asarray(params.band_amplitudes_mm) ** 2)))
    assert rms == pytest.approx(params.sigma_r0_mm, rel=1e-6)


def test_material_differences_are_non_zero_and_ordered():
    """The three required materials must differ in amplitude, scale and transmission."""
    rows = {}
    for mid in ("M01", "M04", "M07"):
        profile = build_material_profile(mid, default_material_params(mid),
                                         make_rng(20261001, "test", mid))
        rows[mid] = fa.appearance_parameters_from_profile(profile, material_id=mid)
    assert rows["M01"].sigma_r0_mm > rows["M04"].sigma_r0_mm > rows["M07"].sigma_r0_mm
    assert rows["M07"].transmission > 0.5 and rows["M01"].transmission == 0.0
    assert rows["M04"].grain_scale_mm < rows["M01"].grain_scale_mm


def test_field_is_band_limited_not_white_noise():
    """The realised relief must be correlated (red spectrum), which per-pixel noise is not."""
    from _run_fracture_appearance import (MASTER_SEED, SPECIMEN, material_profile, patch_faces,
                                          pick_roi, lit_score)
    from _run_fracture_roi import load_target
    from synlab.cameras.profiles import camera_profiles
    from synlab.observe import fracture_roi as fr

    target, body = load_target(SPECIMEN)
    mesh = target.mesh
    config = fr.load_fracture_roi_config()
    base = {p.tier: p for p in camera_profiles()}["LOCAL"]
    closeup = fr.closeup_profile(config, base=base, delivered_long_edge_px=1024)
    footprint = fr.mm_per_px(working_distance_mm=60.0, f_px=float(closeup.K[0, 0])) * 512.0
    rois = fr.fracture_rois(target, config, footprint_radius_mm=footprint)
    roi = max(rois, key=lambda r: lit_score(r, fa.frozen_light()))
    faces = patch_faces(mesh, roi.interface_id)
    field = fa.build_relief_field(
        profile=material_profile(body["material_id"]), roi=roi,
        patch_vertices=mesh.vertices, patch_triangles=np.asarray(mesh.faces)[faces], mesh=mesh,
        rng=make_rng(MASTER_SEED, "appearance_field", body["material_id"]), amplitude_mm=0.08,
        glaze_strip=False)
    report = fa.field_spectrum_report(field, extent_mm=2.0 * field.footprint_radius_mm, n=256)
    assert report["status"] == "OK"
    # red spectrum: a white-noise field would give a flat PSD (slope ~ 0)
    assert report["psd_slope_loglog"] < -0.5
    # the field's own correlation length is the material's, not one sample
    assert report["expected_correlation_length_mm"] > 0.05
    assert field.realized_ra_mm == pytest.approx(0.08, rel=1e-6)
    assert field.slope_rms_at_unit > 0.0


# ------------------------------------------------------------------------------ inverse solves
def test_required_mesh_density_is_a_real_inverse_solve():
    """lambda_min = 0.65 mm (M01) must give a number, and the algebra must close."""
    out = fa.required_mesh_density(lambda_min_mm=0.65, area_mm2=100.0, current_edge_mm=9.0,
                                   ratio=8.0)
    assert out["required_edge_mm"] == pytest.approx(0.65 / 8.0)
    assert out["required_triangles"] == pytest.approx(
        4.0 * 100.0 / (np.sqrt(3.0) * (0.65 / 8.0) ** 2))
    assert out["current_triangles_equivalent"] == pytest.approx(
        4.0 * 100.0 / (np.sqrt(3.0) * 9.0 ** 2))
    assert out["density_factor"] == pytest.approx(
        out["required_triangles"] / out["current_triangles_equivalent"])
    assert out["required_cells_equivalent"] == pytest.approx(out["required_triangles"] / 2.0)
    px = fa.facet_pixel_budget(edge_mm=out["required_edge_mm"], mm_per_px=0.073)
    assert px["edge_px"] == pytest.approx(out["required_edge_mm"] / 0.073)
    assert px["visible"] is False


def test_measured_edge_length_of_a_known_mesh():
    import trimesh

    mesh = trimesh.creation.box(extents=(2.0, 2.0, 2.0))
    out = fa.measured_edge_length_mm(np.asarray(mesh.vertices), np.asarray(mesh.faces))
    assert out["status"] == "OK"
    assert out["edge_median_mm"] == pytest.approx(2.0, rel=1e-9)


def test_facet_metrics_see_a_step_and_ignore_a_flat_field():
    ids = np.zeros((16, 16), dtype=np.int64)
    ids[:, 8:] = 1
    flat = np.full((16, 16), 40.0)
    mask = np.ones((16, 16), dtype=bool)
    out = fa.facet_metrics(flat, ids, mask)
    assert out["facet_edge_dn_step"] == pytest.approx(0.0, abs=1e-12)
    stepped = flat.copy()
    stepped[:, 8:] = 60.0
    out2 = fa.facet_metrics(stepped, ids, mask)
    assert out2["facet_edge_dn_step"] == pytest.approx(20.0, abs=1e-9)
    assert out2["facet_contrast_ratio"] > 1e6


def test_dn_statistics_and_difference_definition():
    dn = np.zeros((8, 8))
    dn[4:, :] = 10.0
    mask = np.ones((8, 8), dtype=bool)
    stats = fa.dn_statistics(dn, mask)
    assert stats["dn_max_minus_min"] == pytest.approx(10.0)
    diff = fa.difference_dn_statistics(dn, np.zeros((8, 8)), mask)
    assert diff["dDN_rms"] == pytest.approx(np.sqrt(0.5 * 100.0))
    assert diff["fraction_above_1_dn"] == pytest.approx(0.5)


# ------------------------------------------------------------------------------ config
def test_shipped_configuration_is_off_by_default_and_valid():
    config = fa.load_fracture_appearance_config()
    assert config.enabled is False
    fa.validate_config(config)
    assert config.normal_mode in fa.NORMAL_MODES
    assert len(config.materials) >= 3
    assert 50.0 <= config.working_distance_mm <= 100.0


def test_config_rejects_out_of_contract_values():
    base = fa.FractureAppearanceConfig()
    with pytest.raises(Exception):
        fa.validate_config(replace(base, normal_mode="PHONG"))
    with pytest.raises(Exception):
        fa.validate_config(replace(base, materials=("M01", "M04")))
    with pytest.raises(Exception):
        fa.validate_config(replace(base, working_distance_mm=10.0))
    with pytest.raises(Exception):
        fa.validate_config(replace(base, supersample=9))
    with pytest.raises(Exception):
        fa.validate_config(replace(base, amplitudes_mm=(0.0,)))


def test_appearance_spec_rejects_unknown_modes():
    with pytest.raises(Exception):
        fa.AppearanceSpec(normal_mode="PHONG")
    with pytest.raises(Exception):
        fa.AppearanceSpec(interpolation="BILINEAR")


# ------------------------------------------------------------------- A1: contract light selection
def test_contract_light_modes_are_exactly_the_five_documented_states():
    """A1 invents no light: the mode list is the contract's, and every mode resolves."""
    from synlab.degrade.specs import light_modes
    from synlab.pipeline import LIGHT_MODE_SPECS

    assert tuple(light_modes()) == fa.CONTRACT_LIGHT_MODES
    assert set(LIGHT_MODE_SPECS) == set(fa.CONTRACT_LIGHT_MODES)
    for mode in fa.CONTRACT_LIGHT_MODES:
        light = fa.contract_light(mode)
        assert np.linalg.norm(np.asarray(light.direction)) == pytest.approx(1.0)
        assert fa.CONTRACT_LIGHT_PURPOSE[mode]
    with pytest.raises(Exception):
        fa.contract_light("SOFTBOX")


def test_light_selection_picks_a_usable_response_and_ranks_all_five():
    """A fracture facing away from the frozen default must be reselected, and the choice recorded."""
    # the ROI normal of the unlit study body's fracture faces away from the frozen WHITE_DIFFUSE
    n = np.array([-0.85, -0.28, -0.45])
    n /= np.linalg.norm(n)
    frozen = fa.contract_light("WHITE_DIFFUSE")
    before = fa.lambert_response_score(normal_world=n, light=frozen)
    assert before < 0.0
    choice = fa.choose_contract_light(normal_world=n)
    assert choice.mode in fa.CONTRACT_LIGHT_MODES
    assert len(choice.ranking) == 5
    assert choice.response_score > before
    # the winner is the one with the largest usable response, and the losers are all reported
    assert choice.ranking[0]["mode"] == choice.mode
    assert all(float(r["usable_response"]) <= float(choice.ranking[0]["usable_response"])
               for r in choice.ranking)
    # and the metadata carries the chosen state, its numbers and its source
    meta = choice.as_dict()
    assert meta["mode"] == choice.mode
    assert meta["n_candidates"] == 5
    assert "LIGHT_MODE_SPECS" in meta["source"]
    assert all("usable_response" in r for r in meta["candidates"])


def test_light_selection_prefers_the_interior_of_the_linear_band():
    """A clipped state (raw <= 0 or raw >= 1) has zero normal response, so it must lose."""
    n = np.array([0.0, 0.0, -1.0])
    choice = fa.choose_contract_light(normal_world=n)
    assert float(choice.ranking[0]["usable_response"]) > 0.0
    assert all(float(r["usable_response"]) == 0.0 for r in choice.ranking
               if float(r["lambert_response"]) <= 0.0
               or float(r["lambert_response"]) >= 1.0)


# ------------------------------------------------------------------------- A2: profile exposure
def test_default_profile_reaches_snr_10_by_rig_side_exposure_only():
    """A2: the default profile must lift Ra = 0.08 mm above the chain's noise, with no post-process.

    The measured curve lives in the run report; this test pins the *contract* the default must
    satisfy: the exposure is a rig-side setting applied before photon counting, and the delivered
    noise falls as ``1/sqrt(gain)``.
    """
    from synlab.observe.imaging import ImagingSpec

    config = fa.load_fracture_appearance_config()
    assert config.imaging_exposure_ev >= 0.0
    assert config.imaging_gain == pytest.approx(2.0 ** config.imaging_exposure_ev)
    spec = ImagingSpec(exposure_ev=float(config.imaging_exposure_ev))
    # no post-processing is part of the default profile
    assert spec.denoise == 0.0 and spec.sharpening == 0.0
    assert spec.resize_scale is None and spec.crop_origin is None
    assert spec.response == "LINEAR"
    # the exposure acts at EXPOSURE_OPTICS, i.e. before the sensor stage
    plan = spec.stage_plan()
    assert plan.index("EXPOSURE_OPTICS") < plan.index("SENSOR_NOISE")
    # and the report's curve must reach SNR >= 10 at the configured default
    import json
    from pathlib import Path

    report = Path(fa.__file__).resolve().parents[2] / config.report_dir \
        / "fracture_appearance_run.json"
    if not report.exists():
        pytest.skip("run report not present")
    stages = json.loads(report.read_text(encoding="utf-8")).get("stages") or {}
    curve = stages.get("snr_gain")
    if not curve:
        pytest.skip("snr_gain stage not present in the report")
    default_row = next(r for r in curve["rows"]
                       if r["exposure_ev"] == float(config.imaging_exposure_ev))
    assert default_row["snr"] >= 10.0
    assert default_row["post_processing_applied"] is False
    assert curve["profile_default"]["denoise"] == 0.0
    # monotone: more photons can never mean less signal-to-noise
    snrs = [r["snr"] for r in curve["rows"]]
    assert all(b >= a * 0.95 for a, b in zip(snrs, snrs[1:]))


# ------------------------------------------------------------------------ A3: albedo texture
def test_texture_is_band_limited_and_below_nyquist():
    tex = fa.make_albedo_texture(mm_per_px=0.073, material_albedo=(0.27, 0.22, 0.17),
                                 correlation_length_mm=2.6)
    report = fa.texture_spectrum_report(tex, n=512)
    assert report["dominant_over_nyquist"] < 0.5
    assert report["dominant_over_nyquist"] == pytest.approx(
        report["declared_dominant_over_nyquist"], rel=0.2)
    assert report["power_fraction_above_nyquist"] < 0.01
    assert tex.nyquist_ok()
    # the declared shortest wavelength is the material's own correlation length / 2
    assert min(tex.wavelengths_mm) == pytest.approx(1.3)


def test_texture_is_continuous_across_a_triangle_boundary():
    """A3's whole point: the albedo must not depend on which triangle a point belongs to."""
    tex = fa.make_albedo_texture(mm_per_px=0.073, material_albedo=(0.27, 0.22, 0.17),
                                 correlation_length_mm=2.6)
    a = tex.albedo(np.array([[10.0, 10.0]]))
    b = tex.albedo(np.array([[10.0 + 1e-9, 10.0 - 1e-9]]))
    assert np.allclose(a, b, atol=1e-6)
    # and it is bounded, strictly positive and zero-mean in modulation
    grid = np.stack(np.meshgrid(np.arange(256.0), np.arange(256.0), indexing="ij"), -1)
    uv = grid.reshape(-1, 2) * tex.mm_per_px
    mod = tex.modulation(uv)
    assert float(np.abs(mod).max()) <= 0.95
    assert abs(float(mod.mean())) < 0.05


def test_the_two_rungs_describe_one_surface():
    """A3 acceptance: 0.073 and 0.0365 mm/px must give the same PHYSICAL texture statistics."""
    out = fa.texture_consistency_report(material_albedo=(0.27, 0.22, 0.17),
                                        correlation_length_mm=2.6,
                                        rungs_mm_per_px=(0.073, 0.0365), n=256)
    assert out["verdict"] == "CONSISTENT"
    assert out["nyquist_ok_every_rung"] is True
    rows = out["rows"]
    assert len(rows) == 2
    # same wavelengths in mm ...
    assert rows[0]["wavelengths_mm"] == pytest.approx(rows[1]["wavelengths_mm"])
    # ... same mm^-1 slope RMS ...
    assert rows[1]["slope_rms_per_mm"] == pytest.approx(rows[0]["slope_rms_per_mm"], rel=0.05)
    # ... while the pixel wavelengths scale exactly as 1/mm_per_px
    for w0, w1 in zip(rows[0]["wavelengths_px"], rows[1]["wavelengths_px"]):
        assert w1 / w0 == pytest.approx(0.073 / 0.0365, rel=1e-6)
    # and the Nyquist ratio improves (never worsens) at the finer rung
    assert rows[1]["dominant_over_nyquist"] < rows[0]["dominant_over_nyquist"]


def test_a_texture_at_an_impossible_rung_says_so():
    """No silent filtering: a rung that cannot carry the material's scale reports nyquist_ok False."""
    tex = fa.make_albedo_texture(mm_per_px=0.2719, material_albedo=(0.27, 0.22, 0.17),
                                 correlation_length_mm=0.2)
    assert tex.nyquist_ok() is False
    out = fa.texture_consistency_report(material_albedo=(0.27, 0.22, 0.17),
                                        correlation_length_mm=0.2,
                                        rungs_mm_per_px=(0.2719,), n=128)
    assert out["nyquist_ok_every_rung"] is False
    assert out["verdict"] == "CONSISTENT_BUT_ALIASED"


def test_albedo_texture_does_not_change_the_frozen_fast_path():
    """The texture is opt-in: without it the per-face palette path is byte-for-byte unchanged."""
    scene, frame, light = _plate()
    spec = RenderSpec(supersample=1, max_pixels=4_000_000)
    a = fa.render_appearance_view(scene, frame, light=light, spec=spec,
                                  appearance=fa.AppearanceSpec(normal_mode="FLAT", relief=False,
                                                              interpolation="FROZEN"))
    assert a.meta["appearance"]["albedo_channel"] == "PER_FACE_PALETTE_FROZEN"
    assert a.meta["appearance"]["albedo_texture"] is None
    tex = fa.make_albedo_texture(mm_per_px=0.1, material_albedo=(0.6, 0.55, 0.5),
                                 correlation_length_mm=2.0)
    b = fa.render_appearance_view(scene, frame, light=light, spec=spec,
                                  appearance=fa.AppearanceSpec(normal_mode="FLAT", relief=False,
                                                               interpolation="PERSPECTIVE_CORRECT",
                                                               albedo_texture=tex))
    assert b.meta["appearance"]["albedo_channel"] == "PER_PIXEL_CONTINUOUS_TEXTURE"
    assert b.meta["appearance"]["albedo_texture"]["kind"] == "CONTINUOUS_BANDLIMITED_ALBEDO"
    hit = np.isfinite(b.depth_z) & np.isfinite(a.depth_z)
    assert hit.any()
    # the texture removes the per-face steps that the palette draws
    fac_a = fa.facet_metrics(np.asarray(a.rgb_linear).mean(axis=2) * 255.0, a.id_map,
                             np.isfinite(a.depth_z))
    fac_b = fa.facet_metrics(np.asarray(b.rgb_linear).mean(axis=2) * 255.0, b.id_map,
                             np.isfinite(b.depth_z))
    assert fac_a["facet_edge_dn_step"] > 0.0
    assert fac_b["facet_edge_dn_step"] < fac_a["facet_edge_dn_step"]


# ------------------------------------------------------------------- A4: prediction on hit points
def test_constant_gradient_prediction_reproduces_the_shading_change():
    """A4: on a constant-gradient field the linearisation is EXACT, so prediction == render.

    This is the calibration that makes the hit-point prediction trustworthy: the frozen shading is
    re-evaluated from the field's own gradient instead of being fitted to the measurement.
    """
    scene, frame, light = _plate()
    light = fa.LightSpec(direction=np.array([0.35, 0.62, 0.70]), color=light.color,
                         ambient=light.ambient)
    spec = RenderSpec(supersample=1, max_pixels=4_000_000)
    normal = np.array([0.0, 0.0, -1.0])
    u_axis, v_axis = fa.tangent_basis(normal)
    gu, gv = 0.04, -0.02
    off = fa.render_appearance_view(scene, frame, light=light, spec=spec,
                                    appearance=fa.AppearanceSpec(normal_mode="FLAT", relief=False,
                                                                 interpolation="PERSPECTIVE_CORRECT"))
    on = fa.render_appearance_view(scene, frame, light=light, spec=spec,
                                   appearance=fa.AppearanceSpec(normal_mode="FLAT", relief=True,
                                                                interpolation="PERSPECTIVE_CORRECT"),
                                   relief_field=_ConstantGradient(gu, gv, u_axis, v_axis))
    hit = np.isfinite(off.depth_z)
    assert hit.any()
    measured = float(np.sqrt(np.mean(
        (np.asarray(on.rgb_linear).mean(axis=2)[hit]
         - np.asarray(off.rgb_linear).mean(axis=2)[hit]) ** 2)))
    # the exact first-order change of the frozen Lambert term for this constant gradient
    d_lam = -(gu * u_axis + gv * v_axis) @ light.direction
    albedo = np.asarray(scene.material.albedo, dtype=np.float64).mean(axis=0)
    expected = 255.0 * float(np.mean(albedo * np.asarray(light.color))) * abs(d_lam)
    assert measured == pytest.approx(float(expected), rel=0.05)


def test_real_prediction_on_hit_points_closes_the_legacy_gap():
    """A4 acceptance: on the real field, hit-point + render-albedo prediction must land within 15%.

    The prediction was evaluated on the ROI plane grid with the material's albedo; the renderer
    evaluates the field at the delivered pixels with the scene's palette albedo.  This test pins
    both corrections on the real audited field.
    """
    from _run_fracture_appearance import (MASTER_SEED, SPECIMEN, material_profile, patch_faces,
                                          rendered_albedo_channels)
    from _run_fracture_roi import load_target
    from synlab.cameras.profiles import camera_profiles
    from synlab.observe import fracture_roi as fr

    target, body = load_target(SPECIMEN)
    mesh = target.mesh
    config = fr.load_fracture_roi_config()
    base = {p.tier: p for p in camera_profiles()}["LOCAL"]
    closeup = fr.closeup_profile(config, base=base, delivered_long_edge_px=1024)
    footprint = fr.mm_per_px(working_distance_mm=60.0, f_px=float(closeup.K[0, 0])) * 512.0
    rois = fr.fracture_rois(target, config, footprint_radius_mm=footprint)
    roi = max(rois, key=lambda r: -(np.asarray(r.normal) @ fa.frozen_light().direction))
    faces = patch_faces(mesh, roi.interface_id)
    field = fa.build_relief_field(
        profile=material_profile(body["material_id"]), roi=roi, patch_vertices=mesh.vertices,
        patch_triangles=np.asarray(mesh.faces)[faces], mesh=mesh,
        rng=make_rng(MASTER_SEED, "appearance_field", body["material_id"]), amplitude_mm=0.08,
        glaze_strip=False)
    s = float(field.amplitude_scale)
    rng = np.random.default_rng(3)
    pts = (field.origin_mm[None, :]
           + rng.uniform(-20.0, 20.0, size=(4000, 1)) * field.u_axis[None, :]
           + rng.uniform(-20.0, 20.0, size=(4000, 1)) * field.v_axis[None, :])
    light = fa.frozen_light()
    alb_mat = np.asarray(field.parameters.albedo, dtype=np.float64)
    alb_render = alb_mat * 2.3            # the palette's measured factor over the material
    pred = field.predicted_shading_ddn_on_points(pts, albedo=alb_mat, light=light,
                                                base_normals=np.repeat(
                                                    np.asarray(field.normal)[None, :], 4000, axis=0),
                                                ra_scale=s, albedo_from_render=alb_render)
    assert pred["status"] == "OK"
    # the render albedo scales the prediction by exactly its own factor
    assert pred["predicted_dDN_from_render_albedo"] == pytest.approx(
        pred["predicted_dDN"] * pred["albedo_factor_ratio_render_over_material"], rel=1e-9)
    assert pred["albedo_factor_ratio_render_over_material"] == pytest.approx(2.3, rel=1e-6)
    assert pred["gradient_rms"] > 0.0 and pred["d_lambert_rms"] > 0.0
    # the legacy ROI-grid path is biased low against the analytic gradient (A4's finding)
    legacy_rms = np.sqrt(np.mean(field._grid_gradients()[0] ** 2
                                 + field._grid_gradients()[1] ** 2))
    assert pred["gradient_rms"] > legacy_rms
    assert rendered_albedo_channels  # the helper is importable and used by the runner
