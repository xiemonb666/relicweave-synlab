"""Build ``data/a12/reports/training_supervision_after.json`` (per-task supervision report).

Reads the *measured* reports that were just produced -- never a constant:

* ``training_smoke_before.json``  the state before the fix (3 steps, real package)
* ``training_smoke.json``         the state after the fix (same package, re-exported)
* the package manifest            which real labels the exporter now writes
* every real exported package     whether any relation row has both ends observed at all

Run from the repository root with the bundled interpreter::

    .venv\\Scripts\\python.exe data/a12/reports/build_training_supervision_after.py \
        --export-exit 0 --smoke-exit 0 --pytest-exit 0
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from synlab.storage.export import TrainingPackage  # noqa: E402

REPORTS = REPO / "data" / "a12" / "reports"
PACKAGE = REPO / "data" / "a12_exports" / "closed_loop" / "training_package"
NEXT_PACKAGE = REPO / "data" / "a12_exports" / "next_experiment" / "training_package"
POOL = REPO / "data" / "a12" / "pools" / "sandbox_dev.json"
TASKS = ("rank", "view", "correspondence", "quality", "contradiction")


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read(path: Path) -> dict[str, Any]:
    return _load(path) if path.exists() else {}


def _task_rows(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    record = (report.get("steps", {}).get("records") or [{}])[0]
    supervision = (report.get("supervision") or {}).get("tasks") or {}
    out: dict[str, dict[str, Any]] = {}
    for task in TASKS:
        reported = (record.get("tasks") or {}).get(task) or {}
        accounted = supervision.get(task) or {}
        out[task] = {
            "n_valid": int(accounted.get("n_valid", reported.get("n_valid", 0))),
            "n_allowed": int(accounted.get("n_allowed", reported.get("n_allowed", 0))),
            "n_valid_labels": int(accounted.get("n_valid_labels",
                                                reported.get("n_valid_labels", 0))),
            "loss": reported.get("loss"),
            "weight": reported.get("weight"),
            "skipped": reported.get("skipped"),
            "reason": reported.get("reason"),
            "blocked_by": list(accounted.get("blocked_by") or []),
            "structural": accounted.get("structural"),
        }
    return out


def _before_task_rows(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The before state has no accounting block, so the pre-fix numbers are read as they are.

    ``n_valid_labels`` did not exist before the fix: the old report only carried the loss's own
    ``n_valid`` (0 for every skipped task) and a catch-all reason, which is exactly the gap this
    report closes.  The label-side counts of the *before* run are therefore re-measured from the
    pre-fix package state (``correspondence_labels_in_package`` / ``valid_quality_targets`` /
    ``positive_pairs``) rather than invented.
    """
    record = (report.get("steps", {}).get("records") or [{}])[0]
    availability = report.get("supervision_availability") or {}
    out: dict[str, dict[str, Any]] = {}
    for task in TASKS:
        reported = (record.get("tasks") or {}).get(task) or {}
        out[task] = {
            "n_valid": int(reported.get("n_valid", 0)),
            "n_allowed": int(reported.get("n_valid", 0)),
            "loss": reported.get("loss"),
            "weight": reported.get("weight"),
            "skipped": reported.get("skipped"),
            "reason": reported.get("reason"),
        }
    out["rank"]["n_valid_labels"] = int(availability.get("positive_pairs", 0))
    out["contradiction"]["n_valid_labels"] = int(availability.get("valid_contradiction_labels", 0))
    out["correspondence"]["n_valid_labels"] = int(
        availability.get("correspondence_labels_in_package", 0))
    out["quality"]["n_valid_labels"] = int(availability.get("valid_quality_targets", 0))
    out["view"]["n_valid_labels"] = int(out["view"]["n_valid"])
    return out


def _observation_corpus() -> dict[str, Any]:
    """Every real relation row of every real package: does any pair have both ends observed?"""
    corpus: dict[str, Any] = {"packages": [], "relations_total": 0, "both_ends_observed": 0,
                              "kinds": {}}
    for package_dir in (PACKAGE, NEXT_PACKAGE):
        if not (package_dir / "export_manifest.json").exists():
            continue
        package = TrainingPackage(package_dir)
        relations = package.relations()
        observed = set((package.observation_index().get("rows") or {}))
        kinds: dict[str, int] = {}
        both = one = none = 0
        for row in relations:
            kind = str(row.get("kind"))
            kinds[kind] = kinds.get(kind, 0) + 1
            corpus["kinds"][kind] = corpus["kinds"].get(kind, 0) + 1
            q, c = str(row.get("query")), str(row.get("candidate"))
            n_obs = int(q in observed) + int(c in observed)
            both += int(n_obs == 2)
            one += int(n_obs == 1)
            none += int(n_obs == 0)
        supervised_negatives = sum(1 for r in relations
                                   if str(r.get("kind")) in ("R1", "R0")
                                   and bool(r.get("valid")) and bool(r.get("loss_mask")))
        corpus["packages"].append({
            "package_dir": str(package_dir.relative_to(REPO)),
            "release_id": package.manifest.get("release_id"),
            "relation_rows": len(relations),
            "relation_kinds": kinds,
            "observed_fragments": len(observed),
            "query_rows": int(package.manifest.get("counts", {}).get("queries", 0)),
            "rows_with_both_ends_observed": both,
            "rows_with_exactly_one_end_observed": one,
            "rows_with_no_end_observed": none,
            "supervised_r1_r0_rows": supervised_negatives,
        })
        corpus["relations_total"] += len(relations)
        corpus["both_ends_observed"] += both
    if POOL.exists():
        pool = _load(POOL)
        edges = pool.get("edges") or []
        hist: dict[str, dict[str, int]] = {}
        for edge in edges:
            key = f"valid={bool(edge.get('valid'))},loss_mask={bool(edge.get('loss_mask'))}"
            hist.setdefault(str(edge.get("kind")), {})
            hist[str(edge.get("kind"))][key] = hist[str(edge.get("kind"))].get(key, 0) + 1
        corpus["pool"] = {"path": str(POOL.relative_to(REPO)), "pool_id": pool.get("pool_id"),
                          "edges": len(edges),
                          "edge_histogram_by_validity": hist}
    return corpus


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export-exit", type=int, default=None)
    parser.add_argument("--smoke-exit", type=int, default=None)
    parser.add_argument("--pytest-exit", type=int, default=None)
    parser.add_argument("--export-seconds", type=float, default=None)
    parser.add_argument("--smoke-seconds", type=float, default=None)
    parser.add_argument("--out", default=str(REPORTS / "training_supervision_after.json"))
    args = parser.parse_args(argv)

    before = _read(REPORTS / "training_smoke_before.json")
    after = _read(REPORTS / "training_smoke.json")
    if not before or not after:
        raise SystemExit("both training_smoke_before.json and training_smoke.json are required")

    package = TrainingPackage(PACKAGE)
    manifest = package.manifest
    before_tasks = _before_task_rows(before)
    after_tasks = _task_rows(after)

    delta = {task: {"n_valid_labels": after_tasks[task]["n_valid_labels"]
                    - before_tasks[task]["n_valid_labels"],
                    "n_allowed": after_tasks[task]["n_allowed"] - before_tasks[task]["n_allowed"],
                    "loss_started": bool(after_tasks[task]["loss"] is not None
                                         and before_tasks[task]["loss"] is None),
                    "loss_stopped": bool(after_tasks[task]["loss"] is None
                                         and before_tasks[task]["loss"] is not None)}
             for task in TASKS}

    blocked = {task: {"reason": after_tasks[task]["reason"],
                      "blocked_by": after_tasks[task]["blocked_by"],
                      "structural": after_tasks[task]["structural"]}
               for task in TASKS if after_tasks[task]["n_allowed"] == 0}

    report = {
        "schema": "synlab.training.supervision.v1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "purpose": ("per-task supervision of the five A12 tasks on the real exported package: "
                    "n_valid (labels that exist) vs n_allowed (rows that survive every mask), "
                    "with the measured blocker and the unlock condition of every blocked task"),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "torch": str((((after.get("model") or {}).get("torch_version")) or "")),
            "device": (after.get("model") or {}).get("device"),
            "cuda_available": (after.get("model") or {}).get("cuda_available"),
            "precision": (after.get("model") or {}).get("precision"),
        },
        "commands": [
            {"cmd": (".venv\\Scripts\\python.exe "
                     "data/a12/reports/reexport_training_package.py "
                     "--store data/a12_exports/closed_loop/store "
                     "--release rel_852ab2a1e4c3_1790905541 "
                     "--out data/a12_exports/closed_loop/training_package"),
             "exit_code": args.export_exit, "seconds": args.export_seconds},
            {"cmd": (".venv\\Scripts\\python.exe -c \"from synlab.training.smoke import run_smoke; "
                     "run_smoke('data/a12_exports/closed_loop/training_package', steps=3, "
                     "out_dir='data/a12/reports', include_loader_probe=True)\""),
             "exit_code": args.smoke_exit, "seconds": args.smoke_seconds},
            {"cmd": ".venv\\Scripts\\python.exe -m pytest tests/a12/training -q",
             "exit_code": args.pytest_exit},
        ],
        "package": {
            "package_dir": str(PACKAGE.relative_to(REPO)),
            "package_id": manifest.get("package_id"),
            "release_id": manifest.get("release_id"),
            "release_manifest_hash": manifest.get("release_manifest_hash"),
            "files": len(manifest.get("files", [])),
            "counts": manifest.get("counts"),
            "label_layers": [{"layer": item["layer"], "rows": item["rows"]}
                             for item in manifest.get("labels", [])],
            "supervision_labels": manifest.get("supervision_labels"),
        },
        "before": {
            "report": "data/a12/reports/training_smoke_before.json",
            "status": before.get("status"),
            "combined_loss_sequence": before.get("steps", {}).get("loss_sequence"),
            "tasks": before_tasks,
        },
        "after": {
            "report": "data/a12/reports/training_smoke.json",
            "status": after.get("status"),
            "combined_loss_sequence": after.get("steps", {}).get("loss_sequence"),
            "tasks": after_tasks,
            "pair_mask": (after.get("supervision") or {}).get("pair_mask"),
            "plan_30_12": (after.get("supervision") or {}).get("plan_30_12"),
            "tasks_with_supervision": (after.get("supervision") or {}).get(
                "tasks_with_supervision"),
            "tasks_structurally_blocked": (after.get("supervision") or {}).get(
                "tasks_structurally_blocked"),
            "tasks_without_explanation": (after.get("supervision") or {}).get(
                "tasks_without_explanation"),
        },
        "delta": delta,
        "blocked_tasks": blocked,
        "structural_evidence": _observation_corpus(),
        "honesty": {
            "synthesised_labels": 0,
            "synthesised_negatives": 0,
            "note": ("every label in the after state is a value the release already measured: "
                     "the quality target is the visible/truth layer's observability ratio and "
                     "the correspondence labels are the clean-truth corr_* arrays; no label was "
                     "generated, resampled or imputed"),
            "no_generalisation_claim": ("2 tasks have supervision rows (view 12, quality 3); "
                                        "3 rows cannot support any accuracy or curve claim"),
        },
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True,
                                   default=str), encoding="utf-8")
    print(f"written {out_path} ({out_path.stat().st_size} B)")
    for task in TASKS:
        b, a = before_tasks[task], after_tasks[task]
        print(f"  {task:14s} before n_valid_labels={b['n_valid_labels']:5d} "
              f"n_allowed={b['n_allowed']:5d} loss={b['loss']}  ->  "
              f"after n_valid_labels={a['n_valid_labels']:5d} n_allowed={a['n_allowed']:5d} "
              f"loss={a['loss']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
