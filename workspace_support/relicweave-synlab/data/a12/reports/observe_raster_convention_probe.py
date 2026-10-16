"""Probe the raster conventions of ``synlab/observe/routes.py`` around hole carving.

Two measurements, both on the real route code (no mocking of the renderer):

1. **route-level hole carving.**  ``route_proxy_scan`` at ``delivered_size=(320, 240)`` with
   ``route_params={'hole_count': 2}`` - the configuration that was independently reported to
   raise ``IndexError`` - for several master seeds: does it run, how many discs were clipped at
   the raster edge, and how long does one view take.
2. **raster orientation of the mask handed to the imaging chain.**  ``render_views`` calls
   ``_resize_to(render.uncertain_mask, render_size)`` while ``derivation()`` returns
   ``(render_w, render_h)`` but ``_resize_to`` reads ``size`` as ``(h, w)``.  The probe records
   the actual shapes and measures what that does to the delivered ``uncertain_mask`` channel by
   running the same imaging chain twice with identically seeded rngs (once with the mask as the
   route builds it, once with the mask oriented like the scene grid).

Usage::

    .venv\\Scripts\\python.exe data\\a12\\reports\\observe_raster_convention_probe.py \
        --out data\\a12\\reports\\observe_raster_convention_probe.json
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from synlab.cameras.api import camera_profiles  # noqa: E402
from synlab.mothers.api import create_mother, default_params  # noqa: E402
from synlab.observe import routes as rt  # noqa: E402
from synlab.observe.imaging import apply_imaging_chain  # noqa: E402
from synlab.observe.render import RenderSpec  # noqa: E402
from synlab.seeds import make_rng  # noqa: E402


def _small_spec(**overrides) -> rt.ObsSpec:
    base = dict(view_count=1, delivered_size=(320, 240), max_render_pixels=320 * 240,
                render_spec=RenderSpec(supersample=1), master_seed=7,
                lineage_id="carve_probe")
    base.update(overrides)
    return rt.ObsSpec(**base)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/a12/reports/observe_raster_convention_probe.json")
    ap.add_argument("--seeds", default="7,11,23,42,101,202,303")
    args = ap.parse_args()
    result: dict = {"route_level": {}, "raster_orientation": {}}

    mother = create_mother("V13", "M01", default_params("V13"),
                           make_rng(7, "carve_probe", "V13"), mother_id="V13-carve-probe")
    target = rt.resolve_target(mother, None)
    profile = camera_profiles()[0]
    result["target"] = {"fragment_id": target.fragment_id, "faces": target.n_faces,
                        "profile": profile.profile_id, "profile_image_size":
                            list(profile.image_size)}

    # ---------------------------------------------------------------- 1. route level
    for seed in [int(s) for s in args.seeds.split(",")]:
        spec = _small_spec(master_seed=seed, route_params={"hole_count": 2, "stride": 1})
        render_size, x0, y0, sx, sy = spec.derivation(profile.image_size)
        entry: dict = {"seed": seed, "render_size_wh": list(render_size),
                       "crop_origin_xy": [x0, y0], "scale_xy": [sx, sy]}
        t0 = time.time()
        try:
            obs, bundles = rt.route_proxy_scan(target, profile, spec,
                                               make_rng(seed, "carve_probe", "proxy"))
        except Exception as exc:  # noqa: BLE001 - a failure here is the measurement
            entry.update({"ok": False, "error": f"{type(exc).__name__}: {exc}",
                          "traceback_tail": traceback.format_exc().strip().splitlines()[-4:]})
        else:
            g03 = obs.backend_report["degradations"]["G03_holes"]
            entry.update({
                "ok": True,
                "wall_s": round(time.time() - t0, 3),
                "depth_shapes": [list(np.asarray(b.render.depth_z).shape) for b in bundles],
                "delivered_depth_shapes": [list(np.asarray(v.depth_z).shape) for v in obs.views],
                "requested_holes": int(g03["requested"]),
                "clip_rule": g03.get("clip_rule"),
                "clipped_count": int(g03.get("clipped_count", -1)),
                "clipped": g03.get("clipped"),
                "nan_pixels_per_view": [int(np.count_nonzero(~np.isfinite(np.asarray(b.render.depth_z))))
                                        for b in bundles],
            })
        result["route_level"][f"seed{seed}"] = entry

    # ---------------------------------------------------------------- 2. raster orientation
    spec = _small_spec(route_params={"hole_count": 0})
    bundles = rt.render_views(target, profile, spec, make_rng(7, "carve_probe", "orient"))
    bundle = bundles[0]
    render_size, x0, y0, sx, sy = spec.derivation(profile.image_size)
    render_hw = tuple(int(s) for s in np.asarray(bundle.render.depth_z).shape)
    uncertain_hw = tuple(int(s) for s in np.asarray(bundle.render.uncertain_mask).shape)
    as_route = rt._resize_to(bundle.render.uncertain_mask, render_size)
    as_scene = rt._resize_to(bundle.render.uncertain_mask, (render_hw[0], render_hw[1]))
    deliver_hw = tuple(int(s) for s in np.asarray(bundle.imaging.image).shape[:2])
    result["raster_orientation"] = {
        "derivation_render_size": list(render_size),
        "render_frame_image_size": list(bundle.render_frame.image_size),
        "render_depth_shape_hw": list(render_hw),
        "render_uncertain_mask_shape_hw": list(uncertain_hw),
        "mask_as_the_route_builds_it_shape_hw": list(as_route.shape),
        "mask_oriented_like_the_scene_shape_hw": list(as_scene.shape),
        "route_call_is_transposed": bool(as_route.shape != as_scene.shape),
        "delivered_image_shape_hw": list(deliver_hw),
        "delivered_uncertain_mask_shape_hw": list(np.asarray(bundle.imaging.uncertain_mask).shape),
        "deploy_mask_shape_hw": list(np.asarray(bundle.deploy_mask).shape),
        "roi_shape_hw": list(np.asarray(bundle.roi).shape),
    }
    # -- A/B: identical scene, identical sensor rng seed, only the mask orientation differs.
    #    The imaging spec is rebuilt exactly as render_views builds it (crop_origin/resize_scale
    #    from derivation), so the only difference between the two runs is the mask orientation.
    def _ab_for(spec_ab: rt.ObsSpec, label: str) -> dict:
        bundles_ab = rt.render_views(target, profile, spec_ab,
                                     make_rng(7, "carve_probe", "orient_" + label))
        b = bundles_ab[0]
        rs, cx0, cy0, csx, csy = spec_ab.derivation(profile.image_size)
        rhw = tuple(int(s) for s in np.asarray(b.render.depth_z).shape)
        as_route_ = rt._resize_to(b.render.uncertain_mask, rs)
        as_scene_ = rt._resize_to(b.render.uncertain_mask, (rhw[0], rhw[1]))
        imaging_spec = copy.copy(spec_ab.imaging)
        imaging_spec.crop_origin = (cx0, cy0)
        imaging_spec.resize_scale = (csx, csy)
        out: dict = {"delivered_size": list(spec_ab.delivered_size),
                     "render_size_wh": list(rs), "render_shape_hw": list(rhw),
                     "render_uncertain_true_px": int(np.count_nonzero(b.render.uncertain_mask)),
                     "crop_origin_xy": [cx0, cy0],
                     "mask_as_route_shape_hw": list(as_route_.shape),
                     "mask_as_scene_shape_hw": list(as_scene_.shape),
                     "route_call_is_transposed": bool(as_route_.shape != as_scene_.shape)}
        masks: dict[str, np.ndarray] = {}
        for name, mask in (("as_route", as_route_), ("as_scene", as_scene_)):
            rng = np.random.Generator(np.random.PCG64(np.uint64(1234)))
            res = apply_imaging_chain(
                np.asarray(b.render.rgb_linear, dtype=np.float32),
                K=np.asarray(b.render_frame.K, dtype=np.float64),
                dist=b.render_frame.dist,
                uncertain_mask=mask,
                depth_z=np.asarray(b.render.depth_z, dtype=np.float32),
                focus_distance_mm=float(b.render_frame.working_distance_mm),
                rng=rng,
                spec=imaging_spec,
                camera_model=str(b.render_frame.camera_model or "PINHOLE"),
            )
            masks[name] = np.asarray(res.uncertain_mask, dtype=bool)
        out["delivered_mask_shape_as_route"] = list(masks["as_route"].shape)
        out["delivered_mask_shape_as_scene"] = list(masks["as_scene"].shape)
        out["delivered_true_px_as_route"] = int(masks["as_route"].sum())
        out["delivered_true_px_as_scene"] = int(masks["as_scene"].sum())
        out["matches_the_mask_the_route_delivered"] = bool(
            np.array_equal(masks["as_route"],
                           np.asarray(b.imaging.uncertain_mask, dtype=bool)))
        if masks["as_route"].shape == masks["as_scene"].shape:
            diff = int(np.count_nonzero(masks["as_route"] != masks["as_scene"]))
            out.update({"differing_px": diff, "total_px": int(masks["as_route"].size),
                        "differing_fraction": diff / max(int(masks["as_route"].size), 1),
                        "equals_transposed_scene_mask": bool(np.array_equal(
                            masks["as_route"], np.ascontiguousarray(masks["as_scene"].T)))})
        else:
            out["shape_mismatch"] = True
        return out

    try:
        result["raster_orientation"]["ab_landscape_320x240"] = _ab_for(
            _small_spec(route_params={"hole_count": 0}), "landscape")
        result["raster_orientation"]["ab_portrait_240x320_ss3"] = _ab_for(
            _small_spec(delivered_size=(240, 320), view_count=1,
                        render_spec=RenderSpec(supersample=3),
                        route_params={"hole_count": 0}), "portrait")
    except Exception as exc:  # noqa: BLE001 - keep the real error
        result["raster_orientation"]["ab_error"] = f"{type(exc).__name__}: {exc}"

    out_path = ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str),
                        encoding="utf-8")
    print(json.dumps(result["route_level"], ensure_ascii=False, indent=2)[:3000])
    print(json.dumps(result["raster_orientation"], ensure_ascii=False, indent=2)[:3000])
    print(f"written {out_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
