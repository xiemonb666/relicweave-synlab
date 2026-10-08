"""Measure why `visible_labels` assets fail QA (empty visible foreground / no visible sample).

Read-only probe over a store: for every `visible_labels` asset it prints the committed QA
block, the per-view counters actually stored in the asset, and the delivered observation's
deployment-mask fill ratio (the "foreground mask is empty" claim in docs/a12/closed_loop.md
must be replaced by a measurement either way).

Usage:  python data/a12/reports/probe_visible_masks.py [--store PATH] [--out PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synlab.roles import ROLE_OBS_RESULT, ROLE_VISIBLE_LABELS  # noqa: E402
from synlab.storage.store import AssetStore  # noqa: E402


def _mask_stats(store: AssetStore, asset_id: str) -> dict:
    arrays = store.load_arrays(asset_id)
    keys = sorted(arrays)
    masks = {k: arrays[k] for k in keys if k.endswith(".deployment_mask")}
    out: dict = {"arrays": keys, "views": len(masks), "per_view": []}
    for key in sorted(masks):
        mask = np.asarray(masks[key], dtype=bool)
        total = int(mask.size)
        nonzero = int(np.count_nonzero(mask))
        out["per_view"].append({
            "key": key, "shape": [int(x) for x in mask.shape], "pixels": total,
            "foreground_pixels": nonzero,
            "foreground_ratio": float(nonzero / total) if total else 0.0,
        })
    if masks:
        all_mask = np.stack([np.asarray(masks[k], dtype=bool) for k in sorted(masks)], axis=0)
        out["any_view_foreground"] = bool(all_mask.any())
        out["union_foreground_pixels"] = int(np.count_nonzero(all_mask.any(axis=0)))
        out["mean_view_foreground_ratio"] = float(
            np.mean([row["foreground_ratio"] for row in out["per_view"]]))
    return out


def probe(store_root: Path, limit: int = 50) -> dict:
    store = AssetStore(store_root)
    report: dict = {"store": str(store_root), "visible_labels": [], "summary": {}}
    for record in store.list_assets(role=ROLE_VISIBLE_LABELS, limit=limit):
        entry: dict = {
            "asset_id": record.asset_id, "qa_status": record.qa_status,
            "lineage_id": record.lineage_id, "split": record.split,
            "ancestry": list(record.ancestry or []),
            "qa": {k: v for k, v in (record.qa or {}).items() if k != "notes"},
            "meta_keys": sorted(record.meta or {}),
            "truth_incomplete": bool((record.meta or {}).get("truth_incomplete", False)),
            "observation_id": (record.meta or {}).get("observation_id"),
            "per_view": (record.meta or {}).get("per_view"),
        }
        arrays = store.load_arrays(record.asset_id)
        for key in ("visible_correspondence_visible_counts",
                    "visible_correspondence_projected_counts",
                    "correspondence_visible_counts", "correspondence_projected_counts"):
            if key in arrays:
                arr = np.asarray(arrays[key])
                entry[key] = {
                    "n": int(arr.size),
                    "nonzero": int(np.count_nonzero(arr)),
                    "max": int(arr.max()) if arr.size else 0,
                }
        entry["payload_arrays"] = sorted(arrays)
        obs_id = None
        for ancestor in record.ancestry or []:
            try:
                candidate = store.get_asset(ancestor)
            except Exception:
                continue
            if candidate.role == ROLE_OBS_RESULT:
                obs_id = candidate.asset_id
                entry["observation"] = {
                    "asset_id": candidate.asset_id, "qa_status": candidate.qa_status,
                    "meta_views": len((candidate.meta or {}).get("views") or []),
                    "meta_keys": sorted(candidate.meta or {}),
                }
                entry["observation"].update(_mask_stats(store, candidate.asset_id))
                break
        if obs_id is None:
            entry["observation"] = {"error": "no obs_result ancestor"}
        report["visible_labels"].append(entry)
    qa_counts: dict = {}
    for row in report["visible_labels"]:
        qa_counts[row["qa_status"]] = qa_counts.get(row["qa_status"], 0) + 1
    report["summary"] = {
        "visible_labels_assets": len(report["visible_labels"]),
        "qa_status": qa_counts,
        "qa_fail": [row["asset_id"] for row in report["visible_labels"]
                    if row["qa_status"] == "QA_FAIL"],
        "all_have_foreground": all(
            bool((row.get("observation") or {}).get("any_view_foreground"))
            for row in report["visible_labels"]),
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", default="data/a12_exports/closed_loop/store")
    parser.add_argument("--out", default="data/a12/reports/visible_labels_mask_probe.json")
    args = parser.parse_args()
    report = probe(Path(args.store))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    for row in report["visible_labels"]:
        obs = row.get("observation") or {}
        print(f"{row['asset_id']} qa={row['qa_status']} "
              f"truth_incomplete={row['truth_incomplete']} "
              f"obs={obs.get('asset_id')} views={obs.get('views')} "
              f"fg_ratio={obs.get('mean_view_foreground_ratio')} "
              f"union_fg={obs.get('union_foreground_pixels')} "
              f"qa_samples_visible={row['qa'].get('samples_visible')} "
              f"qa_samples_projected={row['qa'].get('samples_projected')} "
              f"qa_failures={row['qa'].get('failures')}")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=1))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
