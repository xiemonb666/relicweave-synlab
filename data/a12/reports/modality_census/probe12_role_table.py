"""Probe 12: condensed role contract table from data/a12/metadata.sqlite (READ-ONLY).

One row per role: rows, schema(s), unit(s), frame(s), qa_status breakdown, top-level meta key count.
Also cross-checks the schema strings against synlab/roles.py SCHEMA_* constants.
"""
import json
import os
import re
import sqlite3
import collections

ROOT = r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab"
MAIN = os.path.join(ROOT, "data", "a12", "metadata.sqlite")
ROLES_PY = os.path.join(ROOT, "synlab", "roles.py")
OUT = os.path.join(ROOT, "data", "a12", "reports", "modality_census")


def open_ro(p):
    con = sqlite3.connect("file:" + p.replace("\\", "/") + "?mode=ro&immutable=1", uri=True)
    con.row_factory = sqlite3.Row
    return con


def inner(mj):
    if isinstance(mj, dict) and isinstance(mj.get("meta"), dict):
        return mj["meta"]
    return mj


def parse_roles_py():
    schemas, roles, units, frames = {}, {}, {}, {}
    for i, line in enumerate(open(ROLES_PY, encoding="utf-8"), 1):
        m = re.match(r'^(SCHEMA_\w+)\s*=\s*"([^"]+)"', line)
        if m:
            schemas[m.group(1)] = (m.group(2), i)
        m = re.match(r'^(ROLE_\w+)\s*=\s*"([^"]+)"', line)
        if m:
            roles[m.group(1)] = (m.group(2), i)
        m = re.match(r'^(UNIT_\w+)\s*=\s*"([^"]+)"', line)
        if m:
            units[m.group(1)] = (m.group(2), i)
        m = re.match(r'^(FRAME_\w+)\s*=\s*"([^"]+)"', line)
        if m:
            frames[m.group(1)] = (m.group(2), i)
    return schemas, roles, units, frames


def main():
    L = []
    schemas, roles_c, units_c, frames_c = parse_roles_py()
    L.append("synlab/roles.py constants: %d SCHEMA, %d ROLE, %d UNIT, %d FRAME"
             % (len(schemas), len(roles_c), len(units_c), len(frames_c)))

    con = open_ro(MAIN)
    cur = con.cursor()
    rows = cur.execute("SELECT role, schema, unit, frame, qa_status, meta_json FROM assets").fetchall()
    by_role = collections.defaultdict(list)
    for r in rows:
        by_role[r["role"]].append(r)

    L.append("")
    L.append("=" * 130)
    L.append("ROLE CONTRACT TABLE — data/a12/metadata.sqlite (all %d assets, %d roles)"
             % (len(rows), len(by_role)))
    L.append("=" * 130)
    hdr = "%-24s %5s %-26s %-6s %-7s %-34s %s" % (
        "role", "rows", "schema", "unit", "frame", "qa_status", "top-level meta keys (n)")
    L.append(hdr)
    L.append("-" * 130)
    all_schemas_used = set()
    for role in sorted(by_role):
        rs = by_role[role]
        sch = collections.Counter(r["schema"] for r in rs)
        unt = collections.Counter(r["unit"] for r in rs)
        frm = collections.Counter(r["frame"] for r in rs)
        qa = collections.Counter(r["qa_status"] for r in rs)
        all_schemas_used |= set(sch)
        kc = collections.Counter()
        for r in rs:
            m = inner(json.loads(r["meta_json"]))
            if isinstance(m, dict):
                for k in m:
                    kc[k] += 1
        def fmt(c):
            return "|".join("%s:%d" % (k, v) for k, v in c.most_common())
        ktxt = ", ".join("%s(%d)" % (k, v) for k, v in sorted(kc.items()))
        L.append("%-24s %5d %-26s %-6s %-7s %-34s %s"
                 % (role, len(rs), fmt(sch), fmt(unt), fmt(frm), fmt(qa),
                    ktxt if len(ktxt) < 200 else ktxt[:200] + "...(%d keys)" % len(kc)))

    L.append("")
    L.append("=" * 130)
    L.append("SCHEMA CROSS-CHECK")
    L.append("=" * 130)
    code_schemas = {v[0] for v in schemas.values()}
    L.append("schema strings in roles.py (%d): %s" % (len(code_schemas), sorted(code_schemas)))
    L.append("")
    L.append("schema strings actually on assets in MAIN store (%d): %s"
             % (len(all_schemas_used), sorted(all_schemas_used)))
    L.append("")
    L.append("A) declared in roles.py but ZERO assets in MAIN store:")
    miss = sorted(code_schemas - all_schemas_used)
    if not miss:
        L.append("   无")
    for s in miss:
        names = [k for k, v in schemas.items() if v[0] == s]
        L.append("   %-28s (%s)" % (s, ", ".join("%s:roles.py:%d" % (n, schemas[n][1])
                                                 for n in names)))
    L.append("")
    L.append("B) on assets but NOT declared in roles.py:")
    extra = sorted(all_schemas_used - code_schemas)
    if not extra:
        L.append("   无")
    for s in extra:
        owners = sorted({r["role"] for r in rows if r["schema"] == s})
        L.append("   %-28s roles=%s" % (s, owners))
    L.append("")
    L.append("C) roles declared in roles.py with ZERO assets in MAIN store:")
    role_vals = {v[0] for v in roles_c.values()}
    present = set(by_role)
    zero = sorted(role_vals - present)
    if not zero:
        L.append("   无")
    for rv in zero:
        nm = [k for k, v in roles_c.items() if v[0] == rv]
        L.append("   %-24s (%s)" % (rv, ", ".join("%s:roles.py:%d" % (n, roles_c[n][1])
                                                  for n in nm)))
    L.append("")
    L.append("D) roles on assets but NOT declared in roles.py:")
    und = sorted(present - role_vals)
    if not und:
        L.append("   无")
    for rv in und:
        L.append("   %s (n=%d)" % (rv, len(by_role[rv])))

    con.close()
    with open(os.path.join(OUT, "probe12_role_table.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print("\n".join(L))


if __name__ == "__main__":
    main()
