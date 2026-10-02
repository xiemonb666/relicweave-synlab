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

---

## S5 · `mask_semantics` 落库

**Status: 完成（缺口定位到 `visible_labels`；提交边界加戳 + 门禁收口 + 普查脚本）**

### 问题复现（真实数字，先纠正任务书的一个前提）

任务书写"三代 store 的资产 meta 里 `mask_semantics` 全是 None"。**实测不是全 None**：
`data/a12_trainable/store` 463 个资产里 **115 个** 已经带 `mask_semantics = coc_units_v2`，
`data/a12_campaign/store` 167 个里 **87 个** 带。真实缺口更精确：

```
store: data\a12_trainable\store
  assets 463  values {'coc_units_v2': 115, '<missing>': 348}
    feature_bundle     total=  59 current=  12 legacy=  0 missing=  47
    fragment_mesh      total= 113 current=  54 legacy=  0 missing=  59
    label_bundle       total=  64 current=   5 legacy=  0 missing=  59
    mother_mesh        total=  18 current=  18 legacy=  0 missing=   0
    obs_result         total=  68 current=  21 legacy=  0 missing=  47
    provenance         total=   5 current=   5 legacy=  0 missing=   0
    visible_labels     total=   9 current=   0 legacy=   0 missing=   9   <-- 关键
```

`visible_labels` 是 **0/9** 带戳 —— 而它恰恰是**从交付的掩膜通道**
（`uncertain_mask` / `deployment_mask` / `id_map`）算出来的层，两代 `coc_units` 语义相差实测
`D * N = 74.105` 倍。也就是说：**含义最依赖这个标记的层，是唯一一个从来没写过它的层**。
`visible_labels` 一直被列在 `MARKER_FREE_ROLES`（"结构上无法携带标记"），而 `pipeline.py`
提交它时确实没加戳。

另外 348 个 `<missing>` 是**修复前几代**的真实状态（`docs/a12/data_semantics_versions.md` §3：
"没有这个键"本身就是旧代的判据），不是本项要"补写"的对象——**已写出的资产不能追溯改 meta**
（会破坏 `blob_hash`/审计链），本项修的是**此后每个新资产**。

### 改法

1. `synlab/pipeline.py` 新增 `_stamp_data_semantics(obj)`：把 `data_semantics()`
   （`mask_semantics` / `damage_semantics` / `subset_instrument` / `defined_in`）写进对象的
   `meta`，**已声明的不覆盖**（`setdefault`），非 mapping 参数原样返回（与
   `_stamp_obs_semantics` 同样的容错契约）。
2. `pipeline.py` 在提交 `visible_labels` 的**提交边界**调用它（`update_visibility_truth` 之后、
   `commit_truth` 之前），所以这一层的任何生产者都自动带上标记。
3. `synlab/qc/data_quality.py`：
   * `DATA_SEMANTICS_ROLES` 加入 `visible_labels`（门禁开始**检查**它）；
   * `MARKER_FREE_ROLES` 移除 `visible_labels`（它不再"结构上无法携带标记"）。
   副作用是可验证的：`semantics.mask_semantics` 分母由 **327 → 336**（+9 个 visible_labels）。
4. 新增 `tools/a12_mask_semantics_census.py`：按 `meta["mask_semantics"]` 分组统计，
   给出 `current / legacy / missing / other` 四桶 + 逐角色表 + 门禁自己的判定，并打印可复用 SQL：

   ```sql
   select role, json_extract(meta_json, '$.mask_semantics') as generation, count(*)
   from assets group by 1, 2
   -- '<missing>' = 修复前代（键不存在），永远不当作 current
   ```

### 验证

```
.venv\Scripts\python.exe tools\a12_mask_semantics_census.py --store data\a12_trainable\store \
    --json data\a12_reports\s5_mask_semantics_census.json
```
退出码 **0**。实测输出（节选）：

```
  assets 463  values {'coc_units_v2': 115, '<missing>': 348}
  current  = coc_units_v2
  legacy   = coc_units_v1_pixel_units
    visible_labels     total=   9 current=   0 legacy=   0 missing=   9  -> carries marker: False
    gate semantics.mask_semantics: FAIL (115/336)
```

分母 336 = 327 + 9，正是 `visible_labels` 被纳入门禁的那 9 个；它们**至今仍是 missing**，
如实反映"已写出的资产没有被追溯改过"。

```
.venv\Scripts\python.exe -m pytest tests/a12/qc/test_s5_mask_semantics.py -q   -> 退出码 0
```
测试断言：`visible_labels` 现在既在 `DATA_SEMANTICS_ROLES` 又在 `MARKER_ROLES`、不在
`MARKER_FREE_ROLES`；`_stamp_data_semantics` 写入的正是 `coc_units_v2`；**已声明的版本不被覆盖**；
非 mapping 参数不炸；两代值可区分。

### 仍未解决

* **没有**（也不应该）回填已写出资产的 meta：那会改 `blob_hash` 与审计链。旧资产保持
  `<missing>`，由普查脚本按"键不存在 = 旧代"判定，`docs/a12/data_semantics_versions.md` §3
  的口径不变。
* `clean_truth` / `physical_truth` 仍在 `MARKER_FREE_ROLES`：它们的提交路径不在本次允许的写入
  范围内（`synlab/truth/**` 未授权），因此**未动**。若要它们也带标记，修法同
  `visible_labels`（在 `commit_truth` 前 `_stamp_data_semantics`），但那需要改
  `synlab/truth/**` 或在 `pipeline.py` 的 clean/physical 提交点加戳——后者在写入范围内，可按需补做。
* 门禁对新代资产会 PASS，对旧代资产仍 FAIL：这是**期望行为**（旧代就是不合规数据），
  不是本项引入的回归。

---

## S8 · contradiction 可编码对

**Status: 完成（按"明确写出当前无法产生的解锁条件"交付，未伪造任何标签；并纠正任务书的两处前提）**

### 问题复现与两处口径纠正

任务书：`contradiction_valid=3`、`& allowed` 后为 0、`classes_present=1`。这三条是**旧包**的数字。
在**当前** `trainable` 包上实测（`tools/a12_contradiction_reachability.py`）：

```
package  : data\a12_exports\trainable\next_experiment\training_package
           fragments 59, relation rows 47
           observed relation kinds: {'R2': 22, 'R1': 16, 'R0': 726, 'UNKNOWN': 64, 'TINY_CONTACT': 2}
           contradiction labels valid 748, encodable 748
           label histogram (valid)     : {'COMPATIBLE': 748}
           label histogram (encodable) : {'COMPATIBLE': 748}
           classes present   1/2
           classes encodable 1/2
```

两处必须纠正的前提：

1. **`& allowed` 之后不再是 0**：748 个标签**全部可编码**（`negfix` 包 156 个，同样全可编码）。
   "对端无观测"这条旧阻塞在两端观测补齐后已经消失。
2. **`contradiction` 不是四类，是两类 + 一个掩码**：
   `synlab/training/adapter.py` 只有 `MISSING=0` / `COMPATIBLE=1` / `CONTRADICTING=2`，
   而 `MISSING` 是 `valid=False` 的**掩码**（`losses.contradiction_loss` 把它排除），不是类别。
   文档口径一致（`training_diagnostics_episodes.md` §"contradiction `[Q,C]` `0=missing 1=compatible
   2=contradicting`"）。所以"四类齐全"在这份实现里不存在；真实要求是"**两个可学类别都出现**"。

### 根因（机械定位，不是"不可编码"泛论）

`synlab/training/batch.py::_contradiction_label`：

```python
if relation in (RELATION_R1_CODE, RELATION_R2_CODE):
    return CONTRADICTION_COMPATIBLE, True          # R1/R2 恒 compatible
return (2 if has_contradiction else CONTRADICTION_COMPATIBLE), True
```

`has_contradiction` 来自 `row["contradiction"]`（`batch.py:398`）。**`synlab/**` 里没有任何代码写这个键**：

* 加载器 `synlab/qc/loader_probe.py::_batch_rows` 产出的行键恰好是
  `query / positives / negatives / excluded / sample_key`，没有 `contradiction`；
* `research/relations.parquet` 的列是
  `query / candidate / kind / area_mm2 / valid / loss_mask / pool_id / split / lineage_cluster /
  eligible_as_negative / has_observation / reason` —— **没有 contradiction 列**；
* `synlab/relations/**` 全目录搜 `contradict|incompatib|conflict|compatib` → **0 命中**；
* `build_training_batch` 接受一个 `contradiction_source=` 参数，但**函数体从未读它**（未接线的钩子）。

→ 类 `CONTRADICTING` 在当前数据形态下**结构性不可达**（不是"标签存在但被掩码挡掉"）。
这正好解释了卡里 `classes_present = 1`。

### 交付

* `tools/a12_contradiction_reachability.py`：对每个包真实构建 batch，实测
  `labels_valid` / `labels_allowed` / 逐码直方图 / 可编码逐码直方图 / 观测到的关系类别分布、
  并给出 `unreachable_codes` 与原因。

  ```
  .venv\Scripts\python.exe tools\a12_contradiction_reachability.py \
      --json data\a12_reports\s8_contradiction_reachability.json
  ```
  退出码 **0**。

* `tests/a12/training/test_s8_contradiction_classes.py`：pin 住映射的**算术**
  （掩码语义、R1/R2 恒 compatible、`CONTRADICTING` 只经由 `has_contradiction`），
  并断言 `_batch_rows` 的源码里**不含** `contradiction` 字样——即有生产者加入时测试会**主动失败**
  并指向重测，而不是让"1/2 类"悄悄变成过时结论。

  ```
  .venv\Scripts\python.exe -m pytest tests/a12/training/test_s8_contradiction_classes.py -q
  ```
  退出码 **0**。

### 解锁条件（不伪造标签；给出可执行的补法）

要让 `CONTRADICTING` 可达，需要**一个真实的证据来源**，三选一（均为数据/上游改动，不在本轮写入范围）：

1. **真值层给出兼容/冲突判定**：在 `clean_truth` / `physical_truth` 的 `relations` 行上加
   `contradiction`（布尔）与 `evidence`（布尔）字段，并让导出写进 `research/relations.parquet`；
   加载器 `_batch_rows` 把这两个字段透传成行的 `contradiction` 映射即可。
   **前提**：判定必须来自真值几何（例如同一对的 `iface_normal_p95_deg` / `iface_gap_p95_mm`
   超过某个声明的阈值），不能由"关系类别"反推——否则就是伪造。
2. **用现有的可测冲突量构造**：`iface_*` 数组里已有
   `iface_normal_p95_deg` / `iface_gap_p95_mm` / `iface_ambiguity_ratio` / `iface_offset`，
   可以定义一个**声明的**冲突判据（阈值要在 config 里写明来源），对 R0/R1 对判定冲突。
   本轮**未做**：任何阈值都会定义一个新标签，属于数据语义变更，需要 Lead 裁决，不是"小改"。
3. 接线那个已存在但未使用的 `contradiction_source=` 钩子（同样需要一个真实来源）。

在任一项落地之前，contradiction 任务只有 `COMPATIBLE` 一类：
**单类 CE 在数学上可跑但学不到判别**，因此如实报告为"1/2 类可达"，不假装它可训。

### 仍未解决

* `CONTRADICTING` 仍不可达（0 个标签）；`classes_present = 1/2`。
* `R0/R1/R2 组合`这半边**已经满足**：观测到的类别 `{R2: 22, R1: 16, R0: 726}` 都拿到了标签
  （R1/R2 → compatible；R0 在有冲突证据时会走第二类）。缺的只是**冲突证据本身**。
* `build_training_batch` 的 `contradiction_source=` 是死参数（接受但从不读）；本轮**只记录**，
  未接线——接线本身无意义，直到有真实来源。

---

## S3 · 导出表方向性补全

**Status: 完成（每无序对补出反向 role 行；`effective_queries` 实测 20 → 44）**

### 问题复现（真实数字）

`relations.parquet` 是"每无序对一行"。根因在导出侧的合并键：

```python
key = (a, b) if a <= b else (b, a)      # export.py：规范化为有序键
...
relations = [merged[key] for key in sorted(merged)]
...
for row in relations:                    # 只发 row["a"] -> row["b"] 一个方向
```

而 `query` / `candidate` 是**角色**，不是这一对本身。实测（`data/a12_trainable/store`）：

```
unordered pairs  : 1794
rows shipped     : 1794   (reverse rows present: 0)
rows complete    : 3588   (missing direction rows: 1794)
relation kinds   : {'R2': 38, 'R1': 84, 'UNKNOWN': 109, 'TINY_CONTACT': 3, 'R0': 1560}
supervised pairs : 1598   eligible negatives: 1560
```

而且**上游也是单方向的**（实测 `clean_truth` 的 185 条关系行里，两个方向都出现的对 = **0**），
所以下游无法恢复另一方向；这解释了任务书"约一半 (query,candidate) 监督在规则前丢失"。

真正的代价不在行数，而在**训练资格**：`TrainingBatch.effective_query_count()`
（`batch.py:107-111`）只把"**至少 1 个正例 且 至少 1 个合法负例**"的 query 算作可训。
哪个 role 恰好被记下来，直接决定该 query 能不能训。

### 改法

`synlab/storage/export.py`：从规范化的无序对出发，**按角色各发一行**：

```python
for direction, (query, candidate) in (("canonical", canonical),
                                      ("reverse", (canonical[1], canonical[0]))):
```

* 显式新增两列：`direction`（`canonical` / `reverse`）与 `pair_key`（`a|b` 规范键），
  使"哪一行是哪个角色"可被读取而不必反推（任务书要求的两种写法都满足：既各出一行，也显式列明方向）；
* 标签（`kind` / `valid` / `loss_mask` / `area_mm2`）对两个 role **完全相同**——物理关系是对称的，
  补的是监督暴露面，**没有新增信息、没有伪造标签**；
* 每行仍按**自己作为 query** 重算 `split` / `lineage_cluster` / `has_observation`
  ——这些是 query 侧属性，反向行必须用反向角色的值；
* `counts` 新增三个可核对的数字：`unordered_relation_pairs`、`relation_rows_reverse_role`、
  `relation_pairs_direction_complete`（布尔），使"方向补全"是被**测量**的而不是从行数翻倍猜的。

### 验证

真 store 审计（`tools/a12_relation_direction_audit.py`，直接读 release 的池索引，无需 3 GB 重导出）：

```
.venv\Scripts\python.exe tools\a12_relation_direction_audit.py --store data\a12_trainable\store \
    --json data\a12_reports\s3_relation_direction.json
```
退出码 **0**。

| | before（shipped，单方向） | after（direction_complete） |
|---|---|---|
| 行数 | **1794** | **3588** |
| 有正例的 query | 37 | **75** |
| 有合法负例的 query | 55 | 59 |
| **`effective_queries`** | **20** | **44** |

→ **2.2×**（20 → 44）。这是表格算术，与 `effective_query_count()` 的定义逐字一致
（测试里用 `inspect.getsource` 核对了定义，并确认 `R2 ∉ NEGATIVE_KINDS`）。

真导出验证（小 release，`export_training_package` 实跑）：

```
relations = 6 | unordered_relation_pairs = 3 | relation_rows_reverse_role = 3
relation_pairs_direction_complete = True
directions: Counter({'canonical': 3, 'reverse': 3})
pair_keys with exactly 2 rows: 3 of 3
```

```
.venv\Scripts\python.exe -m pytest tests/a12/storage/test_s3_relation_direction.py -q
```
退出码 **0**（4 passed）。测试断言：行数恰好翻倍且**不新增对**；`effective_queries` 单调上升；
同一 `pair_key` 的两行 `kind`/`valid` **逐一相同**（对称性，不是发明）；
`direction` 恰为 `{"canonical","reverse"}`。

回归：`tests/a12/{storage,training,qc,relations}` 全绿，退出码 **0**。

### 仍未解决

* **6 个 roster 片段仍不在关系表内**（实测，与任务书的观察一致）：
  `LIN0101_V16_M12_PAT12_E03-{m,p,p__+1c1,p__+1c2}`、`LIN0102_V11_M06_PAT16_E03-{m,p}`。
  roster 77 个，关系表覆盖 71 个（表侧无 roster 外片段）。这 6 个是**较晚加入 roster 的
  event**：关系池里没有它们的行 ⇒ 导出侧无处可补。解锁条件：让池构建覆盖这些 event
  （`synlab/relations/**`，本轮未改），或在 roster 生成时拒绝无关系行的片段
  （让缺口在生成时就可见，而不是在训练时表现为 12 个不可训 query）。
* 本项**未**重新导出 `data/a12_exports/**` 的既有包（会覆盖队友正在用的包）；
  修复对**此后每次导出**生效，行数/`effective_queries` 的 after 数字来自
  release 池索引的同源重算 + 小 release 的真实导出。

---

## S9 · 整包 CPU 冒烟 OOM

**Status: 完成（全包 CPU 3 步跑通；峰值 4.6 GiB，替代 19.63 GiB 的失败分配；采样分母全报）**

### 问题复现（真实数字，先确认 21.4 GB 的来源）

用同一个训练器、同一个 batch builder，**不分块**跑整包（`--chunk-fragments 1000`）：

```
RuntimeError: [enforce fail at alloc_cpu.cpp:117] data. DefaultCPUAllocator:
  not enough memory: you tried to allocate 19629342720 bytes.
```

**19,629,342,720 B = 19.63 GiB = 21.08 GB（十进制）** —— 与任务书/`relation_negatives.md` §6.3
记的 **21.4 GB** 是同一次分配（合计口径差异）。失败点在 backward。

真正的驱动量是 `FeatureBundle.global_rgb = [F, V, 3, H, W] float32`：

```
59 片 × 12 视图 × 3 × 768 × 1024 × 4 B = 8.70 GB   （仅这一个输入张量）
+ pixel_valid 727 MB + 激活 + 反向缓存
```

### 改法

新增 `tools/a12_chunked_smoke.py`：**同一个** `Trainer`、同一个 `build_training_batch`、同一套
loss，只把 fragment 作用域切成 chunk，梯度在 chunk 间累加，每个 micro-step 一次 `optimizer.step()`。
监督语义**未改**：

* 每个 chunk 的行来自**包自己的** `relations.parquet` 与包自己的池，正/负完全按导出表判定；
* chunk 外的对端由 builder 记成 `pair_valid=False`（与不分块时"对端未观测"走同一条件），
  不是被静默丢弃；
* 负例配额是**显式输入上限**（`--negative-quota`），报告同时打印**未采样分母与采样后分母**；
* 梯度归一化与 `Trainer.fit` 逐字一致：`accumulate=n_eff` 把 loss 放大 `n_eff` 倍，
  累加后除以 `sum n_eff`（`trainer.py` 原文"gradients hold sum_m (n_m * dL_m); divide by
  sum_m n_m for the weighted mean"），所以在 chunk 上累加得到的就是**不分块的加权均值**；
* 峰值内存由**操作系统**读出（`psutil` → Windows 工作集 → `VmHWM`），不是按张量形状估算。

### 验证

```
.venv\Scripts\python.exe tools\a12_chunked_smoke.py \
  --package data\a12_exports\trainable\next_experiment\training_package \
  --steps 3 --chunk-fragments 8 --negative-quota 4 \
  --json data\a12_reports\s9_chunked_smoke.json
```
退出码 **0**。

```
scope            : 65 fragments in 10 chunk(s) of <= 8
optimizer steps  : 3 / 3
wall seconds     : 18.3
peak RSS         : 4692 MiB
  step 0: 10 chunk(s), grad_norm=574.0,  6.5s, peak 4670 MiB
  step 1: 10 chunk(s), grad_norm=566.7, 12.4s, peak 4689 MiB
  step 2: 10 chunk(s), grad_norm=561.2, 18.3s, peak 4692 MiB
totals           : positives 24, negatives 96, effective_queries 12,
                   encodable_pairs 120, unencodable_pairs 0
```

| | 不分块 | 分块（8 片/chunk，10 chunk） |
|---|---|---|
| 3 步结果 | **失败**：单次分配 19.63 GiB | **3/3 步完成** |
| 峰值 RSS | ≥ 19.63 GiB（分配失败） | **4.69 GiB** |
| 墙钟 | — | 18.3 s（含 3 步 × 10 chunk） |

→ 峰值降到 **1/4.2**，并且第一次真正跑完整包 3 步。

**采样分母**（任务要求"采样要在报告中给分母"）：

| 分母 | 值 |
|---|---|
| 未配额时的负例总数 `negatives_before_quota` | 96 |
| 实际使用 `negatives_used` | 96 |
| 正例 `positives` | 24 |
| `effective_queries`（≥1 正例且 ≥1 合法负例的 query 数） | 12 |
| 可编码对 / 不可编码对 | 120 / 0 |

本例 `--negative-quota 4` **没有真正削减任何 query**（无 query 超过 4 个负例），
所以 before == after == 96，`queries_losing_negatives = 0` —— 报告如实写出这一点，
而不是让"配额"看起来起了作用。

**chunk 尺寸的下限（实测，非设计选择）**：`--chunk-fragments 4`（13 个 chunk）与 `6`（12 个 chunk）
都得到 `no_effective_query_in_chunk`：chunk 切进一个 event 内部时只剩半个 pair，无法训练。
因此 chunk 以 **event/lineage** 为单位打包，本包的最小可用块是 **8 片**（峰值 4.69 GiB）；
请求更小的值会被上调到"一个完整 event"，报告里用
`requested_chunk_fragments` / `effective_chunk_fragments` 两个字段说明实际用了多大。

### 仍未解决

* `--chunk-fragments 4` 与 `6` **跑不通**（0 步）：不是内存问题，而是切分单位问题——
  本包最小的 event 就有 8 片。要让更小的块可训，需要 **`views_per_fragment` 截断**或
  **逐 fragment 流式编码**，两者都会改变输入语义（视图数/批构成），属于数据决策，本轮未做。
* `run_smoke()`（不分块路径）**保留未改**：它是"整包 batch 到底需要多少内存"的诚实证据，
  改掉它会让 19.63 GiB 这个数字失去可复现性。分块路径是**新增**能力，不是替换。
* 4.69 GiB 仍是"8 片 × 12 视图 × 768×1024"的代价；若要单进程更低内存，
  需要减视图数或降低交付分辨率——那属于数据语义变更。
* 未测 GPU 路径（本机 torch 是 CUDA 版但任务要求 CPU 冒烟）。

---

## S2 · 难负例类别隔离参与训练

**Status: 完成（类别在线产出 + 训练侧独立损耗项，默认关；开/关对照实测**无增益** → 建议保持关闭）**

Lead 裁决允许 `CANDIDATE_MATE_PRESENT_NOT_ORDINARY` 作为独立类别 `HARD_NEGATIVE_MATE_PRESENT`
参与训练，四条约束全部按字面实现并**逐条实测**（`conformance` 四键全 true）。

### 问题复现（真实数字）

```
.venv\Scripts\python.exe tools\a12_s2_hard_negatives.py --step class ^
  --package data\a12_exports\trainable\next_experiment\training_package ^
  --out data\a12_reports\s2_hard_negatives_class.json
```
退出码 **0**。实测（`data/a12_reports/s2_hard_negatives_class.json`）：

| 项 | 值 |
|---|---|
| 关系行 | 1721 |
| `POSITIVE_R2` | 28 |
| `ORDINARY_NEGATIVE_MATE_ABSENT` | 440 |
| **`CANDIDATE_MATE_PRESENT_NOT_ORDINARY`** | **1120**（不参与任何 loss） |
| `EXCLUDED` | 133 |
| `eligible_as_negative` true（冻结推导） | 1560 |
| 有邻片片段 / 无邻片片段 | 56 / 15 |
| 1120 行中 **query 有邻片** | **880**（可进入新类别） |
| 1120 行中 **query 无邻片** | **240**（必须拒绝，见约束 4） |

### 实现

**在线侧（`synlab/relations/**`）**——复用 `mate_absent.py` 的类别语义，**不重写** `kind`/`valid`/`area_mm2`/身份：

* `mate_absent.py`：新增 `CLASS_HARD_NEGATIVE`、`HARD_NEGATIVE_LOSS_MASK=True`、
  `HARD_NEGATIVE_ELIGIBLE_AS_NEGATIVE=False`、`HARD_NEGATIVE_TASK`、`HARD_NEGATIVE_RULING`
  （四条约束原文）、`hard_negative_records()`、`hard_negative_class_count()`。
  `hard_negative_records` 只在 `row_class == CLASS_MATE_PRESENT` 的行上产出记录（**判决前后两种状态都认**，
  与 `row_class` 同一判据），并强制约束 4：`query` 必须自带确认 R2 邻片，否则进 `rejected`
  并带 `query_mate_absent`，**不静默丢弃、不监督**。
* `sampler.py`：`hard_negative_candidates(pool, query, limit=)` 在**活池**上产出同一类别
  （只接受被 `negative_exclusion_reason` 以 `candidate_mate_present` 拒绝的候补；自身、query 的历史 R2、
  `TINY_CONTACT`、灰区、未确认仍一律拒绝）；`SamplerParams.hard_negative_limit` 默认 **0**
  （该类别不进 batch），`sample_training_batch` 只在非 0 时给行加 `hard_negatives`，且**永不**并入 `negatives`。

**类别为什么不能并进 `research/relations.parquet`（实测，不是声明）**：决策 D10 的单门规则要求
`eligible_as_negative == (kind in {R0,R1} and loss_mask)` 对**每一行**成立，而本类别的契约正是
`loss_mask=True` 且 `eligible_as_negative=False`。用**真正的**检查器
`qc.decision_checks._check_loss_mask_authority` 对同一张表跑两遍：

| | rows | 满足 D10 | 违反 |
|---|---|---|---|
| 类别留在主表之外 | 1721 | 1718 | 3（既有的 `TINY_CONTACT` 行，与本项无关） |
| 类别并入主表 | 2601 | 1718 | **883**（+880，全部是本类别行） |

→ 并入等于**新增 880 条审计违规**（即放宽 QA 判据），所以类别以**自己的记录集**产出
（`s2_hard_negatives_class_records.json`），主表一字未动。
`tests/a12/relations/test_s2_hard_negative_class.py::test_merging_the_class_into_relations_parquet_would_add_d10_violations`
把这件事实固化（真 parquet + 真检查器）。

**训练侧（`synlab/training/**`）**：

* `batch.py`：新字段 `hard_neg_mask [Q,C]`、`hard_neg_query_mate [Q]`、`mate_present [F]`；
  硬负例占用**追加在 pos/neg 块之后**的独立 slot 块（`c = c_pn + c_hard`），
  `neg_mask`/`pos_mask`/`excluded_mask`/`exclusion_reason` 的既有 slot **逐位不变**；
  `_corr_tensors(slots=)` 让对应权重张量跟住加宽后的 `C`；`negative_audit` 增加
  hard∈neg / hard∈pos / hard∈excluded / 不可编码 / 未确认 / 类别码非法 / query 无邻片 七类判据；
  `mate_present_shortcut_probe()` 用**标签侧**的"候补自己有没有邻片"这一个线索去分辨
  「正例 vs 硬负例」，直接测出捷径强度。
  约束 4 **无开关**：query 无邻片的行**抛错**而不是丢弃；另加"同一候补同时进 ordinary negative 与硬负例"直接拒绝。
  `_mates_of()` 按**池**（而非本 micro-batch）判定候补的邻片，避免"邻片不在本 batch 就被误判"。
* `losses.py`：`HARD_NEGATIVE_TASK="hard_negative"`、`DEFAULT_HARD_NEGATIVE_WEIGHT=0.0`（**默认关**），
  且**不在** `TASK_ORDER` 里（五个核心任务的冻结集不变）；新增 `hard_negative_loss()`：
  `L_h(q) = logsumexp([s(q,p)/τ] ∪ [s(q,h)/τ+margin]) − logsumexp([s(q,p)/τ])`，
  只读 `hard_neg_mask`，**从不读 `neg_mask`**。
* `trainer.py`：权重为 0 时**根本不构造**该项（组合、报告、反向与无本项时逐位一致）；
  非 0 时以独立权重进入 `MultiTaskLoss.combine`，`task_report()` 仍只列五个核心任务。

### 验证：开/关对照（同一最小可训子集，3 步，真实梯度）

```
.venv\Scripts\python.exe tools\a12_s2_hard_negatives.py --step all ^
  --package data\a12_exports\negfix\next_experiment\training_package ^
  --query LIN0101_V16_M12_PAT12_E01-m --steps 3 --negatives 4 --hard-negatives 4 --hard-weight 0.3 ^
  --out data\a12_reports\s2_hard_negatives_ab.json
```
退出码 **0**；`data/a12_reports/s2_hard_negatives_ab.json`（27.7 s，device cuda）。
子集 10 片（query + 1 正例 + 3 ordinary negative + 4 硬负例），三个 arm：

* `off` = 无硬负例 slot、权重 0（S2 之前的批）；
* `control` = 有硬负例 slot、权重 0（隔离"类别存在"本身）；
* `on` = 同一批，权重 0.3。

| | `off` | `control` | `on` |
|---|---|---|---|
| rank loss（3 步） | 6.923782 / 6.776347 / 6.667806 | 6.923782 / 6.776352 / 6.667811 | 6.923782 / **6.777000** / **6.668943** |
| rank `n_valid`/`n_allowed` | 3 / 3 | 3 / 3 | 3 / 3 |
| `effective_queries` | 3 | 3 | 3 |
| positives / negatives / excluded | 1 / 1 / 8 | 1 / 1 / 8 | 1 / 1 / 8 |
| 组合 loss（3 步） | 7.317972 / 7.170210 / 7.061428 | 7.317583 / 7.169848 / 7.061081 | 10.081157 / 9.878906 / 9.730040 |
| grad norm | 329.33 / 322.71 / 317.82 | 329.32 / 322.70 / 317.81 | **459.55 / 450.33 / 443.53** |
| aux 项 | 未构造 | 未构造 | 9.211914 / 9.028023 / 8.892738（权重 0.3） |
| aux `n_valid`/`n_allowed`/`n_valid_labels` | — | — | 1 / 1 / 8（另 8 个 query 被跳过：query 侧非 mate-present，或没有 allowed 的正例/硬负例） |

**约束 2 的数字证明**（`denominator_invariance`）：`off` 与 `control` 的
`positives / negatives / excluded / effective_queries / queries_with_positive / queries_with_legal_negative`
**全部相等**（`moved_fields = {}`、`invariant = true`），rank 任务的 `n_valid`/`n_allowed`/`loss` 在
step 0 **逐位相同**（6.9237823486328125）。唯一变动的是 `exclusion_histogram["none"]`，
它正好增加 `hard_neg_mask.sum()`（= 4），即"被加宽的候补维度"，不是任何分母。

**约束 4 的数字证明**（`mate_present_shortcut_probe`）：`on`/`control` 都是
`queries_probed=1`、`queries_with_constant_cue=1`、`discriminative_power=0.0`
——在辅助项自己的比较集（正例 ∪ 硬负例）里，"候补有没有邻片"这个线索**恒定**，
AUC 未定义 ⇒ 该线索无法被用来解题。`tests/.../test_the_shortcut_probe_is_not_vacuous`
人为把其中一个硬负例的线索改成 False，探针立刻报 AUC 0.75 / power 0.5，证明探针不是恒零。

**指标（子集尺度）**：

| | `control` | `on` |
|---|---|---|
| `positive_rank`（越小越好） | 5 | **5** |
| `hard_negative_accept_rate`（越小越好） | 0.75 | **0.75** |
| `mate_absent_misleading_rate`（越小越好） | 0.25 | **0.25** |
| `candidates_scored` | 9 | 9 |

（`off` 的 `positive_rank=2` 只是因为它的候补集里**没有**那 4 个硬负例；这正是"1120 行不参与训练"
让检索看起来更容易的原因。`any@50`/`Hit@10`/`无邻片误导率` 的冻结分母在 roster 尺度由
`synlab.diagnostics.metrics` 计算，本子集只有 9 个候补，所以这里报的是**子集尺度同义量**，
报告里逐字写明，不冒充冻结指标。）

### 结论与建议：**保持关闭**

* **无增益**：3 步之后 `positive_rank`、`hard_negative_accept_rate`、`mate_absent_misleading_rate`
  在 `control` 与 `on` 之间**完全相同**（5 / 0.75 / 0.25）；aux 项自身确实在降
  （9.2119 → 8.8927，−3.5%），但没有迁移到任何被测指标上。
* **rank 任务反而略差**：`on` 的 rank loss 6.777000/6.668943 vs `control` 6.776352/6.667811
  （差在 1e-3 量级，方向一致地更差）。
* **代价明确**：同一 rank 目标下梯度范数从 329/322/318 升到 460/450/444（**+40%**），
  即多了一个只贡献梯度、不贡献可测指标的项。
* **没有引入捷径**（约束 4 与探针都成立），所以这不是"要关掉因为它有害"，而是
  **"在能测到的范围内没有收益，先关掉"**。默认 `DEFAULT_HARD_NEGATIVE_WEIGHT = 0.0`、
  `SamplerParams.hard_negative_limit = 0`，两条路都默认不产出；打开只需要权重非 0。

### 仍未解决

* **3 步太小**：本项只跑了任务要求的最小对照（同一最小可训子集 3 步）。要判断该类别是否
  在长训练里有价值，需要在**全包**（`tools/a12_chunked_smoke.py` 的分块路径，峰值 4.69 GiB）上
  跑足步数并比较族级指标；本轮未做，因此结论限定为"这 3 步里没有增益"。
* **只用到 4 个硬负例 / 1 个可训 query**：包内该 query 有 36 个硬负例，子集只取了 4 个（内存约束）。
  更大的硬负例集与更多 query 可能改变结论，属上一条的同一解锁条件。
* **240 行（query 无邻片）永久不可用**：这是约束 4 的直接结果，已如实计入 `rejected`，
  没有为了凑数把它们放进来。它们也不是 ordinary negative（候补有邻片），所以这 240 行
  在当前类别体系下**没有任何监督角色**——如果将来要利用，需要 Lead 另立类别与证据。
* **类别没有进包**：`research/relations.parquet` 未写（会违反 D10）。要让下游开箱可用，
  需要 Lead 决定新增一张辅助表（例如 `research/hard_negatives.parquet`）并更新列语义表；
  本轮以 `data/a12_reports/s2_hard_negatives_class_records.json` + 活池 API 交付。

---

## S11 · P03 全局 SDF 提取漂移

**Status: 完成（漂移来源已用实测证据链锁定 = 全局 level-set 重提取；最小修法 = 让 P03 走已存在的窄带后端，
实测漂移 0.35424 → 0.000348 mm；另附"就地修"的实测反证）**

### 问题复现（真实数字）

复现对象：`data/a12_degrade/store` 的 `LIN0000_V02_M01_PAT02_E01-m`（与 `a09_p03_probe.json` 同一谱系），
83262.62 mm³ / 4886 面 / watertight；配方 `P03_depth_light`（`depth_mm=0.05`）。

```
.venv\Scripts\python.exe tools\a12_s11_p03_drift.py --step context --store data\a12_degrade\store ^
  --out data\a12_reports\s11_p03_context.json        # 退出码 0
.venv\Scripts\python.exe tools\a12_s11_p03_drift.py --step sweep --backend global_sdf ^
  --store data\a12_degrade\store --spacings 0.5701,1.1402,2.2804 --depths 0.0,0.0125,0.025,0.05 ^
  --out data\a12_reports\s11_p03_sweep.json          # 退出码 0
```

`--step full --backend global_sdf`（即 `pipeline` 实际走的那条路，见下）实测：

| 量 | 值 |
|---|---|
| `roi_external_drift_mm` | **0.35424** |
| `lost_volume_mm3` | **319.31** |
| 线性预估（`Σ area_face · b(质心)`） | **40.60** |
| 网格 spacing（`basis`） | **1.1402 mm**（`min_wall_thickness/6`=0.95018 被 **node_budget_relaxation** 放大） |
| grid shape / nodes / halo | 108×63×83 / 564 732 / 4.5207 mm |
| ROI | 1214 面 / 1499.01 mm² |
| **`surface_zero_level_max_mm`** | **0.26117**（RMS 0.03053，800 个真实表面采样点） |
| 配方面元数 vs 交付面元数 | 4886 → 119 325（布尔求交后） |
| 交付体 watertight / 边界边 | **False / 43** |

### 证据链（四项独立实测，全部指向同一个来源）

**(1) 零损伤对照——最决定性的一条。** 在同一网格、同一 `marching_cubes_mesh` 调用上只提取 `d0`
（**完全不施加任何损伤**，与 `SdfContext.extract` 用的是同一条语句）：

| | 零损伤提取 (`--step extraction`) | 真实全流程 (`--step full`) |
|---|---|---|
| 体积误差 | **−206.86 mm³ (−0.248 %)** | lost_volume **319.31 mm³** |
| `roi_external_drift_mm` | **0.35424330830574036** | **0.35424330830574036**（逐位相同） |
| 面数 | 58 494 | 119 325 |
| watertight / 边界边 | True / 0 | False / 43 |

→ 276.58/319.31 级别的"损失"里，**206.86 mm³（64.8 %）在没有任何损伤时就已产生**；
而**漂移量完全等于**零损伤提取的漂移量：**漂移与损伤场无关**。
`--step sweep` 的 depth 扫描（0 / 0.0125 / 0.025 / 0.05 mm）在这条对照上给出**逐位相同**的
0.35424330830574036 / −206.85717324719008 —— 对照本身不施加场，所以这只证明"提取漂移对声明深度完全无感"，
不能当作"全流程与深度无关"来读（报告里按此表述）。

**(2) 场的采样/插值残差就是漂移的上界。** `surface_zero_level_max_mm = 0.26117`
= **0.229 × spacing**：节点采样的 `d0` 经三线性插值后在**真实干净表面**上偏离 0 达 0.261 mm。
marching cubes 把顶点放在这个插值零集上，所以交付表面对真实表面的位移不可能小于它。
实测漂移 0.35424 = 1.36 × 该上界（多出的部分来自布尔求交与采样尾统计）。

**(3) 提取顶点对干净表面的残差直接量化了误差。** 零损伤提取的 29 249 个顶点：
`|signed distance|` 均值 **0.00293** / p95 **0.01152** / max **1.4010** mm，6.83 % 的顶点外偏 > 1e-3 mm。

**(4) spacing 扫描（不单调，如实报告）。** `choose_spacing` 被 node budget 覆盖，
请求值几乎无效（请求 1.1402 与 2.2804 都落到同一个 1.1402 mm；请求 0.5701 反而落到 1.1822 mm）：

| 有效 spacing | 漂移 | 体积误差 | 面数 |
|---|---|---|---|
| 1.1402 mm | 0.35424 | −206.86 | 58 494 |
| 1.1822 mm | 0.24084 | −215.70 | 54 288 |

→ 漂移是**采样点的最大值统计**，在这个采样数下对 spacing 不单调；可控结论是
"漂移由网格决定"，而不是"漂移 ∝ spacing"。这本身说明该指标只能当**上界探针**用。

**(5) 就地修的反证（`--step fix`，`s11_p03_projection_fix.json`）。** 在 `synlab/physical/sdf.py`
新增 `refine_to_level_set()`：把 marching-cubes 顶点用**精确场**（`d0(x) + t·α(x)·b(x)`，
`d0` 由 Open3D 在任意点给出）做带保护的 Newton 投影（严格改进 + 位移 ≤ 0.75·spacing + 结果必须
watertight/winding 一致且不产生退化面）。实测：

| | 投影前 | 投影后 |
|---|---|---|
| 顶点残差 均值 / p95 / max | 0.00296 / 0.01152 / 1.4010 | **0.00017 / 6.1e-6 / 1.4010** |
| 接受顶点比例 | — | 59.15 % |
| lost_volume_mm3 | 319.31 | **242.03（−24.2 %）** |
| `roi_external_drift_mm` | 0.35424 | **0.35407（−0.00018）** |
| 交付体 watertight / 边界边 | False / 43 | False / **90** |

→ 投影确实把"提取误差"压下去了（p95 好 1 900 倍、虚假体积损失少 24 %），但**漂移的尾巴动不了**：
尾巴正好落在 1.14 mm 网格表示不了的地方（残差 max 仍是 1.401 mm，那些修正超过了 0.75·spacing 预算被拒），
而且它经布尔求交后**把边界边从 43 条变成 90 条**。
因此该投影**不是本缺陷的修法**，`PROJECT_TO_LEVEL_SET_DEFAULT = False`，仅作为可选、可复现的
局部细化能力保留（`recipe.grid["project_to_level_set"]=True` 打开，效果写进
`details["sdf_level_set_projection"]`）。

**(6) 重合反向绕向三角对不是主因。** `a09_p03_probe.json` 里的 2 体 2 面 0 mm³ debris
在本体上确实存在，但 `assemble_damage_bodies`（`subset_v2`）已按 `MIN_MATERIAL_VOLUME_MM3=1e-9`
把它们判为引擎碎屑并剔除；本轮全流程 `component_count = 1`、无 `NON_POSITIVE_VOLUME`。
它们影响的是 **watertight 判定**（43 条边界边），不是漂移。

### 修法（最小）：把 P03 交回它自己声明的后端

**根因不是提取参数，而是"谁来产生几何"**：

* `synlab/degrade/axes.py` 已把 P02/P03/P04 声明为 **窄带轴**（`NARROWBAND = True`），
  并把它们路由到 `synlab.degrade.physical_narrowband`——一个**表面算子**：只沿法线内移 ROI 顶点、
  把 ROI 边缘钉死（实测 `rim_vertices_pinned = 618`、`narrowband_vertices = 917` / 1214 个 ROI 面）、
  **其余三角面原样保留**，
  `details.narrowband.grid = "none (surface operator, not a voxel field)"`、`spacing_mm = 0.0`。
* 但 `synlab/pipeline.py:1705` 走的是 `physical.api.apply_damage` → `physical.operators.run_damage`
  → **全局 SDF 路径**，于是"声明"和"实际产出"互相矛盾，交付数据带的就是全局路径的漂移。

**改法（写在 `synlab/physical/**` 内）**：`physical/operators.py` 新增
`NARROWBAND_BACKEND_ROUTING`（默认 `"declared"`）、`declared_narrowband_axis()`（只读地问
`degrade.registry` 该轴是否声明为窄带）与 `selected_backend()`；
`run_damage()` 在轴被声明为窄带且 `level > 0` 时调用
`_run_narrowband_as_outcome()`（把 `run_narrowband_damage` 的 `PhysicalResult` 适配回
`DamageOutcome`，`apply_damage` 之后的组件/台账/QA 逻辑一字未改）。
每个结果都在 `details["damage_backend"]` / `details["backend_selection"]` 里写明**是哪个后端产出的**；
`recipe.grid["damage_backend"] = "global_sdf" | "narrowband"` 可按配方覆盖（复现旧行为用前者）。

### 验证（同一 body、同一冻结配方）

```
.venv\Scripts\python.exe tools\a12_s11_p03_drift.py --step full --backend narrowband ^
  --store data\a12_degrade\store --out data\a12_reports\s11_p03_narrowband_routed.json   # 退出码 0
```

| | 全局 SDF（修前 / `--backend global_sdf`） | 窄带（修后 / 默认路由） |
|---|---|---|
| `roi_external_drift_mm` | 0.35424 | **0.000348**（**1 018×**） |
| `lost_volume_mm3` | 319.31 | **32.88** |
| 线性预估 | 40.60（context 的质心式） | 40.46（后端自己的 `linearised_predicted_loss_mm3`），比值 **0.813** |
| 交付体 watertight / 边界边 | False / 43 | **True / 0**（`narrowband_path` 的 `assert_watertight`） |
| 交付体面数 | 119 325 | **4 856** |
| ROI 钉住顶点 / 窄带顶点 | —（全部重提取） | 618 / 917（共 1214 个 ROI 面） |
| `audit_physical` | PASS（`roi_external_drift.pass = false`，**不作为失败码**） | **PASS，`failure_codes = []`** |
| 后端标记 | `physical.operators.global_sdf_level_set` | `degrade.physical_narrowband`（`backend_selection.declared_narrowband = true`） |

### 一处必须点名的 QA 缺口（本轮只记录，未改判据）

`audit_physical` 把 `roi_external_drift_mm` 写进 `checks["roi_external_drift"]` 并给出
`pass: false`，但**它不进 `failure_codes`**，所以 `a09_p03_probe.json` 之外的全局 P03 结果
可以在漂移 0.354 mm 的情况下报 `audit status = PASS`。本项**没有**收紧这个判据
（收紧会让已产出的包集体翻成 FAIL，属 QA 口径变更，需要 Lead 裁决），只把它作为
"漂移能悄悄出厂"的机制记录在此，并已由 `run_damage` 的后端选择显式化。

### 仍未解决

* **历史数据不会被追溯修复**：`data/a12_exports/**` 里已写出的 P03 产物仍然是全局路径的几何。
  要修复需要重新导出（本机可做，但会覆盖队友正在使用的包，未执行）。
* **P02/P04 同属窄带声明，同样被路由**：本项只在 P03 上做了完整的前后对照（P02/P04 共用同一
  适配路径，未逐轴复测）。若 Lead 只想改 P03，把 `NARROWBAND_BACKEND_ROUTING` 或单配方
  `grid["damage_backend"]` 按轴收窄即可——这是**一行**的差别，不需要改实现。
* **默认路由改变了 P03 的产出几何**：这是"让 `physical` 与 `degrade.axes` 的声明一致"，
  但它确实会改变此后每次导出里 P03 的字节。`recipe.grid["damage_backend"]="global_sdf"`
  完整保留旧行为，便于 A/B 与复现。
* **漂移指标本身是"采样点的最大值"**：20000 个表面采样点里少数几点决定读数，缺一个稳健的
  p95/p99 版本；本轮没有改指标定义（改它会让历史数字失去可比性），只如实报告两条 spacing 下的读数。
* **1.14 mm 的 spacing 由 node budget 而非几何需求决定**（`min_wall_thickness/6 = 0.95018` 被
  `+node_budget_relaxation` 放大 20 %）。在仍走全局路径的轴上这是一个独立的精度隐患，本轮未动
  `choose_spacing`（改它会改所有轴的数据）。
* **未改** `synlab/degrade/**`（只读导入）、`synlab/pipeline.py`、`synlab/fracture/**`、`synlab/observe/**`。

---

## 本轮回归（S2 + S11）

回归集共 **365** 项（`pytest tests\a12\{relations,training,physical,qc,storage} --collect-only -q`）。

| 命令 | 退出码 | 结果 |
|---|---|---|
| `.venv\Scripts\python.exe -m pytest tests\a12\relations tests\a12\training tests\a12\physical tests\a12\qc tests\a12\storage -q` | **0**（本会话两次，`_s2s11_pytest_required_exit.txt` / `_req4` 之前的运行） | 全绿 |
| 同上（本轮最终代码，`_s2s11_final.txt`） | **1** | 唯一失败 `tests/a12/qc/test_data_quality.py::test_store_sqlite_is_opened_read_only`（见下） |
| `.venv\Scripts\python.exe -m pytest tests\a12\operators -q` | **0** | 全绿（含 `test_narrowband.py`，证明 S11 的路由没有破坏算子契约） |
| `.venv\Scripts\python.exe -m pytest tests\a12\operators tests\a12\fracture -q` | 1 | 20+ 个 `tests/a12/fracture/**` setup error：`CUTTER_NOT_CLOSED (fracture.cut.verify) cutter is not watertight: 6442 edges` —— 来自**并行队友正在改的** `synlab/fracture/cut.py`（工作区未提交修改），与本项无关 |

**关于 `test_store_sqlite_is_opened_read_only`**：单独运行退出码 **0**（通过），
`pytest tests/a12/qc -q` 整目录运行退出码 **1**，`tests/a12/qc --ignore=test_data_quality.py` 退出码 **0**。
触发条件不是某一个特定测试：把该文件的**第一个**测试与它配对（`-k "test_fully_marked_minimal_store_is_trainable or test_store_sqlite_is_opened_read_only"`）
同样复现，即**它前面只要有任意一个测试**就会失败（顺序相关）。

机制线索（**假设，未改代码验证**）：`synlab/storage/store.py::AssetStore._init_db()` 用
`with self.connect() as conn:` —— 这在 sqlite3 里只做提交、**不关闭连接**，而 `connect()` 每次都会
`PRAGMA journal_mode=WAL`；`journal_mode` 是**写在库文件头里的持久属性**，所以 `green_store` 建出的库
一定是 WAL 库，`-wal`/`-shm` 何时消失取决于那个未被显式关闭的连接何时被 GC 回收，
而 GC 时机又取决于此前跑了多少测试。该测试断言的正是"文件集不变"，于是变成顺序相关。

责任范围：该测试文件只 import `synlab.qc.data_quality` / `synlab.storage.store` / `synlab.roles`，
三个模块**均不在 S2/S11 的改动集内**（本轮改的是 `synlab/{relations,training}/**`、
`synlab/physical/{sdf,operators}.py`、`tests/a12/{relations,training}/**`、`tools/**`、本文件），
`tests/a12/qc/**` 也不在写入范围内。因此如实记录为**既有的、顺序相关的失败**，本轮**未改**它。

---

## 本轮证据索引（S2 + S11）

| 文件 | 内容 |
|---|---|
| `tools/a12_s2_hard_negatives.py` | S2 驱动：`--step class`（类别 + 四条 conformance + D10 并入反证）、`--step ab`（off/control/on 三臂 3 步对照） |
| `data/a12_reports/s2_hard_negatives_class.json` / `..._records.json` | 1721 行的类别统计、880 条类别记录、240 条拒绝、D10 前后对比 |
| `data/a12_reports/s2_hard_negatives_ab.json` | 三臂逐步 loss / grad / rank 分母 / aux 诊断 / 捷径探针 / 子集尺度指标 |
| `tools/a12_s11_p03_drift.py` | S11 驱动：`--step context / extraction / full / narrowband / sweep / fix`，`--backend declared\|global_sdf\|narrowband` |
| `data/a12_reports/s11_p03_context.json` | 网格、spacing 依据（含 node budget 放大）、ROI、`surface_zero_level_*` |
| `data/a12_reports/s11_p03_drift.json` | 全局路径的 context + 零损伤提取 + 全流程（改动前产出，作为"修前"证据） |
| `data/a12_reports/s11_p03_sweep.json` | spacing / depth 扫描（含"请求被 node budget 覆盖"的实测） |
| `data/a12_reports/s11_p03_projection_fix.json` | 就地 Newton 投影的前后对照（含 watertight 退化） |
| `data/a12_reports/s11_p03_narrowband_routed.json` | 默认路由后的窄带结果（漂移 0.000348 mm） |
| `tests/a12/relations/test_s2_hard_negative_class.py` | 类别语义 + 四条约束 + D10（真 parquet + 真检查器）+ 活池 API（14 passed） |
| `tests/a12/training/test_s2_hard_negative_consumption.py` | 分母不变性、slot 布局、三处拒绝、loss 算术、捷径探针非空性（13 passed） |
| `data/a12_reports/_s2s11_*.txt`、`_req*.txt`、`_dq*.txt`、`_wal.txt` | 本轮 pytest / 驱动的原始输出与退出码 |

---

## N9 · `roi_external_drift` 纳入失败码（版本化 QA 变更）

**Status: 完成（QA 收紧，版本 `a12.qa.v2`；旧产物只标注、不改写）**

S11 §"一处必须点名的 QA 缺口"记录的机制——`audit_physical` 把漂移写进 `checks` 却**不进
`failure_codes`**，所以 0.354 mm 可以报 PASS——本轮按 `engineering_policy.md` R5 做成**版本化 QA
变更**。`synlab/physical/**` 不在写入范围，因此收紧落在**独立策略层** `synlab/qc/qa_policy.py`：
只读生产者已经算出的 `pass` 标志，**只增失败码**（`ROI_EXTERNAL_DRIFT_EXCEEDED`），从不把 FAIL 升为
PASS，幂等，并在结果上打 `qa_policy.version` 戳（没有该块的旧记录即 `a12.qa.v1`，这就是旧产物的标注
依据）。

**before/after（真实重跑 + 真实录得审计）**：

| | 全局 SDF | 窄带（S11 默认路由） |
|---|---|---|
| `roi_external_drift_mm` | **0.35424330830574036**（`--step full --backend global_sdf` 重跑逐位相同，退出码 0） | 0.00034815253457054496 |
| audit v1 | `PASS` / `failure_codes=[]` | `PASS` / `[]` |
| audit v2 | **`FAIL`** / `["ROI_EXTERNAL_DRIFT_EXCEEDED"]` | `PASS` / `[]` |

**翻转清单（扫 `data/**` 的 7671 个 JSON + 48 个 sqlite）**：带漂移检查的记录 396 条 → **246 条由
PASS 翻 FAIL**（117 个文件）、148 条本已 FAIL、2 条（窄带）仍 PASS。分类：`data/a12_exports/**`
**13 记录 / 7 文件**（`full/assets/asset_*/meta.json` ×6 + `closed_loop/store/reports/coverage_rows.json`）、
其它 store 资产 90/41（role 全为 `physical_result`）、`a12_reports/**` 7/7、`*/store/reports/coverage_rows.json`
5/5、`data/_archive_pre_fix/**` 131/57。**如实说明**：训练包本身的 manifest 不带漂移检查字段（漂移审计
在 physical 资产 QA 里），所以"翻 FAIL 的包"指 `data/a12_exports/**` 下的资产库；翻转是**正确行为**
（这些几何确实超标），旧产物零改写，标签登记表 `data/a12_reports/n9_qa_v2_flips.json`
（`superseded_by_qa_policy:a12.qa.v1`，与 `_archive_pre_fix` 同口径）。

**残留缺口**：版本戳未写进落库资产——需要在提交边界（`physical/api.py::commit_physical`）调用策略层，
不在写入范围，已如实登记。

---

## N10 · 难负例辅助表 `research/hard_negatives.parquet`

**Status: 完成（表 + 列语义卡 + 一键开关加载器；未并入主表，未改任何已产出包）**

S2 的 1120 条 mate-present 类中 **880 条** query 侧有邻片 → 独立辅助表；240 条 query 无邻片 →
`rejected` 计数（不监督、不静默丢弃）。

| 项 | 实测 |
|---|---|
| 行数 / 列数 | **880**（全 `kind=R0`）× **15** 列（含 `query_mates`/`candidate_mates` list 列） |
| 产物 | `data/a12_reports/n10/hard_negatives.parquet` + `hard_negatives.card.json`（列语义/约束/rejected 块） |
| 主表 | **一字未动**（构建前后 `relations.parquet` sha256 相同）；类别的 `(query,candidate)` 全部来自主表真实行 |
| 并入反证 | 真检查器 D10：表外违反 3 → 并入 **883**（+880） |
| 一键开关消融（真 batch） | off/on：`positives/negatives/excluded/effective_queries/rank_denominator` 逐位相同、`neg_mask`/`pos_mask` 在 pos/neg 块逐位相同；仅 `hard_negatives` 0→3、批次增宽 3 slot（`c = c_pn + c_hard`） |
| 落位 | `<package>/research/hard_negatives.parquet` 由 `--step install` 一条命令写入；**本轮未对已产出包执行**，因为 `--check` 会把未声明的文件判 `unexpected_extra` 并退出 3（该规则用最小夹具包**实测**），声明写者在 `synlab/storage/export.py`（写入范围外） |

驱动：`tools/a12_n10_hard_negatives_table.py --step all`（退出码 **0**）；加载器：
`synlab/relations/hard_negatives_table.py`（`load_hard_negatives` / `attach_hard_negatives(enabled=)` /
`SYNLAB_HARD_NEGATIVES` 环境开关，默认关）。

---

## 协议一致性契约（engineering_policy §3 第 5 行）

**Status: 完成（13 断言 × 4 实现 × 2 上下文全绿；失败注入 6/6 被抓住）**

细节写在 `docs/a12/relation_negatives.md` §9（本节只记结论）：`synlab/qc/pool_contract.py` 是契约单一
真源，`tools/a12_pool_contract.py --step canonical|real` 退出码均 **0**；同一套断言钉死缺陷 (B) 那一类
（`neighbours()` 语义漂移）并把它的注入逐条抓住。实测到一处**真实分歧**（24 条 `valid=False` 的 `R1`
行被画廊/`PoolIndex` 当普通负例，导出读者拒绝），按"改它=改训练数据"处理为**报告 + 测试钉死**，未擅自
改既有语义。

**本轮回归**：

| 命令 | 退出码 | 结果 |
|---|---|---|
| `pytest tests\a12\qc tests\a12\relations tests\a12\training -q` | **0** | 314 项 / 0 失败 / 0 错误 / 19 跳过（66.7 s；`data/a12_reports/_n9n10_pytest_qct.txt` + `_n9n10_junit.xml`） |
| `pytest tests\a12\qc -q` | **0** | 全绿——`open_items.md` 记录的 `test_store_sqlite_is_opened_read_only` 顺序相关失败**本轮未复现**（如实记录，未改该测试） |
| `tools/a12_pool_contract.py --step canonical` / `--step real` | 0 / 0 | 见上 |
| `tools/a12_n9_qa_tighten.py --step all` | 0 | 翻转 246 记录 / 117 文件 |
| `tools/a12_n10_hard_negatives_table.py --step all` | 0 | 880 行表 + 反证 + 消融 |

**记账（不在本轮写入范围，需 Lead 收口）**：`docs/a12/open_items.md` 的 N9/N10 行状态、
`docs/a12/engineering_policy.md` §3 第 5 行（关系池协议）批次，本轮**未改**（两个文件都不在写入范围内），
其实测结论在本节与 `relation_negatives.md` §9。

---

## 负例资格分歧修复（§9.1.1 → §9.1.2；Lead 裁决：语义修复）

**Status: 完成（单真源 + 第 14 条断言 + 第 7 条注入 7/7；四实现 × 两上下文全绿）**

**问题**：三份池实现按 `kind` 重算负例资格，忽略真值层已写下的 `valid`/`loss_mask`——24 条 `R1`
撤回行（48 有向对 / 26 query，`reason=no_direct_fracture_surface`）仍被 `RelationPool`、
`PoolIndex[exported]`、`PoolIndex[gallery]` 当普通负例供给，而 `ExportedRelationPool`/
`TrainingPoolView` 拒绝。机制：`PoolIndex.confirmed()` 答 `relation() in {R0,R1,R2}`；
`RelationsIndex.confirmed()` 不看 `valid`。

**改法（R2 构造性优先）**：新增 `synlab/relations/legal_negative.py` 作为资格**唯一真源**
（`resolve_negative_eligibility`，判据 `kind ∈ {R0,R1} ∧ valid ∧ loss_mask`，带 `reason`/`detail`）。
四实现（含 `PoolIndex` 两载体实例）**只供给输入、不重算规则**，各增协议方法
`negative_eligibility(a, b)`；`confirmed()` 三处一律改为消费它；`PoolIndex` 对"只能答 `relation()`"
的载体**拒绝供给**并写明原因（缺字段保守拒绝，R5）。守卫四条拒绝一条不少（R5：这是**收紧**）。

**新增断言与注入**：`eligibility_follows_extracted_flags`（第 14 条，期望值来自行集本身；自带撤回行
夹具 `eligibility_context()`，否则会空过）+ 注入 `eligibility_recomputed_from_the_kind`（把两处旧机制
原样复原）→ **canonical 与 real 两套上下文各 7/7 被指名抓住**；四实现 × 两上下文 **14/14**。

**before/after 真实代价**（`negfix` 包 71 片 / 1721 行；before 侧用 `git show HEAD:` 的**冻结修订版**
装载，非手写复现）：

| 指标（实时采样路径 `PoolIndex[exported]`） | before | after |
|---|---|---|
| 负例总数（供给 / batch `legal_negatives`） | 3168 / 3168 | **880 / 880** |
| 其中 `R1` | 48 | **0** |
| `effective_queries` | 48 | **36** |
| 每 query 负例中位数 | 53.0 | **9.0** |
| `rank` `n_valid` / `n_allowed` | 48 / 48 | **36 / 36** |
| 被当负例供给的撤回行（§9.1.1 口径 48 有向对） | 48 | **0** |

画廊侧供给 4696 → 2408（每 query 中位数 67 → 23，71 个 query 仍有负例）。**如实报告**：`R1` 负例供给
归零（本包没有 `kind=R1 ∧ valid ∧ loss_mask` 的行），另有 1120 条 `R0`（`loss_mask=False`，
即 N10 的 `CANDIDATE_MATE_PRESENT_NOT_ORDINARY` 类）一并被收紧排除；**未回退口径**。解锁条件写在
`relation_negatives.md` §9.1.2 末（需要真实 R1 直接断口表面标注，或按 N10 走辅助项）。

**本轮回归**：

| 命令 | 退出码 | 结果 |
|---|---|---|
| `pytest tests\a12\qc tests\a12\relations tests\a12\training -q` | **0** | **323 项 / 0 失败 / 0 错误 / 19 跳过**（59.9 s；`data/a12_reports/_negfix_pytest_qct.txt` + `_negfix_junit.xml`） |
| `pytest tests\a12\storage tests\a12\operators tests\a12\diagnostics tests\a12\episodes -q` | **0** | 旁证全绿（`data/a12_reports/_negfix_pytest_side.txt`） |
| `tools/a12_pool_contract.py --step all` | **0** | 5 实例 × 14/14 × 两上下文、注入 7/7、资格分歧 0（保守缺口 861 → 835） |
| `tools/a12_negfix_eligibility.py --step compare` | **0** | before 48 有向对全被三读者提供 → after 0；`data/a12_reports/negfix_eligibility.json` |

**仍未解决**：`R1` 负例供给为 0（需新标注或 N10 辅助项路线）；`relations.sampler`/`relations.negatives`
（library 路线）未接入单真源；`negfix` 包 `relations.parquet` 仍是旧口径（`trainable` 包已是新口径，
`data/**` 不在写入范围）；隐式 `R0` 与导出 `UNKNOWN` 的 835 条保守缺口属既有设计差异，未改。
