# PG-Frag → RelicWeave 动态断面桥接决策输入

日期：2026-10-03（Asia/Shanghai）  
性质：只读源码审阅后的算法选择输入；**没有实现、安装、修改冻结产物或运行新求解**。逐文件范围与外部主来源见 [`tmp/review_20261003/implementation/fracture_surface_bridge/source_audit.md`](../../tmp/review_20261003/implementation/fracture_surface_bridge/source_audit.md)。

## 建议裁决

**先暂停 whole-vessel 物理断裂和 R2 数据准入，先做一个小型、均质各向同性 3D 断裂基准。** 当前 PG 输出可以证明端点哪些 horizon bonds 已失效、哪些点质量被保留；它无法唯一确定动态裂面、首裂时刻或配对面。把断键、损伤云、tet/cell/Voronoi 面、端点连通分量或预设切割面直接命名为物理裂面，均越过了现有证据。

严重度：当前断面桥和方向偏置验证是 **release/data-use blocker**。小基准只解除“能否审计 event / surface candidate”的门；它不会单独解锁器物级 physics 或 physical-grade RelicWeave 数据。

首选的最小兼容路线是：给 Peridynamics.jl 结果补上**逐步不可逆断键事件与材料坐标来源**，再实现一个版本化的**非局部事件裂面重建候选器**。候选器以同一事件窗口内的断键位置/方向、点状态和材料坐标为证据，在材料坐标系拟合一张公共界面，向两侧输出成对表面、正面积、事件与来源 lineage、拟合残差和不确定度。它是需验证的 SynLab synthetic-geometry 方法，不是现成成熟物理定理；拟合连续、两面共用同一张网格或重建后 gap 为零，本身都不能证明裂纹路径真实。

共享构造可通过**合成几何 R2**：同一动态 event、两个不同叶片、可审计的共同材料界面、正面积及 A12 几何门通过。它必须另带 `physical_validation_status=UNVALIDATED/PENDING`。只有固定 CAD、连续材料场和加载条件后，经过独立重离散、点集取向、`δ/h`、空间 `h`、时间步和实测材料/断口基准，才可提升为 physical-grade。当前不存在可填写的数值收敛阈值或 Ra 门槛；应先预注册测量分辨率和误差预算，缺值保持 `PENDING`。

主要备选是成熟 cohesive/FEM 界面模型：它能显式表示成对界面及 traction/jump 历史，正面积接口更直接；但需要体网格、界面预处理或自适应裂纹路径、动态断裂、碎片接触和材料标定。预设界面/单元面本身仍有方向与网格偏置。MOOSE 官方示例描述的是 continuum FE region 间的 cohesive interface，利用 block mesh split 建界面；所引页面是 quasi-static 系统，不能据此宣称冲击陶器已就绪。该路线迁移成本为**很高至极高**，适合作为独立 benchmark 候选，不作为当前临时替换。

## 当前源码能证明什么

PG 锁定的 mechanics/time-solver 文件来自 Peridynamics.jl `v0.5.4`；headless fork 对这 20 个文件逐文件 hash 核对一致，修改仅在 I/O/VTK 路径。上游 bond-based 源码在每次力计算中按临界 stretch 把方向 bond 的 `bond_active` 置为 `false`；`damage` 是 `1 − n_active_bonds / n_neighbors`。这一值丢掉了局部断键方向与时间顺序，不是裂面或裂纹面积。原生 bond 是半径 horizon 内的非局部邻接，距离和断裂状态没有定义一张面。

当前 runner 从 uniform-box bar 启动，运行结束后才规范化 reciprocal directed bonds 为无向对。`bond_states.csv` 记录该端点的 `active`、参考长度和当前长度；`broken_bonds.csv` 是它的 inactive 子集。`components.csv` / `intact_bond_component_id` 是所有仍 active horizon bonds 的端点连通分量。它们可作为**端点图诊断**，不等同刚体碎片或共享裂面。`isolated_points.csv`、完整点表和质量字段保留点集；未来表面提取失败时也必须保留这些点和质量。

实测 branch fixture 为均匀 box、OSB/CriticalStretch、576 点、20,780 个规范 bond pair、5,236 个端点 broken pair、2 个 intact-graph component、50 步。它报告 `UNVALIDATED_PROTOTYPE`、`contact=UNKNOWN`、`surface_mapping=UNKNOWN`，未输出 event timeline、crack mesh 或 paired lineage；该统计不是陶器断裂 mesh、也不能作为 R2。PG 当前 `forge_asset_surface` 被 validator 识别但 runner 返回 `UNSUPPORTED`，原因是 surface-to-volume/material-point 离散、空腔和拓扑分类未实现。当前 VesselForge 样品只有一份中空带把手的 canonical STEP 与表面三角网格；`vertices_material_xyz_mm` 是表面顶点的 rest 坐标，尚无内部 solver points 到 B-rep/母体材料体的映射合同。

| 现在可复算 | 当前不能由 PG v1 推出 |
|---|---|
| 指定 fixture 的完整 point IDs、端点原生 bond activity、参考/当前 bond 长度、damage 数组、graph components、point volume/mass，以及是否有零度孤立点。 | 首次动态失效时间、多个独立 crack event、裂面位置/面积/粗糙度、fragment 的刚体实体形状、配对 surface lineage、历史 true-neighbor/R2、接触/回弹；这些值不得以零、component 标签或 UNKNOWN-free 默认值补齐。 |

## 裂面可辨识性与离散偏置

端点相同的一组失活非局部 bonds，可能对应不同的裂面位置、走向、连通方式和断裂先后；当前端点输出无法区分这些解释。单个或一组 broken horizon bonds 没有可直接积分的面支持；对它们按长度、horizon 截面或点损伤权重求和，会引入未定义的面积模型。端点 components 也可能在局部裂面已形成后仍被远程 intact bonds 连通，或在分散损伤下先断开；它们不能用来在母体上补一刀。

网格面不能自动代表物理裂面。tet、规则 Cartesian cell、Voronoi facet 或 meshless point graph 都可能因材料点 fabric、`δ/h`、边界/空腔处理、局部体积/点权和数值算法而产生路径偏置。受控 cohesive/FEM 面只有在模型假设合适且收敛/方向敏感性证据通过时才可解释为物理；本建议不一概否决网格方法，也不接受“换了 meshless”作为无偏证明。即使独立算法重建出连续平滑表面，它仍是对离散 event 证据的推断，应记录 reconstruction error 与 ambiguity。

初始孔洞、预制缺口、材料层/夹杂、初始损伤和数值支撑 cell 必须在起步状态单独编码（例如 `initial_region_id`、`initial_defect_id`、`support_id`、初始化时已断 bonds）。动态 `fracture_event_id` 只能赋给运行中首次发生的不可逆状态转变。预制缺口边界不得混进新断裂面积；材料 cell/region 也不等于断口。任何候选路径不得以目标片数、选 seed、按 endpoint components 切平面或求解后加噪声生成。

断口宏观上允许平滑。表面粗糙度应在物理样本和声明测量尺度下测量；未校准前只记录解析尺度、分辨率、重建方法和可观测粗糙度统计，不能设任意 Ra 接受线、不能把后加纹理称为物理粗糙度。

## 最小接口建议

PG 新结果应采用显式版本升级，不覆写 `pgfrag.result.v1` 语义，也不把上层 `historic_R2` 写入中性 solver core。首版最少字段如下：

| 记录 | 必需证据 |
|---|---|
| 输入/离散 | CAD 与 asset hash；母体/材料坐标 frame 和单位；连续材料场版本；离散器、点集/mesh hash、point/support IDs、`δ`、`h`、`δ/h`、体积/质量权重、边界/加载、solver 版本和 dt 记录。初始 void、预制 crack、cell/region、初始断键各自分层。 |
| `fracture_bond_event` | 规范无向 `(point_i, point_j)`、两方向一致性、初始/动态来源、首次从 active→inactive 的 step/time、失败准则、事件窗口、双方 reference/current 坐标；保留原生端点 bond table 可复算核对。不能由最终状态倒推时刻。 |
| `particle_state` / `fragment` | 全部点（包括 isolate/粉末/未分类点）、reference/current 坐标、材料/支持 ID、体积/质量、速度、damage、事件时点；每个 fragment 的点集合与质量和；fragment partition 要有独立材料拓扑/几何证据，不能直接沿用 horizon graph components。不能唯一分配的点保持 `UNKNOWN` 并仍计入总量。`intact_bond_component_id` 仅留作图诊断。 |
| `fracture_surface_candidate` | `event_id`、`interface_id`、两侧 fragment IDs、共同材料坐标 surface mesh/面积、双侧法向与映射、唯一来源的 bond/point/support lineage、事件和重建版本、误差预算、ambiguity、有限分辨率、方向敏感性/收敛状态。无正面积、共享事件或唯一双侧 lineage 时 fail closed。 |
| 状态分层 | `surface_status ∈ {CANDIDATE, GEOMETRIC_VALID, UNKNOWN}`；另设 `physical_validation_status ∈ {UNVALIDATED, PENDING, VALIDATED}` 及校准/实物引用。Synthetic geometry R2 与 physical-grade 不能共用一个 PASS 位。失败/多解/不足证据写 `UNKNOWN`，`loss_mask=false`。 |

首选候选器不得直接把 `bond_id` 当 `interface_id` 或 horizon bond 当三角面。它应从 event-window 的断键空间/方向分布与点状态重建局部裂面；拟合算法、空间窗口/尺度、方向模型、正则项和三角化版本应固定并逐结果记录。然后用一个公共 rest-material surface 产生两侧 lineage；两面面积只取同一共同表面的一份面积，双侧变形后面积/gap 分开记录。每个输出三角形都要能回到来源事件与数据局部，未映射/多面候选必须保留 uncertainty 或 `UNKNOWN`，不可任意选一个。

## SynLab 消费影响

SynLab 现有 `FractureResult` / `InterfacePatch` 包含 event tree、碎片、`interface_id`、fragment pair、面积、双侧采样点/法向、gap、法向角与 ambiguity。`finalize_clean_truth()` 要求双方为新断面、unique source、母体材料内采样、面积按 fragment pair 聚合，并检验数值 gap/反向法向；当前冻结候选阈值包括 `max(0.1 mm², 1e-4 × 母体材料面积)`、gap P95 `0.02 mm`、法向反向 P95 `2°`、ambiguity `≤2%`、材料内部比例 `≥0.90`。这是一组 SynLab几何/数值规则，不能替代重离散验证或材料校准；若 PG 的数值分辨率无法满足，应报 `UNKNOWN`，不能偷偷放宽。

当前 `_classify_patch()` 的 `source_triangles` 指向几何切面来源，并拒绝空/负来源。内部动态裂面若没有母体三角面来源，禁止伪造 mother triangle IDs；SynLab 需要一个新版本的 `surface_source_kind + source_event/support IDs + rest-coordinate mapping`，或一条可审计、有效的 PG 内部面到 canonical asset/material source 的映射。必须记录 `event_id`、`interface_id`、fragment pair 和共同 `rest_material_coordinates`；CleanTruth、PhysicalTruth、VisibleLabels 各自 revision/hash。PG 输出是 TruthPack/Provenance 输入，`event_id`、fragment/interface IDs、面积、配对答案和隐藏表面不得进入部署 feature。现有 `R2/R1/R0/TINY_CONTACT/UNKNOWN`、UNKNOWN 不转负例、`loss_mask=false` 规则沿用；历史 R2、当前贴合和观测可见度仍分层保存。

## 首个小型基准与预算

**输入设计（待实现，不是当前 PG 支持的 job）：** 单一解析 3D edge-notched coupon CAD（约 `6 × 6 × 16 mm`），一个显式预制缺口只作为 `initial_defect_id`，外加载荷驱动缺口尖端后的动态扩展；固定 homogeneous isotropic 连续材料场 `E(X), ρ(X), ν(X), Gc(X)`（本轮可用声明为 `UNVALIDATED_PROTOTYPE` 的常数，不称陶瓷标定），统一全局加载/时间函数。无 `target_piece_count`。目标是表面/事件算法与离散敏感性审计，不是全器物行为或现实材料验收。

首个 screening 批次做 3 组**独立生成**的材料点离散（轴对齐规则点集、不同取向/起点重新生成的准均匀点集、独立蓝噪声/Poisson-like 点集），均取 `h≈1 mm`、`δ/h=3`、不超过约 1,000 点。它们使用相同 CAD、连续材料函数、全局边界载荷、时间区间和锁定参数 hash；`seed` 与离散 hash 分开保存。不把同一网格旋转一次当作 remeshing 结论。为守住当前 `local_smoke` 上限，screening 每例最多 50 步、单 CPU thread/chunk、120 秒；3 例总 process-time cap 为 6 分钟，超时即资源门失败，不自动粗化/重试挑图。若 50 步内没有动态断键，记录“未触发事件”，只通过输入/状态无误差审计；表面算法仍未验证，不能声称通过裂面门。

若 screening 的事件/输出链通过，再预注册有限 sensitivity matrix：3 个独立点集各自做 `h≈1 mm` 与 `h≈0.8 mm`、**固定 `δ=3 mm`** 的空间比较；在固定 point set 上各比较 native stable dt 与其一半，保持同一物理加载和 `t_end`；再于 `h≈1 mm` 加一个 `δ=2.5 mm` 对照，单独测 `δ/h` 敏感性。共至多 18 个 solver jobs（3 点集 × 3 个 mesh/horizon 设置 × 2 个 dt 档），每例 1,000 点/500 步/120 秒，aggregate cap 36 分钟。目前 job schema 不支持这些离散输入、event log、notch、或 surface output，所以这只是下一阶段可裁决预算，不代表本机已能执行。超过 cap 时另立 benchmark 资源输入，禁止静默切换 profile。方案采用固定总点数上限会使细化几何/采样准确度受限；若 h refinement 触顶，缩小 CAD 前需先记录比例，不能把几何缩小误当物理尺度一致。

**screening 通过条件：** (1) 三个输入只有离散 hash 不同，CAD/material/loading/event rules 一致；(2) 初始缺口/初始断键与新增断键分开，逐步 active→inactive transition 可从 event log 复算；(3) reciprocal pair 一致、所有 point IDs 唯一且完整、所有 point volume/mass 与结果账本闭合，isolates 不丢；(4) 只有来源闭合、同 event 双侧映射成功的 candidate 才输出共同 rest surface；共享面积须由三角面测量且 `>0`，不是 bond count/长度代理；(5) 表面重复/不连续/多解时明确 UNKNOWN，而不是用平面、cell face 或 noise 填补；(6) 每例报告 event initiation/location/time、重建面积、双侧面差、质量分配、耗能/外功和 orientation-sensitivity 指标；(7) 三例输出都标 `UNVALIDATED`。一例丢点质量、把初始化缺陷当新裂纹、缺少事件时间、surface 无 lineage、任何假 R2，均 FAIL。

screening 的 PASS 只说明数据链和 fail-closed 表面合同可审计，**不**说明裂面物理有效。R2 几何门要另行通过；物理使用还要在开跑前冻结可测误差容差，并让方向差异、`h`/`δ/h`/dt 收敛和材料/真实断口对照都满足门槛。没有已批准的 tolerance、没有独立物理 reference 或无收敛即 `PENDING`，whole-vessel run 和 RelicWeave physical-grade data use 保持 blocker。

粗糙度没有 Ra pass/fail 门槛。平滑面可通过其余物理/几何验证；高频几何不从 `h`、point fabric 或 post-noise 推出物理机制。不能通过挑 seed、冻结某个离散方向或只旋转同一网格来抹掉 orientation variance。

## 工程成本与算力

| 路线 | 这轮判断 | 迁移成本（定性） |
|---|---|---|
| PG 原生 event logging + 事件条件表面候选器 | 与当前求解器方向兼容；mechanics 源码目前无 event timeline，surface reconstruction 是新增、需偏置/收敛验证的算法，不是小字段 patch。 | **高**：event capture/结果 schema 为中等改动；表面可辨识、remesh 对照与 SynLab lineage 改造是高风险主体。 |
| Cohesive/FEM 显式 interface | 配对正面积/traction-jump 来源较直接；裂纹路径和网格、预埋界面/自适应策略仍需独立物理验证，且要新体网格、动态 solver、接触碎片与校准。 | **很高至极高**：更换求解器/输入和 truth adapter 组合，真实成本需 benchmark 再估。 |

不报百分比、工时或吞吐承诺：缺少冻结的杯体体网格、壁厚方向自由度、材料批次、事件时长和目标机器基准。Peridynamics.jl 官方项目文档描述 CPU 多线程/MPI 执行；这允许把 CPU/MPI 做为之后验证的资源方向，但本地 `0.5.4+pgfrag.1` 本例只实际跑了单 CPU chunk。GPU 当前为 `UNSUPPORTED/NOT_IMPLEMENTED`；RTX 5090 存在不等于 PG 获得 CUDA。首轮算法研究不需要承诺 CUDA。

## 主要来源

- 本地 exact source、field、hash 与审阅边界：[`source_audit.md`](../../tmp/review_20261003/implementation/fracture_surface_bridge/source_audit.md)。
- Peridynamics.jl 官方 pinned project/source: [v0.5.4](https://github.com/kaipartmann/Peridynamics.jl/tree/v0.5.4)；官方项目页列出 dynamic/quasi-static、CPU multithreading/MPI 能力，但不证明本地运行或 GPU 能力：[repository README](https://github.com/kaipartmann/Peridynamics.jl)。
- MOOSE 官方 cohesive-zone 文档：[Cohesive Zone QuasiStatic Physics System](https://mooseframework.inl.gov/syntax/Physics/SolidMechanics/CohesiveZone/index.html)（界面位于 continuum FE regions 间并通过 mesh splitting 建立；本页是准静态文档）。
- SynLab 冻结关系与数据要求：[`fracture_truth.md`](fracture_truth.md)、[`data_contract.md`](data_contract.md)、[`v144_data_requirements.md`](v144_data_requirements.md)、[`fracture_realism.md`](fracture_realism.md)、[`PGFRAG_V12_DECISIONS_20261003.md`](PGFRAG_V12_DECISIONS_20261003.md)。

