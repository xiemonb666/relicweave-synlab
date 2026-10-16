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
job_path = (
    repo_root
    / "tmp"
    / "review_20261003"
    / "implementation"
    / "pg"
    / "jobs"
    / "osb_fracture_branch_001"
    / "job.json"
)
expected_job_sha256 = "83af8ea8cb0fd204ab288841fd87382c9dae77ec1cfb5dc9d0c925d610d430d1"
pre_receipt = json.loads((review_dir / "verification_retry_pre.json").read_text(encoding="utf-8"))
relative_result = "tmp/review_20261003/implementation/pg/jobs/osb_fracture_branch_001/output/result.json"
pre_result = next(
    item for item in pre_receipt["input_files"]
    if item["path"].replace("\\", "/") == relative_result
)
expected_result_sha256 = pre_result["sha256"]
actual_result_sha256 = hashlib.sha256((source_root / "result.json").read_bytes()).hexdigest()
if actual_result_sha256 != expected_result_sha256:
    raise SystemExit("result.json differs from the frozen pre-probe source hash")

report = read_pgfrag_result(
    source_root,
    expected_result_sha256=expected_result_sha256,
    job_path=job_path,
    expected_job_sha256=expected_job_sha256,
)
if report.get("status") != "PG_DIAGNOSTIC_ONLY":
    raise SystemExit("named-source probe did not remain at the diagnostic source scope")
if report.get("job_source", {}).get("status") != "SOURCE_VERIFIED":
    raise SystemExit("explicit named job bytes did not verify against result metadata")
if report.get("caller_match", {}).get("status") != "UNKNOWN":
    raise SystemExit("caller rows must remain UNKNOWN when none were supplied")
if "normalized_rows" in report:
    raise SystemExit("probe must not persist normalized source tables")
if any(report["capabilities"][name]["status"] != "UNKNOWN" for name in (
    "physical_fragments", "crack_surfaces", "event_history", "historical_R2",
)):
    raise SystemExit("physical and historical qualifications must remain UNKNOWN")
if report["source_binding"]["component_partition_validation"]["status"] != "UNKNOWN":
    raise SystemExit("graph connectivity must remain UNKNOWN")

(review_dir / "actual_named_job_source_report.json").write_text(
    json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
    encoding="utf-8",
)
