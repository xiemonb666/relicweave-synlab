# 证据索引（最终入口：A12 仓库）

本索引随交接发布在 A12 `docs/handover/20261016/`。A12 continuation 文档位于 [`docs/continuation/`](../../continuation/)；workspace-support 续接源文档与根级实验脚本/证据分别位于 [`workspace_support/docs/continuation/`](../../../workspace_support/docs/continuation/) 和 [`workspace_support/experiments/`](../../../workspace_support/experiments/)。A12 仓库内的 continuation/support 文档使用可点击相对链接；`vesselforge/...`、`pgfrag/...` 等跨仓源码路径以同级三仓和共享 workspace-root layout 为基准，其 GitHub 链接应使用独立 `DELIVERY_RECEIPT` 记录的已发布 refs。`PASS` 必须连同后面的 scope 阅读；同名 candidate、snapshot、receipt 或输出包不能代替该 scope。

## 状态、目标与历史连续性

| 路径 | 当前用途/关键记录 | 能证明 | 不能证明 |
|---|---|---|---|
| [`../../continuation/20261016/STATUS.md`](../../continuation/20261016/STATUS.md) | 截至 10/16 的最新工作状态；逐项列出几何、appearance、物理和 data qualification。 | 当前 claim 的主导航；运行/测试数字和限制索引。 | 不是所有项目都 PASS；其中引用的预测不等于实测资源。 |
| [`../../continuation/20261016/EXTRINSIC_EVENT_MATH.md`](../../continuation/20261016/EXTRINSIC_EVENT_MATH.md) | 96-T4 coupon 的有符号 work、A/B/C/D 时序、tangent、getter 对 mass 的影响和 campaign 决策。 | 现有 652 signed negative D 的原因范围及哪些观察缺失。 | 不等于新 campaign trajectory，也不构成已校准材料规律。 |
| [`../../continuation/20261016/PANEL_MAPPING_MATH.md`](../../continuation/20261016/PANEL_MAPPING_MATH.md) | 有限 panel 在曲面上的 mapping/shear/area 口径。 | 设计坐标的数学定义和有限多边近似。 | 不恢复历史纹样、照片投影或烧前颜料。 |
| [`../../continuation/20261015/REAL_WORLD_REQUIREMENTS.md`](../../continuation/20261015/REAL_WORLD_REQUIREMENTS.md) | 用户对全器型族真实对象证据、构造/厚度、材质、视图和 qualification 的要求。 | 开发目标和禁止用 procedural pass 代替真实器型的约束。 | 不是当前所有 family 已满足这些要求的证据。 |
| [`../../continuation/20261015/STATUS.md`](../../continuation/20261015/STATUS.md) | 10/15 前的状态快照；保留原球碗控制、native cohesive run、A12 exports 和失败控制。 | 解释旧 control/dataset 历史。 | 不是 10/16 最新状态；旧 toy PASS 不能转移到新 v6 几何。 |
| [`../../continuation/20261015/PLAN.md`](../../continuation/20261015/PLAN.md) | 当时用户批准的窄实验计划、归属和资源。 | 当次计划的具体合同。 | 当前暂停不表示继续执行旧授权，也不能复用已消费的 run ID。 |
| [`../20261007/HANDOVER.md`](../20261007/HANDOVER.md) | V1.47 A12 / VF / PG 历史交接。 | 10/07 的目标、旧失败、数据泄漏界限和旧 handover 错时。 | 不是当前状态，不能用其 localhost/runtime/旧执行命令重跑。 |
| [`../../master/20261009/RelicWeave_V1.48_ContractAligned.docx`](../../master/20261009/RelicWeave_V1.48_ContractAligned.docx) | 全局方案版本标记为 V1.48，文档日期 2026-10-09，228 页；SHA-256 `23a42e5f4cca40ef733edc9365c15bd0d5fdff647f8821fddec9c649e52b1455`。Word 原档在暂停时打开并锁定；Python 只读提取与归档副本一致。 | 10/09 前的整体方案口径与既有产品模型。 | 尚未反映 10/15–16 的全器型要求、v6 witness mesh、source-resolved panel、extrinsic 事件和冻结 campaign。10/16 更新版应另存日期文件并保留原档。 |
| [`../../master/20261016/RelicWeave_V1.48_Engineering_Update_20261016.docx`](../../master/20261016/RelicWeave_V1.48_Engineering_Update_20261016.docx) | 独立的 2026-10-16 工程进度更新，SHA-256 `b134f7a781b62bbf8946a269343d8eeedbc87c2697c83dcb55e0ab83cf97fd62`。 | 2026-10-16 的状态、交付物、边界和后续验收导航。 | 不能取代 10/09 V1.48 合同原档，也不改变历史通过/失败判决。 |

## VesselForge：几何、网格、来源

| 路径 | 状态/数值 | 证明边界 |
|---|---|---|
| `vesselforge/experiments/continuation_20261016/reference_v6_tetra/run05/partition_output/result.json` | `GEOMETRY_DIAGNOSTIC_ONLY`；86,624 T4、25,748 NPZ node rows、356 interface triangles、44,182 exterior triangles、16 source faces；CAD/mesh relative volume error 0.240307997%。 | production-mesher run receipt 的几何与 source ancestry 摘要；不是 simulation 或 shape fidelity PASS。 |
| `vesselforge/experiments/continuation_20261016/reference_v6_tetra/run05/audit_receipt.json` | root 独立 audit 的输入 hash、来源及网格 audit 收据。 | 几何校验和已声明哈希。应与对应 `result.json`、inputs/witness lineage 一并检查。 |
| `experiments/continuation_20261016/root_v6_run05_readback.json` | `ROOT_INDEPENDENT_V6_RUN05_GEOMETRY_READBACK_PASS`；MSH 25,579 节点；NPZ 25,748，169 unused；44,182 exterior；356 interface；最大坐标 roundtrip 误差 6.94e-18 m。 | 格式/几何/映射范围；不代表原始 CAD 实物、局部 foot fillet 或材质合格。 |
| `vesselforge/experiments/continuation_20261016/reference_v6_tetra/run05_execution_argv.json`、`run05_prelaunch_preflight.json`、`run05_process_watchdog.json` | 实际执行命令、launch guard、外层 watchdog。 | run05 实际 mesh 生成环境/耗时。forecast 93,808 T4 / 1,536,950,272 B 仅预测，非实测 RAM。 |
| `experiments/continuation_20261016/root_witness_readback.json` | root 对 OCC/native-face witness、roundtrip/import face areas、source-curve volume/quadrature 和负控的复核。 | 当前 v6 native face ancestry bridge 范围。 | 导入 STEP 的 shape name 为空；不能依赖 Gmsh face-label 直传。 |
| `vesselforge/src/vesselforge/face_witness.py`、`named_step.py`、`step_partition.py` | witness import/imprint/cut、具名 STEP、partition source-face ancestry。 | 可复用实现与源代码入口。 | 接口已存在不代表每种 CAD kernel/exporter 都无损保留命名。 |
| `vesselforge/data/continuation_20261015/spherical_bowl/` | 解析厚半球 bowl，STEP 体积相对误差约 1.93e-13，网格 signed-volume 相对误差 7.2643e-5。 | 几何控制/数值案例。 | 不是现实比例器型；仅有 procedural bands，零 relief，材料未验证。 |
| `third_party/reference-assets/apsida-shm17946-0047/` 与 `vesselforge/docs/references/REAL_3D_SOURCES_20261015.md` | SHM 17946:0047，CC BY-SA 4.0；v3 仍有 7 个 pinched links，`FAIL_UNQUALIFIED_SCAN_USE_AS_VISUAL_REFERENCE_ONLY`。 | 来源和已知拓扑精修状态。 | 不可送入实体求解；闭合 indexed edges 不足以资格审查。 |

## PG-Frag：预检、事件、campaign

| 路径 | 状态/数值 | 证明边界 |
|---|---|---|
| `pgfrag/data/continuation_20261016/reference_v6_preflight/run_control.json` | `READY_FOR_SINGLE_NATIVE_INITIALIZATION_PREFLIGHT`，case SHA-256 `2954e053...d6d78`（完整 hash 在文件中）。 | inputs/源代码冻结合同已满足前置阶段；不是 run result。 |
| `pgfrag/data/continuation_20261016/reference_v6_preflight/preflight_budget.json` | `WHOLE_OUTPUT_FORECAST_PASS_RUN_NOT_STARTED`。 | output forecast 在 256 MiB 包络内；不是实际 output/RAM/time，也未初始化 Akantu。 |
| `pgfrag/data/continuation_20261016/reference_v6_preflight/preparation_failure_01.json`、`preparation_failure_02.json` | 两次 preparation 阶段失败；两次都发生于 native process 启动前，之后另有最终 READY 状态。 | 必须作为准备过程失败历史保留；不能说成 native preflight 运行失败，也不能只看最终 READY 而抹去失败。 |
| `pgfrag/data/continuation_20261016/reference_v6_preflight/parser_equivalence.json`、`pgfrag/experiments/continuation_20261016/reference_v6_preflight/inputs/mesh_alias_receipt.json` | physical names alias 仅替换两个 name strings；raw Nodes/Elements、tag/order/connectivity 和 volume group 一致。run05 T4 25,579 MSH referenced nodes，NPZ extra 169 unused nodes。 | 证明输入等价/来源 tags；不证明 solver 接受 mesh 或建立 cohesive element。 |
| `pgfrag/experiments/continuation_20261016/reference_v6_preflight/` | 当前有 `prepare_preflight.py`、`run_preflight.ps1`、`run_native_preflight.sh` 和冻结 inputs；没有 `native_preflight/run01`、`execution_record.json` 或 process watchdog。 | 实验仅准备完成，未启动。脚本 hard-code 当前 Windows/WSL workspace mount。 |
| `pgfrag/data/continuation_20261016/extrinsic_event_audit/REPORT.md`、`audit.json` 与 `pgfrag/experiments/continuation_20261016/extrinsic_event_audit/audit_event.py` | read-only audit；652 D 首次负，22/24 QP signed work negative；650 B=45 nodes，C/D=54 nodes；C 新 node mass row 为 0，D 后每侧 5e-6 kg、总质量 4e-5 kg。 | 历史数组的 signed work 与 mass/lineage；不是新 Akantu solve，acceleration/effective QP parameters/外力缺失。 |
| `pgfrag/data/continuation_20261016/extrinsic_capture_preflight/REPORT.md` 和配套 JSON/NPZ | 实际 Akantu wheel zero-step getter/readout capability；Python 3.12.15、NumPy 2.5.3、Akantu 5.0.7-post1；字段可用，`getTime()`/通用 QP weight getter 不可用。 | 证明 public capture route 与 shape，未运行一步 solver；tagged source v5.0.7 与 wheel provenance 不合并。 |
| `pgfrag/data/continuation_20261016/extrinsic_onset_refinement/shape_only_preflight/shape_only_preflight.json`、`preflight_status_final.json` | `VERIFIED_COUPON_AFFINE_TRI3`；零 solver steps、0 cohesive checks；coupon 八个平面 facets；实际 native shape rule/normal 和几何 area 支持 area/3。 | 仅这一个冻结 coupon 的 affine Tri3；不是通用 Akantu Jacobian/权重 getter。 |
| `pgfrag/data/continuation_20261016/extrinsic_onset_refinement/frozen_protocol.json`、`prepare_validation.json` 和 `pgfrag/experiments/continuation_20261016/extrinsic_onset_refinement/README.md` | `FROZEN_FOR_ROOT_REVIEW_NO_CAMPAIGN_LAUNCHED`、`PREPARED_NO_MODEL_NO_SOLVER_STEPS`；h/h2/h4 common 666h；h8 保留独立决定。 | protocol 与 capture 设计已准备，campaign 没有结果；不是新的 physics evidence。 |
| `pgfrag/experiments/continuation_20261015/frozen_run03/`、`coupled_readback_run02/`、`docs/continuation/20261015/STATUS.md` | 预置 toy patch/native cohesive control 的已有成功结果与独立 audit。 | 仅 toy/free-patch or prescribed seam；不能替代 full-size realistic mother 的应力驱动断裂。 |

## A12 / SynLab：材料、纹样、观察

| 路径 | 状态/数值 | 证明边界 |
|---|---|---|
| `relicweave-synlab/synlab/mothers/design_space.py` | 公开 `parameter_space/build_designed_mother/probe_parameter_effect`；可读 requested/resolved/realized 控件。 | 控件合同；metadata mismatch 和 V23 忽略 inherited controls 仍未修成 qualification。 |
| `relicweave-synlab/synlab/materials/reference_materials.py`、`synlab/patterns/reference_styles.py` | 来源引导 appearance recipes / process compatibility / styles。 | optical/mechanical constants没有被测得；Hacilar motif 不足；材料类不等同陶瓷标定。 |
| `relicweave-synlab/synlab/patterns/underglaze.py`、`synlab/patterns/bluewhite_panel.py` | conservative metric-aware diffusion、bound/mobile 和曲面有限 panel。 | 技术方法/有限网格 receipt；不等于烧成 chemistry、连续原图 mass conservation 或 finished ornament。 |
| `experiments/continuation_20261016/bluewhite_bowl_panel/outputs_v1/receipt.json`、fine/coarse receipts | 45×26 mm finite panel；fine 240×1024；mass drift ~1.66e-16；coarse/fine spread RMS diff ~0.0584；synthetic bowl + vase photo crop。 | 仅离散 grid sensitivity 和新合成 panel；不是 historical bowl decoration。 |
| `relicweave-synlab/experiments/continuation_20261016/bluewhite_source_resolution/README.md`、`outputs_v1/experiment_manifest.json`、`outputs_v1/source_detail_probe.json` | `source_resolved_stationary_v1` opt-in; exact outputs `27,304,078` bytes；10/16 STATUS 记 55 focused tests PASS。 | 保住静态笔触细节的实现测试与 receipt；不代表图案精修、历史复原、物理 qualification 或全局 mass convergence。 |
| `relicweave-synlab/experiments/continuation_20261016/bluewhite_reference_generation/outputs_v2/preview_manifest_bluewhite_v3.json`、对应 instance receipts/previews | source-aware PBR technical previews、四向标记及 receipt hashes。 | root 看过并接受 technical composition slice；finished ornament 仍未通过。 |
| Workspace source files: `experiments/continuation_20261016/generic_mother_binding/run05_binding/{binding_receipt.json,experiment_receipt.json,binding_arrays.npz}`；A12 published archive copies: [`binding_receipt.json`](../../../workspace_support/experiments/continuation_20261016/generic_mother_binding/run05_binding/binding_receipt.json), [`experiment_receipt.json`](../../../workspace_support/experiments/continuation_20261016/generic_mother_binding/run05_binding/experiment_receipt.json), and [`binding_arrays.npz`](../../../workspace_support/experiments/continuation_20261016/generic_mother_binding/run05_binding/binding_arrays.npz) (three hashes match source). | `binding_id=24231c63...36073`，`READ_ONLY_BINDING_VALIDATED`；Aberdeen object ID `ABDMS095708.121`；source face ancestry 有声明容差。`preview.png` 缺失但属 nonbinding artifact。`experiment_receipt.json` SHA-256 `11b2d4351bf833d9b4bf6fab90073f15edd84bd375fcdb8e693a12cf09afd1d6`; binding receipt SHA-256 `66d245e9734abdb5095d768bca4f0771427f3a12f8f3408c7054cab7364ab273`; arrays SHA-256 `2a91442387d1440dab6cf5bff8ea4e7cfe91b7e90ed9ea6e99f345adf61c7d35`. | Structural CAD binding validator output exists and was executed; `PASS_STRUCTURAL_CAD_ONLY` only. The actual run05 binding has not been accepted by root as a complete mother; profile fidelity/material/solver/fracture/observation are unestablished, physical/pretrain false. |
| `relicweave-synlab/data/continuation_20261015/native_cohesive_v6_dataset/`、`native_cohesive_v6_run_summary.json`、`native_cohesive_v6_loader_smoke.json` | 2 个闭合 components，4,342 T4，全量 mass；六视图 8,216 observed points；loader 成功；`physical_pass=false`、`pretrain_eligible=false`。 | 软件 research dataset/窄 compliance control；不是 physical shards/train-ready package。 |

## 暂停时的离线测试证据

`docs/continuation/20261016/STATUS.md` 汇总的早期 focused tests 有：v6 `face_witness`/production mesher 37 checks；A12 source-resolution slice 55 个 panel/generator/underglaze/material checks；早前 26 VF、68 A12 的 stable checkpoint；facet ancestry helper 25 checks。暂停交付验证另有三组离线验证：

| Repo | 文件数 | 结果 | 耗时 | 含义/限制 |
|---|---:|---:|---:|---|
| VesselForge | 7 files | 66 passed，exit 0 | 18.70 s | focused checks，不是全仓库 suite。 |
| PG-Frag | 6 files | 55 passed，exit 0 | 1.07 s | focused checks，含 9 个 mother-binding tests；只验证 validator/software contract，不验收实际 run05 mother。 |
| A12 / SynLab | 9 files | 90 tests，suite exit 0 | 未提供 | 单独 collect-only（清除 double-quiet 配置后）确认总数为 90；focused suite，不是全仓库 suite。 |

三套暂停验证合计 211 项；没有运行 solver，也没有更改功能代码。这与 A12 早期 source-resolution 的独立 55 checks 不同，不能合并或替代。准确命令、逐个测试文件和资格边界见 [`PAUSE_VALIDATION.json`](./PAUSE_VALIDATION.json)；没有单独生成 JUnit/XML 文件，原始终端输出留在交付记录中。不要把更早的 16 underglaze、8 reference generator 或 34 intermediate set 当作最终代码的替代报告。复核时仍应看 repo receipt/source hash 和对应 run timestamp；不要只引用本表。

## 暂停时的仓库与数据保存快照

暂停快照中的三个本地 checkout 分支均为 `backup/forge-work-20261003`；VF/PG 的 GitHub 默认分支同名，A12 的 GitHub 默认分支为 `main`。A12 `HEAD` 相对 `origin/main` 超前 16 commits，祖先关系允许 fast-forward、不需 force。最终发布 branch/commit/remote/ref 由独立 `DELIVERY_RECEIPT` 记录。暂停时没有观察到仍运行的本项目 Python 或 WSL solver。约 6.8 GB raw data 由本地 manifest 保留，不应把所有 raw data 当作必须推送的项目代码；`_temp_matplotlib` 是外部 runtime cache，应排除。最终阅读入口是 A12 `docs/handover/20261016/`；continuation source archive 位于 A12 `workspace_support/docs/continuation/`，root experiment source archive 位于 A12 `workspace_support/experiments/`；同级三仓与共享 root layout 是 workspace-relative paths 的前提，单独克隆 A12 不会包含其他仓库的 evidence files。
