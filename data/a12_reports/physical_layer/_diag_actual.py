"""A4 diagnostic 4: what perturbation does the renderer ACTUALLY apply?

Replays the renderer's own inner loop (frame -> hit points -> tu/tv projection -> n_px) and stores
the perturbation vector, then compares it with the field's analytic gradient at the same points.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests/a12/observe"))

from _run_fracture_appearance import (MASTER_SEED, SPECIMEN, material_profile,  # noqa: E402
                                      mm_per_px_of, patch_faces)
from _run_fracture_roi import load_target  # noqa: E402
from synlab.cameras.profiles import camera_profiles  # noqa: E402
from synlab.observe import fracture_appearance as fa  # noqa: E402
from synlab.observe import fracture_roi as fr  # noqa: E402
from synlab.observe import routes as rt  # noqa: E402
from synlab.observe.render import build_scene  # noqa: E402
from synlab.seeds import make_rng  # noqa: E402

target, body = load_target(SPECIMEN)
mesh = target.mesh
roi_config = fr.load_fracture_roi_config()
base = {p.tier: p for p in camera_profiles()}["LOCAL"]
closeup = fr.closeup_profile(roi_config, base=base, delivered_long_edge_px=1024)
fp = fr.mm_per_px(working_distance_mm=60.0, f_px=float(closeup.K[0, 0])) * 512.0
roi = max(fr.fracture_rois(target, roi_config, footprint_radius_mm=fp),
          key=lambda r: -(np.asarray(r.normal) @ fa.frozen_light().direction))
faces = patch_faces(mesh, roi.interface_id)
tris = np.asarray(mesh.faces)[faces]
spec = rt.ObsSpec(view_count=1, delivered_size=(1024, 768), max_render_pixels=1024 * 1024,
                  master_seed=MASTER_SEED, lineage_id="diag", frame_id="S_mm",
                  renderer=rt.RENDERER_AUTO, distortion_policy=rt.DISTORTION_POLICY_IGNORE)
frame = fr.make_fracture_roi_frames(rois=[roi], profile=closeup, spec=spec, config=roi_config,
                                    long_edge_px=1024,
                                    rng=make_rng(MASTER_SEED, "appearance_frame", roi.roi_id),
                                    run_id="diag", mesh=mesh)[0]
profile = material_profile(body["material_id"])
light = fa.frozen_light()
RA = 0.08
field = fa.build_relief_field(profile=profile, roi=roi, patch_vertices=mesh.vertices,
                              patch_triangles=tris, mesh=mesh,
                              rng=make_rng(MASTER_SEED, "appearance_field", body["material_id"]),
                              amplitude_mm=RA)
scene = build_scene(mesh, surface_tag=target.surface_tag, face_id=target.face_id)
ss = 1
app = fa.AppearanceSpec(normal_mode="FLAT", relief=True, interpolation="PERSPECTIVE_CORRECT")
W, H = int(frame.image_size[0]), int(frame.image_size[1])
buf = fa._rasterise_appearance(scene, fa._scaled_frame(frame, ss), W * ss, H * ss, light, app,
                               field, fa.RenderSpec(supersample=1, max_pixels=8_000_000))
print("rasteriser done; hit px", int(np.isfinite(buf["depth"]).sum()))
# the rasteriser passes its buffers by reference, so take a snapshot to compare against afterwards
ref_depth = np.array(buf["depth"], dtype=np.float64, copy=True)
ref_id = np.array(buf["id"], dtype=np.int32, copy=True)
work_depth = np.full_like(ref_depth, np.inf)

# replay the inner loop to capture points and the perturbation actually applied
T_CW = frame.T_CW
R_ = T_CW[:3, :3]
t_ = T_CW[:3, 3]
world_v = np.asarray(scene.vertices, dtype=np.float64)
verts = world_v @ R_.T + t_[None, :]
from synlab.cameras.projection import distort_normalized  # noqa: E402

z = verts[:, 2]
safe = np.where(np.abs(z) > 1e-12, z, np.nan)
xd, yd = distort_normalized(verts[:, 0] / safe, verts[:, 1] / safe, frame.dist,
                            frame.camera_model or "PINHOLE")
K = frame.K
uvv = np.stack([K[0, 0] * xd + K[0, 1] * yd + K[0, 2],
                K[1, 0] * xd + K[1, 1] * yd + K[1, 2]], axis=1)
ff = scene.faces
p0, p1, p2 = uvv[ff[:, 0]], uvv[ff[:, 1]], uvv[ff[:, 2]]
z0, z1, z2 = z[ff[:, 0]], z[ff[:, 1]], z[ff[:, 2]]
area = (p1[:, 0] - p0[:, 0]) * (p2[:, 1] - p0[:, 1]) - (p2[:, 0] - p0[:, 0]) * (p1[:, 1] - p0[:, 1])
cam0, cam1, cam2 = verts[ff[:, 0]], verts[ff[:, 1]], verts[ff[:, 2]]
face_n = np.cross(cam1 - cam0, cam2 - cam0)
visible = ((z0 > 1.0) & (z1 > 1.0) & (z2 > 1.0) & (face_n[:, 2] < 0.0)
           & np.isfinite(area) & (np.abs(area) > 1e-12))
R_WC = R_
cam_normals = face_n / np.maximum(np.linalg.norm(face_n, axis=1, keepdims=True), 1e-30)
world_normals = cam_normals @ R_WC
t_u, t_v = field.u_axis, field.v_axis

rec_px, rec_pred, rec_nbase, rec_id = [], [], [], []
for fi in np.nonzero(visible)[0]:
    f = int(fi)
    xs_ = (p0[f, 0], p1[f, 0], p2[f, 0])
    ys_ = (p0[f, 1], p1[f, 1], p2[f, 1])
    xmin = max(int(np.floor(min(xs_))), 0)
    xmax = min(int(np.ceil(max(xs_))), W - 1)
    ymin = max(int(np.floor(min(ys_))), 0)
    ymax = min(int(np.ceil(max(ys_))), H - 1)
    if xmax < xmin or ymax < ymin:
        continue
    gx = np.arange(xmin, xmax + 1, dtype=np.float64) + 0.5
    gy = np.arange(ymin, ymax + 1, dtype=np.float64) + 0.5
    px, py = gx[None, :], gy[:, None]
    ax, ay, bx, by, cx, cy = (p0[f, 0], p0[f, 1], p1[f, 0], p1[f, 1], p2[f, 0], p2[f, 1])
    inv = 1.0 / area[f]
    w0 = ((bx - px) * (cy - py) - (cx - px) * (by - py)) * inv
    w1 = ((cx - px) * (ay - py) - (ax - px) * (cy - py)) * inv
    w2 = 1.0 - w0 - w1
    inside = (w0 >= -1e-9) & (w1 >= -1e-9) & (w2 >= -1e-9)
    zi = w0 * z0[f] + w1 * z1[f] + w2 * z2[f]
    better = inside & (zi < work_depth[ymin:ymax + 1, xmin:xmax + 1])
    if not better.any():
        continue
    work_depth[ymin:ymax + 1, xmin:xmax + 1][better] = zi[better]
    rows, cols = np.nonzero(better)
    ww0, ww1, ww2 = w0[rows, cols], w1[rows, cols], w2[rows, cols]
    fv = ff[f]
    pts = ww0[:, None] * world_v[fv[0]] + ww1[:, None] * world_v[fv[1]] + ww2[:, None] * world_v[fv[2]]
    _, gu, gv = field.sample(pts, scale=field.amplitude_scale)
    nb = world_normals[f]
    tu = t_u[None, :] - (pts @ t_u)[:, None] * nb[None, :]
    tu = tu / np.maximum(np.linalg.norm(tu, axis=1, keepdims=True), 1e-30)
    tv = t_v[None, :] - (pts @ t_v)[:, None] * nb[None, :]
    tv = tv / np.maximum(np.linalg.norm(tv, axis=1, keepdims=True), 1e-30)
    pert = gu[:, None] * tu + gv[:, None] * tv
    rec_px.append(pts)
    rec_pred.append(np.hstack([gu[:, None], gv[:, None]]))
    rec_nbase.append(np.repeat(nb[None, :], pts.shape[0], axis=0))
    rec_id.append(np.full(pts.shape[0], f))
pts = np.vstack(rec_px)
grad = np.vstack(rec_pred)
nbase = np.vstack(rec_nbase)
fid = np.concatenate(rec_id)
ty, tx = np.nonzero(np.isfinite(ref_depth))
print("replayed px", pts.shape[0], "depth px", ty.size)
# exact z-fights make the replay's winning set differ by ~0.5% of pixels; the comparison below is
# on the replay's own points, and a 0.5% set difference cannot move an RMS by any factor.

uu, vv = field.uv(pts)
r = np.hypot(uu, vv)
core = r <= field.footprint_radius_mm - field.ramp_width_mm
print("core frac", round(float(core.mean()), 5))
slope = np.hypot(grad[:, 0], grad[:, 1])
print("analytic |grad| rms on these points", round(float(np.sqrt(np.mean(slope ** 2))), 5),
      "p95", round(float(np.percentile(slope, 95)), 5))
a_u = float(np.dot(field.u_axis, light.direction))
a_v = float(np.dot(field.v_axis, light.direction))
d_lin = grad[:, 0] * a_u + grad[:, 1] * a_v
print("linearised d_lambert rms (linear)", round(float(np.sqrt(np.mean(d_lin ** 2))), 6))
# full expression with tangent renormalisation + normal normalisation
n_px = nbase - grad[:, 0:1] * (field.u_axis - (nbase @ field.u_axis)[:, None] * nbase) \
    - grad[:, 1:2] * (field.v_axis - (nbase @ field.v_axis)[:, None] * nbase)
n_px = n_px / np.linalg.norm(n_px, axis=1, keepdims=True)
n0 = nbase / np.linalg.norm(nbase, axis=1, keepdims=True)
d_lam_full = -(n_px - n0) @ light.direction
print("exact d_lambert rms (renormalised)", round(float(np.sqrt(np.mean(d_lam_full ** 2))), 6))
print("ratio exact/linear", round(float(np.sqrt(np.mean(d_lam_full ** 2))
                                        / np.sqrt(np.mean(d_lin ** 2))), 5))
# how oblique is the plane, in terms of |t_u . n| etc
print("mean |t_u . n_base|", round(float(np.mean(np.abs(n0 @ field.u_axis))), 5),
      "mean |t_v . n_base|", round(float(np.mean(np.abs(n0 @ field.v_axis))), 5))
print("mean |t_u projected|", round(float(np.mean(np.linalg.norm(
    field.u_axis[None, :] - (n0 @ field.u_axis)[:, None] * n0, axis=1))), 5))
alb = np.asarray(field.parameters.albedo, dtype=np.float64)
fac = 255.0 * float(np.mean(alb * np.asarray(light.color)))
print("dDN factor", round(fac, 4))
print("predicted dDN (linear)", round(fac * float(np.sqrt(np.mean(d_lin ** 2))), 4))
print("predicted dDN (exact) ", round(fac * float(np.sqrt(np.mean(d_lam_full ** 2))), 4))
