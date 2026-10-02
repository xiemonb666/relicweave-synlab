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

---

# 9. 关系池协议一致性测试（四份并行实现，一套契约）· N9 QA 收紧 · N10 辅助表

本节是本文件的续篇，处理 `engineering_policy.md` §3 第 5 行登记的结构性债务（"关系池协议：四份并行
实现语义分歧"），以及第二轮新增的 N9/N10。三条都按 R1–R5 执行：**R2 让性质构造性成立**、**R3
before/after 实测**、**R4 不劣化基线**、**R5 不放宽判据**。

## 9.1 协议契约测试（`relations.pool_protocol.v1`）

**为什么不是"再修一处"**：§1 缺陷 (B) 的形态是——四份并行实现里**任何一份**单独看都"成功"，但
`neighbours()` 的含义在读者之间漂移，于是 `neighbors(q)` 被当成配偶集，55/55 query 的合法负例全部
被 `assert_legal_negative` 拒绝，`rank` 从未启动。靠约定维持一致已经失败过一次，所以按 R2 把它钉成
**单一契约 + 单一断言集**：一份行集进去，四份实现都从它实例化，跑**同一套断言**。

* 契约模块：`synlab/qc/pool_contract.py`（`POOL_PROTOCOL_VERSION = relations.pool_protocol.v1`），
  **13 条断言**（`ASSERTIONS`）：`interface_present`、`relation_value_domain`、`relation_symmetry`、
  `mates_match_measured_r2`、`neighbours_are_mates`、`legal_set_only_confirmed_negatives`、
  `legal_set_excludes_self`、`legal_set_excludes_mates`、`legal_pool_equals_legal_negatives`、
  `history_exclusions_superset_of_mates`、`history_exclusions_disjoint_from_legal`、
  `assert_legal_negative_accepts_the_legal_set`、`assert_legal_negative_refuses_illegal`。
* 期望值来自**行集本身**（`reference_mates` / `reference_rows`），不来自任何被检实现——共享的误读
  不会让套件变绿。
* 被测对象（5 个实例覆盖 4 份实现）：`qc.loader_probe.ExportedRelationPool`、
  `training.smoke.TrainingPoolView`、`training.sampler.PoolIndex[exported]`、
  `training.sampler.PoolIndex[gallery]`、`relations.gallery.RelationPool`。
* 为让契约成立而**只增**的接口（不改既有语义）：`RelationPool.mates/legal_pool/legal_negatives/
  history_exclusions/assert_legal_negative`、`PoolIndex.mates/legal_negatives/candidate_ids`、
  `ExportedRelationPool.lineup`（`PoolIndex.lineage` 读的就是它；此前该 reader 作 `PoolIndex` 载体时
  候选集为空）。

**驱动与退出码**（`tools/a12_pool_contract.py`）：

```
.venv\Scripts\python.exe tools\a12_pool_contract.py --step canonical --out data\a12_reports\pool_contract_canonical.json
# 退出码 0
.venv\Scripts\python.exe tools\a12_pool_contract.py --step real --out data\a12_reports\pool_contract_real.json
# 退出码 0
```

| | canonical（构造夹具，15 片 / 105 行） | real（`negfix` 包，71 片 / 1721 行 + 真 store 索引） |
|---|---|---|
| `ExportedRelationPool` | 13/13 | 13/13 |
| `TrainingPoolView` | 13/13 | 13/13 |
| `PoolIndex[exported]` | 13/13 | 13/13 |
| `PoolIndex[gallery]` | 13/13 | 13/13 |
| `RelationPool`（真 sparse index + 真 `FragmentRecord`） | 13/13 | 13/13 |
| 跨实现一致（`mates`/`neighbours`/`legal_pool`/measured kind） | 0 分歧 | 0 冲突（见下） |
| 失败注入 | **6/6 被抓住** | **6/6 被抓住** |

**失败注入（可复现的"套件能失败"证明）**：`FAILURE_INJECTIONS` 每个包装器只破坏一条子句，且必须被
**指名**断言抓住——`neighbours_return_the_negative_set`（缺陷 (B) 原文）→ `neighbours_are_mates`；
`history_exclusions_drop_the_mates` → `history_exclusions_superset_of_mates`；
`legal_set_offers_a_mate` → `legal_set_excludes_mates`；`legal_set_offers_unknown` →
`legal_set_only_confirmed_negatives`；`relation_is_asymmetric` → `relation_symmetry`；
`guard_accepts_a_mate` → `assert_legal_negative_refuses_illegal`。
`tests/a12/training/test_pool_protocol_consumption.py` 还把缺陷 (B) 注入到**真实 batch 构建**上：守卫
抛 `LEAKAGE_DETECTED ... historical R2 <candidate> used as an ordinary negative`——即当年 `rank` 停摆的
那条消息。

### 9.1.1 实测到的一处**真实分歧**（报告，不擅自改语义）

`--step real` 的一致块分解为：**保守缺口 861 条**（导出表没有命名的对：导出读者 `UNKNOWN`、画廊隐式
`R0`——两个 reader 的既有设计差异，`docs` 已记录）、**0 条 kind/配偶冲突**、以及一处
**资格（eligibility）分歧**：

| | 值 |
|---|---|
| 受影响行 | **24 条 `R1` 行 / 48 个有向 (query,candidate)** |
| 行的事实 | `valid=False`、`loss_mask=False`、`eligible_as_negative=False`、`reason="no_direct_fracture_surface (same event, mutually exclusive)"` |
| 作为普通负例**提供**的读者 | `relations.gallery.RelationPool`（48）、`PoolIndex[exported]`（48）、`PoolIndex[gallery]`（48） |
| **拒绝**的读者 | `qc.loader_probe.ExportedRelationPool`、`training.smoke.TrainingPoolView` |
| 冻结判据 | `eligible_as_negative == (kind in {R0,R1} and valid and loss_mask)`（决策 D10 / `storage.export`） |

机制（读代码 + 实测）：`PoolIndex.confirmed()` 用 `relation() in {R0,R1,R2}` **自行重算**确认，而不
问载体的 `confirmed()`；`RelationsIndex.confirmed()` 对显式边不看 `valid` 标志。**未改**：改这两处会
改变实时采样器抽到哪些候选（即训练数据），属数据资格裁决（与 N9 同形），不在本任务的写入范围内；
一行修法已记录在 `pool_contract.eligibility_finding()["one_line_fix"]`，并由
`tests/a12/relations/test_pool_protocol_real_package.py::test_the_eligibility_divergence_is_pinned`
把当前读数钉死——修好那天测试会失败并要求更新这份记录。

## 9.2 N9 · `roi_external_drift` 纳入失败码（版本化 QA 变更）

`synlab/physical/api.py` 把 `roi_external_drift_mm` 写进 `checks["roi_external_drift"]` 并给出
`pass=false`，却**从不追加失败码**，于是 0.354 mm 漂移可以带着 `status=PASS`、`failure_codes=[]`
出厂（§S11）。`synlab/physical/**` 不在本任务写入范围，因此收紧实现为**独立的版本化 QA 策略层**：

* `synlab/qc/qa_policy.py`：`QA_POLICY_VERSION = "a12.qa.v2"`，新增失败码
  `ROI_EXTERNAL_DRIFT_EXCEEDED`；策略只读生产者**已经测出的** `pass` 标志（缺 `pass` 时用生产者
  自己的规则 `value <= threshold` 复算），**只增失败码**、从不把 FAIL 升为 PASS、幂等；每条审计结果
  打上 `qa_policy.version` 戳，没有该块的旧记录即 `a12.qa.v1`（旧产物的标注依据）。
* 版本记录（`QA_POLICY_HISTORY`，含变更/理由/证据）：`a12.qa.v1`（基线，漂移不进失败码）→
  `a12.qa.v2`（漂移检查失败即进失败码，R5：只加码不放宽）。

**before/after（真实重跑，非引用旧结论）**：

| | 全局 SDF（修前默认路径） | 窄带（S11 修复后默认路由） |
|---|---|---|
| `roi_external_drift_mm` | **0.35424330830574036**（重跑逐位相同） | 0.00034815253457054496 |
| audit v1（生产者） | `PASS`，`failure_codes=[]` | `PASS`，`failure_codes=[]` |
| audit v2（本策略） | **`FAIL`**，`failure_codes=["ROI_EXTERNAL_DRIFT_EXCEEDED"]` | `PASS`，`failure_codes=[]` |

```
.venv\Scripts\python.exe tools\a12_s11_p03_drift.py --step full --backend global_sdf --out data\a12_reports\n9_rerun_global_sdf.json
# 退出码 0；audit PASS / failure_codes [] / drift 0.35424330830574036
.venv\Scripts\python.exe tools\a12_n9_qa_tighten.py --step all --out data\a12_reports\n9_qa_v2.json
# 退出码 0
```

**翻转清单（真实扫描 `data/**` 的 7671 个 JSON + 48 个 sqlite；其中 24 个文件不可读、0 个因体积跳过）**：

| 类别 | 翻 FAIL 记录 | 翻 FAIL 文件 | 该类别带漂移检查的记录 | 已 FAIL | 仍 PASS | 漂移范围 mm |
|---|---|---|---|---|---|---|
| `data/a12_exports/**`（已产出的导出包/资产库） | **13** | **7** | 19 | 6 | 0 | 1.564 – 5.381 |
| 其它 store 资产（`assets/asset_*/meta.json` + `metadata.sqlite` 的 `qa_json`，role 全为 `physical_result`） | 90 | 41 | 150 | 60 | 0 | 0.139 – 21.693 |
| `data/a12_reports/**` | 7 | 7 | 10 | 1 | 2（窄带） | 0.354 – 5.381 |
| `*/store/reports/coverage_rows.json` 等 | 5 | 5 | 11 | 6 | 0 | 0.287 – 1.564 |
| `data/_archive_pre_fix/**`（已是归档旧代） | 131 | 57 | 206 | 75 | 0 | 0.139 – 9.493 |
| **合计** | **246** | **117** | **396** | 148 | 2 | — |

要点（如实）：

* 翻转是**正确行为**：这些产物的几何确实漂移超标，v1 判据装作没看见；
* **训练包本身（`training_package/deploy|research`）没有带漂移检查的 manifest 字段**——漂移审计存在
  于 physical 资产 QA 里，所以"翻 FAIL 的包"指的是 `data/a12_exports/**` 下的资产/存储（13 条记录 /
  7 个文件：`a12_exports/full/assets/asset_*/meta.json` 6 个 + `closed_loop/store/reports/coverage_rows.json` 1 个）；
* 旧产物**一个字节都没有改写**：`data/a12_reports/n9_qa_v2_flips.json` 是"修复前一代"标签登记表
  （`superseded_by_qa_policy:a12.qa.v1`），与 `_archive_pre_fix` 同口径；
* 残留缺口：把版本戳写进**落库资产**需要在提交边界调用本策略层（`synlab/physical/api.py::
  commit_physical`，不在写入范围）——因此落库资产的 QA 仍是 v1 记录，由登记表标注。

## 9.3 N10 · `research/hard_negatives.parquet` 辅助表

S2 的 1120 条 `CANDIDATE_MATE_PRESENT_NOT_ORDINARY` 中 **880 条** query 侧有邻片，落成独立辅助表
（另有 240 条 query 无邻片 → 拒绝并计数，不监督、不静默丢弃）。

**表**：`data/a12_reports/n10/hard_negatives.parquet`（+ 同名 `hard_negatives.card.json` 列语义卡），
由 `tools/a12_n10_hard_negatives_table.py --step build` 从 `negfix` 包的
`research/relations.parquet`（哈希 `sha256:…`，实测**未改动**）派生。

| | 值 |
|---|---|
| 行数 | **880**（全部 `kind=R0`） |
| 列 | **15** 列，见下表 |
| 拒绝行 | 240（`query_mate_absent`，记录在卡片 `rejected` 块） |
| `conformance` | `loss_mask=true ∧ eligible_as_negative=false`、不进任何主指标分母、仅辅助项、query 侧 mate-present（四键全 true） |
| 并入主表反证 | 真检查器 `qc.decision_checks._check_loss_mask_authority`：表外违反 3 → 并入后 **883**（**+880**） |
| 一键开关消融 | 真实 batch：off/on 的 `positives/negatives/excluded/effective_queries/rank_denominator` **逐位相同**，`neg_mask`/`pos_mask` 在 pos/neg 块上**逐位相同**，仅 `hard_negatives` 0→3、批次增宽 3 个 slot（`c = c_pn + c_hard`，属形状） |

**列语义表（数据卡 `hard_negatives.card.json` 的同一份字典，代码在
`synlab/relations/hard_negatives_table.py::COLUMN_SEMANTICS`）**：

| 列 | dtype | 单位 | 语义 |
|---|---|---|---|
| `query` | string | 1 | 对的 query 片；**按构造** mate-present（裁决条件 4） |
| `candidate` | string | 1 | 候补片；它自己在同一池里有确认 `R2` 配偶——这正是它不能当普通负例的原因 |
| `kind` | string | 1 | 该对实测关系类别（R0/R1），**逐字复制，从不改写** |
| `valid` | bool | 1 | 该行测量是否可用——逐字复制 |
| `area_mm2` | float | mm² | 实测共享断口面积——逐字复制 |
| `loss_mask` | bool | 1 | 恒 `true`：该行**受监督**（由辅助硬负例项） |
| `eligible_as_negative` | bool | 1 | 恒 `false`：**永不**是普通负例、**永不**进任何主指标分母 |
| `class` | string | 1 | `HARD_NEGATIVE_MATE_PRESENT`（辅助监督类别） |
| `ruling_class` | string | 1 | `CANDIDATE_MATE_PRESENT_NOT_ORDINARY`（它在主表规则下的类别） |
| `reason` | string | 1 | 主表该行自身的 reason |
| `query_mate_present` | bool | 1 | 恒 `true`（裁决条件 4） |
| `query_mates` | list\<string\> | 1 | query 的确认 `R2` 配偶（实测） |
| `candidate_mates` | list\<string\> | 1 | 候补的确认 `R2` 配偶（实测） |
| `source_relations_hash` | string | 1 | 派生源的 `relations.parquet` sha256 |
| `table_version` | string | 1 | `synlab.relations.hard_negatives_table.v1` |

**为什么不能并入主表**（表里也写着）：主表的冻结单门规则要求每一行
`eligible_as_negative == (kind ∈ {R0,R1} ∧ loss_mask)`；本类别的契约恰恰是
`loss_mask=True ∧ eligible_as_negative=False`，并入即新增 880 条审计违规（=放宽判据，R5 禁止）。

**加载器示例（消融一键开关）**：

```python
from synlab.relations.hard_negatives_table import (load_hard_negatives, attach_hard_negatives,
                                                   enabled_from_env)
table = load_hard_negatives("data/a12_reports/n10/hard_negatives.parquet", enabled=False)
rows  = attach_hard_negatives(rows, table, enabled=False)   # 默认关：行逐字不变
rows  = attach_hard_negatives(rows, table, enabled=True, limit=4)  # 开：只在 'hard_negatives' 键
# 环境开关：SYNLAB_HARD_NEGATIVES=1 -> enabled_from_env() is True（默认 False）
```

命令行同名演示（真实 batch，含分母不变性断言）：

```
.venv\Scripts\python.exe tools\a12_n10_hard_negatives_table.py --step all --out data\a12_reports\n10\hard_negatives.parquet
# 退出码 0
```

**落位说明（如实）**：`<package>/research/hard_negatives.parquet` 是目标位置，`--step install
--research-dir <pkg>/research` 一条命令即可写入。本轮**未**对两个已产出包执行 install，因为
`tools/load_package.py --check` 会把未在 manifest 中声明的文件判为 `unexpected_extra` 并退出 3——该
规则已用**最小夹具包**实测（`verify.undeclared_extra_rule`：`file_set_ok=false`、
`unexpected_extra=["research/hard_negatives.parquet"]`）。声明它的写者
（`synlab/storage/export.py` 的 manifest/数据卡生成）不在写入范围，所以本轮交付"表 + 卡 + 加载器 +
安装步骤"，不制造一个 `--check` 变红的包。

## 9.4 验收与仍未解决

| 项 | 结果 |
|---|---|
| 契约测试四实现 | 全绿（5 个实例 × 13 断言 × canonical/real 两套上下文），退出码 **0** |
| 失败注入 | **6/6** 被指名断言抓住（canonical 与 real 各一次） |
| QA 版本变更 | `a12.qa.v2`（`ROI_EXTERNAL_DRIFT_EXCEEDED`）；翻转 246 条记录 / 117 个文件（含旧代归档 131/57） |
| 辅助表 | 880 行 × 15 列 + 列语义卡；并入主表反证 +880 D10 违规；off/on 分母逐位相同 |
| `pytest tests/a12/{qc,relations,training} -q` | **退出码 0**：314 项、0 失败、0 错误、19 跳过（66.7 s，`data/a12_reports/_n9n10_junit.xml`）。`open_items.md` 记录的 `test_store_sqlite_is_opened_read_only` **顺序相关失败本轮未复现**（`tests/a12/qc` 单独跑同样退出码 0），如实记录、未改该测试 |

**仍未解决**：

1. **资格分歧（9.1.1）未修**：24 条 `valid=False` 的 `R1` 行仍被 `RelationPool` / `PoolIndex` 当作
   普通负例（实时采样路径）。修法是两处一行的语义改动，会改变训练数据，需裁决。
2. **契约未覆盖 `relations/**` 的其它 reader**：`relations.negatives`（library 路线）与
   `relations.sampler` 走的是自己的排除函数（`negative_exclusion_reason`），本轮只对"池"这一层钉死。
3. **QA 版本戳未进落库资产**：策略层在读取侧生效；提交边界（`physical/api.py`）未接线。
4. **旧代未重导出**：翻转清单里的 246 条记录仍带 v1 判据（标签登记表已给出）。
5. **辅助表未进包**：`--step install` 可写，但 manifest/数据卡声明缺写者（会打红 `--check`）。
6. **240 条 query 侧无邻片的类别行**仍无监督角色（N10 原有结论，未变）。

## 9.5 本轮回归（N9 + N10 + 协议契约）

| 命令 | 退出码 | 结果 |
|---|---|---|
| `.venv\Scripts\python.exe -m pytest tests\a12\qc tests\a12\relations tests\a12\training -q` | **0** | 314 项 / 0 失败 / 0 错误 / 19 跳过（`data/a12_reports/_n9n10_pytest_qct.txt`、`_n9n10_junit.xml`） |
| 同上（`tests\a12\qc` 单独） | **0** | 全绿：`test_store_sqlite_is_opened_read_only` 的既有顺序相关失败**本轮未复现**（未改该测试） |
| `.venv\Scripts\python.exe tools\a12_pool_contract.py --step canonical` | 0 | 5 实例 13/13、0 分歧、注入 6/6 |
| `.venv\Scripts\python.exe tools\a12_pool_contract.py --step real` | 0 | 同上 + 保守缺口 861 / 资格分歧 24 对（48 有向、26 个 query） |
| `.venv\Scripts\python.exe tools\a12_n9_qa_tighten.py --step all` | 0 | v2 翻转全局 SDF，窄带保持 PASS，扫描 396 条记录 |
| `.venv\Scripts\python.exe tools\a12_n10_hard_negatives_table.py --step all` | 0 | 880 行、+880 违规反证、off/on 分母逐位相同 |

## 9.6 本轮证据索引（N9 + N10 + 协议契约）

| 文件 | 内容 |
|---|---|
| `synlab/qc/pool_contract.py` | 协议契约单一真源：13 条断言、参考推导、四实现构造、失败注入 |
| `synlab/qc/qa_policy.py` | `a12.qa.v2` 版本化 QA 策略（只增失败码） |
| `synlab/relations/hard_negatives_table.py` | 辅助表 schema/列语义/读写/一键开关 |
| `tools/a12_pool_contract.py` | 契约驱动：`--step canonical\|real\|all` |
| `tools/a12_n9_qa_tighten.py` | N9 驱动：`--step version\|reproduce\|scan\|all` |
| `tools/a12_n10_hard_negatives_table.py` | N10 驱动：`--step build\|verify\|install\|all` |
| `data/a12_reports/pool_contract_canonical.json` / `pool_contract_real.json` | 两套上下文的 13 断言 × 5 实例、注入、一致/分歧 |
| `data/a12_reports/n9_qa_v2.json` / `n9_qa_v2_reproduce.json` / `n9_qa_v2_flips.json` | 版本记录、before/after、翻转清单 + 旧代标签登记 |
| `data/a12_reports/n9_rerun_global_sdf.json` | 全局 SDF 的**真实重跑**（漂移逐位相同） |
| `data/a12_reports/n10/hard_negatives.parquet` + `hard_negatives.card.json` | 880 行辅助表 + 列语义卡 |
| `data/a12_reports/n10_hard_negatives_build.json` / `_verify.json` | 构建、列/约束校验、D10 反证、一键消融、未声明文件规则实测 |
| `tests/a12/qc/test_pool_protocol_contract.py` | 契约套件 + 注入 + 接口子句 |
| `tests/a12/relations/test_pool_protocol_real_package.py` | 真包真 store 的 13 断言 + 资格分歧钉死 |
| `tests/a12/training/test_pool_protocol_consumption.py` | 消费者子句：缺陷 (B) 让真实 batch 抛 `LEAKAGE_DETECTED` |
| `tests/a12/qc/test_n9_qa_policy.py` | 策略算术与"只增码/不升级"不变量 |
| `tests/a12/relations/test_n10_hard_negatives_table.py`、`tests/a12/training/test_n10_hard_negatives_consumption.py` | 辅助表契约与分母不变性 |
