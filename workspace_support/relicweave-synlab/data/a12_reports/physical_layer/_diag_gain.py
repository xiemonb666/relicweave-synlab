"""Calibrate the renderer's normal channel with a KNOWN constant gradient."""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests/a12/observe"))

from _run_fracture_appearance import (MASTER_SEED, SPECIMEN, patch_faces, pick_roi,
                                      render_and_image)  # noqa: E402
from _run_fracture_roi import load_target  # noqa: E402
from synlab.cameras.profiles import camera_profiles  # noqa: E402
from synlab.observe import fracture_appearance as fa  # noqa: E402
from synlab.observe import fracture_roi as fr  # noqa: E402
from synlab.observe import routes as rt  # noqa: E402
from synlab.seeds import make_rng  # noqa: E402


@dataclass
class ConstantGradient:
    """A stub relief field with a constant gradient (mm/mm) and no envelope."""

    gu: float
    gv: float
    u_axis: np.ndarray
    v_axis: np.ndarray
    amplitude_scale: float = 1.0

    realized_ra_mm: float = 0.0

    def as_dict(self):
        return {"kind": "CONSTANT_GRADIENT_STUB", "gu": self.gu, "gv": self.gv}

    def sample(self, points_world, *, scale=None):
        n = np.asarray(points_world, dtype=np.float64).reshape(-1, 3).shape[0]
        s = float(self.amplitude_scale if scale is None else scale)
        return (np.zeros(n), np.full(n, self.gu * s), np.full(n, self.gv * s))


target, body = load_target(SPECIMEN)
mesh = target.mesh
roi_config = fr.load_fracture_roi_config()
base = {p.tier: p for p in camera_profiles()}["LOCAL"]
closeup = fr.closeup_profile(roi_config, base=base, delivered_long_edge_px=1024)
fp = fr.mm_per_px(working_distance_mm=60.0, f_px=float(closeup.K[0, 0])) * 512.0
roi = pick_roi(fr.fracture_rois(target, roi_config, footprint_radius_mm=fp))
spec = rt.ObsSpec(view_count=1, delivered_size=(1024, 768), max_render_pixels=1024 * 1024,
                  master_seed=MASTER_SEED, lineage_id="diag", frame_id="S_mm",
                  renderer=rt.RENDERER_AUTO, distortion_policy=rt.DISTORTION_POLICY_IGNORE)
frame = fr.make_fracture_roi_frames(rois=[roi], profile=closeup, spec=spec, config=roi_config,
                                    long_edge_px=1024,
                                    rng=make_rng(MASTER_SEED, "appearance_frame", roi.roi_id),
                                    run_id="diag", mesh=mesh)[0]
u_axis, v_axis = fa.tangent_basis(np.asarray(roi.normal, dtype=np.float64))
light = fa.frozen_light()
alb = np.asarray(fa.appearance_parameters_from_profile(
    __import__("_run_fracture_appearance", fromlist=["material_profile"]).material_profile(
        body["material_id"]), material_id=body["material_id"]).albedo)
off = render_and_image(target=target, frame=frame,
                       appearance=fa.AppearanceSpec(normal_mode="FLAT", relief=False,
                                                    interpolation="PERSPECTIVE_CORRECT"),
                       relief=None, obs_spec=spec, imaging_seed=11, supersample=1)
m = off["mask"]
factor = 255.0 * float(np.mean(alb * np.asarray(light.color)))
print("delta_dn_per_unit_dlambert", round(factor, 3))
for gu, gv in ((0.1, 0.0), (0.0, 0.1), (0.1, 0.1), (0.2, 0.0)):
    stub = ConstantGradient(gu=gu, gv=gv, u_axis=u_axis, v_axis=v_axis)
    on = render_and_image(target=target, frame=frame,
                          appearance=fa.AppearanceSpec(normal_mode="FLAT", relief=True,
                                                       interpolation="PERSPECTIVE_CORRECT"),
                          relief=stub, obs_spec=spec, imaging_seed=11, supersample=1)
    d = (on["dn_float"] - off["dn_float"])[m]
    meas = float(np.sqrt((d ** 2).mean()))
    # analytic: dlambert = -(dn . l) with dn = -gu*tu - gv*tv  =>  gu*(tu.l) + gv*(tv.l)
    dl = gu * float(np.dot(u_axis, light.direction)) + gv * float(np.dot(v_axis, light.direction))
    print(f"gu={gu:+.2f} gv={gv:+.2f} | meas rms={meas:8.3f} signed_mean={float(d.mean()):8.3f} "
          f"| pred dlambert={dl:+.4f} pred dDN={factor*abs(dl):8.3f} "
          f"ratio={meas/max(factor*abs(dl),1e-9):.3f}")


