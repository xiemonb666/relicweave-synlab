# UNKNOWN 语义交叉审计

审计日期：2026-10-09。结论基于静态只读检查；没有运行测试、训练或 solver。

## 结论

当前 SynLab 实现没有把 UNKNOWN 当作第四个物理关系类别训练。UNKNOWN 确实出现在关系存储/批次标签码表中，但用于记录未决标签、padding 默认值和排除原因；训练掩码禁止 UNKNOWN 进入正负监督。当前训练主路径也没有输出 R0/R1/R2/UNKNOWN 的关系分类 logits：它以单一相似度分数做多正例排序，另有一个语义不同的三类矛盾/兼容性辅助 CE。

真正的问题在 V1.47 主 DOCX 的未来方案文字不一致：早段已规定三类关系 CE；UA-IFRMN 步骤和 T0 表又写成 `R0/R1/R2/UNKNOWN posterior` 或四类输出；同段稍后才明确 UNKNOWN 是独立认识论拒判状态、物理后验只有 R0/R1/R2。建议统一成“3 类物理关系分数/后验 + 独立 abstain/decision status”，保留 UNKNOWN 作为数据标签/存储状态。评测 API 有通用接受/拒绝指标，但 `training.api.evaluate` 当前阈值筛的是原始 embedding dot score，候选行状态仍固定为 `OK`，不能当作已实现的校准拒判接口。

## 已确认的合同与代码事实

1. **物理关系与身份关系。** 当前计划定义 R2 为同一 clean 事件叶片共享超过阈值的真实新断裂面；R1 为同一物理母体、同一互斥事件库内没有直接有效断裂面；R0 为不同物理母体。TINY_CONTACT 保留测得面积但属于数值灰区；UNKNOWN 表示关系或来源不能确认，`loss_mask=false`，不得编码成 R0。R2 对称、无自环、不传递（`A12_Codex_Execution_Plan_V1.2.md:672-678`）。主 DOCX 也以物理器物表述为 R0=不同器物、R1=同器物且无直接历史断裂接触、R2=直接历史邻接、UNKNOWN=未确认（当前主 DOCX `BODY[109]`）。

2. **UNKNOWN 是合法存储码，不等于分类目标。** 运行时只有字符串常量和 `RelationEdge.kind: str` 字段（`C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\synlab\schemas\runtime.py:255-271`）；训练标签映射是 `R0=0,R1=1,R2=2,TINY_CONTACT=3,UNKNOWN=4`（`C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\synlab\training\adapter.py:36-42`）。批次初始化把空槽填为 UNKNOWN code，并以 `pair_valid=false` 分开标记；实样关系标签会保留该码用于索引/审计（`C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\synlab\training\batch.py:425-435,454-460`）。因此不能仅因 enum 存在 UNKNOWN 就判定它被送入 softmax；也不应为了消除误会而直接删码，否则会破坏存储与 padding 语义。

3. **UNKNOWN/TINY 的监督掩码。** 正例必须是确认的 R2；普通负例经过 `assert_legal_negative`，UNKNOWN、TINY_CONTACT、历史 R2、未确认行都会被拒（`C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\synlab\training\batch.py:214-233,461-481`）。显式排除行标出 `excluded_mask` 和 UNKNOWN/TINY exclusion reason（`C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\synlab\training\batch.py:484-503`）。批次末尾还运行 `negative_audit`，发现 R2/UNKNOWN/TINY 落入 `neg_mask`、未确认行落入监督即拒绝该 batch（`C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\synlab\training\batch.py:236-253,579-613`）。`plan_30_12_evidence` 另计 `unknown_rows_inside_supervision`、未确认监督行和监督中实际关系码（`C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\synlab\training\supervision.py:280-310`）。

4. **当前不是三类或四类关系分类器。** `PairRefineHead` 文档接口返回一个 `refine_logit`，MLP 最后一层维度为 1（`C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\synlab\training\model.py:369-390`）。当前 `Trainer` 主路径由双塔向量点积生成 `[Q,C]` 单分数，按 `pos_mask/neg_mask/allowed` 进入排序损失（`C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\synlab\training\trainer.py:433-463`；排序函数逐个 R2 正例对合法候选分数做 logsumexp，多个正例各自成项，`C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\synlab\training\losses.py:137-145`）。训练代码中未找到 `relation_logits` 或 `relation_head` 符号。局部对应任务的 `log_softmax` 是 token 匹配候选分布，不是 R0/R1/R2 关系类别（`C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\synlab\training\losses.py:336-393`）。

5. **现存三类 CE 的含义不同。** `contradiction_loss` 将末维固定为 3，但标签语义明确是 `0=missing, 1=compatible, 2=contradicting`；valid mask 把 missing/不可信项排出分母（`C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\synlab\training\losses.py:565-592`）。Trainer 从 `[0, sim, -sim]` 构造这 3 个 logits（`C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\synlab\training\trainer.py:566-593`），不是关系三类 head，也没有 UNKNOWN 类。

6. **拒判评测与 UNKNOWN 真值分开。** 通用 `diagnostics.metrics.accept_set` 支持阈值与 `observed_valid`，允许一次接受多个候选；`query_metrics` 接受独立 `status=REJECTED` 并对有邻片的拒判固定记 `EffectiveHit/EffectiveCov=0`（`C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\synlab\diagnostics\metrics.py:168-186,252-284,312-335`）。但是 `training.api.evaluate` 的 `accept_threshold` 直接筛 `emb[q] @ emb[c]` 原始点积，接受集为空时每 query 的 `status` 仍是硬编码 `OK`，顶层返回也固定 `OK`（`C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\synlab\training\api.py:209-219,371-373,405-429,503`）。这提供了阈值筛选/有效指标，不足以证明校准置信度或模型驱动 abstain 已实现。

7. **关系 AUC 的掩码边界需明确。** `relations.negatives.discrimination_auc` 以“R2 vs everything else”计算二元 AUC，样本过滤只检查 `valid`，不检查 `loss_mask`（`C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\synlab\relations\negatives.py:892-928`）。真值生成器会把 TINY_CONTACT 写成 `valid=True, loss_mask=False`（`C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\synlab\truth\api.py:770-785`），所以它会被该函数作为非 R2 项计入负类。该函数可以是宽口径诊断；若要作为确定标签关系评测，应显式排除 loss mask=false 的 TINY/UNKNOWN 行。当前真值生成器把 UNKNOWN 写成 `valid=False, loss_mask=False`，所以正常生成的 UNKNOWN 行会被 `valid` 过滤，但调用方传入 `valid=True` 的 UNKNOWN 仍可能落进负类。

8. **真值层验证了 R2 非传递。** 真值 API 明确规定关系对称、无自环、不作传递闭包；UNKNOWN 始终 `loss_mask=False`，不改写成 R0（`C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\synlab\truth\api.py:6-15,1359-1398`）。已有测试文件定义 A-B 与 B-C 为 R2、A-C 为 R1，并断言 `transitively_closed=False`（`C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\tests\a12\truth\test_relations.py:54-65`）。这里只核对测试代码，没有执行测试。

## DOCX 文本冲突与契约空白

以下 `BODY[n]` 是用指定 bundled Python 对当前主文件 `word/document.xml` 的 `w:body` 直接子节点从 0 开始编号；表格另列行号。文件为 `C:\Users\xiemo\Desktop\ShardForge\RelicWeave_V1.47_A12_VesselForge_PGFrag_Closeout.docx`：

- `BODY[181]` 允许片对 R0/R1/R2 分类，同时明确多名 R2 候选不能用唯一正类 softmax 强迫互斥；`BODY[201]` 说 UNKNOWN 退出监督分母；`BODY[211]` 明确 `relation_logits` 只有 R0/R1/R2 三个 logit。
- 与之冲突的是 `BODY[324]`、`BODY[327]`：relation head / recurrent reasoning 写成输出并更新 `R0/R1/R2/UNKNOWN posterior`。`BODY[352]` 的 T0 Pairwise baseline 行也写“输出 R0/R1/R2/UNKNOWN”。
- 文档自身的正确分离规则出现在 `BODY[331-334]`：`BODY[332]` 明确 UNKNOWN 是独立认识论拒判状态、不是第四物理关系；物理后验只覆盖 R0/R1/R2；同器物身份在闭合成员集合内是等价/传递关系，R1/R2 直接关系本身不传递；`BODY[334]` 建议分开 same-vessel 与 direct-contact 两个头，并将 UNKNOWN/abstention 作为独立拒判状态。
- `BODY[1627]` 的表格 relation 行把 `int8` enum 写成 R0/R1/R2/UNKNOWN，并注明 UNKNOWN 由 `loss_mask` 排除；这是允许的存储合同表达，但和实际映射缺少 TINY_CONTACT 码的说明。执行计划 §11.1 已把 TINY_CONTACT 定义为单独灰区类别。

文本冲突属于方案表述不一致；静态检查没有发现源码存在四/五类物理关系 head。未来 typed head 与 same-vessel 图推理属于建议设计，不能写成当前已实现能力。

数据合同 `C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\docs\a12\data_contract.md` 自述运行期权威在 runtime/spec/roles/store（第 3-5 行）；它只说 RelationPack 携带“R 标签、灰区、监督 valid、loss mask、pool”（第 14-19 行），全文没有 UNKNOWN、三类物理 logits 或 abstain 的明确字段/分层定义。建议补齐，不让读者从 codebook 推断 model head。

## 推荐决策

把关系标注、物理关系预测和系统决策建成三个分开的字段/接口：

- `relation_truth` / `relation_kind` 存储 R0/R1/R2；TINY_CONTACT 与 UNKNOWN 仍保留为可审计存储值。仅确认且可监督的 R0/R1/R2 行进入物理关系 loss；UNKNOWN 与 TINY 的 `loss_mask=false` 具有实际监督约束。
- 若实现关系分类器，`physical_relation_logits` 固定三维 `{R0,R1,R2}`，在**每个 pair 内**做三类概率。UNKNOWN 真值未决时整 pair mask 出物理 CE；它不是第四个 logit，也不映射为 R0。
- `same_vessel_score/probability` 表示 membership；`direct_R2_score/probability` 表示直接历史邻接，并约束 `P_R2 ≤ P_same`。R1 只要求该 pair 的同器物归属已确认，且该 pair 的历史直接邻接已充分排除；不要求整个 frozen gallery 的成员集合闭合。缺边、不可见或证据不足不能仅凭“未观察到 R2”自动推成 R1。完整成员闭合用于 Level 3 分母资格，不是单个 pair 判为 R1 的前提。
- `decision_status` / `abstain_reason` 独立表达 ACCEPT / REJECT / ABSTAIN、证据覆盖、校准策略版本。模型 abstain 是动作/决策结果；训练标签 UNKNOWN 是真值未确认状态。阈值或 coverage 规则基于分离校准集，不把未知真值放入关系 softmax 来“训练拒识”。
- pair 分类的三类 softmax 不应混同候选池归一化。一个 query 可以有多个 R2 候选；排序和接受集合必须保留多正例。

## 最小验收项

1. 三类关系 head 形状断言为最后维 `3`，输出名与序明确为 R0/R1/R2；代码搜索和 checkpoint metadata 中不得把 UNKNOWN/TINY 当物理 logits 类。
2. 构造 R0/R1/R2/TINY/UNKNOWN、padding 与无观测行 fixture；断言只有 confirmed 有效 R0/R1/R2 进入物理关系 CE，关系监督中的 UNKNOWN/TINY 不被当作关系负例或硬负例，关系 AUC 按确定关系 mask 取样并输出排除原因。点对应任务独立使用 mapping_valid：pair-level UNKNOWN/TINY 不自动令局部映射无效，也不自动生成或屏蔽 correspondence dustbin；只有对应任务自身无效/未决的样本才按该任务规则处理。
3. 加一条 `UNKNOWN, valid=false, loss_mask=false`，再加一条恶意 `UNKNOWN, valid=true, loss_mask=false`；关系训练/评测消费者不得以 `valid` 单独替代关系 `loss_mask`。若记录不一致，由关系数据质量门拒绝或按关系 mask 排除；点对应消费者单独检查 `mapping_valid`，不得把关系标签 mask 等同于点映射 mask。
4. A-B R2、B-C R2、A-C R1 fixture：same-vessel membership 可在闭合成员集合内传递，R2 不能传递；单个 pair 只有在同器物归属已确认且该 pair 的 R2 已充分排除时才判 R1，不能只凭缺少 R2 记录推断。完整 gallery 闭合仅用于 Level 3 分母资格。
5. q 同时有 B/C 两个 R2：关系 pair logits 各自分类、列表损失不令 B/C 竞争唯一正类、接受集可以同时含 B 与 C。
6. 低置信/证据不充分的已知关系触发独立 abstain decision；记录原排名、拒判状态/原因、策略与阈值版本、接受率、风险和有效召回。有邻片而拒判时 EffectiveHit/Cov 为 0；无邻片错误接受另计风险。评测状态不得仍标 OK。

## 边界

本次只读了当前 closeout 主 DOCX、原始 `RelicWeave_V1.47.docx`（仅溯源）、执行计划、数据合同和当前源码/测试文件；检索排除了 workspace_backup、旧 backup、vendor 与 third_party 快照。没有修改源码、DOCX、合同或 Git 状态，也没有运行测试/训练/solver。DOCX 证据来自 `C:\Users\xiemo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -B` 的 zipfile/lxml 解析。

