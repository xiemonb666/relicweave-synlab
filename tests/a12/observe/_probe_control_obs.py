"""Scratch probe: inspect the observations committed by the control leg (not a test)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from synlab.observe.api import load_observation  # noqa: E402
from synlab.roles import ROLE_OBS_RESULT  # noqa: E402
from synlab.storage.store import AssetStore  # noqa: E402


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "data" / "a12_realistic"
                / "control_ideal")
    lineage = sys.argv[2] if len(sys.argv) > 2 else None
    store = AssetStore(root)
    records = [r for r in store.list_assets(role=ROLE_OBS_RESULT)
               if lineage is None or r.lineage_id == lineage]
    out = []
    for record in records[:4]:
        obs = load_observation(store, record.asset_id)
        views = []
        for view in obs.views:
            mask = np.asarray(view.deployment_mask, dtype=bool)
            depth = np.asarray(view.depth_z)
            valid = np.isfinite(depth) & (depth > 0)
            views.append({
                "view_id": view.view_id,
                "mask_coverage": float(np.mean(mask)),
                "mask_in_mask_depth_valid": float(np.mean(valid[mask])) if mask.any() else None,
                "depth_valid": float(np.mean(valid)),
                "uncertain": float(np.mean(view.uncertain_mask)),
                "rgb_mean": float(np.mean(view.rgb)),
                "rgb_max": int(np.max(view.rgb)),
                "image_size": list(np.asarray(view.rgb).shape[:2][::-1]),
                "backend": (view.meta or {}).get("render_backend"),
                "labels": list((view.meta or {}).get("imaging_labels") or []),
            })
        out.append({
            "asset_id": record.asset_id,
            "lineage_id": record.lineage_id,
            "route": obs.route,
            "route_status": (obs.meta or {}).get("route_status"),
            "n_points": int(np.asarray(obs.points).shape[0]),
            "renderer": (obs.meta or {}).get("renderer"),
            "distortion_policy": (obs.meta or {}).get("distortion_policy"),
            "backend_failure": (obs.backend_report or {}).get("failure_code"),
            "backend_failure_reason": ((obs.backend_report or {}).get("failure_reason") or "")[:200],
            "reconstruction": (obs.backend_report or {}).get("reconstruction"),
            "n_input_images": (obs.backend_report or {}).get("n_input_images"),
            "mask_files": (obs.backend_report or {}).get("mask_files"),
            "argv_log": [(e.get("argv", [""])[0], e.get("status"), round(e.get("seconds") or 0, 2))
                         for e in ((obs.backend_report or {}).get("argv_log") or [])],
            "views": views,
        })
    print(json.dumps(out, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
