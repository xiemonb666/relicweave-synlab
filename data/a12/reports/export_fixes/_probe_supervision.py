"""Probe: build a REAL batch from a package and report per-task n_valid/n_allowed.

Run:  .venv\\Scripts\\python.exe data\\a12\\reports\\export_fixes\\_probe_supervision.py <package_dir>
No torch: only the numpy paths of ``synlab.qc.loader_probe`` / ``synlab.training.batch``.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from synlab.qc.loader_probe import ExportedRelationPool, _batch_rows, _pool_id, load_features  # noqa: E402
from synlab.storage.export import TrainingPackage  # noqa: E402
from synlab.training.adapter import FeatureBundle  # noqa: E402
from synlab.training.batch import build_training_batch, negative_audit  # noqa: E402
from synlab.training.supervision import supervision_accounting  # noqa: E402


def main(package_dir: str, max_fragments: int | None = None) -> int:
    package = TrainingPackage(package_dir)
    verify = package.verify_files()
    relations = package.relations()
    queries = package.queries()
    print("package", package_dir)
    print("verify", verify["ok"], verify["files_checked"], verify["problems"][:3])
    print("relations", len(relations), "queries", len(queries))

    fragment_ids = [str(r.get("fragment_id") or "") for r in queries]
    fragment_ids = [f for f in dict.fromkeys(fragment_ids) if f]
    if max_fragments:
        fragment_ids = fragment_ids[:max_fragments]
    candidates = sorted({str(r.get("candidate", "")) for r in relations if r.get("candidate")})
    for candidate in candidates:
        if candidate not in fragment_ids:
            fragment_ids.append(candidate)
    print("batch_fragments", len(fragment_ids))

    payloads = load_features(package, fragment_ids)
    bundle = FeatureBundle.from_dict(payloads).check_shapes()
    pool = ExportedRelationPool(relations, pool_id=_pool_id(relations))
    rows = _batch_rows(relations, fragment_ids, pool)
    batch = build_training_batch(bundle, pool=pool, rows=rows)

    print("bundle local_tokens", bundle.local_tokens.shape, "global_rgb", bundle.global_rgb.shape,
          "points", bundle.points.shape)
    print("batch pair_index", np.asarray(batch.pair_index).shape,
          "corr_weight", np.asarray(batch.corr_weight).shape,
          "quality_target", np.asarray(batch.quality_target).shape)
    print("pos", int(batch.pos_mask.sum()), "neg", int(batch.neg_mask.sum()),
          "effective_queries", int(batch.effective_query_count()))
    print("negative_audit ok:", negative_audit(batch).get("ok"))

    # z_valid: same definition the trainer uses (an observed fragment must carry >=1 valid token)
    z_valid = (np.asarray(bundle.tokens_total) > 0) & (np.asarray(bundle.token_valid).sum(axis=1) > 0)
    report = supervision_accounting(batch, z_valid=z_valid)
    print(json.dumps(report["tasks"], indent=2, ensure_ascii=False, default=str))
    print("pair_mask", json.dumps(report["pair_mask"], ensure_ascii=False, default=str))
    print("tasks_with_supervision", report["tasks_with_supervision"])
    out = Path(__file__).with_name("_probe_supervision.json")
    out.write_text(json.dumps({"tasks": report["tasks"], "pair_mask": report["pair_mask"],
                               "z_valid": int(np.count_nonzero(z_valid)),
                               "bundle_shapes": {"local_tokens": list(bundle.local_tokens.shape),
                                                 "global_rgb": list(bundle.global_rgb.shape),
                                                 "points": list(bundle.points.shape)}},
                              indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print("wrote", out)
    return 0


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "data/a12_exports/closed_loop/training_package"
    raise SystemExit(main(target))
