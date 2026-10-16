"""Probe 02: census the store sqlite catalog + asset metadata (READ ONLY, opened immutable)."""
from __future__ import annotations
import json, sqlite3, collections, sys
from pathlib import Path

ROOT = Path(r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab")
OUT = ROOT / "data" / "a12" / "reports" / "modality_census"
DB = ROOT / "data" / "a12" / "metadata.sqlite"


def connect():
    uri = f"file:{DB.as_posix()}?mode=ro&immutable=1"
    return sqlite3.connect(uri, uri=True)


def main() -> None:
    con = connect()
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    L = []
    w = L.append

    w(f"# probe_02 sqlite catalog census  db={DB}  size={DB.stat().st_size if DB.exists() else 'MISSING'}")
    tables = [r[0] for r in cur.execute(
        "select name from sqlite_master where type='table' order by name")]
    w(f"tables ({len(tables)}): {tables}")
    w("")
    for t in tables:
        try:
            n = cur.execute(f'select count(*) from "{t}"').fetchone()[0]
        except Exception as e:  # noqa: BLE001
            w(f"  {t}: count failed: {e}")
            continue
        cols = [r[1] for r in cur.execute(f'pragma table_info("{t}")')]
        w(f"  {t:26s} rows={n:<8d} cols={cols}")
    w("")

    # assets-like table
    for t in tables:
        cols = [r[1] for r in cur.execute(f'pragma table_info("{t}")')]
        if "role" in cols:
            w(f"## role distribution in table {t}")
            for r in cur.execute(
                    f'select role, schema, unit, frame, count(*) c from "{t}" '
                    f'group by role, schema, unit, frame order by c desc'):
                w(f"  {str(r[0]):32s} {str(r[1]):30s} unit={str(r[2]):8s} frame={str(r[3]):16s} {r[4]}")
            w("")
            w(f"## role × status in {t}")
            if "status" in cols:
                for r in cur.execute(
                        f'select role, status, count(*) c from "{t}" group by role,status order by role,c desc'):
                    w(f"  {str(r[0]):32s} {str(r[1]):14s} {r[2]}")
                w("")
            w(f"## role × qa_status in {t}")
            if "qa_status" in cols:
                for r in cur.execute(
                        f'select role, qa_status, count(*) c from "{t}" group by role,qa_status order by role,c desc'):
                    w(f"  {str(r[0]):32s} {str(r[1]):14s} {r[2]}")
                w("")
            w(f"## all columns of {t}: {cols}")
            w("")
            # sample rows (meta stripped)
            w(f"## 3 sample rows from {t} (meta truncated to keys)")
            for r in cur.execute(f'select * from "{t}" limit 3'):
                d = dict(r)
                for k in list(d):
                    if isinstance(d[k], str) and len(d[k]) > 400:
                        try:
                            j = json.loads(d[k])
                            d[k] = f"<json keys={sorted(j)[:40]}>"
                        except Exception:
                            d[k] = d[k][:200] + "..."
                w("  " + json.dumps(d, ensure_ascii=False, default=str)[:3000])
            w("")
    con.close()
    txt = "\n".join(L)
    (OUT / "probe_02_sqlite_census.txt").write_text(txt, encoding="utf-8")
    print(txt[:8000])
    print(f"\n...wrote probe_02_sqlite_census.txt ({len(txt)} chars)")


if __name__ == "__main__":
    main()
