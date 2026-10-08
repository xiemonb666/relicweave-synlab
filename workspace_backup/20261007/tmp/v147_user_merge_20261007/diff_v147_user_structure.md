# DOCX package structure comparison

## Package part sets

- **baseline RelicWeave_V1.46_A12_VesselForge_PGFrag_Integrated_NavFixed.docx**: 23 ZIP parts
- **current RelicWeave_V1.47_A12_VesselForge_PGFrag_Closeout.docx**: 23 ZIP parts
- **user RelicWeave_V1.47.docx**: 23 ZIP parts

### baseline → user

Part paths added (0): none
Part paths removed (0): none

### current → user

Part paths added (0): none
Part paths removed (0): none

## Direct body block alignment: each top-level w:p or w:tbl is one block

### RelicWeave_V1.46_A12_VesselForge_PGFrag_Integrated_NavFixed.docx → RelicWeave_V1.47.docx

Direct top-level blocks: before=2519, after=2642; operations=147 (added 135, removed 12).
Added kinds: {'paragraph': 114, 'table': 21}; removed kinds: {'paragraph': 9, 'table': 3}.

- ADD body block 1 · paragraph · heading:  · cell paragraphs: —
  - V1.47 整器物成员恢复 × 高退化鲁棒检索 × 竞赛/论文双主线整合版 2026年10月7日
- ADD body block 2 · paragraph · heading:  · cell paragraphs: —
  - 我们研究真实低质量、部分观测与物理退化条件下的文物/器物碎片检索与器物成员恢复。系统从任意一块查询碎片出发，先在混合碎片库中提出直接历史邻片R2候选，再联合二维外观、断口、三维几何、材质、纹样、壁厚、曲率和已发现关系，检索同器物但非直接邻接的R1成员；长期目标是在给定数据库范围内恢复该器物的高置信成员集合。证据不足时系统拒绝强判、给出缺失证据与有成本约束的补采建议。比赛交付强调真实工作流、专家减负与可解释候选；论文交付强调高退化鲁棒检索、R2→R1关系推理、整器物成员恢复和Synthetic-to-Real的可归因机制。
- ADD body block 5 · paragraph · heading:  · cell paragraphs: —
  - V1.47在V1.46双子基础设施版本上统一最新项目主线：将长期最终目标从“找一名邻片”明确升级为“Fragment-to-Vessel Retrieval / Vessel Membership Recovery”，新增高磨损与风化证据下的鲁棒检索主线、传统算法与学习方法的公平退化对照、R2局部接触到R1器物身份扩展、整器物成员级指标、比赛价值验证与CVPR级研究收敛路线。VesselForge、PG-Frag与A12的职责边界保持不变；A12增加对退化性能曲线、完整器物关系episode和Synthetic-to-Real的专门支撑。所有历史实验数值、FAIL、STOP、NOT_SUPPORTED、NOT_ESTABLISHED与冻结协议继续原样保护；本版只更新现行目标、研究候选、实验合同、数据GT、产品展示和交付口径，不用新叙事改写旧结果。
- ADD body block 88 · paragraph · heading: 1 文档体系与现行口径 · cell paragraphs: —
  - 本文件包含总纲、四岗位完整执行正文、软硬件、联调、验收、完整合成实验室、历史附录以及两个独立三维基础设施子项目方案，现行版本统一V1.47。总纲第2章给出最新统一任务、应用价值边界和评测合同；A6维护长期科研创新；A8把科研假设转成实验卡；A12与附录G负责合成、退化、预训练和诊断；附录I/J分别规定VesselForge与PG-Frag。附录A至F及历史实验段落继续作为冻结证据保留，旧数值与判决不能按V1.47的新目标直接改写。
- ADD body block 101 · paragraph · heading: 1.3 V1.47信息优先级与历史数据保护规则 · cell paragraphs: —
  - 1.3 V1.47信息优先级与历史数据保护规则
- ADD body block 102 · paragraph · heading: 1.3 V1.47信息优先级与历史数据保护规则 · cell paragraphs: —
  - V1.47采用“现行执行正文覆盖过时规划、历史证据只增不改”的双层治理。新的最终目标、比赛叙事和论文方向可以更新现行正文，但不得把历史实验重新解释成已经支持新主张。任何旧结论若与现行任务定义不完全一致，保留原文并标明其适用数据、指标和当时协议；只有新的冻结实验才能产生新的证据结论。
- ADD body block 103 · table · heading: 1.3 V1.47信息优先级与历史数据保护规则 · cell paragraphs: 18
  - 信息层 主要位置 V1.47处理规则 现行目标与执行口径 总纲第1–10章、A1–A12及B/C/D执行正文 允许更新；V1.47优先，用于现在做什么、为什么做、如何验收。 长期科研候选 A6创新维护区、A12研究支线 允许追加、降级、停止；RESEARCH_CANDIDATE不等于已实现或已证明。 冻结实验数据 附录A/B/C及正文引用的历史数值、hash、FAIL/STOP/NOT_* 只允许补充来源、解释边界和新复算记录；禁止删除、润色或用新口径覆盖旧数值。 旧规划与旧默认值 历史附录中的旧设备、排期、岗位、下一步建议 不再指导现行执行；为可追溯性保留，不与V1.47现行口径并列使用。 新任务扩展 整器物成员恢复、高退化鲁棒检索、R2→R1关系推理 从V1.47起生效；除非专门复跑，不能反向声称旧实验已经验证这些目标。
- ADD body block 105 · paragraph · heading: 2 合并主线与边界 · cell paragraphs: —
  - 主问题升级为：给定一块真实可获得观测的查询碎片q、一个混合碎片数据库G、候选检查预算和误导风险约束，先可靠找回直接历史邻片R2并识别观察不足，再利用碎片自身多模态证据、已发现局部关系和器物级上下文检索R1，最终尽可能恢复G中与q属于同一物理器物的成员集合V(q)。输入仍以整片2D、断口2D和质量信息为基础；合格3D、可信上下文和主动补采是可选增强。输出从单一Top-K扩展为R2邻片候选、R1同器物非邻片候选、器物成员集合、来源可追溯证据、UNKNOWN/拒识、补采或停止原因。
- ADD body block 108 · paragraph · heading: 2.0 最新统一任务定义：从邻片检索到整器物成员恢复 · cell paragraphs: —
  - 2.0 最新统一任务定义：从邻片检索到整器物成员恢复
- ADD body block 109 · paragraph · heading: 2.0 最新统一任务定义：从邻片检索到整器物成员恢复 · cell paragraphs: —
  - 长期最终目标不是“自动把文物粘好”，而是把专家面对的组合搜索问题分成三个可验证层级：先找直接邻片，再找同器物非邻片，最后从任意一片出发恢复数据库范围内的器物成员集合。Level 3只承诺“数据库中已存在碎片的成员恢复”，不等价于几何全自动装配、缺失部分生成或物理修复。
- ADD body block 110 · table · heading: 2.0 最新统一任务定义：从邻片检索到整器物成员恢复 · cell paragraphs: 16
  - 任务层级 输入→输出 主要证据/机制 核心评价 Level 1：R2 Neighbor Retrieval q + G → 直接历史邻片候选 断口、局部2D/3D、几何互补、接触证据 any@M、Hit@K、CovRecall@K、误导/拒识 Level 2：Same-Vessel Retrieval q + G → R1 + R2同器物候选 材质、纹样、壁厚、曲率、器型先验、R2上下文 SameVessel Hit@K、Precision/Recall、R1专门召回 Level 3：Vessel Membership Recovery q + G → 预测成员集合 V_hat(q) UA-IFRMN关系记忆、Vessel Memory、多轮重检索与可修正关系图 Vessel Recall、Vessel Precision、Vessel F1、误纳入率、迭代成本
- ADD body block 111 · paragraph · heading: 2.0 最新统一任务定义：从邻片检索到整器物成员恢复 · cell paragraphs: —
  - 统一终态：系统接收任意查询碎片后，先输出“Direct Neighbor Candidates（R2）”和“Same-Vessel Candidates（R1/R2）”，再形成“Predicted Vessel Set”，并在新成员加入后重新读取整个器物假设；当新增证据不足、风险过高或预算耗尽时停止，而不是为了追求找全强行扩展。
- ADD body block 113 · table · heading: 2.1 比赛必须实现与论文需要证明 · cell paragraphs: 33
  - 能力 比赛系统的内部必做交付 若作为论文主张需要的证据 输入与数据 新样品登记、手机采集、质量检查、真实邻接依据 母体隔离、标签审计和独立确认集 候选链 全库初检、局部精排、证据卡和版本日志 同输入强基线及端到端公平对照 可靠输出 不强迫确定拼合，展示不足、拒识和人工核验 mate-present覆盖与mate-absent风险同时报告 补采 基础版可人工执行建议；自动台列增强交付 等照片和等时间下分别优于强补采基线 主干创新 部署真实验证较好的稳定模型 互补、可观测性或证据重读的可归因机制增益 现场与产品 离线运行、异常恢复、四人交接、真实耗时 工程表现不能代替方法新颖性 用户价值 实测候选检查量与完整任务时间 参与者、任务与对照公开，避免只报列表缩减 高磨损/风化鲁棒性 至少展示清晰、轻度退化、严重退化三档真实或受控样本；同输入比较传统几何基线、简单AI基线与RelicWeave，展示何时传统精确匹配假设开始失效。 冻结退化轴与配对样本，给出性能—退化强度曲线、置信区间、真实域确认和跨设备/材料守卫；不能只挑极端失败样本。 整器物成员恢复 给定一块碎片，界面同时输出R2邻片、R1同器物候选和器物成员集合；人工可逐项接受/驳回，系统更新成员集且保留版本历史。 正式定义Fragment-to-Vessel Membership Recovery任务，建立Vessel Precisi…
- ADD body block 117 · table · heading: 2.2 内部指标合同 · cell paragraphs: 48
  - 指标 定义与适用范围 目标或判定方式 any@50 有邻片查询中至少一名真邻片进入初检50池 正常质量内部目标宏值0.95，连同区间报告 Hit@10 前10中至少一名库内真邻片 比赛准备目标正常质量宏值0.90，95%下界0.85 低质Hit@10 日常低质查询对清晰库，独立母体 内部目标0.85，达不到则缩小适用范围 CovRecall@10 前10找回库内真邻片的比例 与Hit单列，不低于冻结强基线 新方法主比较 同查询同库相对验证集选出的强基线 开发起点为增益3个百分点且对象簇CI下界大于0 干净性能守卫 新方法相对同池强基线 下降不超过2个百分点，阈值先冻结 无邻片误导 mate-absent查询被接受推荐的比例 目标不超过5%，95%上界目标不超过10% 有邻片接受覆盖 mate-present中被系统接受输出的比例 目标至少80%，不能靠全拒绝换低风险 现场流程 新查询采集到结果的完整彩排 20次至少19次完成，仅作为彩排目标 工作流价值 包括拍摄、补拍、检查的总任务时间 中位用时减少30%为内部目标，正确性不恶化 Vessel Recall 预测器物成员集合中找回数据库内真实同器物成员的比例；分母为冻结且闭合的V_G(q)。 长期核心目标；按母体等权宏平均，并报告成员数分层。 Vessel Precision 预测成员集合中真实同器物成员的比例。 防止“把整个库都收…
- ADD body block 124 · paragraph · heading: 2.2.2 器物成员恢复指标、完整分母与退化曲线 · cell paragraphs: —
  - 2.2.2 器物成员恢复指标、完整分母与退化曲线
- ADD body block 125 · paragraph · heading: 2.2.2 器物成员恢复指标、完整分母与退化曲线 · cell paragraphs: —
  - 对query q定义V_G(q)为冻结图库G中与q属于同一器物的全部可评成员，包含R1和R2但排除q自身；预测集合为V_hat(q)。VesselRecall=|V_hat∩V_G|/|V_G|，VesselPrecision=|V_hat∩V_G|/|V_hat|，VesselF1按二者调和平均。只有object membership已闭合、缺失实物去向已记录且UNKNOWN不被强行归类的母体，才进入Level 3主评测。天然残片若无法证明成员全集完整，可报告候选检索和专家工作流，但不能声称完整器物恢复率。
- ADD body block 126 · paragraph · heading: 2.2.2 器物成员恢复指标、完整分母与退化曲线 · cell paragraphs: —
  - 退化鲁棒性主实验必须使用paired/counterfactual设计：D0、D1…Dn共享同一母体、关系GT、query、gallery组成和基础随机种子，只改变预注册的磨损、崩缺、缺失、成像或重建退化轴。传统算法、静态学习基线和RelicWeave在相同合法观测权限下比较；不能给传统算法更差输入，也不能让模型读取clean/oracle信息。
- ADD body block 131 · paragraph · heading: 2.4 痛点、应用价值与“为什么需要AI”的边界 · cell paragraphs: —
  - 2.4 痛点、应用价值与“为什么需要AI”的边界
- ADD body block 132 · paragraph · heading: 2.4 痛点、应用价值与“为什么需要AI”的边界 · cell paragraphs: —
  - V1.47不再用“AI比传统算法先进”作为价值论证。项目的真实痛点是：当碎片数量大、来源混杂、断口被长期风化磨损、局部对应缺失、R1本来就没有直接接触面时，专家需要在巨大的组合空间中反复筛查；传统几何方法在清晰且对应充分的样本上仍然是强基线，但其精确匹配假设在高退化和弱对应条件下可能失效。RelicWeave的目标是把机器用于海量筛选、弱证据融合、排序、不确定性与关系推理，把专家从“搜索者”转为“验证者”，而不是取消专家的最终判断。
- ADD body block 133 · table · heading: 2.4 痛点、应用价值与“为什么需要AI”的边界 · cell paragraphs: 24
  - 场景 传统/人工方案 RelicWeave应增加的能力 可验证价值 小规模、清晰、断口完整 人工/ICP/曲率/局部描述子可能已足够 AI不是必须；作为强基线和成本下限 证明项目没有“为了AI而AI” 大规模混合碎片库 人工组合搜索随库规模快速变难 向量检索+学习排序缩小候选空间 减少专家浏览、比较与实物搬动 高磨损/崩缺/风化 精确几何对应和手工描述子受损 多模态表征+不确定性+退化训练 在证据残缺时保持更平缓的性能退化 R1同器物非邻接 断口没有直接对应，局部几何无法单独判断 Vessel Memory+关系图+多跳身份推理 从“找邻片”扩展到“找同器物成员” 证据不足/高风险样本 强行匹配会增加误导与不必要试拼 校准、拒识、主动补采 降低错误候选和脆弱实物反复操作
- ADD body block 307 · paragraph · heading: A6.14 2025–2026 近邻任务与跨领域前沿工作增补参考池 · cell paragraphs: —
  - A6.14 2025–2026 近邻任务与跨领域前沿工作增补参考池
- ADD body block 308 · paragraph · heading: A6.14 2025–2026 近邻任务与跨领域前沿工作增补参考池 · cell paragraphs: —
  - 本节是 A6 长期创新区的“外部思想增补池”，只记录能够改变本项目问题建模、记忆结构、关系推理、验证方式或实验设计的机制。所有条目均作为 RESEARCH_REFERENCE，不代表已经适用于 RelicWeave，更不代表已经验证有效。采用顺序固定为：先复现／理解原机制 → 映射到本项目的错误模式 → 提出最小可否定假设 → 单独消融 → 只有真实低质量与独立母体上成立后才允许进入主线。
- ADD body block 309 · table · heading: A6.14 2025–2026 近邻任务与跨领域前沿工作增补参考池 · cell paragraphs: 68
  - 参考工作 原工作关键机制 对 RelicWeave 的可借鉴点与价值 明确不直接照搬的边界 SARe: Structure-Aware Large-Scale 3D Fragment Reassembly（2026，arXiv:2603.21611） 联合预测 fracture-surface token probability 与 inter-fragment contact graph；推理期用几何一致性验证候选接触边，只固定可靠子结构，并对其余不确定部分重采样。 直接说明“大规模碎片下错误邻接会产生级联失败”，因此预测关系不能写成永久事实；本项目可借鉴“先预测—再验证—只软写入可靠结构—不确定部分允许重算”的闭环。 不直接搬其生成式完整装配流程；RelicWeave 的主问题是 R2 邻接候选与 R1 同器物非邻接检索，而非全局 6-DoF 完整拼装。 PuzzleFusion++: Auto-agglomerative 3D Fracture Assembly by Denoise and Verify（ICLR 2025） 从单碎片开始，经扩散模型求位姿、Transformer 验证 pair，再把可信碎片合并成更大组并迭代重复，作者明确将其类比为 auto-regressive / auto-agglomerative assembly。 支持“局部关系 → 局部组件 …
- ADD body block 310 · paragraph · heading: A6.14 2025–2026 近邻任务与跨领域前沿工作增补参考池 · cell paragraphs: —
  - 增补参考池的统一结论不是“把这些模型都接起来”，而是抽取五条可测试的设计原则：① 关系预测必须可验证、可撤销，不能 hard commit；② R2 的局部接触证据与 R1 的器物身份证据需要不同记忆和不同读写策略；③ pairwise 结果只能作为多轮／多碎片联合推理的 prior；④ 一块碎片应保留局部 token 集合和 provenance，而不是被压成单一全局向量；⑤ 迭代反馈应优先反馈连续 latent relation state 与不确定性，而不是只反馈一个概率标量。
- ADD body block 311 · paragraph · heading: A6.15 新核心候选：Uncertainty-Aware Iterative Fragment Relational Memory Network（UA-IFRMN） · cell paragraphs: —
  - A6.15 新核心候选：Uncertainty-Aware Iterative Fragment Relational Memory Network（UA-IFRMN）
- ADD body block 312 · paragraph · heading: A6.15 新核心候选：Uncertainty-Aware Iterative Fragment Relational Memory Network（UA-IFRMN） · cell paragraphs: —
  - 中文暂定名：不确定性感知的迭代碎片关系记忆网络。它不是当前稳定主干的替代品，而是登记在长期创新区的 P0 研究候选。其目标是把原本一次性的 pairwise R0/R1/R2 打分，改造成“局部邻接发现 → 软关系写入 → 多跳同器物扩展 → 新证据联合重读 → 旧关系可修正”的迭代关系推理过程。
- ADD body block 313 · paragraph · heading: A6.15 新核心候选：Uncertainty-Aware Iterative Fragment Relational Memory Network（UA-IFRMN） · cell paragraphs: —
  - 核心科学问题：在真实低质量、断口缺失、纹样不完整和 3D 不稳定的条件下，模型能否利用已经发现的高置信直接历史邻接 R2，构建带不确定性的关系上下文，从而提高同器物但非直接邻接 R1 的检索，同时避免错误 R2 被循环放大为器物级错误？
- ADD body block 314 · paragraph · heading: A6.15 新核心候选：Uncertainty-Aware Iterative Fragment Relational Memory Network（UA-IFRMN） · cell paragraphs: —
  - 这里的“自回归”只保留“上一轮内部结果会影响下一轮推理”这一抽象，不采用离散单路径 hard autoregression。更准确的机制名称为 Contact-Conditioned Identity Expansion + Reversible Relational Memory：直接接触证据先形成局部 relation latent，再作为同器物身份扩展的条件；所有写入都带 posterior、quality、provenance 和 revision 权限。
- ADD body block 315 · table · heading: A6.15 新核心候选：Uncertainty-Aware Iterative Fragment Relational Memory Network（UA-IFRMN） · cell paragraphs: 21
  - 组成 建议定义 为什么需要 Fragment Token Bank F_i 每块碎片保留 token set，而不是单 global vector。建议至少含 global、fracture-local、surface/pattern、material、curvature/profile、thickness、3D local patch、quality/provenance 等槽位。 避免 R2 需要的断口细节和 R1 需要的器物身份证据互相覆盖；也方便按关系类型选择性读取。 R2 Local Memory M_R2 保存候选直接邻接的边级 latent e_ij、R0/R1/R2/UNKNOWN posterior、几何互补、fracture visibility、pose/gap/contact、质量与来源。 给后续 R1 推理提供“已经确认到什么局部组件”的精细上下文，但不把概率当事实。 Vessel Identity Memory M_V 从当前一组高可信 same-vessel 碎片中形成器物级 latent / token pool，保存材质、壁厚分布、曲率趋势、器形 profile、纹样体系和稳定全局先验。 解决口沿与底足等远距离 R1 pair 局部外观完全不相似的问题；判断目标从 pair similarity 升级为 candidate 与当前 vessel h…
- ADD body block 316 · paragraph · heading: A6.15.1 UA-IFRMN 的一次完整推理循环 · cell paragraphs: —
  - A6.15.1 UA-IFRMN 的一次完整推理循环
- ADD body block 317 · paragraph · heading: A6.15.1 UA-IFRMN 的一次完整推理循环 · cell paragraphs: —
  - Step 0 — 编码而不压扁：对 query 和候选库生成 Fragment Token Bank；静态 encoder 可沿用现有成熟主干，先不改变 backbone。
- ADD body block 318 · paragraph · heading: A6.15.1 UA-IFRMN 的一次完整推理循环 · cell paragraphs: —
  - Step 1 — 双路粗检：同时产生高召回 same-vessel shortlist 与 R2 contact shortlist。前者防止“只沿邻片链才能发现远端碎片”，后者为关系扩展提供局部结构 seed。
- ADD body block 319 · paragraph · heading: A6.15.1 UA-IFRMN 的一次完整推理循环 · cell paragraphs: —
  - Step 2 — 形成 Soft R2 edges：relation head 输出 R0/R1/R2/UNKNOWN posterior 与 relation latent；3D 可用时再通过几何互补／接触 verifier 产生额外证据，但 verifier 不直接覆盖网络 posterior。
- ADD body block 320 · paragraph · heading: A6.15.1 UA-IFRMN 的一次完整推理循环 · cell paragraphs: —
  - Step 3 — 不确定性感知写入：只有满足质量和可比较条件的证据才进入 M_R2；其写入是 soft 的，保存 posterior、置信区间／校准量、source 与时间版本，不做不可逆 hard merge。
- ADD body block 321 · paragraph · heading: A6.15.1 UA-IFRMN 的一次完整推理循环 · cell paragraphs: —
  - Step 4 — Contact-Conditioned Identity Expansion：以高置信 R2 seed 或局部组件为起点，在 G_t 上做多跳候选扩展；扩展只提高 same-vessel prior，不直接把多跳终点标成 R1 或 R2。
- ADD body block 322 · paragraph · heading: A6.15.1 UA-IFRMN 的一次完整推理循环 · cell paragraphs: —
  - Step 5 — Candidate-conditioned recurrent reasoning：对每个待判候选读取其自身 token、相关 R2 Local Memory、Vessel Memory 与关系图路径，更新 R0/R1/R2/UNKNOWN posterior。
- ADD body block 323 · paragraph · heading: A6.15.1 UA-IFRMN 的一次完整推理循环 · cell paragraphs: —
  - Step 6 — Joint reread / revise：一旦新碎片被高置信接受，重新计算与该局部组件相关的旧边；允许 old R2 下降、R1/R2 互换、候选休眠或恢复。
- ADD body block 324 · paragraph · heading: A6.15.1 UA-IFRMN 的一次完整推理循环 · cell paragraphs: —
  - Step 7 — 动态停止或继续：当 Top-K、typed relation graph 与 vessel latent 连续多轮稳定且证据预算已足够时停止；若仍冲突则继续读 Evidence Bank，或输出 UNKNOWN / 补采建议。
- ADD body block 325 · paragraph · heading: A6.16 从 R2 到 R1 的关系代数：允许“身份传播”，禁止“邻接传播” · cell paragraphs: —
  - A6.16 从 R2 到 R1 的关系代数：允许“身份传播”，禁止“邻接传播”
- ADD body block 326 · paragraph · heading: A6.16 从 R2 到 R1 的关系代数：允许“身份传播”，禁止“邻接传播” · cell paragraphs: —
  - UA-IFRMN 必须显式尊重现行标签定义：R2 是原碎裂事件当前叶子片间的直接历史邻接，R1 是同器物但无直接历史断裂接触。因此，A—B 为 R2、B—C 为 R2，并不能推出 A—C 为 R2；它只能为 “A 与 C 属于同一器物” 提供强结构证据。最终 A—C 是 R1、R2 还是 UNKNOWN，仍要由直接接触证据和历史邻接真值判定。
- ADD body block 327 · table · heading: A6.16 从 R2 到 R1 的关系代数：允许“身份传播”，禁止“邻接传播” · cell paragraphs: 18
  - 关系组合 允许的推理 设计意义 R2(A,B) + R2(B,C) same-vessel(A,C) prior ↑；A-C 的直接邻接类型仍未知。 最典型的“局部接触链 → 器物身份扩展”。 R2(A,B) + R1(B,C) same-vessel(A,C) prior ↑，但强度应低于双高可信 R2，并受 B-C 证据质量控制。 允许 R1 参与身份传播，但避免弱关系无限扩散。 R1(A,B) + R1(B,C) 只能作为 soft same-vessel 支持；不能做硬传递。 R1 本身可能来自外观／材质相似，错误相关风险更高。 R2 路径 + 强材质／器型矛盾 触发 joint reread 和 hypothesis revision，而不是强制维持同器物。 用反证抑制“图一旦连通就全部同器物”的灾难。 多条独立 R2 路径指向同一候选 可增加 same-vessel belief，但必须做 source de-correlation。 避免由同一重建／同一照片派生的多条证据被重复计权。
- ADD body block 328 · paragraph · heading: A6.16 从 R2 到 R1 的关系代数：允许“身份传播”，禁止“邻接传播” · cell paragraphs: —
  - 研究实现上建议把 same-vessel 与 direct-contact 解耦成两个相关但不同的头：P_same(i,j) 表示器物身份兼容，P_R2(i,j) 表示直接历史邻接；随后由 typed relation head 在 R0/R1/R2/UNKNOWN 上给出最终分布。这样多跳图只影响 P_same 或 vessel compatibility，不会错误地让 R2 具备传递性。
- ADD body block 329 · paragraph · heading: A6.17 为什么不能只把“邻片概率”喂回去：Scalar Feedback、Latent Feedback 与多假设记忆 · cell paragraphs: —
  - A6.17 为什么不能只把“邻片概率”喂回去：Scalar Feedback、Latent Feedback 与多假设记忆
- ADD body block 330 · paragraph · heading: A6.17 为什么不能只把“邻片概率”喂回去：Scalar Feedback、Latent Feedback 与多假设记忆 · cell paragraphs: —
  - 用户提出的原始思路“预测邻片后，把邻片预测作为下一轮输入，再判断同器物非邻片”应保留为最小基线，但正式候选必须把“反馈什么”做成分层实验。单一 P(R2) 只表达最终置信度，不包含模型是依据断口、几何、纹样还是质量得出的结论，也无法区分“高分但证据冲突”和“高分且多证据一致”。
- ADD body block 331 · table · heading: A6.17 为什么不能只把“邻片概率”喂回去：Scalar Feedback、Latent Feedback 与多假设记忆 · cell paragraphs: 24
  - 反馈层级 输入下一轮的内容 研究价值 主要风险 B1 Scalar Feedback 只把 P(R2)、margin、quality 等少量标量反馈给下一轮。 最便宜、最可解释，是用户原始想法的直接实现；必须保留为基线。 信息瓶颈最大，无法携带局部证据结构。 B2 Latent Relation Feedback 反馈 e_ij relation latent + typed posterior + provenance mask。 对应 continuous latent reasoning 思想；允许下一轮利用“为什么像邻片”的连续内部表示。 latent 可能学到不可解释捷径，需要 probe 和 corruption test。 B3 Neighbor Token Set 将高可信邻片的局部 token set 作为可查询上下文，而不是压成一个 latent。 保留断口／纹样／3D 多区域证据，接近 set-to-set retrieval。 计算和显存增加，需 K/L 预算。 B4 Soft Multi-Hypothesis Memory 同时保留多个关系／器物假设，以权重而非 one-hot winner 表示。 避免第一步错边后全链路 collapse；允许后续证据翻案。 需要假设裁剪和去重，否则复杂度膨胀。 B5 Joint Graph Reread 新证据加入后，…
- ADD body block 332 · paragraph · heading: A6.17 为什么不能只把“邻片概率”喂回去：Scalar Feedback、Latent Feedback 与多假设记忆 · cell paragraphs: —
  - 因此推荐研究顺序固定为 B1 → B2 → B3 → B4/B5。只有 B2 在同输入、同候选池、相近 FLOPs 下显著优于 B1，才能说明“连续 relation latent”本身具有价值；否则不允许仅因为结构更复杂而升级主干。
- ADD body block 333 · paragraph · heading: A6.18 双记忆与器物潜变量：R2 Local Memory × Vessel Identity Memory · cell paragraphs: —
  - A6.18 双记忆与器物潜变量：R2 Local Memory × Vessel Identity Memory
- ADD body block 334 · paragraph · heading: A6.18 双记忆与器物潜变量：R2 Local Memory × Vessel Identity Memory · cell paragraphs: —
  - R2 与 R1 的核心证据分布不同。R2 更依赖断口局部互补、接触几何、局部纹理连续；R1 可能没有任何直接接触，反而依赖材质、壁厚、器形曲率、纹样体系、制造痕迹以及当前已恢复器物的整体先验。因此不建议让同一个 memory slot 同时承担两类关系。
- ADD body block 335 · table · heading: A6.18 双记忆与器物潜变量：R2 Local Memory × Vessel Identity Memory · cell paragraphs: 16
  - 记忆层 保存内容 主要服务目标 主要思想来源 短时／局部：R2 Local Memory 断口 patch、局部 3D、法线／曲率、互补场、contact/gap/penetration、局部纹样连续、fracture visibility、质量。 高精度直接邻接验证、局部组件形成、反证。 参考 VisMem 的 fine-grained short-term visual memory、GARF 的 fracture-aware 表征、Combinative Matching 的几何互补。 长时／器物：Vessel Identity Memory 材质、釉色／纹样族、壁厚统计、器型 profile、曲率趋势、已确认组件的全局关系、missing/unknown slots、稳定 provenance。 远距离 R1 检索、同器物候选排序、抑制“只看断口”造成的漏检。 参考 Titans 的短／长期记忆分工、Jigsaw++ 完整 shape prior、Beyond Reassembly missing tokens。 证据源：Persistent Evidence Bank 原始图像、局部 patch、3D、质量和采集版本，不被循环覆盖。 任何关系被质疑时可重新取证；防止 self-confirmation。 与 A6.5 既有 Evidence Bank 一致，本节只扩展其在…
- ADD body block 336 · paragraph · heading: A6.18 双记忆与器物潜变量：R2 Local Memory × Vessel Identity Memory · cell paragraphs: —
  - Vessel Memory 不等于“把所有已接受碎片做平均池化”。建议至少比较：mean pooling、attention pooling、slot-based memory、set transformer／Perceiver-style query，以及带 missing slots 的 vessel token。任何复杂版本都必须对照简单 pooling，防止“多参数 = 更好”的假象。
- ADD body block 337 · paragraph · heading: A6.19 错误传播控制：Predict → Verify → Soft Write → Reread → Revise · cell paragraphs: —
  - A6.19 错误传播控制：Predict → Verify → Soft Write → Reread → Revise
- ADD body block 338 · paragraph · heading: A6.19 错误传播控制：Predict → Verify → Soft Write → Reread → Revise · cell paragraphs: —
  - 这条创新线最大的风险不是“能不能利用正确 R2”，而是“错误 R2 会不会污染后续 R1”。因此误差传播本身必须成为论文级评测对象，而不是部署阶段再修。SARe 的 many-fragment cascading failure、MV-RoMa 的 pairwise chaining inconsistency 以及本项目既有反自证规则共同要求：任何关系写入都必须可撤销、可追溯、可重新验证。
- ADD body block 339 · table · heading: A6.19 错误传播控制：Predict → Verify → Soft Write → Reread → Revise · cell paragraphs: 24
  - 控制机制 实施约束 目的 Soft Write 边只写 posterior + latent + quality + provenance，不写 one-hot 真值。 降低早期错误的不可逆性。 Geometric Verification 有合格 3D 时，用局部互补、gap/contact/penetration、相反体积占据等进行独立物理检查。 把“网络觉得像”与“物理上能接触”分开。 Joint Reread 新碎片加入后，重算与受影响组件相关的旧边。 允许 P(R2) 0.82 → 0.41，而不是永久自证。 Candidate Dormancy / Resurrection 低分但证据不足的候选进入 Dormant，不直接永久删除；新证据可复活。 适应低质输入与遮挡。 Multi-Hypothesis Retention 在高不确定时保留多个图假设或边分布。 避免单路径 autoregression 的早期塌缩。 Source De-correlation 相同照片派生的 2D、3D、重建置信度标记同源。 防止一条错误观测以多种“证据”形式被重复放大。 Abstain / UNKNOWN posterior 不稳定、强冲突或 evidence coverage 不足时输出 UNKNOWN / 补采。 错误控制优先于强迫形成完整关系图。
- ADD body block 340 · paragraph · heading: A6.20 训练路线：Oracle 关系上限 → 预测关系闭环 → 人工腐化鲁棒性 · cell paragraphs: —
  - A6.20 训练路线：Oracle 关系上限 → 预测关系闭环 → 人工腐化鲁棒性
- ADD body block 341 · paragraph · heading: A6.20 训练路线：Oracle 关系上限 → 预测关系闭环 → 人工腐化鲁棒性 · cell paragraphs: —
  - 训练不得从一开始就把完整 UA-IFRMN 端到端同时打开。否则任何增益都无法判断来自“R2 上下文真的有用”、更大模型、更大计算还是标签泄漏。建议按下面顺序建立证据。
- ADD body block 342 · table · heading: A6.20 训练路线：Oracle 关系上限 → 预测关系闭环 → 人工腐化鲁棒性 · cell paragraphs: 27
  - 阶段 训练／输入设置 必须回答的问题 T0 Pairwise baseline 完全不使用关系记忆。输入 q,c，输出 R0/R1/R2/UNKNOWN。 冻结最强静态基线。 T1 Oracle-R2 context 第二阶段只给 GT R2 邻片／局部组件，不给模型自己预测的边。 回答最关键问题：如果邻片信息正确，R1 是否存在足够大的可利用上限？若无明显增益，整条路线停止。 T2 Scalar predicted-R2 使用模型自己的 P(R2) 标量反馈。 验证用户原始想法能否在最小复杂度下成立。 T3 Latent predicted-R2 反馈 e_R2 relation latent 与证据 mask。 检验 continuous relation state 是否比 scalar 真正多提供信息。 T4 Scheduled / mixed memory 训练时混合 GT、predicted、incomplete memory，逐步降低 GT 比例。 减少 train-test distribution shift。 T5 Corrupted memory curriculum 主动注入 false R2、missed R2、wrong same-vessel、低质量边、缺失 3D、冲突证据。 强迫模型把 memory 当证据而非真理，并训练 revision。 T6 …
- ADD body block 343 · paragraph · heading: A6.20 训练路线：Oracle 关系上限 → 预测关系闭环 → 人工腐化鲁棒性 · cell paragraphs: —
  - A12 可控合成碎片实验室应为本路线生成专门 episode，而不是只增加总样本量：同一母体生成完整 R2 图与 R1 集合；然后分别制造 0%、5%、10%、20%、30% 错边，或只破坏一个关系证据轴，形成严格配对的 corruption ladder。真实数据必须保留独立母体确认集，合成数据只能用于预训练、机制压力测试和错误模式覆盖，不能代替真实成立证据。
- ADD body block 344 · paragraph · heading: A6.20.1 候选损失项：先作为可拆卸假设，不一次全部启用 · cell paragraphs: —
  - A6.20.1 候选损失项：先作为可拆卸假设，不一次全部启用
- ADD body block 345 · paragraph · heading: A6.20.1 候选损失项：先作为可拆卸假设，不一次全部启用 · cell paragraphs: —
  - 可维护以下损失池：L_same（同器物 membership）、L_R2（直接历史邻接）、L_contact（可比较条件下的接触／互补）、L_rank（候选排序）、L_comp（relation composition 一致性）、L_calib（posterior 校准）、L_revision（错误边被新证据推翻时的修正监督）、L_memory（vessel/local memory 一致性）以及可选 L_distill（TORA-like relation structure distillation）。任何一次正式消融只允许新增一个主要损失项，并报告其对 R1、R2、误导风险和计算的独立影响。
- ADD body block 346 · paragraph · heading: A6.20.1 候选损失项：先作为可拆卸假设，不一次全部启用 · cell paragraphs: —
  - 一个重要约束是：L_comp 只鼓励 R2 路径提高 same-vessel belief，不允许把 R2 传递为 R2。即使 A-B 与 B-C 都是 R2，也不能把 A-C 直接监督为 R2；A-C 的直接邻接标签仍由历史真值单独决定。
- ADD body block 347 · paragraph · heading: A6.21 必做实验矩阵：先证明“邻片上下文有信息”，再证明“新机制能安全利用它” · cell paragraphs: —
  - A6.21 必做实验矩阵：先证明“邻片上下文有信息”，再证明“新机制能安全利用它”
- ADD body block 348 · table · heading: A6.21 必做实验矩阵：先证明“邻片上下文有信息”，再证明“新机制能安全利用它” · cell paragraphs: 48
  - 实验 最低对照 核心观测 否定／进入条件 Oracle-R2 上限实验 Pairwise R1 vs Pairwise + GT R2 context R1 Hit@K / same-vessel Hit@K / CovRecall 若 GT R2 也不能稳定提升 R1，则暂停 UA-IFRMN。 Scalar vs Latent Feedback P(R2) 标量 vs e_R2 latent，同候选池同 FLOPs R1、R2、ECE/Brier、时延 只有 latent 显著优于 scalar 才保留连续反馈。 单邻片 vs 多邻片集合 Top1 R2 context vs Top-K neighbor token set R1、覆盖、多邻片真值恢复 证明 set context 是否真实有价值。 Pairwise chaining vs Soft Graph 直接把边串起来 vs typed soft graph 级联错误率、R1、错误图连通率 Soft graph 必须明显减少错误传播。 Hard Commit vs Reversible Memory 接受后不可撤销 vs joint reread/revise wrong→correct、correct→wrong、最终命中 可反悔机制必须提高恢复率且不显著伤害 clean。 无 Vessel Memory vs Ve…
- ADD body block 349 · paragraph · heading: A6.21 必做实验矩阵：先证明“邻片上下文有信息”，再证明“新机制能安全利用它” · cell paragraphs: —
  - 推荐把 Oracle-R2 gap 作为第一道 go/no-go 门。它直接测量“正确邻接上下文最多能给 R1 带来多少信息”。只有这个上限足够大，后续关于 latent feedback、图记忆、vessel memory 和 multi-hop reasoning 的工程投入才有意义。第二道门是 predicted-R2 与 corruption curve：如果真实预测边一加入就把 R1 拖垮，则优先研究校准、验证和 revision，而不是继续扩主干。
- ADD body block 350 · paragraph · heading: A6.22 可形成的研究主张与明确禁写项 · cell paragraphs: —
  - A6.22 可形成的研究主张与明确禁写项
- ADD body block 351 · paragraph · heading: A6.22 可形成的研究主张与明确禁写项 · cell paragraphs: —
  - 现阶段不得写“首次将自回归用于碎片重建”：PuzzleFusion++ 已经明确采用 auto-agglomerative、类 autoregressive 的逐步组装。也不得写“首次把预测碎片关系反馈给下一轮”：SARe 已经使用接触图、几何验证与可靠子结构反馈／重采样。任何论文新颖性都必须避开这两个宽泛表述。
- ADD body block 352 · paragraph · heading: A6.22 可形成的研究主张与明确禁写项 · cell paragraphs: —
  - 当前更有希望、但仍需实验证明的主张是：在“同器物非邻接检索”问题上，利用直接历史邻接 R2 构建带不确定性、可修正的 typed relation memory，并通过 contact-conditioned multi-hop identity expansion 与 vessel-level latent context 提高 R1 检索；同时显式测量和抑制错误 R2 的级联传播。
- ADD body block 353 · paragraph · heading: A6.22 可形成的研究主张与明确禁写项 · cell paragraphs: —
  - 可暂定英文机制描述：Uncertainty-Aware Iterative Fragment Relational Memory Network (UA-IFRMN) for Contact-Conditioned Identity Expansion。正式投稿前必须再次检索同题工作，并以当时最新文献决定名称与新颖性措辞。
- ADD body block 354 · table · heading: A6.22 可形成的研究主张与明确禁写项 · cell paragraphs: 8
  - 类别 内容 可以研究 R2 作为局部结构 seed 是否显著提高 R1；soft typed graph 是否比 pair chaining 更稳；latent relation feedback 是否比 scalar feedback 更有效；Vessel Memory 是否改善远距离 R1；可反悔机制是否降低级联错误。 不能预先声称 UA-IFRMN 已经优于 SOTA；R2→R1 一定有效；循环／CTM 本身就是创新；自回归思想首次用于碎片；完整器物 prior 一定能帮助低质陶片。 必须保留的失败解释 Oracle-R2 无上限；predicted-R2 噪声抵消收益；Vessel Memory 形成 shortcut；多跳扩展造成 graph over-smoothing；relation latent 无法优于标量；可反悔机制成本过高。
- ADD body block 355 · paragraph · heading: A6.23 创新账本增补：UA-IFRMN 关系记忆路线 · cell paragraphs: —
  - A6.23 创新账本增补：UA-IFRMN 关系记忆路线
- ADD body block 356 · paragraph · heading: A6.23 创新账本增补：UA-IFRMN 关系记忆路线 · cell paragraphs: —
  - 以下编号从现有 INNO-31 之后顺延，只新增、不覆盖旧条目。全部状态初始为 RESEARCH_CANDIDATE 或 IDEA，待冻结实验后再流转。
- ADD body block 357 · table · heading: A6.23 创新账本增补：UA-IFRMN 关系记忆路线 · cell paragraphs: 60
  - ID 创新候选 当前优先级 状态 INNO-32 UA-IFRMN：Uncertainty-Aware Iterative Fragment Relational Memory Network。 P0 核心 RESEARCH_CANDIDATE INNO-33 Contact-Conditioned Identity Expansion：用高置信 R2 局部接触结构作为 R1 同器物身份扩展条件。 P0 核心 RESEARCH_CANDIDATE INNO-34 Soft Typed Relation Graph Memory：R0/R1/R2/UNKNOWN + latent + quality + provenance 的可修正关系图。 P0 核心 RESEARCH_CANDIDATE INNO-35 Latent Relation Feedback：反馈连续 relation latent，而非只反馈 P(R2) 标量。 P1 高潜 RESEARCH_CANDIDATE INNO-36 Dual Relational Memory：R2 Local Memory + Vessel Identity Memory 分工。 P0 架构 RESEARCH_CANDIDATE INNO-37 Reversible Joint Reread：新证据进入后联合重读受影响子图，允许旧边降权…
- ADD body block 358 · paragraph · heading: A6.24 本次增补的外部来源与复现优先级 · cell paragraphs: —
  - A6.24 本次增补的外部来源与复现优先级
- ADD body block 359 · paragraph · heading: A6.24 本次增补的外部来源与复现优先级 · cell paragraphs: —
  - 来源分为两类：会议／期刊正式论文用于建立强对照，2026 年预印本用于跟踪最新方向。预印本在正式投稿前必须再次核验版本、发表状态和结论；不得把预印本结果写成社区共识。建议优先阅读／复现顺序为：SARe → PuzzleFusion++ → GARF → Combinative Matching / Rectified Point Flow → MHopReg → Jigsaw++ / Beyond Reassembly → Bag of Bags → Coconut / VisMem / WorldMM / Titans → TORA / MV-RoMa。
- ADD body block 360 · paragraph · heading: A6.24 本次增补的外部来源与复现优先级 · cell paragraphs: —
  - 1. Jia et al. SARe: Structure-Aware Large-Scale 3D Fragment Reassembly. arXiv:2603.21611, 2026.
- ADD body block 361 · paragraph · heading: A6.24 本次增补的外部来源与复现优先级 · cell paragraphs: —
  - 2. Wang, Chen, Furukawa. PuzzleFusion++: Auto-agglomerative 3D Fracture Assembly by Denoise and Verify. ICLR 2025.
- ADD body block 362 · paragraph · heading: A6.24 本次增补的外部来源与复现优先级 · cell paragraphs: —
  - 3. Li et al. GARF: Learning Generalizable 3D Reassembly for Real-World Fractures. ICCV 2025.
- ADD body block 363 · paragraph · heading: A6.24 本次增补的外部来源与复现优先级 · cell paragraphs: —
  - 4. Sun et al. Rectified Point Flow: Generic Point Cloud Pose Estimation. NeurIPS 2025 Spotlight; arXiv:2506.05282.
- ADD body block 364 · paragraph · heading: A6.24 本次增补的外部来源与复现优先级 · cell paragraphs: —
  - 5. Lee et al. Combinative Matching for Geometric Shape Assembly. ICCV 2025 Highlight. DOI: 10.1109/ICCV51701.2025.00890.
- ADD body block 365 · paragraph · heading: A6.24 本次增补的外部来源与复现优先级 · cell paragraphs: —
  - 6. Lee et al. TORA: Topological Representation Alignment for 3D Shape Assembly. arXiv:2604.04050, 2026.
- ADD body block 366 · paragraph · heading: A6.24 本次增补的外部来源与复现优先级 · cell paragraphs: —
  - 7. Lu, Hua, Huang. Jigsaw++: Imagining Complete Shape Priors for Object Reassembly. ICCV 2025.
- ADD body block 367 · paragraph · heading: A6.24 本次增补的外部来源与复现优先级 · cell paragraphs: —
  - 8. Xu et al. Beyond Reassembly: Fractured Object Recovery with Missing Parts. CVPR 2026.
- ADD body block 368 · paragraph · heading: A6.24 本次增补的外部来源与复现优先级 · cell paragraphs: —
  - 9. Wu et al. MHopReg: Efficient Hierarchical Multi-Hop Graph Search for Point Cloud Registration. CVPR 2026.
- ADD body block 369 · paragraph · heading: A6.24 本次增补的外部来源与复现优先级 · cell paragraphs: —
  - 10. Lee, Kang, Yoo. MV-RoMa: From Pairwise Matching into Multi-View Track Reconstruction. arXiv:2603.27542, 2026.
- ADD body block 370 · paragraph · heading: A6.24 本次增补的外部来源与复现优先级 · cell paragraphs: —
  - 11. Gogawale et al. Bag of Bags: Adaptive Visual Vocabularies for Genizah Join Image Retrieval. CVPR Workshops 2026.
- ADD body block 371 · paragraph · heading: A6.24 本次增补的外部来源与复现优先级 · cell paragraphs: —
  - 12. Yu et al. Mitigating spurious features by contrastive learning in pottery sherd recognition. npj Heritage Science 14, 135 (2026).
- ADD body block 372 · paragraph · heading: A6.24 本次增补的外部来源与复现优先级 · cell paragraphs: —
  - 13. Hao et al. Training Large Language Models to Reason in a Continuous Latent Space (Coconut). arXiv:2412.06769; ICLR 2025 Workshop.
- ADD body block 373 · paragraph · heading: A6.24 本次增补的外部来源与复现优先级 · cell paragraphs: —
  - 14. Behrouz, Zhong, Mirrokni. Titans: Learning to Memorize at Test Time. NeurIPS 2025.
- ADD body block 374 · paragraph · heading: A6.24 本次增补的外部来源与复现优先级 · cell paragraphs: —
  - 15. Yu et al. VisMem: Latent Vision Memory Unlocks Potential of Vision-Language Models. CVPR 2026.
- ADD body block 375 · paragraph · heading: A6.24 本次增补的外部来源与复现优先级 · cell paragraphs: —
  - 16. Yeo et al. WorldMM: Dynamic Multimodal Memory Agent for Long Video Reasoning. CVPR 2026.
- ADD body block 376 · paragraph · heading: A6.24 本次增补的外部来源与复现优先级 · cell paragraphs: —
  - 本次 A6 增补状态：仅完成长期创新区的思想登记、架构假设、参考映射与最小实验合同；未改变 A1–A5、A7 以后正文、现有历史实验判决、A12 合成平台事实状态或比赛稳定主线。
- ADD body block 377 · paragraph · heading: A6.25 Whole-Vessel Membership Recovery：从一块碎片恢复整个器物成员集合 · cell paragraphs: —
  - A6.25 Whole-Vessel Membership Recovery：从一块碎片恢复整个器物成员集合
- ADD body block 378 · paragraph · heading: A6.25 Whole-Vessel Membership Recovery：从一块碎片恢复整个器物成员集合 · cell paragraphs: —
  - 长期主任务定义为Fragment-to-Vessel Membership Recovery：输入任意查询碎片q和混合图库G，输出G中与q属于同一器物的预测成员集合V_hat(q)，并区分其中直接历史邻接R2与非直接邻接R1。该任务不要求一次性输出完整几何装配；它首先研究“哪些碎片属于一起”，再把几何装配作为可选后续。这样既贴合专家实际搜索负担，也把研究问题从pairwise similarity提升为set recovery与relational retrieval。
- ADD body block 379 · table · heading: A6.25 Whole-Vessel Membership Recovery：从一块碎片恢复整个器物成员集合 · cell paragraphs: 21
  - 阶段 核心操作 研究意义 Seed retrieval 从q召回高置信R2和same-vessel种子 建立第一批可靠局部证据；不追求一次找全。 Local component formation 把通过验证的R2软写入R2 Local Memory 得到局部组件，但R2不传递。 Vessel hypothesis 由已接受/高置信成员建立Vessel Identity Memory 形成材质、壁厚、曲率、纹样体系和器型趋势等器物级条件。 Database re-search 用q + 当前器物假设重新扫描全库 寻找与q不接触但与整体器物假设兼容的R1。 Joint reread 新成员加入后重读旧边、冲突与缺失证据 允许早期关系降级、撤回或恢复，控制级联错误。 Stop/abstain 边际收益低、风险高、预算耗尽或无新证据时停止 避免为了高Recall无限扩张集合。
- ADD body block 380 · paragraph · heading: A6.26 High-Degradation Robust Retrieval：高磨损、风化与部分观测下的鲁棒碎片检索 · cell paragraphs: —
  - A6.26 High-Degradation Robust Retrieval：高磨损、风化与部分观测下的鲁棒碎片检索
- ADD body block 381 · paragraph · heading: A6.26 High-Degradation Robust Retrieval：高磨损、风化与部分观测下的鲁棒碎片检索 · cell paragraphs: —
  - 第二条核心研究主线是“证据被物理过程破坏后模型还能保留多少检索能力”。传统几何算法在完整断口、可靠3D和高重叠条件下必须作为强基线；RelicWeave的研究价值不在于清晰样本多赢几个百分点，而在于随着断口磨圆、崩缺、表面侵蚀、纹样缺失、成像噪声和3D重建伪影增强，性能下降是否显著慢于传统精确匹配和普通静态网络。
- ADD body block 382 · table · heading: A6.26 High-Degradation Robust Retrieval：高磨损、风化与部分观测下的鲁棒碎片检索 · cell paragraphs: 21
  - 退化层级 控制内容 要回答的问题 D0 Clean 断口与表面证据完整 建立传统方法和学习方法的上限；允许传统法胜出。 D1 Mild wear 轻度磨圆/轻纹理损伤 观察第一处性能分离点。 D2 Local chipping 局部崩边/缺口 测试局部对应丢失时的多模态补偿。 D3 Partial fracture loss 20–40%断口信息不可见或缺失 测试partial observation与拒识。 D4 Severe mixed degradation 磨损+崩缺+表面退化+成像噪声 测试关系上下文和Vessel Memory是否提供额外鲁棒性。 D5 Real domain 真实自然风化/真实采集误差 只作为独立确认；不能用合成D级替代。
- ADD body block 383 · paragraph · heading: A6.27 统一论文路线：共享一个问题族，不把所有创新强塞进一篇论文 · cell paragraphs: —
  - A6.27 统一论文路线：共享一个问题族，不把所有创新强塞进一篇论文
- ADD body block 384 · paragraph · heading: A6.27 统一论文路线：共享一个问题族，不把所有创新强塞进一篇论文 · cell paragraphs: —
  - V1.47把科研方向整理成一个问题族：低质量碎片如何从局部接触证据逐步恢复器物身份。具体投稿时只选择证据最强的一条主贡献，其他机制降为支撑或后续工作。文化遗产是高价值真实场景，但CVPR级论文必须把任务抽象为可推广的视觉问题，并用强基线、真实退化、机制消融和跨域/跨采集验证证明贡献。
- ADD body block 385 · table · heading: A6.27 统一论文路线：共享一个问题族，不把所有创新强塞进一篇论文 · cell paragraphs: 24
  - 论文候选 核心问题 必须证据 止损条件 PAPER-A：Robust Fragment Retrieval under Physical Degradation 退化鲁棒检索 性能—退化强度曲线；传统几何/静态AI/新方法公平对照；Synthetic→Real。 若真实退化没有稳定增益，转为数据/应用论文。 PAPER-B：Contact-Conditioned Vessel Identity Expansion R2→R1 / UA-IFRMN Oracle-R2→Predicted-R2→Corrupted-R2；证明局部接触上下文对R1有信息且可安全利用。 若Oracle-R2都不能提升R1，停止该主张。 PAPER-C：Fragment-to-Vessel Membership Recovery 整器物成员恢复新任务/集合检索 Vessel Precision/Recall/F1；不同成员数和库规模；set/graph/metric学习强基线。 若任务GT无法闭合或只在单器型有效，先不宣称通用任务。 PAPER-D：Physics-Guided Synthetic-to-Real Pretraining A12/VesselForge/PG-Frag 物理合理碎裂+退化预训练是否降低真实样本需求并提升跨域鲁棒性。 若synthetic-pretrain无真实收益，只保留为实…
- ADD body block 386 · paragraph · heading: A6.28 顶会级研究门槛与禁止性表述 · cell paragraphs: —
  - A6.28 顶会级研究门槛与禁止性表述
- ADD body block 387 · paragraph · heading: A6.28 顶会级研究门槛与禁止性表述 · cell paragraphs: —
  - 进入CVPR/ICCV等主会级主线前至少需要：①真实或可信独立域数据，不能只靠合成；②与传统几何、强检索、set/graph模型和最接近碎片方法的同输入对照；③预注册或冻结的主指标和独立确认；④机制消融能够排除“只是更多参数/更多照片/更多计算”；⑤退化、库规模、成员数和hard negative分层；⑥失败案例与适用域。禁止写“首次使用自回归做碎片”“首次把预测关系反馈回网络”等高风险新颖性断言；真正可能成立的主张应收敛到高退化下的关系记忆、R2条件的器物身份扩展或整器物成员恢复。
- ADD body block 442 · paragraph · heading: EXP10 高磨损/风化鲁棒性基准 · cell paragraphs: —
  - EXP10 高磨损/风化鲁棒性基准
- ADD body block 443 · paragraph · heading: EXP10 高磨损/风化鲁棒性基准 · cell paragraphs: —
  - 冻结同一批query、gallery、GT、训练预算和观测权限，建立D0→Dn配对退化阶梯。最低对照包括人工可观察性、ICP/GICP或等价传统配准、FPFH/SHOT或其他合法局部描述子、曲率/轮廓基线、静态深度检索和当前RelicWeave。主输出为Hit/CovRecall/Same-Vessel与Vessel指标随退化强度的曲线、失败转移点和真实域确认。清晰档传统算法强不算失败；只有高退化档出现稳定且可归因优势，才能写“AI在该场景增加价值”。
- ADD body block 444 · paragraph · heading: EXP11 整器物成员恢复（Vessel Membership Recovery） · cell paragraphs: —
  - EXP11 整器物成员恢复（Vessel Membership Recovery）
- ADD body block 445 · paragraph · heading: EXP11 整器物成员恢复（Vessel Membership Recovery） · cell paragraphs: —
  - 只使用member set闭合的母体。给定单个query，系统从空或最小seed开始迭代检索，输出R2、R1和最终V_hat(q)。比较pairwise retrieval、简单聚类/metric learning、set/graph baseline、静态vessel prototype和UA-IFRMN候选。报告Vessel Precision/Recall/F1、完整找回率、首个错误成员进入轮次、迭代次数、查询墙钟和专家需要核验的候选数。不同器物成员数、图库规模、材质和器型分层。
- ADD body block 446 · paragraph · heading: EXP12 R2→R1关系上下文与错误传播 · cell paragraphs: —
  - EXP12 R2→R1关系上下文与错误传播
- ADD body block 447 · paragraph · heading: EXP12 R2→R1关系上下文与错误传播 · cell paragraphs: —
  - 第一步Oracle-R2：只替换关系上下文，不改视觉输入，验证真实邻接上下文能否提升R1/same-vessel；第二步Predicted-R2：换成模型预测并保留posterior、quality与relation latent；第三步Corrupted-R2：按0/5/10/20/30%注入错边、漏边和不完整memory。比较Scalar Feedback、Latent Feedback、Neighbor Set、Soft Graph、Vessel Memory与Reversible Memory。若Oracle无增益则暂停；若预测闭环增益只在无错边成立，则不能进入部署。
- ADD body block 550 · paragraph · heading: A12.21 V1.47退化性能曲线：把SyntheticLab变成“物理退化压力测试仪” · cell paragraphs: —
  - A12.21 V1.47退化性能曲线：把SyntheticLab变成“物理退化压力测试仪”
- ADD body block 551 · paragraph · heading: A12.21 V1.47退化性能曲线：把SyntheticLab变成“物理退化压力测试仪” · cell paragraphs: —
  - A12新增一类paired counterfactual release：同一clean母体、同一碎片关系、同一query/gallery与基础随机种子，沿磨损、崩缺、表面侵蚀、遮挡、图像质量、3D缺失/增生噪点等单轴或预注册组合轴生成D0→Dn观测。每个release必须同时提供传统算法合法输入、学习模型合法输入和TruthPack，但TruthPack只供评测。输出不仅是某一档准确率，而是每个方法的性能—退化强度曲线、临界失效点、AUC/斜率型诊断和真实域对应样本。
- ADD body block 552 · paragraph · heading: A12.22 Whole-Vessel Episode Generator：为整器物成员恢复生成完整关系世界 · cell paragraphs: —
  - A12.22 Whole-Vessel Episode Generator：为整器物成员恢复生成完整关系世界
- ADD body block 553 · paragraph · heading: A12.22 Whole-Vessel Episode Generator：为整器物成员恢复生成完整关系世界 · cell paragraphs: —
  - 每个合成母体除R2边外，还必须导出完整member set、R1/R2 typed relation graph、可见/不可见断面、缺失材料和母体级属性。episode生成器把多个母体混成gallery，随机选择query并控制同器物成员数、R1/R2比例、hard negative密度、器型相似度、材质相似度和退化分布；训练端只看合法Obs，评测端用完整Truth计算Vessel Precision/Recall/F1及多轮扩展轨迹。这样A12的数据价值从“更多pair”升级为“可控整器物关系规模”。
- ADD body block 554 · paragraph · heading: A12.23 Synthetic-to-Real与数据充分性：最终只以真实域收益决定扩容 · cell paragraphs: —
  - A12.23 Synthetic-to-Real与数据充分性：最终只以真实域收益决定扩容
- ADD body block 555 · paragraph · heading: A12.23 Synthetic-to-Real与数据充分性：最终只以真实域收益决定扩容 · cell paragraphs: —
  - 合成预训练的正式价值判断改为三条：①在相同真实标注量下是否提高真实高退化R2/R1与Vessel指标；②达到同一真实目标性能所需的真实母体/碎片量是否下降；③跨相机、材料、器型或自然风化域是否更稳。若10万/50万合成碎片不能在这些真实指标上带来收益，则停止扩容并审计生成分布、shortcut和任务错位，不用合成规模本身作为成果。
- ADD body block 579 · paragraph · heading: B2.3 器物成员集合GT与关系闭合 · cell paragraphs: —
  - B2.3 器物成员集合GT与关系闭合
- ADD body block 580 · paragraph · heading: B2.3 器物成员集合GT与关系闭合 · cell paragraphs: —
  - Level 3评测要求每个eligible object拥有member_manifest：object_id、全部已入库fragment_id、已知missing_fragment/碎屑去向、member_set_complete、R2边集合、R1定义域、UNKNOWN/争议关系、复核者、label_version与hash。V_G(q)从该manifest派生，不能从模型结果反推。若某母体只知道若干邻接但不知道是否还有同器物碎片遗失或未入库，则只能参加Level 1/2的限定评测，不能进入完整成员恢复主分母。
- ADD body block 581 · paragraph · heading: B2.3 器物成员集合GT与关系闭合 · cell paragraphs: —
  - R1是“同器物且无直接历史断裂接触”，不是“暂时拼不上”。因此member_set闭合和R2关系闭合必须分开审计：先确认哪些fragment属于该object，再确认哪些pair有历史直接接触。R2缺边不能自动把pair改成R1；证据不足保留UNKNOWN。
- ADD body block 583 · table · heading: B3 必须采到的数据 · cell paragraphs: 30
  - 数据 必须内容 不合格处理 整片 正面、反面、侧壁、轮廓及断口概览 缺面标未观察，补拍或限定用途 断口 实际断裂表面、两侧壁、厚度变化、边缘 没拍到断裂面不能用于局部关系主测试 连续线索 可见纹饰延续、凹槽、曲率变化和薄壁交界 没有该线索如实记，不生成伪纹饰 质量配对 同片清晰、日常和差质量真实观察 不以压缩副本代替独立实拍 重复会话 重新装夹后的身份、时间和参数 新session，不沿用旧位姿 相机与尺度 镜头、分辨率、曝光信息、标定工况、实测比例尺 无尺度仍可2D，关闭毫米几何 关系证据 已确认邻接及难负例、争议记录 UNKNOWN不用于确定性关系评测 失败与成本 模糊图、高光图、重拍、操作及等待时间 不删失败以提高采集成功率 器物成员GT object_id、member_manifest、member_set_complete、全部fragment_id、missing/UNKNOWN、R1/R2关系图、复核与版本hash 未闭合只做邻片/同器物候选诊断，不进入Whole-Vessel主评测
- ADD body block 836 · paragraph · heading: D6.5 器物成员恢复页（V1.47新增） · cell paragraphs: —
  - D6.5 器物成员恢复页（V1.47新增）
- ADD body block 837 · paragraph · heading: D6.5 器物成员恢复页（V1.47新增） · cell paragraphs: —
  - 结果页采用“三层视图”而不是把所有候选混在一个Top-K：第一栏Direct Neighbor Candidates只显示R2及局部接触证据；第二栏Same-Vessel Candidates显示R1/R2同器物成员及器物身份支持；第三栏Predicted Vessel Set显示当前已纳入成员、待核验成员、被驳回成员、UNKNOWN、Vessel Precision/Recall仅在有GT的评测模式显示。用户接受/驳回某成员后生成新的revision，系统可以重新检索全库并显示“新增成员导致哪些旧关系被加强、削弱或撤回”。
- ADD body block 838 · paragraph · heading: D6.5 器物成员恢复页（V1.47新增） · cell paragraphs: —
  - 比赛演示默认从一块新query开始：采集/导入→全库粗检→R2邻片→形成初始Vessel Memory→发现R1远距离成员→人工核验→成员集更新或停止。若当前模型尚未通过Level 3验证，界面必须标“研究模式/成员候选”，不得把候选集合称为已恢复器物。
- ADD body block 854 · paragraph · heading: D10 用户价值测试与成本 · cell paragraphs: —
  - 用户价值试验升级为四类条件：纯人工；人工+传统几何/规则候选；人工+静态学习候选；人工+RelicWeave关系/器物成员证据。任务分为直接邻片查找、同器物成员发现和整器物成员恢复三种难度，并按清晰/高退化分层。不同条件随机交叉或顺序平衡，避免同一人重复同题记忆优势。记录正确判断耗时、看过候选数、实物拿取/试拼次数、误配漏配、补拍、退出和最终成员集合质量。
- ADD body block 860 · paragraph · heading: D10.2 应用价值、社会价值与AI必要性的证据矩阵 · cell paragraphs: —
  - D10.2 应用价值、社会价值与AI必要性的证据矩阵
- ADD body block 861 · table · heading: D10.2 应用价值、社会价值与AI必要性的证据矩阵 · cell paragraphs: 28
  - 价值维度 必须记录 希望证明的结论 禁止夸大 专家搜索负担 完成一个任务的人时/墙钟、浏览候选数 RelicWeave相对人工和传统候选是否减少筛查 机器负责搜索，专家负责最终确认 实物操作风险 拿取、翻转、实体试拼次数 数字筛选后是否减少无意义实体操作 对脆弱碎片的保护价值 高退化可用性 D0→Dn的Hit/Cov/Vessel曲线 传统方法何时明显下降，RelicWeave是否更平缓 AI只在传统假设失效场景主张必要性 整器物恢复 Vessel Precision/Recall/F1、完整找回率 能否从单片找回数据库中的同器物成员 从局部拼接工具升级为器物身份恢复工具 经济/部署成本 建库人时、设备摊销、推理、维护、专家复核 节省的专家时间是否覆盖新增数据和系统成本 不把“候选缩小”直接换算成ROI 社会/文化价值 可恢复器物信息、可减少遗漏、可审计证据 是否提高文物数字整理与研究效率 定性价值须由真实从业者访谈/任务证据支持
- ADD body block 916 · paragraph · heading: 10 国赛与CVPR交付计划 · cell paragraphs: —
  - 比赛主交付统一围绕“真实碎片搜索负担”而不是算法名：现场从一块新query开始，完成采集/导入与QA、全库检索、R2邻片候选、R1同器物候选、器物成员集合或证据不足停止，并保留人工核验和版本日志。高磨损场景必须提供传统算法/规则基线和学习方法的公平对照，解释为什么简单样本不需要AI、为什么大库/退化/R1场景需要学习与关系推理。自动采集台、3D、RL、CTM和UA-IFRMN都只有在实测收益成立后才进入比赛主展示。
- ADD body block 917 · paragraph · heading: 10 国赛与CVPR交付计划 · cell paragraphs: —
  - 论文主交付从“系统功能清单”收敛为一个清楚科学问题。候选主线按证据强度排序：A 高退化条件下的Robust Fragment Retrieval；B R2条件的Contact-Conditioned Vessel Identity Expansion与UA-IFRMN；C Fragment-to-Vessel Membership Recovery；D Physics-Guided Synthetic-to-Real Pretraining；E Active Evidence Acquisition。一次投稿只选一条主贡献，其余作为必要支撑或后续工作；文化遗产应用价值不能替代通用视觉问题、强基线和可归因机制证据。
- ADD body block 920 · paragraph · heading: 10.1 竞赛方向：用“真痛点→真操作→真改进”组织叙事 · cell paragraphs: —
  - 10.1 竞赛方向：用“真痛点→真操作→真改进”组织叙事
- ADD body block 921 · paragraph · heading: 10.1 竞赛方向：用“真痛点→真操作→真改进”组织叙事 · cell paragraphs: —
  - 竞赛陈述固定从现实流程开始：海量混合碎片中，专家首先要解决“哪些值得比较、哪些属于同一器物”，而不是直接面对已知正确pair。项目展示顺序应是人工/传统方案的可用边界→高磨损和大库带来的失败→RelicWeave如何缩小候选→如何找到R1远距离成员→如何恢复器物成员集合→专家如何最终确认。技术先进性服务于这个工作流，不把CTM、Transformer、CUDA或硬件数量当价值本身。
- ADD body block 922 · table · heading: 10.1 竞赛方向：用“真痛点→真操作→真改进”组织叙事 · cell paragraphs: 18
  - 竞赛叙事块 核心内容 验收/边界 痛点证据 库规模、人工耗时、候选浏览/实物操作、退化样本失败 至少有真实任务或相关从业者访谈；无行业数据时明确标内部试验。 AI必要性 传统算法清晰样本基线 + 高退化/弱对应对照 允许传统法在D0强；重点看高退化、大库和R1。 技能展示 真实采集/QA、模型推理、设备/软件联调、故障恢复、证据核验 四岗位都有可见技术操作，避免纯PPT讲算法。 应用价值 节省筛查时间、减少无意义试拼、提高成员找回、降低遗漏 全部按完整工作流分母测，不把局部模型指标冒充ROI。 创新展示 高退化鲁棒性、整器物成员恢复、关系记忆/主动补采中的已验证部分 研究候选未通过就标实验模式，不冒充稳定能力。
- ADD body block 923 · paragraph · heading: 10.2 论文方向：一套数据底座，多条可独立收敛的研究问题 · cell paragraphs: —
  - 10.2 论文方向：一套数据底座，多条可独立收敛的研究问题
- ADD body block 924 · paragraph · heading: 10.2 论文方向：一套数据底座，多条可独立收敛的研究问题 · cell paragraphs: —
  - 优先顺序由实验决定而不是由想法“看起来高级”决定。先跑EXP10退化曲线和EXP11整器物任务，确认问题本身有足够难度和方法空间；再用EXP12判断R2上下文是否真的给R1带来信息。若Oracle-R2上限明显、Predicted-R2能在错边下保持收益，则UA-IFRMN可升级为方法主线；若关系机制不成立，但A12的物理退化预训练在真实域稳定增益，则把Synthetic-to-Real转为主线。
- ADD body block 925 · paragraph · heading: 10.2 论文方向：一套数据底座，多条可独立收敛的研究问题 · cell paragraphs: —
  - 顶会目标不要求一次把比赛系统所有模块写进论文。最强版本应围绕一个可以被其他视觉任务理解的问题：高退化partial observation、typed relational reasoning、set membership recovery或physics-guided sim-to-real。数据、代码、协议、强基线和负结果比系统模块数量更重要。
- ADD body block 926 · paragraph · heading: 10.3 竞赛与论文共享的证据底座，但结论严格分开 · cell paragraphs: —
  - 10.3 竞赛与论文共享的证据底座，但结论严格分开
- ADD body block 927 · paragraph · heading: 10.3 竞赛与论文共享的证据底座，但结论严格分开 · cell paragraphs: —
  - 两条路线共享真实数据身份、member/neighbor GT、冻结split、退化压力测试、传统/学习基线和工作流日志。比赛可以强调专家减负、社会价值、可操作性与系统完整；论文只能强调被独立实验支持的方法/任务贡献。比赛演示成功不等于论文创新成立，论文模型增益也不自动证明真实工作流节时。
- ADD body block 937 · paragraph · heading: 11 本次归位与历史记录 · cell paragraphs: —
  - V1.47统一“高退化鲁棒检索→R2邻片→R1同器物→整器物成员恢复”的最新主线，新增Vessel Membership指标、性能—退化曲线、Oracle/Predicted/Corrupted-R2验证、成员GT、整器物UI和竞赛/论文双路线。该更新覆盖了现行正文中仅以“找到一个邻片”为最终目标的旧叙事，但不删除其仍有效的邻片指标；旧Hit/Cov仍作为Level 1核心指标。历史实验数据、旧FAIL/STOP/NOT_*、A12/VesselForge/PG-Frag接口和已冻结数值全部保留，不因最终目标升级而改写。
- ADD body block 945 · paragraph · heading: 历史附录使用说明 · cell paragraphs: —
  - 以下A至F为原实验及工程历史，Q等级、指标、阈值、模型名、资源和判决按当时协议解释，不直接与V1.47的新Level 2/3任务合并。V1.47新增的整器物成员恢复、退化鲁棒性与R2→R1指标只对新冻结实验生效；除非专门复跑并保存新manifest，不能从旧Hit@K或旧pair实验反推Vessel Recall、真实高磨损鲁棒性或UA-IFRMN有效。当前新工作用第4至10章、G/H/I/J；历史附件继续用于重现、审计与保护原始证据。
- REMOVE body block 1 · paragraph · heading:  · cell paragraphs: —
  - V1.46 A12双子基础设施整合版 2026年10月5日
- REMOVE body block 2 · paragraph · heading:  · cell paragraphs: —
  - 我们研究低质量部分观测下的碎片邻接候选检索。系统从真实碎片照片出发，在混合碎片库中提出值得人工核验的邻片候选；证据不足时，提出有成本约束的补采建议或停止推荐。比赛交付可运行、可恢复的辅助系统，研究交付能够经独立对照验证的方法机制。
- REMOVE body block 5 · paragraph · heading:  · cell paragraphs: —
  - 本版在V1.45基础上将A12进一步重构为“合成实验编排与研究层”，正式接入两个可独立演化的三维基础设施子项目：VesselForge负责完整器物、语义纹样、材质与Physics-Ready资产，PG-Frag负责材料/事件驱动的损伤、裂纹、碎裂、断面与碎片动力学。A12不再把器型几何内核和断裂求解器写死在自身代码中，而通过版本化Asset/Job/Result合同调用两个子项目，再完成磨损、成像/重建退化、ObsPack适配、关系采样、预训练与瓶颈诊断。原V1.45的历史数值、FAIL、STOP与NOT_ESTABLISHED判决不变；新增架构与子项目方案仍须按各自Benchmark验收。
- REMOVE body block 88 · paragraph · heading: 1 文档体系与现行口径 · cell paragraphs: —
  - 本文件包含总纲、四岗位完整执行正文、软硬件、联调、验收、完整合成实验室、历史附录以及两个独立三维基础设施子项目方案，现行版本统一V1.46。A12给出合成实验编排、预训练与诊断总览；附录G规定A12编排层、退化层、数据与训练流程；附录I规定VesselForge完整方案；附录J规定PG-Frag完整方案；附录H继续保留V1.44问题修订与验收索引。原历史数值、FAIL、STOP和旧协议保留，不能按新口径直接改写。
- REMOVE body block 102 · paragraph · heading: 2 合并主线与边界 · cell paragraphs: —
  - 主问题是给定真实可获得的观测、候选检查预算和误导风险，如何找回邻片并识别观察不足。输入包括整片2D、断口2D和质量信息；合格3D、可信上下文是可选增强。输出包括有序候选、来源可追溯的证据、待核验状态、补采或停止原因。
- REMOVE body block 106 · table · heading: 2.1 比赛必须实现与论文需要证明 · cell paragraphs: 24
  - 能力 比赛系统的内部必做交付 若作为论文主张需要的证据 输入与数据 新样品登记、手机采集、质量检查、真实邻接依据 母体隔离、标签审计和独立确认集 候选链 全库初检、局部精排、证据卡和版本日志 同输入强基线及端到端公平对照 可靠输出 不强迫确定拼合，展示不足、拒识和人工核验 mate-present覆盖与mate-absent风险同时报告 补采 基础版可人工执行建议；自动台列增强交付 等照片和等时间下分别优于强补采基线 主干创新 部署真实验证较好的稳定模型 互补、可观测性或证据重读的可归因机制增益 现场与产品 离线运行、异常恢复、四人交接、真实耗时 工程表现不能代替方法新颖性 用户价值 实测候选检查量与完整任务时间 参与者、任务与对照公开，避免只报列表缩减
- REMOVE body block 110 · table · heading: 2.2 内部指标合同 · cell paragraphs: 33
  - 指标 定义与适用范围 目标或判定方式 any@50 有邻片查询中至少一名真邻片进入初检50池 正常质量内部目标宏值0.95，连同区间报告 Hit@10 前10中至少一名库内真邻片 比赛准备目标正常质量宏值0.90，95%下界0.85 低质Hit@10 日常低质查询对清晰库，独立母体 内部目标0.85，达不到则缩小适用范围 CovRecall@10 前10找回库内真邻片的比例 与Hit单列，不低于冻结强基线 新方法主比较 同查询同库相对验证集选出的强基线 开发起点为增益3个百分点且对象簇CI下界大于0 干净性能守卫 新方法相对同池强基线 下降不超过2个百分点，阈值先冻结 无邻片误导 mate-absent查询被接受推荐的比例 目标不超过5%，95%上界目标不超过10% 有邻片接受覆盖 mate-present中被系统接受输出的比例 目标至少80%，不能靠全拒绝换低风险 现场流程 新查询采集到结果的完整彩排 20次至少19次完成，仅作为彩排目标 工作流价值 包括拍摄、补拍、检查的总任务时间 中位用时减少30%为内部目标，正确性不恶化
- REMOVE body block 474 · table · heading: B3 必须采到的数据 · cell paragraphs: 27
  - 数据 必须内容 不合格处理 整片 正面、反面、侧壁、轮廓及断口概览 缺面标未观察，补拍或限定用途 断口 实际断裂表面、两侧壁、厚度变化、边缘 没拍到断裂面不能用于局部关系主测试 连续线索 可见纹饰延续、凹槽、曲率变化和薄壁交界 没有该线索如实记，不生成伪纹饰 质量配对 同片清晰、日常和差质量真实观察 不以压缩副本代替独立实拍 重复会话 重新装夹后的身份、时间和参数 新session，不沿用旧位姿 相机与尺度 镜头、分辨率、曝光信息、标定工况、实测比例尺 无尺度仍可2D，关闭毫米几何 关系证据 已确认邻接及难负例、争议记录 UNKNOWN不用于确定性关系评测 失败与成本 模糊图、高光图、重拍、操作及等待时间 不删失败以提高采集成功率
- REMOVE body block 742 · paragraph · heading: D10 用户价值测试与成本 · cell paragraphs: —
  - 比较人工流程、人工加简单候选及人工加新方法证据三种条件。不同难度匹配任务随机交叉分配，避免同一人重复同题记忆优势。记录正确判断耗时、看过候选数、误配漏配、补拍和退出。
- REMOVE body block 802 · paragraph · heading: 10 国赛与CVPR交付计划 · cell paragraphs: —
  - 比赛主交付包括真实新查询流程、原图与GT审计、稳定基线或成立的新方法、风险与不足、补采增强、四人操作、离线恢复、实测价值和明确适用域。自动采集台、3D、RL及CTM不全部列为最低交付。
- REMOVE body block 803 · paragraph · heading: 10 国赛与CVPR交付计划 · cell paragraphs: —
  - 论文主交付包括科学问题、最接近工作、同输入强基线、独立主结果、机制消融、质量与缺失、开放库、成本、失败及复现。METHOD-H1局部互补或METHOD-H3候选条件补采选择证据较强者为核心，架构复杂度不是必要条件。
- REMOVE body block 822 · paragraph · heading: 历史附录使用说明 · cell paragraphs: —
  - 以下A至F为原实验及工程历史，Q等级、指标、阈值、模型名、资源和判决按当时协议解释，不直接与V1.45合并。当前新工作用第4至9章、G与H，不恢复归档未定义编号或旧门。

### RelicWeave_V1.47_A12_VesselForge_PGFrag_Closeout.docx → RelicWeave_V1.47.docx

Direct top-level blocks: before=2526, after=2642; operations=154 (added 135, removed 19).
Added kinds: {'paragraph': 114, 'table': 21}; removed kinds: {'paragraph': 16, 'table': 3}.

- ADD body block 1 · paragraph · heading:  · cell paragraphs: —
  - V1.47 整器物成员恢复 × 高退化鲁棒检索 × 竞赛/论文双主线整合版 2026年10月7日
- ADD body block 2 · paragraph · heading:  · cell paragraphs: —
  - 我们研究真实低质量、部分观测与物理退化条件下的文物/器物碎片检索与器物成员恢复。系统从任意一块查询碎片出发，先在混合碎片库中提出直接历史邻片R2候选，再联合二维外观、断口、三维几何、材质、纹样、壁厚、曲率和已发现关系，检索同器物但非直接邻接的R1成员；长期目标是在给定数据库范围内恢复该器物的高置信成员集合。证据不足时系统拒绝强判、给出缺失证据与有成本约束的补采建议。比赛交付强调真实工作流、专家减负与可解释候选；论文交付强调高退化鲁棒检索、R2→R1关系推理、整器物成员恢复和Synthetic-to-Real的可归因机制。
- ADD body block 5 · paragraph · heading:  · cell paragraphs: —
  - V1.47在V1.46双子基础设施版本上统一最新项目主线：将长期最终目标从“找一名邻片”明确升级为“Fragment-to-Vessel Retrieval / Vessel Membership Recovery”，新增高磨损与风化证据下的鲁棒检索主线、传统算法与学习方法的公平退化对照、R2局部接触到R1器物身份扩展、整器物成员级指标、比赛价值验证与CVPR级研究收敛路线。VesselForge、PG-Frag与A12的职责边界保持不变；A12增加对退化性能曲线、完整器物关系episode和Synthetic-to-Real的专门支撑。所有历史实验数值、FAIL、STOP、NOT_SUPPORTED、NOT_ESTABLISHED与冻结协议继续原样保护；本版只更新现行目标、研究候选、实验合同、数据GT、产品展示和交付口径，不用新叙事改写旧结果。
- ADD body block 88 · paragraph · heading: 1 文档体系与现行口径 · cell paragraphs: —
  - 本文件包含总纲、四岗位完整执行正文、软硬件、联调、验收、完整合成实验室、历史附录以及两个独立三维基础设施子项目方案，现行版本统一V1.47。总纲第2章给出最新统一任务、应用价值边界和评测合同；A6维护长期科研创新；A8把科研假设转成实验卡；A12与附录G负责合成、退化、预训练和诊断；附录I/J分别规定VesselForge与PG-Frag。附录A至F及历史实验段落继续作为冻结证据保留，旧数值与判决不能按V1.47的新目标直接改写。
- ADD body block 101 · paragraph · heading: 1.3 V1.47信息优先级与历史数据保护规则 · cell paragraphs: —
  - 1.3 V1.47信息优先级与历史数据保护规则
- ADD body block 102 · paragraph · heading: 1.3 V1.47信息优先级与历史数据保护规则 · cell paragraphs: —
  - V1.47采用“现行执行正文覆盖过时规划、历史证据只增不改”的双层治理。新的最终目标、比赛叙事和论文方向可以更新现行正文，但不得把历史实验重新解释成已经支持新主张。任何旧结论若与现行任务定义不完全一致，保留原文并标明其适用数据、指标和当时协议；只有新的冻结实验才能产生新的证据结论。
- ADD body block 103 · table · heading: 1.3 V1.47信息优先级与历史数据保护规则 · cell paragraphs: 18
  - 信息层 主要位置 V1.47处理规则 现行目标与执行口径 总纲第1–10章、A1–A12及B/C/D执行正文 允许更新；V1.47优先，用于现在做什么、为什么做、如何验收。 长期科研候选 A6创新维护区、A12研究支线 允许追加、降级、停止；RESEARCH_CANDIDATE不等于已实现或已证明。 冻结实验数据 附录A/B/C及正文引用的历史数值、hash、FAIL/STOP/NOT_* 只允许补充来源、解释边界和新复算记录；禁止删除、润色或用新口径覆盖旧数值。 旧规划与旧默认值 历史附录中的旧设备、排期、岗位、下一步建议 不再指导现行执行；为可追溯性保留，不与V1.47现行口径并列使用。 新任务扩展 整器物成员恢复、高退化鲁棒检索、R2→R1关系推理 从V1.47起生效；除非专门复跑，不能反向声称旧实验已经验证这些目标。
- ADD body block 105 · paragraph · heading: 2 合并主线与边界 · cell paragraphs: —
  - 主问题升级为：给定一块真实可获得观测的查询碎片q、一个混合碎片数据库G、候选检查预算和误导风险约束，先可靠找回直接历史邻片R2并识别观察不足，再利用碎片自身多模态证据、已发现局部关系和器物级上下文检索R1，最终尽可能恢复G中与q属于同一物理器物的成员集合V(q)。输入仍以整片2D、断口2D和质量信息为基础；合格3D、可信上下文和主动补采是可选增强。输出从单一Top-K扩展为R2邻片候选、R1同器物非邻片候选、器物成员集合、来源可追溯证据、UNKNOWN/拒识、补采或停止原因。
- ADD body block 108 · paragraph · heading: 2.0 最新统一任务定义：从邻片检索到整器物成员恢复 · cell paragraphs: —
  - 2.0 最新统一任务定义：从邻片检索到整器物成员恢复
- ADD body block 109 · paragraph · heading: 2.0 最新统一任务定义：从邻片检索到整器物成员恢复 · cell paragraphs: —
  - 长期最终目标不是“自动把文物粘好”，而是把专家面对的组合搜索问题分成三个可验证层级：先找直接邻片，再找同器物非邻片，最后从任意一片出发恢复数据库范围内的器物成员集合。Level 3只承诺“数据库中已存在碎片的成员恢复”，不等价于几何全自动装配、缺失部分生成或物理修复。
- ADD body block 110 · table · heading: 2.0 最新统一任务定义：从邻片检索到整器物成员恢复 · cell paragraphs: 16
  - 任务层级 输入→输出 主要证据/机制 核心评价 Level 1：R2 Neighbor Retrieval q + G → 直接历史邻片候选 断口、局部2D/3D、几何互补、接触证据 any@M、Hit@K、CovRecall@K、误导/拒识 Level 2：Same-Vessel Retrieval q + G → R1 + R2同器物候选 材质、纹样、壁厚、曲率、器型先验、R2上下文 SameVessel Hit@K、Precision/Recall、R1专门召回 Level 3：Vessel Membership Recovery q + G → 预测成员集合 V_hat(q) UA-IFRMN关系记忆、Vessel Memory、多轮重检索与可修正关系图 Vessel Recall、Vessel Precision、Vessel F1、误纳入率、迭代成本
- ADD body block 111 · paragraph · heading: 2.0 最新统一任务定义：从邻片检索到整器物成员恢复 · cell paragraphs: —
  - 统一终态：系统接收任意查询碎片后，先输出“Direct Neighbor Candidates（R2）”和“Same-Vessel Candidates（R1/R2）”，再形成“Predicted Vessel Set”，并在新成员加入后重新读取整个器物假设；当新增证据不足、风险过高或预算耗尽时停止，而不是为了追求找全强行扩展。
- ADD body block 113 · table · heading: 2.1 比赛必须实现与论文需要证明 · cell paragraphs: 33
  - 能力 比赛系统的内部必做交付 若作为论文主张需要的证据 输入与数据 新样品登记、手机采集、质量检查、真实邻接依据 母体隔离、标签审计和独立确认集 候选链 全库初检、局部精排、证据卡和版本日志 同输入强基线及端到端公平对照 可靠输出 不强迫确定拼合，展示不足、拒识和人工核验 mate-present覆盖与mate-absent风险同时报告 补采 基础版可人工执行建议；自动台列增强交付 等照片和等时间下分别优于强补采基线 主干创新 部署真实验证较好的稳定模型 互补、可观测性或证据重读的可归因机制增益 现场与产品 离线运行、异常恢复、四人交接、真实耗时 工程表现不能代替方法新颖性 用户价值 实测候选检查量与完整任务时间 参与者、任务与对照公开，避免只报列表缩减 高磨损/风化鲁棒性 至少展示清晰、轻度退化、严重退化三档真实或受控样本；同输入比较传统几何基线、简单AI基线与RelicWeave，展示何时传统精确匹配假设开始失效。 冻结退化轴与配对样本，给出性能—退化强度曲线、置信区间、真实域确认和跨设备/材料守卫；不能只挑极端失败样本。 整器物成员恢复 给定一块碎片，界面同时输出R2邻片、R1同器物候选和器物成员集合；人工可逐项接受/驳回，系统更新成员集且保留版本历史。 正式定义Fragment-to-Vessel Membership Recovery任务，建立Vessel Precisi…
- ADD body block 117 · table · heading: 2.2 内部指标合同 · cell paragraphs: 48
  - 指标 定义与适用范围 目标或判定方式 any@50 有邻片查询中至少一名真邻片进入初检50池 正常质量内部目标宏值0.95，连同区间报告 Hit@10 前10中至少一名库内真邻片 比赛准备目标正常质量宏值0.90，95%下界0.85 低质Hit@10 日常低质查询对清晰库，独立母体 内部目标0.85，达不到则缩小适用范围 CovRecall@10 前10找回库内真邻片的比例 与Hit单列，不低于冻结强基线 新方法主比较 同查询同库相对验证集选出的强基线 开发起点为增益3个百分点且对象簇CI下界大于0 干净性能守卫 新方法相对同池强基线 下降不超过2个百分点，阈值先冻结 无邻片误导 mate-absent查询被接受推荐的比例 目标不超过5%，95%上界目标不超过10% 有邻片接受覆盖 mate-present中被系统接受输出的比例 目标至少80%，不能靠全拒绝换低风险 现场流程 新查询采集到结果的完整彩排 20次至少19次完成，仅作为彩排目标 工作流价值 包括拍摄、补拍、检查的总任务时间 中位用时减少30%为内部目标，正确性不恶化 Vessel Recall 预测器物成员集合中找回数据库内真实同器物成员的比例；分母为冻结且闭合的V_G(q)。 长期核心目标；按母体等权宏平均，并报告成员数分层。 Vessel Precision 预测成员集合中真实同器物成员的比例。 防止“把整个库都收…
- ADD body block 124 · paragraph · heading: 2.2.2 器物成员恢复指标、完整分母与退化曲线 · cell paragraphs: —
  - 2.2.2 器物成员恢复指标、完整分母与退化曲线
- ADD body block 125 · paragraph · heading: 2.2.2 器物成员恢复指标、完整分母与退化曲线 · cell paragraphs: —
  - 对query q定义V_G(q)为冻结图库G中与q属于同一器物的全部可评成员，包含R1和R2但排除q自身；预测集合为V_hat(q)。VesselRecall=|V_hat∩V_G|/|V_G|，VesselPrecision=|V_hat∩V_G|/|V_hat|，VesselF1按二者调和平均。只有object membership已闭合、缺失实物去向已记录且UNKNOWN不被强行归类的母体，才进入Level 3主评测。天然残片若无法证明成员全集完整，可报告候选检索和专家工作流，但不能声称完整器物恢复率。
- ADD body block 126 · paragraph · heading: 2.2.2 器物成员恢复指标、完整分母与退化曲线 · cell paragraphs: —
  - 退化鲁棒性主实验必须使用paired/counterfactual设计：D0、D1…Dn共享同一母体、关系GT、query、gallery组成和基础随机种子，只改变预注册的磨损、崩缺、缺失、成像或重建退化轴。传统算法、静态学习基线和RelicWeave在相同合法观测权限下比较；不能给传统算法更差输入，也不能让模型读取clean/oracle信息。
- ADD body block 131 · paragraph · heading: 2.4 痛点、应用价值与“为什么需要AI”的边界 · cell paragraphs: —
  - 2.4 痛点、应用价值与“为什么需要AI”的边界
- ADD body block 132 · paragraph · heading: 2.4 痛点、应用价值与“为什么需要AI”的边界 · cell paragraphs: —
  - V1.47不再用“AI比传统算法先进”作为价值论证。项目的真实痛点是：当碎片数量大、来源混杂、断口被长期风化磨损、局部对应缺失、R1本来就没有直接接触面时，专家需要在巨大的组合空间中反复筛查；传统几何方法在清晰且对应充分的样本上仍然是强基线，但其精确匹配假设在高退化和弱对应条件下可能失效。RelicWeave的目标是把机器用于海量筛选、弱证据融合、排序、不确定性与关系推理，把专家从“搜索者”转为“验证者”，而不是取消专家的最终判断。
- ADD body block 133 · table · heading: 2.4 痛点、应用价值与“为什么需要AI”的边界 · cell paragraphs: 24
  - 场景 传统/人工方案 RelicWeave应增加的能力 可验证价值 小规模、清晰、断口完整 人工/ICP/曲率/局部描述子可能已足够 AI不是必须；作为强基线和成本下限 证明项目没有“为了AI而AI” 大规模混合碎片库 人工组合搜索随库规模快速变难 向量检索+学习排序缩小候选空间 减少专家浏览、比较与实物搬动 高磨损/崩缺/风化 精确几何对应和手工描述子受损 多模态表征+不确定性+退化训练 在证据残缺时保持更平缓的性能退化 R1同器物非邻接 断口没有直接对应，局部几何无法单独判断 Vessel Memory+关系图+多跳身份推理 从“找邻片”扩展到“找同器物成员” 证据不足/高风险样本 强行匹配会增加误导与不必要试拼 校准、拒识、主动补采 降低错误候选和脆弱实物反复操作
- ADD body block 307 · paragraph · heading: A6.14 2025–2026 近邻任务与跨领域前沿工作增补参考池 · cell paragraphs: —
  - A6.14 2025–2026 近邻任务与跨领域前沿工作增补参考池
- ADD body block 308 · paragraph · heading: A6.14 2025–2026 近邻任务与跨领域前沿工作增补参考池 · cell paragraphs: —
  - 本节是 A6 长期创新区的“外部思想增补池”，只记录能够改变本项目问题建模、记忆结构、关系推理、验证方式或实验设计的机制。所有条目均作为 RESEARCH_REFERENCE，不代表已经适用于 RelicWeave，更不代表已经验证有效。采用顺序固定为：先复现／理解原机制 → 映射到本项目的错误模式 → 提出最小可否定假设 → 单独消融 → 只有真实低质量与独立母体上成立后才允许进入主线。
- ADD body block 309 · table · heading: A6.14 2025–2026 近邻任务与跨领域前沿工作增补参考池 · cell paragraphs: 68
  - 参考工作 原工作关键机制 对 RelicWeave 的可借鉴点与价值 明确不直接照搬的边界 SARe: Structure-Aware Large-Scale 3D Fragment Reassembly（2026，arXiv:2603.21611） 联合预测 fracture-surface token probability 与 inter-fragment contact graph；推理期用几何一致性验证候选接触边，只固定可靠子结构，并对其余不确定部分重采样。 直接说明“大规模碎片下错误邻接会产生级联失败”，因此预测关系不能写成永久事实；本项目可借鉴“先预测—再验证—只软写入可靠结构—不确定部分允许重算”的闭环。 不直接搬其生成式完整装配流程；RelicWeave 的主问题是 R2 邻接候选与 R1 同器物非邻接检索，而非全局 6-DoF 完整拼装。 PuzzleFusion++: Auto-agglomerative 3D Fracture Assembly by Denoise and Verify（ICLR 2025） 从单碎片开始，经扩散模型求位姿、Transformer 验证 pair，再把可信碎片合并成更大组并迭代重复，作者明确将其类比为 auto-regressive / auto-agglomerative assembly。 支持“局部关系 → 局部组件 …
- ADD body block 310 · paragraph · heading: A6.14 2025–2026 近邻任务与跨领域前沿工作增补参考池 · cell paragraphs: —
  - 增补参考池的统一结论不是“把这些模型都接起来”，而是抽取五条可测试的设计原则：① 关系预测必须可验证、可撤销，不能 hard commit；② R2 的局部接触证据与 R1 的器物身份证据需要不同记忆和不同读写策略；③ pairwise 结果只能作为多轮／多碎片联合推理的 prior；④ 一块碎片应保留局部 token 集合和 provenance，而不是被压成单一全局向量；⑤ 迭代反馈应优先反馈连续 latent relation state 与不确定性，而不是只反馈一个概率标量。
- ADD body block 311 · paragraph · heading: A6.15 新核心候选：Uncertainty-Aware Iterative Fragment Relational Memory Network（UA-IFRMN） · cell paragraphs: —
  - A6.15 新核心候选：Uncertainty-Aware Iterative Fragment Relational Memory Network（UA-IFRMN）
- ADD body block 312 · paragraph · heading: A6.15 新核心候选：Uncertainty-Aware Iterative Fragment Relational Memory Network（UA-IFRMN） · cell paragraphs: —
  - 中文暂定名：不确定性感知的迭代碎片关系记忆网络。它不是当前稳定主干的替代品，而是登记在长期创新区的 P0 研究候选。其目标是把原本一次性的 pairwise R0/R1/R2 打分，改造成“局部邻接发现 → 软关系写入 → 多跳同器物扩展 → 新证据联合重读 → 旧关系可修正”的迭代关系推理过程。
- ADD body block 313 · paragraph · heading: A6.15 新核心候选：Uncertainty-Aware Iterative Fragment Relational Memory Network（UA-IFRMN） · cell paragraphs: —
  - 核心科学问题：在真实低质量、断口缺失、纹样不完整和 3D 不稳定的条件下，模型能否利用已经发现的高置信直接历史邻接 R2，构建带不确定性的关系上下文，从而提高同器物但非直接邻接 R1 的检索，同时避免错误 R2 被循环放大为器物级错误？
- ADD body block 314 · paragraph · heading: A6.15 新核心候选：Uncertainty-Aware Iterative Fragment Relational Memory Network（UA-IFRMN） · cell paragraphs: —
  - 这里的“自回归”只保留“上一轮内部结果会影响下一轮推理”这一抽象，不采用离散单路径 hard autoregression。更准确的机制名称为 Contact-Conditioned Identity Expansion + Reversible Relational Memory：直接接触证据先形成局部 relation latent，再作为同器物身份扩展的条件；所有写入都带 posterior、quality、provenance 和 revision 权限。
- ADD body block 315 · table · heading: A6.15 新核心候选：Uncertainty-Aware Iterative Fragment Relational Memory Network（UA-IFRMN） · cell paragraphs: 21
  - 组成 建议定义 为什么需要 Fragment Token Bank F_i 每块碎片保留 token set，而不是单 global vector。建议至少含 global、fracture-local、surface/pattern、material、curvature/profile、thickness、3D local patch、quality/provenance 等槽位。 避免 R2 需要的断口细节和 R1 需要的器物身份证据互相覆盖；也方便按关系类型选择性读取。 R2 Local Memory M_R2 保存候选直接邻接的边级 latent e_ij、R0/R1/R2/UNKNOWN posterior、几何互补、fracture visibility、pose/gap/contact、质量与来源。 给后续 R1 推理提供“已经确认到什么局部组件”的精细上下文，但不把概率当事实。 Vessel Identity Memory M_V 从当前一组高可信 same-vessel 碎片中形成器物级 latent / token pool，保存材质、壁厚分布、曲率趋势、器形 profile、纹样体系和稳定全局先验。 解决口沿与底足等远距离 R1 pair 局部外观完全不相似的问题；判断目标从 pair similarity 升级为 candidate 与当前 vessel h…
- ADD body block 316 · paragraph · heading: A6.15.1 UA-IFRMN 的一次完整推理循环 · cell paragraphs: —
  - A6.15.1 UA-IFRMN 的一次完整推理循环
- ADD body block 317 · paragraph · heading: A6.15.1 UA-IFRMN 的一次完整推理循环 · cell paragraphs: —
  - Step 0 — 编码而不压扁：对 query 和候选库生成 Fragment Token Bank；静态 encoder 可沿用现有成熟主干，先不改变 backbone。
- ADD body block 318 · paragraph · heading: A6.15.1 UA-IFRMN 的一次完整推理循环 · cell paragraphs: —
  - Step 1 — 双路粗检：同时产生高召回 same-vessel shortlist 与 R2 contact shortlist。前者防止“只沿邻片链才能发现远端碎片”，后者为关系扩展提供局部结构 seed。
- ADD body block 319 · paragraph · heading: A6.15.1 UA-IFRMN 的一次完整推理循环 · cell paragraphs: —
  - Step 2 — 形成 Soft R2 edges：relation head 输出 R0/R1/R2/UNKNOWN posterior 与 relation latent；3D 可用时再通过几何互补／接触 verifier 产生额外证据，但 verifier 不直接覆盖网络 posterior。
- ADD body block 320 · paragraph · heading: A6.15.1 UA-IFRMN 的一次完整推理循环 · cell paragraphs: —
  - Step 3 — 不确定性感知写入：只有满足质量和可比较条件的证据才进入 M_R2；其写入是 soft 的，保存 posterior、置信区间／校准量、source 与时间版本，不做不可逆 hard merge。
- ADD body block 321 · paragraph · heading: A6.15.1 UA-IFRMN 的一次完整推理循环 · cell paragraphs: —
  - Step 4 — Contact-Conditioned Identity Expansion：以高置信 R2 seed 或局部组件为起点，在 G_t 上做多跳候选扩展；扩展只提高 same-vessel prior，不直接把多跳终点标成 R1 或 R2。
- ADD body block 322 · paragraph · heading: A6.15.1 UA-IFRMN 的一次完整推理循环 · cell paragraphs: —
  - Step 5 — Candidate-conditioned recurrent reasoning：对每个待判候选读取其自身 token、相关 R2 Local Memory、Vessel Memory 与关系图路径，更新 R0/R1/R2/UNKNOWN posterior。
- ADD body block 323 · paragraph · heading: A6.15.1 UA-IFRMN 的一次完整推理循环 · cell paragraphs: —
  - Step 6 — Joint reread / revise：一旦新碎片被高置信接受，重新计算与该局部组件相关的旧边；允许 old R2 下降、R1/R2 互换、候选休眠或恢复。
- ADD body block 324 · paragraph · heading: A6.15.1 UA-IFRMN 的一次完整推理循环 · cell paragraphs: —
  - Step 7 — 动态停止或继续：当 Top-K、typed relation graph 与 vessel latent 连续多轮稳定且证据预算已足够时停止；若仍冲突则继续读 Evidence Bank，或输出 UNKNOWN / 补采建议。
- ADD body block 325 · paragraph · heading: A6.16 从 R2 到 R1 的关系代数：允许“身份传播”，禁止“邻接传播” · cell paragraphs: —
  - A6.16 从 R2 到 R1 的关系代数：允许“身份传播”，禁止“邻接传播”
- ADD body block 326 · paragraph · heading: A6.16 从 R2 到 R1 的关系代数：允许“身份传播”，禁止“邻接传播” · cell paragraphs: —
  - UA-IFRMN 必须显式尊重现行标签定义：R2 是原碎裂事件当前叶子片间的直接历史邻接，R1 是同器物但无直接历史断裂接触。因此，A—B 为 R2、B—C 为 R2，并不能推出 A—C 为 R2；它只能为 “A 与 C 属于同一器物” 提供强结构证据。最终 A—C 是 R1、R2 还是 UNKNOWN，仍要由直接接触证据和历史邻接真值判定。
- ADD body block 327 · table · heading: A6.16 从 R2 到 R1 的关系代数：允许“身份传播”，禁止“邻接传播” · cell paragraphs: 18
  - 关系组合 允许的推理 设计意义 R2(A,B) + R2(B,C) same-vessel(A,C) prior ↑；A-C 的直接邻接类型仍未知。 最典型的“局部接触链 → 器物身份扩展”。 R2(A,B) + R1(B,C) same-vessel(A,C) prior ↑，但强度应低于双高可信 R2，并受 B-C 证据质量控制。 允许 R1 参与身份传播，但避免弱关系无限扩散。 R1(A,B) + R1(B,C) 只能作为 soft same-vessel 支持；不能做硬传递。 R1 本身可能来自外观／材质相似，错误相关风险更高。 R2 路径 + 强材质／器型矛盾 触发 joint reread 和 hypothesis revision，而不是强制维持同器物。 用反证抑制“图一旦连通就全部同器物”的灾难。 多条独立 R2 路径指向同一候选 可增加 same-vessel belief，但必须做 source de-correlation。 避免由同一重建／同一照片派生的多条证据被重复计权。
- ADD body block 328 · paragraph · heading: A6.16 从 R2 到 R1 的关系代数：允许“身份传播”，禁止“邻接传播” · cell paragraphs: —
  - 研究实现上建议把 same-vessel 与 direct-contact 解耦成两个相关但不同的头：P_same(i,j) 表示器物身份兼容，P_R2(i,j) 表示直接历史邻接；随后由 typed relation head 在 R0/R1/R2/UNKNOWN 上给出最终分布。这样多跳图只影响 P_same 或 vessel compatibility，不会错误地让 R2 具备传递性。
- ADD body block 329 · paragraph · heading: A6.17 为什么不能只把“邻片概率”喂回去：Scalar Feedback、Latent Feedback 与多假设记忆 · cell paragraphs: —
  - A6.17 为什么不能只把“邻片概率”喂回去：Scalar Feedback、Latent Feedback 与多假设记忆
- ADD body block 330 · paragraph · heading: A6.17 为什么不能只把“邻片概率”喂回去：Scalar Feedback、Latent Feedback 与多假设记忆 · cell paragraphs: —
  - 用户提出的原始思路“预测邻片后，把邻片预测作为下一轮输入，再判断同器物非邻片”应保留为最小基线，但正式候选必须把“反馈什么”做成分层实验。单一 P(R2) 只表达最终置信度，不包含模型是依据断口、几何、纹样还是质量得出的结论，也无法区分“高分但证据冲突”和“高分且多证据一致”。
- ADD body block 331 · table · heading: A6.17 为什么不能只把“邻片概率”喂回去：Scalar Feedback、Latent Feedback 与多假设记忆 · cell paragraphs: 24
  - 反馈层级 输入下一轮的内容 研究价值 主要风险 B1 Scalar Feedback 只把 P(R2)、margin、quality 等少量标量反馈给下一轮。 最便宜、最可解释，是用户原始想法的直接实现；必须保留为基线。 信息瓶颈最大，无法携带局部证据结构。 B2 Latent Relation Feedback 反馈 e_ij relation latent + typed posterior + provenance mask。 对应 continuous latent reasoning 思想；允许下一轮利用“为什么像邻片”的连续内部表示。 latent 可能学到不可解释捷径，需要 probe 和 corruption test。 B3 Neighbor Token Set 将高可信邻片的局部 token set 作为可查询上下文，而不是压成一个 latent。 保留断口／纹样／3D 多区域证据，接近 set-to-set retrieval。 计算和显存增加，需 K/L 预算。 B4 Soft Multi-Hypothesis Memory 同时保留多个关系／器物假设，以权重而非 one-hot winner 表示。 避免第一步错边后全链路 collapse；允许后续证据翻案。 需要假设裁剪和去重，否则复杂度膨胀。 B5 Joint Graph Reread 新证据加入后，…
- ADD body block 332 · paragraph · heading: A6.17 为什么不能只把“邻片概率”喂回去：Scalar Feedback、Latent Feedback 与多假设记忆 · cell paragraphs: —
  - 因此推荐研究顺序固定为 B1 → B2 → B3 → B4/B5。只有 B2 在同输入、同候选池、相近 FLOPs 下显著优于 B1，才能说明“连续 relation latent”本身具有价值；否则不允许仅因为结构更复杂而升级主干。
- ADD body block 333 · paragraph · heading: A6.18 双记忆与器物潜变量：R2 Local Memory × Vessel Identity Memory · cell paragraphs: —
  - A6.18 双记忆与器物潜变量：R2 Local Memory × Vessel Identity Memory
- ADD body block 334 · paragraph · heading: A6.18 双记忆与器物潜变量：R2 Local Memory × Vessel Identity Memory · cell paragraphs: —
  - R2 与 R1 的核心证据分布不同。R2 更依赖断口局部互补、接触几何、局部纹理连续；R1 可能没有任何直接接触，反而依赖材质、壁厚、器形曲率、纹样体系、制造痕迹以及当前已恢复器物的整体先验。因此不建议让同一个 memory slot 同时承担两类关系。
- ADD body block 335 · table · heading: A6.18 双记忆与器物潜变量：R2 Local Memory × Vessel Identity Memory · cell paragraphs: 16
  - 记忆层 保存内容 主要服务目标 主要思想来源 短时／局部：R2 Local Memory 断口 patch、局部 3D、法线／曲率、互补场、contact/gap/penetration、局部纹样连续、fracture visibility、质量。 高精度直接邻接验证、局部组件形成、反证。 参考 VisMem 的 fine-grained short-term visual memory、GARF 的 fracture-aware 表征、Combinative Matching 的几何互补。 长时／器物：Vessel Identity Memory 材质、釉色／纹样族、壁厚统计、器型 profile、曲率趋势、已确认组件的全局关系、missing/unknown slots、稳定 provenance。 远距离 R1 检索、同器物候选排序、抑制“只看断口”造成的漏检。 参考 Titans 的短／长期记忆分工、Jigsaw++ 完整 shape prior、Beyond Reassembly missing tokens。 证据源：Persistent Evidence Bank 原始图像、局部 patch、3D、质量和采集版本，不被循环覆盖。 任何关系被质疑时可重新取证；防止 self-confirmation。 与 A6.5 既有 Evidence Bank 一致，本节只扩展其在…
- ADD body block 336 · paragraph · heading: A6.18 双记忆与器物潜变量：R2 Local Memory × Vessel Identity Memory · cell paragraphs: —
  - Vessel Memory 不等于“把所有已接受碎片做平均池化”。建议至少比较：mean pooling、attention pooling、slot-based memory、set transformer／Perceiver-style query，以及带 missing slots 的 vessel token。任何复杂版本都必须对照简单 pooling，防止“多参数 = 更好”的假象。
- ADD body block 337 · paragraph · heading: A6.19 错误传播控制：Predict → Verify → Soft Write → Reread → Revise · cell paragraphs: —
  - A6.19 错误传播控制：Predict → Verify → Soft Write → Reread → Revise
- ADD body block 338 · paragraph · heading: A6.19 错误传播控制：Predict → Verify → Soft Write → Reread → Revise · cell paragraphs: —
  - 这条创新线最大的风险不是“能不能利用正确 R2”，而是“错误 R2 会不会污染后续 R1”。因此误差传播本身必须成为论文级评测对象，而不是部署阶段再修。SARe 的 many-fragment cascading failure、MV-RoMa 的 pairwise chaining inconsistency 以及本项目既有反自证规则共同要求：任何关系写入都必须可撤销、可追溯、可重新验证。
- ADD body block 339 · table · heading: A6.19 错误传播控制：Predict → Verify → Soft Write → Reread → Revise · cell paragraphs: 24
  - 控制机制 实施约束 目的 Soft Write 边只写 posterior + latent + quality + provenance，不写 one-hot 真值。 降低早期错误的不可逆性。 Geometric Verification 有合格 3D 时，用局部互补、gap/contact/penetration、相反体积占据等进行独立物理检查。 把“网络觉得像”与“物理上能接触”分开。 Joint Reread 新碎片加入后，重算与受影响组件相关的旧边。 允许 P(R2) 0.82 → 0.41，而不是永久自证。 Candidate Dormancy / Resurrection 低分但证据不足的候选进入 Dormant，不直接永久删除；新证据可复活。 适应低质输入与遮挡。 Multi-Hypothesis Retention 在高不确定时保留多个图假设或边分布。 避免单路径 autoregression 的早期塌缩。 Source De-correlation 相同照片派生的 2D、3D、重建置信度标记同源。 防止一条错误观测以多种“证据”形式被重复放大。 Abstain / UNKNOWN posterior 不稳定、强冲突或 evidence coverage 不足时输出 UNKNOWN / 补采。 错误控制优先于强迫形成完整关系图。
- ADD body block 340 · paragraph · heading: A6.20 训练路线：Oracle 关系上限 → 预测关系闭环 → 人工腐化鲁棒性 · cell paragraphs: —
  - A6.20 训练路线：Oracle 关系上限 → 预测关系闭环 → 人工腐化鲁棒性
- ADD body block 341 · paragraph · heading: A6.20 训练路线：Oracle 关系上限 → 预测关系闭环 → 人工腐化鲁棒性 · cell paragraphs: —
  - 训练不得从一开始就把完整 UA-IFRMN 端到端同时打开。否则任何增益都无法判断来自“R2 上下文真的有用”、更大模型、更大计算还是标签泄漏。建议按下面顺序建立证据。
- ADD body block 342 · table · heading: A6.20 训练路线：Oracle 关系上限 → 预测关系闭环 → 人工腐化鲁棒性 · cell paragraphs: 27
  - 阶段 训练／输入设置 必须回答的问题 T0 Pairwise baseline 完全不使用关系记忆。输入 q,c，输出 R0/R1/R2/UNKNOWN。 冻结最强静态基线。 T1 Oracle-R2 context 第二阶段只给 GT R2 邻片／局部组件，不给模型自己预测的边。 回答最关键问题：如果邻片信息正确，R1 是否存在足够大的可利用上限？若无明显增益，整条路线停止。 T2 Scalar predicted-R2 使用模型自己的 P(R2) 标量反馈。 验证用户原始想法能否在最小复杂度下成立。 T3 Latent predicted-R2 反馈 e_R2 relation latent 与证据 mask。 检验 continuous relation state 是否比 scalar 真正多提供信息。 T4 Scheduled / mixed memory 训练时混合 GT、predicted、incomplete memory，逐步降低 GT 比例。 减少 train-test distribution shift。 T5 Corrupted memory curriculum 主动注入 false R2、missed R2、wrong same-vessel、低质量边、缺失 3D、冲突证据。 强迫模型把 memory 当证据而非真理，并训练 revision。 T6 …
- ADD body block 343 · paragraph · heading: A6.20 训练路线：Oracle 关系上限 → 预测关系闭环 → 人工腐化鲁棒性 · cell paragraphs: —
  - A12 可控合成碎片实验室应为本路线生成专门 episode，而不是只增加总样本量：同一母体生成完整 R2 图与 R1 集合；然后分别制造 0%、5%、10%、20%、30% 错边，或只破坏一个关系证据轴，形成严格配对的 corruption ladder。真实数据必须保留独立母体确认集，合成数据只能用于预训练、机制压力测试和错误模式覆盖，不能代替真实成立证据。
- ADD body block 344 · paragraph · heading: A6.20.1 候选损失项：先作为可拆卸假设，不一次全部启用 · cell paragraphs: —
  - A6.20.1 候选损失项：先作为可拆卸假设，不一次全部启用
- ADD body block 345 · paragraph · heading: A6.20.1 候选损失项：先作为可拆卸假设，不一次全部启用 · cell paragraphs: —
  - 可维护以下损失池：L_same（同器物 membership）、L_R2（直接历史邻接）、L_contact（可比较条件下的接触／互补）、L_rank（候选排序）、L_comp（relation composition 一致性）、L_calib（posterior 校准）、L_revision（错误边被新证据推翻时的修正监督）、L_memory（vessel/local memory 一致性）以及可选 L_distill（TORA-like relation structure distillation）。任何一次正式消融只允许新增一个主要损失项，并报告其对 R1、R2、误导风险和计算的独立影响。
- ADD body block 346 · paragraph · heading: A6.20.1 候选损失项：先作为可拆卸假设，不一次全部启用 · cell paragraphs: —
  - 一个重要约束是：L_comp 只鼓励 R2 路径提高 same-vessel belief，不允许把 R2 传递为 R2。即使 A-B 与 B-C 都是 R2，也不能把 A-C 直接监督为 R2；A-C 的直接邻接标签仍由历史真值单独决定。
- ADD body block 347 · paragraph · heading: A6.21 必做实验矩阵：先证明“邻片上下文有信息”，再证明“新机制能安全利用它” · cell paragraphs: —
  - A6.21 必做实验矩阵：先证明“邻片上下文有信息”，再证明“新机制能安全利用它”
- ADD body block 348 · table · heading: A6.21 必做实验矩阵：先证明“邻片上下文有信息”，再证明“新机制能安全利用它” · cell paragraphs: 48
  - 实验 最低对照 核心观测 否定／进入条件 Oracle-R2 上限实验 Pairwise R1 vs Pairwise + GT R2 context R1 Hit@K / same-vessel Hit@K / CovRecall 若 GT R2 也不能稳定提升 R1，则暂停 UA-IFRMN。 Scalar vs Latent Feedback P(R2) 标量 vs e_R2 latent，同候选池同 FLOPs R1、R2、ECE/Brier、时延 只有 latent 显著优于 scalar 才保留连续反馈。 单邻片 vs 多邻片集合 Top1 R2 context vs Top-K neighbor token set R1、覆盖、多邻片真值恢复 证明 set context 是否真实有价值。 Pairwise chaining vs Soft Graph 直接把边串起来 vs typed soft graph 级联错误率、R1、错误图连通率 Soft graph 必须明显减少错误传播。 Hard Commit vs Reversible Memory 接受后不可撤销 vs joint reread/revise wrong→correct、correct→wrong、最终命中 可反悔机制必须提高恢复率且不显著伤害 clean。 无 Vessel Memory vs Ve…
- ADD body block 349 · paragraph · heading: A6.21 必做实验矩阵：先证明“邻片上下文有信息”，再证明“新机制能安全利用它” · cell paragraphs: —
  - 推荐把 Oracle-R2 gap 作为第一道 go/no-go 门。它直接测量“正确邻接上下文最多能给 R1 带来多少信息”。只有这个上限足够大，后续关于 latent feedback、图记忆、vessel memory 和 multi-hop reasoning 的工程投入才有意义。第二道门是 predicted-R2 与 corruption curve：如果真实预测边一加入就把 R1 拖垮，则优先研究校准、验证和 revision，而不是继续扩主干。
- ADD body block 350 · paragraph · heading: A6.22 可形成的研究主张与明确禁写项 · cell paragraphs: —
  - A6.22 可形成的研究主张与明确禁写项
- ADD body block 351 · paragraph · heading: A6.22 可形成的研究主张与明确禁写项 · cell paragraphs: —
  - 现阶段不得写“首次将自回归用于碎片重建”：PuzzleFusion++ 已经明确采用 auto-agglomerative、类 autoregressive 的逐步组装。也不得写“首次把预测碎片关系反馈给下一轮”：SARe 已经使用接触图、几何验证与可靠子结构反馈／重采样。任何论文新颖性都必须避开这两个宽泛表述。
- ADD body block 352 · paragraph · heading: A6.22 可形成的研究主张与明确禁写项 · cell paragraphs: —
  - 当前更有希望、但仍需实验证明的主张是：在“同器物非邻接检索”问题上，利用直接历史邻接 R2 构建带不确定性、可修正的 typed relation memory，并通过 contact-conditioned multi-hop identity expansion 与 vessel-level latent context 提高 R1 检索；同时显式测量和抑制错误 R2 的级联传播。
- ADD body block 353 · paragraph · heading: A6.22 可形成的研究主张与明确禁写项 · cell paragraphs: —
  - 可暂定英文机制描述：Uncertainty-Aware Iterative Fragment Relational Memory Network (UA-IFRMN) for Contact-Conditioned Identity Expansion。正式投稿前必须再次检索同题工作，并以当时最新文献决定名称与新颖性措辞。
- ADD body block 354 · table · heading: A6.22 可形成的研究主张与明确禁写项 · cell paragraphs: 8
  - 类别 内容 可以研究 R2 作为局部结构 seed 是否显著提高 R1；soft typed graph 是否比 pair chaining 更稳；latent relation feedback 是否比 scalar feedback 更有效；Vessel Memory 是否改善远距离 R1；可反悔机制是否降低级联错误。 不能预先声称 UA-IFRMN 已经优于 SOTA；R2→R1 一定有效；循环／CTM 本身就是创新；自回归思想首次用于碎片；完整器物 prior 一定能帮助低质陶片。 必须保留的失败解释 Oracle-R2 无上限；predicted-R2 噪声抵消收益；Vessel Memory 形成 shortcut；多跳扩展造成 graph over-smoothing；relation latent 无法优于标量；可反悔机制成本过高。
- ADD body block 355 · paragraph · heading: A6.23 创新账本增补：UA-IFRMN 关系记忆路线 · cell paragraphs: —
  - A6.23 创新账本增补：UA-IFRMN 关系记忆路线
- ADD body block 356 · paragraph · heading: A6.23 创新账本增补：UA-IFRMN 关系记忆路线 · cell paragraphs: —
  - 以下编号从现有 INNO-31 之后顺延，只新增、不覆盖旧条目。全部状态初始为 RESEARCH_CANDIDATE 或 IDEA，待冻结实验后再流转。
- ADD body block 357 · table · heading: A6.23 创新账本增补：UA-IFRMN 关系记忆路线 · cell paragraphs: 60
  - ID 创新候选 当前优先级 状态 INNO-32 UA-IFRMN：Uncertainty-Aware Iterative Fragment Relational Memory Network。 P0 核心 RESEARCH_CANDIDATE INNO-33 Contact-Conditioned Identity Expansion：用高置信 R2 局部接触结构作为 R1 同器物身份扩展条件。 P0 核心 RESEARCH_CANDIDATE INNO-34 Soft Typed Relation Graph Memory：R0/R1/R2/UNKNOWN + latent + quality + provenance 的可修正关系图。 P0 核心 RESEARCH_CANDIDATE INNO-35 Latent Relation Feedback：反馈连续 relation latent，而非只反馈 P(R2) 标量。 P1 高潜 RESEARCH_CANDIDATE INNO-36 Dual Relational Memory：R2 Local Memory + Vessel Identity Memory 分工。 P0 架构 RESEARCH_CANDIDATE INNO-37 Reversible Joint Reread：新证据进入后联合重读受影响子图，允许旧边降权…
- ADD body block 358 · paragraph · heading: A6.24 本次增补的外部来源与复现优先级 · cell paragraphs: —
  - A6.24 本次增补的外部来源与复现优先级
- ADD body block 359 · paragraph · heading: A6.24 本次增补的外部来源与复现优先级 · cell paragraphs: —
  - 来源分为两类：会议／期刊正式论文用于建立强对照，2026 年预印本用于跟踪最新方向。预印本在正式投稿前必须再次核验版本、发表状态和结论；不得把预印本结果写成社区共识。建议优先阅读／复现顺序为：SARe → PuzzleFusion++ → GARF → Combinative Matching / Rectified Point Flow → MHopReg → Jigsaw++ / Beyond Reassembly → Bag of Bags → Coconut / VisMem / WorldMM / Titans → TORA / MV-RoMa。
- ADD body block 360 · paragraph · heading: A6.24 本次增补的外部来源与复现优先级 · cell paragraphs: —
  - 1. Jia et al. SARe: Structure-Aware Large-Scale 3D Fragment Reassembly. arXiv:2603.21611, 2026.
- ADD body block 361 · paragraph · heading: A6.24 本次增补的外部来源与复现优先级 · cell paragraphs: —
  - 2. Wang, Chen, Furukawa. PuzzleFusion++: Auto-agglomerative 3D Fracture Assembly by Denoise and Verify. ICLR 2025.
- ADD body block 362 · paragraph · heading: A6.24 本次增补的外部来源与复现优先级 · cell paragraphs: —
  - 3. Li et al. GARF: Learning Generalizable 3D Reassembly for Real-World Fractures. ICCV 2025.
- ADD body block 363 · paragraph · heading: A6.24 本次增补的外部来源与复现优先级 · cell paragraphs: —
  - 4. Sun et al. Rectified Point Flow: Generic Point Cloud Pose Estimation. NeurIPS 2025 Spotlight; arXiv:2506.05282.
- ADD body block 364 · paragraph · heading: A6.24 本次增补的外部来源与复现优先级 · cell paragraphs: —
  - 5. Lee et al. Combinative Matching for Geometric Shape Assembly. ICCV 2025 Highlight. DOI: 10.1109/ICCV51701.2025.00890.
- ADD body block 365 · paragraph · heading: A6.24 本次增补的外部来源与复现优先级 · cell paragraphs: —
  - 6. Lee et al. TORA: Topological Representation Alignment for 3D Shape Assembly. arXiv:2604.04050, 2026.
- ADD body block 366 · paragraph · heading: A6.24 本次增补的外部来源与复现优先级 · cell paragraphs: —
  - 7. Lu, Hua, Huang. Jigsaw++: Imagining Complete Shape Priors for Object Reassembly. ICCV 2025.
- ADD body block 367 · paragraph · heading: A6.24 本次增补的外部来源与复现优先级 · cell paragraphs: —
  - 8. Xu et al. Beyond Reassembly: Fractured Object Recovery with Missing Parts. CVPR 2026.
- ADD body block 368 · paragraph · heading: A6.24 本次增补的外部来源与复现优先级 · cell paragraphs: —
  - 9. Wu et al. MHopReg: Efficient Hierarchical Multi-Hop Graph Search for Point Cloud Registration. CVPR 2026.
- ADD body block 369 · paragraph · heading: A6.24 本次增补的外部来源与复现优先级 · cell paragraphs: —
  - 10. Lee, Kang, Yoo. MV-RoMa: From Pairwise Matching into Multi-View Track Reconstruction. arXiv:2603.27542, 2026.
- ADD body block 370 · paragraph · heading: A6.24 本次增补的外部来源与复现优先级 · cell paragraphs: —
  - 11. Gogawale et al. Bag of Bags: Adaptive Visual Vocabularies for Genizah Join Image Retrieval. CVPR Workshops 2026.
- ADD body block 371 · paragraph · heading: A6.24 本次增补的外部来源与复现优先级 · cell paragraphs: —
  - 12. Yu et al. Mitigating spurious features by contrastive learning in pottery sherd recognition. npj Heritage Science 14, 135 (2026).
- ADD body block 372 · paragraph · heading: A6.24 本次增补的外部来源与复现优先级 · cell paragraphs: —
  - 13. Hao et al. Training Large Language Models to Reason in a Continuous Latent Space (Coconut). arXiv:2412.06769; ICLR 2025 Workshop.
- ADD body block 373 · paragraph · heading: A6.24 本次增补的外部来源与复现优先级 · cell paragraphs: —
  - 14. Behrouz, Zhong, Mirrokni. Titans: Learning to Memorize at Test Time. NeurIPS 2025.
- ADD body block 374 · paragraph · heading: A6.24 本次增补的外部来源与复现优先级 · cell paragraphs: —
  - 15. Yu et al. VisMem: Latent Vision Memory Unlocks Potential of Vision-Language Models. CVPR 2026.
- ADD body block 375 · paragraph · heading: A6.24 本次增补的外部来源与复现优先级 · cell paragraphs: —
  - 16. Yeo et al. WorldMM: Dynamic Multimodal Memory Agent for Long Video Reasoning. CVPR 2026.
- ADD body block 376 · paragraph · heading: A6.24 本次增补的外部来源与复现优先级 · cell paragraphs: —
  - 本次 A6 增补状态：仅完成长期创新区的思想登记、架构假设、参考映射与最小实验合同；未改变 A1–A5、A7 以后正文、现有历史实验判决、A12 合成平台事实状态或比赛稳定主线。
- ADD body block 377 · paragraph · heading: A6.25 Whole-Vessel Membership Recovery：从一块碎片恢复整个器物成员集合 · cell paragraphs: —
  - A6.25 Whole-Vessel Membership Recovery：从一块碎片恢复整个器物成员集合
- ADD body block 378 · paragraph · heading: A6.25 Whole-Vessel Membership Recovery：从一块碎片恢复整个器物成员集合 · cell paragraphs: —
  - 长期主任务定义为Fragment-to-Vessel Membership Recovery：输入任意查询碎片q和混合图库G，输出G中与q属于同一器物的预测成员集合V_hat(q)，并区分其中直接历史邻接R2与非直接邻接R1。该任务不要求一次性输出完整几何装配；它首先研究“哪些碎片属于一起”，再把几何装配作为可选后续。这样既贴合专家实际搜索负担，也把研究问题从pairwise similarity提升为set recovery与relational retrieval。
- ADD body block 379 · table · heading: A6.25 Whole-Vessel Membership Recovery：从一块碎片恢复整个器物成员集合 · cell paragraphs: 21
  - 阶段 核心操作 研究意义 Seed retrieval 从q召回高置信R2和same-vessel种子 建立第一批可靠局部证据；不追求一次找全。 Local component formation 把通过验证的R2软写入R2 Local Memory 得到局部组件，但R2不传递。 Vessel hypothesis 由已接受/高置信成员建立Vessel Identity Memory 形成材质、壁厚、曲率、纹样体系和器型趋势等器物级条件。 Database re-search 用q + 当前器物假设重新扫描全库 寻找与q不接触但与整体器物假设兼容的R1。 Joint reread 新成员加入后重读旧边、冲突与缺失证据 允许早期关系降级、撤回或恢复，控制级联错误。 Stop/abstain 边际收益低、风险高、预算耗尽或无新证据时停止 避免为了高Recall无限扩张集合。
- ADD body block 380 · paragraph · heading: A6.26 High-Degradation Robust Retrieval：高磨损、风化与部分观测下的鲁棒碎片检索 · cell paragraphs: —
  - A6.26 High-Degradation Robust Retrieval：高磨损、风化与部分观测下的鲁棒碎片检索
- ADD body block 381 · paragraph · heading: A6.26 High-Degradation Robust Retrieval：高磨损、风化与部分观测下的鲁棒碎片检索 · cell paragraphs: —
  - 第二条核心研究主线是“证据被物理过程破坏后模型还能保留多少检索能力”。传统几何算法在完整断口、可靠3D和高重叠条件下必须作为强基线；RelicWeave的研究价值不在于清晰样本多赢几个百分点，而在于随着断口磨圆、崩缺、表面侵蚀、纹样缺失、成像噪声和3D重建伪影增强，性能下降是否显著慢于传统精确匹配和普通静态网络。
- ADD body block 382 · table · heading: A6.26 High-Degradation Robust Retrieval：高磨损、风化与部分观测下的鲁棒碎片检索 · cell paragraphs: 21
  - 退化层级 控制内容 要回答的问题 D0 Clean 断口与表面证据完整 建立传统方法和学习方法的上限；允许传统法胜出。 D1 Mild wear 轻度磨圆/轻纹理损伤 观察第一处性能分离点。 D2 Local chipping 局部崩边/缺口 测试局部对应丢失时的多模态补偿。 D3 Partial fracture loss 20–40%断口信息不可见或缺失 测试partial observation与拒识。 D4 Severe mixed degradation 磨损+崩缺+表面退化+成像噪声 测试关系上下文和Vessel Memory是否提供额外鲁棒性。 D5 Real domain 真实自然风化/真实采集误差 只作为独立确认；不能用合成D级替代。
- ADD body block 383 · paragraph · heading: A6.27 统一论文路线：共享一个问题族，不把所有创新强塞进一篇论文 · cell paragraphs: —
  - A6.27 统一论文路线：共享一个问题族，不把所有创新强塞进一篇论文
- ADD body block 384 · paragraph · heading: A6.27 统一论文路线：共享一个问题族，不把所有创新强塞进一篇论文 · cell paragraphs: —
  - V1.47把科研方向整理成一个问题族：低质量碎片如何从局部接触证据逐步恢复器物身份。具体投稿时只选择证据最强的一条主贡献，其他机制降为支撑或后续工作。文化遗产是高价值真实场景，但CVPR级论文必须把任务抽象为可推广的视觉问题，并用强基线、真实退化、机制消融和跨域/跨采集验证证明贡献。
- ADD body block 385 · table · heading: A6.27 统一论文路线：共享一个问题族，不把所有创新强塞进一篇论文 · cell paragraphs: 24
  - 论文候选 核心问题 必须证据 止损条件 PAPER-A：Robust Fragment Retrieval under Physical Degradation 退化鲁棒检索 性能—退化强度曲线；传统几何/静态AI/新方法公平对照；Synthetic→Real。 若真实退化没有稳定增益，转为数据/应用论文。 PAPER-B：Contact-Conditioned Vessel Identity Expansion R2→R1 / UA-IFRMN Oracle-R2→Predicted-R2→Corrupted-R2；证明局部接触上下文对R1有信息且可安全利用。 若Oracle-R2都不能提升R1，停止该主张。 PAPER-C：Fragment-to-Vessel Membership Recovery 整器物成员恢复新任务/集合检索 Vessel Precision/Recall/F1；不同成员数和库规模；set/graph/metric学习强基线。 若任务GT无法闭合或只在单器型有效，先不宣称通用任务。 PAPER-D：Physics-Guided Synthetic-to-Real Pretraining A12/VesselForge/PG-Frag 物理合理碎裂+退化预训练是否降低真实样本需求并提升跨域鲁棒性。 若synthetic-pretrain无真实收益，只保留为实…
- ADD body block 386 · paragraph · heading: A6.28 顶会级研究门槛与禁止性表述 · cell paragraphs: —
  - A6.28 顶会级研究门槛与禁止性表述
- ADD body block 387 · paragraph · heading: A6.28 顶会级研究门槛与禁止性表述 · cell paragraphs: —
  - 进入CVPR/ICCV等主会级主线前至少需要：①真实或可信独立域数据，不能只靠合成；②与传统几何、强检索、set/graph模型和最接近碎片方法的同输入对照；③预注册或冻结的主指标和独立确认；④机制消融能够排除“只是更多参数/更多照片/更多计算”；⑤退化、库规模、成员数和hard negative分层；⑥失败案例与适用域。禁止写“首次使用自回归做碎片”“首次把预测关系反馈回网络”等高风险新颖性断言；真正可能成立的主张应收敛到高退化下的关系记忆、R2条件的器物身份扩展或整器物成员恢复。
- ADD body block 442 · paragraph · heading: EXP10 高磨损/风化鲁棒性基准 · cell paragraphs: —
  - EXP10 高磨损/风化鲁棒性基准
- ADD body block 443 · paragraph · heading: EXP10 高磨损/风化鲁棒性基准 · cell paragraphs: —
  - 冻结同一批query、gallery、GT、训练预算和观测权限，建立D0→Dn配对退化阶梯。最低对照包括人工可观察性、ICP/GICP或等价传统配准、FPFH/SHOT或其他合法局部描述子、曲率/轮廓基线、静态深度检索和当前RelicWeave。主输出为Hit/CovRecall/Same-Vessel与Vessel指标随退化强度的曲线、失败转移点和真实域确认。清晰档传统算法强不算失败；只有高退化档出现稳定且可归因优势，才能写“AI在该场景增加价值”。
- ADD body block 444 · paragraph · heading: EXP11 整器物成员恢复（Vessel Membership Recovery） · cell paragraphs: —
  - EXP11 整器物成员恢复（Vessel Membership Recovery）
- ADD body block 445 · paragraph · heading: EXP11 整器物成员恢复（Vessel Membership Recovery） · cell paragraphs: —
  - 只使用member set闭合的母体。给定单个query，系统从空或最小seed开始迭代检索，输出R2、R1和最终V_hat(q)。比较pairwise retrieval、简单聚类/metric learning、set/graph baseline、静态vessel prototype和UA-IFRMN候选。报告Vessel Precision/Recall/F1、完整找回率、首个错误成员进入轮次、迭代次数、查询墙钟和专家需要核验的候选数。不同器物成员数、图库规模、材质和器型分层。
- ADD body block 446 · paragraph · heading: EXP12 R2→R1关系上下文与错误传播 · cell paragraphs: —
  - EXP12 R2→R1关系上下文与错误传播
- ADD body block 447 · paragraph · heading: EXP12 R2→R1关系上下文与错误传播 · cell paragraphs: —
  - 第一步Oracle-R2：只替换关系上下文，不改视觉输入，验证真实邻接上下文能否提升R1/same-vessel；第二步Predicted-R2：换成模型预测并保留posterior、quality与relation latent；第三步Corrupted-R2：按0/5/10/20/30%注入错边、漏边和不完整memory。比较Scalar Feedback、Latent Feedback、Neighbor Set、Soft Graph、Vessel Memory与Reversible Memory。若Oracle无增益则暂停；若预测闭环增益只在无错边成立，则不能进入部署。
- ADD body block 550 · paragraph · heading: A12.21 V1.47退化性能曲线：把SyntheticLab变成“物理退化压力测试仪” · cell paragraphs: —
  - A12.21 V1.47退化性能曲线：把SyntheticLab变成“物理退化压力测试仪”
- ADD body block 551 · paragraph · heading: A12.21 V1.47退化性能曲线：把SyntheticLab变成“物理退化压力测试仪” · cell paragraphs: —
  - A12新增一类paired counterfactual release：同一clean母体、同一碎片关系、同一query/gallery与基础随机种子，沿磨损、崩缺、表面侵蚀、遮挡、图像质量、3D缺失/增生噪点等单轴或预注册组合轴生成D0→Dn观测。每个release必须同时提供传统算法合法输入、学习模型合法输入和TruthPack，但TruthPack只供评测。输出不仅是某一档准确率，而是每个方法的性能—退化强度曲线、临界失效点、AUC/斜率型诊断和真实域对应样本。
- ADD body block 552 · paragraph · heading: A12.22 Whole-Vessel Episode Generator：为整器物成员恢复生成完整关系世界 · cell paragraphs: —
  - A12.22 Whole-Vessel Episode Generator：为整器物成员恢复生成完整关系世界
- ADD body block 553 · paragraph · heading: A12.22 Whole-Vessel Episode Generator：为整器物成员恢复生成完整关系世界 · cell paragraphs: —
  - 每个合成母体除R2边外，还必须导出完整member set、R1/R2 typed relation graph、可见/不可见断面、缺失材料和母体级属性。episode生成器把多个母体混成gallery，随机选择query并控制同器物成员数、R1/R2比例、hard negative密度、器型相似度、材质相似度和退化分布；训练端只看合法Obs，评测端用完整Truth计算Vessel Precision/Recall/F1及多轮扩展轨迹。这样A12的数据价值从“更多pair”升级为“可控整器物关系规模”。
- ADD body block 554 · paragraph · heading: A12.23 Synthetic-to-Real与数据充分性：最终只以真实域收益决定扩容 · cell paragraphs: —
  - A12.23 Synthetic-to-Real与数据充分性：最终只以真实域收益决定扩容
- ADD body block 555 · paragraph · heading: A12.23 Synthetic-to-Real与数据充分性：最终只以真实域收益决定扩容 · cell paragraphs: —
  - 合成预训练的正式价值判断改为三条：①在相同真实标注量下是否提高真实高退化R2/R1与Vessel指标；②达到同一真实目标性能所需的真实母体/碎片量是否下降；③跨相机、材料、器型或自然风化域是否更稳。若10万/50万合成碎片不能在这些真实指标上带来收益，则停止扩容并审计生成分布、shortcut和任务错位，不用合成规模本身作为成果。
- ADD body block 579 · paragraph · heading: B2.3 器物成员集合GT与关系闭合 · cell paragraphs: —
  - B2.3 器物成员集合GT与关系闭合
- ADD body block 580 · paragraph · heading: B2.3 器物成员集合GT与关系闭合 · cell paragraphs: —
  - Level 3评测要求每个eligible object拥有member_manifest：object_id、全部已入库fragment_id、已知missing_fragment/碎屑去向、member_set_complete、R2边集合、R1定义域、UNKNOWN/争议关系、复核者、label_version与hash。V_G(q)从该manifest派生，不能从模型结果反推。若某母体只知道若干邻接但不知道是否还有同器物碎片遗失或未入库，则只能参加Level 1/2的限定评测，不能进入完整成员恢复主分母。
- ADD body block 581 · paragraph · heading: B2.3 器物成员集合GT与关系闭合 · cell paragraphs: —
  - R1是“同器物且无直接历史断裂接触”，不是“暂时拼不上”。因此member_set闭合和R2关系闭合必须分开审计：先确认哪些fragment属于该object，再确认哪些pair有历史直接接触。R2缺边不能自动把pair改成R1；证据不足保留UNKNOWN。
- ADD body block 583 · table · heading: B3 必须采到的数据 · cell paragraphs: 30
  - 数据 必须内容 不合格处理 整片 正面、反面、侧壁、轮廓及断口概览 缺面标未观察，补拍或限定用途 断口 实际断裂表面、两侧壁、厚度变化、边缘 没拍到断裂面不能用于局部关系主测试 连续线索 可见纹饰延续、凹槽、曲率变化和薄壁交界 没有该线索如实记，不生成伪纹饰 质量配对 同片清晰、日常和差质量真实观察 不以压缩副本代替独立实拍 重复会话 重新装夹后的身份、时间和参数 新session，不沿用旧位姿 相机与尺度 镜头、分辨率、曝光信息、标定工况、实测比例尺 无尺度仍可2D，关闭毫米几何 关系证据 已确认邻接及难负例、争议记录 UNKNOWN不用于确定性关系评测 失败与成本 模糊图、高光图、重拍、操作及等待时间 不删失败以提高采集成功率 器物成员GT object_id、member_manifest、member_set_complete、全部fragment_id、missing/UNKNOWN、R1/R2关系图、复核与版本hash 未闭合只做邻片/同器物候选诊断，不进入Whole-Vessel主评测
- ADD body block 836 · paragraph · heading: D6.5 器物成员恢复页（V1.47新增） · cell paragraphs: —
  - D6.5 器物成员恢复页（V1.47新增）
- ADD body block 837 · paragraph · heading: D6.5 器物成员恢复页（V1.47新增） · cell paragraphs: —
  - 结果页采用“三层视图”而不是把所有候选混在一个Top-K：第一栏Direct Neighbor Candidates只显示R2及局部接触证据；第二栏Same-Vessel Candidates显示R1/R2同器物成员及器物身份支持；第三栏Predicted Vessel Set显示当前已纳入成员、待核验成员、被驳回成员、UNKNOWN、Vessel Precision/Recall仅在有GT的评测模式显示。用户接受/驳回某成员后生成新的revision，系统可以重新检索全库并显示“新增成员导致哪些旧关系被加强、削弱或撤回”。
- ADD body block 838 · paragraph · heading: D6.5 器物成员恢复页（V1.47新增） · cell paragraphs: —
  - 比赛演示默认从一块新query开始：采集/导入→全库粗检→R2邻片→形成初始Vessel Memory→发现R1远距离成员→人工核验→成员集更新或停止。若当前模型尚未通过Level 3验证，界面必须标“研究模式/成员候选”，不得把候选集合称为已恢复器物。
- ADD body block 854 · paragraph · heading: D10 用户价值测试与成本 · cell paragraphs: —
  - 用户价值试验升级为四类条件：纯人工；人工+传统几何/规则候选；人工+静态学习候选；人工+RelicWeave关系/器物成员证据。任务分为直接邻片查找、同器物成员发现和整器物成员恢复三种难度，并按清晰/高退化分层。不同条件随机交叉或顺序平衡，避免同一人重复同题记忆优势。记录正确判断耗时、看过候选数、实物拿取/试拼次数、误配漏配、补拍、退出和最终成员集合质量。
- ADD body block 860 · paragraph · heading: D10.2 应用价值、社会价值与AI必要性的证据矩阵 · cell paragraphs: —
  - D10.2 应用价值、社会价值与AI必要性的证据矩阵
- ADD body block 861 · table · heading: D10.2 应用价值、社会价值与AI必要性的证据矩阵 · cell paragraphs: 28
  - 价值维度 必须记录 希望证明的结论 禁止夸大 专家搜索负担 完成一个任务的人时/墙钟、浏览候选数 RelicWeave相对人工和传统候选是否减少筛查 机器负责搜索，专家负责最终确认 实物操作风险 拿取、翻转、实体试拼次数 数字筛选后是否减少无意义实体操作 对脆弱碎片的保护价值 高退化可用性 D0→Dn的Hit/Cov/Vessel曲线 传统方法何时明显下降，RelicWeave是否更平缓 AI只在传统假设失效场景主张必要性 整器物恢复 Vessel Precision/Recall/F1、完整找回率 能否从单片找回数据库中的同器物成员 从局部拼接工具升级为器物身份恢复工具 经济/部署成本 建库人时、设备摊销、推理、维护、专家复核 节省的专家时间是否覆盖新增数据和系统成本 不把“候选缩小”直接换算成ROI 社会/文化价值 可恢复器物信息、可减少遗漏、可审计证据 是否提高文物数字整理与研究效率 定性价值须由真实从业者访谈/任务证据支持
- ADD body block 916 · paragraph · heading: 10 国赛与CVPR交付计划 · cell paragraphs: —
  - 比赛主交付统一围绕“真实碎片搜索负担”而不是算法名：现场从一块新query开始，完成采集/导入与QA、全库检索、R2邻片候选、R1同器物候选、器物成员集合或证据不足停止，并保留人工核验和版本日志。高磨损场景必须提供传统算法/规则基线和学习方法的公平对照，解释为什么简单样本不需要AI、为什么大库/退化/R1场景需要学习与关系推理。自动采集台、3D、RL、CTM和UA-IFRMN都只有在实测收益成立后才进入比赛主展示。
- ADD body block 917 · paragraph · heading: 10 国赛与CVPR交付计划 · cell paragraphs: —
  - 论文主交付从“系统功能清单”收敛为一个清楚科学问题。候选主线按证据强度排序：A 高退化条件下的Robust Fragment Retrieval；B R2条件的Contact-Conditioned Vessel Identity Expansion与UA-IFRMN；C Fragment-to-Vessel Membership Recovery；D Physics-Guided Synthetic-to-Real Pretraining；E Active Evidence Acquisition。一次投稿只选一条主贡献，其余作为必要支撑或后续工作；文化遗产应用价值不能替代通用视觉问题、强基线和可归因机制证据。
- ADD body block 920 · paragraph · heading: 10.1 竞赛方向：用“真痛点→真操作→真改进”组织叙事 · cell paragraphs: —
  - 10.1 竞赛方向：用“真痛点→真操作→真改进”组织叙事
- ADD body block 921 · paragraph · heading: 10.1 竞赛方向：用“真痛点→真操作→真改进”组织叙事 · cell paragraphs: —
  - 竞赛陈述固定从现实流程开始：海量混合碎片中，专家首先要解决“哪些值得比较、哪些属于同一器物”，而不是直接面对已知正确pair。项目展示顺序应是人工/传统方案的可用边界→高磨损和大库带来的失败→RelicWeave如何缩小候选→如何找到R1远距离成员→如何恢复器物成员集合→专家如何最终确认。技术先进性服务于这个工作流，不把CTM、Transformer、CUDA或硬件数量当价值本身。
- ADD body block 922 · table · heading: 10.1 竞赛方向：用“真痛点→真操作→真改进”组织叙事 · cell paragraphs: 18
  - 竞赛叙事块 核心内容 验收/边界 痛点证据 库规模、人工耗时、候选浏览/实物操作、退化样本失败 至少有真实任务或相关从业者访谈；无行业数据时明确标内部试验。 AI必要性 传统算法清晰样本基线 + 高退化/弱对应对照 允许传统法在D0强；重点看高退化、大库和R1。 技能展示 真实采集/QA、模型推理、设备/软件联调、故障恢复、证据核验 四岗位都有可见技术操作，避免纯PPT讲算法。 应用价值 节省筛查时间、减少无意义试拼、提高成员找回、降低遗漏 全部按完整工作流分母测，不把局部模型指标冒充ROI。 创新展示 高退化鲁棒性、整器物成员恢复、关系记忆/主动补采中的已验证部分 研究候选未通过就标实验模式，不冒充稳定能力。
- ADD body block 923 · paragraph · heading: 10.2 论文方向：一套数据底座，多条可独立收敛的研究问题 · cell paragraphs: —
  - 10.2 论文方向：一套数据底座，多条可独立收敛的研究问题
- ADD body block 924 · paragraph · heading: 10.2 论文方向：一套数据底座，多条可独立收敛的研究问题 · cell paragraphs: —
  - 优先顺序由实验决定而不是由想法“看起来高级”决定。先跑EXP10退化曲线和EXP11整器物任务，确认问题本身有足够难度和方法空间；再用EXP12判断R2上下文是否真的给R1带来信息。若Oracle-R2上限明显、Predicted-R2能在错边下保持收益，则UA-IFRMN可升级为方法主线；若关系机制不成立，但A12的物理退化预训练在真实域稳定增益，则把Synthetic-to-Real转为主线。
- ADD body block 925 · paragraph · heading: 10.2 论文方向：一套数据底座，多条可独立收敛的研究问题 · cell paragraphs: —
  - 顶会目标不要求一次把比赛系统所有模块写进论文。最强版本应围绕一个可以被其他视觉任务理解的问题：高退化partial observation、typed relational reasoning、set membership recovery或physics-guided sim-to-real。数据、代码、协议、强基线和负结果比系统模块数量更重要。
- ADD body block 926 · paragraph · heading: 10.3 竞赛与论文共享的证据底座，但结论严格分开 · cell paragraphs: —
  - 10.3 竞赛与论文共享的证据底座，但结论严格分开
- ADD body block 927 · paragraph · heading: 10.3 竞赛与论文共享的证据底座，但结论严格分开 · cell paragraphs: —
  - 两条路线共享真实数据身份、member/neighbor GT、冻结split、退化压力测试、传统/学习基线和工作流日志。比赛可以强调专家减负、社会价值、可操作性与系统完整；论文只能强调被独立实验支持的方法/任务贡献。比赛演示成功不等于论文创新成立，论文模型增益也不自动证明真实工作流节时。
- ADD body block 937 · paragraph · heading: 11 本次归位与历史记录 · cell paragraphs: —
  - V1.47统一“高退化鲁棒检索→R2邻片→R1同器物→整器物成员恢复”的最新主线，新增Vessel Membership指标、性能—退化曲线、Oracle/Predicted/Corrupted-R2验证、成员GT、整器物UI和竞赛/论文双路线。该更新覆盖了现行正文中仅以“找到一个邻片”为最终目标的旧叙事，但不删除其仍有效的邻片指标；旧Hit/Cov仍作为Level 1核心指标。历史实验数据、旧FAIL/STOP/NOT_*、A12/VesselForge/PG-Frag接口和已冻结数值全部保留，不因最终目标升级而改写。
- ADD body block 945 · paragraph · heading: 历史附录使用说明 · cell paragraphs: —
  - 以下A至F为原实验及工程历史，Q等级、指标、阈值、模型名、资源和判决按当时协议解释，不直接与V1.47的新Level 2/3任务合并。V1.47新增的整器物成员恢复、退化鲁棒性与R2→R1指标只对新冻结实验生效；除非专门复跑并保存新manifest，不能从旧Hit@K或旧pair实验反推Vessel Recall、真实高磨损鲁棒性或UA-IFRMN有效。当前新工作用第4至10章、G/H/I/J；历史附件继续用于重现、审计与保护原始证据。
- REMOVE body block 1 · paragraph · heading:  · cell paragraphs: —
  - V1.47 A12／VesselForge／PG-Frag 收口版 2026年10月7日
- REMOVE body block 2 · paragraph · heading:  · cell paragraphs: —
  - 我们研究低质量部分观测下的碎片邻接候选检索。系统从真实碎片照片出发，在混合碎片库中提出值得人工核验的邻片候选；证据不足时，提出有成本约束的补采建议或停止推荐。比赛交付可运行、可恢复的辅助系统，研究交付能够经独立对照验证的方法机制。
- REMOVE body block 5 · paragraph · heading:  · cell paragraphs: —
  - V1.47（2026年10月7日）为 A12、VesselForge 与 PG-Frag 的实现收口和证据归位版：维持三项目的独立边界，补入本轮实现状态、诊断证据及资格缺口。PG-Frag 当前仅有 virgin elastic 固定裂面 bridge 与未形成断开的开口历史 toy；12 状态中 step_index=0..7 尚非全点损伤（step_index=7 的 D 范围为 2/3–1），只有 step_index=8..11 全点 D=1，但 bulk 仍承载。moving-front 单次运行因审计字段错配在 wrench、KKT、G 之前停止。VesselForge 证据限于解析族、几何候选、条件证明、理想曲线距离和来源审阅；A12 计数仍以软件 QA 与未校准数据为主。本次未新增模型成绩或完整物理合格包；历史指标、FAIL、STOP、NOT_ESTABLISHED 判决和既有导航继续保留。
- REMOVE body block 88 · paragraph · heading: 1 文档体系与现行口径 · cell paragraphs: —
  - 本文件包含总纲、四岗位完整执行正文、软硬件、联调、验收、完整合成实验室、历史附录以及两个独立三维基础设施子项目方案，现行版本统一V1.46。A12给出合成实验编排、预训练与诊断总览；附录G规定A12编排层、退化层、数据与训练流程；附录I规定VesselForge完整方案；附录J规定PG-Frag完整方案；附录H继续保留V1.44问题修订与验收索引。原历史数值、FAIL、STOP和旧协议保留，不能按新口径直接改写。
- REMOVE body block 102 · paragraph · heading: 2 合并主线与边界 · cell paragraphs: —
  - 主问题是给定真实可获得的观测、候选检查预算和误导风险，如何找回邻片并识别观察不足。输入包括整片2D、断口2D和质量信息；合格3D、可信上下文是可选增强。输出包括有序候选、来源可追溯的证据、待核验状态、补采或停止原因。
- REMOVE body block 106 · table · heading: 2.1 比赛必须实现与论文需要证明 · cell paragraphs: 24
  - 能力 比赛系统的内部必做交付 若作为论文主张需要的证据 输入与数据 新样品登记、手机采集、质量检查、真实邻接依据 母体隔离、标签审计和独立确认集 候选链 全库初检、局部精排、证据卡和版本日志 同输入强基线及端到端公平对照 可靠输出 不强迫确定拼合，展示不足、拒识和人工核验 mate-present覆盖与mate-absent风险同时报告 补采 基础版可人工执行建议；自动台列增强交付 等照片和等时间下分别优于强补采基线 主干创新 部署真实验证较好的稳定模型 互补、可观测性或证据重读的可归因机制增益 现场与产品 离线运行、异常恢复、四人交接、真实耗时 工程表现不能代替方法新颖性 用户价值 实测候选检查量与完整任务时间 参与者、任务与对照公开，避免只报列表缩减
- REMOVE body block 110 · table · heading: 2.2 内部指标合同 · cell paragraphs: 33
  - 指标 定义与适用范围 目标或判定方式 any@50 有邻片查询中至少一名真邻片进入初检50池 正常质量内部目标宏值0.95，连同区间报告 Hit@10 前10中至少一名库内真邻片 比赛准备目标正常质量宏值0.90，95%下界0.85 低质Hit@10 日常低质查询对清晰库，独立母体 内部目标0.85，达不到则缩小适用范围 CovRecall@10 前10找回库内真邻片的比例 与Hit单列，不低于冻结强基线 新方法主比较 同查询同库相对验证集选出的强基线 开发起点为增益3个百分点且对象簇CI下界大于0 干净性能守卫 新方法相对同池强基线 下降不超过2个百分点，阈值先冻结 无邻片误导 mate-absent查询被接受推荐的比例 目标不超过5%，95%上界目标不超过10% 有邻片接受覆盖 mate-present中被系统接受输出的比例 目标至少80%，不能靠全拒绝换低风险 现场流程 新查询采集到结果的完整彩排 20次至少19次完成，仅作为彩排目标 工作流价值 包括拍摄、补拍、检查的总任务时间 中位用时减少30%为内部目标，正确性不恶化
- REMOVE body block 447 · paragraph · heading: A12.19 实施输出与研究判断 · cell paragraphs: —
  - A12.19 当前状态（2026-10-07）：本节所列 Release 能力仍是目标接口与验收清单，不代表已完成发布。当前 31 个退化轴、155 个档位/检查组合属于软件 QA；其中 9 个轴有测量记录、36 个非零级别，均来自 1 个母体且未校准。16 个纹样族 ID 尚无经历史样式验证的族，12 个材料 ID 尚无经物理校准的材料。端到端检索收益、真实迁移、真实样本需求下降和规模交付均未建立，完整物理合格包为 0。负责人给出的工程进度估计仍为 PG-Frag 25–35%、VesselForge 30–40%、A12 30–40%；这些比例是工程判断，不代表物理准确度或资格覆盖率。
- REMOVE body block 451 · paragraph · heading: A12.20 双子项目的独立性、非锁定与升级规则 · cell paragraphs: —
  - A12.20 当前实施与资格边界（2026-10-07）：独立仓库、公共合同与可替换后端是架构边界；局部源代码接受或诊断 toy 不等于完整实现或项目资格。PG-Frag 的固定界面与开口控制仍未形成断口分离；moving-front 在合同字段错误处停止。VesselForge 尚无历史器型、生产几何、唇口或实体全局壁厚资格。A12 仍承担观测、权限、关系、训练与诊断编排，不复制两个子项目的内核。
- REMOVE body block 476 · table · heading: B3 必须采到的数据 · cell paragraphs: 27
  - 数据 必须内容 不合格处理 整片 正面、反面、侧壁、轮廓及断口概览 缺面标未观察，补拍或限定用途 断口 实际断裂表面、两侧壁、厚度变化、边缘 没拍到断裂面不能用于局部关系主测试 连续线索 可见纹饰延续、凹槽、曲率变化和薄壁交界 没有该线索如实记，不生成伪纹饰 质量配对 同片清晰、日常和差质量真实观察 不以压缩副本代替独立实拍 重复会话 重新装夹后的身份、时间和参数 新session，不沿用旧位姿 相机与尺度 镜头、分辨率、曝光信息、标定工况、实测比例尺 无尺度仍可2D，关闭毫米几何 关系证据 已确认邻接及难负例、争议记录 UNKNOWN不用于确定性关系评测 失败与成本 模糊图、高光图、重拍、操作及等待时间 不删失败以提高采集成功率
- REMOVE body block 744 · paragraph · heading: D10 用户价值测试与成本 · cell paragraphs: —
  - 比较人工流程、人工加简单候选及人工加新方法证据三种条件。不同难度匹配任务随机交叉分配，避免同一人重复同题记忆优势。记录正确判断耗时、看过候选数、误配漏配、补拍和退出。
- REMOVE body block 804 · paragraph · heading: 10 国赛与CVPR交付计划 · cell paragraphs: —
  - 比赛主交付包括真实新查询流程、原图与GT审计、稳定基线或成立的新方法、风险与不足、补采增强、四人操作、离线恢复、实测价值和明确适用域。自动采集台、3D、RL及CTM不全部列为最低交付。
- REMOVE body block 805 · paragraph · heading: 10 国赛与CVPR交付计划 · cell paragraphs: —
  - 论文主交付包括科学问题、最接近工作、同输入强基线、独立主结果、机制消融、质量与缺失、开放库、成本、失败及复现。METHOD-H1局部互补或METHOD-H3候选条件补采选择证据较强者为核心，架构复杂度不是必要条件。
- REMOVE body block 817 · paragraph · heading: 11 本次归位与历史记录 · cell paragraphs: —
  - V1.47（2026-10-07）收口记录：本次更新实施状态、证据边界与后续资格门，并在不改历史文字、数值或导航的前提下修复缺失的东亚字体映射、A12.17 第 39 表深色表头字色及活动版本页眉/日期页脚；未新增模型成绩或完整物理合格包。moving-front 单次运行因审计字段错配在 wrench/KKT/G 前停止，未重试；objectivity 与 native C4 均为经独立审阅接受的 SOURCE_ONLY；VesselForge 解析/几何证据和 A12 软件 QA 仍未达到生产或物理资格。V1.46 全文及导航保持原样，历史指标、FAIL、STOP 与 NOT_ESTABLISHED 判决不变。备份交付回执固定于 `relicweave-synlab/docs/handover/20261007/BACKUP_DELIVERY_RECEIPT.json`；该后置 sidecar 将记录最终三仓 HEAD 与文件清单，不写入本记录以避免循环引用。
- REMOVE body block 825 · paragraph · heading: 历史附录使用说明 · cell paragraphs: —
  - 以下A至F为原实验及工程历史，Q等级、指标、阈值、模型名、资源和判决按当时协议解释，不直接与V1.45合并。当前新工作用第4至9章、G与H，不恢复归档未定义编号或旧门。
- REMOVE body block 1414 · paragraph · heading: 附录G A12可控合成碎片实验室完整实现方法（双子项目编排层） · cell paragraphs: —
  - G0 当前状态（2026-10-07）：本规则已明确底层内核归属，但当前只是局部实现与来源证据归位，不表示端到端 Asset→Job/Result→Release 链路已完整验收。PG-Frag bridge/opening 是诊断 toy；moving-front 因审计字段错配停止。VesselForge native C4 仅完成 driver/runner 来源审阅，未运行 CAD 或 STEP，也没有实体级 wall/lip 结论。
- REMOVE body block 2190 · paragraph · heading: G22.6 1000片精度与资源基准 · cell paragraphs: —
  - G31.1 V1.47 收口核对（2026-10-07）：本节列出的专项签收项目仍是待完成的资格门。当前 31 轴与 155 项 QA 记录没有替代逐档物理校准；16 个纹样族 ID 没有历史样式验证；原方案所列四个必做碎裂后端、完整三方发布谱系、真实检索对照和规模资源实测仍未整体签收。局部来源审阅、几何证明和诊断运行仅按各自范围记录，不晋级为完整程序或物理资格。
- REMOVE body block 2240 · paragraph · heading: 附录I VesselForge：通用三维器物与纹样生成平台（独立子项目方案） · cell paragraphs: —
  - VesselForge 当前状态（2026-10-07）：已有 bowl/beaker/jar 三个解析参数族、两个默认 CAD 实例，以及局部二维几何候选与理想曲线距离证据；仍有 0 个经历史参考验证的器型族、0 个经资格确认的生产实体和 0 个校准材料/真实纹样外观。最新 native C4 来源审阅为 SOURCE_ACCEPTED，仅接受源代码合同，CAD/STEP 未运行。
- REMOVE body block 2386 · paragraph · heading: 附录J PG-Frag：通用三维物理断裂与碎片生成引擎（独立子项目方案） · cell paragraphs: —
  - PG-Frag 当前状态（2026-10-07）：固定裂面 virgin elastic bridge 与开口历史控制均为诊断 toy，未证明裂纹增长或碎片分离。12 状态轨迹中 step_index=0..7 均非全点损伤；step_index=6 的 D 范围为 0–1，step_index=7 为 2/3–1；仅 step_index=8..11（第 9–12 个状态）全点 D=1。bulk 仍承载，未形成 fragment disconnect。moving-front 唯一获准尝试因 schema 字段错配失败并按单次失败规则停止；没有 wrench、KKT、G 或 primary result。当前证据不构成材料校准、方向/网格偏差收敛、动态多接触或完整三维物理断裂资格。后续算法方向采用连续 MLS 与 support-topology-restricted H/front PU enrichment，停止将 Bool-only 作为主路线；这是基于有限裂片两侧可见支撑集突变和 ghost-jump 反例的工程路线修正，不是已证明的新颖性或物理资格。

## document.xml.rels comparison

### baseline → user

Counts: before=14, after=14, added=0, removed=0, changed=0.
- No relationship ID/type/target/mode changes.

### current → user

Counts: before=14, after=14, added=0, removed=0, changed=0.
- No relationship ID/type/target/mode changes.

## Relationships in all .rels parts

### baseline → user

All relationship declarations: before=19, after=19, added=0, removed=0, changed=0.
- No relationship ID/type/target/mode changes.

### current → user

All relationship declarations: before=19, after=19, added=0, removed=0, changed=0.
- No relationship ID/type/target/mode changes.

## Bookmark identity comparison

### baseline → user

Bookmark starts: before=520, after=520, added=0, removed=0.
- The set of `(part, bookmark ID, bookmark name)` identities is unchanged.

### current → user

Bookmark starts: before=520, after=520, added=0, removed=0.
- The set of `(part, bookmark ID, bookmark name)` identities is unchanged.

## Styles used by changed text blocks

- `Heading2` used in changed blocks (user)
  - user: name='heading 2'; type=paragraph; based_on='Normal'; outline='1'
- `Heading3` used in changed blocks (user)
  - user: name='heading 3'; type=paragraph; based_on='Normal'; outline='2'
- `Normal` used in changed blocks (baseline, current, user)
  - baseline: name='Normal'; type=paragraph; based_on=''; outline=''
  - current: name='Normal'; type=paragraph; based_on=''; outline=''
  - user: name='Normal'; type=paragraph; based_on=''; outline=''
- `SYNBody` used in changed blocks (current, user)
  - current: name='SYN Body'; type=paragraph; based_on='Normal'; outline=''
  - user: name='SYN Body'; type=paragraph; based_on='Normal'; outline=''
- `Subtitle` used in changed blocks (baseline, current, user)
  - baseline: name='Subtitle'; type=paragraph; based_on='Normal'; outline=''
  - current: name='Subtitle'; type=paragraph; based_on='Normal'; outline=''
  - user: name='Subtitle'; type=paragraph; based_on='Normal'; outline=''

### Style definitions baseline → user

Definitions: before=175, after=175, added=[], removed=[], changed=[].
- No style-definition changes.


### Style definitions current → user

Definitions: before=175, after=175, added=[], removed=[], changed=['BodyText', 'BodyText2', 'BodyText2Char', 'BodyText3', 'BodyText3Char', 'BodyTextChar', 'BookTitle', 'Caption', 'DefaultParagraphFont', 'Emphasis', 'Footer', 'FooterChar', 'Header', 'HeaderChar', 'HeaderandFooter', 'Heading', 'Heading1', 'Heading1Char', 'Heading2', 'Heading2Char', 'Heading3', 'Heading3Char', 'Heading4', 'Heading4Char', 'Heading5', 'Heading5Char', 'Heading6', 'Heading6Char', 'Heading7', 'Heading7Char', 'Heading8', 'Heading8Char', 'Heading9', 'Heading9Char', 'Hyperlink', 'Index', 'IndexHeading', 'IntenseEmphasis', 'IntenseQuote', 'IntenseQuoteChar', 'IntenseReference', 'List', 'List2', 'List3', 'ListBullet', 'ListBullet2', 'ListBullet3', 'ListContinue', 'ListContinue2', 'ListContinue3', 'ListNumber', 'ListNumber2', 'ListNumber3', 'ListParagraph', 'MacroText', 'MacroTextChar', 'NoSpacing', 'Normal', 'Quote', 'QuoteChar', 'SYNBody', 'SYNCode', 'SYNReference', 'SYNSection', 'SYNSubsection', 'SYNTable', 'Strong', 'Subtitle', 'SubtitleChar', 'SubtleEmphasis', 'SubtleReference', 'TOCHeading', 'Title', 'TitleChar'].
