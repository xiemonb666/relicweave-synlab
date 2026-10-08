# docs/a12/data_contract.md — 数据合同、坐标、权限

权威定义在代码：`synlab/schemas/runtime.py`（运行期类型）、`synlab/schemas/spec.py`（配置）、
`synlab/roles.py`（角色/单位/frame/来源枚举）、`synlab/storage/store.py`（资产库）。
本文件说明字段语义与禁止事项。

## 1. 六种 Pack

| Pack | 角色常量 | 必需内容 |
|---|---|---|
| MotherPack | `mother_mesh`, `mother_meta`, `material_profile` | lineage、参数、闭合 mesh、surface tag、chart、材料场、hash、单位 |
| TruthPack | `clean_truth`, `physical_truth`, `visible_labels` | event/revision、叶片、接口 patch、历史 R2、装配变换、重心对应、QA |
| PhysicalPack | `physical_component`, `physical_result` | 损伤 recipe、mesh、survivor map、丢失体积、revision/hash |
| ObsPack | `obs_view`, `obs_result`, `obs_fused_geometry` | opaque sample ID、RGB、部署 mask/ROI、相机、部分几何、OBS_EST 质量、presence/validity |
| RelationPack | `relation_pool`, `query_roster` | query/candidate、R 标签、灰区、hard type、监督 valid、loss mask、pool |
| EpisodePack | `episode_trace` | 初始观察、动作空间、成本、状态、STOP、奖励规格 |

`features` / `labels` / `provenance` 是三个**分开**的 asset（`feature_bundle` / `label_bundle` / `provenance`），
不允许用字典合并制造泄漏。

## 2. 数组与有效性

| 字段 | 形状/类型 | 规则 |
|---|---|---|
| RGB | `[H,W,3] uint8`；线性源单独 float32 | 记录来源、响应、编码与原始 hash |
| integer label | `[H,W] int32` | 研究语义标签，**禁止插值**出小数类别 |
| deployment mask | `[H,W] bool` | 可获取/估计来源，与 GT 标签分开 |
| points | `[N,3] float32` | `scale_valid=true` 才是局部 mm；否则 arbitrary/reconstruction unit；空模态 `[0,3]` 且 `presence=false` |
| normals | `[N,3] float32` | 从受损观测估计；`normal_valid` 单列 |
| depth_z | `[H,W] float32` | 相机 z，mm；invalid mask 独立；**`r != z`** |
| K / T | `[3,3]` / `[4,4]` | frame 名称与变换方向显式（`T_AB` 把 B 映到 A） |
| quality | `[V,R,Cq] float32` | 每项 valid、来源与估计版本 |
| tokens | `[L,256]` 起步 | L 可变；位置、模态、source grouping、valid |

padding 在 attention/pooling/loss 全部按 valid mask 排除。

## 3. 坐标与像素

* 权威几何：**毫米，右手系**。GLB 展示层用米制/Y-up，经 `T_display_authority` 一次转换（100 mm 立方体验收）。
* 像素中心：OpenCV 约定（左上像素中心 = (0,0)）；导出 COLMAP 时 `cx+0.5, cy+0.5`；往返必须同步坐标与 K。
* crop/resize：`u' = s_x(u-x_0+0.5)-0.5`，`K' = A K`；letterbox 加 pad 平移；EXIF 真实作用于像素。
* 虚拟 U 移动改变沿光轴的相机外参并重新渲染，**不用 resize/crop 模拟物理靠近**。

## 4. 白名单（可进入 forward）

允许：实际 RGB、可获得/预测 mask 与 ROI、OBS_EST 质量、可用相机与标定、受损观测点云/网格及有效尺度、合法上下文。

禁止（`synlab/roles.py::FORBIDDEN_FEATURE_FIELDS`，由 `assert_no_leakage` 递归检查）：
parent/object/bag ID、seed、generator family ID、interface ID、关系答案、historical_R2、mate_present、
truth pose、`T_WF`、clean 隐藏表面、GT 厚度/法向/曲率、精确损伤强度、spurious_mask、hard_case_tag、
lineage_id/mother_id/fragment_id/event_id/split/variant/axis_id/level。

审计覆盖 ROI、融合、质量估计、候选过滤与检索全部阶段，不只 forward。

## 5. 谱系与划分

先划 `shape_lineage_id` 再生成。同基础 mesh 的缩放/换色/微扰/替代断裂/二次破碎/同源扫描属于同谱系。
默认 train/dev/confirm = 80/10/10，确认集开启前冻结。替代碎裂不混池（重叠占据原材料）。
器身与盖保留 `prebreak_component`，原装配接触不算新断裂 R2。

## 6. 资产与发布

* blob 只做字节去重；asset 的 role/schema/unit/frame/`interpretation_hash`/ancestry 独立。
* 提交顺序：临时文件 → flush/fsync → 数量/长度/hash 校验 → 原子 rename → 单写者事务提交。
* release 只引用 COMMITTED + QA_PASS 资产，校验完整引用闭包，manifest 不可变。
* 同字节不同语义（如 clean 与部署输入）允许共存，靠 role 与 interpretation_hash 区分。

## 7. 随机性

每个模块独立子流：`shape/material/pattern/cut/damage/camera/light/sensor/geometry/sampler`。
`pattern.evaluate` 只读冻结系数。执行重试只增加 `execution_attempt`，不改内容 seed；
换 seed/网格预算/算法参数 = 新的 `generation_variant`/`spec_hash`。
五档强度共用同一 `basis_id`。


## 8. 合同勘误（2026-10-09；CONTRACT_DOCUMENT_REVISED）

本节按当前 `relicweave-synlab` 源码和 2026-10-09 静态合同复核补充解释。逐项原文定位、修正句、状态和证据见 [合同对齐报告](contract_alignment_20261009.md)；本节只记录合同口径，不表示新增接口、实现或验收已完成。

### 8.1 版本层级

当前生成配置为内层 `synlab.v3`。配置规范的规范化/序列化键为 `schema`；当前模型内部使用 `schema_id`，并保留 `populate_by_name` 所允许的 `schema_id` 输入形式。`schema_version` 属于 API 外层 job envelope，不是 `GenerationSpec` 的内层配置键。API job 的 `synlab.v3`、`synlab.train.v1`、`synlab.diagnose.v1`，以及 pool、store、各 asset、package 和 deploy 边界的版本各自独立；例如 `synlab.training_package_deploy.v2` 不表示 `synlab.v2` 生成配置。

当前源代码没有证明接受或迁移 `synlab.v2` 配置，也没有证明 `rw-schema-1.1` 到 A12 pack 的 adapter、字段映射或 versioned migrator。旧版只读与迁移的文字在所引主 DOCX 中仍属待兑现合同/设计；在对应模型、字段映射、冻结 fixture、迁移记录和回归验收建立前，不作兼容承诺。G30.1/G30.5 保留“拟实现/研究方案”身份；可执行配置以当前 `configs/a12` 与 `synlab/schemas/spec.py` 为依据。

### 8.2 关系真值、存储标签与预测状态

物理 pair relation 的类别固定为 `R0/R1/R2`。存储和监督侧仍保留合法标签码 `R0=0, R1=1, R2=2, TINY_CONTACT=3, UNKNOWN=4`；该 codebook 不是模型输出维数。`TINY_CONTACT` 是数值灰区，`UNKNOWN` 表示关系/来源未确认；两者不得改写成 `R0` 或用作默认负例。物理关系 logits 目标为三类；`UNKNOWN`/`TINY_CONTACT` 从其关系监督分母排除。决策拒判/abstention 是单独状态，应带 reason、策略/阈值版本和证据覆盖；现有单一 pair similarity、scalar refine 输出及 missing/compatible/contradicting 辅助三分类均不能当作 typed relation head 或校准 abstain 接口。

relation `valid`、`loss_mask`、padding `pair_valid` 与点对应有效性分别表达不同条件。`mapping_valid` 仅是本次合同勘误对点对应有效性的逻辑称呼，不是当前 A12 schema 列名；当前字段为 `synlab.schemas.runtime.CorrespondenceSample.valid`（`runtime.py:290`），导出字段为 `corr_valid`（`schemas/view_channels.json:210`；`storage/export.py:171–175`），具体以代码映射为准。本次不新增列、不改源码。邻接关系未知不自动否定同一 pair 的局部点映射有效性；关系标签 mask 不得替代点对应有效性。

已登记的静态评测缺口：`synlab/relations/negatives.py:892-928` 的 `discrimination_auc` 按 `valid` 筛行但不检查 `loss_mask`；现有 truth producer 对 `TINY_CONTACT` 可标 `valid=true, loss_mask=false`。因此这条诊断路径会将灰区纳入非 R2 类，需在未来修正或清楚限定指标解释。此条是静态代码语义记录，没有运行/重算指标，也未修改代码或历史成绩。不得把所有 `UNKNOWN` 汇总为负例。

### 8.3 成员真值与冻结图库

对查询 `q` 与冻结图库 `G`，R2 直接邻片真值 `N_G(q)` 与成员集合真值 `V_G(q)` 分开定义。`V_G(q)` 必须从独立、已确认的 object-membership GT manifest 与 `G` 求交，再排除 `q`；不得由已标注的 R1/R2 adjacency 边并集构造。若 `q` 与候选的同器身份已独立确认，即使这对的 R1/R2 邻接仍未知，该候选仍为 member-positive。pairwise `R1` 只要求该 pair 的同器身份已确认、且该 pair 的直接历史邻接有充分排除证据；它不要求整个 gallery 闭合。`R2` 邻片闭合与成员集合闭合各自审查；`mate_absent` 不等于 `member_absent`。闭集成员主评测仅纳入独立 object membership 已确认且 manifest 能证明冻结图库闭合的对象。结论范围是库内集合恢复，不延伸到库外实物发现、完整重装配或物理修复。

A12.22 成员恢复仍是目标合同。未来输入限于合法 `Obs`、仅作路由的 opaque sample reference、冻结 gallery/model/policy 版本和公开成本、预算、停止策略。隐藏 `mother_id/object_id`、完整关系图、成员答案、GT 派生奖励只进入离线 truth/training/evaluator，不作部署观察、特征或排序键。建议输出成员集合、R2 邻片候选与 R1 同器候选分栏，另记 ACCEPT/REJECT/ABSTAIN、reason、每轮新增/撤回成员、证据来源、成本和 `stop_reason`。这些是待实现的逻辑字段/合同，不是现有 API、role、schema 或 CLI。

### 8.4 成员评测与状态

闭集主指标按 query 先算，再在 object 内 query 等权，最后 object macro；置信区间按独立 source cluster 聚类，query 加权均值只作补充。对非空 GT 且预测为空，Recall=0、Precision=NA、F1=0。GT 为空时单独统计 `member_absent`、false inclusion 与 abstention；双空只记 `correct-empty`，不记 Precision/Recall/F1=1。固定单 gallery 的结论限定为该 gallery 条件。B1 仅是 R2 标量反馈消融，不是已存在的成员头；Oracle-R2 是离线特权诊断，必须匹配预算并配 equal-budget、shuffle 与 corrupted/predicted-R2 控制，不作为部署输入或当前能力。

新增 `MC01`–`MC07` 是本次提出的独立合同验收门编号，不冒充历史 A01–A36、A37 或已执行门。状态为 `SPECIFIED / NOT_RUN`；实现、数值、测试和 CLI 状态均未改变。本轮不改变 PG/VF/A12 完成度及“0 个物理合格完整数据包”的记录。主 DOCX 的相关正文冲突仍待回写；本 Markdown 报告是本次合同勘误入口。


### 8.5 未注册成员字段与严格 schema（补充勘误，2026-10-09）

当前 `GenerationSpec` 是严格 schema，未声明字段会被拒绝。上文成员恢复请求/结果字段是逻辑合同；不得直接塞入现有配置对象或假定现有 API/CLI 可调用。后续须定义并注册专用版本化 schema、接口和 asset role，完成实现及验收后才能将状态提升；此之前保持 `SPECIFIED / NOT_RUN`。
