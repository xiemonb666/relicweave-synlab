"""Probe 05: flat-dotted-key reality for payload.context / payload.scene / X03 (READ-ONLY).

The role `meta` objects store dotted paths as LITERAL flat key names
(e.g. the key string "payload.context.route"), not nested dicts.  This probe:
  1. locates every store/role carrying flat keys with prefix payload.context / payload.scene
  2. dumps the complete flat key->value map of one such asset per role
  3. dumps every X03 axis asset across ALL stores (full meta)
  4. shows the occluder representation verbatim
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
    for dirpath, dirnames, filenames in os.walk(DATA):
        for fn in filenames:
            if fn == "metadata.sqlite":
                hits.append(os.path.join(dirpath, fn))
    return sorted(hits)


def open_ro(path):
    uri = "file:".replace("\\", "/") + path.replace("\\", "/") + "?mode=ro&immutable=1"
    uri = "file:" + path.replace("\\", "/") + "?mode=ro&immutable=1"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


def inner_meta(mj):
    """The role meta object; meta.json wraps it under 'meta' only for SOME roles."""
    if isinstance(mj, dict) and isinstance(mj.get("meta"), dict):
        return mj["meta"], True
    return mj, False


def main():
    lines = []
    prefix_hits = collections.defaultdict(collections.Counter)   # prefix -> role
    prefix_stores = collections.defaultdict(collections.Counter)
    wrapped_counts = collections.defaultdict(collections.Counter)  # role -> wrapped?
    ctx_keyvals = collections.defaultdict(collections.Counter)
    scene_keyvals = collections.defaultdict(collections.Counter)
    examples = {}
    x03_assets = []

    for p in find_stores():
        rel = os.path.relpath(p, ROOT)
        con = open_ro(p)
        cur = con.cursor()
        tabs = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        if "assets" not in tabs:
            con.close()
            continue
        for r in cur.execute("SELECT asset_id, role, schema, unit, frame, meta_json FROM assets"):
            mj = json.loads(r["meta_json"])
            m, wrapped = inner_meta(mj)
            wrapped_counts[r["role"]]["wrapped" if wrapped else "flat_top"] += 1
            if not isinstance(m, dict):
                continue
            for k, v in m.items():
                ks = str(k)
                if ks.startswith("payload.context") or ks.startswith("payload_meta.payload.context"):
                    prefix_hits["payload.context"][r["role"]] += 1
                    prefix_stores["payload.context"][rel] += 1
                    ctx_keyvals[ks][json.dumps(v, default=str)] += 1
                    examples.setdefault(("ctx", r["role"]), (rel, r["asset_id"], m))
                if ks.startswith("payload.scene") or ks.startswith("payload_meta.payload.scene"):
                    prefix_hits["payload.scene"][r["role"]] += 1
                    prefix_stores["payload.scene"][rel] += 1
                    scene_keyvals[ks][json.dumps(v, default=str)] += 1
                    examples.setdefault(("scene", r["role"]), (rel, r["asset_id"], m))
            if str(m.get("axis_id")) == "X03":
                x03_assets.append({"store": rel, "asset_id": r["asset_id"], "role": r["role"],
                                   "schema": r["schema"], "unit": r["unit"], "frame": r["frame"],
                                   "meta": m})
        con.close()

    lines.append("=" * 100)
    lines.append("PART 0: does meta_json wrap role meta under a top-level 'meta' key?  (per role)")
    lines.append("=" * 100)
    for role in sorted(wrapped_counts):
        w = wrapped_counts[role]
        lines.append("    %-24s wrapped=%d  flat_top_level=%d"
                     % (role, w.get("wrapped", 0), w.get("flat_top", 0)))

    lines.append("")
    lines.append("=" * 100)
    lines.append("PART 1: roles carrying flat `payload.context*` / `payload.scene*` keys (ALL stores)")
    lines.append("=" * 100)
    for pref in ("payload.context", "payload.scene"):
        lines.append("")
        lines.append("  prefix %r -> roles: %s" % (pref, json.dumps(dict(prefix_hits[pref]))))
        lines.append("  prefix %r -> stores: %s" % (pref, json.dumps(dict(prefix_stores[pref]))))

    lines.append("")
    lines.append("=" * 100)
    lines.append("PART 2: payload.context.* EXACT key -> value distribution")
    lines.append("=" * 100)
    for k in sorted(ctx_keyvals):
        if not k.startswith("payload.context"):
            continue
        vals = ctx_keyvals[k]
        lines.append("  %s : %d distinct value(s), n=%d" % (k, len(vals), sum(vals.values())))
        for v, c in vals.most_common(10):
            lines.append("        %-50s n=%d" % (v, c))

    lines.append("")
    lines.append("=" * 100)
    lines.append("PART 3: payload.scene.* EXACT key -> value distribution (obs_view)")
    lines.append("=" * 100)
    for k in sorted(scene_keyvals):
        vals = scene_keyvals[k]
        lines.append("  %-46s n=%-4d values=%s" % (k, sum(vals.values()),
                                                   json.dumps(dict(vals.most_common(4)))[:120]))

    lines.append("")
    lines.append("=" * 100)
    lines.append("PART 4: COMPLETE flat meta of one obs_view carrying payload.scene.*")
    lines.append("=" * 100)
    ex = examples.get(("scene", "obs_view"))
    if ex:
        rel, aid, m = ex
        lines.append("  store=%s asset_id=%s" % (rel, aid))
        lines.append("  %d keys:" % len(m))
        for k in sorted(m):
            s = json.dumps(m[k], default=str)
            if len(s) > 200:
                s = s[:200] + "..."
            lines.append("      %-52s = %s" % (k, s))
    else:
        lines.append("  无 — no obs_view asset carries payload.scene anywhere")

    lines.append("")
    lines.append("=" * 100)
    lines.append("PART 5: COMPLETE flat meta of one degrade_measurement carrying payload.context.*")
    lines.append("=" * 100)
    ex = examples.get(("ctx", "degrade_measurement"))
    if ex:
        rel, aid, m = ex
        lines.append("  store=%s asset_id=%s" % (rel, aid))
        for k in sorted(m):
            if k.startswith("payload.") or k.startswith("payload_meta.") or k in (
                    "axis_id", "variant", "level", "measured", "units", "source_kind"):
                s = json.dumps(m[k], default=str)
                if len(s) > 160:
                    s = s[:160] + "..."
                lines.append("      %-52s = %s" % (k, s))
    else:
        lines.append("  无")

    lines.append("")
    lines.append("=" * 100)
    lines.append("PART 6: EVERY X03 asset across all stores (full flat meta)")
    lines.append("=" * 100)
    lines.append("X03 assets found: %d" % len(x03_assets))
    for e in x03_assets:
        lines.append("")
        lines.append("  store=%s asset=%s role=%s schema=%s unit=%s frame=%s"
                     % (e["store"], e["asset_id"], e["role"], e["schema"], e["unit"], e["frame"]))
        m = e["meta"]
        for k in sorted(m):
            if k.startswith("payload.") or k.startswith("payload_meta.") or k in (
                    "axis_id", "variant", "level", "measured", "units", "realized", "extra",
                    "source_kind", "origin_role", "planned"):
                s = json.dumps(m[k], default=str)
                if len(s) > 300:
                    s = s[:300] + "..."
                lines.append("      %-52s = %s" % (k, s))

    with open(os.path.join(OUT, "probe05_flatkeys.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    with open(os.path.join(OUT, "probe05_flatkeys.json"), "w", encoding="utf-8") as f:
        json.dump({"prefix_hits": {k: dict(v) for k, v in prefix_hits.items()},
                   "prefix_stores": {k: dict(v) for k, v in prefix_stores.items()},
                   "ctx_keyvals": {k: dict(v) for k, v in ctx_keyvals.items()},
                   "scene_keyvals": {k: dict(v) for k, v in scene_keyvals.items()},
                   "wrapped": {k: dict(v) for k, v in wrapped_counts.items()},
                   "n_x03": len(x03_assets),
                   "x03": x03_assets}, f, indent=2, default=str)
    print("\n".join(lines))


if __name__ == "__main__":
    main()
