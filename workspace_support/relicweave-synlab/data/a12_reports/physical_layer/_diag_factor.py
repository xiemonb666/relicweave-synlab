"""A4 diagnostic 11: where does the dDN factor come from?  Recover lambert from the render itself."""
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
from synlab.observe import fracture_appearance as fa  # noqa: E402
from synlab.observe import fracture_roi as fr  # noqa: E402
from synlab.observe import routes as rt  # noqa: E402
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
spec = rt.ObsSpec(view_count=1, delivered_size=(1024, 768), max_render_pixels=1024 * 1024,
                  master_seed=MASTER_SEED, lineage_id="diag", frame_id="S_mm",
                  renderer=rt.RENDERER_AUTO, distortion_policy=rt.DISTORTION_POLICY_IGNORE)
frame = fr.make_fracture_roi_frames(rois=[roi], profile=closeup, spec=spec, config=roi_config,
                                    long_edge_px=1024,
                                    rng=make_rng(MASTER_SEED, "appearance_frame", roi.roi_id),
                                    run_id="diag", mesh=mesh)[0]
profile = material_profile(body["material_id"])
light = fa.frozen_light()
alb = np.asarray(profile["appearance"]["albedo"], dtype=np.float64)
col = np.asarray(light.color, dtype=np.float64)
amb = np.asarray(light.ambient, dtype=np.float64)
print("albedo", alb, "color", col, "ambient", amb)
print("mean_c(alb*col)", round(float(np.mean(alb * col)), 5),
      " mean(alb)*mean(col)", round(float(alb.mean() * col.mean()), 5))
field = fa.build_relief_field(profile=profile, roi=roi, patch_vertices=mesh.vertices,
                              patch_triangles=np.asarray(mesh.faces)[faces], mesh=mesh,
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

# --- the renderer's own rgb_linear, per channel
rgb_off = np.asarray(off["render"].rgb_linear, dtype=np.float64)
rgb_on = np.asarray(on["render"].rgb_linear, dtype=np.float64)
print("rgb_off mean per channel", np.round(rgb_off[mask].mean(axis=0), 6))
# recover lambert per channel and average over channels (they must agree)
lam_c = (rgb_off / alb[None, None, :] - amb[None, None, :]) / col[None, None, :]
print("lambert from the render, per channel p05/p50/p95:",
      [[round(float(np.percentile(lam_c[:, :, c][mask], q)), 4) for q in (5, 50, 95)]
       for c in range(3)])
lam = lam_c[mask].mean(axis=1)
print("lambert mean", round(float(lam.mean()), 5),
      " frac<=0", round(float((lam <= 1e-9).mean()), 4),
      " frac>=1", round(float((lam >= 1 - 1e-9).mean()), 4),
      " fraction strictly inside", round(float(((lam > 1e-6) & (lam < 1 - 1e-6)).mean()), 4))
# --- dDN from the renderer's own rgb_linear, mean over channels, in code values
d_dn = 255.0 * (rgb_on - rgb_off).mean(axis=2)[mask]
print("dDN rms from renderer rgb_linear", round(float(np.sqrt(np.mean(d_dn ** 2))), 4))
print("dDN rms from the imaging chain float  ",
      round(float(fa.difference_dn_statistics(on["dn_float"], off["dn_float"], mask)["dDN_rms"]), 4))
# --- what albedo factor reproduces it?
d_lam = ((rgb_on - rgb_off) / alb[None, None, :] / col[None, None, :])[mask].mean(axis=1)
rms_lam = float(np.sqrt(np.mean(d_lam ** 2)))
print("d_lambert rms from the renderer      ", round(rms_lam, 6))
pred_lam = field.predicted_shading_ddn_on_points(
    np.zeros((0, 3)), albedo=alb, light=light) if False else None
print("implied dDN factor = measured dDN / d_lambert rms =",
      round(float(np.sqrt(np.mean(d_dn ** 2))) / rms_lam, 4))
print("my factor 255*mean_c(alb*col) =", round(255.0 * float(np.mean(alb * col)), 4))
print("255*mean(albedo)            =", round(255.0 * float(alb.mean()), 4))
print("255*mean(albedo)*mean(color)=", round(255.0 * float(alb.mean() * col.mean()), 4))
