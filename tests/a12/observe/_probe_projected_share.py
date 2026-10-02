"""Projected-area cross-check for the rim pixel share (read-only).

For every delivered view of a committed ``obs_result`` this computes the *front-facing projected*
area of the target's faces (``sum area_f * max(0, n_f . u_f)`` with ``u_f`` the unit direction to
the camera) split by ``origin_kind``, and compares that share with the measured rim pixel share of
the same view.  It is the honest denominator for "how much of what the camera sees is fracture
surface", as opposed to the share of the full 3-D surface area.

Usage: python tests/a12/observe/_probe_projected_share.py --root data/a12_iface/store
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RIM_TAG = 2


def rows_of(db: Path) -> list[dict]:
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    out = []
    for row in con.execute("select asset_id, role, files_json, meta_json, lineage_id from assets"):
        entry = dict(row)
        entry["files"] = json.loads(entry.pop("files_json") or "{}")
        entry["meta"] = json.loads(entry.pop("meta_json") or "{}")
        out.append(entry)
    con.close()
    return out


def arrays_of(root: Path, row: dict, *tokens: str) -> dict:
    rel = row["files"].get("arrays")
    if not rel:
        return {}
    with np.load(root / rel, allow_pickle=False) as data:
        return {k: data[k] for k in data.files if any(t in k for t in tokens)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="data/a12_iface/store")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    root = Path(args.root)
    rows = rows_of(root / "metadata.sqlite")
    out: dict = {}
    for obs in [r for r in rows if r["role"] == "obs_result"]:
        lineage = str(obs["lineage_id"])
        meta = obs["meta"]
        fragment = str(meta.get("fragment_id", ""))
        component = next((r for r in rows if r["role"] == "physical_component"
                          and str(r["lineage_id"]) == lineage
                          and str(r["meta"].get("component_id", "")).split("#")[0] == fragment),
                         None)
        if component is None:
            continue
        carrays = arrays_of(root, component, "vertices", "faces", "face__origin_kind",
                            "face__area")
        mesh_vertices = np.asarray(carrays["vertices"], dtype=np.float64)
        mesh_faces = np.asarray(carrays["faces"], dtype=np.int64)
        origin = np.asarray(carrays["face__origin_kind"]).reshape(-1)
        triangles = mesh_vertices[mesh_faces]
        cross = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
        face_area = 0.5 * np.linalg.norm(cross, axis=1)
        normals = cross / np.maximum(np.linalg.norm(cross, axis=1)[:, None], 1e-30)
        centroids = triangles.mean(axis=1)
        iface = origin == 1

        view_arrays = arrays_of(root, obs, "surface_tag", "T_WC")
        entry: dict = {"component": component["asset_id"], "fragment_id": fragment,
                       "interface_area_fraction_3d": float(face_area[iface].sum()
                                                           / face_area.sum()),
                       "views": {}}
        n_views = len(meta.get("views") or [])
        for index in range(n_views):
            key_wc = f"v{index:03d}.T_WC"
            key_tag = f"v{index:03d}.surface_tag"
            if key_wc not in view_arrays or key_tag not in view_arrays:
                continue
            T_WC = np.asarray(view_arrays[key_wc], dtype=np.float64)
            T_CW = np.linalg.inv(T_WC)
            camera_centre = T_CW[:3, 3]
            direction = camera_centre[None, :] - centroids
            direction /= np.maximum(np.linalg.norm(direction, axis=1)[:, None], 1e-30)
            facing = np.maximum(0.0, np.einsum("ij,ij->i", normals, direction))
            projected = face_area * facing
            tag = np.asarray(view_arrays[key_tag])
            object_pixels = int(np.count_nonzero(tag != -1))
            rim_pixels = int(np.count_nonzero(tag == RIM_TAG))
            entry["views"][f"v{index:03d}"] = {
                "projected_area_total_mm2": float(projected.sum()),
                "projected_area_interface_mm2": float(projected[iface].sum()),
                "projected_interface_share": float(projected[iface].sum()
                                                   / max(projected.sum(), 1e-30)),
                "object_pixels": object_pixels, "rim_pixels": rim_pixels,
                "rim_pixel_share": (rim_pixels / object_pixels) if object_pixels else 0.0,
            }
        shares = [(v["rim_pixel_share"], v["projected_interface_share"])
                  for v in entry["views"].values()]
        if shares:
            entry["ratio_pixel_over_projected"] = float(
                np.mean([a / b for a, b in shares if b > 0]) if any(b > 0 for _a, b in shares)
                else 0.0)
        out[f"{lineage}|{obs['asset_id']}"] = entry
        print(json.dumps(entry, indent=1)[:2500], flush=True)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(out, indent=1), encoding="utf-8")
        print("wrote", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
