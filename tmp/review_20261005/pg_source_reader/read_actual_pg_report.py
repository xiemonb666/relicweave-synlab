from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

review_dir = Path(__file__).resolve().parent
repo_root = review_dir.parents[2]
sys.path.insert(0, str(repo_root))

from synlab.qa.source_readers.pgfrag_result import read_pgfrag_result


source_root = (
    repo_root
    / "tmp"
    / "review_20261003"
    / "implementation"
    / "pg"
    / "jobs"
    / "osb_fracture_branch_001"
    / "output"
)
result_bytes = (source_root / "result.json").read_bytes()
report = read_pgfrag_result(
    source_root,
    expected_result_sha256=hashlib.sha256(result_bytes).hexdigest(),
)
if report.get("status") != "PG_DIAGNOSTIC_ONLY":
    raise SystemExit("actual PG-Frag result was not accepted at the diagnostic source scope")
if report.get("row_counts", {}).get("point_rows") != 576:
    raise SystemExit("actual PG-Frag point row count differs from the reviewed source")
if report.get("row_counts", {}).get("bond_state_rows") != 20_780:
    raise SystemExit("actual PG-Frag bond row count differs from the reviewed source")
if report.get("capabilities", {}).get("physical_fragments", {}).get("status") != "UNKNOWN":
    raise SystemExit("physical fragment qualification must remain UNKNOWN")

(review_dir / "actual_pg_source_report.json").write_text(
    json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
    encoding="utf-8",
)
