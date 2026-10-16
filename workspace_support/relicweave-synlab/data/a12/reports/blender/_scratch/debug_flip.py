"""Scratch: prove/deny that the Blender path renders the target rotated 180 deg about Z.

Compares one real Blender view of the V01 mother against the independent ray cast of
(a) the posed mesh as the project builds it, and (b) the same mesh with an extra 180 deg
rotation about the world Z axis (what Blender's PLY importer produced in the axis probe).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from render_1024_12 import cast_rays, mother_target, pinhole_twin  # noqa: E402
from synlab.cameras.api import camera_profiles                    # noqa: E402
from synlab.cameras.viewframes import make_view_frames            # noqa: E402
from synlab.observe.blender import BlenderBackendConfig           # noqa: E402
from synlab.observe.render import BACKEND_BLENDER, RenderSpec, build_scene  # noqa: E402
from synlab.observe.routes import ObsSpec, render_view            # noqa: E402
from synlab.seeds import make_rng                                 # noqa: E402

LONG_EDGE = 1024


def rz180() -> np.ndarray:
    T = np.eye(4)
    T[:3, :3] = np.array([[-1.0, 0.0, 0.0], [0.0, -1.0, 0.0], [0.0, 0.0, 1.0]])
    return T


def compare(depth: np.ndarray, K, T_WC, verts, faces, uncertain, stride: int = 8) -> dict:
    out = {}
    cast = cast_rays(np.asarray(K, dtype=np.float64), np.asarray(T_WC, dtype=np.float64),
                     verts, faces, (LONG_EDGE, int(round(LONG_EDGE * 3 / 4))), stride)
    rendered = np.asarray(depth, dtype=np.float64)[cast["y"], cast["x"]]
    zref = cast["z_mm"]
    both = np.isfinite(rendered) & np.isfinite(zref)
    interior = both & ~np.asarray(uncertain, dtype=bool)[cast["y"], cast["x"]]
    delta = np.abs(rendered - zref)
    out["hits"] = int(np.isfinite(zref).sum())
    out["both"] = int(both.sum())
    out["ray_only"] = int((~np.isfinite(rendered) & np.isfinite(zref)).sum())
    out["render_only"] = int((np.isfinite(rendered) & ~np.isfinite(zref)).sum())
    out["interior"] = int(interior.sum())
    out["interior_max_mm"] = float(delta[interior].max()) if interior.any() else None
    out["interior_mean_mm"] = float(delta[interior].mean()) if interior.any() else None
    out["all_max_mm"] = float(delta[both].max()) if both.any() else None
    face_mismatch = np.asarray(0)
    del face_mismatch
    return out


def main() -> int:
    mother, target = mother_target("V01")
    profile = camera_profiles()[1]
    frames = make_view_frames(profile, target.bbox, 12, make_rng(20261001,
                                                                "blender_route_wiring",
                                                                "render_1024"),
                              tiers=("GLOBAL", "MID", "LOCAL"), orbit=True)
    frame = frames[0]
    # render-grid frame: 1024x768 from the 4000x3000 profile frame (production derivation)
    spec = ObsSpec(view_count=12, delivered_size=(1024, 768), max_render_pixels=1024 * 768,
                   render_spec=RenderSpec(supersample=1), master_seed=20261001,
                   lineage_id="blender_route_wiring", renderer="blender",
                   distortion_policy="undistort")
    size, x0, y0, sx, sy = spec.derivation(frame.image_size)
    from synlab.observe.routes import _rescaled_frame, render_frame_for_backend  # noqa: E402

    rframe = _rescaled_frame(frame, size)
    rframe, _prov = render_frame_for_backend(rframe, backend=BACKEND_BLENDER, spec=spec)
    pose = np.asarray(frame.meta["object_pose_T_WO"], dtype=np.float64)
    verts = np.asarray(target.mesh.vertices, dtype=np.float64)
    faces = np.asarray(target.mesh.faces, dtype=np.int64)
    posed = verts @ pose[:3, :3].T + pose[:3, 3][None, :]
    flipped = posed @ rz180()[:3, :3].T + rz180()[:3, 3][None, :]
    scene = build_scene(target.mesh, surface_tag=target.surface_tag,
                        face_id=target.face_id, name=target.fragment_id)
    render = render_view(scene, rframe, light=spec.resolved_light(), spec=spec.render_spec,
                         object_pose=pose,
                         focus_distance_mm=rframe.working_distance_mm,
                         backend=BACKEND_BLENDER,
                         blender_config=BlenderBackendConfig(samples=8, filter_width=1.5,
                                                             f_number=2.2, previews=False,
                                                             raycast_samples=400,
                                                             run_label="debug_flip"))
    result = {
        "view_id": frame.view_id,
        "backend": render.backend,
        "as_project_builds_it": compare(render.depth_z, rframe.K, rframe.T_WC, posed, faces,
                                        render.uncertain_mask),
        "rotated_180_about_world_Z": compare(render.depth_z, rframe.K, rframe.T_WC, flipped,
                                             faces, render.uncertain_mask),
        "manifest_checks": {
            "raycast_vs_exact_pass": (render.meta.get("checks") or {}).get(
                "raycast_vs_exact_pass"),
            "camera_model": (render.meta.get("checks") or {}).get("camera_model"),
            "face_order": (render.meta.get("checks") or {}).get("face_order"),
        },
        "manifest_path": render.meta.get("manifest_path"),
    }
    (Path(__file__).with_name("debug_flip.json")).write_text(
        json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(json.dumps(result, indent=2, default=str)[:4000], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
