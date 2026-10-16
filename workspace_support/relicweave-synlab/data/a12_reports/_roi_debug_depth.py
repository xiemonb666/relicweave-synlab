"""Debug: does the rendered centre depth agree with the ray-cast distance to the ROI aim point?"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from synlab.observe import fracture_roi as fr  # noqa: E402
from synlab.observe import routes as rt  # noqa: E402
from synlab.observe.render import RenderSpec  # noqa: E402
from synlab.seeds import make_rng  # noqa: E402
from synlab.storage.mesh_io import arrays_to_mesh  # noqa: E402
from synlab.storage.store import AssetStore  # noqa: E402

store = AssetStore(ROOT / "data/a12_campaign/store")
asset = store.get_asset("asset_745a78313d0d5b045b3a")
mesh, _ = arrays_to_mesh(store.load_arrays("asset_745a78313d0d5b045b3a"))
target = rt.resolve_target({"mesh": mesh, "fragment_id": "F1"}, "F1")
cfg = fr.load_fracture_roi_config()
prof = fr.closeup_profile(cfg, delivered_long_edge_px=1024)
rois = fr.fracture_rois(target, cfg, footprint_radius_mm=37.4)
spec = rt.ObsSpec(view_count=1, delivered_size=(1024, 769), max_render_pixels=1024 * 1024,
                  render_spec=RenderSpec(supersample=1), renderer="software_rasterizer",
                  distortion_policy=rt.DISTORTION_POLICY_IGNORE)
rng = make_rng(7, "dbg", "camera")
frames = fr.make_fracture_roi_frames(rois=rois[:1], profile=prof, spec=spec, config=cfg,
                                     long_edge_px=1024, rng=rng, mesh=mesh)
bundles, _ = fr.render_fracture_roi_views(target=target, frames=frames, spec=spec, rng=rng,
                                          backend="software_rasterizer")
report = []
for frame, bundle in zip(frames, bundles):
    K = np.asarray(bundle.render_frame.K, dtype=np.float64)
    depth = np.asarray(bundle.render.depth_z, dtype=np.float64)
    aim = np.asarray(rois[0].aim_mm, dtype=np.float64)
    eye = np.asarray(frame.T_WC[:3, 3], dtype=np.float64)
    forward = np.asarray(frame.T_WC[:3, 2], dtype=np.float64)
    direction = (aim - eye) / np.linalg.norm(aim - eye)
    loc, idx, _tri = mesh.ray.intersects_location(eye.reshape(1, 3), direction.reshape(1, 3),
                                                  multiple_hits=False)
    first = float(np.linalg.norm(loc[0] - eye)) if len(loc) else float("nan")
    cx, cy = int(round(float(K[0, 2]))), int(round(float(K[1, 2])))
    window = depth[max(cy - 4, 0):cy + 5, max(cx - 4, 0):cx + 5]
    wv = window[np.isfinite(window) & (window > 0)]
    report.append({
        "view_id": frame.view_id,
        "offset_deg": frame.meta["direction_offset_deg"],
        "phi_deg": frame.meta["direction_in_plane_deg"],
        "eye_mm": eye.tolist(), "aim_mm": aim.tolist(),
        "|eye-aim|": float(np.linalg.norm(aim - eye)),
        "dot(forward,dir_to_aim)": float(np.dot(forward, direction)),
        "raycast_first_hit_mm": first,
        "depth_centre_median_mm": float(np.median(wv)) if wv.size else float("nan"),
        "depth_at_aim_projected": None,
    })
    # project the aim point with the render K and the camera axes
    R = np.asarray(frame.T_WC[:3, :3], dtype=np.float64)
    x_cam = R.T @ (aim - eye)
    u = float(K[0, 0] * x_cam[0] / x_cam[2] + K[0, 2])
    v = float(K[1, 1] * x_cam[1] / x_cam[2] + K[1, 2])
    report[-1]["aim_projected_px"] = [u, v]
    report[-1]["depth_at_aim_px"] = (float(depth[int(round(v)), int(round(u))])
                                     if 0 <= int(round(v)) < depth.shape[0]
                                     and 0 <= int(round(u)) < depth.shape[1] else None)
print(json.dumps(report, indent=1, default=str))
