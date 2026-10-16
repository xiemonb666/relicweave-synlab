"""Re-run the real training-package export for a frozen release (supervision labels included).

The package is written from the release's own assets: the relation table, the layered labels and
now also the two supervision layers (``quality`` = the label-side observability target of task D,
``correspondence`` = the clean/physical truth ``corr_*`` surface correspondences).  Nothing is
synthesised; the exporter only stops dropping measurements the release already made.

Usage (repository root)::

    .venv\\Scripts\\python.exe data/a12/reports/reexport_training_package.py \
        --store data/a12_exports/closed_loop/store \
        --release rel_852ab2a1e4c3_1790905541 \
        --out data/a12_exports/closed_loop/training_package \
        [--report data/a12/reports/reexport_summary.json]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from synlab.storage.export import export_training_package  # noqa: E402
from synlab.storage.store import AssetStore  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", required=True)
    parser.add_argument("--release", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--report", default=None)
    parser.add_argument("--pkg-id", default=None)
    args = parser.parse_args(argv)

    started = time.perf_counter()
    manifest = export_training_package(AssetStore(Path(args.store)), args.release,
                                       Path(args.out), pkg_id=args.pkg_id)
    summary = {
        "schema": "synlab.training.reexport.v1",
        "store": args.store, "release_id": args.release, "out": args.out,
        "seconds": time.perf_counter() - started,
        "package_id": manifest.get("package_id"),
        "release_manifest_hash": manifest.get("release_manifest_hash"),
        "counts": manifest.get("counts"),
        "counts_total": manifest.get("counts_total"),
        "bytes_total": manifest.get("bytes_total"),
        "labels": [{"layer": i["layer"], "rows": i["rows"]} for i in manifest.get("labels", [])],
        "supervision_labels": manifest.get("supervision_labels"),
    }
    print(json.dumps({k: summary[k] for k in ("seconds", "package_id", "counts", "labels")},
                     ensure_ascii=False, indent=2, default=str))
    if args.report:
        path = Path(args.report)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True,
                                   default=str), encoding="utf-8")
        print(f"written {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
