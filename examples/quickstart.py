#!/usr/bin/env python
"""Quickstart: from a training package to a **real** supervision report in under 30 seconds.

    python examples/quickstart.py [--package DIR] [--batch-size 2]

What it does, in order (nothing is synthetic, nothing is imported from torch):

1. resolves the package and prints its identity (release, manifest hash, files);
2. loads the relation table + label layers with pandas and shows the real kind histogram;
3. builds a real mini-batch through the *same* code path the trainer uses
   (``synlab.qc.loader_probe`` + ``synlab.training.batch``) and prints the tensor shapes;
4. prints the five-task supervision table (``n_valid`` / ``n_allowed`` and the measured blocker);
5. walks the package with :func:`tools.load_package.iter_batches` and prints each batch;
6. if torch is importable it additionally prints the torch tensor shapes of the first batch --
   otherwise it says so and why (this checkout's torch is being reinstalled by another task, so
   the numpy path is the one that must work).

The whole run is timed; the 30 s budget is checked and reported.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.load_package import (                                   # noqa: E402
    TASKS,
    build_batch,
    iter_batches,
    load_labels,
    load_relations,
    resolve_package,
)

DEFAULT_PACKAGE = REPO_ROOT / "data/a12_exports/closed_loop/training_package"
BUDGET_SECONDS = 30.0


def _package(args: argparse.Namespace) -> Path:
    candidate = Path(args.package) if args.package else DEFAULT_PACKAGE
    if not candidate.exists():
        fallback = candidate.parent / "training_package_v2"
        if fallback.exists():
            print(f"[note] {candidate} does not exist; using {fallback}")
            candidate = fallback
    return resolve_package(candidate)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--package", default=None)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--token-budget", type=int, default=256)
    args = parser.parse_args(argv)
    started = time.perf_counter()

    package = _package(args)
    print(f"package: {package}")

    # ---- 1. identity ---------------------------------------------------------------
    manifest = build_batch(package)["package"].manifest
    print(f"release_id={manifest.get('release_id')} "
          f"package_id={manifest.get('package_id')}")
    print(f"manifest_hash={manifest.get('manifest_hash')}")
    print(f"files={len(manifest.get('files') or [])} bytes_total={manifest.get('bytes_total')}")

    # ---- 2. tables -----------------------------------------------------------------
    relations = load_relations(package)
    kinds = relations["kind"].value_counts().to_dict() if not relations.empty else {}
    print(f"\nrelations: {len(relations)} rows, kinds={kinds}")
    if not relations.empty and "eligible_as_negative" in relations.columns:
        legal = relations[(relations["kind"].isin(["R1", "R0"]))
                          & relations["valid"].astype(bool)
                          & relations["loss_mask"].astype(bool)]
        print(f"  eligible_as_negative (R1/R0 with valid & loss_mask): {legal.shape[0]}")
    for layer in ("clean", "physical", "visible", "quality", "correspondence"):
        try:
            frame = load_labels(package, layer)
        except Exception:                                              # noqa: BLE001
            continue
        if frame.empty:
            print(f"  label layer {layer:<15} absent")
            continue
        extra = ""
        if "kind" in frame.columns:
            extra = f" kinds={frame['kind'].value_counts().to_dict()}"
        print(f"  label layer {layer:<15} {frame.shape[0]:>5} rows{extra}")

    # ---- 3. a real batch -----------------------------------------------------------
    built = build_batch(package, token_budget=args.token_budget)
    batch = built["batch"]
    print("\nreal mini-batch (numpy path, same builders the trainer uses):")
    shapes = {name: tuple(np.asarray(getattr(built["bundle"], name)).shape)
              for name in ("global_rgb", "pixel_valid", "local_tokens", "token_view", "points",
                           "normals", "scale_valid")}
    for name, shape in shapes.items():
        print(f"  {name:<15} {str(shape):<24} "
              f"{np.asarray(getattr(built['bundle'], name)).dtype}")
    if batch is not None:
        print(f"  pair_index      {tuple(np.asarray(batch.pair_index).shape)}   "
              f"corr_weight {tuple(np.asarray(batch.corr_weight).shape)}   "
              f"quality_target {tuple(np.asarray(batch.quality_target).shape)}")
        print(f"  positives={int(np.asarray(batch.pos_mask).sum())} "
              f"negatives={int(np.asarray(batch.neg_mask).sum())} "
              f"effective_queries={int(batch.effective_query_count())}")
    print(f"  fragments={built['provenance']['fragment_ids']}")
    print(f"  z_valid fragments: {int(np.count_nonzero(built['z_valid']))}")

    # ---- 4. supervision ------------------------------------------------------------
    print("\nper-task supervision (trainer's own masks):")
    print(f"  {'task':<16}{'n_valid':>9}{'n_allowed':>11}  blocker")
    tasks = built["supervision"].get("tasks") or {}
    for name in TASKS:
        entry = tasks.get(name)
        if entry is None:
            print(f"  {name:<16}{'missing':>9}{'missing':>11}  the batch reported nothing")
            continue
        blocker = (entry.get("structural") or {}).get("reason") or \
            (entry.get("blocked_by") or ["-"])[0]
        print(f"  {name:<16}{int(entry.get('n_valid', 0)):>9}{int(entry.get('n_allowed', 0)):>11}"
              f"  {blocker if int(entry.get('n_allowed', 0)) == 0 else 'supervised'}")

    # ---- 5. iterate ----------------------------------------------------------------
    print(f"\niter_batches(batch_size={args.batch_size}):")
    for item in iter_batches(package, batch_size=args.batch_size, token_budget=args.token_budget):
        allowed = {name: (item["supervision"]["tasks"].get(name) or {}).get("n_allowed")
                   for name in TASKS} if item["supervision"].get("tasks") else {}
        print(f"  batch {item['index']}: queries={len(item['rows'])} "
              f"fragments={len(item['provenance']['fragment_ids'])} n_allowed={allowed}")

    # ---- 6. torch, only if it really works -----------------------------------------
    print("\ntorch:")
    try:
        import torch

        tensors = built["bundle"].to_torch(device="cpu")
        print(f"  torch {torch.__version__}: "
              f"global_rgb {tuple(tensors.global_rgb.shape)} "
              f"local_tokens {tuple(tensors.local_tokens.shape)} "
              f"points {tuple(tensors.points.shape)}")
        if batch is not None:
            pair = torch.as_tensor(np.asarray(batch.pair_index), dtype=torch.long)
            print(f"  pair_index {tuple(pair.shape)} dtype={pair.dtype}, "
                  f"pos_mask {tuple(torch.as_tensor(np.asarray(batch.pos_mask)).shape)}")
    except Exception as exc:                                           # noqa: BLE001
        print(f"  SKIPPED: torch is not usable in this environment "
              f"({type(exc).__name__}: {str(exc).splitlines()[0][:160]})")
        print("  the numpy path above is the supported one; the torch adapter "
              "(FeatureBundle.to_torch) is ready for when torch imports again")

    elapsed = time.perf_counter() - started
    print(f"\nelapsed {elapsed:.2f} s (budget {BUDGET_SECONDS:.0f} s): "
          f"{'OK' if elapsed <= BUDGET_SECONDS else 'OVER BUDGET'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
