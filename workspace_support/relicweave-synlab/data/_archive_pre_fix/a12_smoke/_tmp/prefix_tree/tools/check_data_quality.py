"""``tools/check_data_quality.py`` -- the command-line entry point of the data quality gate.

Answers one question programmatically: **can this data be trained on?**  Read-only: nothing in
the store or the package is created, modified, re-stamped or repaired.  The only file written is
the JSON verdict under ``data/a12/reports/``.

Usage
-----
    .venv\\Scripts\\python.exe tools\\check_data_quality.py --store data\\a12
    .venv\\Scripts\\python.exe tools\\check_data_quality.py --package data\\a12_exports\\next_experiment\\training_package
    .venv\\Scripts\\python.exe tools\\check_data_quality.py --store data\\a12 --no-report
    .venv\\Scripts\\python.exe tools\\check_data_quality.py --all          # every store + package on disk

Exit codes
----------
``0``   trainable -- every required check passed.
``3``   not trainable -- ``partial`` or ``not_trainable``; the first cause and the full per-check
        breakdown are printed.
``2``   usage / input error (the target is not a store and not an export package).
``1``   the gate itself failed unexpectedly.

See ``synlab/qc/data_quality.py`` for the check list, every threshold and where it comes from,
and ``docs/a12/dataset_registry.md`` for the per-target verdicts this tool produced.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synlab.qc.data_quality import (  # noqa: E402  (path bootstrap must come first)
    QcInputError,
    assess_target,
    default_report_dir,
    format_summary,
    report_slug,
    write_report,
)

DATA_ROOTS = ("data/a12", "data/a12_demo", "data/a12_exports", "data/a12_trainable",
              "data/a12_probe_tmp")


def _find_targets(repo: Path) -> list[Path]:
    """Every store root and every export package under the known data roots, read-only."""
    found: dict[str, Path] = {}
    for rel in DATA_ROOTS:
        root = repo / rel
        if not root.exists():
            continue
        if (root / "metadata.sqlite").exists():
            found[str(root)] = root
        for db in sorted(root.glob("**/metadata.sqlite")):
            if db.parent.name.startswith("_"):
                continue
            found[str(db.parent)] = db.parent
        for manifest in sorted(root.glob("**/export_manifest.json")):
            if manifest.parent.name == "release_index":
                continue
            if "_scratch" in manifest.parts or "_baseline" in manifest.parts:
                continue
            found[str(manifest.parent)] = manifest.parent
    return [found[key] for key in sorted(found)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="check_data_quality.py",
        description="Read-only data quality gate: is this store/package trainable?",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--store", metavar="ROOT", type=Path,
                       help="an AssetStore root (a directory holding metadata.sqlite)")
    group.add_argument("--package", metavar="DIR", type=Path,
                       help="an exported training package (a directory holding export_manifest.json)")
    group.add_argument("--all", action="store_true",
                       help="every store and package under the known data roots")
    parser.add_argument("--repo", type=Path, default=REPO_ROOT,
                        help="repository root used for provenance and report paths")
    parser.add_argument("--report-dir", type=Path, default=None,
                        help="where to write the JSON verdict (default data/a12/reports)")
    parser.add_argument("--no-report", action="store_true",
                        help="print only; write no JSON verdict file")
    parser.add_argument("--json", action="store_true",
                        help="print the full JSON report instead of the human summary")
    parser.add_argument("--quiet", action="store_true", help="print nothing but the verdict line")
    args = parser.parse_args(argv)

    repo = args.repo.resolve()
    report_dir = args.report_dir or default_report_dir(repo)

    if args.all:
        targets: list[tuple[Path, str | None]] = [(path, None) for path in _find_targets(repo)]
    elif args.store is not None:
        targets = [(args.store, "store")]
    else:
        targets = [(args.package, "package")]

    worst = 0
    reports = []
    for target, kind in targets:
        try:
            report = assess_target(target, repo=repo, kind=kind)
        except QcInputError as exc:
            print(f"ERROR {target}: {exc}", file=sys.stderr)
            worst = max(worst, 2)
            continue
        except Exception as exc:  # noqa: BLE001 - the gate must not die silently
            print(f"ERROR {target}: {type(exc).__name__}: {exc}", file=sys.stderr)
            worst = max(worst, 1)
            continue
        reports.append((target, report))
        path = None
        if not args.no_report:
            path = write_report(report, target, repo=repo, out_dir=report_dir)
        if args.quiet:
            print(f"{report['verdict']:<14} {report['target']['path']}")
        elif args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, default=str))
        else:
            print(format_summary(report))
            if path is not None:
                print(f"  report  : {path}")
            print()
        if not report["trainable"]:
            worst = max(worst, 3)

    if args.all:
        print(f"scanned {len(targets)} target(s); "
              f"{sum(1 for _, r in reports if r['trainable'])} trainable")
        for target, report in reports:
            first = report.get("first_cause") or {}
            print(f"  {report['verdict']:<14} {report['target']['path']}"
                  + (f"   first: {first.get('check_id')} [{first.get('status')}]" if first else ""))
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
