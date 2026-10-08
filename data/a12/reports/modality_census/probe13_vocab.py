"""Probe 13: global unit/frame vocabulary vs synlab/roles.py constants (READ-ONLY).

Answers: which unit strings and frame strings actually appear on assets across ALL stores,
and which of them are NOT declared in roles.py (UNIT_*/FRAME_*).
"""
import json
import os
import re
import sqlite3
import collections

ROOT = r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab"
DATA = os.path.join(ROOT, "data")
ROLES_PY = os.path.join(ROOT, "synlab", "roles.py")
OUT = os.path.join(DATA, "a12", "reports", "modality_census")


def parse():
    units, frames, schemas = {}, {}, {}
    for i, line in enumerate(open(ROLES_PY, encoding="utf-8"), 1):
        for pat, dst in ((r'^(UNIT_\w+)\s*=\s*"([^"]+)"', units),
                         (r'^(FRAME_\w+)\s*=\s*"([^"]+)"', frames),
                         (r'^(SCHEMA_\w+)\s*=\s*"([^"]+)"', schemas)):
            m = re.match(pat, line)
            if m:
                dst[m.group(2)] = (m.group(1), i)
    return units, frames, schemas


def find_stores():
    hits = []
    for dp, dn, fn in os.walk(DATA):
        for f in fn:
            if f == "metadata.sqlite":
                hits.append(os.path.join(dp, f))
    return sorted(hits)


def main():
    units_c, frames_c, schemas_c = parse()
    unit_use = collections.Counter()
    unit_roles = collections.defaultdict(collections.Counter)
    frame_use = collections.Counter()
    frame_roles = collections.defaultdict(collections.Counter)
    schema_use = collections.Counter()
    n_stores = 0
    n_assets = 0
    for p in find_stores():
        n_stores += 1
        con = sqlite3.connect("file:" + p.replace("\\", "/") + "?mode=ro&immutable=1", uri=True)
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        tabs = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        if "assets" not in tabs:
            con.close()
            continue
        for r in cur.execute("SELECT role, schema, unit, frame FROM assets"):
            n_assets += 1
            unit_use[r["unit"]] += 1
            unit_roles[r["unit"]][r["role"]] += 1
            frame_use[r["frame"]] += 1
            frame_roles[r["frame"]][r["role"]] += 1
            schema_use[r["schema"]] += 1
        con.close()

    L = []
    L.append("Scanned %d stores, %d assets." % (n_stores, n_assets))
    L.append("roles.py declares: UNIT=%s  FRAME=%s" % (sorted(units_c), sorted(frames_c)))
    L.append("")
    L.append("=" * 100)
    L.append("UNIT VOCABULARY ACTUALLY ON ASSETS")
    L.append("=" * 100)
    for u, c in unit_use.most_common():
        declared = "DECLARED %s:roles.py:%d" % (units_c[u][0], units_c[u][1]) if u in units_c \
            else "*** NOT DECLARED IN roles.py ***"
        L.append("  %-14s n=%-5d %s" % (json.dumps(u), c, declared))
        L.append("        roles: %s" % json.dumps(dict(unit_roles[u])))
    L.append("")
    L.append("=" * 100)
    L.append("FRAME VOCABULARY ACTUALLY ON ASSETS")
    L.append("=" * 100)
    for f, c in frame_use.most_common():
        declared = "DECLARED %s:roles.py:%d" % (frames_c[f][0], frames_c[f][1]) if f in frames_c \
            else "*** NOT DECLARED IN roles.py ***"
        L.append("  %-18s n=%-5d %s" % (json.dumps(f), c, declared))
        L.append("        roles: %s" % json.dumps(dict(frame_roles[f])))
    L.append("")
    L.append("=" * 100)
    L.append("SCHEMA VOCABULARY ACTUALLY ON ASSETS (all stores)")
    L.append("=" * 100)
    for s, c in schema_use.most_common():
        declared = "DECLARED %s:roles.py:%d" % (schemas_c[s][0], schemas_c[s][1]) if s in schemas_c \
            else "*** NOT DECLARED IN roles.py ***"
        L.append("  %-30s n=%-5d %s" % (s, c, declared))

    with open(os.path.join(OUT, "probe13_vocab.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print("\n".join(L))


if __name__ == "__main__":
    main()
