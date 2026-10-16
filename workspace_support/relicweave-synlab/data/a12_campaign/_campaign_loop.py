"""Autonomous campaign loop: readiness gate -> pinned batch -> append -> quality gate -> repeat.

Nothing here measures generation; it only sequences the real tools and records their real exit
codes.  The loop is deliberately failure-tolerant:

* if the readiness probe says the shared package is mid-edit or does not compile, **no batch is
  started** (starting one wastes 100-155 s per mother on an import error, as measured);
* if a batch is accepted by nobody, the loop keeps going rather than retrying the same lineage -
  the driver's ``--resume`` already skips accepted lineages, so a retry is only ever a pending one;
* every step's exit code, duration and output head is appended to a step log, and the loop stops
  when a wall-clock budget is exhausted.

Usage::
    python data/a12_campaign/_campaign_loop.py --minutes 40 --batch 4
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CAMPAIGN = REPO / "data" / "a12_campaign"
LOGS = CAMPAIGN / "logs"
PY = str(REPO / ".venv" / "Scripts" / "python.exe")

REALISTIC = {
    "name": "realistic",
    "config": "configs/a12/realistic.yaml",
    "root": "data/a12_campaign/store",
    "ledger": "data/a12_campaign/campaign_ledger.json",
}
CONTROL = {
    "name": "control",
    "config": "configs/a12/next_experiment.yaml",
    "root": "data/a12_campaign/store_control",
    "ledger": "data/a12_campaign/control_ledger.json",
}


def run(cmd: list[str], log_path: Path, timeout: float | None = None) -> tuple[int, float, str]:
    started = time.time()
    with log_path.open("wb") as fh:
        try:
            proc = subprocess.run(cmd, cwd=REPO, stdout=fh, stderr=subprocess.STDOUT, timeout=timeout)
            code = proc.returncode
        except subprocess.TimeoutExpired:
            code = -1
            fh.write(b"\n[loop] TIMEOUT: killed by the loop, not by the host\n")
    seconds = time.time() - started
    text = log_path.read_text(encoding="utf-8", errors="replace")
    return code, seconds, text


def accepted_count(ledger: Path) -> int:
    if not ledger.exists():
        return 0
    try:
        doc = json.loads(ledger.read_text(encoding="utf-8"))
    except Exception:
        return 0
    return sum(1 for row in doc.get("batches", []) if row.get("ok"))


def short_result(text: str) -> str:
    """Only the driver's own one-line-per-mother lines -- never the raw pycolmap log."""
    keys = ("FAILED", " OK ", "nothing pending", "IndentationError", "KeyError")
    lines = [line.strip() for line in text.splitlines()
             if line.startswith("[") and any(k in line for k in keys)]
    return " ; ".join(lines)[:500]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="campaign_loop")
    ap.add_argument("--minutes", type=float, default=40.0)
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--settle-seconds", type=float, default=45.0)
    ap.add_argument("--batch-timeout-minutes", type=float, default=18.0,
                    help="kill one invocation that stalls; the host also kills long processes")
    args = ap.parse_args(argv)

    LOGS.mkdir(parents=True, exist_ok=True)
    steps = LOGS / "campaign_loop_steps.txt"
    deadline = time.time() + args.minutes * 60.0

    def note(line: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        with steps.open("a", encoding="utf-8") as fh:
            fh.write(f"{stamp} {line}\n")
        print(f"{stamp} {line}", flush=True)

    note(f"LOOP_START minutes={args.minutes} batch={args.batch}")
    iteration = 0
    while time.time() < deadline:
        iteration += 1
        note(f"--- iteration {iteration} ---")

        ready, probe = probe_readiness(args.settle_seconds)
        note(f"readiness ready={ready} {probe}")
        if not ready:
            time.sleep(30)
            continue

        # a ready tree: run the pending batch for each campaign that still has pending lineages
        for spec in (REALISTIC, CONTROL):
            if time.time() >= deadline:
                break
            before = accepted_count(REPO / spec["ledger"])
            name = f"{spec['name']}_{iteration:02d}"
            code, seconds, text = run(
                [PY, "data/a12_campaign/_run_batch_pinned.py", "--name", name,
                 "--config", spec["config"], "--root", spec["root"],
                 "--ledger", spec["ledger"], "--batch", str(args.batch)],
                LOGS / f"{name}.loop.txt",
                timeout=args.batch_timeout_minutes * 60.0)
            after = accepted_count(REPO / spec["ledger"])
            note(f"batch {name} exit={code} {seconds:.0f}s accepted_delta={after - before} "
                 f"{short_result(text)}")
            append_batches()
            gate(spec)
            if after - before == 0 and code != 0:
                note(f"batch {name} produced no accepted lineage; continuing (resume skips nothing)")

    note("LOOP_END budget exhausted")
    return 0


def probe_readiness(settle: float) -> tuple[bool, str]:
    log = LOGS / "loop_readiness.json"
    code, seconds, text = run([PY, "data/a12_campaign/_readiness.py",
                               "--config", "configs/a12/realistic.yaml",
                               "--quiet-seconds", str(settle)], log)
    detail = ""
    try:
        doc = json.loads(text)
        detail = (f"syntax={len(doc.get('syntax_problems') or [])} "
                  f"moved={len(doc.get('modules_changed_during_probe') or [])} "
                  f"planned={doc.get('plan', {}).get('planned')}")
    except Exception:
        detail = text.strip().splitlines()[0][:120] if text.strip() else "no output"
    return code == 0, detail


def append_batches() -> None:
    run([PY, "data/a12_campaign/_append_batches.py"], LOGS / "loop_append.txt")


def gate(spec: dict) -> None:
    stamp = time.strftime("%H%M%S")
    log = LOGS / f"gate_{spec['name']}_{stamp}.txt"
    code, seconds, text = run([PY, "tools/check_data_quality.py", "--store", spec["root"],
                               "--no-report"], log)
    first = ""
    for line in text.splitlines():
        if "first" in line.lower() or "verdict" in line.lower():
            first = line.strip()[:200]
            break
    with (LOGS / "campaign_loop_steps.txt").open("a", encoding="utf-8") as fh:
        fh.write(f"{time.strftime('%H:%M:%S')} gate {spec['name']} exit={code} {first}\n")
    print(f"gate {spec['name']} exit={code} {first}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
