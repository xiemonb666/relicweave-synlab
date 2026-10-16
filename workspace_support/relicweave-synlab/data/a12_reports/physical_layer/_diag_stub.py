import sys
from dataclasses import dataclass
from pathlib import Path
import numpy as np
ROOT = Path(".").resolve(); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT/"tests/a12/observe"))
from _run_fracture_appearance import MASTER_SEED, SPECIMEN, pick_roi, render_and_image
from _run_fracture_roi import load_target
from synlab.cameras.profiles import camera_profiles
from synlab.observe import fracture_appearance as fa, fracture_roi as fr, routes as rt
from synlab.seeds import make_rng
target, body = load_target(SPECIMEN); mesh = target.mesh
rc = fr.load_fracture_roi_config(); base = {p.tier: p for p in camera_profiles()}["LOCAL"]
cu = fr.closeup_profile(rc, base=base, delivered_long_edge_px=1024)
fp = fr.mm_per_px(working_distance_mm=60.0, f_px=float(cu.K[0,0]))*512.0
roi = pick_roi(fr.fracture_rois(target, rc, footprint_radius_mm=fp))
spec = rt.ObsSpec(view_count=1, delivered_size=(1024,768), max_render_pixels=1024*1024, master_seed=MASTER_SEED,
                  lineage_id="d", frame_id="S_mm", renderer=rt.RENDERER_AUTO, distortion_policy=rt.DISTORTION_POLICY_IGNORE)
frame = fr.make_fracture_roi_frames(rois=[roi], profile=cu, spec=spec, config=rc, long_edge_px=1024,
                                    rng=make_rng(MASTER_SEED,"appearance_frame",roi.roi_id), run_id="d", mesh=mesh)[0]
u_axis, v_axis = fa.tangent_basis(np.asarray(roi.normal, float))
class Stub:
    def __init__(self, g): self.g = g; self.amplitude_scale = 1.0; self.u_axis = u_axis; self.v_axis = v_axis; self.realized_ra_mm = 0.0
    def sample(self, pts, *, scale=None):
        n = np.asarray(pts, float).reshape(-1,3).shape[0]
        s = self.amplitude_scale if scale is None else scale
        return np.zeros(n), np.full(n, self.g*s), np.zeros(n)
    def as_dict(self): return {"kind":"stub","g":self.g}
off = render_and_image(target=target, frame=frame, appearance=fa.AppearanceSpec(normal_mode="FLAT", relief=False, interpolation="PERSPECTIVE_CORRECT"), relief=None, obs_spec=spec, imaging_seed=11, supersample=1)
m = off["mask"]; print("mask px", int(m.sum()))
for g in (0.1, 1.0, 10.0):
    on = render_and_image(target=target, frame=frame, appearance=fa.AppearanceSpec(normal_mode="FLAT", relief=True, interpolation="PERSPECTIVE_CORRECT"), relief=Stub(g), obs_spec=spec, imaging_seed=11, supersample=1)
    d = (on["dn_float"] - off["dn_float"])[m]
    print("g",g,"dDN rms", round(float(np.sqrt((d**2).mean())),4), "nonzero", round(float((np.abs(d)>1e-9).mean()),4),
          "relief_active", on["render"].meta["appearance"]["relief_active"])
