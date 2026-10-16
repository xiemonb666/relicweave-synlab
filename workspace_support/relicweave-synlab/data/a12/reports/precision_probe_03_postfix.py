"""precision audit probe 03 - post-fix state sweep across every store.

For each store under ``data/`` that has a ``metadata.sqlite`` the probe reports, read only:

* role histogram (subset of interest)
* fracture-interface 2D signal: ``surface_tag == 2`` (rim) pixels over all views of every
  ``obs_result`` / ``label_bundle``, plus the object-pixel denominator
* metadata keys relevant to the calibration-precision axis
  (``calibration_rev`` / ``rig_calibration_rev`` / ``intrinsics_profile_id`` /
  ``px_per_mm`` / ``r_eff_mm`` / ``scale_drift`` / ``oracle_comparison``)
* ``face__origin_kind`` / ``face__interface_id`` presence in ``physical_component``
* ``iface_*`` arrays in the truth layers
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sqlite3
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[3]

ROLES = ("obs_result", "obs_view", "label_bundle", "physical_component", "physical_truth",
         "visible_labels", "clean_truth", "fragment_mesh", "mother_mesh", "degrade_measurement",
         "obs_fused_geometry", "feature_bundle")

CALIB_KEYS = ("calibration_rev", "rig_calibration_rev", "intrinsics_profile_id",
              "calibration_id", "px_per_mm", "r_eff_mm", "scale_drift", "scale_valid",
              "oracle_comparison", "u_position_mm", "working_distance_mm", "region_id_map",
              "surface_tag_pixels", "iface_rim_pixels", "origin_kind", "interface_id",
              "loss_mask", "eligible_as_negative")


def flat_meta_keys(obj, prefix="") -> set[str]:
    """meta_json stores dotted paths as flat string keys; collect both forms."""
    keys: set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            keys.add(str(k))
            keys |= flat_meta_keys(v, prefix + str(k) + ".")
    return keys


def scan_store(db: pathlib.Path) -> dict:
    rec: dict = {"assets_total": 0}
    try:
        con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        return {"error": str(exc)}
    cur = con.cursor()
    cur.execute("SELECT role, COUNT(*) FROM assets GROUP BY role")
    hist = {r[0]: int(r[1]) for r in cur.fetchall()}
    rec["assets_total"] = sum(hist.values())
    rec["roles"] = hist

    # --- rim pixels over obs_result / label_bundle -------------------------------
    rim_total = 0
    tag_total = 0
    obj_total = 0
    n_obs = 0
    per_asset = []
    for role in ("obs_result", "label_bundle"):
        cur.execute("SELECT asset_id, meta_json FROM assets WHERE role=?", (role,))
        for asset_id, meta_json in cur.fetchall():
            adir = db.parent / "assets" / asset_id
            npz = adir / "arrays.npz"
            if not npz.exists():
                continue
            n_obs += 1
            a_rim = a_tag = a_obj = 0
            try:
                with np.load(npz, allow_pickle=False) as z:
                    for k in z.files:
                        if "surface_tag" not in k and "surface_tag_map" not in k:
                            continue
                        arr = np.asarray(z[k])
                        u, c = np.unique(arr, return_counts=True)
                        d = {int(x): int(y) for x, y in zip(u.tolist(), c.tolist())}
                        a_rim += d.get(2, 0)
                        a_tag += sum(d.values())
                        a_obj += sum(v for kk, v in d.items() if kk >= 0)
            except Exception as exc:  # pragma: no cover - defensive
                per_asset.append({"asset_id": asset_id, "role": role, "error": str(exc)})
                continue
            if a_tag:
                per_asset.append({"asset_id": asset_id, "role": role, "rim_px": a_rim,
                                  "tag_px": a_tag, "object_px": a_obj})
            rim_total += a_rim
            tag_total += a_tag
            obj_total += a_obj
    rec["rim"] = {"n_assets_scanned": n_obs, "rim_px": rim_total, "tag_px": tag_total,
                  "object_px": obj_total,
                  "rim_frac_of_object": (rim_total / obj_total) if obj_total else None,
                  "rim_frac_of_frame": (rim_total / tag_total) if tag_total else None,
                  "n_assets_with_rim": sum(1 for p in per_asset if p.get("rim_px", 0) > 0),
                  "per_asset": per_asset[:40]}

    # --- physical component face provenance --------------------------------------
    pc = {"n": 0, "origin_kind_hist": {}, "has_interface_id": 0, "interface_id_hist": {}}
    cur.execute("SELECT asset_id FROM assets WHERE role='physical_component'")
    for (asset_id,) in cur.fetchall():
        npz = db.parent / "assets" / asset_id / "arrays.npz"
        if not npz.exists():
            continue
        pc["n"] += 1
        try:
            with np.load(npz, allow_pickle=False) as z:
                keys = list(z.files)
                ok = [k for k in keys if "origin_kind" in k]
                iid = [k for k in keys if "interface_id" in k]
                if iid:
                    pc["has_interface_id"] += 1
                    a = np.asarray(z[iid[0]]).reshape(-1)
                    u, c = np.unique(a, return_counts=True)
                    for x, y in zip(u.tolist(), c.tolist()):
                        pc["interface_id_hist"][str(int(x))] = (
                            pc["interface_id_hist"].get(str(int(x)), 0) + int(y))
                if ok:
                    a = np.asarray(z[ok[0]]).reshape(-1)
                    u, c = np.unique(a, return_counts=True)
                    for x, y in zip(u.tolist(), c.tolist()):
                        pc["origin_kind_hist"][str(int(x))] = (
                            pc["origin_kind_hist"].get(str(int(x)), 0) + int(y))
        except Exception:  # pragma: no cover - defensive
            continue
    rec["physical_component"] = pc

    # --- truth-layer iface arrays -------------------------------------------------
    tl = {}
    for role in ("clean_truth", "physical_truth", "visible_labels"):
        cur.execute("SELECT asset_id FROM assets WHERE role=?", (role,))
        ids = [r[0] for r in cur.fetchall()]
        keyset: dict[str, int] = {}
        n_arr = 0
        for asset_id in ids:
            npz = db.parent / "assets" / asset_id / "arrays.npz"
            if not npz.exists():
                continue
            with np.load(npz, allow_pickle=False) as z:
                for k in z.files:
                    if k.startswith("iface") or "rim" in k:
                        keyset[k] = keyset.get(k, 0) + 1
                        n_arr += 1
        tl[role] = {"n_assets": len(ids), "iface_keys": keyset}
    rec["truth_layers"] = tl

    # --- metadata key presence for the calibration axis ---------------------------
    keyhits: dict[str, int] = {k: 0 for k in CALIB_KEYS}
    cur.execute("SELECT role, meta_json FROM assets")
    n_scanned = 0
    for role, meta_json in cur.fetchall():
        n_scanned += 1
        try:
            mj = json.loads(meta_json)
        except Exception:  # pragma: no cover - defensive
            continue
        keys = flat_meta_keys(mj)
        for k in CALIB_KEYS:
            if k in keys:
                keyhits[k] += 1
    rec["meta_key_presence"] = {"n_assets_scanned": n_scanned, **keyhits}
    con.close()
    return rec


def discover(root: pathlib.Path) -> list[pathlib.Path]:
    out = []
    for p in sorted(root.glob("data/**/metadata.sqlite")):
        out.append(p)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="data")
    ap.add_argument("--out", default="data/a12/reports/precision_probe_03_postfix.json")
    ap.add_argument("--only", default=None, help="comma separated substring filter on the path")
    args = ap.parse_args()

    dbs = discover(ROOT)
    if args.only:
        subs = [s for s in args.only.split(",") if s]
        dbs = [d for d in dbs if any(s in d.as_posix() for s in subs)]
    report = {}
    for db in dbs:
        rel = db.parent.relative_to(ROOT).as_posix()
        try:
            report[rel] = scan_store(db)
        except Exception as exc:  # pragma: no cover - defensive
            report[rel] = {"error": f"{type(exc).__name__}: {exc}"}
        print(f"scanned {rel}", file=sys.stderr)
    text = json.dumps(report, indent=2, ensure_ascii=False)
    (ROOT / args.out).write_text(text, encoding="utf-8")
    print("wrote", args.out)
    # short human summary
    for rel, rec in report.items():
        if "error" in rec:
            print(f"{rel}: ERROR {rec['error']}")
            continue
        rim = rec.get("rim", {})
        print(f"{rel}: assets={rec['assets_total']} rim_px={rim.get('rim_px')} "
              f"object_px={rim.get('object_px')} rim_frac_obj={rim.get('rim_frac_of_object')} "
              f"pc_interfaces={rec['physical_component'].get('has_interface_id')}/"
              f"{rec['physical_component'].get('n')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
