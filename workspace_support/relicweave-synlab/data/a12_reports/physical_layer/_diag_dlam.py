"""A4 diagnostic 3: measure the renderer's OWN per-pixel perturbation against the field.

For each delivered fracture pixel: recover the world hit point from the render's depth_z, ask the
field for (gu, gv) at that point, form the linearisation the renderer uses, and compare its RMS with
the *actually measured* change of the un-quantised linear shading.  This decides whether the gap is
in the prediction formula or in the field evaluation.
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
alb = np.asarray(field.parameters.albedo, dtype=np.float64)
a_u = float(np.dot(field.u_axis, light.direction))
a_v = float(np.dot(field.v_axis, light.direction))

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
lin_off = np.asarray(off["imaging"].linear, dtype=np.float64)
lam_off = (lin_off / alb[None, None, :] - np.asarray(light.ambient)[None, None, :]) \
    / np.asarray(light.color)[None, None, :]

print("=== (1) does the renderer's own change match the field's analytic gradient? ===")
print(f"{'Ra':>6} {'meas dLambert rms':>18} {'pred from hit grad':>19} {'ratio':>7}")
for amp in (0.02, 0.08, 0.4):
    scaled = fa.resample_relief_ra(field, float(amp))
    on = render_and_image(target=target, frame=frame,
                          appearance=fa.AppearanceSpec(normal_mode="FLAT", relief=True,
                                                       interpolation="PERSPECTIVE_CORRECT"),
                          relief=scaled, obs_spec=spec, imaging_seed=11, supersample=1)
    lin_on = np.asarray(on["imaging"].linear, dtype=np.float64)
    lam_on = (lin_on / alb[None, None, :] - np.asarray(light.ambient)[None, None, :]) \
        / np.asarray(light.color)[None, None, :]
    d_lam = (lam_on - lam_off)[mask].mean(axis=1)
    g = float(scaled.amplitude_scale)
    _, gu, gv = scaled.sample(world, scale=g)
    pred = gu * a_u + gv * a_v
    print(f"{amp:6.3f} {np.sqrt(np.mean(d_lam ** 2)):18.6f} {np.sqrt(np.mean(pred ** 2)):19.6f} "
          f"{np.sqrt(np.mean(d_lam ** 2)) / max(np.sqrt(np.mean(pred ** 2)), 1e-12):7.4f}")

print()
print("=== (2) is the delivered-pixel hit point the sub-pixel point the renderer shaded? ===")
print("corr(d_lam_measured, pred) =",
      round(float(np.corrcoef((lam_on - lam_off)[mask].mean(axis=1), pred)[0, 1]), 5))
n = world.shape[0]
for dy, dx in ((-0.5, 0.0), (0.5, 0.0), (0.0, -0.5), (0.0, 0.5), (-0.25, -0.25)):
    uv2 = uv + np.array([dx, dy])
    w2 = unproject(uv2, depth[ys, xs], np.asarray(frame.K, dtype=np.float64),
                   np.asarray(frame.T_WC, dtype=np.float64),
                   np.asarray(frame.dist, dtype=np.float64) if frame.dist is not None else None,
                   model=frame.camera_model or "PINHOLE")
    _, gu2, gv2 = field.sample(w2, scale=field.amplitude_scale)
    p2 = gu2 * a_u + gv2 * a_v
    _, gu0, gv0 = field.sample(world, scale=field.amplitude_scale)
    print(f"  offset ({dx:+.2f},{dy:+.2f}): pred rms {np.sqrt(np.mean(p2 ** 2)):.5f} "
          f"(centre {np.sqrt(np.mean((gu0 * a_u + gv0 * a_v) ** 2)):.5f})")

print()
print("=== (3) what does the near-camera-plane tangent projection give? ===")
print("|a| from u,v axes", round(float(np.hypot(a_u, a_v)), 5))
print("tilt of u,v plane vs camera: n_roi . view dir",
      round(float(np.asarray(roi.normal) @ (world.mean(axis=0) - np.asarray(frame.T_WC)[:3, 3])
                  / np.linalg.norm(world.mean(axis=0) - np.asarray(frame.T_WC)[:3, 3])), 5))
print("d_lambert measured rms / (analytic hit slope rms * |a|) =",
      round(float(np.sqrt(np.mean(d_lam ** 2))
                  / (np.sqrt(np.mean(gu0 ** 2 + gv0 ** 2)) * np.hypot(a_u, a_v))), 5))
