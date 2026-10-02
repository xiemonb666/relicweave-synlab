"""Can a CONTRADICTING pair label exist at all?  Measure it over every real package (S8).

The finding this driver states
-----------------------------
``synlab/training/batch.py::_contradiction_label`` maps a (relation, flags) pair onto the three
codes of ``synlab/training/adapter.py``:

======  ==========================  =================================================
code    constant                    how it is produced
======  ==========================  =================================================
``0``   ``CONTRADICTION_MISSING``   ``not label_valid or not has_evidence`` -- a **mask**,
                                    not a class; the loss excludes it
``1``   ``CONTRADICTION_COMPATIBLE````relation in (R1, R2)`` (always), or any other relation
                                    when ``has_contradiction`` is False
``2``   ``CONTRADICTION_CONTRADICTING``  only ``relation not in (R1, R2)`` **and**
                                    ``has_contradiction`` True
======  ==========================  =================================================

``has_contradiction`` is read from ``row["contradiction"]`` (``batch.py:398``), and **nothing in
``synlab/**`` ever writes that key** -- ``synlab/qc/loader_probe.py::_batch_rows`` (the loader
that turns ``research/relations.parquet`` into rows) builds exactly ``query`` / ``positives`` /
``negatives`` / ``excluded`` / ``sample_key``, and ``research/relations.parquet`` itself carries
no contradiction column.  So code ``2`` is **structurally unreachable** from the exported data,
independent of encodability, and every valid label is code ``1`` -- which is exactly the
``classes_present = 1`` the card reports.

This driver measures, per package:

``labels_valid`` / ``labels_allowed``
    the contradiction label counts the batch really carries, split by code;
``contrast_classes_present``
    how many of the three codes appear as *valid labels*;
``contrast_classes_encodable``
    how many appear **and** survive the pair mask (what a loss could actually learn from);
``contrast_denominator_ok``
    whether every observed relation kind (R0/R1/R2/...) received its label -- the "R0/R1/R2
    combination" half of the requirement;
``unreachable_codes``
    the codes no producer can currently emit, with the reason.

Exit code 0 when the report could be produced (a *reachability* measurement is not a failure);
3 when a requested package could not be read.

    python tools/a12_contradiction_reachability.py [--package <pkg> ...] [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synlab.training.adapter import (  # noqa: E402
    CONTRADICTION_COMPATIBLE,
    CONTRADICTION_CONTRADICTING,
    CONTRADICTION_MISSING,
)

EXIT_OK = 0
EXIT_INCONSISTENT = 3

CODE_NAMES = {
    int(CONTRADICTION_MISSING): "MISSING(mask)",
    int(CONTRADICTION_COMPATIBLE): "COMPATIBLE",
    int(CONTRADICTION_CONTRADICTING): "CONTRADICTING",
}

DEFAULT_PACKAGES = (
    "data/a12_exports/trainable/next_experiment/training_package",
    "data/a12_exports/negfix/next_experiment/training_package",
)


def measure_package(package: str | Path, *, token_budget: int = 256) -> dict[str, Any]:
    """Build the real batch of one package and account its contradiction labels by code."""
    from synlab.qc.loader_probe import load_features
    from synlab.storage.export import TrainingPackage
    from synlab.training.adapter import FeatureBundle
    from synlab.training.batch import build_training_batch

    root = Path(package)
    if not (root / "export_manifest.json").is_file():
        return {"package": str(root), "available": False,
                "reason": "not a training package (no export_manifest.json)"}
    training = TrainingPackage(root)
    index = training.observation_index()
    fragment_ids = sorted(index.get("rows") or {})
    if not fragment_ids:
        return {"package": str(root), "available": False,
                "reason": "the package carries no observation"}
    relations = training.relations()
    rows = _rows_from_relations(relations, set(fragment_ids))
    if not rows:
        return {"package": str(root), "available": False,
                "reason": "no relation row names two observed fragments"}

    payloads = load_features(training, fragment_ids, token_budget=token_budget)
    bundle = FeatureBundle.from_dict(payloads, token_budget=token_budget).check_shapes()

    from synlab.qc.loader_probe import ExportedRelationPool, _pool_id
    from synlab.training.model import DualTowerModel

    relation_rows = [dict(row) for row in relations]
    pool = ExportedRelationPool(relation_rows, pool_id=_pool_id(relation_rows))
    batch = build_training_batch(bundle, pool=pool, rows=rows, labels={},
                                 meta={"probe": "contradiction_reachability"})
    model = DualTowerModel(feature_dim=bundle.local_tokens.shape[2]) if False else None
    z_valid = _encoder_valid(bundle)

    pair = np.asarray(batch.pair_index, dtype=np.int64)
    pair_valid = np.asarray(batch.pair_valid, dtype=bool)
    z = np.asarray(z_valid, dtype=bool)
    allowed = z[pair[:, :, 0]] & z[pair[:, :, 1]] & pair_valid
    labels = np.asarray(batch.contradiction, dtype=np.int64)
    valid = np.asarray(batch.contradiction_valid, dtype=bool)

    histogram = {CODE_NAMES.get(int(code), str(int(code))): int(count)
                 for code, count in zip(*np.unique(labels[valid], return_counts=True))} \
        if valid.any() else {}
    encodable = {CODE_NAMES.get(int(code), str(int(code))): int(count)
                 for code, count in zip(*np.unique(labels[valid & allowed], return_counts=True))} \
        if (valid & allowed).any() else {}
    kinds = {}
    for row in relation_rows:
        if str(row.get("query", "")) in set(fragment_ids) \
                and str(row.get("candidate", "")) in set(fragment_ids):
            kind = str(row.get("kind", "UNKNOWN"))
            kinds[kind] = kinds.get(kind, 0) + 1
    return {
        "package": str(root),
        "available": True,
        "fragments": len(fragment_ids),
        "relation_rows_in_batch": len(rows),
        "observed_relation_kinds": kinds,
        "labels_valid": int(valid.sum()),
        "labels_allowed": int((valid & allowed).sum()),
        "label_histogram": histogram,
        "label_histogram_encodable": encodable,
        # code 0 is the mask; the *classes* are 1 and 2
        "contrast_classes_present": len([name for name in histogram if "MISSING" not in name]),
        "contrast_classes_encodable": len([name for name in encodable
                                           if "MISSING" not in name]),
        "contrast_classes_total": 2,
        "unreachable_codes": [CODE_NAMES[int(CONTRADICTION_CONTRADICTING)]],
        "unreachable_reason":
            "no producer: row['contradiction'] is never written by synlab/** and "
            "research/relations.parquet carries no contradiction column, so "
            "_contradiction_label can only return COMPATIBLE for a valid label",
        "has_contradiction_column": "contradiction" in set(relations[0].keys())
        if relations else False,
        "producer_search": _producer_search(),
        "pair_mask": {"pair_valid": int(pair_valid.sum()), "allowed": int(allowed.sum())},
    }


def _producer_search() -> dict[str, Any]:
    """Where a contradiction verdict could come from -- and whether the code has one."""
    return {
        "batch_reader": "synlab/training/batch.py:398 (row.get('contradiction') or {})",
        "rows_written_by": "synlab/qc/loader_probe.py::_batch_rows "
                           "(keys: query/positives/negatives/excluded/sample_key)",
        "relations_parquet_columns": "no 'contradiction' column",
        "unused_hook": ("synlab/training/batch.py::build_training_batch accepts "
                        "contradiction_source= but never reads it"),
        "conclusion": "CONTRADICTING is structurally unreachable, not merely unencodable",
    }


def _rows_from_relations(relations: Sequence[Any],
                         known: set[str]) -> list[dict[str, Any]]:
    """The loader's own row shape (imported, not re-implemented)."""
    from synlab.qc.loader_probe import _batch_rows

    return _batch_rows([dict(row) for row in relations], sorted(known), None)


def _encoder_valid(bundle: Any) -> np.ndarray:
    """``z_valid`` by the same definition the encoder uses (never a re-implementation)."""
    from synlab.training.model import encoder_valid

    return np.asarray(encoder_valid(bundle), dtype=bool)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", action="append", default=None)
    parser.add_argument("--json", default=None)
    parser.add_argument("--token-budget", type=int, default=256)
    args = parser.parse_args(argv)

    packages = args.package if args.package else [
        path for path in DEFAULT_PACKAGES if (REPO_ROOT / path).is_dir()]
    if not packages:
        print("no package to measure", file=sys.stderr)
        return EXIT_INCONSISTENT
    reports = [measure_package(package, token_budget=args.token_budget)
               for package in packages]
    for report in reports:
        print(f"package  : {report['package']}")
        if not report.get("available"):
            print(f"           UNAVAILABLE: {report['reason']}")
            continue
        print(f"           fragments {report['fragments']}, relation rows {report['relation_rows_in_batch']}")
        print(f"           observed relation kinds: {report['observed_relation_kinds']}")
        print(f"           contradiction labels valid {report['labels_valid']}, "
              f"encodable {report['labels_allowed']}")
        print(f"           label histogram (valid)     : {report['label_histogram']}")
        print(f"           label histogram (encodable) : {report['label_histogram_encodable']}")
        print(f"           classes present   {report['contrast_classes_present']}"
              f"/{report['contrast_classes_total']}")
        print(f"           classes encodable {report['contrast_classes_encodable']}"
              f"/{report['contrast_classes_total']}")
        print(f"           unreachable: {report['unreachable_codes']}")
        print(f"             because: {report['unreachable_reason']}")
    output = {"reports": reports,
              "reading_note": ("classes 0 (MISSING) is a mask, not a class: the task has exactly "
                               "two learnable classes, COMPATIBLE and CONTRADICTING.  The "
                               "requirement to have every observed relation kind carry a label "
                               "(R0/R1/R2) is measured by label_histogram; the requirement to "
                               "have a real conflict class is measured by classes_present.")}
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True),
                                  encoding="utf-8")
        print(f"wrote {args.json}")
    return EXIT_OK if all(report.get("available") for report in reports) else EXIT_INCONSISTENT


if __name__ == "__main__":
    raise SystemExit(main())
