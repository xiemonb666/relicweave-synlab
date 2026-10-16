"""``synlab.cameras`` façade: profiles, view frames, projection and pixel contracts.

Frozen interface (``docs/a12/interfaces.md`` section 2)::

    camera_profiles() -> list[CameraProfile]
    make_view_frames(profile, target_bbox, count, rng, *, tiers=..., orbit=...) -> list[ViewFrame]
    project(points_mm, K, T_WC, dist=None) -> (uv, z)
    unproject(uv, z, K, T_WC, dist=None) -> points_mm
    pixel_transform_crop_resize(x0, y0, sx, sy, K) -> (A, K_new)
    colmap_convention(K) -> K_colmap
"""

from __future__ import annotations

from .profiles import (
    CAMERA_PROFILE_REVISION,
    DEFAULT_COC_PX,
    DIST_ORDER,
    SUPPORT_RADIUS_MM,
    camera_center_from_profile,
    camera_profiles,
    profile_by_id,
    thin_lens_dof,
    transform_profile_u,
)
from .projection import (
    CAMERA_MODELS,
    apply_exif_to_image,
    camera_to_world,
    colmap_convention,
    colmap_unconvention,
    crop_resize_matrix,
    exif_transform,
    from_colmap_pixels,
    from_colmap_pose,
    letterbox_transform,
    look_at_T_WC,
    pixel_transform_crop_resize,
    project,
    project_cam_from_world,
    to_colmap_pixels,
    to_colmap_pose,
    undistort_normalized,
    unproject,
    unproject_cam_from_world,
    world_to_camera,
)
from .viewframes import (
    BLENDER_FROM_OPENCV,
    RIG_MODEL,
    make_view_frames,
    quaternion_matrix,
    rotation_about_axis,
    sample_so3_quaternion,
    scan_frame,
    view_frame_footprint,
)

__all__ = [
    "CAMERA_PROFILE_REVISION", "DEFAULT_COC_PX", "DIST_ORDER", "SUPPORT_RADIUS_MM",
    "CAMERA_MODELS", "RIG_MODEL", "BLENDER_FROM_OPENCV",
    "camera_profiles", "profile_by_id", "transform_profile_u", "camera_center_from_profile",
    "thin_lens_dof",
    "make_view_frames", "scan_frame", "sample_so3_quaternion", "quaternion_matrix",
    "rotation_about_axis", "view_frame_footprint",
    "project", "unproject", "project_cam_from_world", "unproject_cam_from_world",
    "world_to_camera", "camera_to_world", "look_at_T_WC",
    "crop_resize_matrix", "pixel_transform_crop_resize", "letterbox_transform",
    "exif_transform", "apply_exif_to_image",
    "colmap_convention", "colmap_unconvention", "to_colmap_pixels", "from_colmap_pixels",
    "to_colmap_pose", "from_colmap_pose", "undistort_normalized",
]
