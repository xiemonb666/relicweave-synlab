# 创新研究底账

项目：**PG-Frag**　｜　记录日期：**2026-10-04**

> 本文服务于 RelicWeave 碎片邻接检索与证据决策主线；候选可修改、合并或淘汰。登记不代表已实现、有效、原创或具备论文资格。成熟库/API/求解器、标准 CAD/mesh、包装器不登记为本项目原创算法；没有 primary-literature novelty audit 的条目一律保持候选。

**主线关系：** PG-Frag/A12 为 RelicWeave 提供可审计的几何、事件和物理碎裂训练数据候选；RelicWeave 才是碎片观察→邻接候选→证据→拒识/重采集/STOP 的产品研究主线。当前不能由 solver 运行、几何 QA 或 toy contact 推出 physical R2 或 PRETRAIN 准入。

## 共用的数据语义边界

- 总方案允许将早期程序分区或非平面切割明确标为 SYNTHETIC 几何基线保留；这不降低当前真实物理模拟目标的验收要求，也不得把程序切割标签称为物理 R2。
- R0、R1、R2、UNKNOWN 与 historical_R2、current_fit、evidence_visible 分字段保存；不得混并标签语义或用旧标签改写当前证据。
- bag/object 身份、完整装配信息与 GT/oracle 字段不得进入网络输入；只允许在隔离的标签、审计和评估侧使用。
- 来源范围：RelicWeave_V1.44_Optimized_Complete_Plan.docx：主线问题与输入权限见总纲/第2节及 P00003、P178–180；程序切割作为显式 SYNTHETIC 几何基线见 P1191–1192（由 root 复核）。

## 工程基线（不作为研究创新）

- PG-Frag 当前是围绕 pinned Peridynamics.jl 0.5.4 的 Python SDK/CLI；README 中可运行 slice 是均质 bar 原型，材料值 `UNVALIDATED_PROTOTYPE`，不输出几何裂面、事件时间线、动态碎片或 contact 物理结论。
- 现有 toy native contact case 与 Akantu 是库/API 的受限使用与审计。任何包装器、标准 CAD/mesh、原生 cohesive/PD 求解器本身不登记为原创算法。保留已验证 PD baseline；不先全面迁移或自研通用求解器。
- 工程建议中的分层准入本身已有 A12 六道门槛与 Fracture Route Advisory 记录；门槛实现尚未形成主仓端到端数据发布资格。

## 已证实验事实与边界

- native contact：按 A12 接续记录，完成一例 1-step preflight、240-step baseline、480-step half-dt 和 240-step no-contact control；最大 opposite-body momentum residual 为 3.4188e-24 kg·m/s，名义 cell-envelope overlap 0.5904 mm。toy 未校准，contact-force/energy history 不完整，energy 与 integrated impulse 的物理解读仍 UNKNOWN。
- Akantu 5.0.7.post1 固定中央接口 capability：zero-load 1707 steps，无插入；名义 mode-I（只读诊断判为 mixed-mode）1707 steps 与 half-dt 3414 steps，均插入 8 个 native interfaces。加载耗散分别为 -5.572968137645039e-5 J 和 -9.726359554870569e-6 J，目标 GcA=3.04e-5 J 未达到，细化变化 82.55%；故只证明窄 API/双侧拓扑，不通过数值物理验收。
- 201 patch 当前状态仅采用主代理提供的 2026-10-04 状态快照：run01 属性绑定错误、0 steps；v2 尚未执行。为避免读取变化中的产物，本账未打开该 run 的动态状态、trace 或 output。
- 无真实材料校准、真实自由裂纹或物理 R2；无独立 remesh 方向偏差结果，无 physical-R2/PRETRAIN_ELIGIBLE 数据，无主仓完整集成。h0.5 局部 ROI 仅通过有限静态几何 QA，不能背书 solver。

## 主档案来源

- `pgfrag/README.md` — supported material, no crack surface/event chronology/contact and physical nonclaims。
- `relicweave-synlab/docs/a12/CONTINUATION_20261004.md` — 当前窄结果、Akantu 与 native contact 数值、六道准入门槛。
- `relicweave-synlab/docs/a12/COHESIVE_CAPABILITY_20261004.md` — Akantu capability、负耗散与固定接口范围。
- `relicweave-synlab/docs/a12/COHESIVE_DIAGNOSTICS_20261004.md` — 插入拓扑/lineage 诊断边界与能量/开口 UNKNOWN。
- `relicweave-synlab/docs/a12/FRACTURE_ROUTE_ADVISORY_20261004.md` — PD/cohesive 风险、试验合同、路线切换和 R2 候选阈值，最终裁决留给 root。
- `pgfrag/experiments/cohesive_capability/manifest.json` — 冻结的 toy 输入、材料、预注册边界与源哈希。未检查 201 活动 run 产物。

## 候选研究记录

| ID | 类型 | 状态 | 标题 |
|---|---|---|---|
| PG-RC-001 | candidate_research_contribution | `pending-main-review` | 事件到共同静止材料坐标的双侧裂面谱系 |
| PG-RC-002 | candidate_research_contribution | `pending-main-review` | 薄壁尺度公平性、独立网格方向偏差与物理样本分层准入 |

### PG-RC-001 — 事件到共同静止材料坐标的双侧裂面谱系

**状态：** `pending-main-review`（candidate_research_contribution，等待 root 主审）

**问题：**
能否把真实求解中的裂纹事件映射为同一 rest-material surface 上成对的双侧裂面、共同祖先及后继碎片身份，并在不能唯一决定时保留歧义，从而为 RelicWeave 产生可审计的 fracture evidence？

**与 RelicWeave 核心的关系：**
此候选构造未来训练标签和裂面证据，处于 A12/PG-Frag 数据基础设施层；它不改写 RelicWeave 邻片模型，也不让物理模拟标签自动成为 R2 真值。

**候选方法：**
- 事件记录与几何共享不可变 rest-material 坐标系。Cohesive 路线至少保留 interface ID、parent facet、双侧节点祖先、两侧 bulk IDs、插入/完全脱粘事件及 fragment IDs；只有界面完全失败且两侧成为不同后继片时，才从同一祖先三角面输出 paired patches。
- PD 路线记录稳定无向 bond ID、两端材料点、首个失效步/时间、阈值/材料/参考方向与可重放状态；共同裂面重建应显式列出等价面假设、歧义面积和误差，不以碎片两侧独立拟合后 nearest match 充当真值。
- 同一接口不预选为“创新 solver”：测试目标是可辨识、lineage 与几何合同；如果 event→surface 不唯一，输出 `UNKNOWN`。

**成熟上游内容与归属：**
Peridynamics.jl 0.5.4 与 Akantu 5.0.7.post1 是已有上游 solver；cohesive 插入、PD 断键、mesh connectivity 和常规表面重建不是本项目原创。候选只可能在碎片任务中的共同坐标谱系合同、歧义量化和训练资格关联上形成方法贡献。尚无 primary-literature audit，不引用未经核实的首创判断。

**证据路径与范围：**
- `pgfrag/README.md`：当前 PD bar 只给 material-point state 与端点 bond 状态，不导出 crack surface、动态 event chronology、fragment shapes 或历史 A12 R2。
- `relicweave-synlab/docs/a12/COHESIVE_CAPABILITY_20261004.md` 的 Recorded solver cases / Native insertion and lineage：固定合同网格中 8 interfaces、局部 ID/ordinal lineage 窄证据；负耗散、GcA 未达标。
- `relicweave-synlab/docs/a12/COHESIVE_DIAGNOSTICS_20261004.md` 与 `CONTINUATION_20261004.md` 的只读诊断：当前固定面插入不是自由裂纹/碎片分离，damage/full failure 和能量解释仍 UNKNOWN。
- `relicweave-synlab/docs/a12/FRACTURE_ROUTE_ADVISORY_20261004.md` 的 R2/切换规则：共同 rest-interface、明确歧义、positive area 与成对祖先均为待验证条件。

**失败与不确定性：**
- Akantu 固定中央接口只证明候选 surface topology 可以插入和有限 lineage 映射；能量为负且未达到 GcA，尚无自由路径/完整脱粘/碎片拆分证明。
- PD bond failures are constraints on possible surfaces, not a unique area-bearing 3D crack surface. Surface extraction, branch topology, curvature, crack area and point/horizon/remesh bias remain unresolved.
- 真实陶瓷强度、Gc/混合模态、率效应、空间材料场和 contact 未校准；固定 toy 几何标签不代表真实物理裂面。
- Advisory lists candidate R2 thresholds, but historical data documents contain threshold/version inconsistency; root must freeze the controlling contract before applying it.

**对照基线：**
- Current native PD endpoint bond-state report, which has no geometric surface chronology; quantify what event logging alone adds.
- Fixed central Akantu interface contract case, explicitly as API/connectivity baseline and not free crack path.
- A naive end-state component boundary, arbitrary shared tet facets, and separate-side nearest-surface fit are negative/weak baselines; none may be named truth without validation.

**必要评估（消融/数值/视觉/真实数据）：**
- 先做解析 single-plane 和 branch/intersection toy，保留 no-fracture、partial-damage、contact-only、初始缺口、外表面为负控。固定同一个输入、材料场、事件和随机种子，再逐级测试加密。
- 数值/几何评估：唯一性/歧义面积率、祖先 ID 冲突率、双侧面积差、重心对应 gap_p95、反向法线角 p95、母体材料内采样率、质量守恒、事件时间定位误差及 topology/branch agreement。建议门槛 `area ≥ max(0.1 mm², 1e-4 × mother material area)`、`gap_p95 ≤0.02 mm`、normal p95≤2°、ambiguity≤0.02、interior sampling≥0.90 只作 Advisory 提议，必须 root 复核后冻结。
- 对真实或可信物理结果另测力—位移、断裂功、fragment mass 与实测断面；数值共同祖先保证的是仿真内几何配对，不证明材料物理正确。可视化仅叠加 same-rest-coordinate 的双侧 patch、事件和祖先，不能替代数值门。
- 做一项独立 remesh/point placement 对照，比较共同坐标谱系方法与 nearest-fit baseline；任何模型训练都等待 `CrackSurface` 与 `RelicWeaveData` 门分别通过。

**预冻结验收：**
- root 先批准 R2 版本和面积门，再冻结 canonical geometry/CAD crop、材料/边界、solver/build、mesh/horizon、时间步、裂纹事件定义、surface extractor、fragment definition、随机种子和允许误差。
- surface 必须来自 solver 中实际新失效事件，双侧均映射同一祖先、属于不同后继 fragment，满足已冻结的面积、gap、normal、ambiguity、材料内采样和质量守恒门；部分损伤不得算全 facet 面积。
- 先通过小 toy 的数值/几何合同，再做独立 remesh/材料校准/真实验证；任何 UNKNOWN 或缺证据都从物理预训练 roster 排除。

**否证或切换条件：**
- 若插入面 ancestry 缺失/冲突、PD 事件对应多块同样合理 surface 且歧义门不通过、裂纹不使不同片分离或 R2 几何界失败，则本表示不合格并保持 UNKNOWN。
- 若 cohesive 能运行但独立重网格自由路径偏差不收敛，记录 `NumericPhysical FAIL`，最多一次有依据的分辨率修正；按 Advisory 才可转向冻结 PD 的受限重建 spike。环境/ancestor BLOCKED 也只允许一次 fallback。
- PD fallback 仍不能约束面积/位置/拓扑歧义时停止，不启动第三个自研求解器或视觉后处理修补。

**复现与许可审查：**
- 每次 run 前冻结并保存准确 source/input/manifest bytes 与 SHA-256、solver/wheel/build、环境、命令、材料/几何、所有 event traces、完整失败输出；post-run 诊断另存，不覆写源。当前 capability source hash 闭合不等于完整实验包或跨机器复现。
- 待审 Akantu、Peridynamics.jl/vendor、mesh/geometry 依赖和生成数据的许可证、归属、再分发义务；未完成前仅本地研究，不承诺开放 source/data。
- 当前证据仅为窄 toy；没有完整论文方法/数据复现包，也未做 primary-literature novelty audit。

**下一步：**
root 先裁决路线和 R2 合同，再决定能量/本构受控小例的准入；未经其批准不创建自由路径或 PRETRAIN 样本。

**Novelty 审计：**
NOT_AUDITED — 现有结果不是自由碎裂或方法新颖性证明。


### PG-RC-002 — 薄壁尺度公平性、独立网格方向偏差与物理样本分层准入

**状态：** `pending-main-review`（candidate_research_contribution，等待 root 主审）

**问题：**
在薄壁器型中，怎样把真实壁厚/物理特征尺度与粒子 horizon 或 FEM mesh/process zone 分辨率分开，量化独立网格取向造成的裂纹路径和能量偏差，并确保只有可复现且物理合格的样本进入 RelicWeave 预训练？

**与 RelicWeave 核心的关系：**
此候选将尺度公平评估和数据 admission 接到 A12→RelicWeave：合成外观/几何样本可用于几何研发，只有各层证据门闭合的数据才可带物理裂面标签。分层门禁是工程治理；是否形成科学贡献要由对照实验和 root 裁决。

**候选方法：**
- 对 canonical 薄壁 ROI 记录无量纲尺度表：实测 `t/h`、PD `δ/h` 与 `δ/t`、cohesive 的 `h/l_process-zone` 与 `t/l_process-zone`；以同一 rest-material field/载荷对多个独立生成的网格取向/seed 分别细化。保持 h refine、time-step refine 和 horizon/process-zone sensitivity 为互不替代的对照。
- 至少比较三组独立网格取向/seed 和一个 refinement ladder；记录力—位移、起裂时刻/峰值、有效断裂功、裂面面积/法向、rest-coordinate 路径/分叉、碎片质量和 wall-resolution。单纯旋转同一个网格只作为 covariance check，不当作独立网格偏差。
- 为每条样本写层级 admission 状态：Geometry→NativeRun→NumericPhysical→CalibratedMaterial→CrackSurface→RelicWeaveData；每层保存证据 hash/方法版本，`UNKNOWN/FAIL` 不晋级。六门分层本身沿用已有 A12/route advisory，是工程合同而非独创算法。

**成熟上游内容与归属：**
薄壁分辨率、PD horizon/free-surface correction、cohesive process zone 与网格各向异性均是既有数值力学问题；PG 使用成熟 solver，不主张创造求解器。A12 的六道门和 engineering_policy 已提出分阶段、可证伪、保留基线原则。候选增量是碎片材料域上的统一尺度记录、独立重网格评价和数据资格联动；新颖性未审计。

**证据路径与范围：**
- `relicweave-synlab/docs/a12/FRACTURE_ROUTE_ADVISORY_20261004.md` 的路线风险/三类验收：薄壁 `t/h`、PD `δ/h` 和 `δ/t`、cohesive process zone、独立 remesh 和方向间差值必须分别测。
- `relicweave-synlab/docs/a12/CONTINUATION_20261004.md` 的 local ROI 与六道门：h0.5 只通过有限静态几何 QA；h8/h6 tets 已因体积/内部探针被拒；几何通过不能推出物理或数据资格。
- `relicweave-synlab/docs/a12/engineering_policy.md` R1–R5/复审触发：构造性、对照、保留干净基线、不放宽判据。
- `relicweave-synlab/docs/a12/deploy_boundary_v2.md`：结构与哈希完整性不等于 physical qualification 或科学有效性。

**失败与不确定性：**
- 当前没有通过 physical R2 的样本、标定材料或独立 remesh/方向数据；201 run01 状态按主代理快照为 0 steps，v2 未执行。
- 当前 h0.5 仅有有限几何 QA，不能推断 t/h、process zone、horizon 或动态裂纹精度足够。旧 h8/h6 volumetric meshes 已被拒，不能作为 solver 证据。
- 候选的无量纲尺度项及其合格界限仍需从实际材料、ROI 与 pilot 确定；不得凭经验写一个 t/h 最小值或用图片判断收敛。
- 单一网格旋转、随机化一个网格、增大网格数量但不固定 material field/训练预算，都会混淆公平性结论。

**对照基线：**
- 单一 mesh / point layout 的现有 toy run；相同网格旋转且同步旋转载荷的 covariance 检查。
- 传统几何 QA-only admission 作为负控；它不得被称为物理数据准入 baseline 的成功版本。
- PD 固定 δ 加密 h 与 cohesive 固定过程区尺度加密 h 分开比较；另测 δ/process-zone sensitivity，不混成一个收敛数字。

**必要评估（消融/数值/视觉/真实数据）：**
- 先挑一个 geometry 已通过的 canonical cup-wall 小 ROI；冻结真实壁厚字段、材料空间场、边界、缺口、物理载荷和 final time。不同 mesh 从同一个 rest-space material field 取值；所有 run 保留实际质量、积分支撑和自由表面/边界修正。
- 构造 refinement×orientation/seed×dt 矩阵，至少三组独立网格方向/seed。报告每级粗细差、方向间差、δ/h、δ/t 或 h/process-zone、实际过程区分辨率、接触/能量质量账本；对稳定性指标报告统计分布/置信区间。
- 数值主比较包含裂纹路径/分叉拓扑、峰值和起裂、有效 fracture work、成对表面面积与法向、质量和动量；视觉 overlay 作为定位/审计，不代替数值指标。最终候选还要与实物断裂试验的 load-displacement、断裂功和形貌作独立验证。
- 准入结果统计各 gate 的 pass/fail/unknown 数量及 false-admission 审计，不以 geometry PASS 或 solver exit 0 计入 physical pretraining roster。

**预冻结验收：**
- 在 pilot 前冻结 geometry/material/crop、数值路线、mesh seeds/orientations、h/time/horizon 或 process-zone 序列、每个主指标、预算和失败去向；pilot 后由 root 预注册接受误差与样本量，再运行确认集。当前没有从证据支持的方向/能量数值阈值，不在本账中发明。
- 通过条件要求 refinement 与独立方向间变化均落在已冻结界内；能量、拓扑、面积、质量与数值物理层全部通过；材料参数有来源和不确定度并经外部数据验证；裂面合同与部署数据层单独通过。
- 任何一个 gate `FAIL/UNKNOWN/NOT_RUN` 时保留原始标签和证据，不进入物理训练集；可另列几何/数值研究集但不得混名。

**否证或切换条件：**
- 若网格方向差在 refinement 后不收敛、裂纹拓扑/面积随方向系统变化或能量依赖网格而不能以预先模型解释，则否证当前路线对该尺度/几何的公平性主张。
- 若 physical labels 只通过几何 QA、材料参数靠“让裂纹发生”调到通过，或有效断裂功不守恒，禁止进入 PRETRAIN_ELIGIBLE。
- 按 fracture advisory 最多一次有证据的精度修正；仍失败则保持 candidate/unknown，重新交 root 选择路线，不加第三个 solver 或后处理修补。

**复现与许可审查：**
- 每样本保存 immutable mesh/point set、CAD/rest field/material field、solver/source/build、完整参数、采样、seed、环境、命令、原始 trace、hash/bytes 和后处理版本；确认阶段独立重放至少一个 case。
- 完成 PG/solver/mesh dependencies、实物图像/材料数据授权与再分发审核；hash 闭合不等于 license 允许公开。当前未完成许可审计。
- 分层 admission 代码与仓库整合、统一受控数据集及有效性对照均未完成；方法新颖性需查 primary sources 后才能写入论文主张。

**下一步：**
root 裁决此方向应作为数值验证计划还是独立方法候选；若继续，先确认 canonical ROI 和六层准入合同，再设计有预算的 pilot，禁止先跑大批生成。

**Novelty 审计：**
NOT_AUDITED — 薄壁偏差与数据准入的工程价值可检验，尚无论文创新结论。

## 共通签收口径

- 研究状态与证据结论分开；仿真退出成功、资产几何 QA、代码可执行和材料物理合格是不同事实。
- 当前没有真实自由碎裂/材料标定/独立方向偏差/physical R2 或 PRETRAIN 准入证据。论文主张需在 root 复核、预注册对照、真实数据评估和许可证审查后另行裁决。
- 本账未作广泛文献搜索，也不承诺完成比例、SOTA、独创或已可投稿。
