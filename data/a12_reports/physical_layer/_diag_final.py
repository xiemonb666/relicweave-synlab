"""A4 diagnostic 10 (FINAL): the renderer's own normal vs the analytic prediction, per pixel.

The rasteriser is re-executed with two extra stores: the delivered pixel index of every shaded
point and the shaded normal.  That removes every ambiguity about which face a point belongs to and
lets the frozen shading expression be re-evaluated from the field alone.
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

SRC = Path(fa.__file__).read_text(encoding="utf-8")
MARK = ('        shaded = shade_world_normals(\n'
        '            normals_world=n_px,\n')
assert MARK in SRC
NEW = ('        _CAP.append((np.stack([ymin + rows, xmin + cols], axis=1), n_px.copy(),\n'
       '                     np.repeat(world_normals[f][None, :], pts.shape[0], axis=0)))\n' + MARK)
ns = dict(fa.__dict__)
ns["_CAP"] = []
exec(compile(SRC.replace(MARK, NEW), str(fa.__file__), "exec"), ns)
fa._CAP = ns["_CAP"]
fa._rasterise_appearance = ns["_rasterise_appearance"]

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
off = render_and_image(target=target, frame=frame,
                       appearance=fa.AppearanceSpec(normal_mode="FLAT", relief=False,
                                                    interpolation="PERSPECTIVE_CORRECT"),
                       relief=None, obs_spec=spec, imaging_seed=11, supersample=1)
mask = np.asarray(off["mask"], dtype=bool)
depth = np.asarray(off["render"].depth_z, dtype=np.float64)
fa._CAP.clear()
on = render_and_image(target=target, frame=frame,
                      appearance=fa.AppearanceSpec(normal_mode="FLAT", relief=True,
                                                   interpolation="PERSPECTIVE_CORRECT"),
                      relief=field, obs_spec=spec, imaging_seed=11, supersample=1)
cap = list(fa._CAP)
yx = np.vstack([c[0] for c in cap])
n_on = np.vstack([c[1] for c in cap])
n_base = np.vstack([c[2] for c in cap])
keep = mask[yx[:, 0], yx[:, 1]] & np.isfinite(depth[yx[:, 0], yx[:, 1]])
yx, n_on, n_base = yx[keep], n_on[keep], n_base[keep]
print("pixels kept", yx.shape[0], "of mask", int(mask.sum()))
uv = np.stack([yx[:, 1] + 0.5, yx[:, 0] + 0.5], axis=1)
world = unproject(uv, depth[yx[:, 0], yx[:, 1]], np.asarray(frame.K, dtype=np.float64),
                  np.asarray(frame.T_WC, dtype=np.float64),
                  np.asarray(frame.dist, dtype=np.float64), model=frame.camera_model or "PINHOLE")

# --- collapse the renderer's normal into (gu, gv) and compare with the field's own gradient
n0 = n_base / np.linalg.norm(n_base, axis=1, keepdims=True)
d = n0 - n_on
tu = field.u_axis[None, :] - (n0 @ field.u_axis)[:, None] * n0
tu = tu / np.linalg.norm(tu, axis=1, keepdims=True)
tv = field.v_axis[None, :] - (n0 @ field.v_axis)[:, None] * n0
tv = tv / np.linalg.norm(tv, axis=1, keepdims=True)
B = np.stack([tu, tv], axis=2)          # (n, 3, 2): columns are the two tangents
Y = np.einsum('nji,nj->ni', B, d)       # (n, 2) = B^T d
G = np.einsum('nji,njk->nik', B, B)     # (n, 2, 2) = B^T B
small = G + 1e-12 * np.eye(2)[None]
sol = np.linalg.solve(small, Y[:, :, None])[:, :, 0]
print("sol shape", sol.shape, " G cond p95",
      round(float(np.percentile(np.linalg.cond(small), 95)), 3))
fit = (B * sol[:, None, :]).sum(axis=2)
print("collapse residual rms", round(float(np.sqrt(np.mean((d - fit) ** 2))), 8),
    " |d| rms", round(float(np.sqrt(np.mean(d ** 2))), 8))
# |d| vs the gradient projected on the tangent plane
_, gu, gv = field.sample(world, scale=1.0)
gvec = gu[:, None] * field.u_axis[None, :] + gv[:, None] * field.v_axis[None, :]
gmag = np.linalg.norm(gvec, axis=1)
ratio = np.linalg.norm(d, axis=1) / np.maximum(gmag, 1e-30)
print("|d| rms        ", round(float(np.sqrt(np.mean(np.linalg.norm(d, axis=1) ** 2))), 8))
print("|grad| rms     ", round(float(np.sqrt(np.mean(gmag ** 2))), 8))
print("amplitude_scale", field.amplitude_scale)
print("ratio |d| / |grad| : median", round(float(np.median(ratio)), 6),
      " p05", round(float(np.percentile(ratio, 5)), 6),
      " p95", round(float(np.percentile(ratio, 95)), 6))
print("ratio / amplitude_scale : median", round(float(np.median(ratio)) / field.amplitude_scale, 6))
print("collapsed (gu_scaled) rms", round(float(np.sqrt(np.mean(sol ** 2))), 8),
      " vs amplitude_scale*|grad| rms",
      round(float(field.amplitude_scale * np.sqrt(np.mean(gmag ** 2))), 8))
print("corr(|d|, |grad|)", round(float(np.corrcoef(np.linalg.norm(d, axis=1), gmag)[0, 1]), 5))
# the same in lambert terms
lam_meas = -(n_on - n0) @ light.direction
lam_pred = -(field.amplitude_scale * (gu[:, None] * tu + gv[:, None] * tv)) @ light.direction
fac = 255.0 * float(np.mean(np.asarray(profile["appearance"]["albedo"], dtype=np.float64)
                            * np.asarray(light.color, dtype=np.float64)))
print("d_lambert rms measured", round(float(np.sqrt(np.mean(lam_meas ** 2))), 6),
      " predicted", round(float(np.sqrt(np.mean(lam_pred ** 2))), 6),
      " ratio", round(float(np.sqrt(np.mean(lam_meas ** 2)) / np.sqrt(np.mean(lam_pred ** 2))), 5))
print("-> dDN predicted", round(fac * float(np.sqrt(np.mean(lam_pred ** 2))), 4))
d_stat = fa.difference_dn_statistics(on["dn_float"], off["dn_float"], mask)
print("-> dDN measured ", round(float(d_stat["dDN_rms"]), 4))



