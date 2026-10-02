# A12 数据集登记表（库 / 导出包）

本文逐个登记磁盘上**实际存在**的 store 与导出包，并为每一个给出**由闸门实跑得到**的
"是否可训练"判定。表中每个数字都能由脚本复算（命令见 §7）；本文不含任何凭印象写下的结论。

- 闸门实现：`synlab/qc/data_quality.py`（新增，只读）
- 命令行：`tools/check_data_quality.py`（新增，只读）
- 逐目标 JSON：`data/a12/reports/data_quality_<slug>.json`（21 个）
- 汇总留档：`data/a12/reports/_qc_all_stores.txt`（`--all` 的完整输出，退出码 3）、
  `data/a12/reports/_qc_registry_facts.{json,txt}`（本文各表的机器可读来源）
- 扫描时刻的代码状态：git HEAD `c3a149f6aee73245db7c3540e55c0292da2d1a66`，
  工作区 dirty（29 个差异文件，含本次新增的闸门/测试/文档），
  `REGISTRY.fingerprint()` = `sha256:05f69981b63e739f8533b51cee98e54f296fba89d823abf8779814ef2b9624fb`
  （**注意**：该 fingerprint 依赖 import 顺序，只作记录，不作判据，见 §5）
- **扫描时刻**：2026-10-02 12:41（本地，以 `data_quality_*.json` 的 mtime 为准）。
  `data/a12_trainable/store` 在同一时间**仍在被另一名队友写入**，它的资产数/计数会继续变；
  **以 `data/a12/reports/data_quality_data__a12_trainable__store.json` 为准重跑即可**，
  本文该行数字是那一刻的快照（已在 §2 与 §3.5 标注）。

---

## 0. 结论摘要（一句话版）

**扫描 21 个目标，0 个可训练。** 最严重的问题不是某一份数据坏了，而是**三处标记在批产产物里
根本没落盘**，导致"这份资产属于哪一代"在库层面**不可判定**：

1. `mother_mesh` 资产**不记录** `registry_version`，也不记录 `profile_metrics.z_rim_target_mm`
   —— 71/71（`data/a12`）、21/21（closed_loop）、全部其它 store 皆然。
   原因是 `synlab/mothers/api.py:379` 写的 `registry_version` 到了提交路径
   `synlab/pipeline.py::_commit_mother`（L1011-1021）被丢掉了，只落了
   `vessel_id/material_id/mother_id/params/charts/variant/data_semantics/run_id`。
   库层面**唯一**可用的几何身份是 `qa.geometry_hash`，而它没有可比对的参考值。
2. 导出包（`export_manifest.json`）**完全不携带语义代标记**：全文没有
   `mask_semantics / damage_semantics / obs_semantics / registry_version` 任何一个键
   （实测出现次数 0）。所以**光看包无法判断它属于哪一代**。
3. `data/a12_demo/store` 是**真正混代**的一例：14 个母体里 8 个 `registry_version=1.0`、
   6 个 `1.1`，且 12 个带 `profile_metrics` 的母体里 **2 个 `z_rim` 被截断**（旧几何）。

因此当前**没有任何** store 或导出包可以拿来训练；每一个"缺什么才能变可训练"都写在 §4 的表里。

---

## 1. 闸门做了什么判定

`assess_target()` 对每个目标跑 15 项检查，每项都有**真实分母**与**真实命中数**，
缺标记一律记 `MISSING`（**绝不当作通过**）：

| 检查 id | 判据（阈值） | 阈值来源 |
|---|---|---|
| `semantics.mask_semantics` | 每个带 `data_semantics` 的资产 `mask_semantics == coc_units_v2` | `synlab/observe/render.py::MASK_SEMANTICS` |
| `semantics.damage_semantics` | 每个带 `damage_semantics` 的资产 `== subset_v2` | `synlab/physical/api.py::DAMAGE_SEMANTICS` |
| `semantics.obs_semantics` | 每个 `obs_result` `== physical_side_v2` | `synlab/pipeline.py::OBS_SEMANTICS_V2` |
| `semantics.generation_uniform` | 只能有一个语义代；`legacy == 0 且 mixed == 0`（`missing` 单列，另行判定） | `docs/a12/data_semantics_versions.md` §3 |
| `geometry.registry_version` | 每个 `mother_mesh` 记录的版本 == 当前注册表条目版本（V01–V12/V15/V16/V17 = `1.1`，其余 `1.0`） | `docs/a12/mother_geometry_audit.md` §4.4 步骤 1 |
| `geometry.rim_consistency` | `z_rim_target_mm − z_rim ≤ max(2.0 mm, 1 % × 目标)`（**有符号**） | `data/a12/reports/mother_geometry_audit.json:symptom_rules.S1_profile_truncated` |
| `geometry.geometry_hash` | 每个 `mother_mesh` 有非空 `geometry_hash`，且不落在已记录的**改前**参考集里 | `synlab/mothers/api.py:384`；参考集 `mother_geometry_audit.json` / `geom_fix/s15_audit_all.json` |
| `qa.census_conservation` | `QA_PASS + QA_PENDING + QA_FAIL == 资产总数` 且无未知状态 | `synlab/storage/store.py` |
| `qa.release_closure_pass` | release 闭包引用的每个资产都是 `QA_PASS` | 计划 §30.18 / `synlab/storage/release.py` |
| `training.encodable_endpoints` | 每条确认 R2 的**两端**都可编码 | `synlab/training/model.py:313` |
| `training.legal_negatives` | `eligible_as_negative ≥ 1`（`kind ∈ {R1,R0} 且 valid 且 loss_mask`） | `synlab/storage/export.py:80,581-583` |
| `training.per_task_labels` | 五个任务每个都 `n_allowed > 0` 或有**持久化**的结构性无标签标记 | 任务书 (d) / `synlab/training/trainer.py:364-442` |
| `training.effective_queries` | `≥ 1` 个 query 同时有可编码正例与可编码合法负例 | `docs/a12/training_run.md` §"训练有效性" / `synlab/training/batch.py:107-120` |
| `provenance.export_manifest_hash` | 包 manifest 自哈希可复算且一致 | `synlab/storage/export.py:807-808` |
| `provenance.git_and_registry` | **只报告不设门**：git HEAD、dirty + 差异文件数、registry fingerprint、run_id 归属普查 | 任务书 (e) |

**关于 `geometry.rim_consistency` 阈值为什么不能写成 `|差| ≤ 2.5 mm`（重要，别改回去）**：
修复后口沿鼓起会**负向**超出，实测一个**正确的**修复后资产
（`geom_fix/s14_frozen_after.json` 的 `LIN0006_V09_M09_PAT03.z_rim_shortfall_mm = -3.487551118437068`）
会被对称 2.5 mm 判据误杀。所以闸门用审计自己的**有符号 S1 规则**，
2.5 mm 只作为 `thresholds[]` 里的 warning 记录。测试
`tests/a12/qc/test_data_quality.py::test_rim_rule_is_signed_and_scale_aware` 钉住了这条语义。

**判定状态**：`PASS` / `FAIL` / `MISSING`（该量在产物里**不存在**，不是"大概没事"）/
`NOT_APPLICABLE`（该量在这类目标里**结构上不可能存在**，例如导出包里没有母体元数据）/
`UNREADABLE`（文件在但读不了，路径逐条列出）。

**判定语义（三种"不可训练"要分清）**：

- `trainable`（退出码 **0**）：全部 `required` 检查 PASS；
- `partial`（退出码 3）：**唯一**含义是"有监督、但没有合法负例"——即
  `legal_negatives == 0` 且有可编码正例，正例类任务（`view`）能训、`rank` 任务不能训。
  这是任务书要求保留的中间判定；
- `not_trainable`（退出码 3）：其余全部情形。

---

## 2. 判定总表（21 个目标）

`QA` 列是 `PASS/PENDING/FAIL`；"语义代"列是 `semantics.generation_uniform` 的结论
（`PASS` 只表示**不混**，不表示"是新一代"——是否新一代由 `mask/damage/obs` 三项与
`geometry.registry_version` 决定）。"可训练"列是闸门实跑结论。

| # | 路径 | 类型 | 资产数 | QA | 语义代（混代？） | 可训练 | 首因（第一阻塞项） |
|---|---|---|---|---|---|---|---|
| 1 | `data/a12` | store | 894 | 594/261/39 | `PASS` 但 **103 current + 379 missing** | **否** | `semantics.mask_semantics` FAIL 71/397 |
| 2 | `data/a12/reports/failure_fix_store` | store | 93 | 67/18/8 | `PASS`，全部 missing（旧代） | **否** | `semantics.mask_semantics` FAIL 0/45 |
| 3 | `data/a12/reports/l0_after_fix/store` | store | 15 | 12/3/0 | `PASS`，3 current + 6 missing | **否** | `semantics.mask_semantics` FAIL 1/7 |
| 4 | `data/a12/reports/l0_after_fix_v2/store` | store | 15 | 12/3/0 | `PASS`，9 current + 0 missing | **否** | `semantics.obs_semantics` FAIL 0/1 |
| 5 | `data/a12_demo` | store | 0 | 0/0/0 | `MISSING`（空库） | **否** | `semantics.mask_semantics` MISSING（分母 0） |
| 6 | `data/a12_demo/store` | store | 276 | 223/53/0 | **FAIL：混代 6 current + 8 legacy + 23 missing** | **否** | `semantics.mask_semantics` FAIL 0/23 |
| 7 | `data/a12_exports/_scratch/gen1` | store | 7 | 5/2/0 | `PASS`，全 missing | **否** | `semantics.mask_semantics` FAIL 0/3 |
| 8 | `data/a12_exports/_scratch/gen2` | store | 7 | 5/2/0 | `PASS`，全 missing | **否** | 同 7 |
| 9 | `data/a12_exports/_scratch/gen3` | store | 14 | 10/3/1 | `PASS`，全 missing | **否** | `semantics.mask_semantics` FAIL 0/7 |
| 10 | `data/a12_exports/_scratch/gen4` | store | 14 | 10/3/1 | `PASS`，全 missing | **否** | 同 9 |
| 11 | `data/a12_exports/_scratch/gen5` | store | 14 | 10/3/1 | `PASS`，全 missing | **否** | 同 9 |
| 12 | `data/a12_exports/_scratch/store_backup_a12` | store | 247 | 111/128/8 | `PASS`，全 missing | **否** | `semantics.mask_semantics` FAIL 0/97 |
| 13 | `data/a12_exports/cl_fresh/store` | store | 15 | 14/0/1 | `PASS`，全 missing | **否** | `semantics.mask_semantics` FAIL 0/7 |
| 14 | `data/a12_exports/closed_loop/store` | store | 175 | 165/7/3 | `PASS`，全 missing（旧代） | **否** | `semantics.mask_semantics` FAIL 0/129 |
| 15 | `data/a12_exports/closed_loop/training_package` | package | 165 | 不记录 | `MISSING`（包不带标记） | **否** | `semantics.mask_semantics` MISSING |
| 16 | `data/a12_exports/next_experiment/training_package` | package | 447 | 不记录 | `MISSING`（包不带标记） | **否** | `semantics.mask_semantics` MISSING |
| 17 | `data/a12_exports/pilot_gate/store` | store | 17 | 17/0/0 | `PASS`，2 current + 7 missing | **否** | `semantics.mask_semantics` FAIL 0/7 |
| 18 | `data/a12_exports/runid_fix/after_store` | store | 15 | 11/3/1 | `PASS`，全 missing | **否** | `semantics.mask_semantics` FAIL 0/7 |
| 19 | `data/a12_exports/runid_fix/before_store` | store | 15 | 11/3/1 | `PASS`，全 missing | **否** | 同 18 |
| 20 | `data/a12_probe_tmp` | store | 42 | 33/9/0 | `PASS`，全 missing | **否** | `semantics.mask_semantics` FAIL 0/21 |
| 21 | `data/a12_trainable/store`（队友持续写入中） | store | 114 | 91/21/2 | `PASS` 但 **43 current + 32 missing** | **否** | `semantics.mask_semantics` FAIL 33/65 |
`data/a12_trainable/store` 是**唯一**在本次扫描中出现"相当一部分资产带当前代标记"的 store
（`damage_semantics` 43 个、`obs_semantics` 7 个、`mask_semantics` 33 个），但它**同时**还有
32 个资产完全没有标记 —— 这正是**混代**，不是"新代"；它仍卡在几何代不可判定、没有 release、
没有关系表。它由另一名队友持续写入，**此处数字是扫描时刻的快照**。

---

## 3. 逐目标：为什么不可训练、缺什么才能变可训练

### 3.1 `data/a12`（894 资产 / 21 run / 0 release）—— 主库

**为什么不可训练**（全部是实测命中）：

- `semantics.mask_semantics` **FAIL 71/397**：71 个带 v2 标记，326 个**没有任何标记**。
- `semantics.damage_semantics` **FAIL 103/482**：103 带标记，379 缺失。
- `semantics.obs_semantics` **FAIL 0/37**：37 个 `obs_result` **一个都没有** `obs_semantics`
  —— 与 `data/a12/reports/trainable_prereq_check.json` 记录的「37 个 obs_result，直方图全
  `None`」逐位一致，说明 `-p` 侧两端点观测在库里仍是空的。
- `geometry.registry_version` **MISSING 0/71**、`geometry.rim_consistency` **MISSING 0/0**
  （71 个母体**没有** `profile_metrics`）：几何代**不可判定**。
- `geometry.geometry_hash` PASS 71/71，但**71 个都没有参考值可比对**（批产参数与审计原型
  参数不同，hash 自然不同），所以它只能证明"有哈希"，不能证明"是新几何"。
- `qa.census_conservation` PASS（594+261+39 = 894）；**但没有 release**，闭包无从检查。
- `training.legal_negatives` **FAIL 0/132**：132 条关系行（`R1` 128 / `R2` 4），
  **没有一条** `valid and loss_mask` 的 R1/R0。
- `training.encodable_endpoints` **FAIL 0/4**：4 条确认 R2，18 个端点找不到 feature payload。
- `training.per_task_labels` **FAIL 2/5**：`rank/correspondence/contradiction` 既无标签也无标记。
- 12 个 `feature_bundle` 连 `meta.fragment_id` 和 `meta.component_id` 都没有 → 无法映射到任何
  fragment（见 §6 的 unreadable 清单）。

**缺什么才能变可训练**：① 重新产出一批（`docs/a12/data_semantics_versions.md` §3 明确建议
"要么按标记分开用，要么整批重生成"）；② 让 `_commit_mother` 落 `registry_version` 与
`profile_metrics`；③ 走多事件库路线产出合法负例（单事件管线**不可能**产出，见
`trainable_prereq_check.json:92`）；④ 冻结一个 release 并把 39 个 QA_FAIL 挡在闭包外。

### 3.2 `data/a12_exports/closed_loop/store`（175 资产 / 7 run / 8 release）—— 唯一闭包全绿的 store

**实测**：`qa.release_closure_pass` **PASS 165/165**（8 个 release，闭包 95/113/139/165×5，
全部引用资产都是 `QA_PASS`）。但 `mask_semantics` **0/129**、`damage_semantics` **0/132**、
`obs_semantics` **0/3** —— **整库旧代**，一个标记都没有。

**run_id 归属（闸门普查）**：175 个资产里 **150 个**带
`meta.run_id_source = "closed_loop._tag_run_assets…"`（即补戳），18 个是提交时写的，7 个无
`run_id`。与 `data/a12/reports/runid_fix_manifests.json` 的 147/165（该文件的分母是 release
闭包 165，本文分母是全库 175）**在各自分母内一致**；两个数都对，口径不同，此处并列，不混用。

**缺什么**：整批重生成到新 store（旧语义的掩码覆盖率只有 0.26–7.20 %，损伤结果不合法，
`docs/a12/data_semantics_versions.md` §1.4/§2.3），并让新母体落几何标记。

### 3.3 `data/a12_demo/store`（276 资产）—— **实测混代的一例**

`semantics.generation_uniform` **FAIL**：`current=6, legacy=8, missing=23`。
`geometry.registry_version` **FAIL 8/14**：观测到 `{'1.0': 8, '1.1': 6}` —— 同一库里有 8 个
旧几何母体和 6 个新几何母体。`geometry.rim_consistency` **FAIL 10/12**：12 个带
`profile_metrics` 的母体里 **2 个 `z_rim` 低于声明值**（旧几何）。这个 store 能拿到
`profile_metrics`，是因为它由 `tools/build_demo_assets.py` → `synlab/mothers/api.py:commit_mother`
（L752-765，会把整份 `mother_meta` 写进资产）产出，而**批产路径不会**。

**缺什么**：整库重生成（这批演示资产的几何、掩码、损伤语义互不相容）。

### 3.4 导出包：`next_experiment` 与 `closed_loop`

- `next_experiment/training_package`（447 资产 / 150 关系行）：`qa.release_closure_pass`
  **FAIL 343/475** —— 132 个闭包问题（80 个 `QA_PENDING`、24 个 `QA_FAIL`、28 个"引用的资产
  不在库里"）。`legal_negatives` **FAIL 0/150**（`R1` 117 / `R2` 33，117 条 R1 全是
  `valid=false, loss_mask=false`）；`encodable_endpoints` **FAIL 0/33**（58 个端点在
  `deploy/deploy_index.json` 里三个 shard 全为 `null`）。
  manifest 自哈希 **PASS**（可复算一致）。
- `closed_loop/training_package`（165 资产 / 3 关系行）：`encodable_endpoints` **FAIL 0/3**
  —— `-m` 侧有 shard、`-p` 侧三个 shard 全 `null`，即 R2 的另一端根本没带观测；
  `legal_negatives` **FAIL 0/3**。
- **两个包都缺同一个东西**：包里没有语义代标记，所以"它是哪一代"永远判不出来。

**缺什么**：① `export_manifest.json` 落一份 `data_semantics`（含
`mask/damage/obs_semantics` 与 `registry_version` 汇总），或强制"包必须与源 store 一起登记"；
② 让 `-p` 侧也进 deploy 视图（`obs_semantics=physical_side_v2` 的产物）；③ 走多事件库路线
产出合法负例。

### 3.5 其余 store（清单式）

| 路径 | 实测阻塞（除"缺语义标记"外） | 缺什么 |
|---|---|---|
| `reports/failure_fix_store` | 93 资产 / 8 QA_FAIL / 无 release / 0 合法负例 | 全批重生成 |
| `reports/l0_after_fix/store` | 15 资产，只有 3 个带标记（该 run 共 15 资产，**9 个**才该带标记） | 重生成（旧 store，缺 6 个标记） |
| `reports/l0_after_fix_v2/store` | 15 资产，9 个标记全在，但 `obs_semantics` 0/1 | 这是"补标记复验"的 store，仍未落 `obs_semantics` |
| `_scratch/gen1..gen5` | 每次调试的单母体 store，全 missing、带 QA_FAIL | 丢弃（调试产物） |
| `_scratch/store_backup_a12` | 247 资产 + **8 个 payload 文件已丢失**（见 §6） | 只作备份留档，不可训练 |
| `cl_fresh/store` | 15 资产 / 1 QA_FAIL / 无 release | 重生成 |
| `pilot_gate/store` | 17 资产全 QA_PASS，但只有 `physical_result/physical_component` 2 个带 `damage_semantics` | 补全标记 |
| `runid_fix/{before,after}_store` | 15 资产，run_id 归属修复的 A/B 对照 | 只作对照留档 |
| `a12_probe_tmp` | 42 资产探针库 | 丢弃 |
| `a12_demo`（根） | **空库**（0 资产、0 run） | 不是数据集 |
| `a12_trainable/store`（队友写入中，快照 2026-10-02 12:41） | 114 资产（91/21/2）；`mask` 33/65、`damage` 43/75、`obs` 7/23 → **混代**；缺 `registry_version`/`profile_metrics`、无 release、**0 条关系行** | ① 母体落几何标记；② 把 32 个无标记资产整批重生成或按标记分开；③ 出关系表并含合法负例；④ 冻结 release |

---

## 4. "变可训练"的共同前置（按阻塞面排序）

1. **让母体带上几何代身份**：`synlab/pipeline.py::_commit_mother` 增写
   `registry_version` 与 `profile_metrics`（`synlab/mothers/api.py:379` 已算出，只是没落盘）。
   这是**唯一**能同时解开 `geometry.registry_version` 与 `geometry.rim_consistency` 两项
   MISSING 的改法。该改动属 `synlab/pipeline.py`，**不在本次写入范围**。
2. **让导出包带语义代**：`export_manifest.json` 落 `data_semantics`。属
   `synlab/storage/export.py`，**不在本次写入范围**。
3. **`-p` 侧观测进 deploy 视图**：否则每条 R2 的另一端永远不可编码（
   `closed_loop/training_package` 实测 0/3）。
4. **合法负例**：单事件管线结构性产不出（`relations/gallery.py:134-137` R0 隐式不落库），
   必须走多事件库路线。
5. **冻结 release**：`qa.release_closure_pass` 的分母来自 release 闭包；没有 release 就是
   MISSING，而不是 PASS。

---

## 5. 阈值与口径的诚实声明

- `geometry.geometry_hash` 的 PASS **不等于**"新几何"。它只检查"有哈希且不落在已记录的改前
  参考集里"。批产参数与审计原型参数不同，hash 本来就不会命中参考集，所以本表里它普遍显示
  `N passed / 0 pre-fix reference / N no reference`。**这是如实报告，不是放宽**。
- `REGISTRY.fingerprint()` **不作为判据**：实测同一个工作区在只 import
  `synlab.mothers.api` 时得 `sha256:a96fd2d1…`（只有 vessel 一类条目），在 `load_all()` 之后
  得 `sha256:05f69981…`。`data/a12/reports/geom_fix/s17_registry_versions.json` 记录的是
  前者（部分注册表）。闸门只把它当证据记录。
- git dirty **只报告不设门**：闸门自身就会新增文件。报告里带差异文件数与文件名（截断到 200 条）。
- 所有阈值都写在对应检查的 `thresholds[]` 里，含 `source`；`honesty.relaxed_thresholds`
  恒为空数组。

---

## 6. 磁盘上存在、但**不是**闸门目标的位置（诚实清单）

| 路径 | 状态 | 为什么不判 |
|---|---|---|
| `data/a12_geom_v11` | **不存在** | 任务书提到的这个路径在磁盘上没有；`Test-Path` = False |
| `data/a12/store` | 存在，但只有 `store.sqlite`，**表列表为空**（`[]`） | 没有 `metadata.sqlite`，也没有 `assets` 表 → 不是 store |
| `data/a12_exports/next_experiment`（目录本身） | 有 `gates_evaluated.json` / `release_freeze_blocked.json`，无 `metadata.sqlite`/`export_manifest.json` | 不是 store 也不是包；其包在 `next_experiment/training_package` |
| `data/a12_exports/trainable` | **空目录**（0 项） | 无目标 |
| `data/a12_exports/relation_negatives` | 只有 `meshes/`、`work/`、`library_plan.json` | 未导出成包，无 manifest |
| `data/a12_exports/closed_loop/release_index` | `export_manifest.json` 是 `synlab.export.v1` 的**元数据索引**（165 资产，`"write_scope": "read_only"`），不是训练包 | 按 `--all` 规则排除（它不含训练视图） |
| `data/a12/reports/_store_backup_pre_feature_leak_repair.sqlite` | 独立 `.sqlite` 文件（不是 `metadata.sqlite`），247 资产 | 不在 `**/metadata.sqlite` 扫描范围内；仅作备份 |
| `data/a12_exports/_scratch/store_backup_a12`（已扫描） | 扫描了，但 **8 个 payload 文件确实丢失** | 在报告 `unreadable` 里逐条列出 |

**本次扫描中读不到的东西（全部原样列出，不隐藏）**：

| 目标 | 条数 | 内容 |
|---|---|---|
| `data/a12` | 12 | 12 个 `feature_bundle` 既无 `meta.fragment_id` 也无 `meta.component_id`，无法映射到 fragment |
| `data/a12_demo/store` | 9 | 同上 |
| `_scratch/gen3` / `gen4` / `gen5` | 各 1 | 同上 |
| `_scratch/store_backup_a12` | 32 | 24 个无 fragment 身份的 feature bundle + **8 个 payload 缺失**（`QcInputError: payload missing: …`） |
| 其余 15 个目标 | 0 | — |

`data/a12` 里 45 个 feature bundle 中 33 个只有 `meta.component_id`（形如
`<fragment_id>#c<k>`），闸门按 `#` 前缀取 fragment id 并在
`training.encodable_endpoints.evidence.fragment_id_sources` 里标明来源
（`meta.fragment_id` / `meta.component_id (prefix before '#')`），所以分母依然可审计。

---

## 7. 复现命令（含退出码）

```powershell
cd C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab

# 1) 单个 store / 单个包
& .venv\Scripts\python.exe tools\check_data_quality.py --store data\a12            # exit 3, 写 data_quality_data__a12.json
& .venv\Scripts\python.exe tools\check_data_quality.py --package data\a12_exports\next_experiment\training_package
& .venv\Scripts\python.exe tools\check_data_quality.py --store data\a12 --no-report   # 只打印

# 2) 全盘扫描（21 个目标；本表出处）
& .venv\Scripts\python.exe tools\check_data_quality.py --all > data\a12\reports\_qc_all_stores.txt 2>&1  # exit 3

# 3) 汇总成机器可读事实表
& .venv\Scripts\python.exe data\a12\reports\_qc_registry_facts.py > data\a12\reports\_qc_registry_facts.txt

# 4) 单测
& .venv\Scripts\python.exe -m pytest tests/a12/qc -q           # exit 0, 51 passed（16 旧 + 35 新）
```

退出码：`0` = 可训练；`3` = 不可训练（`partial` 或 `not_trainable`，stdout 打印首因与逐项明细）；
`2` = 目标既不是 store 也不是包；`1` = 闸门自身异常。

本文用到的复算脚本（全部在 `data/a12/reports/`，全部只读）：
`_probe_stores.py`（逐库角色/QA/标记普查）、`_probe_keys.py`（逐角色 meta 键普查）、
`_probe_qa_keys.py`（逐角色 QA 键普查）、`_probe_dump.py`（单资产全量导出）、
`_probe_meta.py`（run/母体/feature/ release 结构）、`_qc_summary.py`（逐报告摘要）、
`_qc_registry_facts.py`（本文 §2–§3 的机器可读来源）、`_qc_unused.py`（新增模块的未用名检查）。
原始输出：`_probe_stores.json`、`_qc_summary.txt`、`_qc_registry_facts.{json,txt}`、
`_qc_all_stores.txt` + `_qc_all_stores_exit.txt`、`pytest_qc_data_quality.txt` +
`pytest_qc_data_quality_exit.txt`。

---

## 8. 仍未解决 / 需要别人落地的

1. `synlab/pipeline.py::_commit_mother` 不落 `registry_version` / `profile_metrics`
   —— 本次写入范围外，**这是解开几何代判定的唯一路径**。
2. `export_manifest.json` 不落语义代 —— 写入范围外。
3. `data/a12_trainable/store` 仍在被另一名队友写入；本文数字是扫描时刻快照，
   它的关系表与 release 尚未出现。
4. `geom_fix/plan_drift_after_geometry_fix.json` **不存在**，`geom_fix/plan_drift/` 只有 10 个
   `*_after.json`、没有 `*_before.json` —— 几何修复后的计划漂移问题在仓库里**仍未回答**
   （`docs/a12/mother_geometry_audit.md` §5 已把它列为未解决）。
5. `data/a12` 的 39 个 `QA_FAIL` 与 261 个 `QA_PENDING` 是否需要清理/墓碑化，本文只如实计数，
   未做任何处置。
6. 单事件管线结构性产不出合法负例（`relations/gallery.py:134-137` 的 R0 隐式语义），
   训练侧要靠多事件库路线；这一点在闸门里以 `training.legal_negatives.evidence.note` 记录。
