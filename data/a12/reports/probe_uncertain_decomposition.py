"""Decompose the delivered `uncertain_mask` of one observation: which rule marked each pixel?

Rules in `synlab.observe.render.render_view`:
    uncertain = (mixed_id | mixed_tag | coc > spec.coc_px_threshold) & (id_map >= 0)
    uncertain |= (~isfinite(depth)) & (id_map >= 0)
and `circle_of_confusion_px(depth, focus, 1.0, f_px)` is always evaluated with aperture
``f_number = 1.0``, whatever the camera profile declares.

This script recomputes the CoC from the committed depth/K and compares, pixel by pixel, the
recomputed predicates with the committed mask, so the dominant rule is a measurement.

Usage: python data/a12/reports/probe_uncertain_decomposition.py --store <path> --obs <asset_id>
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

from synlab.observe.render import circle_of_confusion_px  # noqa: E402
from synlab.storage.store import AssetStore  # noqa: E402


def decompose(store: AssetStore, obs_id: str, *, declared_f_number: float = 8.0) -> dict:
    record = store.get_asset(obs_id)
    arrays = store.load_arrays(obs_id)
    meta = dict(record.meta or {})
    views_meta = meta.get("views") or []
    out: dict = {"obs_asset": obs_id, "views": []}
    for index, view_meta in enumerate(views_meta):
        prefix = f"v{index:03d}."
        if prefix + "depth_z" not in arrays:
            continue
        depth = np.asarray(arrays[prefix + "depth_z"], dtype=np.float64)
        id_map = np.asarray(arrays[prefix + "id_map"])
        uncertain = np.asarray(arrays[prefix + "uncertain_mask"], dtype=bool)
        mask = np.asarray(arrays[prefix + "deployment_mask"], dtype=bool)
        K = np.asarray(arrays[prefix + "K"], dtype=np.float64)
        object_px = id_map >= 0
        focus = float(view_meta.get("working_distance_mm") or 0.0)
        f_px = 0.5 * (float(K[0, 0]) + float(K[1, 1]))
        coc_f1 = circle_of_confusion_px(depth, focus, 1.0, f_px)
        coc_declared = circle_of_confusion_px(depth, focus, float(declared_f_number), f_px)
        row = {
            "view": index, "view_id": view_meta.get("view_id"),
            "working_distance_mm": focus, "f_px": f_px,
            "mm_per_px": float(focus / max(float(K[0, 0]), 1e-9)),
            "object_px": int(np.count_nonzero(object_px)),
            "uncertain_px_on_object": int(np.count_nonzero(uncertain & object_px)),
            "uncertain_ratio": float(np.count_nonzero(uncertain & object_px)
                                     / max(int(np.count_nonzero(object_px)), 1)),
            "mask_px": int(np.count_nonzero(mask)),
            "mask_over_object": float(np.count_nonzero(mask)
                                      / max(int(np.count_nonzero(object_px)), 1)),
            "coc_f1_p50_px": float(np.nanpercentile(coc_f1[object_px], 50)) if object_px.any() else None,
            "coc_f1_p95_px": float(np.nanpercentile(coc_f1[object_px], 95)) if object_px.any() else None,
            "coc_declared_p50_px": float(np.nanpercentile(coc_declared[object_px], 50)) if object_px.any() else None,
            "coc_declared_p95_px": float(np.nanpercentile(coc_declared[object_px], 95)) if object_px.any() else None,
            "depth_span_mm": float(np.nanmax(depth[object_px]) - np.nanmin(depth[object_px])) if object_px.any() else None,
            "nonfinite_depth_on_object_px": int(np.count_nonzero(object_px & ~np.isfinite(depth))),
        }
        # rule agreement: the committed threshold is the pipeline's declared*declared_f_number
        for threshold in (0.75, 0.75 * declared_f_number, 6.0):
            predicted = (coc_f1 > threshold) & object_px
            row[f"coc_f1_gt_{threshold:g}_px"] = int(np.count_nonzero(predicted))
            row[f"agreement_coc_f1_gt_{threshold:g}"] = float(
                np.mean(predicted == (uncertain & object_px)))
        declared_pred = (coc_declared > 0.75) & object_px
        row["coc_declared_gt_0.75_px"] = int(np.count_nonzero(declared_pred))
        row["agreement_coc_declared"] = float(np.mean(declared_pred == (uncertain & object_px)))
        out["views"].append(row)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", default="data/a12_exports/closed_loop/store")
    parser.add_argument("--obs", default="asset_dc7ee32fda6da99aba68")
    parser.add_argument("--f-number", type=float, default=8.0)
    parser.add_argument("--out", default="data/a12/reports/uncertain_decomposition.json")
    args = parser.parse_args()
    report = decompose(AssetStore(Path(args.store)), args.obs, declared_f_number=args.f_number)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
