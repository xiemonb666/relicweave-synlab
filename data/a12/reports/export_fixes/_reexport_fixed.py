"""Re-export one release with the fixed writer (D1/D2/D3) into a new package directory.

Usage:
  python _reexport_fixed.py <store_root> <release_id> <out_dir>

Writes only into ``<out_dir>`` (a new directory): the pre-fix package stays byte-identical so the
before/after comparison in ``docs/a12/export_guide.md`` measures two real exports of the same
release rather than one export measured twice.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from synlab.storage.export import export_training_package  # noqa: E402
from synlab.storage.store import AssetStore  # noqa: E402


def main(store_root: str, release_id: str, out_dir: str) -> int:
    store = AssetStore(store_root)
    target = Path(out_dir)
    started = time.time()
    package = export_training_package(store, release_id, target,
                                      formats=("parquet", "npz", "zarr", "tar"))
    record = {
        "store": str(store_root), "release_id": release_id, "out_dir": str(target),
        "seconds": time.time() - started,
        "package_id": package.get("package_id"),
        "manifest_hash": package.get("manifest_hash"),
        "bytes_total": package.get("bytes_total"),
        "counts_total": package.get("counts_total"),
        "counts": package.get("counts"),
        "views": package.get("views"),
        "separation": package.get("separation"),
        "reference_closure": {k: v for k, v in (package.get("reference_closure") or {}).items()
                              if k != "problems"},
        "token_cache": package.get("token_cache"),
        "obs_index_view_pos": (json.loads((target / "deploy/obs/index.json").read_text(
            encoding="utf-8")).get("view_pos") if (target / "deploy/obs/index.json").exists()
            else None),
        "geometry_index_frame_id": (json.loads((target / "deploy/geometry/index.json").read_text(
            encoding="utf-8")).get("frame_id")
            if (target / "deploy/geometry/index.json").exists() else None),
    }
    out = Path(__file__).with_name(f"_reexport_{target.name}.json")
    out.write_text(json.dumps(record, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps(record, indent=2, ensure_ascii=False, default=str))
    print("wrote", out)
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 4:
        raise SystemExit(__doc__)
    raise SystemExit(main(sys.argv[1], sys.argv[2], sys.argv[3]))
