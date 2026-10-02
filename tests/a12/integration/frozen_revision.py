"""Freeze the code revision a batch actually ran under, and prove it did not move.

Why this exists
---------------
Several agents edit ``synlab/**`` concurrently.  A batch that fails "sometimes" is
un-diagnosable if the code changed between two runs.  This tool records a *content*
fingerprint (sha256 per file, not just mtime) of every source and config file that can
change what the pipeline does, writes it to ``data/a12_reports/frozen_revision_<n>.json``
and can diff two snapshots to answer one question: **was the code the same before and
after the batch?**

What is covered
---------------
* ``git rev-parse HEAD`` -- the committed baseline.
* Every file under ``synlab/**`` and ``configs/**`` plus the driver/entry points, hashed by
  content, with size and mtime_ns recorded alongside so a metadata-only touch is visible
  too (a touch does not change the content hash, so it does not by itself invalidate a run;
  it is reported separately).

Usage::

    python tests/a12/integration/frozen_revision.py freeze --label batch1
    python tests/a12/integration/frozen_revision.py freeze --label batch1 --out data/a12_reports/frozen_revision_1.json
    python tests/a12/integration/frozen_revision.py compare --before <a.json> --after <b.json>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SCHEMA = "synlab.a12.frozen_revision.v1"

#: Directories whose *content* decides what the pipeline produces.
TRACKED_DIRS = ("synlab", "configs")
#: Individual files outside those directories that are read at run time.
TRACKED_FILES = (
    "tools/batch_generate.py",
    "tools/closed_loop.py",
    "tools/load_package.py",
    "tools/next_experiment_export.py",
    "tools/check_data_quality.py",
    "pyproject.toml",
)

_SKIP_SUFFIXES = {".pyc", ".pyo"}
_SKIP_PARTS = {"__pycache__", ".pytest_cache"}


def _iter_files() -> Iterable[Path]:
    for directory in TRACKED_DIRS:
        root = REPO_ROOT / directory
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix in _SKIP_SUFFIXES:
                continue
            if _SKIP_PARTS & set(path.parts):
                continue
            yield path
    for name in TRACKED_FILES:
        path = REPO_ROOT / name
        if path.is_file():
            yield path


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _git(args: Sequence[str]) -> dict[str, Any]:
    try:
        proc = subprocess.run(["git", *args], cwd=str(REPO_ROOT), capture_output=True,
                              text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:  # pragma: no cover - env dependent
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return {"ok": proc.returncode == 0, "returncode": proc.returncode,
            "stdout": proc.stdout.strip(), "stderr": proc.stderr.strip()[-400:]}


def snapshot(*, label: str, note: str | None = None) -> dict[str, Any]:
    files: dict[str, dict[str, Any]] = {}
    for path in _iter_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        stat = path.stat()
        files[rel] = {
            "sha256": _hash_file(path),
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        }
    aggregate = hashlib.sha256()
    for rel in sorted(files):
        aggregate.update(rel.encode("utf-8"))
        aggregate.update(b"\0")
        aggregate.update(files[rel]["sha256"].encode("ascii"))
        aggregate.update(b"\n")
    head = _git(["rev-parse", "HEAD"])
    status = _git(["status", "--porcelain"])
    dirty_paths = sorted(
        line[3:].strip() for line in (status.get("stdout") or "").splitlines() if line.strip()
    )
    return {
        "schema": SCHEMA,
        "label": label,
        "note": note,
        "recorded_at": time.time(),
        "recorded_at_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "repo_root": str(REPO_ROOT),
        "git_head": head.get("stdout") if head.get("ok") else None,
        "git_head_ok": bool(head.get("ok")),
        "git_status_porcelain": status.get("stdout") if status.get("ok") else None,
        "git_dirty_path_count": len(dirty_paths),
        "git_dirty_paths": dirty_paths,
        "file_count": len(files),
        "content_digest": "sha256:" + aggregate.hexdigest(),
        "files": files,
    }


def compare(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    a_files = before.get("files") or {}
    b_files = after.get("files") or {}
    added = sorted(set(b_files) - set(a_files))
    removed = sorted(set(a_files) - set(b_files))
    changed = sorted(
        rel for rel in (set(a_files) & set(b_files))
        if a_files[rel]["sha256"] != b_files[rel]["sha256"]
    )
    touched_only = sorted(
        rel for rel in (set(a_files) & set(b_files))
        if a_files[rel]["sha256"] == b_files[rel]["sha256"]
        and a_files[rel]["mtime_ns"] != b_files[rel]["mtime_ns"]
    )
    if not isinstance(before, dict) or "content_digest" not in before:
        raise SystemExit("--before is not a frozen_revision snapshot")
    stable = (
        before.get("content_digest") == after.get("content_digest")
        and not added and not removed and not changed
    )
    return {
        "schema": SCHEMA,
        "kind": "compare",
        "before_label": before.get("label"),
        "after_label": after.get("label"),
        "before_at_iso": before.get("recorded_at_iso"),
        "after_at_iso": after.get("recorded_at_iso"),
        "before_digest": before.get("content_digest"),
        "after_digest": after.get("content_digest"),
        "git_head_before": before.get("git_head"),
        "git_head_after": after.get("git_head"),
        "git_head_changed": before.get("git_head") != after.get("git_head"),
        "files_added": added,
        "files_removed": removed,
        "files_content_changed": changed,
        "files_mtime_only_touched": touched_only,
        "code_stable_during_batch": bool(stable),
        "verdict": ("code_stable_during_batch=true: no tracking-relevant file changed content"
                    if stable else
                    "code_stable_during_batch=FALSE: the batch ran against moving code; "
                    "its result is not attributable to a single revision"),
    }


def compare_closures(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Did the modules that really executed stay identical between two runs?"""
    a_files = before.get("files") or {}
    b_files = after.get("files") or {}
    changed = sorted(rel for rel in (set(a_files) & set(b_files))
                     if a_files[rel]["sha256"] != b_files[rel]["sha256"])
    added = sorted(set(b_files) - set(a_files))
    removed = sorted(set(a_files) - set(b_files))
    stable = (before.get("content_digest") == after.get("content_digest")
              and not changed and not added and not removed)
    return {
        "schema": "synlab.a12.import_closure.v1",
        "kind": "closure_compare",
        "before_digest": before.get("content_digest"),
        "after_digest": after.get("content_digest"),
        "modules_before": before.get("module_count"),
        "modules_after": after.get("module_count"),
        "modules_added": added,
        "modules_removed": removed,
        "modules_content_changed": changed,
        "executed_closure_stable": bool(stable),
        "verdict": (
            "executed_closure_stable=true: every synlab module that ran has the same bytes in "
            "both runs, so the result is attributable to one executable revision"
            if stable else
            "executed_closure_stable=FALSE: a module that really executed changed between the "
            "two runs; the result spans two revisions"),
    }


def _load(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="frozen_revision")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_freeze = sub.add_parser("freeze")
    p_freeze.add_argument("--label", required=True)
    p_freeze.add_argument("--note", default=None)
    p_freeze.add_argument("--out", default=None)

    p_cmp = sub.add_parser("compare")
    p_cmp.add_argument("--before", required=True)
    p_cmp.add_argument("--after", required=True)
    p_cmp.add_argument("--out", default=None)

    p_clo = sub.add_parser("closure-compare")
    p_clo.add_argument("--before", required=True)
    p_clo.add_argument("--after", required=True)
    p_clo.add_argument("--out", default=None)

    args = parser.parse_args(argv)
    if args.cmd == "closure-compare":
        result = compare_closures(_load(args.before), _load(args.after))
        if args.out:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                     encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["executed_closure_stable"] else 2

    if args.cmd == "freeze":
        snap = snapshot(label=args.label, note=args.note)
        out = Path(args.out) if args.out else REPO_ROOT / "data" / "a12_reports" / (
            f"frozen_revision_{args.label}.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({k: v for k, v in snap.items() if k != "files"},
                         ensure_ascii=False, indent=2))
        print(f"written: {out}")
        return 0

    result = compare(_load(args.before), _load(args.after))
    out = Path(args.out) if args.out else None
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["code_stable_during_batch"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
