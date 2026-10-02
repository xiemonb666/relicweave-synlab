"""CPU smoke of the **whole** package in chunks: 3 real steps without the 21 GB allocation (S9).

The defect
----------
The un-chunked CPU smoke does not fit in this machine's RAM: the batch carries every fragment of
the package at once, and ``FeatureBundle.global_rgb`` is ``[F, V, 3, H, W] float32`` -- measured on
``data/a12_exports/trainable``: ``77 x 12 x 3 x 768 x 1024 x 4`` = **8.7 GB** for that one tensor,
plus ``pixel_valid`` (727 MB), the activations and the backward pass: the recorded allocation is
**21.4 GB** (``docs/a12/relation_negatives.md`` §6.3).

What this driver does instead
-----------------------------
It runs the **same** trainer, the same batch builder and the same loss code, but the fragment
scope is split into chunks and the gradient is accumulated across them before one optimizer step
per micro-step, so the resident set is bounded by the largest chunk instead of the whole package.

Supervision semantics are **not** changed:

* every chunk is built from the package's own relation rows with the package's own pool, so a pair
  is positive/negative exactly when the exported table says so;
* a query is trained as soon as its own row is inside the chunk scope; pairs whose other endpoint
  fell outside the chunk are reported as ``pair_valid=False`` by the builder (the same condition
  the un-chunked batch applies to an unobserved fragment), never silently dropped;
* the negative quota is a documented **input** limit (``--negative-quota``), and the report always
  prints the un-sampled denominator next to the sampled one, so a reader can see what was left out
  and how much supervision the step really used.

Peak memory is measured from the OS (``psutil`` when importable, else the process's own
``VmHWM``/``ru_maxrss``), not estimated from tensor shapes.

    python tools/a12_chunked_smoke.py --package <pkg> --steps 3 --chunk-fragments 12 \
        [--negative-quota 4] [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Sequence

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_USAGE = 2

DEFAULT_PACKAGE = "data/a12_exports/trainable/next_experiment/training_package"


def peak_rss_mb() -> float:
    """Peak resident set size of this process in MiB, measured by the OS.

    ``psutil`` is preferred because it reports the *current* RSS; on Windows (where the ``resource``
    module does not exist) the Win32 working-set query is used instead, so peak memory is a real
    OS number rather than a sum of tensor shapes.
    """
    try:
        import psutil                                      # type: ignore[import-not-found]

        return float(psutil.Process().memory_info().rss) / (1024.0 * 1024.0)
    except Exception:                                      # pragma: no cover - optional dep
        pass
    try:
        import resource                                    # type: ignore[import-not-found]

        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if sys.platform == "darwin" or sys.platform.startswith("win"):
            return float(usage) / (1024.0 * 1024.0)
        return float(usage) / 1024.0
    except Exception:
        pass
    if sys.platform.startswith("win"):                     # pragma: no cover - Windows only
        try:
            import ctypes
            from ctypes import wintypes

            class _Counters(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                            ("PeakWorkingSetSize", ctypes.c_size_t),
                            ("WorkingSetSize", ctypes.c_size_t),
                            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                            ("PagefileUsage", ctypes.c_size_t),
                            ("PeakPagefileUsage", ctypes.c_size_t)]

            counters = _Counters()
            counters.cb = ctypes.sizeof(_Counters)
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            if ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters),
                                                        counters.cb):
                return float(counters.PeakWorkingSetSize) / (1024.0 * 1024.0)
        except Exception:
            pass
    return float("nan")


def _lineage_of(fragment_id: str) -> str:
    return fragment_id.rsplit("_E", 1)[0] if "_E" in fragment_id else fragment_id


def chunk_scope(fragment_ids: Sequence[str], *, chunk_fragments: int,
                by_lineage: bool) -> list[list[str]]:
    """Split the fragment scope into chunks.

    ``by_lineage`` keeps every event (all its fragments) inside one chunk, which is the natural
    unit of a cut: a query and its mate/negatives stay together, so no pair is split across chunks.
    """
    ids = list(fragment_ids)
    if by_lineage:
        groups: dict[str, list[str]] = {}
        for fragment_id in ids:
            groups.setdefault(_lineage_of(fragment_id), []).append(fragment_id)
        ordered = [sorted(members) for _key, members in sorted(groups.items())]
        # Pack whole events into chunks.  A chunk must contain **both endpoints of at least one
        # relation row**, otherwise it builds no encodable pair at all: measured with
        # ``--chunk-fragments 4`` (13 chunks of 4) and ``6`` (12 chunks of 6), every chunk reported
        # ``no_effective_query_in_chunk`` -- cutting *inside* an event leaves only half a pair.
        # A chunk smaller than the smallest event therefore cannot train, so the size is honoured
        # only down to one event and the report says which size was really used.
        size = max(int(chunk_fragments), 1)
        chunks: list[list[str]] = []
        current: list[str] = []
        for group in ordered:
            if current and (len(current) + len(group) > size):
                chunks.append(current)
                current = []
            current.extend(group)
        if current:
            chunks.append(current)
        return chunks
    size = max(int(chunk_fragments), 1)
    return [ids[i:i + size] for i in range(0, len(ids), size)]


def build_rows_for_scope(package: Any, fragment_ids: Sequence[str],
                         pool: Any) -> list[dict[str, Any]]:
    """The package's own rows, restricted to a chunk scope (same helpers as the loader)."""
    from synlab.qc.loader_probe import _batch_rows

    relations = package.relations()
    return _batch_rows(relations, list(fragment_ids), pool)


def cap_negatives(rows: Sequence[dict[str, Any]], quota: int | None
                  ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Apply a documented per-query negative quota, reporting both denominators."""
    if quota is None:
        return [dict(row) for row in rows], {
            "quota": None, "rows": len(rows),
            "negatives_before": int(sum(len(row.get("negatives") or []) for row in rows)),
            "negatives_after": int(sum(len(row.get("negatives") or []) for row in rows)),
            "queries_losing_negatives": 0,
        }
    out: list[dict[str, Any]] = []
    before = after = losing = 0
    for row in rows:
        negatives = list(row.get("negatives") or [])
        before += len(negatives)
        if len(negatives) > int(quota):
            # deterministic, documented order: the exported table's own order (sorted upstream)
            negatives = negatives[: int(quota)]
            losing += 1
        after += len(negatives)
        out.append({**row, "negatives": negatives})
    return out, {"quota": int(quota), "rows": len(rows),
                 "negatives_before": before, "negatives_after": after,
                 "queries_losing_negatives": losing}


def run(package_dir: str | Path, *, steps: int = 3, chunk_fragments: int = 12,
        negative_quota: int | None = None, by_lineage: bool = True,
        token_budget: int = 256) -> dict[str, Any]:
    """Run ``steps`` real optimizer steps over the whole package, one chunk at a time."""
    import torch

    from synlab.qc.loader_probe import load_features
    from synlab.storage.export import TrainingPackage
    from synlab.training.adapter import FeatureBundle
    from synlab.training.batch import build_training_batch
    from synlab.training.labels import PackageLabelSource
    from synlab.training.model import build_model
    from synlab.training.smoke import (SMOKE_SPEC, TrainingPoolView, _batch_facts, _model_digest,
                                       _parameter_counts, _shape_of_pool, _SpecView, _pool_id)
    from synlab.training.trainer import Trainer

    root = Path(package_dir)
    package = TrainingPackage(root)
    report: dict[str, Any] = {"package": str(root), "steps_requested": int(steps),
                              "chunk_fragments": int(chunk_fragments),
                              "negative_quota": negative_quota, "by_lineage": bool(by_lineage),
                              "ram_budget_mb": 0.0, "steps": [], "ok": False}
    relations = package.relations()
    queries = package.queries()
    fragment_ids = [str(row.get("fragment_id") or "") for row in queries]
    fragment_ids = [f for f in dict.fromkeys(fragment_ids) if f]
    for candidate in sorted({str(r.get("candidate", "")) for r in relations
                             if r.get("candidate")}):
        if candidate not in fragment_ids:
            fragment_ids.append(candidate)
    pool_ids = list(fragment_ids)
    chunks = chunk_scope(pool_ids, chunk_fragments=chunk_fragments, by_lineage=by_lineage)
    report["scope"] = {
        "fragments_total": len(pool_ids),
        "chunks": [{"n_fragments": len(chunk), "fragments": chunk} for chunk in chunks],
        "n_chunks": len(chunks),
        "requested_chunk_fragments": int(chunk_fragments),
        "effective_chunk_fragments": max((len(chunk) for chunk in chunks), default=0),
        "chunking_unit": ("event/lineage: a chunk always carries whole events, because a chunk "
                          "that cuts inside an event has no pair to train on (measured)"),
        "relations_rows": len(relations),
        "queries_rows": len(queries),
    }

    # one model + trainer for the whole run, so the steps are a real optimisation, not 3 restarts.
    # ``_shape_of_pool`` reads ``pool.features``, so the first chunk's payloads must be attached
    # before the model is built -- otherwise the quality branch is built with the fallback width
    # and the first forward pass fails on a shape mismatch (8x2 vs 12x32).
    pool = TrainingPoolView(relations, lineup=pool_ids, pool_id=_pool_id(relations))
    first_payloads = load_features(package, chunks[0], token_budget=token_budget)
    pool.features = first_payloads
    FeatureBundle.from_dict(first_payloads, token_budget=token_budget).check_shapes()
    dims = _shape_of_pool(pool)
    model = build_model(seed=int(SMOKE_SPEC["train_seed"]), **dims)
    out_dir = root.parent / "_chunked_smoke"
    trainer = Trainer(_SpecView(SMOKE_SPEC), model, pool=pool, out_dir=out_dir,
                      release_hash=str(package.manifest.get("manifest_hash") or ""),
                      label_source=PackageLabelSource.from_package(package),
                      recipe={"smoke": True, "chunked": True,
                              "package_id": package.manifest.get("package_id")})
    report["model"] = {"parameters": _parameter_counts(model),
                       "initial_param_digest": _model_digest(model),
                       "torch_version": torch.__version__,
                       "cuda_available": bool(torch.cuda.is_available()),
                       "quality_input_dim": dims["quality_input_dim"],
                       "quality_target_dim": dims["quality_target_dim"]}
    report["model"]["index_identity"] = model.index_identity()
    pool.features = {}
    del first_payloads

    totals = {"positives": 0, "negatives": 0, "negatives_before_quota": 0,
              "effective_queries": 0, "encodable_pairs": 0, "unencodable_pairs": 0}
    t0 = time.perf_counter()
    for step in range(int(steps)):
        step_record: dict[str, Any] = {"step": step, "chunks": [], "seconds": None}
        trainer.optimizer.zero_grad(set_to_none=True)
        loss_weight = 0.0
        for chunk_index, chunk in enumerate(chunks):
            payloads = load_features(package, chunk, token_budget=token_budget)
            bundle = FeatureBundle.from_dict(payloads, token_budget=token_budget).check_shapes()
            pool.features = payloads
            rows = build_rows_for_scope(package, chunk, pool)
            limited, quota_info = cap_negatives(rows, negative_quota)
            if not limited:
                step_record["chunks"].append({"chunk": chunk_index, "rows": 0,
                                              "skipped": "no_relation_row_in_scope"})
                continue
            batch = build_training_batch(
                bundle, pool=pool, rows=limited, labels={}, meta={"chunked_smoke": True})
            facts = _batch_facts(batch)
            effective = int(batch.effective_query_count())
            if effective <= 0:
                # no valid supervision in this chunk: skip it explicitly instead of
                # contributing a zero-mass gradient
                step_record["chunks"].append({
                    "chunk": chunk_index, "fragments": len(chunk), "rows": len(limited),
                    "skipped": "no_effective_query_in_chunk", "quota": quota_info})
                del batch, bundle, payloads
                continue
            weight = float(effective)
            info = trainer.train_step(batch, accumulate=weight)
            if info.get("skipped"):
                step_record["chunks"].append({
                    "chunk": chunk_index, "rows": len(limited), "fragments": len(chunk),
                    "skipped": info.get("reason"), "quota": quota_info})
                continue
            loss_weight += weight
            totals["positives"] += facts["positives"]
            totals["negatives"] += facts["negatives"]
            totals["negatives_before_quota"] += quota_info["negatives_before"]
            totals["effective_queries"] += effective
            totals["encodable_pairs"] += int(info.get("encodable_pairs") or 0)
            totals["unencodable_pairs"] += int(info.get("unencodable_pairs") or 0)
            step_record["chunks"].append({
                "chunk": chunk_index, "fragments": len(chunk), "rows": len(limited),
                "loss": float(info["loss"]), "effective_queries": effective,
                "positives": facts["positives"], "negatives": facts["negatives"],
                "n_candidates": facts["n_candidates"],
                "peak_rss_mb": peak_rss_mb(), "quota": quota_info})
            del batch, bundle, payloads
        if loss_weight <= 0:
            step_record["skipped"] = "no_encodable_chunk_in_scope"
            report["steps"].append(step_record)
            break
        params = [p for group in trainer.optimizer.param_groups for p in group["params"]]
        # ``train_step(accumulate=n)`` scales the loss by ``n``, so the gradients hold
        # ``sum_m n_m * dL_m``; divide by ``sum_m n_m`` for the exact effective-query-weighted mean
        # -- the same normalisation ``Trainer.fit`` applies (``trainer.py``: "gradients hold
        # sum_m (n_m * dL_m); divide by sum_m n_m for the weighted mean").
        for group in trainer.optimizer.param_groups:
            for parameter in group["params"]:
                if parameter.grad is not None:
                    parameter.grad.mul_(1.0 / loss_weight)
        grad_norm = torch.nn.utils.clip_grad_norm_(params, trainer.clip_norm)
        step_record["grad_norm"] = float(grad_norm)
        step_record["grad_finite"] = bool(torch.isfinite(grad_norm))
        trainer.optimizer.step()
        trainer.scheduler.step()
        trainer.step_index += 1
        step_record["optimizer_steps"] = int(trainer.step_index)
        step_record["param_digest"] = _model_digest(trainer.model)
        step_record["seconds"] = time.perf_counter() - t0
        step_record["peak_rss_mb"] = peak_rss_mb()
        report["steps"].append(step_record)
    report["seconds"] = time.perf_counter() - t0
    report["optimizer_steps"] = int(trainer.step_index)
    report["final_param_digest"] = _model_digest(trainer.model)
    report["totals"] = totals
    report["peak_rss_mb"] = peak_rss_mb()
    report["denominators"] = {
        "note": ("the same numbers for the un-chunked scope are in the package's data card; here "
                 "they are summed over the chunks that were really trained in each step"),
        "positives": totals["positives"],
        "negatives_used": totals["negatives"],
        "negatives_before_quota": totals["negatives_before_quota"],
        "effective_queries": totals["effective_queries"],
    }
    report["ok"] = bool(report["optimizer_steps"] >= int(steps))
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", default=DEFAULT_PACKAGE)
    parser.add_argument("--steps", type=int, default=3)
    parser.add_argument("--chunk-fragments", type=int, default=12)
    parser.add_argument("--negative-quota", type=int, default=None,
                        help="cap negatives per query (documented input limit; the report prints "
                             "both denominators)")
    parser.add_argument("--no-lineage-chunks", action="store_true",
                        help="chunk by consecutive fragment id instead of by lineage/event")
    parser.add_argument("--json", default=None)
    parser.add_argument("--token-budget", type=int, default=256)
    args = parser.parse_args(argv)

    package = Path(args.package)
    if not (package / "export_manifest.json").is_file():
        print(f"not a training package: {package}", file=sys.stderr)
        return EXIT_USAGE
    report = run(package, steps=args.steps, chunk_fragments=args.chunk_fragments,
                 negative_quota=args.negative_quota, by_lineage=not args.no_lineage_chunks,
                 token_budget=args.token_budget)
    print(f"package          : {report['package']}")
    print(f"scope            : {report['scope']['fragments_total']} fragments in "
          f"{report['scope']['n_chunks']} chunk(s) of <= {report['chunk_fragments']}")
    print(f"negative quota   : {report['negative_quota']}")
    print(f"optimizer steps  : {report['optimizer_steps']} / {report['steps_requested']}")
    print(f"wall seconds     : {report['seconds']:.1f}")
    print(f"peak RSS         : {report['peak_rss_mb']:.0f} MiB")
    for step in report["steps"]:
        if step.get("skipped"):
            print(f"  step {step['step']}: SKIPPED ({step['skipped']})")
            continue
        print(f"  step {step['step']}: {len(step['chunks'])} chunk(s), "
              f"grad_norm={step.get('grad_norm'):.4g}, {step['seconds']:.1f}s, "
              f"peak {step.get('peak_rss_mb', 0):.0f} MiB")
    print(f"totals           : {report['totals']}")
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
                                   encoding="utf-8")
        print(f"wrote {args.json}")
    return EXIT_OK if report["ok"] else EXIT_REFUSED


if __name__ == "__main__":
    raise SystemExit(main())
