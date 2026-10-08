"""Merge survey shards into the canonical survey document, keeping the raw evidence.

The functional census is run as bounded shards (one process per group of lineages) so a killed
process loses at most the lineage in flight.  This merges the shard documents into
``data/a12/reports/synthesis_functional_survey.json``, keeping every raw row (including the
traceback of an ``UNEXPECTED`` outcome) and recording, per row, which shard and run it came from.

Usage::

    python data/a12/reports/synthesis_functional_merge.py \
        --out data/a12/reports/synthesis_functional_survey.json \
        data/a12_smoke/_tmp/survey_finalA.json data/a12_smoke/_tmp/survey_finalB.json
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(prog="synthesis_functional_merge")
    parser.add_argument("shards", nargs="+")
    parser.add_argument("--out", required=True)
    parser.add_argument("--keep", default=None,
                        help="optional extra document whose rows are merged first (a baseline)")
    args = parser.parse_args()

    lineages: dict[str, dict] = {}
    runs: list[dict] = []
    sources: dict[str, str] = {}
    if args.keep:
        keep = json.loads(Path(args.keep).read_text(encoding="utf-8"))
        for row in keep.get("lineages", []):
            lineages[row["lineage_id"]] = row
            sources[row["lineage_id"]] = str(args.keep)
        runs.extend({"source": str(args.keep), **run} for run in keep.get("runs", []))
    for shard in args.shards:
        doc = json.loads(Path(shard).read_text(encoding="utf-8"))
        for row in doc.get("lineages", []):
            row = dict(row)
            row["shard"] = shard
            lineages[row["lineage_id"]] = row
            sources[row["lineage_id"]] = shard
        runs.extend({"source": shard, **run} for run in doc.get("runs", []))

    rows = sorted(lineages.values(), key=lambda r: (r["vessel_id"], r["mother_index"]))
    ok = sum(1 for r in rows if r["ok"])
    document = {
        "schema": "synlab.a12.synthesis_functional_survey.v1",
        "generated_at": time.time(),
        "sources": sources,
        "runs": runs,
        "census": {"surveyed": len(rows), "ok": ok, "failed": len(rows) - ok,
                   "failed_vessels": sorted({r["vessel_id"] for r in rows if not r["ok"]}),
                   "vessels": sorted({r["vessel_id"] for r in rows})},
        "lineages": rows,
    }
    Path(args.out).write_text(json.dumps(document, ensure_ascii=False, indent=2, default=str),
                              encoding="utf-8")
    print(json.dumps(document["census"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
