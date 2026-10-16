"""Second-stage probe: where the damaged body actually sits relative to the clean fragment.

Read-only.  Measures areas, the distance field of the clean fragment's interface patch against the
damaged body, and the area of the damaged surface that lies strictly inside the clean body.

Usage: python tests/a12/physical/_probe_component_vs_clean.py --root data/a12 --lineage LIN0000_V01_M01_PAT01
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


def arrays(root: Path, row: dict, prefix: str | None = None) -> dict:
    rel = row["files"].get("arrays")
    if not rel:
        return {}
    with np.load(root / rel, allow_pickle=False) as data:
        out = {k: data[k] for k in data.files}
    if prefix is None:
        return out
    head = f"{prefix}."
    sel = {k[len(head):]: v for k, v in out.items() if k.startswith(head)}
    return sel or out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="data/a12")
    ap.add_argument("--lineage", default=None)
    args = ap.parse_args(argv)
    root = Path(args.root)
    rows = rows_of(root / "metadata.sqlite")
    comps = [r for r in rows if r["role"] == "physical_component"
             and (args.lineage is None or r["lineage_id"] == args.lineage)]
    frags = {r["lineage_id"]: [x for x in rows if x["role"] == "fragment_mesh"
                               and x["lineage_id"] == r["lineage_id"]] for r in comps}
    out = {}
    for comp in comps[:1]:
        a = arrays(root, comp)
        damaged = trimesh.Trimesh(vertices=np.asarray(a["vertices"], dtype=np.float64),
                                  faces=np.asarray(a["faces"], dtype=np.int64), process=False)
        ancestor = str(comp["meta"].get("ancestor", ""))
        frag = next(f for f in frags[comp["lineage_id"]]
                    if str(f["meta"].get("fragment_id", "")) == ancestor)
        fa = arrays(root, frag, "mesh")
        clean = trimesh.Trimesh(vertices=np.asarray(fa["vertices"], dtype=np.float64),
                                faces=np.asarray(fa["faces"], dtype=np.int64), process=False)
        origin = np.asarray(fa.get("face__origin_kind", np.full(len(clean.faces), -1)))
        iface_id = np.asarray(fa.get("face__interface_id", np.full(len(clean.faces), -1)))
        area = np.asarray(clean.area_faces, dtype=np.float64)
        imask = (origin == 1) | (iface_id >= 0)
        cc = np.asarray(clean.triangles_center, dtype=np.float64)
        dcent = np.asarray(damaged.triangles_center, dtype=np.float64)
        # a) where does the clean interface patch sit relative to the damaged body?
        dist_iface_to_damaged = trimesh.proximity.closest_point(damaged, cc[imask])[1]
        dist_mother_to_damaged = trimesh.proximity.closest_point(damaged, cc[~imask])[1]
        # b) signed depth of every damaged face inside the clean body
        signed = trimesh.proximity.signed_distance(clean, dcent)
        darea = np.asarray(damaged.area_faces, dtype=np.float64)
        # c) damaged faces near the clean interface (in the sense of nearest clean *interface* point)
        iface_sub = trimesh.Trimesh(vertices=clean.vertices, faces=clean.faces[imask], process=False)
        d_iface = trimesh.proximity.closest_point(iface_sub, dcent)[1]
        out = {
            "lineage_id": comp["lineage_id"], "component": comp["asset_id"],
            "ancestor": ancestor, "fragment": frag["asset_id"],
            "clean_faces": int(len(clean.faces)), "damaged_faces": int(len(damaged.faces)),
            "clean_area_mm2": float(clean.area), "damaged_area_mm2": float(damaged.area),
            "clean_volume_mm3": float(abs(clean.volume)),
            "damaged_volume_mm3": float(abs(damaged.volume)),
            "clean_interface_faces": int(imask.sum()),
            "clean_interface_area_mm2": float(area[imask].sum()),
            "clean_interface_area_fraction": float(area[imask].sum() / area.sum()),
            "clean_iface_centroid_to_damaged_mm": {
                "p50": float(np.percentile(dist_iface_to_damaged, 50)),
                "p90": float(np.percentile(dist_iface_to_damaged, 90)),
                "max": float(dist_iface_to_damaged.max())},
            "clean_mother_centroid_to_damaged_mm": {
                "p50": float(np.percentile(dist_mother_to_damaged, 50)),
                "p90": float(np.percentile(dist_mother_to_damaged, 90)),
                "max": float(dist_mother_to_damaged.max())},
            "damaged_faces_signed_depth_mm": {
                "p50": float(np.percentile(signed, 50)), "p90": float(np.percentile(signed, 90)),
                "max": float(signed.max()),
                "outside_faces": int((signed < -1e-3).sum()),
                "inside_deeper_than_0p01mm": int((signed > 0.01).sum())},
            "damaged_area_inside_deeper_than_0p01mm_mm2": float(darea[signed > 0.01].sum()),
            "damaged_face_to_clean_interface_mm": {
                "p10": float(np.percentile(d_iface, 10)), "p25": float(np.percentile(d_iface, 25)),
                "p50": float(np.percentile(d_iface, 50)),
                "faces_within_0p25mm": int((d_iface <= 0.25).sum()),
                "faces_within_0p5mm": int((d_iface <= 0.5).sum()),
                "faces_within_1mm": int((d_iface <= 1.0).sum()),
                "faces_within_3mm": int((d_iface <= 3.0).sum())},
            "damaged_faces_in_roi_band_and_inside": {
                "d01": int(((d_iface <= 1.0) & (signed > 0.01)).sum()),
                "d025": int(((d_iface <= 0.25) & (signed > 0.01)).sum()),
                "d05": int(((d_iface <= 0.5) & (signed > 0.01)).sum())},
        }
        print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
