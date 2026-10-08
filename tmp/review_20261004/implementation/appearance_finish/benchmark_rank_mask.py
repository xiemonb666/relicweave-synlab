from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np

from synlab.physical.fields import rank_mask_for_area_fraction


ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    records = []
    for count in (10_000, 100_000):
        scores = np.arange(count, dtype=np.float64)
        areas = 0.5 + (np.arange(count, dtype=np.float64) % 17) * 0.01
        runtimes = []
        report = None
        mask = None
        for _ in range(3):
            start = time.perf_counter()
            mask, report = rank_mask_for_area_fraction(scores, 0.37, areas, tail="lower")
            runtimes.append(time.perf_counter() - start)
        records.append({
            "texel_count": count,
            "unique_score_count": int(np.unique(scores).size),
            "timings_seconds": runtimes,
            "median_seconds": float(np.median(runtimes)),
            "selected_texels": int(mask.sum()),
            "selected_area_mm2": float(report["selected_area"]),
            "score_group_count": int(report["score_group_count"]),
        })
    (OUT / "rank_benchmark.json").write_text(json.dumps({
        "helper": "synlab.physical.fields.rank_mask_for_area_fraction",
        "score_values": "unique arange float64",
        "area_values": "0.5 + (index % 17) * 0.01 mm2",
        "requested_fraction": 0.37,
        "repetitions": 3,
        "records": records,
    }, indent=2, sort_keys=True), encoding="utf-8")
    (OUT / "benchmark_argv.json").write_text(json.dumps({"argv": sys.argv}, indent=2),
                                              encoding="utf-8")
    fields_path = ROOT / "synlab" / "physical" / "fields.py"
    benchmark_path = Path(__file__).resolve()
    (OUT / "benchmark_source_sha256.json").write_text(json.dumps({
        str(fields_path.relative_to(ROOT)): hashlib.sha256(fields_path.read_bytes()).hexdigest(),
        str(benchmark_path.relative_to(ROOT)): hashlib.sha256(benchmark_path.read_bytes()).hexdigest(),
    }, indent=2, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
