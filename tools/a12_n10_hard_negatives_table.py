#!/usr/bin/env python
"""N10: the ``HARD_NEGATIVE_MATE_PRESENT`` auxiliary table, its card and the one-key switch.

The class (the S2 rows whose candidate carries its own confirmed ``R2`` mate) may not be an
ordinary negative, and it may not be appended to ``research/relations.parquet``: its contract
(``loss_mask=True`` with ``eligible_as_negative=False``) violates decision D10's single gate on
every row -- measured with the real checker at **+880 violations**.  The Lead approved an
independent auxiliary table instead.  This driver builds it, verifies it, and demonstrates the
loader switch:

``--step build``
    Read the package's ``research/relations.parquet``, classify it with
    ``relations.mate_absent.hard_negative_records``, write ``hard_negatives.parquet`` plus its
    sidecar card (column dictionary, constraints, rejected rows) and a report with the measured
    counts.  ``relations.parquet`` is never written.

``--step verify``
    Re-read the written bytes and re-measure: row/column counts, the four ruling conditions, the
    D10 merge counter-proof (real checker, temp packages), the undeclared-extra rule of the
    package checker (minimal fixture, so no real package is modified), and the **one-key
    ablation**: a real batch built with the switch off and on, whose primary denominators must be
    identical and whose ``neg_mask`` must not move.

``--step install``
    Write the table into a package's ``research/`` layer (``--research-dir``) and report exactly
    what package-level integration still needs (a manifest entry and a card column block, both
    written by the exporter -- outside this task's write scope).

Usage::

    python tools/a12_n10_hard_negatives_table.py --step all \
        --package data/a12_exports/negfix/next_experiment/training_package \
        --out data/a12_reports/n10/hard_negatives.parquet
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_PACKAGE = "data/a12_exports/negfix/next_experiment/training_package"
DEFAULT_OUT = "data/a12_reports/n10/hard_negatives.parquet"
DEFAULT_QUERY = "LIN0101_V16_M12_PAT12_E01-m"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def relation_rows(package_dir: str | Path) -> tuple[Any, list[dict[str, Any]]]:
    """The package's relation rows, with the main table's hash for provenance."""
    from synlab.storage.export import TrainingPackage

    package = TrainingPackage(package_dir)
    return package, [dict(row) for row in package.relations()]


# --------------------------------------------------------------------------------------
# --step build
# --------------------------------------------------------------------------------------
def build_step(package_dir: str | Path, *, out: str | Path) -> dict[str, Any]:
    from synlab.relations.hard_negatives_table import (HARD_NEGATIVES_FILE, build_records,
                                                       card_payload, write_table)

    started = time.perf_counter()
    package, rows = relation_rows(package_dir)
    relations_path = Path(package_dir) / "research" / "relations.parquet"
    relations_hash = _sha256(relations_path)
    records, report = build_records(rows, source_relations_hash=relations_hash)
    card = card_payload(source_package=str(package_dir), source_relations_hash=relations_hash,
                        rows=len(records), rejected=report["rejected"],
                        rejected_examples=report.get("rejected_rows", []))
    written = write_table(records, out, card=card)
    after_hash = _sha256(relations_path)
    kinds: dict[str, int] = {}
    for record in records:
        kinds[str(record["kind"])] = kinds.get(str(record["kind"]), 0) + 1
    return {
        "schema": "synlab.a12.n10.hard_negatives.build.v1",
        "step": "build",
        "package_dir": str(package_dir),
        "table_file": HARD_NEGATIVES_FILE,
        "written": written,
        "rows": len(records),
        "rows_by_kind": dict(sorted(kinds.items())),
        "queries": len({str(r["query"]) for r in records}),
        "candidates": len({str(r["candidate"]) for r in records}),
        "class_report": {key: value for key, value in report.items()
                         if key not in ("rejected_rows",)},
        "conformance": report["conformance"],
        "rejected_rows": report["rejected"],
        "rejected_examples": [dict(item) for item in report.get("rejected_rows", [])[:5]],
        "relations_parquet": {"path": str(relations_path), "hash_before": relations_hash,
                              "hash_after": after_hash,
                              "untouched": relations_hash == after_hash},
        "package_files_verified": bool(package.verify_files()["ok"]),
        "wall_seconds": time.perf_counter() - started,
    }


# --------------------------------------------------------------------------------------
# --step verify
# --------------------------------------------------------------------------------------
def _d10_counter_proof(rows: Sequence[Mapping[str, Any]], records: Sequence[Mapping[str, Any]]
                       ) -> dict[str, Any]:
    """Re-measure what appending the class to the main table would do to decision D10."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    from synlab.qc.decision_checks import _check_loss_mask_authority

    def _write(root: Path, name: str, payload: Sequence[Mapping[str, Any]]) -> None:
        target = root / name
        target.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.table({
            "query": pa.array([str(r["query"]) for r in payload]),
            "candidate": pa.array([str(r["candidate"]) for r in payload]),
            "kind": pa.array([str(r.get("kind", "R0")) for r in payload]),
            "valid": pa.array([bool(r.get("valid", False)) for r in payload]),
            "loss_mask": pa.array([bool(r.get("loss_mask", False)) for r in payload]),
            "eligible_as_negative": pa.array([bool(r.get("eligible_as_negative", False))
                                              for r in payload]),
        }), target / "relations.parquet")

    out: dict[str, Any] = {"checker": "synlab.qc.decision_checks._check_loss_mask_authority",
                           "gate": ("eligible_as_negative == (kind in {R0,R1} and loss_mask) "
                                    "and valid == loss_mask for every row")}
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write(root, "separate", rows)
        _write(root, "merged", list(rows) + [dict(r) for r in records])
        for name in ("separate", "merged"):
            result = _check_loss_mask_authority(root / name)
            out[name] = {"status": str(result.status), "rows": int(result.denominator),
                         "hits": int(result.hits),
                         "violations": int(result.denominator - result.hits)}
    out["delta"] = {"rows_added": int(out["merged"]["rows"] - out["separate"]["rows"]),
                    "violations_added": int(out["merged"]["violations"]
                                            - out["separate"]["violations"])}
    out["conclusion"] = (f"appending the class to research/relations.parquet adds "
                         f"{out['delta']['rows_added']} rows and "
                         f"{out['delta']['violations_added']} decision-D10 violations -- it stays "
                         f"a separate table")
    return out


def _undeclared_extra_rule() -> dict[str, Any]:
    """Measure the package checker's rule on a **minimal fixture** (no real package touched)."""
    from tools.load_package import check_package            # type: ignore  # noqa: PLC0415

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "fixture_package"
        (root / "research").mkdir(parents=True)
        declared = root / "research" / "relations.parquet"
        declared.write_bytes(b"not-parquet")                # content is irrelevant to this rule
        extra = root / "research" / "hard_negatives.parquet"
        extra.write_bytes(b"auxiliary")
        manifest = {"schema": "synlab.training_package_manifest.v1",
                    "files": [{"path": "research/relations.parquet", "hash": _sha256(declared),
                               "bytes": declared.stat().st_size, "note": "fixture"}]}
        (root / "export_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        try:
            result = check_package(root)
            file_set = result["checks"]["file_set"]
            ok = bool(file_set["ok"])
            unexpected = list(file_set["unexpected_extra"])
        except Exception as exc:  # noqa: BLE001 - the failure is the measurement
            return {"measured": False, "error": f"{type(exc).__name__}: {exc}"}
    return {
        "measured": True,
        "fixture": "minimal package (one declared file + the auxiliary table) in a temp dir",
        "file_set_ok": ok,
        "unexpected_extra": unexpected,
        "rule": ("tools/load_package.py::check_package reports any on-disk file that the manifest "
                 "does not declare as an undeclared extra and exits 3"),
        "consequence": ("writing <package>/research/hard_negatives.parquet without declaring it in "
                        "the manifest therefore breaks the package's own --check; the declaring "
                        "writer is synlab/storage/export.py (outside this task's write scope)"),
    }


def _ablation(package_dir: str | Path, *, query: str, negatives: int, hard_negatives: int,
              table_path: str | Path, token_budget: int) -> dict[str, Any]:
    """The one-key switch on a real batch: primary denominators must not move."""
    from synlab.qc.loader_probe import _pool_id, load_features
    from synlab.relations.hard_negatives_table import (attach_hard_negatives, load_hard_negatives,
                                                       denominator_snapshot)
    from synlab.storage.export import TrainingPackage
    from synlab.training.adapter import FeatureBundle
    from synlab.training.batch import build_training_batch, negative_audit
    from synlab.training.smoke import TrainingPoolView

    package = TrainingPackage(package_dir)
    rows = [dict(row) for row in package.relations()]
    table = load_hard_negatives(table_path, enabled=False)
    candidates = table.by_query(query)[: int(hard_negatives)]
    pool = TrainingPoolView(rows, lineup=sorted({str(r["query"]) for r in rows}
                                                | {str(r["candidate"]) for r in rows}
                                                | {query} | set(candidates)),
                            pool_id=_pool_id(rows))
    positives = sorted(str(x) for x in pool.mates(query))
    legal = [c for c in pool.legal_pool(query) if c not in set(candidates)]
    chosen_negatives = legal[: int(negatives)]
    if not chosen_negatives or not positives:
        return {"ok": False, "reason": "the chosen query has no legal negative or no positive",
                "query": query, "positives": positives, "legal": len(legal)}
    subset = [query] + positives[:1] + chosen_negatives + candidates
    payloads = load_features(package, subset, token_budget=token_budget)
    bundle = FeatureBundle.from_dict(payloads, token_budget=token_budget).check_shapes()
    base_rows = [{"query": query, "positives": positives[:1], "negatives": chosen_negatives,
                  "sample_key": f"n10::{query}"}]
    off_rows = attach_hard_negatives(base_rows, table, enabled=False)
    on_rows = attach_hard_negatives(base_rows, table, enabled=True)
    off = build_training_batch(bundle, pool=pool, rows=off_rows)
    on = build_training_batch(bundle, pool=pool, rows=on_rows)
    off_snapshot = denominator_snapshot(off)
    on_snapshot = denominator_snapshot(on)
    primary = [key for key in off_snapshot if key != "hard_negatives"]
    identical = all(off_snapshot[key] == on_snapshot[key] for key in primary)
    return {
        "ok": bool(identical and on_snapshot["hard_negatives"] == len(candidates)
                   and off_snapshot["hard_negatives"] == 0),
        "query": query,
        "subset": subset,
        "positives": positives[:1],
        "negatives": chosen_negatives,
        "hard_negatives": candidates,
        "off": off_snapshot,
        "on": on_snapshot,
        "primary_denominators_identical": identical,
        "neg_mask_identical": bool(np.array_equal(off.neg_mask, on.neg_mask)),
        "pos_mask_identical": bool(np.array_equal(off.pos_mask, on.pos_mask)),
        "hard_neg_mask_is_a_separate_block": bool(on.hard_neg_mask.any()
                                                  and not (on.hard_neg_mask & on.neg_mask).any()),
        "negative_audit": {"off": negative_audit(off), "on": negative_audit(on)},
        "note": ("the switch only adds the separate 'hard_negatives' key; every primary "
                 "denominator and both primary masks are bit-identical"),
    }


def verify_step(package_dir: str | Path, *, table_path: str | Path, query: str,
                negatives: int, hard_negatives: int, token_budget: int) -> dict[str, Any]:
    from synlab.relations.hard_negatives_table import (COLUMNS, HARD_NEGATIVES_CARD_FILE,
                                                       load_hard_negatives)

    package, rows = relation_rows(package_dir)
    table = load_hard_negatives(table_path, enabled=False)
    constraints = table.assert_constraints()
    card_path = Path(table_path).with_name(HARD_NEGATIVES_CARD_FILE)
    card = json.loads(card_path.read_text(encoding="utf-8")) if card_path.is_file() else {}
    relations_path = Path(package_dir) / "research" / "relations.parquet"
    relations_hash = _sha256(relations_path)
    payload: dict[str, Any] = {
        "schema": "synlab.a12.n10.hard_negatives.verify.v1",
        "step": "verify",
        "table": {"path": str(table_path), "rows": table.n_rows,
                  "columns": table.columns(), "columns_declared": list(COLUMNS),
                  "columns_match": constraints["columns_match"],
                  "counts": table.counts(), "constraints": constraints,
                  "card_path": str(card_path) if card_path.is_file() else "",
                  "card_constraints": sorted((card.get("constraints") or {}).keys()),
                  "provenance": table.provenance,
                  "source_relations_hash_matches": bool(
                      table.provenance.get("source", {}).get("relations_parquet_hash",
                                                             "") == relations_hash)},
        "relations_parquet_untouched": bool(
            table.provenance.get("source", {}).get("relations_parquet_hash", "") == relations_hash),
        "not_in_the_main_table": bool(
            all(str(r.get("class")) != "HARD_NEGATIVE_MATE_PRESENT" for r in rows)),
        "d10_counter_proof": _d10_counter_proof(rows, table.rows),
        "undeclared_extra_rule": _undeclared_extra_rule(),
        "ablation": _ablation(package_dir, query=query, negatives=negatives,
                              hard_negatives=hard_negatives, table_path=table_path,
                              token_budget=token_budget),
        "package_files_verified": bool(package.verify_files()["ok"]),
    }
    payload["ok"] = bool(
        payload["table"]["columns_match"] and constraints["ok"]
        and payload["table"]["counts"]["all_eligible_false"]
        and payload["table"]["counts"]["all_loss_mask_true"]
        and payload["table"]["counts"]["all_query_mate_present"]
        and payload["relations_parquet_untouched"] and payload["not_in_the_main_table"]
        and payload["d10_counter_proof"]["delta"]["violations_added"] > 0
        and payload["ablation"].get("ok") and payload["package_files_verified"])
    return payload


# --------------------------------------------------------------------------------------
# --step install
# --------------------------------------------------------------------------------------
def install_step(*, research_dir: str | Path, table_path: str | Path) -> dict[str, Any]:
    """Copy the table (+card) into a ``research/`` layer and state the integration step."""
    import shutil

    from synlab.relations.hard_negatives_table import (HARD_NEGATIVES_CARD_FILE,
                                                       HARD_NEGATIVES_FILE)

    target_dir = Path(research_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    table_target = target_dir / HARD_NEGATIVES_FILE
    shutil.copyfile(table_path, table_target)
    card_source = Path(table_path).with_name(HARD_NEGATIVES_CARD_FILE)
    card_target = target_dir / HARD_NEGATIVES_CARD_FILE
    if card_source.is_file():
        shutil.copyfile(card_source, card_target)
    package_root = target_dir.parent
    return {
        "schema": "synlab.a12.n10.hard_negatives.install.v1",
        "step": "install",
        "research_dir": str(target_dir),
        "table": {"path": str(table_target), "hash": _sha256(table_target),
                  "bytes": table_target.stat().st_size},
        "card": str(card_target) if card_target.is_file() else "",
        "package_root": str(package_root),
        "still_required_for_a_green_package_check": [
            "declare research/hard_negatives.parquet in export_manifest.json (files entry with "
            "its sha256) -- written by synlab/storage/export.py, outside this task's write scope",
            "add its column block to dataset_card.json (tools/load_package.py --write-card "
            "regenerates the card from the package bytes)",
        ],
        "measured_consequence_if_not_declared": ("tools/load_package.py::check_package reports "
                                                 "the file as an undeclared extra and exits 3"),
    }


# --------------------------------------------------------------------------------------
def _summary(payload: Mapping[str, Any]) -> str:
    lines: list[str] = []
    build = payload.get("build")
    if build:
        lines.append(f"build: rows={build['rows']} kinds={build['rows_by_kind']} "
                     f"rejected={build['rejected_rows']} "
                     f"relations_untouched={build['relations_parquet']['untouched']} "
                     f"-> {build['written']['path']}")
    verify = payload.get("verify")
    if verify:
        table = verify["table"]
        lines.append(f"verify: columns_match={table['columns_match']} "
                     f"constraints_ok={table['constraints']['ok']} "
                     f"d10_violations_added={verify['d10_counter_proof']['delta']['violations_added']} "
                     f"ok={verify['ok']}")
        abl = verify.get("ablation", {})
        if abl.get("ok") is not None:
            lines.append(f"  ablation: primary denominators identical="
                         f"{abl.get('primary_denominators_identical')} neg_mask identical="
                         f"{abl.get('neg_mask_identical')} hard={abl.get('on', {}).get('hard_negatives')}")
        rule = verify.get("undeclared_extra_rule", {})
        lines.append(f"  undeclared-extra rule measured: {rule.get('file_set_ok')} "
                     f"unexpected={rule.get('unexpected_extra')}")
    install = payload.get("install")
    if install:
        lines.append(f"install: {install['table']['path']} "
                     f"({len(install['still_required_for_a_green_package_check'])} integration "
                     f"step(s) still required)")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--step", default="all", choices=("build", "verify", "install", "all"))
    parser.add_argument("--package", default=DEFAULT_PACKAGE)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument("--negatives", type=int, default=3)
    parser.add_argument("--hard-negatives", type=int, default=3)
    parser.add_argument("--token-budget", type=int, default=64)
    parser.add_argument("--research-dir", default="")
    parser.add_argument("--report", default="data/a12_reports/n10_hard_negatives.json")
    args = parser.parse_args(argv)

    payload: dict[str, Any] = {"schema": "synlab.a12.n10.hard_negatives.run.v1"}
    ok = True
    if args.step in ("build", "all"):
        payload["build"] = build_step(args.package, out=args.out)
        ok = bool(ok and payload["build"]["relations_parquet"]["untouched"]
                  and payload["build"]["conformance"]["loss_mask_true_and_eligible_false"]
                  and payload["build"]["package_files_verified"])
    if args.step in ("verify", "all"):
        payload["verify"] = verify_step(args.package, table_path=args.out, query=args.query,
                                        negatives=args.negatives,
                                        hard_negatives=args.hard_negatives,
                                        token_budget=args.token_budget)
        ok = bool(ok and payload["verify"]["ok"])
    if args.step == "install" or (args.step == "all" and args.research_dir):
        payload["install"] = install_step(research_dir=args.research_dir, table_path=args.out)

    payload["ok"] = ok
    payload["status"] = "PASS" if ok else "FAIL"
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True,
                                      default=str), encoding="utf-8")
    print(_summary(payload))
    print(f"status={payload['status']} report={report_path}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
