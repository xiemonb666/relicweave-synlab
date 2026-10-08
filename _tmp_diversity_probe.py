"""Scratch probe: exercise the diversity materialisation path on the built-in probe sources.

Not a deliverable.  Writes into ``data/a12_degrade/_probe_store`` (the new library tree only).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402

from synlab.degrade.api import observe_probe, probe_appearance  # noqa: E402
from synlab.degrade.diversity import (  # noqa: E402
    commit_observation_sources,
    directory_bytes,
    load_diversity_config,
    materialize_lineage_diversity,
)
from synlab.degrade.sources import SourceBundle, commit_source, load_source  # noqa: E402
from synlab.storage.store import AssetStore  # noqa: E402

ROOT = Path("data/a12_degrade/_probe_store")
store = AssetStore(ROOT)

# --- P source: a real committed mesh asset, read back (mimics the fragment-asset path) -------
from synlab.degrade.api import probe_mesh  # noqa: E402

mesh, meta, provenance = probe_mesh(store=None)
record = store.commit_asset(role="fragment_mesh", schema="synlab.fragment.v1", unit="mm",
                            frame="W_mm", payload={"mesh": mesh},
                            meta={**meta, "provenance": provenance})
bundle = load_source(store, record.asset_id)
bundle.meta.update({"material_id": "M03", "master_seed": 20261001,
                    "provenance": f"PROBE_FRAGMENT_ASSET:{record.asset_id}"})
print("P source kind", bundle.source_kind, "keys", sorted(bundle.payload))

# --- I/G/X sources: real observation -> committed degrade_source -> reloaded ------------------
observation = observe_probe(size=(128, 96), views=4, seed=20261001)
sources = {"P": bundle}
sources.update(commit_observation_sources(store, observation, lineage_id="probe_lineage",
                                          split="train", material_id="M03",
                                          master_seed=20261001,
                                          data_semantics={"probe": True}))
for key, item in sorted(sources.items()):
    print(key, item.source_kind, item.asset_id, item.content_hash()[:16],
          "round_trip", (item.meta or {}).get("round_trip_hash_ok"))

cfg = load_diversity_config()
t0 = time.perf_counter()
report = materialize_lineage_diversity(
    store, config=cfg, sources=sources, lineage_id="probe_lineage", split="train",
    master_seed=20261001, lineage_index=0, run_id="probe_run",
    data_semantics={"probe": True}, progress_path=ROOT / "reports" / "probe.json")
print("seconds", round(time.perf_counter() - t0, 2))
print(json.dumps(report["summary"], ensure_ascii=False, indent=2)[:4000])
print("store bytes", directory_bytes(ROOT))
for axis in report["axes"]:
    for level in axis["levels"]:
        print(axis["axis_id"], level["level"], level["status"], level.get("asset_committed"),
              str(level.get("asset_id"))[:24], json.dumps(level.get("measured") or {})[:160])
