"""Read-only: list the display GLB asset ids that the demo manifest points at."""
from __future__ import annotations

import argparse
import json
import pathlib
import sys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo-root", default=r"data\a12_demo")
    ap.add_argument("--entry", default=None, help="substring filter on entry_id")
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()
    root = pathlib.Path(args.demo_root)
    manifest = json.loads((root / "demo_manifest.json").read_text(encoding="utf-8"))
    out = []
    for entry in manifest["entries"]:
        eid = str(entry.get("entry_id"))
        if args.entry and args.entry not in eid:
            continue
        row = {"entry_id": eid, "kind": entry.get("kind"), "status": entry.get("status"),
               "glbs": []}
        art = entry.get("artifacts") or {}
        if isinstance(art.get("fragments"), list):
            for frag in art["fragments"]:
                row["glbs"].append({"fragment_id": frag.get("fragment_id", "?"),
                                    "asset_id": frag.get("asset_id"),
                                    "role": frag.get("role"), "key": frag.get("key")})
        for name, value in art.items():
            if name == "fragments":
                continue
            if isinstance(value, dict) and value.get("asset_id"):
                row["glbs"].append({"name": name, "asset_id": value.get("asset_id"),
                                    "role": value.get("role"), "key": value.get("key")})
        levels = (entry.get("metrics") or {}).get("levels")
        if isinstance(levels, list):
            for lv in levels:
                glb = ((lv.get("artifacts") or {}).get("glb")) or None
                if glb:
                    row["glbs"].append({"name": f"L{lv.get('level')}", "asset_id": glb.get("asset_id"),
                                        "role": glb.get("role"), "key": glb.get("key"),
                                        "status": lv.get("status")})
        if row["glbs"]:
            out.append(row)
    if args.json_out:
        pathlib.Path(args.json_out).write_text(json.dumps(out, indent=2, ensure_ascii=False),
                                               encoding="utf-8")
    for row in out:
        print(f"{row['entry_id']} [{row['status']}] -> {len(row['glbs'])} glb")
        for glb in row["glbs"][:6]:
            print("   ", glb.get("name") or glb.get("fragment_id"), glb["asset_id"], glb.get("role"))
        if len(row["glbs"]) > 6:
            print(f"    ... +{len(row['glbs']) - 6} more")
    return 0


if __name__ == "__main__":
    sys.exit(main())
