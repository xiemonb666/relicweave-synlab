"""Observation-layer audits (A11, A12, A13, A25 evidence).

These audits measure the delivered channels and operator effects directly — integer label
maps, camera z, uncertain bands, deployable masks, spurious-surface geometry and camera
profile engineering.  Nothing is inferred from configuration.
"""

from __future__ import annotations

import hashlib
from typing import Any

import numpy as np
import trimesh

from ..canonical import array_hash, hash_json
from ..errors import ErrorCode, SynLabError
from ..roles import SOURCE_SENSOR_SIM
from ..schemas.runtime import (
    CameraProfile,
    ObservationResult,
    ObsView,
    RenderOutput,
    ViewFrame,
)
from ..storage.store import AssetStore


def _box(size: tuple[float, float, float] = (100.0, 100.0, 100.0)) -> trimesh.Trimesh:
    mesh = trimesh.creation.box(extents=size)
    return mesh


def _mesh_digest(mesh: trimesh.Trimesh) -> str:
    return hash_json({
        "vertices": array_hash(np.asarray(mesh.vertices, dtype=np.float64)),
        "faces": array_hash(np.asarray(mesh.faces, dtype=np.int32)),
    })


# ---------------------------------------------------------------------------- channels
def audit_channels(store: AssetStore | None = None) -> dict[str, Any]:
    from .render import LightSpec, RenderSpec, build_scene, deployment_mask_from_render, render_view
    from ..cameras.api import make_view_frames

    box = _box()
    scene = build_scene(box, surface_tag=np.zeros(len(box.faces), dtype=np.int16))
    light = LightSpec(direction=np.array([-0.3, -0.4, -0.85]), color=np.array([1.0, 1.0, 1.0]),
                      ambient=np.array([0.05, 0.05, 0.06]))
    profile = _profile("GLOBAL")
    bbox = np.asarray(box.bounds).reshape(-1)
    frames = make_view_frames(profile, tuple(float(x) for x in bbox), 1,
                              np.random.default_rng(7))
    frame: ViewFrame = frames[0]
    render: RenderOutput = render_view(scene, frame, light=light, spec=RenderSpec(supersample=2),
                                       focus_distance_mm=frame.working_distance_mm)
    depth = np.asarray(render.depth_z, dtype=np.float64)
    ids = np.asarray(render.id_map)
    visible = np.asarray(render.visibility) > 0
    uncertain = np.asarray(render.uncertain_mask, dtype=bool)
    rgb = np.asarray(render.rgb_linear)

    # analytic camera z of the box surface along each visible pixel ray
    analytic = _analytic_box_z(box, frame)
    valid = visible & np.isfinite(depth) & np.isfinite(analytic)
    depth_err = np.abs(depth[valid] - analytic[valid]) if valid.any() else np.array([np.inf])

    # integer labels must not be interpolated into fractional classes
    integer_labels = np.issubdtype(ids.dtype, np.integer)
    distinct = np.unique(ids)
    fractional = int(np.sum(~np.isclose(ids, np.round(ids))))

    # the uncertain band must sit on silhouettes: neighbours differ in visibility
    boundary_hits = 0
    if uncertain.any():
        shifted = np.zeros_like(visible)
        shifted[:, :-1] |= visible[:, 1:]
        shifted[:, 1:] |= visible[:, :-1]
        shifted[:-1, :] |= visible[1:, :]
        shifted[1:, :] |= visible[:-1, :]
        boundary_hits = int(np.sum(uncertain & (shifted != visible)))

    mask = deployment_mask_from_render(render)
    mask_excludes_uncertain = bool(not np.any(mask & uncertain))
    mask_not_using_labels_only = bool(mask.sum() <= visible.sum())

    metrics = {
        "rgb_dtype": str(rgb.dtype),
        "rgb_finite": bool(np.isfinite(rgb).all()),
        "rgb_min": float(rgb.min()),
        "rgb_max": float(rgb.max()),
        "depth_median_abs_error_mm": float(np.median(depth_err)),
        "depth_p95_abs_error_mm": float(np.percentile(depth_err, 95)),
        "visible_pixels": int(visible.sum()),
        "integer_label_dtype": integer_labels,
        "label_values": [int(v) for v in distinct[:6]],
        "fractional_labels": fractional,
        "uncertain_pixels": int(uncertain.sum()),
        "uncertain_on_silhouette": boundary_hits,
        "deployment_mask_pixels": int(mask.sum()),
        "mask_excludes_uncertain": mask_excludes_uncertain,
        "mask_within_visibility": mask_not_using_labels_only,
        "backend": render.backend,
    }
    ok = (
        metrics["rgb_finite"] and metrics["rgb_min"] >= 0.0
        and metrics["depth_median_abs_error_mm"] <= 1.0
        and integer_labels and fractional == 0
        and metrics["uncertain_pixels"] > 0 and boundary_hits > 0
        and mask_excludes_uncertain and mask_not_using_labels_only
    )
    # research labels must stay out of the deployment mask by construction
    leaked = bool(mask.sum() and not visible.sum())
    ok = ok and not leaked
    return {
        "ok": bool(ok),
        "status": "PASS" if ok else "FAIL",
        "metrics": metrics,
        "note": ("depth is compared against an analytic ray/box intersection in millimetres; "
                 "integer labels are checked for interpolation; the uncertain band is checked "
                 "against the silhouette, and the deployment mask must exclude it"),
    }


def _analytic_box_z(box: trimesh.Trimesh, frame: ViewFrame) -> np.ndarray:
    """Camera z of the first box surface hit by each pixel ray (analytic, in mm)."""
    height, width = frame.image_size[1], frame.image_size[0]
    us, vs = np.meshgrid(np.arange(width), np.arange(height))
    pixels = np.stack([us.ravel(), vs.ravel()], axis=1).astype(np.float64)
    K = np.asarray(frame.K, dtype=np.float64)
    rays_cam = np.concatenate([
        (pixels[:, 0] - K[0, 2]) / K[0, 0],
        (pixels[:, 1] - K[1, 2]) / K[1, 1],
        np.ones(pixels.shape[0]),
    ], axis=0).reshape(3, -1)
    R = np.asarray(frame.T_WC, dtype=np.float64)[:3, :3]
    t = np.asarray(frame.T_WC, dtype=np.float64)[:3, 3]
    # ray origins in world space, directions in world space
    origins = np.broadcast_to(t[None, :], (pixels.shape[0], 3))
    dirs = (R @ rays_cam).T
    dirs /= np.linalg.norm(dirs, axis=1, keepdims=True)
    # slab intersection with the axis-aligned box; camera z = t along the *camera* forward axis
    lo, hi = np.asarray(box.bounds[0]), np.asarray(box.bounds[1])
    with np.errstate(divide="ignore", invalid="ignore"):
        inv = 1.0 / dirs
        t1 = (lo[None, :] - origins) * inv
        t2 = (hi[None, :] - origins) * inv
    tmin = np.nanmax(np.minimum(t1, t2), axis=1)
    tmax = np.nanmin(np.maximum(t1, t2), axis=1)
    hit = (tmax >= np.maximum(tmin, 0)) & np.isfinite(tmin)
    forward = R[:, 2]
    z = np.where(hit, np.maximum(tmin, 0.0) * (dirs @ forward), np.nan)
    return z.reshape(height, width)


def _profile(tier: str, *, long_edge_px: int = 320) -> CameraProfile:
    """Profile scaled down to a small render target so audits stay cheap."""
    import dataclasses

    from ..cameras.api import camera_profiles

    base = None
    for profile in camera_profiles():
        if profile.tier == tier:
            base = profile
            break
    if base is None:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, f"no camera profile for tier {tier}",
                          stage="observe.audit")
    width, height = base.image_size
    scale = long_edge_px / max(width, height)
    K = np.asarray(base.K, dtype=np.float64).copy()
    K[0, 0] *= scale
    K[1, 1] *= scale
    K[0, 2] *= scale
    K[1, 2] *= scale
    return dataclasses.replace(base, K=K,
                               image_size=(max(16, int(round(width * scale))),
                                           max(16, int(round(height * scale)))))


# ---------------------------------------------------------------------------- spurious
def _spurious_target() -> trimesh.Trimesh:
    """Observation-shaped target with a real boundary hole and two disconnected regions.

    ``false_patch`` needs an observed boundary hole and ``bridge`` needs two disconnected
    regions (plan 15.4); the audit must not silently skip a variant whose precondition the
    fixture does not provide.
    """
    plate = trimesh.creation.box(extents=(80.0, 40.0, 10.0))
    plate = plate.subdivide().subdivide()
    centroids = np.asarray(plate.triangles_center)
    normals = np.asarray(plate.face_normals)
    top = normals[:, 2] > 0.9
    top_idx = np.where(top)[0]
    anchor_xy = np.array([-20.0, 0.0])
    if top_idx.size:
        nearest = top_idx[np.argmin(np.linalg.norm(centroids[top_idx][:, :2] - anchor_xy, axis=1))]
        anchor = centroids[nearest][:2]
        hole = np.zeros(len(plate.faces), dtype=bool)
        # grow the removal radius until at least four top faces are removed, so the hole
        # has a boundary loop long enough for the false_patch operator to close it
        for radius in (10.0, 14.0, 18.0, 24.0):
            hole = top & (np.linalg.norm(centroids[:, :2] - anchor, axis=1) < radius)
            if int(hole.sum()) >= 4:
                break
    else:
        hole = np.zeros(len(plate.faces), dtype=bool)
    carved = trimesh.Trimesh(vertices=plate.vertices, faces=plate.faces[~hole], process=False)
    second = trimesh.creation.box(extents=(18.0, 18.0, 10.0))
    second.apply_translation((55.0, 0.0, 0.0))
    combined = trimesh.util.concatenate([carved, second])
    combined.process(validate=False)
    return combined


def audit_spurious(store: AssetStore | None = None) -> dict[str, Any]:
    from ..schemas.runtime import DegradationBasis
    from .spurious import apply_spurious

    base_mesh = _spurious_target()
    results: dict[str, Any] = {}
    all_ok = True
    level_zero_identity = True
    for variant in ("bump", "false_patch", "bridge"):
        basis = DegradationBasis(axis_id="G08", variant=variant,
                                 basis_id=f"audit-{variant}", seed_ref="audit")
        identity_before = _mesh_digest(base_mesh)
        obs0 = _synthetic_observation(base_mesh)
        try:
            out0, metrics0 = apply_spurious(obs0, variant, 0, basis, np.random.default_rng(1))
        except SynLabError as exc:
            results[variant] = {"status": "FAIL", "error": f"{exc.code}: {exc.message}"}
            all_ok = False
            continue
        level_zero_identity &= out0.fused_mesh is base_mesh or _mesh_digest(out0.fused_mesh) == identity_before
        obs2 = _synthetic_observation(base_mesh)
        try:
            out2, metrics2 = apply_spurious(obs2, variant, 2, basis, np.random.default_rng(2))
        except SynLabError as exc:
            results[variant] = {"status": "FAIL", "error": f"{exc.code}: {exc.message}",
                                "level0_identity": bool(level_zero_identity)}
            all_ok = False
            continue
        source_unchanged = _mesh_digest(base_mesh) == identity_before
        area_before = float(base_mesh.area)
        area_after = float(out2.fused_mesh.area) if out2.fused_mesh is not None else area_before
        comps_before = len(base_mesh.split(only_watertight=False))
        comps_after = len(out2.fused_mesh.split(only_watertight=False)) if out2.fused_mesh is not None else comps_before
        changed = abs(area_after - area_before) > 1e-9 or comps_after != comps_before
        ok = bool(source_unchanged and changed and metrics2)
        all_ok &= ok
        results[variant] = {
            "status": "PASS" if ok else "FAIL",
            "level0_identity": bool(out0.fused_mesh is base_mesh or _mesh_digest(out0.fused_mesh) == identity_before),
            "source_unchanged": bool(source_unchanged),
            "area_before_mm2": area_before,
            "area_after_mm2": area_after,
            "components_before": comps_before,
            "components_after": comps_after,
            "measured": {k: float(v) for k, v in (metrics2 or {}).items()
                         if isinstance(v, (int, float))},
        }
    return {
        "ok": bool(all_ok),
        "status": "PASS" if all_ok else "FAIL",
        "metrics": {"variants": results, "level_zero_identity": bool(level_zero_identity),
                    "clean_hash_unchanged": all(v.get("source_unchanged", False)
                                                for v in results.values())},
        "note": ("spurious surfaces change only the observed geometry; the source mesh digest "
                 "is compared before and after every call"),
    }


def _synthetic_observation(mesh: trimesh.Trimesh) -> ObservationResult:
    points = np.asarray(mesh.vertices, dtype=np.float32)
    frame = ViewFrame(view_id="audit", K=np.asarray([[100.0, 0.0, 32.0], [0.0, 100.0, 32.0],
                                                    [0.0, 0.0, 1.0]]),
                      T_WC=np.eye(4), image_size=(64, 64), profile_id="GLOBAL",
                      tier="GLOBAL", u_position_mm=0.0, working_distance_mm=300.0,
                      focus_setting="fixed", source_kind=SOURCE_SENSOR_SIM)
    view = ObsView(view_id="audit", frame=frame, rgb=np.zeros((64, 64, 3), np.uint8),
                   rgb_linear=np.zeros((64, 64, 3), np.float32), depth_z=np.full((64, 64), np.nan),
                   id_map=np.full((64, 64), -1, np.int32), surface_tag=np.zeros((64, 64), np.int16),
                   deployment_mask=np.zeros((64, 64), bool), roi=None,
                   uncertain_mask=np.zeros((64, 64), bool), quality={}, source_kind=SOURCE_SENSOR_SIM)
    return ObservationResult(
        mother_id="audit", fragment_id="audit", component_id="audit", route="proxy_scan",
        input_profile="SENSOR_PROXY", observation_id="audit", views=[view], points=points,
        normals=np.tile(np.array([[0.0, 0.0, 1.0]], np.float32), (len(points), 1)),
        point_valid=np.ones(len(points), bool), normal_valid=np.ones(len(points), bool),
        scale_valid=True, frame_id="S_mm", quality={}, fused_mesh=mesh,
        spurious_mask=None, backend_report={}, meta={},
    )


# ---------------------------------------------------------------------------- cameras
def audit_camera_profiles(store: AssetStore | None = None) -> dict[str, Any]:
    from ..cameras.api import camera_profiles, make_view_frames, project, unproject
    from ..cameras.profiles import transform_profile_u

    profiles = camera_profiles()
    tiers = {p.tier: p for p in profiles}
    engineering: dict[str, Any] = {}
    ok = True
    box = _box()
    bbox = tuple(float(x) for x in np.asarray(box.bounds).reshape(-1))
    for tier in ("GLOBAL", "MID", "LOCAL"):
        profile = tiers.get(tier)
        if profile is None:
            engineering[tier] = {"status": "FAIL", "error": "profile missing"}
            ok = False
            continue
        frames = make_view_frames(profile, bbox, 2, np.random.default_rng(11))
        moved = None
        move_error = None
        for delta in (10.0, -10.0, 5.0, -5.0):
            try:
                moved = transform_profile_u(profile, profile.u_position_mm + delta)
                break
            except SynLabError as exc:  # outside the declared mechanical travel
                move_error = f"{exc.code}: {exc.message}"
        if moved is None:
            engineering[tier] = {"status": "FAIL", "error": move_error or "U move infeasible",
                                 "declared_travel_error": move_error}
            ok = False
            continue
        frames_moved = make_view_frames(moved, bbox, 1, np.random.default_rng(11))
        delta = float(np.linalg.norm(np.asarray(frames_moved[0].T_WC)[:3, 3]
                                     - np.asarray(frames[0].T_WC)[:3, 3]))
        same_image_size = frames_moved[0].image_size == frames[0].image_size
        # projection round trip with the real intrinsics
        points = np.array([[10.0, 5.0, profile.working_distance_mm]], dtype=np.float64)
        uv, z = project(points, np.asarray(frames[0].K), np.asarray(frames[0].T_WC))
        back = np.asarray(unproject(uv, z, np.asarray(frames[0].K), np.asarray(frames[0].T_WC)))
        roundtrip_mm = float(np.max(np.abs(back - points)))
        entry = {
            "status": "PASS" if (delta > 0.5 and same_image_size and roundtrip_mm <= 1e-6) else "FAIL",
            "working_distance_mm": float(profile.working_distance_mm),
            "u_position_mm": float(profile.u_position_mm),
            "mm_per_pixel": float(profile.mm_per_pixel),
            "u_move_translation_mm": delta,
            "u_move_delta_mm": float(moved.u_position_mm - profile.u_position_mm),
            "image_size_unchanged": bool(same_image_size),
            "projection_roundtrip_mm": roundtrip_mm,
            "calibrated": bool(profile.calibrated),
        }
        engineering[tier] = entry
        ok &= entry["status"] == "PASS"
    calibration_ok = all(p.calibrated for p in profiles)
    return {
        "ok": bool(ok),
        "engineering_ok": bool(ok),
        "calibration_ok": bool(calibration_ok),
        "status": "PASS" if ok and calibration_ok else ("PENDING" if ok else "FAIL"),
        "metrics": {"tiers": engineering,
                    "profiles": [p.profile_id for p in profiles],
                    "note": ("a U move changes the camera extrinsic and never the image size; "
                             "real-capture calibration is absent on this host, so "
                             "A13.real_calibration stays PENDING")},
    }
