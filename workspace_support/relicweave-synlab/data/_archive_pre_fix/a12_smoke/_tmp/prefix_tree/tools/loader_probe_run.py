"""Scratch: run the real loader probe and report the real outcome without a huge JSON dump.

``qc.loader_probe.probe_training_package`` builds its full report and then writes it with
``json.dumps``; on this package that allocation raises ``MemoryError`` *after* the probe has
already done its work, which loses the verdict.  This runner calls the same probe with
``out_path=None`` (no dump) and prints a bounded summary of the real report, then writes that
summary to the standard report path.  The probe itself is untouched.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from synlab.qc.loader_probe import probe_training_package  # noqa: E402

PACKAGE = ROOT / "data/a12_exports/next_experiment/training_package"
REPORT = ROOT / "data/a12/reports/loader_probe_summary.json"


def shrink(value, depth: int = 0, limit: int = 4000):
    """Bounded, JSON-safe projection of the probe report (arrays -> shape/dtype)."""
    if depth > 4:
        return "<depth-limit>"
    if isinstance(value, dict):
        out = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 60:
                out["<truncated>"] = f"{len(value) - 60} more keys"
                break
            out[str(key)] = shrink(item, depth + 1, limit)
        return out
    if isinstance(value, (list, tuple)):
        if len(value) > 25:
            return [shrink(v, depth + 1, limit) for v in value[:25]] + [f"<{len(value) - 25} more>"]
        return [shrink(v, depth + 1, limit) for v in value]
    if hasattr(value, "shape") and hasattr(value, "dtype"):
        return {"__array__": list(value.shape), "dtype": str(value.dtype)}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)[:200]


report = probe_training_package(PACKAGE, out_path=None)
summary = {
    "ok": report.get("ok"),
    "status": report.get("status"),
    "files_ok": report.get("files_ok"),
    "files_checked": report.get("files_checked"),
    "counts": report.get("counts"),
    "relation_pool": report.get("relation_pool"),
    "batch_fragments": report.get("batch_fragments"),
    "batch": shrink(report.get("batch")),
    "feature_shapes": shrink(report.get("feature_shapes")),
    "real_denominator": shrink(report.get("real_denominator")),
    "negative_audit": shrink(report.get("negative_audit")),
    "degenerate": report.get("degenerate"),
    "blocking_attempt": report.get("blocking_attempt"),
    "error": report.get("error"),
    "attempts": [{"name": a.get("name"), "ok": a.get("ok"),
                  "error_code": a.get("error_code"), "error": str(a.get("error"))[:300]}
                 for a in report.get("attempts", [])],
    "note": ("produced by tools/loader_probe_run.py: qc.loader_probe.probe_training_package on "
             "data/a12_exports/next_experiment/training_package; the probe's own json dump was "
             "skipped because it raises MemoryError on this package size"),
}
REPORT.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
print(json.dumps({k: v for k, v in summary.items() if k not in ("batch", "feature_shapes")},
                 ensure_ascii=False, indent=2, default=str))
print("\nwrote", REPORT)
