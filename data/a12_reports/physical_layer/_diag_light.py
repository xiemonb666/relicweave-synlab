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
frames = fr.make_fracture_roi_frames(rois=[roi], profile=cu, spec=spec, config=rc, long_edge_px=1024,
                                     rng=make_rng(MASTER_SEED,"appearance_frame",roi.roi_id), run_id="d", mesh=mesh)
print("n frames", len(frames))
for i, frame in enumerate(frames):
    off = render_and_image(target=target, frame=frame, appearance=fa.AppearanceSpec(normal_mode="FLAT", relief=False, interpolation="PERSPECTIVE_CORRECT"), relief=None, obs_spec=spec, imaging_seed=11, supersample=1)
    lam = off["render"].meta["appearance"]["lambert"]
    print(f"dir {i} theta={frame.meta['direction_offset_deg']:+.0f} phi={frame.meta['direction_in_plane_deg']:.0f} "
          f"rim_px={int(off['mask'].sum())} unlit={lam.get('unlit_fraction')} lit={lam.get('lit_fraction')} "
          f"mean_raw_dot={lam.get('mean_raw_dot'):.3f} dN_p95p05={fa.dn_statistics(off['dn'], off['mask'])['dn_p95_minus_p05']:.1f}")

