# A12 small-but-unstarted defects: per-item close-out (S1-S11)

Every section below is written **after** the item was reproduced, fixed and verified, and records
the real command, its exit code and the measured numbers.  Nothing here is a projection.

Scope discipline: `synlab/fracture/**`, `synlab/observe/**`, `configs/a12/next_experiment.yaml`,
`frontend/**` and `data/a12/**` (except reports) were not modified.

---

## S1 · correspondence 标签投影到 token 空间

**Status: 部分完成（token 映射实现并验证；本发布版 0/9 对可同时定位 → 加载器仍为 0，阻塞点已用实测数字锁定）**

### 问题复现（真实数字）

`research/labels/correspondence.parquet` 有 3299 行（不是任务书里的 3587，见下），
`PackageLabelSource.correspondence_for()` **无条件 `return None`**，所以
`batch.corr_weight` 恒为 0，`correspondence n_allowed = 0`。

两个独立的真实缺陷：

1. `correspondence_for()` 在每一行标签上读 `row["positives"]` / `row["negatives"]` ——
   这两列**在导出的标签表里根本不存在**（表按 `fragment_a`/`fragment_b` 键）。因此
   `wanted` 集合恒为空，`labelled` 恒为空，任何包都不可能得到对应监督。
2. 导出侧唯一的定位字段是 `corr_index_a` / `corr_index_b`，而这两个数组**不是位置**：
   实测 `np.unique(corr_index_a) == [0]`、`np.unique(corr_index_b) == [1]`（552 行全部如此），
   即它们是"这一对的两个端点 id"，不含任何逐样本几何信息。

`export_guide.md` 记的 3587 行 / `n_allowed=0` 属于更早的一次导出；当前 `trainable` 包实测
`correspondence_samples = 3299`、`correspondence_pairs = 4`。

### 真实的逐样本几何是什么（实测）

| 检查 | 结果 |
|---|---|
| `corr_point_a` == `iface_points_a` | 逐元素相等（max 0），`\|corr_point_a - corr_point_b\|` 中位数 7.1e-15 mm |
| 由 (`corr_face_a`, `corr_bary_a`) 重建顶点 | 与 `corr_point_a` 差 max **4.26e-14** mm |
| `corr_bary_a` 在三角形内 | **552/552** 全部在 [0,1]，和 = 1 |
| 点到自身面平面距离 | 中位数 3.8e-15 mm |

结论：`corr_point_*` 是**真实的面片采样点**（face + barycentric 可完全重建），
`corr_face_*` 指向 fragment mesh 的面。`corr_index_*` 只是端点簿记。

### 实现

`synlab/storage/export.py` 新增（供完整导出与工具共用）：

* `_correspondence_token_rows(store, relations, obs_of_fragment)` —— 逐对产出
  `token_a` / `token_b` / `token_view_a` / `token_view_b` / `token_pixel_a` / `token_pixel_b` /
  `token_valid` / `token_reason`，并给出 `samples_mapped`、`unmapped_reason_histogram` 等 prov。
* `_locate_samples_in_token_grid()` / `_project_samples_into_view()` —— **逐视图向量化**投影
  （原标量写法实测 0.6 s/100 样本，一发布要几分钟；向量化后一对 552 样本 = 12 次投影）。
* `load_projection_arrays()` —— 只按键读 `K/T_WC/depth_z/id_map/roi/deployment_mask/uncertain_mask`。
  完整 `load_arrays` 会把 59 个观测资产各 ~270 MB 全部读入（≈16 GB，宿主直接杀进程；实测触发）。

判定条件（三项同时成立），token 索引 = `(block_row*4 + block_col)*3 + channel`，
每视图 48 个 token、`TOKEN_BLOCK = 4`：

1. **面身份**：`id_map[v, u] == corr_face`（渲染 `id_map` 是逐面标签，这是精确身份检验，不是阈值）；
2. `roi`/`deployment_mask` 接受该像素、`uncertain_mask` 不接受；
3. 重投影深度与渲染 `depth_z` 差 ≤ 5.0 mm（`FRAME_ID_TOLERANCE_MM`），且像素落在池化网格内。

`synlab/training/labels.py::correspondence_for()` 改为读该 token 定位表并真正构造
`{"rows", "cols", "weights"}`（供 `_corr_tensors` 消费），并按实测原因分档报告 blocker。

工具：`tools/a12_corr_token_map.py`（对既有包重算标签表，免 3.3 GB 重导出）。

### 验证

```
.venv\Scripts\python.exe tools\a12_corr_token_map.py \
  --package data\a12_exports\trainable\next_experiment\training_package \
  --store data\a12_trainable\store --json data\a12_reports\s1_corr_token_dryrun.json
```
退出码 **0**。实测（`data/a12_reports/s1_corr_token_dryrun.json`）：

| 项 | 值 |
|---|---|
| 监督对 `pairs_supervised` | 53 |
| 带 corr_* 的对 `pairs_with_correspondence` | 18 |
| 标签行 | 17001 |
| 一侧可定位 | **2750** |
| 两侧都可定位 | **0** |
| `label_row_invalid` | 4 |
| `neither_side_has_token_evidence` | 14247（其中 **10614** 条的 reason 命中下述阻塞） |

**面身份检验在"对得上"的一侧非常干净**（`_locate_samples_in_token_grid` 实测）：

| 谱系 | 样本 | -m 定位 | -p 定位 | 两侧 | 已定位样本深度残差中位数 |
|---|---|---|---|---|---|
| LIN0001_V21_M06_PAT16 | 577 | 185 | 0 | 0 | — |
| LIN0002_V23_M11_PAT06 | 2836 | 0 | 0 | 0 | — |
| LIN0005_V03_M11_PAT16 | 854 | 52 | 0 | 0 | — |
| LIN0006_V09_M09_PAT03 | 960 | 0 | 149 | 0 | — |
| LIN0008_V08_M08_PAT05 | 1631 | 0 | 0 | 0 | — |
| LIN0009_V04_M01_PAT02 | 552 | 0 | 5 | 0 | 3.09 mm |
| LIN0010_V07_M10_PAT08 | 897 | 0 | 334 | 0 | **0.40 mm** |
| LIN0012_V03_M02_PAT01 | 629 | 0 | 23 | 0 | 0.40 mm |
| LIN0013_V11_M02_PAT07 | 1221 | 442 | 0 | 0 | **0.49 mm** |

→ 9 对里 **0 对**两侧同时可定位，总两侧样本数 **0**。

### 阻塞点（已定位到具体机制，非"不可编码"泛论）

每一对都**恰好一侧**能定位、另一侧恒为 0：

| 谱系 | 侧 | mesh 面数 | `id_map` 标签数 | 标签超出 mesh 面数的个数 | corr 面出现在 id_map |
|---|---|---|---|---|---|
| LIN0009 | -m | 3660 | 21774 | **21373** | 148/529 (28.0%) |
| LIN0009 | -p | 3752 | 1667 | 0 | 346/528 (65.5%) |
| LIN0010 | -m | 5864 | 17158 | 11315 | 88/828 (10.6%) |
| LIN0010 | -p | 5482 | 3723 | 0 | 775/840 (92.3%) |
| LIN0013 | -m | 6138 | 4347 | 0 | 1020/1147 (88.9%) |
| LIN0013 | -p | 6254 | 55486 | **53480** | 413/1159 (35.6%) |

不成立的说法（已排除）：
* **不是"一侧没有观测"**：本店 18 个谱系**全部**同时观测了 `-m` 与 `-p`（实测
  `lineages with BOTH -m and -p observed: 18, one-side only: 0`）。
* **不是常数面索引偏移**：对 LIN0009 扫 ±400 偏移，最佳覆盖率 0.293（恒等 0.280），无解。
* **不是"两块只沿细缝接触"**：两片点云最近邻中位数 33–56 mm（互相独立），
  所以遮挡不是主因。

机制：**渲染 `id_map` 的 `face_id` 空间与 `corr_face_*` 所指的 fragment mesh 面索引空间
在一侧不一致**。`render.py` 写入的是 `scene.face_id[f]`（渲染场景的面 id），并不保证等于
fragment mesh 资产的行索引；`-m`（或 LIN0013 的 `-p`）那侧的标签最大值远超 mesh 面数，
说明渲染用的是**另一份（更密的）几何**。两侧点云还相距 ~50 mm，说明该侧观测确实来
自与对应 mesh 不重合的实体。

**解锁条件（二选一，均在 `synlab/observe/**`，本轮被并发纪律冻结，未改）**

1. 渲染侧把 `scene.face_id` 写成 **fragment mesh 的行索引**并随资产记录该映射
   （或直接导出 `face_id` 数组），使 `id_map` 与 `corr_face_*` 同空间；或
2. 让同一 cut event 的**两片用同一份几何来源**（同一 mesh 资产）渲染。

修好后本实现即可直接产出两侧定位（对得上的一侧已有 396/505 个样本、残差 0.4–0.5 mm 的
实证），`n_allowed` 会立即变正；**无需**再改训练侧。

### 仍未解决

* `correspondence n_allowed` 仍为 **0**：本发布版没有任何一对两侧同时可定位（0/9）。
* 未伪造任何对应关系：不可投影的样本一律 `token_valid=false` 并带 `token_reason`。
* 未在 `data/a12_exports` 上执行 `--write`（不覆盖别的队友正在用的包）；工具已具备该能力。

---

## S4 · 部署视图表列声明（`bag_id`）

**Status: 完成（`features_carry_answer_fields` 由 1 个 hit 降到 0；反例测试证明豁免只有 `bag_id` 一个名字）**

### 问题复现（真实数字）

策略文件只声明了**通道**（`capture_context_fields`），没有声明**表列**。而扫描器的输入是
"写出的每个容器里的每个 key"，parquet 的列名同样在内：

```
包   : data\a12_exports\trainable\next_experiment\training_package
视图 : deploy
扫描 : 504 个容器 / 168 个 unique key
豁免集为空（修复前）: answer hits = 1  ->  {'bag_id': 1}
```

`deploy/queries.parquet` 的列：`query_id / lineage / mother / fragment / gallery /
historical_N_G / status / has_observation / context_id / batch_id / bag_id / stratum_id /
excavation_area_id / applicability` —— `bag_id` 命中 `roles.FORBIDDEN_FEATURE_FIELDS`。

一个必须说清的事实：`lineage` / `mother` / `status` **不是**
`FORBIDDEN_FEATURE_FIELDS` 的成员（该集合用的是 `lineage_id` / `mother_id`），所以本包
deploy 视图里唯一真正命中的就是 `bag_id`——这也解释了为什么修掉它以后 hit 数正好归零。

### 改法

1. `synlab/schemas/view_channels.json` 新增 `table_columns` 块，声明

   ```json
   {"key":"bag_id","table":"deploy/queries.parquet","evidence_class":"capture_context",
    "rig_obtainable":true,"claim_allowed":true}
   ```

2. `synlab/storage/export.py::_resolve_capture_context()` 改为**同时**校验
   `capture_context_fields.fields` 与 `table_columns.columns`，两者过**同一套**准入规则
   （`evidence_class=capture_context` + `rig_obtainable=true` + `claim_allowed=true`，且名字
   不得落在 `TRUTH_CRITICAL_FIELDS | research_only | TRUTH_BEARING_FIELDS` 内，否则
   `load_channel_policy` 直接抛 `LEAKAGE_DETECTED`）。两个块的条目都进
   `capture_context_keys`，所以"减去策略声明的捕获上下文名"这一步**自动**同时减去表列声明。
3. `capture_context_scan` 现在记录 `declaration_blocks_used`、逐条 `declarations`（含
   `declared_in` 与 `table`），使豁免可审计。

### 验证

```
.venv\Scripts\python.exe -m pytest tests/a12/storage/test_s1_s4_smallfixes.py -q
```
退出码 **0**（18 passed）。

真实包重扫（同一个 `scan_view_fields` 结果喂给两种豁免集）：

| | 豁免集 | 扫描容器 | answer hits | capture hits |
|---|---|---|---|---|
| before | `{}` | 504 | **1**（`bag_id`） | 0 |
| after | `{"bag_id"}` | 504 | **0** | 1（`bag_id`） |

→ `features_carry_answer_fields = false`。

反例测试（`test_answer_field_scan_clears_bag_id_but_keeps_every_other_forbidden_name`）：
构造 `deploy/relations.parquet` + `research/labels/*.parquet` 同时含 `bag_id`、10 个真实
`FORBIDDEN_FEATURE_FIELDS` 成员、以及 `kind`/`loss_mask`/`eligible_as_negative`，断言

* `bag_id` 进 capture（2 次命中，两个容器各一次）、不在 hits；
* 其余 13 个名字**全部仍命中**；
* `effective_answer_fields` 恰为 `FORBIDDEN_FEATURE_FIELDS - {bag_id}`。

真值通道/`corr_*`/`iface_*` 由另一组测试逐名守护
（`test_truth_critical_channels_stay_out_of_any_declaration`）：`id_map`/`T_WC`/
`corr_weight`/`corr_point_a`/`iface_id`/`surface_tag`/`clean_truth`/`visible_labels`
每一次尝试声明都会让策略加载失败并报出该名字。注意口径：这些名字**不在**
`FORBIDDEN_FEATURE_FIELDS` 里（那张表管的是"能否进模型前向"），拦住它们的是通道策略 +
`TRUTH_CRITICAL_FIELDS`，报告里已按此表述，没有把两件事混为一谈。

### 仍未解决

* 未重新导出（3.3 GB）；结论来自对**已写出包**的同一扫描函数重算，`export.py` 的导出路径
  也走同一函数，逻辑一致。
* `lineage`/`mother`/`status` 仍在 deploy 表里且不被扫描命中——它们不是
  `FORBIDDEN_FEATURE_FIELDS` 成员，属于"答案侧分组"的既有口径问题，不在本项范围。

---

## S6 · `negfix` / `full` 包补数据卡

**Status: 完成（两个包都写出卡，`--check` 退出码 0）**

### 改法

* `negfix`：`tools/load_package.py --write-card`（既有能力，未改）。
* `full`：`tools/load_full_package.py` **此前没有写卡能力**，新增 `--write-card`：
  `build_card()` 从 manifest + 磁盘扫描组装，`render_card_readme()` 产出 markdown。
  markdown 落 **`DATASET_CARD.md`**（不是 `README.md`）：`README.md` 由
  `synlab/storage/export_full.py::render_readme` 从 manifest 生成，卡写入器不得覆盖别的写入器
  拥有的文件（这一点是实测踩出来的：第一版覆盖了手写 README，已用 `render_readme` 原样重建）。
* `synlab/storage/export_full.py::check_full_package()` 增加 `READER_ARTIFACTS`
  （`dataset_card.json` + `DATASET_CARD.md`）：它们是**读者产物**，按已声明处理且不参与哈希比对。
  不加这一步，"写卡"这个动作本身会把一致性判定从 0 变成 3（实测）。

### 验证

```
.venv\Scripts\python.exe tools\load_package.py --package data\a12_exports\negfix\next_experiment\training_package --write-card
  -> 退出码 0；写 dataset_card.json + README.md + data/a12_reports/s6_negfix_card.json
.venv\Scripts\python.exe tools\load_package.py --package ... --check
  -> 退出码 0
     [PASS] file_set: declared 1276 / on_disk 1279 / missing [] / unexpected_extra []
     [PASS] sha256: checked 1276 / mismatched []
     [PASS] column_dictionary: tables 7 / problems []
     [PASS] splits: leak_free true; train 4924 行 / 16 lineages / 71 fragments

.venv\Scripts\python.exe tools\load_full_package.py --package data\a12_exports\full --write-card
  -> 退出码 0；写 dataset_card.json + DATASET_CARD.md
     modalities present 48/87, missing 39
.venv\Scripts\python.exe tools\load_full_package.py --package data\a12_exports\full --check
  -> 退出码 0（修复前后对比：未登记卡时 3，登记后 0）
     files_declared 898 / files_on_disk 898 / problems []
```

`negfix` 卡里同时如实记下了 S1 的状态：`correspondence n_valid 3299 / n_allowed 0 /
why = surface_sample_to_token_mapping_is_not_in_the_label_table`——这正是卡应该暴露的东西。

---

## S10 · `u_position` 口径冲突

**Status: 完成（profile 侧 `max_travel_mm` 修正为契约值 150；并查明"实测最大"其实不是行程量）**

### 问题复现（真实数字）

三个口径互相矛盾：

| 来源 | 值 | 含义 |
|---|---|---|
| `configs/a12/capture_contract.json#mechanics.u_axis_near_far`（t052） | `travel_mm_nominal = 150`，`reserved [100, 200]` | 扫描台 U 导轨行程 |
| `synlab/degrade/specs.py::u_rail_travel_mm` | `150.0`（DOCUMENTED, p530，硬门） | 同上 |
| `configs/a12/camera_profiles.json` | `max_travel_mm = 120.0`（3 个 profile 全部） | ← 与上面冲突 |
| `synlab/cameras/profiles.py::_TIER_SPECS`（真正被 `transform_profile_u` 拒的） | GLOBAL `[-100,-40]` / MID `[-30,30]` / LOCAL `[40,70]`，并集 span **170 mm** | 每档窗口，不是导轨行程 |

`max_travel_mm = 120` 其实等于三个标称锁位的**跨度**（0/60/120），不是行程。把它当行程读，
127.12 mm 就成了"超程"。而 127.12 mm 本身在 150 mm 行程内 → **profile 值过小**。

### 实测（读真实包的 `deploy/obs/*.tar` → `view_pos.npy`）

```
trainable 包: 708 views, signed range [-136.32, 335.12] mm
             travel reading   span   = 471.44 mm
             absolute reading absmax = 335.12 mm
negfix   包: 同上（同一批观测）
```

471.44 mm ≫ 150 mm，两者都不成立 → 必须继续查"127.12 到底是不是行程量"。

### 关键发现：`view_pos` 根本不是滑架坐标

`export.py::_view_u_position_mm` 的定义是 `view_pos := T_WC[0, 3]`。但 `T_WC` 的构造
（`synlab/cameras/viewframes.py`）是 `T_WC[:3,3] = center + [0,0,distance]` 再乘一个姿态抖动，
`T_WC[0,3]` 是**相机中心在扫描系里的 X 分量**，随视角朝向变化。实测（同一次观测、metadata 声明
单一 profile `CAM_MID_V3`、工作距离恒为 220 mm）：

```
camera-centre spread  x = 145.82 mm   y = 168.38 mm   z = 14.86 mm
```

同一个 fragment、同一个工作距离下 X 摆 145.82 mm —— 这是**帧几何**，不是行程。所以：

* profile 的 `max_travel_mm=120` 确实过小（契约是 150）→ **已修**；
* 而"实测最大 127.12 mm"（以及 335.12 mm）**不是行程量**，它既不能证明也不能否证超程。
  真实滑架读数不存在（无编码器），这一点 `precision_audit.md` §6.2(e) 已经写明"误差 = missing"。
* 因此本轮**没有**把 471.44 mm 判成"超程"：那是把一个通道定义缺陷记到机械账上。

### 改法

`configs/a12/camera_profiles.json`：

* 三个 profile 的 `max_travel_mm`：`120.0 → 150.0`（契约 t052 的 nominal）；
* 新增 `travel_limits` 块，写明 150 / reserved `[100,200]` 及其来源，
  并说明 `max_travel_mm` 曾被误当成行程、以及**真正被强制**的是
  `profiles.py::_TIER_SPECS`（本轮未动，改它会改变可达工作距离 ⇒ 改数据，属另一项决策）。

新驱动 `tools/a12_u_travel_check.py`：一次打印三个口径 + 实测，并给出**两种读法**（`span` 与
`absmax`），再用 `frame_geometry_evidence` 判定这个通道到底是不是滑架坐标。

### 验证

```
.venv\Scripts\python.exe tools\a12_u_travel_check.py --json data\a12_reports\s10_u_travel.json
```
退出码 **0**。

```
contract      : nominal 150 mm, reserved [100, 200] (t052)
profiles      : declared nominal 150.0 mm; max_travel_mm=[150.0]
enforced tiers: union travel [-100.0, 70.0] (span 170.0 mm)
measured      : trainable / negfix 包 708 views, span 471.44 mm, absmax 335.12 mm
                reads as a slide coordinate: False
                  declared working distance [220.0] mm; camera-centre spread
                  x=145.82 y=168.38 z=14.86 mm
OK: the declared limits agree with the contract, and no measured span is a travel statement
```

### 仍未解决

* `precision_audit.md` §6.2(e) 记的"127.12 mm > profile 120"这一条，本轮结论是
  **profile 侧错、且该数字不是行程量**；两份文档的口径已按契约统一到 150 mm。
* 真正的滑架行程**没有被测量过**（合成侧无编码器、无实测滑架位置）：`view_pos` 与实测位置之差
  仍是 `missing`。要闭合它需要真机标定或编码器读数，不在本仓库能力内。
* `profiles.py::_TIER_SPECS` 的三档窗口（并集 170 mm）与契约 150 mm 也不完全对齐；本轮只记录，
  未改——动它会改变可采样的工作距离，也就是改变已产出的数据。

---

## S7 · quality 监督样本量

**Status: 完成（加载器不再写死零；`FeatureBundle.quality` 由空变成真实通道）**

### 问题复现（真实数字）

`synlab/qc/loader_probe.py::_observed_payload` 对**每个** fragment 写死：

```python
"quality": np.zeros((1, 1), dtype=np.float32),
"quality_valid": np.zeros((1, 1), dtype=bool),
```

所以 `FeatureBundle.quality`（模型质量头真正读的张量）恒为零。而"观测的 OBS_EST 质量通道"
**从来没有缺失**：`data/a12_trainable/store` 的 `obs_result` metadata 里有 18 个
`meta["quality"]` 条目，其中 **15 个** `source_kind = OBS_EST`、`estimator_version = obs_est.v1`。
它们只是**没有进包**，加载器也就无从读起。

口径也需要说清：D 任务的**目标**（`quality n_valid/n_allowed = 3 / 3`，
`docs/a12/training_run.md` §7）走的是**标签侧** `research/labels/quality.parquet`
（`PackageLabelSource.quality_target_for`），和这里修的**特征输入**是两条不同的路径。
`_observed_payload` 填的是 `features.quality`，`build_training_batch` 在**没有**显式
`quality_target=` 时把它当作目标（`batch.py:411-414`）——那条路径修好之前恒为零。

### 改法

1. `synlab/storage/export.py::_observation_quality_index()`：把 `obs_result.meta["quality"]` 里
   `source_kind == OBS_EST` 且 `valid is True`、数值有限的通道抽出来，按**通道名排序**固定顺序，
   写成 `deploy/obs/index.json` 的 `quality_research` 块（`rows` 按 fragment）。
   只取 OBS_EST：oracle/真值派生的数字**不是**模型输入。
2. 该块是 **research 兄弟块**，不动 `rows` 的既有形状（别的测试/工具依赖它），也不放进部署分片——
   部署视图的答案字段扫描因此永远看不到它。
3. `TrainingPackage.observation_quality(fragment_id)`：读该块；返回 `None` 表示"该 fragment 没有
   测量"，绝不表示"测量值等于 0"。
4. `synlab/qc/loader_probe.py`：新增 `_quality_row()`，把真实通道装成 `[1, C]`；
   没有测量时返回 `valid=False` 的**单槽掩码行**并带原因（"未测"与"测到 0"保持可区分）。

### 验证

端到端（真 store → 真 export → 真 loader），用 `data/a12_exports/closed_loop/store`
（3 个 obs_result，各 14 个 OBS_EST 通道）：

```
.venv\Scripts\python.exe -m pytest tests/a12/qc/test_s7_observation_quality.py -q
```
退出码 **0**（5 passed）。测试内部**真的重新导出**一个小包（实测 2.0 s），不是手搭 payload。

导出侧实测：

| 项 | 值 |
|---|---|
| `quality_research` 块存在 | True |
| 通道数 | **14**（`blur_laplacian_min` … `view_coverage_mean`） |
| `estimator_version` | `['obs_est.v1']` |
| `fragments_with_quality` | **3 / 3**（无缺失） |
| 例（LIN0000…-m） | 前 3 通道 = 24790.2358 / 26319.8934 / 0.8988 |

加载器 before/after：

| | `FeatureBundle.quality` 形状 | `quality_valid` 求和 |
|---|---|---|
| **before**（旧 loader 写死的 `zeros((1,1))`） | `(3, 1, 1)` | **0** |
| **after**（读包内真实通道） | `(3, 1, **14**)` | **42** |

`n_valid / n_allowed`：本项的分母不是"标签行数"而是**特征通道槽位**——
`n_valid = n_valid_allowed = 42`（`3 × 1 × 14`），此前为 `0`。
标签侧 D 任务目标维持 `3 / 3` 不变（有 pin 测试守着，本轮未动）。

`probe_training_package()` 对新包返回 `ok = True`、`files_ok = True`。

### 仍未解决

* 旧包（`data/a12_exports/**` 里已写出的那些）**没有** `quality_research` 块，加载器对它们仍返回
  单槽掩码 + 原因 `the package carries no observation-quality block (written before the S7 fix)`。
  这是"未测"而不是"测到 0"，是正确行为；要让旧包也有真实通道需要重新导出（本机可做，但会覆盖
  别的队友正在用的包，未执行）。
* `data/a12_trainable/store` 的 15 个 OBS_EST 通道里，`roi_coverage_mean` 实测为 0.0（真实测量值，
  非缺省）；它作为合法 0 值参与，不是 bug。
* 未改 `tools/load_package.py` 的数据卡列语义表（`QUALITY_TARGET_CHANNEL` 仍指标签侧通道）
   ——那里描述的是 D 任务目标，与本项的特征输入不是同一件东西。
