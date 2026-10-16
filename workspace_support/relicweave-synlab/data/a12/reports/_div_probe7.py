"""Reproduce the cv2.error with the exact sampled ObsSpec, on a real fragment."""
from __future__ import annotations

import dataclasses
import sys
import time
import traceback
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from synlab.cameras.api import camera_profiles  # noqa: E402
from synlab.fracture.api import fracture_event  # noqa: E402
from synlab.fracture.spec import FractureSpec  # noqa: E402
from synlab.mothers.api import create_mother  # noqa: E402
from synlab.observe.api import observe  # noqa: E402
from synlab.observe.render import RenderSpec  # noqa: E402
from synlab.observe.routes import ObsSpec  # noqa: E402
from synlab.seeds import derive_named_rngs, make_rng  # noqa: E402

params = {"base_mm": 5.173956834743791, "belly": 0.8044526411931665,
          "depth_ratio": 0.25813382003420415, "diameter_mm": 170.59528695766963,
          "foot_height_ratio": 0.04142833303108983, "foot_ring_ratio": 0.889988267999535,
          "rim_flare": -0.0341073992881093, "wall_mm": 9.324583657218447,
          "warp_amplitude": 0.028333870748001488, "warp_eccentricity_mm": 2.394345260187333,
          "warp_lobes": 2}

mother = create_mother("V01", "M01", params, make_rng(20261001, "probe", "shape"),
                       mother_id="probe_V01")
fr = fracture_event(mother, FractureSpec(backend="plane_shared_cut",
                                         plane_normal=np.array([0.0284, 0.97801, -0.20662]),
                                         plane_point=np.asarray(mother.mesh.vertices).mean(axis=0)),
                    make_rng(20261001, "probe", "cut"), event_id="probe_E01")
frag = max((f for f in fr.fragments if not f.is_tiny), key=lambda f: f.volume_mm3)
print("fragment", frag.fragment_id, "vol", frag.volume_mm3)

profile = camera_profiles()[2]
rngs = derive_named_rngs(20261001, "probe")

cases = [
    ("baseline 12v/512", 12, (512, 384), 512 * 384, 0.75 * float(profile.f_number)),
    ("sampled 14v/512", 14, (512, 384), 512 * 384, 0.75 * float(profile.f_number)),
    ("11v/512", 11, (512, 384), 512 * 384, 0.75 * float(profile.f_number)),
    ("13v/512", 13, (512, 384), 512 * 384, 0.75 * float(profile.f_number)),
    ("12v/640", 12, (640, 480), 640 * 480, 0.75 * float(profile.f_number)),
    ("12v/256", 12, (256, 192), 256 * 192, 0.75 * float(profile.f_number)),
]
for name, views, delivered, budget, coc in cases:
    spec = ObsSpec(view_count=views, delivered_size=delivered, max_render_pixels=budget,
                   render_spec=RenderSpec(supersample=1, coc_px_threshold=coc))
    t0 = time.perf_counter()
    try:
        obs = observe(frag, None, rngs, route="proxy_scan", profile=profile, spec=spec)
        frames = [v for v in (obs.meta.get("views") or [])]
        print(f"{name:20s} OK   views={len(frames)} "
              f"img={frames[0].get('image_size') if frames else None} "
              f"{time.perf_counter() - t0:.1f}s")
    except Exception as exc:  # noqa: BLE001
        tb = traceback.format_exc().strip().splitlines()[-4:]
        print(f"{name:20s} FAIL {type(exc).__name__}: {str(exc)[:90]} {time.perf_counter() - t0:.1f}s")
        for line in tb:
            print("      ", line.strip())
