"""A4 diagnostic 9: measure the exact relation between the renderer's applied perturbation and
the field's analytic gradient, at the points the renderer shaded."""
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
assert MARK in SRC
NEW = ('        _CAP.append((pts.copy(), n_px.copy(), float(scale_used)))\n' + MARK)
_INS = ('        scale_used = (relief_field.amplitude_scale'
        ' * float(appearance.amplitude_scale))\n')
src2 = SRC.replace('            _, gu, gv = relief_field.sample(pts, scale=relief_field.amplitude_scale\n'
                   '                                            * float(appearance.amplitude_scale))',
                   '            _, gu, gv = relief_field.sample(pts, scale='
                   '(relief_field.amplitude_scale * float(appearance.amplitude_scale)))')
assert 'relief_field.amplitude_scale * float(appearance.amplitude_scale)))' in src2, "not patched"
src2 = src2.replace(MARK, _INS + MARK)
ns = dict(fa.__dict__)
ns["_CAP"] = []
exec(compile(src2.replace(MARK, NEW), str(fa.__file__), "exec"), ns)
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
RA = 0.08
field = fa.build_relief_field(profile=profile, roi=roi, patch_vertices=mesh.vertices,
                              patch_triangles=tris, mesh=mesh,
                              rng=make_rng(MASTER_SEED, "appearance_field", body["material_id"]),
                              amplitude_mm=RA)
print("field.amplitude_scale", field.amplitude_scale, "ra_at_unit", field.ra_at_unit_mm,
      "realized", field.realized_ra_mm)
fa._CAP.clear()
res = render_and_image(target=target, frame=frame,
                       appearance=fa.AppearanceSpec(normal_mode="FLAT", relief=True,
                                                    interpolation="PERSPECTIVE_CORRECT"),
                       relief=field, obs_spec=spec, imaging_seed=11, supersample=1)
cap = list(fa._CAP)
scales = sorted({round(float(c[2]), 9) for c in cap})
print("renderer used scale(s):", scales, " n chunks", len(cap))
pts = np.vstack([c[0] for c in cap])
n_px = np.vstack([c[1] for c in cap])

# true face normal at each captured point, by plane distance then an inside test with a wide
# tolerance (the points come from the same rasteriser, so the plane distance is ~0 for the winner)
v0, v1, v2 = tris[:, 0], tris[:, 1], tris[:, 2]
P, A, B, C = pts, mesh.vertices[v0], mesh.vertices[v1], mesh.vertices[v2]
best = np.full(P.shape[0], -1, dtype=np.int64)
bestd = np.full(P.shape[0], np.inf)
for i in range(A.shape[0]):
    a, b, c = A[i], B[i], C[i]
    n = np.cross(b - a, c - a)
    nn = float(np.linalg.norm(n))
    if nn < 1e-30:
        continue
    n = n / nn
    d = np.abs((P - a[None, :]) @ n)
    e0, e1, e2 = b - a, c - b, a - c
    inside = np.ones(P.shape[0], dtype=bool)
    for e, o in ((e0, a), (e1, b), (e2, c)):
        cr = np.cross(e[None, :], P - o[None, :])
        inside &= ((cr @ n) >= -1e-4)
    upd = inside & (d < bestd)
    best[upd] = i
    bestd[upd] = d[upd]
print("points assigned to a patch face:", int((best >= 0).sum()), "/", P.shape[0],
      " plane distance p95 of the winners", round(float(np.percentile(bestd[best >= 0], 95)), 9))
fidx = faces[best]
tri_all = np.asarray(mesh.faces)
fn_all = np.cross(mesh.vertices[tri_all[:, 1]] - mesh.vertices[tri_all[:, 0]],
                  mesh.vertices[tri_all[:, 2]] - mesh.vertices[tri_all[:, 0]])
fn_all = fn_all / np.linalg.norm(fn_all, axis=1, keepdims=True)
n0 = fn_all[fidx]
ok = best >= 0
n0, P, n_px = n0[ok], P[ok], n_px[ok]

# the renderer's actual perturbation, projected on the field's tangent frame
pert_true = n0 - n_px * (n0 * n_px).sum(axis=1)[:, None] / np.maximum(
    (n0 * n_px).sum(axis=1), 1e-30)[:, None]
_, gu, gv = field.sample(P, scale=1.0)
print("field.sample(scale=1.0) |g| rms   ", round(float(np.sqrt(np.mean(gu ** 2 + gv ** 2))), 6))
print("field.sample(scale=amp) |g| rms   ", round(float(np.sqrt(np.mean(
    (gu * field.amplitude_scale) ** 2 + (gv * field.amplitude_scale) ** 2))), 6))
# coefficient k such that n0 - n_px = k * (gu*tu + gv*tv) with tu/tv the renormalised tangents
tu = field.u_axis[None, :] - (n0 @ field.u_axis)[:, None] * n0
tu = tu / np.linalg.norm(tu, axis=1, keepdims=True)
tv = field.v_axis[None, :] - (n0 @ field.v_axis)[:, None] * n0
tv = tv / np.linalg.norm(tv, axis=1, keepdims=True)
basis = np.stack([tu, tv], axis=1)            # (n, 2, 3)
rhs = np.einsum('nij,nj->ni', basis, n0 - n_px)
gram = np.einsum('nij,nkj->nik', basis, basis)
sol = np.linalg.solve(gram + 1e-12 * np.eye(2)[None, :, :], rhs[:, :, None])[:, :, 0]
g_at = np.stack([gu, gv], axis=1)
kk = (sol * g_at).sum(axis=1) / np.maximum((g_at ** 2).sum(axis=1), 1e-30)
print("damping factor k (true pert / unit-scale gradient)  median", round(float(np.median(kk)), 6),
      " p05", round(float(np.percentile(kk, 5)), 6), " p95", round(float(np.percentile(kk, 95)), 6))
print("  -> k / field.amplitude_scale =", round(float(np.median(kk)) / field.amplitude_scale, 6))
print("residual of the 2-term fit (rms of n0-n_px minus k*grad):",
      round(float(np.sqrt(np.mean(((n0 - n_px) - kk[:, None] * (g_at[:, 0:1] * tu
                                                                + g_at[:, 1:2] * tv)) ** 2))), 6),
      " vs |pert| rms", round(float(np.sqrt(np.mean((n0 - n_px) ** 2))), 6))
