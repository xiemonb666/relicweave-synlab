# RelicWeave V1.44 总计划与 A12 交接审阅

审阅日期：2026-10-02（Asia/Shanghai）  
范围：总计划、A12 子计划与指定交接文件、状态/验收快照、现存实现证据。本文是基于文件和报告的只读核对；没有重跑服务、生成任务或训练。

## 文档与证据基准

- 总文档：`RelicWeave_V1.44_Optimized_Complete_Plan.docx`，546,163 bytes，SHA-256 `4507ead923d60cc8dc20c2a31e532394f4d8ab406a5703bf09eeb606ab6f6374`。
- 按 DOCX XML 正文顺序抽取段落和表格：`relicweave-synlab/tmp/review_20261002/plan_docx_extracted.txt`，覆盖 1,807 个正文段落（其中 8 个空段落）和 128 张表；提取文本 3,030 行。下文同时给 DOCX 的段落/表格编号和提取文件行号，方便复核。未做版面审阅。
- 子计划：`A12_Codex_Execution_Plan_V1.2.md`。其第 5–13 行声明它是 V1.1 Markdown 附件的执行方案，编写时未读取其所称的 V1.45 Word、A3/A4 完整接口或实际仓库；M00 必须先核验外部合同。当前 A12 自己的 `docs/a12/contract_diff.json` 也保留 `MAIN_REPO_INTEGRATION_PENDING`（第 5、8–13、67、74、77 行）。
- 指定交接文件 `docs/a12/HANDOVER.md`、`status.md`、`open_items.md`、`architecture.md`、`acceptance_report.md`、`status_matrix.csv` 均已全文读取。行号均相对 `relicweave-synlab/`。

## 总项目是什么，A12 在哪里

总计划明确主任务是：从真实的低质量、部分碎片观测出发，在混合图库中检索真实邻片候选；证据不足时建议有成本约束的补拍或停止，而不是自动拼完整器物。总计划还明确目前是手机加人工转盘，真实输入规模、真值完整度和检索效果仍待记录验证（DOCX p3–5；提取文件第 4–6 行）。文档导航列的是 A1–A12；没有名为 A0 的岗位/章节。若使用“A0–A12”称呼，A0 应指总纲/项目边界（DOCX §§1–2），不能误写成一个已有独立实现的 A0 模块（提取文件第 7–23 行）。

总计划中的 A1–A12 职责分别是：A1 架构与近期工作；A2 旧模型重构；A3 输入/表示合同；A4 静态主干；A5 训练和损失；A6 CTM/循环机制研究候选；A7 主动补采、自监督与强化学习；A8 实验卡；A9 报告和失败处理；A10 推进与交接；A11 技术参考；A12 可控合成、预训练和退化诊断（DOCX p12–23；提取文件第 12–23 行）。A6 中的创新仍是候选，须先经冻结、可归因对照和真实低质输入验证（DOCX p114；提取文件第 160 行）。

**A12 是 A3/A4 的实验支线和数据/诊断基础设施，不是替代 A3/A4 的主检索产品，也不是独立的真实效果证明。** 总计划给出的关键依赖是：

```text
真实采集主线：真实照片/合法可选几何 → A3 ObsPack/FeaturePack 输入合同
             → A4 全库初检 M → 局部互补精排/可靠性/拒识 → 候选证据卡
             → A7 真实补拍建议或 STOP → 冻结评测与独立真实确认

A12 支线：参数化器物/纹样 → 碎裂和分层真值 → 损伤/相机/退化
          → 同义 ObsPack/RelationPack → 合成预训练及 N×Q/机制诊断
          → 固定真实数据的 T0–T3 迁移比较 → 独立真实测试
```

这是“支线服务主线”的关系：A12 与真实采集并行但绝不取代它；合成平台继续回答“真实邻片能否进入候选集合”，使用同一 `any@50`、`Hit@10`、`CovRecall@10`、开放库拒识和真实工作流口径（DOCX p345–346；提取文件第 586–588 行）。A12 生成的 ObsPack/FeaturePack 字段须与 A3 同义；合成 provenance 可用于审计，但对象 ID、seed、GT 邻接和原装配姿态不得进入推理特征（DOCX p370–373、表 p372；提取文件第 650–662 行）。A12 输出应进入上述合同，再由 A3/A4 的真实评估链判断是否有用，不能用独立 `a12.obs.v1` 自证已接入。

具体依赖：

- **A3→A4：** A3 定义可变数量的真实观察，包括整片和断口 ROI、质量、相机/标定、来源分组和可选几何；禁止 ID/GT/答案字段。A4 规定共享 DINOv2 编码器、整片与局部描述的并集初检、冻结预算 M、局部双线性/交互精排、单独的可观测性/可靠性，以及支持、冲突、观察不足和未建立对应等输出（DOCX p130–160；提取文件第 193–239 行）。A4 的候选链要求全库初检、局部精排、证据卡与版本日志（DOCX 表 p102；提取文件第 127–136 行）。
- **A7→真实采集：** ActionProposal 的输入依当前真实证据、候选、台体能力和剩余成本；最初人工执行 SOP，硬件通过后再接自动适配。追加照片后提升 observation revision 并对冻结全图库重检；只重排初检池要标作 `POOL_RERANK_ONLY`，不能宣称找回了池外邻片（DOCX p270–290；提取文件第 469–489 行）。A12 可做受控 episode/规则策略诊断，不能代替真机动作、真实图像、动作成本和真实候选变化。
- **A12→冻结实验/真实迁移：** 合成平台先验证真值、可重放性、单因素退化、关系与负例，再做预训练/机制实验；真实迁移必须固定真实训练/确认母体、输入、选择规则和预算，并保留 T0–T3 各自初始化/可训练边界。只有独立真实测试上的可归因结果才可升级主线主张（DOCX p391–404、表 p396；提取文件第 724–738、742–745 行）。合成 N 不得换算成真实 N；N×Q 曲面是资源诊断而不是因果证明（DOCX p348、p382–385；提取文件第 590–596、689–710 行）。

## A0–A12 范围与现存实现的对应

下表区分“代码/fixture 已存在”和“对应总项目能力已被验证”。后者不能由前者自动推出。

| 总计划范围 | 当前实现/证据 | 结论 |
|---|---|---|
| A0 总纲与产品边界（非编号章节） | README 将 `relicweave-synlab` 声明为 A12 独立工程，并注明 `MAIN_REPO_INTEGRATION_PENDING`（`README.md:1–10`）；架构文档称“独立工程、无主仓”（`docs/a12/architecture.md:5–12`） | 平台定位有明确说明；A0 本身不是交付模块。当前 checkout 内无主 A3/A4 工程。 |
| A1 架构、项目执行与接口边界 | A12 有 schema、资产库、调度、pipeline、API/UI 和验收模块目录（`docs/a12/architecture.md:22–48`） | A12 内部平台工程已实现不少；不能当作主产品的 A1/A3/A4 端到端集成。 |
| A2 旧模型复现/重构 | A12 有训练 adapter/model 和自己的训练 API；`FragmentEncoder`、`PairRefineHead` 在 `synlab/training/model.py:116,369` | 这是独立 A12 模型原型。未见主仓旧模型的已验证迁移或兼容锚点。 |
| A3 输入/表示合同 | SynLab 使用 `a12.obs.v1`（`synlab/observe/features.py:37,169–183`），contract diff 明说外部 schema 缺失且未映射字段仍 PENDING（`docs/a12/contract_diff.json:5–13,67–77`） | A12 自有输入合同存在；A3 合同适配/一致性未完成。 |
| A4 静态主干/全库候选检索 | 有独立双塔/精排类、训练 API、关系图库和 build-pool API（`synlab/training/model.py:116,369`；`synlab/relations/api.py:308,815`）；SANDBOX 验收 A29=NA（`docs/a12/status_matrix.csv:122`） | 有合成平台内的原型组件，不等于总计划 A4 的 DINOv2 主干、真实 gallery、候选 M、可靠性/拒识和真实端到端测试。当前主仓集成 pending。 |
| A5 训练方式/损失 | 子系统实现五任务损失和训练/checkpoint 的计划证据见 `docs/a12/status_matrix.csv:148`；`status.md:42,47` 报一次 rank loss 下降和旧包 `--check` 通过 | 仅能支持“训练路径/玩具拟合曾运行”。rank 包适格性已有资格策略问题，且无 A4/真实效果结论。 |
| A6 循环/CTM | 合成方案和候选研究设计存在；总计划明确这只是长期创新候选（DOCX p114、p230–268、p387–390） | 未证实为可部署/有效机制；须按对照和止损规则验证。 |
| A7 主动补采/RL | `synlab/episodes/env.py:78` 存在 EpisodeEnv；架构列有 `synlab/episodes`（`docs/a12/architecture.md:44`）；验收 A19 仍 `NOT_RUN`（`docs/a12/status_matrix.csv:112`） | 有模拟/规则接口代码；真实相机/补拍收益与策略有效性未验证。 |
| A8–A11 实验、报告、推进、参考 | 有诊断、统计、experiment protocols、状态和操作文档 | 是平台/方案基础；不能把规格页、统计 fixture 或状态表当作真实模型结果。冻结确认仍需实际完整运行。 |
| A12 合成碎片实验室 | 独立实现覆盖母体、材料、纹样、断裂、真值、损伤、相机、观察、退化、关系、训练、诊断、episodes、QC、API/UI（`docs/a12/architecture.md:22–48`） | 是本仓库主体；软件平台进展丰富，但验收存在 FAIL/PENDING/NOT_RUN，物理真实性和真实迁移没有整体通过。 |

### 依据交接资料能成立的状态

- **已验证/有运行证据（限具体子项）：** API/存储、部分相机/坐标/权限/恢复/确定性等有 fixture 或专门测试；A12 的不少模块已有代码。`status.md:42,47` 记载 `rank loss 6.32830→6.05966`、包加载器退出 0、哈希自检，以及当时 119 个 storage tests 通过。此证据证明测试/训练路径能运行，不证明有效真实候选检索。最新 `status.md:104` 的验收汇总是 FAIL 4（A05/A06/A09*/A24）、PENDING 6、NOT_RUN 6、NA 7，不能用无根据的百分比概括。
- **部分验证：** status 记载 31×5 退化测试与 31 轴注册，但同一资料只说 9 轴物化、33 档（`status.md:47`）；“轴已注册/fixture 通过”不等于完整物理数据与成像路径均已物化。母体总资产数字不能代替独立母体：`acceptance_report.md:14` 给 `total_mothers=55`、19 类器型且每器型最低 lineage=1，但 A03 仍 PENDING；`status.md:85` 记录独立母体 `1/20`。
- **生成/真值重要门未过：** 花纹 A05 FAIL；断裂守恒 A06 FAIL；物理损伤 A09 待重跑/失败；来源 DAG A24 FAIL（`status.md:104`、`status_matrix.csv:98–103,117`）。另有 pattern inheritance 仍 FAIL、真实花纹章法/釉色统计未做（`open_items.md:105`）。
- **缺失/未跑：** SANDBOX 中 A19 episode=NOT_RUN、A29 检索匹配=NA（`status_matrix.csv:112,122`）；真实标定、T0–T3 迁移、≥20 独立母体、主仓 A3/A4 接口仍 pending（`open_items.md:118,121–123`）。
- **隐式断裂不是“仍平”，但也没过门：** 最新 `data/a12_reports/implicit/measure_delivered.json` 有非零实测粗糙度（Ra 3.676 mm、Rz 11.214 mm）、1,183,196 面闭合网格和两片水密断片；同时 source coverage=0.993161，低于 0.999，`audit.passed=false`。因此 HANDOVER 的“断口仍平”已过时，但不能据此称断裂守恒/来源映射整体通过；A06 仍 FAIL。粗糙度值是生成/测量结果，不等于与真实材料统计校准。

## 交接声明中已过时或相互矛盾之处

1. `HANDOVER.md:31` 说当前唯一主线是 SDF、断口仍平；`:147` 又说除几何外外观、ROI、包、消融、契约、QA 都“已就位”。最新隐式几何测量表明至少一个样本已经非平面，但 source coverage 未过门；与此同时最新 `status.md:74,82,84,85,104` 和 `open_items.md:105,118–123` 仍列外观问题、QA/N9 反复、A05/A06/A24 FAIL、独立母体不足及主仓集成/迁移待做。故`:147` 的“只等几何”不成立。
2. `HANDOVER.md:130` 把实验就绪包列为 rank `n_allowed=1496, negatives=3120, effective_queries=44` 的期望值；同一文件 `:120` 明确这批 `experiment_ready/negfix` relations 是资格修复前口径，负例高估约 3.5×，修复后当前路径供给 880、有效 query 约 36，且旧包虽 `--check` 通过仍不能直接训练 rank。`status.md:42,47` 的旧 loss/包数字不应当作有效 A4 检索结论；哈希自洽不代表标签资格正确。
3. `acceptance_report.md:35` 将 A24 记为 PASS，而后续 `status_matrix.csv:117` 与较新的 `status.md:104` 将 A24 记为 FAIL；`acceptance_report.md:16` 的 A05 同为 FAIL。验收报告和 CSV 是不同时间的快照，不能择有利值拼成当前通过状态。
4. Handover `:144` 声称最近提交 `3d800d7`、工作树 clean；当前 HEAD 是 `139a5d5`（其父提交 `0f9e680`，见 `git log -2`），本次读取时工作树另有测试文件改动/新增。故 handover 的 git 状态/版本引用陈旧；异步或当前运行进程未在本审阅中独立确认。
5. 资源快照自相矛盾：`status_matrix.csv:144` 仍说 torch 2.5.1+cpu、没有 CUDA torch；`status.md:54–55` 和 `gpu_acceleration.md:38–41,69` 记录 torch 2.11.0+cu128、CUDA 可用及 Blender GPU 路径。能力结论应引用带日期的实测报告，不应再引用旧 CSV 句子。

## 建议接手顺序与当前主张边界

1. 把 `HANDOVER.md` 和 `acceptance_report.md` 当历史快照；接手起点引用当前 HEAD、当前唯一版本化状态台账，并分别记录每个报告的时间与实验包资格策略。暂不复用资格修复前旧包做 rank 训练；需按当前合法负例策略重导出并保存新 manifest。
2. 先补 M00：取得/校验主项目 A3/A4 实际 schema 和代码，逐字段生成 contract diff 与适配器验证；把 A12 的 ObsPack/FeaturePack 输出映射到 A3，明确 A4 主干/候选 M/精排/校准/拒识的真实入口。没有这步前，称呼“ A12 检索原型”可以，称“A4 已实现/已接入”不成立。
3. 以总计划主任务重新列门：真实 query/gallery、R2/R1/R0/UNKNOWN 完整资格、A3 合法输入、A4 全库初检和精排、可靠性/拒识、候选证据卡。逐项跑静态基线和冻结评测；模拟 episode 或训练 loss 只能作辅助证据。
4. 单独处理 A12 失败门与几何来源 coverage；保留 source coverage 失败事实，不通过放宽门来宣告完成。纹样章法、断口统计、材料表现和成像路径要与软件水密/拓扑检查分开评价。
5. 再做实拍手机补拍/动作成本对照和 T0–T3 迁移；按父器物隔离、冻结开发/确认集合、图库、查询、预算、选择规则和协议。只有独立真实测试上的可归因收益能支持真实迁移或论文主张；没有真实对照时写“工程实现/合成受控证据/未验证”，不写“真实有效”。

仍未由本审阅证实的主张：真实手机检索的命中与风险；合成材料/断口的实物统计拟合；真实花纹章法和釉色分布；所有 A3/A4 主仓接口的兼容性；A7 真机动作策略收益；T0–T3 真实迁移收益；SANDBOX 以外的整套发布门；当前运行进程是否仍存活。
