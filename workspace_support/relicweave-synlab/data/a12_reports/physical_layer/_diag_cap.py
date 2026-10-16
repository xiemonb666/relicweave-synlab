"""A4 diagnostic 7 (DEFINITIVE): capture the renderer's actual per-pixel shaded normal.

The module source is re-executed with ONE extra line that stores ``(pts, n_px, albedo)`` whenever
the renderer shades a pixel through the per-pixel-normal path, and the patched function is put back
into the live module.  The numbers below are therefore the renderer's own.
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
from synlab.observe import fracture_appearance as fa  # noqa: E402
from synlab.observe import fracture_roi as fr  # noqa: E402
from synlab.observe import routes as rt  # noqa: E402
from synlab.seeds import make_rng  # noqa: E402

SRC = Path(fa.__file__).read_text(encoding="utf-8")
MARK = ('        shaded = shade_world_normals(\n'
        '            normals_world=n_px,\n')
assert MARK in SRC, "marker not found"
NEW = ('        _CAP.append((pts.copy(), n_px.copy(), albedo_px[f].copy()))\n' + MARK)
ns = dict(fa.__dict__)
ns["_CAP"] = []
exec(compile(SRC.replace(MARK, NEW), str(fa.__file__), "exec"), ns)
fa._CAP = ns["_CAP"]
fa._rasterise_appearance = ns["_rasterise_appearance"]
print("patched OK; capture list is", len(fa._CAP), "entries")

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

fa._CAP.clear()
off = render_and_image(target=target, frame=frame,
                       appearance=fa.AppearanceSpec(normal_mode="FLAT", relief=False,
                                                    interpolation="PERSPECTIVE_CORRECT"),
                       relief=None, obs_spec=spec, imaging_seed=11, supersample=1)
off_cap = list(fa._CAP)
print("off capture chunks", len(off_cap), "(relief_off takes the flat fast path, so 0 is expected)")
fa._CAP.clear()
on = render_and_image(target=target, frame=frame,
                      appearance=fa.AppearanceSpec(normal_mode="FLAT", relief=True,
                                                   interpolation="PERSPECTIVE_CORRECT"),
                      relief=field, obs_spec=spec, imaging_seed=11, supersample=1)
on_cap = list(fa._CAP)
print("off capture chunks", len(off_cap), "on capture chunks", len(on_cap))

def stack(cap):
    return (np.vstack([c[0] for c in cap]), np.vstack([c[1] for c in cap]))

pts, n_on = stack(on_cap)
print("captured px on", pts.shape[0])
alb = np.asarray(field.parameters.albedo, dtype=np.float64)
a_u = float(np.dot(field.u_axis, light.direction))
a_v = float(np.dot(field.v_axis, light.direction))
# the base normal is the face normal at the captured point (world frame), exactly as the fast path
verts = np.asarray(mesh.vertices, dtype=np.float64)
fcs = np.asarray(mesh.faces)[faces]
tri = verts[fcs]
fn = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
fn = fn / np.linalg.norm(fn, axis=1, keepdims=True)
cent = tri.mean(axis=1)
dist = np.linalg.norm(pts[:, None, :] - cent[None, :, :], axis=2)
nf = fn[np.argmin(dist, axis=1)]
n0 = nf / np.linalg.norm(nf, axis=1, keepdims=True)
d_lam_actual = -(n_on - n0) @ light.direction
_, gu1, gv1 = field.sample(pts, scale=1.0)
print("|grad| rms captured at unit scale", round(float(np.sqrt(np.mean(gu1 ** 2 + gv1 ** 2))), 6))
pred_lin = float(field.amplitude_scale) * (gu1 * a_u + gv1 * a_v)
print("actual d_lambert rms ", round(float(np.sqrt(np.mean(d_lam_actual ** 2))), 6))
print("linear pred rms      ", round(float(np.sqrt(np.mean(pred_lin ** 2))), 6))
print("ratio actual/linear  ", round(float(np.sqrt(np.mean(d_lam_actual ** 2))
                                          / np.sqrt(np.mean(pred_lin ** 2))), 6))
# with the tangent renormalisation the renderer applies
tu = field.u_axis[None, :] - (n0 @ field.u_axis)[:, None] * n0
tu = tu / np.linalg.norm(tu, axis=1, keepdims=True)
tv = field.v_axis[None, :] - (n0 @ field.v_axis)[:, None] * n0
tv = tv / np.linalg.norm(tv, axis=1, keepdims=True)
s = float(field.amplitude_scale)
pert = (s * gu1)[:, None] * tu + (s * gv1)[:, None] * tv
n_pred = n0 - pert
n_pred = n_pred / np.linalg.norm(n_pred, axis=1, keepdims=True)
d_lam_pred = -(n_pred - n0) @ light.direction
print("pred with renormalised tangents", round(float(np.sqrt(np.mean(d_lam_pred ** 2))), 6))
print("ratio actual/pred             ", round(float(np.sqrt(np.mean(d_lam_actual ** 2))
                                                    / np.sqrt(np.mean(d_lam_pred ** 2))), 6))
print("max |n_on - n_pred|", float(np.max(np.abs(n_on - n_pred))))
# and what the measured delivered dDN implies
d = fa.difference_dn_statistics(on["dn_float"], off["dn_float"], np.asarray(on["mask"], bool))
fac = 255.0 * float(np.mean(alb * np.asarray(light.color)))
print("measured dDN rms", round(float(d["dDN_rms"]), 4),
      "-> implied d_lambert rms", round(float(d["dDN_rms"]) / fac, 6))
