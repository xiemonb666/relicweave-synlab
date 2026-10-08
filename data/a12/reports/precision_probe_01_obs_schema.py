"""precision audit probe 01 - schema + one obs_result payload, read only."""
from __future__ import annotations

import json
import pathlib
import sqlite3
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[3]


def main() -> int:
    store = ROOT / "data/a12/metadata.sqlite"
    con = sqlite3.connect(f"file:{store.as_posix()}?mode=ro", uri=True)
    cur = con.cursor()
    cur.execute("PRAGMA table_info(assets)")
    print("assets columns:", [r[1] for r in cur.fetchall()])
    cur.execute("PRAGMA table_info(blobs)")
    print("blobs columns:", [r[1] for r in cur.fetchall()])
    cur.execute("SELECT asset_id, role, meta_json FROM assets WHERE role='obs_result' LIMIT 1")
    asset_id, role, meta_json = cur.fetchone()
    print("asset:", asset_id, role)
    mj = json.loads(meta_json)
    print("meta_json top-level keys:", sorted(mj.keys())[:40])
    inner = mj.get("meta", {})
    print("inner meta keys:", sorted(inner.keys())[:60])
    print(json.dumps({k: v for k, v in list(inner.items())[:25]}, ensure_ascii=False)[:3000])
    cur.execute("SELECT blob_hash, relative_path, size FROM blobs LIMIT 5")
    cols = [d[0] for d in cur.description]
    for row in cur.fetchall():
        print("blob row:", dict(zip(cols, [str(v)[:120] for v in row])))
    con.close()
    adir = ROOT / "data/a12/assets" / asset_id
    print("asset dir exists:", adir.exists(), "listing:", sorted(p.name for p in adir.iterdir())[:20])
    npz = adir / "arrays.npz"
    if npz.exists():
        with np.load(npz, allow_pickle=False) as z:
            print("arrays.npz keys:", sorted(z.files)[:80])
            for k in sorted(z.files):
                if k.endswith(".rgb") or k.endswith(".depth_z") or k == "K" or k.endswith(".K"):
                    a = z[k]
                    print(f"  {k}: shape={a.shape} dtype={a.dtype}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
