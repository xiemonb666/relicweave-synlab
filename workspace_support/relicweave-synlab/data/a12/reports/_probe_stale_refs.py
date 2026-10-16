"""Probe: which derived reports still name the 8 retired feature asset ids?"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RETIRED = [
    "asset_2ddeda824c6b7dec8a95", "asset_846bd1b7cf1e44d139d0",
    "asset_0bcbf10e87b9b54fbbc2", "asset_e612e193c8fa59f47aa5",
    "asset_2e59947b6438587153b5", "asset_b31e078177be3f23c81b",
    "asset_5bb19a7894def812c16e", "asset_b438e92147420409adae",
]
NEW = {
    "asset_2ddeda824c6b7dec8a95": "asset_fded2bb0ae17aa1f409f",
    "asset_846bd1b7cf1e44d139d0": "asset_b9a422864590b8115042",
    "asset_0bcbf10e87b9b54fbbc2": "asset_8c29450b0260f5726bd3",
    "asset_e612e193c8fa59f47aa5": "asset_cadb60574457189e9b22",
    "asset_2e59947b6438587153b5": "asset_219282d10ed84ad8cc9a",
    "asset_b31e078177be3f23c81b": "asset_fb073cc932fc7661d49a",
    "asset_5bb19a7894def812c16e": "asset_1214795958e2a814c8b6",
    "asset_b438e92147420409adae": "asset_433cc1381e62aa47d28a",
}

reports = ROOT / "data/a12/reports"
for path in sorted(reports.rglob("*")):
    if not path.is_file() or path.name.startswith("_") or path.suffix not in (".json", ".parquet", ".txt"):
        continue
    if path.name in ("feature_leak_assets_before.json", "feature_leak_repair.json",
                     "leakage_negative_control.json"):
        continue
    try:
        data = path.read_bytes()
    except OSError:
        continue
    hits = [rid for rid in RETIRED if rid.encode() in data]
    if hits:
        print(f"{path.relative_to(ROOT)}: {len(hits)} retired ids -> {hits}")

coverage = reports / "coverage.json"
payload = json.loads(coverage.read_text(encoding="utf-8"))
blob = json.dumps(payload)
print("coverage.json names retired ids:",
      [rid for rid in RETIRED if rid in blob],
      "| names new ids:", [nid for nid in NEW.values() if nid in blob])
print("coverage.json top-level keys:", sorted(payload)[:12])
