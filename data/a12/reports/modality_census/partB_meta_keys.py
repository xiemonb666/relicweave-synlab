"""partB_meta_keys -- READ-ONLY deep dive into meta_json per role.

Answers, with real numbers:
* is meta_json a wrapper around an inner "meta" object?  (per role: how many rows)
* the full, untruncated top-level key union per role with per-key asset counts
* for rows that DO carry a nested "meta" key: what is inside it
* specific value probes: pixel convention, unit declarations inside meta, schema key vs column

Writes partB_meta_keys.txt / partB_meta_keys.json.  Reads metadata.sqlite with mode=ro.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter, OrderedDict
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
DB = REPO / "data" / "a12" / "metadata.sqlite"
OUT_TXT = HERE / "partB_meta_keys.txt"
OUT_JSON = HERE / "partB_meta_keys.json"


def connect(path: Path) -> sqlite3.Connection:
    uri = "file:" + str(path).replace("\\", "/") + "?mode=ro&immutable=1"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


def main() -> int:
    lines: list[str] = []

    def emit(text: str = "") -> None:
        lines.append(text)

    con = connect(DB)
    cur = con.cursor()

    roles = [r["role"] for r in cur.execute(
        "SELECT role, COUNT(*) n FROM assets GROUP BY 1 ORDER BY n DESC, role")]

    out: "OrderedDict[str, dict]" = OrderedDict()
    total_wrapper = 0
    total_rows = 0

    for role in roles:
        rows = list(cur.execute(
            "SELECT asset_id, schema, unit, frame, meta_json FROM assets WHERE role=? ORDER BY asset_id",
            (role,)))
        n = len(rows)
        total_rows += n
        key_counts: Counter = Counter()
        nested_meta_rows: list[str] = []
        nested_meta_keys: Counter = Counter()
        schema_key_values: Counter = Counter()
        unit_like: Counter = Counter()
        nonscalar_keys: Counter = Counter()
        for row in rows:
            meta = json.loads(row["meta_json"])
            for k, v in meta.items():
                key_counts[k] += 1
                if not isinstance(v, (str, int, float, bool)) and v is not None:
                    nonscalar_keys[k] += 1
            if "meta" in meta:
                nested_meta_rows.append(row["asset_id"])
                inner = meta["meta"]
                if isinstance(inner, dict):
                    for k in inner:
                        nested_meta_keys[k] += 1
            if "schema" in meta:
                schema_key_values[str(meta["schema"])] += 1
            if "units" in meta:
                units = meta["units"]
                if isinstance(units, dict):
                    for k, v in units.items():
                        unit_like[f"{k}={v}"] += 1
                else:
                    unit_like[f"units={units}"] += 1
        total_wrapper += len(nested_meta_rows)
        out[role] = {
            "row_count": n,
            "n_rows_with_nested_meta_key": len(nested_meta_rows),
            "nested_meta_asset_ids_sample": nested_meta_rows[:3],
            "nested_meta_inner_keys": OrderedDict(
                sorted(nested_meta_keys.items(), key=lambda kv: (-kv[1], kv[0]))),
            "meta_keys": OrderedDict(sorted(key_counts.items(), key=lambda kv: (-kv[1], kv[0]))),
            "meta_keys_full": sorted(k for k, v in key_counts.items() if v == n),
            "meta_keys_partial": OrderedDict(
                (k, v) for k, v in sorted(key_counts.items(), key=lambda kv: (-kv[1], kv[0]))
                if v != n),
            "nonscalar_key_counts": OrderedDict(
                sorted(nonscalar_keys.items(), key=lambda kv: (-kv[1], kv[0]))),
            "schema_key_values": OrderedDict(sorted(schema_key_values.items())),
            "unit_like_values": OrderedDict(sorted(unit_like.items())),
        }

    emit("=" * 100)
    emit("PART 1 -- is meta_json a wrapper with a top-level 'meta' object?")
    emit("=" * 100)
    emit(f"  assets rows total                                    : {total_rows}")
    emit(f"  rows whose meta_json HAS a top-level 'meta' key      : {total_wrapper}")
    emit(f"  rows whose meta_json has NO top-level 'meta' key     : {total_rows - total_wrapper}")
    emit("")
    emit(f"  {'role':<24} {'rows':>5} {'with meta key':>14}  interpretation")
    for role, e in out.items():
        n_meta = e["n_rows_with_nested_meta_key"]
        if n_meta == 0:
            note = "meta_json IS the role metadata (no wrapper)"
        elif n_meta == e["row_count"]:
            note = "every row has a field literally named 'meta' (a dataclass field, not a wrapper)"
        else:
            note = f"{n_meta}/{e['row_count']} rows carry a field named 'meta'"
        emit(f"  {role:<24} {e['row_count']:>5} {n_meta:>14}  {note}")

    emit("\n" + "=" * 100)
    emit("PART 2 -- full top-level meta_json key union per role (untruncated, with counts)")
    emit("=" * 100)
    for role, e in out.items():
        emit(f"\n### role={role}  rows={e['row_count']}  distinct_keys={len(e['meta_keys'])}")
        if e["meta_keys_full"]:
            emit(f"    keys in ALL {e['row_count']} rows (n={e['row_count']}): "
                 + ", ".join(e["meta_keys_full"]))
        else:
            emit(f"    keys in ALL {e['row_count']} rows: 无 (none)")
        if e["meta_keys_partial"]:
            emit(f"    keys in SOME rows ({len(e['meta_keys_partial'])}):")
            for k, v in e["meta_keys_partial"].items():
                emit(f"        {k:<44} {v}/{e['row_count']}")
        else:
            emit("    keys in SOME rows: 无 (none)")

    emit("\n" + "=" * 100)
    emit("PART 3 -- what is inside the nested 'meta' key where it exists")
    emit("=" * 100)
    for role, e in out.items():
        if e["n_rows_with_nested_meta_key"] == 0:
            continue
        emit(f"\n  role={role}: {e['n_rows_with_nested_meta_key']}/{e['row_count']} rows; "
             f"inner keys={len(e['nested_meta_inner_keys'])}")
        for k, v in e["nested_meta_inner_keys"].items():
            emit(f"      {k:<40} {v}/{e['n_rows_with_nested_meta_key']}")
        emit(f"      sample asset ids: {e['nested_meta_asset_ids_sample']}")

    emit("\n" + "=" * 100)
    emit("PART 4 -- meta['schema'] vs the assets.schema column, and meta['units'] probes")
    emit("=" * 100)
    for role, e in out.items():
        if e["schema_key_values"]:
            emit(f"  {role:<24} meta['schema'] values: {dict(e['schema_key_values'])}")
    emit("")
    for role, e in out.items():
        if e["unit_like_values"]:
            emit(f"  {role:<24} meta['units'] content: {dict(list(e['unit_like_values'].items())[:12])}")

    emit("\n" + "=" * 100)
    emit("PART 5 -- pixel-convention style values (FRAME_PIXEL='pixel_cv_center' probe)")
    emit("=" * 100)
    for key in ("pixel_convention", "colmap_pixel_convention"):
        rows = list(cur.execute(
            "SELECT role, COUNT(*) n FROM assets WHERE json_extract(meta_json, '$.' || ?) IS NOT NULL "
            "GROUP BY 1 ORDER BY n DESC", (key,)))
        emit(f"  meta_json['{key}'] present in: " + (", ".join(f"{r['role']} n={r['n']}" for r in rows) or "无 (none)"))
        for r in cur.execute(
                "SELECT DISTINCT json_extract(meta_json, '$.' || ?) v FROM assets "
                "WHERE json_extract(meta_json, '$.' || ?) IS NOT NULL", (key, key)):
            emit(f"        value={r['v']!r}")
    frames = [r["frame"] for r in cur.execute("SELECT DISTINCT frame FROM assets ORDER BY 1")]
    emit(f"  DISTINCT frame column values in sqlite: {frames}")
    for probe in ("C_mm", "pixel_cv_center", "NA", "S_mm", "W_mm", "F_mm", "none"):
        n = cur.execute("SELECT COUNT(*) FROM assets WHERE frame=?", (probe,)).fetchone()[0]
        emit(f"        frame={probe!r:<18} rows={n}")

    emit("\n" + "=" * 100)
    emit("PART 6 -- data_semantics / run_id presence per role")
    emit("=" * 100)
    for role, e in out.items():
        ds = e["meta_keys"].get("data_semantics", 0)
        rid = e["meta_keys"].get("run_id", 0)
        emit(f"  {role:<24} data_semantics {ds}/{e['row_count']:<4} run_id {rid}/{e['row_count']}")

    OUT_JSON.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    OUT_TXT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    con.close()
    print(f"wrote {OUT_TXT} ({OUT_TXT.stat().st_size} bytes)")
    print(f"wrote {OUT_JSON} ({OUT_JSON.stat().st_size} bytes)")
    print(f"rows={total_rows} rows_with_top_level_meta_key={total_wrapper}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
