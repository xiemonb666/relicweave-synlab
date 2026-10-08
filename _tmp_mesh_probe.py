"""Read-only: inspect the AUTHORITY meshes that the display GLBs are derived from.

Prints vertex sharing / split-vertex statistics and the real face attributes
(``origin_kind`` / ``interface_id``) together with their face counts and areas.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent


def load_arrays(store_root: pathlib.Path, asset_id: str) -> dict:
    import numpy as np

    asset_dir = store_root / "assets" / asset_id
    npz = None
    for candidate in sorted(asset_dir.glob("*")):
        if candidate.suffix.lower() == ".npz" or "arrays" in candidate.name:
            npz = candidate
            break
    if npz is None:
        raise SystemExit(f"no arrays payload in {asset_dir}: {sorted(p.name for p in asset_dir.iterdir())}")
    data = np.load(npz, allow_pickle=False)
    return {k: data[k] for k in data.files}


def report(store_root: pathlib.Path, asset_id: str) -> dict:
    import numpy as np

    arrays = load_arrays(store_root, asset_id)
    vertices = np.asarray(arrays["vertices"], dtype=np.float64)
    faces = np.asarray(arrays["faces"], dtype=np.int64)
    face_keys = sorted(k for k in arrays if k.startswith("face__"))
    # vertex sharing: unique positions vs vertex count
    quant = np.round(vertices, 6)
    _, inverse, counts = np.unique(quant, axis=0, return_inverse=True, return_counts=True)
    # how many welded positions are referenced by >1 vertex index (= split vertices)
    split_positions = int(np.sum(counts > 1))
    # faces per welded position
    welded_of_face = inverse[faces]  # (F,3)
    out = {
        "asset_id": asset_id,
        "vertices": int(len(vertices)),
        "faces": int(len(faces)),
        "welded_positions": int(len(counts)),
        "split_vertex_positions": split_positions,
        "max_duplicate_vertex_copies": int(counts.max()) if len(counts) else 0,
        "face_attr_keys": face_keys,
        "bounds_mm": [vertices.min(axis=0).tolist(), vertices.max(axis=0).tolist()],
        "area_mm2_total": None,
        "attrs": {},
    }
    v0, v1, v2 = vertices[faces[:, 0]], vertices[faces[:, 1]], vertices[faces[:, 2]]
    tri_area = 0.5 * np.linalg.norm(np.cross(v1 - v0, v2 - v0), axis=1)
    out["area_mm2_total"] = float(tri_area.sum())
    for key in face_keys:
        values = np.asarray(arrays[key])
        if values.ndim != 1 or len(values) != len(faces):
            out["attrs"][key] = {"shape": list(values.shape), "note": "not a per-face scalar"}
            continue
        uniq, cnt = np.unique(values, return_counts=True)
        per_value = []
        for value, count in zip(uniq.tolist(), cnt.tolist()):
            mask = values == value
            per_value.append({"value": int(value), "faces": int(count),
                              "area_mm2": float(tri_area[mask].sum())})
        out["attrs"][key] = {"dtype": str(values.dtype), "per_value": per_value}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store-root", default=r"data\a12_demo\store")
    ap.add_argument("asset_ids", nargs="+")
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()
    store_root = pathlib.Path(args.store_root)
    rows = [report(store_root, asset_id) for asset_id in args.asset_ids]
    if args.json_out:
        pathlib.Path(args.json_out).write_text(json.dumps(rows, indent=2, ensure_ascii=False),
                                               encoding="utf-8")
    for row in rows:
        print("=" * 100)
        print(f"{row['asset_id']}: V={row['vertices']} F={row['faces']} "
              f"welded={row['welded_positions']} split_positions={row['split_vertex_positions']} "
              f"max_copies={row['max_duplicate_vertex_copies']}")
        print("   bounds_mm:", json.dumps(row["bounds_mm"]))
        print("   total_area_mm2:", round(row["area_mm2_total"], 6))
        for key, info in row["attrs"].items():
            if "per_value" not in info:
                print(f"   {key}: {info}")
                continue
            print(f"   {key} ({info['dtype']}):")
            for entry in info["per_value"][:12]:
                print(f"      value={entry['value']:>4}  faces={entry['faces']:>7}  "
                      f"area_mm2={entry['area_mm2']:.4f}")
            if len(info["per_value"]) > 12:
                print(f"      ... +{len(info['per_value']) - 12} more values")
    return 0


if __name__ == "__main__":
    sys.exit(main())
