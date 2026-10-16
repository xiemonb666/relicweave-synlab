"""Probe the observe chain on a real fragment: render -> deploy mask -> imaging -> delivery."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402

from synlab.config import load_generation_spec  # noqa: E402
from synlab.observe.routes import ObsSpec, render_views  # noqa: E402
from synlab.observe.routes import resolve_target  # noqa: E402
from synlab.observe.render import deployment_mask_from_render  # noqa: E402
from synlab.seeds import make_rng  # noqa: E402
from synlab.storage.store import AssetStore  # noqa: E402


def main() -> None:
    store = AssetStore(sys.argv[1])
    spec_obj = load_generation_spec("configs/a12/sandbox.yaml")
    phys = store.list_assets(role="physical_component", limit=1)[0]
    arrays = store.load_arrays(phys.asset_id)
    from synlab.storage.mesh_io import arrays_to_mesh

    mesh, _attrs = arrays_to_mesh(arrays)
    target = resolve_target({"mesh": mesh, "fragment_id": "probe"}, None)
    from synlab.observe.api import _resolve_profile  # noqa: PLC2701

    profile = _resolve_profile(None)
    rng = make_rng(spec_obj.master_seed, "probe", "observe")
    from synlab.pipeline import _resolve_observe_spec

    obs_spec = _resolve_observe_spec(spec_obj, store)
    out = {"n_bundles": 0, "obs_spec": {
        "view_count": obs_spec.view_count,
        "delivered_size": list(obs_spec.delivered_size),
        "max_render_pixels": obs_spec.max_render_pixels,
    }, "views": []}
    bundles = render_views(target, profile, obs_spec, rng)
    out["n_bundles"] = len(bundles)
    for bundle in bundles[:3]:
        render = bundle.render
        dep_raw = deployment_mask_from_render(render)
        rf = bundle.render_frame
        dep_b = np.asarray(bundle.deploy_mask, bool)
        entry = {
            "view_id": bundle.frame.view_id,
            "working_distance_mm": float(rf.working_distance_mm),
            "f_px": float(0.5 * (rf.K[0, 0] + rf.K[1, 1])),
            "coc_threshold": float(obs_spec.render_spec.coc_px_threshold),
            "render_rgb_shape": list(np.asarray(render.rgb_linear).shape),
            "render_idm_ok": int((np.asarray(render.id_map) >= 0).sum()),
            "render_vis_gt0": int((np.asarray(render.visibility) > 0).sum()),
            "render_mixed_id": int(render.meta.get("uncertain_fraction", -1) * 1),
            "render_uncertain": int(np.asarray(render.uncertain_mask).sum()),
            "dep_raw_px": int(np.asarray(dep_raw).sum()),
            "dep_raw_shape": list(np.asarray(dep_raw).shape),
            "dep_bundle_px": int(dep_b.sum()),
            "dep_bundle_shape": list(dep_b.shape),
            "imaging_shape": list(np.asarray(bundle.imaging.image).shape),
            "imaging_uncertain": int(np.asarray(bundle.imaging.uncertain_mask).sum()),
            "roi_px": int(np.asarray(bundle.roi).sum()) if bundle.roi is not None else None,
            "img_uncertain_shape": list(np.asarray(bundle.imaging.uncertain_mask).shape),
        }
        out["views"].append(entry)
    print(json.dumps(out, ensure_ascii=False, indent=1)[:5000])


if __name__ == "__main__":
    main()
