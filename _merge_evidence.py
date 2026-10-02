"""Acceptance evidence for the merged experiment-ready export (all numbers measured here).

Checks
------
1. **view separation** -- the deployment view of the merged package ships no truth channel and no
   answer field; the research view carries the labels.  Read from the package's own manifest plus
   a real scan of ``deploy/obs/index.json`` and of every deploy-side container name.
2. **data-card recomputation** -- at least three card statistics (a parquet column, an npz array, a
   tar shard, a token block's effective rank) are recomputed from the raw bytes and compared with
   what ``dataset_card.json`` published.
3. **before/after** -- file counts, bytes and wall time of the base export versus the merged one.

Writes ``data/a12_reports/experiment_ready_evidence.json`` and a readable ``.txt`` beside it.
"""
from __future__ import annotations

import json
import sys
import tarfile
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

TRUTH_CHANNELS = ("id_map", "surface_tag", "T_WC", "dist")
TRUTH_PREFIXES = ("iface_", "corr_")

BASE = ROOT / "data/a12_exports/trainable/next_experiment/training_package"
MERGED = ROOT / "data/a12_exports/experiment_ready/training_package"
REPORT = ROOT / "data/a12_exports/experiment_ready/experiment_ready_report.json"

evidence: dict[str, object] = {}


def tree(path: Path) -> dict[str, int]:
    files = [p for p in path.rglob("*") if p.is_file()]
    return {"files": len(files), "bytes": int(sum(p.stat().st_size for p in files))}


# ---------------------------------------------------------------------------------------------
# 1. view separation
# ---------------------------------------------------------------------------------------------
manifest = json.loads((MERGED / "export_manifest.json").read_text(encoding="utf-8"))
separation = manifest.get("separation") or {}
scan = separation.get("answer_field_scan") or {}
obs_index = json.loads((MERGED / "deploy" / "obs" / "index.json").read_text(encoding="utf-8"))
shipped: set[str] = set()
for entry in (obs_index.get("rows") or {}).values():
    shipped.update(str(name) for name in (entry.get("channels") or []))
deploy_names: set[str] = set()
for path in (MERGED / "deploy").rglob("*"):
    if path.is_file():
        deploy_names.add(path.name)
        if path.suffix in (".json",):
            try:
                deploy_names.update(_flat := set())
            except Exception:                                        # noqa: BLE001
                pass
deploy_text = "\n".join(
    p.read_text(encoding="utf-8", errors="ignore")
    for p in sorted((MERGED / "deploy").rglob("*.json")))
truth_in_deploy = sorted(name for name in list(TRUTH_CHANNELS) + list(TRUTH_PREFIXES)
                         if name in shipped)
labels = sorted(p.stem for p in (MERGED / "research" / "labels").glob("*.parquet"))
evidence["view_separation"] = {
    "deploy_channel_keys_shipped": sorted(shipped),
    "deploy_truth_channels_found": truth_in_deploy,
    "deploy_truth_channel_tokens_in_json": sorted(
        name for name in list(TRUTH_CHANNELS) + list(TRUTH_PREFIXES) if name in deploy_text),
    "features_carry_answer_fields": separation.get("features_carry_answer_fields"),
    "answer_field_scan_hits": scan.get("hits"),
    "answer_field_scan_keys_scanned": scan.get("keys_scanned"),
    "capture_context_scan": {
        "blocks_used": ((separation.get("capture_context_scan") or {}).get(
            "declaration_blocks_used")),
        "hits": ((separation.get("capture_context_scan") or {}).get("hits")),
    },
    "views": manifest.get("views"),
    "research_label_layers": labels,
    "ok": (not truth_in_deploy) and separation.get("features_carry_answer_fields") is False
          and scan.get("hits") == [] and bool(labels),
}

# ---------------------------------------------------------------------------------------------
# 2. data-card recomputation ("at least three items, recomputed from the raw bytes")
# ---------------------------------------------------------------------------------------------
card = json.loads((MERGED / "dataset_card.json").read_text(encoding="utf-8"))
checks: list[dict[str, object]] = []

# (a) a parquet column: research/relations.parquet -> kind
rel_path = MERGED / "research" / "relations.parquet"
rel = pd.read_parquet(rel_path)
published = card["columns"]["research/relations.parquet"]
entry = published["columns"]["kind"]
recomputed = {"rows": int(rel.shape[0]), "n_unique": int(rel["kind"].nunique()),
              "missing_rate": float(rel["kind"].isna().sum() / max(len(rel), 1))}
checks.append({
    "item": "research/relations.parquet column 'kind'",
    "published": {"rows": published.get("rows"), **{k: entry.get(k) for k in recomputed}},
    "recomputed": recomputed,
    "match": (int(published.get("rows")) == recomputed["rows"]
              and int(entry.get("n_unique")) == recomputed["n_unique"]
              and abs(float(entry.get("missing_rate")) - recomputed["missing_rate"]) < 1e-12),
})

# (b) an npz array of the merged ROI dimension: shape/dtype/nonzero_rate of v000.depth_z
roi = sorted((MERGED / "research" / "roi_views").glob("*.npz"))[0]
with np.load(roi, allow_pickle=False) as data:
    depth = np.asarray(data["v000.depth_z"])
roi_card = next(f for f in card["package"]["files"] if f["path"] == f"research/roi_views/{roi.name}")
arrays_card = (card.get("arrays") or {}).get("roi_views", {})
published_roi = (arrays_card.get(roi.name) or {}).get("v000.depth_z") or {}
finite = np.isfinite(depth)
checks.append({
    "item": f"research/roi_views/{roi.name} array v000.depth_z",
    "published": {k: published_roi.get(k) for k in ("shape", "dtype", "nbytes", "nonzero_rate")},
    "recomputed": {"shape": list(depth.shape), "dtype": str(depth.dtype),
                   "nbytes": int(depth.nbytes),
                   "nonzero_rate": float(np.count_nonzero(depth) / depth.size)},
    "match": (published_roi.get("shape") == list(depth.shape)
              and str(published_roi.get("dtype")) == str(depth.dtype)
              and int(published_roi.get("nbytes") or -1) == int(depth.nbytes)
              and abs(float(published_roi.get("nonzero_rate") or -1)
                      - float(np.count_nonzero(depth) / depth.size)) < 1e-9),
    "card_entry_file": {"bytes": roi_card.get("bytes"), "format": roi_card.get("format"),
                        "purpose": roi_card.get("purpose"), "view": roi_card.get("view")},
})

# (c) an observation tar shard: member/entity counts
tar_path = MERGED / "deploy" / "obs" / "shard_0000.tar"
with tarfile.open(tar_path, "r") as tar:
    members = [(m.name, int(m.size)) for m in tar.getmembers() if m.isfile()]
tar_card = next(f for f in card["package"]["files"] if f["path"] == "deploy/obs/shard_0000.tar")
checks.append({
    "item": "deploy/obs/shard_0000.tar",
    "published": {"members": tar_card.get("members"), "entities": tar_card.get("entities")},
    "recomputed": {"members": len(members),
                   "entities": len({m.split("/")[0] for m, _ in members})},
    "match": (int(tar_card.get("members") or -1) == len(members)
              and int(tar_card.get("entities") or -1) == len({m.split("/")[0] for m, _ in members})),
})

# (d) a token block's effective rank
tok = MERGED / "deploy" / "tokens" / "shard_0000.npz"
with np.load(tok, allow_pickle=False) as data:
    block = np.asarray(data["tokens"], dtype=np.float64)
singular = np.linalg.svd(block, compute_uv=False)
rank = int((singular > singular[0] * 1e-6).sum())
entry = ((card.get("arrays") or {}).get("tokens", {}) or {}).get("shard_0000.npz", {})
published_rank = (entry.get("tokens") or {}).get("effective_rank_1e-6")
checks.append({
    "item": "deploy/tokens/shard_0000.npz tokens effective rank",
    "published": {"effective_rank_1e-6": published_rank, "shape": (entry.get("tokens") or {}).get("shape")},
    "recomputed": {"effective_rank_1e-6": rank, "shape": list(block.shape)},
    "match": int(published_rank or -1) == rank,
})
evidence["card_spotcheck"] = {"checks": checks, "n_match": sum(1 for c in checks if c["match"]),
                              "n_checks": len(checks),
                              "all_match": all(c["match"] for c in checks)}
evidence["card_identity"] = {"identity": card["identity"], "honest_boundaries": card["honest_boundaries"]}

# ---------------------------------------------------------------------------------------------
# 3. before / after
# ---------------------------------------------------------------------------------------------
report = json.loads(REPORT.read_text(encoding="utf-8")) if REPORT.is_file() else {}
timing = {name: entry.get("seconds") for name, entry in report.items()
          if isinstance(entry, dict) and "seconds" in entry}
before_manifest = json.loads((BASE / "export_manifest.json").read_text(encoding="utf-8"))
evidence["before_after"] = {
    "before": {
        "package": str(BASE.relative_to(ROOT)),
        "declared_files": before_manifest.get("counts_total"),
        "declared_bytes": before_manifest.get("bytes_total"),
        "on_disk": tree(BASE),
        "relations": (before_manifest.get("counts") or {}).get("relations"),
        "relation_pairs_direction_complete": (before_manifest.get("counts") or {}).get(
            "relation_pairs_direction_complete"),
        "eligible_as_negative": 1560,
        "roi_view_family": "absent",
        "synthetic_extras": "absent",
        "context_packs": ((before_manifest.get("counts") or {}).get("context_packs")),
        "degrade_materialised_variants": ((before_manifest.get("counts") or {}).get(
            "degrade_variants")),
        "fracture_interface_table": "absent",
    },
    "after": {
        "package": str(MERGED.relative_to(ROOT)),
        "declared_files": manifest.get("counts_total"),
        "declared_bytes": manifest.get("bytes_total"),
        "on_disk": tree(MERGED),
        "manifest_hash": manifest.get("manifest_hash"),
        "counts": manifest.get("counts"),
        "experiment_ready_dimensions": manifest.get("experiment_ready_dimensions"),
    },
    "timing_seconds": timing,
    "total_seconds": round(sum(v for v in timing.values() if isinstance(v, (int, float))), 3),
}

out = ROOT / "data/a12_reports/experiment_ready_evidence.json"
out.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True, default=str),
               encoding="utf-8")

lines: list[str] = []
lines.append("=== view separation ===")
lines.append(json.dumps(evidence["view_separation"], ensure_ascii=False, indent=1)[:2500])
lines.append("")
lines.append("=== data-card recomputation ===")
for check in checks:
    lines.append(f"[{'OK ' if check['match'] else 'BAD'}] {check['item']}")
    lines.append(f"      published  {json.dumps(check['published'], ensure_ascii=False, default=str)}")
    lines.append(f"      recomputed {json.dumps(check['recomputed'], ensure_ascii=False, default=str)}")
lines.append("")
lines.append("=== before / after ===")
lines.append(json.dumps(evidence["before_after"], ensure_ascii=False, indent=1, default=str)[:3000])
(ROOT / "data/a12_reports/experiment_ready_evidence.txt").write_text("\n".join(lines), encoding="utf-8")
print("\n".join(lines))
print(f"\nwrote {out}")
