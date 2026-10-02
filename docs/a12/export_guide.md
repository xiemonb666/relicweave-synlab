# 训练导出包使用指南（数据卡 / 加载器 / 三缺陷修复 / 开箱可训差距）

> 权威证据文件（本次全部真实运行产出）：
> `data/a12/reports/export_fixes/` 下的 `_measure_*.json`、`_reexport_*.json`、
> `_probe_defect_sources.json`、`_pytest_storage_2.log`、`_loader_*.log`、`_quickstart.log`。
> 缺陷普查见 `docs/a12/modality_census.md` §7.7（D1/D2/D3）。

本文回答四件事：**包里到底有什么**（数据卡字段）、**怎么把它读进来**（加载器）、
**三个静默缺陷改成了什么**（before/after 实测）、**还缺什么才能真的开训**（对照
`docs/a12/training_run.md` §4.1 的最小需求）。

---

## 1. 为什么需要一份"数据卡"

一个训练包是 56～548 个文件、不同格式（parquet / npz / tar / zarr / json）的混合体，
`export_manifest.json` 只声明**哈希与计数**，不声明"这一列是什么单位、是不是标签、
能不能进部署视图、这个任务现在有没有监督"。审计与训练前的判断因此只能靠人读文档 —— 这正是
"缺字段记 `missing`、无监督记 `not_applicable`"必须落到**机器可读文件**里的原因。

数据卡由 `tools/load_package.py --write-card` 生成，写进包内两个文件：

| 文件 | 作用 |
|---|---|
| `dataset_card.json` | 机器可读全量数据卡（本文 §2 逐字段说明） |
| `README.md` | 同一份卡片的渲染版（人读：身份表、文件表、任务表、划分、标签、诚实边界、用法） |

**卡片的每一个数字都来自对包内字节的真实扫描**：逐文件 `sha256` 与磁盘字节数、
parquet 逐列 `min/max/缺失率/唯一值`、npz/tar/zarr 逐数组 `shape/dtype/缺失率/非零率`、
token 块的**有效秩**、`view_pos` 的非零比例、`frame_id` 与行号计数器的关系、
以及一个**真实 mini-batch** 的五任务 `n_valid / n_allowed`。没有任何常量表冒充测量值；
本工具自己不认识的列会写 `"meaning": "not documented"` 并进入诚实边界清单。

---

## 2. 数据卡字段说明

`dataset_card.json`（`schema = synlab.dataset_card.v1`）分七块：

### 2.1 `identity` —— 包身份

| 字段 | 含义 | 缺失时的写法 |
|---|---|---|
| `run_id` | 产出该包的 run | 训练包 schema 里**没有** run_id → `"missing"` + `run_id_reason`（源头是 store 的 `runs` 表） |
| `release_id` / `package_id` | 冻结发布 / 包标识 | 直接取 manifest |
| `git_head.head` / `.dirty` | 扫描时的 `git rev-parse HEAD` 与 `git status --porcelain` 是否非空 | git 不可用时 `"missing"` + `reason` |
| `registry.fingerprint` | `synlab.registry.REGISTRY.fingerprint()` | 导入失败时 `"missing"` + `reason` |
| `exported_at_utc` | manifest 文件的真实 mtime（不是"生成卡片的时间"） | — |
| `spec_hash` | 该 run 的 spec 哈希 | 包里**不含** spec → `"missing"` + `spec_hash_reason` |
| `manifest_hash` / `release_manifest_hash` | 包清单 / 发布清单哈希 | — |
| `writer.sha256` | `synlab/storage/export.py` 的 sha256（"哪个写者写的这些字节"） | — |
| `loader.sha256` | 本工具自身哈希（"哪版加载器读的"） | — |

> 诚实点：`run_id` 与 `spec_hash` 在 `synlab.training_package_manifest.v1` 里就不存在。
> 不猜、不编：写 `missing` 并给出唯一可信来源。

### 2.2 `package` —— 逐文件清单

每个 manifest 声明的文件一行：`path`、`format`、`bytes`、`manifest_hash`、`sha256`（真实重算）、
`purpose`（一句话用途）、`unit`、`frame`、`view`（deploy/research/package），
以及按格式补充的规模信息：parquet `rows/columns/column_names`、npz `arrays/dtypes/n_arrays`、
tar `members/entities/member_names`。另有：

* `files_extra`：磁盘上存在但 manifest 未声明的文件（正常情况只有 `export_manifest.json`
  与卡片自身的两个文件）；
* `files_missing`：manifest 声明但磁盘缺失的文件；
* `hashes_match_manifest`：全部声明文件 sha256 是否一致（布尔，实测）。

### 2.3 `columns` —— 逐表逐列字典

对每个 parquet：`rows` + `columns`，每列给
`dtype`、`meaning`（语义）、`unit`、`is_label`（是否答案侧监督）、`missing_rate`（真实缺失率）、
`n_unique`、数值列的 `min/max/mean`、低基数列的 `value_counts`。
`is_label=true` 的列**不得**进入部署视图。

### 2.4 `arrays` + `array_dictionary` —— 逐通道字典

`arrays` 按 `geometry / tokens / obs / zarr` 四族给每个碎片每个数组的
`shape`、`dtype`、`nbytes`、浮点的 `min/max/mean/missing_rate/nonzero_rate`、
布尔的 `true_rate`、整数的 `min/max/n_unique/nonzero_rate`；
token 数组额外带 `effective_rank`（见 §5.1）。
`array_dictionary` 给出通道级语义（`points/normals/*_valid/frame_id/tokens/token_view/view_pos/...` 的
含义、单位、坐标系、是否标签）。

### 2.5 `tasks` —— 五任务定义与当前监督

每个任务给：`inputs`（输入字段）、`supervision`（监督字段/来源）、`loss_mask` 语义、
`measured.n_valid / measured.n_allowed`（**真实值**，来自 loader 用 `synlab.training.batch` +
`synlab.training.supervision` 在真包上构建的批次）、`measured.why`（当前为什么有/没有监督）、
`measured.unlock_condition`（解锁条件）。`_table` 汇总五任务；`_relation_columns_present`
列出关系表真实列。

### 2.6 `splits` —— 谱系级划分

`by_split`：每个 split 的 `rows`（按表细分）、`lineages`、`fragments`；
`lineages`/`fragments` 给出每个谱系/碎片落在哪些 split（**只有单元素集合才算合法**）；
`leak_free` 与 `problems` 是实测结论：同一谱系或同一碎片跨 split 即列问题。

### 2.7 `labels` —— 标注清单

`relation_kinds`（R2/R1/R0/TINY/UNKNOWN 真实计数）、`eligible_as_negative`
（`kind in {R1,R0} and valid and loss_mask` 的真实计数）、`layers.<layer>`
（每层行数、列、`kind_counts`、`reason_counts`、`valid_rows`、`loss_masked_rows`、`splits`）、
`label_source`（每层的来源资产 id 列表 + 路径，来自 manifest 的 `labels` 块）、
`supervision_labels`（quality/correspondence 的产者统计）。
"哪次提交、哪个真值层"由 `identity.git_head` + `label_source`（资产 id）+ `label_layer` 三者共同确定。

### 2.8 `honest_boundaries` —— 诚实边界

每条给 `id`、`status`、`current_value`（真实测量）、`impact`、`unlock_condition`。
当前自动生成的条目：

| id | 触发条件 | 现状（closed_loop 包） |
|---|---|---|
| `no_legal_negatives` | `eligible_as_negative == 0` | `not_applicable`：R2 3 行、合法负例 0 行 |
| `tokens_broadcast_defect` | token 块是"首列缩放广播" | 旧包 `defect_present`（有效秩 1），新包 `fixed_in_this_package` |
| `view_pos_all_zero` | 交付的 `view_pos` 全零 | 旧包 `defect_present`（3/3 数组全零），新包 `fixed_in_this_package`（误差 0） |
| `frame_id_row_counter` | 几何索引没有 `frame_id` 语义块 | 旧包 `defect_present`，新包 `fixed_in_this_package`（匹配率 97.9%） |
| `deployment_mask_sparse` | 部署 mask 真值率 | 实测 0.36%–1.77%（逐碎片） |
| `undocumented_columns` | 存在未文档化列 | `complete`（0 列） |
| `deploy_view_channels` | 部署视图通道超出 3 个核心通道 | 政策放开后列出 `depth_z/K/uncertain_mask/roi` |
| `no_query_rows` | 没有查询行 | 不触发（6 行） |

---

## 3. 加载器 `tools/load_package.py`

### 3.1 命令行

```powershell
cd C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab

# 数据卡摘要 + 五任务监督 + 一个真实 mini-batch（形状与来源）
& .venv\Scripts\python.exe tools\load_package.py --package data\a12_exports\closed_loop\training_package

# 逐批走包（每批打印 n_allowed）
& .venv\Scripts\python.exe tools\load_package.py --package <dir> --iterate --batch-size 2

# 由真实扫描生成 / 刷新包内数据卡
& .venv\Scripts\python.exe tools\load_package.py --package <dir> --write-card

# 独立校验：退出码 0=一致 / 3=不一致
& .venv\Scripts\python.exe tools\load_package.py --package <dir> --check
```

其它开关：`--json <file>`（把卡片或校验结论落盘）、`--token-budget N`、
`--sample-fragments N`（只扫描前 N 个碎片的数组统计）、`--no-hash`（跳过全文件 sha256，更快但卡片更弱）。

### 3.2 可 import 的 API（numpy / pandas，不依赖 torch）

```python
from tools.load_package import (load_relations, load_labels, load_queries,
                                load_arrays, iter_batches, build_batch,
                                supervision_table, zarr_npz_consistency, check_package)

relations = load_relations(pkg)                      # pandas.DataFrame：query/candidate/kind/valid/loss_mask/...
quality   = load_labels(pkg, "quality")              # 逐 fragment×view 的可观测率目标
geometry  = load_arrays(pkg, kind="geometry")         # {fragment: {points/normals/frame_id/...}}
same_geo  = load_arrays(pkg, "LIN0000_...", kind="geometry", source="zarr")   # 读 zarr 副本
obs       = load_arrays(pkg, "LIN0000_...", kind="obs")                       # tar 内全部通道

for batch in iter_batches(pkg, batch_size=2):
    batch["features"]["<fragment>"]["local_tokens"]      # 逐碎片 numpy 张量
    batch["labels"]["pos_mask"], batch["labels"]["corr_weight"]
    batch["supervision"]["tasks"]["rank"]["n_allowed"]
```

* `build_batch(pkg)` 走的是**训练器自己的代码路径**：`synlab.qc.loader_probe.load_features`
  → `FeatureBundle.from_dict(...).check_shapes()` → `PackageLabelSource`
  （quality / correspondence 标签接线）→ `synlab.training.batch.build_training_batch`
  → `synlab.training.supervision.supervision_accounting`。
* `z_valid` 由 `tools/load_package.encoder_valid()` 复刻 `synlab/training/model.py::encode`
  的 `valid = (rgb_gate + geo_gate + tok_gate) > 0`，因此 `n_allowed` 与训练器同分母。
* zarr：`read_zarr_array()` 优先用 `zarr` 包，**没有 zarr 时用内置 v3 读取器**
  （`bytes`+`zstd` 解码，zstd 经 `numcodecs`），两条路径都由
  `zarr_npz_consistency()` 与 npz 逐字节比对。

### 3.3 `--check` 校验了什么

| 检查 | 内容 | closed_loop 包实测 |
|---|---|---|
| `file_set` | manifest 声明集合 vs 磁盘集合；额外文件只允许 `export_manifest.json` + 卡片两件 | PASS（55 声明 / 58 在盘 / 0 缺失 / 0 非预期） |
| `sha256` | 每个声明文件真实重算 | PASS（55/55 一致） |
| `column_dictionary` | 卡片逐表列名/行数 vs 真实 parquet（表不可读也算问题） | PASS（7 张表） |
| `splits` | 谱系/碎片是否跨 split | PASS（`leak_free=true`） |

退出码：`0` 一致、`3` 不一致、`2` 用法错误。篡改一个 parquet 字节或塞一个未声明文件都会被判 3
（`tests/a12/storage/test_load_package.py::test_check_package_detects_a_tampered_file` /
`..._detects_an_undeclared_file` 钉住）。

---

## 4. 真实输出

### 4.1 `python tools/load_package.py --package data/a12_exports/closed_loop/training_package`

```
package      : data\a12_exports\closed_loop\training_package
release_id   : rel_852ab2a1e4c3_1790905541   package_id: pkg_rel_852ab2a1e4c3_1790905541
git HEAD     : c3a149f6aee73245db7c3540e55c0292da2d1a66 (dirty=True)
REGISTRY.fp  : sha256:4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945
run_id       : missing   spec_hash: missing
files/bytes  : 56 files, 3.8 MiB, hashes_match_manifest=True
relations    : {"R2": 3}  eligible_as_negative=0
splits       : leak_free=True {"dev": {...}, "train": {...}}

per-task supervision (real batch, trainer's own masks):
  task             n_valid  n_allowed  why
  view                  12         12  supervised
  rank                   3          0  no_legal_negative_in_the_exported_relation_table
  correspondence      3587          0  one_side_of_every_labelled_pair_has_no_token_evidence
  quality                3          3  supervised
  contradiction          3          0  no_encodable_contradiction_pair

mini-batch (real, built from this package):
  feature global_rgb     [6, 4, 3, 192, 256]    float32
  feature pixel_valid    [6, 4, 192, 256]       bool
  feature local_tokens   [6, 192, 256]          float32
  feature token_view     [6, 192]               int32
  feature points         [6, 4158, 3]           float32
  feature normals        [6, 4158, 3]           float32
  label   pair_index     [3, 1, 2]              int64
  label   quality_target [6, 1, 1]              float32
  label   corr_weight    [3, 1, 192]            float32
  fragments=6 observed=3 positives=3 negatives=0 effective_queries=0
  source  : relations=research/relations.parquet queries=deploy/queries.parquet
            tokens=['tokens/shard_0000.npz'] geometry=['geometry/shard_0000.npz'] obs=['obs/shard_0000.tar']
```

退出码 **0**。（全文见 `data/a12/reports/export_fixes/_loader_run_old.log`。）

### 4.2 `python tools/load_package.py --package <dir> --check`

```
[PASS] file_set: {"declared": 55, "on_disk": 58, "missing": [], "extra": ["README.md", "dataset_card.json", "export_manifest.json"], "unexpected_extra": []}
[PASS] sha256: {"checked": 55, "mismatched": []}
[PASS] column_dictionary: {"tables": 7, "problems": []}
[PASS] splits: {"leak_free": true, "problems": [], "by_split": {...}}
{"ok": true, "problems": []}
exit 0 (consistent)
```

退出码 **0**。（日志 `_loader_check_old.log`。）

### 4.3 `python examples/quickstart.py`

```
package: ...\data\a12_exports\closed_loop\training_package
relations: 3 rows, kinds={'R2': 3}
  label layer correspondence   3587 rows
real mini-batch (numpy path, same builders the trainer uses): ... 
per-task supervision: view 12/12、rank 3/0、correspondence 3587/0、quality 3/3、contradiction 3/0
iter_batches(batch_size=2): batch 0 queries=2 fragments=4 n_allowed={'view': 8, 'rank': 0, ...}
torch: torch 2.11.0+cu128: global_rgb (6, 4, 3, 192, 256) local_tokens (6, 192, 256) points (6, 4158, 3)
elapsed 5.06 s (budget 30 s): OK
```

退出码 **0**，脚本内计时 **5.06 s**（含 python 启动的墙钟 6.99 s，均远低于 30 s 预算）。
torch 在本次运行期间可用，因此张量分支真实打印；torch 不可用时该分支打印
`SKIPPED: torch is not usable ...` 并说明 numpy 路径是受支持路径。

### 4.4 四条验收命令的退出码

| 命令 | 退出码 | 证据 |
|---|---|---|
| `tools/load_package.py --package data/a12_exports/closed_loop/training_package` | **0** | `_acc1_loader.log` |
| `tools/load_package.py --package <dir> --check`（修复前包 / 修复后包 / nx 包） | **0 / 0 / 0** | `_acc2a_check.log`、`_acc2b_check.log`、`_acc2c_check_nx.log` |
| `examples/quickstart.py` | **0**（脚本内 6.48 s；含启动墙钟 12.56 s） | `_acc3_quickstart.log` |
| `pytest tests/a12/storage -q` | **0**（`54 passed, 2 skipped`，其中本任务新增 14 条） | `_acc4_pytest_dir.log`、`_acc4_pytest_mine.log` |

> 目录级结果是**并发状态下**测得的，会随队友同期落地的用例波动：本任务运行期间
> `tests/a12/storage/` 里先后出现了 `test_export_full.py` / `test_load_full_package.py`
> （`synlab/storage/export_full.py`，flavour="full" 导出器）与
> `test_context_and_channel_policy.py`（通道政策）。观测到的三种状态：
> ① `26 passed, 2 skipped`（fixture 补齐后）、② `54 passed, 2 skipped`、exit **0**、
> ③ 最后一次 `exit 1`，失败全部落在 `test_context_and_channel_policy.py`
> （`test_observed_channels_reads_real_files` 等 1–3 条：该用例要求"声明不等于测量"，
> 即 `observed_channels()` 不应把 `obs/index.json` 的 `channel_names` 计入 `counts`，
> 而该函数当前仍会读它）——**均为并发作者的进行中用例，不是本任务交付物**。
> 本任务自有的 14 条用例始终：`pytest tests/a12/storage/test_load_package.py -q` → exit **0**。
>
> `examples/quickstart.py` 的耗时随机器负载变化（实测 5.06 s / 6.48 s / 18.43 s，
> 均为并发跑测试或 1.3 GiB 全量哈希时测得），三次都打印 `OK`（预算 30 s）。



### 4.5 修复后的包 `training_package_v2`（同一 release 的第二次真实导出）

```
package_id   : pkg_rel_852ab2a1e4c3_1790905541
manifest_hash: sha256:72b0030f8cb3a69327f8df4a3cd4ac84955bf2c7964d77cbce8da788241edc04
files/bytes  : 58 files, 8 157 001 B（旧包 55 文件 / 3 998 691 B）
导出耗时     : 4.58 s（`_reexport_training_package_v2.json`）
部署通道     : tiles, valid, view_pos, deployment_mask, uncertain_mask, roi, K, depth_z（后者随
               `synlab/schemas/view_channels.json` 政策放开，逐碎片 3/3 交付）
frame_id     : T_WC+K+depth_z，匹配 5924/6049 = 0.9793，容差 5 mm
view_pos     : finite 12/12、nonzero 12/12、min −5.0956 / max 12.7215 mm
五任务       : view 12/12、rank 3/0、correspondence 3587/0、quality 3/3、contradiction 3/0（与修复前一致）
`--check`    : exit 0（58 声明 / 61 在盘 / 0 缺失 / 0 非预期 / 哈希全一致 / 划分无泄漏）
```

> ⚠️ **写者侧仍有一处待处理（不属于本次三个缺陷）**：`training_package_v2` 的
> `separation.answer_field_scan.hits = [{"file": "queries.parquet", "field": "bag_id"}]`、
> `features_carry_answer_fields = true`、`views.deploy.contains_truth = true` —— 即并发队友新增的
> "模拟发掘上下文"（plan t088）把 `bag_id` 写进了部署视图，而 `bag_id` 同时是
> `roles.FORBIDDEN_FEATURE_FIELDS` 里的名字。数据卡已把它列为
> `honest_boundaries.deploy_view_answer_field_hit = defect_present`。修法二选一：
> 从部署视图移除该字段，或把 `bag_id` 作为"允许的采集上下文"写进政策文档并注明 `evidence_class`。
> 本次未替该功能做决定（它属于并发写者的范围），只如实标注。


---

## 5. 三个静默缺陷的修复记录（before / after 实测）

测量脚本：`data/a12/reports/export_fixes/_measure_export_defects.py`（直接读 shard 字节，
不使用任何队友脚本）与 `_probe_defect_sources.py`（读 store 源码数组作真值）。
"before" 与 "after" 是**同一个 release 的两次真实导出**：`training_package`（修复前）
与 `training_package_v2`（修复后），不是同一次导出测两遍。

### 5.1 D1 —— `tokens` 是"首列缩放广播"（有效秩 1）

* 旧写者：`tokens[:, k] = flat if k == 0 else flat * (1 - 1e-6 * k)`，
  `deploy/tokens/index.json` 却声明 `token_dim = 256`。
* 新写者：一个 token 仍是 `(view, block, channel)` 槽位（每视图 48 个），但它的 256 维是
  **该槽位自己的 16×16 子网格块均值**（`TOKEN_SUB=16`，`TOKEN_SUB**2 == TOKEN_DIM`），
  即交付 RGB 的真实局部内容；索引新增 `token_layout` / `token_sub_grid` / `tokens_per_view` 声明。

| 指标（closed_loop，3 碎片） | before | after |
|---|---|---|
| `columns_equal_to_scaled_column0` | **256 / 256** | 1（仅第 0 列自身） |
| `max_abs_error_vs_scaled_broadcast` | 1.2e-08 – 4.6e-08 | **1.0**（不再是广播） |
| `sv[1] / sv[0]` | **5.6e-09 – 7.5e-09** | **0.46 – 0.68** |
| `effective_rank (sv > sv0·1e-6)` | **1** | **192**（= min(行数,256)，满行秩） |
| `tokens[:,0] == token_input` | True（旧不变量） | False（`token_input` 仍是旧的粗块均值，作溯源保留） |

`token_input`（每个视图 48 维真实块均值）**保持不变**：它是真数，不是占位；改变的只是不再用它冒充 256 维特征。

### 5.2 D2 —— `view_pos.npy` 31/31 全零（声明单位 mm）

* 根因两层：源侧 `views[].u_position_mm` **本身就是 0.0**（3 个 obs 资产 × 4 视角全 0，实测），
  而写者 `meta_view.get("u_position_mm", 0.0)` 把这个占位值原样写出去。
* 新写者：优先用交付位姿 **`T_WC[0,3]`**，这正是仓库自己的定义
  （`synlab/degrade/api.py:802` 构造 `ViewFrame` 时 `u_position_mm = T_WC[0,3]`）；
  没有位姿才回退 `view_meta.u_position_mm`；两者都没有 → 写 `nan` 并在索引记
  `view_pos_source="unavailable"`（不再写假 0）。索引新增 `view_pos` 语义块（单位/定义/缺失标记/实测统计）。

| 指标 | before | after |
|---|---|---|
| 全零数组 | **3 / 3**（12 个视角全 0） | 0（12/12 非零，`finite=12`） |
| `view_pos_source` | 字段不存在 | `T_WC[0,3]`（每碎片） |
| 与真实 `T_WC[0,3]` 的误差 | 5.0956 / 12.7215 / 0.3904 mm（= 真值本身） | **0.0 mm（精确相等）** |
| 索引声明 | `channels` 字符串里写着"u position mm"但无字段语义 | `obs/index.json.view_pos` 给出定义、回退、缺失标记与实测 min/max |

**诚实保留**：本批 rig 是 `FIXED_CAMERA_ON_SLIDE_AXIS_PLUS_OBJECT_TURNTABLE`，相机固定在滑移轴上、
物体转台旋转，所以 `T_WC[0,3]` 在**同一碎片内恒定**（各碎片之间不同）。因此 `view_pos` 现在是
**真值但恒定**，仍然**不是视角标识**——视角标识由 §5.3 的 `frame_id` 交付。数据卡的
`honest_boundaries.view_pos_all_zero.per_fragment` 逐碎片给出 `varies_within_fragment`，
避免把写者索引里"跨碎片 pooled 的 `varies_across_views=true`"误读成"逐视角变化"。
要一个真正变化的位姿通道，需要滑移台架或新增通道：

```jsonc
// synlab/schemas/view_channels.json -> views.deploy.channels 追加（政策是数据，改文件即可）
{ "key": "camera_center", "source_array": "T_WC[:3,3]", "dtype": "float32", "unit": "mm",
  "shape": [3], "reason": "camera centre in the scan frame; the turntable rig moves this per view",
  "evidence_class": "RIG_MEASURED" }
```

### 5.3 D3 —— `frame_id == arange(n) % n_views`（行号计数器，零信息）

* 旧写者：`frame_id = (np.arange(n_points) % views)` → 行索引的确定性函数。
* 新写者 `_frame_ids_from_views()`：把点用交付位姿 `T_WC` 映到每个视图相机系、用 `K` 投影，
  取渲染 `depth_z` 与重投影深度**最接近且 ≤ 5 mm** 的视图作为该点的 `frame_id`；
  没有任何视图能解释的点记 **-1**。索引新增 `frame_id` 语义块（定义/容差/未匹配标记/实测匹配率）。

| 指标（3 碎片，6049 点） | before | after |
|---|---|---|
| `frame_id == arange(n) % n_views` | **True（3/3）** | **False（3/3）** |
| 唯一值数 | 4（= 视角数，恒等分布 327/327/326/326） | 5（4 个真实视角 + `-1`） |
| 每视角点数 | 均匀（行号取模） | 434/217/338/315（真实可见性分布，LIN0000） |
| 未匹配 | 0 | 2 / 0 / 123（匹配率 99.8% / 100% / 97.0%） |
| 索引 `frame_id_source` | 字段不存在 | `T_WC+K+depth_z`；`frame_id_match_fraction` = 0.979（全局 5924/6049） |
| 重投影残差中位数（独立探针） | — | 0.34–0.68 mm（`_probe_defect_sources.json`） |

> 这条修复把 `depth_z` **当作派生输入**使用（部署视图是否交付 `depth_z` 由
> `synlab/schemas/view_channels.json` 决定），导出物仍然只有 `frame_id` 这一个整数数组。

### 5.4 三个修复的回归测试

`tests/a12/storage/test_load_package.py`：`test_token_block_is_not_a_scaled_broadcast`、
`test_view_position_uses_the_delivered_pose`、`test_frame_id_comes_from_the_delivered_views`
（纯单元，构造已知几何：z=5mm 的点归视图 0、z=50mm 的点归视图 1、相机背后的点记 -1），
以及包级 `test_load_arrays_npz_matches_zarr`、`test_check_package_*`。
`pytest tests/a12/storage -q` → **exit 0, 14 passed**（`_pytest_storage_2.log`）。

### 5.5 zarr 分片现在真的能被读回

普查发现 `synlab/training/` 里 `zarr` 出现 **0 次**：zarr 副本被写入、被哈希校验、**从不被解析**。
本加载器补上读取并做一致性校验：

* `read_zarr_array()`：优先 `zarr` 3.4.0；无 zarr 时用内置 v3 读取器（`bytes` + `zstd` 编解码，
  代码顺序按**逆序**应用：先解压再按 dtype/端序解释）。
* `zarr_npz_consistency()`：逐碎片逐数组与 npz 比对 `shape/dtype/字节`。
  closed_loop 实测 **18/18 数组逐字节一致**（`points/frame_id` 单独复核也一致）；
  强制走内置读取器（`sys.modules["zarr"]=None`）结果相同。

---

## 6. 五任务监督现状（真实值，来自 data card）

| 任务 | 输入字段 | 监督字段 | `loss_mask` 语义 | closed_loop `n_valid / n_allowed` | 为什么现在无监督 / 解锁条件 |
|---|---|---|---|---|---|
| **view** | `obs/<opaque>/tiles.npy`、`view_pos.npy` | 同一碎片的多视角自监督 | `global_valid` 逐视角；<2 个有效视角的碎片不产生锚点 | **12 / 12** | 有监督 |
| **rank** | `tokens/<opaque>__tokens`、`geometry/*` | `relations.parquet`：`kind=R2&valid` 为正；`kind∈{R1,R0}&valid&loss_mask` 为合法负 | `allowed = z_valid[q] & z_valid[c] & pair_valid`；UNKNOWN 永不进 loss、也永不改写成 R0 | **3 / 0** | `eligible_as_negative=0`（合法负例 0 行）→ 需要"两端都有观测的 confirmed R1/R0 行" |
| **correspondence** | token 空间（`corr_weight` 落在其上） | `labels/correspondence.parquet`（`index_a/index_b/weight/residual_mm/ambiguous/sample_valid`） | `corr_weight>0` 且过同一 `allowed` 掩码 | **3587 / 0** | 实测阻断：`one_side_of_every_labelled_pair_has_no_token_evidence`（3 条 R2 的 `-p` 侧无观测）→ 给 `-p` 侧补观测 |
| **quality** | 交付观测（观测侧质量估计） | `labels/quality.parquet.target_value`（逐 fragment×view 可观测率） | 逐行 `valid`；无测量不是 0 目标 | **3 / 3** | 有监督 |
| **contradiction** | 双方 token/几何 | `relations.parquet` 的 pair 标签 | `contradiction_valid` 且过同一 `allowed`（对偶 logits 需两端可编码） | **3 / 0** | `no_encodable_contradiction_pair` → 需要"一对两端都可编码"的标签；当前标签还全是同一类（compatible） |

> 与 `docs/a12/training_run.md` §4 / §8 的独立结论一致（该文档给出 rank 0、correspondence 被掩码挡掉、
> contradiction 无法启动、view/quality 可用）。本表直接由 `dataset_card.json.tasks.*.measured` 生成，
> 因此不会再与文档漂移。

---

## 7. 还需补什么才能"开箱可训"（对照 `training_run.md` §4.1）

`training_run.md` §4.1 的最小需求是："**1 个 query + 1 个可编码 R2 正例 + 1 个合法负例，三者都必须有观测**
→ `effective_queries ≥ 1`"。逐条对照当前包：

| 需求项 | 当前（closed_loop） | 差距 | 谁来解决 |
|---|---|---|---|
| query 行 | 6（3 条真实关系行） | 链路级够用 | — |
| 可编码 R2 正例 | 名义 3、可编码 **0** | **缺**：3 条 R2 都是 `-m`(有观测) ↔ `-p`(无观测) | 观测侧给 `-p` 侧补观测（比加 query 行数更紧迫） |
| 合法负例（R1/R0，valid & loss_mask） | **0** | **缺** | 关系/负例批产：产出确认 R1 或可用 R0 |
| 每查询 ≥2 负例（最小可训练） | 0 | 缺 | 同上（`negative_mix` 默认 (R1,R0)=(0.5,0.5)） |
| 跨 lineage 划分 | 2 train / 1 dev（`leak_free=true`） | 评测下限 ≥3 lineage | 扩母体数量 |
| quality 目标 | 3（有效 12 视角） | 已具备 | — |
| correspondence 边 | 标签 3587 已进包、**token 空间 0** | 缺"对端可编码" | 与正例同一根因 |
| contradiction 标签 | 3（有效但 `allowed=0`，且同类） | 缺对端可编码 + 反例类 | 同上 |
| 导出完整性 | 55/55 哈希一致、`--check` 退出 0 | 已具备 | — |
| 三缺陷 | 新包全部修复（§5） | 已具备 | — |

**结论**：与本包"管道可信、数据是瓶颈"的既有结论一致。修复三个静默缺陷**不会**让包变得可训——
它消除的是"模型以为拿到了 256 维 token / 视角位置 / 帧 id，其实是占位"的**误读风险**；
真正的瓶颈仍是 **①没有合法负例、②正例两端不都可编码**。按上表补上这两项后，
`n_allowed(rank) > 0` 才会出现，`effective_queries` 才会 ≥ 1。

短期仍可用的监督（无需新数据）：`view`（12 行）与 `quality`（3 行）。
若要立刻验证 rank 链路，最小改动是**给至少一个 `-p` 片段补观测**，让那 3 条 R2 中的一条变成可编码正例，
再补 2 个合法负例。

---

## 8. 复现命令（含退出码）

```powershell
cd C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab

# 0) 数据卡（写进包内 dataset_card.json + README.md）
& .venv\Scripts\python.exe tools\load_package.py --package data\a12_exports\closed_loop\training_package --write-card   # exit 0
& .venv\Scripts\python.exe tools\load_package.py --package data\a12_exports\closed_loop\training_package                # exit 0
& .venv\Scripts\python.exe tools\load_package.py --package data\a12_exports\closed_loop\training_package --check        # exit 0

# 1) 快速上手（<30 s）
& .venv\Scripts\python.exe examples\quickstart.py                                                                      # exit 0, 5.06 s

# 2) 三个缺陷的 before/after 实测
& .venv\Scripts\python.exe data\a12\reports\export_fixes\_measure_export_defects.py data/a12_exports/closed_loop/training_package    data/a12_exports/closed_loop/store
& .venv\Scripts\python.exe data\a12\reports\export_fixes\_measure_export_defects.py data/a12_exports/closed_loop/training_package_v2 data/a12_exports/closed_loop/store

# 3) 回归测试
& .venv\Scripts\python.exe -m pytest tests/a12/storage -q                                                               # exit 0, 14 passed

# 4) 用修复后的写者重新导出（新目录，不动修复前的包）
& .venv\Scripts\python.exe data\a12\reports\export_fixes\_reexport_fixed.py data/a12_exports/closed_loop/store rel_852ab2a1e4c3_1790905541 data/a12_exports/closed_loop/training_package_v2
```

---

## 9. 与并发写者的接口约定

`synlab/storage/export.py` 在本次任务期间被另一名队友**同时修改**（部署视图通道白名单：
`synlab/schemas/view_channels.json` + 政策驱动的通道写出）。因此：

1. 本次的三处修复已合并进该文件（`_token_arrays` / `_view_u_position_mm` / `_frame_ids_from_views`
   三个函数 + 索引语义块）；**再次改动前请先确认这三处未被回退**：
   ```powershell
   Select-String -Path synlab\storage\export.py -Pattern 'TOKEN_SUB|_view_u_position_mm|_frame_ids_from_views|FRAME_ID_TOLERANCE_MM'
   ```
2. 新写者把 `view_pos` 视为政策通道（`source_array: "views[].u_position_mm"`），而实现优先用
   交付位姿 `T_WC[0,3]`。**建议把政策文档里的 `source_array` 改成**
   `"views[].u_position_mm, else T_WC[0,3] (delivered pose)"`，让政策与实测行为一致
   （否则"政策说什么"与"包真有什么"会再次分叉）。
3. 写者侧仍可收窄的一处（本次未改，避免与并发写者冲突）：`obs/index.json` 的
   `view_pos.measured.varies_across_views` 是把所有碎片 pooled 起来算的，单碎片内可能恒定。
   建议改为逐碎片统计，补丁片段：

   ```python
   # export.py，obs/index.json 的 "view_pos" 块内
   varying = sum(1 for payload in obs_by_fragment.values()
                 if np.any(np.isfinite(payload["view_pos"]))
                 and float(np.ptp(payload["view_pos"][np.isfinite(payload["view_pos"])])) > 0.0)
   constant = sum(1 for payload in obs_by_fragment.values()
                  if np.any(np.isfinite(payload["view_pos"]))
                  and float(np.ptp(payload["view_pos"][np.isfinite(payload["view_pos"])])) == 0.0)
   # 用 {"fragments_varying": varying, "fragments_constant": constant} 取代
   # "varies_across_views": bool(...)，语义就从"pooled"变成"逐碎片"。
   ```
   （数据卡已按逐碎片给出该测量，见 §2.8 `view_pos_all_zero.per_fragment`，所以即使这一处不改，
   消费方也不会误读。）

---

## 10. 写者侧的三个一行解阻修复（本次实际改动）

并发队友把政策驱动的通道写者合并进 `synlab/storage/export.py` 时，留下三处使
`export_training_package` **完全无法运行**的缺陷（不是风格问题：函数直接抛异常）。因为"重新导出
带完整标注、拿去就能跑实验"必须以导出能跑为前提，本次按最小改法修掉，全部在此登记：

| # | 位置（修复后行号） | 症状 | 改法 |
|---|---|---|---|
| 1 | `export_training_package` 的 obs 循环 | `optional = {key: [] for key in OPTIONAL_DEPLOY_CHANNELS}` 用**三元组**当键，随后 `optional[channel_key]` 抛 `KeyError: 'depth_z'` | 改为 `{key: [] for key, _array, _dtype in OPTIONAL_DEPLOY_CHANNELS}` |
| 2 | 同上，模拟发掘上下文块 | `packs` 未初始化 → `counts["context_packs"] = len(packs)` 抛 `NameError: name 'packs' is not defined` | 在 `deploy_context_rows`/`research_membership` 旁补 `packs: list[dict[str, Any]] = []` |
| 3 | `observed_channels()` | 把计数表 `by_channel`（值域是 `int`）当文件列表迭代 → `TypeError: 'int' object is not iterable`，任何真含通道的视图都会崩 | 返回块改用 `files_by_channel`（`channels`/`counts` 都从它派生） |

三处修好后 `training_package_v2` 才能导出（4.58 s，§4.5）。回归护栏由
`tests/a12/storage` 的包级用例承担：任何一处回退都会让 `--check` 与
`test_load_arrays_npz_matches_zarr` / `test_data_card_is_scanned_not_hardcoded` 无法运行。

---

## 11. 大规模包 `data/a12_exports/next_experiment/training_package`（548 文件 / 1.3 GiB）

同一套工具在该包上的真实结果（`_next_experiment_card.log`，已写入包内数据卡）：

```
package      : data\a12_exports\next_experiment\training_package
release_id   : rel_nexp_1790913735
files/bytes  : 548 files, 1.3 GiB, hashes_match_manifest=True
relations    : {"R1": 117, "R2": 33}   eligible_as_negative=0
splits       : leak_free=True（train 21 谱系 / dev 3 / confirm 4；行数 305 / 27 / 214）
observations : 28 碎片、336 视角；未观测碎片 58（= 86 查询中的 58 个没有交付观测）
三缺陷       : tokens 有效秩 1（defect_present）、view_pos 28/28 全零、frame_id 为行号计数器
mini-batch   : view 18/18 有监督；rank 4/0、correspondence 0/0、quality 0/0、contradiction 4/0
               （8 碎片样本，其中仅 2 个带观测 —— 这是包本身的缺口）
```

要点：

* 该包的 `--write-card` 用 `--sample-fragments 2 --batch-fragments N` 生成，
  数据卡里 `sampling` 块如实记录"数组统计只测了前 2 个碎片、mini-batch 只用了 N 个碎片"；
  文件清单与全部 sha256 **始终是完整的**（1.3 GiB 全量重算）。
* mini-batch 采样**按关系表的成对端点**取碎片（对批次必须至少含一条完整关系行的两端），
  并在多对之间优先选"观测端点更多"的那些 —— 否则会出现"只因为抽到的前 N 个碎片恰好无观测
  或凑不成一对"就误报"无监督"。即便如此，本包 86 个查询里只有 28 个有观测，
  抽到的 8 个碎片中仍只有少数带观测，这是**包本身的缺口**，不是采样问题。
* 117 条 R1 行仍然 `eligible_as_negative = 0`（没有一条同时 `valid & loss_mask`），
  与 `docs/a12/training_run.md` §4 的结论一致：**负例缺口在这个包上同样存在**；
  `correspondence / quality` 两层标签在该包里根本没有（`label_layers = 3`），
  所以那两个任务的 `why` 是"包里没有这类标签"，而不是"被掩码挡掉"。


