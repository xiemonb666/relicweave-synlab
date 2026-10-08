"""Scratch: debug the photometric-stereo solve inputs."""
from __future__ import annotations

import sys

import numpy as np
import trimesh

sys.stdout.reconfigure(encoding="utf-8")

import synlab.observe.synthetic_extras as se
from synlab.observe.render import BACKEND_SOFTWARE, LightSpec, build_scene, render_view
from synlab.observe.routes import ObsSpec, resolve_target

m = trimesh.creation.box(extents=(120.0, 100.0, 40.0))
n = len(m.faces)
m.metadata["face_attr_arrays"] = {
    "origin_kind": np.full(n, 1, dtype=np.uint8),
    "interface_id": np.where(np.arange(n) % 3 == 0, 0, -1).astype(np.int32),
}
t = resolve_target({"mesh": m, "fragment_id": "F001", "component_id": "C001"})
p = se.resolve_profile("MID")
size = se._extras_size(p, 48)
fr = se._turntable_frame(view_id="v", profile=p, size=size,
                        center=se._bbox_center(t.bbox))
spec = ObsSpec()
scene = build_scene(t.mesh, surface_tag=t.surface_tag, face_id=t.face_id)

center = se._bbox_center(t.bbox)
R = np.asarray(fr.T_WC[:3, :3])
C = np.asarray(fr.T_WC[:3, 3])
center_cam = R.T @ (center - C)
print("center_cam", center_cam)
imgs = []
dirs = []
for name, position in se._PS_LIGHT_POSITIONS:
    pos = np.asarray(position, float)
    pos = pos / np.linalg.norm(pos)
    pos_cam = R.T @ (center + pos * p.working_distance_mm - C)
    travel = center_cam - pos_cam
    travel = travel / np.linalg.norm(travel)
    light = LightSpec(direction=travel, color=np.array([2.4, 2.4, 2.4]),
                      ambient=np.zeros(3))
    out = render_view(scene, fr, light=light, spec=spec.render_spec,
                      backend=BACKEND_SOFTWARE)
    img = np.asarray(out.rgb_linear, dtype=np.float32)
    imgs.append(img)
    dirs.append(travel)
    visible = np.isfinite(out.depth_z)
    print(f"{name:<10} travel={np.round(travel,3).tolist()} "
          f"mean={float(img[visible].mean()) if visible.any() else float('nan'):.4f} "
          f"max={float(img.max()):.4f} visible={int(visible.sum())}")

stack = np.stack(imgs, 0)
depth = np.asarray(out.depth_z, float)
mask = np.isfinite(depth) & (depth > 0)
print("mask pixels", int(mask.sum()))
sol = se.solve_photometric_normals(stack, np.stack(dirs, 0), mask)
print("ps_valid", int(sol["ps_valid"].sum()),
      "obs histogram", np.bincount(sol["ps_observations"].ravel()).tolist())
print("ps_albedo max", float(sol["ps_albedo"].max()))
if sol["ps_valid"].any():
    print("ps_normal sample", np.round(sol["ps_normal"][sol["ps_valid"]][:3], 3).tolist())
