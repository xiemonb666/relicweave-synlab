"""Decisive test: is the relief dDN really the relief, or a fast-path vs per-pixel artifact?"""
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
print("R_WC=\n", np.round(frame.T_WC[:3, :3], 4))
print("roi normal", np.round(roi.normal, 4), "aim", np.round(roi.aim_mm, 2))
profile = material_profile(body["material_id"])
field = fa.build_relief_field(profile=profile, roi=roi, patch_vertices=mesh.vertices,
                              patch_triangles=tris, mesh=mesh,
                              rng=make_rng(MASTER_SEED, "appearance_field", body["material_id"]),
                              amplitude_mm=0.4)
zero = fa.replace_relief_scale(field, 0.0) if hasattr(fa, "replace_relief_scale") else None
import dataclasses
zero = dataclasses.replace(field, amplitude_scale=0.0)
variants = {
    "off (fast path)": (fa.AppearanceSpec(normal_mode="FLAT", relief=False,
                                          interpolation="PERSPECTIVE_CORRECT"), None),
    "on, scale 0": (fa.AppearanceSpec(normal_mode="FLAT", relief=True,
                                      interpolation="PERSPECTIVE_CORRECT"), zero),
    "on, Ra=0.4": (fa.AppearanceSpec(normal_mode="FLAT", relief=True,
                                     interpolation="PERSPECTIVE_CORRECT"), field),
}
res = {}
for name, (app, rel) in variants.items():
    res[name] = render_and_image(target=target, frame=frame, appearance=app, relief=rel,
                                 obs_spec=spec, imaging_seed=11, supersample=1)
m = res["off (fast path)"]["mask"]
base_dn = res["off (fast path)"]["dn_float"]
for name, r in res.items():
    d = (r["dn_float"] - base_dn)[m]
    print(f"{name:18s} dDN rms={float(np.sqrt((d**2).mean())):.4f} "
          f"mean|d|={float(np.abs(d).mean()):.4f} nonzero={float((np.abs(d)>1e-9).mean()):.4f} "
          f"max={float(np.abs(d).max()):.2f}")
