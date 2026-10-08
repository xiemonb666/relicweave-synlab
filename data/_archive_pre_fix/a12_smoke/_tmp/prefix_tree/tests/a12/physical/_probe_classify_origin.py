"""Retrofit probe: run the new face-provenance classifier on *committed* physical components.

Read-only on ``--root`` (default ``data/a12``).  Pairs every ``physical_component`` with the
``fragment_mesh`` it descends from (``meta.ancestor``) and reports, for a sweep of co-location
tolerances, the real three-class histogram, the per-class area, the ROI band used and the mapping
hit rate.

Usage:
  python tests/a12/physical/_probe_classify_origin.py --root data/a12 --lineages 2 --out <json>
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np
import trimesh

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from synlab.physical.api import (  # noqa: E402
    ORIGIN_COLOCATION_COS_MIN,
    classify_face_origin,
    origin_colocation_tolerance_mm,
)


def store_rows(db: Path) -> list[dict]:
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    out = []
    for row in con.execute("select asset_id, role, files_json, meta_json, lineage_id, qa_status "
                           "from assets"):
        entry = dict(row)
        entry["files"] = json.loads(entry.pop("files_json") or "{}")
        entry["meta"] = json.loads(entry.pop("meta_json") or "{}")
        out.append(entry)
    con.close()
    return out


def arrays_of(root: Path, row: dict, prefix: str | None = None) -> dict:
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
    ap.add_argument("--lineages", type=int, default=2)
    ap.add_argument("--spacing-mm", type=float, default=0.5246,
                    help="frozen SDF grid spacing of the probe asset (declared in "
                         "synlab/degrade/axes.py P03 NOTES)")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    root = Path(args.root)
    rows = store_rows(root / "metadata.sqlite")
    comps = [r for r in rows if r["role"] == "physical_component"]
    frags: dict[str, list[dict]] = {}
    for row in rows:
        if row["role"] == "fragment_mesh":
            frags.setdefault(str(row["lineage_id"]), []).append(row)

    report: dict = {"root": str(root), "cos_min": ORIGIN_COLOCATION_COS_MIN,
                    "spacing_mm": args.spacing_mm, "lineages": {}}
    seen: set[str] = set()
    done = 0
    for comp in comps:
        lineage = str(comp["lineage_id"])
        if lineage in seen:
            continue
        ancestor = str(comp["meta"].get("ancestor", ""))
        frag = next((f for f in frags.get(lineage, [])
                     if str(f["meta"].get("fragment_id", "")) == ancestor), None)
        if frag is None:
            continue
        seen.add(lineage)
        done += 1
        t0 = time.time()
        ca = arrays_of(root, comp)
        clean = trimesh.Trimesh(vertices=np.asarray(ca["vertices"], dtype=np.float64),
                                faces=np.asarray(ca["faces"], dtype=np.int64), process=False)
        fa = arrays_of(root, frag, "mesh")
        source = trimesh.Trimesh(vertices=np.asarray(fa["vertices"], dtype=np.float64),
                                 faces=np.asarray(fa["faces"], dtype=np.int64), process=False)
        origin = np.asarray(fa.get("face__origin_kind", np.full(len(source.faces), -1)))
        iface = np.asarray(fa.get("face__interface_id", np.full(len(source.faces), -1)))
        roi_ids = np.flatnonzero((origin == 1) | (iface >= 0))
        area = np.asarray(source.area_faces, dtype=np.float64)
        entry: dict = {
            "lineage_id": lineage, "component": comp["asset_id"], "fragment": frag["asset_id"],
            "ancestor": ancestor, "damaged_faces": int(len(clean.faces)),
            "clean_faces": int(len(source.faces)),
            "clean_roi_faces": int(roi_ids.size),
            "clean_roi_area_mm2": float(area[roi_ids].sum()),
            "clean_area_mm2": float(source.area),
            "clean_roi_area_fraction": float(area[roi_ids].sum() / max(area.sum(), 1e-12)),
            "sweep": {},
        }
        rule_tol = origin_colocation_tolerance_mm(spacing_mm=args.spacing_mm,
                                                  realized_recession_mm=0.05)
        entry["rule_tol_mm"] = rule_tol
        for tol in sorted({0.05, 0.1, 0.25, 0.5, 1.0, round(rule_tol, 4)}):
            for band in (rule_tol + 3.0,):
                t1 = time.time()
                o, i, rep = classify_face_origin(
                    clean, source, origin=origin, interface_id=iface, roi_ids=roi_ids,
                    tol_mm=float(tol), roi_tol_mm=float(band))
                rep["seconds"] = round(time.time() - t1, 2)
                rep["roi_band_mm"] = float(band)
                entry["sweep"][f"tol={tol:g}|band={band:g}"] = rep
        entry["seconds"] = round(time.time() - t0, 2)
        report["lineages"][lineage] = entry
        print(json.dumps({"lineage": lineage, "rule_tol_mm": rule_tol,
                          "sweep": {k: {"classes": v["classes"],
                                        "area_fraction": {kk: round(vv, 5) for kk, vv
                                                          in v["class_area_fraction"].items()},
                                        "mapped_fraction": round(v["mapped_fraction"], 4),
                                        "ambiguous_reasons": v["ambiguous_reasons"]}
                                    for k, v in entry["sweep"].items()}}, indent=1), flush=True)
        if done >= int(args.lineages):
            break
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(report, indent=1), encoding="utf-8")
        print("wrote", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
