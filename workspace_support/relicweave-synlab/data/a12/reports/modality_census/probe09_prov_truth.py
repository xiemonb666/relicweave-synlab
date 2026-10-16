"""Probe 09: provenance, truth layers, QA, leakage, and grouping-key producers (READ-ONLY).

C1  provenance role: exact meta keys, code_fingerprint, backend_fingerprints, git commit/dirty
C2  truth layers clean_truth / physical_truth / visible_labels: fields, truth_incomplete,
    history.historical_R2, association_counts, qa_status counts
C4  feature_bundle: dropped_forbidden_fields presence + which fields were dropped
A1b grouping-key search: bag_id / object_id / parent_id / event_id / mother_id / fragment_id
"""
import json
import os
import sqlite3
import collections

ROOT = r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab"
DATA = os.path.join(ROOT, "data")
MAIN = os.path.join(DATA, "a12", "metadata.sqlite")
OUT = os.path.join(DATA, "a12", "reports", "modality_census")


def open_ro(path):
    uri = "file:" + path.replace("\\", "/") + "?mode=ro&immutable=1"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


def find_stores():
    hits = []
    for dp, dn, fn in os.walk(DATA):
        for f in fn:
            if f == "metadata.sqlite":
                hits.append(os.path.join(dp, f))
    return sorted(hits)


def inner(mj):
    if isinstance(mj, dict) and isinstance(mj.get("meta"), dict):
        return mj["meta"]
    return mj


def flat_keys(obj, prefix=""):
    """All key paths, treating literal dotted keys as single keys too."""
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = "%s.%s" % (prefix, k) if prefix else str(k)
            out.append(p)
            out.extend(flat_keys(v, p))
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:2]):
            out.extend(flat_keys(v, "%s[%d]" % (prefix, i)))
    return out


def main():
    lines = []
    con = open_ro(MAIN)
    cur = con.cursor()

    # ---------------------------------------------------------------- C1 provenance
    lines.append("=" * 100)
    lines.append("C1  role=provenance in data/a12/metadata.sqlite")
    lines.append("=" * 100)
    rows = cur.execute("SELECT asset_id, schema, unit, frame, qa_status, split, meta_json "
                       "FROM assets WHERE role='provenance'").fetchall()
    lines.append("provenance assets: %d" % len(rows))
    key_counts = collections.Counter()
    for r in rows:
        m = inner(json.loads(r["meta_json"]))
        if isinstance(m, dict):
            for k in m:
                key_counts[k] += 1
    lines.append("")
    lines.append("TOP-LEVEL meta keys (n = #assets carrying, of %d):" % len(rows))
    for k, c in sorted(key_counts.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append("    %-40s n=%d" % (k, c))
    lines.append("")
    lines.append("schema/unit/frame/qa_status distinct values:")
    for col in ("schema", "unit", "frame", "qa_status", "split"):
        vc = collections.Counter(r[col] for r in rows)
        lines.append("    %-12s %s" % (col, json.dumps(dict(vc))))
    lines.append("")
    for r in rows[:2]:
        m = inner(json.loads(r["meta_json"]))
        lines.append("--- FULL meta of %s ---" % r["asset_id"])
        lines.append(json.dumps(m, indent=2, default=str))

    # ---------------------------------------------------------------- C2 truth layers
    lines.append("")
    lines.append("=" * 100)
    lines.append("C2  truth layers in data/a12/metadata.sqlite")
    lines.append("=" * 100)
    for role in ("clean_truth", "physical_truth", "visible_labels", "label_bundle",
                 "physical_result", "feature_bundle", "degrade_measurement",
                 "obs_view", "obs_result", "obs_fused_geometry", "material_profile",
                 "physical_component", "pattern_channels", "pattern_recipe",
                 "fragment_mesh", "mother_mesh", "qa_report", "relation_pool",
                 "query_roster"):
        rs = cur.execute("SELECT schema, unit, frame, qa_status, meta_json FROM assets "
                         "WHERE role=?", (role,)).fetchall()
        if not rs:
            lines.append("")
            lines.append("[%s] 0 assets in MAIN store" % role)
            continue
        sch = collections.Counter(r["schema"] for r in rs)
        unt = collections.Counter(r["unit"] for r in rs)
        frm = collections.Counter(r["frame"] for r in rs)
        qa = collections.Counter(r["qa_status"] for r in rs)
        kc = collections.Counter()
        for r in rs:
            m = inner(json.loads(r["meta_json"]))
            if isinstance(m, dict):
                for k in m:
                    kc[k] += 1
        lines.append("")
        lines.append("[%s] n=%d" % (role, len(rs)))
        lines.append("    schema=%s" % json.dumps(dict(sch)))
        lines.append("    unit  =%s" % json.dumps(dict(unt)))
        lines.append("    frame =%s" % json.dumps(dict(frm)))
        lines.append("    qa    =%s" % json.dumps(dict(qa)))
        lines.append("    top-level meta keys:")
        for k, c in sorted(kc.items(), key=lambda kv: (-kv[1], kv[0])):
            lines.append("        %-46s n=%d" % (k, c))

    # ---------------------------------------------------------------- truth_incomplete / historical_R2 / association_counts
    lines.append("")
    lines.append("=" * 100)
    lines.append("C2b truth_incomplete / history.* / association_counts  REAL VALUES (MAIN store)")
    lines.append("=" * 100)
    for role in ("clean_truth", "physical_truth", "visible_labels", "label_bundle"):
        rs = cur.execute("SELECT asset_id, meta_json FROM assets WHERE role=?", (role,)).fetchall()
        ti = collections.Counter()
        hr2 = collections.Counter()
        ac = collections.defaultdict(collections.Counter)
        akind = collections.Counter()
        for r in rs:
            m = inner(json.loads(r["meta_json"]))
            if not isinstance(m, dict):
                continue
            ti[json.dumps(m.get("truth_incomplete"), default=str)] += 1
            hist = m.get("history")
            if isinstance(hist, dict):
                hr2[json.dumps(hist.get("historical_R2"), default=str)] += 1
                if "association_kind" in hist:
                    akind[json.dumps(hist["association_kind"], default=str)] += 1
            counts = m.get("association_counts")
            if isinstance(counts, dict):
                for k, v in counts.items():
                    ac[k][json.dumps(v, default=str)] += 1
            elif "association_counts" in m:
                ac["<non-dict>"][json.dumps(m["association_counts"], default=str)] += 1
        lines.append("")
        lines.append("[%s] n=%d" % (role, len(rs)))
        lines.append("    truth_incomplete -> %s" % json.dumps(dict(ti)))
        lines.append("    history.historical_R2 -> %s" % json.dumps(dict(hr2)))
        lines.append("    history.association_kind -> %s" % json.dumps(dict(akind)))
        for k in sorted(ac):
            lines.append("    association_counts.%s -> %s" % (k, json.dumps(dict(ac[k]))))

    # ---------------------------------------------------------------- C4 leakage
    lines.append("")
    lines.append("=" * 100)
    lines.append("C4  role=feature_bundle: dropped_forbidden_fields (MAIN store)")
    lines.append("=" * 100)
    rs = cur.execute("SELECT asset_id, meta_json FROM assets WHERE role='feature_bundle'").fetchall()
    n_total = len(rs)
    n_has = 0
    n_empty = 0
    dropped_counter = collections.Counter()
    key_present = collections.Counter()
    for r in rs:
        m = inner(json.loads(r["meta_json"]))
        if not isinstance(m, dict):
            continue
        if "dropped_forbidden_fields" in m:
            n_has += 1
            d = m["dropped_forbidden_fields"]
            if isinstance(d, list):
                if not d:
                    n_empty += 1
                for x in d:
                    dropped_counter[json.dumps(x, default=str)] += 1
            else:
                dropped_counter["<non-list:%s>" % type(d).__name__] += 1
        for k in ("feature_fields", "integrity", "groups", "n_features", "leakage_check"):
            if k in m:
                key_present[k] += 1
    lines.append("feature_bundle assets: %d" % n_total)
    lines.append("  carry `dropped_forbidden_fields`: %d / %d" % (n_has, n_total))
    lines.append("  of those, empty list: %d" % n_empty)
    lines.append("  dropped field names (value -> #assets): %s"
                 % json.dumps(dict(dropped_counter.most_common(40))))
    lines.append("  other key presence: %s" % json.dumps(dict(key_present)))
    lines.append("")
    lines.append("  FORBIDDEN_FEATURE_FIELDS in code (synlab/roles.py:87-93): see report")

    # ---------------------------------------------------------------- A1b grouping keys
    lines.append("")
    lines.append("=" * 100)
    lines.append("A1b GROUPING-KEY SEARCH across ALL stores+roles (bag_id/object_id/event_id/...)")
    lines.append("=" * 100)
    targets = ["bag_id", "object_id", "parent_id", "generator_family", "generator_family_id",
               "event_id", "mother_id", "fragment_id", "seed", "lineage_id", "split",
               "interface_id", "relation", "batch", "lot_id", "group_id"]
    hits = collections.defaultdict(collections.Counter)   # target -> role
    samples = {}
    for p in find_stores():
        rel = os.path.relpath(p, ROOT)
        c2 = open_ro(p)
        cu = c2.cursor()
        tabs = [r[0] for r in cu.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        if "assets" not in tabs:
            c2.close()
            continue
        for r in cu.execute("SELECT asset_id, role, meta_json FROM assets"):
            m = inner(json.loads(r["meta_json"]))
            if not isinstance(m, dict):
                continue
            ks = set()
            for path in flat_keys(m):
                ks.add(path.split(".")[-1].split("[")[0])
            for t in targets:
                if t in ks:
                    hits[t][r["role"]] += 1
                    samples.setdefault(t, (rel, r["asset_id"]))
        c2.close()
    for t in targets:
        if hits[t]:
            lines.append("  %-22s total=%d  roles=%s   e.g. %s"
                         % (t, sum(hits[t].values()), json.dumps(dict(hits[t])),
                            samples.get(t)))
        else:
            lines.append("  %-22s 无 (0 assets in all %d stores)" % (t, len(find_stores())))

    con.close()
    with open(os.path.join(OUT, "probe09_prov_truth.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n".join(lines[:150]))


if __name__ == "__main__":
    main()
