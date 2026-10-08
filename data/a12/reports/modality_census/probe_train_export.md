# Trainable-export modality census — `relicweave-synlab`

READ-ONLY evidence census. **No code, config, or existing data was modified.** Every new file lives under
`data/a12/reports/modality_census/`.

Repo root: `C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab`
Python: `.venv\Scripts\python.exe` (3.12.14; pandas 2.2.3, numpy 2.5.3, pyarrow 25.0.1, zarr 3.4.0)

> ## ⚠️ PROVENANCE / STABILITY WARNING — read before quoting any `file:line`
>
> This census ran while **another agent session was concurrently writing to this repo**. Verified at
> census end: `git status --porcelain` shows **43 changed paths** (21 tracked `M` + 22 untracked `??`), and
> **live processes** were running `data\a12_trainable\tools\batch_driver.py`, `...\neg_run.py`,
> `tools\batch_generate.py --config configs/a12/realistic.yaml`, `tests\a12\observe\run_realistic_lineage.py`,
> `_tmp_run_degrade_diversity.py`, and `pytest tests/a12/fracture/test_multishell_shared_cut.py`.
> Modified tracked files include `synlab/storage/export.py`, `synlab/pipeline.py`, `synlab/training/{adapter,batch,losses,smoke,trainer}.py`.
>
> **None of those changes are mine.** This census wrote only inside `data/a12/reports/modality_census/`.
> Consequences:
>
> - All **data facts** in this report (file counts, sizes, parquet rows/values, array shapes, channel content,
>   zarr chunks, tar members, `a12_trainable` census, the 0-byte `loader_probe.json`) are **immutable snapshots**
>   of the bytes on disk at census time and remain valid.
> - All **code citations** (`file:line`) are pinned to that moment and may drift. Line numbers were re-verified
>   at census end: `synlab/qc/loader_probe.py`, `synlab/training/{adapter,batch,smoke}.py` and
>   `synlab/qc/data_quality.py` were **unchanged**, but `synlab/storage/export.py` **grew by ~136 lines**
>   (e.g. `class TrainingPackage` moved `1447 → 1583`). The `export.py` line numbers below are the
>   **re-verified current** ones.
> - **All three export defects were re-confirmed present after the concurrent edit** (§9), so they are live
>   defects, not stale readings: `_token_arrays` scaled-copy loop still at `export.py:269`,
>   `view_pos` `0.0` default still at `export.py:461`, `frame_id = arange % views` still at `export.py:539`.

## Repro commands

All probes are plain scripts; each prints to stdout and was redirected to a `.out` next to it.

```powershell
cd C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab
$py = ".venv\Scripts\python.exe"; $d = "data\a12\reports\modality_census"; $env:PYTHONIOENCODING="utf-8"
& $py "$d\p1_tree_index.py"     2>&1 | Out-File -Encoding utf8 "$d\p1_tree_index.out"
& $py "$d\p1b_json_compact.py"  2>&1 | Out-File -Encoding utf8 "$d\p1b_json_compact.out"
& $py "$d\p2_parquet.py"        2>&1 | Out-File -Encoding utf8 "$d\p2_parquet.out"
& $py "$d\p3_arrays_zarr.py"    2>&1 | Out-File -Encoding utf8 "$d\p3_arrays_zarr.out"
& $py "$d\p4_obs_tar.py"        2>&1 | Out-File -Encoding utf8 "$d\p4_obs_tar.out"
& $py "$d\p5_defect_verify.py"  2>&1 | Out-File -Encoding utf8 "$d\p5_defect_verify.out"
& $py "$d\p6_trainable.py"      2>&1 | Out-File -Encoding utf8 "$d\p6_trainable.out"
```

| script | evidence produced |
|---|---|
| [`p1_tree_index.py`](p1_tree_index.py) → [`p1_tree_index.out`](p1_tree_index.out) | full tree, sizes, JSON listing (7207 lines) |
| [`p1b_json_compact.py`](p1b_json_compact.py) → [`p1b_json_compact.out`](p1b_json_compact.out) | index/manifest schemas + row counts |
| [`p2_parquet.py`](p2_parquet.py) → [`p2_parquet.out`](p2_parquet.out) | all 12 tables: rows/cols/dtypes/value counts |
| [`p3_arrays_zarr.py`](p3_arrays_zarr.py) → [`p3_arrays_zarr.out`](p3_arrays_zarr.out) | npz channels + zarr read-back test |
| [`p4_obs_tar.py`](p4_obs_tar.py) → [`p4_obs_tar.out`](p4_obs_tar.out) | tar members, `valid`/`view_pos`, token/frame_id checks |
| [`p5_defect_verify.py`](p5_defect_verify.py) → [`p5_defect_verify.out`](p5_defect_verify.out) | numeric proof of the two export defects |
| [`p6_trainable.py`](p6_trainable.py) → [`p6_trainable.out`](p6_trainable.out) | `a12_trainable` layout, sqlite census, training-artifact search |
| [`sub_loader_findings.md`](sub_loader_findings.md) (+ `sub_loader_shard_keys.py`) | loader grep, tensor tables, probe artifacts |

---

## 1. Package tree + index/manifest JSON

| package | path | files | bytes |
|---|---|---|---|
| next_experiment | `data/a12_exports/next_experiment/training_package` | **548** | **1,447,103,119** (1.3 GB) |
| closed_loop | `data/a12_exports/closed_loop/training_package` | **56** | **4,036,352** (3.9 MB) |

### next_experiment — rollup by top dir

| dir | files | bytes |
|---|---|---|
| `<root>` (`export_manifest.json`) | 1 | 155,874 |
| `deploy/` | 542 | 1,446,908,032 |
| `research/` | 5 | 39,213 |

By suffix: `.json` 203 / 307,433 · `.npz` 8 / 344,596,748 · `.parquet` 5 / 38,885 · `.tar` 4 / 1,057,064,960 · (no suffix, zarr chunks) 328 / 45,095,093

Deploy file inventory (next_experiment):

```
       16,944  deploy/deploy_index.json
        7,952  deploy/geometry/index.json
   12,961,591  deploy/geometry/shard_0000.npz
   21,567,718  deploy/geometry/shard_0001.npz
   19,667,759  deploy/geometry/shard_0002.npz
    9,455,768  deploy/geometry/shard_0003.npz
       10,134  deploy/obs/index.json
  302,018,560  deploy/obs/shard_0000.tar ... shard_0002.tar (x3, identical size)
  151,009,280  deploy/obs/shard_0003.tar
        7,873  deploy/tokens/index.json
  106,384,518  deploy/tokens/shard_0000.npz ... (4 shards)
        5,504  deploy/queries.parquet
          246  deploy/zarr/zarr.json
     ~45,000,000  deploy/zarr/<24-hex>/{points,normals,point_valid,normal_valid,scale_valid,frame_id}
       12,822  research/labels/clean.parquet
       10,936  research/labels/physical.parquet
        4,019  research/labels/visible.parquet
        5,604  research/relations.parquet
        5,832  research/labels/query_map.json
```

closed_loop is the same shape, single shard, no `query_map.json`: `deploy/geometry/shard_0000.npz`, `deploy/obs/shard_0000.tar` (2,375,680), `deploy/tokens/shard_0000.npz` (1,189,402), `deploy/queries.parquet`, `deploy/deploy_index.json`, indices, `research/labels/{clean,physical,visible,correspondence,quality}.parquet`, `research/relations.parquet`.

### Index/manifest JSON schemas + row counts

The exact index file names are:

```
export_manifest.json
deploy/deploy_index.json
deploy/geometry/index.json
deploy/obs/index.json
deploy/tokens/index.json
deploy/zarr/zarr.json          <-- group attributes, NOT an "index.json"
deploy/zarr/<opaque>/zarr.json <-- group
deploy/zarr/<opaque>/<array>/zarr.json <-- array
research/labels/query_map.json (next_experiment only)
```

**`deploy/zarr/index.json` DOES NOT EXIST in either package** — the zarr tree uses `zarr.json` metadata files only.

#### `deploy/deploy_index.json` — `synlab.deploy_index.v1`

`note`: *"opaque-name map for the deployment view; contains no label and no split"*

| package | size | rows | row-schema | shard-populated / null |
|---|---|---|---|---|
| next_experiment | 16,944 B | **86** | `geometry_shard, obs_shard, opaque, token_shard` | 28 populated / **58 null** |
| closed_loop | 1,364 B | **6** | same | 3 populated / **3 null** |

`opaque` is non-null for **all** rows (86 / 6). Distinct opaque values: **86** (next_experiment), **6** (closed_loop).

#### `deploy/geometry/index.json` — `synlab.geometry_index.v1`

`arrays`: `["points","normals","point_valid","normal_valid","scale_valid","frame_id"]`

| package | rows | row-schema |
|---|---|---|
| next_experiment | **28** | `frames, n_points, opaque, points_hash, shard` |
| closed_loop | **3** | same |

Distinct shards: next_experiment `geometry/shard_0000..0003.npz`; closed_loop `geometry/shard_0000.npz`.

#### `deploy/obs/index.json` — `synlab.obs_index.v1` (see §4 for detail)

| package | rows | `opaque_naming` |
|---|---|---|
| next_experiment | **28** | `sha256(asset fragment id)[:24]` |
| closed_loop | **3** | same |

#### `deploy/tokens/index.json` — `synlab.token_index.v1`

`token_dim: 256`, `encoder_id: "identity_rgb_blockmean"`, `token_policy_id: "obspack_rgb_blockmean_v1"`.
Rows: **28** (next_experiment) / **3** (closed_loop); row-schema `opaque, shard, token_dim, tokens, tokens_hash`.

#### `export_manifest.json` — `synlab.training_package_manifest.v1`

| field | next_experiment | closed_loop |
|---|---|---|
| `package_schema` | `synlab.training_package.v1` | `synlab.training_package.v1` |
| `package_id` | `pkg_rel_nexp_1790913735` | `pkg_rel_852ab2a1e4c3_1790905541` |
| `release_id` | `rel_nexp_1790913735` | `rel_852ab2a1e4c3_1790905541` |
| `release_profile` | **`PILOT_UNFROZEN`** | **`SANDBOX_CORE`** |
| `release_scope` | `SYNTHETIC` | `SYNTHETIC` |
| `release_gates` | `{"freeze refused; this manifest is not a release"}` | **25 × `PENDING`, 12 × `PASS`** |
| `counts_total` | 547 | 55 |
| `files` | 547 entries (`bytes,hash,path`) | 55 entries |
| `bytes_total` | 1,446,947,245 | 3,998,691 |
| `views.deployment.contains_truth` | False | False |
| `views.research.contains_truth` | True | True |
| `separation.features_carry_answer_fields` | **False** | **False** |
| `separation.answer_field_scan.hits` | **[]** (0 hits) | **[]** (0 hits) |
| `separation.answer_field_scan.keys_scanned` | 276 (unique 132) | 79 (unique 52) |
| `release_scope_completed/pending` | both `null` | completed 6 items, pending `[]` |

next_experiment `reference_closure`: 475 / 470 entries, `contains_truth=False`, and a non-empty problem list mixing
`missing asset LIN....:v1`, `asset ... qa_status=QA_PENDING`, `asset ... qa_status=QA_FAIL`.

closed_loop `superseded_relations`: **18** rows, e.g. kept `{area_mm2 6499.93396608907, kind R2, source clean_truth, valid true}` vs superseded `{area_mm2 0.0, kind UNKNOWN, valid false}`.
closed_loop `supervision_labels.rule` (verbatim): *"visible = inside the delivered image AND camera z>0 AND |z - rendered depth| <= max(0.5 mm, 4 * mm_per_px) AND id_map>=0 AND not uncertain_mask AND deployment_mask (measured by the visible/truth layer)"*.

---

## 2. Parquet tables

**12 tables total** (5 next_experiment, 7 closed_loop).

| package | table | rows | cols | bytes | row groups |
|---|---|---|---|---|---|
| next_experiment | `deploy/queries.parquet` | **86** | 10 | 5,504 | 1 |
| next_experiment | `research/labels/clean.parquet` | **258** | 15 | 12,822 | 1 |
| next_experiment | `research/labels/physical.parquet` | **189** | 15 | 10,936 | 1 |
| next_experiment | `research/labels/visible.parquet` | **64** | 8 | 4,019 | 1 |
| next_experiment | `research/relations.parquet` | **150** | 12 | 5,604 | 1 |
| closed_loop | `deploy/queries.parquet` | **6** | 10 | 3,296 | 1 |
| closed_loop | `research/labels/clean.parquet` | **27** | 15 | 5,925 | 1 |
| closed_loop | `research/labels/correspondence.parquet` | **3,587** | 19 | 61,633 | **8** |
| closed_loop | `research/labels/physical.parquet` | **27** | 15 | 5,930 | 1 |
| closed_loop | `research/labels/quality.parquet` | **12** | 25 | 8,564 | 1 |
| closed_loop | `research/labels/visible.parquet` | **12** | 8 | 2,709 | 1 |
| closed_loop | `research/relations.parquet` | **3** | 12 | 3,714 | 1 |

> Note: `pq.ParquetFile.metadata.num_columns` reports 10 for `queries.parquet` while pandas reads 9 columns —
> the file carries one extra physical column that the pandas view collapses (a nested/`applicability` struct).

### `queries.parquet` (both)

Columns: `query_id, lineage, mother, fragment, gallery, historical_N_G, status, has_observation, applicability(dict)`.

| package | `has_observation` True/False | `status` | distinct lineage / mother / fragment | `applicability` |
|---|---|---|---|---|
| next_experiment | **28 / 58** (32.56% / 67.44%) | `FROZEN` 86 (100%) | 29 / 28 / 86 | 2 distinct values |
| closed_loop | **3 / 3** (50%) | `FROZEN` 6 (100%) | 4 / 3 / 6 | 2 distinct values |

`applicability` is a dict column (needed a hashable-key workaround; `nunique=2` in both).

### `clean.parquet` / `physical.parquet` / `visible.parquet` — role split

Columns for clean/physical (15): `label_layer, asset_id, lineage, split, passed, fragment_id, role, detail, candidate_id, kind, area_mm2, valid, loss_mask, reason, unique_source_triangle`.
`visible` has only 8: `label_layer, asset_id, lineage, split, passed, fragment_id, role, detail` (no `kind`/`area_mm2`/`valid`/`loss_mask`).

| package | table | rows | role=`fragment` | role=`relation` | `passed` | note |
|---|---|---|---|---|---|---|
| next_experiment | clean | 258 | **97** (37.60%) | **161** (62.40%) | True 258 (100%) | R1 124, R2 37 |
| next_experiment | physical | 189 | **68** (35.98%) | **121** (64.02%) | True 189 (100%) | R1 95, R2 26 |
| next_experiment | visible | 64 | **64** (100%) | 0 | **True 35 / False 29** | only table with failures |
| closed_loop | clean | 27 | **18** (66.67%) | **9** (33.33%) | True 27 (100%) | R2 6, UNKNOWN 3 |
| closed_loop | physical | 27 | **18** (66.67%) | **9** (33.33%) | True 27 (100%) | R2 6, UNKNOWN 3 |
| closed_loop | visible | 12 | **12** (100%) | 0 | True 12 (100%) | — |

`label_layer` is a single value per table (`clean`/`physical`/`visible`), so it is not discriminative.
`valid` and `loss_mask` are **identical** in every table (they co-vary exactly).

**Key value counts — next_experiment `clean.parquet` (n=258, 97 nulls = 37.60%)**

| column | value counts |
|---|---|
| `role` | relation 161 (62.40%), fragment 97 (37.60%) |
| `kind` | R1 **124** (48.06%), `None` 97, R2 **37** (14.34%) |
| `valid` | False 124, `None` 97, True 37 |
| `loss_mask` | False 124, `None` 97, True 37 |
| `split` | train 141 (54.65%), confirm 105 (40.70%), dev 12 (4.65%) |
| `passed` | True 258 (100%) |
| `unique_source_triangle` | False 161, `None` 97 — **never True** |

crosstab `role × kind`: fragment → all `NaN` (97); relation → **R1 124, R2 37**. So supervised rows are exactly R2.

**next_experiment `physical.parquet` (n=189, 68 nulls = 35.98%)**: `kind` R1 95 / R2 26; `valid`=`loss_mask` False 95 / `None` 68 / True 26; `split` train 99 (52.38%) / confirm 81 (42.86%) / dev 9 (4.76%); crosstab fragment→NaN 68, relation→R1 95 / R2 26.

**next_experiment `visible.parquet` (n=64)**: `role` fragment 64 (100%); `passed` **True 35 / False 29**; `split` train 45 (70.31%) / confirm 14 (21.88%) / dev 5 (7.81%). No `area_mm2`.

**closed_loop `clean`/`physical` (n=27, 18 nulls = 66.67%)**: `kind` R2 6 / **UNKNOWN 3** / `None` 18; `valid`=`loss_mask` True 6 / False 3 / `None` 18; `split` train 18 (66.67%) / dev 9 (33.33%) — **no `confirm` split**. crosstab fragment→NaN 18, relation→R2 6 / UNKNOWN 3.

### `area_mm2` distribution (where present)

| package / table | n | nulls | min | median | max | mean | std | **zeros** | negatives | sum |
|---|---|---|---|---|---|---|---|---|---|---|
| next_experiment clean | 161 | 97 | **0.000000** | **0.000000** | **38,985.625167** | 1,913.956567 | 5,758.185754 | **124** | 0 | 308,147.007 |
| next_experiment physical | 121 | 68 | **0.000000** | **0.000000** | 38,985.625167 | 2,088.020656 | 6,252.191443 | **95** | 0 | 252,650.499 |
| next_experiment visible | — | — | — | — | — | — | — | — | — | (no column) |
| closed_loop clean/physical | 9 | 18 | 0.0 | 0.0 | 6,499.93396608907 | — | — | 3 | 0 | — |

`area_mm2` is only ever populated for `role=relation` rows (fragment rows are all-null). **The median is 0.0 in every table**: the zero-area rows are exactly the R1 rows (124 in clean, 95 in physical), and the non-zero rows are the R2 rows. `area_mm2` is therefore a clean R1/R2 separator.

### `correspondence.parquet` (closed_loop only)

- **rows = 3,587**, cols 19, 8 row groups, 61,633 B
- distinct `(fragment_a, fragment_b)` pairs = **3**
- distinct `fragment_a` = 3, distinct `fragment_b` = 3, **distinct fragments overall = 6**
- Top pairs: `(LIN0001_V02_M01_PAT01_E01-m, …-p)` ×1329 · `(LIN0000_V01_M01_PAT01_E01-m, …-p)` ×1201 · `(LIN0002_V13_M01_PAT01_E01-m, …-p)` ×1057
- `interface_id`: **nunique 13**, nulls 0 — counts: 1:384, 2:384, 3:383, 4:379, **−1:377**, 5:322, 6:267, 7:254, 9:250, 8:248, 10:190, 11:125, 12:24 → **n(−1)=377, n(≥0)=3,210**
- `residual_mm`: **max = 0.000002**, min 0.000000, median 0.000000, mean 0.000000, p90 0.0, p99 0.0 (653 distinct)
- `relation_kind`: **`R2` 3,587 (100%)**
- `valid` True 3,586 / False **1** (0.0279%); `sample_valid` True 3,586 / False 1; `ambiguous` False 3,586 / **True 1**
- `association_code`: **0 → 3,586**, **2 → 1**
- `source_kind`: `CLEAN_TRUTH` 3,587 (100%); `split`: train 2,258 (62.95%) / dev 1,329 (37.05%) — **no `confirm`**
- `index_a` and `index_b` are each **single-valued** (nunique 1); `weight` has 1,999 distinct values

> Despite 3,587 rows, this table describes only **3 distinct fragment pairs**. Its `valid`/`ambiguous`/`association_code` are all one-off exceptions against a uniform baseline.

### `quality.parquet` (closed_loop only)

- **rows = 12**, cols 25
- `target_channel`: **exactly one value, `observability_visible_rate`, 12/12 (100%)**
- `target_unit`: **`'1'`**, 12/12
- per-channel row count: `observability_visible_rate` → 12
- `target_value` per channel: n=12, **min 0.0**, **max 0.1301416048550236**, **median 0.0**, mean 0.013177521951564271
- `source_kind`: `GT_ORACLE` 12/12; `valid`: True 12/12; `split`: train 8 (66.67%) / dev 4 (33.33%)
- `fragment_id` 3 distinct, `view_id` 4 distinct, `lineage` 3 distinct
- diagnostic columns present: `samples, projected, depth_ok, id_ok, not_uncertain, deployment_ok, visible` and `*_rate` variants (`visible_rate, depth_ok_rate, id_ok_rate, not_uncertain_rate, deployment_ok_rate`)

> Only **one** channel is present, and it is 8/12 zeros with a max of 0.130 — a very weak target.

### `relations.parquet`

| package | rows | `kind` R1/R2 | `valid` | `loss_mask` | `eligible_as_negative` | `has_observation` | `pool_id` | `split` |
|---|---|---|---|---|---|---|---|---|
| next_experiment | **150** | **R1 117 (78%), R2 33 (22%)** | False 117 / True 33 | False 117 / True 33 | **False 150 (100%)** | **False 150 (100%)** | 1 distinct | **`''` 115 (76.67%)**, train 20, confirm 14, dev 1 |
| closed_loop | **3** | R2 3 (100%) | — | — | — | — | — | — |

Columns (12): `query, candidate, kind, area_mm2, valid, loss_mask, pool_id, split, lineage_cluster, eligible_as_negative, has_observation, reason`.

**This is the single most important table finding: `eligible_as_negative` is `False` for all 150 rows and `has_observation` is `False` for all 150 rows.** There is no legal negative in either exported relation table (closed_loop has only 3 rows, all R2). This is exactly what blocks the dominant training task (see §8).

---

## 3. Arrays — `deploy/geometry/shard_*.npz` and `deploy/tokens/shard_*.npz`

### Key-naming convention

**`<24-hex-opaque>__<channel>`** — confirmed exactly. Keys that fail the pattern: **0** in every shard of both packages.

### geometry npz

| package | shards | keys/shard | **total keys** | **distinct opaque ids** | channel histogram |
|---|---|---|---|---|---|
| next_experiment | 0000–0003 | 48 / 48 / 48 / **24** | **168** | **28** (+4/8/8/8 per shard) | `points` 28, `normals` 28, `point_valid` 28, `normal_valid` 28, `scale_valid` 28, `frame_id` 28 |
| closed_loop | 0000 | 18 | **18** | **3** | same 6 channels × 3 |

Per-channel shapes/dtypes (one representative opaque each; identical structure for all):

| channel | shape | dtype | min / max | bool `True` fraction |
|---|---|---|---|---|
| `points` | `(N, 3)` | **float32** | next_exp **−225.893 … +403.369**; closed_loop −95.7211 … +152.547 | — |
| `normals` | `(N, 3)` | **float32** | **−1.0 … +1.0** | — |
| `point_valid` | `(N,)` | **bool** | — | **1.000000 (100% True, all 28+3 fragments)** |
| `normal_valid` | `(N,)` | **bool** | — | **1.000000 (100% True, all fragments)** |
| `scale_valid` | `(N,)` | **bool** | — | **1.000000 (100% True, all fragments)** |
| `frame_id` | `(N,)` | **int32** | **0 … 11** (next_exp), **0 … 3** (closed_loop) | — |

`N` per fragment is fragment-specific and ranges widely, e.g. next_experiment 7,428 / 11,405 / 14,259 / 15,171 / 16,118 / 30,926 / 33,868 / 35,714 / 37,308 / 40,459 / 46,404 / 49,914 / 50,828 … up to **217,855**. Total geometry points = **2,051,676** (next_experiment, from manifest) / **6,049** (closed_loop).

**`scale_valid` fraction = 1.000000 (100% True) in every single fragment of both packages.** Metric scale is usable and is not a gating channel here. Contrast with the loader probe: `scale_valid_fraction` 0.25 (16/64 fragments) for next_experiment and 0.5 (3/6) for closed_loop — the fraction is driven by *fragment coverage*, not by any `False` inside a covered fragment.

### `frame_id` — exact meaning, read from the writer (NOT guessed)

`synlab/storage/export.py:537-539`:

```python
scale_valid = np.full(points.shape[0], bool(meta.get("scale_valid", False)), dtype=bool)
views = int(obs_by_fragment.get(fragment_id, {}).get("views", 1) or 1)
frame_id = (np.arange(points.shape[0], dtype=np.int32) % views).astype(np.int32)
```

`export.py:563` then records `"frames": int(np.unique(frame_id).size)` in the geometry index.

**`frame_id[i] = i mod n_views`.** It is a positional counter modulo the view count — *not* a coordinate frame, not a camera id, and not a per-point viewpoint. It does not reference `S_mm` or any transform (the unrelated `frame_id="S_mm"` strings elsewhere — `observe/audit.py:292`, `degrade/api.py:568` — never reach the geometry shard).

Verified numerically in `p5_defect_verify.py` / `p4_obs_tar.py`:

```
frame_id == arange(n) % 12  -> True   (all 24 next_experiment fragments)
frame_id == arange(n) % 4   -> True   (all 3 closed_loop fragments)
per-value counts (n=89082, 12 views): {0..5: 7424 each, 6..11: 7423 each}   # perfectly uniform
```

`frame_id` is a deterministic function of the row index, so it carries **zero information**. Any model or analysis that treats `frame_id` as a viewpoint label is mis-reading it. (It is consistent with the loader's `token_view`, which is likewise `np.repeat(arange(n_views), blocks)` — see §6.)

### tokens npz

| package | shards | **total keys** | **distinct opaque ids** | channel histogram |
|---|---|---|---|---|
| next_experiment | 0000–0003 | **140** | **28** | `tokens` 28, `token_valid` 28, `token_view` 28, `token_input` 28, `tile_valid` 28 |
| closed_loop | 0000 | **15** | **3** | same 5 channels × 3 |

| channel | next_experiment shape | closed_loop shape | dtype | values |
|---|---|---|---|---|
| `tokens` | `(576, 256)` | `(192, 256)` | **float32** | **0.0179194 … 0.730001** / 0.0139938 … 0.645182 |
| `token_input` | `(576,)` | `(192,)` | **float32** | **0.017924 … 0.730001** / 0.0139974 … 0.645182 |
| `token_valid` | `(576,)` | `(192,)` | **bool** | **True_frac 1.000000 (all)** |
| `token_view` | `(576,)` | `(192,)` | **int32** | **0 … 11** / **0 … 3**, nunique 12 / 4 |
| `tile_valid` | `(12, 768, 1024)` | `(4, 192, 256)` | **bool** | **True_frac min 0.000070 / mean 0.273400 / max 0.664962** (next_exp); 0.003627 / 0.010323 / 0.017746 (closed_loop) |

Token budget is constant: 576 = 12 views × 48 blocks; 192 = 4 views × 48 blocks.

---

## 4. Obs tars — `deploy/obs/shard_*.tar`

Members were read **in memory** via `tarfile.extractfile`; nothing was extracted to disk.

### Declared channels (`deploy/obs/index.json`, verbatim)

```json
"opaque_naming": "sha256(asset fragment id)[:24]",
"channels": ["tiles.npy (uint8 RGB)", "valid.npy (deployment mask)", "view_pos.npy (u position mm)"],
"forbidden_channels": ["depth_z", "id_map", "surface_tag", "uncertain_mask", "roi", "K", "T_WC", "dist"]
```

**`channels` = 3**, **`forbidden_channels` = 8**, and `truth_channels` is `[]` for every row in both packages (28/28 and 3/3) — the deployment view declares no truth channel.

### Index row counts

| package | index `rows` | distinct `shape` | distinct `views` | rows per shard | Σ views | Σ shape elements |
|---|---|---|---|---|---|---|
| next_experiment | **28** | `(12, 768, 1024, 3)` ×28 | `12` ×28 | 0000:8, 0001:8, 0002:8, **0003:4** | **336** | 792,723,456 |
| closed_loop | **3** | `(4, 192, 256, 3)` ×3 | `4` ×3 | 0000:3 | **12** | 1,769,472 |

### Tar members

| tar | members | distinct opaques | suffixes | total member bytes |
|---|---|---|---|---|
| next_experiment `shard_0000.tar` | **24** | 8 | `tiles.npy` 8, `valid.npy` 8, `view_pos.npy` 8 | 301,993,344 |
| next_experiment `shard_0001.tar` | 24 | 8 | same | 301,993,344 |
| next_experiment `shard_0002.tar` | 24 | 8 | same | 301,993,344 |
| next_experiment `shard_0003.tar` | **12** | **4** | same | 150,996,672 |
| closed_loop `shard_0000.tar` | **9** | **3** | same | 2,360,496 |

Member naming convention: **`<24-hex-opaque>/<tiles|valid|view_pos>.npy`** — 0 non-matching members. Member name lengths are only 24+1+len(suffix). All members have `mtime=0` (deterministic archives).

### Per-member array shapes/dtypes

| member | next_experiment | closed_loop | dtype |
|---|---|---|---|
| `tiles.npy` | `(12, 768, 1024, 3)` | `(4, 192, 256, 3)` | **uint8** (0 … 255) |
| `valid.npy` | `(12, 768, 1024)` | `(4, 192, 256)` | **bool** |
| `view_pos.npy` | `(12,)` | `(4,)` | **float32** |

### `valid.npy` — fraction True

| tar | True fraction | n_True / n |
|---|---|---|
| next_experiment shard_0000 | **0.000648** | 6,114 / 9,437,184 |
| next_experiment shard_0001 | **0.000386** | 3,647 / 9,437,184 |
| next_experiment shard_0002 | **0.179365** | 1,692,700 / 9,437,184 |
| next_experiment shard_0003 | **0.264235** | 2,493,637 / 9,437,184 |
| closed_loop shard_0000 | **0.003627** | 713 / 196,608 |

**The deployment mask is extremely sparse and wildly uneven across shards — from 0.039% to 26.4%.** shard_0000/0001 are nearly empty. Per-view True counts are also very uneven, e.g. shard_0000 view-wise `[720, 0, 0, 879, 1404, 0, 0, 665, 1016, 0, 126, 1304]` — **three views of twelve are entirely empty**.

`valid` does not equal "tiles are non-black": agreement is only 0.783–0.906, and IoU(valid, tiles_nonzero) collapses to **0.001224** (shard_0001) and **0.005320** (shard_0000). Many `valid=True` pixels are black and many non-black pixels are `valid=False`.

### `view_pos.npy` — units and range

Declared unit is **mm** ("u position mm", the camera slide position `u_position_mm`). Actual content:

```
next_experiment: view_pos members=28  all-zero members=28 (100.0%)  global min=0.0 max=0.0 n_unique=1
closed_loop:     view_pos members=3   all-zero members=3  (100.0%)  global min=0.0 max=0.0 n_unique=1
```

**`view_pos.npy` is identically zero in all 31 members of both packages.** Range is `[0.0, 0.0]`, `n_unique = 1`.

Writer `synlab/storage/export.py:461`:

```python
view_pos.append(np.asarray(meta_view.get("u_position_mm", 0.0), dtype=np.float32))
```

The `u_position_mm` key is absent from the stored view metadata on this path, so the silent `0.0` default is written for every view. The same `0.0` default exists on the read path (`observe/routes.py:1969`). **The declared mm position channel is dead data — there is no camera-slide/position signal in either package.**

---

## 5. Zarr store

`deploy/zarr/` (next_experiment: 28 groups, closed_loop: 3 groups). Group names are 24-hex opaque ids; every group has the identical member set `[frame_id, normal_valid, normals, point_valid, points, scale_valid]` (6 arrays). There is **no `deploy/zarr/index.json`**; the store is described by `zarr.json` files (zarr format **3**).

Root `deploy/zarr/zarr.json`:

```json
{"attributes": {"schema": "synlab.geometry.zarr.v1",
                "arrays": ["points","normals","point_valid","normal_valid","scale_valid","frame_id"]},
 "zarr_format": 3, "node_type": "group"}
```

Per-group `zarr.json` is `{"attributes": {}, "zarr_format": 3, "node_type": "group"}`.

### Per-array declared `shape` / `data_type` / `chunk_grid`

| array | `data_type` | `shape` | `chunk_grid` | `fill_value` | codecs |
|---|---|---|---|---|---|
| `points` | `float32` | `[N, 3]` | `regular`, `chunk_shape` `[ceil(N/2), 3]` or `[ceil(N/4), 2]` (varies) | 0 | `bytes(little)` + `zstd(level 0)` |
| `normals` | `float32` | `[N, 3]` | same scheme as `points` | 0 | `bytes(little)` + `zstd` |
| `point_valid` | `bool` | `[N]` | `regular`, `chunk_shape` `[N]` | `false` | `bytes` + `zstd` |
| `normal_valid` | `bool` | `[N]` | `regular`, `chunk_shape` `[N]` | `false` | `bytes` + `zstd` |
| `scale_valid` | `bool` | `[N]` | `regular`, `chunk_shape` `[N]` | `false` | `bytes` + `zstd` |
| `frame_id` | `int32` | `[N]` | `regular`, `chunk_shape` `[N]` or `[N/2]` | 0 | `bytes(little)` + `zstd` |

`chunk_key_encoding` is `{"name":"default","separator":"/"}`; `dimension_names` is `null`; `node_type` is `array`.

### Are the chunk data files actually present? — **YES**

| package | groups | arrays declared | **on-disk chunk files** | bytes |
|---|---|---|---|---|
| next_experiment | 28 | **168** | **328** | **45,095,093** |
| closed_loop | 3 | **18** | **18** | **132,337** |

Real paths and sizes (closed_loop, verbatim):

```
       34  56af3b4c1137751192c649b4/frame_id/c/0
       19  56af3b4c1137751192c649b4/normal_valid/c/0
    6,417  56af3b4c1137751192c649b4/normals/c/0/0
       19  56af3b4c1137751192c649b4/point_valid/c/0
    6,440  56af3b4c1137751192c649b4/points/c/0/0
       19  56af3b4c1137751192c649b4/scale_valid/c/0
```

The 328 chunk files match the 328 suffix-less files counted in the package tree rollup — the accounting closes.

Note the sizes: `frame_id` chunks are **34–323 bytes** and `*_valid` chunks are **19–26 bytes**. That is the compression signature of exactly the degenerate content proven in §3 (`frame_id` = a ramp; `*_valid` = all-True), and it is an independent confirmation of those findings.

### Verdict: the zarr store is **COMPLETE and USABLE**, not metadata-only

Proven by an actual read-back with zarr 3.4.0:

```
zarr.open_group OK: 28 groups = ['03ff40a3…', '0bfd7c43…', …]
[56af3b4c1137751192c649b4]/points:        read shape=(585, 3) dtype=float32  min=-41.7791862487793 max=58.92715072631836
[56af3b4c1137751192c649b4]/frame_id:      read shape=(585,)   dtype=int32    min=0 max=3  unique=[0,1,2,3]
[56af3b4c1137751192c649b4]/point_valid:   read shape=(585,)   dtype=bool     True_frac=1.000000
[56af3b4c1137751192c649b4]/scale_valid:   read shape=(585,)   dtype=bool     True_frac=1.000000
CROSS-CHECK geometry/shard_0001.npz:03ff40a308a0626310c1a441__points vs zarr points -> identical=True
```

The zarr replica is byte-equivalent to the npz geometry. **However, nothing reads it** — see §6. It is hash-verified by `TrainingPackage.verify_files` and then never parsed. It is 45 MB of manifest-only ballast in next_experiment.

---

## 6. Loader

Investigated in [`sub_loader_findings.md`](sub_loader_findings.md) (full detail + verbatim artifacts).
`export.py` line numbers below are **re-verified after the concurrent edit**; the other files' citations were unchanged.

### Functions that read the package

| function | file:line |
|---|---|
| `class TrainingPackage` | `synlab/storage/export.py:1583` |
| `.__init__` (reads + hash-checks `export_manifest.json`) | `synlab/storage/export.py:1586` |
| `.verify_files` | `synlab/storage/export.py:1605` |
| `.relations` / `.queries` / `.labels` | `synlab/storage/export.py:1619` / `:1622` / `:1625` |
| `.observation_index` | `synlab/storage/export.py:1640` |
| `.read_observation` (tar) | `synlab/storage/export.py:1644` |
| `.read_geometry` / `.read_tokens` | `synlab/storage/export.py:1666` / `:1669` |
| `._read_shard` (npz) | `synlab/storage/export.py:1672` |
| `class ExportedRelationPool` | `synlab/qc/loader_probe.py:61` |
| `load_features` | `synlab/qc/loader_probe.py:171` |
| `probe_training_package` | `synlab/qc/loader_probe.py:262` |
| `build_training_batch` | `synlab/training/batch.py:253` |
| `load_real_inputs` | `synlab/training/smoke.py:148` |
| `PackageLabelSource.from_package` | `synlab/training/labels.py:70` |

Everything is **index-driven, nothing hardcoded**: `shard = self.deploy / entry["shard"]` (`export.py:1651`), `prefix = f"{entry['opaque']}__"` (`export.py:1684`). Zero shard-count literals. Writer-side shard f-strings now at `export.py:481` (obs tar), `:552` (geometry npz), `:598` (tokens npz).

### Exact tensors/batches yielded (3 stages)

**Stage A — raw per-fragment payload** (`_observed_payload`, `loader_probe.py:218`): `global_rgb [V,3,H,W]` float32 · `global_valid [V]` bool · `pixel_valid [V,H,W]` bool · `points [N,3]` float32 · `point_valid [N]` bool · `normals [N,3]` float32 · `normal_valid [N]` bool · `local_tokens [T,256]` float32 · `token_valid [T]` bool · `token_view [T]` int32 · `token_modality [T]` int32 (all 0) · `token_source [T]` int32 (all 0) · `tokens_total` int32 · `quality (1,1)` float32 zeros · `quality_valid (1,1)` bool · `presence (1,)` float32 · `presence_valid (1,)` bool · `scale_valid` bool · `obs_version` int32 = 1 · `token_budget` int. A leak guard at `loader_probe.py:253-258` raises `LEAKAGE_DETECTED` if any forbidden key appears.

**Stage B — `FeatureBundle`** (`adapter.py:406-428`). Real next_experiment (F=64, V=12, H=768, W=1024, L=576, N=217855):

| name | shape | dtype |
|---|---|---|
| `fragment_ids` | list len 64 | str |
| `global_rgb` | `[64,12,3,768,1024]` | float32 |
| `global_valid` | `[64,12]` | bool |
| `pixel_valid` | `[64,12,768,1024]` | bool |
| `local_tokens` | `[64,576,256]` | float32 |
| `token_valid` | `[64,576]` | bool |
| `token_view` | `[64,576]` | int32 |
| `token_pixel` | `[64,576,2]` **all −1, never filled** | int32 |
| `token_modality` / `token_source` | `[64,576]` | int32 |
| `token_retrieval` | `[64,576]` **all −1** | int32 |
| `tokens_total` | `[64]` | int32 |
| `points` | `[64,217855,3]` | float32 |
| `point_valid` | `[64,217855]` | bool |
| `normals` | `[64,217855,3]` | float32 |
| `normal_valid` | `[64,217855]` | bool |
| `quality` / `quality_valid` | `[64,1,1]` | float32 / bool |
| `presence` / `presence_valid` | `[64,1]` | float32 / bool |
| `scale_valid` | `[64]` | bool |
| `obs_version` | `[64]` | int32 |

closed_loop real: `global_rgb [6,4,3,192,256]`, `local_tokens [6,192,256]`, `points [6,4158,3]`, token_budget 192.
`to_torch` (`adapter.py:523-531`): floats→float32, `*_valid`→bool, all index/token int fields→**int64**.

**Stage C — `TrainingBatch`** (`batch.py:293-304,375,390,395-396,424-430`):

| name | next_experiment | closed_loop | dtype |
|---|---|---|---|
| `pair_index` | `[36,1,2]` | `[3,1,2]` | int64 |
| `pair_valid` | `[36,1]` | `[3,1]` | bool |
| `labels_relation` | `[36,1]` | `[3,1]` | int8 |
| `label_pair_valid` | — | `[3,1]` | bool |
| `pos_mask` / `neg_mask` / `excluded_mask` | `[36,1]` | `[3,1]` | bool |
| `exclusion_reason` | `[36,1]` | `[3,1]` | int8 |
| `negative_is_r2_history` | must be all False | | bool |
| `r1_fallback_used` | — | `[3,1]` | bool |
| `sample_keys` | `[36]` | `[3]` | `<U64` |
| `quality_target` | `[64,1,1]` | `[6,1,1]` | float32 |
| `quality_target_valid` | — | `[6,1,1]` | bool |
| `corr_weight` | `[36,1,576]` | `[3,1,192]` | float32 |
| `corr_row_valid` / `corr_col_valid` | — | `[3,1,192]` | bool |
| `corr_kind` | — | `[6,192]` | int8 |
| `contradiction` / `contradiction_valid` | `[36,1]` | `[3,1]` | int8 / bool |
| `quality_tier` | `[64]` | `[6]` | int8 |
| `lineage_cluster` | `[64]` | `[6]` | int64 |
| `pool_id` | `"exported"` | `"exported"` | str |

Row splits — next_experiment: n_queries 36, n_candidates 1, positives 12, **negatives 0**, excluded 24, **effective_queries 0**. closed_loop: 3 / 1 / 3 / **0** / 0 / **0**.

### Can it read BOTH packages? — **YES, one code path**

`_read_shard` takes the shard name from `entry["shard"]` and the array prefix from `entry["opaque"]`; neither the loader nor the probe lists, globs, or counts shards (grep for `glob|iterdir|rglob|== 4|0000` in `loader_probe.py` → no shard-enumeration code). Required inputs are `export_manifest.json` + per-fragment rows in `deploy/geometry/index.json` / `deploy/tokens/index.json`; `deploy/obs/index.json`, `queries.parquet`, `relations.parquet` and label layers are all optional (missing → `{}` / `[]`). Both real packages have the full required set and both PASS in real probe runs.

**One real caveat:** `probe_training_package` has `max_fragments=16` (`loader_probe.py:262`, truncation at `:323`). On next_experiment this silently caps the batch at 64 fragments / 16 queries instead of 86. `synlab/training/smoke.py:160-164` deliberately omits the truncation. closed_loop (6 queries) is unaffected.

### Does it read the zarr path? — **NO**

`grep zarr` → **0 hits** in `synlab/qc/loader_probe.py` and **0 hits** in all of `synlab/training/`. In `export.py`, zarr appears only in the writer (`_zarr_root:205`, zarr write block, `_write_zarr:1357`) and the manifest scanner (`_zarr_declared_arrays:1449`). `TrainingPackage` composes only `export_manifest.json`, `deploy/obs/index.json`, `deploy/<entry["shard"]>`, `research/relations.parquet`, `deploy/queries.parquet`, `research/labels/<layer>.parquet`. `ZARR_DIR_NAME` (`export.py:77`) is exported but referenced by no reader. Geometry actually used comes from `deploy/geometry/shard_*.npz`.

Likewise `deploy/deploy_index.json` is read by **no loader** — the only reader in the repo is `synlab/qc/data_quality.py:1388`, a QC counter.

### Real loader probe artifacts

`data/a12/reports/loader_probe_summary.json` (+ byte-identical `data/a12/reports/next_experiment/loader_probe.out`) — **next_experiment**:
`ok true / status PASS / files_ok true / files_checked 547`; counts relations **150**, queries **86**, kinds `{R1:117, R2:33}`; `pool_id "exported"`, r2_closure ok true, edges 33, fragments_with_mates 66; batch_fragments **64**; feature_shapes n_fragments 64, n_views 12, token_budget 576, n_points 217855, global_rgb `[64,12,3,768,1024]`, local_tokens `[64,576,256]`, points `[64,217855,3]`, **scale_valid_fraction 0.25**; real_denominator fragments 64, with_observation 16, without_observation 48, tokens_total 9216, tokens_valid 9216, points_valid 1,208,720, scale_valid_fragments 16; batch n_queries 36, n_candidates 1, positives 12, **negatives 0**, excluded 24, **effective_queries 0**; exposure tokens 9216 points 1208720 clean_fraction 1.0, tier `{Q0:64}`, exclusion `{none:12, gray_zone:24, rest 0}`; negative_audit `{ok true, problems [], negatives 0, positives 12, r1_fallback_used 0}`; all 10 attempts ok.

**`data/a12/reports/loader_probe.json` is 0 BYTES on disk** — the probe's own JSON dump hit `MemoryError` on this package size. Its real content was preserved in `data/a12_exports/_scratch/numbers.txt:44-49` (closed_loop): `ok True status PASS files_ok True`, counts `{"queries": 6, "relation_kinds": {"R2": 3}, "relations": 3}`, feature_shapes `global_rgb [6,4,3,192,256]`, `local_tokens [6,192,256]`, `points [6,4158,3]`, n_views 4, token_budget 192, `scale_valid_fraction 0.5`, `token_retention [1.0, 0.0, 1.0, 0.0, 1.0, 0.0]`.

`data/a12_exports/_scratch/loop_loader.out` (314 B, verbatim):
```
[loader_probe] running ...
[loader_probe] OK in 1.6s

=== closed loop ===
  loader_probe             OK            1.6s  ok=True queries=3 pos=3 neg=0
```
`loop_loader2.out` identical at 1.5s; `data/a12/reports/closed_loop_loader_after_fix.txt` identical at 1.8s; all corresponding `.err` files are 0 bytes.

`data/a12_exports/_scratch/loader2_check.txt` (419 B): `ok True status PASS files_ok True files_checked 13`, counts `{"queries": 6, "relation_kinds": {"R2": 3}, "relations": 3}`, real_denominator `{fragments 6, with_obs 3, without_obs 3, points_valid 6049, scale_valid_fragments 3, tokens_total 576, tokens_valid 576}`, negative_audit `{negatives 0, ok true, positives 3, problems [], r1_fallback_used 0}`.

### Invocation (there is NO console script for the loader)

`pyproject.toml:40-41` declares exactly one console script: `synlab = "synlab.cli:main"`, and `synlab/cli.py` has no loader-probe command. `loader_probe.py` has no `argparse`/`main()`/`__main__` — library only.

```powershell
# closed_loop, canonical report path
& $py -c "from synlab.qc.loader_probe import probe_training_package; probe_training_package('data/a12_exports/closed_loop/training_package', out_path='data/a12/reports/loader_probe.json')"
# closed-loop driver (produced loop_loader*.out; --step loader_probe)
& $py tools\closed_loop.py --step loader_probe
# next_experiment (no dump; bounded summary) -- produced loader_probe_summary.json
& $py tools\loader_probe_run.py
& $py tools\next_experiment_export.py --step loader_probe
# training smoke (same loader helpers, then real forward/backward)
& $py -m synlab.training.smoke --package data/a12_exports/closed_loop/training_package --steps 3 --out data/a12/reports
```

`probe_training_package(package_dir, *, max_fragments=16, out_path=None, token_budget=None)` — pass `out_path=None` to skip the dump that MemoryErrors (`_finish`, `loader_probe.py:418-427`).

---

## 7. `obs/index.json` rows count and distinct fragment/opaque ids

| package | `deploy/obs/index.json` rows | `deploy/geometry/index.json` rows | `deploy/tokens/index.json` rows | `deploy_index.json` rows | distinct `opaque` in `deploy_index.json` |
|---|---|---|---|---|---|
| next_experiment | **28** | **28** | **28** | **86** | **86** |
| closed_loop | **3** | **3** | **3** | **6** | **6** |

The three shard indices agree exactly with each other and with the count of populated (non-null-shard) rows in `deploy_index.json` (28 and 3). `deploy_index.json` additionally carries 58 (next_experiment) and 3 (closed_loop) **unobserved** fragments with a valid `opaque` but `geometry_shard = obs_shard = token_shard = null` — those are the pair-partners that were never rendered, which is the root cause of the "one side of every labelled pair has no token evidence" blocker in §8.

`query_map.json` (next_experiment only) maps all 86 opaque observation names to their ids.

---

## 8. `data/a12_trainable/` — layout and what actually ran

**This directory contains NO training.** It is a data-generation store, and it is graded `not_trainable`.

### Layout

```
TOTAL FILES = 602   TOTAL BYTES = 11,158,579,409

config_sha256.txt   64 B        8186653101612cbc20e9eeba3f60ffbc241e3d1e3ebd690fdecb60746ab1fb16
logs/               43 files    62,486 B
negatives/          64 files    2,033,009 B   (meshes/, reports/, work/, library.json, library_plan.json)
reports/            2 files     17,195 B      (batch_driver.json, neg_run.json)
store/              487 files   11,156,410,171 B
tools/              5 files     56,484 B      (poll_prereq_a.py, batch_driver.py, run_export_and_measure.py,
                                               neg_run.py, neg_driver.py)

store/assets/       483 files   11,149,244,052 B
store/blobs/        0 files     0                <-- EMPTY
store/releases/     0 files     0                <-- EMPTY (no release was ever frozen)
store/reports/      1 file      18,975 B         (next_experiment_batches.json)
store/tmp/          0 files     0                <-- EMPTY
```

`store/metadata.sqlite` = 2,965,504 B (+ `-wal` 4,148,872, `-shm` 32,768). `tools/` contains **no training script** — `batch_driver.py` (10,455 B) generates, `run_export_and_measure.py` (11,078 B) exports and measures, `neg_driver.py` (19,453 B) drives negatives.

### `store/metadata.sqlite` census (opened read-only)

12 tables: `assets, blobs, dependencies, events, gpu_leases, idempotency, jobs, releases, reservations, runs, schema_meta, sqlite_sequence`.

| table | rows |
|---|---|
| **`assets`** | **236** |
| `events` | 242 |
| `runs` | 6 |
| `schema_meta` | 1 |
| `blobs` | **0** |
| `dependencies` | **0** |
| `gpu_leases` | **0** |
| `idempotency` | **0** |
| `jobs` | **0** |
| `releases` | **0** |
| `reservations` | **0** |

> **Correction to the brief:** the assets table has **236 rows**, not 176. On-disk `store/assets/` also has exactly **236** directories (file kinds: `.json` 236, `.npz` 218, `.bin` 29), so the DB and disk agree at 236.

`assets` value counts:

| column | distribution |
|---|---|
| `role` | `obs_result` 51, `feature_bundle` 42, `fragment_mesh` 30, `material_profile` 15, `mother_mesh` 15, `pattern_channels` 14, `pattern_recipe` 14, `clean_truth` 12, `physical_component` 9, `physical_result` 9, `physical_truth` 9, `visible_labels` 8, `label_bundle` 4, `provenance` 4 |
| `split` | train **195**, dev **21**, confirm **20** |
| `qa_status` | **QA_PASS 193**, **QA_PENDING 37**, **QA_FAIL 6** |

`runs.status` = **`PENDING` for all 6 runs**. `events.state`: QA_PASS 193, QA_PENDING 37, QA_FAIL 6, PENDING 6. `jobs`/`releases`/`gpu_leases`/`reservations` are all empty — **no job ever transitioned to running or done, and no release was ever frozen.**

### Search for real training artifacts — none exist

Patterns `*.pt *.pth *.ckpt *.safetensors *.onnx *optim* *loss* *epoch* *train* *checkpoint* *metric* *curve* *history*` under `data/a12_trainable`:

- Only hit class: **29 × `relations.bin`** (2 B – 2,413 B) — relation payloads, not model weights.
- **No checkpoint, optimizer state, loss curve, epoch count, metric file, or training log exists anywhere in `data/a12_trainable`.**
- The literal string `epoch` appears **nowhere**. Every `loss` hit is the QA accounting field `loss_accounting` (e.g. `{"absolute_error_mm3": 0.0, "declared_lost_volume_mm3": 1150.525…, "pass": true}`) inside asset `meta.json` — geometry QA, not a training loss.

### What actually happened — the real production ledger

`reports/batch_driver.json` (`synlab.a12.trainable.batch_driver.v1`, config `configs/a12/next_experiment.yaml`, config_sha256 matches `config_sha256.txt`): **`target_accepted: 10`, and only 4 were accepted.**

| invocation | mothers | wall s | exit | accepted | failed | running total | dominant errors |
|---|---|---|---|---|---|---|---|
| 1 | 1,2,3 | 347.828 | 1 | 0 | 4 | 0 | `NameError: name '_stamp_obs_semantics' is not defined`; `TypeError: _commit_features() got an unexpected keyword argument 'obs_semantics'` |
| 2 | 4,5,6 | 387.442 | 1 | 0 | 3 | 0 | `ErrorCode.PRECISION_NOT_REALIZED` (manifold: "Not all meshes are volumes!"); `_commit_features() ... 'obs_semantics'` |
| 3 | 7,8,9 | 201.964 | 1 | **1** | 2 | 1 | `ErrorCode.FRACTURE_CONSERVATION_FAIL` ("M_minus is not watertight after the boolean (faces=6892)"); `PRECISION_NOT_REALIZED` |
| 4 | 10,11,12 | 491.519 | **0** | **3** | 0 | **4** | — |

`stop_reason: "max_invocations_reached"`. `accepted_after: [LIN0009_V04_M01_PAT02, LIN0010_V07_M10_PAT08, LIN0011_V17_M12_PAT09, LIN0012_V03_M02_PAT01]`.
`disk_bytes_total_after: 11,156,105,595`, `disk_delta_bytes_total: 11,152,723,877`.
`store_obs_semantics_histogram` evolves `<none>`: 4 → 9 → 12 → 14 and `physical_side_v2`: 0 → 0 → 1 → 4 — i.e. the `obs_semantics` fix only reached storage in invocations 3–4.
**Accept rate 4/12 lineages; ~13.3 hours of total wall time across 4 invocations for 11.2 GB.**

`reports/neg_run.json` (`synlab.a12.trainable.neg_run.v1`): `target_mothers_ok: 10`, `run_id: "run_trainable_relneg"`, indices 100–111, `stop_reason: "indices_exhausted"`, `mothers_observed_ok: [102, 103, 104, 105]` → **4 of 6 attempted mothers observed successfully**. Failures: `FRACTURE_CONSERVATION_FAIL` (overlap_ratio 0.0078125 / 0.0195312 / 0.0351562 all `> 0.0001`), `observe_exit_code 1` with empty `observed_fragments`, and a third code bug — `NameError: name '_cut_both_sides' is not defined` (mother 105, event 2).

Event histograms show very few negatives: mother 100 → `{R2: 1}`; 101 → `{R2: 1, R1: 5}` (×2); 102/103/105 → `{R2: 1}`; 104 → `{R2: 1}`, `{R2: 1}`, `{R1: 1}`.

### Data-quality verdict for this store

`data/a12/reports/data_quality_data__a12_trainable__store.json`:

```json
"verdict": "not_trainable",
"trainable": false,
"counts": {"total": 114, "QA_PASS": 91, "QA_PENDING": 21, "QA_FAIL": 2, ...},
"first_cause": {"check_id": "semantics.mask_semantics",
                "detail": "33/65 assets record mask_semantics=coc_units_v2; observed values {'coc_units_v2': 33, '<missing>': 32}",
                "status": "FAIL"}
```

15 checks: **4 PASS, 4 FAIL, 6 MISSING, 1 NOT_APPLICABLE**. `honesty.relaxed_thresholds: []` and `missing_is_not_a_pass: true`.

`data/a12/reports/trainable_prereq_check.json` confirms the intent explicitly — `task`: *"produce a minimal trainable dataset (>=8 accepted lineages, each with >=1 encodable R2 and >=1 legal negative)"*. It also records that the ordinary single-event pipeline **cannot** emit a legal negative (R0 is implicit and never materialised; `synlab/relations/gallery.py:134-137`), and that negatives only reach a package via the multi-event library route.

### The only real training run in the repo

It lives beside the report, not in `a12_trainable`: `data/a12/reports/training_smoke.json` + `data/a12/reports/real_package_smoke_step3.pt`.

| item | value |
|---|---|
| schema / status | `synlab.training.smoke.v1` / **`PIPELINE_OK_DATA_INSUFFICIENT`** (`ok: true`) |
| package | `data/a12_exports/closed_loop/training_package` (closed_loop, 3.9 MB) |
| device / precision | **cpu**, **fp32**, torch `2.5.1+cpu`, cuda_available false |
| model | `a12.dual_tower.v1:dim64`, input_schema `a12.obs.v1`, temperature 0.1 |
| parameters | **total 72,710** (encoder 47,940 · pair_head 24,770 · head_group 26,882 · backbone_group 45,828) |
| optimizer steps | **3** |
| **loss sequence** | **[0.235010027885437, 0.23460811376571655, 0.23429083824157715]** |
| **grad norm sequence** | **[5.177638053894043, 5.487186431884766, 5.751092433929443]** |
| lr after step | 7.5e-5 → 2.5e-5 (decreasing) |
| loss weights | **rank 1.0**, contradiction 0.1, correspondence 0.1, view 0.1, quality 0.05 |
| per-task loss | quality **1.9800523e-4** (huber, delta 1.0, **mae 0.0131775**) · view **2.3417089** · contradiction/correspondence/rank **null (skipped)** |
| task coverage | `n_present {contradiction 0, correspondence 0, quality 3, rank 0, view 3}`; `skipped {contradiction 3, correspondence 3, rank 3}` |
| skip reasons | rank: **`no_legal_negative_in_exported_relations`** · correspondence: `correspondence_labels_never_reached_token_space` · contradiction: `no_encodable_contradiction_pair_candidate_side_unobserved` |
| batch | n_queries 3, n_candidates 1, positives 3, **negatives 0**, **effective_queries 0** |
| checkpoint | `real_package_smoke_step3.pt`, **537,658 B**, step 3 |
| checkpoint integrity | `load_is_bitwise_identical: true`; all 4 param digests equal (`sha256:cd165c2d4a79d687237d0439971e092749bebe5544890e8717d44563f025021d`); `parameters_checked: 37`, `mismatches: []` |
| reproducibility | `EXACT_SAMPLER_SEQUENCE_AND_STEP_CPU_FP32_SAME_PROCESS`; `extra_step_loss_equal: true`, `extra_step_loss_delta: 0.0` (live 0.23418079316616058 == resumed) |
| negative control | resume on a different dataset correctly refused with `REPLAY_MISMATCH` |
| checks | all 5 true: `batch_built, checkpoint_consistent, losses_finite, optimizer_steps_taken, package_files_verified` |
| honesty | `synthesised_labels: 0`, `synthesised_negatives: 0`; claim = pipeline exercised on real bytes, **no generalisation claim** |

**Verdict on `a12_trainable`:** it is a partially-successful **data-generation** store (4 of a target 10 lineages, `store/releases` empty, all 6 runs still `PENDING`), graded **`not_trainable`**. The repo's only executed training is a 3-step, CPU, 72,710-parameter **smoke test** on the 3.9 MB closed_loop package, in which the highest-weighted task (`rank`, w=1.0) received **zero** supervision because `relations.parquet` contains no legal negative. The pipeline is mechanically sound (bitwise-reproducible checkpoint, verified refusal control) — the blocker is data, not code.

---

## 9. Two verified export defects (numeric proof in `p5_defect_verify.out`)

### D1 — `tokens` is a rank-1 pseudo-broadcast of `token_input`

Writer `synlab/storage/export.py:262-274`:

```python
def _token_arrays(tile_rgb, tile_valid):
    vectors = [_tokens_from_view(tile_rgb[v]) for v in range(int(tile_rgb.shape[0]))]
    flat = np.concatenate(vectors) if vectors else np.zeros(0, dtype=np.float32)
    tokens = np.zeros((flat.size, TOKEN_DIM), dtype=np.float32)
    if flat.size:
        for k in range(TOKEN_DIM):
            tokens[:, k] = flat if k == 0 else flat * (1.0 - 1e-6 * k)   # <-- 255 scaled copies
```
Verified on every fragment of both packages:

```
tokens[:,0] == token_input              -> True
tokens == predicted scaled-copy matrix  -> True   (max abs diff 0.000e+00)
max |tokens[i,:] - tokens[i,0]| over rows -> 5.6e-05 .. 1.9e-04  (vs value magnitude ~0.04..0.36)
per-row variation across the 256 dims is ~1.0e-03 .. 1.6e-03 of the mean magnitude
singular values of centered tokens: top ~22..83,  2nd ~1e-5..5e-5,  rest ~0   (cond up to 1.9e10)
```

The `(N, 256)` token tensor therefore carries **exactly** the information of the 768-d block-mean RGB vector; 255 of its 256 columns are deterministic rescalings. Any model treating `tokens` as 256 informative features is consuming 1 real dimension plus 255 near-duplicates at float32 noise level. This also explains why `local_tokens [64,576,256]` (the largest tensor in the batch) is ~256× larger than the information it carries.

### D2 — `view_pos.npy` is identically zero

Covered in §4. 31/31 members all-zero; writer `export.py:461` silently defaults `u_position_mm` to `0.0`. The declared `"view_pos.npy (u position mm)"` channel carries no position data in either package.

### D3 (contextual) — `frame_id` and `token_view` are index counters

`frame_id = arange(N) % views` (`export.py:539`, verified exact) and `token_view = np.repeat(arange(n_views), blocks)` (`export.py:272`). Both are deterministic functions of position. Neither is a viewpoint, camera id, or coordinate frame.

These three findings are consistent with the encoded size evidence in §5 (`frame_id` chunks 34–323 B, `*_valid` chunks 19–26 B) and with the loader's own `token_pixel`/`token_retrieval` being left as all-`-1` sentinels.

---

## 10. What a consumer must know

1. **Both packages load** through one index-driven, shard-count-agnostic code path (`synlab/storage/export.py:1583` `TrainingPackage` + `synlab/qc/loader_probe.py`). No shard-count literals.
2. **The zarr store is real and complete** (28/3 groups, 328/18 chunks, 45,095,093 / 132,337 B) and byte-equal to npz — but **no reader opens it**. Geometry must come from `deploy/geometry/shard_*.npz`. Reading zarr would require writing a reader that does not exist.
3. **`deploy/deploy_index.json` is read by no loader** (only `synlab/qc/data_quality.py:1388`, a QC counter).
4. **`probe_training_package` defaults to `max_fragments=16`** and silently caps next_experiment at 16 queries / 64 fragments.
5. **There is no legal negative** in either `relations.parquet` (next_experiment `eligible_as_negative` False 150/150; closed_loop 3 rows, all R2). This is the measured cause of `effective_queries = 0` and of the skipped `rank` task.
6. **Only one side of each R2 pair is rendered** (closed_loop: 3 fragments with observation, 3 without; next_experiment: 16 with, 48 without), which is why every positive pair is rejected by `z_valid[candidate]==False`.
7. **`tokens` and `view_pos` should not be trusted as feature channels** (D1/D2); `frame_id`/`token_view` should not be treated as viewpoint identity (D3).
8. **The `u`/`view` task did train** (12 allowed, loss 2.3417, structural: null) despite D2 — i.e. the `view` task is supervised by view *count/index*, not by the position channel.
9. `data/a12_trainable` is **`not_trainable`** and its `store/releases` is empty; `a12_trainable/reports/batch_driver.json` is the real generation ledger (4/10 accepted).

---

### Files created by this census (all new, nothing modified)

`probe_train_export.md` (this file) · `p1_tree_index.py`/`.out` · `p1b_json_compact.py`/`.out` · `p2_parquet.py`/`.out` · `p3_arrays_zarr.py`/`.out` · `p4_obs_tar.py`/`.out` · `p5_defect_verify.py`/`.out` · `p6_trainable.py`/`.out` · `sub_loader_findings.md` · `sub_loader_shard_keys.py`
