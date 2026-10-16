"""Probe 11: 2D imagery -- per-route channels, resolution, views, real post-processing (READ ONLY)."""
from __future__ import annotations
import json, sqlite3, collections
from pathlib import Path
import numpy as np

ROOT = Path(r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab")
OUT = ROOT / "data" / "a12" / "reports" / "modality_census"
ASSETS = ROOT / "data" / "a12" / "assets"

L = []
w = L.append


def laplacian_var(g: np.ndarray) -> float:
    k = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], dtype=np.float32)
    from numpy.lib.stride_tricks import sliding_window_view
    if g.shape[0] < 3 or g.shape[1] < 3:
        return float("nan")
    win = sliding_window_view(g.astype(np.float32), (3, 3))
    return float(np.var(np.einsum("ijkl,kl->ij", win, k)))


def main() -> None:
    con = sqlite3.connect(f"file:{(ROOT/'data/a12/metadata.sqlite').as_posix()}?mode=ro&immutable=1",
                          uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "select asset_id, role, meta_json from assets where role in "
        "('obs_result','obs_view','feature_bundle','obs_fused_geometry')").fetchall()
    con.close()

    # ---------- A. obs_result: full per-frame channel inventory, resolution, distortion
    obs = [r for r in rows if r["role"] == "obs_result"]
    channels = collections.Counter()
    resolutions = collections.Counter()
    view_counts = collections.Counter()
    encodings = collections.Counter()
    focus = []
    dist_nonzero = 0
    n_dist = 0
    uncertainty = collections.Counter()
    rgb_dynamic = []
    blur_vals = []
    depth_valid_frac = []
    w("=" * 100)
    w(f"# probe_11 2D imagery   obs_result n={len(obs)}")
    w("")
    n_views_from_meta = collections.Counter()
    for r in obs:
        mj = json.loads(r["meta_json"])
        mm = mj.get("meta") or {}
        n_views_from_meta[int(mm.get("n_views") or 0)] += 1
        p = ASSETS / r["asset_id"] / "arrays.npz"
        with np.load(p, allow_pickle=False) as z:
            keys = list(z.files)
            for k in keys:
                channels[k.split(".", 1)[1] if "." in k else k] += 1
            vids = sorted({k.split(".")[0] for k in keys if k.startswith("v")})
            view_counts[len(vids)] += 1
            for v in vids:
                if f"{v}.rgb" in keys:
                    resolutions[tuple(z[f"{v}.rgb"].shape)] += 1
                if f"{v}.rgb_linear" in keys:
                    rgb_dynamic.append(float(z[f"{v}.rgb_linear"].max()))
                if f"{v}.depth_z" in keys and f"{v}.deployment_mask" in keys:
                    d = z[f"{v}.depth_z"]
                    dm = z[f"{v}.deployment_mask"]
                    depth_valid_frac.append(float(np.mean(dm)))
                if f"{v}.rgb" in keys:
                    g = z[f"{v}.rgb"].astype(np.float32).mean(axis=2)
                    bv = laplacian_var(g / 255.0)
                    if np.isfinite(bv):
                        blur_vals.append(bv)
                if f"{v}.uncertain_mask" in keys:
                    uncertainty["present"] += 1
                    uncertainty["true_px"] += int(np.count_nonzero(z[f"{v}.uncertain_mask"]))
                    uncertainty["total_px"] += int(z[f"{v}.uncertain_mask"].size)
                if f"{v}.dist" in keys:
                    n_dist += 1
                    if float(np.max(np.abs(z[f"{v}.dist"]))) > 1e-12:
                        dist_nonzero += 1
    w(f"  views per obs_result: {dict(view_counts)}")
    w(f"  n_views declared in meta: {dict(n_views_from_meta)}")
    w(f"  RGB resolutions (H,W,C): {dict(resolutions)}")
    w("  per-view channels present (count out of total frames):")
    for k, v in channels.most_common():
        w(f"      {k:22s} {v}")
    w(f"  distortion: frames with `dist` = {n_dist}; with any nonzero coefficient = {dist_nonzero}")
    w(f"  uncertain_mask: {uncertainty['present']} frames, true pixels {uncertainty['true_px']} / "
      f"{uncertainty['total_px']} = {100.0*uncertainty['true_px']/max(uncertainty['total_px'],1):.4f}%")
    w(f"  deployment_mask true fraction (mean over frames) = "
      f"{np.mean(depth_valid_frac) if depth_valid_frac else float('nan'):.4f} "
      f"(n={len(depth_valid_frac)} frames); min={min(depth_valid_frac) if depth_valid_frac else float('nan'):.4f} "
      f"max={max(depth_valid_frac) if depth_valid_frac else float('nan'):.4f}")
    bv = np.array(blur_vals)
    w(f"  RGB laplacian variance (sharpness proxy, n={bv.size}): min={bv.min():.6f} "
      f"median={np.median(bv):.6f} max={bv.max():.6f}  (lower = blurrier)")
    w(f"  rgb_linear max radiance: min={min(rgb_dynamic):.4f} median={np.median(rgb_dynamic):.4f} "
      f"max={max(rgb_dynamic):.4f}")
    w("")
    w("  per-asset: asset_id, n_views, resolution, dist_nonzero, uncertain_frac, deploy_frac")
    for r in obs[:12]:
        mj = json.loads(r["meta_json"])
        p = ASSETS / r["asset_id"] / "arrays.npz"
        with np.load(p, allow_pickle=False) as z:
            ks = list(z.files)
            vids = sorted({k.split(".")[0] for k in ks if k.startswith("v")})
            res = tuple(z[f"{vids[0]}.rgb"].shape) if vids and f"{vids[0]}.rgb" in ks else None
            dn = any(f"{v}.dist" in ks and float(np.max(np.abs(z[f"{v}.dist"]))) > 1e-12 for v in vids)
            uf = (np.mean([np.count_nonzero(z[f"{v}.uncertain_mask"])/z[f"{v}.uncertain_mask"].size
                           for v in vids if f"{v}.uncertain_mask" in ks])
                  if any(f"{v}.uncertain_mask" in ks for v in vids) else float("nan"))
            df = (np.mean([np.mean(z[f"{v}.deployment_mask"]) for v in vids
                           if f"{v}.deployment_mask" in ks])
                  if any(f"{v}.deployment_mask" in ks for v in vids) else float("nan"))
        w(f"    {r['asset_id']} nv={len(vids)} res={res} dist_nonzero={dn} "
          f"uncertain_frac={uf:.5f} deploy_frac={df:.4f}")

    # ---------- B. obs_view: deliverable-format frames + real post-processing numbers
    w("")
    w("=" * 100)
    ov = [r for r in rows if r["role"] == "obs_view"]
    w(f"# obs_view n={len(ov)}  -- pixel-level delivery variants")
    enc = collections.Counter()
    optics = collections.Counter()
    variants = collections.Counter()
    units_keys = collections.Counter()
    scene_keys = collections.Counter()
    res_ov = collections.Counter()
    for r in ov:
        mj = json.loads(r["meta_json"])
        variants[str(mj.get("variant"))] += 1
        for k, v in mj.items():
            if k.startswith("units."):
                units_keys[k[len("units."):]] += 1
            if k.startswith("payload.scene."):
                scene_keys[k[len("payload.scene."):]] += 1
            if ".encoding" in k:
                enc[str(v)] += 1
            if ".optics_domain" in k:
                optics[str(v)] += 1
        p = ASSETS / r["asset_id"] / "arrays.npz"
        with np.load(p, allow_pickle=False) as z:
            for k in z.files:
                if k.endswith(".rgb"):
                    res_ov[tuple(z[k].shape)] += 1
    w(f"  variants: {dict(variants)}")
    w(f"  per-frame encoding: {dict(enc)}")
    w(f"  optics_domain: {dict(optics)}")
    w(f"  delivered RGB resolutions: {dict(res_ov)}")
    w(f"  declared units keys (count of assets declaring): ")
    for k, v in units_keys.most_common():
        w(f"      {k:36s} {v}")
    w(f"  payload.scene keys: ")
    for k, v in scene_keys.most_common(40):
        w(f"      {k:40s} {v}")

    # ---------- C. feature_bundle global_rgb
    w("")
    w("=" * 100)
    fb = [r for r in rows if r["role"] == "feature_bundle"]
    w(f"# feature_bundle n={len(fb)}  -- encoder-visible RGB + fields")
    fres = collections.Counter()
    pcsizes = []
    tok = []
    for r in fb:
        p = ASSETS / r["asset_id"] / "arrays.npz"
        with np.load(p, allow_pickle=False) as z:
            ks = set(z.files)
            if "global_rgb" in ks:
                fres[tuple(z["global_rgb"].shape)] += 1
            if "point_cloud__xyz" in ks:
                pcsizes.append(int(z["point_cloud__xyz"].shape[0]))
            if "token_index" in ks:
                tok.append(int(z["token_index"].shape[0]))
            if "view_tokens" in ks:
                fres[f"view_tokens{tuple(z['view_tokens'].shape)}"] += 1
    w(f"  global_rgb shapes: {dict(fres)}")
    a = np.array(pcsizes)
    w(f"  point_cloud__xyz N (n={a.size}): min={a.min()} median={int(np.median(a))} max={a.max()} sum={a.sum()}")
    t = np.array(tok)
    w(f"  token_index N (n={t.size}): min={t.min()} median={int(np.median(t))} max={t.max()} sum={t.sum()}")

    # ---------- D. obs_fused_geometry point counts
    w("")
    fg = [r for r in rows if r["role"] == "obs_fused_geometry"]
    w(f"# obs_fused_geometry n={len(fg)}")
    pts = []
    for r in fg:
        p = ASSETS / r["asset_id"] / "arrays.npz"
        with np.load(p, allow_pickle=False) as z:
            if "payload.points" in z.files:
                pts.append(int(z["payload.points"].shape[0]))
    pa = np.array(pts)
    w(f"  fused point count (n={pa.size}): min={pa.min()} median={int(np.median(pa))} max={pa.max()} sum={pa.sum()}")

    txt = "\n".join(L)
    (OUT / "probe_11_imagery.txt").write_text(txt, encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    main()
