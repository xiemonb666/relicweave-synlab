# PGFrag / VesselForge 工程差距审计

审阅日期：2026-10-03  
范围：将《PGFrag_VesselForge_Guide_v11》与当前 A12 工程、现有依赖与本地运行/调度入口对照。只读；未创建仓库、迁移数据、安装依赖、启动服务、运行 Blender/求解器或执行升级流水线。成本等级是工作量级别，不是工期承诺：S=局部适配，M=一个完整模块，L=多个模块联调，XL=需要独立算法/验证与产品化工作流。

## 结论

这不是把 A12 的断裂后端换成 PeriLab 的单项替换。指南定义的是两个可独立发布的基础设施：VesselForge 负责通用几何/纹样/物理就绪资产，PG-Frag 负责材料、动态损伤/断裂、接触与碎片结果；两者通过版本化 Asset Contract 解耦。A12 是现有应用、数据生成与检索/训练平台，适合作为薄适配器和首批消费者。这个边界在指南 P0017–0037、P0503、P0525–0544 中有明确要求。

建议保持决策边界：VF 与 PG 各自独立代码库、版本与 CI；从最小垂直链路就接 A12，而不是等两边做完再集成。独立发布契约不要求在每个阶段复制整套 Web、UI 和数据库；可复用 A12 当前消费者界面与存储/任务模式，但应由适配器转换契约。PG solver 进程与 A12 API/worker 环境隔离，通过明确输入包、manifest、进度与错误 envelope、结果包和校验报告交接。A12 内部的 AssetRecord、role、lineage、QA 字段不是 VF/PG 公共 schema。

## 阶段差距与成本级别

| 指南阶段/能力 | A12 现状与可复用项 | 缺口与判断 | 成本 |
|---|---|---|---|
| VF v0.1：参数化旋转体 + Loft/Sweep、规则纹样、physics-ready export（P0525–0528） | 有固定器物/材质/纹样注册表，Manifold3D/Trimesh 几何、Blender 子进程渲染、Gmsh Python 包；可复用几何质量检查、资产写入、A12 页面作为消费者。 | 当前 GenerationSpec 属于 A12 synlab.v3 应用输入，不是通用部件/器型语法；本机无 CadQuery/OCP、xatlas、libigl、OpenVDB、meshio/VTK。现有 Gmsh 探针验证的是离散共享表面，不代表能为任意薄壁、复杂部件稳定生成带区域/厚度/材料字段的 physics-ready 体网格。新建独立 VF 几何模型、导出器、validator 与契约测试。 | L |
| PG v0.1：统一 job schema、一个 PD backend、基本碰撞、碎片提取（P0527–0528） | A12 有资产输入/存储、作业状态、错误 envelope、预算检查、UI 展示，可作为初始宿主和观察端。 | A12 fracture 是共享切割几何路线，不是动态连续体求解。BUILT_BACKENDS 只有 plane/rough shared cut、secondary、warp_voronoi_cut；warped_partition/fracture_modes 仍 pending。材料代码显式把模量、泊松比、断裂韧度、抗折强度、密度记为 UNKNOWN。当前没有 PD 时间积分、初始/边界条件、接触求解、动态碎片刚体排空及对应数值验证。PeriLab 可作为候选 adapter，不会替代输入映射、校准、后处理、验收与失败语义。 | XL |
| v0.3：PeriLab/Chrono adapter、材料插件、随机场（P0530–0532） | 可复用 A12 的 seed、manifest、资源预算和 provenance 经验。 | 本机没有 Julia/PeriLab、Chrono/PyChrono 或 MPI；须增加 Julia/solver 包部署、输入 deck 生成、进程监督、超时/取消、stdout/stderr 归档、崩溃识别、结果导入与 golden benchmark。Chrono 的刚体碎片段需与连续体断裂输出有明确切换条件/质量、速度、角动量交接。材料校准及随机场的单位、相关长度与标定来源尚不存在于当前 profile。 | L–XL |
| v0.5：至少两类 FEM-PD/phase-field/OpenRadioss backend，多材料/界面（P0534–0536） | A12 有材料/标签语义资产，但不含物理标定。 | 这是跨求解器语义契约和一致性报告问题，不是多加几个 registry ID。需统一 capability declaration、材料/边界条件映射、公共结果 validator、跨 backend benchmark 与解释性差异报告。指南要求所有输出检查能量、质量、拓扑、NaN/发散（P0511–0518、P0564–0575）。PeriLab 官方文档明确 coupling-zone element shape 有约束（rectangular、quadratic 或 parallelograms），因此不能把其 FEM-PD 耦合当作任意三维自适应耦合已解决。 | XL |
| v1.0：独立产品级、headless scheduler、HPC（P0537–0540） | A12 有本地 SQLite scheduler/lease/fencing、单机 CPU/RSS/GPU/磁盘 admission guard、HTTP jobs 与 SPA。 | 当前 worker 是本机进程、直接调用 Python handler，无集群 placement、队列后端、MPI/HPC executor 或 solver capability 路由。需抽象 local subprocess/container/remote scheduler executor，再增加集群资源模型、结果 staging、取消/恢复语义与水平扩展验证。该缺口对 v0.1 CLI/本地小算例不是先决条件，对 v1.0 是明确新增工作。 | XL |

## 可复用 / 新增 / 隔离

**优先复用 A12：** A12 API 的鉴权与错误响应、异步 job 查询/事件、workspace 隔离、UI 任务状态/结果查看、SQLite 资产存储、hash/integrity 与报告生成、资源预算和 seed/provenance 模式。首个端到端切片可以由 A12 现有向导或 CLI 提交 VF 资产包，经薄 adapter 转成 PG 输入，执行一个很小的 PD case，再把结果 manifest/status 返回 A12 展示。

**必须新增在 VF/PG 独立核心：** 与框架无关的几何/材料/事件/场/结果 schema 与版本迁移；资产契约和校验器；backend capability registry；solver adapter SDK；确定性与版本清单；solver 输入/输出映射；真实材料参数与来源；批次基准、守恒/稳定性/拓扑指标；CLI 与 Python API。公共接口应表达 simulate(..., backend=...) 一类稳定能力，不把 PeriLab 私有对象或 A12 role/hash 语义变成 core API（指南 P0505–0518）。

**应适配或隔离：** a12.obs.v1 是观测/特征合同；A12 GenerationSpec 和 FractureConfig 是固定应用枚举/几何参数。新 Asset Contract 应定义 surface.glb、可选 solid.step / volume.vtu、regions、厚度/方向/材料场、provenance 等（指南 P0501–0503），再由 A12 adapter 做映射。不要把 lineage_id、split、truth/QA role 当作 PG core 的通用几何或 solver schema。

## 当前工程证据

### 1. 断裂与材料不是可直接升级为动力学求解的数据

- synlab/fracture/api.py:55–60 把已建后端与 pending/gated 后端分开；synlab/schemas/spec.py:147–166 的 FractureConfig 只有固定后端名、目标碎片数、切割误差/粗糙度、尝试次数等参数，没有载荷历史、边界/初始条件、时间积分或数值容差契约。
- synlab/materials/api.py:46–51,141–145 将关键机械材料量置为 None 并记录 mechanics.status="UNKNOWN"。这对 A12 的程序化生成/外观资料是诚实的，但不能作为 PD/FEM 物理材料输入。需从实验/可靠数据源校准，并验证不同 constitutive model 的参数含义和单位。
- docs/a12/open_items.md:102 仍把 Gmsh 共形 PLC + 共享分割面列为 warped_partition 待办。已经安装 Gmsh 只能证明库在环境中，不证明该几何路径已通过生产质量验证。

### 2. Job/API 已可复用，但现有后台执行并非 solver 平台

- synlab/jobs/scheduler.py:1–5,149–213 实现 SQLite 单写者、依赖检查、lease 与 fencing；synlab/api/worker.py:101–114 每个 tick 至多领取一个作业并串行执行；:116–138 在本地进程内 dispatch Python handler 和资源 admission。synlab/jobs/resources.py:43–77 的 guard 约束本机磁盘/保留资源，不负责跨机器放置。
- synlab/api/handlers.py:665–672 只有 freeze_spec、audit、export、display_lod 是具体 handler；其他 stage 经 setdefault 进入 run_capability_gated，并在能力模块可导入后仍以 INTEGRATION_PENDING 失败（:638–643）。POST /jobs 返回 202 表示已接受而不是已执行（synlab/api/routers/jobs.py:125–205）。
- A12 的两条入口行为有意不同：mode=pipeline 直接同步调用 synlab.pipeline.build_one_mother，mode=jobs 走异步 job handler；后者目前返回 INTEGRATION_PENDING。此差异已在 docs/a12/api_ui.md:454–465 和 synlab/api/routers/synthesis.py 中披露，不能把 job API 宣称为完整的生成/solver 通道。A12 这部分应作为宿主/消费者复用，PG solver adapter 应运行在独立进程或独立执行环境。
- synlab/storage/store.py:212–235 是不可变 asset store + SQLite WAL；:250–265 按 payload hash 写 blob；:312–335 将 ndarray、bytes 与其余 metadata 落到 A12 内部表示。它适合借鉴原子写入、内容 hash 与元数据索引，但 schema 层仍需要 VF/PG 的中立 Asset/Result contract。

### 3. 本机库与外部求解器可行性

只读探针脚本 tmp/review_20261003/pgfrag/installed_capabilities.py 与 solver_feasibility.py 均 exit 0；检查 .venv Python 3.12.14。探针中“importable”主要由 importlib.util.find_spec/安装包版本判断；env_report() 另实际调用 torch.cuda.is_available()。这些结果不等于做过每个库的功能 benchmark，更不等于 solver 验收。

- 当前可发现：NumPy 2.5.3、SciPy 1.18.1、scikit-image 0.26、OpenCV 5.0、Trimesh 5.1、Manifold3D 3.5、Shapely 2.1、SVGPathtools 1.8、Gmsh 4.15.2、Open3D 0.19、pycolmap 3.11、FAISS 1.15、Torch 2.11.0+cu128。环境报告的 Torch CUDA availability 为 true。它可支持现有图像/几何/索引/网格准备工作，但 CUDA Torch 并不表示 PD solver 能在 GPU 上运行，也没有本次性能测量。
- 当前没有：Julia、PeriLab、Chrono/PyChrono、OpenRadioss、MPI runtime/mpi4py、CadQuery/OCP、xatlas/libigl、OpenVDB、meshio/VTK、TetGen、Taichi、FEniCS 等。PATH 有 CMake 4.4.3，无 Ninja。gmsh/blender 独立命令未在 PATH。
- Blender 有单独的 portable executable：C:\Users\xiemo\Desktop\ShardForge\third_party\blender-5.2.2-windows-x64\blender.exe，存在性已检查；.venv 调用 find_blender_binary() exit 0 并解析到该路径；synlab/observe/blender.py:106–132 会搜索项目 portable directory，docs/a12/backend_capabilities.json 记录先前 backend:blender_render selftest PASS（Blender 5.2.2 LTS）。本轮没有启动/重测它。PeriLab 官方仓库说明 Windows/Linux release binary 可自带 Julia；其 MPI 指引对 Windows 建议 WSL。因此这里的结论是当前未安装、未验证，不是 PeriLab 必然不能在 Windows 使用。对于 MPI/HPC 或 Julia/Chrono 与 Python/A12 的混合环境，独立 solver process / container / remote adapter 是较稳妥的边界。PeriLab 官方 coupling 文档说明 coupling zone 对 element shape 有上述限制：[安装与平台说明](https://github.com/PeriHub/PeriLab.jl)，[FEM-PD coupling 限制](https://perihub.github.io/PeriLab.jl/stable/theory/theory_FEM_PD_coupling/)。

### 4. 本机环境与前端有已复现的能力标志不一致

项目侧 synlab/api/capabilities.py:197–202 对 blender_bpy 只检查 find_spec("bpy")；当前 .venv 没有 bpy wheel，因此 API 的 env.blender_bpy 为 ENV_CAPABILITY_MISSING。但 renderer 实际使用独立 Blender binary：synlab/observe/blender.py:124–132 能从 portable root 查找它；synlab/observe/routes.py:520–573 也通过该 finder 决定 blender 是否可用。前端 frontend/src/pages/SynthesisWizard.tsx:71,292–293,1152–1160 却用 env.blender_bpy 禁用 Blender 选项。因此在当前工作区，存在的 renderer subprocess backend 被 UI 误报为不可用。最小修复方向是 capability 输出反映真实 subprocess selftest/binary 能力，或 UI 使用独立 blender_render capability；不要要求把 bpy 安装进宿主 Python。

同一信息源也存在明显陈旧：docs/a12/env_report.json 记录旧的 Torch 2.5.1 CPU/no Blender；本次 .venv 是 Torch 2.11.0+cu128、CUDA available，且 portable Blender 文件存在。docs/a12/runbook.md:26–28,121 仍记录 Blender missing；pyproject.toml 的 train extra 注释声称 Torch 2.5.1 已验证。应为能力报告加生成时间、Python 环境/后端类型，避免把旧探针结果用于当前 UI/交接决策。

## 当前资产库证据（不可当作 PGFrag 物理验证）

- **当前 data/a12_trainable/store census**：tmp/review_20261003/pgfrag/a12_current_evidence.json 的只读 metadata/NPZ-header census 显示 463 项资产、59 个 feature_bundle、14.39 GB store，8 个 run 记录全为 PENDING；该 census 另记录 11 个 physical_component 的 ancestry 引用在本 store 内未解析。角色 QA 状态是记录值，不等于本次重验通过。独立的 feature 审计来自 tmp/review_20261002/data/current_store_audit.json：feature_scope 明确为本库 59 个 feature_bundle；审计报告其中 20 个 feature metadata 含 event_id/lineage_id，truth_dependency_paths 为空，且该审计自身的 unresolved_ancestry_count 为 0。此 feature 审计仅覆盖 feature 依赖路径，不是对全 463 项资产做 ancestry 闭包扫描，因此不能与 census 的 11 个 physical_component 未解析引用合并；它也未重新哈希 NPZ，只检查 key/header 和小样本结构，不能证明训练模型不存在其他 shortcut，也不能据此断言 forward 已使用这些 metadata。
- **历史 data/a12_demo/store**：此前只读审阅发现 9 条旧 feature_bundle 被误标，schema 为 a12.obs.v1 且没有 feature_fields 声明；这是展示库的兼容问题，不代表当前 trainable store，也不应迁移/修正旧资产来适配 PGFrag。当前 trainable 的结构审计问题应独立处理。
- A12 数据规模和 QA 不能替代 PG-Frag v0.1 的小型力学 benchmark。指南 P0564–0575 还要求数值稳定、质量/动量/能量账本、裂纹演化对照、断面质量、跨 backend 差异和规模测试。

## 主要风险与验证门

1. **物理建模与材料校准（最高风险）**：先固定一个明确的 brittle-material PD scope；建立含单位、测试来源、置信度和适用范围的材料参数 schema。用公开/可复现实验或有来源的样件，在单元素/单杆/拉伸/三点弯曲/低能碰撞逐步验证。未完成前，A12 当前材料 profile 不能被转成“近似真值”输入。
2. **几何到 solver 网格（最高风险）**：建立几类薄壁/实体、锐角、薄特征和孔洞夹具；记录 watertight、非流形、自交、局部尺寸、体网格最差质量、区域/材料场保留和失败原因。单独测出几何离散误差，不因 Gmsh 安装或一张成功网格图宣称通用 physics-ready。
3. **跨进程/跨语言可靠性（高）**：Adapter contract 至少包含 input manifest/hash、backend/version/capabilities、seed、进度事件、终止状态、退出码、超时/取消、stdout/stderr、输出 manifest/hash、完整性与公共 validator。通过破坏性夹具验证 solver 崩溃/超时/部分输出不能提交成成功资产。
4. **HPC 扩展（中期高）**：先定义 Executor 接口和本地独立进程实现；后续再加 WSL/container/Slurm/PBS 等 executor、资源和数据 staging。local worker 的 CPU/RSS/GPU 预算不能映射成集群 rank/GPU 分配。
5. **契约和 Non-Lock-In（高）**：VF 与 PG 分别维护 schema/version/CLI/CI；先设计“从 A12 存储导出标准输入 → 独立 PG 求解 → 导入结果供 A12 看”的细薄 adapter。每步输出由共享 validator 验证；unsupported capability 明确拒绝，不能静默换后端。
6. **依赖/许可与供应链（中高）**：对 CAD/mesh/solver/Chrono/OpenRadioss 逐个确认 license、再分发要求、NOTICE、二进制发布与 Windows/Linux/HPC 构建矩阵，再锁定版本。指南 P0042–0059 要求先调研、许可检查和小型 benchmark；候选算法名不能当作已验收 backend。
7. **A12范围控制（持续风险）**：保持 A12 的原目标（观测退化、关系/检索、训练与诊断）不被“泛物理平台”替换。PG/VF schema、solver生命周期和 physics QA 在新 core；A12 的 VF/PG 接入层只持有映射、提交、状态查询与结果展示的版本化适配器，A12 本身继续维护其观测/退化/关系、预训练与诊断平台。

建议按“单资产 VF 输出 → A12 导入/展示 → 单 PD benchmark → A12 状态/结果展示”完成最小纵向链路，再扩展到第二个几何和材料。之后按 v0.3/v0.5 加 backend adapter，并以指南 benchmark 矩阵作为放行条件。不要先把 UI/API/数据库复制成两个完整服务；复用现有消费者端，独立隔离求解器生命周期与契约即可。

## 本轮验证边界

- .venv 能力探针：installed_capabilities.py exit 0；solver_feasibility.py exit 0。它们核实包查找/版本和 env_report，不是求解器功能测试。
- 未运行 pytest、TypeScript/build、Blender、PeriLab、Chrono、OpenRadioss、MPI 或 PGFrag/VesselForge 流水线；未安装依赖、启动服务、创建新仓库或修改生产代码/历史资产。
- 外部官方文档只用于核实 PeriLab 平台安装与 coupling 约束；没有在本机下载或运行它。


