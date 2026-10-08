"""precision audit probe 04 - calibration + exported-feature precision (dims 4 and 6).

Read only.

Calibration (dim 4):
  * every pixel focal length actually used by rendered frames (K[0,0]) from
    ``obs_result`` / ``obs_view`` arrays, against the working distance implied by depth
  * the documented five-distance mm/px ladder from ``synlab.degrade.specs``
  * which calibration axes are CANDIDATE / DERIVED / MEASURED in the spec objects
  * presence of ``calibration_rev`` / ``rig_calibration_rev`` / ``intrinsics_profile_id``
    in asset meta (a required scan-rig field)

Exported feature tokens (dim 6):
  * ``tokens`` effective rank (sv[1]/sv[0]) and ``tokens[:,0] == token_input``
  * ``view_pos`` non-zero fraction and value range
  * ``frame_id`` vs ``arange(n) % n_views``
  * relations parquet: ``loss_mask`` vs ``valid`` vs ``kind``, ``eligible_as_negative``
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import sqlite3
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[3]


def discover_packages(root: pathlib.Path) -> list[pathlib.Path]:
    out = []
    for p in sorted(root.glob("data/**/deploy/tokens/index.json")):
        out.append(p.parent.parent.parent)
    return out


def probe_tokens(pkg: pathlib.Path) -> dict:
    tok = pkg / "deploy" / "tokens"
    obs = pkg / "deploy" / "obs"
    geo = pkg / "deploy" / "geometry"
    rec: dict = {"package": pkg.relative_to(ROOT).as_posix()}
    # ---- tokens ----
    shards = sorted(tok.glob("shard_*.npz"))
    rec["token_shards"] = len(shards)
    detail = []
    for sh in shards[:2]:
        with np.load(sh, allow_pickle=False) as z:
            ents = sorted({k.split("__")[0] for k in z.files})
            for e in ents[:4]:
                T = np.asarray(z[f"{e}__tokens"], dtype=np.float64)
                ti = (np.asarray(z[f"{e}__token_input"], dtype=np.float64)
                      if f"{e}__token_input" in z.files else None)
                sv = np.linalg.svd(T, compute_uv=False)
                rec_ent = {
                    "entity": e, "shape": list(T.shape),
                    "sv0": float(sv[0]), "sv1": float(sv[1]),
                    "sv1_over_sv0": float(sv[1] / sv[0]) if sv[0] else None,
                    "rank_eps": int(np.sum(sv > sv[0] * T.shape[1] * np.finfo(np.float64).eps)),
                    "rank_1e-3": int(np.sum(sv > 1e-3 * sv[0])),
                    "rank_1e-2": int(np.sum(sv > 1e-2 * sv[0])),
                    "rank_1e-1": int(np.sum(sv > 1e-1 * sv[0])),
                    "n_sv": int(sv.size),
                }
                if ti is not None:
                    rec_ent["tokens0_equals_token_input_maxabs"] = float(
                        np.max(np.abs(T[:, 0] - ti)))
                    # the historic writer form: tokens[:,k] = flat*(1-1e-6*k)
                    k = np.arange(T.shape[1], dtype=np.float64)
                    model = np.outer(T[:, 0], 1.0 - 1e-6 * k)
                    rec_ent["broadcast_model_maxabs"] = float(np.max(np.abs(T - model)))
                detail.append(rec_ent)
    rec["tokens_detail"] = detail
    # ---- obs shard tar members ----
    import tarfile
    obs_rec = {"shards": [], }
    for sh in sorted(obs.glob("shard_*.tar"))[:4]:
        with tarfile.open(sh) as tf:
            names = tf.getnames()
            entry = {"shard": sh.name, "members": len(names),
                     "has_view_pos": any("view_pos" in n for n in names),
                     "has_valid": any("valid" in n for n in names)}
            import io
            for want in ("view_pos.npy", "valid.npy"):
                hit = [n for n in names if n.endswith(want)]
                if not hit:
                    continue
                m = tf.extractfile(hit[0])
                if m is None:
                    continue
                a = np.load(io.BytesIO(m.read()), allow_pickle=False)
                entry[want.replace(".npy", "")] = {
                    "shape": list(a.shape), "dtype": str(a.dtype),
                    "absmax": float(np.max(np.abs(a.astype(np.float64)))) if a.size else None,
                    "nonzero": int(np.count_nonzero(a)),
                    "size": int(a.size),
                    "mean": float(np.mean(a.astype(np.float64))) if a.size else None,
                    "true_frac": (float(np.count_nonzero(a) / a.size) if a.size else None),
                }
                m.close()
            obs_rec["shards"].append(entry)
    rec["obs"] = obs_rec
    # ---- geometry frame_id ----
    gdetail = []
    for sh in sorted(geo.glob("shard_*.npz"))[:2]:
        with np.load(sh, allow_pickle=False) as z:
            ents = sorted({k.split("__")[0] for k in z.files})
            for e in ents[:4]:
                fid = (np.asarray(z[f"{e}__frame_id"]) if f"{e}__frame_id" in z.files else None)
                if fid is None:
                    continue
                n = fid.size
                candidates = {}
                for nv in (4, 12):
                    candidates[f"arange_mod_{nv}"] = bool(
                        np.array_equal(fid, (np.arange(n) % nv).astype(fid.dtype)))
                gdetail.append({"entity": e, "n": int(n),
                                "distinct": int(np.unique(fid).size),
                                "min": int(fid.min()), "max": int(fid.max()),
                                "matches": {k: v for k, v in candidates.items() if v}})
    rec["frame_id"] = gdetail
    # ---- geometry index: frame_id match fraction + view_pos declaration -------------
    gidx = pkg / "deploy" / "geometry" / "index.json"
    if gidx.exists():
        gi = json.loads(gidx.read_text(encoding="utf-8"))
        block = gi.get("frame_id")
        if isinstance(block, dict):
            rec["frame_id_index_block"] = {
                "definition": block.get("definition"),
                "measured": block.get("measured"),
                "tolerance_mm": block.get("tolerance_mm"),
                "sources": block.get("sources"),
                "unmatched_marker": block.get("unmatched_marker"),
            }
        else:
            rec["frame_id_index_block"] = None
        rec["geometry_index_keys"] = sorted(gi.keys())
    oidx = pkg / "deploy" / "obs" / "index.json"
    if oidx.exists():
        oi = json.loads(oidx.read_text(encoding="utf-8"))
        rec["obs_index"] = {k: oi.get(k) for k in ("channels", "forbidden_channels",
                                                   "opaque_naming", "schema")}
    # ---- parquet relations ----
    try:
        import pandas as pd
        rp = pkg / "research" / "relations.parquet"
        if rp.exists():
            df = pd.read_parquet(rp)
            rec["relations"] = {
                "rows": int(len(df)), "columns": list(df.columns),
                "kind_counts": (df["kind"].value_counts().to_dict()
                                if "kind" in df else None),
                "valid_true": int(df["valid"].sum()) if "valid" in df else None,
                "loss_mask_true": int(df["loss_mask"].sum()) if "loss_mask" in df else None,
                "loss_mask_equals_valid":
                    bool((df["loss_mask"] == df["valid"]).all())
                    if "loss_mask" in df and "valid" in df else None,
                "loss_mask_equals_kind_R2":
                    bool((df["loss_mask"] == (df["kind"] == "R2")).all())
                    if "loss_mask" in df and "kind" in df else None,
                "eligible_as_negative_true":
                    int(df["eligible_as_negative"].sum())
                    if "eligible_as_negative" in df else None,
                "has_observation_true":
                    int(df["has_observation"].sum()) if "has_observation" in df else None,
            }
    except Exception as exc:  # pragma: no cover - defensive
        rec["relations_error"] = f"{type(exc).__name__}: {exc}"
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/a12/reports/precision_probe_04_calib_tokens.json")
    args = ap.parse_args()
    sys.path.insert(0, str(ROOT))
    report: dict = {}

    # --- documented ladder vs the synthetic profiles -------------------------------
    try:
        from synlab.degrade.specs import capture_rig_spec  # type: ignore
        spec = capture_rig_spec()
        cam = spec.camera
        ladder = []
        for d in (50, 100, 150, 200, 250):
            mmpp = cam.mm_per_px(float(d))
            ladder.append({
                "distance_mm": d, "mm_per_px": float(mmpp),
                "px_per_mm": float(1.0 / mmpp),
                "px_for_0p2mm": float(0.2 / mmpp),
                "coverage_mm": float(2.0 * d * math.tan(math.radians(float(cam.fov_h_deg.value)) / 2.0)),
            })
        report["documented_ladder"] = {
            "focal_length_mm": float(cam.focal_mm),
            "focal_px": float(cam.focal_px),
            "pixel_pitch_mm": float(cam.pixel_pitch_mm.value),
            "px_per_mm_sensor": float(cam.px_per_mm_sensor),
            "fov_h_deg": float(cam.fov_h_deg.value),
            "f_number": float(cam.lens.aperture_ratio),
            "f_number_provenance": cam.lens.f_number.provenance,
            "f_number_note": cam.lens.f_number.note,
            "line_time_us": float(cam.line_time_us.value),
            "line_time_provenance": cam.line_time_us.provenance,
            "rows": ladder,
            "coverage_method": "W(d) = 2 d tan(FOV_h/2); s = W/N_x (p0518/t051)",
        }
    except Exception as exc:  # pragma: no cover - defensive
        report["documented_ladder_error"] = f"{type(exc).__name__}: {exc}"

    # --- real K values used in the rendered frames ---------------------------------
    krec: dict = {}
    for rel in ("data/a12/metadata.sqlite", "data/a12_final/store/metadata.sqlite",
                "data/a12_campaign/store/metadata.sqlite"):
        db = ROOT / rel
        if not db.exists():
            continue
        con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        cur = con.cursor()
        cur.execute("SELECT asset_id FROM assets WHERE role='obs_result'")
        fxs, zs, sizes = [], [], {}
        for (aid,) in cur.fetchall():
            npz = db.parent / "assets" / aid / "arrays.npz"
            if not npz.exists():
                continue
            with np.load(npz, allow_pickle=False) as z:
                for k in z.files:
                    if k.endswith(".K"):
                        K = np.asarray(z[k], dtype=np.float64)
                        depth = np.asarray(z[k[:-1] + "depth_z"], dtype=np.float64)
                        v = np.isfinite(depth) & (depth > 0)
                        fxs.append(float(K[0, 0]))
                        if v.any():
                            zs.append(float(np.median(depth[v])))
                        sizes[tuple(depth.shape)] = sizes.get(tuple(depth.shape), 0) + 1
        con.close()
        krec[rel] = {
            "n_views": len(fxs),
            "fx_min": float(np.min(fxs)) if fxs else None,
            "fx_max": float(np.max(fxs)) if fxs else None,
            "fx_median": float(np.median(fxs)) if fxs else None,
            "distinct_fx": sorted({round(v, 6) for v in fxs}),
            "z_median_mm_min": float(np.min(zs)) if zs else None,
            "z_median_mm_max": float(np.max(zs)) if zs else None,
            "view_shapes": {f"{k[0]}x{k[1]}": v for k, v in sizes.items()},
            "implied_mm_per_px_median": (
                float(np.median([z / f for z, f in zip(zs, fxs)])) if zs else None),
        }
    report["synthetic_frames"] = krec

    # --- packages -------------------------------------------------------------------
    report["packages"] = [probe_tokens(p) for p in discover_packages(ROOT)]

    text = json.dumps(report, indent=2, ensure_ascii=False)
    (ROOT / args.out).write_text(text, encoding="utf-8")
    print("wrote", args.out)
    print(json.dumps(report.get("documented_ladder", {}), indent=2, ensure_ascii=False)[:2500])
    return 0


if __name__ == "__main__":
    sys.exit(main())
