"""Probe 10: the 23rd store (data/a12_smoke/_tmp/v23store) + keyword re-check on all 23.

probe01 (run earlier) saw 22 stores; a later os.walk sees 23. This probe:
  1. reports the roles/rows of the 23rd store
  2. re-runs ONLY the archaeological-keyword census over all 23 stores and prints the
     per-keyword count, so the report can state a verified denominator.
"""
import json
import os
import sqlite3
import collections

ROOT = r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab"
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(DATA, "a12", "reports", "modality_census")

KEYWORDS = ["context", "site", "trench", "layer", "stratum", "strat", "unit", "batch",
            "lot", "findspot", "locus", "square", "grid", "coordinate_ref", "scale_ref",
            "scalebar", "soil", "earth", "matrix", "deposit", "feature", "parcel",
            "plot", "provenance", "coexist", "association", "group", "episode",
            "roster", "scene", "env", "environment"]


def find_stores():
    hits = []
    for dp, dn, fn in os.walk(DATA):
        for f in fn:
            if f == "metadata.sqlite":
                hits.append(os.path.join(dp, f))
    return sorted(hits)


def open_ro(p):
    con = sqlite3.connect("file:" + p.replace("\\", "/") + "?mode=ro&immutable=1", uri=True)
    con.row_factory = sqlite3.Row
    return con


def inner(mj):
    if isinstance(mj, dict) and isinstance(mj.get("meta"), dict):
        return mj["meta"]
    return mj


def main():
    stores = find_stores()
    lines = ["STORES (verified this run): %d" % len(stores)]
    for p in stores:
        lines.append("    %s" % os.path.relpath(p, ROOT))

    lines.append("")
    lines.append("=" * 90)
    lines.append("23rd store detail: data/a12_smoke/_tmp/v23store/metadata.sqlite")
    lines.append("=" * 90)
    p23 = os.path.join(DATA, "a12_smoke", "_tmp", "v23store", "metadata.sqlite")
    if os.path.exists(p23):
        con = open_ro(p23)
        cur = con.cursor()
        tabs = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        lines.append("tables: %s" % tabs)
        if "assets" in tabs:
            n = cur.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
            lines.append("assets: %d" % n)
            for r in cur.execute("SELECT role, COUNT(*) c FROM assets GROUP BY role ORDER BY role"):
                lines.append("    %-26s %d" % (r["role"], r["c"]))
            mj_hits = collections.Counter()
            for r in cur.execute("SELECT role, meta_json FROM assets"):
                m = inner(json.loads(r["meta_json"]))
                if isinstance(m, dict):
                    for k in m:
                        kl = str(k).lower()
                        for kw in KEYWORDS:
                            if kw in kl:
                                mj_hits[(kw, str(k))] += 1
            lines.append("")
            lines.append("archaeological-keyword key hits in this store:")
            if not mj_hits:
                lines.append("    无 (0)")
            for (kw, k), c in sorted(mj_hits.items()):
                lines.append("    kw=%-14s key=%-44s n=%d" % (kw, k, c))
        con.close()
    else:
        lines.append("MISSING")

    # ---- keyword census over ALL 23, counted as #assets carrying >=1 matching key
    lines.append("")
    lines.append("=" * 90)
    lines.append("KEYWORD CENSUS over all %d stores — #ASSETS carrying at least one key "
                 "whose name contains the keyword" % len(stores))
    lines.append("=" * 90)
    per_kw_assets = collections.Counter()
    per_kw_roles = collections.defaultdict(collections.Counter)
    per_kw_keys = collections.defaultdict(set)
    total_assets = 0
    per_store_assets = {}
    for p in stores:
        rel = os.path.relpath(p, ROOT)
        con = open_ro(p)
        cur = con.cursor()
        tabs = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        if "assets" not in tabs:
            con.close()
            continue
        n = 0
        for r in cur.execute("SELECT role, meta_json FROM assets"):
            n += 1
            total_assets += 1
            m = inner(json.loads(r["meta_json"]))
            if not isinstance(m, dict):
                continue
            matched = set()
            for k in m:
                kl = str(k).lower()
                for kw in KEYWORDS:
                    if kw in kl:
                        matched.add(kw)
                        per_kw_keys[kw].add(str(k))
            for kw in matched:
                per_kw_assets[kw] += 1
                per_kw_roles[kw][r["role"]] += 1
        per_store_assets[rel] = n
        con.close()

    lines.append("TOTAL ASSETS SCANNED: %d across %d stores" % (total_assets, len(stores)))
    lines.append("")
    lines.append("  %-16s %-8s %-8s %s" % ("keyword", "#assets", "#keys", "roles (assets)"))
    for kw in KEYWORDS:
        n = per_kw_assets.get(kw, 0)
        nk = len(per_kw_keys.get(kw, ()))
        roles = ", ".join("%s=%d" % (a, b) for a, b in per_kw_roles[kw].most_common())
        lines.append("  %-16s %-8d %-8d %s" % (kw, n, nk, roles if roles else "无"))

    with open(os.path.join(OUT, "probe10_23stores.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
