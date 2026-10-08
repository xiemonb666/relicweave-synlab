"""Read-only probe: per-interface fracture height-field statistics of stored physical components.

Measured, not estimated: for every asset that carries ``face__interface_id`` the probe fits a
plane to each interface (``interface_id >= 0``) patch and reports the *measured* height field
statistics (Ra / Rz / Rt / RMS) plus the patch geometry (area, centroid, normal, extent).

Output: data/a12_reports/_roi_fracture_stats.json (and a text mirror).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from synlab.storage.mesh_io import arrays_to_mesh  # noqa: E402
from synlab.storage.store import AssetStore  # noqa: E402

STORES = [
    "data/a12_campaign/store", "data/a12_final/store", "data/a12_iface/store",
    "data/a12_fcal/store", "data/a12_extras/store",
]


def _face_attr(mesh, name):
    attrs = dict((mesh.metadata or {}).get("face_attr_arrays") or {})
    if name in attrs:
        return np.asarray(attrs[name]).reshape(-1)
    fa = (mesh.metadata or {}).get("face_attrs") or {}
    if isinstance(fa, dict) and name in fa:
        return np.asarray(fa[name]).reshape(-1)
    return None


def plane_fit(points: np.ndarray, weights: np.ndarray):
    """Total-least-squares plane through ``points``; returns (centroid, unit normal)."""
    w = weights / max(weights.sum(), 1e-30)
    c = (points * w[:, None]).sum(axis=0)
    q = points - c
    cov = (q * w[:, None]).T @ q
    vals, vecs = np.linalg.eigh(cov)
    n = vecs[:, int(np.argmin(vals))]
    return c, n / max(np.linalg.norm(n), 1e-30)


def interface_stats(mesh, interface_id: np.ndarray) -> list[dict]:
    faces = np.asarray(mesh.faces)
    verts = np.asarray(mesh.vertices, dtype=np.float64)
    tri = verts[faces]
    area = 0.5 * np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1)
    out = []
    for iid in sorted({int(v) for v in np.unique(interface_id) if int(v) >= 0}):
        sel = interface_id == iid
        if int(sel.sum()) < 4:
            out.append({"interface_id": iid, "status": "TOO_FEW_FACES",
                        "n_faces": int(sel.sum())})
            continue
        centroids = tri[sel].mean(axis=1)
        c, n = plane_fit(centroids, np.maximum(area[sel], 1e-12))
        # orient the normal away from the mesh centroid so "outward" is consistent
        if float(np.dot(n, c - verts.mean(axis=0))) < 0:
            n = -n
        h_c = (centroids - c) @ n
        # vertex heights, restricted to vertices only touched by this interface patch
        idx = np.unique(faces[sel].reshape(-1))
        other = np.zeros(len(verts), dtype=bool)
        other[np.unique(faces[~sel].reshape(-1))] = True
        pure = idx[~other[idx]]
        h_v = (verts[pure] - c) @ n if pure.size else np.zeros(0)
        extent = np.linalg.norm(centroids - c, axis=1)
        def stats(h):
            if h.size == 0:
                return {"n": 0}
            a = np.abs(h)
            order = np.argsort(h)
            k = max(1, int(round(0.05 * h.size)))
            rz = float(h[order[-k:]].mean() - h[order[:k]].mean())
            return {"n": int(h.size), "Ra_mm": float(a.mean()), "Rq_rms_mm": float(np.sqrt((h ** 2).mean())),
                    "Rz_mm": rz, "Rt_mm": float(h.max() - h.min()),
                    "mean_mm": float(h.mean()), "p95_abs_mm": float(np.percentile(a, 95))}
        out.append({
            "interface_id": iid, "status": "OK", "n_faces": int(sel.sum()),
            "area_mm2": float(area[sel].sum()),
            "centroid_mm": c.tolist(), "normal": n.tolist(),
            "radius_mm": float(extent.max()), "radius_p50_mm": float(np.median(extent)),
            "centroid_heights": stats(h_c), "vertex_heights": stats(h_v),
            "n_pure_vertices": int(pure.size),
        })
    return out


def main() -> None:
    out: dict[str, object] = {}
    for rel in STORES:
        root = ROOT / rel
        if not (root / "metadata.sqlite").exists():
            continue
        store = AssetStore(root)
        for asset in store.list_assets(role="physical_component", limit=500):
            try:
                arrs = store.load_arrays(asset.asset_id)
                mesh, _attrs = arrays_to_mesh(arrs)
            except Exception as exc:  # noqa: BLE001
                out[f"{rel}:{asset.asset_id}"] = {"error": str(exc)[:200]}
                continue
            idc = _face_attr(mesh, "interface_id")
            okc = _face_attr(mesh, "origin_kind")
            entry = {
                "store": rel, "asset_id": asset.asset_id, "lineage_id": asset.lineage_id,
                "n_faces": int(np.asarray(mesh.faces).shape[0]),
                "n_vertices": int(np.asarray(mesh.vertices).shape[0]),
                "interface_ids": (None if idc is None else
                                  sorted({int(v) for v in np.unique(idc)})),
                "origin_kind_histogram": (None if okc is None else
                                          {str(int(k)): int(v) for k, v in
                                           zip(*np.unique(okc, return_counts=True))}),
                "meta": {k: asset.meta.get(k) for k in
                         ("fragment_id", "component_id", "recipe_id", "axis_id", "level",
                          "status", "run_id", "damage_semantics")},
                "bbox_mm": [float(x) for x in np.concatenate([mesh.vertices.min(axis=0),
                                                              mesh.vertices.max(axis=0)])],
            }
            if idc is not None:
                entry["interfaces"] = interface_stats(mesh, idc)
            out[f"{rel}:{asset.asset_id}"] = entry
    path = ROOT / "data/a12_reports/_roi_fracture_stats.json"
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    lines = []
    for key, entry in out.items():
        if "error" in entry:
            lines.append(f"{key}: ERROR {entry['error']}")
            continue
        lines.append(f"\n=== {key}")
        lines.append(f"    lineage={entry['lineage_id']} faces={entry['n_faces']} "
                     f"iface_ids={entry['interface_ids']} kinds={entry['origin_kind_histogram']}")
        for st in entry.get("interfaces", []) or []:
            if st.get("status") != "OK":
                lines.append(f"    iface {st['interface_id']}: {st['status']}")
                continue
            vh = st["vertex_heights"]
            lines.append(
                f"    iface {st['interface_id']}: faces={st['n_faces']} area={st['area_mm2']:.3f} mm2 "
                f"radius={st['radius_mm']:.3f} mm  Ra_v={vh.get('Ra_mm')} Rz_v={vh.get('Rz_mm')} "
                f"Rt_v={vh.get('Rt_mm')}  Ra_c={st['centroid_heights'].get('Ra_mm')} "
                f"n_pure={st['n_pure_vertices']}")
    (ROOT / "data/a12_reports/_roi_fracture_stats.txt").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
