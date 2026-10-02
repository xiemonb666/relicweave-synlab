"""Diagnose the G01 correlated-depth-field crash on a committed physical component.

Loads the representative ``physical_component`` of one lineage from a store, resolves the
*pipeline's own* observation spec for that store, and runs ``route_proxy_scan`` step by step so the
measured ``render_mm_per_px`` / sigma / correlation values are printed before the OpenCV call.

Usage: python tests/a12/observe/_probe_g01_crash.py --root data/a12_iface/store --lineage LIN0001_V02_M01_PAT01
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import traceback
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="data/a12_iface/store")
    ap.add_argument("--lineage", default=None)
    ap.add_argument("--config", default="configs/a12/sandbox.yaml")
    args = ap.parse_args(argv)
    root = Path(args.root)

    from synlab.config import load_generation_spec
    from synlab.observe import routes as rt
    from synlab.pipeline import _resolve_observe_spec
    from synlab.registry import load_all
    from synlab.seeds import make_rng
    from synlab.storage.store import AssetStore

    load_all()
    store = AssetStore(root)
    lineage = args.lineage
    if lineage is None:
        records = store.list_assets(role="physical_component")
        lineage = str(records[0].lineage_id) if records else None
    print("lineage:", lineage)
    records = [r for r in store.list_assets(role="physical_component")
               if str(r.lineage_id) == lineage]
    if not records:
        print("no physical_component for this lineage")
        return 1
    record = records[-1]
    arrays = store.load_arrays(record.asset_id)
    flat = {k: v for k, v in arrays.items() if not k.endswith(".vertices")}
    if "vertices" in flat:
        selected = flat
    else:  # nested ``mesh.*`` layout
        selected = {k.split(".", 1)[1]: v for k, v in arrays.items()
                    if k.startswith("mesh.")}
    from synlab.storage.mesh_io import arrays_to_mesh

    mesh, attrs = arrays_to_mesh({k: v for k, v in selected.items()
                                  if k in ("vertices", "faces") or k.startswith("face__")})
    print("component:", record.asset_id, "faces:", len(mesh.faces),
          "face attrs:", sorted(attrs))
    print("provenance:", json.dumps(record.meta.get("face_provenance"), default=str)[:600])

    target = rt.resolve_target({"mesh": mesh, "fragment_id": record.meta.get("ancestor", "frag")},
                               None)
    print("surface_tag_source:", target.meta.get("surface_tag_source"),
          "tag histogram:", target.meta.get("surface_tag_face_histogram"))

    gen_spec = load_generation_spec(args.config)
    plan = _resolve_observe_spec(gen_spec, store)
    obs_spec = getattr(plan, "obs_spec", plan)
    print("obs spec: views:", obs_spec.view_count, "delivered:", obs_spec.delivered_size,
          "max_render_pixels:", obs_spec.max_render_pixels, "renderer:", obs_spec.renderer)
    print("route_params:", json.dumps(getattr(obs_spec, "route_params", {}), default=str)[:600])

    from synlab.cameras.api import camera_profiles
    profile = camera_profiles()[1]
    rng = make_rng(20261001, str(lineage), "camera")
    try:
        bundles = rt.render_views(target, profile, obs_spec, rng, backend="software_rasterizer")
    except Exception:
        traceback.print_exc()
        return 3
    for index, bundle in enumerate(bundles):
        frame = bundle.render_frame
        print(f"view {index}: render_mm_per_px={bundle.render_mm_per_px!r} "
              f"wd={frame.working_distance_mm!r} fx={float(frame.K[0, 0])!r} "
              f"K={np.asarray(frame.K).ravel()[:4].tolist()} tier={frame.tier} "
              f"depth_shape={np.asarray(bundle.render.depth_z).shape}")
        tag = np.asarray(bundle.render.surface_tag)
        values, counts = np.unique(tag, return_counts=True)
        print(f"   render.surface_tag histogram: {dict(zip(values.tolist(), counts.tolist()))}")
    params = dict(getattr(obs_spec, "route_params", {}) or {})
    depth_sigma = float(params.get("depth_error_sigma_mm", 0.35))
    depth_corr = float(params.get("depth_error_correlation_mm", 8.0))
    pitch = bundles[0].render_mm_per_px if bundles else float("nan")
    sigma_px = max(depth_corr / max(pitch, 1e-9), 0.5)
    print(f"G01: depth_sigma={depth_sigma} correlation_mm={depth_corr} pitch={pitch!r} "
          f"-> sigma_px={sigma_px!r}")
    try:
        import cv2

        white = np.random.default_rng(0).standard_normal((64, 64))
        cv2.GaussianBlur(white, (0, 0), sigmaX=sigma_px, sigmaY=sigma_px,
                         borderType=cv2.BORDER_REFLECT101)
        print("GaussianBlur with the measured sigma: OK on a 64x64 probe")
    except Exception as exc:  # noqa: BLE001
        print("GaussianBlur with the measured sigma FAILED:", type(exc).__name__, exc)
    try:
        observation, _ = rt.route_proxy_scan(target, profile, obs_spec, rng,
                                             backend="software_rasterizer")
        block = observation.meta.get("surface_tag_pixels", {})
        print("route_proxy_scan OK: rim_pixels:", block.get("rim_pixels"),
              "tag_source:", observation.meta.get("surface_tag_source"))
    except Exception as exc:  # noqa: BLE001
        print("route_proxy_scan FAILED:", type(exc).__name__, exc)
        traceback.print_exc()
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
