#!/usr/bin/env python
"""Negative-eligibility fix: before/after cost measurement and the eligibility census.

Background (``docs/a12/relation_negatives.md`` §9.1.1, ``data/a12_reports/pool_contract.json``
``eligibility_finding()``): three of the four parallel relation-pool readers recomputed a
candidate's negative eligibility from the pair's **kind** and ignored the row's own
``valid`` / ``loss_mask`` flags, so 24 ``R1`` rows (48 directed pairs) that the truth layer
withdrew (``valid=False``, ``loss_mask=False``, ``reason=no_direct_fracture_surface``) were still
supplied as ordinary negatives by ``relations.gallery.RelationPool``,
``training.sampler.PoolIndex[exported]`` and ``training.sampler.PoolIndex[gallery]``.  The fix makes
eligibility follow the extracted flags (one truth source), so this driver measures what that
costs -- and the before side is measured by running the **frozen pre-fix revisions** of the three
modules (``--step compare`` spawns a child with ``SYNLAB_BEFORE_SNAPSHOT``), never by
re-implementing them.

Steps
-----
``--step audit``
    Per implementation: candidate universe, per-query legal-negative counts and the **eligibility
    census** -- which readers offer a directed pair whose row says it is not eligible.  The census
    reports two buckets, because the finding has a narrow and a broad reading: ``stated_divergence``
    is the population §9.1.1 recorded (``kind == R1 and valid is False``: 24 unordered rows / 48
    directed pairs / 26 queries) and the broader bucket is every row the frozen gate refuses
    (``valid`` **or** ``loss_mask`` false, or a contradicting ``eligible_as_negative``).  After the
    fix every ``offered_by`` list must be empty in both buckets; before it, the driver exits 1.
``--step batch``
    A real :class:`~synlab.training.batch.TrainingBatch` over the real exported relation rows
    (``build_training_batch`` + ``Trainer.compute_losses``) and the supervision numbers it carries:
    ``legal_negatives``, ``effective_queries``, the per-query negative median and the ``rank``
    task's ``n_valid`` / ``n_allowed``.  The observation side is a **fixed synthetic bundle** (the
    real package's observation shards are 2.5 GB; loading them is neither needed nor possible for a
    cost measurement) -- it is identical on both sides of the comparison, so the measured delta is
    the eligibility change and nothing else.  ``--real-features`` loads the packaged shards
    instead, which is only affordable for a handful of fragments.
``--step compare``
    ``before`` (frozen revisions) vs ``after`` (this checkout) over the same inputs, written to one
    report with the deltas and the honest trainability verdict.  The before side is produced by a
    child process with ``SYNLAB_BEFORE_SNAPSHOT=<dir>``, which loads the frozen pre-fix
    ``loader_probe.py`` / ``sampler.py`` / ``gallery.py`` (as written by
    ``git show HEAD:synlab/... > <dir>/<file>.py``) under their real package context -- so the
    before numbers come from the old code, not from a re-implementation of it.  ``ok`` requires the
    *after* side to pass **and** the before side to fail **on the eligibility census**: a before
    side that passes proves nothing, and a before side that crashes is reported, not blessed.

Usage::

    .venv\\Scripts\\python.exe tools\\a12_negfix_eligibility.py --step all ^
        --out data\\a12_reports\\negfix_eligibility.json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_PACKAGE = "data/a12_exports/negfix/next_experiment/training_package"
DEFAULT_STORE = "data/a12_trainable/store"
DEFAULT_SNAPSHOT = "tmp/before"
SCHEMA = "synlab.a12.negfix_eligibility.v1"

#: the four implementations, including ``PoolIndex`` over each carrier family
LABELS = (
    "qc.loader_probe.ExportedRelationPool",
    "training.smoke.TrainingPoolView",
    "training.sampler.PoolIndex[exported]",
    "training.sampler.PoolIndex[gallery]",
    "relations.gallery.RelationPool",
)

_SMOKE_SPEC: dict[str, Any] = {
    "retrieval": {"temperature": 0.1},
    "optimization": {"head_lr": 1e-4, "backbone_lr": 1e-5, "weight_decay": 0.01,
                     "warmup_fraction": 0.05, "gradient_clip_norm": 1.0,
                     "accumulation_steps": 1, "max_steps": 3, "precision": "fp32"},
    "losses": {"rank": 1.0, "view": 0.1, "correspondence": 0.1, "quality": 0.05,
               "contradiction": 0.1},
    "curriculum": {"enabled": False},
    "train_seed": 11,
}


# --------------------------------------------------------------------------------------
# the frozen-revision shim (before side)
# --------------------------------------------------------------------------------------
#: dotted module -> file name inside the snapshot directory.  The files are executed under their
#: real package context, so their relative imports resolve to the live package while their own
#: code stays the frozen revision.  They are installed **before** anything imports them.
_FROZEN = {
    "synlab.qc.loader_probe": "loader_probe.py",
    "synlab.training.sampler": "sampler.py",
    "synlab.relations.gallery": "gallery.py",
}


def preload_snapshot() -> list[str]:
    """Load the pre-fix revisions of the three modules, if a snapshot is configured."""
    value = os.environ.get("SYNLAB_BEFORE_SNAPSHOT", "")
    if not value:
        return []
    root = Path(value)
    if not root.is_dir():
        raise FileNotFoundError(f"SYNLAB_BEFORE_SNAPSHOT is not a directory: {root}")
    import synlab  # noqa: F401 - the live package: frozen relative imports resolve here
    import synlab.qc  # noqa: F401
    import synlab.relations  # noqa: F401
    import synlab.training  # noqa: F401

    replaced: list[str] = []
    for dotted, filename in _FROZEN.items():
        path = root / filename
        if not path.exists():
            raise FileNotFoundError(f"before-snapshot is missing {filename}: {path}")
        spec = importlib.util.spec_from_file_location(dotted, path)
        if spec is None or spec.loader is None:  # pragma: no cover - defensive
            raise ImportError(f"cannot load {dotted} from {path}")
        module = importlib.util.module_from_spec(spec)
        module.__package__ = dotted.rsplit(".", 1)[0]
        sys.modules[dotted] = module
        spec.loader.exec_module(module)
        replaced.append(f"{dotted} <- {path}")
    return replaced


_SNAPSHOT_NOTES = preload_snapshot()


# --------------------------------------------------------------------------------------
# inputs
# --------------------------------------------------------------------------------------
def load_relations(package_dir: str | Path) -> list[dict[str, Any]]:
    """The exported relation rows verbatim (the hash-checking reader is not needed here)."""
    import pyarrow.parquet as pq

    table = pq.read_table(Path(package_dir) / "research" / "relations.parquet")
    return [{key: value for key, value in zip(table.column_names, row)}
            for row in zip(*[table.column(name).to_pylist() for name in table.column_names])]


def real_context(rows: Sequence[Mapping[str, Any]], *, name: str) -> Any:
    from synlab.qc.pool_contract import ProtocolContext

    endpoints = sorted({str(row.get("query", "")) for row in rows}
                       | {str(row.get("candidate", "")) for row in rows})
    return ProtocolContext(name=name, lineup=tuple(fid for fid in endpoints if fid),
                           rows=tuple(dict(row) for row in rows), source=name)


def build_pools(ctx: Any, *, store_dir: str | Path | None) -> dict[str, Any]:
    from synlab.qc.pool_contract import (exported_pool, gallery_pool, pool_index,
                                         training_pool_view)

    fragments: dict[str, Any] = {}
    store_info: dict[str, Any] = {"used": False}
    if store_dir and Path(store_dir).exists():
        from synlab.relations.gallery import collect_fragments
        from synlab.storage.store import AssetStore

        records = collect_fragments(AssetStore(Path(store_dir)), release=None)
        wanted = set(ctx.universe())
        fragments = {fid: rec for fid, rec in records.items() if fid in wanted}
        store_info = {"used": True, "store": str(store_dir), "records": len(records),
                      "records_for_this_universe": len(fragments), "universe": len(wanted)}
    return {
        "qc.loader_probe.ExportedRelationPool": exported_pool(ctx),
        "training.smoke.TrainingPoolView": training_pool_view(ctx),
        "training.sampler.PoolIndex[exported]": pool_index(ctx, carrier="exported"),
        "relations.gallery.RelationPool": gallery_pool(ctx, fragments=fragments),
        "training.sampler.PoolIndex[gallery]": pool_index(ctx, carrier="gallery"),
        "_store": store_info,
    }


# --------------------------------------------------------------------------------------
# step: audit (supply + eligibility census)
# --------------------------------------------------------------------------------------
def _row_index(rows: Sequence[Mapping[str, Any]]) -> dict[tuple[str, str], Mapping[str, Any]]:
    """``{(a, b): row}`` for **both** directions of every relation row.

    Relations are symmetric while the exported table keeps one row per unordered pair, so a
    directed lookup has to see the row from either side -- otherwise "the row of this direction"
    would silently depend on which way round the table happened to write it.
    """
    out: dict[tuple[str, str], Mapping[str, Any]] = {}
    for row in rows:
        query, candidate = str(row.get("query", "")), str(row.get("candidate", ""))
        if not query or not candidate or query == candidate:
            continue
        out.setdefault((query, candidate), row)
        out.setdefault((candidate, query), row)
    return out


def audit_step(ctx: Any, pools: Mapping[str, Any]) -> dict[str, Any]:
    legends = [label for label in LABELS if label in pools]
    rows_at = _row_index(ctx.rows)
    per_pool: dict[str, Any] = {}
    for label in legends:
        pool = pools[label]
        per_query = {str(fid): len({str(x) for x in pool.legal_pool(fid)})
                     for fid in ctx.universe()}
        counts = sorted(per_query.values())
        r1 = sum(len([c for c in pool.legal_pool(fid)
                      if str(pool.relation(fid, c)) == "R1"]) for fid in ctx.universe())
        per_pool[label] = {
            "candidates": sum(len(pool.candidate_ids(fid)) for fid in ctx.universe()),
            "legal_negative_supply": int(sum(counts)),
            "r1_in_supply": int(r1),
            "queries_with_a_negative": int(sum(1 for value in counts if value)),
            "negative_median_per_query": float(statistics.median(counts)) if counts else 0.0,
            "negative_mean_per_query": (float(sum(counts)) / len(counts)) if counts else 0.0,
            "negative_min_per_query": int(counts[0]) if counts else 0,
            "negative_max_per_query": int(counts[-1]) if counts else 0,
        }
    # eligibility census: a directed pair a row marks ineligible but a reader still offers
    offered: dict[tuple[str, str], list[str]] = {}
    ineligible: dict[tuple[str, str], Mapping[str, Any]] = {}
    for fid in ctx.universe():
        for candidate in sorted(set(ctx.universe()) - {str(fid)}):
            row = rows_at.get((str(fid), str(candidate)))
            if row is None:
                continue
            kind = str(row.get("kind", ""))
            valid = bool(row.get("valid", False))
            loss_mask = bool(row.get("loss_mask", False))
            frozen = bool(row.get("eligible_as_negative", False))
            if frozen or (kind in ("R0", "R1") and valid and loss_mask):
                continue                      # eligible under the frozen gate: not a finding
            ineligible[(str(fid), candidate)] = row
            for label in legends:
                if candidate in {str(x) for x in pools[label].legal_pool(fid)}:
                    offered.setdefault((str(fid), candidate), []).append(label)
    queries = {key[0] for key in offered}
    # two buckets, because the finding has a narrow and a broad reading and both are real:
    # ``stated`` = the divergence §9.1.1 recorded (an R1 row withdrawn by valid=False);
    # ``broad``  = every row the frozen gate refuses (any kind, valid=False or loss_mask=False).
    stated = {key: row for key, row in ineligible.items()
              if str(row.get("kind", "")) == "R1" and not bool(row.get("valid", False))}
    stated_offered = {key: labels for key, labels in offered.items() if key in stated}
    gate_disagreement = [{"query": key[0], "candidate": key[1],
                          "kind": str(row.get("kind", "")),
                          "valid": bool(row.get("valid", False)),
                          "loss_mask": bool(row.get("loss_mask", False)),
                          "eligible_as_negative": bool(row.get("eligible_as_negative", False))}
                         for key, row in sorted(ineligible.items())
                         if bool(row.get("kind", "")) in ("R0", "R1")
                         and (bool(row.get("eligible_as_negative", False))
                              != bool(bool(row.get("valid", False))
                                      and bool(row.get("loss_mask", False))))]
    return {
        "context": {"name": ctx.name, "rows": len(ctx.rows), "universe": len(ctx.universe())},
        "snapshot_loaded": list(_SNAPSHOT_NOTES),
        "implementations": per_pool,
        "eligibility_census": {
            "ineligible_directed_pairs": len(ineligible),
            "ineligible_unordered_pairs": len({tuple(sorted(key)) for key in ineligible}),
            "ineligible_queries": len({key[0] for key in ineligible}),
            "kinds": sorted({str(row.get("kind", "")) for row in ineligible.values()}),
            "stated_divergence": {
                "criterion": "kind == R1 and valid is False",
                "directed_pairs": len(stated),
                "unordered_pairs": len({tuple(sorted(key)) for key in stated}),
                "queries": len({key[0] for key in stated}),
                "offered_directed_pairs": len(stated_offered),
                "offered_by_counts": {label: sum(1 for labels in stated_offered.values()
                                                 if label in labels)
                                      for label in legends}},
            "gate_disagreement": {
                "criterion": "eligible_as_negative != (kind in {R0,R1} and valid and loss_mask)",
                "rows": len(gate_disagreement),
                "examples": gate_disagreement[:5],
                "ok": not gate_disagreement},
            "offered_directed_pairs": len(offered),
            "offered_by_counts": {label: sum(1 for labels in offered.values() if label in labels)
                                  for label in legends},
            "examples": [{"query": key[0], "candidate": key[1],
                          "kind": str(ineligible[key].get("kind", "")),
                          "valid": bool(ineligible[key].get("valid", False)),
                          "loss_mask": bool(ineligible[key].get("loss_mask", False)),
                          "row_eligible_as_negative":
                              bool(ineligible[key].get("eligible_as_negative", False)),
                          "reason": str(ineligible[key].get("reason", "") or ""),
                          "offered_by": offered.get(key, [])}
                         for key in sorted(offered)[:6]],
            "ok": not offered,
        },
    }


# --------------------------------------------------------------------------------------
# step: batch (real rows -> real TrainingBatch -> real rank numbers)
# --------------------------------------------------------------------------------------
def make_features(fragment_ids: Sequence[str], *, n_views: int = 2, image_size: int = 8,
                  n_tokens: int = 12, n_points: int = 8, n_regions: int = 2,
                  seed: int = 7) -> dict[str, dict]:
    """A fixed synthetic ``a12.obs.v1`` bundle (identical on both sides of the comparison).

    Shaped exactly like ``tests/a12/_fixtures.make_feature_payload`` -- the same layout the
    training contract consumes -- so the only thing that differs between the two sides of the
    comparison is the relation-pool eligibility reading.
    """
    import numpy as np

    payloads: dict[str, dict] = {}
    for index, fid in enumerate(fragment_ids):
        rng = np.random.default_rng(seed + index)
        height = width = int(image_size)
        global_rgb = rng.random((n_views, 3, height, width), dtype=np.float32)
        pixel_valid = rng.random((n_views, height, width)) > 0.15
        local_tokens = rng.random((n_tokens, 256), dtype=np.float32)
        token_pixel = np.asarray([[int(rng.integers(0, height)), int(rng.integers(0, width))]
                                  for _ in range(n_tokens)], dtype=np.int32)
        normals = rng.standard_normal((n_points, 3)).astype(np.float32)
        payloads[str(fid)] = {
            "schema": "a12.obs.v1",
            "fragment_id": str(fid),
            "obs_version": np.int32(1),
            "global_rgb": global_rgb,
            "global_valid": np.ones((n_views,), dtype=bool),
            "pixel_valid": pixel_valid,
            "local_tokens": local_tokens,
            "token_valid": np.ones((n_tokens,), dtype=bool),
            "token_view": np.asarray([i % max(n_views, 1) for i in range(n_tokens)],
                                     dtype=np.int32),
            "token_pixel": token_pixel,
            "token_modality": np.zeros((n_tokens,), dtype=np.int32),
            "token_source": np.asarray([i % 2 for i in range(n_tokens)], dtype=np.int32),
            "token_retrieval": np.arange(n_tokens, dtype=np.int32),
            "tokens_total": np.int32(n_tokens),
            "points": rng.random((n_points, 3), dtype=np.float32),
            "point_valid": np.ones((n_points,), dtype=bool),
            "normals": normals,
            "normal_valid": np.ones((n_points,), dtype=bool),
            "quality": rng.random((n_regions, 4), dtype=np.float32),
            "quality_valid": np.ones((n_regions, 4), dtype=bool),
            "presence": rng.random((3,), dtype=np.float32),
            "presence_valid": np.ones((3,), dtype=bool),
            "scale_valid": True,
            "quality_tier": 0,
            "roi_area_px": np.asarray([float(np.count_nonzero(pixel_valid[k]))
                                       for k in range(n_views)], dtype=np.float32),
        }
    return payloads


def pool_rows(pool: Any, ctx: Any) -> list[dict[str, Any]]:
    """One row per query, derived **from the pool's own readings** (never from the kind).

    ``positives`` is ``pool.mates(q)``, ``negatives`` is ``pool.legal_pool(q)`` and ``excluded``
    is the rest of the candidate universe.  A reader that stops supplying an ineligible candidate
    therefore shows up here as one fewer negative and one more excluded candidate -- the consumer
    side of the fix, with no eligibility rule re-implemented in this driver.
    """
    rows: list[dict[str, Any]] = []
    for fid in ctx.universe():
        positives = sorted(str(x) for x in pool.mates(fid))
        negatives = sorted(str(x) for x in pool.legal_pool(fid))
        candidates = {str(x) for x in pool.candidate_ids(fid)}
        excluded = sorted(candidates - set(positives) - set(negatives))
        rows.append({"query": str(fid), "positives": positives, "negatives": negatives,
                     "excluded": excluded, "sample_key": f"negfix::{fid}"})
    return rows


def batch_step(ctx: Any, pools: Mapping[str, Any], *, label: str, seed: int = 11) -> dict:
    import numpy as np

    from synlab.training.adapter import FeatureBundle
    from synlab.training.api import _SpecView, _shape_of_pool
    from synlab.training.batch import build_training_batch, exclusion_histogram, negative_audit
    from synlab.training.model import build_model
    from synlab.training.trainer import Trainer

    pool = pools[label]
    ids = [str(fid) for fid in ctx.universe()]
    payloads = make_features(ids, seed=seed)
    # ``SynLabError``-safe attachment: ``PoolIndex`` delegates its attributes to the carrier
    # (``self.pool``), while the three readers carry ``features``/``quality_tier`` themselves.
    for target in (pool, getattr(pool, "pool", None)):
        if target is None:
            continue
        try:
            merged = dict(getattr(target, "features", {}) or {})
            merged.update(payloads)
            target.features = merged
        except Exception:  # noqa: BLE001 - a frozen carrier may refuse attribute writes
            pass
        try:
            tiers = getattr(target, "quality_tier", None)
            if not isinstance(tiers, Mapping) or not tiers:
                target.quality_tier = {fid: 0 for fid in ids}
        except Exception:  # noqa: BLE001 - property without a setter on a frozen carrier
            pass
    bundle = FeatureBundle.from_dict(payloads, token_budget=12).check_shapes()
    rows = pool_rows(pool, ctx)
    batch = build_training_batch(bundle, pool=pool, rows=rows)
    audit = negative_audit(batch)
    per_query = np.asarray(batch.negative_counts(), dtype=np.int64)
    pos = np.asarray(batch.pos_mask)
    neg = np.asarray(batch.neg_mask)

    # the model is dimensioned from the bundle the batch actually carries (one source: the batch)
    dims = {"quality_input_dim": int(batch.features.quality.shape[1]
                                     * batch.features.quality.shape[2]
                                     + batch.features.presence.shape[1]),
            "quality_target_dim": int(batch.features.quality.shape[1]
                                      * batch.features.quality.shape[2])}
    model = build_model(seed=int(_SMOKE_SPEC["train_seed"]), **dims)
    trainer = Trainer(_SpecView(_SMOKE_SPEC), model, pool=pool, out_dir=None, device="cpu")
    info = trainer.compute_losses(batch)
    losses = dict(info.get("results") or {})
    # the framework's own supervision numbers: ``MultiTaskLoss.combine`` reports
    # ``n_valid``/``n_allowed``/``n_valid_labels`` per task (``n_allowed`` = rows that survived
    # every mask the task applies), so the measurement uses that report instead of re-deriving it.
    task_report = dict((info.get("combined") or {}).get("report") or {})
    rank = dict(task_report.get("rank") or {})
    rank_diag = dict(rank.get("diagnostics") or (losses.get("rank") or {}).get("diagnostics") or {})
    kinds = {}
    for name, reading in (("R0", "R0"), ("R1", "R1")):
        kinds[name] = int(sum(1 for fid in ids for cand in pool.legal_pool(fid)
                              if str(pool.relation(fid, cand)) == reading))
    return {
        "implementation": label,
        "fragments": len(ids),
        "rows_from_the_pool": len(rows),
        "batch": {
            "n_queries": int(batch.n_queries),
            "n_candidates": int(batch.n_candidates),
            "positives": int(pos.sum()),
            "legal_negatives": int(neg.sum()),
            "excluded": int(batch.excluded_mask.sum()),
            "legal_negatives_r0": kinds["R0"],
            "legal_negatives_r1": kinds["R1"],
            "queries_with_positive": int((pos.sum(axis=1) > 0).sum()),
            "queries_with_legal_negative": int((per_query > 0).sum()),
            "negative_median_per_query": float(np.median(per_query)) if per_query.size else 0.0,
            "negative_mean_per_query": float(per_query.mean()) if per_query.size else 0.0,
            "effective_queries": int(batch.effective_query_count()),
            "exclusion_histogram": exclusion_histogram(batch),
            "negative_audit_ok": bool(audit["ok"]),
            "negative_audit_problems": list(audit["problems"]),
        },
        "rank_task": {
            "skipped": bool(rank.get("skipped", True)),
            "reason": rank.get("reason"),
            "n_valid": int(rank.get("n_valid", 0) or 0),
            "n_allowed": int(rank.get("n_allowed", 0) or 0),
            "n_valid_labels": int(rank.get("n_valid_labels", 0) or 0),
            "loss": (None if rank.get("loss") is None
                     else float(rank["loss"].detach() if hasattr(rank["loss"], "detach")
                                else rank["loss"])),
            "effective_supervision_ratio": rank.get("effective_supervision_ratio"),
            "encodable_pairs": int(info.get("encodable_pairs", 0) or 0),
            "unencodable_pairs": int(info.get("unencodable_pairs", 0) or 0),
            "n_positives_label_valid": int(rank_diag.get("n_positives_label_valid", 0) or 0),
            "n_negatives_label_valid": int(rank_diag.get("n_negatives_label_valid", 0) or 0),
            "diagnostics": {key: value for key, value in rank_diag.items()
                            if isinstance(value, (int, float, str, bool))},
        },
        "trainability": {
            "effective_queries": int(batch.effective_query_count()),
            "verdict": ("rank can start" if int(batch.effective_query_count()) > 0
                        else "rank cannot start: no query has both a positive and a legal "
                             "negative in this pool"),
        },
    }


# --------------------------------------------------------------------------------------
# step: compare (before = frozen revisions, after = this checkout)
# --------------------------------------------------------------------------------------
def _run_child(package: str, store: str, *, snapshot: str | None, out: Path,
               step: str) -> dict[str, Any]:
    env = dict(os.environ)
    if snapshot:
        env["SYNLAB_BEFORE_SNAPSHOT"] = str(Path(snapshot).resolve())
    else:
        env.pop("SYNLAB_BEFORE_SNAPSHOT", None)
    env["PYTHONUTF8"] = "1"
    command = [sys.executable, str(Path(__file__).resolve()), "--step", step,
               "--package", package, "--store", store or "", "--out", str(out)]
    started = time.perf_counter()
    completed = subprocess.run(command, capture_output=True, text=True, env=env,
                               cwd=str(REPO_ROOT))
    return {"command": " ".join(command), "returncode": int(completed.returncode),
            "seconds": time.perf_counter() - started,
            "side": "before" if snapshot else "after",
            "stdout_tail": completed.stdout[-2000:], "stderr_tail": completed.stderr[-4000:],
            "report": str(out)}


def _delta(before: Any, after: Any) -> Any:
    if isinstance(before, bool) or isinstance(after, bool):
        return {"before": before, "after": after}
    if isinstance(before, (int, float)) and isinstance(after, (int, float)):
        return {"before": before, "after": after, "delta": after - before}
    return {"before": before, "after": after}


def compare_step(package: str, store: str, snapshot: str, *, step: str,
                 out_dir: Path) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    runs = {
        "before": _run_child(package, store, snapshot=snapshot, step=step,
                             out=out_dir / "negfix_eligibility_before.json"),
        "after": _run_child(package, store, snapshot=None, step=step,
                            out=out_dir / "negfix_eligibility_after.json"),
    }
    before = json.loads(Path(runs["before"]["report"]).read_text(encoding="utf-8"))
    after = json.loads(Path(runs["after"]["report"]).read_text(encoding="utf-8"))
    comparison: dict[str, Any] = {
        "schema": SCHEMA + ".compare",
        "step": step,
        "package": package,
        "store": store,
        "snapshot": snapshot,
        "runs": runs,
        "ok": False,
    }
    if "audit" in before and "audit" in after:
        census = {
            "ineligible_directed_pairs": _delta(
                before["audit"]["eligibility_census"]["ineligible_directed_pairs"],
                after["audit"]["eligibility_census"]["ineligible_directed_pairs"]),
            "offered_directed_pairs": _delta(
                before["audit"]["eligibility_census"]["offered_directed_pairs"],
                after["audit"]["eligibility_census"]["offered_directed_pairs"]),
            "offered_by_counts_before": before["audit"]["eligibility_census"]["offered_by_counts"],
            "offered_by_counts_after": after["audit"]["eligibility_census"]["offered_by_counts"],
            "stated_divergence_before": before["audit"]["eligibility_census"].get(
                "stated_divergence"),
            "stated_divergence_after": after["audit"]["eligibility_census"].get(
                "stated_divergence"),
            "gate_disagreement_before": (before["audit"]["eligibility_census"].get(
                "gate_disagreement") or {}).get("rows"),
            "gate_disagreement_after": (after["audit"]["eligibility_census"].get(
                "gate_disagreement") or {}).get("rows"),
            "ok": {"before": before["audit"]["eligibility_census"]["ok"],
                   "after": after["audit"]["eligibility_census"]["ok"]},
        }
        supply: dict[str, Any] = {}
        for label in sorted(before["audit"]["implementations"]):
            left = before["audit"]["implementations"][label]
            right = after["audit"]["implementations"].get(label, {})
            supply[label] = {
                key: _delta(left.get(key), right.get(key))
                for key in ("legal_negative_supply", "r1_in_supply", "queries_with_a_negative",
                            "negative_median_per_query", "candidates")}
        comparison["eligibility_census"] = census
        comparison["supply"] = supply
    if "batch" in before and "batch" in after:
        batches: dict[str, Any] = {}
        for label in sorted(before["batch"]):
            left = before["batch"][label]
            right = after["batch"].get(label, {})
            batches[label] = {
                "legal_negatives": _delta(left["batch"]["legal_negatives"],
                                          right["batch"]["legal_negatives"]),
                "legal_negatives_r0": _delta(left["batch"]["legal_negatives_r0"],
                                             right["batch"]["legal_negatives_r0"]),
                "legal_negatives_r1": _delta(left["batch"]["legal_negatives_r1"],
                                             right["batch"]["legal_negatives_r1"]),
                "effective_queries": _delta(left["batch"]["effective_queries"],
                                            right["batch"]["effective_queries"]),
                "queries_with_legal_negative": _delta(
                    left["batch"]["queries_with_legal_negative"],
                    right["batch"]["queries_with_legal_negative"]),
                "negative_median_per_query": _delta(left["batch"]["negative_median_per_query"],
                                                    right["batch"]["negative_median_per_query"]),
                "rank_n_valid": _delta(left["rank_task"]["n_valid"], right["rank_task"]["n_valid"]),
                "rank_n_allowed": _delta(left["rank_task"]["n_allowed"],
                                         right["rank_task"]["n_allowed"]),
                "rank_skipped": _delta(left["rank_task"]["skipped"],
                                       right["rank_task"]["skipped"]),
                "rank_reason": _delta(left["rank_task"]["reason"], right["rank_task"]["reason"]),
                "trainability_verdict": right.get("trainability", {}).get("verdict"),
            }
        comparison["batch"] = batches
    comparison["after_census_ok"] = bool(
        after.get("audit", {}).get("eligibility_census", {}).get("ok", False))
    # ``ok`` has to keep both halves honest: the *after* side must pass on its own merits, and the
    # *before* side must **fail on the eligibility census** -- that failure is the defect being
    # demonstrated, not an error.  A before-side that passes, or one that fails for another reason
    # (a crash: ``audit``/``batch`` absent), makes the comparison meaningless and is reported.
    before_report = before.get("audit", {}).get("eligibility_census", {}) if before else {}
    before_shows_the_defect = bool(before_report) and not bool(before_report.get("ok", True))
    comparison["before_shows_the_defect"] = before_shows_the_defect
    comparison["before_errored"] = not bool(before.get("audit")) and not bool(before.get("batch"))
    comparison["ok"] = bool(comparison["after_census_ok"] and before_shows_the_defect
                            and not comparison["before_errored"]
                            and runs["after"]["returncode"] == 0)
    return comparison


# --------------------------------------------------------------------------------------
# runner
# --------------------------------------------------------------------------------------
def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--step", default="all",
                        choices=("audit", "batch", "audit-and-batch", "compare", "all"))
    parser.add_argument("--package", default=DEFAULT_PACKAGE)
    parser.add_argument("--store", default=DEFAULT_STORE)
    parser.add_argument("--snapshot", default=DEFAULT_SNAPSHOT,
                        help="directory holding the frozen pre-fix module revisions")
    parser.add_argument("--batch-implementation", default="training.sampler.PoolIndex[exported]")
    parser.add_argument("--out", default="data/a12_reports/negfix_eligibility.json")
    args = parser.parse_args(argv)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    want_audit = args.step in ("audit", "audit-and-batch", "all")
    want_batch = args.step in ("batch", "audit-and-batch", "all")
    out_dir = out_path.parent / "negfix_eligibility" if args.step == "compare" else None
    if args.step == "compare":
        payload = compare_step(args.package, args.store, args.snapshot,
                               step="audit-and-batch", out_dir=out_dir)
    else:
        payload = {"schema": SCHEMA, "package": args.package, "store": args.store,
                   "snapshot_loaded": list(_SNAPSHOT_NOTES), "steps": args.step,
                   "audit": {}, "batch": {}}
        ctx = pools = None
        if want_audit or want_batch:
            rows = load_relations(args.package)
            ctx = real_context(rows, name=f"negfix::{Path(args.package).name}")
            pools = build_pools(ctx, store_dir=args.store or None)
        if want_audit:
            payload["audit"] = audit_step(ctx, pools)
        if want_batch:
            payload["batch"] = {args.batch_implementation:
                                batch_step(ctx, pools, label=args.batch_implementation)}
        ok = True
        if payload["audit"]:
            ok = bool(ok and payload["audit"]["eligibility_census"]["ok"])
        if payload["batch"]:
            ok = bool(ok and all(item["batch"]["negative_audit_ok"]
                                 for item in payload["batch"].values()))
        payload["ok"] = ok
    payload.setdefault("ok", False)
    payload["status"] = "PASS" if payload["ok"] else "FAIL"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True,
                                  default=str), encoding="utf-8")
    _summary(payload, out_path)
    return 0 if payload["ok"] else 1


def _summary(payload: Mapping[str, Any], out_path: Path) -> None:
    if "runs" in payload:
        for side, run in sorted(payload["runs"].items()):
            print(f"[{side}] rc={run['returncode']} report={run['report']}")
            if run["returncode"] != 0 and run.get("stderr_tail"):
                print(run["stderr_tail"][-1500:])
    if "context" in payload:
        print(f"[audit] context={payload['context']['name']} "
              f"universe={payload['context']['universe']} rows={payload['context']['rows']}")
    if "eligibility_census" in payload and "ineligible_directed_pairs" in payload["eligibility_census"]:
        for label, item in sorted((payload.get("implementations") or {}).items()):
            print(f"  {label}: supply={item['legal_negative_supply']} "
                  f"(R1 {item['r1_in_supply']}) queries_with_negative="
                  f"{item['queries_with_a_negative']} median={item['negative_median_per_query']}")
        census = payload["eligibility_census"]
        print(f"  eligibility census: ineligible {census.get('ineligible_directed_pairs')} "
              f"directed pair(s), offered by {census.get('offered_directed_pairs')} -> ok="
              f"{census.get('ok')} {census.get('offered_by_counts_before') or census.get('offered_by_counts') or {}}")
        stated = census.get("stated_divergence") or {}
        if stated:
            print(f"    stated divergence ({stated['criterion']}): "
                  f"{stated['directed_pairs']} directed / {stated['unordered_pairs']} unordered / "
                  f"{stated['queries']} queries, offered by {stated['offered_directed_pairs']} "
                  f"{stated.get('offered_by_counts', {})}")
        gate = census.get("gate_disagreement") or {}
        if gate:
            print(f"    frozen-gate disagreement rows: {gate['rows']} -> ok={gate['ok']}")
    if "batch" in payload and payload.get("implementations"):
        for label, item in sorted(payload["batch"].items()):
            batch, rank = item["batch"], item["rank_task"]
            print(f"[batch] {label}: negatives={batch['legal_negatives']} "
                  f"(R0 {batch['legal_negatives_r0']} / R1 {batch['legal_negatives_r1']}) "
                  f"effective_queries={batch['effective_queries']} "
                  f"median/query={batch['negative_median_per_query']} "
                  f"rank n_valid={rank['n_valid']} n_allowed={rank['n_allowed']} "
                  f"skipped={rank['skipped']} reason={rank['reason']}")
    if "supply" in payload:
        for label, item in sorted(payload["supply"].items()):
            print(f"[supply] {label}: " + " ".join(
                f"{key}={value.get('before')}->{value.get('after')}"
                for key, value in item.items() if key != "candidates"))
        for label, item in sorted(payload.get("batch", {}).items()):
            print(f"[batch] {label}: " + " ".join(
                f"{key}={value.get('before')}->{value.get('after')}"
                for key, value in item.items() if isinstance(value, Mapping)
                and "before" in value and key != "rank_reason"))
        print(f"  after census ok={payload.get('after_census_ok')}")
    print(f"status={payload['status']} out={out_path}")


if __name__ == "__main__":
    raise SystemExit(main())
