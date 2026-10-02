"""S8 contract: which contradiction classes can exist at all, measured on real packages.

The requirement was "construct a set in which every class occurs using real data, **or** state the
unlock condition explicitly -- never fabricate a label".  This test pins the measurement that makes
the second option the honest one:

* ``_contradiction_label`` (``synlab/training/batch.py``) can emit ``MISSING`` (a **mask**,
  ``valid=False``), ``COMPATIBLE`` and ``CONTRADICTING``;
* ``CONTRADICTING`` requires ``row["contradiction"]`` to be true, and **nothing in ``synlab/**``
  writes that key**: the loader's ``_batch_rows`` builds exactly
  ``query/positives/negatives/excluded/sample_key`` and ``research/relations.parquet`` has no
  contradiction column;
* therefore every valid label is ``COMPATIBLE`` on the real packages -- which the datasets
  already report as ``classes_present = 1``.

The test asserts the *arithmetic* of the mapping as well, so if a producer is added later the
second class becomes reachable without touching this file.
"""

from __future__ import annotations

import numpy as np
import pytest

from _fixtures import build_fixture_pool
from synlab.training.adapter import (
    CONTRADICTION_COMPATIBLE,
    CONTRADICTION_CONTRADICTING,
    CONTRADICTION_MISSING,
)
from synlab.training.batch import _contradiction_label

#: the relation codes ``_contradiction_label`` branches on
RELATION_R1_CODE = 1
RELATION_R2_CODE = 2
RELATION_R0_CODE = 0


def test_missing_is_a_mask_not_a_class() -> None:
    """A label that is not valid, or has no evidence, is masked -- never a class."""
    assert _contradiction_label(RELATION_R0_CODE, label_valid=False,
                                has_contradiction=True, has_evidence=True) == (
        CONTRADICTION_MISSING, False)
    assert _contradiction_label(RELATION_R0_CODE, label_valid=True,
                                has_contradiction=True, has_evidence=False) == (
        CONTRADICTION_MISSING, False)


def test_r1_and_r2_are_always_compatible() -> None:
    """A mate relation is compatible by definition, whatever the flag says."""
    for relation in (RELATION_R1_CODE, RELATION_R2_CODE):
        for flag in (False, True):
            code, valid = _contradiction_label(relation, label_valid=True,
                                               has_contradiction=flag, has_evidence=True)
            assert (code, valid) == (CONTRADICTION_COMPATIBLE, True)


def test_contradicting_needs_the_flag_and_a_non_mate_relation() -> None:
    """The second class is reachable *only* through ``has_contradiction``."""
    code, valid = _contradiction_label(RELATION_R0_CODE, label_valid=True,
                                       has_contradiction=False, has_evidence=True)
    assert (code, valid) == (CONTRADICTION_COMPATIBLE, True)
    code, valid = _contradiction_label(RELATION_R0_CODE, label_valid=True,
                                       has_contradiction=True, has_evidence=True)
    assert (code, valid) == (CONTRADICTION_CONTRADICTING, True)


def test_no_package_side_producer_writes_the_contradiction_flag() -> None:
    """The measured blocker: the key the mapping reads has no writer in ``synlab/**``.

    This is a *source* assertion, and it is the reason the S8 item is reported as
    "structurally unreachable" instead of "not encodable": a producer is missing, not a pair.
    If a producer is ever added, this test fails on purpose and points at the re-measurement.
    """
    import inspect

    from synlab.qc import loader_probe

    source = inspect.getsource(loader_probe._batch_rows)
    assert "contradiction" not in source, (
        "loader_probe._batch_rows now writes a contradiction flag: the second class may be "
        "reachable -- re-measure tools/a12_contradiction_reachability.py and update the S8 "
        "section of docs/a12/smallfixes_report.md")
    # the hook a producer would use exists and is documented, so the fix is additive
    from synlab.training import batch as batch_module

    assert "contradiction_source" in inspect.signature(
        batch_module.build_training_batch).parameters


def test_fixture_pool_rows_carry_no_contradiction_key() -> None:
    """Even the richest fixture row shape has no contradiction verdict to read."""
    pool = build_fixture_pool(lineages={"l0": ["a", "b"]},
                              r2={"a": ["b"]}, with_features=False)
    rows = pool.sample_training_batch(np.random.default_rng(0), queries=1)
    for row in rows["rows"]:
        assert "contradiction" not in row
