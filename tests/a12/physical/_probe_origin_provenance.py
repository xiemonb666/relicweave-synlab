"""Characterise the provenance of damaged-component faces against their clean fragment.

Read-only.  For every face of a committed ``physical_component`` it measures the *exact*
point-to-surface relationship to the clean ``fragment_mesh`` it descends from, and reports the
distance histogram, the origin kind of the clean face each damaged face lands on, the normal
agreement, and (for the faces that land on nothing) where they sit relative to the clean
interface ROI.

Usage:  python tests/a12/physical/_probe_origin_provenance.py [--root data/a12] [--lineages N]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import trimesh

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ORIGIN_NAMES = {0: "mother_surface", 1: "interface", 2: "ambiguous"}


def load_rows(db: Path) -> list[dict]:
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = []
    for row in con.execute("select asset_id, role, files_json, meta_json, lineage_id, qa_status "
                           "from assets"):
        entry = dict(row)
        entry["files"] = json.loads(entry.pop("files_json") or "{}")
        entry["meta"] = json.loads(entry.pop("meta_json") or "{}")
        rows.append(entry)
    con.close()
    return rows


def load_arrays(root: Path, row: dict, *, mesh_prefix: str | None = None) -> dict:
    """Arrays of one asset; with ``mesh_prefix`` the ``<prefix>.`` keys are returned bare."""
    rel = row["files"].get("arrays")
    if not rel:
        return {}
    with np.load(root / rel, allow_pickle=False) as data:
        out = {k: data[k] for k in data.files}
    if mesh_prefix is None:
        return out
    head = f"{mesh_prefix}."
    return {k[len(head):]: v for k, v in out.items() if k.startswith(head)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="data/a12")
    ap.add_argument("--lineages", type=int, default=3)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    root = Path(args.root)
    rows = load_rows(root / "metadata.sqlite")

    frags: dict[str, list[dict]] = {}
    comps: dict[str, list[dict]] = {}
    for row in rows:
        if row["role"] == "fragment_mesh":
            frags.setdefault(str(row["lineage_id"]), []).append(row)
        elif row["role"] == "physical_component":
            comps.setdefault(str(row["lineage_id"]), []).append(row)
    pairs = [(lin, comps[lin], frags[lin]) for lin in sorted(comps) if lin in frags]
    print(f"lineages with both fragment_mesh and physical_component: {len(pairs)}")

    report: dict = {"root": str(root), "lineages": {}}
    for lineage, comp_list, frag_list in pairs[: int(args.lineages)]:
        comp = comp_list[0]
        arrays = load_arrays(root, comp)
        if "vertices" not in arrays:
            arrays = load_arrays(root, comp, mesh_prefix="mesh")
        verts = np.asarray(arrays["vertices"], dtype=np.float64)
        faces = np.asarray(arrays["faces"], dtype=np.int64)
        damaged = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
        ancestor = str(comp["meta"].get("ancestor", ""))
        frag = next((f for f in frag_list
                     if str(f["meta"].get("fragment_id", "")) == ancestor), frag_list[0])
        farrays = load_arrays(root, frag, mesh_prefix="mesh")
        if "vertices" not in farrays:
            farrays = load_arrays(root, frag)
        fverts = np.asarray(farrays["vertices"], dtype=np.float64)
        ffaces = np.asarray(farrays["faces"], dtype=np.int64)
        clean = trimesh.Trimesh(vertices=fverts, faces=ffaces, process=False)
        origin = np.asarray(farrays.get("face__origin_kind",
                                        np.full(len(ffaces), -1)), dtype=np.int64)
        iface_id = np.asarray(farrays.get("face__interface_id",
                                          np.full(len(ffaces), -1)), dtype=np.int64)
        if "face__source_tri" in farrays:
            src = np.asarray(farrays["face__source_tri"], dtype=np.int64)
        elif "face__source_triangle" in farrays:
            src = np.asarray(farrays["face__source_triangle"], dtype=np.int64)
        else:
            src = np.full(len(ffaces), -1, dtype=np.int64)

        centroids = np.asarray(damaged.triangles_center, dtype=np.float64)
        dnormals = np.asarray(damaged.face_normals, dtype=np.float64)
        close, dist, tri = trimesh.proximity.closest_point(clean, centroids)
        signed = trimesh.proximity.signed_distance(clean, centroids)   # >0 = inside
        tri = np.asarray(tri, dtype=np.int64)
        matched_origin = origin[tri] if tri.size else np.zeros(0, dtype=np.int64)
        cos = np.abs(np.einsum("ij,ij->i", dnormals, np.asarray(clean.face_normals)[tri]))
        plane_mm = np.abs(np.einsum("ij,ij->i", centroids - close,
                                    np.asarray(clean.face_normals)[tri]))

        entry: dict = {
            "lineage_id": lineage,
            "component_asset": comp["asset_id"], "fragment_asset": frag["asset_id"],
            "ancestor": ancestor,
            "damaged_faces": int(len(faces)), "clean_faces": int(len(ffaces)),
            "clean_origin_histogram": {ORIGIN_NAMES.get(int(k), str(k)): int(v)
                                       for k, v in zip(*np.unique(origin, return_counts=True))},
            "damaged_face__origin_kind_histogram": (
                {str(int(k)): int(v) for k, v in zip(*np.unique(
                    np.asarray(arrays.get("face__origin_kind",
                                          np.full(len(faces), -1))), return_counts=True))}),
            "distance_mm": {
                "min": float(dist.min()), "p50": float(np.percentile(dist, 50)),
                "p90": float(np.percentile(dist, 90)), "p99": float(np.percentile(dist, 99)),
                "max": float(dist.max()),
            },
            "tolerances": {},
        }
        for tol in (1e-9, 1e-6, 1e-4, 1e-3, 1e-2, 0.05, 0.1, 0.25, 0.5):
            near = dist <= tol
            coplanar = near & (cos >= 0.999) & (plane_mm <= tol)
            hist = {}
            for k in np.unique(matched_origin[coplanar]):
                hist[ORIGIN_NAMES.get(int(k), str(int(k)))] = int(np.sum(matched_origin[coplanar] == k))
            entry["tolerances"][f"{tol:g}"] = {
                "faces_within_tol": int(near.sum()),
                "faces_within_tol_frac": float(near.mean()),
                "coplanar_faces": int(coplanar.sum()),
                "coplanar_frac": float(coplanar.mean()),
                "coplanar_origin_histogram": hist,
                "coplanar_origin_interface_id_histogram": {
                    str(int(k)): int(v) for k, v in zip(*np.unique(iface_id[tri][coplanar],
                                                                   return_counts=True))},
            }
        # the faces that land on nothing: where do they sit?
        tol = 1e-3
        coplanar = (dist <= tol) & (cos >= 0.999) & (plane_mm <= tol)
        new = ~coplanar
        entry["new_faces"] = int(new.sum())
        if new.any():
            iface_mask = (origin == 1) | (iface_id >= 0)
            outer_mask = (origin == 0) & (iface_id < 0)
            iface_sub = trimesh.Trimesh(vertices=clean.vertices, faces=clean.faces[iface_mask],
                                        process=False)
            outer_sub = trimesh.Trimesh(vertices=clean.vertices, faces=clean.faces[outer_mask],
                                        process=False)
            ri = trimesh.proximity.closest_point(iface_sub, centroids[new])[1] \
                if iface_mask.any() else np.full(int(new.sum()), np.inf)
            ro = trimesh.proximity.closest_point(outer_sub, centroids[new])[1] \
                if outer_mask.any() else np.full(int(new.sum()), np.inf)
            entry["new_faces_geometry"] = {
                "dist_to_clean_interface_mm": {
                    "p50": float(np.percentile(ri, 50)), "p90": float(np.percentile(ri, 90)),
                    "max": float(np.max(ri))},
                "dist_to_clean_outer_mm": {
                    "p50": float(np.percentile(ro, 50)), "p90": float(np.percentile(ro, 90)),
                    "max": float(np.max(ro))},
                "signed_mm": {"min": float(signed[new].min()),
                              "p50": float(np.percentile(signed[new], 50)),
                              "max": float(signed[new].max())},
                "inside_fraction": float(np.mean(signed[new] > 0)),
                "closer_to_interface_frac": float(np.mean(ri < ro)),
                "src_tri_negative_frac_of_clean": float(np.mean(src < 0)) if src.size else None,
            }
        report["lineages"][f"{lineage}|{comp['asset_id']}"] = entry
        print(json.dumps(entry, indent=1)[:4000], flush=True)

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(report, indent=1), encoding="utf-8")
        print("wrote", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
