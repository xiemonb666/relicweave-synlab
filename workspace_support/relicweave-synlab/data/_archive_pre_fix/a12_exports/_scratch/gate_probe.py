"""Evaluate the release gates for one run, read-only, and print them compactly.

Usage: python gate_probe.py <store_root> <run_id> [evidence_root ...]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from synlab.qc.gates import evaluate_gates, gate_evidence  # noqa: E402
from synlab.storage.release import PROFILE_GATES  # noqa: E402
from synlab.storage.store import AssetStore  # noqa: E402

store_root = ROOT / sys.argv[1]
run_id = sys.argv[2]
evidence = [str(ROOT / p) for p in sys.argv[3:]]
store = AssetStore(store_root)
gates, asset_ids, profile = evaluate_gates(store, run_id, evidence_dirs=evidence)
required = PROFILE_GATES[profile]
print("profile:", profile, "run_id:", run_id, "qa_pass_assets:", len(asset_ids))
print("\nrequired gates:")
for gate in required:
    print(f"  {gate:<28} {gates.get(gate)}")
print("\nall gates:")
for gate in sorted(gates):
    print(f"  {gate:<28} {gates[gate]}")
pending = [g for g in required if gates.get(g) != "PASS"]
print("\nrequired_not_pass:", json.dumps(pending))
print("\nevidence files read:")
for name, entry in sorted(gate_evidence(store, run_id, evidence_dirs=evidence).items()):
    print(f"  {name:<28} {entry.get('path')}")
