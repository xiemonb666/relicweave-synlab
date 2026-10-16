"""Reproduce failure class 2 (pattern stage) on a real mother, in isolation.

For each requested lineage the script:
  * reads the *committed* mother asset metadata from the store to recover the real params
    the batch used (the mesh itself is rebuilt with ``create_mother`` because the pipeline
    commits a reduced chart payload that ``load_mother`` cannot round-trip),
  * rebuilds the pattern recipe exactly like ``pipeline._build_pattern_recipe`` does,
  * runs ``synlab.patterns.api.evaluate`` with the same sample points/tags the pipeline uses,
  * prints the full traceback of whatever fails.

Cost: one mother build + one pattern evaluation per lineage (seconds).  The store is only
read.
"""
from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from synlab.config import load_generation_spec  # noqa: E402
from synlab.mothers.api import create_mother  # noqa: E402
from synlab.patterns.api import evaluate  # noqa: E402
from synlab.pipeline import _build_pattern_recipe  # noqa: E402
from synlab.seeds import derive_named_rngs  # noqa: E402
from synlab.storage.store import AssetStore  # noqa: E402

SPEC = ROOT / "configs" / "a12" / "next_experiment.yaml"

# lineage id -> (mother asset id, vessel, material, pattern)
CASES = [
    ("LIN0001_V21_M06_PAT16", "asset_9db153ed6b43d5189719", "V21", "M06", "PAT16"),
    ("LIN0002_V23_M07_PAT12", "asset_02b922a7c1814b4b5c23", "V23", "M07", "PAT12"),
    ("LIN0003_V23_M11_PAT06", "asset_c9a18c27d2ec6602d83d", "V23", "M11", "PAT06"),
    ("LIN0000_V10_M11_PAT15", "asset_60c959ac514d6f3121ef", "V10", "M11", "PAT15"),
]

if len(sys.argv) > 1:
    wanted = set(sys.argv[1].split(","))
    CASES = [c for c in CASES if c[0] in wanted]


def main() -> int:
    store = AssetStore(ROOT / "data" / "a12")
    spec = load_generation_spec(SPEC)
    for lineage_id, asset_id, vessel, material, pattern_id in CASES:
        print("=" * 100)
        print(f"{lineage_id}  vessel={vessel} material={material} pattern={pattern_id} "
              f"asset={asset_id}")
        record = store.get_asset(asset_id)
        params = dict(record.meta.get("params") or {})
        print(f"  params={json.dumps(params, sort_keys=True)}")
        rngs = derive_named_rngs(spec.master_seed, lineage_id)
        try:
            mother = create_mother(vessel, material, params, rngs["shape"],
                                   mother_id=lineage_id)
            print(f"  mother faces={len(mother.mesh.faces)} verts={len(mother.mesh.vertices)} "
                  f"charts={[c.name for c in mother.charts]}")
            recipe = _build_pattern_recipe(mother, spec, rngs["pattern"], pattern_id)
            print(f"  recipe family={getattr(recipe, 'family', None)} "
                  f"params={getattr(recipe, 'params', None)}")
            sample_points = np.asarray(mother.mesh.vertices, dtype=np.float64)
            sample_tags = np.zeros(len(sample_points), dtype=np.int32)
            channels = evaluate(recipe, mother, sample_points, sample_tags)
            fields = getattr(channels, "fields", None)
            if fields is None and isinstance(channels, dict):
                fields = channels
            described = {}
            for key, value in dict(fields or {}).items():
                described[key] = getattr(value, "shape", None) if not isinstance(value, np.ndarray) \
                    else value.shape
            print(f"  evaluate OK: type={type(channels).__name__} fields="
                  f"{json.dumps(described, default=str)}")
        except Exception:
            print("  FAILED:")
            print(traceback.format_exc())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

