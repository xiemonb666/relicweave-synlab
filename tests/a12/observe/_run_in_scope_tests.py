"""Run the in-scope test files one at a time and record each exit code (A12 surface-signal work).

Writes ``data/a12/reports/fracture_surface_signal/pytest_files.json`` with one row per file.  A
file killed by the host is recorded with its real exit code; nothing is retried silently.

Usage: python tests/a12/observe/_run_in_scope_tests.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PY = str(ROOT / ".venv" / "Scripts" / "python.exe")
OUT = ROOT / "data" / "a12" / "reports" / "fracture_surface_signal"

FILES = [
    "tests/a12/physical/test_face_provenance.py",
    "tests/a12/truth/test_interface_layer.py",
    "tests/a12/truth/test_persistence.py",
    "tests/a12/truth/test_relations.py",
    "tests/a12/truth/test_pipeline_contracts.py",
    "tests/a12/observe/test_fracture_surface_signal.py",
    "tests/a12/observe/test_coc_units.py",
    "tests/a12/observe/test_pixel_contract.py",
    "tests/a12/observe/test_mvs_subset.py",
    "tests/a12/observe/test_renderer_dispatch.py",
    "tests/a12/observe/test_carve_holes_bounds.py",
    "tests/a12/observe/test_realism_config_and_bridge.py",
    "tests/a12/observe/test_blender_backend.py",
]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for name in FILES:
        path = ROOT / name
        if not path.exists():
            rows.append({"file": name, "exit_code": None, "status": "MISSING"})
            continue
        log = OUT / ("pytest_" + name.replace("/", "__").replace(".py", "") + ".txt")
        t0 = time.time()
        with open(log, "wb") as handle:
            proc = subprocess.run([PY, "-m", "pytest", name, "-q"], cwd=str(ROOT),
                                  stdout=handle, stderr=subprocess.STDOUT)
        tail = ""
        try:
            tail = "\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-3:])
        except OSError:
            pass
        rows.append({"file": name, "exit_code": int(proc.returncode),
                     "seconds": round(time.time() - t0, 1), "log": str(log.relative_to(ROOT)),
                     "tail": tail})
        print(f"{name}: exit={proc.returncode} {rows[-1]['seconds']}s", flush=True)
    (OUT / "pytest_files.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print("wrote", OUT / "pytest_files.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
