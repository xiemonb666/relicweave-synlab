# PG-Frag 裂面路线裁决建议（2026-10-04）

范围：只读代码/文档核查与有限官方来源检索；没有安装后端、运行新仿真或实现裂面导出。最终裁决归 root。本文不更改既有六道准入门槛、失败记录或冻结 R2 常量。

**建议主路线：先做成熟 extrinsic cohesive FEM 的独立小 spike，首选核验 Akantu；通过后才考虑增加 PG 后端。保留、冻结现有 PD 基线，不先全面迁移。** 选择依据是“求解过程中显式存在双侧界面，适合构造性保存 R2 lineage”，不是 PD runner 少写了日志，也不是 cohesive 天然物理正确或无网格偏差。

**两条路线的实质差别**

| 路线 | 可直接利用的性质 | 尚须解决的关键风险 |
|---|---|---|
| PD 事件/损伤局部化 + 裂面提取 | 现有 native 数值基线；裂纹不被要求逐片落在 bulk 单元面上；可容纳分叉 | 有限物质点及断键只是约束，通常不能唯一确定具有面积的三维裂面。完整断键时间序列也不消除此不可辨识性。必须另选、验证一个共同 rest-interface 表示、拓扑/分叉规则及重建误差；对两个碎片分别拟合再最近匹配不足以成为真值。点分布、horizon、求积、表面修正仍会产生方向偏差。 |
| extrinsic cohesive FEM | 由应力准则插入、有牵引—张开本构的零厚度界面；双侧节点和界面连通性属于数值模型，可保存共同祖先面 | 裂纹可选路径受 bulk 面限制；网格引入方向偏差和额外路径面积/韧度。必须检查独立重网格下的响应、能量、面积和路径收敛。材料还需要强度、混合模态等参数，单有 E/Gc 不够。 |

工程推断：本项目首先需要可靠的物理事件到成对裂面的链路，第二条路线减少了一项独立的三维逆重建问题。它仍可能因方向偏差而被否决。沿单元面的**受本构控制、经收敛检验的失效**可以作为候选；不能把任意 tet 共有面或末态组件边界直接命名为真实裂面。PD 与 cohesive 的子网格细节均不可凭视觉美化补齐。

**成熟后端核验及边界**

- Akantu 官方 [3D scalability 示例](https://akantu.readthedocs.io/en/latest/examples.html#scalability-test-3d) 的源码明确使用 `spatial_dimension=3`、`_is_extrinsic=true`，随后初始化显式求解器，在步循环内检查 cohesive 应力并执行动态步。因此 3D 动态插入有官方代码依据。示例有开关，展示的参数中 `cohesive_insertion=false`；验证必须启用并检查实际插入数，不能把示例运行结束当作插入成功。**不运行该页面的百万单元网格。**
- 官方 [元素/连通性说明](https://akantu.readthedocs.io/en/v5.0.6/manual/basic_types.html#cohesive-elements) 列出三维六节点三角形界面和连通性访问。由此可确定显式双侧拓扑可表达；**跨插入、重编号、碎片化的永久 parent-facet/material-node IDs 与本项目所需 lineage 导出尚未证实**，属于首个 spike 必须现场证明的接口条件，不能声称开箱即用。
- 官方 [contact 文档](https://akantu.gitlab.io/akantu/manual/contactmechanicsmodel.html) 提供 cohesive surface selector 与 `CouplerSolidCohesiveContact`，支持选择新 cohesive 面进入接触。这里只核实文档接口；同版本 3D 碎片自接触、交叉碎片接触、穿透与守恒仍须小例实测。不能把 cohesive 的局部压缩惩罚自动当作完整碎片碰撞。
- [官方 cohesive 模型说明](https://akantu.readthedocs.io/en/stable/manual/solidmechanicsmodel.html#insertion-of-cohesive-elements) 给出动态插入判据、损耗/可逆/接触能量访问。公开的功能不等于本机可用：Windows 安装、ABI、Python 暴露范围、固定版本运行均为 **UNKNOWN / NOT_RUN**；GPU 与 RTX 5090 吞吐没有核验，不承诺。不同版本网页不是已经验证的单一运行配置。
- 已读 [Rimoli & Rojas 原始论文摘要](https://arxiv.org/abs/1302.1161)：其区分 mesh-induced anisotropy 与 mesh-induced toughness，支持不能仅靠随机化网格宣称无偏。此处只使用摘要结论，没有将二维网格策略外推为三维杯体收敛证明。

**首个可执行最小 spike（由 Luna 独立实现，生产代码不动）**

1. 固定后端版本/构建哈希，先做能力 preflight：3D、实际动态插入、双侧连接及原始节点映射可读。首件为 **2×2×4 mm 小块，中央 4 mm² 界面，≤200 bulk tets**，冻结输入及 toy 材料状态。只在中央面允许插入，这是有解析面积的接口/能量测试，明确不证明自由裂纹路径。
2. 跑零载与 mode-I 开裂；开裂使用同一网格、同一物理载荷/终止时间的 dt 与 dt/2。每例单进程、≤10,000 步、≤300 s；达到限制则记 NOT_REACHED，不自动加大计算。记录真实 preflight、非零步、插入/完全脱粘时间以及逐步反力、外功、动能、bulk/界面储能和损耗。完全分离的线性 mode-I 界面应耗散 `Gc × 4e-6 m²`；建议本 spike 的能量误差与时间加密变化各 ≤1%，这是待 root 冻结的**新小例门槛**，不是修改现有 R2 判据。
3. 从求解时的同一个界面取出双侧 rest 三角形，保存原始面 ID、复制节点祖先、两侧 bulk IDs、事件时间及最终 fragment IDs。由共用重心坐标生成对应；证明面面积各为 4 mm²，法向相反，材料质量全部保留。未完全脱粘、裂纹尚未分隔出不同碎片、外表、初始缺口和只接触的面不得冒充新 R2。做一个分离后再接触的小步检查，确认接触选择器实际纳入新面并导出穿透/动量/能量。
4. 只有上述接口闭环通过，才用**已验几何的 canonical 杯壁小 ROI**（采用 wall-resolution 任务同一 CAD crop）开展自由路径 spike：保留真实曲率/4 mm 材料域、人工截断边界明确标注，预缺口与载荷固定在 rest 坐标，允许区域内部自由插入。首次 ≤10,000 bulk tets；不做整杯。先 mode-I，再一个固定斜向/混合模态例，避免单一对称直裂纹掩盖方向偏差。

第一小块即使全部通过，也仅证明 NativeRun、界面本构/导出与几何 R2 小合同；不构成陶瓷校准、自然粗糙断口或真实器物 fracture-grade 验收。

**切换规则：只允许一次明确的受阻后切换**

如果上述独立 cohesive 能力 spike 因固定运行环境无法执行，或不能保全插入时双侧祖先映射而 **BLOCKED**，当轮保存完整证据，停止同路径安装/包装器反复修补，执行唯一 fallback：**在冻结的 native PD 上做有预算的事件记录与共同裂面重建 spike**。它只研究两个小例（单裂纹、分叉/相交裂纹），要求提取器对分辨率、点布置和允许的提取参数变化保持事件拓扑及面积/位置误差可控。原始断键到多个同样合理裂面的歧义必须显式输出；不能为了过 R2 选一个面再把选择当物理真值。

如果 cohesive 已运行但自由路径的独立重网格比较不收敛，这是 **NumericPhysical FAIL**，不是环境受阻；最多一轮有依据的网格/过程区分辨率修正后，仍不满足预先门槛则同样切到上述 fallback 评估。PD fallback 未证明锐裂面的可辨识误差及下述门槛前保持 UNKNOWN，不产出物理 R2 训练样本；若它也失败，报告该表示尚不合格，交 root 另作表示裁决，不启动第三条自研求解器或无休止补丁。

**现有 native 0.5.4 的不足与最少新增元数据**

这些项应补，但**补齐日志不能使 PD 裂面唯一化**：

- [`run_fixture.jl`](../../../pgfrag/src/pgfrag/resources/julia/run_fixture.jl) 第 69 行构造默认 BB/OSB；第 126 行起在求解结束后枚举断键；末尾明确 energy ledger/surface mapping 为 UNKNOWN。[`backend.py`](../../../pgfrag/src/pgfrag/backend.py) 第 95 行起也准确声明无裂面、无事件时间。冻结这些已验证输出及 SHA，新增版本化能力，勿改写旧通过范围。
- [`ordinary_state_based.jl`](../../../pgfrag/src/pgfrag/resources/julia/vendor/Peridynamics.jl/src/physics/ordinary_state_based.jl) 第 94 行默认 `NoCorrection`；第 152 行断键只将布尔值设为 false。仓库确有 `EnergySurfaceCorrection`，但当前 runner 未选择它，且开启它不自动证明薄壁准确。[`bond_system.jl`](../../../pgfrag/src/pgfrag/resources/julia/vendor/Peridynamics.jl/src/discretization/bond_system.jl) 以距离 horizon 建邻居；现有过滤是预定义裂纹，不含 canonical CAD 的空腔可见性判定。geometry clipping 后仍须明确、检验跨空腔的相互作用规则。
- 最小静态元数据：输入/CAD/代码哈希、单位、rest 点与真实积分支撑/体积、密度与全部点质量、初始邻居、kernel/δ/权重/修正、边界和初始缺口、连续 rest-material field 的定义/种子/哈希。重网格时重采样同一空间场，不能给每个新单元重新抽随机材料。
- 最小事件元数据：稳定无向 bond ID、初始预断与动态破坏原因、首次 active→failed 的 step/time（含时间定位精度）、两端全局 ID、参考/当前方向与长度、触发 stretch/阈值/材料参数、事件前后可重放状态。cohesive 对应保存 interface ID、parent facet、双侧节点祖先、插入与完全脱粘时间、积分点 traction/opening/damage/dissipation；最终碎片归属可由完整 bulk 拓扑另算，必须保留 ancestry。
- 最小逐步账本：全部质量/孤立点、反力外功、动能、弹性与界面储能、不可逆断裂损耗、接触/摩擦/阻尼能、动量及残差。OSB 是状态耦合能量，不能直接按独立 BB 弹簧公式求“每根断键耗能”。[`fracture.jl`](../../../pgfrag/src/pgfrag/resources/julia/vendor/Peridynamics.jl/src/physics/fracture.jl) 第 116 行给出依赖 K、δ 的 Gc→critical-stretch 关系；需要用实际 kernel/修正/薄壁几何检验有效断裂功，不能把输入 Gc 当作已经实测满足。

**三类验收各自成立，六道发布门保持分离**

1. **数值物理：** Geometry/NativeRun 先通过。CZM 固定本构/过程区尺度做 h 收敛，报告过程区内实际分辨率；PD 固定 δ 加密 h，分别报告 δ/h、δ/实测壁厚、自由表面修正及后续 δ 敏感性。两者均在固定网格做 dt 收敛。方向测试固定 CAD、载荷和 rest-material field，独立生成至少三个取向/seed 的网格，再比较加密结果；旋转同一网格连同载荷只算 covariance。比较力—位移、起裂时间/峰值、断裂耗能、裂面面积与法向分布、rest 路径/分叉拓扑、碎片质量分布和总质量；单看 fragment count 或图像不够。允许统计波动的动态分叉需预先声明可比较的统计量。阈值预先冻结；至少记录粗→细差值和方向间差值，不能只报“看起来一致”。
2. **材料校准：** toy 参数永久标记 UNVALIDATED。真实陶瓷需有来源与不确定度的 E、ν、ρ、强度、Gc/混合模态及相关率效应/空间相关长度，并用独立实验载荷—位移、断裂功和形貌验证。为了让裂纹发生而改材料参数不算数值收敛。粗糙度只有解析了可信材料非均匀性并经实物形貌验证后，才可称物理预测；求解后加噪声、平滑、细分或复制两侧同噪声只改变外观。
3. **几何 R2/训练真值：** 事件唯一；真正新断面；两侧属于不同后继片；共用 rest 界面与可靠 ancestry；按 fragment 对汇总正面积，采用 [`fracture_truth.md`](fracture_truth.md) 原门槛：`area ≥ max(0.1 mm², 1e-4 × mother material area)`、`gap_p95 ≤0.02 mm`、反向法线误差 `p95≤2°`、歧义面积率 ≤0.02、材料内采样率 ≥0.90。数据文档另有逐 patch/逐 pair 的历史不一致记录，bridge 必须调用 root 确认的当前合同，不悄悄选择较宽规则。部分损伤界面不能以整个 facet 面积充当断裂面积；无法定位则 UNKNOWN。共同构造的两侧可保证配对，但这只是数值模型内的几何真值，不能反过来证明该面具有真实物理正确性。余下接触、退化、泄漏与部署门仍独立 fail closed。

canonical H56/D41/wall4 的旧 h8/h6 tets 已因 CAD 体积误差约 2.03%/1.61% 及内部探针 OUT 被拒；不用它们为任何求解器背书。[`cad_volume_spike.py`](../../../pgfrag/experiments/cad_volume_spike.py) 与 [`cad_clipped_cells_spike.py`](../../../pgfrag/experiments/cad_clipped_cells_spike.py) 都只构造静态体积分候选。精确 clipped cells 可改善材料域/质量求积，既不定义物理裂纹面，也不自动满足 wall/horizon 分辨率。

以上建议遵循 [`engineering_policy.md`](engineering_policy.md) 的构造性优先、先 spike 后迁移、保留基线和不放宽判据；现状以 [`CONTINUATION_20261003.md`](CONTINUATION_20261003.md) 为准。本次唯一新增文件为此建议书，其余保持只读。
