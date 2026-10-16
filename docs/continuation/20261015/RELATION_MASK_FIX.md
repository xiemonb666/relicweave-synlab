# Relation AUC mask repair (2026-10-15)

Status: `IMPLEMENTED / TARGETED_TESTS_PASS`. This is the bounded MC07 data-quality repair for
`discrimination_auc`; it does not change training heads, package/global versioning, or historical
metrics.

## Contract and implementation

`docs/a12/contract_alignment_20261009.md` MC07 requires relation masking and says `valid` cannot
stand in for `loss_mask`; `UNKNOWN` must not be treated as a negative. The current implementation
is `synlab/relations/negatives.py::discrimination_auc` (`metric_version:
relations.discrimination_auc.v2`). It scores only rows with kind in `R0/R1/R2`, `valid=True`, and
resolved `loss_mask=True`. `TINY_CONTACT`, `UNKNOWN`, missing kinds, invalid rows, and explicitly
masked rows never reach positive/negative classification.

For legacy legal R0/R1/R2 mapping rows that omit `loss_mask`, the metric resolves the mask to
`True`, matching the structured `RelationEdge.loss_mask` default. Missing `valid` resolves false;
missing `kind` resolves to `UNKNOWN`. `positive_kinds` still divides the retained legal classes
into positive and negative labels.

The result's `denominator` reports input rows, first-filter exclusion counts, legal relation rows,
eligible but unscorable self/missing-feature pairs, and the final scorable/positive/negative pair
counts. `pairs` and that final scorable count are the AUC denominator. An empty scorable set is
`NOT_RUN` with all metric values null and a reason naming the zero denominator. A one-class set is
`NOT_ESTABLISHED`; AUC, its interval, and median-threshold accuracy are null. Two-class sets retain
the mother-clustered bootstrap behavior. The global `NEGATIVES_VERSION` remains
`relations.negatives.v1`; the local metric version identifies only this AUC contract change.

## Hand-calculated fixture

`tests/a12/relations/test_discrimination_auc_mask_20261015.py` uses exact cosine scores. Its nine
input rows include two R2 positives (scores 0.9 and 0.8; one omits the legacy-defaulted mask), two
legal negatives (R0 at 0.6 and R1 at 0.2; one omits the mask), a high-scoring R0 with
`loss_mask=False`, a `valid=True`/`loss_mask=False` TINY_CONTACT, a masked-in UNKNOWN, an invalid
R0, and a row with no kind. The retained denominator is four pairs: two positives and two
negatives. Both positives outrank both negatives, so the hand AUC is 4/4 = 1.0. The high-scoring
masked R0 would reduce AUC to 4/6 if wrongly counted, making the mask assertion observable.

The same test file checks that a single positive with its only negative masked reports
`NOT_ESTABLISHED` and null metrics, and that a set containing only invalid/UNKNOWN rows reports
`NOT_RUN` with `scorable_pairs=0`.

## Verification

Executed from `relicweave-synlab` with the repository environment:

```text
.venv/Scripts/python.exe -m pytest tests/a12/relations/test_discrimination_auc_mask_20261015.py tests/a12/relations/test_multi_event_negatives.py -q -rA
19 passed, exit code 0
```

This verifies the new hand-built cases plus the existing A12 relation-negative tests. It does not
rerun historical metric jobs or change their recorded status.
