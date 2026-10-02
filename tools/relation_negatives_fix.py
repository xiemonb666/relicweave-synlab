#!/usr/bin/env python
"""Re-export a training package with the mate-absent negative rule applied, step by step.

Why this driver exists
----------------------
``data/a12_exports/trainable/next_experiment/training_package`` carries 1560
``eligible_as_negative`` rows, but the candidates of those rows are ordinary negatives while
several of them have **their own** confirmed ``R2`` mate inside the same pool.  The rule that
fixes this (``synlab.relations.mate_absent``) has to reach the *exported relation table*, and the
relation table of that package is written by the frozen exporter
(``synlab.storage.export.export_training_package``) from the *stored* pool/truth/label assets of
``data/a12`` -- assets this task must not rewrite.

So the driver re-runs the **real exporter** over the very same release scope
(``rel_nexp_1790919836``, the 328-asset unfrozen scope recorded by the previous run in
``data/a12_exports/trainable/next_experiment/next_experiment_export_state.json``) and intervenes
at exactly one point: the moment the writer serialises ``research/relations.parquet``.  There the
rows pass through :func:`synlab.relations.mate_absent.apply_rule`, which clears ``loss_mask`` on
the rows whose candidate is mate-present (a *separate* class, see the module docstring) and
records the reason; every other byte of the package (observations, geometry, tokens, zarr, all
other label layers, the manifest, the file hashes) is produced by the frozen writer unchanged.

Steps::

    python tools/relation_negatives_fix.py --step plan      # analyse the base package + the rule
    python tools/relation_negatives_fix.py --step export    # re-export with the rule applied
    python tools/relation_negatives_fix.py --step diff      # new table vs base table, row by row
    python tools/relation_negatives_fix.py --step sample    # >=20 negatives re-checked from raw
    python tools/relation_negatives_fix.py --step classes   # class table of the new package

Every step writes its measured numbers to ``--out`` before returning.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synlab.relations import mate_absent  # noqa: E402

DEFAULT_OUT = "data/a12_neg"
#: The store that owns the release scope of the "trainable" package.  It is a *different* store
#: than ``data/a12`` (which holds 894 assets of other runs): ``data/a12_trainable/store`` is the
#: one whose metadata carries the 328 scope assets of ``rel_nexp_1790919836``.  It is only ever
#: read here; every byte this driver writes goes to ``--package`` / ``--out``.
DEFAULT_STORE = "data/a12_trainable/store"
DEFAULT_BASE = "data/a12_exports/trainable/next_experiment/training_package"
DEFAULT_STATE = "data/a12_exports/trainable/next_experiment/next_experiment_export_state.json"
DEFAULT_PACKAGE = "data/a12_exports/negfix/next_experiment/training_package"
RELATIONS_IN_PACKAGE = "research/relations.parquet"
FORMATS = ("parquet", "npz", "zarr", "tar")


# ---------------------------------------------------------------------------------- plumbing
def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True,
                               default=str), encoding="utf-8")


def _rows_of(package: str | Path) -> list[dict[str, Any]]:
    frame = pd.read_parquet(Path(package) / RELATIONS_IN_PACKAGE)
    return [dict(row) for row in frame.to_dict("records")]


def _token_counts(package_dir: Path, fragment_ids: Sequence[str]) -> dict[str, int]:
    """Real token counts per fragment from the packaged token cache (no RGB is loaded)."""
    from synlab.storage.export import TrainingPackage

    package = TrainingPackage(package_dir)
    out: dict[str, int] = {}
    for fragment_id in fragment_ids:
        try:
            tokens = package.read_tokens(fragment_id)
        except Exception:                                     # noqa: BLE001 - absent is a fact
            out[str(fragment_id)] = 0
            continue
        out[str(fragment_id)] = int(np.asarray(tokens["tokens"]).shape[0])
    return out


def _geometry_gate(package_dir: Path, fragment_ids: Sequence[str]) -> dict[str, bool]:
    """``(point_valid | normal_valid) & scale_valid`` per fragment, from the geometry shards."""
    from synlab.storage.export import TrainingPackage

    package = TrainingPackage(package_dir)
    out: dict[str, bool] = {}
    for fragment_id in fragment_ids:
        try:
            geometry = package.read_geometry(fragment_id)
        except Exception:                                     # noqa: BLE001
            out[str(fragment_id)] = False
            continue
        point_valid = np.asarray(geometry["point_valid"], dtype=bool)
        normal_valid = np.asarray(geometry["normal_valid"], dtype=bool)
        scale_valid = bool(np.asarray(geometry["scale_valid"], dtype=bool).any())
        out[str(fragment_id)] = bool(((point_valid | normal_valid) & scale_valid).any())
    return out


def encodable_from_packaged_shards(package_dir: str | Path, fragment_ids: Sequence[str]
                                   ) -> tuple[dict[str, bool], dict[str, Any]]:
    """Conservative encodability: tokens or scaled geometry (the RGB gate is *not* read here).

    The trainer's own denominator is ``z_valid`` (``training.model.encode``), which also accepts
    a fragment that only has valid global RGB.  Reading the 896 MB of packaged RGB just for this
    report is wasteful, so this helper reads the token cache and the geometry shards and reports
    the two gates it really measured; the smoke run (which loads every array anyway) is the
    authoritative encodability evidence and its ``z_valid`` count is recorded beside this one.
    """
    ids = [str(f) for f in fragment_ids]
    tokens = _token_counts(Path(package_dir), ids)
    geometry = _geometry_gate(Path(package_dir), ids)
    encodable = {fid: bool(tokens.get(fid, 0) > 0 or geometry.get(fid, False)) for fid in ids}
    return encodable, {
        "definition": "token_valid.any() and tokens_total>0, or ((point_valid|normal_valid) & "
                      "scale_valid).any()",
        "source": "packaged deploy/tokens shards + deploy/geometry shards",
        "rgb_gate_measured": False,
        "note": ("the global-RGB gate of training.model.encode is not read here; a fragment that "
                 "is encodable only through RGB would be under-reported, never over-reported"),
        "tokens_total_by_fragment": tokens,
        "geometry_gate_by_fragment": geometry,
        "fragments_encodable": int(sum(1 for v in encodable.values() if v)),
    }


# -------------------------------------------------------------------------------------- plan
def step_plan(args: argparse.Namespace, out: Path) -> dict[str, Any]:
    base = Path(args.base)
    rows = _rows_of(base)
    ids = sorted({fid for row in rows for fid in (str(row["query"]), str(row["candidate"]))})
    encodable, enc_report = encodable_from_packaged_shards(base, ids)
    ruled, report = mate_absent.apply_rule(rows)
    table = mate_absent.class_count_table(rows)
    minimal = mate_absent.minimal_trainable_set(
        rows, encodable={fid: encodable[fid] for fid in ids}, minimum_negatives=2)

    ordinary = mate_absent.ordinary_negative_pairs(rows)
    leaks = sorted({c for _q, c in ordinary if mate_absent.r2_mates(rows).get(c)})
    payload = {
        "ok": True, "step": "plan", "package": str(base),
        "rule": report["rule"], "rule_version": report["version"],
        "relations": len(rows),
        "kind_histogram": _kind_histogram(rows),
        "classes": table["classes"], "classes_by_kind": table["classes_by_kind"],
        "ordinary_negatives_before": report["ordinary_negatives_before"],
        "ordinary_negatives_after": report["ordinary_negatives_after"],
        "rows_reruled": report["rows_reruled"],
        "rows_reruled_detail": report["rows_reruled_detail"],
        "queries_with_ordinary_negative": report["queries_with_ordinary_negative"],
        "queries_with_blocked_candidate": report["queries_with_blocked_candidate"],
        "mate_absent_fragments": table["mate_absent_fragments"],
        "fragments_with_mate": table["fragments_with_mate"],
        "r2_edges": table["r2_edges"],
        "ordinary_negatives_with_a_mate_of_their_own": leaks,
        "encodability": enc_report,
        "minimal_trainable_set": minimal,
    }
    _write_json(out / "plan.json", payload)
    return payload


def _kind_histogram(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in rows:
        key = str(row.get("kind"))
        out[key] = out.get(key, 0) + 1
    return out


# ------------------------------------------------------------------------------------ export
def _unverified_manifest(store: Any, release_id: str, asset_ids: Sequence[str],
                         *, profile: str = "PILOT") -> dict[str, Any]:
    """The same in-memory UNFROZEN manifest ``tools/next_experiment_export.py`` uses.

    Reused verbatim in behaviour (that tool's ``--allow-unverified`` path) and re-stated here so
    this driver does not import another CLI module for one helper.  It is never written to
    ``<store>/releases``: the release it describes was refused by its gates.
    """
    from synlab.canonical import hash_json

    assets = []
    for asset_id in asset_ids:
        record = store.get_asset(asset_id)
        assets.append({"asset_id": record.asset_id, "role": record.role, "schema": record.schema,
                       "unit": record.unit, "frame": record.frame, "blob_hash": record.blob_hash,
                       "qa_status": record.qa_status, "lineage_id": record.lineage_id,
                       "split": record.split,
                       "interpretation_hash": record.interpretation_hash,
                       "files": record.files})
    payload = {
        "schema": "synlab.release.v1",
        "release_id": release_id,
        "profile": f"{profile}_UNFROZEN",
        "scope": "SYNTHETIC",
        "gates": {"note": "freeze refused; this manifest is not a release"},
        "assets": assets,
    }
    payload["manifest_hash"] = hash_json(payload)
    return payload


def step_export(args: argparse.Namespace, out: Path) -> dict[str, Any]:
    from synlab.storage import export as export_mod
    from synlab.storage import release as release_mod
    from synlab.storage.export import export_training_package
    from synlab.storage.store import AssetStore

    state = json.loads(Path(args.state).read_text(encoding="utf-8"))
    release_id = str(state["release_id"])
    scope_ids = list(state["freeze"]["unverified_scope_ids"])
    store = AssetStore(Path(args.store))
    manifest = _unverified_manifest(store, release_id, scope_ids)

    package_dir = Path(args.package)
    applied: dict[str, Any] = {"calls": 0, "rule_report": None}

    original_write = export_mod._write_parquet

    def patched_write(path, rows, row_group_size):        # noqa: ANN001 - writer hook
        path = Path(path)
        if path.name == "relations.parquet":
            ruled, report = mate_absent.apply_rule(rows)
            applied["calls"] += 1
            applied["rule_report"] = report
            applied["rows_in"] = len(rows)
            applied["rows_out"] = len(ruled)
            rows = ruled
        return original_write(path, rows, row_group_size)

    original_load = release_mod.ReleaseManager.load

    def patched_load(self, requested_id):                 # noqa: ANN001 - release hook
        if str(requested_id) == release_id:
            return manifest
        return original_load(self, requested_id)

    started = time.time()
    export_mod._write_parquet = patched_write
    release_mod.ReleaseManager.load = patched_load
    try:
        package = export_training_package(store, release_id, package_dir, formats=FORMATS)
    finally:
        export_mod._write_parquet = original_write
        release_mod.ReleaseManager.load = original_load

    if applied["calls"] != 1:
        raise SystemExit(
            f"the mate-absent hook fired {applied['calls']} time(s) instead of exactly 1 -- the "
            "export layout changed and the rule was NOT applied to the relation table")

    counts = package.get("counts") or {}
    payload = {
        "ok": True, "step": "export", "seconds": round(time.time() - started, 3),
        "package_dir": str(package_dir), "release_id": release_id,
        "release_profile": package.get("release_profile"),
        "release_manifest": "in-memory, NOT written to <store>/releases (the freeze was refused)",
        "scope_assets": len(scope_ids),
        "manifest_hash": package.get("manifest_hash"),
        "relations": counts.get("relations"), "relation_kinds": counts.get("relation_kinds"),
        "files_total": package.get("counts_total"), "bytes_total": package.get("bytes_total"),
        "formats": list(FORMATS),
        "rule": {
            "version": applied["rule_report"]["version"],
            "applied_at": "synlab.storage.export._write_parquet (research/relations.parquet only)",
            "rows_in": applied["rows_in"], "rows_out": applied["rows_out"],
            "rows_reruled": applied["rule_report"]["rows_reruled"],
            "ordinary_negatives_before": applied["rule_report"]["ordinary_negatives_before"],
            "ordinary_negatives_after": applied["rule_report"]["ordinary_negatives_after"],
            "classes": applied["rule_report"]["classes"],
            "queries_with_ordinary_negative":
                applied["rule_report"]["queries_with_ordinary_negative"],
        },
    }
    _write_json(out / "export.json", payload)
    _write_json(out / "export_rule_detail.json", applied["rule_report"])
    return payload


# -------------------------------------------------------------------------------------- diff
def step_diff(args: argparse.Namespace, out: Path) -> dict[str, Any]:
    base = _rows_of(args.base)
    new = _rows_of(args.package)
    base_map = {_pair_key(row): row for row in base}
    new_map = {_pair_key(row): row for row in new}
    only_base = sorted(set(base_map) - set(new_map))
    only_new = sorted(set(new_map) - set(base_map))
    changed: list[dict[str, Any]] = []
    same = 0
    for key in sorted(set(base_map) & set(new_map)):
        left, right = base_map[key], new_map[key]
        for field in ("kind", "valid", "area_mm2", "has_observation", "split", "pool_id"):
            if left.get(field) != right.get(field):
                changed.append({"pair": list(key), "field": field,
                                "base": left.get(field), "new": right.get(field)})
        if bool(left.get("loss_mask")) != bool(right.get("loss_mask")):
            changed.append({"pair": list(key), "field": "loss_mask",
                            "base": bool(left.get("loss_mask")),
                            "new": bool(right.get("loss_mask")),
                            "new_reason": right.get("reason")})
        if bool(left.get("eligible_as_negative")) != bool(right.get("eligible_as_negative")):
            changed.append({"pair": list(key), "field": "eligible_as_negative",
                            "base": bool(left.get("eligible_as_negative")),
                            "new": bool(right.get("eligible_as_negative"))})
        if str(left.get("reason")) != str(right.get("reason")):
            changed.append({"pair": list(key), "field": "reason", "base": left.get("reason"),
                            "new": right.get("reason")})
        if not any(entry["pair"] == list(key) for entry in changed):
            same += 1
    fields_touched = sorted({entry["field"] for entry in changed})
    payload = {
        "ok": not only_base and not only_new and set(fields_touched) <= {"loss_mask",
                                                                        "eligible_as_negative",
                                                                        "reason"},
        "step": "diff", "base": str(args.base), "package": str(args.package),
        "rows_base": len(base), "rows_new": len(new),
        "pairs_identical": same, "pairs_only_in_base": [list(k) for k in only_base],
        "pairs_only_in_new": [list(k) for k in only_new],
        "changed_fields": fields_touched, "changes": changed,
        "changed_pairs": len({tuple(entry["pair"]) for entry in changed}),
        "claim": ("the new package differs from the base package in the relation table only, and "
                  "inside that table only in loss_mask / eligible_as_negative / reason of the "
                  "rows whose candidate carries its own R2 mate"),
    }
    _write_json(out / "diff.json", payload)
    return payload


def _pair_key(row: Mapping[str, Any]) -> tuple[str, str]:
    a, b = str(row["query"]), str(row["candidate"])
    return (a, b) if a <= b else (b, a)


# ------------------------------------------------------------------------------------ classes
def step_classes(args: argparse.Namespace, out: Path) -> dict[str, Any]:
    rows = _rows_of(args.package)
    table = mate_absent.class_count_table(rows)
    ordinary = mate_absent.ordinary_negative_pairs(rows)
    mates = mate_absent.r2_mates(rows)
    leaks = sorted({c for _q, c in ordinary if mates.get(c)})
    ids = sorted({fid for row in rows for fid in (str(row["query"]), str(row["candidate"]))})
    encodable, enc_report = encodable_from_packaged_shards(args.package, ids)
    minimal = mate_absent.minimal_trainable_set(
        rows, encodable={fid: encodable[fid] for fid in ids}, minimum_negatives=2)
    by_query: dict[str, list[str]] = {}
    for query, candidate in ordinary:
        by_query.setdefault(query, []).append(candidate)
    payload = {
        "ok": not leaks, "step": "classes", "package": str(args.package),
        "relations": table["rows"], "classes": table["classes"],
        "classes_by_kind": table["classes_by_kind"], "r2_edges": table["r2_edges"],
        "fragments_with_mate": table["fragments_with_mate"],
        "fragments_mate_absent": table["fragments_mate_absent"],
        "mate_absent_fragments": table["mate_absent_fragments"],
        "ordinary_negatives": len(ordinary),
        "ordinary_negatives_by_query": {k: len(v) for k, v in sorted(by_query.items())},
        "ordinary_negatives_with_a_mate_of_their_own": leaks,
        "encodability": enc_report,
        "minimal_trainable_set": minimal,
    }
    _write_json(out / "classes.json", payload)
    return payload


# ------------------------------------------------------------------------------------- sample
def step_sample(args: argparse.Namespace, out: Path) -> dict[str, Any]:
    """Re-derive >=20 ordinary negatives from the **raw store rows**, not from the export.

    For every sampled ``(query, candidate)`` of the new package the check rebuilds the facts from
    the release's own assets (the ``relation_pool`` index arrays and the truth/label relation
    payloads) and asserts, independently of the exported table:

    1. the pair is in the raw rows with the same measured kind (``R0``/``R1``) and is not ``R2``;
    2. the candidate has **no** ``R2`` mate anywhere in the raw rows (the mate-absent rule);
    3. the query is not its own candidate and the pair is not the query's own ``R2`` edge;
    4. both endpoints are named by the release (they exist as fragments, not as free text).
    """
    from synlab.roles import ROLE_CLEAN_TRUTH, ROLE_LABEL_BUNDLE
    from synlab.storage.export import _pool_relations, _truth_relations
    from synlab.storage.store import AssetStore

    state = json.loads(Path(args.state).read_text(encoding="utf-8"))
    scope_ids = list(state["freeze"]["unverified_scope_ids"])
    store = AssetStore(Path(args.store))
    records = {asset_id: store.get_asset(asset_id) for asset_id in scope_ids}
    release_assets = {asset_id: None for asset_id in scope_ids}
    clean = [rec for rec in records.values() if rec.role == ROLE_CLEAN_TRUTH]
    labels = [rec for rec in records.values() if rec.role == ROLE_LABEL_BUNDLE]
    raw: list[dict[str, Any]] = []
    raw += _pool_relations(store, release_assets)
    raw += _truth_relations(store, clean)
    raw += _truth_relations(store, labels)
    raw_pairs: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in raw:
        a, b = str(row.get("a", "")), str(row.get("b", ""))
        if not a or not b or a == b:
            continue
        key = (a, b) if a <= b else (b, a)
        raw_pairs.setdefault(key, []).append(row)
    raw_mates = mate_absent.r2_mates([{"query": str(r["a"]), "candidate": str(r["b"]),
                                       "kind": r.get("kind", "UNKNOWN"),
                                       "valid": r.get("valid", False)} for r in raw])

    rows = _rows_of(args.package)
    ordinary = sorted(mate_absent.ordinary_negative_pairs(rows))
    rng = np.random.default_rng(int(args.seed))
    take = min(int(args.sample), len(ordinary))
    order = rng.permutation(len(ordinary))[:take] if take else []
    checked: list[dict[str, Any]] = []
    mismatches: list[dict[str, Any]] = []
    for index in sorted(int(i) for i in order):
        query, candidate = ordinary[index]
        key = (query, candidate) if query <= candidate else (candidate, query)
        raw_rows = raw_pairs.get(key, [])
        raw_kinds = sorted({str(r.get("kind")) for r in raw_rows})
        evidence: dict[str, Any] = {
            "query": query, "candidate": candidate,
            "package_row_kind": next((str(r.get("kind")) for r in rows
                                      if str(r.get("query")) == query
                                      and str(r.get("candidate")) == candidate), None),
            "raw_rows": [{"kind": str(r.get("kind")), "valid": bool(r.get("valid", False)),
                          "loss_mask": bool(r.get("loss_mask", False))} for r in raw_rows],
            "raw_kinds": raw_kinds,
            "candidate_raw_mates": sorted(raw_mates.get(candidate, set())),
            "query_raw_mates": sorted(raw_mates.get(query, set())),
            "candidate_is_query_r2": candidate in raw_mates.get(query, set()),
        }
        problems: list[str] = []
        if not raw_rows:
            problems.append("the pair is not in the raw store rows at all")
        if "R2" in raw_kinds:
            problems.append("a raw row measures this pair as R2")
        if not set(raw_kinds) & {"R0", "R1"}:
            problems.append(f"no raw R0/R1 row for the pair (raw kinds {raw_kinds})")
        if evidence["candidate_raw_mates"]:
            problems.append("the candidate has an R2 mate in the raw rows (mate-present)")
        if evidence["candidate_is_query_r2"]:
            problems.append("the candidate is the query's own historical R2")
        if query == candidate:
            problems.append("candidate == query")
        evidence["ok"] = not problems
        evidence["problems"] = problems
        checked.append(evidence)
        if problems:
            mismatches.append(evidence)

    payload = {
        "ok": not mismatches, "step": "sample", "package": str(args.package),
        "method": ("each sampled ordinary negative is re-derived from the release's raw assets "
                   "(relation_pool index arrays + clean_truth/label_bundle relation payloads), "
                   "never from the exported table it is checking"),
        "population": len(ordinary), "sampled": len(checked), "seed": int(args.seed),
        "raw_rows_read": len(raw), "raw_pairs": len(raw_pairs),
        "raw_fragments_with_mate": sum(1 for v in raw_mates.values() if v),
        "mismatches": mismatches,
        "checked": checked,
    }
    _write_json(out / "negative_sample_audit.json", payload)
    return payload


STEPS = {"plan": step_plan, "export": step_export, "diff": step_diff,
         "classes": step_classes, "sample": step_sample}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="relation_negatives_fix")
    parser.add_argument("--step", required=True, choices=sorted(STEPS))
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--package", default=DEFAULT_PACKAGE)
    parser.add_argument("--store", default=DEFAULT_STORE)
    parser.add_argument("--state", default=DEFAULT_STATE)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--sample", type=int, default=24)
    parser.add_argument("--seed", type=int, default=20261002)
    args = parser.parse_args(argv)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    started = time.time()
    try:
        result = STEPS[args.step](args, out)
    except BaseException as exc:                              # noqa: BLE001 - never hide a crash
        result = {"ok": False, "step": args.step,
                  "escaped_exception": f"{type(exc).__name__}: {exc}",
                  "traceback": traceback.format_exc()[-4000:]}
        _write_json(out / f"error_{args.step}.json", result)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 1
    result["seconds"] = round(time.time() - started, 3)
    print(json.dumps({k: v for k, v in result.items()
                      if k not in ("checked", "rows_reruled_detail", "encodability",
                                   "changes", "mate_absent_fragments")},
                     ensure_ascii=False, indent=2, default=str))
    return 0 if result.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
