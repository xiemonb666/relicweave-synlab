"""Probe 08: relation_pool meta + relations.parquet + labels parquet (READ-ONLY).

A5: does anything group fragments by same batch / same mother / same event?
C3: real value counts for loss_mask / valid / kind in the research parquet files.
"""
import json
import os
import sqlite3
import collections

ROOT = r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab"
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(DATA, "a12", "reports", "modality_census")
PKG = os.path.join(DATA, "a12_exports", "next_experiment", "training_package")

import pandas as pd  # noqa: E402


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


def inner(mj):
    if isinstance(mj, dict) and isinstance(mj.get("meta"), dict):
        return mj["meta"]
    return mj


def main():
    lines = []

    # ---------- A5: relation_pool / query_roster meta
    lines.append("=" * 100)
    lines.append("A5.1  relation_pool + query_roster assets: schema/unit/frame, top-level meta keys")
    lines.append("=" * 100)
    pool_keys = collections.Counter()
    pool_rows = 0
    roster_keys = collections.Counter()
    roster_rows = 0
    samples = []
    for p in find_stores():
        rel = os.path.relpath(p, ROOT)
        con = open_ro(p)
        cur = con.cursor()
        tabs = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        if "assets" not in tabs:
            con.close()
            continue
        for r in cur.execute("SELECT asset_id, role, schema, unit, frame, meta_json, qa_status, "
                            "split, lineage_id FROM assets "
                            "WHERE role IN ('relation_pool','query_roster')"):
            m = inner(json.loads(r["meta_json"]))
            if not isinstance(m, dict):
                continue
            if r["role"] == "relation_pool":
                pool_rows += 1
                for k in m:
                    pool_keys[k] += 1
            else:
                roster_rows += 1
                for k in m:
                    roster_keys[k] += 1
            samples.append({"store": rel, "asset_id": r["asset_id"], "role": r["role"],
                            "schema": r["schema"], "unit": r["unit"], "frame": r["frame"],
                            "qa_status": r["qa_status"], "split": r["split"],
                            "lineage_id": r["lineage_id"],
                            "n_meta_keys": len(m), "meta_keys": sorted(m),
                            "gallery": m.get("gallery"), "pool_meta": m.get("pool_meta"),
                            "n_fragment_records": (len(m["fragment_records"])
                                                   if isinstance(m.get("fragment_records"), dict)
                                                   else m.get("n_fragment_records")),
                            "n_roster": (len(m["roster"]) if isinstance(m.get("roster"), list)
                                         else None)})
        con.close()

    lines.append("relation_pool assets: %d ; query_roster assets: %d" % (pool_rows, roster_rows))
    lines.append("")
    lines.append("relation_pool TOP-LEVEL meta keys (n = #assets carrying):")
    for k, c in sorted(pool_keys.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append("    %-40s n=%d" % (k, c))
    lines.append("")
    lines.append("query_roster TOP-LEVEL meta keys (n = #assets carrying):")
    for k, c in sorted(roster_keys.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append("    %-40s n=%d" % (k, c))
    lines.append("")
    lines.append("PER-ASSET DETAIL:")
    for s in samples:
        lines.append("")
        lines.append("  store=%s asset=%s role=%s schema=%s unit=%s frame=%s qa=%s"
                     % (s["store"], s["asset_id"], s["role"], s["schema"], s["unit"],
                        s["frame"], s["qa_status"]))
        lines.append("    split=%s lineage_id=%s n_meta_keys=%d"
                     % (s["split"], s["lineage_id"], s["n_meta_keys"]))
        lines.append("    keys=%s" % json.dumps(s["meta_keys"]))
        lines.append("    n_fragment_records=%s n_roster=%s"
                     % (s["n_fragment_records"], s["n_roster"]))
        if s["gallery"] is not None:
            g = json.dumps(s["gallery"], default=str)
            lines.append("    gallery=%s" % (g[:600]))
        if s["pool_meta"] is not None:
            pm = json.dumps(s["pool_meta"], default=str)
            lines.append("    pool_meta=%s" % (pm[:900]))

    # ---------- A5.2 + C3: parquet
    lines.append("")
    lines.append("=" * 100)
    lines.append("A5.2  research/relations.parquet — columns, dtypes, cardinalities")
    lines.append("=" * 100)
    rp = os.path.join(PKG, "research", "relations.parquet")
    df = pd.read_parquet(rp)
    lines.append("path: %s" % os.path.relpath(rp, ROOT))
    lines.append("shape: %d rows x %d cols" % df.shape)
    lines.append("")
    lines.append("  %-28s %-14s %-10s %s" % ("column", "dtype", "n_unique", "example/most common"))
    for c in df.columns:
        nu = df[c].nunique(dropna=False)
        try:
            vc = df[c].value_counts(dropna=False).head(3)
            ex = ", ".join("%r:%d" % (k, v) for k, v in vc.items())
        except Exception:
            ex = "<unhashable>"
        lines.append("  %-28s %-14s %-10d %s" % (c, str(df[c].dtype), nu, ex[:90]))
    lines.append("")
    lines.append("FULL relations.parquet dump (all %d rows):" % len(df))
    lines.append(df.to_string(max_colwidth=40))

    lines.append("")
    lines.append("=" * 100)
    lines.append("C3  research/labels/*.parquet — loss_mask / valid / kind value counts")
    lines.append("=" * 100)
    for name in ("clean", "physical", "visible"):
        p = os.path.join(PKG, "research", "labels", "%s.parquet" % name)
        if not os.path.exists(p):
            lines.append("  %s.parquet : MISSING" % name)
            continue
        d = pd.read_parquet(p)
        lines.append("")
        lines.append("  --- labels/%s.parquet : %d rows x %d cols" % (name, d.shape[0], d.shape[1]))
        lines.append("  columns: %s" % list(d.columns))
        for col in ("loss_mask", "valid", "kind", "layer", "split", "relation",
                    "historical_R2", "truth_incomplete"):
            if col in d.columns:
                vc = d[col].value_counts(dropna=False)
                lines.append("    %-22s (%s) -> %s" % (col, d[col].dtype,
                                                       json.dumps({str(k): int(v)
                                                                   for k, v in vc.items()})))
        lines.append("    first row: %s" % json.dumps(
            {k: (None if pd.isna(v) else (v.item() if hasattr(v, "item") else v))
             for k, v in d.iloc[0].items()}, default=str)[:700])

    with open(os.path.join(OUT, "probe08_relations.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n".join(lines[:200]))


if __name__ == "__main__":
    main()
