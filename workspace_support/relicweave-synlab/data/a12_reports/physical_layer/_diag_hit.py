"""A4 diagnostic 2: prediction on the exact rendered hit points (apples-to-apples).

Recovers the world point each delivered fracture pixel hit by unprojecting the render's own
``depth_z`` through ``cameras.projection.unproject``, evaluates the audited field's **analytic**
gradient there, and forms the linearised frozen-shading change

    d_lambert = amp * (dh/du * (t_u . l) + dh/dv * (t_v . l))
    dDN_pred  = 255 * mean_c(albedo_c * color_c) * rms(d_lambert)

which is what the renderer actually applies.  Compared against the measured dDN at each Ra.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests/a12/observe"))

from _run_fracture_appearance import (MASTER_SEED, SPECIMEN, band_prediction, material_profile,  # noqa: E402
                                      mm_per_px_of, patch_faces, render_and_image)
from _run_fracture_roi import load_target  # noqa: E402
from synlab.cameras.profiles import camera_profiles  # noqa: E402
from synlab.cameras.projection import unproject  # noqa: E402
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
field = fa.build_relief_field(profile=profile, roi=roi, patch_vertices=mesh.vertices,
                              patch_triangles=tris, mesh=mesh,
                              rng=make_rng(MASTER_SEED, "appearance_field", body["material_id"]),
                              amplitude_mm=0.08)
print("mm/px", round(mm_per_px_of(frame), 6), "roi", roi.roi_id, "face", frame.view_id)

off = render_and_image(target=target, frame=frame,
                       appearance=fa.AppearanceSpec(normal_mode="FLAT", relief=False,
                                                    interpolation="PERSPECTIVE_CORRECT"),
                       relief=None, obs_spec=spec, imaging_seed=11, supersample=1)
mask = np.asarray(off["mask"], dtype=bool)
depth = np.asarray(off["render"].depth_z, dtype=np.float64)
ys, xs = np.nonzero(mask & np.isfinite(depth))
uv = np.stack([xs + 0.5, ys + 0.5], axis=1)
world = unproject(uv, depth[ys, xs], np.asarray(frame.K, dtype=np.float64),
                  np.asarray(frame.T_WC, dtype=np.float64),
                  np.asarray(frame.dist, dtype=np.float64) if frame.dist is not None else None,
                  model=frame.camera_model or "PINHOLE")
uu, vv = field.uv(world)
print("hit points", world.shape, "u range", round(float(uu.min()), 3), round(float(uu.max()), 3),
      "v range", round(float(vv.min()), 3), round(float(vv.max()), 3))

# analytic gradient at the exact hit points, envelope included (same call the renderer makes)
_, gu_hit, gv_hit = field.sample(world, scale=1.0)
a_u = float(np.dot(field.u_axis, light.direction))
a_v = float(np.dot(field.v_axis, light.direction))
alb = np.asarray(field.parameters.albedo, dtype=np.float64)
fac = 255.0 * float(np.mean(alb * np.asarray(light.color)))
print("a_u", round(a_u, 5), "a_v", round(a_v, 5), "factor", round(fac, 4))

# measured pair at each Ra, same view / seed / supersample
print()
print(f"{'Ra':>6} {'meas_rms':>9} {'pred_hitGrad':>13} {'meas/pred':>10} "
      f"{'pred_ROIgrid':>13} {'meas/pred_grid':>15} {'pred_band':>10}")
rows = []
for amp in (0.02, 0.08, 0.4):
    scaled = fa.resample_relief_ra(field, float(amp))
    on = render_and_image(target=target, frame=frame,
                          appearance=fa.AppearanceSpec(normal_mode="FLAT", relief=True,
                                                       interpolation="PERSPECTIVE_CORRECT"),
                          relief=scaled, obs_spec=spec, imaging_seed=11, supersample=1)
    d = fa.difference_dn_statistics(on["dn_float"], off["dn_float"], mask)
    m = float(d["dDN_rms"])
    g = float(scaled.amplitude_scale)
    dlam_hit = g * (gu_hit * a_u + gv_hit * a_v)
    pred_hit = fac * float(np.sqrt(np.mean(dlam_hit ** 2)))
    p_roi = band_prediction(scaled, ra_mm=float(amp), albedo=float(np.mean(alb)))
    rows.append((amp, m, pred_hit, m / max(pred_hit, 1e-12), p_roi["dDN_from_measured_slope"],
                 m / max(p_roi["dDN_from_measured_slope"], 1e-12), p_roi["band_dDN"]))
    print(f"{amp:6.3f} {m:9.4f} {pred_hit:13.4f} {m / max(pred_hit, 1e-12):10.4f} "
          f"{p_roi['dDN_from_measured_slope']:13.4f} "
          f"{m / max(p_roi['dDN_from_measured_slope'], 1e-12):15.4f} {p_roi['band_dDN']:10.4f}")

# the same hit-point gradient, but evaluated through a coarse finite difference (the ROI grid)
step = float(field.sample_mm)
fd_u = (np.asarray(field.height.raw(uu + step, vv)) - np.asarray(field.height.raw(uu, vv))) / step
fd_v = (np.asarray(field.height.raw(uu, vv + step)) - np.asarray(field.height.raw(uu, vv))) / step
print()
print("hit-point analytic slope rms", round(float(np.sqrt(np.mean(gu_hit ** 2 + gv_hit ** 2))), 5))
print("hit-point FD slope rms (step = ROI grid)", round(float(np.sqrt(np.mean(fd_u ** 2 + fd_v ** 2))), 5))
print("ratio analytic/FD at the SAME points  ",
      round(float(np.sqrt(np.mean(gu_hit ** 2 + gv_hit ** 2))
                  / np.sqrt(np.mean(fd_u ** 2 + fd_v ** 2))), 5))
print("hit points inside the envelope core (u,v within R - ramp):",
      int(np.sum(np.hypot(uu, vv) <= field.footprint_radius_mm - field.ramp_width_mm)))
print("frac of hits on the ramp:", round(float(np.mean(
    np.hypot(uu, vv) > field.footprint_radius_mm - field.ramp_width_mm)), 5))
