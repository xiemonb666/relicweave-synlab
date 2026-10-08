"""Focused diagnostic: where does the predicted relief dDN go?"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests/a12/observe"))

from _run_fracture_appearance import (MASTER_SEED, SPECIMEN, material_profile, patch_faces,
                                      render_and_image, pick_roi)  # noqa: E402
from _run_fracture_roi import load_target  # noqa: E402
from synlab.cameras.profiles import camera_profiles  # noqa: E402
from synlab.observe import fracture_appearance as fa  # noqa: E402
from synlab.observe.render import MaterialSpec  # noqa: E402
from synlab.observe import fracture_roi as fr  # noqa: E402
from synlab.observe import routes as rt  # noqa: E402
from synlab.seeds import make_rng  # noqa: E402

target, body = load_target(SPECIMEN)
mesh = target.mesh
roi_config = fr.load_fracture_roi_config()
base = {p.tier: p for p in camera_profiles()}["LOCAL"]
closeup = fr.closeup_profile(roi_config, base=base, delivered_long_edge_px=1024)
fp = fr.mm_per_px(working_distance_mm=60.0, f_px=float(closeup.K[0, 0])) * 512.0
roi = pick_roi(fr.fracture_rois(target, roi_config, footprint_radius_mm=fp))
faces = patch_faces(mesh, roi.interface_id)
tris = np.asarray(mesh.faces)[faces]
spec = rt.ObsSpec(view_count=1, delivered_size=(1024, 768), max_render_pixels=1024 * 1024,
                  master_seed=MASTER_SEED, lineage_id="diag", frame_id="S_mm",
                  renderer=rt.RENDERER_AUTO, distortion_policy=rt.DISTORTION_POLICY_IGNORE)
frame = fr.make_fracture_roi_frames(rois=[roi], profile=closeup, spec=spec, config=roi_config,
                                    long_edge_px=1024, rng=make_rng(MASTER_SEED, "appearance_frame",
                                                                    roi.roi_id),
                                    run_id="diag", mesh=mesh)[0]
profile = material_profile(body["material_id"])
field = fa.build_relief_field(profile=profile, roi=roi, patch_vertices=mesh.vertices,
                              patch_triangles=tris, mesh=mesh,
                              rng=make_rng(MASTER_SEED, "appearance_field", body["material_id"]),
                              amplitude_mm=0.4)
light = fa.frozen_light()
T = frame.T_WC

off = render_and_image(target=target, frame=frame,
                       appearance=fa.AppearanceSpec(normal_mode="FLAT", relief=False,
                                                    interpolation="PERSPECTIVE_CORRECT"),
                       relief=None, obs_spec=spec, imaging_seed=11, supersample=1)
on = render_and_image(target=target, frame=frame,
                      appearance=fa.AppearanceSpec(normal_mode="FLAT", relief=True,
                                                   interpolation="PERSPECTIVE_CORRECT"),
                      relief=field, obs_spec=spec, imaging_seed=11, supersample=1)
m = off["mask"]
d = (on["dn_float"] - off["dn_float"])[m]
print("mask px", int(m.sum()))
print("dDN_float rms", round(float(np.sqrt((d ** 2).mean())), 4),
      "mean|d|", round(float(np.abs(d).mean()), 4),
      "nonzero frac", round(float((np.abs(d) > 1e-9).mean()), 4),
      "abs>0.5 frac", round(float((np.abs(d) > 0.5).mean()), 4),
      "max", round(float(np.abs(d).max()), 2))
# the shading of the off render in linear terms
lin_off = np.asarray(off["imaging"].linear, dtype=np.float64).mean(axis=2)
alb = np.asarray(field.parameters.albedo)
print("albedo", alb, "mean", round(float(alb.mean()), 4))
val = lin_off[m]
print("shading linear p05/p50/p95", [round(float(np.percentile(val, q)), 4) for q in (5, 50, 95)])
# implied lambert: linear = albedo_mean*(ambient_mean + color_mean*L)
amb = float(np.mean(light.ambient)); col = float(np.mean(light.color))
L = (val / float(alb.mean()) - amb) / col
print("implied lambert p05/p50/p95", [round(float(np.percentile(L, q)), 4) for q in (5, 50, 95)],
      "frac clipped at 0", round(float((L <= 1e-6).mean()), 4),
      "frac clipped at 1", round(float((L >= 1 - 1e-6).mean()), 4))
# relief perturbation the renderer should have applied
lin_on = np.asarray(on["imaging"].linear, dtype=np.float64).mean(axis=2)
# recover hit points with a tiny rasterisation of the same frame (reuse the module's rasteriser)
scene = fa.Scene(name="t", vertices=np.asarray(mesh.vertices, dtype=np.float64),
                 faces=np.asarray(mesh.faces, dtype=np.int32),
                 surface_tag=np.asarray(target.surface_tag, dtype=np.int16),
                 material=MaterialSpec(np.tile(np.array([0.5, 0.5, 0.5], np.float32),
                                                  (np.asarray(mesh.faces).shape[0], 1)),
                                          np.full(np.asarray(mesh.faces).shape[0], 0.5,
                                                  np.float32)))
buf = fa._rasterise_appearance(scene, fa._scaled_frame(frame, 1), 1024, 768, light,
                               fa.AppearanceSpec(normal_mode="FLAT", relief=False), None, spec)
# per-pixel world position via the same loop is not exposed; approximate the gradient at the
# aim plane instead: sample the field on the ROI plane and report its slope statistics
uu, vv = np.meshgrid(np.arange(-37.0, 37.0, 0.5), np.arange(-28.0, 28.0, 0.5), indexing="ij")
h, gu, gv = field.sample(field.origin_mm[None, :] + uu.ravel()[:, None] * field.u_axis[None, :]
                         + vv.ravel()[:, None] * field.v_axis[None, :])
slope = np.hypot(gu, gv)
print("plane slope rms", round(float(np.sqrt((slope ** 2).mean())), 5),
      "p95", round(float(np.percentile(slope, 95)), 5),
      "h rms", round(float(np.sqrt((h ** 2).mean())), 5))
perp = float(np.sqrt(max(0.0, 1.0 - float(light.direction[2]) ** 2)))
print("light perp (camera-frame formula)", round(perp, 4))
pred = 255.0 * float(np.mean(alb * np.asarray(light.color))) * perp \
    * float(np.sqrt((slope ** 2).mean()))
print("predicted dDN from the plane slope", round(pred, 4))
print("ratio measured/predicted", round(float(np.sqrt((d ** 2).mean())) / max(pred, 1e-9), 4))

