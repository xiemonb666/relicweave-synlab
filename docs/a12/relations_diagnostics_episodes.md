# A12 关系库 / 诊断统计 / 主动观察 episode：实现、实测与缺口

本文件是 `synlab/relations/**`、`synlab/diagnostics/**`、`synlab/episodes/**` 的
**实现说明 + 实测证据 + 缺口清单**。权威规格是计划第 16/17/19 节与 30.10/30.11/30.13/30.14/30.15，
接口名与类型以 [`docs/a12/interfaces.md`](interfaces.md)、`synlab/schemas/{runtime,spec}.py`
为准；本文件不重定义任何上游类型。

> 状态：三个模块**已实现并在本地 fixture 上跑通**（89 个测试，退出码 0）。
> 真实证据库 `data/a12` 目前**没有** `clean_truth` / `label_bundle` 资产（`synlab.truth`、
> `synlab.observe` 仍在并行开发），因此真实链路上的 gallery 构建、诊断与 episode 都是
> `GALLERY_SIZE_PENDING` / `INPUT_UNAVAILABLE`（**NOT_RUN**，不是 0 分）。

---

## 0. 交付文件与入口

| 文件 | 内容 |
|---|---|
| `synlab/relations/gallery.py` | `RelationsIndex`（稀疏关系）、`FragmentRecord`、`RelationPool`、存储读取与 `attach_features` |
| `synlab/relations/sampler.py` | `sample_training_batch`、`mine_hard_negatives`、负例合法性判定 |
| `synlab/relations/api.py` | `build_pool`、`build_pool_from_config`、`commit_pool` / `commit_roster`、`load_pool`、portable JSON 读写 |
| `synlab/diagnostics/metrics.py` | Hit@K / CovRecall@K / any@M / PoolCov@M / ConditionalCov / EffectiveHit / EffectiveCov / 拒识 / 两个风险事件 / 冻结分母聚合 |
| `synlab/diagnostics/stats.py` | 母体簇 bootstrap、Holm、Clopper–Pearson、功效 `power_approx`、`n90`、零事件表 |
| `synlab/diagnostics/fixtures.py` | `run_fixtures()`：手算 fixture（metric_fixture / stat_fixture 的来源） |
| `synlab/diagnostics/runner.py` | 固定 gallery/roster 的 cell 评测、scorer、na/失败记录、五个报告产物 |
| `synlab/diagnostics/api.py` | `run_diagnosis(spec, store)`、`pool_metrics`、`paired_bootstrap`、`risk_upper_bound` |
| `synlab/episodes/env.py` | `EpisodeEnv`（reset / available_actions / step / stop）、动作目录（由 camera profile 声明） |
| `synlab/episodes/baselines.py` | 5 个合法规则基线 + `ORACLE_ACTION` 上界 |
| `synlab/episodes/api.py` | `run_episode_config(store, config_path)` |
| 测试 | `tests/a12/relations/*`、`tests/a12/diagnostics/*`、`tests/a12/episodes/*` |

能力探测（`synlab/api/capabilities.py`）实测：`relations` / `diagnostics` / `episodes` 三个
key 均 `status=OK`，门面函数 `build_pool`、`sample_training_batch`、`run_diagnosis`、
`EpisodeEnv`、`available_actions`、`step` 全部解析成功。

### 0.1 与已存在模块的接线（实测可用的路径）

| 消费方 | 接口 | 说明 |
|---|---|---|
| `synlab.training.api.evaluate` | 从 `synlab.diagnostics.metrics` 导入 `hit_at_k` / `cov_recall_at_k` / `any_at_m` / `pool_cov_at_m` / `conditional_cov` / `accept_set` / `effective_hit_at_k` / `effective_cov_at_k` / `risk_events` | 函数名、位置参数顺序与返回语义已按该调用点实现；无邻片时返回 `None`（`np.asarray([...,None], float)` → `nan`，其 `_agg` 按 NA 跳过） |
| `synlab.training.batch.build_training_batch` | `rows=` = `sample_training_batch(...)["rows"]` | 行键 `query`/`positives`/`negatives`/`excluded`/`r1_fallback`/`sample_key` 与 `training/batch.py` 的读取一致（见 §5 G1 的阻塞项） |
| `synlab.training.model` | `ObservationVectorBaseline`（浅基线，episode 与诊断的默认 scorer）、`build_model`（checkpoint scorer） | 只读取合法观测通道 |
| `synlab.pipeline._commit_labels` | `label_bundle` 资产：`meta["relations_json"]` 为全事件关系列表 | `relations` 把它当作首选关系来源（另兼容 `clean_truth` 的 `meta["relations"]` 与 `rel_a/rel_b/rel_kind` 数组形式） |
| `configs/a12/diagnose_sandbox.yaml` | `candidate_pool_ref: data/a12/pools/sandbox_dev.json`、`query_roster_ref: data/a12/pools/sandbox_dev_queries.json` | `build_pool_from_config` 正是写这两个文件（pool_id 来自 `pool_dev.yaml` 的 `sandbox_dev`） |
| `tools/run_evidence.py` | `build_pool_from_config` / `run_fixtures` / `run_diagnosis` / `run_episode_config` | 返回值可直接写成 `pool_audit.json`、`metric_fixture.json`、`stat_fixture.json`、`diagnostic_report.json`、`episode_trace.json` |

`pool_audit.json` 顶层含 `ok` 与 `distractor_isolated`（A15/A31 直接读取），并含
`queries`/`candidates`/`r2_edges`/`distractor_isolated` 等键与一份 `metrics` 镜像（A15 读
`report["metrics"]`）。`run_fixtures()` 返回 `{"metrics": {...}, "stats": {...}}`，其中
`metrics.ok`、`hand_computed_hit/poolcov/cov`、`effective_zero_on_failure`、`absent_risk_defined`
（A18/A30）与 `stats.clopper_pearson_ok`、`stats.bootstrap_unit == "shape_lineage"`（A31）
已按验收代码的键名提供。

---

## 1. `synlab/relations`

### 1.1 稀疏关系，不物化 N²

* 只保存 **非 R0** 显式边（`R2/R1/TINY_CONTACT/UNKNOWN`）；`R0` 由冻结构造规则**隐式推导**：
  不同断裂事件（互斥）或同事件但无共享界面 ⇒ 已确认非邻接；真值不完整的片（`qa_status != QA_PASS`
  或 `association_kind == UNKNOWN_MAPPING`）的未标注对 ⇒ `UNKNOWN`（**不当 R0**）。
* 报告里 `n2_materialised=False`、`relation_storage="sparse_non_r0_edges_only"`，并给出
  `explicit_edges` 与 `r0_implicit_pairs` 两个计数以便审计。
* 10 万片场景下只保存 R2/R1/灰区稀疏边与按需索引；`build_pool` 的便携 JSON 在
  `> 20000` 片时返回 `SKIPPED_SIZE`（不写巨型文件，store 资产仍是权威）。

### 1.2 gallery 固定项（`build_pool`）

* 固定物理母体 + 互斥事件集合；**query 自身永不出现在自己的候选里**（`candidate_ids` 过滤）。
* 保存**全 R2 集合 N_G(q)**（`historical_neighbours`，含被移出 line-up 的邻片计数
  `out_of_gallery_neighbours`），不因可见性/池外缩小分母。
* 四个 scope：`FULL`、`MATE_REMOVED`（删光 roster query 的全部邻片，N_G(q)=∅）、
  `NESTED`（冻结顺序的嵌套前缀，超出可用片数记 `GALLERY_SIZE_PENDING`）、`DISTRACTOR_ONLY`。
* `distractor_isolated` = 没有任何 lineage 同时出现在 distractor 库与训练谱系中；无 distractor
  谱系时**为真但标注 `isolation_basis` 为"vacuous"**（不冒充隔离证据）。
* 每库有独立 `pool_id` / `gallery_version` / `hash`（`hash_json`，去 `hash` 字段自洽）。
* 输出版本号与产物：`relation_pool` 资产（数组 + meta；`load_pool` 往返保 N_G 与 R1/TINY/UNKNOWN）、
  `query_roster` 资产、`<store>/pools/<pool_id>.json`、`<store>/pools/<pool_id>_queries.json`。

### 1.3 训练采样（§16.2）

* lineage 均衡抽 query（每轮每 lineage 一个，最少曝光优先）；正例 1–2 个取自**完整 R2**，
  `state["r2_cursor"]` 跨 batch 轮转，**每个 R2 边最终都会被覆盖**（实测 12 个 batch 覆盖全部邻片）。
* 负例起步 `4×R1 + 4×R0`（按 `negative_mix` 分流）；R1 不足时**显式 fallback 到 R0** 并写
  `r1_fallback=True`（绝不伪造 R1）。R0 配额在**有合法观测**时按 同型异器 / 纹样近似 /
  几何近似 / 普通异器 分配，缺观测时记入 `r0_categories_unavailable`。
* 负例集合删除**全部历史 R2**（不只是本 batch 抽中的正例）、`TINY_CONTACT`、`UNKNOWN`/灰区、
  未确认关系、query 自身；每个被排除候选的 `excluded` 列表与原因直方图随行返回。
* 曝光分开统计：R2 边、母体、lineage、困难组、R0 类别、R1 fallback 次数；
  严重 Q5 不可辨 query 记入 `q5_unresolvable_queries` 并**保留**（不从评测移走）。
* 返回 `query/candidate` **索引**（`index`）、观测引用（`observations`）、标签（`labels`）、
  来源（`provenance`）；`hard_type`/`mate_present` 只出现在标签侧，绝不进特征。

### 1.4 困难负例挖掘（§16.3）

* 只用**合法可观测特征**检索（出现禁字段直接 `LEAKAGE_DETECTED`）：`view_tokens`（若有）、
  尺度归一后的点/法向矩、OBS_EST 质量；精确 TopM 内积（优先复用已装 FAISS `IndexFlatIP`，
  不可用时 numpy 精确回退，两者排序一致）。
* 标签只在检索**之后**用于排除历史 R2 / 灰区 / `UNKNOWN` / `TINY_CONTACT` 与确认 R1/R0：
  返回项带 `relation`、`hard_group`、`usable_as_negative`、`exclusion_reason`。
* 记录 encoder hash、缓存年龄与陈旧标记（`cache.stale`），cache 来源固定标注 `train_only`；
  候选选择是确定性 TopM（不随机抽候选），保留随机负例由采样器负责。

---

## 2. `synlab/diagnostics`

### 2.1 指标与分母（§19.1、§30.14）

* `Hit@K/CovRecall@K`：无库内邻片 ⇒ **NA**（`None`，不写 0），仍进风险分母。
* `any@M/PoolCov@M`：分母是全库历史邻片；无邻片同样 NA。
* `ConditionalCov`：分母是池内正例数，零池正例 ⇒ NA 且计 `pool_miss`。
* 有邻片但**超时/重建失败/无输入**：`EffectiveHit=EffectiveCov=0` 且**留在冻结主分母**；
  原始排名未产生时 Hit/Cov = NA（`rank_produced=False`，失败原因单列）。
* **拒识**：原排名、接受率与拒识后的 Effective 一起报；有邻片而拒识的有效找回 = 0。
* 重复候选身份合并（`duplicates_removed`）、query 自身永不作为候选（`self_candidates_removed`）；
  无法编码的候选仍在逻辑 gallery 与 N_G 中（`unencodable_candidates`），只不进向量索引。
* 两个冻结风险事件：`absent_false_accept=1[|N_G|=0 ∧ |A|>0]`；
  `present_wrong_accept=1[|N_G|>0 ∧ A\N_G≠∅]`（命中真邻片同时误荐 R1/R0 也算）。

### 2.2 统计（§19.4、§30.15）

* `paired_bootstrap_ci(paired, unit="shape_lineage", replicates=10000, confidence=0.95)`：
  **按 lineage 簇整体重采样**，簇内重复（片/view/质量档/seed）不被当成独立 n；单簇直接拒绝出区间。
* `holm_correction`（step-down，单调化）、`macro_mean_by_stratum`（宏平均 + 最差层）。
* `clopper_pearson_upper(e, n, alpha)`：`e=0` 用闭式 `1-α^(1/n)`；`e>0` 用 `scipy.stats.beta.ppf`；
  `e=n` 上界 1。零事件样本量表 10%/5%/1% → 29/59/299。
* `power_approx(sigma, delta, alpha, power)`、`achieved_power`、`power_report`（含敏感性）；
  `n90(points, reference=...)`：只用实测点，**不插值不外推**，未达阈值记 `NOT_REACHED`。

### 2.3 runner 与报告（§19.6）

* cell = `clean` 基线 + 每个 (axis, level)；每 cell **真实编码整个固定 gallery** 并给出
  per-query 原始排名、初检池、接受集、风险、成本。
* 扰动缺失/未实现 ⇒ cell `status="NA"`（`na_reason` 记原因），**该 cell 的所有指标为 NA**，
  曲线只在 `missing` 里出现该档（`interpolated=False`、`measured_points_only=True`）；
  绝不画拟合曲线或随机曲线。
* scorer：`CheckpointScorer`（`build_model` + checkpoint，维度由 pool 特征推导，记录 index identity）
  / `ClassicalScorer`（浅基线，报告标注 `DEPLOYMENT_MODEL_NOT_PROVIDED`）
  / `CallableScorer`（注入，用于测试与后续学习型策略）。
* 决策阶段前递归校验禁字段（`assert_legal_payloads`），命中即 `LEAKAGE_DETECTED`。
* 产物：`per_query_metrics.parquet`（一行一个 roster query × cell）、`diagnostic_summary.parquet`
  （一行一个 cell）、`failure_counts.json`、`run_spec.json`（protocol/pool/roster/scorer hash 与
  统计结果）、`report.md`（表格 + 仅实测点曲线 + 失败/缺失清单）；目录
  `<store>/reports/diagnosis_<protocol_id>/`，并另存 `diagnostic_report` 资产。
* `confirmation.open=false` 而 `evaluation_split=confirm` ⇒ `EXPERIMENT_PROTOCOL_VIOLATION`
  （不把确认集当确认）；`open=true` 时记录 `opened_at` 与 `used_as_confirmation=true`，
  提示"一次启封不可擦除重来"。

---

## 3. `synlab/episodes`

* `EpisodeEnv(store, pool, cameras=None)`：`reset(episode_id)` 只揭示初始观察
  （`revealed_views` = 初始 view id），`state.meta["no_ground_truth"]=True`；策略可见的是已揭示
  观察与 `state.available_actions`。**状态里没有 reward / GT / success 字段**（reward 只在环境侧 trace）。
* 动作目录**只由 camera profile 声明**：U 移动取自 `u_travel_mm`/`u_step_mm` 网格（含 `action_cost_seconds`），
  LOCAL 档给 `LOCAL_FRACTURE_FRAME`，灯光/偏振/重新装夹需要 profile `declared_actions`，
  转台需要 `turntable`。未声明的动作（默认 rig 的 `TOGGLE_LIGHT` 等）与越界 U 位置一律
  `TARGET_INFEASIBLE`，任意"相机瞬移"不是合法动作。
* `step(action)`：**动作后重检整个固定 gallery**，得到新的 TopM；新进入/离开的候选记入
  `candidates_entered/candidates_left`，只重排原池时标 `pool_rerank_only=True`（**不算候选恢复能力**）；
  未选动作的图像不进 state（实测：只多出被执行动作的那一个 view id）。
* 成本分开记：拍摄秒（声明值）、人工秒、推理秒（实测编码耗时）、帧数、动作数，累计到
  `cumulative_cost`；预算耗尽写 `BUDGET_ACTIONS`/`BUDGET_TIME`，`stop()` 写 `STOP`，
  停后任何动作都被拒（STOP 封闭）。
* 规则基线：`uniform_capture`、`coverage_first`、`single_step_quality`、`greedy_gain_cost`
  （无已训收益预测器时显式标 `UNLEARNED_GAIN_PROXY`，用声明的单步质量/成本代理）、`stop_only`。
  按 GT Cov 增益挑动作只在 `oracle_action()`/`run_oracle()` 中，标 `ORACLE_ACTION`、
  `legal_baseline=False`，且 `assert_baseline_legal("ORACLE_ACTION")` 抛错 —— 永不出现在合法列表。
* 离线奖励（环境侧）：`全库 CovRecall 增益 − λ_time×新增秒 − λ_risk×新增误荐事件`；
  轨迹保留错→对/对→错、不必要动作、净召回增益、误荐风险、额外时间与全部 STOP/失败轨迹。
* `run_episode_config(store, config_path)` 输出 `{ok, status, steps, costs, stop_reasons, metrics,
  policy_metrics, runs, oracle, pool, config}`，并提交 `episode_trace` 资产。

---

## 4. 实测（真实运行结果）

### 4.1 命令与退出码

| 命令（仓库根为工作目录） | 实测结果 |
|---|---|
| `& .venv\Scripts\python.exe -m pytest tests/a12/relations tests/a12/diagnostics tests/a12/episodes -q` | **exit 0**；89 passed；22.0 s |
| `& .venv\Scripts\python.exe -m pytest tests/a12/foundation -q` | **exit 0**；18 passed（回归对照） |
| `& .venv\Scripts\python.exe -m pytest tests/a12/api/test_capabilities_and_specs.py tests/a12/api/test_jobs_and_budgets.py tests/a12/api/test_roles_and_isolation.py -q` | **exit 0**；35 passed（capability 探测因三个模块落地而由缺失转为可用，测试仍通过） |
| `& .venv\Scripts\python.exe -m pytest tests/a12/api/test_assets_and_paths.py tests/a12/api/test_events_sse.py -q` | **exit 1**；3 failed，**与本任务无关的既存失败**：`synlab/api/integrity.py::resolve_file` 抛 `ApiProblem` 而测试期望 `SynLabError`（2 例）、`test_heartbeat_is_a_comment_not_a_fake_progress_event`（1 例）。本任务未修改 `synlab/api/**` |
| `& .venv\Scripts\python.exe -m synlab.cli build-pool --release sandbox --config configs/a12/pool_dev.yaml --json` | **exit 1**；`ok=false`、`status=GALLERY_SIZE_PENDING`、`queries=0`、`candidates=0`、`r2_edges=0`、`n2_materialised=false`（空库无真值资产，如实拒绝） |
| `& .venv\Scripts\python.exe -m synlab.cli diagnose --config configs/a12/diagnose_sandbox.yaml` | **exit 2 (BLOCKED)**；`INPUT_UNAVAILABLE`（`data/a12/pools/sandbox_dev.json` 不存在：还不是 pool 资产也不是便携产物） |
| `& .venv\Scripts\python.exe -m synlab.cli episode --config configs/a12/pool_dev.yaml` | **exit 2 (BLOCKED)**；`INPUT_UNAVAILABLE`（无冻结池：需先跑生成得到 label_bundle/clean_truth） |
| `python -c "from synlab.diagnostics.fixtures import run_fixtures; ..."` | `ok=True`，metrics **62/62** 检查通过（12 个手算用例），stats **28/28** 检查通过（5 个统计块），`run_fixtures()` 自身 1.61 s |

### 4.2 fixture 数值（手算对照）

| 项 | 实测值 | 规格预期 |
|---|---|---|
| 手算用例 q 真邻 {B,C}、池仅 B、TopK 含 B | Hit=1、PoolCov=0.5、Cov=0.5、ConditionalCov=1 | §19.1 完全一致 |
| Clopper–Pearson 零事件 n=20 | 0.1391083407 | ≈13.9% |
| 零事件 n=29 | 0.0981446277 | ≈9.8% |
| 零事件 n=59 / n=299 | 0.0495076099 / 0.0099691468 | <5% / <1% |
| CP e=1，n=20 | 0.2161061642 | `scipy.stats.beta.ppf(0.95,2,19)` 一致 |
| 功效 σ=0.10, δ=0.03, α=.05, power=.8 | n=88 | 计划示例 88 |
| 功效 σ=0.20, δ=0.03 | n=349 | 计划示例 349 |
| 簇 bootstrap（5 簇 / 10000 次 / seed 7） | 点估计 0.0385，CI [0.0190, 0.0600]，unit=`shape_lineage` | 按簇重采样、可复现 |

### 4.3 端到端演示（本地 fixture，读数为真实测量）

构建 3 事件 / 7 片 fixture store（2 个 dev lineage + 1 个孤立片）后：

* `build_pool`：`queries=4`、`candidates=7`、`r2_edges=5`、`r1_edges=2`、`tiny_contact_edges=1`、
  `unknown_edges=1`、`explicit_edges=9`、`distractor_isolated=true`、`n2_materialised=false`，
  耗时 0.039 s；R0 隐含对 = 21−9 = 12（未物化）。
* `run_diagnosis`（浅基线 scorer，dev，confirmation 关闭）：`status=QA_PASSED`；
  PoolCov@M=1.0、any@M=1.0、ConditionalCov=1.0、Hit@1=0.25、Cov@1=0.125、Hit@5=1.0、
  Cov@10=Cov@20=1.0；`present_denominator=4`、`absent_denominator=0`；
  `present_wrong_accept=4/4`（默认接受集 = TopK，误荐如实计入）；**风险单元数 = 0 ⇒
  `upper_bound=null`、`verdict=NA`**（没有 mate-absent 单元就不给上界）；bootstrap `n_clusters=2`、
  `replicates=200`。五个报告文件均生成，parquet 行数 = 4（per-query）与 1（summary）。
* `run_episode_config`：`ok=true`、`steps_total=10`、`stop_reasons={"BUDGET_ACTIONS":4,"STOP":2}`、
  `seconds_total=189.0`、`frames_total=8`、`pool_rerank_only_steps=8`、`stop_closed=true`；
  各基线净召回增益 0.0（沙箱内没有新证据到达，如实为 0 而非编造增益），
  `ORACLE_ACTION` 单独上报且 `legal_baseline=false`。

---

## 5. 状态与缺口（诚实清单）

| 项 | 状态 |
|---|---|
| `relations/{gallery,sampler,api}.py` | **QA_PASSED（本地 fixture）** |
| `diagnostics/{metrics,stats,fixtures,runner,api}.py` | **QA_PASSED（本地 fixture，手算 fixture 全等）** |
| `episodes/{env,baselines,api}.py` | **QA_PASSED（本地 fixture）** |
| 真实证据库上的 pool/diagnosis/episode | **NOT_RUN**：`data/a12` 无 `clean_truth`/`label_bundle` 资产 |
| 训练型 checkpoint 诊断 | **PENDING**：无已训 checkpoint（默认浅基线，报告标注 `DEPLOYMENT_MODEL_NOT_PROVIDED`） |
| 31 轴实测曲线 | **PENDING**：degrade 侧无 committed per-axis/level 观测产物，cell 记 `NA/OPERATOR_NOT_REALIZED` |
| 实拍/标定/GPU 小时 | **PENDING**：`REAL_DATA_PENDING`、相机 profile `UNCALIBRATED`、CPU-only |

* **G1（阻塞，需训练模块改一行）**：`synlab/training/batch.py::_build_lookup` 返回的是
  邻接 **dict**，而 `build_training_batch` 在 `history_r2 = cid in neighbours_lookup(qid)` 处
  把它当函数调用，任何非空 rows 都会 `TypeError: 'dict' object is not callable`。
  该文件不在本任务写入范围，因此集成测试 `test_rows_feed_training_batch` 用等价的本地 wrapper
  证明：**本模块产出的 rows 完全合法**（`negative_audit.ok=True`，无历史 R2/TINY/UNKNOWN/自身进负例）。
  修复后应删除该 wrapper。
* **G2**：上游 `synlab.truth` / `synlab.observe` 尚未落地，pool 的关系来源目前读取
  `label_bundle.meta["relations_json"]`（`pipeline._commit_labels` 的真实格式）与
  `clean_truth.meta["relations"]`；真实 truth 模块的序列化若不同，需要在此处加一个分支（已在
  `_relations_from_record` 写明三种可接受编码）。
* **G3**：`tests/a12/_fixtures.make_feature_payload` 的 `a12.obs.v1` 载荷没有 `view_tokens`
  字段（真实 `observe.features._view_tokens` 会产出），因此本仓库的 R0 类别与挖掘向量在该 fixture 上
  回退到点/法向/质量统计；接上真实 adapter 后自动使用 `view_tokens`。
* **G4**：默认扰动提供者（`degrade.api.apply_axis` 路径）当前对每个 axis/level 返回
  `OPERATOR_NOT_REALIZED`（没有可用的 committed 观测产物），runner 因此把 cell 记 NA；
  接入后（或注入 provider）即可得到实测曲线。**绝不**用随机数补 cell。
* **G5**：episode 的默认 observer（store 中同一 query 的后续 `obs_version` 资产）在本 checkout
  恒为 `None`，动作因此只重排原池并标 `POOL_RERANK_ONLY`；拿到 observe 的分版本资产后即可产生
  真实"新证据 → 候选集变化"轨迹（`test_step_rechecks_the_whole_fixed_gallery` 已用注入 observer
  验证该路径）。
* **G6**：10k/100k 嵌套库与 `SCALE_*` 便携 JSON 未实测（无可生成数据）；超出可用片数的嵌套尺寸记
  `GALLERY_SIZE_PENDING`，>20000 片的便携 JSON 直接 `SKIPPED_SIZE`（store 资产仍为权威）。
* **G7**：跨母体的 `R1`（同型异器）标签必须由真值/审核给出；当前只有真值资产显式声明的 R1/TINY/UNKNOWN
  才是显式边，其余跨事件对按"互斥 ⇒ R0"处理（已在文档与代码注释写明，不得当成"未确认"）。
* **G8**：episode 成本用的是未标定相机 profile 的声明耗时（`UNCALIBRATED`），真实拍摄/人工秒数
  需要同片真实对照；本报告不据此声称墙钟时间。
* **G9**：`docs/a12/training_diagnostics_episodes.md`（另一并行任务所写）在本模块落地前已声明
  `diagnostics/**`、`episodes/**` 为 QA_PASSED；本文件是该声明的**实际证据来源**，
  两者如冲突以本文件与实测为准。
* **G10**：空库时 `build_pool_from_config` 返回 `ok=false` + `GALLERY_SIZE_PENDING`（结构化审计，
  而不是抛异常），因此 `run_evidence.py` 仍会写出 `pool_audit.json`，验收 A15 会显示 **FAIL**
  而不是 **NOT_RUN**。若 Lead 希望"库不可构建"记为 NOT_RUN，只需让本函数在无片段时改为抛
  `SynLabError(GALLERY_SIZE_PENDING)`（`run_evidence.attempt` 会写成 NOT_RUN）——此处选择
  "返回结构化失败"，因为计划明确把数量不足定义为 `GALLERY_SIZE_PENDING` 状态。
* **G11**：`tests/a12/api/test_assets_and_paths.py`、`tests/a12/api/test_events_sse.py` 存在
  3 个**既存**失败（`synlab/api/integrity.py` 抛 `ApiProblem` 而非 `SynLabError`；SSE 心跳空闲流
  被关闭），与本任务写入范围无关，未做改动，供 Lead 分派。

---

## 6. 复现命令

```powershell
# 全部本任务测试
& .venv\Scripts\python.exe -m pytest tests/a12/relations tests/a12/diagnostics tests/a12/episodes -q

# 手算 fixture（A18/A30/A31 的证据来源）
& .venv\Scripts\python.exe -c "from synlab.diagnostics.fixtures import run_fixtures; import json; print(json.dumps(run_fixtures()['metrics']['ok'])); print(json.dumps(run_fixtures()['stats']['clopper_pearson']['upper_bounds']))"

# 能力探测
& .venv\Scripts\python.exe -c "from synlab.api.capabilities import probe_capability; [print(k, probe_capability(k, refresh=True).status) for k in ('relations','diagnostics','episodes')]"

# 真实链路（需先生成 label_bundle/clean_truth 资产）
& .venv\Scripts\python.exe -m synlab.cli build-pool --release <run>_release --config configs/a12/pool_dev.yaml
& .venv\Scripts\python.exe -m synlab.cli diagnose   --config configs/a12/diagnose_sandbox.yaml
& .venv\Scripts\python.exe -m synlab.cli episode    --config configs/a12/pool_dev.yaml
```
