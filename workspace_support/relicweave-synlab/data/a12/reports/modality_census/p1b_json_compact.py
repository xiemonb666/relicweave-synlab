"""Probe 1b: compact index/manifest JSON summariser (no row-level explosion).

READ-ONLY. Prints to stdout.
Repro:
  cd C:\\Users\\xiemo\\Desktop\\ShardForge\\relicweave-synlab
  .venv\\Scripts\\python.exe data\\a12\\reports\\modality_census\\p1b_json_compact.py > data\\a12\\reports\\modality_census\\p1b_json_compact.out 2>&1
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
PKGS = {
    "next_experiment": REPO / "data" / "a12_exports" / "next_experiment" / "training_package",
    "closed_loop": REPO / "data" / "a12_exports" / "closed_loop" / "training_package",
}

# index/manifest json of interest (non-zarr)
NAMED = [
    "export_manifest.json",
    "deploy/deploy_index.json",
    "deploy/geometry/index.json",
    "deploy/obs/index.json",
    "deploy/tokens/index.json",
    "deploy/zarr/index.json",
    "deploy/zarr/zarr.json",
    "research/labels/query_map.json",
]


def rtype(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "float"
    if isinstance(v, str):
        return "str"
    if isinstance(v, list):
        return f"list[{len(v)}]"
    if isinstance(v, dict):
        return f"dict[{len(v)}]"
    return type(v).__name__


def summarize(obj, name: str, indent="    ", depth=0, maxdepth=2):
    """Print keys + types + scalar values, but for dict-of-row dicts only show count+sample."""
    lines = []
    if not isinstance(obj, dict):
        lines.append(f"{indent}<{rtype(obj)}>")
        return lines
    for k in sorted(obj.keys()):
        v = obj[k]
        t = rtype(v)
        if isinstance(v, (int, float, str, bool)) or v is None:
            s = repr(v)
            if len(s) > 110:
                s = s[:107] + "...'"
            lines.append(f"{indent}{k}: {t} = {s}")
        elif isinstance(v, list):
            lines.append(f"{indent}{k}: {t}")
            if v and not isinstance(v[0], (dict, list)):
                c = Counter(map(repr, v))
                shown = ", ".join(f"{kk}x{cc}" for kk, cc in c.most_common(8))
                lines.append(f"{indent}    values: {shown}")
            elif v and isinstance(v[0], dict):
                lines.append(f"{indent}    elem0 keys: {sorted(v[0].keys())}")
                lines.append(f"{indent}    elem0: {json.dumps(v[0])[:300]}")
        elif isinstance(v, dict):
            lines.append(f"{indent}{k}: {t}")
            if depth + 1 <= maxdepth:
                # if it looks like a map of rows -> summarize the VALUE schema uniformly
                vals = list(v.values())
                if vals and all(isinstance(x, dict) for x in vals):
                    vk = sorted({kk for x in vals for kk in x.keys()})
                    lines.append(f"{indent}    row-schema keys (union over {len(vals)} rows): {vk}")
                    for kk in vk:
                        tc = Counter(rtype(x.get(kk)) for x in vals)
                        nnull = sum(1 for x in vals if x.get(kk) is None)
                        extra = ""
                        if tc.get("str", 0) and tc.get("str", 0) <= 12:
                            u = Counter(x.get(kk) for x in vals if isinstance(x.get(kk), str))
                            extra = f"  distinct={dict(u)}"
                        lines.append(
                            f"{indent}      .{kk}: {dict(tc)}  null={nnull}{extra}"
                        )
                elif vals and not isinstance(vals[0], (dict, list)):
                    c = Counter(map(repr, vals))
                    lines.append(
                        f"{indent}    values: {', '.join(f'{kk}x{cc}' for kk, cc in c.most_common(10))}"
                    )
                else:
                    lines.extend(summarize(v, name, indent + "    ", depth + 1, maxdepth))
    return lines


def main() -> int:
    print("=" * 100)
    print("PROBE 1b: COMPACT INDEX/MANIFEST JSON SUMMARY")
    print("=" * 100)
    for pkg, root in PKGS.items():
        print("\n" + "#" * 100)
        print(f"# PACKAGE: {pkg}   ({root})")
        print("#" * 100)
        if not root.is_dir():
            print("  MISSING")
            continue
        for rel in NAMED:
            p = root / rel
            if not p.is_file():
                print(f"\n[{rel}]  *** ABSENT ***")
                continue
            obj = json.loads(p.read_text(encoding="utf-8"))
            print(f"\n[{rel}]  {p.stat().st_size:,} bytes  toplevel={rtype(obj)}")
            for line in summarize(obj, rel):
                print(line)

        # canonical zarr.json per-group schema (uniform across groups) -> show one + distribution
        zd = root / "deploy" / "zarr"
        if zd.is_dir():
            groups = sorted([d for d in zd.iterdir() if d.is_dir()])
            print(f"\n[deploy/zarr/]  opaque GROUPS on disk = {len(groups)}")
            print(f"  group names: {[g.name for g in groups]}")
            print(f"  name length set: {sorted({len(g.name) for g in groups})}")
            # root zarr.json
            rz = zd / "zarr.json"
            if rz.is_file():
                print(f"\n  [root zarr.json] {json.loads(rz.read_text(encoding='utf-8'))}")
            # per-group member dirs
            memberset = Counter()
            for g in groups:
                subs = sorted([d.name for d in g.iterdir() if d.is_dir()])
                memberset[tuple(subs)] += 1
            print("\n  member-array sets across groups (set -> #groups):")
            for s, c in memberset.items():
                print(f"    {list(s)}  ->  {c}")
            # group-level zarr.json
            gz = groups[0] / "zarr.json"
            print(f"\n  [group zarr.json example: {groups[0].name}] {json.loads(gz.read_text(encoding='utf-8'))}")
            # per-array zarr.json, deduped by content
            print("\n  PER-ARRAY zarr.json (deduped by content signature):")
            seen = {}
            for g in groups:
                for arr in sorted([d for d in g.iterdir() if d.is_dir()]):
                    zj = arr / "zarr.json"
                    if not zj.is_file():
                        seen.setdefault(("MISSING", arr.name), []).append(g.name)
                        continue
                    o = json.loads(zj.read_text(encoding="utf-8"))
                    sig = json.dumps(
                        {k: o.get(k) for k in ("shape", "data_type", "chunk_grid", "chunk_key_encoding",
                                               "fill_value", "codecs", "dimension_names", "zarr_format", "node_type")},
                        sort_keys=True,
                    )
                    seen.setdefault((sig, arr.name), []).append(g.name)
            for (sig, arrname), gs in sorted(seen.items(), key=lambda t: t[0][1]):
                print(f"\n    array='{arrname}'  present_in_groups={len(gs)}")
                if sig == "MISSING":
                    print("      *** zarr.json MISSING ***")
                else:
                    print(f"      {sig}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
