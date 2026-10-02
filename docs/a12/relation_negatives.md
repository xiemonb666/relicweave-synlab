# Relation negatives: the mate-absent rule (`rank` becomes trainable)

Scope of this document: **how an ordinary relation negative is constructed**, why the constructed
set was not legal, what was changed (and what was deliberately *not* changed), the measured counts
of the new package, the independent re-check of sampled negatives, the minimal trainable set, and
what is still open.

Artifacts referenced here (all produced by the drivers below, every number re-derivable):

| artifact | what it is |
| --- | --- |
| `synlab/relations/mate_absent.py` | the rule (single source of truth), its classes and its reports |
| `synlab/relations/sampler.py` | live exclusion vocabulary: `negative_exclusion_reason` now returns `candidate_mate_present` |
| `tools/relation_negatives_fix.py` | driver: `plan` / `export` / `diff` / `classes` / `sample` |
| `tools/neg_diag.py` | read-only probe: is a legal negative also what the frozen pool calls a "neighbour"? |
| `tools/negfix_train_smoke.py` | training smoke on a fragment subset (real losses, small batch) |
| `data/a12_exports/negfix/next_experiment/training_package` | the re-exported package (same release scope, ruled negatives) |
| `data/a12_neg/*.json` | the measured reports (`plan`, `export`, `diff`, `classes`, `negative_sample_audit`) |
| `data/a12_reports/negfix_smoke_subset.json` | the real training step records |

---

## 1. Two independent defects, do not conflate them

**(A) The negative set contained candidates that carry their own true neighbour.**
`research/relations.parquet` of `data/a12_exports/trainable/next_experiment/training_package` had
1560 rows with `eligible_as_negative = (kind in {R1,R0}) and valid and loss_mask`. 1120 of them
named a candidate that has **its own confirmed `R2` mate inside the same pool**. Example measured
by `tools/neg_diag.py`: the pair `LIN0100_V17_M02_PAT08_E01-m → LIN0101_V16_M12_PAT12_E01-m` is a
genuine cross-lineage `R0` row, but the candidate's own mate
`LIN0101_V16_M12_PAT12_E01-p` sits in the same gallery. Supervising "these two are not the same
body" on such a candidate teaches the shortcut *"a fragment that has a matching partner somewhere
in the gallery is a positive"* — a gallery-level (transductive) cue that has nothing to do with the
observed surface. This is defect (A), and it is what the rule in §2 fixes.

**(B) The reader called the confirmed R1/R0 set "neighbours".**
`synlab.qc.loader_probe.ExportedRelationPool.neighbours()` returned the confirmed **R1/R0** set,
while `synlab.training.batch` reads `neighbours(q)` as the **historical-R2 mate set** when it
guards against R2 contamination. Measured: `every_legal_negative_is_a_pool_neighbour = true` for
**55/55** queries of the base package (`data/a12_neg/diag_base.json`), i.e. *no* legal negative
could ever pass `assert_legal_negative` through the frozen `pool=` route — the reported
`LEAKAGE_DETECTED ... historical R2 LIN0101_V16_M12_PAT12_E01-m used as an ordinary negative of
LIN0100_V17_M02_PAT08_E01-m` was a false positive of the reader, not a true mate conflict (the
same probe measures `candidate_is_true_r2_mate_of_query = false` for that very pair).

Defect (B) was fixed outside this task's write scope, in commit `5959a42` ("align the exported
relation pool with the mate-set contract"): `neighbours()` now returns `mates()` and the R1/R0 set
is exposed separately as `legal_negatives()`. Defect (A) is what this task fixes, and the two are
verified separately below — with (B) fixed, the *base* package also loads, so a green loader alone
does not prove the rule works; the counts and the sample audit do.

---

## 2. The rule

> A candidate may be an **ordinary negative** of a query only when it has **no confirmed `R2`
> mate in the pool** (`mate_absent(candidate)`). A candidate that has one is a **separate class**:
> the row keeps its measured `kind`/`valid`/`area_mm2`, its `loss_mask` is cleared and its
> `reason` records why. It never enters the ordinary negative set.

Basis: the pool semantics the project already uses for retrieval queries. A fragment whose mate is
absent from the gallery cannot be a retrieval target (`Hit` / `CovRecall` are `N/A` for it and it
stays in the risk denominator — `synlab/diagnostics/metrics.py`, `configs/a12/negative_pool.yaml`
scope `MATE_REMOVED`); its role in the pool is distractor/negative. The same reading applied to the
*candidate* side of a negative pair is exactly the rule above. Two consequences follow, and both
are intended: mate-present fragments are query/positive material, mate-absent fragments are the
negative population.

### Classes (exactly one per row)

| class | predicate | effect |
| --- | --- | --- |
| `POSITIVE_R2` | `kind == R2 and valid` | untouched |
| `ORDINARY_NEGATIVE_MATE_ABSENT` | `kind in {R1,R0} and valid and loss_mask and mate_absent(candidate)` | legal ordinary negative |
| `CANDIDATE_MATE_PRESENT_NOT_ORDINARY` | `kind in {R1,R0} and valid and loss_mask` but the candidate has its own `R2` mate | **not** an ordinary negative: `loss_mask=False`, `reason += " \| ordinary_negative_forbidden:mate_present_candidate"`, `eligible_as_negative` recomputed |
| `EXCLUDED` | everything else (invalid, already unmasked, `TINY_CONTACT`, `UNKNOWN`, ...) | untouched |

`kind`, `valid`, `area_mm2` and the fragment identities are **never** rewritten: only the
supervision eligibility of a row and its recorded `reason` change. The frozen derivation
`eligible_as_negative := (kind ∈ {R1,R0}) ∧ loss_mask` still holds — the rule changes an *input*
of that derivation, not the derivation.

### Is the separate class allowed by the guard?

Measured and pinned in `tests/a12/relations/test_mate_absent_negatives.py`:
`training.batch.assert_legal_negative("R0", query_id="a00", candidate_id="b00", is_history_r2=False,
confirmed=True)` **does not raise** — the guard only refuses the query itself, the query's *own*
historical `R2`, `UNKNOWN`/`TINY_CONTACT` and unconfirmed labels. So the mate-present class is not a
guard violation; it is refused by the plan's mate-absent rule, which is stricter. That is precisely
why the ruling has to happen in the negative **construction** (this document) and why the guard was
left exactly as it was.

### What the guard still refuses (unchanged)

Same test file: `is_history_r2=True` raises `LEAKAGE_DETECTED` for `R2` and for `R0`;
`UNKNOWN` raises; an unconfirmed candidate raises. Nothing in this task relaxes
`assert_legal_negative`, `loss_mask`, `eligible_as_negative` or the exclusion semantics of
`training.batch`; no label, mate or class value is invented.

---

## 3. Where the rule is applied

1. **Live pool / sampler** — `synlab/relations/sampler.py::negative_exclusion_reason` returns
   `candidate_mate_present` (constant `MATE_PRESENT_EXCLUSION_REASON`) for a candidate whose own
   `neighbours()` set is non-empty, so `sample_training_batch`, `mine_hard_negatives` and
   `assert_legal_negative(pool, ...)` all obey it. In the miner a mate-present candidate keeps its
   real hard group (`same_instrument_not_adjacent` / `same_type_different_object` /
   `pattern_like_geometry_off` / ...) instead of being folded into `no_neighbour_in_gallery`; the
   reason is reported per candidate beside it.
2. **Exported relation table** — `tools/relation_negatives_fix.py --step export` re-runs the *real*
   exporter (`synlab.storage.export.export_training_package`) over the same unfrozen release scope
   (`rel_nexp_1790919836`, the 328 assets recorded by the previous run) and lets the rows pass
   through `mate_absent.apply_rule()` at the single point where the writer serialises
   `research/relations.parquet`. Every other byte of the package (observations, geometry, tokens,
   zarr, the other label layers, the manifest) is written by the frozen writer unchanged; the
   driver aborts if the hook fires a number of times other than exactly one. The store
   (`data/a12_trainable/store`, which owns the scope — *not* `data/a12`) is only read.

Reproducing:

```powershell
& .venv\Scripts\python.exe tools\relation_negatives_fix.py --step plan      # -> data/a12_neg/plan.json
& .venv\Scripts\python.exe tools\relation_negatives_fix.py --step export    # -> the package (55 s)
& .venv\Scripts\python.exe tools\relation_negatives_fix.py --step diff      # -> data/a12_neg/diff.json
& .venv\Scripts\python.exe tools\relation_negatives_fix.py --step classes   # -> data/a12_neg/classes.json
& .venv\Scripts\python.exe tools\relation_negatives_fix.py --step sample    # -> data/a12_neg/negative_sample_audit.json
```

---

## 4. Measured counts

### 4.1 Relation table (both packages, same release scope, same 1721 pairs)

| | base package | ruled package (`negfix`) |
| --- | --- | --- |
| rows / kinds | 1721 = {R2 28, R1 24, R0 1560, TINY_CONTACT 3, UNKNOWN 106} | identical |
| `eligible_as_negative` rows (= `kind in {R1,R0} ∧ valid ∧ loss_mask`) | **1560** | **440** |
| `POSITIVE_R2` | 28 | 28 |
| `ORDINARY_NEGATIVE_MATE_ABSENT` | 440 | 440 |
| `CANDIDATE_MATE_PRESENT_NOT_ORDINARY` | 1120 | 1120 (same rows, now `loss_mask=False` + reason marker) |
| `EXCLUDED` | 133 | 133 |
| `ordinary_negatives_with_a_mate_of_their_own` | **1120** | **0** |

The class of a pair is a property of the pair, not of when it was read: the ruling is recognised
both before it is applied (`kind in {R1,R0} ∧ valid ∧ loss_mask` and the candidate has a mate) and
after (`loss_mask` cleared, `reason` carries the marker), which is why the two columns classify
identically (`--step classes` on the ruled package; `apply_rule(...)["rows_reruled"] = 1120`).

`--step diff` proves the two packages differ **only** in that table and only in
`loss_mask` / `eligible_as_negative` / `reason` of those 1120 pairs: `pairs_only_in_base = []`,
`pairs_only_in_new = []`, `changed_fields = [eligible_as_negative, loss_mask, reason]`,
`changed_pairs = 1120`, `pairs_identical = 601`.

Classes by kind (ruled package): `R2 → POSITIVE_R2 28`; `R0 → ORDINARY 440 + MATE_PRESENT 1120`;
`R1 24 → EXCLUDED` (all four `R1` rows of this scope are `valid=False` — "no direct fracture
surface"), `UNKNOWN 106 → EXCLUDED`, `TINY_CONTACT 3 → EXCLUDED`.

### 4.2 Fragments and negative supply

* 77 fragments in the roster (`deploy/queries.parquet`), 71 of them named by a relation row (the
  six unnamed ones are `LIN0101_V16_M12_PAT12_E03-*` (4) and `LIN0102_V11_M06_PAT16_E03-*` (2));
* 56 have a confirmed `R2` mate (28 edges), **15 are mate-absent** — the whole ordinary-negative
  supply of this scope: `LIN0104_V11_M04_PAT07_E03-{m,p}`,
  `LIN0108_V04_M10_PAT10_E03-{m,p}` + `LIN0108_V04_M10_PAT10_E03-m__-1c1`, the
  `LIN0109_V09_M11_PAT09_E03_a2-*` pieces (4) and the four extra children
  `LIN0101_V16_M12_PAT12_E0{1,2}-p__+1c{1,2}` / `LIN0109_V09_M11_PAT09_E0{1,2}-p__+1c1`;
* 45 of the 55 queries that had negatives before the rule keep at least one: 15 rows each for the
  four `LIN0100` pieces, 11 for `LIN0101/0102/0103`, 9 for `LIN0104/0105/0106/0107`, 6 for
  `LIN0108` (`data/a12_neg/classes.json`);
* 59 of 77 fragments carry a delivered observation; the mate-absent fragments used below are all
  observed.

**The negative supply of this scope is small (15 fragments).** That is a data property, not a rule
defect: an event only produces mate-absent pieces when no shared fracture surface is measured
(the `E03`-style events and the extra children), and a scope without such pieces has **no** legal
ordinary negative at all. A corpus that wants a large legal-negative gallery needs more of those
pieces (or a `MATE_REMOVED` gallery variant), and the rule's report names that condition instead
of padding the set.

---

## 5. Minimal trainable set (query + encodable R2 positive + ≥ 2 legal negatives, all observed)

`mate_absent.minimal_trainable_set` on the ruled package (encodability read from the packaged
token and geometry shards: `token_valid.any() and tokens_total>0` or
`((point_valid|normal_valid) & scale_valid).any()`; the global-RGB gate is *not* read there, so a
fragment encodable only through RGB would be under-reported — never over-reported):

| role | fragment | note |
| --- | --- | --- |
| query | `LIN0101_V16_M12_PAT12_E01-m` | mate-present (has a positive), observed |
| positive | `LIN0101_V16_M12_PAT12_E01-p` | confirmed `R2`, observed, encodable |
| negative 1 | `LIN0104_V11_M04_PAT07_E03-m` | `R0`, mate-absent, observed |
| negative 2 | `LIN0104_V11_M04_PAT07_E03-p` | `R0`, mate-absent, observed |
| further legal negatives | `LIN0108_V04_M10_PAT10_E03-m`, `LIN0108_V04_M10_PAT10_E03-m__-1c1`, `LIN0108_V04_M10_PAT10_E03-p` | `R0`, mate-absent, observed |

`all_three_observed = true`; **14 queries** are trainable under the rule (each with ≥1 encodable
positive and ≥2 legal negatives). The champion set is a *measurement*, not a choice: the query was
picked as the first trainable query in sorted order.

---

## 6. Verification (real numbers, real exit codes)

### 6.1 The loader

```powershell
& .venv\Scripts\python.exe tools\load_package.py --package data/a12_exports/negfix/next_experiment/training_package
# exit 0   (data/a12_neg/_loader_negfix.txt)
```

```
relations    : {"R0": 1560, "UNKNOWN": 106, "R2": 28, "R1": 24, "TINY_CONTACT": 3}  eligible_as_negative=440
per-task supervision (real batch, trainer's own masks):
  view                 590        589  supervised
  rank                 468        156  supervised
  correspondence      3299          0  surface_sample_to_token_mapping_is_not_derivable_from_the_package
  quality                5          5  supervised
  contradiction        468        156  supervised
  fragments=77 observed=59 positives=28 negatives=440 effective_queries=18
```

* `negatives = 440 > 0` ✅ (all 440 are `ORDINARY_NEGATIVE_MATE_ABSENT`)
* `effective_queries = 18 ≥ 1` ✅
* `rank` `n_valid = 468`, **`n_allowed = 156 > 0`** ✅
* `data/a12_neg/_loader_negfix.txt`, exit code recorded in the same file; the package's own card is
  regenerated with `--write-card` (exit 0) and
  `& .venv\Scripts\python.exe tools\load_package.py --package data/a12_exports/negfix/next_experiment/training_package --check`
  returns `{"ok": true, "problems": []}` / exit 0 (files, hashes, column dictionary and splits all
  verify against the package's own manifest).

For honest attribution, the **same** command on the **base** package (now that the reader contract
is fixed) is also exit 0, with `negatives=1560`, `effective_queries=20`, `rank n_allowed=748`
(`data/a12_neg/_loader_base_after_readerfix.txt`). The loader's exit code therefore measures the
reader fix, and the negative set it *legally* consumes is what measures this rule: 1560 → 440, of
which none has a mate of its own.

### 6.2 Sample audit — 24 ordinary negatives re-derived from the raw store rows

```powershell
& .venv\Scripts\python.exe tools\relation_negatives_fix.py --step sample --sample 24 --seed 20261002
# exit 0 -> data/a12_neg/negative_sample_audit.json
```

Method: the check never reads the exported table it is verifying. It rebuilds the release's raw
relation rows from the store's own assets — the `relation_pool` index arrays
(`storage.export._pool_relations`) plus the `clean_truth` and `label_bundle` relation payloads
(`storage.export._truth_relations`), 3488 raw rows over 1721 pairs — and for every sampled
`(query, candidate)` asserts:

1. the pair exists in the raw rows, and no raw row measures it as `R2`;
2. at least one raw row measures it as `R0`/`R1` (the kind the package labels it with);
3. the **candidate has no `R2` mate anywhere in the raw rows** (the mate-absent rule);
4. the candidate is not the query's own historical `R2`, and `candidate != query`.

Result: `population = 440`, `sampled = 24`, `mismatches = 0`, `raw_fragments_with_mate = 56`.
All 24 sampled rows are `R0` (this scope's `R1` rows are all `valid=False`), every sampled candidate
has an empty raw mate set, and 19 of the 24 queries have a raw mate of their own (the other five are
mate-absent queries: legal negatives, simply without a positive anchor). Examples:

```
LIN0100_V17_M02_PAT08_E02-p → LIN0101_V16_M12_PAT12_E02-p__+1c2   R0   candidate mates: []   ok
LIN0100_V17_M02_PAT08_E02-p → LIN0109_V09_M11_PAT09_E03_a2-p      R0   candidate mates: []   ok
LIN0101_V16_M12_PAT12_E01-p → LIN0109_V09_M11_PAT09_E02-p__+1c1   R0   candidate mates: []   ok
```

The complementary probe `tools/neg_diag.py --package <ruled package>` reports
`every_legal_negative_is_a_pool_neighbour = false` (was `true` for 55/55 queries on the base
package) and `first_refusal = null`; with the mate-set contract in place `neighbours(q)` is now the
query's mate set (size 1 for a two-piece event).

### 6.3 Training smoke — the `rank` loss really runs

The prescribed full-package smoke builds the batch (real negatives, `440`) and then dies in the
backward pass on RAM:

```powershell
& .venv\Scripts\python.exe -m synlab.training.smoke --package data/a12_exports/negfix/next_experiment/training_package --steps 2 --out data/a12_reports/negfix_smoke --no-loader-probe
# exit 1  (data/a12_neg/_smoke_negfix.txt)
# RuntimeError: [enforce fail at alloc_cpu.cpp:117] DefaultCPUAllocator: not enough memory:
#               you tried to allocate 21441282048 bytes
```

That is a *resource* limit of stacking 59 observed fragments (896 MB of delivered RGB as uint8,
~3.6 GB as float32) and not a supervision problem. The same trainer, the same losses and the same
`TrainingPoolView` were therefore run on the minimal trainable set of §5:

```powershell
& .venv\Scripts\python.exe tools\negfix_train_smoke.py --package data/a12_exports/negfix/next_experiment/training_package --steps 3
# exit 0 -> data/a12_reports/negfix_smoke_subset.json   status = RANK_TASK_TRAINED_ON_REAL_NEGATIVES
```

```
batch: Q=5 C=5 positives=1 negatives=12 excluded=2 effective_queries=1
rank supervision: n_valid=13 n_allowed=13 (positives 1, negatives 12)  effective_queries=1
step 1  loss=6.658840179443359   grad_norm=393.1551818847656
        rank           skipped=0  loss=6.328300476074219    n_valid=1  n_allowed=1   weight=1.0
        view           skipped=0  loss=3.27839732170105     n_valid=37 n_allowed=37  weight=0.1
        contradiction  skipped=0  loss=0.026997337117791176 n_valid=13 n_allowed=13  weight=0.1
        correspondence skipped=1  reason=correspondence_labels_never_reached_token_space
        quality        skipped=1  reason=no_valid_quality_target
step 2  loss=6.503690242767334   rank loss=6.17352294921875    grad_norm=385.267578125
step 3  loss=6.3895487785339355  rank loss=6.059661865234375   grad_norm=379.44403076171875
```

`rank` is **not skipped**: it reports a real loss that decreases over the three real optimizer
steps, over the real pair (one positive against twelve legal negatives, 13 allowed pairs, all six
fragments observed and encodable). Two `n_allowed` readings appear and both are real: the loss-side
record counts anchors (`1` query with an allowed pair), the supervision block counts pairs
(`13`). The tasks that are still skipped are skipped with their measured reason, never with `0.0`.

### 6.4 Tests

```powershell
& .venv\Scripts\python.exe -m pytest tests\a12\relations -q            # 63 passed
& .venv\Scripts\python.exe -m pytest tests\a12\diagnostics tests\a12\episodes -q   # passed
& .venv\Scripts\python.exe -m pytest tests\a12\training tests\a12\qc tests\a12\storage -q   # 228 passed
```

New: `tests/a12/relations/test_mate_absent_negatives.py` (rule units, idempotence, "the input is
never mutated", the live-pool vocabulary, the exported-table/live-pool agreement, and the two
integration proofs — `build_training_batch` accepts the ruled rows with the guard active and
`neg_audit.negatives > 0`, while the guard still refuses a mate-present candidate *of its own
mate*). Adapted: `tests/a12/relations/test_sampler.py` + `pool_fixtures.py` now model both
populations of a corpus (R2 chains = queries/positives, mate-absent pieces = the negative
population), because a pool in which *every* fragment has a mate has no legal ordinary negative by
construction.

Two integration failures remain in `tests/a12/integration/test_closed_loop.py`
(`test_separation_block_is_measured_on_the_written_package`: `bag_id` among the deployment keys;
`test_deployment_view_carries_no_truth`: `views.deploy.contains_truth is True`). They are
unrelated to this rule — they read the package's separation block and deployment view, which
nothing in `synlab/relations/**` touches — and they belong to the in-flight context-pack /
deployment-view work stream.

---

## 7. Still open (measured, not hand-waved)

1. **The exported table is one row per *unordered* pair** (`pairs_identical = 601`,
   `distinct unordered pairs = 1721 = rows`), and the row's `query`/`candidate` columns are just
   the order the source stored. Only the direction that happens to be written can supervise a
   negative, so roughly half of the potential `(query, candidate)` negative supervision is lost
   before the rule even applies. In this scope 6 of the 77 roster fragments (the
   `LIN0101_V16_M12_PAT12_E03-*` and `LIN0102_V11_M06_PAT16_E03-*` pieces) appear in no relation
   row at all. A lasting fix belongs to the exporter (write the pair once for the positive role and
   once per negative direction, or keep an explicit role column), which is outside this task's
   write scope.
2. **The mate-present population is currently unused.** 1120 rows (their mates are in the pool) are
   classified and documented but enter no loss. Whether they are usable as a *hard*-negative class
   (they are accepted by `assert_legal_negative`, see §2) is a plan decision, not something this
   task may introduce silently; the rows keep their measured kind and a machine-readable `reason`
   marker so such a class can be added without re-measuring anything.
3. **The full-package CPU smoke does not fit in RAM** (§6.3): a 21.4 GB allocation in the backward
   pass. The supervision is there (the batch builds with 440 negatives); the run needs a GPU or a
   fragment-subset/streaming batch, which `synlab/training/**` would have to provide.
4. **The ruling of the exported table is applied by a writer-level hook**
   (`tools/relation_negatives_fix.py`, `_write_parquet` for `research/relations.parquet` only),
   because the store assets of `data/a12_trainable/store` are frozen and `synlab/storage/**` is
   outside this task's write scope. The hook is explicit, single-shot (the driver aborts otherwise)
   and verified by `--step diff`; the lasting fix is to apply `mate_absent.apply_rule` inside the
   exporter (or to construct only mate-absent negative rows in the pool builder).
5. **Negative supply.** 15 mate-absent fragments → 440 ordinary-negative rows → 45 queries with at
   least one. `rank` is trainable, but a corpus with many mate-present pieces and few `E03`-style
   pieces will starve; the rule reports that condition (`minimal_trainable_set.reason`) instead of
   padding the set with illegal candidates.
6. **`correspondence` and `quality` remain blocked** in this package for their own reasons
   (`surface_sample_to_token_mapping_is_not_derivable_from_the_package`, and 5 valid quality
   targets only). They are untouched by this task.

---

## 8. Evidence index

| file | content |
| --- | --- |
| `data/a12_neg/diag_base.json` | defect (B) and defect (A) on the base package (55/55 flagged, `candidate_is_true_r2_mate_of_query = false`) |
| `data/a12_neg/diag_negfix.json` | the same probe on the ruled package (`every_legal_negative_is_a_pool_neighbour = false`, `first_refusal = null`) |
| `data/a12_neg/plan.json` | the rule's classes, per-query counts, minimal trainable set, encodability |
| `data/a12_neg/export.json`, `export_rule_detail.json` | the re-export: scope, manifest hash, rows re-ruled, per-row before/after detail |
| `data/a12_neg/diff.json` | base vs ruled package, field by field |
| `data/a12_neg/classes.json` | class table + per-query ordinary negatives of the ruled package |
| `data/a12_neg/negative_sample_audit.json` | the 24 sampled negatives and their raw-store evidence |
| `data/a12_neg/_loader_negfix.txt`, `_loader_base_after_readerfix.txt` | loader runs + exit codes |
| `data/a12_neg/_smoke_negfix.txt` | the full-package smoke's RAM failure (exit 1) |
| `data/a12_reports/negfix_smoke_subset.json` | the real step records (per-task loss / `n_allowed`) |
| `data/a12_neg/_pytest_*.txt` | the test runs quoted in §6.4 |
