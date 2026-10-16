# A12 SyntheticLab 接手盘点（2026-10-15）

## 范围与仓库基线

本记录是代码与现存文档/产物的静态盘点。没有运行 tests、CLI、训练、solver、服务、实验或数值生成；没有改源码或历史产物。

- 子仓：`C:/Users/xiemo/Desktop/ShardForge/relicweave-synlab`
- branch：`backup/forge-work-20261003`
- HEAD：`9f1b4d5e53745d16d92ed2635b541aca859bf7d9`（2026-10-09，`docs: archive V1.48 contract-aligned publication`）
- 检查时已有工作树状态：仅两个未跟踪 handover 收据 `docs/handover/20261007/BACKUP_DELIVERY_RECEIPT.{json,md}`，无 tracked 修改。没有找到适用的 `AGENTS.md`。
- 本分支 README 将 A12 称为独立 synthetic lab，接口合同为 `a12.obs.v1`，主仓集成仍为 `MAIN_REPO_INTEGRATION_PENDING`。

## 结论先行

当前最短可复用链是 A12 自己的单谱系生成管线：内部 mother → material/pattern → A12 几何分割 → clean/physical truth → observation → visible labels/features/labels/provenance。它适合做器型/纹样与前期合成观察训练包的独立 smoke，但 `fracture_event` 是 A12 几何分割路径，`apply_damage` 是断裂后的单片损伤/磨耗；这条链不能证明 VesselForge 输入已进入生产生成，也不能代替 PG-Frag 动力学破裂。

VF 当前可调用边界是**验证包并渲染预览**。PG 当前可调用边界是**有界读取结果并生成诊断报告**。两者均未接入 A12 的母体/断裂生产入口。2026-10-09 合同复核明确保持 PG/VF/A12 完成度不变，记录“0 个物理合格完整数据包”；成员恢复扩展仍是 `SPECIFIED / NOT_RUN`，无现成 API/CLI。

## 入口、结果与输出接口

| 区域 | 现有接口/文件 | 能力边界与状态 |
|---|---|---|
| VesselForge 包读取 | `synlab/integrations/forge_asset.py::load_forge_asset(package_dir)`（约 L246） | 验证 `forge.asset.v1` manifest、文件哈希/字节、路径、单位/坐标系、geometry-only producer report 及 NPZ。验证范围基于哈希绑定的生产者报告，并非本地独立重测。 |
| VF 场景适配 | `scene_from_forge_asset(asset, allow_prototype_preview=False, ...)`（约 L593）；`render_forge_asset_preview(...)`（约 L689） | 必须显式允许 `UNVALIDATED_PROTOTYPE` 预览；VF 母体区域 1–5 合并成 A12 母体表面 tag 0，tag 2 保留给有事件来源的断裂像素。输出 metadata 明示 `fracture_output=NONE`、`r2_output=NONE`、`production_physical_pass=false`、`feature_export_allowed=false`。这不是 A12 `MotherGeometry` ingress，也不进入 `run_generation`。 |
| PG-Frag 结果读取 | `synlab/qa/source_readers/pgfrag_result.py::read_pgfrag_result(...)`（L661 起） | 读取有界的 `pgfrag.result.v1` `result.json`/`data_dictionary.json` 及 points/components/bond-state/broken-bond/isolated-point CSV；核验哈希、大小、路径及类型化行。SI 单位不自动转 mm。模块标记 `PG_DIAGNOSTIC_ONLY`，明确不把 components 当 physical fragments，也不推导 crack surface、event history 或 R2。 |
| PG 链路审计 | `synlab/qa/forge_chain_audit.py::_dispatch_pgfrag_source_reader(...)`（L349 起）；模块 CLI `main()`（L1252 起） | 仅允许 input-v2 声明的固定 PG reader，报告只读且不接 A12 训练/导出。命令形式：`python -m synlab.qa.forge_chain_audit --root <root> --input <root-rel.json> --output <new-root-rel-report.json> [--fail-on-incomplete]`。 |
| A12 结果包络 | `synlab/errors.py::Result`（L129–153） | API 统一返回 `status/output_refs/input_hashes/qa_report_ref/metrics/error`。它不是 PG `result.v1`，也不是 training package。 |
| A12 生成管线 | `synlab/pipeline.py::build_one_mother(...)`（L1549 起）；`run_generation(...)`；`synlab/cli.py` 的 `generate`（L153–175） | 主管线依次调用 `create_mother`、材料/纹样、`fracture_event`、clean truth、`apply_damage`/physical truth、观察、visible labels、features/labels/provenance；分阶段提交独立资产。当前 `lineage_id` 在 `pipeline.py:L903` 由 index/vessel/material/pattern 组成，不含 spec identity，跨 spec 不能据此合并。 |
| 观察与标签 | `synlab/observe/api.py::observe`（L97）、`commit_observation`（L213）；`synlab/truth/api.py::finalize_clean_truth`（L522）、`update_residual_truth`（L894）、`update_visibility_truth`（L1089）、`build_labels`（L1300）、`commit_truth`（L1425） | 有 OBS、clean/physical/visible truth 与标签 producer。`build_labels` 与 feature bundle 分离；`synlab/observe/features.py::assert_no_leakage`（L67）和 `adapt_observed_features`（L166）负责观察特征边界。`pipeline.py::_commit_features`（L2369）和 `_commit_labels`（L2461）分别提交 `feature_bundle`/`label_bundle`，provenance 单独留存。 |
| Release 与训练包 | `synlab/cli.py` 的 `export`（L280–293）调用 `export_release`；训练包 writer 是 `synlab/storage/export.py::export_training_package(...)`（L769），reader 是 `TrainingPackage(root, access=...)`（L3007） | CLI `export` 是 release 归档/索引，不是训练包导出。训练包 schema 为 `synlab.training_package.v1`，manifest 为 `synlab.training_package_manifest.v1`；部署/研究视图分开，reader 的部署访问与研究访问分权。训练包需调用 writer 或 `tools/a12_experiment_ready_export.py`（CLI `--step base|merge|finalise|ablation|card|all`，L1183 起）；`tools/load_package.py --check` 可做独立加载检查。注意 writer 的 `include_truth=True` 默认值。 |

`synlab/roles.py::FORBIDDEN_FEATURE_FIELDS` 与观察层递归泄漏检查提供特征侧约束；这不等于部署视图的内容已无真值。版本方面，当前内层配置是严格 `synlab.v3`；`contract_alignment_20261009.md` 明确没有 `synlab.v2` 迁移、`rw-schema-1.1` adapter，也没有成员恢复 API/CLI。

## 能力与已有证据分开看

**源代码所能做的事：**

- `synlab/mothers/api.py::create_mother`、`synlab/patterns/api.py::build_pattern`、`synlab/fracture/api.py::fracture_event`、`synlab/physical/api.py::apply_damage` 和上述管线能组成 A12 内部合成链。断裂步骤是 `warp_voronoi_cut` 等几何分区/共享切割器；`apply_damage` 是分割后 damage/wear，不是动态裂纹起始与传播。`implicit_sheet_cut` 在普通 facade 中 gated/off，不应列入可用生产链。
- `synlab/qa/source_readers/pgfrag_result.py` 能验证来源字节并报告 PG endpoint 数据；`forge_chain_audit` 能验证明示来源引用。报告成功只代表来源/字节读取达到对应状态，不代表 physical fragments、裂纹面、事件历史、接触关系或 A12 训练资格。
- `synlab/storage/export.py` 有训练包 writer/reader、双视图和特征扫描器；这证明有隔离机制实现，不代表已产出的每个包通过严格的部署无真值门。

**仓库内可见的历史证据：**

- `docs/a12/evidence/20261005/pg_source_reader/actual_named_job_source_report.json` 保存 `SOURCE_VERIFIED` 的 named job/result 字节绑定；fixture 为 `uniform_box_bar_fixture`，576 points、20,780 bond-state rows、5,236 broken-bond rows、576 component rows、0 isolated points。该报告仍标 `PG_DIAGNOSTIC_ONLY`；crack surfaces、event history、historical R2、physical fragments 均为 `UNKNOWN`，component connectivity 也未重算。它是 reader/source 证据，不是完整物理破裂证据。本盘点没有重跑 reader。
- `docs/a12/physical_layer_wiring.md` 的旧实测记录包括有限器型上的 `plane_shared_cut` 与失败/门控的 rough/morphology 路径；它们是 A12 几何切割测试，不是 PG 动力学物理验收。10/09 复核仍明确为 0 个物理合格完整包。
- 当前目录已有 `data/a12_exports/experiment_ready/training_package` 和 `data/a12_exports/negfix/next_experiment/training_package` 历史包。前者 manifest 报 `synlab.training_package.v1`、59 observations、56 R2 relations、5 label layers、约 5.20 GB，`features_carry_answer_fields=false`、部署扫描 `hits=[]`，但同时 `views.deploy.contains_truth=true`，且 `deploy_truth_content_files` 指向 `obs/index.json`（理由字段 `reason`）；manifest 也记录 `build.include_truth=true`。README 记录该包由不同源码 HEAD/dirty tree 导出，`spec_hash` 缺失。因此“没有命中禁用字段”不能推出“部署视图没有真值”，这些旧包不能当作当前 HEAD 的可复现实验或无真值证明。本盘点只读 manifest/README，未运行 loader。
- `docs/a12/status.md` 自标为 2026-10-02 快照，并含 10/07 精度澄清；例如 155/155 是未标定的执行/有效性，单一独立母体，22/31 轴无实测配对。`docs/a12/next_experiment_data.md` 仍含批次、覆盖、导出、缺口和复现占位符。以 10/09 `contract_alignment_20261009.md` 作为最新状态边界；旧 QA PASS 不能推广为当前物理合格。

## 最小集成顺序

1. **先锁定 A12 合成 smoke 与可复用数据合同。** 建立全新 store/output、单谱系小配置和独立 run/spec hash；用标准 `run_generation` 形成 mother、pattern、A12 geometric fracture、truth、OBS、feature/label/provenance，再审计全部引用/QA。不得按现有 lineage ID 把不同 spec 合并，也不要覆盖历史目录。该 smoke 可以支持器型/纹样与前期训练工程，不宣称真实物理破裂。
2. **把 VF 作为有来源 provenance 的母体输入单独接入。** 固定 `forge.asset.v1` 包 hash、单位、坐标系和 geometry-only 范围；为其新增版本化 A12 ingress，将 verified mesh 映射到 A12 mother asset/lineage，而非复用只渲染 `Scene` 的预览 adapter。VF 区域、源 ID、材料参数、装饰坐标放 provenance/真值，不进 OBS/features；材料未校准、无断裂标签或 R2 推断。`GenerationSpec` 是严格 schema，不往其中直接塞未声明的 VF/member 字段。
3. **再建 PG physical bridge。** 先升级/版本化 PG 输出与 reader，明确提供逐步 bond active→inactive 事件、材料坐标/point mapping、可验证的组件/质量完整性，以及事件绑定的双侧 crack surface 几何/lineage/面积/不确定度；reader 仍按固定 allowlist 接入。物理验收状态与 surface 几何 QA 分字段；缺项保留 UNKNOWN，不转成负例或 R0。将验收后的 physical fracture 作为独立输入 asset 接入 A12 truth/observe 管线，保留原始 job/result hash。现有 PG v1 endpoint components 不足以代替这些数据。
4. **冻结并审查训练包。** 使用新 release 与 `export_training_package`/experiment-ready exporter；用 `TrainingPackage(..., access="deploy")`、`tools/load_package.py --check` 和真实内容扫描验证 manifest hash/文件清单、view 权限、来源/谱系划分、OBS 通道、features、labels/provenance。当前历史包已经显示 `obs/index.json.reason` 会被真值扫描器判为 supervision；必须明确该字段的语义/边界并让部署真值扫描达到 `contains_truth=false`、`truth_bearing_files=[]`，同时研究侧保留标签/映射。负控应在 `mother_id/event_id/historical_R2/clean_hidden_surface` 等答案字段下注入，确认 features/deploy 拒绝它们。

## 下一轮有意义的验收检查

- VF fixture：manifest/file hashes、路径穿越/符号链接、单位/坐标系、geometry-only PASS、`UNVALIDATED_PROTOTYPE` opt-in；断言 importer 不把 VF region 255/producer IDs 转成断裂标签、R2 或模型特征。
- PG fixture：result/job 外部 SHA、每个输出文件 hash/size/安全路径、schema/status/SI units、typed rows 与 caller rows；缺事件/双侧面/物理碎片字段时必须保持 `PG_DIAGNOSTIC_ONLY`/UNKNOWN，且诊断结果不可导入训练 truth。
- A12 fresh-store smoke：固定 spec/seed 的可复现 hash；单谱系完整 asset ancestry；分割/损伤语义分别记录；QA 失败进 quarantine；features 与 labels/provenance 角色互斥；对写入后的 asset hashes 做核验。
- Training package：manifest/hash 与 loader 检查；部署内容扫描不只查键名，还检查 supervision-bearing 内容；`deploy.contains_truth=false`、无 truth-bearing 文件、labels 与 opaque↔source map 仅研究侧；部署输入不含身份排序键。复跑只对新鲜输出做比对，不写入历史包。
- 如继续做 A12.22 成员恢复，先注册专用版本化 schema/API/asset role，再做独立 membership manifest 与冻结 gallery 的集合真值；不从 R1/R2 邻接边并集构造成员集合。合同规定为 `SPECIFIED / NOT_RUN`，不是当前 smoke 的验收项目。

## 本轮没有验证的项目

未运行任何 test、CLI、训练、求解器或渲染；未重算历史 QA/指标；未打开服务或循环；未校验历史包 loader；未实测 VF→A12、PG→物理 fracture asset 或 A12→部署训练包的端到端链。因此上文提到的源码接口、历史报告与旧包 manifest 属于不同证据等级，不能合并成端到端完成声明。
