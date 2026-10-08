"""Throw-away probe: dump one store's job rows + events to a UTF-8 text file.

Usage:  python _probe_jobs.py <store-root> <out.txt>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from synlab.storage.store import AssetStore  # noqa: E402


def main() -> int:
    root = Path(sys.argv[1])
    out = Path(sys.argv[2])
    store = AssetStore(root)
    lines: list[str] = []
    with store.connect() as conn:
        for row in conn.execute("SELECT job_id, stage, state, attempt, error_json FROM jobs"):
            lines.append(f"JOB {row['job_id']} stage={row['stage']} state={row['state']} attempt={row['attempt']}")
            if row["error_json"]:
                lines.append("    error=" + str(row["error_json"])[:800])
        for row in conn.execute("SELECT run_id, status, revision FROM runs"):
            lines.append(f"RUN {row['run_id']} status={row['status']} revision={row['revision']}")
        cols = [r[1] for r in conn.execute("PRAGMA table_info(events)")]
        lines.append("EVENT_COLUMNS " + ", ".join(cols))
        for row in conn.execute("SELECT * FROM events ORDER BY rowid"):
            record = dict(row)
            lines.append("EV " + json.dumps(record, ensure_ascii=False, default=str)[:600])
    assets = store.list_assets(limit=2000)
    lines.append(f"ASSETS {len(assets)}")
    for asset in assets[:40]:
        lines.append(f"  {asset.asset_id} {asset.role} {asset.qa_status} meta.run_id={(asset.meta or {}).get('run_id')}")
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"written {len(lines)} lines -> {out}")
    # also echo a compact json view of the biggest pieces so a shell can read it
    print(json.dumps({"jobs": len([l for l in lines if l.startswith('JOB')]),
                      "assets": len(assets)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
