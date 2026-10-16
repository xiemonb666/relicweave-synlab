"""Probe 03: per-role field/array census with REAL numbers (READ ONLY)."""
from __future__ import annotations
import json, sqlite3, collections, numpy as np
from pathlib import Path

ROOT = Path(r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab")
OUT = ROOT / "data" / "a12" / "reports" / "modality_census"
DB = ROOT / "data" / "a12" / "metadata.sqlite"
ASSETS = ROOT / "data" / "a12" / "assets"


def main() -> None:
    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro&immutable=1", uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "select asset_id, role, schema, unit, frame, qa_status, files_json, meta_json "
        "from assets order by role, asset_id").fetchall()
    con.close()

    L = []
    w = L.append
    w(f"# probe_03 per-role field/array census  (rows={len(rows)})")
    w("")

    by_role = collections.defaultdict(list)
    for r in rows:
        by_role[r["role"]].append(r)

    for role in sorted(by_role):
        rs = by_role[role]
        w(f"{'='*100}")
        w(f"## ROLE {role}   n={len(rs)}   schema={rs[0]['schema']} unit={rs[0]['unit']} frame={rs[0]['frame']}")
        meta_keys = collections.Counter()
        nested = collections.defaultdict(collections.Counter)
        for r in rs:
            mj = json.loads(r["meta_json"] or "{}")
            for k, v in mj.items():
                meta_keys[k] += 1
                if isinstance(v, dict):
                    for kk in v:
                        nested[k][kk] += 1
        w(f"  meta.json :: meta keys (count of assets having key):")
        for k, c in meta_keys.most_common(80):
            w(f"      {k:44s} {c}")
        for k in sorted(nested):
            if len(nested[k]) <= 30:
                w(f"  nested under '{k}': {dict(nested[k])}")
        w("")
        # arrays
        arrkeys = collections.defaultdict(collections.Counter)
        arrshapes = collections.defaultdict(collections.Counter)
        arrdtype = collections.defaultdict(collections.Counter)
        n_npz = 0
        for r in rs:
            p = ASSETS / r["asset_id"] / "arrays.npz"
            if not p.exists():
                continue
            n_npz += 1
            try:
                with np.load(p, allow_pickle=False) as z:
                    for k in z.files:
                        a = z[k]
                        arrkeys[k][role] += 1
                        arrshapes[k][f"{a.shape}|{a.dtype}"] += 1
            except Exception as e:  # noqa: BLE001
                w(f"  !! npz read fail {r['asset_id']}: {e}")
        w(f"  arrays.npz present for {n_npz}/{len(rs)} assets")
        for k in sorted(arrshapes):
            top = arrshapes[k].most_common(6)
            w(f"      {k:28s} count={sum(arrshapes[k].values()):<4d} shapes/dtypes: " +
              ", ".join(f"{s}x{c}" for s, c in top))
        w("")
        # qa_status
        qs = collections.Counter(r["qa_status"] for r in rs)
        w(f"  qa_status: {dict(qs)}")
        w("")

    txt = "\n".join(L)
    (OUT / "probe_03_role_fields.txt").write_text(txt, encoding="utf-8")
    print(txt[:30000])
    print(f"\n...wrote probe_03_role_fields.txt ({len(txt)} chars)")


if __name__ == "__main__":
    main()
