"""A4 diagnostic 12 (EXACT): re-evaluate the frozen shading from the field at the points the
renderer itself shaded, using the renderer's own depth buffer and pixel coordinates."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests/a12/observe"))

from _run_fracture_appearance import (MASTER_SEED, SPECIMEN, material_profile,  # noqa: E402
                                      mm_per_px_of, patch_faces, render_and_image)
from _run_fracture_roi import load_target  # noqa: E402
from synlab.cameras.profiles import camera_profiles  # noqa: E402
from synlab.cameras.projection import unproject  # noqa: E402
from synlab.observe import fracture_appearance as fa  # noqa: E402
from synlab.observe import fracture_roi as fr  # noqa: E402
from synlab.observe import routes as rt  # noqa: E402
from synlab.observe.render import procedural_albedo  # noqa: E402
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
                  master_seed=MASTER_SEED, lineage_id="d", frame_id="S_mm",
                  renderer=rt.RENDERER_AUTO, distortion_policy=rt.DISTORTION_POLICY_IGNORE)
frame = fr.make_fracture_roi_frames(rois=[roi], profile=closeup, spec=spec, config=roi_config,
                                    long_edge_px=1024,
                                    rng=make_rng(MASTER_SEED, "appearance_frame", roi.roi_id),
                                    run_id="d", mesh=mesh)[0]
profile = material_profile(body["material_id"])
light = fa.frozen_light()
field = fa.build_relief_field(profile=profile, roi=roi, patch_vertices=mesh.vertices,
                              patch_triangles=tris, mesh=mesh,
                              rng=make_rng(MASTER_SEED, "appearance_field", body["material_id"]),
                              amplitude_mm=0.08)
off = render_and_image(target=target, frame=frame,
                       appearance=fa.AppearanceSpec(normal_mode="FLAT", relief=False,
                                                    interpolation="PERSPECTIVE_CORRECT"),
                       relief=None, obs_spec=spec, imaging_seed=11, supersample=1)
on = render_and_image(target=target, frame=frame,
                      appearance=fa.AppearanceSpec(normal_mode="FLAT", relief=True,
                                                   interpolation="PERSPECTIVE_CORRECT"),
                      relief=field, obs_spec=spec, imaging_seed=11, supersample=1)
mask = np.asarray(off["mask"], dtype=bool)
depth = np.asarray(off["render"].depth_z, dtype=np.float64)
idm = np.asarray(off["render"].id_map)
ys, xs = np.nonzero(mask & np.isfinite(depth))
world = unproject(np.stack([xs + 0.5, ys + 0.5], axis=1), depth[ys, xs],
                  np.asarray(frame.K, dtype=np.float64), np.asarray(frame.T_WC, dtype=np.float64),
                  np.asarray(frame.dist, dtype=np.float64), model=frame.camera_model or "PINHOLE")
fn = fa.face_normals(np.asarray(mesh.vertices), np.asarray(mesh.faces))
n0 = fn[np.clip(idm[ys, xs], 0, fn.shape[0] - 1)]
n0 = n0 / np.linalg.norm(n0, axis=1, keepdims=True)

_, gu1, gv1 = field.sample(world, scale=1.0)
s = float(field.amplitude_scale)
tu = field.u_axis[None, :] - (n0 @ field.u_axis)[:, None] * n0
tu = tu / np.linalg.norm(tu, axis=1, keepdims=True)
tv = field.v_axis[None, :] - (n0 @ field.v_axis)[:, None] * n0
tv = tv / np.linalg.norm(tv, axis=1, keepdims=True)
pert = (s * gu1)[:, None] * tu + (s * gv1)[:, None] * tv
print("in-plane |pert| rms      ", round(float(np.sqrt(np.mean(np.linalg.norm(pert, axis=1) ** 2))), 6))
print("(unnormalised) d_lambert rms", round(float(np.sqrt(np.mean((pert @ light.direction) ** 2))), 6))
n_pred = n0 - pert
n_pred = n_pred / np.linalg.norm(n_pred, axis=1, keepdims=True)
pred_lam = -(n_pred @ light.direction)
print("(exact)       d_lambert rms", round(float(np.sqrt(np.mean(
    (pred_lam - (-(n0 @ light.direction))) ** 2))), 6))
# the render's own d_lambert, per channel, with the SCENE's palette albedo
lab = procedural_albedo(np.asarray(mesh.faces).shape[0], seed=0x5EED)
alb_px = lab[np.clip(idm, 0, lab.shape[0] - 1)][ys, xs]
rgb_o = np.asarray(off["render"].rgb_linear, dtype=np.float64)[ys, xs]
rgb_n = np.asarray(on["render"].rgb_linear, dtype=np.float64)[ys, xs]
d_lam_render = ((rgb_n - rgb_o) / np.maximum(alb_px, 1e-6)
                / np.asarray(light.color)[None, :]).mean(axis=1)
print("render        d_lambert rms", round(float(np.sqrt(np.mean(d_lam_render ** 2))), 6))
print("ratio render/pred          ", round(float(np.sqrt(np.mean(d_lam_render ** 2))
                                                / np.sqrt(np.mean((pred_lam - (-(n0 @ light.direction)))
                                                                  ** 2))), 5))
print("corr(render, pred)         ", round(float(np.corrcoef(d_lam_render,
                                                             pred_lam - (-(n0 @ light.direction)))[0, 1]), 5))
# the same with the MATERIAL albedo (what the current prediction assumes)
alb_mat = np.asarray(profile["appearance"]["albedo"], dtype=np.float64)
d_lam_mat = ((rgb_n - rgb_o) / alb_mat[None, :] / np.asarray(light.color)[None, :]).mean(axis=1)
print("render d_lambert rms (material albedo)", round(float(np.sqrt(np.mean(d_lam_mat ** 2))), 6))
print("palette albedo mean per channel", np.round(alb_px.mean(axis=0), 5),
      " material albedo", np.round(alb_mat, 5))
print("factor alpha*color mean: palette", round(255.0 * float(np.mean(alb_px.mean(axis=0)
                                                                     * np.asarray(light.color))), 3),
      " material", round(255.0 * float(np.mean(alb_mat * np.asarray(light.color))), 3))
print("measured dDN (imaging chain)",
      round(float(fa.difference_dn_statistics(on["dn_float"], off["dn_float"], mask)["dDN_rms"]), 4))
print("dDN implied by render rgb_linear",
      round(float(np.sqrt(np.mean((255.0 * (rgb_n - rgb_o).mean(axis=1)) ** 2))), 4))
