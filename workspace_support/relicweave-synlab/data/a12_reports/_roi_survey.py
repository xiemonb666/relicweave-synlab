"""Read-only survey: which store holds fracture-bearing fragments, of which vessel/material.

Writes nothing but its own JSON/text output under data/a12_reports/.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from synlab.storage.store import AssetStore  # noqa: E402

STORES = [
    "data/a12", "data/a12_final/store", "data/a12_campaign/store", "data/a12_morph/store",
    "data/a12_phys/store", "data/a12_realistic/store", "data/a12_iface/store",
    "data/a12_extras/store", "data/a12_fcal/store",
]


def main() -> None:
    out: dict[str, object] = {}
    for rel in STORES:
        root = ROOT / rel
        if not (root / "metadata.sqlite").exists():
            out[rel] = {"status": "NO_STORE"}
            continue
        store = AssetStore(root)
        roles = Counter()
        assets = store.list_assets(limit=5000)
        for a in assets:
            roles[a.role] += 1
        info: dict[str, object] = {"n_assets": len(assets), "roles": dict(roles)}
        rows = []
        for a in assets:
            if a.role not in ("fragment_mesh", "physical_component", "clean_fragment"):
                continue
            arrays = {}
            try:
                arrays = store.load_arrays(a.asset_id)
            except Exception as exc:  # noqa: BLE001
                rows.append({"asset_id": a.asset_id, "role": a.role, "error": str(exc)[:120]})
                continue
            keys = sorted(arrays)
            n_faces = None
            for key in ("face_origin_kind", "origin_kind", "face_interface_id", "interface_id"):
                if key in arrays:
                    n_faces = int(np.asarray(arrays[key]).size)
                    break
            if n_faces is None:
                for key in keys:
                    if key.endswith("faces") or key == "mesh.faces":
                        n_faces = int(np.asarray(arrays[key]).shape[0])
                        break
            iface = arrays.get("face_interface_id", arrays.get("interface_id"))
            iface_ids = sorted({int(v) for v in np.unique(iface)}) if iface is not None else None
            row = {
                "asset_id": a.asset_id, "role": a.role, "lineage_id": a.lineage_id,
                "n_faces": n_faces, "array_keys": keys[:24],
                "iface_ids": iface_ids,
                "meta_keys": sorted((a.meta or {}))[:24],
                "vessel": (a.meta or {}).get("vessel_id") or (a.meta or {}).get("vessel"),
                "material": (a.meta or {}).get("material_id") or (a.meta or {}).get("material"),
                "fragment_id": (a.meta or {}).get("fragment_id") or (a.meta or {}).get("clean_fragment_id"),
            }
            rows.append(row)
        info["rows"] = rows
        out[rel] = info
    path = ROOT / "data/a12_reports/_roi_survey.json"
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    for rel, info in out.items():
        if not isinstance(info, dict) or "roles" not in info:
            print(f"{rel}: {info}")
            continue
        print(f"\n=== {rel}  n_assets={info['n_assets']}")
        print("   roles:", info["roles"])
        for row in info["rows"][:12]:
            print("   ", json.dumps({k: v for k, v in row.items() if k != "array_keys"},
                                    ensure_ascii=False, default=str)[:300])
        if len(info["rows"]) > 12:
            print(f"    ... {len(info['rows']) - 12} more rows in the JSON")


if __name__ == "__main__":
    main()
