"""View-frame construction: 3 height layers x 4 azimuths, quaternion SO(3) sampling.

Plan 13.1 fixes the starting capture cache at **12 whole-fragment views** (3 height
layers x 4 azimuths).  Twelve frames is a *training cache budget*; it is not a claim
about how many views MVS needs (plan 14.4 asks for 30-120 overlapping frames per
fragment).

Rotation sampling
-----------------
Random orientations use normalised Gaussian quaternions (:func:`sample_so3_quaternion`),
which is the Haar-uniform distribution on SO(3).  Uniform Euler angles are **not**
uniform on SO(3) and are never used to stand in for them (plan 4.3).

Scan frame
----------
Every fragment gets an independent random scan frame ``S`` (a rigid transform of the
assembly world ``W`` recorded in the view-frame metadata).  All views of one fragment
share the same ``S`` so that the observation is geometrically consistent, while
different fragments get different ``S``.  ``T_WF`` (the clean assembly pose of the
fragment) is never written into a ``ViewFrame``.
"""

from __future__ import annotations

import numpy as np

from ..errors import ErrorCode, SynLabError
from ..schemas.runtime import CameraProfile, ViewFrame

#: Fixture model of the capture bench (plan 13.4).  The phone fixture is bolted to the
#: linear slide; the *object* sits on a manual turntable.  Every view therefore has the
#: camera centre on the rig optical axis (+Z through the target centre) and the
#: azimuthal diversity comes from the scanned object pose, not from moving the camera
#: off the axis.
RIG_MODEL = "FIXED_CAMERA_ON_SLIDE_AXIS_PLUS_OBJECT_TURNTABLE"

#: Camera local frame of Blender (right, up, -z view direction) expressed in the
#: OpenCV camera frame (right, down, +z view direction).  ``T_C_blender = FLIP``.
BLENDER_FROM_OPENCV = np.diag([1.0, -1.0, -1.0]).astype(np.float64)

#: Default 3 height layers x 4 azimuths starting cache (plan 13.1).
DEFAULT_LAYERS = 4
DEFAULT_AZIMUTHS = 4


def rotation_about_axis(axis: np.ndarray, angle_rad: float) -> np.ndarray:
    axis = np.asarray(axis, dtype=np.float64).reshape(3)
    n = np.linalg.norm(axis)
    if n < 1e-15:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "rotation axis is degenerate",
                          stage="cameras.rotation_about_axis")
    x, y, z = axis / n
    c, s = float(np.cos(angle_rad)), float(np.sin(angle_rad))
    C = 1.0 - c
    return np.array([
        [c + x * x * C, x * y * C - z * s, x * z * C + y * s],
        [y * x * C + z * s, c + y * y * C, y * z * C - x * s],
        [z * x * C - y * s, z * y * C + x * s, c + z * z * C],
    ], dtype=np.float64)


def homogeneous(R: np.ndarray, t: np.ndarray | None = None) -> np.ndarray:
    T = np.eye(4, dtype=np.float64)
    T[:3, :3] = np.asarray(R, dtype=np.float64)
    if t is not None:
        T[:3, 3] = np.asarray(t, dtype=np.float64).reshape(3)
    return T


def sample_so3_quaternion(rng: np.random.Generator) -> np.ndarray:
    """One Haar-uniform rotation as a unit quaternion ``(w, x, y, z)``.

    A 4-vector of i.i.d. standard normals normalised to unit length is exactly uniform
    on S^3, which double-covers SO(3) uniformly (Shoemake 1985).
    """
    q = rng.normal(size=4)
    n = float(np.linalg.norm(q))
    while n < 1e-12:
        q = rng.normal(size=4)
        n = float(np.linalg.norm(q))
    return q / n


def quaternion_matrix(q: np.ndarray) -> np.ndarray:
    q = np.asarray(q, dtype=np.float64).reshape(4)
    w, x, y, z = q / np.linalg.norm(q)
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ], dtype=np.float64)


def scan_frame(rng: np.random.Generator) -> np.ndarray:
    """Independent random rigid scan frame ``T_WS`` for one fragment."""
    q = sample_so3_quaternion(rng)
    R = quaternion_matrix(q)
    t = rng.normal(scale=5.0, size=3)  # mm; a scan jig is hand-placed
    return homogeneous(R, t)


def make_view_frames(
    profile: CameraProfile,
    target_bbox: np.ndarray | tuple[float, float, float, float, float, float],
    count: int,
    rng: np.random.Generator,
    *,
    tiers: tuple[str, ...] = ("GLOBAL", "MID", "LOCAL"),
    orbit: bool = True,
    scan_frame_id: str = "S",
) -> list[ViewFrame]:
    """Build ``count`` view frames for one fragment under ``profile``.

    ``target_bbox`` is ``(xmin, ymin, zmin, xmax, ymax, zmax)`` in assembly-world mm (or
    the observation scan frame; the caller decides).  ``count`` is normally 12
    (3 layers x 4 azimuths).

    ``orbit=True`` keeps the camera centre on the rig optical axis and distributes the
    object pose over ``layers x azimuths``; ``orbit=False`` places the camera itself on
    the sampled sphere directions (wrist/eye-in-hand capture), which is recorded in the
    frame metadata rather than being silently mixed in.
    """
    bbox = np.asarray(target_bbox, dtype=np.float64).reshape(-1)
    if bbox.size != 6:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"target_bbox must have 6 entries, got {bbox.size}",
                          stage="cameras.make_view_frames")
    center = np.array([(bbox[0] + bbox[3]) / 2.0, (bbox[1] + bbox[4]) / 2.0,
                       (bbox[2] + bbox[5]) / 2.0])
    extent = np.array([bbox[3] - bbox[0], bbox[4] - bbox[1], bbox[5] - bbox[2]])
    if np.any(extent < 0):
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "target_bbox min > max",
                          stage="cameras.make_view_frames")
    radius = float(np.linalg.norm(extent) / 2.0)
    if radius <= 0:
        radius = 1.0

    count = int(count)
    if count < 1:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, f"count must be >= 1, got {count}",
                          stage="cameras.make_view_frames")
    layers = min(DEFAULT_LAYERS, count)
    azimuths = int(np.ceil(count / layers))
    width, height = int(profile.image_size[0]), int(profile.image_size[1])
    distance = float(profile.working_distance_mm)
    T_WS = scan_frame(rng) if scan_frame_id else np.eye(4)

    # Half the field of view in each axis, used to check that the object still fits.
    f_x = float(profile.K[0, 0])
    half_w_mm = distance * width / (2.0 * f_x)
    half_h_mm = distance * height / (2.0 * float(profile.K[1, 1]))

    # Extra per-view pose jitter (hand re-clamping), sampled in the *rotation* group.
    frames: list[ViewFrame] = []
    for index in range(count):
        layer = index % layers
        azimuth_index = index // layers
        elevation = np.deg2rad(-22.5 + 45.0 * layer / max(layers - 1, 1))
        azimuth = 2.0 * np.pi * azimuth_index / azimuths
        if orbit:
            eye = center + np.array([
                distance * np.sin(elevation) * np.sin(azimuth),
                -distance * np.sin(elevation) * np.cos(azimuth),
                distance * np.cos(elevation),
            ])
            # small wrist re-clamp: rotate the view direction about the eye, <= 0.35 deg
            axis = rng.normal(size=3)
            axis /= max(float(np.linalg.norm(axis)), 1e-12)
            jitter = rotation_about_axis(axis, float(rng.normal(scale=np.deg2rad(0.35))))
            T_WC = np.eye(4, dtype=np.float64)
            forward = (center - eye)
            forward /= np.linalg.norm(forward)
            up = np.array([0.0, 1.0, 0.0])
            if abs(float(np.dot(forward, up))) > 0.999:
                up = np.array([1.0, 0.0, 0.0])
            x_c = np.cross(up, forward)
            x_c /= np.linalg.norm(x_c)
            y_c = np.cross(forward, x_c)
            T_WC[:3, 0], T_WC[:3, 1], T_WC[:3, 2] = x_c, y_c, forward
            T_WC[:3, :3] = T_WC[:3, :3] @ jitter
            T_WC[:3, 3] = eye
            framing = "ORBIT"
            object_pose = np.eye(4)
        else:
            # fixture: the camera never leaves the slide axis.  Azimuthal diversity is
            # the scanned object pose R_y(azimuth) applied to the fragment.
            T_WC = np.eye(4, dtype=np.float64)
            # OpenCV camera at +Z looking back down the axis (-z view direction is
            # +z forward = towards -Z world), so the camera +z axis is -Z world.
            T_WC[:3, 0] = np.array([1.0, 0.0, 0.0])
            T_WC[:3, 1] = np.array([0.0, -1.0, 0.0])
            T_WC[:3, 2] = np.array([0.0, 0.0, -1.0])
            T_WC[:3, 3] = center + np.array([0.0, 0.0, distance])
            axis = rng.normal(size=3)
            axis /= max(float(np.linalg.norm(axis)), 1e-12)
            jitter = rotation_about_axis(axis, float(rng.normal(scale=np.deg2rad(0.35))))
            T_WC[:3, :3] = T_WC[:3, :3] @ jitter
            framing = "TURNTABLE"
            object_pose = np.eye(4)
            R_turn = rotation_about_axis(np.array([0.0, 1.0, 0.0]), azimuth)
            object_pose[:3, :3] = R_turn
            # rotate about the vertical axis *through the fragment centre* so the
            # fragment stays on the camera axis, exactly as a centred turntable does.
            object_pose[:3, 3] = center - R_turn @ center
        view_id = f"{profile.profile_id}#v{index:02d}"
        meta = {
            "rig_model": RIG_MODEL,
            "framing": framing,
            "layer_index": int(layer),
            "azimuth_index": int(azimuth_index),
            "layers": int(layers),
            "azimuths": int(azimuths),
            "elevation_deg": float(np.rad2deg(elevation)),
            "azimuth_deg": float(np.rad2deg(azimuth)),
            "object_pose_T_WO": object_pose.tolist(),
            "scan_frame_id": scan_frame_id,
            "T_WS": T_WS.tolist(),
            "target_center_mm": center.tolist(),
            "target_radius_mm": radius,
            "half_fov_mm_at_target": [half_w_mm, half_h_mm],
            "in_fov": bool(radius <= 0.98 * min(half_w_mm, half_h_mm)),
            "profile_revision": int(profile.revision),
            "focal_length_mm": profile.meta.get("focal_length_mm"),
            "mm_per_pixel": profile.mm_per_pixel,
            "calibration_status": profile.meta.get("calibration_status", "UNCALIBRATED"),
            "T_blender_from_opencv": BLENDER_FROM_OPENCV.tolist(),
            "digital_zoom_applied": False,
        }
        frames.append(ViewFrame(
            view_id=view_id,
            K=np.asarray(profile.K, dtype=np.float64).copy(),
            T_WC=T_WC,
            image_size=(width, height),
            profile_id=profile.profile_id,
            tier=str(profile.tier),
            u_position_mm=float(profile.u_position_mm),
            working_distance_mm=float(profile.working_distance_mm),
            focus_setting=profile.focus_setting,
            source_kind=str(profile.meta.get("pose_source_kind", "SENSOR_SIM")),
            camera_model=str(profile.meta.get("camera_model", "PINHOLE")),
            dist=np.asarray(profile.dist, dtype=np.float64).copy(),
            meta=meta,
        ))
    return frames


def view_frame_footprint(frame: ViewFrame, half_extent_mm: float = 60.0) -> dict[str, float]:
    """Analytic check values for QA: mm/px at the target and the covered width."""
    width, height = frame.image_size
    z = float(frame.working_distance_mm)
    return {
        "mm_per_pixel_x": z / float(frame.K[0, 0]),
        "mm_per_pixel_y": z / float(frame.K[1, 1]),
        "fov_width_mm": z * width / float(frame.K[0, 0]),
        "fov_height_mm": z * height / float(frame.K[1, 1]),
        "half_extent_mm": float(half_extent_mm),
    }
