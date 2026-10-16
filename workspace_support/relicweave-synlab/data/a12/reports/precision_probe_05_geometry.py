"""precision audit probe 05 - geometry precision (dimension 2).

Read only.  For every ``fragment_mesh`` / ``mother_mesh`` / ``clean_truth`` asset of one store:

* triangle edge-length distribution (min / p05 / p50 / p95 / max) in mm -- the mesh's own
  smallest supported feature;
* for ``clean_truth``: ``iface_area_mm2``, ``iface_gap_p95_mm``, ``iface_normal_p95_deg``,
  ``iface_ambiguity_ratio``, ``iface_common_clip_area_mm2`` and the ``corr_residual_mm``
  distribution of the paired fracture correspondence.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sqlite3
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[3]


def edge_stats(vertices: np.ndarray, faces: np.ndarray) -> dict:
    v = np.asarray(vertices, dtype=np.float64)
    f = np.asarray(faces, dtype=np.int64)
    if f.size == 0 or v.size == 0:
        return {}
    e = np.concatenate([
        np.linalg.norm(v[f[:, 1]] - v[f[:, 0]], axis=1),
        np.linalg.norm(v[f[:, 2]] - v[f[:, 1]], axis=1),
        np.linalg.norm(v[f[:, 0]] - v[f[:, 2]], axis=1),
    ])
    e = e[np.isfinite(e)]
    if e.size == 0:
        return {}
    return {"n_edges": int(e.size), "min": float(e.min()),
            "p01": float(np.percentile(e, 1)),
            "p05": float(np.percentile(e, 5)), "p50": float(np.percentile(e, 50)),
            "p95": float(np.percentile(e, 95)), "max": float(e.max()),
            "mean": float(e.mean()),
            "frac_below_1e-3mm": float(np.mean(e < 1e-3)),
            "frac_below_1e-2mm": float(np.mean(e < 1e-2)),
            "n_below_mm_per_px": int(np.sum(e < 0.195)),
            "median_face_area_mm2": float(np.median(
                0.5 * np.linalg.norm(np.cross(v[f[:, 1]] - v[f[:, 0]],
                                              v[f[:, 2]] - v[f[:, 0]]), axis=1)))}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default="data/a12_final/store")
    ap.add_argument("--out", default="data/a12/reports/precision_probe_05_geometry.json")
    args = ap.parse_args()

    db = (ROOT / args.store / "metadata.sqlite")
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    cur = con.cursor()
    report: dict = {"store": args.store}

    for role in ("fragment_mesh", "mother_mesh"):
        cur.execute("SELECT asset_id, meta_json FROM assets WHERE role=?", (role,))
        rows = cur.fetchall()
        per = []
        agg_edges = []
        for asset_id, meta_json in rows:
            npz = db.parent / "assets" / asset_id / "arrays.npz"
            if not npz.exists():
                continue
            with np.load(npz, allow_pickle=False) as z:
                keys = list(z.files)
                vk = next((k for k in keys if k.endswith("vertices")), None)
                fk = next((k for k in keys if k.endswith("faces")), None)
                if vk is None or fk is None:
                    continue
                st = edge_stats(z[vk], z[fk])
            if st:
                st["asset_id"] = asset_id
                try:
                    mj = json.loads(meta_json)
                except Exception:
                    mj = {}
                st["origin_kind_hist"] = None
                per.append(st)
                agg_edges.append((st["n_edges"], st["min"], st["p50"], st["max"]))
        report[role] = {
            "n_assets": len(per),
            "edge_len_mm_min_of_min": float(min(p["min"] for p in per)) if per else None,
            "edge_len_mm_p01_min": float(min(p["p01"] for p in per)) if per else None,
            "edge_len_mm_p05_max": float(max(p["p05"] for p in per)) if per else None,
            "edge_len_mm_p50_range": [float(min(p["p50"] for p in per)),
                                      float(max(p["p50"] for p in per))] if per else None,
            "edge_len_mm_max_of_max": float(max(p["max"] for p in per)) if per else None,
            "edge_len_mm_p95_max": float(max(p["p95"] for p in per)) if per else None,
            "frac_edges_below_1e-3mm_max": float(max(p["frac_below_1e-3mm"] for p in per)) if per else None,
            "median_face_area_mm2_range": [float(min(p["median_face_area_mm2"] for p in per)),
                                           float(max(p["median_face_area_mm2"] for p in per))]
            if per else None,
            "per_asset_head": per[:6],
        }

    # ---- clean truth interface metrics -------------------------------------------
    cur.execute("SELECT asset_id, meta_json FROM assets WHERE role='clean_truth'")
    ct = cur.fetchall()
    gaps, normals, areas, ambig, clip, ncour = [], [], [], [], [], []
    corr_res = []
    per_asset = []
    for asset_id, meta_json in ct:
        npz = db.parent / "assets" / asset_id / "arrays.npz"
        if not npz.exists():
            continue
        rec = {"asset_id": asset_id}
        with np.load(npz, allow_pickle=False) as z:
            keys = list(z.files)
            def take(name):
                return np.asarray(z[name], dtype=np.float64) if name in keys else None
            g = take("iface_gap_p95_mm")
            n = take("iface_normal_p95_deg")
            a = take("iface_area_mm2")
            m = take("iface_ambiguity_ratio")
            c = take("iface_common_clip_area_mm2")
            r = take("corr_residual_mm")
        if g is not None and g.size:
            gaps.append(g); rec["gap_p95_max"] = float(np.nanmax(g))
            rec["gap_p95_mean"] = float(np.nanmean(g)); rec["n_iface"] = int(g.size)
        if n is not None and n.size:
            normals.append(n); rec["normal_p95_max"] = float(np.nanmax(n))
        if a is not None and a.size:
            areas.append(a); rec["area_sum_mm2"] = float(np.nansum(a))
        if m is not None and m.size:
            ambig.append(m); rec["ambiguity_max"] = float(np.nanmax(m))
        if c is not None and c.size:
            clip.append(c); rec["clip_sum_mm2"] = float(np.nansum(c))
        if r is not None and r.size:
            corr_res.append(r); rec["corr_residual_p95"] = float(
                np.nanpercentile(r, 95)); rec["n_corr"] = int(r.size)
            rec["corr_residual_max"] = float(np.nanmax(r))
        per_asset.append(rec)

    def cat(lst):
        return (np.concatenate(lst) if lst else np.array([]))

    G, N, A, M, C, R = cat(gaps), cat(normals), cat(areas), cat(ambig), cat(clip), cat(corr_res)
    report["clean_truth"] = {
        "n_assets": len(ct),
        "interface_count_total": int(G.size) if G.size else None,
        "gap_p95_mm": {"n": int(G.size), "median": float(np.median(G)) if G.size else None,
                       "p95": float(np.percentile(G, 95)) if G.size else None,
                       "max": float(G.max()) if G.size else None,
                       "mean": float(G.mean()) if G.size else None},
        "normal_p95_deg": {"n": int(N.size), "median": float(np.median(N)) if N.size else None,
                           "p95": float(np.percentile(N, 95)) if N.size else None,
                           "max": float(N.max()) if N.size else None},
        "area_mm2": {"n": int(A.size), "sum": float(A.sum()) if A.size else None,
                     "median": float(np.median(A)) if A.size else None},
        "ambiguity_ratio": {"p95": float(np.percentile(M, 95)) if M.size else None,
                            "max": float(M.max()) if M.size else None},
        "common_clip_area_mm2_sum": float(C.sum()) if C.size else None,
        "corr_residual_mm": {"n": int(R.size),
                             "median": float(np.median(R)) if R.size else None,
                             "p95": float(np.percentile(R, 95)) if R.size else None,
                             "max": float(R.max()) if R.size else None},
        "per_asset": per_asset,
    }

    # ---- physical_component face provenance + face area ---------------------------
    cur.execute("SELECT asset_id FROM assets WHERE role='physical_component'")
    pc_ids = [r[0] for r in cur.fetchall()]
    oh, ih, face_areas = {}, {}, []
    n_with_iface = 0
    for asset_id in pc_ids:
        npz = db.parent / "assets" / asset_id / "arrays.npz"
        if not npz.exists():
            continue
        with np.load(npz, allow_pickle=False) as z:
            keys = list(z.files)
            ok = next((k for k in keys if "origin_kind" in k), None)
            iid = next((k for k in keys if "interface_id" in k), None)
            vk = next((k for k in keys if k.endswith("vertices")), None)
            fk = next((k for k in keys if k.endswith("faces")), None)
            if iid is not None:
                n_with_iface += 1
                u, c = np.unique(np.asarray(z[iid]).reshape(-1), return_counts=True)
                for x, y in zip(u.tolist(), c.tolist()):
                    ih[str(int(x))] = ih.get(str(int(x)), 0) + int(y)
            if ok is not None:
                u, c = np.unique(np.asarray(z[ok]).reshape(-1), return_counts=True)
                for x, y in zip(u.tolist(), c.tolist()):
                    oh[str(int(x))] = oh.get(str(int(x)), 0) + int(y)
            if vk and fk:
                st = edge_stats(z[vk], z[fk])
                if st:
                    face_areas.append(st)
    report["physical_component"] = {
        "n": len(pc_ids), "n_with_interface_id_channel": n_with_iface,
        "origin_kind_hist": oh, "interface_id_hist_top": dict(
            sorted(ih.items(), key=lambda kv: -kv[1])[:12]),
        "edge_len_mm_min_of_min": (min(s["min"] for s in face_areas) if face_areas else None),
        "edge_len_mm_p50_range": ([min(s["p50"] for s in face_areas),
                                   max(s["p50"] for s in face_areas)] if face_areas else None),
    }
    con.close()
    text = json.dumps(report, indent=2, ensure_ascii=False)
    (ROOT / args.out).write_text(text, encoding="utf-8")
    print("wrote", args.out)
    print(json.dumps({k: v for k, v in report.items() if k != "clean_truth"}, indent=2,
                     ensure_ascii=False)[:4000])
    print("clean_truth:", json.dumps({k: v for k, v in report["clean_truth"].items()
                                      if k != "per_asset"}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
