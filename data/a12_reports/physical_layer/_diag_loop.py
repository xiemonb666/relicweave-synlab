"""Closed-loop check: rendered relief dDN vs the projection-aware prediction."""
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
light = fa.frozen_light()
for material_id in ("M11", "M01"):
    closeup = fr.closeup_profile(roi_config, base=base, delivered_long_edge_px=1024)
    fp = fr.mm_per_px(working_distance_mm=60.0, f_px=float(closeup.K[0, 0])) * 512.0
    roi = pick_roi(fr.fracture_rois(target, roi_config, footprint_radius_mm=fp))
    faces = patch_faces(mesh, roi.interface_id)
    tris = np.asarray(mesh.faces)[faces]
    spec = rt.ObsSpec(view_count=1, delivered_size=(1024, 768), max_render_pixels=1024 * 1024,
                      master_seed=MASTER_SEED, lineage_id="diag", frame_id="S_mm",
                      renderer=rt.RENDERER_AUTO, distortion_policy=rt.DISTORTION_POLICY_IGNORE)
    frame = fr.make_fracture_roi_frames(rois=[roi], profile=closeup, spec=spec, config=roi_config,
                                        long_edge_px=1024,
                                        rng=make_rng(MASTER_SEED, "appearance_frame", roi.roi_id),
                                        run_id="diag", mesh=mesh)[0]
    profile = material_profile(material_id)
    params = fa.appearance_parameters_from_profile(profile, material_id=material_id)
    alb = np.asarray(params.albedo)
    print(f"=== {material_id} albedo {np.round(alb,3)} sigma_r0 {params.sigma_r0_mm:.4f} "
          f"lam_min {params.lambda_min_mm:.3f} glaze {params.glaze_thickness_mm:.2f}")
    for ra in (0.02, 0.08, 0.4):
        field = fa.build_relief_field(profile=profile, roi=roi, patch_vertices=mesh.vertices,
                                      patch_triangles=tris, mesh=mesh,
                                      rng=make_rng(MASTER_SEED, "appearance_field", material_id),
                                      amplitude_mm=ra)
        off = render_and_image(target=target, frame=frame,
                               appearance=fa.AppearanceSpec(normal_mode="FLAT", relief=False,
                                                            interpolation="PERSPECTIVE_CORRECT"),
                               relief=None, obs_spec=spec, imaging_seed=11, supersample=2)
        on = render_and_image(target=target, frame=frame,
                              appearance=fa.AppearanceSpec(normal_mode="FLAT", relief=True,
                                                           interpolation="PERSPECTIVE_CORRECT"),
                              relief=field, obs_spec=spec, imaging_seed=11, supersample=2)
        m = off["mask"]
        d = (on["dn_float"] - off["dn_float"])[m]
        pred = field.predicted_shading_ddn(albedo=alb, light=light, T_WC=frame.T_WC,
                                           ra_scale=field.amplitude_scale)
        meas = float(np.sqrt((d ** 2).mean()))
        print(f"  Ra={ra:.2f} realized={field.realized_ra_mm:.4f} slope_rms_unit="
              f"{field.slope_rms_at_unit:.4f} | dDN_meas_rms={meas:.3f} "
              f"pred_rms={pred['predicted_dDN']:.3f} ratio={meas / max(pred['predicted_dDN'],1e-9):.3f} "
              f"| dDN_p95_meas={float(np.percentile(np.abs(d),95)):.2f} "
              f"pred_p95={pred['predicted_dDN_p95']:.2f} "
              f"| tu_l={pred['tangent_projection_u']:.3f} tv_l={pred['tangent_projection_v']:.3f}")

