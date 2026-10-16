"""Sweep declared render settings to find a variant with a non-empty deployable mask."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402

from synlab.config import load_generation_spec  # noqa: E402
from synlab.observe.render import RenderSpec, deployment_mask_from_render  # noqa: E402
from synlab.observe.routes import ObsSpec, render_views, resolve_target  # noqa: E402
from synlab.seeds import make_rng  # noqa: E402
from synlab.storage.mesh_io import arrays_to_mesh  # noqa: E402
from synlab.storage.store import AssetStore  # noqa: E402


def main() -> None:
    store = AssetStore(sys.argv[1])
    spec_obj = load_generation_spec("configs/a12/sandbox.yaml")
    phys = store.list_assets(role="physical_component", limit=1)[0]
    mesh, _ = arrays_to_mesh(store.load_arrays(phys.asset_id))
    target = resolve_target({"mesh": mesh, "fragment_id": "probe"}, None)
    from synlab.observe.api import _resolve_profile

    profile = _resolve_profile(None)
    variants = [
        {"edge": 512, "delivered": (512, 384), "max_px": 512 * 384,
         "coc": 32.0, "supersample": 2},
        {"edge": 512, "delivered": (512, 384), "max_px": 512 * 384,
         "coc": 56.0, "supersample": 2},
        {"edge": 512, "delivered": (512, 384), "max_px": 512 * 384,
         "coc": 128.0, "supersample": 2},
        {"edge": 512, "delivered": (512, 384), "max_px": 512 * 384,
         "coc": 1e6, "supersample": 2},
    ]
    out = []
    for variant in variants:
        obs_spec = ObsSpec(view_count=1, delivered_size=variant["delivered"],
                           max_render_pixels=variant["max_px"],
                           render_spec=RenderSpec(coc_px_threshold=variant["coc"],
                                                  supersample=variant["supersample"]),
                           master_seed=spec_obj.master_seed, lineage_id="sweep")
        rng = make_rng(spec_obj.master_seed, "sweep", str(variant))
        try:
            bundles = render_views(target, profile, obs_spec, rng)
        except Exception as exc:  # noqa: BLE001
            out.append({**variant, "error": f"{type(exc).__name__}: {exc}"})
            continue
        for bundle in bundles[:1]:
            render = bundle.render
            dep = deployment_mask_from_render(render)
            out.append({
                **{k: (list(v) if isinstance(v, tuple) else v) for k, v in variant.items()},
                "view_id": bundle.frame.view_id,
                "f_px": float(0.5 * (bundle.render_frame.K[0, 0]
                                     + bundle.render_frame.K[1, 1])),
                "working_distance_mm": float(bundle.render_frame.working_distance_mm),
                "render_shape": list(np.asarray(render.id_map).shape),
                "id_ok": int((np.asarray(render.id_map) >= 0).sum()),
                "vis_gt0": int((np.asarray(render.visibility) > 0).sum()),
                "uncertain": int(np.asarray(render.uncertain_mask).sum()),
                "coc_p50": float(np.nanmedian(np.asarray(render.depth_z))),
                "dep_px": int(np.asarray(dep).sum()),
                "dep_shape": list(np.asarray(dep).shape),
                "delivered_shape": list(np.asarray(bundle.imaging.image).shape),
            })
    print(json.dumps(out, ensure_ascii=False, indent=1)[:7000])


if __name__ == "__main__":
    main()
