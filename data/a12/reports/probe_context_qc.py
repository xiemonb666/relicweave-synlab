"""Reproduce the context-pack QC verdict on a fixture store and print the raw evidence."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab")
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests" / "a12"))
sys.path.insert(0, str(REPO / "tests" / "a12" / "qc"))

import tempfile  # noqa: E402

from test_data_quality import Fixture, check  # noqa: E402

tmp = Path(tempfile.mkdtemp(prefix="ctxprobe_"))
fixture = Fixture(tmp / "store", repo=tmp).build_green()
report = check(fixture.root, fixture.repo)
item = next(c for c in report["checks"] if c["id"] == "context.pack_contract")
print("status:", item["status"])
print("detail:", item["detail"])
for key in ("not_simulated", "incomplete", "answer_side_fields", "unresolvable"):
    print(f"{key}: {json.dumps(item['evidence'].get(key), ensure_ascii=False)}")
print("packs:", json.dumps(item["evidence"].get("packs"), ensure_ascii=False, indent=2))
print()
print("all failing checks:", [c["id"] + ":" + c["status"] for c in report["checks"]
                              if c["status"] in ("FAIL", "MISSING")])
