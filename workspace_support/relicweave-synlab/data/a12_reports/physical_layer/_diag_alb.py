import sys
from pathlib import Path
import numpy as np
ROOT = Path(".").resolve()
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests/a12/observe"))
from _run_fracture_appearance import (MASTER_SEED, SPECIMEN, material_profile, patch_faces,
                                      render_and_image)
from _run_fracture_roi import load_target
from synlab.cameras.profiles import camera_profiles
from synlab.observe import fracture_appearance as fa, fracture_roi as fr, routes as rt
from synlab.observe.render import procedural_albedo
from synlab.seeds import make_rng
target, body = load_target(SPECIMEN); mesh = target.mesh
rc = fr.load_fracture_roi_config(); base = {p.tier: p for p in camera_profiles()}["LOCAL"]
cu = fr.closeup_profile(rc, base=base, delivered_long_edge_px=1024)
fp = fr.mm_per_px(working_distance_mm=60.0, f_px=float(cu.K[0,0])) * 512.0
roi = max(fr.fracture_rois(target, rc, footprint_radius_mm=fp),
          key=lambda r: -(np.asarray(r.normal) @ fa.frozen_light().direction))
faces = patch_faces(mesh, roi.interface_id)
spec = rt.ObsSpec(view_count=1, delivered_size=(1024,768), max_render_pixels=1024*1024,
                  master_seed=MASTER_SEED, lineage_id="d", frame_id="S_mm",
                  renderer=rt.RENDERER_AUTO, distortion_policy=rt.DISTORTION_POLICY_IGNORE)
frame = fr.make_fracture_roi_frames(rois=[roi], profile=cu, spec=spec, config=rc,
        long_edge_px=1024, rng=make_rng(MASTER_SEED,"appearance_frame",roi.roi_id),
        run_id="d", mesh=mesh)[0]
off = render_and_image(target=target, frame=frame,
        appearance=fa.AppearanceSpec(normal_mode="FLAT", relief=False,
                                     interpolation="PERSPECTIVE_CORRECT"),
        relief=None, obs_spec=spec, imaging_seed=11, supersample=1)
mask = np.asarray(off["mask"], bool)
rgb = np.asarray(off["render"].rgb_linear, float)
light = fa.frozen_light()
# recover the per-face albedo actually used: rgb = albedo*(ambient + color*lambert)
lam = (-(fa.face_normals(np.asarray(mesh.vertices), np.asarray(mesh.faces))
         @ np.asarray(light.direction)))          # world normal = face normal for FLAT
tr = (np.asarray(light.ambient)[None,:] + np.asarray(light.color)[None,:]*lam[:,None])
alb_faces = np.asarray(off["render"].id_map)
lab = procedural_albedo(np.asarray(mesh.faces).shape[0], seed=0x5EED)
idm = np.asarray(off["render"].id_map)
alb_px = lab[np.clip(idm,0,lab.shape[0]-1)]
print("scene albedo p05/p50/p95 (channel mean):",
      [round(float(np.percentile(alb_px[:,:,c][mask], q)),4) for c in range(3) for q in (5,)] ,
      " mean per channel", np.round(alb_px[mask].mean(axis=0),5))
print("procedural_albedo mean per channel", np.round(lab.mean(axis=0),5))
print("lambert recovered (unclipped):  mean", round(float(lam.mean()),5),
      " frac>1:", round(float((lam>1).mean()),4), " frac<0:", round(float((lam<0).mean()),4))
d = ((np.asarray(off["render"].rgb_linear,float)))
print("albedo*m(amb+color*lam) mismatch vs render (rms):",
      round(float(np.sqrt(np.mean((alb_px*(np.asarray(light.ambient)[None,None,:]
        + np.asarray(light.color)[None,None,:]*lam[None,:,None]) - rgb)**2))), 6))
fac = 255.0*float(np.mean(alb_px[mask].mean(axis=0)*np.asarray(light.color)))
print("TRUE dDN factor (scene palette) =", round(fac,3))
print("material-albedo factor          =", round(255.0*float(np.mean(
      np.asarray(profile_albedo:=material_profile(body["material_id"])["appearance"]["albedo"])
      * np.asarray(light.color))),3))
