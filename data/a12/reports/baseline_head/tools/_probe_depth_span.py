"""Report the actual depth span of a fragment as seen by the camera (diagnostic)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402

from synlab.config import load_generation_spec  # noqa: E402
from synlab.observe.render import RenderSpec, circle_of_confusion_px  # noqa: E402
from synlab.observe.routes import ObsSpec, render_views, resolve_target  # noqa: E402
from synlab.seeds import make_rng  # noqa: E402
from synlab.storage.mesh_io import arrays_to_mesh  # noqa: E402
from synlab.storage.store import AssetStore  # noqa: E402


def main() -> None:
    store = AssetStore(sys.argv[1])
    spec_obj = load_generation_spec("configs/a12/sandbox.yaml")
    out = []
    for phys in store.list_assets(role="physical_component", limit=3):
        mesh, _ = arrays_to_mesh(store.load_arrays(phys.asset_id))
        target = resolve_target({"mesh": mesh, "fragment_id": "probe"}, None)
        from synlab.observe.api import _resolve_profile

        profile = _resolve_profile(None)
        obs_spec = ObsSpec(view_count=1, delivered_size=(1024, 768),
                           max_render_pixels=1024 * 768,
                           render_spec=RenderSpec(supersample=1), master_seed=7,
                           lineage_id="depth")
        bundles = render_views(target, profile, obs_spec,
                               make_rng(7, "depth", phys.asset_id))
        for bundle in bundles[:1]:
            rf = bundle.render_frame
            depth = np.asarray(bundle.render.depth_z, dtype=np.float64)
            valid = np.isfinite(depth) & (depth > 0)
            f_px = float(0.5 * (rf.K[0, 0] + rf.K[1, 1]))
            z = depth[valid]
            entry = {
                "asset_id": phys.asset_id,
                "bbox_mm": list(np.asarray(mesh.bounds[1] - mesh.bounds[0]).round(1)),
                "working_distance_mm": float(rf.working_distance_mm),
                "focus_distance_mm": float(rf.working_distance_mm),
                "f_px": f_px,
                "n_valid": int(valid.sum()),
                "z_min_mm": float(z.min()), "z_p05": float(np.percentile(z, 5)),
                "z_median_mm": float(np.median(z)), "z_p95": float(np.percentile(z, 95)),
                "z_max_mm": float(z.max()),
            }
            for threshold in (0.75, 6.0, 24.0):
                coc = circle_of_confusion_px(depth, rf.working_distance_mm, 1.0, f_px)
                entry[f"uncertain_at_{threshold}"] = int(np.sum((coc > threshold) & valid))
            # what aperture would keep the whole object inside the declared CoC?
            f_min = f_px
            zf = float(rf.working_distance_mm)
            coc_unit = (f_min ** 2 / (1.0 * np.maximum(z, 1e-6)) * np.abs(z - zf) / zf)
            entry["required_f_number_for_0p75px"] = float(np.ceil(
                0.75 ** -1 * float(np.max(coc_unit))))
            out.append(entry)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
