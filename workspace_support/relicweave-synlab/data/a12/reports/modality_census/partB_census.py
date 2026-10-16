"""partB_census -- READ-ONLY sqlite census of the asset metadata contract (role -> schema/unit/frame/qa/meta keys).

Writes partB_census.txt and partB_census.json into the same directory.
Never opens the database for writing: mode=ro&immutable=1, uri=True.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter, OrderedDict
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]  # data/a12/reports/modality_census -> repo root
DB = REPO / "data" / "a12" / "metadata.sqlite"

OUT_TXT = HERE / "partB_census.txt"
OUT_JSON = HERE / "partB_census.json"


def connect(path: Path) -> sqlite3.Connection:
    uri = "file:" + str(path).replace("\\", "/") + "?mode=ro&immutable=1"
    return sqlite3.connect(uri, uri=True)


def main() -> int:
    lines: list[str] = []

    def emit(text: str = "") -> None:
        lines.append(text)

    emit(f"repo_root      = {REPO}")
    emit(f"db_path        = {DB}")
    emit(f"db_exists      = {DB.exists()}  size_bytes = {DB.stat().st_size if DB.exists() else -1}")

    con = connect(DB)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    # ---------------------------------------------------------------- schema of the db
    emit("\n== sqlite schema objects ==")
    for row in cur.execute(
        "SELECT type, name, tbl_name FROM sqlite_master ORDER BY type, name"
    ):
        emit(f"  {row['type']:6s} {row['name']:28s} tbl={row['tbl_name']}")

    emit("\n== PRAGMA table_info(assets) ==")
    cols = list(cur.execute("PRAGMA table_info(assets)"))
    for c in cols:
        emit(f"  cid={c['cid']:<3} {c['name']:<20} type={c['type']:<10} notnull={c['notnull']} pk={c['pk']}")
    col_names = [c["name"] for c in cols]
    emit(f"  asset column count = {len(col_names)}")

    emit("\n== integrity / counts ==")
    total = cur.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
    emit(f"  assets rows total          = {total}")
    emit(f"  distinct asset_id          = {cur.execute('SELECT COUNT(DISTINCT asset_id) FROM assets').fetchone()[0]}")
    emit(f"  distinct blob_hash         = {cur.execute('SELECT COUNT(DISTINCT blob_hash) FROM assets').fetchone()[0]}")
    emit(f"  distinct role              = {cur.execute('SELECT COUNT(DISTINCT role) FROM assets').fetchone()[0]}")
    emit(f"  distinct schema            = {cur.execute('SELECT COUNT(DISTINCT schema) FROM assets').fetchone()[0]}")
    emit(f"  distinct unit              = {cur.execute('SELECT COUNT(DISTINCT unit) FROM assets').fetchone()[0]}")
    emit(f"  distinct frame             = {cur.execute('SELECT COUNT(DISTINCT frame) FROM assets').fetchone()[0]}")
    emit(f"  distinct qa_status         = {cur.execute('SELECT COUNT(DISTINCT qa_status) FROM assets').fetchone()[0]}")

    emit("\n== global distinct values ==")
    for column in ("schema", "unit", "frame", "qa_status", "split"):
        rows = list(cur.execute(f"SELECT {column} AS v, COUNT(*) AS n FROM assets GROUP BY 1 ORDER BY n DESC, v"))
        emit(f"  {column}: {len(rows)} distinct")
        for r in rows:
            emit(f"      {r['v']!r:<34} n={r['n']}")

    emit("\n== NULL / empty audit for the columns of interest ==")
    for column in col_names:
        n_null = cur.execute(f"SELECT COUNT(*) FROM assets WHERE {column} IS NULL").fetchone()[0]
        n_empty = cur.execute(
            f"SELECT COUNT(*) FROM assets WHERE {column} IS NOT NULL AND CAST({column} AS TEXT) = ''"
        ).fetchone()[0]
        emit(f"  {column:<20} null={n_null:<6} empty_string={n_empty}")

    # ---------------------------------------------------------------- per role
    roles = [r["role"] for r in cur.execute("SELECT role, COUNT(*) n FROM assets GROUP BY 1 ORDER BY n DESC, role")]
    emit(f"\n== distinct roles in sqlite = {len(roles)} ==")
    for r in roles:
        n = cur.execute("SELECT COUNT(*) FROM assets WHERE role=?", (r,)).fetchone()[0]
        emit(f"  {r:<24} {n}")

    report: "OrderedDict[str, dict]" = OrderedDict()
    meta_anomalies: list[dict] = []
    json_failures: list[dict] = []

    for role in roles:
        entry: dict = OrderedDict()
        entry["row_count"] = cur.execute("SELECT COUNT(*) FROM assets WHERE role=?", (role,)).fetchone()[0]
        for column in ("schema", "unit", "frame", "qa_status", "split"):
            rows = list(
                cur.execute(
                    f"SELECT {column} AS v, COUNT(*) AS n FROM assets WHERE role=? GROUP BY 1 ORDER BY n DESC, v",
                    (role,),
                )
            )
            entry[column] = OrderedDict((("" if r["v"] is None else str(r["v"])), r["n"]) for r in rows)

        # meta_json -> inner "meta" object
        key_counts: Counter = Counter()
        n_rows = 0
        n_obj = 0
        n_top_meta_key = 0
        n_inner_dict = 0
        n_inner_missing = 0
        n_meta_null = 0
        inner_union_sample: dict = {}
        for row in cur.execute(
            "SELECT asset_id, meta_json FROM assets WHERE role=? ORDER BY asset_id", (role,)
        ):
            n_rows += 1
            raw = row["meta_json"]
            if raw is None:
                n_meta_null += 1
                continue
            try:
                outer = json.loads(raw)
            except Exception as exc:  # noqa: BLE001
                json_failures.append({"role": role, "asset_id": row["asset_id"], "error": repr(exc)})
                continue
            if not isinstance(outer, dict):
                json_failures.append(
                    {"role": role, "asset_id": row["asset_id"], "error": f"outer type {type(outer).__name__}"}
                )
                continue
            n_obj += 1
            if "meta" in outer:
                n_top_meta_key += 1
            else:
                meta_anomalies.append(
                    {"role": role, "asset_id": row["asset_id"], "why": "no top-level 'meta' key",
                     "outer_keys": sorted(outer.keys())}
                )
                continue
            inner = outer["meta"]
            if inner is None:
                n_inner_missing += 1
                continue
            if not isinstance(inner, dict):
                n_inner_missing += 1
                meta_anomalies.append(
                    {"role": role, "asset_id": row["asset_id"], "why": f"inner 'meta' type {type(inner).__name__}"}
                )
                continue
            n_inner_dict += 1
            for k in inner.keys():
                key_counts[k] += 1
            if len(inner_union_sample) < 3:
                inner_union_sample[row["asset_id"]] = sorted(inner.keys())

        entry["meta_rows"] = n_rows
        entry["meta_json_null"] = n_meta_null
        entry["meta_json_object"] = n_obj
        entry["meta_top_key_present"] = n_top_meta_key
        entry["meta_inner_dict"] = n_inner_dict
        entry["meta_inner_not_dict_or_null"] = n_inner_missing
        entry["meta_keys"] = OrderedDict(sorted(key_counts.items(), key=lambda kv: (-kv[1], kv[0])))
        entry["meta_keys_full_rows"] = sorted(k for k, v in key_counts.items() if v == n_rows)
        entry["meta_keys_partial"] = OrderedDict(
            (k, v) for k, v in entry["meta_keys"].items() if v != n_rows
        )
        entry["meta_key_sample"] = inner_union_sample
        entry["meta_top_level_keys_outside_meta"] = OrderedDict()  # filled below

        # top-level keys of meta_json itself (outer object)
        outer_counts: Counter = Counter()
        for row in cur.execute("SELECT meta_json FROM assets WHERE role=?", (role,)):
            if row["meta_json"] is None:
                continue
            try:
                outer = json.loads(row["meta_json"])
            except Exception:  # noqa: BLE001
                continue
            if isinstance(outer, dict):
                for k in outer.keys():
                    outer_counts[k] += 1
        entry["meta_top_level_keys_outside_meta"] = OrderedDict(
            sorted(outer_counts.items(), key=lambda kv: (-kv[1], kv[0]))
        )
        report[role] = entry

    # ---------------------------------------------------------------- text dump
    emit("\n\n=================== PER-ROLE CENSUS ===================")
    for role, e in report.items():
        emit(f"\n--- role={role}  row_count={e['row_count']}")
        for column in ("schema", "unit", "frame", "qa_status", "split"):
            emit(f"    {column:<10}: " + ", ".join(f"{k!r} n={v}" for k, v in e[column].items()))
        emit(
            f"    meta_json: rows={e['meta_rows']} null={e['meta_json_null']} "
            f"object={e['meta_json_object']} has_top_'meta'={e['meta_top_key_present']} "
            f"inner_dict={e['meta_inner_dict']} inner_null/other={e['meta_inner_not_dict_or_null']}"
        )
        emit(f"    meta_keys ({len(e['meta_keys'])} distinct):")
        for k, v in e["meta_keys"].items():
            tag = f"n={v}" + ("  <-- all rows" if v == e["row_count"] else f"  ({v}/{e['row_count']})")
            emit(f"        {k:<34} {tag}")
        emit(f"    meta_json outer keys: " + ", ".join(f"{k} n={v}" for k, v in e["meta_top_level_keys_outside_meta"].items()))

    emit("\n\n=================== ANOMALIES ===================")
    emit(f"  rows where meta_json is not a JSON object / unparsable : {len(json_failures)}")
    for f in json_failures[:50]:
        emit(f"      {f}")
    emit(f"  rows with no top-level 'meta' key or non-dict inner  : {len(meta_anomalies)}")
    for a in meta_anomalies[:50]:
        emit(f"      {a}")

    # ---------------------------------------------------------------- json dump
    payload = {
        "db_path": str(DB),
        "assets_rows_total": total,
        "distinct_roles_in_sqlite": len(roles),
        "roles_in_sqlite": roles,
        "per_role": report,
        "json_failures": json_failures,
        "meta_anomalies": meta_anomalies,
    }
    OUT_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    OUT_TXT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    con.close()
    print(f"wrote {OUT_TXT} ({OUT_TXT.stat().st_size} bytes)")
    print(f"wrote {OUT_JSON} ({OUT_JSON.stat().st_size} bytes)")
    print(f"roles={len(roles)} rows={total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
