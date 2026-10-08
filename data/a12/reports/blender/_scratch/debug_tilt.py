"""Scratch: decide whether the tilted-box depth disagreement is a reference bug or real.

Three independent values per sampled pixel:
  * analytic plane ray-plane intersection from the triangle's 3 vertices,
  * the software rasteriser depth,
  * the Blender exact Z pass.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import trimesh

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synlab.observe.blender import BlenderBackendConfig          # noqa: E402
from synlab.observe.render import BACKEND_BLENDER, RenderSpec, build_scene  # noqa: E402
from synlab.observe.routes import ObsSpec, render_view           # noqa: E402
from synlab.schemas.runtime import ViewFrame                     # noqa: E402

SIZE = (1024, 768)
FX = 1200.0
CAM_Z = -400.0


def plane_z(K, T_WC, tri: np.ndarray, pixels: np.ndarray) -> np.ndarray:
    """Ray-plane intersection z for the plane of ``tri`` (3x3 world mm)."""
    n = np.cross(tri[1] - tri[0], tri[2] - tri[0])
    n = n / np.linalg.norm(n)
    d = -float(n @ tri[0])
    R, C = T_WC[:3, :3], T_WC[:3, 3]
    dirs = []
    for u, v in pixels:
        d_cam = np.array([(u - K[0, 2]) / K[0, 0], (v - K[1, 2]) / K[1, 1], 1.0])
        dirs.append(R @ d_cam)
    dirs = np.asarray(dirs)
    t = -(float(n @ C) + d) / (dirs @ n)
    return t  # t is the camera z because d_cam has z = 1


def main() -> int:
    box = trimesh.creation.box(extents=(100.0, 100.0, 100.0))
    box.apply_transform(trimesh.transformations.rotation_matrix(np.deg2rad(45.0),
                                                               [0, 0, 1]))
    box.apply_transform(trimesh.transformations.rotation_matrix(np.deg2rad(20.0),
                                                               [1, 0, 0]))
    verts = np.asarray(box.vertices)
    faces = np.asarray(box.faces)
    scene = build_scene(box, surface_tag=np.zeros(faces.shape[0], dtype=np.int16),
                        face_id=np.arange(faces.shape[0]), name="tilt")
    K = np.array([[FX, 0.0, (SIZE[0] - 1) / 2.0], [0.0, FX, (SIZE[1] - 1) / 2.0],
                  [0.0, 0.0, 1.0]])
    T_WC = np.eye(4)
    T_WC[2, 3] = CAM_Z
    frame = ViewFrame(view_id="tilt", K=K, T_WC=T_WC, image_size=SIZE, profile_id="fx",
                      tier="GLOBAL", u_position_mm=0.0, working_distance_mm=abs(CAM_Z),
                      focus_setting="FIXED", source_kind="SENSOR_SIM",
                      camera_model="PINHOLE", dist=None)
    light = ObsSpec().resolved_light()
    sw = render_view(scene, frame, light=light, spec=RenderSpec(supersample=1),
                     focus_distance_mm=abs(CAM_Z), backend="SOFTWARE_RASTERIZER")
    bl = render_view(scene, frame, light=light, spec=RenderSpec(),
                     focus_distance_mm=abs(CAM_Z), backend=BACKEND_BLENDER,
                     blender_config=BlenderBackendConfig(samples=4, filter_width=1.5,
                                                         f_number=8.0, previews=False,
                                                         raycast_samples=100,
                                                         run_label="debug_tilt"))
    print("sw backend", sw.backend, "bl backend", bl.backend)
    # pick interior pixels of the two largest faces via a dense ray cast of the reference
    from render_1024_12 import cast_rays  # noqa: E402  (scratch dir on sys.path)

    cast = cast_rays(K, T_WC, verts, faces, SIZE, 1)
    face_grid = np.full((SIZE[1], SIZE[0]), -1, dtype=np.int64)
    face_grid[cast["y"], cast["x"]] = cast["face"]
    counts = {int(f): int((face_grid == f).sum()) for f in np.unique(face_grid) if f >= 0}
    top = sorted(counts, key=lambda f: -counts[f])[:4]
    print("face pixel counts", {f: counts[f] for f in top})
    for f in top:
        ys, xs = np.nonzero(face_grid == f)
        take = np.linspace(0, ys.size - 1, 5).astype(int)
        pix = np.stack([xs[take] + 0.5, ys[take] + 0.5], axis=1)
        pz = plane_z(K, T_WC, verts[faces[f]], pix)
        print(f"face {f}: verts z {verts[faces[f]][:, 2].round(2)}")
        for k in range(pix.shape[0]):
            x = int(pix[k, 0] - 0.5)
            y = int(pix[k, 1] - 0.5)
            print(f"   px({x},{y}) analytic_plane_z={pz[k]:9.3f} "
                  f"raycast_z={cast['z_mm'][(cast['y'] == y) & (cast['x'] == x)][0]:9.3f} "
                  f"software_z={sw.depth_z[y, x]:9.3f} blender_z={bl.depth_z[y, x]:9.3f} "
                  f"bl_id={bl.id_map[y, x]} sw_id={sw.id_map[y, x]} face={f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
