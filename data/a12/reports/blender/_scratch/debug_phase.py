"""Scratch: measure the sampling *phase* of the Blender depth pass vs the rasteriser.

On a planar, slanted face the camera z is a linear function of the pixel coordinate, so the
phase that minimises |render - ray(phase)| is the phase the renderer actually samples.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import trimesh

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from render_1024_12 import cast_rays                                # noqa: E402
from synlab.observe.blender import BlenderBackendConfig             # noqa: E402
from synlab.observe.render import BACKEND_BLENDER, RenderSpec, build_scene  # noqa: E402
from synlab.observe.routes import ObsSpec, render_view              # noqa: E402
from synlab.schemas.runtime import ViewFrame                        # noqa: E402

SIZE = (1024, 768)
FX = 1200.0
CAM_Z = -400.0
PHASES = [(0.5, 0.5), (0.0, 0.0), (1.0, 1.0), (0.0, 0.5), (0.5, 0.0), (1.0, 0.5), (0.5, 1.0)]


def cast_at(K, T_WC, verts, faces, phase) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Face-interior pixel list + reference z for a given sampling phase."""
    # shift the principal point by (phase - 0.5 px) so that index i maps to i + phase
    K2 = np.array(K, dtype=np.float64).copy()
    K2[0, 2] += phase[0] - 0.5
    K2[1, 2] += phase[1] - 0.5
    cast = cast_rays(K2, T_WC, verts, faces, SIZE, 1)
    face_grid = np.full((SIZE[1], SIZE[0]), -1, dtype=np.int64)
    face_grid[cast["y"], cast["x"]] = cast["face"]
    same = np.ones_like(face_grid, dtype=bool)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            same &= (np.roll(np.roll(face_grid, -dy, axis=0), -dx, axis=1) == face_grid)
    interior = same & (face_grid >= 0)
    return interior, cast["y"], cast["x"], cast["z_mm"]


def main() -> int:
    box = trimesh.creation.box(extents=(100.0, 100.0, 100.0))
    box.apply_transform(trimesh.transformations.rotation_matrix(np.deg2rad(45.0), [0, 0, 1]))
    box.apply_transform(trimesh.transformations.rotation_matrix(np.deg2rad(20.0), [1, 0, 0]))
    verts = np.asarray(box.vertices, dtype=np.float64)
    faces = np.asarray(box.faces, dtype=np.int64)
    scene = build_scene(box, surface_tag=np.zeros(faces.shape[0], dtype=np.int16),
                        face_id=np.arange(faces.shape[0]), name="phase")
    K = np.array([[FX, 0.0, (SIZE[0] - 1) / 2.0], [0.0, FX, (SIZE[1] - 1) / 2.0],
                  [0.0, 0.0, 1.0]])
    T_WC = np.eye(4)
    T_WC[2, 3] = CAM_Z
    frame = ViewFrame(view_id="phase", K=K, T_WC=T_WC, image_size=SIZE, profile_id="fx",
                      tier="GLOBAL", u_position_mm=0.0, working_distance_mm=abs(CAM_Z),
                      focus_setting="FIXED", source_kind="SENSOR_SIM",
                      camera_model="PINHOLE", dist=None)
    light = ObsSpec().resolved_light()
    identity = np.eye(4)
    sw = render_view(scene, frame, light=light, spec=RenderSpec(supersample=1),
                     object_pose=identity, focus_distance_mm=abs(CAM_Z),
                     backend="SOFTWARE_RASTERIZER")
    bl = render_view(scene, frame, light=light, spec=RenderSpec(), object_pose=identity,
                     focus_distance_mm=abs(CAM_Z), backend=BACKEND_BLENDER,
                     blender_config=BlenderBackendConfig(samples=8, filter_width=1.5,
                                                         f_number=8.0, previews=False,
                                                         raycast_samples=200,
                                                         run_label="debug_phase"))
    results: dict[str, object] = {"backends": {}}
    for tag, render in (("software", sw), ("blender", bl)):
        depth = np.asarray(render.depth_z, dtype=np.float64)
        rows = []
        for phase in PHASES:
            interior, ys, xs, zref = cast_at(K, T_WC, verts, faces, phase)
            sel = interior[ys, xs] & np.isfinite(zref) & np.isfinite(depth[ys, xs])
            if not sel.any():
                continue
            delta = np.abs(depth[ys, xs][sel] - zref[sel])
            rows.append({"phase": list(phase), "n": int(sel.sum()),
                         "median_mm": float(np.median(delta)),
                         "mean_mm": float(delta.mean()), "max_mm": float(delta.max())})
        rows.sort(key=lambda r: r["mean_mm"])
        results["backends"][tag] = {"by_phase": rows, "best": rows[0] if rows else None,
                                   "backend": render.backend}
        print(tag, json.dumps(rows), flush=True)
    Path(__file__).with_name("debug_phase.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
