"""Probe 03: X03 context payload + observed context values, from real assets (READ-ONLY).

For every asset whose role is degrade_measurement (and feature_bundle), dump:
  - meta.payload.context.*   (the observed context mapping X03 perturbs)
  - meta.measured.*          (X03's own measurement block)
  - meta.extra.touched/conflicts/missing
  - meta.variant / meta.axis_id
Also finds any asset meta carrying axis_id == X03.
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
    uri = "file:" + path.replace("\\", "/") + "?mode=ro&immutable=1"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


def walk_find(obj, key):
    """Yield every value stored under `key` anywhere in a nested structure."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key:
                yield v
            yield from walk_find(v, key)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_find(v, key)


def main():
    ctx_values = collections.defaultdict(collections.Counter)
    n_ctx_assets = 0
    n_ctx_assets_by_role = collections.Counter()
    x03_assets = []
    variant_counts = collections.Counter()
    axis_counts = collections.Counter()
    measured_dist = collections.defaultdict(collections.Counter)
    n_axis_assets = 0
    lines = []

    for p in find_stores():
        rel = os.path.relpath(p, ROOT)
        con = open_ro(p)
        cur = con.cursor()
        tabs = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        if "assets" not in tabs:
            con.close()
            continue
        for r in cur.execute("SELECT asset_id, role, meta_json FROM assets"):
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
            found_ctx = False
            for ctx in walk_find(meta, "context"):
                if isinstance(ctx, dict):
                    found_ctx = True
                    for k, v in ctx.items():
                        ctx_values[k][json.dumps(v, default=str)] += 1
            if found_ctx:
                n_ctx_assets += 1
                n_ctx_assets_by_role[r["role"]] += 1

            axis_id = meta.get("axis_id")
            if axis_id:
                n_axis_assets += 1
                axis_counts[str(axis_id)] += 1
            variant = meta.get("variant")
            if variant:
                variant_counts[(str(axis_id), str(variant))] += 1

            # X03-style payload: payload.context + measured.keys_total
            payload = meta.get("payload")
            meas = meta.get("measured")
            if isinstance(payload, dict) and "context" in payload and isinstance(meas, dict) \
                    and "keys_total" in meas:
                entry = {
                    "store": rel,
                    "asset_id": r["asset_id"],
                    "role": r["role"],
                    "axis_id": axis_id,
                    "variant": variant,
                    "level": meta.get("level"),
                    "context_before": payload.get("context"),
                    "measured": meas,
                    "extra": meta.get("extra"),
                }
                x03_assets.append(entry)
                for k, v in meas.items():
                    measured_dist[k][json.dumps(v, default=str)] += 1
        con.close()

    lines.append("=" * 100)
    lines.append("PART 1: `context` MAPPINGS FOUND ANYWHERE IN meta_json")
    lines.append("=" * 100)
    lines.append("assets carrying a `context` dict anywhere: %d" % n_ctx_assets)
    lines.append("by role: %s" % json.dumps(dict(n_ctx_assets_by_role)))
    lines.append("")
    lines.append("REAL VALUES OBSERVED PER context KEY (value -> #occurrences across all assets/stores):")
    for k in sorted(ctx_values):
        vals = ctx_values[k]
        lines.append("")
        lines.append("  context key %r : %d distinct values, %d total occurrences"
                     % (k, len(vals), sum(vals.values())))
        for v, c in vals.most_common(12):
            s = v if len(v) < 110 else v[:110] + "..."
            lines.append("        %-70s  n=%d" % (s, c))
        if len(vals) > 12:
            lines.append("        ... %d more distinct values" % (len(vals) - 12))

    lines.append("")
    lines.append("=" * 100)
    lines.append("PART 2: axis_id / variant DISTRIBUTION (all stores)")
    lines.append("=" * 100)
    lines.append("assets carrying meta.axis_id: %d" % n_axis_assets)
    for a, c in axis_counts.most_common():
        lines.append("    axis_id=%-6s n=%d" % (a, c))
    lines.append("")
    lines.append("(axis_id, variant) pairs:")
    for (a, v), c in variant_counts.most_common():
        lines.append("    %-6s %-24s n=%d" % (a, v, c))

    lines.append("")
    lines.append("=" * 100)
    lines.append("PART 3: X03-SHAPED PAYLOADS (payload.context + measured.keys_total)")
    lines.append("=" * 100)
    lines.append("matching assets: %d" % len(x03_assets))
    for e in x03_assets[:40]:
        lines.append("")
        lines.append("  store=%s asset=%s role=%s axis=%s variant=%s level=%s"
                     % (e["store"], e["asset_id"], e["role"], e["axis_id"],
                        e["variant"], e["level"]))
        lines.append("    payload.context = %s" % json.dumps(e["context_before"], default=str))
        lines.append("    measured        = %s" % json.dumps(e["measured"], default=str))
        lines.append("    extra           = %s" % json.dumps(e["extra"], default=str))
    if len(x03_assets) > 40:
        lines.append("")
        lines.append("  ... %d more (see JSON)" % (len(x03_assets) - 40))

    lines.append("")
    lines.append("=" * 100)
    lines.append("PART 4: measured.* VALUE DISTRIBUTION FOR X03-SHAPED ASSETS")
    lines.append("=" * 100)
    for k in sorted(measured_dist):
        lines.append("  measured.%s -> %s" % (k, json.dumps(dict(measured_dist[k]))))

    with open(os.path.join(OUT, "probe03_x03_context.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    with open(os.path.join(OUT, "probe03_x03_context.json"), "w", encoding="utf-8") as f:
        json.dump({"ctx_values": {k: dict(v) for k, v in ctx_values.items()},
                   "n_ctx_assets": n_ctx_assets,
                   "n_ctx_assets_by_role": dict(n_ctx_assets_by_role),
                   "axis_counts": dict(axis_counts),
                   "variant_counts": {"%s|%s" % k: v for k, v in variant_counts.items()},
                   "x03_assets": x03_assets,
                   "measured_dist": {k: dict(v) for k, v in measured_dist.items()}},
                  f, indent=2, default=str)
    print("\n".join(lines[:200]))


if __name__ == "__main__":
    main()
