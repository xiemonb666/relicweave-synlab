"""Scratch: smoke-generate the nine extras on a synthetic test body."""
from __future__ import annotations

import sys

import numpy as np
import trimesh

sys.stdout.reconfigure(encoding="utf-8")

import synlab.observe.synthetic_extras as se
from synlab.observe.routes import resolve_target

m = trimesh.creation.box(extents=(120.0, 100.0, 40.0))
n = len(m.faces)
m.metadata["face_attr_arrays"] = {
    "origin_kind": np.full(n, 1, dtype=np.uint8),
    "interface_id": np.where(np.arange(n) % 3 == 0, 0, -1).astype(np.int32),
}
t = resolve_target({"mesh": m, "fragment_id": "F001", "component_id": "C001"})
p = se.resolve_profile(None)
size = se._extras_size(p, 48)
fr = se._turntable_frame(view_id="v", profile=p, size=size,
                        center=se._bbox_center(t.bbox))
print("frame", p.profile_id, size, "K00", round(float(fr.K[0, 0]), 3), "cx", fr.K[0, 2])

try:
    cal = se.synthesize_calibration(profile=p, frame=fr, target=t,
                                    rng=np.random.default_rng(0))
    print("cal ok uv", np.round(cal["target_corners_uv"], 2).tolist(),
          "resid", float(cal["roundtrip_residual_mm"].max()))
except Exception as exc:
    print("cal FAIL", type(exc).__name__, exc)

res = se.generate_synthetic_extras(t, master_seed=20261001, lineage_id="LIN0000",
                                   long_edge_px=48, rotation_step_deg=45.0)
print("total", round(res.seconds, 2))
for b in res.bundles:
    print(f"{b.modality_id:<28} ok={b.ok} t={b.seconds:6.2f}s "
          f"bytes={b.array_bytes():>8} {b.failure or ''}")

for mid in ("photometric_normals", "dense_depth_reliable", "hard_sync_stereo",
            "continuous_rotation", "synthetic_calibration", "auto_flip_second_set"):
    b = res.by_id(mid)
    if not b.ok:
        continue
    ann = b.annotation
    print(mid, "->",
          {k: ann.get(k) for k in ("ps_vs_geom_angle_median_deg", "ps_valid_fraction",
                                   "depth_source", "cross_check_max_delta_mm",
                                   "silhouette_valid_fraction", "disparity_median_px",
                                   "n_views", "sweep_deg", "calibrated",
                                   "calibration_source", "roundtrip_max_residual_mm",
                                   "front_back_overlap_iou") if ann.get(k) is not None})
