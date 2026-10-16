import sys
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
    def __init__(self, g): self.g=g; self.amplitude_scale=1.0; self.u_axis=u_axis; self.v_axis=v_axis; self.realized_ra_mm=0.0
    def sample(self, pts, *, scale=None):
        n = np.asarray(pts,float).reshape(-1,3).shape[0]; s = self.amplitude_scale if scale is None else scale
        return np.zeros(n), np.full(n, self.g*s), np.zeros(n)
    def as_dict(self): return {"kind":"stub"}
off = render_and_image(target=target, frame=frame, appearance=fa.AppearanceSpec(normal_mode="FLAT", relief=False, interpolation="PERSPECTIVE_CORRECT"), relief=None, obs_spec=spec, imaging_seed=11, supersample=1)
on = render_and_image(target=target, frame=frame, appearance=fa.AppearanceSpec(normal_mode="FLAT", relief=True, interpolation="PERSPECTIVE_CORRECT"), relief=Stub(0.3), obs_spec=spec, imaging_seed=11, supersample=1)
a = np.asarray(off["render"].rgb_linear); b = np.asarray(on["render"].rgb_linear)
m = off["mask"]
print("rgb_linear max|diff|", float(np.abs(a-b).max()), "mean off/on", float(a.mean()), float(b.mean()))
print("rgb_linear in mask: off mean", float(a[m].mean()), "on mean", float(b[m].mean()))
la = np.asarray(off["imaging"].linear); lb = np.asarray(on["imaging"].linear)
print("linear max|diff|", float(np.abs(la-lb).max()), "mean", float(la.mean()), float(lb.mean()))
print("images identical:", bool(np.array_equal(off["image"], on["image"])))
print("dn_float max|diff|", float(np.abs(off["dn_float"]-on["dn_float"]).max()))
print("off image mean", float(off["image"].mean()), "on image mean", float(on["image"].mean()))
