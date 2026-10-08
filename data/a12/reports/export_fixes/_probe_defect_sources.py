"""Probe the *sources* the three export defects could be fixed from (real store bytes).

Usage:
  python _probe_defect_sources.py <store_root> [<release_id>]

Answers, with measured numbers:
  1. does the source obs meta carry a real per-view position (`u_position_mm`)?
  2. does the source obs payload carry `T_WC`, and what is `T_WC[0,3]` per view?
  3. can `frame_id` be replaced by a *real* per-point view id, i.e. does the point cloud
     reproject onto the rendered `depth_z` through `K`/`T_WC`?
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def obs_rows(store: Path):
    con = sqlite3.connect(str(store / "metadata.sqlite"))
    con.row_factory = sqlite3.Row
    for row in con.execute("select * from assets where role='obs_result' order by asset_id"):
        yield dict(row)


def main(store_dir: str) -> int:
    store = Path(store_dir)
    out = {"store": str(store), "fragments": []}
    for row in obs_rows(store):
        meta = json.loads(row["meta_json"])
        arrays_path = store / (json.loads(row["files_json"])["arrays"])
        if not arrays_path.exists():
            continue
        z = np.load(arrays_path, allow_pickle=False)
        views = list(meta.get("views") or [])
        entry = {
            "asset_id": row["asset_id"], "fragment_id": meta.get("fragment_id"),
            "n_views": len(views),
            "meta_u_position_mm": [v.get("u_position_mm") for v in views],
            "view_meta_keys": sorted((views[0].get("meta") or {}).get("view_meta", {}).keys())
            if views else [],
            "view_meta_0": (views[0].get("meta") or {}).get("view_meta") if views else None,
            "T_WC_x": [], "camera_centers": [], "view_ids": [v.get("view_id") for v in views],
        }
        points = np.asarray(z["points"], dtype=np.float64)
        entry["n_points"] = int(points.shape[0])
        match_counts, residuals = [], []
        for index in range(len(views)):
            pose_key = f"v{index:03d}.T_WC"
            if pose_key not in z.files:
                continue
            T = np.asarray(z[pose_key], dtype=np.float64)
            entry["T_WC_x"].append(float(T[0, 3]))
            entry["camera_centers"].append([float(x) for x in T[:3, 3]])
            K = np.asarray(z[f"v{index:03d}.K"], dtype=np.float64)
            depth = np.asarray(z[f"v{index:03d}.depth_z"], dtype=np.float64)
            h, w = depth.shape
            cam = (np.linalg.inv(T) @ np.concatenate([points, np.ones((points.shape[0], 1))],
                                                     axis=1).T).T[:, :3]
            uv = (K @ cam.T).T
            u = uv[:, 0] / np.where(uv[:, 2] == 0, np.nan, uv[:, 2])
            v = uv[:, 1] / np.where(uv[:, 2] == 0, np.nan, uv[:, 2])
            ui = np.round(u).astype(np.int64)
            vi = np.round(v).astype(np.int64)
            inside = (cam[:, 2] > 0) & (ui >= 0) & (ui < w) & (vi >= 0) & (vi < h)
            sampled = np.full(points.shape[0], np.nan)
            sampled[inside] = depth[vi[inside], ui[inside]]
            resid = np.abs(sampled - cam[:, 2])
            finite = np.isfinite(resid)
            entry.setdefault("projection", []).append({
                "view": index,
                "inside_fraction": float(inside.mean()),
                "finite_fraction": float(finite.mean()),
                "median_residual_mm": float(np.nanmedian(resid)) if finite.any() else None,
                "frac_residual_lt_1mm": float(np.nanmean(resid[finite] < 1.0)) if finite.any() else 0.0,
                "frac_residual_lt_5mm": float(np.nanmean(resid[finite] < 5.0)) if finite.any() else 0.0,
            })
            match_counts.append(int((finite & (resid < 5.0)).sum()))
            residuals.append(resid)
        # a real per-point frame id: the view whose depth best matches the reprojection
        if residuals:
            stack = np.vstack([np.nan_to_num(r, nan=1e9) for r in residuals])
            best = np.argmin(stack, axis=0)
            best_resid = stack[best, np.arange(stack.shape[1])]
            entry["best_view_match"] = {
                "matched_lt_5mm": int((best_resid < 5.0).sum()),
                "matched_lt_1mm": int((best_resid < 1.0).sum()),
                "n_points": int(points.shape[0]),
                "distinct_best_views": int(np.unique(best[best_resid < 5.0]).size),
                "counts_per_view": {int(k): int(v) for k, v in
                                    zip(*np.unique(best[best_resid < 5.0], return_counts=True))},
            }
        out["fragments"].append(entry)
        print(json.dumps(entry, indent=1, ensure_ascii=False, default=str))
    path = Path(__file__).with_name("_probe_defect_sources.json")
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print("wrote", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1
                          else "data/a12_exports/closed_loop/store"))
