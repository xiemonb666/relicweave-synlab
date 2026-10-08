"""Per-vessel functional survey of the synthesis chain (A12 next-experiment config).

Why this file exists
--------------------
``tools/batch_generate.py`` records a lineage outcome as an error *code* and a one-line
message.  That is enough to count failures but not enough to fix them: the real cause of an
``UNEXPECTED`` outcome lives in the traceback, which ``build_one_mother`` returns in the
outcome but the batch ledger does not persist.

What it does
------------
Runs the *same* deterministic plan (``plan_generation``) against a chosen store root, one
lineage at a time, and writes one row per lineage with the honest, measured outcome:

* ``ok`` and the full ``error`` dict (code, stage, message **and traceback**),
* fragment / observation / r2 counts and per-stage wall clock,
* the vessel, material, pattern, layer plan of the lineage.

By default it surveys the **first planned lineage of every registered vessel** (24 rows, the
"one lineage per vessel" functional census).  ``--indices`` restricts it to specific mother
indices and ``--force`` re-runs a lineage that is already recorded.  The output JSON is
rewritten after *every* lineage, so a killed process loses at most the lineage in flight.

Nothing is fabricated and nothing is retried silently: a row always reports what the chain
really returned.

Usage::

    python data/a12/reports/synthesis_functional_survey.py --root data/a12_smoke
    python data/a12/reports/synthesis_functional_survey.py --root data/a12_smoke --indices 0,3
    python data/a12/reports/synthesis_functional_survey.py --root data/a12_smoke --vessels V23
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synlab.config import load_generation_spec  # noqa: E402
from synlab.pipeline import build_one_mother, plan_generation  # noqa: E402
from synlab.registry import load_all  # noqa: E402
from synlab.storage.store import AssetStore  # noqa: E402

SCHEMA = "synlab.a12.synthesis_functional_survey.v1"
DEFAULT_CONFIG = "configs/a12/next_experiment.yaml"
DEFAULT_OUT = "data/a12/reports/synthesis_functional_survey.json"


def _load(path: Path) -> dict[str, Any]:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    return {"schema": SCHEMA, "lineages": [], "runs": []}


def _save(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.part")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def _pioneers(plan: Any) -> list[Any]:
    """First planned lineage of every vessel, in vessel order."""
    first: dict[str, Any] = {}
    for lineage in plan.lineages:
        first.setdefault(lineage.vessel_id, lineage)
    return [first[vessel] for vessel in sorted(first)]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="synthesis_functional_survey")
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--root", default="data/a12_smoke")
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--indices", default=None, help="comma-separated mother indices")
    parser.add_argument("--vessels", default=None, help="comma-separated vessel ids")
    parser.add_argument("--force", action="store_true",
                        help="re-run lineages that already have a recorded outcome")
    parser.add_argument("--label", default=None,
                        help="tag written into the run record (e.g. 'after-fix')")
    args = parser.parse_args(argv)

    load_all()
    spec = load_generation_spec(args.config)
    plan = plan_generation(spec)
    store = AssetStore(Path(args.root))
    out_path = Path(args.out)
    doc = _load(out_path)

    if args.indices:
        wanted = {int(x) for x in args.indices.split(",") if x.strip()}
        selected = [l for l in plan.lineages if l.mother_index in wanted]
    elif args.vessels:
        wanted_v = {v.strip() for v in args.vessels.split(",") if v.strip()}
        selected = [l for l in _pioneers(plan) if l.vessel_id in wanted_v]
    else:
        selected = _pioneers(plan)

    recorded = {row["lineage_id"]: row for row in doc["lineages"]}
    if not args.force:
        selected = [l for l in selected
                    if not (recorded.get(l.lineage_id) or {}).get("ok")]
    if not selected:
        print("nothing to survey; every selected lineage already has a recorded ok outcome")
        return 0

    run_id = "run_" + time.strftime("%Y%m%dT%H%M%S", time.localtime())
    store.create_run(run_id, plan.spec_hash, scope=spec.data_scope.value,
                     profile=spec.release_profile.value,
                     meta={"plan": plan.as_dict(),
                           "driver": "data/a12/reports/synthesis_functional_survey.py",
                           "label": args.label or ""})
    doc["runs"].append({"run_id": run_id, "label": args.label or "",
                        "at": time.time(), "config": args.config, "root": args.root,
                        "indices": [l.mother_index for l in selected]})

    for lineage in selected:
        print(f"... {lineage.lineage_id}", flush=True)
        started = time.time()
        outcome = build_one_mother(plan, lineage, store, run_id=run_id)
        seconds = time.time() - started
        row_coverage = outcome["coverage_row"]
        error = outcome.get("error") or {}
        row = {
            "lineage_id": lineage.lineage_id,
            "mother_index": lineage.mother_index,
            "vessel_id": lineage.vessel_id,
            "material_id": lineage.material_id,
            "pattern_id": lineage.pattern_id,
            "layer_combo_id": lineage.layer_combo_id,
            "split": lineage.split,
            "ok": bool(outcome["ok"]),
            "seconds": round(seconds, 3),
            "fragments": row_coverage.get("fragments"),
            "observations": row_coverage.get("observations"),
            "r2_pairs": row_coverage.get("r2_pairs"),
            "error_code": error.get("code"),
            "error_stage": error.get("stage"),
            "error_message": error.get("message"),
            "traceback": error.get("traceback"),
            "quarantine_reason": row_coverage.get("quarantine_reason"),
            "stages": row_coverage.get("stages") or {},
            "obs_endpoint_failures": row_coverage.get("obs_endpoint_failures") or {},
            "physical_audit_status": row_coverage.get("physical_audit_status"),
            "run_id": run_id,
            "surveyed_at": time.time(),
        }
        doc["lineages"] = [r for r in doc["lineages"] if r["lineage_id"] != lineage.lineage_id]
        doc["lineages"].append(row)
        doc["lineages"].sort(key=lambda r: (r["vessel_id"], r["mother_index"]))
        _save(out_path, doc)
        print(f"[{lineage.vessel_id}] {lineage.lineage_id} "
              f"{'OK' if row['ok'] else 'FAIL ' + str(row['error_code'])} "
              f"frag={row['fragments']} obs={row['observations']} r2={row['r2_pairs']} "
              f"{seconds:.1f}s" + (f" :: {str(row['error_message'])[:160]}"
                                   if not row["ok"] else ""), flush=True)

    ok = sum(1 for r in doc["lineages"] if r["ok"])
    print(json.dumps({"surveyed": len(doc["lineages"]), "ok": ok,
                      "failed": len(doc["lineages"]) - ok}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
