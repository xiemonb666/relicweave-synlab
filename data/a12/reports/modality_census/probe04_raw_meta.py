"""Probe 04: raw meta_json dumps for the key roles (READ-ONLY).

Dumps the FULL structure of representative assets so the shape of `payload.context`,
`payload.scene`, X03's meta and obs_view scene keys can be read literally (JSON
structure, not dotted guesses). Also reports how `context` is actually nested.
"""
import json
import os
import sqlite3

ROOT = r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab"
MAIN = os.path.join(ROOT, "data", "a12", "metadata.sqlite")
OUT = os.path.join(ROOT, "data", "a12", "reports", "modality_census")


def open_ro(path):
    uri = "file:" + path.replace("\\", "/") + "?mode=ro&immutable=1"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


def skeleton(obj, depth=0, maxdepth=6):
    """Render the STRUCTURE of a JSON object with leaf values, compactly."""
    pad = "  " * depth
    if depth > maxdepth:
        return pad + "...\n"
    out = []
    if isinstance(obj, dict):
        for k in obj:
            v = obj[k]
            if isinstance(v, dict):
                out.append("%s%s: {dict, %d keys}" % (pad, k, len(v)))
                out.append(skeleton(v, depth + 1, maxdepth))
            elif isinstance(v, list):
                out.append("%s%s: [list, %d items]" % (pad, k, len(v)))
                if v:
                    out.append(skeleton(v[0], depth + 1, maxdepth))
            else:
                s = json.dumps(v, default=str)
                if len(s) > 120:
                    s = s[:120] + "..."
                out.append("%s%s: %s" % (pad, k, s))
    else:
        out.append("%s%s" % (pad, json.dumps(obj, default=str)[:200]))
    return "\n".join(out)


def find_context_paths(obj, prefix=""):
    """Yield (json_path, value) for every key literally named 'context'."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = "%s.%s" % (prefix, k) if prefix else str(k)
            if k == "context":
                yield (p, v)
            yield from find_context_paths(v, p)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from find_context_paths(v, "%s[%d]" % (prefix, i))


def main():
    con = open_ro(MAIN)
    cur = con.cursor()
    lines = []

    # ---- 1. Where is `context` in MAIN store, and what is its Python type?
    lines.append("=" * 100)
    lines.append("PART 1: literal `context` keys in data/a12/metadata.sqlite — JSON PATH + PYTHON TYPE")
    lines.append("=" * 100)
    type_counts = {}
    example_by_role = {}
    for r in cur.execute("SELECT asset_id, role, meta_json FROM assets"):
        mj = json.loads(r["meta_json"])
        for path, val in find_context_paths(mj):
            key = (path, type(val).__name__)
            type_counts[key] = type_counts.get(key, 0) + 1
            example_by_role.setdefault((r["role"], path), (r["asset_id"], val))
    for (path, tname), c in sorted(type_counts.items(), key=lambda kv: -kv[1]):
        lines.append("    path=%-46s type=%-6s n=%d" % (path, tname, c))
    lines.append("")
    lines.append("REAL VALUES (first example per role+path):")
    for (role, path), (aid, val) in sorted(example_by_role.items()):
        s = json.dumps(val, default=str)
        if len(s) > 220:
            s = s[:220] + "..."
        lines.append("    role=%-20s path=%-34s asset=%s" % (role, path, aid))
        lines.append("        value = %s" % s)

    # ---- 2. Full skeleton of one X03 asset
    lines.append("")
    lines.append("=" * 100)
    lines.append("PART 2: FULL STRUCTURE of an X03 degrade_measurement asset")
    lines.append("=" * 100)
    rows = cur.execute(
        "SELECT asset_id, role, schema, unit, frame, meta_json FROM assets "
        "WHERE json_extract(meta_json,'$.meta.axis_id')='X03'").fetchall()
    lines.append("X03 assets matched by json_extract($.meta.axis_id)='X03': %d" % len(rows))
    if not rows:
        # fall back: search in python
        cand = []
        for r in cur.execute("SELECT asset_id, role, schema, unit, frame, meta_json FROM assets"):
            mj = json.loads(r["meta_json"])
            m = mj.get("meta", {})
            if isinstance(m, dict) and str(m.get("axis_id")) == "X03":
                cand.append(r)
        rows = cand
        lines.append("X03 assets matched by python scan: %d" % len(rows))
    for r in rows[:3]:
        lines.append("")
        lines.append("  asset_id=%s role=%s schema=%s unit=%s frame=%s"
                     % (r["asset_id"], r["role"], r["schema"], r["unit"], r["frame"]))
        mj = json.loads(r["meta_json"])
        lines.append("  TOP-LEVEL meta_json keys: %s" % sorted(mj))
        m = mj.get("meta", {})
        lines.append("  inner meta keys: %s" % sorted(m) if isinstance(m, dict) else "NOT A DICT")
        lines.append("  --- skeleton(meta_json) ---")
        lines.append(skeleton(mj, 1))
        lines.append("  --- literal context paths in this asset ---")
        for path, val in find_context_paths(mj):
            lines.append("      %s = %s" % (path, json.dumps(val, default=str)[:400]))

    # ---- 3. Full skeleton of one feature_bundle + one degrade_measurement that carry context-ish
    for role in ("feature_bundle", "degrade_measurement"):
        lines.append("")
        lines.append("=" * 100)
        lines.append("PART 3: one %s asset that mentions context (raw)" % role)
        lines.append("=" * 100)
        hit = None
        for r in cur.execute("SELECT asset_id, role, schema, unit, frame, meta_json FROM assets "
                             "WHERE role=?", (role,)):
            if "context" in r["meta_json"]:
                hit = r
                break
        if hit is None:
            lines.append("    no %s asset in the MAIN store mentions 'context'" % role)
            continue
        lines.append("  asset_id=%s schema=%s unit=%s frame=%s"
                     % (hit["asset_id"], hit["schema"], hit["unit"], hit["frame"]))
        mj = json.loads(hit["meta_json"])
        lines.append("  TOP-LEVEL meta_json keys: %s" % sorted(mj))
        lines.append(skeleton(mj, 1))
        lines.append("  --- literal context paths ---")
        for path, val in find_context_paths(mj):
            lines.append("      %s" % path)
            lines.append("        = %s" % json.dumps(val, default=str)[:600])

    # ---- 4. obs_view scene sub-keys
    lines.append("")
    lines.append("=" * 100)
    lines.append("PART 4: obs_view payload.scene.* — exact sub-keys and how many assets carry each")
    lines.append("=" * 100)
    n_obs = 0
    scene_key_counts = {}
    scene_vals = {}
    n_with_scene = 0
    for r in cur.execute("SELECT asset_id, meta_json FROM assets WHERE role='obs_view'"):
        n_obs += 1
        mj = json.loads(r["meta_json"])
        m = mj.get("meta", {})
        payload = m.get("payload") if isinstance(m, dict) else None
        scene = payload.get("scene") if isinstance(payload, dict) else None
        if isinstance(scene, dict):
            n_with_scene += 1
            for k, v in scene.items():
                scene_key_counts[k] = scene_key_counts.get(k, 0) + 1
                if k not in scene_vals:
                    scene_vals[k] = v
    lines.append("obs_view assets in MAIN store: %d ; carrying payload.scene dict: %d"
                 % (n_obs, n_with_scene))
    lines.append("")
    lines.append("payload.scene sub-keys (n = #obs_view assets carrying it):")
    for k, c in sorted(scene_key_counts.items(), key=lambda kv: -kv[1]):
        s = json.dumps(scene_vals[k], default=str)
        if len(s) > 200:
            s = s[:200] + "..."
        lines.append("    %-28s n=%-5d example=%s" % (k, c, s))

    # ---- 5. occluder object identity check
    lines.append("")
    lines.append("=" * 100)
    lines.append("PART 5: occluder structure — identity or anonymous spheres?")
    lines.append("=" * 100)
    seen = 0
    for r in cur.execute("SELECT asset_id, meta_json FROM assets WHERE role='obs_view'"):
        mj = json.loads(r["meta_json"])
        m = mj.get("meta", {})
        payload = m.get("payload") if isinstance(m, dict) else {}
        scene = payload.get("scene") if isinstance(payload, dict) else {}
        if isinstance(scene, dict) and "occluders" in scene:
            lines.append("  asset=%s" % r["asset_id"])
            lines.append("    payload.scene.occluders = %s"
                         % json.dumps(scene["occluders"], default=str)[:500])
            for k in ("occluder_count", "occluder_capacity", "occluder_radius_mm",
                      "occluder_min_radius_mm", "occluder_directions", "light",
                      "target_coverage"):
                if k in scene:
                    lines.append("    payload.scene.%s = %s"
                                 % (k, json.dumps(scene[k], default=str)[:300]))
            seen += 1
            if seen >= 3:
                break
    if seen == 0:
        lines.append("  no obs_view in MAIN store carries payload.scene.occluders")

    con.close()
    with open(os.path.join(OUT, "probe04_raw_meta.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
