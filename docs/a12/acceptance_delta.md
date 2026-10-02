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
