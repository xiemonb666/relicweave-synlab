"""Probe 01: inventory of every metadata.sqlite under data/ (READ-ONLY).

Opens each store with sqlite3 URI mode=ro&immutable=1. Dumps schema, table list,
row counts per table, and the assets table columns. Writes JSON + text.
"""
import json
import os
import sqlite3
import sys

ROOT = r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab"
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(DATA, "a12", "reports", "modality_census")


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


def main():
    stores = find_stores()
    report = {"n_stores": len(stores), "stores": []}
    lines = []
    lines.append("STORES FOUND: %d" % len(stores))
    for p in stores:
        rel = os.path.relpath(p, ROOT)
        entry = {"path": p, "rel": rel, "size": os.path.getsize(p)}
        try:
            con = open_ro(p)
            cur = con.cursor()
            tabs = [r[0] for r in cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
            entry["tables"] = tabs
            counts = {}
            for t in tabs:
                try:
                    counts[t] = cur.execute('SELECT COUNT(*) FROM "%s"' % t).fetchone()[0]
                except Exception as e:
                    counts[t] = "ERR:%s" % e
            entry["row_counts"] = counts
            if "assets" in tabs:
                cols = [r[1] for r in cur.execute("PRAGMA table_info(assets)")]
                entry["assets_columns"] = cols
                roles = cur.execute(
                    "SELECT role, COUNT(*) c FROM assets GROUP BY role ORDER BY role").fetchall()
                entry["roles"] = {r["role"]: r["c"] for r in roles}
            con.close()
        except Exception as e:
            entry["error"] = repr(e)
        report["stores"].append(entry)
        lines.append("")
        lines.append("=" * 78)
        lines.append("%s  (%d bytes)" % (rel, entry["size"]))
        if "error" in entry:
            lines.append("  ERROR: %s" % entry["error"])
            continue
        lines.append("  tables: %s" % ", ".join(entry["tables"]))
        lines.append("  row_counts: %s" % json.dumps(entry["row_counts"]))
        if "roles" in entry:
            lines.append("  assets columns: %s" % entry["assets_columns"])
            lines.append("  roles (%d distinct, %d rows):"
                         % (len(entry["roles"]), sum(entry["roles"].values())))
            for r, c in entry["roles"].items():
                lines.append("      %-24s %6d" % (r, c))

    with open(os.path.join(OUT, "probe01_inventory.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    with open(os.path.join(OUT, "probe01_inventory.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n".join(lines[:200]))


if __name__ == "__main__":
    main()
