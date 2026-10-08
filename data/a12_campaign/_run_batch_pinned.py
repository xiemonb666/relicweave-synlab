"""Run one bounded, resumable ``tools/batch_generate.py`` invocation and pin it to a code state.

Why this wrapper exists
-----------------------
The shared package was being edited *while* the campaign ran: ``synlab/observe/quality.py``,
``synlab/observe/features.py``, ``synlab/pipeline.py`` and eight more modules all changed at
13:08:2x-13:08:4x, seconds after a batch had already imported the previous revision.  A Python
process loads its modules at start-up, so two batches of the *same* config can be produced by two
different revisions of the code and their counts are then not comparable.

This wrapper therefore:
1. hashes every ``synlab/**/*.py`` file plus ``tools/batch_generate.py`` **before** the child
   starts, and again **after** it exits;
2. runs the real driver unchanged (same flags the task brief specifies) and captures its exit code
   and log;
3. writes a JSON sidecar next to the log with both hash sets, ``code_stable`` (did any module
   change while the batch ran?), the wall time and the exit code.

Nothing here re-implements or re-measures generation: the counts stay in the driver's ledger.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CAMPAIGN = REPO / "data" / "a12_campaign"


def hash_tree() -> dict[str, str]:
    out: dict[str, str] = {}
    for path in sorted(list((REPO / "synlab").rglob("*.py"))
                       + [REPO / "tools" / "batch_generate.py"]):
        rel = str(path.relative_to(REPO)).replace("\\", "/")
        try:
            out[rel] = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as exc:  # a file that cannot be read is reported, not skipped silently
            out[rel] = f"UNREADABLE: {type(exc).__name__}: {exc}"
    return out


def digest(hashes: dict[str, str]) -> str:
    payload = json.dumps(hashes, sort_keys=True).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="run_batch_pinned")
    ap.add_argument("--name", required=True, help="batch label, e.g. realistic_03")
    ap.add_argument("--config", required=True)
    ap.add_argument("--root", required=True)
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--only", default=None)
    ap.add_argument("extra", nargs="*", help="extra driver flags passed through verbatim")
    args = ap.parse_args(argv)

    logs = CAMPAIGN / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    log = logs / f"{args.name}.txt"
    sidecar = logs / f"{args.name}.code.json"

    before = hash_tree()
    cmd = [sys.executable, "tools/batch_generate.py", "--config", args.config,
           "--root", args.root, "--batch", str(args.batch), "--resume",
           "--ledger", args.ledger]
    if args.only:
        cmd += ["--only", args.only]
    cmd += list(args.extra)

    started = time.time()
    with log.open("wb") as fh:
        proc = subprocess.run(cmd, cwd=REPO, stdout=fh, stderr=subprocess.STDOUT)
    seconds = time.time() - started
    after = hash_tree()

    changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    record = {
        "batch_name": args.name,
        "command": " ".join(cmd),
        "exit_code": proc.returncode,
        "seconds": round(seconds, 3),
        "started_at": started,
        "config": args.config,
        "root": args.root,
        "ledger": args.ledger,
        "code_digest_before": digest(before),
        "code_digest_after": digest(after),
        "code_stable_during_batch": not changed,
        "modules_changed_during_batch": changed,
        "n_modules": len(after),
        "log": str(log.relative_to(REPO)).replace("\\", "/"),
    }
    sidecar.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
