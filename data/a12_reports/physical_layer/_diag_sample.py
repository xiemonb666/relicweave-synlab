"""A4 diagnostic 5: field.sample() vs the raw height gradient — where does the factor come from?"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests/a12/observe"))

from _run_fracture_appearance import MASTER_SEED, SPECIMEN, material_profile, patch_faces  # noqa: E402
from _run_fracture_roi import load_target  # noqa: E402
from synlab.cameras.profiles import camera_profiles  # noqa: E402
from synlab.observe import fracture_appearance as fa  # noqa: E402
from synlab.observe import fracture_roi as fr  # noqa: E402
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
profile = material_profile(body["material_id"])
field = fa.build_relief_field(profile=profile, roi=roi, patch_vertices=mesh.vertices,
                              patch_triangles=tris, mesh=mesh,
                              rng=make_rng(MASTER_SEED, "appearance_field", body["material_id"]),
                              amplitude_mm=0.08)
print("amplitude_scale", field.amplitude_scale, "glaze_strip", field.glaze_strip,
      "sample_mm", field.sample_mm, "ramp", field.ramp_width_mm, "R", field.footprint_radius_mm)
h = field.height
print("height.window", h.window, "modulation", h.modulation, "amplitude_max", h.amplitude_max_mm)
print("pits", 0 if h.pits is None else len(h.pits))

# a small patch of plane points straight around the ROI plane origin
ax = np.arange(-8.0, 8.0, 0.4)
uu, vv = np.meshgrid(ax, ax, indexing="ij")
pts = field.origin_mm[None, :] + uu.ravel()[:, None] * field.u_axis[None, :] \
    + vv.ravel()[:, None] * field.v_axis[None, :]
guh, gvh = h.gradient(uu.ravel(), vv.ravel())
hs, gus, gvs = field.sample(pts)
print("raw height.gradient |g| rms", round(float(np.sqrt(np.mean(guh ** 2 + gvh ** 2))), 6))
print("field.sample        |g| rms", round(float(np.sqrt(np.mean(gus ** 2 + gvs ** 2))), 6))
print("ratio", round(float(np.sqrt(np.mean(guh ** 2 + gvh ** 2))
                         / np.sqrt(np.mean(gus ** 2 + gvs ** 2))), 6))
print("corr(gu)", round(float(np.corrcoef(guh, gus)[0, 1]), 6),
      "corr(gv)", round(float(np.corrcoef(gvh, gvs)[0, 1]), 6))
env, deu, dev = fa._envelope(uu.ravel(), vv.ravel(), field.footprint_radius_mm,
                             field.ramp_width_mm)
print("env min/max/mean", round(float(env.min()), 6), round(float(env.max()), 6),
      round(float(env.mean()), 6), "|d_env| max", round(float(np.abs(deu).max()), 6))
# per-point ratio distribution
rr = np.hypot(gus, gvs) / np.maximum(np.hypot(guh, gvh), 1e-30)
print("sample/raw ratio p05/p50/p95", [round(float(np.percentile(rr, q)), 5) for q in (5, 50, 95)])
# is the sample result the ITEMS at the plane, i.e. exactly equal to the raw value at a different u,v?
print("sample h rms", round(float(np.sqrt(np.mean(hs ** 2))), 6),
      "raw h rms", round(float(np.sqrt(np.mean(
          np.asarray(h.raw(uu.ravel(), vv.ravel())) ** 2))), 6))
print("vs raw * amplitude_scale:",
      round(float(np.sqrt(np.mean(
          (np.asarray(h.raw(uu.ravel(), vv.ravel())) * field.amplitude_scale) ** 2))), 6))
print("guh rms * amp", round(float(np.sqrt(np.mean(guh ** 2 + gvh ** 2))) * field.amplitude_scale, 6))
print("gus rms", round(float(np.sqrt(np.mean(gus ** 2 + gvs ** 2))), 6))
