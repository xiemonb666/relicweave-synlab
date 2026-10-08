"""Debug 2: enumerate every ray hit along the camera axis and compare with the depth buffer."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from synlab.observe import fracture_roi as fr  # noqa: E402
from synlab.observe import routes as rt  # noqa: E402
from synlab.observe.render import RenderSpec, build_scene  # noqa: E402
from synlab.seeds import make_rng  # noqa: E402
from synlab.storage.mesh_io import arrays_to_mesh  # noqa: E402
from synlab.storage.store import AssetStore  # noqa: E402

store = AssetStore(ROOT / "data/a12_campaign/store")
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
scene = build_scene(target.mesh, surface_tag=target.surface_tag, face_id=target.face_id,
                    name=target.fragment_id)
report = []
for frame, bundle in zip(frames, bundles):
    depth = np.asarray(bundle.render.depth_z, dtype=np.float64)
    eye = np.asarray(frame.T_WC[:3, 3], dtype=np.float64)
    forward = np.asarray(frame.T_WC[:3, 2], dtype=np.float64)
    loc, idx, tri = mesh.ray.intersects_location(eye.reshape(1, 3), forward.reshape(1, 3),
                                                 multiple_hits=True)
    order = np.argsort(np.linalg.norm(loc - eye, axis=1)) if len(loc) else []
    hits = [float(np.linalg.norm(loc[i] - eye)) for i in order[:6]]
    K = np.asarray(bundle.render_frame.K, dtype=np.float64)
    cx, cy = int(round(float(K[0, 2]))), int(round(float(K[1, 2])))
    report.append({
        "view_id": frame.view_id, "offset_deg": frame.meta["direction_offset_deg"],
        "depth_shape": list(depth.shape), "render_size": list(frame.image_size),
        "render_grid": list(bundle.render_frame.image_size),
        "K_cx_cy": [float(K[0, 2]), float(K[1, 2])],
        "ray_hits_along_axis_mm": hits,
        "depth_at_principal_mm": float(depth[cy, cx]),
        "depth_median_mm": float(np.median(depth[np.isfinite(depth)])),
        "scene_faces": int(np.asarray(scene.faces).shape[0]),
        "mesh_faces": int(len(mesh.faces)),
        "visible_frac": float(np.mean(np.isfinite(depth))),
    })
print(json.dumps(report, indent=1, default=str))
