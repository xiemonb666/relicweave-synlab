"""Read-only probe: the *interface* faces (``origin_kind == ORIGIN_INTERFACE``) of stored
physical components - per-interface patches, their plane, extent and measured roughness.

The earlier probe grouped by ``face__interface_id`` alone; that channel is inherited from the
clean source face, so it also labels mother-surface faces (measured: LIN0000_V10_M11_PAT15 has
15 interface ids but only 746 interface faces).  This probe therefore selects
``origin_kind == ORIGIN_INTERFACE`` first and only then groups by id + connectivity.

Output: data/a12_reports/_roi_patch_probe.json / .txt
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from synlab.schemas.runtime import ORIGIN_INTERFACE  # noqa: E402
from synlab.storage.mesh_io import arrays_to_mesh  # noqa: E402
from synlab.storage.store import AssetStore  # noqa: E402

CANDIDATES = [
    ("data/a12_campaign/store", "asset_745a78313d0d5b045b3a"),   # V10 / M11
    ("data/a12_campaign/store", "asset_73da9901b275bb65c04e"),   # V21 / M06
    ("data/a12_campaign/store", "asset_aba4549620450f1f6adf"),   # V23 / M07
    ("data/a12_iface/store", "asset_8ad98a2081675cc92587"),      # V02 / M01
    ("data/a12_extras/store", "asset_cb0962cd4e649dd07a03"),     # V01 / M01
    ("data/a12_fcal/store", "asset_828971a31113c8f5bbb6"),       # V02 / M01
]


def face_components(faces: np.ndarray) -> np.ndarray:
    """Connected components of a triangle soup, split by shared edge (2 shared vertices)."""
    from collections import defaultdict

    n = len(faces)
    edges: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i, (a, b, c) in enumerate(faces):
        for u, v in ((a, b), (b, c), (c, a)):
            edges[(min(u, v), max(u, v))].append(i)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[max(rx, ry)] = min(rx, ry)

    for members in edges.values():
        for other in members[1:]:
            union(members[0], other)
    roots = np.array([find(i) for i in range(n)])
    _, labels = np.unique(roots, return_inverse=True)
    return labels


def patch_stats(verts, faces, sel, interface_id_value) -> dict:
    tri = verts[faces[sel]]
    area = 0.5 * np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1)
    centroids = tri.mean(axis=1)
    w = np.maximum(area, 1e-12)
    c = (centroids * (w / w.sum())[:, None]).sum(axis=0)
    q = centroids - c
    cov = (q * (w / w.sum())[:, None]).T @ q
    vals, vecs = np.linalg.eigh(cov)
    n = vecs[:, int(np.argmin(vals))]
    if float(np.dot(n, centroids.mean(axis=0) - verts.mean(axis=0))) < 0:
        n = -n
    h = q @ n
    r = np.linalg.norm(q, axis=1)
    a = np.abs(h)
    order = np.argsort(h)
    k = max(1, int(round(0.10 * h.size)))
    return {
        "interface_id": int(interface_id_value), "n_faces": int(sel.sum()),
        "area_mm2": float(area.sum()),
        "centroid_mm": [float(v) for v in c], "normal": [float(v) for v in n],
        "radius_p50_mm": float(np.percentile(r, 50)), "radius_p95_mm": float(np.percentile(r, 95)),
        "radius_max_mm": float(r.max()),
        "height_Ra_mm": float(a.mean()), "height_Rq_mm": float(np.sqrt((h ** 2).mean())),
        "height_Rz_mm": float(h[order[-k:]].mean() - h[order[:k]].mean()),
        "height_Rt_mm": float(h.max() - h.min()),
        "height_p95_abs_mm": float(np.percentile(a, 95)),
        "plane_fit_rms_mm": float(np.sqrt((h ** 2).mean())),
    }


def main() -> None:
    out: dict[str, object] = {}
    for rel, asset_id in CANDIDATES:
        store = AssetStore(ROOT / rel)
        asset = store.get_asset(asset_id)
        arrays = store.load_arrays(asset_id)
        mesh, attrs = arrays_to_mesh(arrays)
        verts = np.asarray(mesh.vertices, dtype=np.float64)
        faces = np.asarray(mesh.faces)
        kind = np.asarray(attrs["origin_kind"]).reshape(-1)
        iface = np.asarray(attrs.get("interface_id", np.full(len(faces), -1))).reshape(-1)
        sel_all = kind == ORIGIN_INTERFACE
        entry: dict[str, object] = {
            "store": rel, "asset_id": asset_id, "lineage_id": asset.lineage_id,
            "n_faces": int(len(faces)), "n_vertices": int(len(verts)),
            "origin_kind_histogram": {str(int(k)): int(v) for k, v in
                                      zip(*np.unique(kind, return_counts=True))},
            "interface_faces": int(sel_all.sum()),
            "interface_area_mm2": float(
                mesh.area_faces[sel_all].sum()) if bool(sel_all.any()) else 0.0,
            "total_area_mm2": float(mesh.area_faces.sum()),
            "interface_id_histogram_on_interface_faces": {
                str(int(k)): int(v) for k, v in
                zip(*np.unique(iface[sel_all], return_counts=True))} if bool(sel_all.any()) else {},
            "patches": [],
        }
        if bool(sel_all.any()):
            idx = np.flatnonzero(sel_all)
            comp = face_components(faces[idx])
            patch_rows = []
            for iid in sorted({int(v) for v in np.unique(iface[sel_all])}):
                for comp_id in sorted({int(v) for v in np.unique(comp[iface[idx] == iid])}):
                    mask = (iface[idx] == iid) & (comp == comp_id)
                    sub = np.zeros(len(faces), dtype=bool)
                    sub[idx[mask]] = True
                    row = patch_stats(verts, faces, sub, iid)
                    row["component_id"] = int(comp_id)
                    patch_rows.append(row)
            patch_rows.sort(key=lambda r: -r["area_mm2"])
            entry["patches"] = patch_rows
            entry["n_patches"] = len(patch_rows)
        out[f"{rel}:{asset_id}"] = entry

    path = ROOT / "data/a12_reports/_roi_patch_probe.json"
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    lines = []
    for key, e in out.items():
        lines.append(f"\n=== {key}  lineage={e['lineage_id']}")
        lines.append(f"    faces={e['n_faces']} kinds={e['origin_kind_histogram']} "
                     f"interface_faces={e['interface_faces']} "
                     f"area={e['interface_area_mm2']:.2f}/{e['total_area_mm2']:.2f} mm2 "
                     f"({100.0 * e['interface_area_mm2'] / max(e['total_area_mm2'], 1e-9):.2f}%)")
        lines.append(f"    iface ids on interface faces: "
                     f"{e['interface_id_histogram_on_interface_faces']}")
        lines.append(f"    patches={e.get('n_patches')}")
        for p in e["patches"][:10]:
            lines.append(
                f"      id={p['interface_id']} n={p['n_faces']} area={p['area_mm2']:.3f} "
                f"r50={p['radius_p50_mm']:.3f} r95={p['radius_p95_mm']:.3f} "
                f"Ra={p['height_Ra_mm']:.6g} Rz={p['height_Rz_mm']:.6g} "
                f"Rt={p['height_Rt_mm']:.6g} n={p['normal']}")
    (ROOT / "data/a12_reports/_roi_patch_probe.txt").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
