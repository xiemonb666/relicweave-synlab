# LOADER investigation — the reader that consumes the exported training packages

Scope: `relicweave-synlab`. Read-only investigation. No existing file was modified.
Artifacts created under `data/a12/reports/modality_census/` only (`sub_loader_*`).

> **LINE-NUMBER CAVEAT (added at census close).** This investigation ran while another agent session was
> concurrently writing to the repo. Every line number was **re-verified after that edit**:
> `synlab/qc/loader_probe.py`, `synlab/training/{adapter,batch,smoke,labels}.py` and `synlab/qc/data_quality.py`
> were **unchanged**, so all citations to those files in the body below remain exact.
> **`synlab/storage/export.py` grew by ~136 lines**, so every `export.py:NNNN` citation in the body is the
> **pre-edit** value. Re-verified current values:
> `class TrainingPackage` **1583** (was 1447) · `._read_shard` **1672** (1536) · `.read_geometry` **1666** (1530) ·
> `.read_tokens` **1669** (1533) · `.read_observation` **1644** (1508) · `.observation_index` **1640** (1504) ·
> `.verify_files` **1605** (1469) · `.relations/.queries/.labels` **1619/1622/1625** (1483/1486/1489) ·
> `entry["shard"]` **1651** (1515) · `prefix = entry['opaque']` **1684** (1548) · `_zarr_root` **205** (unchanged) ·
> `_write_zarr` **1357** (1221) · `_zarr_declared_arrays` **1449** (1313) · writer shard f-strings
> **481/552/598** (365/436/482) · `ZARR_DIR_NAME` **77** (unchanged) · `_token_arrays` **262** /
> scaled-copy loop **269** / `token_view` **272** / `view_pos` default **461** / `frame_id` **539**.
> All **findings and verdicts** are unaffected — the three export defects were re-confirmed present post-edit.

Packages investigated:

| package | files | bytes (manifest `bytes_total`) | manifest `release_id` |
|---|---|---|---|
| `data/a12_exports/next_experiment/training_package` | 548 on disk / 547 in manifest | 1 446 947 245 | `rel_nexp_1790913735` |
| `data/a12_exports/closed_loop/training_package` | 56 on disk / 55 in manifest | 3 998 691 | `rel_852ab2a1e4c3_1790905541` |

(The `548`/`547` and `56`/`55` difference is `export_manifest.json` itself, which is not listed
inside its own `files` array — see `synlab/storage/export.py:640-649`.)

---

## 1. Grep hit list (`training_package|deploy_index|shard_|zarr`)

Command shape: ripgrep for `training_package|deploy_index|shard_|zarr` over the three requested
targets.

### 1a. `synlab\training\` — 5 hits, all in one file

| file:line | what it is |
|---|---|
| `synlab/training/smoke.py:4` | Module docstring: names `data/a12_exports/closed_loop/training_package` as the real package the smoke reads. |
| `synlab/training/smoke.py:62` | `DEFAULT_PACKAGE = Path("data/a12_exports/closed_loop/training_package")` — the smoke's default package. |
| `synlab/training/smoke.py:152` | Docstring of `load_real_inputs`: "The fragment-id set and the row split follow `qc.loader_probe.probe_training_package` exactly". |
| `synlab/training/smoke.py:349` | `from ..qc.loader_probe import probe_training_package` (inside `run_smoke`, `include_loader_probe` branch). |
| `synlab/training/smoke.py:351` | `probe = probe_training_package(package_dir)` — nests the probe report inside the smoke report. |

**Notable negative result:** nothing else in `synlab/training/` mentions `training_package`,
`deploy_index`, `shard_`, or `zarr`. In particular `synlab/training/adapter.py`,
`batch.py`, `labels.py`, `sampler.py`, `trainer.py`, `model.py`, `losses.py`, `supervision.py`
contain **zero** shard-path literals and **zero** zarr references. The whole training stack
receives already-materialised arrays.

### 1b. `synlab\storage\export.py` — 53 hits (writer-side, plus one reader class)

| file:line | what it is |
|---|---|
| `synlab/storage/export.py:10` | Module docstring naming `export_training_package`. |
| `synlab/storage/export.py:63` | `PACKAGE_SCHEMA = "synlab.training_package.v1"`. |
| `synlab/storage/export.py:64` | `PACKAGE_MANIFEST_SCHEMA = "synlab.training_package_manifest.v1"`. |
| `synlab/storage/export.py:71` | Comment: formats `export_training_package` can materialise. |
| `synlab/storage/export.py:72` | `TRAINING_FORMATS = ("parquet", "npz", "zarr", "tar")`. |
| `synlab/storage/export.py:74-75` | Comment: directory inside a view holding the zarr replica. |
| `synlab/storage/export.py:77` | `ZARR_DIR_NAME = "zarr"`. |
| `synlab/storage/export.py:100` | Docstring pointer to `export_training_package`. |
| `synlab/storage/export.py:205` | `def _zarr_root(view_root: Path) -> Path:` — the single place that decides the zarr path. |
| `synlab/storage/export.py:206-210` | Docstring/comment: writer and manifest scanner disagreed (`<view>/geometry/zarr` vs `<view>/zarr`), so every zarr file stayed out of the manifest; both now use this function. |
| `synlab/storage/export.py:278` | Section banner `# export_training_package`. |
| `synlab/storage/export.py:280-281` | `def export_training_package(store, release_id, out_dir, *, formats=("parquet","npz","zarr","tar"))`. |
| `synlab/storage/export.py:298` | `stage="export.export_training_package"`. |
| `synlab/storage/export.py:363-365` | ObsPack sharding: `_shard(...)` then `name = f"obs/shard_{index:04d}.tar"`. |
| `synlab/storage/export.py:407` | Comment: geometry npz + tar shards, zarr replica. |
| `synlab/storage/export.py:436` | `name = f"geometry/shard_{index:04d}.npz"`. |
| `synlab/storage/export.py:461-470` | zarr write block: `if geometry_by_fragment and "zarr" in formats:` → `_write_zarr(zarr_root, ...)`, `counts["zarr_arrays"]`, `counts["zarr_files"]`, `_record(..., note="zarr replica of the geometry shards")`. |
| `synlab/storage/export.py:482` | `name = f"tokens/shard_{index:04d}.npz"`. |
| `synlab/storage/export.py:639-649` | `deploy_index = deploy_root / "deploy_index.json"`; writes `{"schema": "synlab.deploy_index.v1", ...}`; `_record(files, deploy_index, out)`. |
| `synlab/storage/export.py:714` | `stage="export.export_training_package"`. |
| `synlab/storage/export.py:1221-1236` | `def _write_zarr(store_root, geometry)`; `import zarr`; `zarr.open_group(...)`; `group.attrs["schema"] = "synlab.geometry.zarr.v1"`. |
| `synlab/storage/export.py:1253-1257` | `STORAGE_METADATA_NAMES` frozenset (`zarr.json`, `.zarray`, `.zattrs`, `.zgroup`, ...). |
| `synlab/storage/export.py:1313-1316` | `def _zarr_declared_arrays(zarr_root)`; reads `root / "zarr.json"`. |
| `synlab/storage/export.py:1334` | Comment: npz archives its array names, "a zarr ...". |
| `synlab/storage/export.py:1350` | Skip reason `"(zarr chunk/compression vocabulary)"`. |
| `synlab/storage/export.py:1359` | `declared = _zarr_declared_arrays(_zarr_root(root))` — manifest scanning side. |
| `synlab/storage/export.py:1448` | `class TrainingPackage:` docstring — "**Reader** for a package written by `export_training_package`." |
| `synlab/storage/export.py:1556` | `__all__` exports `export_training_package`, `TrainingPackage`. |

### 1c. `synlab\qc\loader_probe.py` — 2 hits

| file:line | what it is |
|---|---|
| `synlab/qc/loader_probe.py:262` | `def probe_training_package(package_dir, *, max_fragments=16, out_path=None, token_budget=None)`. |
| `synlab/qc/loader_probe.py:527` | `__all__` includes `probe_training_package`. |

**Notable negative result:** the string literal `training_package` occurs in `loader_probe.py`
**only** inside the function name. The file contains **no** `deploy_index` reference, **no**
`shard_` literal, and **no** `zarr` reference anywhere.

### 1d. Bonus grep: `zarr|deploy_index` over the whole `synlab\` package

| file:line | what it is |
|---|---|
| `synlab/doctor.py:48` | `OPTIONAL_IMPORTS = (..., "zarr", ...)` — dependency check only. |
| `synlab/doctor.py:373-384` | `import zarr`; writes a throwaway `tokens.zarr` in a temp dir to prove the zarr dependency loads. Write-side self-test, not a package reader. |
| `synlab/storage/export.py` | (all hits already listed in 1b — writer + manifest scanner.) |
| `synlab/qc/data_quality.py:1388` | `deploy = package / "deploy" / "deploy_index.json"` — **the only place in the repo that reads `deploy_index.json`**, and it is a QC data-quality counter, *not* the loader. |
| `synlab/qc/data_quality.py:1428` | `"deploy_index_rows": len(index)`. |

So: **`deploy/deploy_index.json` is never read by the loader.**

---

## 2. Loader functions and the exact tensors they yield

### 2a. Function inventory (definition lines)

| function / class | file:line | role |
|---|---|---|
| `class TrainingPackage` | `synlab/storage/export.py:1447` | The package reader (shard/index/manifest access). |
| `TrainingPackage.__init__` | `synlab/storage/export.py:1450` | Loads + hash-verifies `export_manifest.json`. |
| `TrainingPackage.verify_files` | `synlab/storage/export.py:1469` | Re-hashes every manifest entry. |
| `TrainingPackage.relations` | `synlab/storage/export.py:1483` | Reads `research/relations.parquet`. |
| `TrainingPackage.queries` | `synlab/storage/export.py:1486` | Reads `deploy/queries.parquet`. |
| `TrainingPackage.labels` | `synlab/storage/export.py:1489` | Reads `research/labels/<layer>.parquet`. |
| `TrainingPackage._table` | `synlab/storage/export.py:1494` | parquet-or-json table reader. |
| `TrainingPackage.observation_index` | `synlab/storage/export.py:1504` | Reads `deploy/obs/index.json`. |
| `TrainingPackage.read_observation` | `synlab/storage/export.py:1508` | Reads `deploy/obs/shard_*.tar` members. |
| `TrainingPackage.read_geometry` | `synlab/storage/export.py:1530` | → `_read_shard("geometry/index.json", ...)`. |
| `TrainingPackage.read_tokens` | `synlab/storage/export.py:1533` | → `_read_shard("tokens/index.json", ...)`. |
| `TrainingPackage._read_shard` | `synlab/storage/export.py:1536` | Reads one fragment out of the `.npz`. |
| `class ExportedRelationPool` | `synlab/qc/loader_probe.py:61` | Frozen-pool adapter over the exported relation table. |
| `load_features` | `synlab/qc/loader_probe.py:171` | Assembles the `a12.obs.v1` payload per fragment. |
| `_absent_payload` | `synlab/qc/loader_probe.py:191` | Payload for a modelled-but-unobserved fragment. |
| `_observed_payload` | `synlab/qc/loader_probe.py:218` | Payload for an observed fragment. |
| `probe_training_package` | `synlab/qc/loader_probe.py:262` | The probe: package → payloads → bundle → batch → audit. |
| `FeatureBundle.from_dict` | `synlab/training/adapter.py:360` | Payloads → padded feature batch. |
| `FeatureBundle.check_shapes` | `synlab/training/adapter.py:474` | Shape/dtype assertions on the bundle. |
| `build_training_batch` | `synlab/training/batch.py:253` | Bundle + rows + pool → `TrainingBatch`. |
| `load_real_inputs` | `synlab/training/smoke.py:148` | Same read path, for the training smoke. |
| `PackageLabelSource.from_package` | `synlab/training/labels.py:70` | Reads `labels("quality")` / `labels("correspondence")` (the extra closed-loop layers). |

### 2b. The read path, with the key lines

`TrainingPackage.__init__` requires exactly one file and validates its own hash:

```
1450:    def __init__(self, root: str | Path):
1451:        self.root = Path(root)
1452:        manifest_path = self.root / "export_manifest.json"
1453:        if not manifest_path.exists():
1454:            raise SynLabError(ErrorCode.INPUT_UNAVAILABLE,
1455:                              f"training package manifest not found: {manifest_path}",
1456:                              stage="export.TrainingPackage")
1457:        self.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
1458:        stored = self.manifest.get("manifest_hash")
1459:        recomputed = hash_json({k: v for k, v in self.manifest.items()
1460:                                if k != "manifest_hash"})
1461:        if stored != recomputed:
1462:            raise SynLabError(ErrorCode.ASSET_HASH_MISMATCH,
1463:                              "training package manifest was modified after export",
1464:                              stage="export.TrainingPackage")
1465:        self.deploy = self.root / VIEW_DEPLOY
1466:        self.research = self.root / VIEW_RESEARCH
```

Observation index — **optional**, missing index degrades to "no observed rows":

```
1504:    def observation_index(self) -> dict[str, Any]:
1505:        path = self.deploy / "obs" / "index.json"
1506:        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"rows": {}}
```

Observation read — dispatch by the index's own `shard` string, **no shard-name literal**:

```
1515:        shard = self.deploy / entry["shard"]
1516:        with tarfile.open(shard, "r") as tar:
1517:            out = {}
1518:            for suffix, key, dtype in (("tiles.npy", "rgb", np.uint8),
1519:                                       ("valid.npy", "valid", bool),
1520:                                       ("view_pos.npy", "view_pos", np.float32)):
1521:                member = tar.extractfile(f"{entry['opaque']}/{suffix}")
...
1526:                out[key] = np.load(io.BytesIO(member.read()), allow_pickle=False).astype(dtype)
```

Geometry/token read — one generic `_read_shard`, array names come from the npz itself:

```
1536:    def _read_shard(self, index_rel: str, root: Path, fragment_id: str) -> dict[str, np.ndarray]:
1537:        path = root / index_rel
...
1541:        index = json.loads(path.read_text(encoding="utf-8"))
1542:        entry = (index.get("rows") or {}).get(fragment_id)
...
1547:        with np.load(root / entry["shard"], allow_pickle=False) as data:
1548:            prefix = f"{entry['opaque']}__"
1549:            return {k[len(prefix):]: data[k] for k in data.files if k.startswith(prefix)}
```

Payload assembly per fragment (`_observed_payload`) — this is where the tensors are born:

```
218: def _observed_payload(package: TrainingPackage, fragment_id: str, *,
219:                       token_budget: int | None) -> dict[str, Any]:
220:     obs = package.read_observation(fragment_id)
221:     geometry = package.read_geometry(fragment_id)
222:     tokens = package.read_tokens(fragment_id)
223:     rgb = np.asarray(obs["rgb"], dtype=np.uint8)
224:     valid = np.asarray(obs["valid"], dtype=bool)
225:     if rgb.max(initial=0) > 1:
226:         rgb_f = rgb.astype(np.float32) / 255.0
227:     else:
228:         rgb_f = rgb.astype(np.float32)
229:     n_tokens = int(np.asarray(tokens["tokens"]).shape[0])
230:     payload = {
231:         "schema": FEATURE_SCHEMA,
232:         "global_rgb": np.transpose(rgb_f, (0, 3, 1, 2)),          # [V,3,H,W]
233:         "global_valid": np.asarray([bool(v.any()) for v in valid], dtype=bool),
234:         "pixel_valid": valid,
235:         "points": np.asarray(geometry["points"], dtype=np.float32),
236:         "point_valid": np.asarray(geometry["point_valid"], dtype=bool),
237:         "normals": np.asarray(geometry["normals"], dtype=np.float32),
238:         "normal_valid": np.asarray(geometry["normal_valid"], dtype=bool),
239:         "local_tokens": np.asarray(tokens["tokens"], dtype=np.float32),
240:         "token_valid": np.asarray(tokens["token_valid"], dtype=bool),
241:         "token_view": np.asarray(tokens["token_view"], dtype=np.int32),
242:         "token_modality": np.zeros(n_tokens, dtype=np.int32),
243:         "token_source": np.zeros(n_tokens, dtype=np.int32),
244:         "tokens_total": np.int32(n_tokens),
245:         "quality": np.zeros((1, 1), dtype=np.float32),
246:         "quality_valid": np.zeros((1, 1), dtype=bool),
247:         "presence": np.zeros((1,), dtype=np.float32),
248:         "presence_valid": np.zeros((1,), dtype=bool),
249:         "scale_valid": bool(np.asarray(geometry["scale_valid"], dtype=bool).any()),
250:         "obs_version": np.int32(1),
251:         "token_budget": int(token_budget or n_tokens),
252:     }
```

Leak guard (payload may never carry a label field):

```
253:     leaked = sorted(FORBIDDEN_PAYLOAD_KEYS.intersection(payload.keys()))
254:     if leaked:
255:         raise SynLabError(ErrorCode.LEAKAGE_DETECTED,
256:                           f"loader payload {fragment_id} carries {leaked}",
257:                           stage="qc.loader_probe.load_features",
258:                           evidence_refs=leaked)
```

Filling the padded batch (`FeatureBundle.from_dict`, `synlab/training/adapter.py:406-428`):

```
408:             global_rgb=np.zeros((f, n_views, 3, height, width), dtype=np.float32),
409:             global_valid=np.zeros((f, n_views), dtype=bool),
410:             pixel_valid=np.zeros((f, n_views, height, width), dtype=bool),
411:             local_tokens=np.zeros((f, max_tokens, TOKEN_DIM), dtype=np.float32),
412:             token_valid=np.zeros((f, max_tokens), dtype=bool),
413:             token_view=np.full((f, max_tokens), -1, dtype=np.int32),
414:             token_pixel=np.full((f, max_tokens, 2), -1, dtype=np.int32),
415:             token_modality=np.full((f, max_tokens), -1, dtype=np.int32),
416:             token_source=np.full((f, max_tokens), -1, dtype=np.int32),
417:             token_retrieval=np.full((f, max_tokens), -1, dtype=np.int32),
418:             tokens_total=np.zeros((f,), dtype=np.int32),
419:             points=np.zeros((f, max_points, 3), dtype=np.float32),
420:             point_valid=np.zeros((f, max_points), dtype=bool),
421:             normals=np.zeros((f, max_points, 3), dtype=np.float32),
422:             normal_valid=np.zeros((f, max_points), dtype=bool),
423:             quality=np.zeros((f, n_regions, c_quality), dtype=np.float32),
424:             quality_valid=np.zeros((f, n_regions, c_quality), dtype=bool),
425:             presence=np.zeros((f, c_presence), dtype=np.float32),
426:             presence_valid=np.zeros((f, c_presence), dtype=bool),
427:             scale_valid=np.zeros((f,), dtype=bool),
428:             obs_version=np.zeros((f,), dtype=np.int32),
```

Batch tensors (`synlab/training/batch.py:293-304`, `375`, `390`, `395-396`, `424-430`):

```
293:     pair_index = np.zeros((q, c, 2), dtype=np.int64)
294:     pair_valid = np.zeros((q, c), dtype=bool)
295:     labels_relation = np.full((q, c), RELATION_UNKNOWN_CODE, dtype=np.int8)
296:     label_pair_valid = np.zeros((q, c), dtype=bool)
297:     pos_mask = np.zeros((q, c), dtype=bool)
298:     neg_mask = np.zeros((q, c), dtype=bool)
299:     excluded_mask = np.zeros((q, c), dtype=bool)
300:     exclusion_reason = np.full((q, c), EXCLUSION_NONE, dtype=np.int8)
301:     negative_is_r2_history = np.zeros((q, c), dtype=bool)
302:     r1_fallback_used = np.zeros((q, c), dtype=bool)
303:     sample_keys = np.array([str(r.get("sample_key", f"q{i:04d}")) for i, r in enumerate(rows)],
304:                            dtype="U64")
...
375:     quality_tier_arr = np.zeros(f, dtype=np.int8)
390:     corr_kind = np.full((f, features.token_budget), 0, dtype=np.int8)
395:     cont = np.full((q, c), CONTRADICTION_MISSING, dtype=np.int8)
396:     cont_valid = np.zeros((q, c), dtype=bool)
424:         quality_target=np.asarray(quality_target, dtype=np.float32),
425:         quality_target_valid=np.asarray(quality_target_valid, dtype=bool),
```
`corr_weight / corr_row_valid / corr_col_valid` are built in `_corr_tensors`
(`synlab/training/batch.py:618-625`): `k = max(int(token_budget), 1)`,
`weight = np.zeros((q, c, k), dtype=np.float32)`, `row_valid/col_valid = np.zeros((q, c, k), dtype=bool)`.
`lineage_cluster` is `np.zeros(len(fragment_ids), dtype=np.int64)` (`synlab/training/batch.py:235`).

### 2c. Exact yielded tensor table

Symbols: `F` = fragments in the bundle, `V` = views, `H`/`W` = tile height/width,
`L` = token budget (`max_tokens`), `N` = max points across fragments, `R` = regions,
`Cq` = quality channels, `Cm` = presence channels, `Q` = batch query rows, `C` = candidate slots,
`K` = `token_budget`.

**Stage A — `load_features` / `_observed_payload` output (one dict per fragment, raw NumPy, no padding)**

Verified against the real shards with `sub_loader_shard_keys.py` (see §5b).

| field | next_experiment (fragment `LIN0000_V10_M11_PAT15_E01-p`) | closed_loop (fragment `LIN0000_V01_M01_PAT01_E01-m`) | dtype | source line |
|---|---|---|---|---|
| `schema` | `"a12.obs.v1"` | `"a12.obs.v1"` | `str` | `loader_probe.py:231` |
| `global_rgb` | `(12, 3, 768, 1024)` | `(4, 3, 192, 256)` | `float32` | `loader_probe.py:232` |
| `global_valid` | `(12,)` | `(4,)` | `bool` | `loader_probe.py:233` |
| `pixel_valid` | `(12, 768, 1024)` | `(4, 192, 256)` | `bool` | `loader_probe.py:234` |
| `points` | `(89082, 3)` | `(1306, 3)` | `float32` | `loader_probe.py:235` |
| `point_valid` | `(89082,)` | `(1306,)` | `bool` | `loader_probe.py:236` |
| `normals` | `(89082, 3)` | `(1306, 3)` | `float32` | `loader_probe.py:237` |
| `normal_valid` | `(89082,)` | `(1306,)` | `bool` | `loader_probe.py:238` |
| `local_tokens` | `(576, 256)` | `(192, 256)` | `float32` | `loader_probe.py:239` |
| `token_valid` | `(576,)` | `(192,)` | `bool` | `loader_probe.py:240` |
| `token_view` | `(576,)` | `(192,)` | `int32` | `loader_probe.py:241` |
| `token_modality` | `(576,)` all `0` | `(192,)` all `0` | `int32` | `loader_probe.py:242` |
| `token_source` | `(576,)` all `0` | `(192,)` all `0` | `int32` | `loader_probe.py:243` |
| `tokens_total` | `np.int32(576)` | `np.int32(192)` | `int32` scalar | `loader_probe.py:244` |
| `quality` | `(1, 1)` zeros | `(1, 1)` zeros | `float32` | `loader_probe.py:245` |
| `quality_valid` | `(1, 1)` zeros | `(1, 1)` zeros | `bool` | `loader_probe.py:246` |
| `presence` | `(1,)` zeros | `(1,)` zeros | `float32` | `loader_probe.py:247` |
| `presence_valid` | `(1,)` zeros | `(1,)` zeros | `bool` | `loader_probe.py:248` |
| `scale_valid` | `bool` | `bool` | `bool` scalar | `loader_probe.py:249` |
| `obs_version` | `np.int32(1)` | `np.int32(1)` | `int32` scalar | `loader_probe.py:250` |
| `token_budget` | `576` | `192` | `int` | `loader_probe.py:251` |

The **absent** variant (`_absent_payload`, `loader_probe.py:191-215`) yields the same key set with
every mask `False`, `points (0,3)`, `normals (0,3)`, `local_tokens (0,256)`,
`tokens_total = np.int32(0)`, `obs_version = np.int32(0)`, `scale_valid = False`.

Geometry arrays actually present in the npz per fragment (verified): `points (N,3) float32`,
`normals (N,3) float32`, `point_valid (N,) bool`, `normal_valid (N,) bool`,
`scale_valid (N,) bool`, `frame_id (N,) int32`. **`frame_id` is loaded by `_read_shard` but never
consumed by `_observed_payload`.** Token npz per fragment also carries `tile_valid (V,H,W) bool`
and `token_input (L,) float32`, which the loader likewise never reads.

**Stage B — `FeatureBundle` (the feature batch, `FeatureBundle.from_dict`, adapter.py:406-428)**

Real `next_experiment` shapes from `data/a12/reports/loader_probe_summary.json:118-172`
(F = 64, V = 12, H = 768, W = 1024, L = 576, N = 217855, R = 1, Cq = 1, Cm = 1);
real `closed_loop` shapes from `data/a12_exports/_scratch/numbers.txt:49`
(F = 6, V = 4, H = 192, W = 256, L = 192, N = 4158, R = 1, Cq = 1, Cm = 1).

| field | shape (symbolic) | next_experiment (real) | closed_loop (real) | dtype |
|---|---|---|---|---|
| `fragment_ids` | `list[str]` len F | 64 | 6 | `str` list |
| `global_rgb` | `[F,V,3,H,W]` | `[64,12,3,768,1024]` | `[6,4,3,192,256]` | `float32` |
| `global_valid` | `[F,V]` | `[64,12]` | `[6,4]` | `bool` |
| `pixel_valid` | `[F,V,H,W]` | `[64,12,768,1024]` | `[6,4,192,256]` | `bool` |
| `local_tokens` | `[F,L,256]` | `[64,576,256]` | `[6,192,256]` | `float32` |
| `token_valid` | `[F,L]` | `[64,576]` | `[6,192]` | `bool` |
| `token_view` | `[F,L]` | `[64,576]` | `[6,192]` | `int32` |
| `token_pixel` | `[F,L,2]` (all `-1`; loader never fills it) | `[64,576,2]` | `[6,192,2]` | `int32` |
| `token_modality` | `[F,L]` | `[64,576]` | `[6,192]` | `int32` |
| `token_source` | `[F,L]` | `[64,576]` | `[6,192]` | `int32` |
| `token_retrieval` | `[F,L]` (all `-1`) | `[64,576]` | `[6,192]` | `int32` |
| `tokens_total` | `[F]` | `[64]` | `[6]` | `int32` |
| `points` | `[F,N,3]` | `[64,217855,3]` | `[6,4158,3]` | `float32` |
| `point_valid` | `[F,N]` | `[64,217855]` | `[6,4158]` | `bool` |
| `normals` | `[F,N,3]` | `[64,217855,3]` | `[6,4158,3]` | `float32` |
| `normal_valid` | `[F,N]` | `[64,217855]` | `[6,4158]` | `bool` |
| `quality` | `[F,R,Cq]` | `[64,1,1]` | `[6,1,1]` | `float32` |
| `quality_valid` | `[F,R,Cq]` | `[64,1,1]` | `[6,1,1]` | `bool` |
| `presence` | `[F,Cm]` | `[64,1]` | `[6,1]` | `float32` |
| `presence_valid` | `[F,Cm]` | `[64,1]` | `[6,1]` | `bool` |
| `scale_valid` | `[F]` | `[64]` | `[6]` | `bool` |
| `obs_version` | `[F]` | `[64]` | `[6]` | `int32` |

`check_shapes` (`adapter.py:474-517`) asserts exactly these prefixes (lines 477-498) and that
`global_valid, pixel_valid, token_valid, point_valid, normal_valid, quality_valid, presence_valid,
scale_valid` are `np.bool_` (lines 506-510).

Torch-side dtypes applied by `FeatureBundle.to_torch` (`adapter.py:523-531`): all float fields →
`torch.float32`; all `*_valid` → `torch.bool`; `token_view, token_pixel, token_modality,
token_source, token_retrieval, tokens_total, obs_version` → `torch.int64` (i.e. `int32` NumPy →
`int64` torch).

**Stage C — `TrainingBatch` label side (`build_training_batch`, batch.py:253)**

Real `next_experiment` shapes from `data/a12/reports/loader_probe_summary.json:28-116`
(Q = 36, C = 1, F = 64, K = 576); real `closed_loop` shapes from
`data/a12/reports/training_smoke_summary.txt:22` (Q = 3, C = 1, F = 6, K = 192).

| field | shape (symbolic) | next_experiment (real) | closed_loop (real) | dtype | line |
|---|---|---|---|---|---|
| `pair_index` | `[Q,C,2]` | `[36,1,2]` | `[3,1,2]` | `int64` | `batch.py:293` |
| `pair_valid` | `[Q,C]` | `[36,1]` | `[3,1]` | `bool` | `batch.py:294` |
| `labels_relation` | `[Q,C]` | `[36,1]` | `[3,1]` | `int8` | `batch.py:295` |
| `label_pair_valid` | `[Q,C]` | (not reported by the probe) | `[3,1]` | `bool` | `batch.py:296` |
| `pos_mask` | `[Q,C]` | `[36,1]` | `[3,1]` | `bool` | `batch.py:297` |
| `neg_mask` | `[Q,C]` | `[36,1]` | `[3,1]` | `bool` | `batch.py:298` |
| `excluded_mask` | `[Q,C]` | `[36,1]` | `[3,1]` | `bool` | `batch.py:299` |
| `exclusion_reason` | `[Q,C]` | `[36,1]` | `[3,1]` | `int8` | `batch.py:300` |
| `negative_is_r2_history` | `[Q,C]` must be all False | — | — | `bool` | `batch.py:301` |
| `r1_fallback_used` | `[Q,C]` | — | `[3,1]` | `bool` | `batch.py:302` |
| `sample_keys` | `[Q]` | `[36]` | `[3]` | `<U64` (NumPy unicode) | `batch.py:303-304` |
| `quality_target` | `[F,R,Cq]` | `[64,1,1]` | `[6,1,1]` | `float32` | `batch.py:424` |
| `quality_target_valid` | `[F,R,Cq]` | — | `[6,1,1]` | `bool` | `batch.py:425` |
| `corr_weight` | `[Q,C,K]` | `[36,1,576]` | `[3,1,192]` | `float32` | `batch.py:623` |
| `corr_row_valid` | `[Q,C,K]` | — | `[3,1,192]` | `bool` | `batch.py:624` |
| `corr_col_valid` | `[Q,C,K]` | — | `[3,1,192]` | `bool` | `batch.py:625` |
| `corr_kind` | `[F,L]` | — | `[6,192]` | `int8` | `batch.py:390` |
| `contradiction` | `[Q,C]` | `[36,1]` | `[3,1]` | `int8` | `batch.py:395` |
| `contradiction_valid` | `[Q,C]` | — | `[3,1]` | `bool` | `batch.py:396` |
| `quality_tier` | `[F]` | `[64]` | `[6]` | `int8` | `batch.py:375` |
| `lineage_cluster` | `[F]` | `[64]` | `[6]` | `int64` | `batch.py:235` |
| `pool_id` | `str` | `"exported"` | `"exported"` | `str` | `batch.py:431` |

Batch row split, `next_experiment` (real, `loader_probe_summary.json:84-89`):
`n_queries = 36`, `n_candidates = 1`, `positives = 12`, `negatives = 0`, `excluded = 24`,
`effective_queries = 0`.
Batch row split, `closed_loop` (real, `training_smoke_summary.txt:20`):
`n_queries = 3`, `n_candidates = 1`, `positives = 3`, `negatives = 0`, `effective_queries = 0`.

---

## 3. Verdicts

### 3a. Both packages? — **YES, the loader reads BOTH.** One code path, no shard-count assumption.

Evidence:

1. **No shard-count assumption anywhere in the reader.** `TrainingPackage._read_shard`
   (`export.py:1536-1549`) reads the shard *name out of the index* (`entry["shard"]`, line 1547) and
   the array prefix out of the index (`entry["opaque"]`, line 1548). `read_observation`
   (`export.py:1508-1527`) likewise uses `entry["shard"]` (line 1515) and `entry["opaque"]`
   (line 1521). Neither function lists, globs, or counts shard files.
2. `grep` for `glob|iterdir|rglob|== 4|0000` inside `synlab/qc/loader_probe.py` returns **no**
   shard-enumeration or shard-count code (only `len(...)` over relations/queries/rows).
3. `grep` for `0000` inside `synlab/storage/export.py` hits only the **writer** f-strings
   (`export.py:365`, `436`, `482` — `f"obs/shard_{index:04d}.tar"` etc.), never the reader.
4. **Required vs optional files.** Hard-required: `export_manifest.json`
   (`export.py:1452-1456`) and each per-fragment entry must appear in `deploy/geometry/index.json`
   / `deploy/tokens/index.json` (`export.py:1538-1546`). Soft/optional:
   `deploy/obs/index.json` (missing → `{"rows": {}}`, `export.py:1504-1506`, so all fragments
   degrade to `_absent_payload`), `deploy/queries.parquet` and `research/relations.parquet`
   (`_table` returns `[]` when neither the parquet nor its json fallback exists,
   `export.py:1494-1501`), and `research/labels/<layer>.parquet` (`labels()` + `_table`, same
   fallback). `PackageLabelSource.from_package` (`labels.py:70`) reads the `quality` and
   `correspondence` layers (`labels.py:44-45`) and simply yields empty maps when they are absent.
5. **Both real packages satisfy the required set.** Verified on disk: both contain
   `export_manifest.json`, `deploy/obs/index.json`, `deploy/geometry/index.json`,
   `deploy/tokens/index.json`, `deploy/queries.parquet`, `research/relations.parquet`.

Real index evidence of the asymmetry the loader absorbs without complaint:

| index | next_experiment | closed_loop |
|---|---|---|
| `deploy/obs/index.json` → `rows` | 28 rows, shards `obs/shard_0000..0003.tar` | 3 rows, shard `obs/shard_0000.tar` |
| `deploy/geometry/index.json` → `rows` | 28 rows, shards `geometry/shard_0000..0003.npz` | 3 rows, shard `geometry/shard_0000.npz` |
| `deploy/tokens/index.json` → `rows` | 28 rows, shards `tokens/shard_0000..0003.npz` | 3 rows, shard `tokens/shard_0000.npz` |
| `counts.zarr_files` in manifest | 525 | 40 |
| `counts.label_layers` in manifest | 3 (`clean`,`physical`,`visible`) | 5 (+`correspondence`,`quality`) |
| `counts.relations` / `relation_kinds` | 150 (`R1`:117, `R2`:33) | 3 (`R2`:3) |

Both are read by the same functions. **Confirmed by real artifacts:** the probe has PASSed on both
— `next_experiment` in `data/a12/reports/next_experiment/loader_probe.out` (`files_checked: 547`,
`ok: true`) and `closed_loop` in `data/a12/reports/training_smoke.json:1094-1190`
(`files_ok: true`, `ok: true`, `files_checked: 55`).

**One real caveat, and it is a limitation of the *probe*, not of the loader:**
`probe_training_package` defaults to `max_fragments: int = 16` (`loader_probe.py:262`) and truncates
the query-derived fragment list at `loader_probe.py:323`:
`fragment_ids = [f for f in dict.fromkeys(fragment_ids) if f][: int(max_fragments)]`. On
`next_experiment` (86 queries) this caps the batch scope at 16 queries (→ 64 fragments after
candidates are appended, `batch_fragments: 64` in `loader_probe_summary.json:27`), whereas
`closed_loop` (6 queries) is unaffected (`batch_fragments: 6`). The **loader** (`TrainingPackage`,
`load_features`) has no such cap; `synlab/training/smoke.py:160-164` deliberately omits the
truncation (`smoke.py:161` has no `[:max_fragments]`).

A second real caveat: `probe_training_package`'s own JSON dump fails on the 1447 MB package.
`tools/loader_probe_run.py:3-7` states: *"``qc.loader_probe.probe_training_package`` builds its full
report and then writes it with ``json.dumps``; on this package that allocation raises
``MemoryError`` after the probe has already done its work"*. The on-disk
`data/a12/reports/loader_probe.json` is therefore **0 bytes** (§4).

### 3b. Does the loader read `deploy\zarr\`? — **NO. Nothing in the loader path touches zarr.**

- `grep zarr` in `synlab/qc/loader_probe.py` → **0 hits**.
- `grep zarr` in `synlab/training/` → **0 hits**.
- `grep zarr` in `synlab/storage/export.py` → hits only the *writer*
  (`_zarr_root:205`, `_write_zarr:1221`, write call `:461-470`) and the *manifest scanner*
  (`_zarr_declared_arrays:1313`, `_zarr_root` use at `:1359`), i.e. code that produces or verifies
  the manifest, not code that loads a package.
- `class TrainingPackage` (`export.py:1447-1549`) never composes a zarr path. Its only path
  composition is `self.root / "export_manifest.json"` (`:1452`), `self.deploy / "obs" / "index.json"`
  (`:1505`), `self.deploy / entry["shard"]` (`:1515`), `root / index_rel` (`:1537`),
  `root / entry["shard"]` (`:1547`), `self.research / "relations.parquet"` (`:1484`),
  `self.deploy / "queries.parquet"` (`:1487`), `self.research / "labels" / f"{layer}.parquet"` (`:1490`).
- `ZARR_DIR_NAME = "zarr"` (`export.py:77`) is exported in `__all__` (`export.py:1555`) but is
  referenced by **no reader**.
- Repo-wide, the only `zarr` consumer outside `export.py` is `synlab/doctor.py:373-384`, which
  *creates* a temp store to smoke-test the dependency.

**Consequence:** the 525 zarr files in `next_experiment` (and 40 in `closed_loop`) are pure
manifest payload — they are hash-verified by `TrainingPackage.verify_files` (`export.py:1469-1480`)
but never parsed. Deleting them would change `verify_files` from `ok: true` to "missing" entries and
nothing else in the loader would notice. The geometry the loader *does* use comes from
`deploy/geometry/shard_*.npz` via `deploy/geometry/index.json`.

---

## 4. Real loader probe artifacts (verbatim)

### 4a. Artifact inventory found

| path | bytes | what it is |
|---|---|---|
| `data/a12_exports/_scratch/loop_loader.out` | 314 | closed-loop run: `--step loader_probe` stdout. |
| `data/a12_exports/_scratch/loop_loader.err` | 0 | (empty) |
| `data/a12_exports/_scratch/loop_loader2.out` | 314 | re-run stdout. |
| `data/a12_exports/_scratch/loop_loader2.err` | 0 | (empty) |
| `data/a12_exports/_scratch/loader2_check.txt` | 419 | compact probe summary of an **earlier** closed_loop package. |
| `data/a12\reports\closed_loop_loader_after_fix.txt` | 314 | same closed-loop line after a fix. |
| `data/a12\reports\loader_probe.json` | **0** | the canonical probe report path — **empty file** (the MemoryError dump failure, §3a). |
| `data/a12\reports\loader_probe_summary.json` | 4978 | bounded summary of the `next_experiment` probe. |
| `data/a12\reports\next_experiment\loader_probe.out` | 5286 | same summary printed by `tools/loader_probe_run.py`. |
| `data/a12\reports\next_experiment\loader_probe.err` | 0 | (empty) |
| `data/a12\reports\training_smoke.json` | — | `loader_probe` sub-report for `closed_loop` (lines 1094-1191). |
| `data/a12\reports\training_smoke_summary.txt` | — | human summary incl. `loader_probe.*` lines 84-86. |
| `data/a12_exports/_scratch/numbers.txt` | — | captured the **full content** of the now-empty `loader_probe.json` (line 49). |
| `data/a12\reports\release_freeze_after_feature_leak_repair.json` | — | evidence-manifest metrics of an earlier `loader_probe.json` (lines 280-324). |

### 4b. `next_experiment` — `data/a12/reports/loader_probe_summary.json` (real, verbatim)

```json
{
  "ok": true,
  "status": "PASS",
  "files_ok": true,
  "files_checked": 547,
  "counts": {
    "relations": 150,
    "queries": 86,
    "relation_kinds": {
      "R1": 117,
      "R2": 33
    }
  },
  "relation_pool": {
    "pool_id": "exported",
    "kinds": {
      "R1": 117,
      "R2": 33
    },
    "r2_closure": {
      "ok": true,
      "problems": [],
      "edges": 33,
      "fragments_with_mates": 66
    }
  },
  "batch_fragments": 64,
  "feature_shapes": {
    "n_fragments": 64,
    "n_views": 12,
    "token_budget": 576,
    "n_points": 217855,
    "n_regions": 1,
    "c_quality": 1,
    "c_presence": 1,
    "global_rgb": [64, 12, 3, 768, 1024],
    "local_tokens": [64, 576, 256],
    "points": [64, 217855, 3],
    "token_retention": [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0, 0.0, 1.0, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0,
                        0.0, 1.0, 0.0, 0.0, 1.0, 0.0, 1.0, 0.0, 0.0, 0.0, "<39 more>"],
    "scale_valid_fraction": 0.25
  },
  "real_denominator": {
    "fragments": 64,
    "fragments_with_observation": 16,
    "fragments_without_observation": 48,
    "tokens_total": 9216,
    "tokens_valid": 9216,
    "points_valid": 1208720,
    "scale_valid_fragments": 16
  },
  "negative_audit": {
    "ok": true,
    "problems": [],
    "negatives": 0,
    "positives": 12,
    "r1_fallback_used": 0
  },
  "degenerate": null,
  "blocking_attempt": null,
  "error": null,
  "note": "produced by tools/loader_probe_run.py: qc.loader_probe.probe_training_package on data/a12_exports/next_experiment/training_package; the probe's own json dump was skipped because it raises MemoryError on this package size"
}
```

Batch block from the same file (lines 28-116), verbatim:

```json
"batch": {
    "shapes": {
      "pair_index": [36, 1, 2],
      "pair_valid": [36, 1],
      "labels_relation": [36, 1],
      "pos_mask": [36, 1],
      "neg_mask": [36, 1],
      "excluded_mask": [36, 1],
      "exclusion_reason": [36, 1],
      "quality_target": [64, 1, 1],
      "corr_weight": [36, 1, 576],
      "contradiction": [36, 1],
      "quality_tier": [64],
      "lineage_cluster": [64],
      "sample_keys": [36]
    },
    "pool_id": "exported",
    "n_queries": 36,
    "n_candidates": 1,
    "positives": 12,
    "negatives": 0,
    "excluded": 24,
    "effective_queries": 0,
    "exposure": {
      "fragments": 64,
      "queries": 36,
      "effective_queries": 0,
      "r2_edges_exposed": 12,
      "legal_negatives": 0,
      "excluded_candidates": 24,
      "unconfirmed_candidates": 0,
      "correspondence_edges": 0,
      "contradiction_labels": 12,
      "quality_targets": 0,
      "tokens": 9216,
      "points": 1208720,
      "clean_fraction": 1.0,
      "tier_histogram": {"Q0": 64},
      "exclusion_histogram": {
        "none": 12, "same_fragment": 0, "known_R2": 0, "gray_zone": 24,
        "unknown": 0, "TINY": 0, "label_invalid": 0
      }
    }
  }
```

All ten `attempts[]` entries report `"ok": true` with `"error_code": null`
(`loader_probe_summary.json:192-253`).

### 4c. `closed_loop` — real probe numbers

`data/a12/reports/training_smoke.json:1094-1190` (`loader_probe` sub-report), verbatim excerpts:

```json
"loader_probe": {
    "batch": {
      "effective_queries": 0,
      "excluded": 0,
      "n_candidates": 1,
      "n_queries": 3,
      "negatives": 0,
      "pool_id": "exported",
      "positives": 3,
      "shapes": {
        "contradiction": [3, 1],
        "corr_weight": [3, 1, 192],
        "excluded_mask": [3, 1],
        "exclusion_reason": [3, 1],
        "labels_relation": [3, 1],
        "lineage_cluster": [6],
        "neg_mask": [3, 1],
        "pair_index": [3, 1, 2],
        "pair_valid": [3, 1],
        "pos_mask": [3, 1],
        "quality_target": [6, 1, 1],
        "quality_tier": [6],
        "sample_keys": [3]
      }
    },
    "batch_fragments": 6,
    "batch_rows": {"rows": 3, "with_negatives": 0, "with_positives": 3},
    "counts": {"queries": 6, "relation_kinds": {"R2": 3}, "relations": 3},
    "files_ok": true,
    "negative_audit": {"negatives": 0, "ok": true, "positives": 3, "problems": [],
                       "r1_fallback_used": 0},
    "ok": true,
    "real_denominator": {
      "fragments": 6,
      "fragments_with_observation": 3,
      "fragments_without_observation": 3,
      "points_valid": 6049,
      "scale_valid_fragments": 3,
      "tokens_total": 576,
      "tokens_valid": 576
    },
    "report_path": null,
    "seconds": 0.31713032722473145
  }
```

`data/a12/reports/training_smoke_summary.txt:84-86`, verbatim:

```
loader_probe.negative_audit: {"negatives": 0, "ok": true, "positives": 3, "problems": [], "r1_fallback_used": 0}
loader_probe.real_denominator: {"fragments": 6, "fragments_with_observation": 3, "fragments_without_observation": 3, "points_valid": 6049, "scale_valid_fragments": 3, "tokens_total": 576, "tokens_valid": 576}
loader_probe.seconds: 0.35863733291625977
```

### 4d. `closed_loop` — the full `loader_probe.json` content, recovered

`data/a12/reports/loader_probe.json` is **0 bytes on disk today**. Its content was captured by
`data/a12_exports/_scratch/collect_numbers.py` into `data/a12_exports/_scratch/numbers.txt:44-49`,
verbatim:

```
### data/a12/reports/loader_probe.json
ok: True status: PASS files_ok: True
counts: {"queries": 6, "relation_kinds": {"R2": 3}, "relations": 3}
real_denominator: {"fragments": 6, "fragments_with_observation": 3, "fragments_without_observation": 3, "points_valid": 6049, "scale_valid_fragments": 3, "tokens_total": 576, "tokens_valid": 576}
relation_pool: {"kinds": {"R2": 3}, "pool_id": "exported", "r2_closure": {"edges": 3, "fragments_with_mates": 6, "ok": true, "problems": []}}
feature_shapes: {"c_presence": 1, "c_quality": 1, "global_rgb": [6, 4, 3, 192, 256], "local_tokens": [6, 192, 256], "n_fragments": 6, "n_points": 4158, "n_regions": 1, "n_views": 4, "points": [6, 4158, 3], "scale_valid_fraction": 0.5, "token_budget": 192, "token_retention": [1.0, 0.0, 1.0, 0.0, 1.0, 0.0]}
```

Same run's step ledger, `data/a12_exports/_scratch/numbers.txt:28`:
`-- loader_probe: status=OK seconds=1.591`.
And `data/a12_exports/_scratch/ledger_digest.txt:3`:
`step_status: {"audit": "DEGRADED", "build_pool": "OK", "export_training_package": "OK", "generate": "OK", "loader_probe": "OK", "release_freeze": "OK", "report": "OK"}`.
`ledger_digest.txt:22-23`:
```
=== loader_probe ===
{"counts": {"queries": 6, "relation_kinds": {"R2": 3}, "relations": 3}, "error": null, "ok": true, "seconds": 1.107, "status": "OK"}
```

An earlier capture of the same report is hashed into the release-freeze evidence manifest,
`data/a12/reports/release_freeze_after_feature_leak_repair.json:280-324`
(`"path": "...\\data\\a12\\reports\\loader_probe.json"`, `"hash": "sha256:05fdead52b08984ef3a9d21ef87fab52e5fdf27d503bd1f2b3a89906cd9c12f9"`),
with metrics including `feature_shapes.n_fragments: 6`, `feature_shapes.n_points: 4158`,
`feature_shapes.n_views: 4`, `feature_shapes.token_budget: 192`,
`feature_shapes.scale_valid_fraction: 0.5`, `files_checked: 13`,
`real_denominator.points_valid: 6049`, `relation_kinds_in_batch.R2: 3`,
`seconds: 0.4709935188293457`.

### 4e. `loop_loader*.out` / `loader2_check.txt` — verbatim

`data/a12_exports/_scratch/loop_loader.out` (314 bytes):

```
[loader_probe] running ...
[loader_probe] OK in 1.6s

=== closed loop ===
  loader_probe             OK            1.6s  ok=True queries=3 pos=3 neg=0
```

`data/a12_exports/_scratch/loop_loader2.out` (314 bytes):

```
[loader_probe] running ...
[loader_probe] OK in 1.5s

=== closed loop ===
  loader_probe             OK            1.5s  ok=True queries=3 pos=3 neg=0
```

`data/a12/reports/closed_loop_loader_after_fix.txt` (314 bytes):

```
[loader_probe] running ...
[loader_probe] OK in 1.8s

=== closed loop ===
  loader_probe             OK            1.8s  ok=True queries=3 pos=3 neg=0
```

`data/a12_exports/_scratch/loader2_check.txt` (419 bytes) — note `files_checked 13`, which matches
the pre-zarr closed_loop package (manifest now `counts_total: 55` with 40 zarr files + 2 extra label
layers; `55 - 40 - 2 = 13`):

```
ok True status PASS files_ok True files_checked 13
counts {"queries": 6, "relation_kinds": {"R2": 3}, "relations": 3}
real_denominator {"fragments": 6, "fragments_with_observation": 3, "fragments_without_observation": 3, "points_valid": 6049, "scale_valid_fragments": 3, "tokens_total": 576, "tokens_valid": 576}
negative_audit {"negatives": 0, "ok": true, "positives": 3, "problems": [], "r1_fallback_used": 0}
```

Cross-check against the current package manifests, which agree with the probe's denominators:
`next_experiment` `counts.geometry_points: 2051676` / `tokens: 16128` /
`fragments_with_observation: 28` (all 28 observation rows, but the probe's *truncated* batch scope
only saw 16 observed + 48 unobserved fragments); `closed_loop` `counts.geometry_points: 6049` /
`tokens: 576` / `observations: 3` — exactly the probe's `points_valid: 6049`,
`tokens_total: 576`, `fragments_with_observation: 3`.

### 4f. What `synlab/qc/loader_probe.py` does and how it is invoked

The module docstring (`loader_probe.py:1-28`) states it is the "the loader really reads it" check:
it reads the packaged ObsPack RGB shards, geometry shards, token cache, relation table and labels,
assembles the `a12.obs.v1` payload form that `FeatureBundle.from_dict` consumes, and builds a real
`TrainingBatch` through `build_training_batch`. The report path is
`data/a12/reports/loader_probe.json` "(or `--out`)".

`probe_training_package` (`loader_probe.py:262-415`) runs ten guarded `attempt(...)` steps in order
(`loader_probe.py:294-395`):

1. `storage.export.TrainingPackage` (`:294`) 2. `package.verify_files` (`:299`)
3. `package.relations` (`:306`) 4. `package.queries` (`:307`)
5. `qc.loader_probe.ExportedRelationPool` (`:314`)
6. `load_features(local_tokens/geometry/global_rgb)` (`:335`)
7. `training.adapter.FeatureBundle.from_dict` (`:341`)
8. `training.adapter.FeatureBundle.check_shapes` (`:346`)
9. `training.batch.build_training_batch` (`:365`)
10. `training.batch.negative_audit` (`:371`)

`ok` is the conjunction of file integrity **and** the negative audit (`loader_probe.py:390-406`):

```
390:    # ``ok`` is the *whole* claim: the package must verify against its own manifest hashes
391:    # (``package.verify_files``) **and** the batch must pass its negative audit.  Reporting only
392:    # the audit made a package whose declared hashes do not verify load "ok" -- a loader that
393:    # accepts tampered bytes is not a loader.
394:    integrity_ok = bool(report.get("files_ok"))
395:    report["ok"] = bool(integrity_ok and audit and audit.get("ok"))
```

`_finish` (`loader_probe.py:418-427`) writes the JSON only when `out_path is not None`
(`:422`) — this is the allocation that raises `MemoryError` on the 1447 MB package.

There is **no CLI in `loader_probe.py`** — it has no `argparse`, no `main()`, no
`if __name__ == "__main__"`. It is a library function; callers supply the package dir.

---

## 5. How the loader is invoked (reproduction)

### 5a. Entry points

| entry point | file:line | what it does |
|---|---|---|
| Library call | `synlab/qc/loader_probe.py:262` | `probe_training_package(package_dir, *, max_fragments=16, out_path=None, token_budget=None)`. |
| Scratch runner (has the real `next_experiment` invocation) | `tools/loader_probe_run.py:21,48,71` | `PACKAGE = ROOT / "data/a12_exports/next_experiment/training_package"`, `REPORT = ROOT / "data/a12/reports/loader_probe_summary.json"`, `report = probe_training_package(PACKAGE, out_path=None)`. |
| Closed-loop step | `tools/closed_loop.py:1312-1314` | `def step_loader_probe(*, package_dir, report_path, ledger)` → `probe_training_package(package_dir, out_path=report_path)`. Selected by `--step loader_probe` (help text at `data/a12_exports/_scratch/closed_loop_help.txt:9-10`). |
| Next-experiment step | `tools/next_experiment_export.py:354-358` | `probe_training_package(package_dir, out_path=report_path)`, selected by `--step loader_probe` (`:373-374`). |
| Training smoke (real batch + forward/backward) | `synlab/training/smoke.py:148-171` and `:348-351` | `load_real_inputs(package_dir)` then, when `include_loader_probe`, `probe_training_package(package_dir)`. |
| Library callers in tests | `tests/a12/integration/test_closed_loop.py:636,654,672,678` | Probe of a clone, of the real package, and of a non-existent dir. |

**Console script:** `pyproject.toml:40-41` declares exactly one —
`[project.scripts]` / `synlab = "synlab.cli:main"`. There is **no** `loader_probe` console script,
and `synlab/cli.py` has no loader-probe command (`grep loader_prob|probe` in `synlab/cli.py` returns
only `export` at lines 270-280). So loader-probe reachability is: the `synlab` CLI does **not**
expose it.

### 5b. Exact reproduction commands

```powershell
# closed_loop probe — the canonical report path (data/a12/reports/loader_probe.json)
cd C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab
.venv\Scripts\python.exe -c "from synlab.qc.loader_probe import probe_training_package; probe_training_package('data/a12_exports/closed_loop/training_package', out_path='data/a12/reports/loader_probe.json')"

# same, through the closed-loop driver (this is what produced loop_loader*.out)
.venv\Scripts\python.exe tools\closed_loop.py --step loader_probe

# next_experiment probe — the 1447 MB package; dump skipped (MemoryError), bounded summary written
.venv\Scripts\python.exe tools\loader_probe_run.py
#   -> prints the summary and writes data/a12/reports/loader_probe_summary.json

# next_experiment probe the driver way
.venv\Scripts\python.exe tools\next_experiment_export.py --step loader_probe

# training smoke (reads the package through the SAME loader helpers, then trains)
.venv\Scripts\python.exe -m synlab.training.smoke --package data/a12_exports/closed_loop/training_package --steps 3 --out data/a12/reports
#   CLI flags: synlab/training/smoke.py:654-667  (--package --steps --token-budget --out --no-loader-probe)

# one-liner recorded in the supervision report
.venv\Scripts\python.exe -c "from synlab.training.smoke import run_smoke; run_smoke('data/a12_exports/closed_loop/training_package', steps=3, out_dir='data/a12/reports', include_loader_probe=True)"
#   verbatim from data/a12/reports/training_supervision_after.json:334
```

`synlab/training/smoke.py:34-38` documents the intended usage:
`.venv\Scripts\python.exe -m synlab.training.smoke --package <dir> --steps 3 --out data/a12/reports/training_smoke.json`.

### 5c. Read-only shard verification performed for this report

`data/a12/reports/modality_census/sub_loader_shard_keys.py` (created by this investigation; reads
only, run with `python -B`, writes nothing) dumped the raw keys/shapes/dtypes of both packages'
shards. Real output:

```
[2] geometry shard geometry/shard_0000.npz (12961591 bytes)   # next_experiment
    arrays under prefix '2d233618af9243f6739f2aef__' = ['frame_id', 'normal_valid', 'normals', 'point_valid', 'points', 'scale_valid']
    frame_id        shape=(89082,)     dtype=int32
    normal_valid    shape=(89082,)     dtype=bool
    normals         shape=(89082, 3)   dtype=float32
    point_valid     shape=(89082,)     dtype=bool
    points          shape=(89082, 3)   dtype=float32
    scale_valid     shape=(89082,)     dtype=bool

[3] token shard tokens/shard_0000.npz (80269686 bytes)        # next_experiment
    arrays = ['tile_valid', 'token_input', 'token_valid', 'token_view', 'tokens']
    tile_valid      shape=(12, 768, 1024)  dtype=bool
    token_input     shape=(576,)           dtype=float32
    token_valid     shape=(576,)           dtype=bool
    token_view      shape=(576,)           dtype=int32
    tokens          shape=(576, 256)       dtype=float32

[4] obs shard obs/shard_0000.tar (302018560 bytes)            # next_experiment
    rgb (tiles.npy)       shape=(12, 768, 1024, 3)  dtype=uint8
    valid (valid.npy)     shape=(12, 768, 1024)     dtype=bool
    view_pos (view_pos.npy) shape=(12,)             dtype=float32

[2] geometry shard geometry/shard_0000.npz (192983 bytes)     # closed_loop
    points (1306,3) float32 | normals (1306,3) float32 | point_valid (1306,) bool
    normal_valid (1306,) bool | scale_valid (1306,) bool | frame_id (1306,) int32
[3] token shard tokens/shard_0000.npz (1189402 bytes)         # closed_loop
    tokens (192,256) float32 | token_valid (192,) bool | token_view (192,) int32
[4] obs shard obs/shard_0000.tar (2375680 bytes)              # closed_loop
    rgb (4,192,256,3) uint8 | valid (4,192,256) bool | view_pos (4,) float32
```

This confirms `_observed_payload`'s dtype casts (`loader_probe.py:223-241`) are lossless for both
packages, and that the `token_dim`/`views`/`n_points` declared in each `index.json` match the
arrays actually stored.

---

## 6. Summary of the load-bearing claims

1. The loader is `synlab/storage/export.py:1447 class TrainingPackage` + the payload assembler
   `synlab/qc/loader_probe.py:171 load_features` (+ `_observed_payload:218`, `_absent_payload:191`).
   `FeatureBundle.from_dict` (`adapter.py:360`) and `build_training_batch` (`batch.py:253`) turn
   those into the batch tensors.
2. **Both packages load.** The reader derives every shard path from `index.json`
   (`export.py:1515`, `:1547`) and every array name from `entry["opaque"]` (`:1548`); there is no
   shard-count, shard-name or file-count expectation in the reader. Real PASS artifacts exist for
   both (`next_experiment`: `files_checked 547`, `ok true`; `closed_loop`: `files_checked 55`,
   `ok true`).
3. **`deploy/zarr/` is never read.** zarr appears only in the writer
   (`export.py:461-470`, `_write_zarr:1221`, `_zarr_root:205`) and the manifest scanner
   (`_zarr_declared_arrays:1313`, `:1359`), plus `synlab/doctor.py:373-384` (dependency smoke).
   `loader_probe.py` and all of `synlab/training/` contain zero `zarr` occurrences.
4. `deploy/deploy_index.json` is written by the exporter (`export.py:639-649`) and read **only** by
   `synlab/qc/data_quality.py:1388`; the loader ignores it.
5. The one real, non-obvious loader-side limit is the **probe's** `max_fragments=16` truncation
   (`loader_probe.py:262`, `:323`), which is why the 86-query `next_experiment` package yields a
   36-query / 64-fragment batch.
6. The canonical `data/a12/reports/loader_probe.json` is a **0-byte file**; its real content is
   recovered from `data/a12_exports/_scratch/numbers.txt:44-49`.
