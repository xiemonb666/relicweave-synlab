"""Which batch assets carry which data semantics? (measured, per asset)

The batch teammate is producing data with ``tools/batch_generate.py`` while the mask/damage
semantics change lands, so the store can contain assets of *both* generations.  This probe reads
the store directly and reports, per ``run_id``:

* the run creation time and how many lineages it produced;
* per role/QA-status, whether the asset carries ``damage_semantics`` (physical_result),
  ``data_semantics`` (obs_result) or **no marker at all** -- the last case is exactly how every
  asset produced before the change is identified (docs/a12/data_semantics_versions.md §3).

Usage:
  .venv\\Scripts\\python.exe data/a12/reports/probe_batch_semantics.py --store data/a12
"""

from __future__ import annotations

import argparse
import collections
import json
import sqlite3
from pathlib import Path


def probe(store_root: Path) -> dict:
    db = store_root / "metadata.sqlite"
    ledger_path = store_root / "reports" / "next_experiment_batches.json"
    con = sqlite3.connect(str(db))
    con.row_factory = sqlite3.Row
    runs = {r["run_id"]: dict(r) for r in con.execute(
        "SELECT run_id, status, created_at FROM runs")}
    lineages: dict[str, int] = collections.Counter()
    ok: dict[str, int] = collections.Counter()
    if ledger_path.is_file():
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        for row in ledger.get("batches", []):
            lineages[row["run_id"]] += 1
            ok[row["run_id"]] += 1 if row.get("ok") else 0

    out: dict = {"store": str(store_root), "runs": [], "totals": {}}
    totals: collections.Counter = collections.Counter()
    for row in con.execute("SELECT meta_json, role, qa_status, created_at FROM assets"):
        meta = json.loads(row["meta_json"] or "{}")
        if meta.get("damage_semantics"):
            marker = f"damage_semantics={meta['damage_semantics']}"
        elif (meta.get("meta") or {}).get("data_semantics"):
            inner = meta["meta"]["data_semantics"]
            marker = f"mask_semantics={inner.get('mask_semantics')},damage_semantics={inner.get('damage_semantics')}"
        else:
            marker = "NO_MARKER"
        run_id = str(meta.get("run_id") or "None")
        totals[(row["role"], row["qa_status"], marker)] += 1
        out.setdefault("_per_run", collections.Counter())[
            (run_id, row["role"], row["qa_status"], marker)] += 1
    per_run: collections.Counter = out.pop("_per_run", collections.Counter())
    by_run: dict[str, list] = collections.defaultdict(list)
    for (rid, role, qa_status, marker), count in per_run.items():
        by_run[rid].append({"role": role, "qa_status": qa_status, "marker": marker,
                            "count": count})
    for rid in sorted(by_run, key=lambda r: (runs.get(r, {}).get("created_at") or 0, r)):
        entry = {"run_id": rid, "created_at": runs.get(rid, {}).get("created_at"),
                 "status": runs.get(rid, {}).get("status"),
                 "lineages": lineages.get(rid, 0), "ok_lineages": ok.get(rid, 0),
                 "assets": sorted(by_run[rid],
                                  key=lambda a: (a["role"], a["qa_status"], a["marker"]))}
        out["runs"].append(entry)
    out["totals"] = {f"{k[0]}|{k[1]}|{k[2]}": v for k, v in sorted(totals.items(),
                                                                   key=lambda kv: str(kv[0]))}
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", default="data/a12")
    parser.add_argument("--out", default="data/a12/reports/batch_data_semantics.json")
    args = parser.parse_args()
    report = probe(Path(args.store))
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str),
                      encoding="utf-8")
    for entry in report["runs"]:
        print(f"--- {entry['run_id']} created={entry['created_at']} lineages={entry['lineages']} "
              f"ok={entry['ok_lineages']}")
        for asset in entry["assets"]:
            print(f"      {asset['role']:20s} {asset['qa_status']:11s} "
                  f"{asset['marker']:70s} x{asset['count']}")
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
