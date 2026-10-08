"""Scratch probe 44: exact shapes returned by the current truth API."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "a12" / "truth"))

import json  # noqa: E402

from synlab.truth.api import (  # noqa: E402
    build_labels,
    finalize_clean_truth,
    update_residual_truth,
    update_visibility_truth,
)
from truth_fixtures import two_block_event  # noqa: E402


def main() -> None:
    mother, event = two_block_event()
    clean = finalize_clean_truth(mother, event)
    print("clean.meta keys:", sorted(clean.meta))
    labels = build_labels(clean)
    print("build_labels keys:", sorted(labels))
    inner = labels.get("labels")
    print("labels['labels'] keys:", sorted(inner) if isinstance(inner, dict) else type(inner))
    print("leakage block:", json.dumps(labels.get("leakage"), default=str)[:400])
    print("relations storage:", list(clean.relations)[:4])
    print("has (B,A)?", ("B", "A") in clean.relations)
    print("update_residual_truth signature sample:",
          update_residual_truth.__doc__.splitlines()[0])


if __name__ == "__main__":
    main()
