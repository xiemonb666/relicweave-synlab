"""Verify the SQL snippets quoted in docs/a12/closed_loop.md section 15 against a real store.

Usage: python data/a12_exports/_scratch/check_doc_sql.py <store_root>
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

RUN_ROLE_SQL = """
SELECT json_extract(meta_json,'$.run_id') AS run_id, role, COUNT(*) AS n,
       SUM(CASE WHEN qa_status='QA_PASS' THEN 1 ELSE 0 END) AS qa_pass
FROM assets GROUP BY 1,2 ORDER BY 1,2
"""

SET_SQL = {
    "vessels": "SELECT DISTINCT json_extract(meta_json,'$.vessel_id') FROM assets "
               "WHERE role='mother_mesh'",
    "materials": "SELECT DISTINCT json_extract(meta_json,'$.material_id') FROM assets "
                 "WHERE role IN ('mother_mesh','material_profile')",
    "patterns": "SELECT DISTINCT json_extract(meta_json,'$.family_id') FROM assets "
                "WHERE role='pattern_recipe'",
    "fracture_backends": "SELECT DISTINCT json_extract(meta_json,'$.backend') FROM assets "
                         "WHERE role IN ('fragment_mesh','clean_truth')",
    "axes": "SELECT DISTINCT json_extract(meta_json,'$.axis_id') FROM assets "
            "WHERE json_extract(meta_json,'$.axis_id') IS NOT NULL",
}

ATTRIBUTION_SQL = """
SELECT CASE WHEN json_extract(meta_json,'$.run_id') IS NULL THEN 'none'
            WHEN json_extract(meta_json,'$.run_id_source') IS NULL THEN 'at_commit'
            ELSE 'repair' END AS attribution, COUNT(*) AS n
FROM assets GROUP BY 1 ORDER BY 1
"""

MOTHERS_SQL = """
SELECT COUNT(DISTINCT json_extract(meta_json,'$.mother_id')) FROM assets
WHERE role='mother_mesh'
"""


def main(argv: list[str]) -> int:
    root = Path(argv[1])
    con = sqlite3.connect(f"file:{root / 'metadata.sqlite'}?mode=ro", uri=True)
    rows = con.execute(RUN_ROLE_SQL).fetchall()
    print(f"run/role rows: {len(rows)}")
    for row in rows[:3]:
        print("   ", row)
    for name, sql in SET_SQL.items():
        values = sorted(value for (value,) in con.execute(sql) if value)
        print(f"{name}: {len(values)} {values[:8]}")
    print("attribution:", con.execute(ATTRIBUTION_SQL).fetchall())
    print("distinct mothers:", con.execute(MOTHERS_SQL).fetchone())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
