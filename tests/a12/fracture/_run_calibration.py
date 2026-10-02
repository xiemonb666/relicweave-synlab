"""Driver for the fracture calibration evidence (one step per process, every step writes to disk).

Steps (all optional, run them one at a time -- this host kills heavy processes):

```powershell
& .venv\\Scripts\\python.exe tests\\a12\\fracture\\_run_calibration.py batch  --lineages 1 --label b1
& .venv\\Scripts\\python.exe tests\\a12\\fracture\\_run_calibration.py batch  --lineages 2 --label b2
& .venv\\Scripts\\python.exe tests\\a12\\fracture\\_run_calibration.py verify --label b1
```

The measurements themselves live in :mod:`synlab.fracture.calibrate` (the instrument) and
``tests/a12/fracture/_batch_voronoi.py`` (the batch acceptance run); this file only sequences them
and writes the JSON the documents quote.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

REPORT_DIR = REPO_ROOT / "data" / "a12_reports"


def _write(name: str, payload: dict[str, Any]) -> Path:
    path = REPORT_DIR / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False, default=str),
                    encoding="utf-8")
    return path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="fracture calibration evidence driver")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("batch")
    p.add_argument("--lineages", type=int, default=1)
    p.add_argument("--base-config", default="configs/a12/sandbox.yaml")
    p.add_argument("--label", default="b1")

    p = sub.add_parser("verify")
    p.add_argument("--label", default="b1")
    p.add_argument("--store-root", default="")

    p = sub.add_parser("validate")
    p.add_argument("--config", default="configs/a12/fracture_physics.yaml")
    p.add_argument("--label", default="validate")

    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.command == "batch":
        sys.path.insert(0, str(REPO_ROOT / "tests" / "a12" / "fracture"))
        from _batch_voronoi import STORE_ROOT, run_batch  # type: ignore[import-not-found]

        started = time.perf_counter()
        payload = run_batch(args.base_config, target_mothers=int(args.lineages),
                            store_root=STORE_ROOT,
                            progress_path=REPORT_DIR / f"fracture_batch_{args.label}.json")
        payload["wall_seconds_driver"] = round(time.perf_counter() - started, 3)
        path = _write(f"fracture_batch_{args.label}.json", payload)
        ledger = payload.get("generation") or {}
        print(json.dumps({k: ledger.get(k) for k in
                          ("planned", "attempted", "accepted", "quarantined", "failed",
                           "complete", "fracture_backend")}, indent=1), flush=True)
        for row in (ledger.get("rows") or []):
            print(f"  {row.get('lineage_id')}: accepted={row.get('accepted')} "
                  f"backend={row.get('backend')} fragments={row.get('fragments')} "
                  f"stages={row.get('stages')}", flush=True)
        for failure in (ledger.get("failures") or []):
            print(f"  FAILED {failure}", flush=True)
        print("wrote", path, flush=True)
    elif args.command == "verify":
        sys.path.insert(0, str(REPO_ROOT / "tests" / "a12" / "fracture"))
        from _batch_voronoi import STORE_ROOT, verify_batch  # type: ignore[import-not-found]

        payload = verify_batch(args.store_root or STORE_ROOT,
                               coverage_rows=REPO_ROOT / "data" / "a12_fcal" / "store"
                               / "reports" / "coverage_rows.json")
        path = _write(f"fracture_batch_{args.label}_verify.json", payload)
        print(json.dumps({k: payload[k] for k in
                          ("assets", "fragment_backends", "lineages")}, indent=1), flush=True)
        print("wrote", path, flush=True)
    elif args.command == "validate":
        from typer.testing import CliRunner

        from synlab.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["validate", "--config", args.config, "--json"])
        payload = {"schema": "synlab.fracture_calibration.validate.v1", "config": args.config,
                   "exit_code": int(result.exit_code), "stdout": result.stdout,
                   "stderr": getattr(result, "stderr", "")}
        try:
            payload["result"] = json.loads(result.stdout)
        except Exception:  # noqa: BLE001 - non-JSON output is reported verbatim
            payload["result"] = None
        path = _write(f"fracture_{args.label}.json", payload)
        print("exit_code", result.exit_code, flush=True)
        print(result.stdout[:1200], flush=True)
        print("wrote", path, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
