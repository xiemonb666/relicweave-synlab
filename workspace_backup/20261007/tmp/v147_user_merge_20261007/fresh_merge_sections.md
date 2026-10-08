# RelicWeave_V1.47.docx
## key=1.3 V1.47 para_index=178 style=Heading2
[177|Normal] 进度报告采用任务状态与证据结论双列：NOT_STARTED、IN_PROGRESS、DONE表示工作状态；SUPPORTED、NOT_ESTABLISHED、NOT_SUPPORTED、STOP表示实验结论。模拟跑通、代码可执行、实物动作成功、任务效果改善和独立研究结论是五种不同成果。
[178|Heading2] 1.3 V1.47信息优先级与历史数据保护规则
[179|] V1.47采用“现行执行正文覆盖过时规划、历史证据只增不改”的双层治理。新的最终目标、比赛叙事和论文方向可以更新现行正文，但不得把历史实验重新解释成已经支持新主张。任何旧结论若与现行任务定义不完全一致，保留原文并标明其适用数据、指标和当时协议；只有新的冻结实验才能产生新的证据结论。
[180|] 信息层
[181|] 主要位置
[182|] V1.47处理规则
[183|] 现行目标与执行口径
## key=2.2.2 para_index=312 style=Heading3
[311|] 手算卡：真邻片B、C，初检仅B且Top10含B，any=1、PoolCov=0.5、Cov=0.5、ConditionalCov=1；不是全邻片找回。另测零正例池、多邻片、|G|<K、自身排除、UNKNOWN和拒识。
[312|Heading3] 2.2.2 器物成员恢复指标、完整分母与退化曲线
[313|] 对query q定义V_G(q)为冻结图库G中与q属于同一器物的全部可评成员，包含R1和R2但排除q自身；预测集合为V_hat(q)。VesselRecall=|V_hat∩V_G|/|V_G|，VesselPrecision=|V_hat∩V_G|/|V_hat|，VesselF1按二者调和平均。只有object membership已闭合、缺失实物去向已记录且UNKNOWN不被强行归类的母体，才进入Level 3主评测。天然残片若无法证明成员全集完整，可报告候选检索和专家工作流，但不能声称完整器物恢复率。
[314|] 退化鲁棒性主实验必须使用paired/counterfactual设计：D0、D1…Dn共享同一母体、关系GT、query、gallery组成和基础随机种子，只改变预注册的磨损、崩缺、缺失、成像或重建退化轴。传统算法、静态学习基线和RelicWeave在相同合法观测权限下比较；不能给传统算法更差输入，也不能让模型读取clean/oracle信息。
[315|Heading2] 2.3 创新收敛与止损
[316|Normal] 第一研究方向METHOD-H1为缺失感知的局部互补审议，第二METHOD-H3为候选条件的带成本补采。一次确认批次只选择一个主要机制比较，CTM、同步、路由与循环均为可替换组件。根据真实开发集及等预算收益选择；确认集只评已经锁定的比较。
[317|Normal] 保留新机制需要回答哪里失败、修改哪里、增益如何归因及哪个对照能否定解释。连续两轮没有可归因进展，保留稳定基线并停止该分支；不能用更多照片、更大模型或更复杂硬件同时变化制造无法解释的提升。
## key=B2.3 para_index=2151 style=Heading2
[2150|] 5  有完整答案的小母体先盲标再核对漏边率和闭合比例。无邻片只由闭合集合移除全部R2构造；未闭合天然残片可做人工辅助，但不能产生确定mate-absent准确率。
[2151|Heading2] B2.3 器物成员集合GT与关系闭合
[2152|] Level 3评测要求每个eligible object拥有member_manifest：object_id、全部已入库fragment_id、已知missing_fragment/碎屑去向、member_set_complete、R2边集合、R1定义域、UNKNOWN/争议关系、复核者、label_version与hash。V_G(q)从该manifest派生，不能从模型结果反推。若某母体只知道若干邻接但不知道是否还有同器物碎片遗失或未入库，则只能参加Level 1/2的限定评测，不能进入完整成员恢复主分母。
[2153|] R1是“同器物且无直接历史断裂接触”，不是“暂时拼不上”。因此member_set闭合和R2关系闭合必须分开审计：先确认哪些fragment属于该object，再确认哪些pair有历史直接接触。R2缺边不能自动把pair改成R1；证据不足保留UNKNOWN。
[2154|Heading1] B3 必须采到的数据
[2155|Normal] 数据
[2156|Normal] 必须内容
## key=A6.14 para_index=1001 style=Heading2
[1000|] CTM分支另注册神经元状态[B,M,Dn]、H=8历史、固定P同步对、历史MLP和同步算子，明确归一化、窗口mask、梯度截断及成本。缺少历史处理或同步就称CTM-inspired；同步无监督一致性不当概率。普通循环、均值历史和等成本模块通过后再放行。
[1001|Heading2] A6.14 2025–2026 近邻任务与跨领域前沿工作增补参考池
[1002|] 本节是 A6 长期创新区的“外部思想增补池”，只记录能够改变本项目问题建模、记忆结构、关系推理、验证方式或实验设计的机制。所有条目均作为 RESEARCH_REFERENCE，不代表已经适用于 RelicWeave，更不代表已经验证有效。采用顺序固定为：先复现／理解原机制 → 映射到本项目的错误模式 → 提出最小可否定假设 → 单独消融 → 只有真实低质量与独立母体上成立后才允许进入主线。
[1003|] 参考工作
[1004|] 原工作关键机制
[1005|] 对 RelicWeave 的可借鉴点与价值
[1006|] 明确不直接照搬的边界
## key=A6.15 para_index=1072 style=Heading2
[1071|] 增补参考池的统一结论不是“把这些模型都接起来”，而是抽取五条可测试的设计原则：① 关系预测必须可验证、可撤销，不能 hard commit；② R2 的局部接触证据与 R1 的器物身份证据需要不同记忆和不同读写策略；③ pairwise 结果只能作为多轮／多碎片联合推理的 prior；④ 一块碎片应保留局部 token 集合和 provenance，而不是被压成单一全局向量；⑤ 迭代反馈应优先反馈连续 latent relation state 与不确定性，而不是只反馈一个概率标量。
[1072|Heading2] A6.15 新核心候选：Uncertainty-Aware Iterative Fragment Relational Memory Network（UA-IFRMN）
[1073|] 中文暂定名：不确定性感知的迭代碎片关系记忆网络。它不是当前稳定主干的替代品，而是登记在长期创新区的 P0 研究候选。其目标是把原本一次性的 pairwise R0/R1/R2 打分，改造成“局部邻接发现 → 软关系写入 → 多跳同器物扩展 → 新证据联合重读 → 旧关系可修正”的迭代关系推理过程。
[1074|] 核心科学问题：在真实低质量、断口缺失、纹样不完整和 3D 不稳定的条件下，模型能否利用已经发现的高置信直接历史邻接 R2，构建带不确定性的关系上下文，从而提高同器物但非直接邻接 R1 的检索，同时避免错误 R2 被循环放大为器物级错误？
[1075|] 这里的“自回归”只保留“上一轮内部结果会影响下一轮推理”这一抽象，不采用离散单路径 hard autoregression。更准确的机制名称为 Contact-Conditioned Identity Expansion + Reversible Relational Memory：直接接触证据先形成局部 relation latent，再作为同器物身份扩展的条件；所有写入都带 posterior、quality、provenance 和 revision 权限。
[1076|] 组成
[1077|] 建议定义
## key=A6.15 para_index=1097 style=Heading3
[1096|] 保证“State != Evidence”；当关系被质疑时可以回到原始证据，而不是只在已经被模型过滤过的 hidden state 上自证。
[1097|Heading3] A6.15.1 UA-IFRMN 的一次完整推理循环
[1098|] Step 0 — 编码而不压扁：对 query 和候选库生成 Fragment Token Bank；静态 encoder 可沿用现有成熟主干，先不改变 backbone。
[1099|] Step 1 — 双路粗检：同时产生高召回 same-vessel shortlist 与 R2 contact shortlist。前者防止“只沿邻片链才能发现远端碎片”，后者为关系扩展提供局部结构 seed。
[1100|] Step 2 — 形成 Soft R2 edges：relation head 输出 R0/R1/R2/UNKNOWN posterior 与 relation latent；3D 可用时再通过几何互补／接触 verifier 产生额外证据，但 verifier 不直接覆盖网络 posterior。
[1101|] Step 3 — 不确定性感知写入：只有满足质量和可比较条件的证据才进入 M_R2；其写入是 soft 的，保存 posterior、置信区间／校准量、source 与时间版本，不做不可逆 hard merge。
[1102|] Step 4 — Contact-Conditioned Identity Expansion：以高置信 R2 seed 或局部组件为起点，在 G_t 上做多跳候选扩展；扩展只提高 same-vessel prior，不直接把多跳终点标成 R1 或 R2。
## key=A6.16 para_index=1106 style=Heading2
[1105|] Step 7 — 动态停止或继续：当 Top-K、typed relation graph 与 vessel latent 连续多轮稳定且证据预算已足够时停止；若仍冲突则继续读 Evidence Bank，或输出 UNKNOWN / 补采建议。
[1106|Heading2] A6.16 从 R2 到 R1 的关系代数：允许“身份传播”，禁止“邻接传播”
[1107|] UA-IFRMN 必须显式尊重现行标签定义：R2 是原碎裂事件当前叶子片间的直接历史邻接，R1 是同器物但无直接历史断裂接触。因此，A—B 为 R2、B—C 为 R2，并不能推出 A—C 为 R2；它只能为 “A 与 C 属于同一器物” 提供强结构证据。最终 A—C 是 R1、R2 还是 UNKNOWN，仍要由直接接触证据和历史邻接真值判定。
[1108|] 关系组合
[1109|] 允许的推理
[1110|] 设计意义
[1111|] R2(A,B) + R2(B,C)
## key=A6.17 para_index=1127 style=Heading2
[1126|] 研究实现上建议把 same-vessel 与 direct-contact 解耦成两个相关但不同的头：P_same(i,j) 表示器物身份兼容，P_R2(i,j) 表示直接历史邻接；随后由 typed relation head 在 R0/R1/R2/UNKNOWN 上给出最终分布。这样多跳图只影响 P_same 或 vessel compatibility，不会错误地让 R2 具备传递性。
[1127|Heading2] A6.17 为什么不能只把“邻片概率”喂回去：Scalar Feedback、Latent Feedback 与多假设记忆
[1128|] 用户提出的原始思路“预测邻片后，把邻片预测作为下一轮输入，再判断同器物非邻片”应保留为最小基线，但正式候选必须把“反馈什么”做成分层实验。单一 P(R2) 只表达最终置信度，不包含模型是依据断口、几何、纹样还是质量得出的结论，也无法区分“高分但证据冲突”和“高分且多证据一致”。
[1129|] 反馈层级
[1130|] 输入下一轮的内容
[1131|] 研究价值
[1132|] 主要风险
## key=A6.18 para_index=1154 style=Heading2
[1153|] 因此推荐研究顺序固定为 B1 → B2 → B3 → B4/B5。只有 B2 在同输入、同候选池、相近 FLOPs 下显著优于 B1，才能说明“连续 relation latent”本身具有价值；否则不允许仅因为结构更复杂而升级主干。
[1154|Heading2] A6.18 双记忆与器物潜变量：R2 Local Memory × Vessel Identity Memory
[1155|] R2 与 R1 的核心证据分布不同。R2 更依赖断口局部互补、接触几何、局部纹理连续；R1 可能没有任何直接接触，反而依赖材质、壁厚、器形曲率、纹样体系、制造痕迹以及当前已恢复器物的整体先验。因此不建议让同一个 memory slot 同时承担两类关系。
[1156|] 记忆层
[1157|] 保存内容
[1158|] 主要服务目标
[1159|] 主要思想来源
## key=A6.19 para_index=1173 style=Heading2
[1172|] Vessel Memory 不等于“把所有已接受碎片做平均池化”。建议至少比较：mean pooling、attention pooling、slot-based memory、set transformer／Perceiver-style query，以及带 missing slots 的 vessel token。任何复杂版本都必须对照简单 pooling，防止“多参数 = 更好”的假象。
[1173|Heading2] A6.19 错误传播控制：Predict → Verify → Soft Write → Reread → Revise
[1174|] 这条创新线最大的风险不是“能不能利用正确 R2”，而是“错误 R2 会不会污染后续 R1”。因此误差传播本身必须成为论文级评测对象，而不是部署阶段再修。SARe 的 many-fragment cascading failure、MV-RoMa 的 pairwise chaining inconsistency 以及本项目既有反自证规则共同要求：任何关系写入都必须可撤销、可追溯、可重新验证。
[1175|] 控制机制
[1176|] 实施约束
[1177|] 目的
[1178|] Soft Write
## key=A6.20 para_index=1199 style=Heading2
[1198|] 错误控制优先于强迫形成完整关系图。
[1199|Heading2] A6.20 训练路线：Oracle 关系上限 → 预测关系闭环 → 人工腐化鲁棒性
[1200|] 训练不得从一开始就把完整 UA-IFRMN 端到端同时打开。否则任何增益都无法判断来自“R2 上下文真的有用”、更大模型、更大计算还是标签泄漏。建议按下面顺序建立证据。
[1201|] 阶段
[1202|] 训练／输入设置
[1203|] 必须回答的问题
[1204|] T0 Pairwise baseline
## key=A6.20 para_index=1229 style=Heading3
[1228|] A12 可控合成碎片实验室应为本路线生成专门 episode，而不是只增加总样本量：同一母体生成完整 R2 图与 R1 集合；然后分别制造 0%、5%、10%、20%、30% 错边，或只破坏一个关系证据轴，形成严格配对的 corruption ladder。真实数据必须保留独立母体确认集，合成数据只能用于预训练、机制压力测试和错误模式覆盖，不能代替真实成立证据。
[1229|Heading3] A6.20.1 候选损失项：先作为可拆卸假设，不一次全部启用
[1230|] 可维护以下损失池：L_same（同器物 membership）、L_R2（直接历史邻接）、L_contact（可比较条件下的接触／互补）、L_rank（候选排序）、L_comp（relation composition 一致性）、L_calib（posterior 校准）、L_revision（错误边被新证据推翻时的修正监督）、L_memory（vessel/local memory 一致性）以及可选 L_distill（TORA-like relation structure distillation）。任何一次正式消融只允许新增一个主要损失项，并报告其对 R1、R2、误导风险和计算的独立影响。
[1231|] 一个重要约束是：L_comp 只鼓励 R2 路径提高 same-vessel belief，不允许把 R2 传递为 R2。即使 A-B 与 B-C 都是 R2，也不能把 A-C 直接监督为 R2；A-C 的直接邻接标签仍由历史真值单独决定。
[1232|Heading2] A6.21 必做实验矩阵：先证明“邻片上下文有信息”，再证明“新机制能安全利用它”
[1233|] 实验
[1234|] 最低对照
## key=A6.21 para_index=1232 style=Heading2
[1231|] 一个重要约束是：L_comp 只鼓励 R2 路径提高 same-vessel belief，不允许把 R2 传递为 R2。即使 A-B 与 B-C 都是 R2，也不能把 A-C 直接监督为 R2；A-C 的直接邻接标签仍由历史真值单独决定。
[1232|Heading2] A6.21 必做实验矩阵：先证明“邻片上下文有信息”，再证明“新机制能安全利用它”
[1233|] 实验
[1234|] 最低对照
[1235|] 核心观测
[1236|] 否定／进入条件
[1237|] Oracle-R2 上限实验
## key=A6.24 para_index=1356 style=Heading2
[1355|] IDEA
[1356|Heading2] A6.24 本次增补的外部来源与复现优先级
[1357|] 来源分为两类：会议／期刊正式论文用于建立强对照，2026 年预印本用于跟踪最新方向。预印本在正式投稿前必须再次核验版本、发表状态和结论；不得把预印本结果写成社区共识。建议优先阅读／复现顺序为：SARe → PuzzleFusion++ → GARF → Combinative Matching / Rectified Point Flow → MHopReg → Jigsaw++ / Beyond Reassembly → Bag of Bags → Coconut / VisMem / WorldMM / Titans → TORA / MV-RoMa。
[1358|] 1. Jia et al. SARe: Structure-Aware Large-Scale 3D Fragment Reassembly. arXiv:2603.21611, 2026.
[1359|] 2. Wang, Chen, Furukawa. PuzzleFusion++: Auto-agglomerative 3D Fracture Assembly by Denoise and Verify. ICLR 2025.
[1360|] 3. Li et al. GARF: Learning Generalizable 3D Reassembly for Real-World Fractures. ICCV 2025.
[1361|] 4. Sun et al. Rectified Point Flow: Generic Point Cloud Pose Estimation. NeurIPS 2025 Spotlight; arXiv:2506.05282.
## key=EXP12 para_index=1507 style=Heading2
[1506|] 只使用member set闭合的母体。给定单个query，系统从空或最小seed开始迭代检索，输出R2、R1和最终V_hat(q)。比较pairwise retrieval、简单聚类/metric learning、set/graph baseline、静态vessel prototype和UA-IFRMN候选。报告Vessel Precision/Recall/F1、完整找回率、首个错误成员进入轮次、迭代次数、查询墙钟和专家需要核验的候选数。不同器物成员数、图库规模、材质和器型分层。
[1507|Heading2] EXP12 R2→R1关系上下文与错误传播
[1508|] 第一步Oracle-R2：只替换关系上下文，不改视觉输入，验证真实邻接上下文能否提升R1/same-vessel；第二步Predicted-R2：换成模型预测并保留posterior、quality与relation latent；第三步Corrupted-R2：按0/5/10/20/30%注入错边、漏边和不完整memory。比较Scalar Feedback、Latent Feedback、Neighbor Set、Soft Graph、Vessel Memory与Reversible Memory。若Oracle无增益则暂停；若预测闭环增益只在无错边成立，则不能进入部署。
[1509|Heading1] A9 结果归档与常见失败处理
[1510|Normal] 每次运行交付spec、data及split manifest、环境、config、权重、逐查询预测、母体指标、配对区间、成本、失败清单和hash_manifest。报告写清数据范围、最强可部署对照、主比较、限制及下一动作。
[1511|Heading2] A9.1 指标手算与失败标签
[1512|Normal] 手算例：查询Q有库内真邻片B和C，初检池只保留B，Top10未含B，则any@M为1、Hit@10为0、CovRecall@10为0；主失败为池内错排，次因是部分邻片池外。若Top10含B，则Hit为1、CovRecall为0.5，不能写全部邻片已找回。若B和C均池外，则主失败为全部池外。
## key=EXP12 para_index=3365 style=
[3364|Heading2] 10.2 论文方向：一套数据底座，多条可独立收敛的研究问题
[3365|] 优先顺序由实验决定而不是由想法“看起来高级”决定。先跑EXP10退化曲线和EXP11整器物任务，确认问题本身有足够难度和方法空间；再用EXP12判断R2上下文是否真的给R1带来信息。若Oracle-R2上限明显、Predicted-R2能在错边下保持收益，则UA-IFRMN可升级为方法主线；若关系机制不成立，但A12的物理退化预训练在真实域稳定增益，则把Synthetic-to-Real转为主线。
[3366|] 顶会目标不要求一次把比赛系统所有模块写进论文。最强版本应围绕一个可以被其他视觉任务理解的问题：高退化partial observation、typed relational reasoning、set membership recovery或physics-guided sim-to-real。数据、代码、协议、强基线和负结果比系统模块数量更重要。
[3367|Heading2] 10.3 竞赛与论文共享的证据底座，但结论严格分开
[3368|] 两条路线共享真实数据身份、member/neighbor GT、冻结split、退化压力测试、传统/学习基线和工作流日志。比赛可以强调专家减负、社会价值、可操作性与系统完整；论文只能强调被独立实验支持的方法/任务贡献。比赛演示成功不等于论文创新成立，论文模型增益也不自动证明真实工作流节时。
[3369|Heading1] 11 本次归位与历史记录
[3370|Normal] 原V1.30章节
## key=A12.21 para_index=2088 style=Heading2
[2087|] VesselForge和PG-Frag必须各自拥有独立仓库、版本号、CI、单元测试、Benchmark、CLI/Python API与插件注册表；RelicWeave只是当前上层调用方之一。公共API使用能力接口而不是算法名，例如simulate(..., backend=...)，资产/结果Schema不得暴露某个库的私有对象。第三方只要满足Asset Contract即可直接接入PG-Frag；VesselForge生成的资产也可直接输出给CAD/CAE、渲染、数字孪生或其他数据平台。Stable后端用于默认生产，Candidate完成基本验证，Experimental仅用于前沿探索；新后端必须经过许可证、复现、正确性、维护状态、隔离、可观测和显式失败验收后才能晋级。
[2088|Heading2] A12.21 V1.47退化性能曲线：把SyntheticLab变成“物理退化压力测试仪”
[2089|] A12新增一类paired counterfactual release：同一clean母体、同一碎片关系、同一query/gallery与基础随机种子，沿磨损、崩缺、表面侵蚀、遮挡、图像质量、3D缺失/增生噪点等单轴或预注册组合轴生成D0→Dn观测。每个release必须同时提供传统算法合法输入、学习模型合法输入和TruthPack，但TruthPack只供评测。输出不仅是某一档准确率，而是每个方法的性能—退化强度曲线、临界失效点、AUC/斜率型诊断和真实域对应样本。
[2090|Heading2] A12.22 Whole-Vessel Episode Generator：为整器物成员恢复生成完整关系世界
[2091|] 每个合成母体除R2边外，还必须导出完整member set、R1/R2 typed relation graph、可见/不可见断面、缺失材料和母体级属性。episode生成器把多个母体混成gallery，随机选择query并控制同器物成员数、R1/R2比例、hard negative密度、器型相似度、材质相似度和退化分布；训练端只看合法Obs，评测端用完整Truth计算Vessel Precision/Recall/F1及多轮扩展轨迹。这样A12的数据价值从“更多pair”升级为“可控整器物关系规模”。
[2092|Heading2] A12.23 Synthetic-to-Real与数据充分性：最终只以真实域收益决定扩容
[2093|] 合成预训练的正式价值判断改为三条：①在相同真实标注量下是否提高真实高退化R2/R1与Vessel指标；②达到同一真实目标性能所需的真实母体/碎片量是否下降；③跨相机、材料、器型或自然风化域是否更稳。若10万/50万合成碎片不能在这些真实指标上带来收益，则停止扩容并审计生成分布、shortcut和任务错位，不用合成规模本身作为成果。
## key=D6.5 para_index=2947 style=Heading2
[2946|Normal] 比赛强调新查询、真实动作、真实新增观察和结果更新。回放模式有持续可见标记及原始运行时间；mock模式有明显标记且不进入比赛真实主表。界面不预写正确候选，也不把GT送给动作策略。
[2947|Heading2] D6.5 器物成员恢复页（V1.47新增）
[2948|] 结果页采用“三层视图”而不是把所有候选混在一个Top-K：第一栏Direct Neighbor Candidates只显示R2及局部接触证据；第二栏Same-Vessel Candidates显示R1/R2同器物成员及器物身份支持；第三栏Predicted Vessel Set显示当前已纳入成员、待核验成员、被驳回成员、UNKNOWN、Vessel Precision/Recall仅在有GT的评测模式显示。用户接受/驳回某成员后生成新的revision，系统可以重新检索全库并显示“新增成员导致哪些旧关系被加强、削弱或撤回”。
[2949|] 比赛演示默认从一块新query开始：采集/导入→全库粗检→R2邻片→形成初始Vessel Memory→发现R1远距离成员→人工核验→成员集更新或停止。若当前模型尚未通过Level 3验证，界面必须标“研究模式/成员候选”，不得把候选集合称为已恢复器物。
[2950|Heading1] D7 首版与后续版本路线
[2951|Normal] 版本
[2952|Normal] 必须实现
# RelicWeave_V1.47_A12_VesselForge_PGFrag_Closeout.docx