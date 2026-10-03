# 当前状态补充（截至 2026-10-04）

本节优先于下方 2026-10-03 历史快照。详见 [2026-10-04 接续矩阵](CONTINUATION_20261004.md) 与 [证据索引](evidence/20261004/index.md)。

A12 仍服务于 RelicWeave synthetic / observation / degradation / retrieval diagnostics；主仓 A3/A4 集成仍待完成。本轮仅在本机做小规模验证，未运行 RTX5090 批量合成或训练。Astra 单次顾问已结束；Akantu 5.0.7.post1 extrinsic cohesive tiny capability spike 已完成但未晋级为物理结果，PD baseline 冻结，不做全面迁移。

已接受的窄范围：appearance 46 PASS、100k 排序中位数 81.37 ms（O(N log N)，toy only）；deploy 85 PASS（schema/runtime only，旧 5 GB 包未迁移）；native contact 1/240/480/240 steps 成功，momentum residual 3.42e-24、nominal envelope overlap 0.5904 mm，energy history UNKNOWN；C2 BREP 单次持久化与 half-cut 局部检查通过，单次 remesh 602 samples 最大偏差 0.0400846 mm，但 production STEP 仍 FAIL / NOT_PROMOTED；ROI h1 因 292 个 inside 样本中 1 个 OUT（0.000407 mm）FAIL，h0.5 以 1506 tets 通过有限几何 QA、不是 physics；clipped COM OUT 在 58/294 处中止，整分区体积准确度未评估。9 项 broader routing/narrowband FAIL 仍保留；P02/P03 actual 输出各有 6 boundary edges、not watertight。QA/label 30 PASS 与 damage legality/face provenance 16 PASS 为最终哈希下的窄测试；appearance 46 PASS 重跑仍只计 46 项。Measurement.valid 不等于 physical QA 有效。

Akantu 5.0.7.post1 cohesive 小型能力验证已运行：zero 1707 steps 为 0 interface insertion / 0 drift；mode-I 1707 与 half-dt 3414 steps，两组加载均有 8 个 native interfaces。原始耗散 −5.572968137645039e-5 J 与 −9.726359554870569e-6 J 均未达到 GcA=3.04e-5 J，coarse 绝对值归一差 82.55%，不晋级为物理结果；full-debond、damage、native-energy 语义仍 UNKNOWN。runner 查询 `getEnergy('contact')`，reviewed native API 只确认 `cohesive contact` key；未知 key 的返回语义未验证，故该能量通道和派生 ledger 均 UNKNOWN。物理 contact 仍为 NOT_RUN。基准仅固定中央界面 API，无自由裂纹或真实器物；界面插入不自动代表断裂事件。

**Native-run 快照纪律：** 每次运行前，将准确执行脚本、输入和 manifest 保存为不可覆盖快照，并记录每个文件的 byte count 与 SHA-256；运行后诊断、标签或解释性修正另存，不覆盖原始脚本、输入、manifest 或 receipt。只记录 hash 而未保存对应 source bytes，不足以精确复现。Akantu 本轮执行源码由 current `run_contract` 保留：29,542 B、SHA-256 前缀 `67dd1eb98…`，与冻结 canonical manifest 的 `source_sha256` 及三份原始 status/receipt 哈希一致；manifest SHA-256 前缀 `21b563…`。此前 24,567 B 是较早未冻结代码尺寸，不是本轮执行脚本。此为执行源保真与哈希闭合，不表示全实验精确复现已验收；未声明另机重放或完整环境封装。

## 历史快照（截至 2026-10-03 晚间；当前状态以本文件顶部 2026-10-04 补充为准）

当前追踪见 [CONTINUATION_20261003.md](CONTINUATION_20261003.md)，小型审阅证据与 SHA 见 [evidence/20261003/index.md](evidence/20261003/index.md)。历史规则与失败记录不因当前摘要而覆盖。

VF BRep 语义原型窄验收：26 faces、38,486 triangles、UNKNOWN=0、handle-root 误标 0/0、canonical3 geometry/lineage bitwise equal、whole/lower-root depth parity 0 mismatch；16 tests PASS，602 个 trimmed-face 样本最大偏差 0.0196136578 mm。该误差为有限样本，不能外推全局壁厚或真实器型。smooth-CAD 3D shell candidate FAIL，第二 2D 表示与 CAD-native clippedcells candidate PENDING；h8/h6 tetra-volume error 均超过 1% 门槛。

A12 adapter/camera 32 PASS。depth/noise 71 与 frozen parity 2 是此前归档日志，本轮未逐字重放 71 argv。private continuous sampler 的 40-PASS 独立 SS=1/2 + nonzero-distortion target 和 24-PASS default regression（15 projective + 7 noise + 2 flat-frozen）已由 root 在此窄范围接受；legacy appearance 29 PASS / 4 FAIL 独立保留。root 接受的 synthetic degradation audit 仍不是修复通过：coverage 反向、P05/P06 payload channel 丢失、P02 QA false PASS 的修复分别已分配；不得放宽 QA 或将 audit status 替代修复验收。

实际旧 deploy 包 INVALID_DEPLOY_TRUTH_LEAK / PENDING，等待 strict-v2。native-contact attempt03 因 Julia load syntax error 在 preflight 前停止；新的 minimal-native endpoint 尚未通过三例 contact 检查。现实性文件 [REALISM_ACCEPTANCE_20261003.md](REALISM_ACCEPTANCE_20261003.md) 将几何/物理/材料校准/实物形貌分层：预览仅供展示，E/Gc 候选数值保留，实际 calibration 为 UNKNOWN / UNVALIDATED。A12 仍不替换主 A3/A4 retrieval/rejection/recapture/STOP。
## 物理级断裂与 RelicWeave 数据准入（用户约束 / 更新于 2026-10-04）

用户已看过 h8 实际输出并判定其断裂质量不足以称为 physical-grade/high-quality fracture。几何精度、tetra volume accuracy、watertight 或一张裂纹图均不能代替物理断裂验收。当前 clippedcells h8 只属于 native geometry accuracy，状态为 NOT_PHYSICAL_READY。

验收必须分开记录 Geometry、NativeRun、NumericPhysical、CalibratedMaterial、CrackSurface、RelicWeaveData 六道门槛；一个阶段 PASS 不自动传播到后续阶段：

1. **Geometry：** 声明单位、边界误差、拓扑与实测厚度范围。区分有限采样和全局证明；不能把解析/轮廓壁厚说成全局最小壁厚。
2. **NativeRun：** 要有真实 preflight 与非零 solver steps、版本化输入和原始结果。Julia load syntax error、未执行 preflight 的旧 wrapper 或 zero-step 调用都不是 native run。minimal-native-contact 的三例 contact/control 均已完成并通过窄数值检查，但仅为 toy；Akantu cohesive 也只完成固定中央界面 API 基准，均不构成校准器物的物理验收。Contact energy history UNKNOWN；Akantu 执行脚本及 manifest 的本轮 source hash 与 status 闭合并保留于 `run_contract`。
3. **NumericPhysical：** 报告 element quality/orientation、PD δ/h 与 horizon×wall 关系及 surface correction；做 fixed-δ spatial convergence 与 fixed-mesh dt temporal convergence。Akantu 两加载原始耗散未达到 GcA 目标且相差 82.55%；full-debond、damage、native-energy 语义 UNKNOWN。相同物理 case 应在独立 remesh orientation 和 mesh seed 下比较，固定 rest-material field，并比较 crack energy、response、mass distribution。只旋转原网格只能证明 covariance，不能证明 remesh bias 已控制。不得从 max-edge/t 推断精确 through-wall layers。
4. **CalibratedMaterial：** E/Gc、密度及相关材料属性须有来源、测量方法、不确定度与状态。保留候选原值，但实际 E/Gc/material calibration 目前 UNKNOWN / UNVALIDATED。
5. **CrackSurface：** 需要由裂纹事件生成且具有 positive-area 的配对裂面与 lineage。当前固定界面插入不等同于断裂事件；不得固定 fractureN，也不得把未经验证的 tet facets 当作 physical truth。cohesive/tet-facet 路径经本构与收敛验证后可列为 candidate；已校准的形貌 surrogate 必须单独标注，不能替代断裂 physics。
6. **RelicWeaveData：** 覆盖 all point mass 和 isolated points；报告 contact penetration、momentum 与 energy。annotation 必须来自受验事件真值；truth leakage、错误标签和 QA failure 必须 fail closed，不能将错误 manifest flag 或 summary PASS 当成无泄漏证据。

luna_wall_resolution 负责审计 old h8/h6 element quality 并检查 actual ROI static h=1 mm / h=0.5 mm。h1 trial FAIL（292 tets、292 个 centroid IN，但 292 个有限内部样本有 1 个 OUT，距 CAD 0.000407289 mm）；h0.5 通过有限几何 QA（1,506 tets、512 个有限样本全 IN），两者均不构成 physics PASS。真实裂纹 mesh-direction bias 仍未量化，尚无真实裂纹跨网格对照。现有 whole-mesh 只读质量审计记录 h8 有 9 个 tet 的最小二面角 <10°、1 个 <5°、max R/rmax=113.1；h6 有 10 个 <10°、max R/rmax=112.6。h8/h6 体积候选分别有 21/512 与 12/512 个 finite interior probes OUT；CAD-reference signed volume delta 分别约 −2.0343% 与 −1.6142%。这些 tet 是 quadrature candidates，不是 PG solver input；h8 权重和匹配自身 mesh volume 不代表 CAD 体积/质量正确。max-edge 与名义 t 不能代替壁内分辨率。当前 clippedcells h8 仍仅有几何精度范围。全量只读质量审计的小型副本和 SHA 见 evidence index。物理准入矩阵与负责项见 [CONTINUATION_20261003.md](CONTINUATION_20261003.md)。
## 早期状态快照（保留为历史记录，当前状态以上述接续摘要为准）

VF 首件的 canonical STEP 面分类、连续 rest-coordinate 绘制和 BRep face 语义映射已完成狭义原型验收；器身 C0 折角、把手根部几何过渡、材料标定和历史样式仍为 `PENDING`。这不代表 A12 生产 appearance 链路已闭环：当前有 4 项 appearance 测试失败，GPU 路径未实现，完整物理断裂→遗存退化→低成本观测链尚未完成。A12 adapter/camera32 检查为 `PASS`，但近似 per-face 字段仍漏掉窄红带。PG owner 报告 physics/time SHA 为 20/20，OSB/BB 独立 API fixture 已通过真实 CLI；最终 wheel 仍由 PG owner 检查。jobs 修复测试为 19 项通过，仍在审查中。

细节、图像和状态边界见 [2026-10-03 implementation ledger](INFRA_IMPLEMENTATION_20261003.md)；PG 接口裁决见 [v12 decisions](PGFRAG_V12_DECISIONS_20261003.md)。以下既有政策条文和历史记录保持原样。

## 接续状态更正（2026-10-03）

当前验收和剩余项见 [CONTINUATION_20261003.md](CONTINUATION_20261003.md)，小型、可复核证据见 [evidence/20261003/index.md](evidence/20261003/index.md)。连续绘制的 4-band preview 与独立像素中心 oracle 已获 root 窄范围接受：新 SS=1/2、nonzero distortion 目标 40 PASS；private default regression 已完成并获 root 窄范围接受，24 PASS（15 projective + 7 noise + 2 flat-frozen），这不修复 legacy appearance 29/4 FAIL。旧 38-PASS 被拒是原始 K 上的 half-pixel 射线偏移（未抵消 frame 已有 +0.5），不是复用 renderer。

当前 smooth-CAD 3D shell candidate 的 sampled deviation 为 0.118432 mm，超过 0.10 mm 门槛，且 native halfsection 无效/为空；第二个 2D 表示仍 PENDING。实际旧 deploy package 已确认含 lineage/mother/fragment/historical_N_G 字段及 raw lineage/M-style index keys，状态为 INVALID_DEPLOY_TRUTH_LEAK / PENDING，等待 strict-v2 及 root 验收。现实校准与实物形貌结论见 [REALISM_ACCEPTANCE_20261003.md](REALISM_ACCEPTANCE_20261003.md)：视觉仅供展示，候选 E/Gc 数值保留而实际 calibration 为 UNKNOWN / UNVALIDATED。
# A12 工程政策：算法选型与"停止死磕"规则

**状态**：生效（用户裁决，2026-10-02）。
**适用范围**：本仓库所有子系统（几何/断裂、观测与渲染、退化、关系与检索、训练、存储与导出、QA）。
**与其它文档的关系**：`open_items.md`（未完成项清单）· `decision_record.md`（数据/口径裁决）· `precision_audit.md`（实测精度）· `fracture_implicit.md`（本政策第一次应用）。

---

## 一、政策条文（用户原话的工程化）

> **之后遇到同类型的问题就用业界最稳定最先进的算法，不要死磕无用算法。**

落成五条可执行规则：

| 规则 | 内容 | 判定方式 |
|---|---|---|
| **R1 三次补丁规则** | 同一根因**第 3 次**打补丁仍不收敛 → **立即停手**，转入"表示/算法复审"，不得继续在细节上修补 | 检查该模块的修复历史与失败测试名是否重复 |
| **R2 构造性优先** | 优先选择让关键性质**构造性成立**的算法，而不是"生成后再验证/修补"的方案 | 关键性质清单：水密、流形、共轭、守恒、无自交、可复现 |
| **R3 先尖刀后落地** | 换算法必须先做**带验收指标的 spike**（小规模、真实数据、真实门限），用**实测对比**决定是否采纳；**禁止**"先重构再看效果" | spike 必须产出 before/after 数字表 |
| **R4 保留干净基线** | 已被证明**精确且高效**的路径**不替换**（例：`plane_shared_cut`、Blender Cycles 数值、射线投射 mm/px） | 替换前必须证明新路径在精度/速度上不劣 |
| **R5 不放宽判据** | 换算法**不得**以放宽审计/泄漏/QA/门限为代价；旧产物按"修复前一代"标注而非重写判据 | 任何门限变更需版本化 + 记录理由 |

**同时废除**（反面清单）：不得以"再调一个参数就好"为由，在同一脆弱表示上继续加条件分支；不得用**上采样/后处理/外观纹理**去**伪装**几何或统计上缺失的性质。

---

## 二、各领域的"业界稳定/先进"默认选择（复审时的首选库表）

| 领域 | 不再死磕的脆弱路径 | 首选稳健路径 |
|---|---|---|
| **实体几何 / 断裂面** | 四叉树细化 + 精确 CSG + **共形三角化**（T 型接头） | **隐式场（SDF）**：窄带 marching cubes / **dual contouring**；位移高度场薄片 + 边界缝合；`manifold3d`（已用）做布尔；`gmsh` 做约束三角化 |
| **网格修复 / 保水密** | 手工焊接顶点、容差拼缝 | `manifold3d` 的 repair、MeshFix/Manifold 类工具；**先在隐式域合并再提取** |
| **参数化 / 展 UV** | 自研 chart 光栅往返 | `xatlas`/`libigl`（angle-based flattening）；或**直接在 3D 求值**（triplanar/解析 UV） |
| **体积表示 / 窄带操作** | 全局体素 level-set（漂移 0.354 mm） | **窄带 SDF**（`degrade/physical_narrowband` 已证：0.354 → 0.000348 mm）；OpenVDB 类稀疏体素 |
| **MVS / 立体重建** | pycolmap（无 CUDA、无 `patch_match_stereo`） | **OpenMVS / COLMAP-CUDA**；合成数据**直接从网格投射深度**（已在用） |
| **光栅化** | 自研 z 缓冲（掠射面误差 35.6 mm） | 修**透视正确插值**，或统一**射线投射**；需要真实相机模型时优先 Blender/Cycles |
| **渲染吞吐** | 每视图一个进程（启动占 22.2%） | **常驻进程批量渲多视图** + 按 pass 分派设备；必要时 Cycles standalone / 头显式 GPU 分派 |
| **程序化纹理** | 高频噪声直接采样（摩尔纹） | **带限/足迹感知**噪声（frequency-limited noise、triplanar + mipmap） |
| **数据集 / 训练内存** | 整包一次性物化（19.63 GiB/backward） | **流式/分片数据集** + 梯度累加（`chunked_smoke` 已证 4.69 GiB） |
| **协议一致性** | 同一协议**多份并行实现**（`neighbours()` 语义分歧） | **单一真源 + 一致性测试**（所有实现跑同一套 contract test） |
| **语义/世代标记** | 靠约定散落各处 | **提交边界强制写入**（`_stamp_data_semantics` 模式）+ 门禁分母可查 |

---

## 三、同类结构性问题登记表（架构债，按影响排序）

| # | 位置 | 脆弱路径 | 稳健替代 | 实测证据 | 批次 |
|---|---|---|---|---|---|
| 1 | 断裂几何 | 四叉树 + 精确 CSG + 共形三角化 | **隐式场/SDF（位移薄片或窄带 MC）** | T 型接头 **14 154** 单用边、`CUTTER_NOT_CLOSED`、预算 432 k、误差 0.01056>0.01 | **进行中** |
| 2 | 器型几何（母体） | 程序化网格 + **互相穿透的多个闭合壳**做 CSG | 隐式/实体建模后提取，或**显式构造流形** | V10 多壳守恒失败（改逐壳切割绕过）；`wall_thickness` 对采样面数敏感（**27.2 vs 11.7 mm**） | 第三批 |
| 3 | 花纹落到 3D | 三维↔二维**栅格往返** | **直接在 3D 求值**（解析 UV / triplanar） | `x_period_mm=None` 崩溃、`(685,984)↔(685,985)` 取整、接缝靠补丁 | 第三批 |
| 4 | 退化轴声明 vs 路由 | 声明窄带却走**全局体素** | 按声明路由（P03 已修） | P03 漂移 **0.354 → 0.000348 mm**、watertight False/43 边 → **True/0 边**；**P02/P04 未逐轴复测** | **第二批** |
| 5 | 关系池协议 | **四份并行实现**语义分歧 | 单一协议 + **一致性测试** | `neighbours()` 错位致 **55/55 query 被拒**、`rank` 从未启动（已修一处） | **第二批** |
| 6 | 语义标记（世代） | 散落约定 | 提交边界强制写入 | 三代 `mask_semantics` 曾全 None；`visible_labels` 0/9 | **第二批** |
| 7 | Blender 吞吐 | 每视图一进程（启动 22.2%） | 常驻进程批量渲 + 分派设备 | 端到端最好 2.14×、等负载 1.02×；单 render CUDA 2.9× | 第三批 |
| 8 | 软件光栅器 | z 缓冲**非透视正确** | 修透视插值或统一射线投射 | 掠射面深度差 **35.6 mm**（已绕开未修） | 第三批 |
| 9 | 训练内存 | 整包物化 | 流式/分片数据集 | **19.63 GiB** → 分块 **4.69 GiB**（1/4.2） | 第三批 |
| 10 | MVS 路线 | 依赖不可用工具链 | 带 CUDA 的 colmap/OpenMVS，或直接网格投射 | `MVS_NOT_AVAILABLE` 反复 | 第三批 |
| 11 | LOD 依赖 | `fast_simplification` 反复装卸 | 固定依赖或自研简化 | L1/L2 未物化 | 低危 |
| 12 | 标定/尺度字段 | 5 个版本字段 0 命中、候选值 | 显式标定产物贯穿全链 | `f` 三支并存（3.125/3.6/2.77） | 需硬件 |

---

## 四、例外（明确**不**替换）

| 对象 | 理由 |
|---|---|
| `plane_shared_cut` | 审计最干净（gap P95 **1.19e-07 mm**、共轭 **9.0e-09 mm**、体积差 4.8e-10）、**逐位可回归**、比 voronoi **快 4–4.5×** → 作为精确基线与快速批产长期保留 |
| Blender Cycles 数值 | 与 CPU 分类通道**逐位相同**、depth 仅 1/356 968 像素 >0.001 mm → 数值可信；问题只在**进程架构**（见 #7） |
| numpy 量化/哈希链路 | 可复现性与逐位回归的基础 |
| `_archive_pre_fix` 归档策略 | 旧代数据以"移动归档 + 标注"处理，不重写判据 |

---

## 五、执行方式（写进后续所有任务书）

每份任务书必须包含：
1. **根因编号**与"这是第几次补丁"（触发 R1 即停）；
2. **关键性质清单**及"是否构造性成立"的判断（R2）；
3. **spike 的 before/after 数字表**要求（R3）；
4. **基线不可劣化**的证明要求（R4）；
5. **不得放宽判据**的明文（R5）。

**复审触发条件**（任一满足即启动"表示/算法复审"）：
- 同一根因第 3 次补丁仍不收敛；
- 关键性质需要"生成后再验证/修补"才能成立；
- 出现"为了让结果好看而放宽/绕过门限"的倾向；
- 单元/内存/时间预算随精度提升呈**超线性爆炸**（如 432 k 单元仍不达标）。

**记录纪律**：复审结论必须写入本文件第三节（新增条目或更新批次），并同步 `open_items.md`。
