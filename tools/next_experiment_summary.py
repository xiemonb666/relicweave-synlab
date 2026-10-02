"""Final census for the next-experiment batch: per-run, per-lineage, per-split, per-axis.

Read-only over ``data/a12/metadata.sqlite`` (asset metadata + the batch ledger).  Every number in
``docs/a12/next_experiment_data.md`` is produced by this script, so any of them can be recomputed:

    .venv\\Scripts\\python.exe tools\\next_experiment_summary.py
"""

from __future__ import annotations

import argparse
import collections
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load_ledger(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="next_experiment_summary")
    parser.add_argument("--root", default="data/a12")
    parser.add_argument("--out", default="data/a12/reports/next_experiment_summary.json")
    args = parser.parse_args(argv)
    root = Path(args.root)
    con = sqlite3.connect(str(root / "metadata.sqlite"))
    con.row_factory = sqlite3.Row

    ledger = load_ledger(ROOT / "data/a12/reports/next_experiment_batches.json")
    attempt_rows = ledger.get("batches", [])
    runs = sorted({r["run_id"] for r in attempt_rows if r.get("run_id")})

    # ---- assets of the batch's runs ------------------------------------------------------
    assets = [dict(r) for r in con.execute(
        "select asset_id, role, qa_status, lineage_id, split, meta_json from assets")]
    by_run: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for row in assets:
        meta = json.loads(row["meta_json"] or "{}")
        run_id = meta.get("run_id")
        if run_id in runs:
            row["meta"] = meta
            by_run[run_id].append(row)

    lineage_run: dict[str, str] = {}
    lineage_roles: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    lineage_meta: dict[str, dict[str, Any]] = {}
    for run_id in runs:
        for row in by_run[run_id]:
            lin = row["lineage_id"]
            if not lin:
                continue
            lineage_run.setdefault(lin, run_id)
            lineage_roles[lin][f'{row["role"]}/{row["qa_status"]}'] += 1
            if row["role"] == "mother_mesh" and lin not in lineage_meta:
                lineage_meta[lin] = {
                    "vessel": row["meta"].get("vessel_id"), "material": row["meta"].get("material_id"),
                    "split": row["split"], "run_id": run_id,
                }

    accepted = sorted(lin for lin, roles in lineage_roles.items()
                      if roles.get("label_bundle/QA_PASS"))
    attempted_lineages = sorted(lineage_roles)
    failed = [lin for lin in attempted_lineages if lin not in accepted]

    per_lineage = {}
    for lin in attempted_lineages:
        meta = lineage_meta.get(lin, {})
        per_lineage[lin] = {
            "run_id": lineage_run.get(lin), "split": meta.get("split"),
            "vessel": meta.get("vessel"), "material": meta.get("material"),
            "accepted": lin in accepted,
            "fragments": lineage_roles[lin].get("fragment_mesh/QA_PASS", 0),
            "roles": dict(lineage_roles[lin]),
        }

    def count(split: str | None = None, key: str | None = None) -> dict[str, int]:
        out: collections.Counter = collections.Counter()
        for lin in accepted:
            entry = per_lineage[lin]
            if split and entry["split"] != split:
                continue
            out[str(entry.get(key or "vessel"))] += 1
        return dict(sorted(out.items()))

    # observation count per accepted lineage comes from the label bundle metadata
    obs_total = 0
    r2_total = 0
    for run_id in runs:
        for row in by_run[run_id]:
            if row["role"] != "label_bundle" or row["qa_status"] != "QA_PASS":
                continue
            obs_total += int(row["meta"].get("relation_count") or 0)
            r2_total += int(row["meta"].get("r2_count") or 0)

    # observation records / view assets of the batch runs
    role_totals: collections.Counter = collections.Counter()
    for run_id in runs:
        for row in by_run[run_id]:
            role_totals[f'{row["role"]}/{row["qa_status"]}'] += 1

    attempts_by_index: dict[int, list[dict[str, Any]]] = collections.defaultdict(list)
    for row in attempt_rows:
        attempts_by_index[int(row["mother_index"])].append(row)
    attempts_total = len(attempt_rows)
    attempts_ok = sum(1 for row in attempt_rows if row.get("ok"))
    seconds_total = sum(float(row.get("seconds") or 0.0) for row in attempt_rows)

    summary = {
        "schema": "synlab.next_experiment.summary.v1",
        "root": str(root),
        "runs": runs,
        "planned_mothers": ledger.get("last_batch", {}).get("planned") or None,
        "attempts": {
            "total": attempts_total, "accepted": attempts_ok,
            "failed": attempts_total - attempts_ok,
            "seconds_total": round(seconds_total, 1),
            "seconds_per_accepted": round(seconds_total / attempts_ok, 1) if attempts_ok else None,
            "distinct_indices_attempted": len(attempts_by_index),
        },
        "lineages": {
            "attempted": len(attempted_lineages),
            "accepted": len(accepted),
            "failed": len(failed),
            "accepted_ids": accepted,
            "failed_ids": failed,
        },
        "per_lineage": per_lineage,
        "coverage_accepted": {
            "vessels": count(key="vessel"),
            "materials": count(key="material"),
            "splits": count(key="split"),
            "n_vessels": len(count(key="vessel")),
            "n_materials": len(count(key="material")),
        },
        "totals": {
            "fragments": sum(per_lineage[l]["fragments"] for l in accepted),
            "relation_count": obs_total,
            "r2_count": r2_total,
            "assets_in_batch_runs": sum(role_totals.values()),
            "roles": dict(sorted(role_totals.items())),
        },
    }
    out_path = ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str),
                        encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items()
                      if k not in ("per_lineage", "lineages")}, ensure_ascii=False, indent=2))
    print("accepted lineages:", len(accepted), "->", out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
