# A12 验收增量报告（acceptance delta）

- 生成方式：本文件由本轮实跑结果汇总，所有数字取自 `data/a12/reports/` 下的真实产物与
  `data/a12/reports/acceptance_summary.json`，没有手写推测值。
- 基线快照：`data/a12/reports/_baseline/acceptance_summary_before.json`
  （本轮开始前最近一次 `synlab acceptance --profile SANDBOX_CORE` 的结果）。
- 本轮验收快照：`data/a12/reports/acceptance_summary.json`（`generated_at=1790876724.42`，
  2026-10-02 01:45:24 本地时间）。
- 状态矩阵：`docs/a12/status_matrix.csv`（`python tools/gen_status_matrix.py --data-root data/a12`）。
- 验收报告：`docs/a12/acceptance_report.md`（由 `synlab.cli acceptance` 直接生成，未手工编辑）。

## 1. 前后计数

| 状态 | 前 | 后 | 变化 |
|---|---|---|---|
| PASS | 5 | **10** | +5 |
| PENDING | 3 | **5** | +2 |
| FAIL | 4 | **7** | +3 |
| NOT_RUN | 17 | **7** | −10 |
| NA（该 profile 不适用） | 7 | 7 | 0 |
| 合计 | 36 | 36 | — |

`NOT_RUN` 从 17 项降到 7 项；`FAIL` 增加是因为 5 项此前根本没有证据（`NOT_RUN`），
本轮跑出实测后如实落到 `FAIL`（A05/A24/A25 + A01 的状态变化）。

## 2. 逐项迁移（只列状态发生变化者）

| ID | 前 | 后 | 依据（真实产物） |
|---|---|---|---|
| A01 | PASS | **FAIL** | 见第 5 节：算子审计把 20 个带 `axis_id/level/variant` 的结果资产提交到 `feature_bundle` 角色，A01 的“承诺特征不得携带答案字段”因此不成立 |
| A05 | NOT_RUN | **FAIL** | `pattern_audit.json`：16 族全部实测（真实母体 `V01-M01-101`，6624 面），14 族 QA_PASSED；PAT07/PAT08 的 `cut_continuity` 继承检查失败；最大接缝色差 6.18e-14 ≤ 1e-5 |
| A10 | NOT_RUN | **PENDING** | `operator_audit.json`：31 轴全部注册并实测，26 PASS / 5 NA / 0 FAIL，`identity_ok=true`；但每轴 `independent_mothers=1`，未达 20，故 PENDING |
| A11 | NOT_RUN | **PASS** | `spurious_audit.json`：G08 三变体（凸起/补面/假桥）实测通过，level-0 恒等性成立 |
| A12 | NOT_RUN | **PASS** | `channel_audit.json`：深度中位误差 0.431 mm、标签为整型且小数标签 0 个、不确定带 3438 px 中有 176 px 落在可见性轮廓上、部署 mask 排除不确定像素 |
| A13 | NOT_RUN | **PENDING** | `camera_profile_audit.json`：`engineering_ok=true`（U 位移只改外参、不改像幅，往返 2.8e-14 mm）；本机无实拍标定数据，`calibration_ok=false` → 真实标定保持 PENDING |
| A18 | NOT_RUN | **PASS** | `metric_fixture.json` 62/62、`stat_fixture.json` 28/28 全部通过 |
| A20 | NOT_RUN | **PASS** | `api_ui_evidence.json`：`create_app(role="researcher")` + TestClient 实测 `/api/synlab/capabilities`=200、`/registry/vessel`=200、`/assets`=200（5 条），且 `frontend/dist/index.html` 存在 |
| A24 | NOT_RUN | **FAIL** | `source_dependency_audit.json`（同仓另一位队友产出）：`gt_pose_invariance=false` |
| A25 | NOT_RUN | **FAIL** | `pixel_contract.json`：`synlab/cameras/audit.py` 已由队友补齐，实测发现 `synlab/api/display.py::authority_to_display` 的缩放为 `1e6`（应为 `1e-3`），列为 blocking defect |
| A30 | NOT_RUN | **PASS** | `metric_fixture.json`：`hand_computed_hit/poolcov/cov`、`effective_zero_on_failure`、`absent_risk_defined` 五项全为 true |
| A36 | FAIL | **PASS** | 见第 3 节 |

其余项状态未变：A02/A23/A33/A34 保持 PASS；A03/A22/A28 保持 PENDING；A06/A09/A17 保持
FAIL；A14/A16/A21/A29/A31/A32/A35 在该 profile 下为 NA。

## 3. A36 根因与修法

### 3.1 诊断过程

逐个执行 `synlab validate --config <每个 configs/a12/*.yaml>` 与 `compile_recipe`：

| 配置 | `synlab validate` | A36 旧逻辑（按文件名分派） |
|---|---|---|
| `sandbox.yaml` / `pilot.yaml` / `coverage.yaml` | exit 0 | OK（`GenerationSpec`+`compile_spec`） |
| `diagnose_sandbox.yaml` | exit 3 | OK（`DiagnosticSpec`） |
| `train_sandbox.yaml` / `train_pilot.yaml` | exit 3 | OK（`TrainingSpec`） |
| `pool_dev.yaml` / `pool_pilot.yaml` | exit 3 | **ERROR（14 条 `extra_forbidden`）** |
| `degrade_recipes/*.yaml` | — | OK |

### 3.2 根因

`pool_dev.yaml` / `pool_pilot.yaml` 声明的是 `schema: synlab.pool.v1`，由
`synlab.relations.api.PoolConfig.from_mapping` 消费（严格拒绝未知键 + `scope` 枚举校验）。
它们**本身是合法的**：`PoolConfig.from_mapping` 对两个文件都返回 OK
（`sandbox_dev`/`FULL`/200 与 `pilot_dev`/`FULL`/1000）。

A36 旧逻辑把 `configs/a12/*.yaml` 中除 `train*`/`diagnose*` 之外的所有文件都交给
`GenerationSpec` 编译，于是把 pool 配置当成生成配置来校验——“证明”的只是两个 schema 不同，
并不是配置文件有错。`synlab validate` 有同样的分派缺口（它只认 `GenerationSpec`）。

因此**不是配置文件写错，也不是 schema 需要放宽**：修的是 harness 的分派。

### 3.3 修法（`synlab/qc/acceptance.py` 的 A36，最小改动）

- 增加 `pool*`/`gallery*`/`roster*` 分支：先断言文件里的 `schema` 必须等于
  `roles.SCHEMA_POOL`（`synlab.pool.v1`），再调用 `PoolConfig.from_mapping(document)`。
- 记录 `validators` 映射，报告里能直接看到每个配置走的是哪个严格模型。
- 未放宽任何 schema：`GenerationSpec`/`TrainingSpec`/`DiagnosticSpec`/
  `DegradationRecipeSpec`/`PoolConfig` 的校验强度都与改动前一致；pool 分支比原来更严
  （额外校验 `schema` 字面量）。

结果：10 个顶层配置 + 2 个 degrade recipe 全部 `OK`，`failed={}` → A36 **PASS**。

未改动：`synlab/cli.py`（不在允许写入范围内）。因此
`synlab validate --config configs/a12/pool_*.yaml` 仍然 exit 3——这是 CLI 的分派缺口，
不是配置缺陷，留给 owner 决定是否让 `validate` 也按 `schema:` 字段分派。

## 4. 本轮补齐的报告产物

| 报告 | 生成调用 | ok / status |
|---|---|---|
| `pattern_audit.json` | `audit_all_patterns(store, families=<4族/批>, n_pairs=150, commit=False)` ×4 批 + 按模块自身规则合并 | false / QA_FAILED（16 族，14 通过） |
| `operator_audit.json` | `audit_all_axes(store, axes=<1轴/进程>, levels=[0,1,2,3,4])` ×31 进程 + 按模块自身规则合并 | true / PASS（31 轴，26 PASS / 5 NA） |
| `operator_measurements.parquet` | `degrade.api.write_operator_measurements(measurements, store=...)` | 150 行 × 313 列 |
| `channel_audit.json` | `observe.audit.audit_channels(store)` | true / PASS |
| `spurious_audit.json` | `observe.audit.audit_spurious(store)` | true / PASS |
| `camera_profile_audit.json` | `observe.audit.audit_camera_profiles(store)` | `engineering_ok=true`、`calibration_ok=false` |
| `pixel_contract.json` | `cameras.audit.audit_pixel_contract(store)`（队友已补齐该模块） | false / FAIL |
| `scale_report.json` | 直接清点 `store.list_assets(role="fragment_mesh")` 等 | false / PENDING（0 个 fragment，L2/L3 运行产物尚未产生） |
| `resource_profile.json` | `qc.profile.profile_run(store, "probe_recovery")` | true / PASS（1 job，实测字节数） |
| `loader_probe.json` | `relations.api.load_pool` / `store.load_arrays` / `FeatureBundle.from_dict` / `ShardedIterableDataset` 真实尝试 | false / NOT_RUN（见第 5 节） |
| `leakage_negative_control.json` | `qc.leakage.run_negative_control(store, "probe_recovery")` | false / FAIL（见第 5 节） |
| `api_ui_evidence.json` | `create_app(store_root, role="researcher")` + `TestClient` 打三个端点 + 检查 `frontend/dist` | true / PASS |
| `metric_fixture.json` / `stat_fixture.json` | `diagnostics.fixtures.run_fixtures()` | true / 62+28 项全通过 |
| `store_health.json` | `storage.store.health_check(str(store_root))` | true / PASS |

所有步骤由 `tools/evidence_min.py --step <name>` **每个步骤一个独立进程**执行、立即写盘；
运行日志与退出码逐条记录。`data/a12/reports/_parts/` 保存分批运行的分片原样输出。

## 5. 仍未通过 / 未运行的项及原因

### FAIL（已实测且有证据）

- **A01** — 承诺的 `feature_bundle` 资产里出现了 `axis_id`/`level`/`variant` 等答案字段。
  直接原因：本轮按任务要求执行的 `audit_all_axes(store, levels=[0,1,2,3,4])` 会通过
  `synlab/degrade/api.py::_apply_impl` 把每个档位的结果资产**提交回 store**，X 轴源是
  feature 角色（资产 meta 里保留了 `origin_role`），因此 20 个结果资产落在
  `feature_bundle` 角色上并携带轴身份。`qc.leakage` 的负控独立复现了同一现象
  （`truth_isolation=false`，problems 列出同一批资产）。
  这是本轮唯一一处 PASS→FAIL：它与 A10 的证据链是同一批真实调用造成的，
  修法在 `synlab/degrade/api.py` 的提交路径或 A01 的判定口径，**不在本轮写入范围**，
  未擅自改动验收口径。
- **A05** — 14/16 族通过；`PAT07`（periodic tile/line lattice）与 `PAT08`（meander fret）
  的 `inheritance check failed: cut_continuity`。接缝、确定性、几何施加、配方哈希唯一性、
  复杂度分层全部通过，只有这两族的继承检查失败。
- **A06** — `fracture_audit.json` 仍来自旧生成 run：唯一一例 `plane_shared_cut` 失败
  （`coverage_rows.json` 记录该母体构建阶段就因 `M01: unknown material parameters` 被隔离，
  没有产出碎片）。要转 PASS 需要一次成功的生成运行。
- **A09** — `physical_audit.json` 同上，来自同一条失败 run，`ok=false`。
- **A17** — `synlab/jobs/recovery.py::recovery_probe` 用固定 `run_id="probe_recovery"` 与
  `job_id="probe_job"` 写持久化 store，store 里已存在这两行，第二次运行必然
  `IntegrityError: UNIQUE constraint failed: jobs.job_id`。属于该文件的缺陷，
  `synlab/jobs/**` 不在写入范围，未改；需要 owner 让 probe 使用唯一 id 或临时 store。
- **A24** — 队友产出的 `source_dependency_audit.json`：`gt_pose_invariance=false`。
- **A25** — 队友补齐的 `pixel_contract` 套件实测出 `synlab/api/display.py::authority_to_display`
  缩放比 `1e6`（应为 `1e-3`）；该函数未被 GLB/UI 主路径使用，属未使用辅助函数的缺陷。
  修 `synlab/api/display.py` 不在本轮写入范围。

### NOT_RUN（本轮范围内无可用能力，如实标注）

- **A07** — 需要一次带误差预算的断裂事件（`precision_report.json`），本机不存在成功 run。
- **A08** — 需要 `synlab.truth` fixture 运行（`truth_fixture.json`）。
- **A15** — 需要先 `synlab build-pool` 产出冻结池；空库下 `build_pool_from_config` 返回
  `GALLERY_SIZE_PENDING`。按本报告口径，把这种“前置条件缺失”写成 `ok=false` 只会让 A15 变
  `FAIL`（该判定没有 PENDING 分支），语义上不如保持 `NOT_RUN`，故未伪写报告。
- **A19** — 同上：无冻结池时 `run_episode_config` 抛 `INPUT_UNAVAILABLE`，写报告只会得到
  语义错误的 `FAIL`。
- **A26** — 需要 `warped_partition` 后端运行（`mesh_warp_report.json`）。
- **A27** — 需要断裂 + 真值审计（`origin_correspondence_audit.json`）。
- **A04** — 需要 `material_layer_audit.json`；仓库没有对应的既有审计 API，且 store 中没有任何
  `material_profile` 资产（0 个），本轮没有可调用的真实入口，未自制审计。

另有 `loader_probe`（非 A 项）为 NOT_RUN：真实尝试 4 条加载路径，`store.list_assets` 里有
20 个 `feature_bundle` 资产，但它们实际是 `a12.obs.v1` 观测资产，`store.load_arrays` 能真实
读出（`payload.K`/`payload.mask`/`payload.modalities.rgb.data` 等），而
`training.adapter.FeatureBundle.from_dict` 需要 `adapt_observed_features` 的载荷形式，
直接抛 `KeyError: 'local_tokens'`；store 中没有 `relation_pool` 资产，
`relations.load_pool` 与 `ShardedIterableDataset` 都拒绝。拒绝是实测结果，没有合成 batch。

### PENDING（前置数据/规模未具备）

- **A03**：已提交母体 1 个（1 vessel × 1 lineage），24 族 × ≥20 独立母体需要 L2 run。
- **A10**：轴身份与效果已实测，但每轴 1 个母体，未达 20。
- **A13**：工程档通过，真实标定无实拍数据。
- **A22**：runbook 存在、store 健康，`releases=0`（尚无发布目录）。
- **A28**：需要 `physical_identity.json`（组件/碎屑/血缘审计）。

## 6. 诚实性与已知偏差

1. **被系统杀掉的进程（如实记录，未反复重试）**
   - `tools/evidence_min.py --step registry`：`[exit -1]`，无 traceback、无任何输出
     （无法确定被杀在导入期还是执行期）；按“不反复重试同一重活”的要求未再重试，
     `registry_summary.json` 保留此前一次的真实产物。
   - `--step axes-batch --batch-size 2 --batch-index 0`：`[exit -1]`，无输出；改为
     **一轴一进程**（`--batch-size 1`，31 个进程）后全部完成。
   - `--step axes-batch --batch-size 1 --batch-index 30`（X05）：`[exit -1]`；单独重跑一次成功。
   - `--step axes-batch --batch-size 1 --batch-index 19`（P02）：一次
     `NameError: name 'roi_faces_of' is not defined`（该名字在 `synlab/degrade/axes.py` 是模块级
     定义的）；记录后单独重跑一次成功，未再复现，最终产物是成功那次。
2. **P04 轴**在 `audit_all_axes` 内抛出 `SynLabError[NA_NOT_APPLICABLE]`（该源体没有
   interface 面属性，P 轴 interface 算子不适用），异常在 `_basis_payload` 阶段逃出逐档
   try/except。分片里按模块自身语义记为 `NA` + 原因，不是臆造，也没有被算作 PASS。
3. **并发协作**：`synlab/cameras/audit.py`、`data/a12/reports/pixel_contract.json`、
   `source_dependency_audit.json`、`mvs_subset.json` 由同仓另一位队友在本轮期间写入；
   本文件的计数取最后一整轮 `synlab acceptance` 的快照，`mvs_subset.json` 在
   `SANDBOX_CORE` 下不影响 A14（NA）。
4. **store 状态变化**：算子审计的提交使 `data/a12` 的资产从 14 个增加到 130 个
   （`feature_bundle` 20、`obs_view` 48、`obs_fused_geometry` 32、`physical_component` 16）。
   这是被要求调用的模块 API 的真实副作用，已如实反映在 A01/A32 的证据里。
5. 本报告不使用任何占位值、随机曲线或复制设计值；缺失能力一律 `NOT_RUN` + 具体原因。

## 7. 复现命令

```powershell
$py = ".venv\Scripts\python.exe"
& $py tools/evidence_min.py --data-root data/a12 --step pattern-batch --batch-size 4 --batch-index 0 --pattern-pairs 150
& $py tools/evidence_min.py --data-root data/a12 --step pattern-batch --batch-size 4 --batch-index 1 --pattern-pairs 150
& $py tools/evidence_min.py --data-root data/a12 --step pattern-batch --batch-size 4 --batch-index 2 --pattern-pairs 150
& $py tools/evidence_min.py --data-root data/a12 --step pattern-batch --batch-size 4 --batch-index 3 --pattern-pairs 150
& $py tools/evidence_min.py --data-root data/a12 --step pattern-merge --pattern-pairs 150
foreach ($i in 0..30) { & $py tools/evidence_min.py --data-root data/a12 --step axes-batch --batch-size 1 --batch-index $i }
& $py tools/evidence_min.py --data-root data/a12 --step axes-merge
& $py tools/evidence_min.py --data-root data/a12 --step observe
& $py tools/evidence_min.py --data-root data/a12 --step fixtures
& $py tools/evidence_min.py --data-root data/a12 --step pixel-contract
& $py tools/evidence_min.py --data-root data/a12 --step scale
& $py tools/evidence_min.py --data-root data/a12 --step resource-profile --run-id probe_recovery
& $py tools/evidence_min.py --data-root data/a12 --step loader-probe
& $py tools/evidence_min.py --data-root data/a12 --step leakage --run-id probe_recovery
& $py tools/evidence_min.py --data-root data/a12 --step api-ui
& $py tools/evidence_min.py --data-root data/a12 --step health
& $py -m synlab.cli acceptance --profile SANDBOX_CORE --json
& $py tools/gen_status_matrix.py --data-root data/a12
```

## 8. 最终（收口轮：最小 release 冻结 + 泄漏修复 + 验收）

本节由收口轮实跑结果汇总；闭环细节见 `docs/a12/closed_loop.md`，数字全部取自
`data/a12/reports/*.json`、`data/a12_exports/closed_loop/closed_loop_report.json` 与
`data/a12_exports/closed_loop/store/releases/rel_852ab2a1e4c3_1790905541/manifest.json`。

### 8.1 命令与退出码

| 命令 | 退出码 | 结果 |
|---|---|---|
| `python tools\closed_loop.py --step audit` | 0 | DEGRADED（3 个 `visible_labels` QA_FAIL + 特征角色带 `fragment_id/mother_id`，均为真实问题） |
| `python tools\closed_loop.py --step release_freeze` | 0 | 冻结 `rel_852ab2a1e4c3_1790905541` / `SANDBOX_CORE`，165 资产，`scope_pending=[]` |
| `python tools\closed_loop.py --step export_training_package` | 0 | 13 文件 / 3 785 587 B |
| `python tools\closed_loop.py --step loader_probe` | 0 | `ok=true` / `status=PASS` |
| `python tools\closed_loop.py --step report` | 0 | 账本 `ok=true`，`degraded_steps={audit}` |
| `python tools\closed_loop.py --step all --resume` | 0（带 caveat） | 7 步全部有记录，`audit` 保持 DEGRADED |
| `python data\a12\reports\repair_degrade_role.py --store data/a12 --apply` | 0 | 20/20 退化资产改挂 `degrade_measurement`，字节一致 |
| `python tools\evidence_min.py --step leakage --data-root data/a12 --run-id run_2fad0ac4d3b67098` | 0 | `ok=false`（真实残余，见 8.3） |
| `python -m synlab.cli acceptance --profile SANDBOX_CORE --json` | **1** | 前=后：FAIL 5 / PASS 12 / PENDING 6 / NOT_RUN 6 / NA 7 |
| `python tools\gen_status_matrix.py --data-root data/a12` | 0 | `docs/a12/status_matrix.csv`（153 行：capability 92 / acceptance 36 / reuse 25） |

### 8.2 前后计数（最终轮）

| 快照 | `generated_at` | FAIL | PASS | PENDING | NOT_RUN | NA |
|---|---|---|---|---|---|---|
| 前 `acceptance_summary.before.json` | 1790905375.21 | 5 | 12 | 6 | 6 | 7 |
| 后 `acceptance_summary.json`（并留 `acceptance_summary.after.json`） | 1790905610.66 | 5 | 12 | 6 | 6 | 7 |

**状态迁移：0 项**（`summary_hash=sha256:3c7ecc0800902f467c443ff1cb426add5aec3bcfbcfd694fd91b93b7e339515c`）。
本轮没有把任何一项“改绿”：修的是**可读性缺陷**（gate 读错层级）与**角色错挂**，
A01 的实测明细变了但判定不变：

| 指标 | 前 | 后 |
|---|---|---|
| `A01.metrics.forbidden_fields_in_committed_features` 条数 | **76** | **16** |
| 其中 `axis_id`/`level`/`variant`（退化错挂） | 60 条（20 资产 × 3 键） | **0** |
| 其中 `fragment_id`/`mother_id`（pipeline 特征 meta） | 16 条（8 资产 × 2 键） | 16 条（未变） |
| `A01.status` | FAIL | **FAIL（口径未放宽）** |

> 上表是收口轮当时的快照。其中 `fragment_id`/`mother_id` 的 16 条（8 资产）已在 **§9** 修复：
> 现为 **0 条 / 0 资产**、`A01.status=PASS`（判定口径未改）。

### 8.3 泄漏修复与残余（A01 / leakage）

- **代码**：`synlab/roles.py` 新增 `ROLE_DEGRADE_MEASUREMENT="degrade_measurement"`；
  `synlab/degrade/api.py` 的 `COMMIT_ROLES["X"]` 改为
  `(degrade_measurement, synlab.measurement.v1)`。A01 判定口径未改。
- **存量**：`data/a12` 的 20 个错挂 `feature_bundle` 行用模块自身 `load_source`→`commit_source`
  往返重提交为正确角色（逐数组 hash 一致），然后删除错挂行与目录，墓碑与映射见
  `data/a12/reports/degrade_role_repair.json`。`feature_bundle` 32 → **12**，
  带因子标签的 0；`degrade_measurement` 0 → **20**；`health_check ok=true`（247 资产）。
- **负控**（`data/a12/reports/leakage_negative_control.json`）：

| 范围 | features | `truth_isolation` | `ok` |
|---|---|---|---|
| run `run_2fad0ac4d3b67098` | 4 | false | false |
| 全店 | 12 | false | false |
| 干净 run `run_23664ddb26eada4b` | 4 | **true** | **true** |

- **为什么仍 false（真实原因，未掩盖）**：残余 8 个 QA_PASS 特征资产
  （`run_2fad0ac4d3b67098` 4 个、`run_404bbe3c80f2c04e` 4 个）的 meta 带 `fragment_id`/`mother_id`
  且写进 `feature_fields`，提交方是 `synlab/pipeline.py::_commit_features` /
  `_observation_feature_block`。该文件**不在本轮写入范围**，且这些是真实 run 的 QA_PASS 资产
  （被 run 覆盖与闭包引用，meta 参与 `payload_hash`/`asset_id`），故不删不改，如实保留 FAIL
  并写明修法。闭环 store 自己的审计也抓到同一缺陷（`legal_inputs` 门因此 PENDING）。

> **本节该结论已被 §9 取代**：这 8 个资产已在 §9 用“重提交字节一致孪生 + 退役旧行 + 改指派生边”
> 全部修掉 —— `forbidden_fields_in_committed_features` 16 → **0**、`A01` FAIL → **PASS**、
> `truth_isolation` false → **true**。代码侧残余（`synlab/pipeline.py:893`）见 §9.6 第 1 条。

### 8.4 release 与导出（最小闭环）

- **已冻结**：`rel_852ab2a1e4c3_1790905541`，`profile=SANDBOX_CORE`，`scope=SYNTHETIC`，
  165 个 QA_PASS 资产，`manifest_hash=sha256:c86c14af36e243fef2b2ba5e5a909d73555ddcfcb79aa9899cd3d2f9a3b01ddd`，
  引用闭包 `ok=true`（165/165 文件逐个哈希校验）。
- **必需门（全部 PASS，全部来自 store 证据，`gate_overrides=[]`）**：`fixture_contract`、
  `coordinate_contract`、`source_map`、`readonly_commit`、`fracture_operator_runs`、
  `observation_operator_runs`。**未过必需门：无**（`scope_pending=[]`）。
- **本轮修掉的两个“门读出错误”**：(1) `synlab/qc/gates.py` 用 `acceptance["A02"]` 读顶层键，
  而验收报告嵌在 `items` 下，导致 `coordinate_contract` 恒 PENDING；新增 `acceptance_item()`
  兼容两种形状后读到真实条目（A02 PASS）。(2) `tools/closed_loop.py` 里硬编码把 6 个必需门
  强判 PASS 的 `GATE_DOWNGRADES` 表已清空，并加了“任何声明都不得把门抬成 PASS”的拒绝逻辑；
  freeze 被拒时落盘 `release_freeze_blocked.json`（含门明细与 `scope_pending`），
  并说明 SANDBOX_CORE 已是 `PROFILE_GATES` 最低档、不存在可降级 profile。
- **导出包**：`training_package` 13 文件 / 3 785 587 B（deploy 8 / 3 766 777 B，
  `contains_truth=false`、`deploy_truth_files=[]`；research 5 / 18 810 B，`contains_truth=true`）；
  `geometry_points=6049`、`geometry_bytes=145176`、`obs_views=12`、`obs_bytes=2359296`、
  `tokens=576`、`relations=3`（全 R2）、`queries=6`、`label_layers=3`（27/27/12 行）。
  另出 `release_index` 平铺导出（165 资产）。
- **loader**：`data/a12/reports/loader_probe.json` `ok=true`/`status=PASS`；真实分母
  fragments 6（有观测 3 / 无观测 3）、points_valid 6049、tokens 576；
  batch `n_queries=3 / positives=3 / negatives=0`，`negative_audit.ok=true`（负例为 0 的原因是
  exposure 直方图 `none=3`、其余桶全 0：本环 pool 只有 R2，合法负例确实不存在）。
- **本轮修掉的一个 loader 完整性漏洞**（`synlab/qc/loader_probe.py`）：
  `probe_training_package` 的 `ok` 只看 `negative_audit.ok`，**忽略 `package.verify_files`**，
  于是 manifest 哈希对不上的包也报 `ok=true`（集成测试
  `test_loader_refuses_a_tampered_package` 因此失败）。现在
  `ok = files_ok ∧ negative_audit.ok`，完整性问题落
  `error.code=ASSET_HASH_MISMATCH` + `blocking_attempt=package.verify_files`；
  真实包复跑结果不变（`files_ok=true`、`files_checked=13`、`ok=true/PASS`）。
  集成测试随之从 20 通过 / 2 失败变为 **21 通过 / 1 失败**，剩余 1 项是
  `synlab/storage/export.py` 的 zarr 路径缺陷（写入 `deploy/geometry/zarr`、登记扫描
  `deploy/zarr`，越权未改，见 `docs/a12/closed_loop.md` 第 8 节第 8 条）。

### 8.5 诚实性说明（最终轮）

1. **证据哈希的时点性**：release manifest 的 `evidence_reports` 记录“冻结那一刻读到的文件 +
   哈希”。冻结后又补跑了 audit（修 `_run_contract_item`）与 loader_probe，因此 12 个证据文件中
   4 个当前哈希与记录不同（`acceptance_summary`、`audit_run_852ab2a1e4c3b70f`、`loader_probe`、
   `recovery_probe`）；四者的结论未变（A02 PASS / loader ok=true / recovery COMMITTED）。
   冻结后重新核验：manifest 自校验通过、闭包 165/165 `ok=true`、6 个必需门仍全 PASS。
2. **`export_manifest.json` 的 `separation.features_carry_answer_fields` 是硬编码常量**
   （`synlab/storage/export.py` 第 696 行），不是测量值；不拿它当泄漏证据（A01 实测为 FAIL）。
   包内真正的边界证据是 deployment 视图按文件名实测无 truth 文件 + 与 research 物理分目录。
3. **store 里的残留文件**：闭环 store 报告目录的 `acceptance_summary.staged.json` 是
   `_run_contract_item` 旧实现把 markdown 写成 `.json` 的遗留物，保留未删（它本身就是该 bug 的证据）。
4. **`audit` DEGRADED 未消除**：3 个 `visible_labels` 资产 QA_FAIL 是真实缺口（交付前景 mask 为空），
   不是流程噪声；它们被排除出冻结范围并逐个记录。
5. **越权项**：`synlab/pipeline.py`（A01 残余）、`synlab/storage/export.py`（常量字段 +
   zarr 路径登记缺陷）不在写入范围，均只报告不改动；`tools/evidence_min.py` 的 `leakage` 步骤
   同样是 run 范围口径，未修改，全店/干净-run/残余原因写进同一份报告。
6. **测试**（按目录分开跑，避免两个同名 `conftest.py` 冲突）：
   `tests/a12/operators` 148 项通过（exit 0）、`tests/a12/api/test_roles_and_isolation.py`
   21 项通过（exit 0）、`tests/a12/integration/test_closed_loop.py` 修复前 20/2、
   修 loader 完整性后 21 通过 / 1 失败（唯一失败项为 export.py 的 zarr 路径缺陷，见 8.4）。

## 9. feature 泄漏修复（A01 存量收口：76 → 16 → 0）

本节收口 §8.3 留下的**最后 8 个残余资产**。8 个历史 `feature_bundle` 全部处理完毕：
用**原特征数组重提交为字节一致的孪生资产**（meta 去掉身份字段），再退役旧行（SQLite 行 +
`assets/<id>` 目录，写完整墓碑），最后把它在**派生边（`ancestry`）**上的引用改指到孪生资产。
A01 的 `forbidden_fields_in_committed_features` 由 **16 条 → 0 条**。
**A01 判定口径、`FORBIDDEN_FEATURE_FIELDS`、`qc/leakage.py`、`qc/audit.py` 与各 release 门一行未改。**

### 9.1 命令与退出码

| 命令 | 退出码 | 结果 |
|---|---|---|
| `python tools\repair_feature_leak.py --store data/a12 --plan` | 0 | 复现：8 个资产 / 16 条 forbidden（每资产 `fragment_id`+`mother_id`） |
| `python tools\repair_feature_leak.py --store data/a12 --apply` | 0 | `repaired=8` / `refused=0`，8/8 `faithful=true`，派生边 8/8 改指成功 |
| `python tools\repair_feature_leak.py --store data/a12 --verify` | 0 | 全店 `forbidden_entries_total=0`；`truth_isolation=true` |
| `python tools\repair_feature_leak.py --store data/a12 --freeze --apply` | 0 | 两个 run 的 release **均未冻结**（门未过，见 9.5） |
| `python tools\evidence_min.py --step leakage --data-root data/a12 --run-id run_2fad0ac4d3b67098` | 0 | `ok=true` / `status=PASS`（原为 `ok=false`） |
| `python data\a12\reports\augment_leakage_report.py --store data/a12` | 0 | 追加 `runs_scoped` 等范围与修复摘要 |
| `python -m synlab.cli acceptance --profile SANDBOX_CORE --json` | **1** | FAIL 5→**4**、PASS 12→**13**；**A01 FAIL→PASS**；退出码 1 由 A05/A06/A09/A24 造成（与本轮无关） |
| `python tools\gen_status_matrix.py --data-root data/a12` | 0 | `docs/a12/status_matrix.csv` 中 A01 行 = `PASS` |

### 9.2 A01 前后明细（同一口径，三次快照）

| 快照 | forbidden 条目 | 其中 `axis_id/level/variant` | 其中 `fragment_id/mother_id` | 相关资产数 | A01 |
|---|---|---|---|---|---|
| 基线 `acceptance_summary.before.json` | **76** | 60（20 个错挂退化资产 × 3） | 32→16 | **28**（20+8） | FAIL |
| 收口前 `acceptance_summary.before_feature_leak_repair.json` | **16** | 0 | 16（8 资产 × 2） | **8** | FAIL |
| 本轮后 `acceptance_summary.json` | **0** | 0 | **0** | **0** | **PASS** |

`leakage_detector=true`、`unknown_field_rejected=true` 三项均未变；`summary_hash=sha256:d8fb0f7455abd8a88de52604b1c55bad083646129b429089a7fe5a4a7de046a1`。

### 9.3 8 个资产的处理结果与 faithful 证据

规则：`asset_id = interpret_hash(role, schema, unit, frame, payload_hash)`，meta 参与 `payload_hash`，
因此**不就地改 meta / 不就地改 role**；做法是重提交 + 退役 + 墓碑 + 映射
（`data/a12/reports/feature_leak_repair.json`，风格与 `repair_degrade_role.py` 一致）。

| 退役资产 | run | lineage | 孪生资产（新 id） | 数组数 | 逐数组 hash 全等 | 改指的派生边 |
|---|---|---|---|---|---|---|
| `asset_2ddeda824c6b7dec8a95` | `run_404bbe3c80f2c04e` | LIN0000_V01_M01_PAT01 | `asset_fded2bb0ae17aa1f409f` | 17 | **true** | `asset_4775c2eea78e597a1b16`（provenance） |
| `asset_846bd1b7cf1e44d139d0` | `run_404bbe3c80f2c04e` | LIN0001_V02_M01_PAT01 | `asset_b9a422864590b8115042` | 17 | **true** | `asset_272a76eaee10000431d8` |
| `asset_0bcbf10e87b9b54fbbc2` | `run_404bbe3c80f2c04e` | LIN0002_V13_M01_PAT01 | `asset_8c29450b0260f5726bd3` | 17 | **true** | `asset_c572dfecc0fdaeeb764b` |
| `asset_e612e193c8fa59f47aa5` | `run_404bbe3c80f2c04e` | LIN0003_V01_M04_PAT01 | `asset_cadb60574457189e9b22` | 17 | **true** | `asset_b52990143d30b5a65140` |
| `asset_2e59947b6438587153b5` | `run_2fad0ac4d3b67098` | LIN0000_V01_M01_PAT01 | `asset_219282d10ed84ad8cc9a` | 17 | **true** | `asset_b768b19b90557e4baa6c` |
| `asset_b31e078177be3f23c81b` | `run_2fad0ac4d3b67098` | LIN0001_V02_M01_PAT01 | `asset_fb073cc932fc7661d49a` | 17 | **true** | `asset_fe93f6a83a4b83beec5c` |
| `asset_5bb19a7894def812c16e` | `run_2fad0ac4d3b67098` | LIN0002_V13_M01_PAT01 | `asset_1214795958e2a814c8b6` | 17 | **true** | `asset_f6b04f527062b33badf7` |
| `asset_b438e92147420409adae` | `run_2fad0ac4d3b67098` | LIN0003_V01_M04_PAT01 | `asset_433cc1381e62aa47d28a` | 17 | **true** | `asset_22a81af62755ab7bcbb1` |

- **faithful 的判定方式**：`store.load_arrays` 读出的**原始数组**逐个算
  `synlab.canonical.array_hash`，新资产再读一遍逐数组比对 —— `array_keys_equal=true`、
  `array_hashes_equal=true`（8/8）、keys/shape/dtype 全等，`differences=[]`；
  每个资产 17 个数组（含 `global_rgb`〔4,192,256,3〕uint8、`pixel_valid`、`point_cloud__xyz`、
  `curvature_field__*`、`quality__*`、`view_tokens` 等）。
- **meta 处置**：剔除 `fragment_id`/`mother_id`（在 `FORBIDDEN_FEATURE_FIELDS` 内）与
  `component_id`/`observation_id`（同一身份链，非表内但同属身份）；重算
  `meta["feature_fields"]`（不再声明身份键），并记 `dropped_forbidden_fields` +
  `leak_repair`（含 `source_asset_id`）；保留有特征含义的
  `n_views`/`image_size`/`tokens_total`/`scale_valid`（在 `a12.obs.v1` 标量契约内）。
- **为什么必须改指派生边**：退役 id 出现在同 run 的 provenance 资产 `ancestry`
  （`[feature, label]`）里，共 8 条；不改指则 `ReleaseManager.verify_closure` 会报
  `missing asset`。`ancestry` 不参与 `interpret_hash`/`blob_hash`，改指不改变任何资产的 id
  与文件哈希；每条改动的前后值与原因都逐条写在报告里。冻结清单内的引用会被**拒绝改写**
  （本次 0 条命中）。
- **store 复核**：`health_check ok=true`（247 资产 / 250 文件 / 0 问题）；
  退役行与目录均已删除，旧 id 只保留在 events 追加日志与本次报告/墓碑中（有意留痕）。

### 9.4 负控复验（`data/a12/reports/leakage_negative_control.json`）

| 范围 | features | `truth_isolation` | `ok` |
|---|---|---|---|
| run `run_2fad0ac4d3b67098` | 4 | **true** | **true** |
| run `run_404bbe3c80f2c04e` | 4 | **true** | **true** |
| 全店（无 run 过滤） | 12 | **true** | **true** |
| 干净对照 `run_23664ddb26eada4b` | 4 | **true** | **true** |

`residual.offending_assets` 现为 `[]`（报告里仍保留 `repair_mapping` 与 `still_open` 字段）。
`metadata_permutation`、`row_permutation_invariance` 仍为 `true`。

### 9.5 release：**未重新冻结成功**（被必需门拦下，未放宽任何门）

- **`data/a12` 里原本没有任何已冻结 release**：`releases` 表 0 行、`data/a12/releases/` 为空。
  因此**不存在“闭包里的 8 个引用失效”**：8 个旧 id 从未被任何 release manifest 引用
  （全仓字节级扫描：只有 `_scratch` 笔记、旧 store 备份与本次墓碑/报告提到它们）。
- 仍按要求**真实尝试**了冻结（新 id，从不覆盖同名 release），两次尝试都**被拒**并落盘
  `data/a12/reports/release_freeze_after_feature_leak_repair.json`
  （门全部来自 `qc.gates.evaluate_gates` 的 store 证据，`gate_overrides` 为空）：
  - 全范围（run 的 24 个 QA_PASS 资产）：闭包**不通过**，引用遍历到
    `asset_6351703c8814ff83c390`（`physical_component`，`QA_PENDING`）与其
    `ancestry` 里的 `LIN0000_V01_M01_PAT01:LIN0000_V01_M01_PAT01_E01:v1`（**是 fragment id、
    不是 asset id**）；
  - 缩减范围（自身闭包可验证的 16 个资产，排除 8 个 provenance/feature）：闭包可过，
    但仍被 `STOP_QA` 拦下 —— 必需门 `fracture_operator_runs`、`observation_operator_runs`
    为 PENDING（本 store 的 truth/observation 资产没有 `meta["run_id"]`，而这两个门按 run 统计
    QA_PASS 资产）。
  - 结论：**两个 run 的 `frozen=false`，本次没有产生任何新 manifest**（不制造“看起来成功”的发行版）。
- **旧 release 只读未动**：`data/a12_exports/closed_loop/store/releases/` 下 5 个 manifest
  在修复前后**逐文件哈希完全相同**（`external_releases_untouched=true`）。

### 9.6 仍未解决项 / 诚实性（本节）

1. **代码侧残余仍在**（未改，越权）：`synlab/pipeline.py:893`
   `meta["fragment_id"] = encoded.get("fragment_id") if encoded else None` 位于剔除逻辑
   （887–889 行）**之后**，所以任何走 `_commit_features` 的**新**生成仍会把 `fragment_id`
   写进特征 meta。实测证据（不是推断）：
   `pytest tests/a12/integration/test_l0_loop.py -q` →
   `test_features_and_labels_are_separate_and_clean` FAIL：
   `AssertionError: features carry forbidden fields: ['fragment_id']`（退出码 1，输出
   `data/a12_exports/_scratch/l0_gap_probe.txt`）；闭环 store 的 21 个特征资产也全带
   `fragment_id/mother_id` 且已进 5 个已冻结 manifest。最小修法是**删掉第 893 行**
   （`relations/gallery.py::attach_features` 与 `storage/export.py` 都有 provenance/obs 回退路径），
   但该改动会牵动 pool 装配与训练包导出两条正在并行开发的路径，故**本任务只报告、不代改**。
2. **闭环 store 的 5 个已冻结 release 仍含带 `fragment_id/mother_id` 的特征资产**
   （`rel_8049cf187288_*`/`rel_fda083aa68a8_*`/`rel_b06f9f7e9508_*`/`rel_852ab2a1e4c3_*`×2，
   12–21 个/份）。按“旧 release 只读”规则未动；要修必须在该 store **重新生成 + 重新冻结新版本**，
   不在本任务范围。
3. **陈旧派生台账**：`data/a12/reports/coverage_rows.json`（4 个旧 id）、
   `coverage.parquet`（2 个旧 id）仍提到退役 id；它们由 `synlab/pipeline.py::_write_coverage`
   在**下一次生成**时重写，本次不手改（`coverage.json` 本身不含 asset id，不受影响）。
4. **门状态没有因本轮修复而变化**：`legal_inputs` 等门仍取决于 run 标注与闭环 store 的缺陷；
   本轮只让 A01 从 FAIL 变 PASS（这一项本来就是被这 8 个资产卡住的）。
5. **pool 装配没有因此变差（实测，不是推断）**：`relations.gallery.attach_features` 的映射阶段
   在修前把 4 个 fragment 映射到 4 个**退役**资产（走 `meta["fragment_id"]`），修后同样映射到
   4 个**孪生**资产（走 provenance `ancestry` 回退路径）—— 映射未断。payload 阶段两边都是 0：
   `_feature_payload` 要求 payload 里有 `points` 键，而本 store 的特征数组是
   `point_cloud__xyz`/`global_rgb`/`view_tokens`，**未修过的干净 run 特征资产同样返回空 payload**
   （实测 `payload_empty=True`），所以 `attached=0` 是既有缺陷、与本轮修复无关。
   证据：`data/a12_exports/_scratch/probe_attach_stages.txt`（映射/载荷两阶段分别测量）。

