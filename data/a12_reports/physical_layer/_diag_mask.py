"""A4 diagnostic 6: is the fracture mask actually the ROI patch, and where are its hit points?"""
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
from synlab.cameras.projection import project, unproject  # noqa: E402
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
off = render_and_image(target=target, frame=frame,
                       appearance=fa.AppearanceSpec(normal_mode="FLAT", relief=False,
                                                    interpolation="PERSPECTIVE_CORRECT"),
                       relief=None, obs_spec=spec, imaging_seed=11, supersample=1)
mask = np.asarray(off["mask"], dtype=bool)
idmap = np.asarray(off["render"].id_map)
depth = np.asarray(off["render"].depth_z, dtype=np.float64)
print("mask px", int(mask.sum()), "id_map>=0", int((idmap >= 0).sum()))
print("mask ids unique", np.unique(idmap[mask]).size, "patch faces", faces.size)
print("mask ids subset of patch?", bool(np.isin(np.unique(idmap[mask]),
                                                np.asarray(target.face_id)[faces]).all()))
# project the patch vertices: where do they land?
patch_v = np.unique(np.asarray(mesh.faces)[faces])
uvv, zz = project(np.asarray(mesh.vertices)[patch_v], np.asarray(frame.K, dtype=np.float64),
                  np.asarray(frame.T_WC, dtype=np.float64),
                  np.asarray(frame.dist, dtype=np.float64), model=frame.camera_model or "PINHOLE")
inside = (uvv[:, 0] >= 0) & (uvv[:, 0] < 1024) & (uvv[:, 1] >= 0) & (uvv[:, 1] < 768)
print("patch verts", patch_v.size, "projected inside frame", int(inside.sum()))
W, H = 1024, 768
face_centroids = np.asarray(mesh.vertices)[np.asarray(mesh.faces)[faces]].mean(axis=1)
cuv, cz = project(face_centroids, np.asarray(frame.K, dtype=np.float64),
                  np.asarray(frame.T_WC, dtype=np.float64),
                  np.asarray(frame.dist, dtype=np.float64), model=frame.camera_model or "PINHOLE")
ok = np.isfinite(cuv[:, 0])
xi = np.clip(np.round(cuv[ok, 0]).astype(int), 0, W - 1)
yi = np.clip(np.round(cuv[ok, 1]).astype(int), 0, H - 1)
print("patch face centroids in frame:", int(ok.sum()),
      "  of those on the mask:", int(mask[yi, xi].sum()),
      "  of those with id_map==own id:", int((idmap[yi, xi] == np.asarray(target.face_id)[faces][ok]).sum()))
# ROI-plane coordinates of the 3D patch vertices, then of the mask hit points
n = np.asarray(roi.normal, dtype=np.float64)
u_ax, v_ax = fa.tangent_basis(n)
origin = np.asarray(roi.aim_mm, dtype=np.float64)
pv = np.asarray(mesh.vertices)[patch_v] - origin[None, :]
print("patch vertex u range", round(float((pv @ u_ax).min()), 2), round(float((pv @ u_ax).max()), 2),
      " v range", round(float((pv @ v_ax).min()), 2), round(float((pv @ v_ax).max()), 2))
ys, xs = np.nonzero(mask & np.isfinite(depth))
world = unproject(np.stack([xs + 0.5, ys + 0.5], axis=1), depth[ys, xs],
                  np.asarray(frame.K, dtype=np.float64), np.asarray(frame.T_WC, dtype=np.float64),
                  np.asarray(frame.dist, dtype=np.float64), model=frame.camera_model or "PINHOLE")
rel = world - origin[None, :]
print("hit u range", round(float((rel @ u_ax).min()), 2), round(float((rel @ u_ax).max()), 2),
      " v range", round(float((rel @ v_ax).min()), 2), round(float((rel @ v_ax).max()), 2))
print("hit |normal offset| median", round(float(np.median(np.abs(rel @ n))), 4),
      "p95", round(float(np.percentile(np.abs(rel @ n), 95)), 4))
# distance of hits from the aim point
d = np.linalg.norm(rel, axis=1)
print("hit distance from aim mm: p05/med/p95", [round(float(np.percentile(d, q)), 3)
                                                for q in (5, 50, 95)])
# is the unprojection self-consistent? reproject the recovered points
uv2, z2 = project(world, np.asarray(frame.K, dtype=np.float64),
                  np.asarray(frame.T_WC, dtype=np.float64),
                  np.asarray(frame.dist, dtype=np.float64), model=frame.camera_model or "PINHOLE")
print("reprojection err px", round(float(np.max(np.abs(uv2[:, 0] - (xs + 0.5)))), 9),
      round(float(np.max(np.abs(uv2[:, 1] - (ys + 0.5)))), 9))
print("z rel err", round(float(np.max(np.abs(z2 - depth[ys, xs]) / depth[ys, xs])), 9))
