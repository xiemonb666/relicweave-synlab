"""Probe 02: keyword census over every meta_json in every metadata.sqlite (READ-ONLY).

Walks the inner `meta` object of every asset's meta_json, flattens all key paths,
and matches case-insensitive substring against the archaeological-context keyword
list. Reports exact key -> count, and key -> role breakdown.
"""
import json
import os
import sqlite3
import collections

ROOT = r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab"
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(DATA, "a12", "reports", "modality_census")

KEYWORDS = [
    "context", "site", "trench", "layer", "stratum", "strat", "unit", "batch",
    "lot", "findspot", "locus", "square", "grid", "coordinate_ref", "scale_ref",
    "scalebar", "soil", "earth", "matrix", "deposit", "feature", "parcel",
    "plot", "provenance", "coexist", "association", "group", "episode",
    "roster", "scene", "env", "environment",
]


def find_stores():
    hits = []
    for dirpath, dirnames, filenames in os.walk(DATA):
        for fn in filenames:
            if fn == "metadata.sqlite":
                hits.append(os.path.join(dirpath, fn))
    return sorted(hits)


def open_ro(path):
    uri = "file:" + path.replace("\\", "/") + "?mode=ro&immutable=1"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


def flatten(obj, prefix=""):
    """Yield (dotted_path, leaf_value) for every scalar leaf, and (path, '<list[n]>') for lists."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = "%s.%s" % (prefix, k) if prefix else str(k)
            for item in flatten(v, p):
                yield item
    elif isinstance(obj, list):
        yield (prefix + "[]", "<list[%d]>" % len(obj))
        for i, v in enumerate(obj[:3]):
            p = "%s[%d]" % (prefix, i)
            for item in flatten(v, p):
                yield item
    else:
        yield (prefix, obj)


def main():
    stores = find_stores()
    # key_path -> {store -> count}
    key_counts = collections.Counter()
    key_roles = collections.defaultdict(collections.Counter)
    key_stores = collections.defaultdict(collections.Counter)
    key_samples = {}
    matched_by_kw = collections.defaultdict(collections.Counter)
    per_store = {}
    total_assets = 0
    total_meta_ok = 0

    for p in stores:
        rel = os.path.relpath(p, ROOT)
        try:
            con = open_ro(p)
            cur = con.cursor()
            tabs = [r[0] for r in cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")]
            if "assets" not in tabs:
                con.close()
                continue
            rows = cur.execute("SELECT asset_id, role, meta_json FROM assets").fetchall()
            n = 0
            for r in rows:
                total_assets += 1
                n += 1
                raw = r["meta_json"]
                if not raw:
                    continue
                try:
                    mj = json.loads(raw)
                except Exception:
                    continue
                meta = mj.get("meta", mj) if isinstance(mj, dict) else {}
                if not isinstance(meta, dict):
                    continue
                total_meta_ok += 1
                seen_here = set()
                for path, val in flatten(meta):
                    seen_here.add(path)
                    low = path.lower()
                    for kw in KEYWORDS:
                        if kw in low:
                            matched_by_kw[kw][path] += 1
                            break
                for path in seen_here:
                    key_counts[path] += 1
                    key_roles[path][r["role"]] += 1
                    key_stores[path][rel] += 1
                    if path not in key_samples:
                        # capture a real sample value
                        for p2, v2 in flatten(meta):
                            if p2 == path:
                                key_samples[path] = v2
                                break
            per_store[rel] = n
            con.close()
        except Exception as e:
            per_store[rel] = "ERR:%r" % e

    # matched keys only
    matched_keys = set()
    for kw, paths in matched_by_kw.items():
        matched_keys |= set(paths)

    lines = []
    lines.append("STORES SCANNED: %d" % len(stores))
    lines.append("ASSETS SCANNED: %d   (assets with parseable meta: %d)" % (total_assets, total_meta_ok))
    lines.append("DISTINCT meta KEY PATHS: %d" % len(key_counts))
    lines.append("DISTINCT meta KEY PATHS MATCHING KEYWORDS: %d" % len(matched_keys))
    lines.append("")
    lines.append("=" * 100)
    lines.append("KEYWORD -> MATCHING KEY PATHS (count = #assets carrying that path)")
    lines.append("=" * 100)
    for kw in KEYWORDS:
        paths = matched_by_kw.get(kw)
        if not paths:
            lines.append("")
            lines.append("[%s]  NO MATCH (0 key paths)" % kw)
            continue
        lines.append("")
        lines.append("[%s]  %d distinct key paths" % (kw, len(paths)))
        for path, c in sorted(paths.items(), key=lambda kv: -kv[1]):
            roles = key_roles[path]
            rtxt = ", ".join("%s=%d" % (r, n) for r, n in roles.most_common())
            lines.append("    %-52s n=%-5d roles{%s}" % (path, c, rtxt))
    lines.append("")
    lines.append("=" * 100)
    lines.append("SAMPLE VALUE PER MATCHED KEY (first observed, may be from any store)")
    lines.append("=" * 100)
    for path in sorted(matched_keys):
        v = key_samples.get(path, "<none>")
        sv = json.dumps(v, default=str)
        if len(sv) > 150:
            sv = sv[:150] + "..."
        lines.append("    %-52s = %s" % (path, sv))

    with open(os.path.join(OUT, "probe02_keywords.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    dump = {
        "n_stores": len(stores),
        "total_assets": total_assets,
        "total_meta_ok": total_meta_ok,
        "per_store_assets": per_store,
        "key_counts": dict(key_counts),
        "key_roles": {k: dict(v) for k, v in key_roles.items()},
        "matched_by_kw": {k: dict(v) for k, v in matched_by_kw.items()},
        "samples": {k: (v if isinstance(v, (int, float, str, bool, type(None))) else str(v))
                    for k, v in key_samples.items()},
    }
    with open(os.path.join(OUT, "probe02_keywords.json"), "w", encoding="utf-8") as f:
        json.dump(dump, f, indent=2, default=str)
    print("\n".join(lines[:120]))


if __name__ == "__main__":
    main()
