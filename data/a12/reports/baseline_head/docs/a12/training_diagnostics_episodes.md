# A12 训练 / 退化诊断统计 / 主动观察 episode：接口、集成点与状态

本文件是 `synlab/training/**`、`synlab/diagnostics/**`、`synlab/episodes/**` 三个模块的
**本地冻结契约 + 实现状态 + 复用证据索引**。上位权威仍是
[`docs/a12/interfaces.md`](interfaces.md) 与计划第 0/3/17/18/19/26/30 节；本文件只补充
并行开发期需要显式约定的数据形状与集成点，不重定义上游类型。

> 诚实状态：截至本次运行，`synlab.observe.api` 与 `synlab.relations.api` **在本仓库尚不存在**
> （并行开发中）。因此所有训练/诊断/episode 代码通过**结构化只读适配器**访问它们，测试一律使用
> 本地 fixture。真实上游接入前，以下能力标记为 `PENDING`：
> `REAL_DATA_PENDING`（无实拍数据）、`INTEGRATION_PENDING`（上游模块未落地）、
> `ENV_CAPABILITY_MISSING`（无 CUDA，仅 CPU torch）。

---

## 0. 运行环境（实测）

| 项目 | 值 |
|---|---|
| 解释器 | `C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\.venv\Scripts\python.exe`（CPython 3.12.14） |
| torch | `2.5.1+cpu`，`torch.cuda.is_available() == False` |
| numpy / scipy / pandas / pyarrow | 2.5.3 / 1.18.1 / 2.2.3 / 25.0.1 |
| faiss | `faiss-cpu 1.15.1`（`IndexFlatIP` 精确内积） |
| sklearn | **不存在**（自实现 bootstrap / Holm / Clopper–Pearson） |
| 训练精度 | **FP32 only**（CPU，无 BF16 路径；见 §3.6） |

所有命令均以仓库根为工作目录：
`& .venv\Scripts\python.exe -m pytest tests/a12 -q`

---

## 1. 张量与数据合同（`a12.obs.v1` → 训练张量）

`synlab.training.adapter.FeatureBundle` 是**张量前的中间合同**；上游
`synlab.observe.api.adapt_observed_features(obs, contract)` 的输出被
`FeatureBundle.from_dict()` 消费。所有数组以 numpy 表示，进入
`torch` 只做 `from_numpy`（不复制语义，不改变 dtype 语义）。

| 字段 | 形状 | dtype | 语义 |
|---|---|---|---|
| `fragment_ids` | `[F]` | `<U…` | batch 内**去重**片身份（opaque，仅用于索引与日志） |
| `global_rgb` | `[F,V,3,H,W]` | `float32` | global/fracture RGB，scene-linear 归一化到 `[0,1]` |
| `global_valid` | `[F,V]` | `bool` | view 是否可编码（缺输入 → False，**不补零冒充有效**） |
| `pixel_valid` | `[F,V,H,W]` | `bool` | 像素级 mask（背景/遮挡为 False） |
| `local_tokens` | `[F,L,256]` | `float32` | 局部 token 特征，**可变长度**（`L=max`，按 `token_valid` mask） |
| `token_valid` | `[F,L]` | `bool` | 活跃 token（真实数量，不重复填充） |
| `token_view` | `[F,L]` | `int32` | token 所属 view 索引，无效为 `-1` |
| `token_pixel` | `[F,L,2]` | `int32` | `(y,x)` 像素中心，无效为 `-1` |
| `token_modality` | `[F,L]` | `int32` | `0=RGB 1=DEPTH 2=NORMAL 3=POINT` |
| `token_source` | `[F,L]` | `int32` | 拍摄来源分组 id：**同 crop 复现的 token 共享 id**（30.11 去重加权） |
| `token_retrieval` | `[F,L]` | `int32` | 超额 token 的**回取索引**（指回上游全量 token 表），无则 `-1` |
| `tokens_total` | `[F]` | `int32` | 上游该片可用 token 总数（用于保留率验收） |
| `points` | `[F,N,3]` | `float32` | 观测扫描坐标（mm，仅 `scale_valid` 时是 mm） |
| `point_valid` | `[F,N]` | `bool` | 有效点（不足 N 保真实数量，尾部 False） |
| `normals` | `[F,N,3]` | `float32` | 估计法向 |
| `normal_valid` | `[F,N]` | `bool` | 法向有效 |
| `quality` | `[F,R,Cq]` | `float32` | `OBS_EST` 质量通道（**不是 oracle**） |
| `quality_valid` | `[F,R,Cq]` | `bool` | 每通道 target valid（来源独立） |
| `presence` | `[F,Cm]` | `float32` | 模态/参数存在性通道 |
| `presence_valid` | `[F,Cm]` | `bool` | 存在性 target valid |
| `scale_valid` | `[F]` | `bool` | 观测尺度可信（进 3D 分支的硬门） |
| `obs_version` | `[F]` | `int32` | 观测版本（episode 用） |

配额（18.1）：每片活跃 token 上限默认 `256`（`128/256/512` 可配）；分层配额按
**可见断口面积 → OBS_EST 质量 → 空间分层** 依次分配，小 ROI 有最低配额
（`min_roi_quota`，默认 8）；超额部分写 `token_retrieval` 回取索引，**不丢弃地丢失来源**。

### 1.1 训练批 `TrainingBatch`

| 字段 | 形状 | 语义 |
|---|---|---|
| `pair_index` | `[Q,C,2]` | `(query 片索引, 候选片索引)`，`Q`=query 数，`C`=候选数 |
| `pair_valid` | `[Q,C]` | 该 (q,c) 是否为合法候选（否则整对 mask） |
| `labels_relation` | `[Q,C]` | `0=R0 1=R1 2=R2 3=TINY 4=UNKNOWN`（**仅 loss 侧可读**） |
| `label_pair_valid` | `[Q,C]` | 关系标签是否已确认（未确认 → False，不当 R0） |
| `pos_mask` | `[Q,C]` | 该候选是否进 query 的正例集合（多正例**互不竞争**） |
| `neg_mask` | `[Q,C]` | 合法负例（R1/R0 且已确认） |
| `excluded_mask` | `[Q,C]` | 被排除（R2 已知但本次未采样为正、灰区、UNKNOWN、同片） |
| `exclusion_reason` | `[Q,C]` | `0=none 1=same_fragment 2=known_R2 3=gray_zone 4=unknown 5=TINY 6=label_invalid` |
| `quality_target` | `[F,R,Cq]` | 质量回归/分桶 target（`GT_ORACLE` 侧） |
| `quality_target_valid` | `[F,R,Cq]` | 每通道独立 valid |
| `corr_rows` / `corr_cols` / `corr_weight` | `[Q,C,K]` | 局部对应的多对多**边权 W**（`W≥0`，行归一后为 soft target） |
| `corr_row_valid` / `corr_col_valid` | `[Q,C,K]` | 行/列 token 是否有效（未知整行 mask；明确无目标才 dustbin） |
| `corr_kind` | `[F,L]` | `0=UNKNOWN 1=EXACT_SURVIVOR 2=VERIFIED_RECESSION`（**UNKNOWN 不进正对应**） |
| `contradiction` | `[Q,C]` | `0=missing 1=compatible 2=contradicting`（missing 单独 mask） |
| `contradiction_valid` | `[Q,C]` | 反证标签是否可信（无构造 → False） |
| `quality_tier` | `[F]` | `0..5` → `Q0/Q1/Q2/Q3/Q4/Q5`（课程用；`Q2` 未校准按 `stress` 标记） |
| `lineage_cluster` | `[F]` | 谱系簇（抽样均衡 + bootstrap 单位） |
| `negative_is_r2_history` | `[Q,C]` | 历史 R2/灰区标记：**必须为 False 才允许进负例** |
| `r1_fallback_used` | `[Q,C]` | 缺 R1 时退到 R0 的记录位 |
| `sample_keys` | `[Q]` | 确定性样本键（resume 序列比对） |

`labels`（R2/对应/贴合/quality/loss_mask）与特征**分开返回**，绝不拼进特征张量。

---

## 2. 集成点（并行模块）

| 上游 | 期望调用 | 本模块落点 | 状态 |
|---|---|---|---|
| `synlab.observe.api.adapt_observed_features` | `adapt_observed_features(obs, contract) -> dict`（JSON/ndarray 混合） | `training.adapter.FeatureBundle.from_dict` | `INTEGRATION_PENDING`（模块不存在） |
| `synlab.relations.api.build_pool` | `build_pool(store, release, spec) -> GallerySpec` | `training.sampler.PoolIndex`、`diagnostics.runner` | `INTEGRATION_PENDING` |
| `synlab.relations.api.sample_training_batch` | `sample_training_batch(pool, sampler_cfg, rng) -> dict` | `training.sampler.BatchSource` 的参考实现；本地用 `FixturePool` | `INTEGRATION_PENDING` |
| `synlab.cameras.api.camera_profiles` | `camera_profiles() -> list[CameraProfile]` | `episodes.env.EpisodeEnv` 可达性判定 | `INTEGRATION_PENDING` |

**适配器约定**：三个模块都不 `import synlab.observe` / `synlab.relations`（避免并行开发期
导入失败）；一律用 `Protocol` + 结构化 duck typing。上游落地后只需替换 fixture，无需改本模块。
测试 fixture 位于 `tests/a12/_fixtures.py`（numpy 生成的合法特征包，不依赖上游）。

---

## 3. 实现状态表

| 文件 | 内容 | 状态 |
|---|---|---|
| `training/adapter.py` | 输入合同 → 张量、分层配额、masked pooling/gating | QA_PASSED（本地 fixture） |
| `training/model.py` | 双塔初检 + 局部精排头 + classical 浅基线 | QA_PASSED（本地 fixture） |
| `training/losses.py` | A–E 五项损失、有效分母、logsumexp | QA_PASSED（本地 fixture） |
| `training/sampler.py` | lineage 均衡抽样、分桶、IterableDataset、派生 seed | QA_PASSED（本地 fixture） |
| `training/trainer.py` | AdamW/课程/梯度累积/checkpoint/resume/NaN 护栏 | QA_PASSED（本地 fixture） |
| `training/api.py` | `train` / `evaluate` / `resume` | QA_PASSED（本地 fixture） |
| `diagnostics/metrics.py` | Hit@K/CovRecall@K/any@M/PoolCov@M/ConditionalCov/Effective*/风险事件 | QA_PASSED（手算 fixture 全等） |
| `diagnostics/stats.py` | 母体簇 bootstrap、配对差、Holm、Clopper–Pearson、功效、N90/Qcrit | QA_PASSED（数值对照 scipy） |
| `diagnostics/runner.py` | 固定 roster+gallery 评测、parquet 报告、曲线/矩阵 | QA_PASSED（本地 fixture） |
| `diagnostics/api.py` | `run_diagnosis` / `evaluate_pool` / 协议守卫 | QA_PASSED（本地 fixture） |
| `episodes/env.py` | `EpisodeEnv`、可达动作、全库重检、轨迹记录 | QA_PASSED（本地 fixture） |
| `episodes/baselines.py` | 规则基线 + ORACLE_ACTION 隔离 + 离线奖励 | QA_PASSED（本地 fixture） |
| `episodes/api.py` | `run_episode` 轨迹回放与成本汇总 | QA_PASSED（本地 fixture） |

数据规模：所有实测数值均来自 **CPU-only、小规模 fixture**，不声称 GPU 小时。

---

## 4. 复用证据

见 [`reuse_evidence_training.json`](reuse_evidence_training.json)：PyTorch（`logsumexp` /
`AdamW` / `autograd` / checkpoint 张量序列化）、FAISS `IndexFlatIP`（与 numpy 精确内积逐位校验）、
`scipy.stats`（`beta.ppf` Clopper–Pearson、`norm.ppf` 功效）。不含自造训练框架或向量索引。

---

## 5. 诚实规则落地

* 无有效监督的损失项 → **显式跳过并计数**（`skipped`），不返回 `0.0` 冒充已训练。
* `padding` 永不作为标签；分母一律按有效 query/候选计。
* 主端到端失败/超时/无输入 → `EffectiveHit=EffectiveCov=0`，**仍在冻结分母内**。
* 无邻片 query → `Hit/Cov=NA`（不写 0），仍进风险分母。
* `ORACLE_ACTION` 不进合法基线列表；`POOL_RERANK_ONLY` 不计候选恢复能力。
* 曲线只画实测点，缺失处标缺失，不做平滑拟合。
* 训练 seeds 只描述优化波动，**禁止 ×3 扩 n**。
