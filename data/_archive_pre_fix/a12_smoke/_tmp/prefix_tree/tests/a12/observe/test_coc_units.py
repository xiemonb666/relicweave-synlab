"""CoC unit semantics (``mask_semantics = coc_units_v2``) -- regression tests.

These tests pin the *units* of the defocus mark-out, because the delivered mask chain
(``uncertain_mask`` -> ``deployment_mask`` -> ``visible``) is only meaningful if the circle of
confusion is a length in millimetres converted by the delivered sampling density
``D = f_px / focal_length_mm``.  The superseded expression fed a *pixel* focal length into the
millimetre formula and dropped ``D``; it inflated the CoC by ``D * f_number`` (measured 74.105
on the delivered L0 views) and eroded the deployable mask to 0.26-7.2 % of the object.

Nothing here is relaxed: the thresholds are the shipped ones and the assertions are exact
relations, not tolerances fitted to the current output.
"""

from __future__ import annotations

import numpy as np
import pytest

from synlab.cameras.profiles import profile_by_id, thin_lens_dof
from synlab.observe.render import (
    MASK_SEMANTICS,
    MASK_SEMANTICS_PIXEL_UNITS_V1,
    LightSpec,
    RenderSpec,
    Scene,
    circle_of_confusion_px,
    render_view,
    resolve_declared_optics,
)
from synlab.schemas.runtime import ViewFrame

WIDTH, HEIGHT = 256, 192
FOCUS_MM = 220.0


def frame_with_declared_optics(*, profile_id: str = "CAM_MID_V3",
                               focal_length_mm: float | None = 5.2,
                               f_number: float | None = 2.2,
                               width: int = WIDTH, height: int = HEIGHT) -> ViewFrame:
    """A camera 220 mm in front of a target at world z = 0 (camera z = 220 mm)."""
    f_px = 5.2 / 7.6 * width
    K = np.array([[f_px, 0.0, (width - 1) / 2.0],
                  [0.0, f_px, (height - 1) / 2.0],
                  [0.0, 0.0, 1.0]], dtype=np.float64)
    # the rig convention of the shipped fixtures: R = diag(-1,-1,1), camera at world z = -220
    T_WC = np.diag(np.array([-1.0, -1.0, 1.0, 1.0]))
    T_WC[2, 3] = -FOCUS_MM
    meta: dict = {}
    if focal_length_mm is not None:
        meta["focal_length_mm"] = float(focal_length_mm)
    if f_number is not None:
        meta["f_number"] = float(f_number)
    return ViewFrame(view_id="coc_units", K=K, T_WC=T_WC, image_size=(width, height),
                     profile_id=profile_id, tier="MID", u_position_mm=0.0,
                     working_distance_mm=FOCUS_MM, focus_setting="mid",
                     source_kind="SENSOR_SIM", camera_model="PINHOLE", dist=None, meta=meta)


def scene_with_face() -> tuple[Scene, LightSpec]:
    """One 120 x 90 mm plate at world z = 0, i.e. exactly at the working distance."""
    xs = np.array([-60.0, -60.0, 60.0, 60.0])
    ys = np.array([-45.0, 45.0, 45.0, -45.0])
    vertices = np.stack([xs, ys, np.zeros(4)], axis=1)
    faces = np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int32)   # normal -z: toward the camera
    from synlab.observe.render import MaterialSpec

    scene = Scene(name="coc_units_fixture", vertices=vertices, faces=faces,
                  surface_tag=np.zeros(2, dtype=np.int16),
                  material=MaterialSpec(albedo=np.full((2, 3), 0.5, dtype=np.float32),
                                        roughness=np.full(2, 0.5, dtype=np.float32)))
    light = LightSpec(direction=np.array([0.0, 0.0, 1.0]),
                      color=np.array([1.0, 1.0, 1.0]), ambient=np.array([0.2, 0.2, 0.2]))
    return scene, light


# --------------------------------------------------------------------------------------
# 1. arithmetic: the mm form converted by D
# --------------------------------------------------------------------------------------
def test_v2_equals_the_thin_lens_mm_form_times_the_sampling_density():
    f_mm, f_number, z_f, sensor_width_mm, width_px = 5.2, 2.2, 220.0, 7.6, 256
    D = width_px / sensor_width_mm
    f_px = f_mm * D
    z = np.array([180.0, 200.0, 220.0, 240.0, 300.0])
    got = circle_of_confusion_px(z, z_f, f_number, f_px, sampling_px_per_mm=D)
    expected = D * (f_mm ** 2) / (f_number * (z - f_mm)) * np.abs(z - z_f) / z_f
    assert np.allclose(got, expected, rtol=1e-12, atol=1e-15)


def test_declared_optics_reproduce_the_profile_depth_of_field():
    """Inverting the corrected formula on the declared DOF limit must give the declared CoC."""
    profile = profile_by_id("CAM_MID_V3")
    f_mm = float(profile.meta["focal_length_mm"])
    f_number = float(profile.f_number)
    z_f = float(profile.working_distance_mm)
    sensor_width_mm = float(profile.meta["sensor_width_mm"])
    pitch_native = sensor_width_mm / int(profile.image_size[0])
    coc_px = float(profile.meta["coC_px"])
    D = WIDTH / sensor_width_mm
    near, _far = (float(v) for v in profile.depth_of_field_mm)
    c_mm = float(circle_of_confusion_px(np.array([near]), z_f, f_number, f_mm * D,
                                        sampling_px_per_mm=D)[0]) / D
    assert c_mm == pytest.approx(coc_px * pitch_native, rel=1e-9)
    # the advertised interval itself is the classical thin-lens one
    assert thin_lens_dof(z_f, f_mm, f_number, coc_px, pitch_native)[0] == pytest.approx(near)


def test_legacy_expression_is_inflated_by_the_sampling_density_and_aperture():
    """The superseded branch is D*N*(z-f)/z larger -- that is the defect being locked out."""
    f_mm, f_number, z_f, sensor_width_mm, width_px = 5.2, 2.2, 220.0, 7.6, 256
    D = width_px / sensor_width_mm
    f_px = f_mm * D
    z = np.array([190.0, 210.0, 240.0, 260.0])
    legacy = circle_of_confusion_px(z, z_f, 1.0, f_px)          # pre-v2: pixel units, f/1
    fixed = circle_of_confusion_px(z, z_f, f_number, f_px, sampling_px_per_mm=D)
    expected = 1.0 * D * f_number * (z - f_mm) / z
    assert np.allclose(legacy / fixed, expected, rtol=1e-12)
    assert np.all(legacy / fixed > 70.0)                         # measured 72.0 - 72.3


# --------------------------------------------------------------------------------------
# 2. optics resolution and labelling
# --------------------------------------------------------------------------------------
def test_resolve_declared_optics_reads_frame_meta_then_the_profile_registry():
    declared = resolve_declared_optics(frame_with_declared_optics())
    assert declared["declared"] is True
    assert declared["focal_length_mm"] == pytest.approx(5.2)
    assert declared["f_number"] == pytest.approx(2.2)
    assert declared["sampling_px_per_mm"] == pytest.approx(256 / 7.6)
    assert declared["source"] == {"focal_length_mm": "frame_meta", "f_number": "frame_meta"}

    from_registry = resolve_declared_optics(
        frame_with_declared_optics(focal_length_mm=None, f_number=None))
    assert from_registry["declared"] is True
    assert from_registry["focal_length_mm"] == pytest.approx(5.2)
    assert from_registry["f_number"] == pytest.approx(2.2)
    assert from_registry["source"]["f_number"] == "camera_profile"

    override = resolve_declared_optics(frame_with_declared_optics(f_number=None),
                                       RenderSpec(f_number=8.0))
    assert override["f_number"] == pytest.approx(8.0)
    assert override["source"]["f_number"] == "render_spec"


def test_render_view_labels_the_semantics_it_used():
    scene, light = scene_with_face()
    declared = render_view(scene, frame_with_declared_optics(), light=light,
                           spec=RenderSpec(supersample=1))
    assert declared.meta["mask_semantics"] == MASK_SEMANTICS
    assert declared.meta["coc_optics"]["declared"] is True
    assert declared.meta["coc_optics"]["sampling_px_per_mm"] == pytest.approx(256 / 7.6)
    assert declared.meta["coc_optics"]["f_number"] == pytest.approx(2.2)

    undeclared = render_view(scene, frame_with_declared_optics(profile_id="pinhole_fx200",
                                                               focal_length_mm=None,
                                                               f_number=None),
                             light=light, spec=RenderSpec(supersample=1))
    assert undeclared.meta["mask_semantics"] == MASK_SEMANTICS_PIXEL_UNITS_V1
    assert undeclared.meta["coc_optics"]["declared"] is False
    assert undeclared.meta["coc_optics"]["sampling_px_per_mm"] is None


def test_an_in_focus_object_keeps_every_pixel_certain_under_the_declared_optics():
    """A flat target at the working distance is in focus: no object pixel may be dropped."""
    scene, light = scene_with_face()
    render = render_view(scene, frame_with_declared_optics(), light=light,
                         spec=RenderSpec(supersample=1, coc_px_threshold=0.75 * 2.2))
    obj = render.id_map >= 0
    assert int(np.count_nonzero(obj)) > 2000
    assert int(np.count_nonzero(render.uncertain_mask & obj)) == 0
    assert float(render.meta["coc_p95_px"]) == pytest.approx(0.0, abs=1e-9)
