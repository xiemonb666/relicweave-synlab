"""Re-run one lineage until the *executed* code revision is stable, then stamp it.

The host runs several agents at once, so a tree-wide fingerprint is almost never equal before
and after a five-minute lineage build.  This script answers the question the acceptance needs
instead, in two layers, and refuses to claim more than it measured:

* a tree-wide ``frozen_revision`` snapshot before and after (reported honestly even when it moved);
* the **executed import closure** of each run (``run_one_lineage.py --closure-out``): the sha256 of
  every ``synlab`` module the run really imported.  Two runs whose closure digests match executed
  identical code, whatever else moved in the tree.

Attempts are bounded; every attempt's artifacts are kept so a failure is auditable.

Usage::

    python tests/a12/integration/pinned_batch.py --attempts 3
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DRIVER = REPO_ROOT / "tests" / "a12" / "integration" / "run_one_lineage.py"
FREEZER = REPO_ROOT / "tests" / "a12" / "integration" / "frozen_revision.py"
PYTHON = REPO_ROOT / ".venv" / "Scripts" / "python.exe"


def _run(cmd: Sequence[str], log: Path) -> int:
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w", encoding="utf-8", errors="replace") as handle:
        proc = subprocess.run([str(part) for part in cmd], cwd=str(REPO_ROOT),
                              stdout=handle, stderr=subprocess.STDOUT)
    return proc.returncode


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pinned_batch")
    ap.add_argument("--config", default="configs/a12/realistic.yaml")
    ap.add_argument("--lineage", default="LIN0000_V10_M11_PAT15")
    ap.add_argument("--store", default="data/a12_final/store")
    ap.add_argument("--reports", default="data/a12_reports")
    ap.add_argument("--attempts", type=int, default=3)
    args = ap.parse_args(argv)

    store = (REPO_ROOT / args.store).resolve()
    reports = (REPO_ROOT / args.reports)
    reports.mkdir(parents=True, exist_ok=True)
    history: list[dict[str, Any]] = []

    for attempt in range(1, max(1, args.attempts) + 1):
        # a fresh store each attempt: the artifact must come from one executable revision
        if store.exists():
            shutil.rmtree(store)
        snap_before = reports / f"frozen_revision_attempt{attempt}_before.json"
        snap_after = reports / f"frozen_revision_attempt{attempt}_after.json"
        clo = reports / f"import_closure_attempt{attempt}.json"
        clo_ref = reports / f"import_closure_reference.json"
        cmp_out = reports / f"frozen_revision_attempt{attempt}_compare.json"
        clo_cmp = reports / f"code_stability_attempt{attempt}.json"

        _run([PYTHON, FREEZER, "freeze", "--label", f"attempt{attempt}_before",
              "--out", snap_before], reports / f"_pin{attempt}_freeze_before.log")
        rc = _run([PYTHON, DRIVER, "--config", args.config, "--root", args.store,
                   "--lineage", args.lineage, "--closure-out", clo,
                   "--out", reports / f"run_attempt{attempt}.json"],
                  reports / f"_pin{attempt}_run.log")
        _run([PYTHON, FREEZER, "freeze", "--label", f"attempt{attempt}_after",
              "--out", snap_after], reports / f"_pin{attempt}_freeze_after.log")
        _run([PYTHON, FREEZER, "compare", "--before", snap_before, "--after", snap_after,
              "--out", cmp_out], reports / f"_pin{attempt}_compare.log")

        tree = json.loads(cmp_out.read_text(encoding="utf-8"))
        closure = json.loads(clo.read_text(encoding="utf-8"))
        executed = set(closure.get("files") or {})
        # The sound criterion: a module that *really executed* and whose bytes are identical in
        # the snapshot taken immediately before and immediately after the run was necessarily
        # identical when it was imported.  A module that changed inside that window cannot be
        # claimed either way, so it makes the attempt unresolved -- and the attempt is retried.
        moved_and_executed = sorted(set(tree["files_content_changed"]) & executed)
        removed_and_executed = sorted(set(tree["files_removed"]) & executed)
        closure_stable = not moved_and_executed and not removed_and_executed
        _run([PYTHON, FREEZER, "closure-compare", "--before", clo_ref, "--after", clo,
              "--out", clo_cmp], reports / f"_pin{attempt}_closure_cmp.log")
        outcome = json.loads((reports / f"run_attempt{attempt}.json").read_text(encoding="utf-8"))
        entry = {
            "attempt": attempt,
            "run_exit_code": rc,
            "lineage_ok": bool(outcome.get("ok")),
            "lineage_error": (outcome.get("error") or {}).get("message") if outcome.get("error") else None,
            "seconds": outcome.get("seconds"),
            "tree_code_stable": tree["code_stable_during_batch"],
            "tree_files_changed": tree["files_content_changed"],
            "executed_module_count": len(executed),
            "executed_modules_changed_during_window": moved_and_executed,
            "executed_closure_stable": bool(closure_stable),
            "import_closure_digest": outcome.get("import_closure_digest"),
            "imported_synlab_modules": outcome.get("imported_synlab_modules"),
        }
        history.append(entry)
        print(json.dumps(entry, ensure_ascii=False, indent=2), flush=True)
        if outcome.get("ok") and closure_stable:
            summary = {
                "schema": "synlab.a12.pinned_batch.v1",
                "config": args.config,
                "lineage": args.lineage,
                "store": args.store,
                "attempts_used": attempt,
                "accepted_attempt": attempt,
                "executed_closure_stable": True,
                "tree_code_stable": tree["code_stable_during_batch"],
                "tree_files_changed_during_batch": tree["files_content_changed"],
                "executed_modules_changed_during_window": moved_and_executed,
                "criterion": ("executed_closure_stable := executed modules (import closure of the "
                              "run) that changed bytes between the pre-run and post-run tree "
                              "snapshot is empty; a module outside that interval is provably "
                              "byte-identical when it was imported"),
                "import_closure_digest": outcome.get("import_closure_digest"),
                "executed_module_count": len(executed),
                "git_head": json.loads(snap_before.read_text(encoding="utf-8")).get("git_head"),
                "history": history,
            }
            (reports / "pinned_batch_summary.json").write_text(
                json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
            print("ACCEPTED attempt " + str(attempt))
            return 0
        time.sleep(5)

    summary = {
        "schema": "synlab.a12.pinned_batch.v1",
        "config": args.config, "lineage": args.lineage, "store": args.store,
        "attempts_used": len(history), "accepted_attempt": None,
        "executed_closure_stable": False,
        "criterion": ("executed_closure_stable := executed modules (import closure of the run) "
                      "that changed bytes between the pre-run and post-run tree snapshot is empty"),
        "history": history,
    }
    (reports / "pinned_batch_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("NO STABLE ATTEMPT")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
