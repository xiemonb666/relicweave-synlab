"""Reproduce the OpenCV failure with a bounded probe: which (profile, view_count, delivered) fails?"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from synlab.cameras.api import camera_profiles, transform_profile_u  # noqa: E402
from synlab.observe.routes import ObsSpec  # noqa: E402
from synlab.observe.render import LightSpec, RenderSpec  # noqa: E402

frame = (4000, 3000)
for profile in camera_profiles():
    for delivered in ((256, 192), (512, 384), (768, 576)):
        spec = ObsSpec(view_count=14, delivered_size=delivered,
                       max_render_pixels=delivered[0] * delivered[1],
                       render_spec=RenderSpec(supersample=1,
                                              coc_px_threshold=0.75 * float(profile.f_number)))
        try:
            rs, x0, y0, sx, sy = spec.derivation(frame)
            print(f"{profile.profile_id:16s} delivered={delivered} render_size={rs} "
                  f"crop=({x0},{y0}) scale=({sx:.4f},{sy:.4f}) -> OK")
        except Exception as exc:  # noqa: BLE001
            print(f"{profile.profile_id:16s} delivered={delivered} -> {type(exc).__name__}: {exc}")

print()
for u in (-30.0, 0.0, 30.0, -100.0, 70.0, 100.0):
    for profile in camera_profiles():
        try:
            moved = transform_profile_u(profile, u)
            print(f"{profile.profile_id:16s} u={u:7.1f} wd={moved.working_distance_mm:7.1f} "
                  f"fx={moved.K[0,0]:8.2f} dof={tuple(round(v,1) for v in moved.depth_of_field_mm)}")
        except Exception as exc:  # noqa: BLE001
            print(f"{profile.profile_id:16s} u={u:7.1f} -> refused: {exc}")
