"""Probe 07: scan EVERY metadata.sqlite under data/ -- global role census + obs backend (READ ONLY)."""
from __future__ import annotations
import json, sqlite3, collections
from pathlib import Path

ROOT = Path(r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab")
OUT = ROOT / "data" / "a12" / "reports" / "modality_census"

L = []
w = L.append


def main() -> None:
    dbs = sorted(ROOT.joinpath("data").rglob("metadata.sqlite"))
    w(f"# probe_07 global store scan -- {len(dbs)} metadata.sqlite files under data/")
    w("")
    global_roles = collections.Counter()
    global_schema_ok = 0
    writer_classes = collections.Counter()
    renderers = collections.Counter()
    routes = collections.Counter()
    obs_rows = []
    lod_rows = []
    glb_files = []
    for db in dbs:
        rel = db.relative_to(ROOT).as_posix()
        try:
            con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro&immutable=1", uri=True)
            con.row_factory = sqlite3.Row
            tabs = [r[0] for r in con.execute(
                "select name from sqlite_master where type='table'")]
            if "assets" not in tabs:
                w(f"  {rel}: no assets table (tables={tabs})")
                con.close()
                continue
            rows = con.execute(
                "select role, schema, unit, frame, qa_status, meta_json from assets").fetchall()
            con.close()
        except Exception as e:  # noqa: BLE001
            w(f"  {rel}: ERROR {e}")
            continue
        w(f"  {rel:70s} assets={len(rows):6d}")
        global_schema_ok += len(rows)
        rc = collections.Counter(r["role"] for r in rows)
        for k, v in rc.items():
            global_roles[k] += v
        for r in rows:
            global_roles[r["role"]] += 0
            if r["role"] == "obs_result":
                mj = json.loads(r["meta_json"] or "{}")
                br = mj.get("backend_report") or {}
                mm = mj.get("meta") or {}
                writer_classes[str(br.get("route"))] += 1
                renderers[str(mm.get("renderer"))] += 1
                routes[str(mj.get("route"))] += 1
                obs_rows.append((rel, r["schema"], str(mm.get("renderer")),
                                 str(mm.get("renderer_class")), str(mj.get("route")),
                                 int(mm.get("n_views") or 0)))
            if r["role"] in ("display_lod_glb",):
                lod_rows.append((rel, r["schema"]))
    w("")
    w("## global role census across ALL stores")
    for k, v in global_roles.most_common():
        w(f"  {k:32s} {v}")
    w("")
    w(f"## total asset rows across all stores = {global_schema_ok}")
    w("")
    w("## obs_result backend_report.route histogram")
    for k, v in writer_classes.most_common():
        w(f"  {k:32s} {v}")
    w("## obs_result meta.renderer histogram")
    for k, v in renderers.most_common():
        w(f"  {k:32s} {v}")
    w("## obs_result meta.renderer_class histogram")
    rc2 = collections.Counter(str(x[3]) for x in obs_rows)
    for k, v in rc2.most_common():
        w(f"  {k:32s} {v}")
    w("## obs_result route histogram")
    for k, v in routes.most_common():
        w(f"  {k:32s} {v}")
    w("## obs_result n_views histogram")
    for k, v in collections.Counter(x[5] for x in obs_rows).most_common():
        w(f"  n_views={k:4d}  {v}")
    w("")
    w(f"## display_lod_glb rows found in ANY store: {len(lod_rows)}")
    # search filesystem for glb / LOD artifacts
    for pat in ("*.glb", "*.gltf"):
        hits = sorted(ROOT.joinpath("data").rglob(pat))
        w(f"## filesystem {pat}: {len(hits)}")
        for h in hits[:25]:
            w(f"    {h.relative_to(ROOT).as_posix()}  {h.stat().st_size/1024:.1f} KB")
    # search for LOD-ish names
    hits = [p for p in ROOT.joinpath("data").rglob("*")
            if p.is_file() and any(t in p.name.lower() for t in ("lod", "decimat", "simplif"))]
    w(f"## files with lod/decimat/simplif in the name: {len(hits)}")
    for h in hits[:30]:
        w(f"    {h.relative_to(ROOT).as_posix()}")

    txt = "\n".join(L)
    (OUT / "probe_07_global_stores.txt").write_text(txt, encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    main()
