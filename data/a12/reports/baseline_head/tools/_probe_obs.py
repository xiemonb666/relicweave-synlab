"""Probe one real observation: deploy mask / id_map / visibility statistics."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402

from synlab.storage.store import AssetStore  # noqa: E402


def main() -> None:
    store = AssetStore(sys.argv[1])
    obs_assets = store.list_assets(role="obs_result", limit=10)
    out = []
    for asset in obs_assets:
        from synlab.observe.api import load_observation

        obs = load_observation(store, asset.asset_id)
        arrays = store.load_arrays(asset.asset_id)
        entry = {
            "asset_id": asset.asset_id,
            "qa_status": asset.qa_status,
            "route": obs.route,
            "n_views": len(obs.views),
            "fragment_id": obs.fragment_id,
            "scale_valid": bool(obs.scale_valid),
            "points": int(np.asarray(obs.points).shape[0]),
            "point_valid": int(np.asarray(obs.point_valid).sum()),
            "meta_keys": sorted(dict(asset.meta or {}).keys()),
            "array_keys": sorted(arrays.keys()),
            "views": [],
        }
        for view in obs.views:
            dep = np.asarray(getattr(view, "deployment_mask", np.zeros((0, 0), bool)), bool)
            idm = np.asarray(getattr(view, "id_map", np.full((0, 0), -1)), np.int64)
            vis = np.asarray(getattr(view, "visibility", np.zeros((0, 0))), np.float64)
            unc = np.asarray(getattr(view, "uncertain_mask", np.zeros((0, 0), bool)), bool)
            rgb = np.asarray(getattr(view, "rgb", np.zeros((0, 0, 3))), np.float64)
            entry["views"].append({
                "view_id": str(view.view_id),
                "deploy_px": int(dep.sum()), "deploy_shape": list(dep.shape),
                "id_ok_px": int((idm >= 0).sum()),
                "vis_gt0_px": int((vis > 0).sum()),
                "vis_shape": list(vis.shape),
                "uncertain_px": int(unc.sum()),
                "rgb_shape": list(rgb.shape),
                "rgb_min": float(rgb.min()) if rgb.size else None,
                "rgb_max": float(rgb.max()) if rgb.size else None,
                "source_kind": str(getattr(view, "source_kind", "")),
                "roi_px": int(np.asarray(getattr(view, "roi", np.zeros((0, 0), bool)), bool).sum()),
            })
        out.append(entry)
    print(json.dumps(out, ensure_ascii=False, indent=1)[:9000])


if __name__ == "__main__":
    main()
