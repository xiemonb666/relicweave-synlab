"""Probe: scope ids recorded for the trainable batch, and the real array keys of the
ROI / extras / context payloads (npz header only -- no full decompression)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, ".")
import numpy as np  # noqa: E402
from synlab.storage.store import AssetStore  # noqa: E402

state = json.loads(Path(
    "data/a12_exports/trainable/next_experiment/next_experiment_export_state.json"
).read_text(encoding="utf-8"))
freeze = state.get("freeze") or {}
print("freeze keys:", sorted(freeze.keys()))
ids = freeze.get("unverified_scope_ids") or []
print("unverified_scope_ids:", len(ids))
print("roles:", json.dumps(freeze.get("unverified_scope_roles"), ensure_ascii=False))
print("release_id:", state.get("release_id"))
print("export step keys:", sorted((state.get("export_training_package") or {}).keys()))
exp = state.get("export_training_package") or {}
print("export status:", exp.get("status"), "package_dir:", exp.get("package_dir"),
      "files:", exp.get("files_total"), "bytes:", exp.get("bytes_total"))

out: dict[str, object] = {}
for name, path in (("roi", "data/a12_roi/store"), ("extras", "data/a12_extras/store"),
                   ("context", "data/a12_context/store"), ("degrade", "data/a12_degrade/store")):
    store = AssetStore(Path(path))
    rows = []
    for a in store.list_assets(limit=500000):
        npz_rel = (a.files or {}).get("arrays")
        keys: list[str] = []
        total = 0
        if npz_rel:
            npz_path = store.root / Path(*npz_rel.split("/"))
            if npz_path.exists():
                total = npz_path.stat().st_size
                with np.load(npz_path, allow_pickle=False) as data:
                    keys = [(k, list(np.shape(data[k])), str(data[k].dtype)) for k in data.files]
        rows.append({"asset_id": a.asset_id, "role": a.role, "schema": a.schema,
                     "unit": a.unit, "frame": a.frame, "lineage": a.lineage_id,
                     "npz_bytes": total, "n_arrays": len(keys),
                     "arrays": [k[0] for k in keys][:60],
                     "shapes": {k[0]: k[1] for k in keys[:60]}})
        meta_path = store.root / "assets" / a.asset_id / "meta.json"
        rows[-1]["meta_bytes"] = meta_path.stat().st_size if meta_path.exists() else 0
    out[name] = rows
    print("=" * 90)
    print(f"{name}: {len(rows)} assets")
    for r in rows:
        if r["role"] in ("obs_result", "context_pack", "degrade_variant", "degrade_source",
                         "feature_bundle", "clean_truth", "label_bundle", "provenance",
                         "physical_component", "physical_truth", "visible_labels"):
            print(f"  {r['role']:<18} {r['asset_id']} npz={r['npz_bytes']/1e6:8.2f}MB "
                  f"n={r['n_arrays']:3d} meta={r['meta_bytes']/1e3:7.1f}kB {r['lineage']}")
            if r["role"] in ("obs_result", "feature_bundle", "context_pack"):
                print("      arrays:", r["arrays"][:40])

Path("data/a12_reports/_merge_array_keys.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True, default=str), encoding="utf-8")
print("wrote data/a12_reports/_merge_array_keys.json")
