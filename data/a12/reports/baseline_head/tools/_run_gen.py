"""Run a real N-mother generation into a store and print an honest outcome JSON.

Diagnostic/utility tool for the closed loop (temporary).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from synlab.config import load_generation_spec  # noqa: E402
from synlab.pipeline import run_generation  # noqa: E402


def main() -> None:
    argv = sys.argv[1:]
    spec_path = argv[0]
    store_root = argv[1]
    mothers = int(argv[2]) if len(argv) > 2 else 1
    spec = load_generation_spec(spec_path)
    spec.storage.root = str(store_root)
    t0 = time.time()
    report = run_generation(spec, store_root=store_root, max_mothers=mothers)
    report["wall_seconds"] = time.time() - t0
    rows_path = Path(store_root) / "reports" / "coverage_rows.json"
    if rows_path.exists():
        rows = json.loads(rows_path.read_text(encoding="utf-8"))
        report["rows"] = [
            {k: r.get(k) for k in ("lineage_id", "accepted", "quarantined", "quarantine_reason",
                                   "fragments", "observations", "stages")}
            for r in rows
        ]
    text = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    if len(argv) > 3:
        Path(argv[3]).write_text(text, encoding="utf-8")
        print(f"wrote {argv[3]} ({len(text)} bytes)")
    else:
        print(text)


if __name__ == "__main__":
    main()
