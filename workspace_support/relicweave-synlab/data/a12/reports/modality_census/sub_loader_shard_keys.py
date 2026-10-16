"""READ-ONLY: dump the raw keys/shapes/dtypes of the packaged shards the loader reads.

Creates nothing, writes nothing (run with ``python -B``).  Only reads npz/tar members and the
index JSONs, so it is safe against both exported packages.
"""

from __future__ import annotations

import io
import json
import sys
import tarfile
from pathlib import Path

import numpy as np

ROOT = Path(r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab")
PKGS = {
    "next_experiment": ROOT / "data/a12_exports/next_experiment/training_package",
    "closed_loop": ROOT / "data/a12_exports/closed_loop/training_package",
}


def show(label: str, arr: np.ndarray) -> None:
    print(f"    {label:34s} shape={str(arr.shape):22s} dtype={arr.dtype}")


for name, pkg in PKGS.items():
    print("=" * 100)
    print(f"PACKAGE {name}: {pkg}")
    print("=" * 100)

    obs_index = json.loads((pkg / "deploy/obs/index.json").read_text())
    geo_index = json.loads((pkg / "deploy/geometry/index.json").read_text())
    tok_index = json.loads((pkg / "deploy/tokens/index.json").read_text())

    obs_rows = obs_index["rows"]
    geo_rows = geo_index["rows"]
    tok_rows = tok_index["rows"]
    fid = sorted(geo_rows)[0]
    geo_entry = geo_rows[fid]
    tok_entry = tok_rows[fid]
    obs_entry = obs_rows[fid]

    print(f"\n[1] loader index lookup key (geometry) = {fid!r}")
    print(f"    geometry entry   = {json.dumps(geo_entry, sort_keys=True)}")
    print(f"    tokens entry     = {json.dumps(tok_entry, sort_keys=True)}")
    print(f"    obs entry        = {json.dumps(obs_entry, sort_keys=True)}")

    geo_npz = pkg / "deploy" / geo_entry["shard"]
    print(f"\n[2] geometry shard {geo_entry['shard']} ({geo_npz.stat().st_size} bytes)")
    with np.load(geo_npz, allow_pickle=False) as data:
        names = list(data.files)
        print(f"    npz array-name count = {len(names)}")
        prefix = f"{geo_entry['opaque']}__"
        stripped = sorted(k[len(prefix):] for k in names if k.startswith(prefix))
        print(f"    arrays under prefix {prefix!r} = {stripped}")
        print("    -> _read_shard() strips the prefix and returns exactly those keys")
        for key in stripped:
            show(key, data[prefix + key])
        other = sorted(k for k in names if not k.startswith(prefix))
        print(f"    arrays NOT matching this fragment's prefix = {other[:8]}")

    tok_npz = pkg / "deploy" / tok_entry["shard"]
    print(f"\n[3] token shard {tok_entry['shard']} ({tok_npz.stat().st_size} bytes)")
    with np.load(tok_npz, allow_pickle=False) as data:
        names = list(data.files)
        prefix = f"{tok_entry['opaque']}__"
        stripped = sorted(k[len(prefix):] for k in names if k.startswith(prefix))
        print(f"    arrays under prefix {prefix!r} = {stripped}")
        for key in stripped:
            show(key, data[prefix + key])

    tar_path = pkg / "deploy" / obs_entry["shard"]
    print(f"\n[4] obs shard {obs_entry['shard']} ({tar_path.stat().st_size} bytes)")
    with tarfile.open(tar_path, "r") as tar:
        members = tar.getnames()
        print(f"    tar member count = {len(members)}")
        print(f"    member sample = {members[:6]}")
        for suffix, key, dtype in (("tiles.npy", "rgb", np.uint8),
                                   ("valid.npy", "valid", bool),
                                   ("view_pos.npy", "view_pos", np.float32)):
            member = tar.extractfile(f"{obs_entry['opaque']}/{suffix}")
            if member is None:
                print(f"    MISSING {obs_entry['opaque']}/{suffix}")
                continue
            arr = np.load(io.BytesIO(member.read()), allow_pickle=False)
            show(f"{key} ({suffix})", arr)
            print(f"      -> np.asarray({key}, dtype={np.dtype(dtype).name}).shape == {arr.shape}")

print("\nDONE")
sys.exit(0)
