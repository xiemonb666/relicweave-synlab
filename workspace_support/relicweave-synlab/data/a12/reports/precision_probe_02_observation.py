"""precision audit probe 02 - observation precision (dimension 1 + 3 + 7).

Reads every ``obs_result`` / ``label_bundle`` asset in a store **read only** and reports,
per store and per view:

* delivered image size, ``K[0,0]``, median/percentile camera z (depth_z) in mm
* object-space sampling ``px_per_mm = f_px / z`` and ``mm_per_px = z / f_px`` per pixel
* the resolvable feature size implied by that sampling (>=4 px and 6-8 px targets)
* mask coverage: deployment_mask / roi / uncertain_mask true fractions
* surface_tag histogram (rim == 2 is the fracture-interface channel)
* depth error against the analytic camera-z of the render plane when available

Nothing is written back to the store.
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import sqlite3
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[3]


def _pct(a: np.ndarray, q: float) -> float | None:
    a = np.asarray(a, dtype=np.float64)
    a = a[np.isfinite(a)]
    if a.size == 0:
        return None
    return float(np.percentile(a, q))


def store_assets(store: pathlib.Path, roles: tuple[str, ...]) -> list[tuple[str, str, dict]]:
    con = sqlite3.connect(f"file:{store.as_posix()}?mode=ro", uri=True)
    cur = con.cursor()
    q = "SELECT asset_id, role, meta_json FROM assets WHERE role IN (%s)" % ",".join(
        "?" * len(roles))
    cur.execute(q, roles)
    rows = [(a, r, json.loads(m)) for a, r, m in cur.fetchall()]
    con.close()
    return rows


def asset_dir(store: pathlib.Path, asset_id: str) -> pathlib.Path:
    return store.parent / "assets" / asset_id


def probe_obs_result(store: pathlib.Path, rows, limit_assets: int | None) -> dict:
    out = {"role": "obs_result", "n_assets": len(rows), "views": []}
    n_used = 0
    for asset_id, role, meta in rows:
        adir = asset_dir(store, asset_id)
        npz = adir / "arrays.npz"
        if not npz.exists():
            continue
        n_used += 1
        if limit_assets is not None and n_used > limit_assets:
            break
        inner = meta.get("meta", {})
        with np.load(npz, allow_pickle=False) as z:
            keys = list(z.files)
            vids = sorted({k.split(".")[0] for k in keys if "." in k})
            for vid in vids:
                kk = f"{vid}.K"
                if kk not in keys:
                    continue
                K = np.asarray(z[kk], dtype=np.float64)
                depth = np.asarray(z[f"{vid}.depth_z"], dtype=np.float64)
                rgb = np.asarray(z[f"{vid}.rgb"])
                h, w = depth.shape
                dm = np.asarray(z[f"{vid}.deployment_mask"]).astype(bool)
                roi = np.asarray(z[f"{vid}.roi"]).astype(bool) if f"{vid}.roi" in keys else None
                um = (np.asarray(z[f"{vid}.uncertain_mask"]).astype(bool)
                      if f"{vid}.uncertain_mask" in keys else None)
                tag = (np.asarray(z[f"{vid}.surface_tag"]) if f"{vid}.surface_tag" in keys
                       else None)
                idm = np.asarray(z[f"{vid}.id_map"]) if f"{vid}.id_map" in keys else None
                T = np.asarray(z[f"{vid}.T_WC"], dtype=np.float64) if f"{vid}.T_WC" in keys else None
                valid = np.isfinite(depth) & (depth > 0)
                fpx = float(K[0, 0])
                mmpp = depth[valid] / fpx if fpx > 0 else np.array([])
                taghist = {}
                if tag is not None:
                    u, c = np.unique(tag, return_counts=True)
                    taghist = {int(a): int(b) for a, b in zip(u.tolist(), c.tolist())}
                rec = {
                    "asset_id": asset_id, "view": vid, "shape": [int(h), int(w)],
                    "K_fx": fpx, "K_fy": float(K[1, 1]),
                    "K_cx": float(K[0, 2]), "K_cy": float(K[1, 2]),
                    "n_valid_depth_px": int(valid.sum()),
                    "object_px_total": int(h) * int(w),
                    "valid_frac_of_frame": float(valid.mean()),
                    "depth_mm_median": _pct(depth[valid], 50),
                    "depth_mm_p01": _pct(depth[valid], 1),
                    "depth_mm_p99": _pct(depth[valid], 99),
                    "depth_mm_min": (float(depth[valid].min()) if valid.any() else None),
                    "depth_mm_max": (float(depth[valid].max()) if valid.any() else None),
                    "mm_per_px_at_median_depth": (float(np.median(mmpp)) if mmpp.size else None),
                    "mm_per_px_p05": _pct(mmpp, 5), "mm_per_px_p95": _pct(mmpp, 95),
                    "px_per_mm_at_median_depth": (float(1.0 / np.median(mmpp))
                                                  if mmpp.size else None),
                    "resolvable_4px_mm": (float(4.0 * np.median(mmpp)) if mmpp.size else None),
                    "resolvable_6px_mm": (float(6.0 * np.median(mmpp)) if mmpp.size else None),
                    "resolvable_8px_mm": (float(8.0 * np.median(mmpp)) if mmpp.size else None),
                    "deployment_mask_frac": float(dm.mean()),
                    "roi_frac": (float(roi.mean()) if roi is not None else None),
                    "uncertain_frac_of_frame": (float(um.mean()) if um is not None else None),
                    "uncertain_frac_of_object": (float(um[valid].mean()) if um is not None
                                                 and valid.any() else None),
                    "surface_tag_hist": taghist,
                    "n_id_values": (int(np.unique(idm).size) if idm is not None else None),
                    "camera_center_mm": ([float(v) for v in T[:3, 3]] if T is not None else None),
                    "rgb_source": "obs_result",
                    "delivered_size_meta": inner.get("obs_spec", {}).get("delivered_size"),
                    "route": meta.get("route"),
                    "renderer": inner.get("renderer"),
                }
                out["views"].append(rec)
    return out


def agg(view_records: list[dict]) -> dict:
    if not view_records:
        return {}
    def col(key):
        return [v[key] for v in view_records if v.get(key) is not None]
    zs = col("depth_mm_median")
    mmpp = col("mm_per_px_at_median_depth")
    tag_rim = [v["surface_tag_hist"].get(2, 0) for v in view_records]
    tag_tot = [sum(v["surface_tag_hist"].values()) for v in view_records]
    return {
        "n_views": len(view_records),
        "shapes": sorted({tuple(v["shape"]) for v in view_records}),
        "working_distance_mm_median": float(np.median(zs)) if zs else None,
        "working_distance_mm_min": float(np.min(zs)) if zs else None,
        "working_distance_mm_max": float(np.max(zs)) if zs else None,
        "mm_per_px_median": float(np.median(mmpp)) if mmpp else None,
        "mm_per_px_min": float(np.min(mmpp)) if mmpp else None,
        "mm_per_px_max": float(np.max(mmpp)) if mmpp else None,
        "px_per_mm_median": float(1.0 / np.median(mmpp)) if mmpp else None,
        "resolvable_4px_mm_median": float(np.median(col("resolvable_4px_mm"))) if mmpp else None,
        "resolvable_8px_mm_median": float(np.median(col("resolvable_8px_mm"))) if mmpp else None,
        "deployment_mask_frac_mean": float(np.mean(col("deployment_mask_frac"))),
        "deployment_mask_frac_min": float(np.min(col("deployment_mask_frac"))),
        "deployment_mask_frac_max": float(np.max(col("deployment_mask_frac"))),
        "uncertain_frac_of_frame_mean": float(np.mean(col("uncertain_frac_of_frame"))),
        "rim_px_total": int(np.sum(tag_rim)),
        "tag_px_total": int(np.sum(tag_tot)),
        "rim_frac": float(np.sum(tag_rim) / max(np.sum(tag_tot), 1)),
        "n_views_with_rim": int(np.sum([1 for r in tag_rim if r > 0])),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default="data/a12")
    ap.add_argument("--limit-assets", type=int, default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    store = (ROOT / args.store).resolve()
    db = store / "metadata.sqlite" if store.is_dir() else store
    rows = store_assets(db, ("obs_result", "label_bundle", "obs_view"))
    by_role: dict[str, list] = {}
    for r in rows:
        by_role.setdefault(r[1], []).append(r)

    report = {"store": str(db.relative_to(ROOT)).replace("\\", "/"), "roles": {}}
    obs = probe_obs_result(db, by_role.get("obs_result", []), args.limit_assets)
    report["roles"]["obs_result"] = {"n_assets": obs["n_assets"], "aggregate": agg(obs["views"]),
                                     "views": obs["views"]}
    # label_bundle carries the label__* maps (surface_tag / mask / depth copies)
    lb_views: list[dict] = []
    for asset_id, role, meta in by_role.get("label_bundle", []):
        adir = asset_dir(db, asset_id)
        npz = adir / "arrays.npz"
        if not npz.exists():
            continue
        with np.load(npz, allow_pickle=False) as z:
            keys = list(z.files)
            for k in keys:
                if "surface_tag" in k:
                    a = np.asarray(z[k])
                    u, c = np.unique(a, return_counts=True)
                    lb_views.append({"asset_id": asset_id, "key": k,
                                     "shape": [int(a.shape[0]), int(a.shape[1])],
                                     "tag_hist": {int(x): int(y) for x, y in zip(u, c)}})
    lb_rim = sum(v["tag_hist"].get(2, 0) for v in lb_views)
    lb_tot = sum(sum(v["tag_hist"].values()) for v in lb_views)
    report["roles"]["label_bundle"] = {"n_tag_maps": len(lb_views), "rim_px_total": lb_rim,
                                       "tag_px_total": lb_tot,
                                       "rim_frac": float(lb_rim / max(lb_tot, 1))}
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.out:
        (ROOT / args.out).write_text(text, encoding="utf-8")
        print("wrote", args.out)
        print(json.dumps(report["roles"]["obs_result"]["aggregate"], indent=2, ensure_ascii=False))
        print(json.dumps(report["roles"]["label_bundle"], indent=2, ensure_ascii=False))
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
