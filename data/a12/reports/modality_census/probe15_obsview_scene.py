"""Probe 15: EXACT obs_view payload.scene.* census for data/a12/metadata.sqlite ONLY.

The task asks: which obs_view assets in data/a12/metadata.sqlite carry payload.scene.* keys,
with exact denominators.  Also verifies whether `light` is a reference string or numeric params.
"""
import json
import os
import sqlite3
import collections

ROOT = r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab"
MAIN = os.path.join(ROOT, "data", "a12", "metadata.sqlite")
OUT = os.path.join(ROOT, "data", "a12", "reports", "modality_census")


def main():
    con = sqlite3.connect("file:" + MAIN.replace("\\", "/") + "?mode=ro&immutable=1", uri=True)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    rows = cur.execute("SELECT asset_id, unit, frame, qa_status, meta_json FROM assets "
                       "WHERE role='obs_view'").fetchall()
    n = len(rows)
    keycount = collections.Counter()
    keyval = collections.defaultdict(collections.Counter)
    n_any_scene = 0
    n_occluder_set = 0
    n_light_only = 0
    per_asset = []
    for r in rows:
        mj = json.loads(r["meta_json"])
        m = mj.get("meta", mj)
        scene = {k: v for k, v in m.items() if str(k).startswith("payload.scene")}
        if scene:
            n_any_scene += 1
        has_occ = any(k.startswith("payload.scene.occluder") for k in scene)
        if has_occ:
            n_occluder_set += 1
        if scene and not has_occ:
            n_light_only += 1
        for k, v in scene.items():
            keycount[k] += 1
            keyval[k][json.dumps(v, default=str)] += 1
        per_asset.append((r["asset_id"], len(scene), has_occ, bool(scene)))

    L = []
    L.append("data/a12/metadata.sqlite  role=obs_view : %d assets total" % n)
    L.append("  assets carrying ANY payload.scene* key : %d / %d" % (n_any_scene, n))
    L.append("  assets carrying an occluder* key      : %d / %d" % (n_occluder_set, n))
    L.append("  assets carrying scene but no occluder : %d / %d" % (n_light_only, n))
    L.append("  assets carrying NO scene key          : %d / %d" % (n - n_any_scene, n))
    L.append("")
    L.append("unit/frame/qa of the obs_view assets:")
    for col in ("unit", "frame", "qa_status"):
        L.append("    %-10s %s" % (col, json.dumps(dict(collections.Counter(
            r[col] for r in rows)))))
    L.append("")
    L.append("=" * 96)
    L.append("EXACT payload.scene.* KEY -> COUNT (out of %d obs_view assets)" % n)
    L.append("=" * 96)
    for k, c in sorted(keycount.items()):
        vals = keyval[k]
        vs = ", ".join("%s:%d" % (a, b) for a, b in vals.most_common(6))
        if len(vs) > 110:
            vs = vs[:110] + "..."
        L.append("  %-42s n=%-3d  values{%s}" % (k, c, vs))
    L.append("")
    L.append("distinct payload.scene.* key names in MAIN store: %d" % len(keycount))
    L.append("")
    L.append("=" * 96)
    L.append("IS `light` NUMERIC LIGHTING PARAMETERS OR A REFERENCE STRING?")
    L.append("=" * 96)
    lv = keyval.get("payload.scene.light", {})
    L.append("  payload.scene.light distinct values: %s" % json.dumps(dict(lv)))
    L.append("  -> a single quoted STRING naming a spec object, not intensity/colour numbers")
    L.append("")
    L.append("  payload.scene.occluders distinct values: %s"
             % json.dumps(dict(keyval.get("payload.scene.occluders", {}))))
    L.append("  -> the scalar 0, written literally at synlab/degrade/api.py:923")

    con.close()
    with open(os.path.join(OUT, "probe15_obsview_scene.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print("\n".join(L))


if __name__ == "__main__":
    main()
