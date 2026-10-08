"""Decide whether the 3 QA_FAIL `visible_labels` are stale or reproducible with the current
render configuration: read the *committed observation metadata* of each visible label's
observation and print the render spec / mask source / visibility counters that decided it.

Usage: python data/a12/reports/probe_visible_render_spec.py --store <path> [--out <json>]
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

KEYS = ("render_spec", "deployment_mask_source", "backend", "route", "input_profile",
        "scale_valid", "quality", "mm_per_pixel", "frame_id")


def _dig(meta: dict) -> dict:
    out: dict = {}
    for key in KEYS:
        if key in meta:
            out[key] = meta[key]
    inner = meta.get("meta")
    if isinstance(inner, dict):
        for key in KEYS:
            if key in inner and key not in out:
                out[f"meta.{key}"] = inner[key]
    view0 = (meta.get("views") or [{}])[0]
    if isinstance(view0, dict):
        for key in ("view_id", "profile_id", "tier", "working_distance_mm", "focus_setting",
                    "source_kind", "camera_model", "image_size"):
            if key in view0:
                out[f"view0.{key}"] = view0[key]
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", default="data/a12_exports/closed_loop/store")
    parser.add_argument("--out", default="data/a12/reports/visible_labels_render_spec_probe.json")
    args = parser.parse_args()
    store = AssetStore(Path(args.store))
    report: list[dict] = []
    for record in store.list_assets(role=ROLE_VISIBLE_LABELS, limit=50):
        entry = {"visible_asset": record.asset_id, "qa_status": record.qa_status,
                 "lineage_id": record.lineage_id,
                 "samples_visible": (record.qa or {}).get("samples_visible"),
                 "samples_projected": (record.qa or {}).get("samples_projected"),
                 "truth_incomplete": (record.meta or {}).get("truth_incomplete")}
        for ancestor in record.ancestry or []:
            try:
                candidate = store.get_asset(ancestor)
            except Exception:
                continue
            if candidate.role != ROLE_OBS_RESULT:
                continue
            entry["obs_asset"] = candidate.asset_id
            entry["obs_meta"] = _dig(dict(candidate.meta or {}))
            arrays = store.load_arrays(candidate.asset_id)
            per_view = []
            for index in sorted({int(k.split(".")[0][1:]) for k in arrays if k[0] == "v"}):
                p = f"v{index:03d}."
                id_map = np.asarray(arrays[p + "id_map"])
                mask = np.asarray(arrays[p + "deployment_mask"], dtype=bool)
                uncertain = np.asarray(arrays[p + "uncertain_mask"], dtype=bool)
                tag = np.asarray(arrays[p + "surface_tag"])
                obj = id_map >= 0
                per_view.append({
                    "view": index,
                    "object_px": int(np.count_nonzero(obj)),
                    "object_ratio": float(np.mean(obj)),
                    "uncertain_px": int(np.count_nonzero(uncertain)),
                    "uncertain_ratio_of_object": float(
                        np.count_nonzero(uncertain & obj) / max(int(np.count_nonzero(obj)), 1)),
                    "mask_px": int(np.count_nonzero(mask)),
                    "mask_ratio": float(np.mean(mask)),
                    "mask_over_object": float(
                        np.count_nonzero(mask) / max(int(np.count_nonzero(obj)), 1)),
                    "interface_tag_px": int(np.count_nonzero((tag == 2) & obj)),
                    "tag_values": sorted(int(v) for v in np.unique(tag[obj])),
                })
            entry["per_view_geometry"] = per_view
            break
        report.append(entry)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    for entry in report:
        print(f"{entry['visible_asset']} qa={entry['qa_status']} "
              f"visible={entry['samples_visible']}/{entry['samples_projected']} "
              f"obs={entry.get('obs_asset')} meta={json.dumps(entry.get('obs_meta'), default=str)[:400]}")
        for row in entry.get("per_view_geometry") or []:
            print("   ", json.dumps(row))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
