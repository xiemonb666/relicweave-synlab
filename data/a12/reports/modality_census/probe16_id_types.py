"""Probe 16: real JSON types of component_id / observation_id / fragment_id in artifacts.

runtime.py types component_id as int in Fragment (runtime.py:204) but str in
PhysicalComponent (:343) and ObservationResult (:452).  This probe reports what the
artifacts actually carry, per role, so the mismatch can be stated with real numbers.
"""
import json
import os
import sqlite3
import collections

ROOT = r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab"
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(DATA, "a12", "reports", "modality_census")


def find_stores():
    hits = []
    for dp, dn, fn in os.walk(DATA):
        for f in fn:
            if f == "metadata.sqlite":
                hits.append(os.path.join(dp, f))
    return sorted(hits)


def main():
    fields = ("component_id", "observation_id", "fragment_id", "event_id", "mother_id")
    types = collections.defaultdict(lambda: collections.defaultdict(int))
    samples = collections.defaultdict(dict)
    meta_wrapped = collections.Counter()
    n_assets = 0
    for p in find_stores():
        con = sqlite3.connect("file:" + p.replace("\\", "/") + "?mode=ro&immutable=1", uri=True)
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        tabs = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        if "assets" not in tabs:
            con.close()
            continue
        for r in cur.execute("SELECT role, meta_json FROM assets"):
            n_assets += 1
            mj = json.loads(r["meta_json"])
            m = mj["meta"] if isinstance(mj, dict) and isinstance(mj.get("meta"), dict) else mj
            if not isinstance(m, dict):
                continue
            meta_wrapped[r["role"]] += 1
            for f in fields:
                if f in m:
                    v = m[f]
                    t = type(v).__name__
                    types[(r["role"], f)][t] += 1
                    if t not in samples[(r["role"], f)]:
                        samples[(r["role"], f)][t] = json.dumps(v)[:60]

    L = []
    L.append("Scanned %d assets." % n_assets)
    L.append("")
    L.append("=" * 104)
    L.append("REAL JSON TYPE OF ID FIELDS, PER ROLE (all stores)")
    L.append("=" * 104)
    L.append("  %-24s %-16s %s" % ("role", "field", "type -> count  (sample value)"))
    for (role, f) in sorted(types):
        tc = types[(role, f)]
        for t, c in sorted(tc.items(), key=lambda kv: -kv[1]):
            L.append("  %-24s %-16s %-8s n=%-5d sample=%s"
                     % (role, f, t, c, samples[(role, f)].get(t, "")))
    L.append("")
    L.append("=" * 104)
    L.append("ROLES WHOSE meta_json IS WRAPPED UNDER A TOP-LEVEL 'meta' KEY")
    L.append("=" * 104)
    for role in sorted(meta_wrapped):
        L.append("  %-24s wrapped rows=%d" % (role, meta_wrapped[role]))

    with open(os.path.join(OUT, "probe16_id_types.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(L))
    print("\n".join(L))


if __name__ == "__main__":
    main()
