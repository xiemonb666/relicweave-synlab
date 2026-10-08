import sys
from pathlib import Path
import numpy as np
ROOT = Path(".").resolve(); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT/"tests/a12/observe"))
from _run_fracture_roi import STUDY, load_target
from _run_fracture_appearance import lit_score
from synlab.cameras.profiles import camera_profiles
from synlab.observe import fracture_appearance as fa, fracture_roi as fr
from synlab.seeds import make_rng
light = fa.frozen_light()
rc = fr.load_fracture_roi_config(); base = {p.tier: p for p in camera_profiles()}["LOCAL"]
cu = fr.closeup_profile(rc, base=base, delivered_long_edge_px=1024)
fp = fr.mm_per_px(working_distance_mm=60.0, f_px=float(cu.K[0,0]))*512.0
rows=[]
for entry in STUDY:
    target, body = load_target(entry)
    rois = fr.fracture_rois(target, fr.load_fracture_roi_config(), footprint_radius_mm=fp)
    for roi in rois:
        rows.append((lit_score(roi, light), body["vessel_id"], body["material_id"], roi.roi_id, roi.n_faces, round(roi.area_mm2,1)))
rows.sort(reverse=True)
for r in rows: print(f"lit={r[0]:+.3f} {r[1]}/{r[2]} {r[3]} faces={r[4]} area={r[5]}")
