# PG-Frag / VesselForge 指南升级难度与数据差距审计

审计时间：2026-10-03 10:27 +08:00。范围是只读审阅 A12 的数据/生成/物理碎裂/观测/关系/训练接口，并映射到 `PGFrag_VesselForge_Guide_v11.docx`。指南提取文件为 `guide_extracted.txt`，源文件 SHA-256：`1eb926d3be9d081f236db2b0c47f573a9e283e51295e9bb2969b5c0d32224d19`。本报告没有改生产代码、配置、store、release 或历史报告；没有训练、安装依赖或批量生成数据。

## 结论

这项升级难度高，且不能按“给当前切割器换一个 backend 名”估算。A12 已有可复用的程序化器型/纹样、网格切割、资产存储、溯源、观测、关系标签与数据导出基础；但现行断裂链的主体仍是几何分区/切割和经验片数律，不是指南定义的动态损伤、裂纹传播、碎片接触/运动与物理断面重建。指南 v0.1 本身已要求一个 PD backend、基本碰撞与碎片提取（[P0525–P0528]），因此不能把“先用未知材料参数跑一个看起来像的切割”称作 v0.1。

较可行的路径是把现有 A12 代码作为 VesselForge/PG-Frag 的迁移与适配参考，另行建立不依赖 A12 内部实现的独立 Asset/Job/Result 契约、求解器 adapter 和验证基准。运行时 RelicWeave 应是 VesselForge/PG-Frag 结果的消费者，而不是独立核心的上游依赖。指南强调可替换求解器、格式中立、可复现与溯源优先（[P0030–P0037]），并要求复用现成数值/网格/接触能力、做许可证审查和基准后才自研（[P0039–P0063]）。目前尚无足够证据估算具体开发工时、GPU 小时或物理验收通过率。

## 现有数据基线

只读扫描脚本与原始结果分别为 `a12_current_evidence.py`、`a12_current_evidence.json`。脚本以 SQLite `mode=ro` 读取 store 索引，以 NPZ 成员头读取数组形状和 dtype；没有解压图像/深度数组，没有写入 store。ancestry 是 asset ID 列表；本次已通过完整索引建立 asset ID→role 映射，未知 ID 单列，不把空结果解释成“无依赖”。

| 观察项 | 当前 census | 含义/限制 |
|---|---:|---|
| store 资产 | 463 | 14 个 role；这是索引快照，不等同一批已验收物理试验。 |
| store 递归文件长度合计 | 14,390,645,786 bytes（约 14.39 GB） | 是文件逻辑长度合计，不是 NTFS 实际分配空间，也不能直接外推新仿真成本。 |
| obs_result NPZ | 68 个，压缩文件字节约 12.80 GB | 头部显示每个 12 views；图像/深度 payload 未加载。 |
| feature_bundle | 59 个，约 1.236 GB | 59 个有结构化点云/法向/曲率/密度/token 字段；47 个还保留旧 `points/normals/quality` 键。 |
| 视图尺寸元数据 | 47 个 `[512,384]`，12 个 `[1024,768]` | 表示现有流水线有分辨率版本差异；在明确每个字段的坐标/采样契约前，不合并尺寸、不据此判为错误。 |
| truth/关系资产 | clean_truth 40、physical_truth 11、visible_labels 9、label_bundle 64 | 只有 15 个 clean_truth 含 `corr_*`/`iface_*` 数组，40 个有 `iface_id`；11 个 physical_truth 有 `corr_*`；9 个 visible_labels 只有投影/可见计数。它们来自 A12 的静态切割/退化标签，不证明动态裂纹历史已建模。 |
| 物理层资产 | physical_component/result/truth 各 11 | 物化量有限，不是 solver 轨迹或经实验校准的动态断裂库。 |
| 材料/器型 | material_profile 18、mother_mesh 18 | 18 个材料 profile 在代码中按 `mechanics_status=UNKNOWN` 记录；现有 profile 是程序化参数资料，不能当成测量过的本构参数。 |
| runs | 8 个，全部 `PENDING` | 不应把资产数量或 QA 状态读成已完成科学验收。 |
| QA 状态 | feature_bundle 59 PASS；physical_result 8 PASS/3 FAIL；visible_labels 5 PASS/4 FAIL；pattern_channels、pattern_recipe、physical_component 各 11–18 项 PENDING | QA_PASS 是既有检查器结果，不是与真实断裂实验吻合的证据。 |

本次解析得到的 ancestry 角色边包括：`clean_truth→fragment_mesh(54), mother_mesh(15)`、`fragment_mesh→label_bundle(59), mother_mesh(54)`、`feature_bundle→obs_result(59)`、`obs_result→fragment_mesh(12), physical_component(9)`、`physical_result→clean_truth(11), physical_component(11)`、`physical_truth→physical_component(11)`、`visible_labels→obs_result(9), physical_truth(9)`。`physical_component` 有 11 个 ancestry ID 在本 store 索引中无对应记录；当前只标记为 unresolved in-store reference，尚不能断定是坏引用，也可能指向外部/旧库对象。

上述数据说明 A12 已能组织合成观测、网格、静态真值及 lineage；它没有给出 PG-Frag 所需的体网格/求解输入、逐时刻损伤状态、接触轨迹或实验校准数据。为避免误读，本 census 的大小是文件字节，不是计算资源 benchmark；内容细节见同目录 `a12_current_evidence.json`。

## 可复用、需适配、必须补建

| 层 | 可复用证据 | 对 PG-Frag 的差距 |
|---|---|---|
| 几何与上游生成 | `synlab/mothers` 可提供参数化壳体/母体；`synlab/fracture` 有共享切割器、Voronoi 分块、二次分块、形貌/网格测量；`synlab/storage/store.py` 提供通用 AssetStore 与 ancestry。 | 输入需要带尺度、封闭/可转换状态、区域/层材料场和坐标系；store 的 A12 role/schema 与训练包不是指南的 solver-ready Asset Contract。需要独立 schema/validator/适配器，支持指南列出的 GLB/STEP/VTU 等互操作格式（[P0500–P0503]）。当前 census 没有体网格/体场资产。 |
| 求解器编排 | `synlab/fracture/api.py:56–57,130,273–280` 已有 backend registry、明确的 PENDING/MISSING 拒绝路径；可复用“显式声明能力，不静默回退”的工程模式。 | 代码列出的已建 backend 是 plane/rough/shared cut、secondary、Voronoi；`warped_partition` 为 PENDING，`fracture_modes` 为 MISSING。`warp_voronoi_cut` 生成受约束的 Voronoi 几何分块并调用经验片数律，不是 PD/FEM/phase-field 的时域求解。依赖包中没有 PeriLab、Peridynamics.jl、PyChrono 或 OpenRadioss adapter（`pyproject.toml` 仅列 NumPy/SciPy 等；可选 external 为 gmsh/open3d/pycolmap/faiss）。指南所列多个 backend 只能是候选，需逐一做许可证、版本、最小基准与适配验证（[P0313–P0320], [P0372–P0395]）。 |
| 材料模型 | `synlab/materials` 有程序化 profile、表面/孔隙等视觉与几何参数，可作为 preset/字段容器的起点。 | 指南材料插件要求本构参数/空间场/取向/界面/损伤律，不是材料名映射（[P0403–P0432]）。`synlab/materials/api.py:46–51,144–145` 明确力学属性为 UNKNOWN；但 `synlab/fracture/calibration.py:54–77` 会对密度用 2.2 g/cm³ fallback，`synlab/fracture/impact.py:133–140,247–310` 还使用工程配置的 Weibull/能量参数。它们可用于程序化 sweep，不能充当已标定材料。需要测量 E、ν、ρ、强度、断裂能/韧性、孔隙/晶粒统计及温度/速率适用范围，并记录来源/不确定度；UNKNOWN 不得默认补值后冒充解决。 |
| 随机性与缺陷 | 现有 RNG、seed、参数化 pattern/morphology 和可复算 hash 可复用为随机流/溯源框架。 | 当前 Voronoi/粗糙面路径在预定义切割后构造共享界面/表面场；这不同于从记录的材料/缺陷随机场演化出裂纹。指南明确随机变化要来自可记录的材料/缺陷变量，而不是裂面生成后再抖动（[P0410–P0432]）。至少要有 defect seed、场参数/ realization、初始缺陷、solver 输入与裂纹事件的一一 lineage。 |
| 接触、裂纹和碎片运动 | A12 有 mesh/fragment topology 和 pair relation 周边工具。 | 代码中没有时间积分、动态裂纹传播、碰撞/摩擦求解与碎片运动轨迹；几何“切开后多个 fragment”不代表经历了动态接触。v0.1 要求基本碰撞和碎片提取（[P0525–P0528]）；需调用并适配已有稳定求解器，而不是在 A12 几何流程里添加伪时间步。 |
| 输出重建 | A12 能输出 fragment mesh、静态 `interface_id`、clean/physical/visible truth 与投影 label。 | PG-Frag 要把 fracture surface 作为一级结果，明确 exterior/fracture surface 分区、裂纹事件时间/父子分叉/损伤场、两侧局部材料场/法线/尺度及 solver lineage，并统一重建不同后端的点/体素/phase-field 输出（[P0455–P0461]）。当前 label/interface 契约不能直接表示这些历史事实。 |
| 发布/部署 | 现有 CLI/API、QC、manifest 与训练 export 的工程经验可以借鉴。 | A12 导出核心面向训练数据，不是独立 PG-Frag 的 Job/Result schema；需要独立 repo/API/CLI/版本、能力声明、headless 调度、明确错误与公共 validator（[P0490–P0518], [P0525–P0544]）。 |

## 关键语义差距：历史 R2 不等于当前接触或切割共轭

A12 预定义 cut 的 `interface_id`、两侧共享 cutter 和严格共轭，描述的是某次静态几何构造；它不能直接作为动态破坏后的 `historic_R2`。动态求解必须从损伤/断键状态重建裂面，并记录：共同断裂事件 ID/时间、材料参考坐标、父裂纹/分支关系、两侧 surface lineage、形成顺序、材料场值和重建方法。对当前接触应单独测量 `current_fit`；部署观测能否看见应另记 `evidence_visible`。二者都不能反推历史是否曾由同一裂纹面分离。

尤其要区分：弹性回弹或后续退化造成的当前错位、粉碎/erosion 的材料缺失、后来的接触面，分别不能自动抹掉或创造 historic_R2；当前几何精确贴合也不能单独证明历史关系。部署可见特征必须与 GT 历史映射隔离，不能让真值字段进入 forward features。静态 A12 的旧切割基线与门槛应版本化保留；新动态 backend 应按自己的能力定义守恒、收敛、裂面偏差和实验对照，而不能要求和旧切割结果逐位相同，也不能用新判据放宽旧资产的既有门槛。

如果点云/粗体素/网格修补用于重建，必须报告其对裂面形状、材料坐标、体积/质量和拓扑的影响；没有守恒与断面误差标记的“补洞”不能视为可信物理输出。

## 可信度、标定与计算量

指南给的是指标族，尚未冻结可直接验收的数值阈值：数值稳定/NaN/时间步、质量与线/角动量/能量账本、首裂位置和时间、裂纹速度/分支、碎片数量与尺寸分布、断面流形/孔洞/重建偏差/粗糙度、backend 差异与规模曲线（[P0565–P0575]）。因此首先要选定材料和加载边界，为几何、质量、事件、成像及追踪取得有校准链的实物/仪器数据；至少需要重复试验量化材料离散性，并留出不参与拟合的验证样本。未给定材料、加载和设备时，不能负责任地补造精度阈值或工作小时数。

用于估算量级而非实测 benchmark：按现有 `impact.py` 参考体积约 `3.4e5 mm³`，理想均匀体采样在间距 `h=1/0.5/0.25 mm` 时分别约 `0.34/2.7/21.7 million` 采样点。仅在固定物理体积、固定 horizon/h（邻域半径与粒距之比），使用同一显式 solver 和相同事件时长，且稳定步长近似正比于 h 的理想尺度假设下，h 每减半，采样点约增 8×、步数约增 2×；当每点邻居数近似不变时，单次求解工作量可能约增 16×，邻居表/场的内存约按采样点数增长。实际缩放取决于 solver、邻域、稀疏性、自适应和接触，需用真实几何做逐级 benchmark，不能据此声称某个 GPU 小时数或完成率。

另有一项直接影响未来深度/观测真值的未修复误差：临时解析 ray-plane spike 在斜平面上测得现行屏幕空间线性 z 插值误差（pinhole SS1 mean/p95/max 约 1.336/2.371/2.721 mm；非零 distortion SS1 约 1.426/2.563/2.998 mm），并测到 OpenCV 像素中心与超采样 K affine 不一致。证据在 `tmp/review_20261002/data/render_depth/render_depth_spike.json`。这不是对所有畸变边界的结论，也不是生产修复；它说明现有 QA_PASS 或“有深度通道”不能当作深度精确的证据。该生产修复已获授权，但本次升级分析暂缓，尚未生产修复。

## 建议推进门槛

1. 先冻结 PG-Frag 的独立 Asset/Job/Result schema：单位与坐标系、闭合/体网格、区域材料字段、载荷/初始状态、能力声明、seed、版本与完整 lineage；Adapter 隔离第三方求解器对象，失败时显式报告。用玩具材料参数的 PD case 可验证契约贯通、求解器调用、基本数值性质和输出拓扑，但只能验收 v0.1 骨架，不能据此声称真实陶瓷物理已验收。
2. 按指南的算法复用规则检索候选 solver 并核对许可证/维护/部署；选一个最小稳定 PD 路线做粗尺度验证，再通过 backend-neutral contract 接入接触和 fragment extraction，不预先承诺它适用于所有材料/速度。
3. 建立一组有测量记录的受控材料/几何/加载试验；先校准一个材料族和简单几何，验证独立样本上的首裂时空位置、碎片谱、守恒和断面误差。材料字段缺测就阻止“物理结果”级别验收，不能静默使用默认数。
4. 设计 fracture surface reconstruction 与历史 relation schema，区分 `historic_R2`、`current_fit`、`evidence_visible`；用同一动态 event 关联两侧裂面和材料坐标，另外标注 erosion/缺失/后续接触。保留静态 cut 的旧数据和旧门槛并独立版本化。
5. 逐级测 CPU/GPU 内存、运行时间、守恒误差、收敛曲线和重建误差；FAST/BALANCED/HIGH/REFERENCE 等精度 Profile 只有在这些基准有实测阈值后才有可交付含义（[P0463–P0488]）。

## 本次审计的边界与阶段状态

此报告是升级差距分析，不是科学验收。此前已有 leakage 边界、历史 R2 评测分母和 ConditionalCov@K 的针对性回归；最近可复核的针对测试日志为 `tmp/review_20261002/data/final-targeted-pytest-custom.log`（39 passed）。这只证明对应软件合同回归通过，不证明数据反捷径、求解器物理正确或与实物吻合。渲染斜面深度错误仍未生产修复；此前排队的噪声修改已暂停，当前任务未碰 noise 或生产 renderer。旧 release 与历史资产未改写。指南 v0.1 骨架结构贯通与真实材料可信数据是不同等级：前者可用合成/玩具参数验证接口和基本数值性质；后者还必须完成材料标定、独立实物对照和冻结的误差/守恒/收敛门槛。
