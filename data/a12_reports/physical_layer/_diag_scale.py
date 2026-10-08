"""A4 diagnostic: is the 1.9x predicted-vs-measured dDN gap a SAMPLING effect of the prediction grid?

Measures, for the same audited morphology field:
  * the ANALYTIC gradient RMS  sqrt(mean(gu^2+gv^2))  at several plane-grid steps
  * the FORWARD-DIFFERENCE gradient RMS at the same steps (what a coarse ROI grid would see)
and the exact-vs-finite-difference split of MorphologyHeightField.gradient.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests/a12/observe"))

from _run_fracture_appearance import MASTER_SEED, SPECIMEN, material_profile, patch_faces  # noqa: E402
from _run_fracture_roi import load_target  # noqa: E402
from synlab.observe import fracture_appearance as fa  # noqa: E402
from synlab.observe import fracture_roi as fr  # noqa: E402
from synlab.seeds import make_rng  # noqa: E402

target, body = load_target(SPECIMEN)
mesh = target.mesh
roi_config = fr.load_fracture_roi_config()
from synlab.cameras.profiles import camera_profiles  # noqa: E402
base = {p.tier: p for p in camera_profiles()}["LOCAL"]
closeup = fr.closeup_profile(roi_config, base=base, delivered_long_edge_px=1024)
fp = fr.mm_per_px(working_distance_mm=60.0, f_px=float(closeup.K[0, 0])) * 512.0
rois = fr.fracture_rois(target, roi_config, footprint_radius_mm=fp)
roi = max(rois, key=lambda r: -(np.asarray(r.normal) @ fa.frozen_light().direction))
faces = patch_faces(mesh, roi.interface_id)
tris = np.asarray(mesh.faces)[faces]
profile = material_profile(body["material_id"])
field = fa.build_relief_field(profile=profile, roi=roi, patch_vertices=mesh.vertices,
                              patch_triangles=tris, mesh=mesh,
                              rng=make_rng(MASTER_SEED, "appearance_field", body["material_id"]),
                              amplitude_mm=None)
print("ROI", roi.roi_id, "ra_at_unit", round(field.ra_at_unit_mm, 6),
      "store sample_mm", field.sample_mm)
h = field.height
print("bands", [(round(b.amplitude_mm, 5), round(b.wavelength_mm, 4)) for b in h.bands])
print("hackle", h.hackle_count, round(h.hackle_amplitude_mm, 5), "mirror", round(h.mirror_radius_mm, 4),
      "mist", round(h.mist_radius_mm, 4))
print("rib", round(h.rib_amplitude_mm, 5), round(h.rib_spacing_mm, 4),
      "pit n", 0 if h.pits is None else len(h.pits))
print("origin_uv", h.origin_uv, "footprint R", field.footprint_radius_mm)

R = float(field.footprint_radius_mm)
half = 26.0  # a 52 mm window, well inside the flat-envelope core (R=37.4, ramp 2.0)

rows = []
for step in (0.5, 0.25, 0.2, 0.1083, 0.073, 0.05, 0.0365, 0.02, 0.01, 0.005):
    n = int(2 * half / step)
    ax = (np.arange(n) + 0.5) * step - half
    uu, vv = np.meshgrid(ax, ax, indexing="ij")
    gu, gv = h.gradient(uu, vv)
    an = np.sqrt(np.mean(gu ** 2 + gv ** 2))
    if step <= 0.1083:
        fd_u = (h.raw(uu + step, vv) - h.raw(uu, vv)) / step
        fd_v = (h.raw(uu, vv + step) - h.raw(uu, vv)) / step
        fd = np.sqrt(np.mean(fd_u ** 2 + fd_v ** 2))
    else:
        fd = float("nan")
    rows.append((step, n * n, an, fd, an / fd if fd == fd else float("nan"),
                 float(np.percentile(np.hypot(gu, gv), 95))))

print()
print(f"{'step_mm':>8} {'n_px':>9} {'analytic_rms':>13} {'fd_rms':>10} {'an/fd':>7} {'p95':>8}")
for step, npx, an, fd, ratio, p95 in rows:
    print(f"{step:8.4f} {npx:9d} {an:13.5f} {fd:10.5f} {ratio:7.3f} {p95:8.5f}")

# exact vs forward-difference split of MorphologyHeightField.gradient
step = 0.073
ax = (np.arange(700) + 0.5) * step - 25.0
uu, vv = np.meshgrid(ax, ax, indexing="ij")
ls = np.zeros_like(uu)
lv = np.zeros_like(vv)
for band in h.bands:
    k = band.k
    arg = k * (band.direction[0] * uu + band.direction[1] * vv) + band.phase
    s = -band.amplitude_mm * k * np.sin(arg)
    ls += s * band.direction[0]
    lv += s * band.direction[1]
rest = h.dome(uu, vv) + h._relief(uu, vv)
fstep = 0.05
rest_u = (h.dome(uu + fstep, vv) + h._relief(uu + fstep, vv) - rest) / fstep
rest_v = (h.dome(uu, vv + fstep) + h._relief(uu, vv + fstep) - rest) / fstep
print()
print("exact-band   slope rms", round(float(np.sqrt(np.mean(ls ** 2 + lv ** 2))), 5))
print("fd-rest      slope rms", round(float(np.sqrt(np.mean(rest_u ** 2 + rest_v ** 2))), 5))
print("rest mag rms", round(float(np.sqrt(np.mean(rest ** 2))), 5),
      "rest p95|.|", round(float(np.percentile(np.abs(rest), 95)), 5))
print("total        slope rms", round(float(np.sqrt(np.mean((ls + rest_u) ** 2
                                                           + (lv + rest_v) ** 2))), 5))
# what the frozen shading would produce for the linearised model
light = fa.frozen_light()
alb = np.asarray(field.parameters.albedo, dtype=np.float64)
fac = 255.0 * float(np.mean(alb * np.asarray(light.color)))
a_u, a_v = float(np.dot(field.u_axis, light.direction)), float(np.dot(field.v_axis, light.direction))
print("tangent projections a_u", round(a_u, 5), "a_v", round(a_v, 5),
      "a_perp", round(float(np.hypot(a_u, a_v)), 5))
for step, npx, an, fd, ratio, p95 in rows:
    print(f"predicted dDN at unit scale, step={step:8.4f}: "
          f"analytic {fac * float(np.hypot(a_u, a_v)) * an:8.4f}")
