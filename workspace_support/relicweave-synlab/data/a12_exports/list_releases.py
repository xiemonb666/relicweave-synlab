"""Read-only: every frozen release of the two closed-loop stores (gate_overrides audit)."""

from __future__ import annotations

import glob
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for pattern in ("data/a12_exports/closed_loop/store/releases/*/manifest.json",
                "data/a12_exports/cl_fresh/store/releases/*/manifest.json"):
    for name in sorted(glob.glob(str(ROOT / pattern))):
        manifest = json.loads(Path(name).read_text(encoding="utf-8"))
        extra = manifest.get("extra") or {}
        print(f"{manifest['release_id']:<34} assets={len(manifest['assets']):<4} "
              f"frozen={time.strftime('%H:%M:%S', time.localtime(Path(name).stat().st_mtime))} "
              f"overrides={len(extra.get('gate_overrides') or [])} "
              f"refused={len(extra.get('refused_gate_overrides') or [])} "
              f"pending={manifest['scope_pending']} "
              f"r2={manifest['coverage'].get('r2_relations_in_scope')} "
              f"attribution={ {k: v for k, v in (manifest['coverage'].get('run_id_attribution') or {}).items() if k != 'note'} }")
