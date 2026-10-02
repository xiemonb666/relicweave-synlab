#!/usr/bin/env python
"""S2 driver: the ``HARD_NEGATIVE_MATE_PRESENT`` class, and its on/off training comparison.

Two steps, both driven by real packaged data:

``--step class``
    Classify a package's ``research/relations.parquet`` with
    ``synlab.relations.mate_absent`` and emit the ``HARD_NEGATIVE_MATE_PRESENT`` supervision
    records (the 1120 mate-present rows), their four-condition conformance record, and the
    measured demonstration of why the class may **not** be merged into the main relation table
    (decision D10's single-gate rule).  Nothing in ``data/a12_exports/**`` is written.

``--step ab``
    The controlled on/off experiment on one minimal trainable subset: the same query, its
    confirmed R2 positive, its legal (mate-absent) negatives and its hard negatives, three real
    optimizer steps per arm.

    * ``off``     -- the pre-S2 batch: no hard-negative slots at all, weight 0;
    * ``control`` -- hard-negative slots present in the batch, auxiliary weight 0;
    * ``on``      -- the same batch, auxiliary weight ``--hard-weight``.

    ``off`` vs ``control`` isolates the *presence* of the class inside the batch (it must not
    move any primary denominator, and the report proves it by comparing the rank denominators
    field by field); ``control`` vs ``on`` isolates the auxiliary *term*.  Per-step losses and
    per-task ``n_valid``/``n_allowed``/weight come from ``Trainer.train_step``; the ranking
    diagnostics come from the model's own pair scores before the first step and after the last.

Usage::

    python tools/a12_s2_hard_negatives.py --step class \
        --package data/a12_exports/trainable/next_experiment/training_package \
        --out data/a12_reports/s2_hard_negatives_class.json
    python tools/a12_s2_hard_negatives.py --step ab --steps 3 --hard-weight 0.3 \
        --query LIN0101_V16_M12_PAT12_E01-m \
        --package data/a12_exports/negfix/next_experiment/training_package \
        --out data/a12_reports/s2_hard_negatives_ab.json
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_PACKAGE = "data/a12_exports/trainable/next_experiment/training_package"
DEFAULT_QUERY = "LIN0101_V16_M12_PAT12_E01-m"


# --------------------------------------------------------------------------------------
# relation rows of a package (the same shape the class producer takes)
# --------------------------------------------------------------------------------------
def relation_rows(package_dir: str | Path) -> tuple[Any, list[dict[str, Any]]]:
    from synlab.storage.export import TrainingPackage

    package = TrainingPackage(package_dir)
    rows: list[dict[str, Any]] = []
    for raw in package.relations():
        rows.append({
            "query": str(raw.get("query", "")), "candidate": str(raw.get("candidate", "")),
            "kind": str(raw.get("kind", "")), "valid": bool(raw.get("valid", False)),
            "loss_mask": bool(raw.get("loss_mask", False)),
            "eligible_as_negative": bool(raw.get("eligible_as_negative", False)),
            "area_mm2": float(raw.get("area_mm2") or 0.0),
            "reason": str(raw.get("reason", "") or ""),
        })
    return package, rows


# --------------------------------------------------------------------------------------
# --step class
# --------------------------------------------------------------------------------------
def _d10_merge_demonstration(main_rows: Sequence[Mapping[str, Any]],
                             hard_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Measure what merging the class into ``relations.parquet`` would do to decision D10.

    Two packages are written into a temporary directory and read back by the **real** checker
    ``synlab.qc.decision_checks._check_loss_mask_authority``:

    * ``separate`` -- the main table as the exporter writes it (the class lives outside it);
    * ``merged``   -- the same table with the class rows appended as ``kind=R0`` rows carrying
      ``loss_mask=True`` and ``eligible_as_negative=False``.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    from synlab.qc.decision_checks import _check_loss_mask_authority

    def _write(root: Path, name: str, rows: Sequence[Mapping[str, Any]]) -> None:
        target = root / name
        target.mkdir(parents=True, exist_ok=True)
        table = pa.table({
            "query": pa.array([str(r["query"]) for r in rows]),
            "candidate": pa.array([str(r["candidate"]) for r in rows]),
            "kind": pa.array([str(r["kind"]) for r in rows]),
            "valid": pa.array([bool(r.get("valid", False)) for r in rows]),
            "loss_mask": pa.array([bool(r.get("loss_mask", False)) for r in rows]),
            "eligible_as_negative": pa.array([bool(r.get("eligible_as_negative", False))
                                              for r in rows]),
        })
        pq.write_table(table, target / "relations.parquet")

    out: dict[str, Any] = {"checker": "synlab.qc.decision_checks._check_loss_mask_authority",
                           "threshold": ("eligible_as_negative == (kind in {R0,R1} and "
                                         "loss_mask) and valid == loss_mask for every row")}
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write(root, "separate", main_rows)
        merged = list(main_rows) + [{"query": r["query"], "candidate": r["candidate"],
                                     "kind": r["kind"], "valid": r["valid"],
                                     "loss_mask": True, "eligible_as_negative": False}
                                    for r in hard_rows]
        _write(root, "merged", merged)
        for name in ("separate", "merged"):
            result = _check_loss_mask_authority(root / name)
            out[name] = {"status": str(result.status), "detail": result.detail,
                         "denominator": int(result.denominator), "hits": int(result.hits),
                         "violations": int(result.denominator - result.hits),
                         "violation_examples": (result.evidence or {}).get("violations", [])[:3]}
    out["delta"] = {
        "rows_added_by_merge": int(out["merged"]["denominator"] - out["separate"]["denominator"]),
        "violations_added_by_merge": int(out["merged"]["violations"]
                                         - out["separate"]["violations"]),
        "preexisting_violations_in_main_table": int(out["separate"]["violations"]),
    }
    out["conclusion"] = (
        "the class is emitted as its own record set. Because its contract is loss_mask=True "
        "with eligible_as_negative=False, appending it to research/relations.parquet adds "
        f"{out['delta']['rows_added_by_merge']} rows and "
        f"{out['delta']['violations_added_by_merge']} decision-D10 violations (the frozen "
        "single-gate rule requires eligible_as_negative == loss_mask on every R0/R1 row). "
        "Relaxing that rule is not available, so the class stays outside the main table; the "
        f"{out['delta']['preexisting_violations_in_main_table']} pre-existing violation(s) of "
        "the main table are unrelated to this class and are left untouched.")
    return out


def step_class(package_dir: str | Path, *, out: Path, hard_negative_limit: int | None) -> dict:
    from synlab.relations.mate_absent import (
        CLASS_HARD_NEGATIVE,
        hard_negative_class_count,
        hard_negative_records,
    )

    started = time.perf_counter()
    package, rows = relation_rows(package_dir)
    records, report = hard_negative_records(rows)
    table = hard_negative_class_count(rows)
    payload: dict[str, Any] = {
        "schema": "synlab.a12.s2.hard_negative_class.v1",
        "step": "class", "package_dir": str(package_dir),
        "class": CLASS_HARD_NEGATIVE,
        "package": {"files_verified": bool(package.verify_files()["ok"]),
                    "relations": len(rows)},
        "class_report": {k: v for k, v in report.items() if k != "rejected_rows"},
        "class_table": table,
        "records_sample": records[:5],
        "records_path": None,
        "d10_merge_demonstration": _d10_merge_demonstration(rows, records),
    }
    if hard_negative_limit is not None and int(hard_negative_limit) >= 0:
        kept = records[: int(hard_negative_limit)]
        payload["limited_to"] = {"limit": int(hard_negative_limit), "records": len(kept)}
    # the full record set goes to its own file, never into relations.parquet
    records_path = out.with_name(out.stem + "_records.json")
    records_path.parent.mkdir(parents=True, exist_ok=True)
    records_path.write_text(json.dumps(records, ensure_ascii=False, indent=2, sort_keys=True),
                            encoding="utf-8")
    payload["records_path"] = str(records_path)
    payload["wall_seconds"] = time.perf_counter() - started
    return payload


# --------------------------------------------------------------------------------------
# --step ab
# --------------------------------------------------------------------------------------
def _subset_and_records(package_dir: str | Path, *, query: str, negatives: int,
                        hard_negatives: int) -> tuple[Any, list[dict[str, Any]], dict[str, Any]]:
    from synlab.relations.mate_absent import (
        CLASS_MATE_PRESENT,
        CLASS_POSITIVE,
        hard_negative_records,
        r2_mates,
        row_class,
    )
    from synlab.relations.mate_absent import CLASS_ORDINARY_NEGATIVE

    package, rows = relation_rows(package_dir)
    records, report = hard_negative_records(rows)
    mates = r2_mates(rows)
    classes = [row_class(r, mates) for r in rows]
    positives = sorted({r["candidate"] for r, k in zip(rows, classes)
                        if r["query"] == query and k == CLASS_POSITIVE})
    legal = sorted({r["candidate"] for r, k in zip(rows, classes)
                    if r["query"] == query and k == CLASS_ORDINARY_NEGATIVE})
    hard = [r["candidate"] for r in records if r["query"] == query]
    selection = {
        "query": query, "positives_of_query": positives, "legal_negatives_of_query": legal,
        "hard_negatives_of_query": hard,
        "classes_in_table": {
            name: int(sum(1 for k in classes if k == name))
            for name in (CLASS_POSITIVE, CLASS_ORDINARY_NEGATIVE, CLASS_MATE_PRESENT, "EXCLUDED")},
        "class_report": {k: v for k, v in report.items() if k != "rejected_rows"},
    }
    subset = [query, *positives, *legal[: max(int(negatives), 0)],
              *hard[: max(int(hard_negatives), 0)]]
    subset = [fid for fid in dict.fromkeys(subset) if fid]
    selection["fragment_subset"] = subset
    selection["hard_negatives_used"] = [f for f in subset if f in set(hard)]
    return package, records, selection, subset


def _rows_with_hard_negatives(relations: Sequence[Mapping[str, Any]],
                              subset: Sequence[str], pool: Any,
                              records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    from synlab.qc.loader_probe import _batch_rows

    rows = _batch_rows(relations, subset, pool)
    known = set(subset)
    by_query: dict[str, list[str]] = {}
    for record in records:
        if record["query"] in known and record["candidate"] in known:
            by_query.setdefault(str(record["query"]), []).append(str(record["candidate"]))
    for row in rows:
        hard = sorted(dict.fromkeys(by_query.get(str(row["query"]), [])))
        hard = [h for h in hard if h not in row["positives"] and h not in row["negatives"]]
        row["hard_negatives"] = hard
    return rows


def _pair_scores(trainer: Any, batch: Any) -> tuple[np.ndarray, np.ndarray]:
    torch = __import__("torch")

    features = batch.features.to_torch(device=str(trainer.device))
    with torch.no_grad():
        z, z_valid = trainer.model.encoder.encode(features)
    pair = torch.as_tensor(batch.pair_index, dtype=torch.long)
    sim = (z[pair[:, :, 0]] * z[pair[:, :, 1]]).sum(dim=-1) / max(trainer.temperature, 1e-8)
    valid = (z_valid[pair[:, :, 0]] & z_valid[pair[:, :, 1]]
             & torch.as_tensor(batch.pair_valid, dtype=torch.bool))
    return sim.detach().cpu().numpy(), valid.detach().cpu().numpy()


def _ranking_diagnostics(batch: Any, trainer: Any, query: str) -> dict[str, Any]:
    """Subset-scale ranking numbers measured from the model's own pair scores.

    These are **subset analogs**, not the frozen plan metrics: with a handful of candidates
    ``any@50`` is trivially 1 and ``Hit@10`` is degenerate, and the report says so instead of
    quoting a number that means nothing at this size.  What is measured:

    * ``positive_rank`` -- 1 + the number of valid candidates scored strictly above the query's
      best positive (ties counted as not-above, i.e. optimistic for the model);
    * ``hit_at_k`` for k in {1, 5, 10};
    * ``mate_absent_misleading_rate`` -- the fraction of **mate-absent** candidates accepted at
      or above the best positive score (the plan's ``无邻片误导率`` read on this subset);
    * ``hard_negative_accept_rate`` -- the same for the auxiliary class's candidates.
    """
    ids = list(batch.features.fragment_ids)
    rows = np.nonzero(np.asarray([ids[int(batch.pair_index[i, 0, 0])] == query
                                  for i in range(batch.n_queries)]))[0]
    if rows.size == 0:
        return {"available": False, "reason": "query not present in this batch"}
    i = int(rows[0])
    sim, valid = _pair_scores(trainer, batch)
    pos = np.asarray(batch.pos_mask[i], dtype=bool) & valid[i]
    if not pos.any():
        return {"available": False, "reason": "the query has no encodable positive in this batch"}
    best = float(sim[i][pos].max())
    cand = valid[i]
    above = cand & (sim[i] > best)
    cand_frag = np.asarray(batch.pair_index[i, :, 1], dtype=np.int64)
    mate_absent = cand & ~np.asarray(batch.mate_present, dtype=bool)[cand_frag]
    hard = np.asarray(batch.hard_neg_mask[i], dtype=bool) & cand
    rank = 1 + int(above.sum())
    return {
        "available": True, "query": query,
        "candidates_scored": int(cand.sum()),
        "best_positive_score": best,
        "positive_rank": rank,
        "hit_at_k": {str(k): bool(rank <= k) for k in (1, 5, 10)},
        "mate_absent_candidates": int(mate_absent.sum()),
        "mate_absent_misleading_rate": (float((sim[i][mate_absent] >= best).mean())
                                        if mate_absent.any() else None),
        "hard_negative_candidates": int(hard.sum()),
        "hard_negative_accept_rate": (float((sim[i][hard] >= best).mean())
                                      if hard.any() else None),
        "note": ("subset-scale analog; the frozen any@50 / Hit@10 / misleading-rate "
                 "denominators are computed at roster scale by synlab.diagnostics.metrics"),
    }


def _run_arm(name: str, *, package: Any, relations: Sequence[Mapping[str, Any]], subset: Sequence[str],
             rows: Sequence[Mapping[str, Any]], weight: float, steps: int, token_budget: int,
             query: str, carry_hard_slots: bool) -> dict[str, Any]:
    from synlab.qc.loader_probe import _pool_id, load_features
    from synlab.training import smoke
    from synlab.training.api import _SpecView, _shape_of_pool
    from synlab.training.batch import mate_present_shortcut_probe
    from synlab.training.labels import PackageLabelSource
    from synlab.training.model import build_model
    from synlab.training.trainer import Trainer

    payloads = load_features(package, subset, token_budget=token_budget)
    pool = smoke.TrainingPoolView(relations, lineup=subset, pool_id=_pool_id(relations))
    pool.features = payloads
    arm_rows = [dict(r) for r in rows]
    if not carry_hard_slots:
        for row in arm_rows:
            row.pop("hard_negatives", None)
    dims = _shape_of_pool(pool)
    model = build_model(seed=int(smoke.SMOKE_SPEC["train_seed"]), **dims)
    spec_data = json.loads(json.dumps(smoke.SMOKE_SPEC))
    spec_data["losses"]["hard_negative"] = float(weight)
    spec = _SpecView(spec_data)
    label_source = PackageLabelSource.from_package(package)
    manifest = package.manifest
    release_hash = str(manifest.get("release_manifest_hash") or manifest.get("manifest_hash") or "")
    trainer = Trainer(spec, model, pool=pool, out_dir=None, release_hash=release_hash,
                      label_source=label_source,
                      recipe={"s2_ab_arm": name, "package_id": manifest.get("package_id")})
    batch = trainer.build_batch(smoke._sample_spec(arm_rows, pool))
    facts = smoke._batch_facts(batch)
    out: dict[str, Any] = {
        "arm": name, "hard_negative_weight": float(weight),
        "hard_slots_in_batch": bool(carry_hard_slots),
        "batch": {k: v for k, v in facts.items() if k != "rows"},
        "hard_negative_audit": {
            "hard_negatives": int(batch.hard_neg_mask.sum()),
            "hard_negative_queries": int(batch.hard_negative_queries().size),
            "negatives": int(batch.neg_mask.sum()),
            "positives": int(batch.pos_mask.sum()),
            "effective_queries": int(batch.effective_query_count()),
            "exclusion_histogram": batch.exposure()["exclusion_histogram"],
        },
        "mate_present_shortcut_probe": mate_present_shortcut_probe(batch),
        "ranking_before": _ranking_diagnostics(batch, trainer, query),
    }
    records = [smoke._run_step(trainer, batch) for _ in range(int(steps))]
    out["steps"] = {
        "optimizer_steps_taken": int(trainer.step_index),
        "loss_sequence": [r.get("loss") for r in records],
        "grad_norm_sequence": [r.get("grad_norm") for r in records],
        "records": records,
    }
    out["ranking_after"] = _ranking_diagnostics(batch, trainer, query)
    out["supervision"] = records[0].get("supervision") if records else None
    return out


def step_ab(package_dir: str | Path, *, out: Path, query: str, steps: int, negatives: int,
            hard_negatives: int, hard_weight: float, token_budget: int) -> dict:
    from synlab.relations.mate_absent import HARD_NEGATIVE_TASK

    started = time.perf_counter()
    package, records, selection, subset = _subset_and_records(
        package_dir, query=query, negatives=negatives, hard_negatives=hard_negatives)
    relations = [dict(r) for r in package.relations()]
    from synlab.qc.loader_probe import _pool_id
    from synlab.training import smoke

    pool = smoke.TrainingPoolView(relations, lineup=subset, pool_id=_pool_id(relations))
    rows = _rows_with_hard_negatives(relations, subset, pool, records)
    payload: dict[str, Any] = {
        "schema": "synlab.a12.s2.hard_negative_ab.v1", "step": "ab",
        "package_dir": str(package_dir), "task": HARD_NEGATIVE_TASK,
        "selection": selection, "steps_requested": int(steps),
        "hard_negative_weight_on": float(hard_weight),
        "device": ("cuda" if __import__("torch").cuda.is_available() else "cpu"),
        "ok": False,
    }
    arms = [
        ("off", 0.0, False),
        ("control", 0.0, True),
        ("on", float(hard_weight), True),
    ]
    payload["arms"] = {}
    for name, weight, carry in arms:
        payload["arms"][name] = _run_arm(
            name, package=package, relations=relations, subset=subset, rows=rows,
            weight=weight, steps=steps, token_budget=token_budget, query=query,
            carry_hard_slots=carry)
    payload["denominator_invariance"] = _denominator_invariance(payload["arms"])
    payload["ok"] = all(a["steps"]["optimizer_steps_taken"] == int(steps)
                        for a in payload["arms"].values())
    payload["wall_seconds"] = time.perf_counter() - started
    return payload


def _denominator_invariance(arms: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Field-by-field proof that the class does not move any primary denominator."""
    off, control = arms["off"]["batch"], arms["control"]["batch"]
    keys = ("positives", "negatives", "excluded", "effective_queries",
            "queries_with_positive", "queries_with_legal_negative")
    moved = {k: {"off": off.get(k), "control": control.get(k)}
             for k in keys if off.get(k) != control.get(k)}
    off_rank = _rank_task(arms["off"])
    ctl_rank = _rank_task(arms["control"])
    on_rank = _rank_task(arms["on"])
    return {
        "fields_compared": list(keys),
        "moved_fields": moved,
        "invariant": not moved,
        "rank_task_off_vs_control": {"off": off_rank, "control": ctl_rank,
                                     "identical": off_rank == ctl_rank},
        "rank_task_control_vs_on": {"control": ctl_rank, "on": on_rank},
        "note": ("the rank task's n_valid/n_allowed and every batch denominator are compared "
                 "between the arm without hard-negative slots and the arm with them; the "
                 "effective-query count is the primary denominator of the rank metric family"),
    }


def _rank_task(arm: Mapping[str, Any]) -> dict[str, Any]:
    records = (arm.get("steps") or {}).get("records") or []
    if not records:
        return {}
    task = (records[0].get("tasks") or {}).get("rank") or {}
    return {"n_valid": task.get("n_valid"), "n_allowed": task.get("n_allowed"),
            "loss": task.get("loss"), "effective_queries": records[0].get("effective_queries")}


# --------------------------------------------------------------------------------------
def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="a12_s2_hard_negatives")
    parser.add_argument("--step", choices=("class", "ab", "all"), default="all")
    parser.add_argument("--package", default=DEFAULT_PACKAGE)
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument("--steps", type=int, default=3)
    parser.add_argument("--negatives", type=int, default=4)
    parser.add_argument("--hard-negatives", type=int, default=4)
    parser.add_argument("--hard-weight", type=float, default=0.3)
    parser.add_argument("--token-budget", type=int, default=256)
    parser.add_argument("--class-limit", type=int, default=None)
    parser.add_argument("--out", default="data/a12_reports/s2_hard_negatives.json")
    args = parser.parse_args(argv)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {"schema": "synlab.a12.s2.v1", "steps_requested": args.step}
    try:
        if args.step in ("class", "all"):
            report["class"] = step_class(args.package, out=out,
                                         hard_negative_limit=args.class_limit)
        if args.step in ("ab", "all"):
            report["ab"] = step_ab(args.package, out=out, query=args.query, steps=args.steps,
                                   negatives=args.negatives, hard_negatives=args.hard_negatives,
                                   hard_weight=args.hard_weight, token_budget=args.token_budget)
        report["ok"] = True
    except BaseException as exc:  # noqa: BLE001 - a crash is an outcome, not a silent failure
        report["ok"] = False
        report["escaped_exception"] = f"{type(exc).__name__}: {exc}"
        report["traceback"] = traceback.format_exc()[-4000:]
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, default=str),
                   encoding="utf-8")
    print(json.dumps(_summary(report), ensure_ascii=False, indent=2, default=str))
    print(f"wrote {out}")
    return 0 if report.get("ok") else 1


def _summary(report: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"ok": report.get("ok"), "schema": report.get("schema")}
    if "escaped_exception" in report:
        out["escaped_exception"] = report["escaped_exception"]
        out["traceback"] = report.get("traceback")
    cls = report.get("class")
    if cls:
        out["class"] = {
            "rows": cls["package"]["relations"],
            "class_report": {k: v for k, v in cls["class_report"].items()
                             if k in ("records", "rejected", "rows_classed_mate_present",
                                      "conformance")},
            "d10": {k: {kk: cls["d10_merge_demonstration"][k][kk]
                        for kk in ("status", "denominator", "hits", "violations")}
                    for k in ("separate", "merged")},
            "d10_delta": cls["d10_merge_demonstration"]["delta"],
            "records_path": cls.get("records_path"),
        }
    ab = report.get("ab")
    if ab:
        out["ab"] = {
            "selection": {k: v for k, v in ab["selection"].items()
                          if k in ("query", "positives_of_query", "legal_negatives_of_query",
                                   "hard_negatives_of_query", "fragment_subset",
                                   "hard_negatives_used")},
            "denominator_invariance": ab["denominator_invariance"],
            "arms": {name: {
                "weight": arm["hard_negative_weight"],
                "hard_slots": arm["hard_slots_in_batch"],
                "loss_sequence": arm["steps"]["loss_sequence"],
                "grad_norms": arm["steps"]["grad_norm_sequence"],
                "rank": _rank_task(arm),
                "hard_task": (arm["steps"]["records"][0]["tasks"].get("hard_negative")
                              if arm["steps"]["records"] else None),
                "shortcut": {k: arm["mate_present_shortcut_probe"][k]
                             for k in ("queries_probed", "queries_with_constant_cue",
                                       "mean_auc_mate_present_vs_positive",
                                       "discriminative_power")},
                "ranking_before": arm["ranking_before"],
                "ranking_after": arm["ranking_after"],
            } for name, arm in ab["arms"].items()},
        }
    return out


if __name__ == "__main__":
    raise SystemExit(main())
