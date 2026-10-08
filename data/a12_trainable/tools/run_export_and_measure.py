"""Freeze -> export -> probe -> real training batch, over the trainable store.

Every step is the documented one, run through the documented entry point:

1. ``tools/next_experiment_export.py --step freeze``            (release freeze of the batch)
2. ``tools/next_experiment_export.py --step export_training_package --allow-unverified``
3. ``synlab.qc.loader_probe.probe_training_package(out_path=None)``  -- the package's own loader
   verdict.  ``out_path=None`` on purpose: the probe's own ``json.dumps`` of the full report raises
   ``MemoryError`` on this package size *after* the probe has done its work, which loses the
   verdict (this is the same reason ``tools/loader_probe_run.py`` exists).
4. ``python -m synlab.training.smoke``  -- builds a real ``TrainingBatch`` out of the exported
   package and runs real forward/backward/optimizer steps, reporting each task's loss or its
   honest skip reason.

The six numbers this writes are read out of step 4's report (``qc.loader_probe`` and
``training.smoke`` compute them from the package bytes, never from a declaration here):

    n_queries, positives, negatives, effective_queries, encodable_pairs, unencodable_pairs
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SCHEMA = "synlab.a12.trainable.package_measurement.v1"
TASKS = ("view", "rank", "correspondence", "quality", "contradiction")


def _run(cmd: list[str], log: Path) -> tuple[int, float]:
    started = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO),
                          encoding="utf-8", errors="replace")
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(f"CMD: {' '.join(cmd)}\nEXIT: {proc.returncode}\n--- stdout ---\n"
                   + (proc.stdout or "") + "\n--- stderr ---\n" + (proc.stderr or ""),
                   encoding="utf-8")
    return proc.returncode, round(time.time() - started, 3)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="run_export_and_measure")
    parser.add_argument("--store", default="data/a12_trainable/store")
    parser.add_argument("--ledger",
                        default="data/a12_trainable/store/reports/next_experiment_batches.json")
    parser.add_argument("--out", default="data/a12_exports/trainable/next_experiment")
    parser.add_argument("--measure-out", default="data/a12_trainable/reports/smoke")
    parser.add_argument("--report", default="data/a12_trainable/reports/package_measurement.json")
    parser.add_argument("--logs", default="data/a12_trainable/logs")
    parser.add_argument("--steps", type=int, default=3)
    parser.add_argument("--token-budget", type=int, default=256)
    parser.add_argument("--evidence", default="data/a12")
    args = parser.parse_args(argv)

    out_dir = Path(args.out)
    logs = Path(args.logs)
    package_dir = out_dir / "training_package"
    report: dict = {"schema": SCHEMA, "store": args.store, "ledger": args.ledger,
                    "out": str(out_dir), "steps_requested": int(args.steps),
                    "started_at": time.time()}

    common = ["--store", args.store, "--out", str(out_dir), "--ledger", args.ledger,
              "--evidence", args.evidence]

    rc, secs = _run([sys.executable, str(REPO / "tools" / "next_experiment_export.py"),
                     "--step", "freeze", *common], logs / "export_freeze.log")
    report["freeze"] = {"exit_code": rc, "seconds": secs}
    state_path = out_dir / "next_experiment_export_state.json"
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        freeze = state.get("freeze") or {}
        report["freeze"].update({
            "status": freeze.get("status"), "frozen": freeze.get("frozen"),
            "release_id": freeze.get("release_id") or state.get("release_id"),
            "assets": freeze.get("assets"), "assets_by_role": freeze.get("assets_by_role"),
            "coverage": freeze.get("coverage"), "error": freeze.get("error")})

    release = report["freeze"].get("release_id")
    rc, secs = _run([sys.executable, str(REPO / "tools" / "next_experiment_export.py"),
                     "--step", "export_training_package", "--allow-unverified", *common],
                    logs / "export_package.log")
    report["export"] = {"exit_code": rc, "seconds": secs}
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        export = state.get("export_training_package") or {}
        report["export"].update({
            "status": export.get("status"), "frozen": export.get("frozen"),
            "package_dir": export.get("package_dir"), "counts": export.get("counts"),
            "relation_kinds": export.get("relation_kinds"), "views": export.get("views"),
            "reference_closure": export.get("reference_closure"),
            "error": export.get("error")})
    report["release_id_used"] = release

    probe = {"ran": False}
    if (package_dir / "export_manifest.json").exists():
        code = (
            "import json,sys; sys.path.insert(0, r'{repo}');"
            "from synlab.qc.loader_probe import probe_training_package;"
            "r = probe_training_package(r'{pkg}', out_path=None);"
            "out = {{'ok': r.get('ok'), 'status': r.get('status'),"
            " 'files_ok': r.get('files_ok'), 'files_checked': r.get('files_checked'),"
            " 'counts': r.get('counts'), 'relation_pool': r.get('relation_pool'),"
            " 'batch_rows': r.get('batch_rows'),"
            " 'batch': {{k: v for k, v in (r.get('batch') or {{}}).items()"
            "            if k not in ('shapes', 'exposure')}},"
            " 'exposure': (r.get('batch') or {{}}).get('exposure'),"
            " 'real_denominator': r.get('real_denominator'),"
            " 'negative_audit': r.get('negative_audit'), 'degenerate': r.get('degenerate'),"
            " 'error': r.get('error'),"
            " 'attempts': [{{'name': a.get('name'), 'ok': a.get('ok'),"
            "               'error': str(a.get('error'))[:300]}} for a in r.get('attempts', [])]}};"
            "print('@@JSON@@' + json.dumps(out, ensure_ascii=False, default=str))"
        ).format(repo=str(REPO), pkg=str(package_dir))
        probe_log = logs / "package_probe.log"
        started = time.time()
        proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                              cwd=str(REPO), encoding="utf-8", errors="replace")
        probe_log.write_text((proc.stdout or "") + "\n--- stderr ---\n" + (proc.stderr or ""),
                            encoding="utf-8")
        payload = {}
        for line in (proc.stdout or "").splitlines():
            if line.startswith("@@JSON@@"):
                payload = json.loads(line[len("@@JSON@@"):])
        probe = {"ran": True, "exit_code": proc.returncode,
                 "seconds": round(time.time() - started, 3), **payload}
    report["loader_probe"] = probe

    smoke = {"ran": False}
    if (package_dir / "export_manifest.json").exists():
        measure_out = Path(args.measure_out)
        rc, secs = _run([sys.executable, "-m", "synlab.training.smoke",
                         "--package", str(package_dir), "--steps", str(args.steps),
                         "--token-budget", str(args.token_budget),
                         "--out", str(measure_out), "--no-loader-probe"],
                        logs / "smoke.log")
        smoke = {"ran": True, "exit_code": rc, "seconds": secs}
        smoke_path = measure_out / "training_smoke.json"
        if smoke_path.exists():
            payload = json.loads(smoke_path.read_text(encoding="utf-8"))
            batch = payload.get("batch") or {}
            records = ((payload.get("steps") or {}).get("records")) or []
            first = records[0] if records else {}
            smoke.update({
                "status": payload.get("status"), "ok": payload.get("ok"),
                "package": {k: v for k, v in (payload.get("package") or {}).items()
                            if k in ("files_verified", "files_checked", "relation_rows",
                                     "relation_kind_histogram", "query_rows",
                                     "queries_with_observation", "label_layers")},
                "six_counts": {
                    "n_queries": batch.get("n_queries"),
                    "positives": batch.get("positives"),
                    "negatives": batch.get("negatives"),
                    "effective_queries": batch.get("effective_queries"),
                    "encodable_pairs": first.get("encodable_pairs"),
                    "unencodable_pairs": first.get("unencodable_pairs")},
                "batch_more": {k: batch.get(k) for k in
                               ("n_candidates", "excluded", "queries_with_positive",
                                "queries_with_legal_negative", "unconfirmed_candidates")},
                "negative_audit": payload.get("negative_audit"),
                "per_task_first_step": {name: (first.get("tasks") or {}).get(name)
                                        for name in TASKS},
                "per_task_all_steps": [
                    {"step": i, "loss": r.get("loss"), "grad_norm": r.get("grad_norm"),
                     "effective_queries": r.get("effective_queries"),
                     "encodable_pairs": r.get("encodable_pairs"),
                     "unencodable_pairs": r.get("unencodable_pairs"),
                     "tasks": {name: {"skipped": (r.get("tasks") or {}).get(name, {}).get("skipped"),
                                      "loss": (r.get("tasks") or {}).get(name, {}).get("loss"),
                                      "n_valid": (r.get("tasks") or {}).get(name, {}).get("n_valid"),
                                      "reason": (r.get("tasks") or {}).get(name, {}).get("reason")}
                               for name in TASKS}}
                    for i, r in enumerate(records)],
                "loss_sequence": ((payload.get("steps") or {}).get("loss_sequence")),
                "checks": payload.get("checks"), "honesty": payload.get("honesty"),
                "report_path": str(smoke_path)})
        else:
            smoke["report_missing"] = str(smoke_path)
    report["training_smoke"] = smoke

    report["six_counts"] = (smoke.get("six_counts") if smoke.get("ran")
                            else (probe.get("batch") if probe.get("ran") else None))
    report["finished_at"] = time.time()
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str),
                                encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("freeze", "export", "six_counts")
                      if k in report}, ensure_ascii=False, indent=2, default=str))
    print("wrote", args.report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
