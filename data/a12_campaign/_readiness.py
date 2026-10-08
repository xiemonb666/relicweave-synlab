"""Read-only readiness probe for the campaign: may a batch be started right now?

The shared package is being edited continuously (measured: 11 modules rewritten inside one
minute), so starting a batch on a broken or half-saved revision wastes a full 100-155 s mother
and can be killed by the host before it records anything.  This probe answers three questions
with real checks and writes nothing to the store:

1. **does every module even compile?**  ``compileall``-equivalent over ``synlab/**/*.py`` plus
   ``tools/batch_generate.py``; a live ``IndentationError`` is reported with its file and line.
2. **is the tree quiet?**  the tree is hashed twice, ``--quiet-seconds`` apart; if any file moved,
   the answer is NOT_READY and the changed files are listed.
3. **does the plan still load?**  ``load_all()`` + ``load_generation_spec`` + ``plan_generation``
   for the config, which is exactly what the driver does before it builds anything.

Exit code 0 = READY, 3 = NOT_READY.  Nothing is written, so it is safe to call in a loop.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))


def targets() -> list[Path]:
    return sorted(list((REPO / "synlab").rglob("*.py"))
                  + [REPO / "tools" / "batch_generate.py"])


def hash_tree() -> dict[str, str]:
    out: dict[str, str] = {}
    for path in targets():
        try:
            out[str(path.relative_to(REPO)).replace("\\", "/")] = hashlib.sha256(
                path.read_bytes()).hexdigest()
        except OSError as exc:
            out[str(path.relative_to(REPO))] = f"UNREADABLE: {type(exc).__name__}"
    return out


def compile_check() -> list[dict[str, str]]:
    problems: list[dict[str, str]] = []
    for path in targets():
        try:
            source = path.read_text(encoding="utf-8")
        except OSError as exc:
            problems.append({"file": str(path), "error": f"UNREADABLE: {type(exc).__name__}"})
            continue
        try:
            compile(source, str(path), "exec")
        except SyntaxError as exc:
            problems.append({
                "file": str(path.relative_to(REPO)).replace("\\", "/"),
                "error": f"{type(exc).__name__}: {exc.msg} (line {exc.lineno})",
            })
        except ValueError as exc:
            problems.append({"file": str(path), "error": f"{type(exc).__name__}: {exc}"})
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="readiness_probe")
    ap.add_argument("--config", required=True)
    ap.add_argument("--quiet-seconds", type=float, default=20.0)
    args = ap.parse_args(argv)

    first = hash_tree()
    problems = compile_check()
    time.sleep(max(0.0, args.quiet_seconds))
    second = hash_tree()
    moved = sorted(k for k in set(first) | set(second) if first.get(k) != second.get(k))

    plan_report: dict[str, object] = {}
    plan_error = None
    if not problems and not moved:
        try:
            from synlab.config import load_generation_spec
            from synlab.pipeline import plan_generation
            from synlab.registry import load_all

            reports = load_all()
            spec = load_generation_spec(REPO / args.config)
            plan = plan_generation(spec)
            plan_report = {
                "planned": len(plan.lineages),
                "spec_hash": plan.spec_hash,
                "job_id": plan.job_id,
                "load_all_errors": {k: v for k, v in reports.items() if v != "OK"},
            }
        except Exception as exc:  # noqa: BLE001 - the probe reports, never raises
            plan_error = f"{type(exc).__name__}: {exc}"

    ready = not problems and not moved and plan_error is None
    verdict = {
        "ready": ready,
        "checked_at": time.time(),
        "config": args.config,
        "n_modules": len(second),
        "syntax_problems": problems,
        "modules_changed_during_probe": moved,
        "quiet_seconds": args.quiet_seconds,
        "plan": plan_report,
        "plan_error": plan_error,
        "code_digest": "sha256:" + hashlib.sha256(
            json.dumps(second, sort_keys=True).encode("utf-8")).hexdigest(),
    }
    print(json.dumps(verdict, ensure_ascii=False, indent=2))
    return 0 if ready else 3


if __name__ == "__main__":
    raise SystemExit(main())
