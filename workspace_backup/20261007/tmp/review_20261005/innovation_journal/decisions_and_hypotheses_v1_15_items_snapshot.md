# Decisions and hypotheses — 2026-10-05

本记录只整理现有文档、实验方案和冻结收据中的决策与待证假设。编写日志没有启动新的 CAD、solver、pytest、GPU 或文献检索；下文另行标出已存在的运行/测试收据及其窄范围，不把它们扩大成物理结论。没有足够收据支持的主张标为 `SOURCE_ONLY` / `UNKNOWN`；`UNKNOWN` 表示现有证据不能裁决，不等于失败或通过。

VesselForge 与 PG-Frag 可以各自发展成论文方向，但这只是研究意图。工程设计、接口或局部实现本身不构成已确立的新颖性结论；每项文献检索仍待完成，并需各自基准、对照和可复现结果。

本次现有记录中，qualified complete pack、physical qualification 与 pretraining qualification 均为 0；论文创新性 `NOT_ESTABLISHED`。

## RW-01 — 观测碎片闭环与 GT 隔离

**问题与决策。** RelicWeave 的可审计路径固定为 `observed fragment → ranked candidates → per-candidate evidence → accept / reject / recapture / STOP`。排名只是待核候选；证据反驳候选时拒绝，证据不足且仍可补采时重采，超出补采能力或仍有歧义时 STOP。GT 与历史关系标签留在审计/训练标签侧，不进入候选排序或推理特征。

**可证伪验证。** 用源绑定的真实观测和实际 producer/export/inference payload 做逐行谱系审计；对推理张量执行字段与依赖追踪，确认 GT 改动不会改变排名输入；对已知真值集分别记录接受、拒绝、重采与 STOP。任一来源哈希/行映射缺失、GT 可影响推理张量、或候选排名被当作真值，均判 FAIL。

**现有证据与状态。** A12 审计摘要为 30 gaps、0 条已审计 fragment rows、producer/source binding `UNKNOWN`；计划明确 observed-fragment 闭环，但本轮没有真实观测闭环验证。当前 `SOURCE_ONLY / UNKNOWN`。

证据文件：`C:\Users\xiemo\Desktop\ShardForge\tmp\review_20261005\plan_inventory\structural_audit.json`；其源方案为 `C:\Users\xiemo\Desktop\ShardForge\RelicWeave_V1.46_A12_VesselForge_PGFrag_Integrated_NavFixed.docx`，SHA-256 `15978a3956fa33e8048cc54c1dad6878a7e19d9c71b84415dcaf8732f041a3b4`。当前真实观测链的冻结 SHA：`UNKNOWN`。

**文献检索：** 待检索 observed-fragment matching、主动补采/拒识、考古碎片配对与 GT 泄漏审计；尚无新颖性结论。

## INF-01 — VF → PG → A12 的独立基础设施首链路

**问题与决策。** VesselForge（完整器物、语义/材质资产）与 PG-Frag（材料/事件驱动损伤、断裂及碎片）作为各自可独立版本化的基础设施；A12 通过显式 Asset/Job/Result 合同编排二者。首条集成路径就要从 VF 的源绑定资产到 PG 的结果，再到 A12 的观测/实验产物保留版本和 lineage。论文可分别研究两条基础设施，但须分别提出研究问题与基准。

**可证伪验证。** 从一个冻结 VF Asset 实际提交 PG Job，核对输入/输出字节哈希、单位/坐标系、点/碎片映射与事件谱系，再由 A12 消费实际 PG payload；GT 独立审计。少任一真实调用点或 source-bound 映射，整链仍为 INCOMPLETE。论文贡献另需与相关工作及基准比较，不能由接口存在推出新颖性。

**现有证据与状态。** V1.46 方案把两个项目定义为独立基础设施。ChainCLI 最新窄收据为 25/25 focused PASS（7 个新 dispatch + 18 个旧 audit），16 个文件 pre/post SHA 全部相同；代码源 SHA 为 `3f84f824ca2dbc908303ae3c2b14f3ac3e1d8c88349238adf59ed747be48b5d7`，source-reader SHA 为 `ed1d72f0bd25d2962217e88a226d2a72706c013c7087465b53bb9ca04116bd9e`。这只验证 CLI 对 PG diagnostic fixture 的读取与审计规则；主链仍 30 gaps、0 qualification，A12 producer/export/inference 接点仍待接入，物理关系和两条论文贡献仍 `UNKNOWN`。

证据文件：`C:\Users\xiemo\Desktop\ShardForge\tmp\review_20261005\plan_inventory\extract.txt`（源方案 SHA-256 `15978a3956fa33e8048cc54c1dad6878a7e19d9c71b84415dcaf8732f041a3b4`）；`C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\tmp\review_20261005\chain_contract_review\focused_pytest_20261005.junit.xml`（25 tests、0 failures/errors）；`C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\tmp\review_20261005\chain_contract_review\prepost_hash_comparison_20261005.json`（16 files unchanged）；`C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\tmp\review_20261005\chain_contract_review\posttest_sha256_20261005.json`（代码/readers SHA）。主链 qualification 仍见 `C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\tmp\review_20261005\chain_contract_review\chain_contract_review.md`。

**文献检索：** 分别待检索程序化器物/语义表面资产基础设施、离散断裂与碎片动力学、可追溯合成数据链；不预设三者已有论文贡献。

## VF-01 — geometry-only `AddOptimal(False, False)` 与 STEP 字节身份

**问题与决策。** 把几何测量一致性与 STEP 文件字节相同分开报告。geometry-only `AddOptimal(False, False)` 可作为不依赖三角化缓存/形状容差扩张的 bounds 测量策略；几何 bounds/体积 roundtrip 通过不能证明输入与导出 STEP 字节相同。

**可证伪验证。** 冻结 STEP、几何体和测量程序；在网格缓存前后及 STEP 重载前后分别记录 geometry-only bounds、体积和拓扑指标，同时独立记录输入/导出 STEP 的 SHA-256。几何门按预先冻结的数值容差判定；字节 SHA 不同就只能报“几何 roundtrip 一致”，不得报 byte-preserving。

**现有证据与状态。** Beaker 冻结运行记录 `AddOptimal_s(..., False, False)`；STEP reload 的 volume delta 为 `−2.73576e−9 mm³`，六个 bounds delta 均为 0，STEP 几何门通过。另有结构审计记载 geometry-only bounds 在 mesh 前后 delta 为 0。收据没有记录源 STEP 与重写 STEP 的字节哈希，故字节保留 `UNKNOWN`。这是一次局部既有运行，不是本轮新增实验；法线射线 1 个 UNKNOWN 使整次候选判为 `FAIL_OR_LOCAL_EVIDENCE_UNKNOWN`。

文件：`C:\Users\xiemo\Desktop\ShardForge\tmp\review_20261005\smooth_candidate\run_beaker\run_metadata.json`；冻结候选源 SHA-256 `359DC041B521799C39A08ED1F2A680A192EECC234FD8E47845511CAE58048D8E`，fixed-case SHA-256 `9AFDFC764C28FC73932598B38A1A36DB56642864F620B0C67E2382AD5DAEF74F`。结果：`C:\Users\xiemo\Desktop\ShardForge\tmp\review_20261005\smooth_candidate\FAILURE_ANALYSIS.md`。

**文献检索：** 待检索 OCP/Open CASCADE geometry-only bounds 对三角化缓存的保证，以及 STEP 几何 roundtrip、拓扑/语义保真和字节级保真各自的既有定义。

## VF-02 — CAD deflection、h、t、δ、λ 分尺度

**问题与决策。** 分开记录 CAD chord deflection、tet-edge/点间距 `h`、局部壁厚 `t`、PD horizon `δ`、process-zone 尺度及浮雕/粗糙度最小波长 `λ_min`。至少报告 `h/t`、`δ/h`、`λ_min/h`；CAD deflection 不充当 `h` 或 `δ`，单报 `δ/h` 也不能替代壁厚/细节分辨率检查。`h` 与 `t` 同数量级时不判为高质量离散。

**可证伪验证。** 对冻结同一物体分别固定 `δ` 改变 `h`、固定 `h` 改变 `δ`，另用固定几何扫描 CAD deflection；每组记录局部 `t` 和 `λ_min`、生成网格及观测到的纹样/壁厚误差。若报告无法分别追溯各尺度，或改变一种尺度却把另一种尺度当作等价代理，判 FAIL。阈值与收敛标准待预注册。

**现有证据与状态。** 方案审计已经写明这些尺度须分列并报告比例。Ornament 独立补充报告明确指出 20 mm fan chord/三角形质量不是 mechanical relief height `h` 或 fracture criterion；几何 mm 度量与物理离散尺度必须分开。没有本轮尺度扫描或收敛结果，阈值/物理充分性仍 `UNKNOWN`。

文件：`C:\Users\xiemo\Desktop\ShardForge\tmp\review_20261005\plan_inventory\structural_audit.json`；来源方案 SHA-256 `15978a3956fa33e8048cc54c1dad6878a7e19d9c71b84415dcaf8732f041a3b4`。实验冻结 SHA：`UNKNOWN`。

**文献检索：** 待检索 PD horizon/discretization 收敛、壁厚与裂纹过程区分辨率、CAD 曲面/浮雕离散误差；现有分尺度要求不是新颖性结论。

## VF-03 — 局部连续 relief lineage 与有限近似

**问题与决策。** relief/刻纹/材质先属于完整母体的局部连续表面字段，再按碎片域继承映射与版本 lineage；不为每片独立随机贴图。连续字段只是生成/语义定义，网格、纹理或渲染采样始终是有限近似，需报告分辨率与误差，不能宣称有限采样等同数学连续表面。

**可证伪验证。** 固定母体字段、映射版本和 seed；在同一父曲面坐标处比较跨断口相邻片的 relief/material 取值及边界导数，并随离散/纹理分辨率加密记录误差收敛。丢失父 lineage、接缝跳变超过预注册误差，或加密后误差不收敛，均反驳当前实现假设。

**现有证据与状态。** V1.46 方案说明纹样须先存在于完整母体，碎片继承并保留结构化语义。已存在的只读 Ornament lineage supplement 对两组冻结有限网格重建了全部 face-corner 与新增 vertex lineage，outer chart 最大残差 `1.7763568394002505e-14 mm`；expanded outer color 样本不是 bitwise 相同，最大绝对差 `1.11e-16`，低于原记录的 `1e-12` 容差。whole-mesh min Q `0.0849` / max aspect `20.38` 位于 base radial fan；较细样本 unornamented body max aspect `8.0014`（粗样本 `4.0007`）。这些是保存网格上的 lineage/形状检查，不是连续曲面证明、CAD/generator 执行、机械 relief 高度 `h` 或 fracture 验收。连续字段跨真实断裂的局部 lineage 与有限近似收敛仍 `SOURCE_ONLY / UNKNOWN`。

文件：`C:\Users\xiemo\Desktop\ShardForge\tmp\review_20261005\plan_inventory\extract.txt`（源方案 SHA-256 `15978a3956fa33e8048cc54c1dad6878a7e19d9c71b84415dcaf8732f041a3b4`）；`C:\Users\xiemo\Desktop\ShardForge\vesselforge\tmp\review_20261005\ornament_independent_review\supplement_report.md`；`C:\Users\xiemo\Desktop\ShardForge\vesselforge\tmp\review_20261005\ornament_independent_review\supplement_receipt.json`；`C:\Users\xiemo\Desktop\ShardForge\vesselforge\tmp\review_20261005\ornament_independent_review\supplement_input_sha256.json`；supplement source `C:\Users\xiemo\Desktop\ShardForge\vesselforge\tmp\review_20261005\ornament_independent_review\lineage_geometry_supplement.py` (SHA-256 `b7efeedcc1ae43e852a14ea69ea730932423475514a26357d07144dd0186bb4a`)；reviewed prototype `C:\Users\xiemo\Desktop\ShardForge\vesselforge\experiments\surface_ornament_refinement_20261005\refinement_prototype.py` (SHA-256 `5e946c205fb233e9354dfdde10d562597484ee38193e7930f93ce999f5840f74`)。Input hash manifest SHA-256 `96cf8aadca22b21f6fd98e9ba7beff7bcb1490596d8b6b2c9045751b741cc6b7`；baseline SHA-256 `b44bb78176e690d8bc92ab2fc10f0803e142a0311acee8ff3944d4e324b9b974`；两组 candidate SHA-256 `ac3c7da3dda89ab2e6d26b997a05d4d693384626f44e0d5154c061824d2e87e6` / `8a2539dff0a05444951ecae6bd66ba2d849c753764dc635a4bacdf8382c6cfdf`。supplement report SHA-256 `952c634eac7cda72b6ad1589e210b827d91b663b02c4394d2a5864042e9e2e9e`。连续 relief 实现/实验冻结 SHA：`UNKNOWN`。

**文献检索：** 待检索 CAD/B-rep 参数曲面上的 relief lineage、跨断裂纹样延续、有限网格/纹理近似误差；无新颖性结论。

## VF-04 — rounded rim 曲率约束的条件性不可达假设

**问题与决策。** 对旧 `2.5 mm` 水平端点间隔配置，若 rounded-rim 中心线是凸的平面半周转（总转角 `π`）、两端因 C2 接直线而有 `κ=0`，则要求全曲线 `R_min ≥ 1.25 mm` 不可达：在 `|κ|≤1/1.25` 下半周宽度下界为 `2R=2.5 mm`；取等号要求内部几乎处处为恒曲率圆弧，与端点连续零曲率冲突。该条件性不可行结论只对应旧 `2.5 mm` 配置，不代表后来加宽到 `3.5 mm` 的 v2 lip 仍不可行。

**决策。** 保留曲率门槛，不通过放宽门槛隐藏 infeasible。旧 `2.5 mm` 组合的不可能性以凸性、半周转及端点条件为前提；后续 v2 实际把 lip 的水平 endpoint gap 加宽到 `3.5 mm` 并给出精确凸单转弧证书。不得把该解析剖面结论写成 CAD 修复或真实器壁资格。

**可证伪验证。** 作者先确认切向累计转角、曲线凸性、端点曲率条件和 gap 的几何定义；再对同一冻结端点 jets 给出完整曲率界/可行构造或不可能性证明。只看离散采样的 `R_min` 不足以证明全曲线通过。

**现有证据与状态。** 旧 Beaker 的圆角采样半径约 `0.916 mm`，STEP 门通过但一条法线射线 UNKNOWN。之后 v2 把 mouth transition 的水平 endpoint gap 改为 `3.5 mm`，记录 exact regular convex one-turn/no-inflection lip certificate，且有限采样最小半径 `1.456012678 mm`；这通过固定的有限采样 `1.25 mm` 门，但不是 CAD 实体或 whole-curve curvature-bound 证明。v2 inner-base 第二 span 仍以 `0.742951260 mm` 失败，之后的 single-quintic inner-base math candidate 有单弧精确证书及有限采样半径 `3.377668938 mm`。旧 `2.5 mm` 假设与新 `3.5 mm` 运行分别记录，不混同。之后一次 root 授权的 native CAD pilot 在该 single-inner candidate 上通过窄 topology/STEP/face-identity 门：一闭壳/一实体、19 faces，STEP 往返 57,660 bytes；1e-7 mm face inventory identity 通过、geometry-only bbox delta 为 0。此结果不证明截面无自交、全局法向壁厚、style/material 或 physics；normal-wall checker 与 wall-mesh binding 未运行，global self-intersection `UNKNOWN`，root 原生视觉复核待完成。

基线收据：`C:\Users\xiemo\Desktop\ShardForge\tmp\review_20261005\smooth_candidate\FAILURE_ANALYSIS.md`；候选源 SHA-256 `359DC041B521799C39A08ED1F2A680A192EECC234FD8E47845511CAE58048D8E`、fixed-case SHA-256 `9AFDFC764C28FC73932598B38A1A36DB56642864F620B0C67E2382AD5DAEF74F`。新 feasibility 论证/修复源 SHA：`UNKNOWN`。

**文献检索：** 待检索受约束曲线公平化、曲率半径界与端点 jet 可行性；数学可行性先由作者核实，文献检索不替代该证明。

**冻结 RZ 数学诊断。** v2 单次诊断的 exact non-axis C2 与控制约束通过；convex one-turn lip 的有限采样最小曲率半径 `1.456012678 mm` 通过 `1.25 mm` 门，但 inner-base 第二 fairing span 为 `0.742951260 mm`，在不调参、不放宽门槛下失败，run status `PURE_MATH_DIAGNOSTIC_NEEDS_REVIEW`、exit 2。root 查看实际 RZ 后发现 inner-bottom 中间 station 造成 S 形；随后 root 批准单 quintic end-jet 候选，保留两个端点 jets 和旧两段总 parameter width `0.8`。该候选一次 math 与 PNG 运行均 exit 0；单内底 span 的最小采样曲率半径为 `3.377668938 mm`，大于固定 `1.25 mm` target，并通过 exact derivative/curvature Bernstein sign 证书，run status `PURE_MATH_TARGETS_MET_FINITE_ONLY_WITH_EXACT_INNER_BASE_CERTIFICATE`。这只证明单弧局部性质，不证明完整截面简单、自交不存在、全局法向壁厚或 CAD 体有效。

文件：v2 结果 `C:\Users\xiemo\Desktop\ShardForge\tmp\review_20261005\smooth_coupled_design\frozen_run\RESULTS.md`；v2 freeze 清单 `C:\Users\xiemo\Desktop\ShardForge\tmp\review_20261005\smooth_coupled_design\FROZEN_SHA256.txt`（math source `4a90264b83e465af8bdb4dc7771f61ab4cb8314bc8d4d0ef540952310f3cb85b`，fixed case `7e65d490c5cf1a5fa80d9964b1c89392c06a30290768bf00bfad03b4e757d391`）；single-span review `C:\Users\xiemo\Desktop\ShardForge\tmp\review_20261005\smooth_single_inner_fairing\REVIEW_AND_EXECUTION_BUDGET.md`；frozen results `C:\Users\xiemo\Desktop\ShardForge\tmp\review_20261005\smooth_single_inner_fairing\frozen_run\RESULTS.md`；run record `C:\Users\xiemo\Desktop\ShardForge\tmp\review_20261005\smooth_single_inner_fairing\frozen_run\diagnostic_run_record.json`；plot record `C:\Users\xiemo\Desktop\ShardForge\tmp\review_20261005\smooth_single_inner_fairing\frozen_run\plot_run_record.json`；PNG hashes `C:\Users\xiemo\Desktop\ShardForge\tmp\review_20261005\smooth_coupled_design\frozen_run\RUN_OUTPUT_SHA256.txt` 与 `C:\Users\xiemo\Desktop\ShardForge\tmp\review_20261005\smooth_single_inner_fairing\frozen_run\RUN_OUTPUT_SHA256.txt`。Single-span math source SHA `f3315ac8d1fc112f4dc0af4bb4cea86dddd262052bcbc94c6f776780aefbbec8`，fixed case SHA `2d7a0950f870a8663f7e326275e3c666d880e906d04fccbcd0f1ba7d453fd3c0`；math diagnostics SHA `88b09514619fa62e1df1afb4954d4be14275b3907fad76ba13749c066933b550`，single-span plot PNG SHA `8bbe41a5c3e6b78ba220b6f5b181f195a44e88f17addeea86b943d095c81e147`，v2 plot PNG SHA `abdd6cdfbcf3eba83d625a73aa9663f45d7c6b7848e4944384ee8131af131d33`。实际 viewed RZ PNGs：`C:\Users\xiemo\Desktop\ShardForge\tmp\review_20261005\smooth_coupled_design\frozen_run\plot\coupled_profile_rz.png` 与 `C:\Users\xiemo\Desktop\ShardForge\tmp\review_20261005\smooth_single_inner_fairing\frozen_run\plot\single_inner_fairing_profile_rz.png`。

Native CAD receipts and output: `C:\Users\xiemo\Desktop\ShardForge\vesselforge\experiments\smooth_surface_native_adapter_20261005\tmp\runner\single_inner_native_01\runner_receipt.json` SHA-256 `f1c263cb53f0a332dae352299b3617854c92efefef66ca104d7f4d98b109e60d` (49,488 ms, exit 0); `C:\Users\xiemo\Desktop\ShardForge\vesselforge\experiments\smooth_surface_native_adapter_20261005\tmp\runs\single_inner_native_01\run_receipt.json` SHA-256 `4c17fe03c74a6fe4474d98b3de9305916572910247c64bd144189ca2c3f711c8`; resulting `C:\Users\xiemo\Desktop\ShardForge\vesselforge\experiments\smooth_surface_native_adapter_20261005\tmp\runs\single_inner_native_01\candidate.step` SHA-256 `9a6ac86efb2d714e5d2d737263307014487fe2e45979c4181f6071c6f0cf6c71`. Adapter source SHA-256 `7d745f48111d24b38a288714b580c0eefe55415b2998351bf6144fa1cf4dab76`, run input freeze-manifest SHA-256 `35fe13502da52b67ae3d7a15ce1b7566f050ab339f04cd9708c7ee56b7ed82f4`, root review/one-run approval SHA-256 `4be5467f4ba6cad657e4de2eda20d772a9d69fab809aa22d4d294f5a5bd76b4b` / `4e3e1dd952ba16a67dc0eda9298b4427f76e997f28a3375dff973f8a91a233cd`。该 run 只做 1 native body build、1 STEP export/import，0 mesh generation、0 normal rays、0 solver runs；视觉复核仍 pending。

## VF-05 — floor-fan 全局重三角化的 multi-parent overlay 谱系

**问题与决策。** Ornament 保存 candidate 的 whole-mesh 最差 `Q=0.0849`、max aspect `20.38` 位于平面 bottom radial fan；重铺该 floor fan 时，新 triangle 可能跨越多个旧 radial sectors。必须用精确裁剪/overlay 记录每个输出 triangle 覆盖的全部 source patches、面积和双侧重建映射；不得用 centroid parent 把跨父面 triangle 假装成单父面。legacy single-parent 行只在一个源三角形完整覆盖输出面时有效，多父面须显式 schema-v2 状态与 patch lineage。

**可证伪验证。** 对冻结 baseline 与 local-B 输入执行一次候选构造后，独立 readback 重建每个 patch 顶点的 source/output barycentric 坐标，检查 patch 面积覆盖无重叠、floor polygon 面积不变、整体 topology/volume 与实际三角形 Q/aspect，并验证外表 relief/color 与输入谱系。任何 overlay 漏片、面积重叠/缺口、单 centroid 归属，或旧 reader 把 schema-v2 sentinel 当作正常 source ID，均判 FAIL。生成前须先隔离旧 schema-v1 readers，或令其遇到明确缺失 keys 时硬拒绝。

**现有证据与状态。** 独立静态 review 确认方案使用逐三角形 clipped multi-parent patches（不是 centroid owner）；旧 `source_face_ids=-1`/NaN legacy barycentrics 可能被旧 reader 当作负索引，root 决定 revised source 改用明确命名的 v2 keys。随后唯一一次 generation attempt 用时 `2.015211 s`，receipt 状态 `UNKNOWN_OR_FAIL`、错误类型 `CandidateUnknown`，在 local-B base colors 与 frozen continuous field 的断言处停止。这个失败位置及根因尚待只读诊断；没有可报告的 mesh-quality PASS，不能说质量改善或生产集成。新 floor vertex lineage 的完整 focused readback、global self-intersection 与 normal wall 仍 `UNKNOWN`。

文件：`C:\Users\xiemo\Desktop\ShardForge\vesselforge\experiments\global_mesh_quality_candidate_20261005\SOURCE_REVIEW.md`；静态审阅 `C:\Users\xiemo\Desktop\ShardForge\vesselforge\tmp\review_20261005\global_mesh_quality_independent\static_source_review.md`；修订静态审阅 `C:\Users\xiemo\Desktop\ShardForge\vesselforge\tmp\review_20261005\global_mesh_quality_independent\revised_static_source_review.md`；source freeze `C:\Users\xiemo\Desktop\ShardForge\vesselforge\experiments\global_mesh_quality_candidate_20261005\SOURCE_FREEZE.json` SHA-256 `09b972cdc1c04698b12f01acd88479a564ce03b0bf1ff68af2e9979e4e104b17`；attempt receipt `C:\Users\xiemo\Desktop\ShardForge\vesselforge\tmp\review_20261005\global_mesh_quality_candidate\run_receipt.json` SHA-256 `ae9501ec085e5c22419bcc09a99c91d209fe28c54a16035d9de110e8faab3bc9`。该 pre-attempt freeze 中 candidate/focused-checks/contract SHA 为 `3a3a9c5a82cf936d3611ccffdfc6956331f3ba6514114b1905ff76e3254f4445` / `35ca4504cb161bd5780c0d9f6e7df53eea72b51e7fd0a8486dcea62d92bc5c65` / `b804e6089d4553dcc393dfc866f0e92f8f4dd0bf4d38c4bded433103328cd998`。历史较早版本的 hashes 仅对应 earlier snapshot，不作为本次 attempt 的 source freeze。local-B assertion 上游 source SHA `8a2539dff0a05444951ecae6bd66ba2d849c753764dc635a4bacdf8382c6cfdf`、check SHA `4e4c08b96bd6e7dd47a3285377979fc93fc3865a0bc1fcdd48d79397c23e14e8`。冻结源/收据没有给出独立质量结果。本轮只读工作树哈希核对时间为 2026-10-05 10:18 UTC：当前 `SOURCE_FREEZE.json` SHA-256 `47dbd74954126eecb648b3ee693cf1877150404f4db3aef06d9c338c194867e3`、`candidate.py` SHA-256 `9fa7ed881d30444dba545d3b1f6b3fd12e08faf8bd77cfdd0f124d002499cd5e`、`focused_checks.py` SHA-256 `35ca4504cb161bd5780c0d9f6e7df53eea72b51e7fd0a8486dcea62d92bc5c65`；当前 manifest/candidate 已不同于失败 attempt 的历史冻结值。这里只记一次读时快照：后续源修订未重跑、未读回，根因仍待只读诊断，不把新源倒灌为失败运行输入。

**文献检索：** 待检索三角网格 overlay/patch lineage、跨父面颜色/参数连续性与全局质量度量；这些工程决策尚非新颖性结论。

## VF-06 — 96-cell B-rep volume ingress diagnostic 与 blocked report finalization

**问题与决策。** 对 VF 几何做受限 96-cell ROI 的 OCP B-rep solid/cell common，另算 solid/ROI reference common；只有正体积 components、严格 `IN` centroid、拓扑和 cell-sum/reference 体积对照通过后，才允许形成局部点集。局部几何门不等于完整母体离散、surface-parent lineage、PG 原生接入或物理材料资格。报告终结/预算失败时保留 stage 并阻断晋升，不从 partial pointset 推断 worker PASS。

**可证伪验证。** 对冻结资产运行唯一固定 ROI 与 `h=0.5 mm` 测试；确认 96 cells、每个正 component 的 OCP classifier 为 `IN`、体积总和对 ROI common 在预冻结容差内，密度×体积与 emitted mass 一致；必须同时取得稳定 final ingress report、父子 receipt 和 stage inventory。独立解析/图片审阅后才能接受有限 geometry diagnostic。任一 cell 漏记、`ON/OUT/UNKNOWN` 混入正点集、体积/质量超容差、report finalization 失败或 stage 被错误晋升均为 FAIL/BLOCKED；不得自动重跑或把局部诊断升格为 full-mother/physics claim。

**现有证据与状态。** root 授权的一次 bounded run 已处理 ROI `[7.5,10.5] × [-1,1] × [4,6] mm` 的 96 个 cells：80 个正 component/point，16 个 zero intersection，0 blocked；80/80 centroid 为 `IN`、component topology 均 PASS。reference common 为 `8.01676271854943 mm³`，96-cell sum 为 `8.016762718544449 mm³`，差 `−4.980904577678302e−12 mm³`（低于冻结 `8.01676e−8 mm³` tolerance）；density `2100 kg/m³` 下 point mass sum `1.6835201708943335e−5 kg`。这些只是在失败 report run 中恢复出的 raw local geometry ledger。worker child exit 0，但外层 supervisor exit 2；原因是 `_write_final_report` 无法稳定包含 report 的输出总字节数，`ingress_report.json` 未产生。partial stage `.forge_ingress_stage__2srs6ad` 保留，325,188 bytes（低于 20 MiB）；parent/worker failure receipts 实际在 stage 中。source/input hashes 前后不变，run 禁止 rerun。独立 raw parse 与 PNG 审阅 pending；root 同意审阅后最多有限接受 local geometry diagnostic。pipeline 当前 `BLOCKED`，pointset 未晋升；source semantic projection、surface parent mapping、candidate pair classification、native PG-Frag integration、full-mother conservation、global wall、mechanics calibration、physics-ready 均 UNKNOWN/未连接。该源不提供新颖性或 production claim。

文件：final source review `C:\Users\xiemo\Desktop\ShardForge\pgfrag\tmp\review_20261005\forge_volume_ingress_independent_review\FINAL_SOURCE_REVIEW.md` SHA-256 `4772135b732c80166f1a5c1bbd9fc758a9a886884ca566290af184e427d59566`；运行摘要 `C:\Users\xiemo\Desktop\ShardForge\pgfrag\experiments\forge_volume_ingress_20261005\tmp\candidate_run01_supervisor\pilot_results_summary.md` / `.json` SHA-256 `c93d1160fbdffff2e0d4cff3ca7a9a17a1415666141aba04581fbbceac3579de` / `391ae016166451f1135c0467cb90d24bfe751a3f39c199d1561705039d678213`；supervisor receipt `C:\Users\xiemo\Desktop\ShardForge\pgfrag\experiments\forge_volume_ingress_20261005\tmp\candidate_run01_supervisor\final_receipt.json` SHA-256 `721f5021b248afe5d3eb14e32cff0d6edc7a3a03a535ad36588e2c5e71f8cf4c`。本次 source snapshot freeze SHA-256 `3b29580e4470cfa3016968eb784cd5b1ab9c02e832a2ce1bf5dee57c2a2a5538`；该 run worker SHA-256 `be02c2914b3459b727b43d9969b95efeb07b014768ac68d9ab39bbba8da602d5`（保留的 `source_snapshot_before_report_fix`；当前 worker SHA 不作为旧 run 的执行 source）。contract SHA-256 `7151df72d082b0d1d728f86aa118c3f396a4d6a3e545fbf5dc76f37a7118c6f7`；failed-stage parent receipt SHA `97310270be5a002b78e24b75e61d3f8c301f66b8c3095ddef61caf475f2a6bb5`，worker failure SHA `5eb4c9739430bf1f9a26e8ce6f51d0d951e879791fe10a2f37fa586a8a6c5e1e`。source worker/report finalization 之后的更新状态不回写到原失败阶段或本次运行。

**文献检索：** 仅待检索 CAD B-rep cell intersection/volume clipping 的同类 ingress 基准及材料积分误差；本次单一 bounded geometry diagnostic 不是新颖性或一般收敛证据。

## PG-01 — geometry/material/visibility 初始化，不伪造 precrack

**问题与决策。** 把几何可见性从物理断裂状态分开。geometry/material mask 必须在 native bond graph、邻居计数、halo、kernel 与 correction 初始化前应用；被排除的几何 pair 进入独立 exclusion ledger。保留的物理键初始 active、damage 为零；solver 的 `precrack!` 只表达真正预置裂纹，不能模拟空腔/可见性排除。传输决策改为 Julia stdlib `TOML` + `SHA` 的 immutable typed-TOML policy；Python JSON 保留为审计产物，native policy 持有不可变 TOML 字符串和摘要，不引入 JSON3 解析依赖。

**可证伪验证。** 固定 hollow CAD 与有序点表，逐键对比完整 native Euclidean candidate set、mask 和 native readback；跨空腔 pair 在双向 graph 均缺席、同壁材料 pair 留存、初始 active/damage 合约成立，且 exclusion 不出现在 fracture-event ledger。任何未知 pair 被静默初始化、计数或 correction 未重建，判 FAIL。

**现有证据与状态。** bridge contract suite 有一份实际执行收据：2026-10-05 04:48:45–04:48:46 UTC，pytest exit 0、manifest 汇总 12、0 failure/error；JUnit 实际列出 9 个 testcase/node ID，另 3 个是 subtests，故按 9 个独立用例加 3 个子例报告。bridge 与 test 的 pre/post SHA 不变，分别为 `67b8f3090abebb093b7a1e099059c35c2ae09890b4f6b78453dd44d8a6ad4085` 与 `cb9c9b62214c6be2f5d9368d8ff9498f90a16c16537e135d9dd4a7c1e9cd09d07`。这只支持静态 contract suite 的窄 PASS。独立审阅发现 static ledger 不重建完整 Euclidean horizon candidate set，也不由所给 horizon 验证距离；漏掉的候选（包括 UNKNOWN）不能触发阻断。新的 JSON→TOML compiler 未测试，`pinned_fork_initial_bond_policy.patch` 未应用，native policy 未启用，也没有 native graph 初始化/readback。因此 `NATIVE_GEOMETRY_GATE_PENDING`，几何可见性初始化仍 `UNKNOWN`。

文件：`C:\Users\xiemo\Desktop\ShardForge\pgfrag\experiments\material_visibility_native_bridge_20261005\README.md`；设计 patch：`C:\Users\xiemo\Desktop\ShardForge\pgfrag\experiments\material_visibility_native_bridge_20261005\pinned_fork_initial_bond_policy.patch`；审计 JSON schema：`C:\Users\xiemo\Desktop\ShardForge\pgfrag\experiments\material_visibility_native_bridge_20261005\mask_contract.schema.json`；执行清单：`C:\Users\xiemo\Desktop\ShardForge\pgfrag\tmp\review_20261005\bridge_contract_tests\run_manifest.json`；JUnit：`C:\Users\xiemo\Desktop\ShardForge\pgfrag\tmp\review_20261005\bridge_contract_tests\bridge_contract.junit.xml`；独立静态审阅：`C:\Users\xiemo\Desktop\ShardForge\pgfrag\tmp\review_20261005\bridge_independent_review\review.md`。运行绑定的 bridge/test SHA 如上；TOML compiler、fork patch 与 native graph 的执行/冻结 SHA 仍 `UNKNOWN`。

**文献检索：** 待检索 peridynamic graph construction、自由表面/空腔邻接、初始裂纹与几何 void 表示；设计接口不等于 native capability。

**待核源状态。** root 另报告 `ROI96` ingress 的 final source review 已通过、一个 CAD test 曾获单次授权；对应记录现由 VF-06 的实际失败报告说明。该单次 run 的最终 pipeline 状态为 `BLOCKED`，不是 source approval 或 worker geometry 子状态的 PASS。native material-visibility policy 仍只在 TOML design source 中，patch 未应用、native graph 未验证。

## PG-02 — native VelocityVerlet 离散 BC impulse 与 surrogate

**问题与决策。** 报告 native 离散边界约束冲量 `J_BC = m(v_half,after_BC − v_half,predicted)`；`J_BC/Δt` 是该步平均约束力，不是连续端面牵引。约束速度替换造成的动能跳变量单列为离散边界功。force-displacement trapezoid 保留为命名含 `surrogate` 的诊断值，不纳入能量残差；半步/整步交错也使残差只能作为诊断。

**可证伪验证。** 实际 native run 逐步保留 BC 前后半步速度及全步状态；验证无 BC 自由分量冲量在舍入限内、动量改变量与 native `(b_int+b_ext)V` 积分加 `J_BC` 相符，并分别输出两种 work 数值，确认 surrogate 不进入能量闭合项。改变 `Δt` 后仍须按原生时间层定义复核。

**现有证据与状态。** 冻结的 native reversible coupon 已执行：4,500 点、49 状态/48 intervals、`dt=7.5e-8 s`，launcher 43,035 ms、native exit 0；`failure_enabled=false`，末态 inactive native bonds 为 0，因此没有断裂。记录包含 native BC impulse、整步动量及两种 work。独立审核的 20 项 arithmetic/state 检查通过：free-DOF impulse residual 为 0，momentum identity 最大残差 `2.6402e-18 kg·m/s`，grip path 最大误差 `1.90e-21 m`。最终 residual `3.5650704e-5 J`，约报告 final total 的 `7.1826%`；短 dwell 采样段最大自由点速率 `1.808 m/s`。root 后续指出：velocity BC 改写 `v_half` 后，native force update 给出 `V_full = v_half + a_n Δt/2`，因此 held-grip position 与 `v_half=0` 不推出存储 `V_full=0`。既有 all-point kinetic-energy 重算只应视为 raw solver diagnostic，不是受约束 DOF 的 physical KE；作者正分开报告 free/constrained raw KE 并收窄 dwell wording。再加上 Verlet 半步/整步错位，不能称 energy closure 或 dwell stationarity。surrogate force-displacement trapezoid 不进入 residual。root 阅读独立报告、复算 source 关键值并查看两张实际 PNG，只接受 baseline 工程算术和加载路径完整性。`dt/2` companion 已有 exit-0、96 steps/97 states 收据且实际 `dt` 为恰好一半；专属独立 audit 正在进行，暂不报告精度比较结论。材料校准、表面修正资格与 fracture energy 仍 `UNKNOWN`。

文件：`C:\Users\xiemo\Desktop\ShardForge\pgfrag\experiments\free_evolution_coupon_20261005\SOURCE_REVIEW.md`（运行前文档，`SOURCE_ONLY_NOT_RUN` 标签早于下列收据）；`C:\Users\xiemo\Desktop\ShardForge\pgfrag\experiments\free_evolution_coupon_20261005\run_attempt_01\launcher_receipt.json`；`C:\Users\xiemo\Desktop\ShardForge\pgfrag\experiments\free_evolution_coupon_20261005\run_attempt_01\results\summary.toml`；独立审核 `C:\Users\xiemo\Desktop\ShardForge\pgfrag\tmp\review_20261005\free_coupon_independent_review\independent_review.md`。基础 run source-freeze SHA `3d0a3cadf244eeb4612ec8999a9328b4be06cd087e16b08a731551250a4614b2`，driver SHA `bea71ad8c9c224180bfd544913646b281cf35e0c6644971ba3746d1e2af488af`，fixed-case SHA `e6aa57f3edf136970e9f7108a1df2535a1e7c0d4cb56ee89fee8d858cd3c603d`。`dt/2` companion 收据：`C:\Users\xiemo\Desktop\ShardForge\pgfrag\experiments\free_evolution_coupon_dt_half_20261005\run_attempt_01\launcher_receipt.json`；比较记录：`C:\Users\xiemo\Desktop\ShardForge\pgfrag\tmp\review_20261005\native_resume_dt_half\one_shot_execution_20261005\baseline_vs_dt_half_comparison.json`；其 source-freeze SHA `684439db34e2375d5996eed0dd1d518a413565cbaf92cd96a42f4d3799c70aef`、fixed-case SHA `7baee8e2efeca485927f8f265409ca35656731e39fba75cd7d95a6a2a47c2323`、driver SHA 与基础 run 相同。VelocityVerlet 与 velocity BC 源 pin 分别为 `584f0afbb1d0cd9808bfeb56d128327d28f7eca486666ffe2a7bbc6feeea48d6` / `eca99fbf67cf5169a0ea8e34f72b949f3b607155b4a5837cfea1b2a000d264e`。

**文献检索：** 待检索 VelocityVerlet 离散运动学约束冲量、半步能量记账及 reaction force 定义；本文当前区分是对 pinned solver 的工程量定义，不声称新方法。

## PG-03 — 固定物理时间输入与完整 typed-binary 上限

**问题与决策。** 按固定物理秒数定义 `u(t)` 的 ramp/hold/unload/dwell；phase step count 的 ceil 不能悄悄拉长物理时长。将 21 个 Float64 值/点/状态写成一个 typed binary tensor，启动前核算完整二进制并限制在 `≤200 MiB`。同一连续物理时间路径须原样用于 `dt` 与 `dt/2` 对照。

**可证伪验证。** 在 solver 前按实际 dtype、点数、捕获状态数和 `[21, point_count, state_count]` shape 精确计算序列化字节数并保存预算收据；超过 200 MiB 必须在 solver 启动前拒绝。冻结后用运行时间戳证明 `u(t)` 按指定秒数取值，phase 边界没有因 ceil 步数发生累计漂移；预算与实际 payload 字节数须一致。

**现有证据与状态。** 基础 run 已冻结执行：连续物理秒数 ramp/hold/unload/dwell 为 `1.0/0.6/1.0/1.0 µs`，总时长 `3.6 µs`；`dt=75 ns`、48 intervals，采样末时刻无可见 overrun。独立 audit 在 49 个状态验证 grip path 最大误差约 `1.90e-21 m`。保存 21 个 Float64/point/state（6 个三分量历史量加 3 个 scalar），shape `[21,4500,49]`，little-endian tensor 恰为 `37,044,000` bytes；实验输出 `37,620,554` bytes，低于 `199,229,440`-byte output cap 和 `209,715,200`-byte attempt cap，launcher exit 0、43,035 ms。该收据只验证这个固定 case 的路径采样与二进制预算执行，不证明时间步收敛、物理精度或格式的一般性。`dt/2` companion 收据显示 `dt=37.5 ns`、96 intervals、binary `73,332,000` bytes、exit 0，comparison 为 `MATCHED_DT_HALF_DIAGNOSTIC_ONLY` 且确为恰好半步；独立数值审计正在进行，准确性/收敛状态仍 `UNKNOWN`。不据此推断 CSV 字段或 CSV 数量未实现。

文件：`C:\Users\xiemo\Desktop\ShardForge\pgfrag\experiments\free_evolution_coupon_20261005\SOURCE_REVIEW.md`；`C:\Users\xiemo\Desktop\ShardForge\pgfrag\experiments\free_evolution_coupon_20261005\source_freeze.toml`；`C:\Users\xiemo\Desktop\ShardForge\pgfrag\experiments\free_evolution_coupon_20261005\run_attempt_01\launcher_receipt.json`；`C:\Users\xiemo\Desktop\ShardForge\pgfrag\experiments\free_evolution_coupon_20261005\run_attempt_01\results\summary.toml`；`C:\Users\xiemo\Desktop\ShardForge\pgfrag\tmp\review_20261005\free_coupon_independent_review\independent_review.md`；`C:\Users\xiemo\Desktop\ShardForge\pgfrag\experiments\free_evolution_coupon_dt_half_20261005\run_attempt_01\launcher_receipt.json`；`C:\Users\xiemo\Desktop\ShardForge\pgfrag\tmp\review_20261005\native_resume_dt_half\one_shot_execution_20261005\baseline_vs_dt_half_comparison.json`。基础源 freeze/driver/case SHA 见 PG-02；`dt/2` freeze/driver/case SHA 为 `684439db34e2375d5996eed0dd1d518a413565cbaf92cd96a42f4d3799c70aef` / `bea71ad8c9c224180bfd544913646b281cf35e0c6644971ba3746d1e2af488af` / `7baee8e2efeca485927f8f265409ca35656731e39fba75cd7d95a6a2a47c2323`。

**文献检索：** 待检索与本文决策直接相关的数值时间采样/输出预算无需借文献背书；任何求解器时间精度或稳定性主张仍须单独检索和验证。

## PG-04 — 几何真值使用 mechanics-coupled explicit surface；OSB 保持事件诊断

**问题与决策。** native OSB/CriticalStretch 的 active-to-inactive bond transitions 是该模型的离散事件记录，不包含 off-grid crack surface、front、surface side-pairing 或 fragment faces。root 选择 B：把 mechanics-coupled explicit crack-surface branch 作为后续 geometric-truth producer；原生 OSB pilot 继续作为独立 event diagnostic，不把 cell-interface/reconstruction proxy 冒充 native crack。已发表的 2018 adaptive cracking-particle method 只作为 LEFM benchmark 的既有 formulation 起点；不主张本工程选择具有新颖性，也不声称其已有 production implementation。新增 primitives/front/surface state 源仍 `SOURCE_ONLY / PENDING`，本记录未定位到已执行实现或 source freeze。

**可证伪验证。** 按决策文件重现所选已发表 formulation 的 3D inclined penny-crack LEFM benchmark，先冻结边界、增长规则和 reference comparisons；做一次局部加密与旋转 point-layout 比较。必须证明显式表面在求解中改变 mechanical support/interaction visibility 与演化，而非只在事后拟合；保存 immutable surface ID、材料参考坐标、side signs、creation step、两侧位移映射，并将同一表面导出。若 export surface 与求解时表面不一致、旋转/加密改变超出预注册误差的路径，或只凭 OSB events/graph components 产出 crack faces，几何真值主张 FAIL。能源和材料校准另过门，不由 LEFM benchmark 自动通过。

**现有证据与状态。** Astra decision 选择 B 并保留 OSB native failure 为 diagnostic，method audit 说明 bond events 不能确定连续裂纹几何。唯一 native free-fracture pilot 实际执行：4,500 点、96 intervals/97 states、`dt=37.5 ns`、3.6 µs fixed-physical-time path；launcher `COMPLETED_EXIT_0`、39,962 ms、result authoritative、输出预算通过。native OSB/CriticalStretch 记录 6,810 canonical bond failure transitions；第一事件在 step 4、`t=1.5e−7 s`。完整 rectangular grid、无 notch/point-removal/precrack/CAD，failure 启用且无手动 bond edit。root 从 graph labels 报告末态 2 connected components、largest component 约占总质量 95%；它仍是 graph-connectivity diagnostic，不代表两片实际 fragments，也没有 crack surface。root 的事件/视觉独立复核 pending。`NoCorrection` surface truncation 未校正、材料未校准、energy ledger `DIAGNOSTIC_ONLY`、fracture dissipation `NOT_COMPUTED`；不推导实际断裂能、真实陶瓷响应或 production readiness。几何表面 B branch 仍只有决策与论文基准提案，无源 freeze/实现/运行。

文件：Astra architecture decision `C:\Users\xiemo\Desktop\ShardForge\pgfrag\tmp\review_20261005\astra_crack_surface_architecture\DECISION.md` SHA-256 `284c444662960b2f15d8ae99d61aed2b25091048ff3c104dce72d2139f6d3b47`；机器可读 decision `C:\Users\xiemo\Desktop\ShardForge\pgfrag\tmp\review_20261005\astra_crack_surface_architecture\decision.json` SHA-256 `3c24782b308b40b9bb4e5cfb6d803c9a20adff0adc2f38cbf7789adaedeb849e`；crack surface method audit `C:\Users\xiemo\Desktop\ShardForge\pgfrag\tmp\review_20261005\crack_surface_method_audit\AUDIT.md` SHA-256 `60067293891c269d08a3f55a167f56a89471e67492039b147cd5da0351e3aa88`。Native pilot freeze/source/case SHA-256 `1f4c3e9b10a607d303bbc3435bf22ae8b591ce8f6b5651aacb6cba3c3bfd7217` / `9922d52c13468df5152d88c1fdb1b7c9fc6ce473a1a3a9e56507aaf37479f50b` / `45b9f8bb5d10522fa2e6fa91ca8d944e2d6af27396034b489e27a026783bbedd`；launcher receipt `C:\Users\xiemo\Desktop\ShardForge\pgfrag\experiments\free_fracture_pilot_20261005\run_attempt_01\launcher_receipt.json` SHA-256 `0bae8302c765effdd2614f72a2e1802d4779aa9ea4910829a1281f063c4eb557`；结果 `C:\Users\xiemo\Desktop\ShardForge\pgfrag\experiments\free_fracture_pilot_20261005\run_attempt_01\results\summary.toml` SHA-256 `1e3396d30aa124a3371b47bcd6cc40eea4118312a18d685bbfbe3fdaa60a9c8c`；graph-label binary output 的 summary-declared SHA-256 `7575f682d5e5efbb96f3128102550b14f0a906b5f92cc23df1e4a3976cff4d16`。该 run 不构成 mechanics-coupled surface branch 的 source freeze；其 surface-branch source path/SHA 为 `UNKNOWN`。

**文献检索：** 原决策已列 2018 CPM 和相邻 formulation 作为既有方法/benchmark；仍需有限地核对 benchmark 和相关工作，不扩张为“该工程方案新颖”的结论。

## A12-01 — 正体积矩形 height-graph 材料子集证明

**问题与决策。** 对两个封闭、有向一致、同矩形 height-graph domain、同 lower graph/rim trace、正厚度且完整 side curtains 的输入，candidate 只证明其材料占据正体积并且属于 source 的材料子集。空几何不受支持，不能称为 empty-geometry/empty-Boolean 证明。该受限命题不再从通用 Boolean 输出猜测；非矩形、前提缺失或预算耗尽返回 `UNKNOWN`。这不是通用 3D Boolean 替代物。

**可证伪验证。** 必须先验证全部 source graph/side/topology 正体积前提，只有 source 有效后才允许 candidate 关系检查产生 candidate-owned FAIL；source 无效时应返回 UNKNOWN。测试真实 ndarray 限额、硬 pair cap `250,000`、输入位数预算和十个合同案例；修复后才考虑对冻结 P02/P03 arrays 做窄 probe。错误 PASS、source 无效却先得到 candidate FAIL、预算未硬限或超域不返回 UNKNOWN，均判 FAIL。证书不能升级 global wall、物理 QA 或 labels。

**现有证据与状态。** 先前冻结快照有十个 authored tests，未运行、未接 production、未 probe P02/P03。独立静态 review 在 module SHA `59097293dcca391148862be911ec7292eae956cace8f09a19f2d120c3386f768` 发现 source 中心 `s_source=-3`、bottom `b_source=-2` 时，当前顺序会先返回 candidate `FAIL`，而应先识别无效 source 并返回 `UNKNOWN`。review 同时指出 duck-typed 假 shape 可绕过 ndarray 限额、pair budget 无硬上限、缺输入位数预算；该具体 snapshot 仍不接受，修正状态在该 freeze 边界下为 pending。另有较后的隔离 review2 记录 12-case suite 全 PASS（module `c1a3468cae00b944bcb86c4186b04c5c7cd8e42af586bd27e9603bc6284523ec`、test `ba9929534d71bb6d59489db6c69946282007112c956919829c6655df80487377`、freeze manifest `ce7590ca661636322d0689126c13c4084ec63ec7f6d00d90f828eb184c3e6b43`）；这是后续隔离测试快照，不是 5909… 的同一 source freeze，也不构成 P02/P03 saved-array probe、production integration、P03 wall guard 或物理资格。当前不追踪该隔离源的实时后续变化。

文件：`C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\tmp\review_20261005\degradation_resume\source-review-plan.md`；独立审阅：`C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\tmp\review_20261005\heightgraph_proof_independent`；冻结清单：`C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\tmp\review_20261005\degradation_resume\source-freeze.sha256`（module SHA-256 `59097293dcca391148862be911ec7292eae956cace8f09a19f2d120c3386f768`，tests SHA-256 `b95a259e3028819dbe8db9fff034a52eee5c1c18eec78cd34bd7007882a4ca68`，清单 SHA-256 `9ea87a249539874d8cf86a827c58b9065796b988f2eb944fd99ddb4d57aba1b5`）。module bytes read/hash window: `2026-10-05 00:53:42–00:54:02 UTC`; author fixes remain pending review.

**文献检索：** 待检索 height-field/height-graph inclusion certificates、精确叠置与 B-rep/mesh Boolean 健壮性；受限证明边界未构成新颖性结论。

**后续 12-case 收据：** `C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\tmp\review_20261005\degradation_resume\focused_pytest_review2.junit.xml`（12 tests、0 failures/errors/skips）；过程与资格边界见 `C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\tmp\review_20261005\degradation_resume\report.md`，freeze 清单 `C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\tmp\review_20261005\degradation_resume\source-freeze-review2.sha256`。PASS 只覆盖隔离合同样例；P03、physical wear、production route 仍 `UNKNOWN`，也不改写上文针对 module `590972…` 冻结快照的拒收问题。

## RW-02 — reader hash 不升级 physical fragments；R2 不随 wear 消失

**问题与决策。** Source reader 的 SHA/表格一致性只能证明读取到的 producer payload 字节与结构；不能把 endpoint connected components 升级成 physical fragments、crack surfaces、event history 或 `historical_R2`。`historical_R2` 记录原碎裂事件的真实直接邻接，须与当前贴合 `current_fit_valid` 及当前可见 `evidence_visible` 分开；后续 wear 可改变后两者，不得回写/删除原始 R2。

**可证伪验证。** 使用有实际 fracture/event lineage 的真实 producer payload，验证 reader 对源文件、单位/坐标、ID/交叉表和事件谱系；独立核对原始 R2 roster。对同一身份应用不同 wear 后，R2 清单及来源 hash 保持不变，而 current fit/visibility 可独立变化。只要 toy/endpoint hash 被用于物理标签，或 wear 删除原邻接，判 FAIL。

**现有证据与状态。** 已存在的 source-reader 冻结测试：一轮 19 case 中 18 pass、1 个 stale test variable 失败；修正后的单节点 retry pass。另有 25 个 focused ChainCLI dispatch/audit tests PASS，且 16 个 source/fixture 文件 pre/post hash unchanged。实际 named-job payload 仅 `PG_DIAGNOSTIC_ONLY`；`physical_fragments`、`crack_surfaces`、`event_history`、`historical_R2` 均 `UNKNOWN`。这些是 reader/CLI 窄测试收据，不是物理碎裂或 R2 验证。A12 计划明确 R2/wear 语义分离。当前物理升级 `UNKNOWN`。

文件：`C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\tmp\review_20261005\pg_source_reader\final_validation_summary.json`；reader SHA-256 `ed1d72f0bd25d2962217e88a226d2a72706c013c7087465b53bb9ca04116bd9e`，测试 SHA-256 `0071ad62a7d6780771923cba0da01bde4326e390732ba371e703825fd8640c54`，toy result SHA-256 `b3fb84f20d409f4a4dca0b34ffd8b95a07b7c7944b8b6ecd70100b0b5b17dc20`。R2 语义文件：`C:\Users\xiemo\Desktop\ShardForge\docs\a12\v144_project_core.md`（本轮可用的文件冻结 SHA：`UNKNOWN`）；V1.46 集成方案源：`C:\Users\xiemo\Desktop\ShardForge\RelicWeave_V1.46_A12_VesselForge_PGFrag_Integrated_NavFixed.docx`，SHA-256 `15978a3956fa33e8048cc54c1dad6878a7e19d9c71b84415dcaf8732f041a3b4`。

**文献检索：** 待检索碎片物理身份/拓扑、断裂事件谱系、wear 前后邻接标签的定义；reader capability 与标签效度需分别论证。

## SYS-01 — GPU 路径后置且 UNKNOWN

**问题与决策。** 批量 GPU 训练后置；不把计划配置、GPU 存在或 CPU Julia 窄范围结果当作 GPU 验证。

**可证伪验证。** 先冻结 backend/runtime 与实际 job 输入，再运行可复现小批路径并核对数值、资源和输出 lineage；达到计划的独立吞吐/正确性门槛后方可提升状态。本轮没有 GPU 执行。

**现有证据与状态。** 当前记录为 LocalTiny，CPU Julia 只有窄范围执行证据；5090 批量训练后置，GPU 路径未实现且未经验证，状态 `UNKNOWN`。本轮 `SOURCE_ONLY / UNKNOWN`。

文件：`C:\Users\xiemo\Desktop\ShardForge\tmp\review_20261005\plan_inventory\structural_audit.json`；来源方案 SHA-256 `15978a3956fa33e8048cc54c1dad6878a7e19d9c71b84415dcaf8732f041a3b4`。GPU runner/执行收据 SHA：`UNKNOWN`。

**文献检索：** 待检索 GPU peridynamics/几何生成和训练基准的可比性；硬件路径本身不作为创新声明。

