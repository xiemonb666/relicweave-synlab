#!/usr/bin/env python
"""Training smoke on a **fragment subset** of an exported package (real losses, small batch).

Why a subset and not ``synlab.training.smoke --package <dir>``
--------------------------------------------------------------
``synlab.training.smoke`` stacks **every** fragment of the package into one feature bundle.  For
``data/a12_exports/negfix/next_experiment/training_package`` that is 59 observed fragments of
12 views each (896 MB of delivered RGB as uint8, ~3.6 GB as the float32 the bundle carries) and
the backward pass then asked the CPU allocator for 21.4 GB -- measured, the full-package smoke
died in ``trainer.train_step -> backward`` with ``DefaultCPUAllocator: not enough memory``
(``data/a12_neg/_smoke_negfix.txt``).  That is a *resource* limit, not a supervision problem: the
batch itself was built, and it carried the real negatives (440).

This driver therefore runs the **same** code path (``smoke.load_real_inputs`` helpers,
``smoke.TrainingPoolView``, ``qc.loader_probe._batch_rows``, ``Trainer.build_batch``,
``smoke._run_step``) on an explicit fragment subset -- the minimal trainable set the mate-absent
rule leaves in the package: one query, its encodable R2 positive and its legal negatives.  Every
number it prints (per-task ``loss``/``n_allowed``, ``effective_queries``, ``z_valid``) comes from
that run; nothing is synthesised and no mask is relaxed.

Usage::

    python tools/negfix_train_smoke.py --package <dir> --steps 3 \
        --query LIN0101_V16_M12_PAT12_E01-m --out data/a12_reports/negfix_smoke_subset.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Sequence

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_PACKAGE = "data/a12_exports/negfix/next_experiment/training_package"
DEFAULT_QUERY = "LIN0101_V16_M12_PAT12_E01-m"


def _jsonable(value: Any) -> Any:
    from synlab.storage.export import _jsonable as convert

    return convert(value)


def run(package_dir: str | Path, *, query: str, steps: int, token_budget: int,
        extra_negatives: int) -> dict[str, Any]:
    from synlab.qc.loader_probe import _batch_rows, _pool_id, load_features
    from synlab.storage.export import TrainingPackage
    from synlab.training import smoke
    from synlab.training.api import _SpecView, _shape_of_pool
    from synlab.training.labels import PackageLabelSource
    from synlab.training.model import build_model
    from synlab.training.trainer import Trainer

    torch = __import__("torch")
    started = time.perf_counter()
    package = TrainingPackage(package_dir)
    verify = package.verify_files()
    relations = package.relations()
    queries = package.queries()

    # ---- the subset: the query, its R2 positives and its legal negatives ----------------
    positives = sorted({str(r["candidate"]) for r in relations
                        if str(r["query"]) == query and str(r["kind"]) == "R2"
                        and bool(r.get("valid"))})
    negatives = sorted({str(r["candidate"]) for r in relations
                        if str(r["query"]) == query and str(r["kind"]) in ("R0", "R1")
                        and bool(r.get("valid")) and bool(r.get("loss_mask"))})
    subset = [str(query), *positives, *negatives[: max(int(extra_negatives), 0)]]
    subset = [fid for fid in dict.fromkeys(subset) if fid]
    report: dict[str, Any] = {
        "schema": "synlab.negfix.train_smoke.v1",
        "package_dir": str(package_dir), "query": str(query), "steps_requested": int(steps),
        "fragment_subset": subset,
        "selection": {
            "positives_of_query": positives, "legal_negatives_of_query": negatives,
            "negatives_used": subset[1 + len(positives):],
            "rule": ("ordinary negatives are the rows with kind in {R1,R0} and valid and "
                     "loss_mask; on this package those are exactly the mate-absent candidates "
                     "(synlab.relations.mate_absent)"),
        },
        "package": {"files_verified": bool(verify["ok"]), "files_checked": verify["files_checked"],
                    "relations": len(relations), "queries": len(queries),
                    "relation_kinds": _kind_histogram(relations)},
        "device": "cuda" if torch.cuda.is_available() else "cpu",
        "torch_version": torch.__version__,
        "ok": False,
    }

    payloads = load_features(package, subset, token_budget=token_budget)
    pool = smoke.TrainingPoolView(relations, lineup=subset, pool_id=_pool_id(relations))
    pool.features = payloads
    rows = _batch_rows(relations, subset, pool)
    dims = _shape_of_pool(pool)
    model = build_model(seed=int(smoke.SMOKE_SPEC["train_seed"]), **dims)
    spec = _SpecView(smoke.SMOKE_SPEC)
    label_source = PackageLabelSource.from_package(package)
    manifest = package.manifest
    release_hash = str(manifest.get("release_manifest_hash") or manifest.get("manifest_hash") or "")
    trainer = Trainer(spec, model, pool=pool, out_dir=None, release_hash=release_hash,
                      label_source=label_source,
                      recipe={"smoke_subset": True, "package_id": manifest.get("package_id")})
    batch = trainer.build_batch(smoke._sample_spec(rows, pool))
    facts = smoke._batch_facts(batch)
    report["batch"] = {k: v for k, v in facts.items() if k != "rows"}
    report["batch"]["rows"] = facts["rows"]
    report["batch"]["fragment_ids"] = list(batch.features.fragment_ids)
    report["encodability"] = {
        "fragments": int(batch.features.n_fragments),
        "observed": int(np.count_nonzero(np.asarray(batch.features.tokens_total) > 0)),
        "tokens_total": int(np.sum(np.asarray(batch.features.tokens_total))),
        "points_valid": int(np.asarray(batch.features.point_valid).sum()),
    }

    records = [smoke._run_step(trainer, batch) for _ in range(int(steps))]
    report["steps"] = {
        "optimizer_steps_taken": int(trainer.step_index),
        "records": records,
        "loss_sequence": [r.get("loss") for r in records],
        "grad_norm_sequence": [r.get("grad_norm") for r in records],
    }
    report["supervision"] = _jsonable(records[0].get("supervision") or {})
    report["ok"] = bool(records) and not records[0]["skipped"] and all(
        r.get("loss") is not None and np.isfinite(r["loss"]) for r in records)
    report["status"] = ("RANK_TASK_TRAINED_ON_REAL_NEGATIVES" if report["ok"]
                        else "FAILED_OR_SKIPPED")
    report["wall_seconds"] = time.perf_counter() - started
    return report


def _kind_histogram(rows: Sequence[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in rows:
        key = str(row.get("kind"))
        out[key] = out.get(key, 0) + 1
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="negfix_train_smoke")
    parser.add_argument("--package", default=DEFAULT_PACKAGE)
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument("--steps", type=int, default=3)
    parser.add_argument("--token-budget", type=int, default=256)
    parser.add_argument("--negatives", type=int, default=4,
                        help="how many of the query's legal negatives to load")
    parser.add_argument("--out", default="data/a12_reports/negfix_smoke_subset.json")
    args = parser.parse_args(argv)

    try:
        report = run(args.package, query=args.query, steps=args.steps,
                     token_budget=args.token_budget, extra_negatives=args.negatives)
    except BaseException as exc:                              # noqa: BLE001 - never hide a crash
        report = {"ok": False, "status": "CRASHED",
                  "escaped_exception": f"{type(exc).__name__}: {exc}",
                  "traceback": traceback.format_exc()[-4000:]}
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str),
                                  encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        return 1
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(_jsonable(report), ensure_ascii=False, indent=2,
                                          sort_keys=True, default=str), encoding="utf-8")
    print(json.dumps({k: v for k, v in _jsonable(report).items() if k != "steps"},
                     ensure_ascii=False, indent=2, default=str))
    for record in report["steps"]["records"]:
        print(f"step loss={record.get('loss')} grad_norm={record.get('grad_norm')} "
              f"effective_queries={record.get('effective_queries')} "
              f"encodable_pairs={record.get('encodable_pairs')}")
        for name, task in (record.get("tasks") or {}).items():
            print(f"  {name:<15} skipped={task['skipped']:<5} loss={task['loss']} "
                  f"n_valid={task['n_valid']} n_allowed={task['n_allowed']} "
                  f"weight={task['weight']} reason={task['reason']}")
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
