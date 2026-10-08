"""Bounded, resumable batch driver for ``synlab`` generation (A12 next-experiment).

Why this file exists
--------------------
``synlab.cli generate`` plans ``dataset.target_mothers`` lineages and then builds *all* of them
in one process.  Two properties of this host make that unusable for a real batch: long heavy
Python processes are killed without a traceback (exit ``-1``/``1``), and the sequential chain of
one mother is already ~1.5 min at the delivered observation settings.  A single ``generate``
call for a few dozen mothers therefore never finishes.

What it does instead
--------------------
1. It builds the *same* deterministic plan ``run_generation`` would build
   (:func:`synlab.pipeline.plan_generation`) with ``target_mothers`` taken from the config.
   Plan derivation depends only on ``master_seed``, the vessel/material/pattern/layer lists and
   the target count -- never on how many mothers have already run -- so batching cannot shift
   any lineage: mother *i* is the same mother in every batch, in any order.
2. It asks the store which of those lineage ids are already committed (``--status`` does this
   without running anything) and skips them.
3. It runs at most ``--batch`` pending lineages, writing one coverage row to
   ``<root>/reports/next_experiment_batches.json`` after *every* mother, so a killed process
   loses at most the mother in flight and the ledger still says which one that was.
4. Failures are recorded in the honest denominator (planned/attempted/accepted/failed) and are
   never retried silently: a lineage is only "done" when it is accepted, otherwise it stays in
   the pending set and the same command retries it on the next invocation.

Everything is measured; nothing is fabricated.  ``--status``, ``--dry-run`` and the batch
ledger come from the store and from real per-mother outcomes.

Usage::

    python tools/batch_generate.py --config configs/a12/next_experiment.yaml --status
    python tools/batch_generate.py --config configs/a12/next_experiment.yaml --batch 6 --resume
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synlab.config import load_generation_spec  # noqa: E402
from synlab.errors import SynLabError  # noqa: E402
from synlab.pipeline import build_one_mother, plan_generation  # noqa: E402
from synlab.registry import load_all  # noqa: E402
from synlab.storage.store import QA_PASS, AssetStore  # noqa: E402

LEDGER_SCHEMA = "synlab.next_experiment.batches.v1"
#: Roles whose presence proves a lineage was carried all the way to a committed asset.
ACCEPT_ROLE = "label_bundle"


def _dir_bytes(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                pass
    return total


def _lineage_state(store: AssetStore, lineage_ids: Sequence[str]) -> dict[str, dict[str, Any]]:
    """Which lineages already have committed assets, and with which QA status."""
    wanted = set(lineage_ids)
    state: dict[str, dict[str, Any]] = {
        lid: {"assets": 0, "accept_role": 0, "roles": {}} for lid in lineage_ids
    }
    for asset in store.list_assets(limit=500000):
        lineage = getattr(asset, "lineage_id", None)
        if lineage not in wanted:
            continue
        entry = state[lineage]
        entry["assets"] += 1
        entry["roles"][asset.role] = entry["roles"].get(asset.role, 0) + 1
        if asset.role == ACCEPT_ROLE and asset.qa_status == QA_PASS:
            entry["accept_role"] += 1
    for entry in state.values():
        entry["accepted"] = entry["accept_role"] > 0
    return state


def _load_ledger(path: Path) -> dict[str, Any]:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    return {"schema": LEDGER_SCHEMA, "batches": [], "lineages": {}}


def _save_ledger(path: Path, ledger: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.part")
    tmp.write_text(json.dumps(ledger, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def _ledger_path(root: Path, override: str | None) -> Path:
    return Path(override) if override else root / "reports" / "next_experiment_batches.json"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="batch_generate",
                                     description="Bounded, resumable synlab generation driver.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--root", default="data/a12")
    parser.add_argument("--batch", type=int, default=4,
                        help="maximum mothers to build in this invocation")
    parser.add_argument("--status", action="store_true", help="report plan/store state and exit")
    parser.add_argument("--dry-run", action="store_true", help="plan only, build nothing")
    parser.add_argument("--resume", action="store_true",
                        help="accepted lineages from the store and the ledger are skipped")
    parser.add_argument("--only", default=None,
                        help="comma-separated mother indices to restrict this invocation to")
    parser.add_argument("--ledger", default=None, help="batch ledger path override")
    parser.add_argument("--expect-config-sha256", default=None,
                        help="abort unless the config file hashes to this value; the plan is "
                             "derived from the file's content, so a silent edit drifts it")
    args = parser.parse_args(argv)

    root = Path(args.root)
    store = AssetStore(root)
    from synlab.canonical import hash_file

    config_hash = hash_file(args.config)
    if args.expect_config_sha256:
        expected = args.expect_config_sha256.strip()
        if not expected.startswith("sha256:"):
            expected = "sha256:" + expected
        if config_hash != expected:
            raise SystemExit(f"config hash mismatch: {config_hash} != {expected}; the plan would "
                             f"drift, refusing to run")
    load_all()
    spec = load_generation_spec(args.config)
    plan = plan_generation(spec)
    lineage_ids = [l.lineage_id for l in plan.lineages]

    ledger_file = _ledger_path(root, args.ledger)
    ledger = _load_ledger(ledger_file)
    state = _lineage_state(store, lineage_ids)

    accepted_before = [lid for lid in lineage_ids if state[lid]["accepted"]]
    pending = [l for l in plan.lineages if not state[l.lineage_id]["accepted"]]
    if args.only:
        wanted = {int(x) for x in args.only.split(",") if x.strip()}
        pending = [l for l in pending if l.mother_index in wanted]

    per_split_plan: dict[str, int] = {}
    for lineage in plan.lineages:
        per_split_plan[lineage.split] = per_split_plan.get(lineage.split, 0) + 1

    summary = {
        "config": args.config,
        "config_hash": config_hash,
        "spec_hash": plan.spec_hash,
        "job_id": plan.job_id,
        "planned": len(plan.lineages),
        "per_split_planned": per_split_plan,
        "accepted_in_store": len(accepted_before),
        "pending": len(pending),
        "vessels_planned": sorted({l.vessel_id for l in plan.lineages}),
        "materials_planned": sorted({l.material_id for l in plan.lineages}),
        "patterns_planned": sorted({l.pattern_id for l in plan.lineages}),
        "layer_combos_planned": sorted({l.layer_combo_id for l in plan.lineages if l.layer_combo_id}),
        "fracture_backend": spec.fracture.backend,
        "ledger": str(ledger_file),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.status or args.dry_run:
        return 0

    batch = pending[: max(0, int(args.batch))]
    if not batch:
        print("nothing pending; every planned lineage is already accepted in the store")
        return 0

    bytes_before = _dir_bytes(root)
    run_id = f"run_{plan.job_id.split('_', 1)[-1][:16]}"
    store.create_run(run_id, plan.spec_hash, scope=spec.data_scope.value,
                     profile=spec.release_profile.value,
                     meta={"plan": plan.as_dict(), "spec": plan.compiled.expanded,
                           "batch_driver": "tools/batch_generate.py"})
    started = time.time()
    rows: list[dict[str, Any]] = []
    accepted = 0
    attempted = 0
    for lineage in batch:
        attempted += 1
        t0 = time.time()
        outcome = build_one_mother(plan, lineage, store, run_id=run_id)
        seconds = time.time() - t0
        row = {
            "lineage_id": lineage.lineage_id,
            "mother_index": lineage.mother_index,
            "split": lineage.split,
            "vessel_id": lineage.vessel_id,
            "material_id": lineage.material_id,
            "pattern_id": lineage.pattern_id,
            "layer_combo_id": lineage.layer_combo_id,
            "ok": bool(outcome["ok"]),
            "seconds": round(seconds, 3),
            "fragments": outcome["coverage_row"].get("fragments"),
            "observations": outcome["coverage_row"].get("observations"),
            "r2_pairs": outcome["coverage_row"].get("r2_pairs"),
            "error": (outcome.get("error") or {}).get("code") if not outcome["ok"] else None,
            "error_message": (outcome.get("error") or {}).get("message") if not outcome["ok"] else None,
            "stages": outcome["coverage_row"].get("stages") or {},
        }
        if outcome["ok"]:
            accepted += 1
        rows.append(row)
        ledger["batches"].append({"at": time.time(), "run_id": run_id, **row})
        ledger["lineages"][lineage.lineage_id] = {
            "accepted": bool(outcome["ok"]), "split": lineage.split,
            "vessel_id": lineage.vessel_id, "material_id": lineage.material_id,
            "pattern_id": lineage.pattern_id, "layer_combo_id": lineage.layer_combo_id,
            "fragments": row["fragments"], "observations": row["observations"],
            "r2_pairs": row["r2_pairs"], "seconds": row["seconds"],
            "updated_at": time.time(),
        }
        _save_ledger(ledger_file, ledger)
        print(f"[{attempted}/{len(batch)}] {lineage.lineage_id} "
              f"{'OK' if outcome['ok'] else 'FAILED ' + str(row['error'])} "
              f"frag={row['fragments']} obs={row['observations']} r2={row['r2_pairs']} "
              f"{seconds:.1f}s", flush=True)

    seconds_total = time.time() - started
    bytes_after = _dir_bytes(root)
    result = {
        "run_id": run_id,
        "batch": len(batch),
        "attempted": attempted,
        "accepted": accepted,
        "failed": attempted - accepted,
        "seconds": round(seconds_total, 3),
        "seconds_per_accepted_mother": round(seconds_total / accepted, 3) if accepted else None,
        "disk_delta_bytes": bytes_after - bytes_before,
        "disk_delta_mb": round((bytes_after - bytes_before) / 1e6, 1),
        "store_bytes": bytes_after,
        "rows": rows,
    }
    ledger["last_batch"] = result
    _save_ledger(ledger_file, ledger)
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, ensure_ascii=False, indent=2))
    return 0 if accepted == attempted else 1


if __name__ == "__main__":
    raise SystemExit(main())
