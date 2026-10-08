"""Camera profile catalogue: GLOBAL / MID / LOCAL tiers (plan 13.4, 30.3).

Physical model
--------------
The capture bench is a phone/camera fixture mounted on a linear slide that moves the
lens **along the optical axis** (``u_position_mm``).  Moving ``u`` therefore changes

* ``working_distance_mm``  = Z distance from the camera centre to the object centre,
* the effective focal length (the lens is re-focused and the nominal focal length of
  the selected lens/focus group changes with the position lock),
* the depth of field (classical thin-lens formula at the working distance),
* the pixel scale ``mm_per_pixel = Z / f_x``.

It **never** changes ``image_size`` or applies a digital crop/zoom; a virtual U move is
realised by re-rendering from a new camera extrinsic along the optical axis.  Digital
resolution loss at a *fixed* working distance is a separate axis (I09) and lives in
:mod:`synlab.observe.imaging`.

Calibration status
------------------
None of these tiers has been measured on a real bench: there are no real captures and
no target images in this repository.  Every profile is therefore marked
``UNCALIBRATED`` (nominal operating tiers) or ``STRESS_UNCALIBRATED`` (tiers whose
reach/depth-of-field depends on unverified mechanical assumptions).  ``calibrated`` is
``False`` on all of them and the realised intrinsics must be replaced by target-based
calibration before any phone-RGB deployment claim (release gate ``CALIBRATED_PHONE``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from ..errors import ErrorCode, SynLabError
from ..schemas.runtime import CameraProfile
from ..roles import SOURCE_CALIBRATED, SOURCE_SENSOR_SIM

#: Profile catalogue revision.  Every consumer (simulation, camera page, episode cost,
#: diagnosis report) must cite this same revision (plan 13.4).
CAMERA_PROFILE_REVISION = 3

#: CoC used for the thin-lens depth-of-field report, in pixels.
DEFAULT_COC_PX = 2.0

#: OpenCV distortion order (k1, k2, p1, p2, k3).
DIST_ORDER = ("k1", "k2", "p1", "p2", "k3")


@dataclass(frozen=True)
class _TierSpec:
    """Frozen nominal specification of one physical slide lock position."""

    tier: str
    profile_id: str
    label: str
    sensor_width_mm: float
    u_position_mm: float
    working_distance_mm: float
    focal_length_mm: float
    f_number: float
    image_size: tuple[int, int]
    focus_setting: str
    dist: tuple[float, ...]
    u_travel_mm: tuple[float, float]
    u_step_mm: float
    action_cost_seconds: float
    calibration_status: str
    calibration_refs: tuple[str, ...]
    alignment_error_px_rms: float
    notes: str


#: 12 MP-class phone sensor (4000x3000), 1/1.7"-class active width.  The three tiers are
#: *nominal* slide positions of the manual rig; the travel limits are the mechanical
#: clearance of the fixture, not a lens specification (plan 13.4 forbids promising a
#: fixed travel or minimum resolution without lens data).
_TIER_SPECS: tuple[_TierSpec, ...] = (
    _TierSpec(
        tier="GLOBAL",
        profile_id="CAM_GLOBAL_V3",
        label="global context / whole-object framing",
        sensor_width_mm=7.6,
        u_position_mm=-100.0,
        working_distance_mm=380.0,
        focal_length_mm=4.4,
        f_number=2.0,
        image_size=(4000, 3000),
        focus_setting="SLIDE_NEAR_LOCK_A",
        dist=(-0.041, 0.011, 0.0008, -0.0006, -0.0025),
        u_travel_mm=(-100.0, -40.0),
        u_step_mm=10.0,
        action_cost_seconds=21.0,
        calibration_status="UNCALIBRATED",
        calibration_refs=("nominal:sensor_width_7.6mm", "nominal:f_4.4mm_f2.0"),
        alignment_error_px_rms=0.0,
        notes=(
            "Nominal wide framing tier.  f_x/f_y and the ROI are derived from the "
            "declared sensor width and the slide read-out; no target image exists in "
            "this repository, so the profile is UNCALIBRATED."
        ),
    ),
    _TierSpec(
        tier="MID",
        profile_id="CAM_MID_V3",
        label="mid framing / fracture neighbourhood",
        sensor_width_mm=7.6,
        u_position_mm=0.0,
        working_distance_mm=220.0,
        focal_length_mm=5.2,
        f_number=2.2,
        image_size=(4000, 3000),
        focus_setting="SLIDE_MID_LOCK_B",
        dist=(-0.033, 0.008, 0.0006, -0.0005, -0.0018),
        u_travel_mm=(-30.0, 30.0),
        u_step_mm=5.0,
        action_cost_seconds=17.0,
        calibration_status="UNCALIBRATED",
        calibration_refs=("nominal:sensor_width_7.6mm", "nominal:f_5.2mm_f2.2"),
        alignment_error_px_rms=0.0,
        notes="Nominal default working position of the slide.",
    ),
    _TierSpec(
        tier="LOCAL",
        profile_id="CAM_LOCAL_V3",
        label="local fracture detail / closest lockable position",
        sensor_width_mm=7.6,
        u_position_mm=70.0,
        working_distance_mm=140.0,
        focal_length_mm=6.1,
        f_number=2.4,
        image_size=(4000, 3000),
        focus_setting="SLIDE_FAR_LOCK_C_MACRO",
        dist=(-0.052, 0.019, 0.0012, -0.0009, -0.0041),
        u_travel_mm=(40.0, 70.0),
        u_step_mm=5.0,
        action_cost_seconds=26.0,
        calibration_status="STRESS_UNCALIBRATED",
        calibration_refs=("nominal:sensor_width_7.6mm", "nominal:f_6.1mm_f2.4"),
        alignment_error_px_rms=0.0,
        notes=(
            "Closest lockable position.  The reach limit, the macro focus group and the "
            "shallow depth of field are mechanical assumptions that have not been "
            "verified on a real bench: STRESS_UNCALIBRATED.  Over-close defocus / "
            "field-of-view overflow / fixture collision remain reachable failures."
        ),
    ),
)

#: Physical half-extent of the fragment support surface, mm.  The turntable platter is
#: 200 mm across; anything wider than that is not supported by this rig.
SUPPORT_RADIUS_MM = 100.0


def _intrinsics(spec: _TierSpec) -> np.ndarray:
    width, height = spec.image_size
    f_x = spec.focal_length_mm / spec.sensor_width_mm * width
    f_y = f_x
    return np.array(
        [[f_x, 0.0, width / 2.0 - 0.5],
         [0.0, f_y, height / 2.0 - 0.5],
         [0.0, 0.0, 1.0]],
        dtype=np.float64,
    )


def _fov_mm(spec: _TierSpec) -> tuple[float, float]:
    width, height = spec.image_size
    f_x = spec.focal_length_mm / spec.sensor_width_mm * width
    z = spec.working_distance_mm
    return (z * width / f_x, z * height / f_x)


def _roi(spec: _TierSpec) -> tuple[int, int, int, int]:
    """Center ROI that keeps >= 90 % of the frame (crop origin, size)."""
    width, height = spec.image_size
    cw, ch = int(round(width * 0.95)), int(round(height * 0.95))
    x0, y0 = (width - cw) // 2, (height - ch) // 2
    return (x0, y0, cw, ch)


def _profile_from_spec(spec: _TierSpec) -> CameraProfile:
    K = _intrinsics(spec)
    calibrated = False
    refs = list(spec.calibration_refs)
    near, far = thin_lens_dof(spec.working_distance_mm, spec.focal_length_mm, spec.f_number,
                              DEFAULT_COC_PX, spec.sensor_width_mm / spec.image_size[0])
    meta: dict[str, Any] = {
        "profile_revision": CAMERA_PROFILE_REVISION,
        "label": spec.label,
        "sensor_width_mm": spec.sensor_width_mm,
        "focal_length_mm": spec.focal_length_mm,
        "u_travel_mm": list(spec.u_travel_mm),
        "u_step_mm": spec.u_step_mm,
        "u_allowed_range_mm": list(spec.u_travel_mm),
        "roi_xywh": list(_roi(spec)),
        "allow_digital_zoom": False,
        "coC_px": DEFAULT_COC_PX,
        "dist_order": list(DIST_ORDER),
        "camera_model": "OPENCV",
        "calibration_status": spec.calibration_status,
        "calibration_source": "NOMINAL_SIM" if not calibrated else SOURCE_CALIBRATED,
        "intrinsics_source_kind": SOURCE_SENSOR_SIM,
        "pose_source_kind": SOURCE_SENSOR_SIM,
        "u_move_changes": ["T_WC.t_z", "working_distance_mm", "focal_length_group", "K",
                           "depth_of_field_mm", "focus_setting"],
        "u_move_forbidden": ["image_resize", "digital_crop", "digital_zoom"],
        "support_radius_mm": SUPPORT_RADIUS_MM,
        "readout_time_seconds": spec.action_cost_seconds,
        "notes": spec.notes,
        "pending": [
            "REAL_CALIBRATION_PENDING: no physical target image / measured intrinsics",
            "FOCUS_GROUP_SWEEP_PENDING: focus_setting -> K mapping not measured",
        ],
    }
    return CameraProfile(
        profile_id=spec.profile_id,
        revision=CAMERA_PROFILE_REVISION,
        tier=spec.tier,  # type: ignore[arg-type]
        working_distance_mm=float(spec.working_distance_mm),
        u_position_mm=float(spec.u_position_mm),
        K=K,
        dist=np.asarray(spec.dist, dtype=np.float64),
        image_size=(int(spec.image_size[0]), int(spec.image_size[1])),
        fov_mm=_fov_mm(spec),
        depth_of_field_mm=(near, far),
        focus_setting=spec.focus_setting,
        calibration_refs=refs,
        calibrated=calibrated,
        action_cost_seconds=float(spec.action_cost_seconds),
        f_number=float(spec.f_number),
        meta=meta,
    )


def camera_profiles() -> list[CameraProfile]:
    """GLOBAL / MID / LOCAL profiles at their nominal slide lock positions."""
    return [_profile_from_spec(spec) for spec in _TIER_SPECS]


def profile_by_id(profile_id: str) -> CameraProfile:
    for profile in camera_profiles():
        if profile.profile_id == profile_id:
            return profile
    raise SynLabError(ErrorCode.SCHEMA_INVALID, f"unknown camera profile {profile_id!r}",
                      stage="cameras.profile_by_id",
                      evidence_refs=[p.profile_id for p in camera_profiles()])


def _spec_for_tier(tier: str) -> _TierSpec:
    for spec in _TIER_SPECS:
        if spec.tier == tier:
            return spec
    raise SynLabError(ErrorCode.SCHEMA_INVALID, f"unknown camera tier {tier!r}",
                      stage="cameras.spec_for_tier")


def thin_lens_dof(working_distance_mm: float, focal_length_mm: float, f_number: float,
                  coc_px: float, pixel_pitch_mm: float) -> tuple[float, float]:
    """Classical thin-lens depth of field at ``working_distance_mm`` (mm, mm)."""
    if working_distance_mm <= 0 or focal_length_mm <= 0 or f_number <= 0:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          "working distance, focal length and f-number must be positive",
                          stage="cameras.thin_lens_dof")
    coc_mm = max(coc_px * pixel_pitch_mm, 1e-6)
    z, f, N = working_distance_mm, focal_length_mm, f_number
    hyperfocal = f * f / (N * coc_mm) + f
    near = hyperfocal * z / (hyperfocal + (z - f))
    if z >= hyperfocal:
        far = math.inf
    else:
        far = hyperfocal * z / (hyperfocal - (z - f))
    return float(near), float(far)


def transform_profile_u(profile: CameraProfile, u_position_mm: float) -> CameraProfile:
    """Return the profile at a new *physical* slide position ``u_position_mm``.

    The optical axis of the rig is the world +Z direction through the object centre, so
    a U move changes the camera extrinsic ``t_z`` by ``-(u - u0)``.  The focal length
    group changes with the focus setting, which changes ``K``; ``image_size`` and the
    ROI are unchanged, i.e. no digital zoom or crop is involved.

    Raises ``TARGET_INFEASIBLE`` outside the declared mechanical travel.
    """
    spec = _spec_for_tier(str(profile.tier))
    travel = spec.u_travel_mm
    u = float(u_position_mm)
    if u < travel[0] - 1e-9 or u > travel[1] + 1e-9:
        raise SynLabError(
            ErrorCode.TARGET_INFEASIBLE,
            f"U position {u:.3f} mm outside the declared mechanical travel "
            f"[{travel[0]:.1f}, {travel[1]:.1f}] mm for tier {spec.tier}",
            stage="cameras.transform_profile_u",
            measurements={"u_position_mm": u, "travel_mm": list(travel)},
        )
    delta = u - float(profile.u_position_mm)
    width, height = profile.image_size
    pixel_pitch_mm = spec.sensor_width_mm / float(width)

    # 1. Physical proximity: the camera moves along the optical axis, so the object
    #    centre distance shrinks by exactly the slide displacement.
    new_z = float(profile.working_distance_mm) - delta
    if new_z <= 0:
        raise SynLabError(
            ErrorCode.TARGET_INFEASIBLE,
            f"U position {u:.3f} mm would place the camera at/inside the object "
            f"(working distance {new_z:.3f} mm)",
            stage="cameras.transform_profile_u",
            measurements={"u_position_mm": u, "working_distance_mm": new_z},
        )

    # 2. Focus group: moving the slide forces a re-focus, and the |delta| used here is
    #    the *nominal* focus-group shift declared for this tier.  It is deliberately a
    #    small correction, not a zoom: it is the lens group travel, not a crop factor.
    group_delta_mm = float(np.clip(delta * 0.06, -0.25, 0.25))
    new_focal_mm = spec.focal_length_mm + group_delta_mm
    f_x = new_focal_mm / spec.sensor_width_mm * width
    f_y = f_x
    K = np.array([[f_x, 0.0, width / 2.0 - 0.5],
                  [0.0, f_y, height / 2.0 - 0.5],
                  [0.0, 0.0, 1.0]], dtype=np.float64)

    # 3. Distortion follows the focus group; the change is small and frozen by the
    #    nominal lens curve.
    dist = np.asarray(profile.dist, dtype=np.float64).copy()
    if dist.size >= 5:
        dist = dist * (1.0 + 0.15 * group_delta_mm / max(spec.focal_length_mm, 1e-6))

    near, far = thin_lens_dof(new_z, new_focal_mm, float(profile.f_number),
                              DEFAULT_COC_PX, pixel_pitch_mm)
    meta = dict(profile.meta)
    meta["u_position_mm"] = u
    meta["focus_group_delta_mm"] = group_delta_mm
    meta["focal_length_mm"] = new_focal_mm
    meta["mm_per_pixel"] = new_z / f_x
    meta["u_move_realised_as"] = "CAMERA_EXTRINSIC_ALONG_OPTICAL_AXIS"
    meta["digital_zoom_applied"] = False
    if u > spec.u_travel_mm[1] - spec.u_step_mm / 2 or u < spec.u_travel_mm[0] + spec.u_step_mm / 2:
        meta["calibration_status"] = "STRESS_UNCALIBRATED"
    return CameraProfile(
        profile_id=f"{spec.profile_id}_U{u:+.0f}mm",
        revision=int(profile.revision),
        tier=profile.tier,
        working_distance_mm=new_z,
        u_position_mm=u,
        K=K,
        dist=dist,
        image_size=profile.image_size,
        fov_mm=(new_z * width / f_x, new_z * height / f_y),
        depth_of_field_mm=(near, far),
        focus_setting=f"{spec.focus_setting}@{u:+.0f}mm",
        calibration_refs=list(profile.calibration_refs),
        calibrated=False,
        action_cost_seconds=float(profile.action_cost_seconds),
        f_number=float(profile.f_number),
        meta=meta,
    )


def camera_center_from_profile(profile: CameraProfile,
                               target_center_mm: np.ndarray) -> np.ndarray:
    """Camera centre on the optical axis at ``working_distance_mm`` from the target."""
    center = np.asarray(target_center_mm, dtype=np.float64).reshape(3)
    return center + np.array([0.0, 0.0, float(profile.working_distance_mm)])
