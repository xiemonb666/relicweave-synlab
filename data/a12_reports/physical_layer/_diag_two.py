"""A4 diagnostic 8 (DECISIVE): the SAME field gradient estimator on two point sets.

Point set A: the 3D fracture pixels actually rendered (unprojected from depth_z).
Point set B: the ROI plane sample grid at field.sample_mm that the prediction uses.
Both through field.sample(), unit scale, envelope included.
"""
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
field = fa.build_relief_field(profile=profile, roi=roi, patch_vertices=mesh.vertices,
                              patch_triangles=tris, mesh=mesh,
                              rng=make_rng(MASTER_SEED, "appearance_field", body["material_id"]),
                              amplitude_mm=0.08)
R = float(field.footprint_radius_mm)
step = float(field.sample_mm)

# ---- point set B: the ROI plane grid the prediction uses (field._grid_gradients' own points)
uu, vv = np.meshgrid(np.arange(-R, R + 0.5 * step, step), np.arange(-R, R + 0.5 * step, step),
                     indexing="ij")
print("B grid", uu.shape, "points", uu.size)
_, bgu, bgv = field.sample(field.origin_mm[None, :] + uu.ravel()[:, None] * field.u_axis[None, :]
                           + vv.ravel()[:, None] * field.v_axis[None, :], scale=1.0)
b_slope = np.hypot(bgu, bgv)
print("B  |grad| rms (unit)      ", round(float(np.sqrt(np.mean(b_slope ** 2))), 6),
      " p95", round(float(np.percentile(b_slope, 95)), 6))

# ---- point set A: the rendered fracture pixels
off = render_and_image(target=target, frame=frame,
                       appearance=fa.AppearanceSpec(normal_mode="FLAT", relief=False,
                                                    interpolation="PERSPECTIVE_CORRECT"),
                       relief=None, obs_spec=spec, imaging_seed=11, supersample=1)
mask = np.asarray(off["mask"], dtype=bool)
depth = np.asarray(off["render"].depth_z, dtype=np.float64)
ys, xs = np.nonzero(mask & np.isfinite(depth))
world = unproject(np.stack([xs + 0.5, ys + 0.5], axis=1), depth[ys, xs],
                  np.asarray(frame.K, dtype=np.float64), np.asarray(frame.T_WC, dtype=np.float64),
                  np.asarray(frame.dist, dtype=np.float64), model=frame.camera_model or "PINHOLE")
_, agu, agv = field.sample(world, scale=1.0)
a_slope = np.hypot(agu, agv)
print("A  |grad| rms (unit)      ", round(float(np.sqrt(np.mean(a_slope ** 2))), 6),
      " p95", round(float(np.percentile(a_slope, 95)), 6))
au, av = field.uv(world)
print("A  u,v area mm^2 (bbox)", round(float((au.max() - au.min()) * (av.max() - av.min())), 2),
      " A px", au.size)
bu, bv = field.uv(field.origin_mm[None, :] + uu.ravel()[:, None] * field.u_axis[None, :]
                  + vv.ravel()[:, None] * field.v_axis[None, :])
print("B  u,v area mm^2 (bbox)", round(float((bu.max() - bu.min()) * (bv.max() - bv.min())), 2),
      " B px", bu.size)

# ---- radius profile: where does each estimator's weight sit?
for name, ru, rv, sl in (("A", au, av, a_slope), ("B", bu, bv, b_slope)):
    rr = np.hypot(ru, rv)
    hgram = []
    for lo, hi in ((0, 5), (5, 10), (10, 20), (20, 30), (30, 36), (36, 40)):
        sel = (rr >= lo) & (rr < hi)
        hgram.append(f"{lo}-{hi}: n={int(sel.sum())} rms={float(np.sqrt(np.mean(sl[sel] ** 2))) if sel.any() else float('nan'):.4f}")
    print(f"{name} radial rms by radius: " + " | ".join(hgram))
print("note: grad rms over the field is dominated by the SMALL-radius hackle/pit region; the "
      "prediction grid and the rendered pixels weight radii differently")
