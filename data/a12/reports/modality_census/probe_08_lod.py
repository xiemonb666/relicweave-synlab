"""Probe 08: display_lod_glb assets -- what is actually stored, and can it be exported? (READ ONLY)."""
from __future__ import annotations
import json, sqlite3, collections
from pathlib import Path
import numpy as np

ROOT = Path(r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab")
OUT = ROOT / "data" / "a12" / "reports" / "modality_census"

L = []
w = L.append


def main() -> None:
    dbs = sorted(ROOT.joinpath("data").rglob("metadata.sqlite"))
    found = []
    for db in dbs:
        try:
            con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro&immutable=1", uri=True)
            con.row_factory = sqlite3.Row
            tabs = [r[0] for r in con.execute("select name from sqlite_master where type='table'")]
            if "assets" not in tabs:
                con.close()
                continue
            rows = con.execute(
                "select asset_id, role, schema, unit, frame, qa_status, files_json, meta_json "
                "from assets where role='display_lod_glb'").fetchall()
            con.close()
        except Exception:  # noqa: BLE001
            continue
        store_root = db.parent
        for r in rows:
            found.append((db, store_root, r))
    w(f"# probe_08 display_lod_glb census -- {len(found)} assets in {len({f[0] for f in found})} stores")
    w("")
    by_store = collections.Counter(str(f[0].relative_to(ROOT)) for f in found)
    for k, v in by_store.most_common():
        w(f"  {k:60s} {v}")
    w("")
    if found:
        r0 = found[0][2]
        w("## first asset full record")
        w(f"  asset_id={r0['asset_id']} schema={r0['schema']} unit={r0['unit']} frame={r0['frame']} qa={r0['qa_status']}")
        w(f"  files_json={r0['files_json']}")
        w(f"  meta_json={json.dumps(json.loads(r0['meta_json'] or '{}'), ensure_ascii=False)[:3000]}")
        w("")
    # meta keys census
    keys = collections.Counter()
    nested = collections.defaultdict(collections.Counter)
    arrmeta = collections.Counter()
    sizes = []
    exists = collections.Counter()
    for db, store_root, r in found:
        mj = json.loads(r["meta_json"] or "{}")
        for k, v in mj.items():
            keys[k] += 1
            if isinstance(v, dict):
                for kk in v:
                    nested[k][kk] += 1
        fj = json.loads(r["files_json"] or "{}")
        for k, rel in fj.items():
            p = store_root / rel
            exists["exists" if p.exists() else "MISSING"] += 1
            if p.exists():
                sizes.append(p.stat().st_size)
    w("## meta keys across all display_lod_glb")
    for k, v in keys.most_common(40):
        w(f"  {k:34s} {v}")
    for k in sorted(nested):
        w(f"  nested '{k}': {dict(nested[k])}")
    w("")
    w(f"## files_json path existence: {dict(exists)}")
    if sizes:
        a = np.array(sizes)
        w(f"## real file sizes: n={a.size} min={a.min()} median={int(np.median(a))} max={a.max()}")
    # what does the code claim
    w("")
    w("## code: where display_lod_glb is produced")
    txt = "\n".join(L)
    (OUT / "probe_08_lod.txt").write_text(txt, encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    main()
