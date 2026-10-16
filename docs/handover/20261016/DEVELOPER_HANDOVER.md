# RelicWeave / VesselForge / PG-Frag 详细接手手册

**冻结时间口径：** 当前证据截至 2026-10-16（Asia/Shanghai）。开发已暂停等待交接。历史失败和旧快照均保留；下列状态按证据而非文件名或退出码判断。此手册仅汇总已有资料，没有新增实验或求解器结果；暂停交付另做了 211 项离线重点检查，见 PAUSE_VALIDATION.json。

最终阅读入口是 A12 仓库的 `docs/handover/20261016/`；continuation 状态与数学说明保存在 A12 [`docs/continuation/`](../../continuation/)；workspace-support 来源按用途分别归档于 [`workspace_support/docs/continuation/`](../../../workspace_support/docs/continuation/) 与 [`workspace_support/experiments/`](../../../workspace_support/experiments/)。恢复步骤见 [workspace-support 恢复说明](./WORKSPACE_SUPPORT_RECOVERY.md)。源路径以三个同级仓库和共享 workspace-root layout 为基准；A12 仓库内的 continuation 使用相对链接，跨仓代码/证据链接以独立 `DELIVERY_RECEIPT` 中的 GitHub refs 为准。单独克隆 A12 不含所有 workspace 路径。

## 产品目标与用户要求

RelicWeave 的长期目标是把可追溯的器物母体、材料/工艺与装饰参数连接到可审核的断裂结果，再生成只暴露允许观测的碎片数据，支持碎片候选排序、证据解释，以及接受、拒绝、补采或 STOP。A12 是模型/观测/数据与研究层；VesselForge 是母体几何、来源面语义和外观构造层；PG-Frag 是物理求解、断面、碎片提取和结果包层。在线排序不能读取母体身份、隐藏装配姿态、真值邻接、求解内部场或完整 GT；这些仅可留在离线审计目标。

用户明确把**日用器物和考古器物都列为目标**，要求现有与未来器型族都受真实对象证据约束。对每个参考对象，记录馆藏/对象 ID、主来源 URL、目录尺寸、照片、年代/材质/工艺、许可和哈希；再分开记录“来源明确测量”“图像判读”“生成器假设”。目录直径、重量或照片不能自行推出内径、壁厚、完整剖面、材质弹性模量、断裂韧度或原始烧前纹样。

模型需覆盖完整外形和内形、口沿与底、足圈/肩/颈/把手/流口等实际子型结构；每个几何参数提供请求值、解析值和实现值，保留有量纲范围和制造约束。按对象/工艺把釉层、底色、笔触和纹样放到对应表面；蓝白效果必须含可控笔触密度及扩散，不可只给蓝色图标。先以素面检查侧、俯、底、剖面和尺寸/厚度，再审装饰。实物材质与烧成化学只有测量或可靠出处支持后才能用于物理求解。

数值对照、来源引导合成和真实测量重建应由 manifest/receipt 显式区分。几何与网格通过不等于物理通过；特定 toy 的数值通过不能转移到新母体；数据集、快照和六张合成视图不能凭“碎片”命名取得 physical/PRETRAIN/deployment 资格。

## 三仓职责和当前关键接口

| 仓库 | 责任边界 | 当前接手模块/入口 |
|---|---|---|
| `vesselforge` | 来源绑定的母体 CAD/网格、面 ID/角色和到网格的边界祖先关系；提供给物理与外观层的可审核母体包。 | `src/vesselforge/revolved_profile.py`（子午线分段、剖面验证、法向偏移与旋转实体）；`spherical_bowl.py`（旧数值控制/实验球碗）；`reference_mesh.py`（保留索引和属性的扫描网格变形）；`named_step.py`、`face_witness.py`（具名 STEP 与 OCC 历史 witness）；`step_partition.py`、`tetra_audit.py`（分割、来源祖先与 T4 审核）。`forge.asset.v1` 原 validator 仍是既有合同。 |
| `pgfrag` | 从冻结母体网格和材料卡执行显式 cohesive/断裂路线，保留事件、质量/能量、裂面父子关系，提取完整闭合碎片。 | `src/pgfrag/cohesive_vessel.py::run`（实验 runner；`--preflight-only` 只做初始化）；`cohesive_mesh.py::read_gmsh22/build_native_lineage/quadrature_signed_work`；`cohesive_stability.py::mass_normalized_stiffness_bound`；`facet_ancestry.py::build_source_facet_table/map_native_cohesive_ancestry/event_delta`；`cohesive_fragments.py::extract_cohesive_fragments`。实验脚本不是默认安全 CLI；启动受单次预算、冻结哈希和新的运行决定约束。 |
| `relicweave-synlab`（A12） | 母体设计空间、材料/工艺外观、纹样、碎片观测、离线真值和资格标签；只在显式许可下暴露无泄漏观测。 | `synlab/mothers/design_space.py::parameter_space/build_designed_mother/probe_parameter_effect`；`materials/reference_materials.py::list_reference_materials/reference_material/sample_reference_material/process_compatibility`；`patterns/reference_styles.py::list_reference_styles/build_reference_pattern/sample_reference_style`；`patterns/underglaze.py::build_surface_of_revolution_operator/diffuse_pigment/diffuse_two_fraction_appearance/blue_white_appearance`；`patterns/bluewhite_panel.py::build_bluewhite_panel`；`integrations/reference_generator.py::load_reference_mother/compose_reference_instance/sample_outer_wall_texture/write_reference_instance`；`integrations/native_cohesive.py::validate_native_cohesive_fragments/export_native_cohesive_dataset/load_native_cohesive_dataset`。 |

跨仓的基础链条是：VesselForge 输出带 source provenance、section/profile、solid STEP、surface、face lineage/witness 与网格结果；PG-Frag 绑定原始 node/cell tags、source facet identity、材料卡、状态/事件和独立读回；A12 只从合格 packet 构建匿名观察与离线 truth，manifest 绑定 source group、哈希和资格。当前还没有一个版本化、可独立安装的整体三仓 API package；更改公共字段时须同步 manifest、loader 和资格合同。

## 当前事实状态

### 几何与真实对象

- 当前参考引导几何至少包含 Aberdeen 日用小足碗 `ABDMS095708.121` 的 v6 候选、Met 18.56.44 v2 候选及三个独立器型家族变体；具有实际 STEP、surface、section、lineage 和结构报告。候选视图已由 root 查看。尺寸引导不等于测量重建；Aberdeen 108×53 mm 是目录值，低角度照片显示更高的足部，候选的约 7 mm 足高属于视觉设计假设。外部扫描改型 run02 保留原始索引/属性但仍为 raw scan，不是已精修实物资产。
- `third_party/reference-assets/apsida-shm17946-0047` 的 CC BY-SA 4.0 来源和哈希有记录；v3 衍生件去掉了断连岛、零面积面和一对反绕重合三角形，但还剩 7 个 pinched vertex links。结论为 `FAIL_UNQUALIFIED_SCAN_USE_AS_VISUAL_REFERENCE_ONLY`；不可静默送入实体求解。
- A12 的 design-space adapter 已暴露请求/解析/实现控件，但已知 metadata mismatch 和 V23 继承控件忽略仍作为风险保留。Hasami Tokusa 和纯色 Jun 有来源引导样式；Hacilar 当前只是几何研究，尚不能用三角形代替真实 chevron motif。

### v6 source-witness tetra mesh：几何诊断 PASS，物理未开始

最新 v6 mesh 是 `vesselforge/experiments/continuation_20261016/reference_v6_tetra/run05/partition_output/`。`result.json` 状态为 `GEOMETRY_DIAGNOSTIC_ONLY`：86,624 个正 T4；NPZ 总数为 25,748 node rows；Gmsh MSH 只有 25,579 个 T4 引用节点，另 169 个 NPZ 节点未被 T4 使用且不在 MSH Nodes 中；356 个双父 interface triangles；44,182 个 exterior triangles；16 个 source FID/role；CAD 网格体积相对误差 `0.00240307996868`，即约 **0.240308%**。成功读取回执 `experiments/continuation_20261016/root_v6_run05_readback.json` 状态为 `ROOT_INDEPENDENT_V6_RUN05_GEOMETRY_READBACK_PASS`。MSH/NPZ T4 跨格式用原始 cell tag 和有序 corner node tag 对齐；不是依赖近似坐标推断。ASCII 坐标 roundtrip 最大绝对误差 `6.94e-18 m`，是声明容差内，不是二进制完全相等。

run05 使用全局 2.2 mm、rim role 局部 0.5 mm；93,808 T4 / 1.537 GB 是资源预测，非实际峰值内存或 OS 内存保证。foot fillet 局部面面积偏差约 −9.72%、−8.70% 仍需整改或限定。它通过几何/来源映射/序列化范围检查，不通过来源形状拟合、全特征精度、实物重建、材料、native evolution、断裂、碎片或训练资格。

### v6 初始化预检：准备完毕，未运行

`pgfrag/data/continuation_20261016/reference_v6_preflight/` 有 `run_control.json`、`preflight_budget.json`、`parser_equivalence.json`、输入冻结件和审计脚本。状态分别为 `READY_FOR_SINGLE_NATIVE_INITIALIZATION_PREFLIGHT` 与 `WHOLE_OUTPUT_FORECAST_PASS_RUN_NOT_STARTED`。`pgfrag/experiments/continuation_20261016/reference_v6_preflight/` 只有准备/运行脚本和 `inputs/` 冻结包；目录中**没有** `native_preflight/run01`、`execution_record.json`、process watchdog 或结果读回，因此没有 Akantu 初始化证据。

执行 MSH 只把两个物理组字符串从 `cut_interface`/`source_exterior` 改为 wrapper 要求的 `interface`/`exterior`。alias receipt 证明 Nodes/Elements blocks、tag/顺序、连接和物理整数标签一致，体积物理组不变；这不会改变 169 个未用 NPZ 节点的事实。脚本设计为单次 zero-step `--preflight-only`，全输出预算 256 MiB、单次 shell timeout 300 s、PowerShell watchdog 330 s、单线程 CPU 0。该结果若将来获得明确决定，也只证明初始化/质量/存储预测，不授权 evolution 或断裂。

### 蓝白 panel：算法基础与技术预览已有，成品纹样未验收

- A12 `patterns/underglaze.py` 的 metric finite-volume diffusion 和 bound/mobile appearance 有源图 demo 与质量证据；最早的大面积整体虚焦效果已被拒为成品。局部 dragon-head study 可保住较清晰核心并控制 halo，但仍非完整瓷碗纹样。`patterns/bluewhite_panel.py` 将烧成后的 Met 50899 青花照片 crop 映射到实际 varying-radius bowl panel：细网格 240×1024、245,760 cells、离散网格质量漂移约 `1.66e-16`、多边线近似 shear 上界 `0.63665`；粗细网格 spread RMS 差约 `0.0584`，是敏感性而非收敛。面板宽 45 mm、高 26 mm，只是单块新合成设计，不重复铺满圆周。
- A12 source-resolution 对照采用 opt-in `source_resolved_stationary_v1`，静止笔触直接从 immutable 原分辨率源图采样，移动部分从 transport grid 采样，默认仍为 legacy；零传输可重现原连续 source。两包总输出精确 `27,304,078 bytes`。Root 对 closeup、receipt hashes 和输出量做过独立读回，并记录 55 个 panel/generator/underglaze/material focused checks PASS。此口径包含 technical source-detail retention；网格质量为 `DISCRETE_GRID_MASS_ONLY`，不是连续源的质量守恒、完整纹样、历史复原、化学标定或几何/物理资格。
- 最终 `bluewhite_v3` 技术预览修复了 texture orientation/PBR binding/连续纹理采样等显示缺陷，root 已查看，接受技术构图 slice；crop 本身仍是未完成的 ornament proxy。Vase 的烧成照片不提供烧前颜料、照片照明/釉/投影校正、完整图案或历史 bowl attribution；不声称测得 optical coefficient 或 firing chemistry。

### native fracture / extrinsic insertion

- 2026-10-15 的已完成 native control 有两个闭合 native components，完整 4,342-T4/质量覆盖，158 paired failed facets；A12 导出六张理想软件 RGB-D 视图、8,216 可见点。它来自小厚球碗上的预置弱 seam/未校准材料控制，数据仍 `physical_pass=false`、`pretrain_eligible=false`、`deployment_eligible=false`、`production_a12_complete=false`。只能称数值/软件观察 control，不转移到 Aberdeen v6。
- 小型 96-T4 extrinsic coupon 的只读 audit 重构：650→651 增量 work 约 `+3.68237e-7 J`、dissipation `+1.72626e-7 J`；651→652 work 约 `−5.60979e-5 J`、native `D≈−5.57297e-5 J`，22/24 QPs work increment 为负，first negative getter 是 652。这个原始 signed work 路径解释当前负值；领先解释是近零开口的方向刚度/未解析反转，而不是已证实唯一根因。
- 原 capture 的 phase C 新复制节点 mass rows 为 0、重复 u/v 与父节点一致；phase D solve 后每组件重复节点质量约 `5e-6 kg`、总质量保持 `4e-5 kg`。必须注意 kinetic-energy getter 可能触发质量重装：已检查的 tagged source 中 getter 会调用 mass assembly，而 installed wheel 与该 source 的字节/版本等价尚未证明；旧 capture 的取样先后不能证明 C 的 mass 一直为 0。新 driver 将另存 getter 前/后的 C 和 D 状态。
- 零步 wheel capture 已确认公共 `flattenInternalReal` 和要求的 state/internal-field getter 路线；没有 public `getTime()`，用 driver step×dt 并单独记录 prescribed BC phase。公开 FEEngine shapes/normals 的 zero-step shape-only preflight 结果 `VERIFIED_COUPON_AFFINE_TRI3`：只对冻结 coupon 的八个平面仿射 Tri3 用实际面面积/3 作 QP 权重；没有通用 per-QP integration weight/Jacobian getter。
- `frozen_protocol.json` 状态 `FROZEN_FOR_ROOT_REVIEW_NO_CAMPAIGN_LAUNCHED`；`prepare_validation.json` 状态 `PREPARED_NO_MODEL_NO_SOLVER_STEPS`。主计划仅 h/h2/h4（三次 fresh initialization，共同物理终点 666h）；h/8 需要单独确认。campaign 必需捕获 A/B/C/D、native field semantics、mass/forces/u/v/a、stable source FID、QP 顺序、能量和 event-time；不允许从历史 arrays 初始化或重跑失败目录。当前未得到新 native trajectory，也没有足够证据宣称 onset/tangent/energy pass。

### generic mother binding 与仍未创建的成品

`experiments/continuation_20261016/generic_mother_binding/run05_binding/experiment_receipt.json` 写 `READ_ONLY_BINDING_VALIDATED`，对应的 `binding_receipt.json` 与 `binding_arrays.npz` 均存在。它把 run05 的网格与 `ABDMS095708.121` 的 section、face lineage、surface/STEP/source provenance 和 witness hashes 绑定；实际 run05 binding 尚未完成 root acceptance。包未创建 preview、fracture 或 observation；`physical_material_status=UNKNOWN`、solver 未建立、profile fidelity 未建立、`physical_pass=false`、`pretrain_eligible=false`。`preview.png` 是缺失的非绑定 artifact。binding receipt 中的 `PASS_STRUCTURAL_CAD_ONLY` 只限结构 CAD，不升级为裂纹接口或真实器型完整包。9 个相关 unit checks 通过也只说明 validator 的软件合同，不等同于母体 acceptance。验证 read-only binding 不是 native solver run；对应 A12 发布归档副本位于 [`workspace_support/experiments/continuation_20261016/generic_mother_binding/run05_binding/`](../../../workspace_support/experiments/continuation_20261016/generic_mother_binding/run05_binding/)，三份文件的 SHA-256 与共享 workspace 源目录一致；具体值见 `EVIDENCE_INDEX.md`。

## 完成项、失败项、半成品和未启动项一览

| 状态 | 项目 | 接受范围 |
|---|---|---|
| 已完成、窄范围 PASS | v6 run05 tetra 几何与来源读回；v15 native-face witness 数学读回；A12 面板/参考材质/generator focused tests；extrinsic getter capability/ coupon `area/3` zero-step shape preflight；old v6 contact weak control 的窄 transient bonded-compliance 数值比较。 | 仅各自 receipt 列出的几何、布局、质量或软件契约；不能叫整项目/物理 PASS。 |
| 保留的 FAIL/停止/已知不通过 | Apsida scan v3 仍 7 pinched links；旧小 coupon 652 signed work 第一负耗散；早期圆碗 mesh run01/03/04 未过 1% 体积门；run02 forecast 超 cell cap；old same-day contacts/controls 曾有独立的 transient bonded compliance 失败（见 10-15 STATUS）；Hacilar motif 未达表达要求。 | 都不可因新 candidate PASS 删除或抹平。 |
| 半成品/候选 | Aberdeen/Met reference-guided 几何、扫描变形、A12 materials/patterns、source-resolved蓝白 crop、generic mother binding、native closed-component RGB-D dataset、v6 mesh. | 保存文件或流程成功不自动等于 refinement、museum fidelity、完整输入/观察/物理包或 qualification。 |
| 未启动 | v6 reference vessel native initialization preflight；extrinsic onset h/h2/h4 campaign；完整 Aberdeen v6 loaded evolution/fracture；实物材料校准；mesh/time/orientation 收敛；blue-white finished ornament review；A12 whole-model admission/training readiness；批量生产/训练。 | 保持未运行，不能从预检或控制成功推定。 |

## 恢复顺序与命令约束

1. 从 A12 `docs/handover/20261016/` 阅读入口文件和 [最新 continuation 状态](../../continuation/20261016/STATUS.md)；workspace-support 续接说明和实验脚本/证据分别归档在 [`workspace_support/docs/continuation/`](../../../workspace_support/docs/continuation/) 与 [`workspace_support/experiments/`](../../../workspace_support/experiments/)。以独立 `DELIVERY_RECEIPT` 核对三仓最终 branch、commit SHA、remote 和推送状态。跨仓 evidence links 必须指向该记录中的 refs，不能仅凭 workspace 相对路径推定单仓克隆含有文件。
2. 继续工作前复核三仓代码/数据清单、来源许可和大型文件取舍，再只读核对 `run_control.json` / `preflight_budget.json` / alias receipt hashes。不得把 `READY` 或 forecast `PASS` 写成初始化 PASS。不要对工作区做 blanket `git add .`；逐项区分输出数据、第三方资源、缓存与项目源码。
3. v6 preflight 是已准备的一次性 `--preflight-only` 包。现有 `run_preflight.ps1` 和 `run_native_preflight.sh` 硬编码了当前 workspace/WSL 路径；移交到另一台机器前必须修成 workspace-root-relative 并重新校验 runner hash，或在原机保持原冻结字节。若因上述改变重新准备，需新证据目录/receipt，不能伪造原 hash。取得新的明确运行决定后，方可启动该单次 zero-step attempt；结果只允许做初始化与 cost evidence。
4. Extrinsic campaign 的 `--prepare` 和 API inspection 不等于数值运行；protocol hash 在 `prepare_validation.json` 中。先读 `pgfrag/experiments/continuation_20261016/extrinsic_onset_refinement/README.md` 和 protocol，再完成审核并取得新的运行决定。h、h/2、h/4 单独 fresh 初始化；run each once; h/8 不包括在当前 matrix。
5. 在物理结果前继续补全参考器型轮廓、内腔/壁厚/唇口/足部和图像审阅，给 imported source 明确 refinement/acceptance gate；接着才评估实际母体上的 solver/material/loading。最后才能生成 observation package、跑 A12 leakage/qualification gates。

**安全/范围：** 开发目前暂停。脚本与验证命令只用于定位已保存的流程，不构成新实验授权。不得运行任何未启动 solver campaign，不得改写或复用单次 run ID，不得把窄 numerical acceptance 用于 Aberdeen 母体、材料真值或模型训练。

## 环境与复现注意

- 环境证据来自 Windows + WSL Ubuntu。项目运行时按各 repo/实验的冻结协议选择，不应退回全局 PATH。Akantu v6 preflight 预期 Python `3.12.15`、NumPy `2.5.3`、Akantu wheel `5.0.7-post1`；被检查的本地源码标记 v5.0.7，和 runtime wheel 分别记录，不能写成同一 source build。VesselForge 路线依赖 CadQuery/OCP（已记录 CadQuery 2.8.0、OCP 7.9.3.1 系列）；A12 使用仓库项目 Python/依赖及 SciPy sparse。
- 部分 runtime 在 `third_party/...`；这不是完整安装 lockfile，许可证/下载来源没有全仓统一审计。Akantu one-off scripts 使用 WSL `/mnt/...` 绝对路径，VF/A12 旧 handover 也记录本机 runtime absolute paths。当前记录可帮助原开发机复现，不能证明别的机器安装可重现。恢复前先由开发环境 manifest 固定 Windows/WSL、Python/NumPy/SciPy/CadQuery/OCP/Akantu 版本，wheel、source、license hash 与 setup 检查。
- 2026-10-16 暂停交付的三套 focused 验证共 211 项，准确命令、测试文件和资格边界见 [PAUSE_VALIDATION.json](./PAUSE_VALIDATION.json)。这不是全仓库 suite，没有 solver 或新实验；9 个母器绑定 unit checks 不等于实际 run05 母体验收。后续验证前应核对代码 commit 与对应 runtime。

## 工作区和发布状态

暂停快照中的三个本地 checkout 分支均为 `backup/forge-work-20261003`。VF/PG 的 GitHub 默认分支同名；A12 默认分支为 `main`，A12 `HEAD` 相对 `origin/main` ahead 16 commits，origin/main 是祖先，可 fast-forward。交付后的实际 branch/ref 以独立 `DELIVERY_RECEIPT` 为准。

约 6.8 GB raw data 由本地 manifest 保留；不应把所有 raw data 当作项目源码推送。`_temp_matplotlib` 是外部 runtime cache，应排除。暂停时没有观察到仍运行中的本项目 Python 或 WSL solver。三套暂停交付 focused checks（VF 66、PG 55、A12 90，合计 211）及精确命令/文件见 [PAUSE_VALIDATION.json](./PAUSE_VALIDATION.json)，不是全仓库 suite。A12 更早 source-resolution 的 55 checks 是另一组；PG 的 9 个 mother-binding tests 仅验证 validator software contract。

交接入口为 `relicweave-synlab/docs/handover/20261016/`；workspace-support continuation 来源与根级实验脚本/证据分别收在 `relicweave-synlab/workspace_support/docs/continuation/` 和 `relicweave-synlab/workspace_support/experiments/`。README 导航指向统一交接入口，具体 GitHub repository/branch/commit SHA 和发布范围由 `DELIVERY_RECEIPT` 独立记录。

总方案原档 `RelicWeave_V1.48_ContractAligned.docx` 是 228 页，SHA-256 为 `23a42e5f4cca40ef733edc9365c15bd0d5fdff647f8821fddec9c649e52b1455`；Word 原档在暂停时打开并锁定，Python 只读提取与归档副本一致。独立更新版已保存为 [`RelicWeave_V1.48_Engineering_Update_20261016.docx`](../../master/20261016/RelicWeave_V1.48_Engineering_Update_20261016.docx)，SHA-256 为 `b134f7a781b62bbf8946a269343d8eeedbc87c2697c83dcb55e0ab83cf97fd62`；保留 10/09 原档，不覆盖历史版本。更新范围见 `DOCUMENT_REVIEW.md`。
