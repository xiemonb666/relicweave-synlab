"""Diagnostic: is the relief normal channel actually entering the frozen shading?"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests/a12/observe"))

from _run_fracture_appearance import (MASTER_SEED, SPECIMEN, material_profile, patch_faces,
                                      render_and_image, pick_roi)  # noqa: E402
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
rois = fr.fracture_rois(target, roi_config, footprint_radius_mm=fp)
roi = pick_roi(rois)
faces = patch_faces(mesh, roi.interface_id)
tris = np.asarray(mesh.faces)[faces]
spec = rt.ObsSpec(view_count=1, delivered_size=(1024, 768), max_render_pixels=1024 * 1024,
                  master_seed=MASTER_SEED, lineage_id="diag", frame_id="S_mm",
                  renderer=rt.RENDERER_AUTO, distortion_policy=rt.DISTORTION_POLICY_IGNORE)
frame = fr.make_fracture_roi_frames(rois=[roi], profile=closeup, spec=spec, config=roi_config,
                                    long_edge_px=1024, rng=make_rng(MASTER_SEED, "appearance_frame",
                                                                    roi.roi_id),
                                    run_id="diag", mesh=mesh)[0]
profile = material_profile(body["material_id"])
field = fa.build_relief_field(profile=profile, roi=roi, patch_vertices=mesh.vertices,
                              patch_triangles=tris, mesh=mesh,
                              rng=make_rng(MASTER_SEED, "appearance_field", body["material_id"]),
                              amplitude_mm=None)
print("ra_at_unit", round(field.ra_at_unit_mm, 4), "rq", round(field.rq_at_unit_mm, 4),
      "dome_share", round(field.dome_share, 3))
print("bands", field.parameters.band_wavelengths_mm, [round(a, 4) for a in
                                                      field.parameters.band_amplitudes_mm])
g = field.height.meta["morphology"]
print("hackle N", g["hackle_count"], "a_h", round(g["hackle_amplitude_mm"], 4),
      "a_rib", round(g["rib_amplitude_mm"], 4), "pit depth", round(g["pit_depth_mm"], 4),
      "pit r", round(g["pit_radius_mm"], 3), "pit count", g["pit_count"],
      "dome R", round(g["dome_radius_mm"], 2), "dome a", round(g["dome_amplitude_mm"], 4),
      "mirror r", round(g["mirror_radius_mm"], 3), "mist r", round(g["mist_radius_mm"], 3))
print("wall", field.meta["wall_thickness"])
off = render_and_image(target=target, frame=frame,
                       appearance=fa.AppearanceSpec(normal_mode="FLAT", relief=False,
                                                    interpolation="PERSPECTIVE_CORRECT"),
                       relief=None, obs_spec=spec, imaging_seed=11, supersample=2)
dn = off["dn"]
m = off["mask"]
print("off dn p05/p50/p95", [round(float(np.percentile(dn[m], q)), 1) for q in (5, 50, 95)],
      "unique-ish", len(np.unique(np.round(dn[m], 1))))
for target_ra in (None, 0.4, 1.2):
    f2 = field if target_ra is None else fa.resample_relief_ra(field, target_ra)
    on = render_and_image(target=target, frame=frame,
                          appearance=fa.AppearanceSpec(normal_mode="FLAT", relief=True,
                                                       interpolation="PERSPECTIVE_CORRECT"),
                          relief=f2, obs_spec=spec, imaging_seed=11, supersample=2)
    d = np.abs(on["dn"] - off["dn"])[m]
    print(f"Ra={target_ra} realized={f2.realized_ra_mm:.4f} | "
          f"dDN rms={d.mean() and float(np.sqrt((d**2).mean())):.3f} mean={d.mean():.3f} "
          f"p50={float(np.percentile(d,50)):.3f} p95={float(np.percentile(d,95)):.2f} "
          f"max={d.max():.1f} frac>=1={float((d>=1).mean()):.3f}")
    # lambert sensitivity probe: the shading gradient vs the normal perturbation
    n_px_probe = None
    del n_px_probe
