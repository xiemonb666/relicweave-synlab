# V1.47 user update diff summary

## Decision summary

The user V1.47 file is a specification update built from the V1.46 integrated baseline. It adds a three-level retrieval goal, whole-vessel membership evaluation, high-degradation tests, and the UA-IFRMN research candidate. It omits the seven current closeout status paragraphs. Use the current closeout as the merge base and transplant the reviewed specification deltas while retaining its status and font/style fixes.

## Counts and integrity

- Paragraph/cell stream: baseline **6846**, current closeout **6853**, user V1.47 **7462**. Baseline→user: **619 adds**, **3 deletes**, **6 probable replacements**; net **+616** blocks. Current closeout→user: 619 adds, 10 deletes, 6 replacements.
- Headings: 339 → 372 (**+33 added heading entries by alignment**).
- All three packages contain the same 23 part paths. All 14 document relationships and all 19 package relationship declarations match; all 520 bookmark `(part,id,name)` identities match.
- V1.46 and user style definitions match. Current closeout differs in 75 style definitions; incoming paragraphs use Heading2, Heading3, Normal, and SYNBody, which all exist in the current closeout. Preserve its font/style fix.
- No historical experiment-result or old numeric-result paragraph changed. New appendix content adds A12.21–A12.23; the updated history-use paragraph says old results remain frozen.

## Main deltas

1. **Task scope:** R2 direct-neighbor retrieval becomes Level 1; Level 2 adds same-vessel R1/R2 retrieval; Level 3 targets a closed-gallery member set from one query fragment. It is not full geometric assembly or restoration.
2. **UA-IFRMN:** proposes typed soft relations, separate direct-contact and same-vessel reasoning, R2 local and vessel identity memory, candidate-conditioned feedback, evidence provenance, reversible rereading, and bounded stopping. It is explicitly a research candidate.
3. **Evaluation:** adds Vessel Precision/Recall/F1 and complete member manifests; restricts Level 3 claims to closed membership sets with missing-fragment disposition and UNKNOWN preserved.
4. **Robustness:** adds paired D0→Dn degradation comparisons, matched traditional and static-learning baselines, real-domain confirmation, whole-vessel episodes, and real-domain utility gates for synthetic scale-up.
5. **Product/workflow:** adds separate R2, R1/R2, and predicted vessel-set views; human accept/reject with revisions; research-mode labeling before Level 3 validation. Mission language preserves recapture/STOP, but D6.5 demo path does not name recapture as a UI action.
6. **Governance/delivery:** adds frozen-history rules, narrows novelty claims, and replaces two shorter old contest/paper plan paragraphs with new section 10.

## Added section headings

- block 184: 1.3 V1.47信息优先级与历史数据保护规则
- block 210: 2.0 最新统一任务定义：从邻片检索到整器物成员恢复
- block 326: 2.2.2 器物成员恢复指标、完整分母与退化曲线
- block 333: 2.4 痛点、应用价值与“为什么需要AI”的边界
- block 1051: A6.14 2025–2026 近邻任务与跨领域前沿工作增补参考池
- block 1124: A6.15 新核心候选：Uncertainty-Aware Iterative Fragment Relational Memory Network（UA-IFRMN）
- block 1151: A6.15.1 UA-IFRMN 的一次完整推理循环
- block 1160: A6.16 从 R2 到 R1 的关系代数：允许“身份传播”，禁止“邻接传播”
- block 1183: A6.17 为什么不能只把“邻片概率”喂回去：Scalar Feedback、Latent Feedback 与多假设记忆
- block 1212: A6.18 双记忆与器物潜变量：R2 Local Memory × Vessel Identity Memory
- block 1233: A6.19 错误传播控制：Predict → Verify → Soft Write → Reread → Revise
- block 1261: A6.20 训练路线：Oracle 关系上限 → 预测关系闭环 → 人工腐化鲁棒性
- block 1293: A6.20.1 候选损失项：先作为可拆卸假设，不一次全部启用
- block 1296: A6.21 必做实验矩阵：先证明“邻片上下文有信息”，再证明“新机制能安全利用它”
- block 1348: A6.22 可形成的研究主张与明确禁写项
- block 1362: A6.23 创新账本增补：UA-IFRMN 关系记忆路线
- block 1426: A6.24 本次增补的外部来源与复现优先级
- block 1445: A6.25 Whole-Vessel Membership Recovery：从一块碎片恢复整个器物成员集合
- block 1470: A6.26 High-Degradation Robust Retrieval：高磨损、风化与部分观测下的鲁棒碎片检索
- block 1495: A6.27 统一论文路线：共享一个问题族，不把所有创新强塞进一篇论文
- block 1523: A6.28 顶会级研究门槛与禁止性表述
- block 1579: EXP10 高磨损/风化鲁棒性基准
- block 1581: EXP11 整器物成员恢复（Vessel Membership Recovery）
- block 1583: EXP12 R2→R1关系上下文与错误传播
- block 2200: A12.21 V1.47退化性能曲线：把SyntheticLab变成“物理退化压力测试仪”
- block 2202: A12.22 Whole-Vessel Episode Generator：为整器物成员恢复生成完整关系世界
- block 2204: A12.23 Synthetic-to-Real与数据充分性：最终只以真实域收益决定扩容
- block 2267: B2.3 器物成员集合GT与关系闭合
- block 3105: D6.5 器物成员恢复页（V1.47新增）
- block 3188: D10.2 应用价值、社会价值与AI必要性的证据矩阵
- block 3526: 10.1 竞赛方向：用“真痛点→真操作→真改进”组织叙事
- block 3548: 10.2 论文方向：一套数据底座，多条可独立收敛的研究问题
- block 3551: 10.3 竞赛与论文共享的证据底座，但结论严格分开

## Critical boundary

A6.16 refers to historical adjacency truth when finalizing R2/R1/UNKNOWN; keep that truth as training labels/evaluation only, never an inference-time feature. The document separately says TruthPack is evaluation-only and presents Oracle-R2 as a controlled upper-bound experiment, which is compatible if the separation is enforced. The current closeout still reports zero complete physics-qualified package and no established end-to-end retrieval benefit; the user's proposed metrics, gates, and architecture are not achieved results.

## Exact replacements and omitted closeout status

The paired JSON carries exact old/new replacement text plus the seven status paragraphs. The full detailed paragraph/table-cell manifest is `diff_v147_user_manifest.json`; the larger structural extraction and readable full report are diagnostic artifacts, not merge inputs.

## Feasibility and merge path

Level 3 is feasible first on explicitly closed synthetic episodes, then on a separately closed real cohort; incomplete natural collections can support Level 1/2 only. UA-IFRMN should start with bounded Top-K graphs and limited reread radius/rounds because full-graph refresh may be O(N²). Preserve the user's own oracle→predicted→corrupted go/no-go sequence; do not claim a real-domain result until current physical/data qualification gaps are closed.

Merge from current closeout; import the reviewed new sections and replacement wording; retain the seven closeout status paragraphs and current style/header/font fixes. Reconcile the removed old delivery paragraphs with section 10. No merge or source-file edit was done.

## Source hashes

- RelicWeave_V1.46_A12_VesselForge_PGFrag_Integrated_NavFixed.docx: 733634 bytes, SHA-256 `15978a3956fa33e8048cc54c1dad6878a7e19d9c71b84415dcaf8732f041a3b4`
- RelicWeave_V1.47_A12_VesselForge_PGFrag_Closeout.docx: 734565 bytes, SHA-256 `9af0efe877115200dd99bbcf8f24f3124e2932245d71795fc00252d08e278436`
- RelicWeave_V1.47.docx: 779513 bytes, SHA-256 `41f1254e40a2ecabdcfa1c6583af2fce0ae1b0ab980d5f9179bbaf687b7be64b`
