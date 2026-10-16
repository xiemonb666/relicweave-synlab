"""Scratch smoke: renderer dispatch through routes/api on the real mother asset.

Measures what the new tests will cost so the test file stays bounded.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

from synlab.mothers.api import create_mother, default_params
from synlab.observe.api import observe
from synlab.observe.render import BACKEND_BLENDER, BACKEND_SOFTWARE, RenderSpec
from synlab.observe.routes import (ObsSpec, render_views, resolve_render_backend,
                                   resolve_target)
from synlab.cameras.api import camera_profiles
from synlab.seeds import make_rng

OUT = Path(__file__).with_name("smoke_dispatch.json")


def main() -> int:
    out: dict[str, object] = {}
    mother = create_mother("V13", "M01", default_params("V13"),
                           make_rng(7, "smoke", "V13"), mother_id="V13-smoke")
    target = resolve_target(mother, None)
    out["target"] = {"fragment_id": target.fragment_id, "n_faces": target.n_faces,
                     "tags": sorted(int(v) for v in np.unique(target.surface_tag)),
                     "meta_keys": sorted(target.meta)}
    profile = camera_profiles()[0]
    out["profile"] = {"id": profile.profile_id, "image_size": list(profile.image_size),
                      "model": profile.meta.get("camera_model"),
                      "dist": np.asarray(profile.dist).tolist()}

    # -- 1. tiny software render through the route (default renderer)
    spec = ObsSpec(view_count=2, delivered_size=(96, 72), max_render_pixels=96 * 72,
                   render_spec=RenderSpec(supersample=1), master_seed=7,
                   lineage_id="smoke")
    t0 = time.perf_counter()
    bundles = render_views(target, profile, spec, make_rng(7, "smoke", "sw"))
    out["software"] = {"seconds": time.perf_counter() - t0,
                       "backend": bundles[0].render.backend,
                       "render_size": list(bundles[0].render_frame.image_size),
                       "delivered_size": list(bundles[0].imaging.image.shape[:2][::-1]),
                       "distortion": bundles[0].distortion}
    del bundles

    # -- 2. tiny Blender render through the route (undistort policy)
    if resolve_render_backend("blender", verify_available=False) == BACKEND_BLENDER:
        from synlab.observe.blender import find_blender_binary
        out["blender_binary"] = find_blender_binary()
        for policy in ("error", "undistort"):
            bspec = ObsSpec(view_count=1, delivered_size=(96, 72), max_render_pixels=96 * 72,
                            render_spec=RenderSpec(supersample=1), master_seed=7,
                            lineage_id="smoke", renderer="blender", distortion_policy=policy)
            t0 = time.perf_counter()
            try:
                bb = render_views(target, profile, bspec, make_rng(7, "smoke", policy),
                                  backend="blender",
                                  blender_config=_cfg(Path(__file__).with_name(f"work_{policy}")))
                out[f"blender_{policy}"] = {
                    "seconds": time.perf_counter() - t0,
                    "backend": bb[0].render.backend,
                    "render_size": list(bb[0].render_frame.image_size),
                    "frame_model": bb[0].render_frame.camera_model,
                    "frame_dist": None if bb[0].render_frame.dist is None
                    else np.asarray(bb[0].render_frame.dist).tolist(),
                    "samples_used": bb[0].render.meta.get("samples_used"),
                    "blender_version": bb[0].render.meta.get("blender_version"),
                    "distortion": bb[0].distortion,
                }
            except Exception as exc:  # noqa: BLE001
                out[f"blender_{policy}"] = {"error": f"{type(exc).__name__}: {exc}"[:400]}
        del bb  # noqa: F821 - only on success

    # -- 3. api-level dispatch on a small spec
    t0 = time.perf_counter()
    obs = observe(mother, None, make_rng(7, "smoke", "api"), route="ideal_visible", spec=spec)
    out["api_software"] = {"seconds": time.perf_counter() - t0,
                           "renderer": obs.meta.get("renderer"),
                           "renderer_requested": obs.meta.get("renderer_requested"),
                           "view_backend": obs.views[0].meta.get("render_backend"),
                           "view_backend_class": obs.views[0].meta.get("render_backend_class")}
    t0 = time.perf_counter()
    try:
        observe(mother, None, make_rng(7, "smoke", "api-b"), route="ideal_visible", spec=spec,
                renderer="blender")
        out["api_blender_default_policy"] = {"note": "no error!"}
    except Exception as exc:  # noqa: BLE001
        out["api_blender_default_policy"] = {
            "seconds": time.perf_counter() - t0,
            "error": f"{type(exc).__name__}: {exc}"[:300],
            "code": str(getattr(exc, "code", None))}

    # -- 4. the real generation config keeps the software default
    from synlab.config import load_generation_spec
    from synlab.pipeline import _resolve_observe_spec
    spec_gen = load_generation_spec("configs/a12/next_experiment.yaml")
    projected = _resolve_observe_spec(spec_gen, None)
    out["generation_config"] = {
        "observation_renderer": str(spec_gen.observation.renderer),
        "projected_renderer": str(projected.renderer),
        "projected_backend": resolve_render_backend(spec=projected),
        "projected_distortion_policy": str(projected.distortion_policy),
        "views": int(projected.view_count),
        "delivered_size": list(projected.delivered_size),
    }
    OUT.write_text(json.dumps(out, indent=2, sort_keys=True, default=str), encoding="utf-8")
    print(json.dumps(out, indent=2, sort_keys=True, default=str))
    return 0


def _cfg(workdir: Path):
    from synlab.observe.blender import BlenderBackendConfig

    return BlenderBackendConfig(samples=8, filter_width=1.5, f_number=8.0,
                                raycast_samples=200, run_label="smoke",
                                workdir=str(workdir))


if __name__ == "__main__":
    raise SystemExit(main())
