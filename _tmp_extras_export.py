"""Scratch driver: build the sibling package view and export the §8 extras into it.

Layout produced (see docs/a12/synthetic_extras.md for why):

    data/a12_exports/a12_extras/training_package/{deploy,research,...}   <- unmodified exporter
    data/a12_exports/a12_extras/synthetic_extra/                         <- this task

`training_package/` comes from a frozen release of the small `cl_fresh` store because the
new `data/a12_extras/store` has no frozen release (freezing one requires every gate of the
profile to pass).  The extras themselves come from the new store's single lineage.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
sys.stdout.reconfigure(encoding="utf-8")

from synlab.storage.export_extras import export_extras, extras_dir, scan_extras
from synlab.storage.store import AssetStore

PKG = REPO / "data" / "a12_exports" / "a12_extras"
TRAINING = PKG / "training_package"
EXTRAS_STORE = REPO / "data" / "a12_extras" / "store"
SOURCE_STORE = REPO / "data" / "a12_exports" / "cl_fresh" / "store"
SOURCE_RELEASE = "rel_9a5c5a39a8ad_1790909613"
REPORT = REPO / "data" / "a12_reports" / "synthetic_extras_run.json"

LINEAGE = "LIN0000_V01_M01_PAT01"


def build_training_package() -> dict:
    from synlab.storage.export import export_training_package

    if (TRAINING / "export_manifest.json").exists():
        return {"skipped": "already present"}
    store = AssetStore(SOURCE_STORE)
    manifest = export_training_package(store, SOURCE_RELEASE, TRAINING)
    return {"package_id": manifest.get("package_id"),
            "release_id": manifest.get("release_id"),
            "files": len(manifest.get("files", []))}


def main() -> int:
    t0 = time.time()
    report: dict = {"lineage_id": LINEAGE, "package": str(PKG)}
    PKG.mkdir(parents=True, exist_ok=True)

    report["training_package"] = build_training_package()
    report["deploy_and_research_present"] = {
        "deploy": (TRAINING / "deploy").is_dir(),
        "research": (TRAINING / "research").is_dir(),
        "export_manifest": (TRAINING / "export_manifest.json").is_file(),
    }

    store = AssetStore(EXTRAS_STORE)
    index = export_extras(store, PKG, lineage_id=LINEAGE, profile="MID",
                          master_seed=20261001, long_edge_px=128,
                          baseline_mm=60.0, rotation_step_deg=5.0,
                          polarizer_step_deg=15.0, claim_mm=0.1)
    report["export"] = {
        "resolved_targets": index.get("resolved_targets"),
        "totals": index.get("totals"),
        "generate_seconds": index.get("generate_seconds"),
        "generation_failures": index.get("generation_failures"),
        "scan_problems": index.get("problems"),
        "isolation": index.get("isolation"),
    }

    # per-modality, per-array detail straight from the scanned index
    detail = {}
    for row in index.get("rows", {}).values():
        entry = detail.setdefault(row["modality_id"], {"instances": 0, "file_bytes": 0,
                                                       "array_bytes": 0, "arrays": {}})
        entry["instances"] += 1
        entry["file_bytes"] += int(row["file_bytes"])
        entry["array_bytes"] += int(row["array_bytes"])
        for name, meta in row["arrays"].items():
            entry["arrays"][name] = {"shape": meta["shape"], "dtype": meta["dtype"],
                                     "bytes": meta["bytes"]}
    report["per_modality"] = detail

    annotations = {}
    for row in index.get("rows", {}).values():
        ann = row["annotation"]
        annotations.setdefault(row["modality_id"], {
            "rig_obtainable": ann.get("rig_obtainable"),
            "synthetic_only": ann.get("synthetic_only"),
            "rig_source": ann.get("rig_source"),
            "claim_allowed": ann.get("claim_allowed"),
            "unit": ann.get("unit"),
            "frame": ann.get("frame"),
            "seed_path": (ann.get("generator") or {}).get("seed_path"),
            "seconds": (ann.get("generator") or {}).get("seconds"),
            "params": (ann.get("generator") or {}).get("params"),
        })
    report["annotation_fields"] = annotations

    report["seconds_total"] = round(time.time() - t0, 2)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str),
                      encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items()
                      if k not in ("per_modality", "annotation_fields")},
                     ensure_ascii=False, indent=2, default=str))
    print("report ->", REPORT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
