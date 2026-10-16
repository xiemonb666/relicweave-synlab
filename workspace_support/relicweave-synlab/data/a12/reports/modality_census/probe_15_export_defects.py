"""Probe 15: INDEPENDENT verification of token rank / view_pos / frame_id claims (READ ONLY)."""
from __future__ import annotations
import json, tarfile, io, collections
from pathlib import Path
import numpy as np

ROOT = Path(r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab")
OUT = ROOT / "data" / "a12" / "reports" / "modality_census"
PKGS = {
    "next_experiment": ROOT / "data" / "a12_exports" / "next_experiment" / "training_package",
    "closed_loop": ROOT / "data" / "a12_exports" / "closed_loop" / "training_package",
}

L = []
w = L.append


def main() -> None:
    w("# probe_15 INDEPENDENT verification: tokens rank / view_pos / frame_id")
    w("")
    for label, pkg in PKGS.items():
        w("=" * 96)
        w(f"## PACKAGE {label}")
        tdir = pkg / "deploy" / "obs"
        gdir = pkg / "deploy" / "geometry"
        kdir = pkg / "deploy" / "tokens"

        # ---------- view_pos over all tar members
        vp_stats = []
        member_names = []
        for tar_path in sorted(tdir.glob("*.tar")):
            with tarfile.open(tar_path, "r") as tf:
                for m in tf.getmembers():
                    if m.name.endswith("view_pos.npy"):
                        a = np.load(io.BytesIO(tf.extractfile(m).read()))
                        vp_stats.append((tar_path.name, m.name, a.shape, a.dtype,
                                         float(np.min(a)), float(np.max(a)),
                                         float(np.abs(a).max()), int(np.count_nonzero(a))))
                    member_names.append(m.name)
        w(f"  obs tar members total = {len(member_names)}")
        w(f"  view_pos.npy members  = {len(vp_stats)}")
        if vp_stats:
            allzero = sum(1 for s in vp_stats if s[6] == 0.0)
            w(f"  view_pos members that are IDENTICALLY ZERO = {allzero} / {len(vp_stats)}")
            for s in vp_stats[:4]:
                w(f"    {s[0]} :: {s[1]}  shape={s[2]} dtype={s[3]} min={s[4]} max={s[5]} "
                  f"absmax={s[6]} nonzero={s[7]}")
        # suffix histogram
        suf = collections.Counter(Path(n).name for n in member_names)
        w(f"  member basename histogram: {dict(suf)}")

        # ---------- tokens rank
        w("")
        ranks = []
        for npz in sorted(kdir.glob("shard_*.npz")):
            with np.load(npz, allow_pickle=False) as z:
                keys = [k for k in z.files if k.endswith("__tokens")]
                for k in keys[:6]:
                    T = z[k]
                    if T.ndim != 2 or T.shape[0] < 2:
                        continue
                    s = np.linalg.svd(T.astype(np.float64), compute_uv=False)
                    tol = s[0] * max(T.shape) * np.finfo(np.float64).eps
                    r = int(np.count_nonzero(s > tol))
                    ti = z.get(k.replace("__tokens", "__token_input"))
                    same0 = None
                    if ti is not None and ti.shape[0] == T.shape[0]:
                        same0 = bool(np.array_equal(T[:, 0], ti))
                    ranks.append((npz.name, k, T.shape, float(s[0]),
                                  float(s[1]) if s.size > 1 else 0.0,
                                  float(s[2]) if s.size > 2 else 0.0, r, same0))
        w(f"  token arrays inspected = {len(ranks)}")
        for x in ranks[:6]:
            w(f"    {x[0]} {x[1]}: shape={x[2]} sv[0]={x[3]:.6g} sv[1]={x[4]:.6g} sv[2]={x[5]:.6g} "
              f"numerical_rank={x[6]}  tokens[:,0]==token_input: {x[7]}")
        if ranks:
            w(f"  numerical rank histogram: {dict(collections.Counter(x[6] for x in ranks))}")
            w(f"  sv[1]/sv[0] max over all = {max(x[4]/max(x[3],1e-30) for x in ranks):.3e}")

        # ---------- frame_id
        w("")
        fid = []
        for npz in sorted(gdir.glob("shard_*.npz")):
            with np.load(npz, allow_pickle=False) as z:
                for k in [x for x in z.files if x.endswith("__frame_id")][:6]:
                    a = z[k]
                    pts = z.get(k.replace("__frame_id", "__points"))
                    n = a.shape[0]
                    # candidate: arange(n) % views  -- infer views from tile_valid if present
                    views = None
                    tk = None
                    fid.append((npz.name, k, n, a.dtype, int(a.max()) + 1, int(len(np.unique(a)))))
        w(f"  frame_id arrays inspected = {len(fid)}")
        for x in fid[:6]:
            w(f"    {x[0]} {x[1]}: n={x[2]} dtype={x[3]} distinct_values={x[5]} max+1={x[4]}")
        w(f"  distinct-value histogram: {dict(collections.Counter(x[5] for x in fid))}")

        # ---------- cross-check frame_id == arange(n) % views
        w("")
        matches = 0
        checks = 0
        for npz in sorted(gdir.glob("shard_*.npz")):
            with np.load(npz, allow_pickle=False) as z:
                tknpz = kdir / npz.name
                for k in [x for x in z.files if x.endswith("__frame_id")][:8]:
                    a = z[k]
                    n = a.shape[0]
                    views = None
                    if tknpz.exists():
                        with np.load(tknpz, allow_pickle=False) as tz:
                            tv = k.replace("__frame_id", "__tile_valid")
                            if tv in tz.files:
                                views = int(tz[tv].shape[0])
                    if views is None:
                        continue
                    checks += 1
                    if np.array_equal(a, (np.arange(n) % views).astype(a.dtype)):
                        matches += 1
        w(f"  frame_id == arange(n) % n_views  : {matches} / {checks} checked")

        # ---------- tokens formula check
        w("")
        w("  tokens[:,k] == flat*(1-1e-6*k) hypothesis check (export.py:262-274):")
        n_ok = 0
        n_chk = 0
        worst = 0.0
        for npz in sorted(kdir.glob("shard_*.npz")):
            with np.load(npz, allow_pickle=False) as z:
                for k in [x for x in z.files if x.endswith("__tokens")][:3]:
                    T = z[k].astype(np.float64)
                    ti = z.get(k.replace("__tokens", "__token_input"))
                    if ti is None or T.ndim != 2:
                        continue
                    n_chk += 1
                    flat = ti.astype(np.float64)
                    kk = np.arange(T.shape[1], dtype=np.float64)
                    pred = flat[:, None] * (1.0 - 1e-6 * kk)[None, :]
                    d = float(np.abs(T - pred).max())
                    worst = max(worst, d)
                    n_ok += 1 if d < 1e-4 else 0
        w(f"    fragments checked = {n_chk}; matching the formula = {n_ok}; worst abs diff = {worst:.3e}")

    txt = "\n".join(L)
    (OUT / "probe_15_export_defects.txt").write_text(txt, encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    main()
