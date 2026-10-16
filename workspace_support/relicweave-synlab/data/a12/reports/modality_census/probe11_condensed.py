"""Probe 11: condensed exact values for the report tables (READ-ONLY).

Outputs, for data/a12/metadata.sqlite:
  - distinct (git, commit, dirty, diff_hash, source_tree_hash) across all 45 provenance assets
  - distinct backend_fingerprints package->version across all provenance assets
  - distinct seed_ref / run_id / spec_hash / params keys / data_semantics
  - qa_status counts per role (whole store)
  - truth_incomplete / history.* / association_counts real values per truth role
  - dropped_forbidden_fields real counts
  - loss_mask invariants from truth/api.py-aligned meta
"""
import json
import os
import sqlite3
import collections

ROOT = r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab"
MAIN = os.path.join(ROOT, "data", "a12", "metadata.sqlite")
OUT = os.path.join(ROOT, "data", "a12", "reports", "modality_census")


def open_ro(p):
    con = sqlite3.connect("file:" + p.replace("\\", "/") + "?mode=ro&immutable=1", uri=True)
    con.row_factory = sqlite3.Row
    return con


def inner(mj):
    if isinstance(mj, dict) and isinstance(mj.get("meta"), dict):
        return mj["meta"]
    return mj


def main():
    L = []
    con = open_ro(MAIN)
    cur = con.cursor()

    # ---- qa_status per role
    L.append("=" * 90)
    L.append("QA_STATUS PER ROLE (data/a12/metadata.sqlite, all 894 assets)")
    L.append("=" * 90)
    tot = collections.Counter()
    for r in cur.execute("SELECT role, qa_status, COUNT(*) c FROM assets GROUP BY role, qa_status "
                         "ORDER BY role, qa_status"):
        L.append("    %-24s %-14s %d" % (r["role"], r["qa_status"], r["c"]))
        tot[r["qa_status"]] += r["c"]
    L.append("    --- store totals: %s" % json.dumps(dict(tot)))

    # ---- provenance condensed
    L.append("")
    L.append("=" * 90)
    L.append("C1a  provenance role: distinct code_fingerprint across all rows")
    L.append("=" * 90)
    rows = cur.execute("SELECT meta_json FROM assets WHERE role='provenance'").fetchall()
    combos = collections.Counter()
    bfpkgs = collections.defaultdict(collections.Counter)
    runs = collections.Counter()
    seeds = collections.Counter()
    specs = collections.Counter()
    params_keys = collections.Counter()
    dsem = collections.Counter()
    n_untracked = collections.Counter()
    for r in rows:
        m = inner(json.loads(r["meta_json"]))
        cf = m.get("code_fingerprint") or {}
        combos[(cf.get("git"), str(cf.get("commit")), cf.get("dirty"),
                str(cf.get("diff_hash")), str(cf.get("source_tree_hash")))] += 1
        n_untracked[len(cf.get("untracked") or [])] += 1
        for pkg, ver in (m.get("backend_fingerprints") or {}).items():
            bfpkgs[pkg][str(ver)] += 1
        runs[str(m.get("run_id"))] += 1
        seeds[json.dumps(m.get("seed_ref"), default=str)] += 1
        specs[str(m.get("spec_hash"))] += 1
        p = m.get("params")
        if isinstance(p, dict):
            for k in p:
                params_keys[k] += 1
        if "data_semantics" in m:
            dsem[json.dumps(m["data_semantics"], default=str)[:200]] += 1
    L.append("provenance rows: %d" % len(rows))
    L.append("")
    L.append("distinct (git, commit, dirty, diff_hash, source_tree_hash) -> count:")
    for k, c in combos.most_common():
        L.append("    n=%-4d git=%s commit=%s dirty=%s" % (c, k[0], k[1], k[2]))
        L.append("           diff_hash=%s" % k[3])
        L.append("           source_tree_hash=%s" % k[4])
    L.append("")
    L.append("untracked-path count distribution: %s" % json.dumps(dict(n_untracked)))
    L.append("")
    L.append("backend_fingerprints (package -> version, count of provenance rows carrying it):")
    for pkg in sorted(bfpkgs):
        L.append("    %-16s %s" % (pkg, json.dumps(dict(bfpkgs[pkg]))))
    L.append("distinct packages: %d" % len(bfpkgs))
    L.append("")
    L.append("run_id distinct: %d -> %s" % (len(runs), json.dumps(dict(runs.most_common(8)))))
    L.append("seed_ref distinct: %d -> %s" % (len(seeds), json.dumps(dict(seeds.most_common(4)))))
    L.append("spec_hash distinct: %d -> %s" % (len(specs), json.dumps(dict(specs.most_common(4)))))
    L.append("params keys: %s" % json.dumps(dict(params_keys)))
    L.append("data_semantics (7 rows): %s" % json.dumps(dict(dsem)))

    # ---- truth condensed
    L.append("")
    L.append("=" * 90)
    L.append("C2a  truth-layer role contracts + real truth_incomplete / history / counts")
    L.append("=" * 90)
    for role in ("clean_truth", "physical_truth", "visible_labels", "label_bundle"):
        rs = cur.execute("SELECT asset_id, schema, unit, frame, qa_status, meta_json FROM assets "
                         "WHERE role=?", (role,)).fetchall()
        L.append("")
        L.append("--- %s : %d assets" % (role, len(rs)))
        for col in ("schema", "unit", "frame", "qa_status"):
            L.append("      %-9s %s" % (col, json.dumps(dict(collections.Counter(
                r[col] for r in rs)))))
        kc = collections.Counter()
        ti = collections.Counter()
        hr2 = collections.Counter()
        akind = collections.Counter()
        ac = collections.defaultdict(collections.Counter)
        nh = collections.Counter()
        for r in rs:
            m = inner(json.loads(r["meta_json"]))
            if not isinstance(m, dict):
                continue
            for k in m:
                kc[k] += 1
            if "truth_incomplete" in m:
                ti[json.dumps(m["truth_incomplete"], default=str)] += 1
            h = m.get("history")
            if isinstance(h, dict):
                nh[len(h)] += 1
                if "historical_R2" in h:
                    hr2[json.dumps(h["historical_R2"], default=str)] += 1
                if "association_kind" in h:
                    akind[json.dumps(h["association_kind"], default=str)] += 1
            c = m.get("association_counts")
            if isinstance(c, dict):
                for k, v in c.items():
                    ac[k][json.dumps(v, default=str)] += 1
        L.append("      top-level meta keys:")
        for k, c in sorted(kc.items(), key=lambda kv: (-kv[1], kv[0])):
            L.append("          %-44s n=%d" % (k, c))
        L.append("      truth_incomplete -> %s" % json.dumps(dict(ti)))
        L.append("      history key-count distribution -> %s" % json.dumps(dict(nh)))
        L.append("      history.historical_R2 -> %s" % json.dumps(dict(hr2)))
        L.append("      history.association_kind -> %s" % json.dumps(dict(akind)))
        for k in sorted(ac):
            L.append("      association_counts.%s -> %s" % (k, json.dumps(dict(ac[k]))))

    # ---- dropped_forbidden_fields
    L.append("")
    L.append("=" * 90)
    L.append("C4a  role=feature_bundle: dropped_forbidden_fields (MAIN store)")
    L.append("=" * 90)
    rs = cur.execute("SELECT asset_id, meta_json FROM assets WHERE role='feature_bundle'").fetchall()
    n_has = n_empty = 0
    dropped = collections.Counter()
    for r in rs:
        m = inner(json.loads(r["meta_json"]))
        if not isinstance(m, dict) or "dropped_forbidden_fields" not in m:
            continue
        n_has += 1
        d = m["dropped_forbidden_fields"]
        if isinstance(d, list):
            if not d:
                n_empty += 1
            for x in d:
                dropped[json.dumps(x, default=str)] += 1
        else:
            dropped["<non-list %s>" % type(d).__name__] += 1
    L.append("feature_bundle assets: %d ; carry dropped_forbidden_fields: %d ; empty list: %d"
             % (len(rs), n_has, n_empty))
    L.append("dropped names (name -> #assets): %s" % json.dumps(dict(dropped.most_common(30))))
    L.append("distinct dropped names: %d" % len(dropped))

    con.close()
    with open(os.path.join(OUT, "probe11_condensed.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print("\n".join(L))


if __name__ == "__main__":
    main()
