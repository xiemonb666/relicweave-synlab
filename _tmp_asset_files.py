"""Read-only: locate a demo asset's payload file on disk and report its hash."""
from __future__ import annotations

import argparse
import json
import pathlib
import sys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo-root", default=r"data\a12_demo")
    ap.add_argument("asset_ids", nargs="*")
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()
    root = pathlib.Path(args.demo_root)
    store = root / "store"
    out = {}
    for asset_id in args.asset_ids:
        meta_dir = store / "assets" / asset_id
        if not meta_dir.is_dir():
            out[asset_id] = {"error": "no such asset dir", "dir": str(meta_dir)}
            continue
        files = sorted(p.name for p in meta_dir.iterdir())
        files_meta = {}
        for name in files:
            info = meta_dir / name
            if info.is_file():
                files_meta[name] = {"bytes": info.stat().st_size,
                                    "sha256": None}
        # metadata json
        meta = None
        for name in files:
            if name.endswith(".json") and "meta" in name:
                try:
                    meta = json.loads((meta_dir / name).read_text(encoding="utf-8"))
                except Exception as exc:  # noqa: BLE001
                    meta = {"parse_error": str(exc)}
        out[asset_id] = {"dir": str(meta_dir), "files": files_meta, "meta": meta}
    if args.json_out:
        pathlib.Path(args.json_out).write_text(json.dumps(out, indent=2, ensure_ascii=False),
                                               encoding="utf-8")
    for asset_id, row in out.items():
        print(asset_id, row.get("error", ""))
        for name, info in (row.get("files") or {}).items():
            print("   ", name, info["bytes"])
        meta = row.get("meta")
        if isinstance(meta, dict):
            keep = {k: meta[k] for k in ("role", "schema", "unit", "frame", "qa_status",
                                         "label", "files") if k in meta}
            print("    meta:", json.dumps(keep, ensure_ascii=False)[:400])
    return 0


if __name__ == "__main__":
    sys.exit(main())
