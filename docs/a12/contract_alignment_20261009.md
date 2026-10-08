# A12 synlab 合同对齐与勘误（2026-10-09）

状态：`CONTRACT_DOCUMENT_REVISED / STATIC_REVIEW`。本报告与两个 dated addendum 是本轮合同勘误入口；主 DOCX 正文回写为 `PENDING`。成员恢复新接口为 `SPECIFIED / NOT_RUN`，不是现有可调用 API/CLI。

本轮只做静态合同核对、Markdown 写入、快照/副本和哈希/链接验证。没有运行 tests、CLI、训练、solver、实验或数值生成；没有改源码、DOCX、历史 receipt、delivery sidecar、原审计源或验收状态。PG/VF/A12 完成度及“0 个物理合格完整数据包”的记录不变。

## 统一口径

当前生成配置是内层 `synlab.v3`。规范化序列化键为 `schema`；实现模型内部字段为 `schema_id`，`populate_by_name` 也允许 `schema_id` 输入。`schema_version` 是 API 外层 job envelope 字段，不是内层 `GenerationSpec` 字段。API 的 `synlab.v3`、`synlab.train.v1`、`synlab.diagnose.v1`，以及 pool、store、asset、package、deploy 各自独立版本；`synlab.training_package_deploy.v2` 不等于生成配置 `synlab.v2`。当前没有 `synlab.v2` 配置读取/迁移或 `rw-schema-1.1` 到 A12 pack 的 adapter、字段映射、migrator 证据。

物理 pair relation 只有 `R0/R1/R2`。存储/标签码仍合法保留 `R0=0, R1=1, R2=2, TINY_CONTACT=3, UNKNOWN=4`；码表不等于模型 logits 维度。`TINY_CONTACT` 是数值灰区；`UNKNOWN` 是未确认关系/来源，不能转成 R0 或默认负例。relation `valid`、`loss_mask`、padding `pair_valid` 与点对应有效性分属不同任务。本文用 `mapping_valid` 作为点对应有效性的逻辑称呼，并非现有 A12 schema 列名；当前字段是 `CorrespondenceSample.valid`（`synlab/schemas/runtime.py:290`），导出名为 `corr_valid`（`synlab/schemas/view_channels.json:210`；`synlab/storage/export.py:171–175`），以代码映射为准；不新增列、不改源码。现有训练有单一 pair similarity、scalar refine 及另一项 missing/compatible/contradicting 三分类；没有 typed relation head 或校准 abstention 接口。

成员集合真值 `V_G(q)` 必须从冻结图库中独立、已确认的 object-membership GT manifest 求交后排除 `q`；不能从已标注的 R1/R2 adjacency 边并集构造。身份已确认而某 pair 邻接未知时，该候选仍是 member-positive。pairwise R1 只需该 pair 的同器身份已确认，且该 pair 的直接历史邻接有充分排除证据，不要求整个 gallery 闭合。R2 邻片 `N_G(q)` 与成员 `V_G(q)`、neighbor closure 与 member closure 分开；`mate_absent` 不等于 `member_absent`。成员恢复范围是冻结图库内集合，不承诺库外寻物、完整装配或物理修复。

A12.22 仍是目标合同：没有找到成员 generator、独立成员 manifest/result role、API/CLI、静态基线或成员指标实现。建议输入/输出字段是逻辑合同，不能直接塞入严格 `GenerationSpec`（未声明字段会拒绝）；需另建并注册版本化 schema、接口和 asset role 后再实现验收。线上只用授权 Obs、作路由的 opaque sample reference、冻结 gallery/model/policy 版本和公开成本/预算/停止策略。GT 答案、mother/object ID、完整图与 GT 派生奖励只供离线 truth/training/evaluator；opaque 引用不作身份特征或排序键。输出逻辑应分开成员集合、R2 候选、R1 候选，记录 ACCEPT/REJECT/ABSTAIN、reason、每轮新增/撤回、证据、成本和 `stop_reason`。

成员 P/R/F1 保留 V1.47 body[128–129] 的空值语义：GT 非空且预测空时 R=0/P=NA/F1=0；GT 空单列 member-absent、false inclusion 与 abstention；双空只记 correct-empty，不报 P/R/F1=1。先 object 内 query 等权，再 object macro；区间按独立 source cluster 聚类，query 加权均值仅作补充。单一冻结 gallery 只支持该 gallery 条件结论。B1 是 R2 scalar-feedback 消融，不是 member head。Oracle-R2 仅为离线特权诊断，不保证是严格性能上界；需匹配候选池/上下文/预算并配 shuffle、equal-context 和 predicted/corrupted-R2 controls。

静态审阅登记一处关系评测语义缺口：`synlab/relations/negatives.py:892–928` 的 `discrimination_auc` 筛 `valid` 但不筛 `loss_mask`；truth producer 可令 TINY_CONTACT 为 `valid=true, loss_mask=false`，因此该诊断会将灰区放进非 R2 类。未修源码、未重算历史指标、未运行数值评测。不要把所有 UNKNOWN 并为负例。

## 主 DOCX 原文定位与建议修句

`BODY[n]` 指 `word/document.xml` 中 `w:body` 的 0 起始直接子节点，不代表页码。主 DOCX 本轮未改，下列条目等待后续正式回写。

| 定位 | 冲突/现状 | 建议修句 | 状态 |
|---|---|---|---|
| 第9章 BODY[920–921]；G25.3 BODY[2109–2110]；H2 BODY[2354–2355] row[5] | body[921] 称 rw-schema-1.1 与 synlab.v2 为现行；G25/H2 又称旧版只读迁移。 | 当前生成配置是内层 synlab.v3（规范键 schema）；synlab.v2 与 rw-schema-1.1 adapter/迁移在映射、fixture、记录与回归证据出现前均为 pending；各 artifact/package/deploy 版本独立。 | DOCX PENDING |
| G30.1 BODY[2146–2151] | 明确是拟实现骨架，但 v2 示例含 schema_version、release_id、单数 unit、顶层 mother；无当前字段映射。 | 保留方案身份；当前可执行配置以 configs/a12 和 GenerationSpec 为准。无已验证映射前不承诺 v2/rw-schema 兼容。 | DOCX PENDING |
| G30.5 BODY[2241–2243] | v3 内层例子写 schema_version，并称保留旧 migrator。 | 内层写 schema: synlab.v3；schema_version 仅在 API job envelope；未实现迁移器标 pending。 | DOCX PENDING |
| BODY[109], [181], [201], [211]；训练表 BODY[1627] | 三关系及 UNKNOWN 分离在部分文字已正确，但四路 posterior 和 enum 表易混淆 label/storage 与 head，且漏 TINY code。 | 物理 posterior 为 R0/R1/R2；保留存储码 R0=0,R1=1,R2=2,TINY_CONTACT=3,UNKNOWN=4；relation valid/loss_mask/pair_valid 与点对应有效性及 abstention 各自独立。mapping_valid 是本次逻辑称呼；现有字段为 CorrespondenceSample.valid、导出 corr_valid，不新增列。 | DOCX PENDING |
| A6.15 组件表 BODY[319] paragraph[7] M_R2、paragraph[13] Soft Typed Graph | 两个单元将 R0/R1/R2/UNKNOWN 写成 posterior/distribution，是实质四路输出冲突；UNKNOWN 仍是合法存储状态，但不是第四种物理预测类别。 | 两处改为三类物理分数/后验加独立 unresolved/abstain 字段；保留 UNKNOWN 存储码，不全局删除 UNKNOWN。 | DOCX PENDING |
| A6.15 BODY[315]、A6.15.1 BODY[320]、Step 2 BODY[324]、Step 5 BODY[327]；分离规则 BODY[331–334] | 候选步骤写四类 R0/R1/R2/UNKNOWN posterior，后文又把 UNKNOWN 定义为独立拒判。 | Step 2/5 只预测三类物理关系；UNKNOWN/abstention 独立输出状态与原因；same-vessel 与 direct-contact 分开。A6.15 保留 RESEARCH_CANDIDATE。 | DOCX PENDING |
| T0 baseline BODY[350–352] | T0 行写四类输出。 | T0 为三类物理关系分数加独立决策状态；允许多个 R2 候选。 | DOCX PENDING |
| Graph Memory BODY[366–368] | R0/R1/R2/UNKNOWN 列表可被读成四类后验。 | 图中可保存 UNKNOWN 未确认状态；物理后验仍为三类；研究候选不表示实现。 | DOCX PENDING |
| §2.0 BODY[112–114]；A12.22 BODY[568–569] | 定义库内成员恢复目标，但未给出独立成员真值派生和当前实现证据。 | V_G(q) 从冻结 G 中独立 membership GT manifest 求交并排除 q；N_G(q) 单独表示 R2 邻片。 | DOCX PENDING |
| §2.2.2 BODY[128–129] | 指标与空集语义已有规定，但成员真值不能由邻接边并集代替。 | 保留 P/R/F1 与空集规则；独立 manifest 证明成员闭合，pairwise R1 不要求全 gallery 闭合。 | DOCX PENDING |

原始 `RelicWeave_V1.47.docx` 对应 body[903]、[2090]、[2126–2127]、[2222–2223]、[2334] row[5] 仅用于溯源，没有修改。当前 master DOCX SHA-256 前后为 `883c831648d0697f456228f4d862deda8a36ff9740ecd6aadb3a3ebfdfdffc7d`。

## 新增合同验收门

`MC01`–`MC07` 是独立新编号，不冒充历史 A37，不改变 A01–A36。每项为合同要求，执行状态均 `NOT_RUN`。

| 门 | 需要的证据 | 状态/缺口 |
|---|---|---|
| MC01 独立成员真值 | manifest ∩ 冻结 G，再排除 q；邻接未决但身份确认仍正例；成员闭合与 R2 闭合独立。 | SPECIFIED / NOT_RUN；当前无 member manifest/closure。 |
| MC02 schema 与注册 | 专用版本化 member schema/API/role；严格 GenerationSpec 继续拒绝未声明成员字段。 | SPECIFIED / NOT_RUN；无可调用 member API/CLI/role。 |
| MC03 GT 隔离 | 线上只接合法 Obs、opaque 路由引用、冻结版本与公开预算；GT 答案/ID/全图/奖励保持离线并有泄漏负控。 | SPECIFIED / NOT_RUN；成员专属测试未见。 |
| MC04 集合语义 | R1-only 正例、R2 不传递、排除 q、UNKNOWN 双维状态、邻接未知但身份已确认、开闭集资格。 | SPECIFIED / NOT_RUN；现有 pair/R2 fixture 不覆盖成员集合。 |
| MC05 指标统计 | 非空/空/双空手算；object 内 query 等权、object macro、source-cluster CI。 | SPECIFIED / NOT_RUN；现有指标是 pair/R2 指标。 |
| MC06 多轮/预算/对照 | hypothesis/hash、每轮 add/remove、cost/stop；B1 为消融；Oracle-R2 为离线特权诊断且不保证严格上界，匹配预算/上下文并做 shuffle/equal-context/corrupted/predicted 对照。 | SPECIFIED / NOT_RUN；episode_trace 是观察轨迹，没有成员状态或对照。 |
| MC07 关系 AUC mask | relation metric 明确 relation mask；不以 valid 代 loss_mask，不把 UNKNOWN 整体并作负类。 | SPECIFIED / NOT_RUN；只确认静态代码缺口。 |

## 证据、历史快照与限制

版本证据：`synlab/schemas/spec.py:15,221–246`、`synlab/config.py:83–88,115–166`、`synlab/api/deps.py:59–70`、`synlab/api/specs.py:25–46`、`synlab/cli.py:92–116`、`synlab/roles.py:19`、`synlab/storage/{store,export,deploy_boundary}.py`。标签/mask 证据：`synlab/schemas/runtime.py:255–271`、`synlab/training/adapter.py:36–42`、`synlab/training/batch.py:214–253,425–435,454–503,579–613`、`synlab/truth/api.py:770–785`。当前 head 证据：`synlab/training/model.py:369–390,732–768`、`trainer.py:433–463,566–593`、`losses.py:137–145,336–393,565–592`。成员底座：`synlab/relations/gallery.py:454–456,558–559`、`training/api.py:209–211,324–331,443–510`、`episodes/api.py:95–136,207–215`、`roles.py:16–20,47–60`、`cli.py:297–361`。缺项结论只限审阅范围 `docs/a12`、`synlab`、`tests/a12`、README/current handover，排除备份、vendor、third_party。

两份 A17 历史快照同日状态不同：`acceptance_delta.md` 时间为 2026-10-02 01:45:24 +08，记录 job/run ID UNIQUE 冲突 FAIL；`acceptance_report.md` 于 2026-10-02 11:48:01 +08 生成，记录 PASS。两者均不说明当前 A17 状态；A17 是数据 job/checkpoint 恢复，与 member recovery 无关。A18/A30 的 PASS 也不是成员恢复证据。

本轮输入 pins、12 项写入清单、文件 size/SHA、原字节快照与副本校验见 [JSON 清单](contract_alignment_20261009.json)。三份审计副本：[version](reviews/20261009/version_audit.md)、[UNKNOWN](reviews/20261009/unknown_audit.md)、[membership](reviews/20261009/membership_audit.md)。原合同快照：[data_contract](reviews/20261009/data_contract.before.md)、[interfaces](reviews/20261009/interfaces.before.md)。合同文件：[data_contract.md](data_contract.md)、[interfaces.md](interfaces.md)。

写后静态校验包括 JSON 解析、输入 pins、原始快照和 byte-prefix、6 份报告逐字复制、DOCX hash 不变及本地链接存在；没有运行 tests、CLI 或数值计算。
