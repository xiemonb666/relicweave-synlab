"""Debug 3: run one ROI frame through the Blender worker and report its camera self-check."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from synlab.cameras.profiles import camera_profiles  # noqa: E402
from synlab.errors import SynLabError  # noqa: E402
from synlab.observe import fracture_roi as fr  # noqa: E402
from synlab.observe import routes as rt  # noqa: E402
from synlab.observe.blender import BlenderBackendConfig  # noqa: E402
from synlab.observe.render import RenderSpec  # noqa: E402
from synlab.seeds import make_rng  # noqa: E402
from synlab.storage.mesh_io import arrays_to_mesh  # noqa: E402
from synlab.storage.store import AssetStore  # noqa: E402

store = AssetStore(ROOT / "data/a12_campaign/store")
mesh, _ = arrays_to_mesh(store.load_arrays("asset_745a78313d0d5b045b3a"))
target = rt.resolve_target({"mesh": mesh, "fragment_id": "F1"}, "F1")
cfg = fr.load_fracture_roi_config()
p = {x.tier: x for x in camera_profiles()}
prof = fr.closeup_profile(cfg, base=p["LOCAL"], delivered_long_edge_px=1024)
rois = fr.fracture_rois(target, cfg, footprint_radius_mm=37.4)
spec = rt.ObsSpec(view_count=1, delivered_size=(1024, 768), max_render_pixels=1024 * 1024,
                  render_spec=RenderSpec(supersample=1), renderer="blender",
                  distortion_policy=rt.DISTORTION_POLICY_IGNORE,
                  blender_config=BlenderBackendConfig(samples=4, device="GPU",
                                                      compute_device_type="AUTO",
                                                      gpu_require=True))
rng = make_rng(7, "dbg", "camera")
frames = fr.make_fracture_roi_frames(rois=rois[:1], profile=prof, spec=spec, config=cfg,
                                     long_edge_px=1024, rng=rng, mesh=mesh)
print("n_frames", len(frames))
print("profile", prof.profile_id, prof.image_size, "K", np.asarray(prof.K).tolist())
for frame in frames[:2]:
    eye = np.asarray(frame.T_WC[:3, 3])
    aim = np.asarray(frame.meta["roi_aim_mm"])
    inside = None
    try:
        inside = bool(mesh.contains(eye.reshape(1, 3))[0])
    except Exception as exc:  # noqa: BLE001
        inside = f"contains() failed: {type(exc).__name__}"
    print(f"\n{frame.view_id} off={frame.meta['direction_offset_deg']} eye={eye.round(2).tolist()} "
          f"aim={aim.round(2).tolist()} eye_inside_mesh={inside}")
    try:
        bundles, seconds = fr.render_fracture_roi_views(target=target, frames=[frame], spec=spec,
                                                        rng=rng, backend="blender")
        print("  OK", seconds, "s")
    except SynLabError as exc:
        print("  FAILED", exc.code, exc.message[:400])
        print("  measurements:", json.dumps(exc.measurements, default=str)[:1500])
