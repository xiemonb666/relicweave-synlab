"""Batch driver for the A12 *trainable* store.

Why this exists on top of ``tools/batch_generate.py``
-----------------------------------------------------
``batch_generate.py`` executes ``pending[:batch]`` in **plan order**, and a lineage that fails
stays pending forever (it is only "done" when it is accepted).  On this build several mothers fail
deterministically at the fracture stage (``FRACTURE_CONSERVATION_FAIL``), so plan-order batching
would re-attempt the same broken prefix on every invocation and never reach a new mother.

This driver therefore walks the plan **once per mother**: each invocation is handed, through the
documented ``--only`` flag, the next ``k`` mother indices that have never been attempted before.
Consequences, all of them honest:

* the attempted denominator is one attempt per mother -- a deterministic failure is counted once,
  not inflated into "retried 20 times";
* a mother that fails is *not* claimed as accepted, and it stays pending in the store;
* a process killed by the host costs at most the mothers of that one invocation, because
  ``batch_generate.py`` writes one ledger row per mother and the store commit is per asset.

Every number reported here is read back out of the store and out of
``<root>/reports/next_experiment_batches.json``; nothing is carried in memory across invocations.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

CONFIG_SHA256 = "8186653101612cbc20e9eeba3f60ffbc241e3d1e3ebd690fdecb60746ab1fb16"
DRIVER_SCHEMA = "synlab.a12.trainable.batch_driver.v1"


def _store_state(root: Path) -> dict[str, dict]:
    from synlab.storage.store import QA_PASS, AssetStore

    store = AssetStore(root)
    state: dict[str, dict] = {}
    for asset in store.list_assets(limit=500000):
        lineage = getattr(asset, "lineage_id", None)
        if not lineage:
            continue
        entry = state.setdefault(lineage, {"assets": 0, "accepted": False,
                                           "obs_semantics": set(), "r2_meta": 0})
        entry["assets"] += 1
        if asset.role == "label_bundle" and asset.qa_status == QA_PASS:
            entry["accepted"] = True
        meta = asset.meta or {}
        if meta.get("obs_semantics"):
            entry["obs_semantics"].add(str(meta["obs_semantics"]))
        if asset.role == "label_bundle":
            entry["r2_meta"] += int(meta.get("r2_count") or 0)
    for entry in state.values():
        entry["obs_semantics"] = sorted(entry["obs_semantics"])
    return state


def _plan_lineages(config: str):
    from synlab.config import load_generation_spec
    from synlab.pipeline import plan_generation
    from synlab.registry import load_all

    load_all()
    return plan_generation(load_generation_spec(config)).lineages


def _dir_bytes(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                pass
    return total


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="batch_driver")
    parser.add_argument("--config", default="configs/a12/next_experiment.yaml")
    parser.add_argument("--root", default="data/a12_trainable/store")
    parser.add_argument("--ledger", default=None)
    parser.add_argument("--out", default="data/a12_trainable/reports/batch_driver.json")
    parser.add_argument("--batch", type=int, default=3)
    parser.add_argument("--target-accepted", type=int, default=10)
    parser.add_argument("--max-invocations", type=int, default=60)
    parser.add_argument("--logs", default="data/a12_trainable/logs")
    parser.add_argument("--retry-indices", default="",
                        help="mother indices allowed ONE extra attempt.  Used for a mother whose "
                             "recorded failure was a code defect that has since been fixed (e.g. "
                             "the NameError from the in-flight observation fix), never for a "
                             "deterministic data failure.")
    args = parser.parse_args(argv)
    retry_extra = {int(x) for x in str(args.retry_indices).split(",") if x.strip()}

    root = Path(args.root)
    ledger_path = Path(args.ledger) if args.ledger else root / "reports" / "next_experiment_batches.json"
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    logs = Path(args.logs)
    logs.mkdir(parents=True, exist_ok=True)

    lineages = _plan_lineages(args.config)
    by_index = {int(l.mother_index): l for l in lineages}

    def attempts_per_index() -> dict[int, int]:
        if not ledger_path.exists():
            return {}
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        counts: dict[int, int] = {}
        for row in ledger.get("batches", []):
            if row.get("mother_index") is None:
                continue
            index = int(row["mother_index"])
            counts[index] = counts.get(index, 0) + 1
        return counts

    def attempted_indices() -> set[int]:
        return set(attempts_per_index())

    report = {"schema": DRIVER_SCHEMA, "config": args.config, "config_sha256": CONFIG_SHA256,
              "store": str(root), "ledger": str(ledger_path),
              "target_accepted": int(args.target_accepted), "invocations": [],
              "started_at": time.time()}
    state_before = _store_state(root)
    report["accepted_before"] = sorted(l for l, e in state_before.items() if e["accepted"])
    bytes_before_all = _dir_bytes(root)

    for invocation in range(1, int(args.max_invocations) + 1):
        state = _store_state(root)
        accepted = sorted(l for l, e in state.items() if e["accepted"])
        if len(accepted) >= int(args.target_accepted):
            report["stop_reason"] = f"target_accepted_reached({len(accepted)})"
            break
        attempts = attempts_per_index()
        accepted_set = set(accepted)
        remaining = []
        for index in sorted(by_index):
            if by_index[index].lineage_id in accepted_set:
                continue
            allowance = 2 if index in retry_extra else 1
            if attempts.get(index, 0) < allowance:
                remaining.append(index)
        if not remaining:
            report["stop_reason"] = "plan_exhausted"
            break
        pick = remaining[: max(1, int(args.batch))]
        only = ",".join(str(i) for i in pick)
        cmd = [sys.executable, str(REPO / "tools" / "batch_generate.py"),
               "--config", args.config, "--root", str(root), "--ledger", str(ledger_path),
               "--batch", str(len(pick)), "--resume",
               "--expect-config-sha256", CONFIG_SHA256, "--only", only]
        log_path = logs / f"batch_inv{invocation:02d}_m{only.replace(',', '-')}.log"
        t0 = time.time()
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO),
                              encoding="utf-8", errors="replace")
        seconds = round(time.time() - t0, 3)
        log_path.write_text((proc.stdout or "") + "\n--- stderr ---\n" + (proc.stderr or ""),
                            encoding="utf-8")
        state_after = _store_state(root)
        accepted_after = sorted(l for l, e in state_after.items() if e["accepted"])
        ledger = json.loads(ledger_path.read_text(encoding="utf-8")) if ledger_path.exists() else {}
        rows = [r for r in ledger.get("batches", [])
                if int(r.get("mother_index", -1)) in set(pick)]
        entry = {
            "invocation": invocation,
            "mother_indices": pick,
            "lineage_ids": [by_index[i].lineage_id for i in pick],
            "splits": [by_index[i].split for i in pick],
            "process_exit_code": proc.returncode,
            "returncode_interrupted_or_killed": proc.returncode not in (0, 1),
            "wall_seconds": seconds,
            "rows": [{"lineage_id": r.get("lineage_id"), "mother_index": r.get("mother_index"),
                      "ok": bool(r.get("ok")), "seconds": r.get("seconds"),
                      "fragments": r.get("fragments"), "observations": r.get("observations"),
                      "r2_pairs": r.get("r2_pairs"), "error": r.get("error"),
                      "error_message": (str(r.get("error_message"))[:300]
                                        if r.get("error_message") else None)}
                     for r in rows],
            "attempted": len(pick),
            "accepted_in_this_invocation": sum(1 for r in rows if r.get("ok")),
            "failed_in_this_invocation": sum(1 for r in rows if not r.get("ok")),
            "accepted_total_after": len(accepted_after),
            "store_obs_semantics_histogram": _semantics_histogram(state_after),
            "log": str(log_path),
        }
        report["invocations"].append(entry)
        report["accepted_after"] = accepted_after
        report["stop_reason"] = "max_invocations_reached"
        report["disk_bytes_total_after"] = _dir_bytes(root)
        report["disk_delta_bytes_total"] = report["disk_bytes_total_after"] - bytes_before_all
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str),
                            encoding="utf-8")
        print(json.dumps({k: v for k, v in entry.items() if k != "rows"}, ensure_ascii=False),
              flush=True)

    final = _store_state(root)
    report["accepted_final"] = sorted(l for l, e in final.items() if e["accepted"])
    report["accepted_final_count"] = len(report["accepted_final"])
    report["finished_at"] = time.time()
    report["store_obs_semantics_histogram_final"] = _semantics_histogram(final)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str),
                        encoding="utf-8")
    print("FINAL accepted =", report["accepted_final_count"], "->", out_path)
    return 0 if report["accepted_final_count"] >= int(args.target_accepted) else 1


def _semantics_histogram(state: dict[str, dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for entry in state.values():
        key = ",".join(entry.get("obs_semantics") or []) or "<none>"
        out[key] = out.get(key, 0) + 1
    return out


if __name__ == "__main__":
    raise SystemExit(main())
