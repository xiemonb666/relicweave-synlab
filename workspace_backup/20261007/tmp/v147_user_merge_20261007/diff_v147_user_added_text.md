## BASELINE→USER

### (no heading)

- block 5 · paragraph · body

```text
V1.47在V1.46双子基础设施版本上统一最新项目主线：将长期最终目标从“找一名邻片”明确升级为“Fragment-to-Vessel Retrieval / Vessel Membership Recovery”，新增高磨损与风化证据下的鲁棒检索主线、传统算法与学习方法的公平退化对照、R2局部接触到R1器物身份扩展、整器物成员级指标、比赛价值验证与CVPR级研究收敛路线。VesselForge、PG-Frag与A12的职责边界保持不变；A12增加对退化性能曲线、完整器物关系episode和Synthetic-to-Real的专门支撑。所有历史实验数值、FAIL、STOP、NOT_SUPPORTED、NOT_ESTABLISHED与冻结协议继续原样保护；本版只更新现行目标、研究候选、实验合同、数据GT、产品展示和交付口径，不用新叙事改写旧结果。
```

### 1.3 V1.47信息优先级与历史数据保护规则

- block 184 · paragraph · body

```text
1.3 V1.47信息优先级与历史数据保护规则
```

- block 185 · paragraph · body

```text
V1.47采用“现行执行正文覆盖过时规划、历史证据只增不改”的双层治理。新的最终目标、比赛叙事和论文方向可以更新现行正文，但不得把历史实验重新解释成已经支持新主张。任何旧结论若与现行任务定义不完全一致，保留原文并标明其适用数据、指标和当时协议；只有新的冻结实验才能产生新的证据结论。
```

- block 187 · table_cell_paragraph · body/table4/row1/cell1

```text
信息层
```

- block 188 · table_cell_paragraph · body/table4/row1/cell2

```text
主要位置
```

- block 189 · table_cell_paragraph · body/table4/row1/cell3

```text
V1.47处理规则
```

- block 190 · table_cell_paragraph · body/table4/row2/cell1

```text
现行目标与执行口径
```

- block 191 · table_cell_paragraph · body/table4/row2/cell2

```text
总纲第1–10章、A1–A12及B/C/D执行正文
```

- block 192 · table_cell_paragraph · body/table4/row2/cell3

```text
允许更新；V1.47优先，用于现在做什么、为什么做、如何验收。
```

- block 193 · table_cell_paragraph · body/table4/row3/cell1

```text
长期科研候选
```

- block 194 · table_cell_paragraph · body/table4/row3/cell2

```text
A6创新维护区、A12研究支线
```

- block 195 · table_cell_paragraph · body/table4/row3/cell3

```text
允许追加、降级、停止；RESEARCH_CANDIDATE不等于已实现或已证明。
```

- block 196 · table_cell_paragraph · body/table4/row4/cell1

```text
冻结实验数据
```

- block 197 · table_cell_paragraph · body/table4/row4/cell2

```text
附录A/B/C及正文引用的历史数值、hash、FAIL/STOP/NOT_*
```

- block 198 · table_cell_paragraph · body/table4/row4/cell3

```text
只允许补充来源、解释边界和新复算记录；禁止删除、润色或用新口径覆盖旧数值。
```

- block 199 · table_cell_paragraph · body/table4/row5/cell1

```text
旧规划与旧默认值
```

- block 200 · table_cell_paragraph · body/table4/row5/cell2

```text
历史附录中的旧设备、排期、岗位、下一步建议
```

- block 201 · table_cell_paragraph · body/table4/row5/cell3

```text
不再指导现行执行；为可追溯性保留，不与V1.47现行口径并列使用。
```

- block 202 · table_cell_paragraph · body/table4/row6/cell1

```text
新任务扩展
```

- block 203 · table_cell_paragraph · body/table4/row6/cell2

```text
整器物成员恢复、高退化鲁棒检索、R2→R1关系推理
```

- block 204 · table_cell_paragraph · body/table4/row6/cell3

```text
从V1.47起生效；除非专门复跑，不能反向声称旧实验已经验证这些目标。
```

### 2.0 最新统一任务定义：从邻片检索到整器物成员恢复

- block 210 · paragraph · body

```text
2.0 最新统一任务定义：从邻片检索到整器物成员恢复
```

- block 211 · paragraph · body

```text
长期最终目标不是“自动把文物粘好”，而是把专家面对的组合搜索问题分成三个可验证层级：先找直接邻片，再找同器物非邻片，最后从任意一片出发恢复数据库范围内的器物成员集合。Level 3只承诺“数据库中已存在碎片的成员恢复”，不等价于几何全自动装配、缺失部分生成或物理修复。
```

- block 213 · table_cell_paragraph · body/table5/row1/cell1

```text
任务层级
```

- block 214 · table_cell_paragraph · body/table5/row1/cell2

```text
输入→输出
```

- block 215 · table_cell_paragraph · body/table5/row1/cell3

```text
主要证据/机制
```

- block 216 · table_cell_paragraph · body/table5/row1/cell4

```text
核心评价
```

- block 217 · table_cell_paragraph · body/table5/row2/cell1

```text
Level 1：R2 Neighbor Retrieval
```

- block 218 · table_cell_paragraph · body/table5/row2/cell2

```text
q + G → 直接历史邻片候选
```

- block 219 · table_cell_paragraph · body/table5/row2/cell3

```text
断口、局部2D/3D、几何互补、接触证据
```

- block 220 · table_cell_paragraph · body/table5/row2/cell4

```text
any@M、Hit@K、CovRecall@K、误导/拒识
```

- block 221 · table_cell_paragraph · body/table5/row3/cell1

```text
Level 2：Same-Vessel Retrieval
```

- block 222 · table_cell_paragraph · body/table5/row3/cell2

```text
q + G → R1 + R2同器物候选
```

- block 223 · table_cell_paragraph · body/table5/row3/cell3

```text
材质、纹样、壁厚、曲率、器型先验、R2上下文
```

- block 224 · table_cell_paragraph · body/table5/row3/cell4

```text
SameVessel Hit@K、Precision/Recall、R1专门召回
```

- block 225 · table_cell_paragraph · body/table5/row4/cell1

```text
Level 3：Vessel Membership Recovery
```

- block 226 · table_cell_paragraph · body/table5/row4/cell2

```text
q + G → 预测成员集合 V_hat(q)
```

- block 227 · table_cell_paragraph · body/table5/row4/cell3

```text
UA-IFRMN关系记忆、Vessel Memory、多轮重检索与可修正关系图
```

- block 228 · table_cell_paragraph · body/table5/row4/cell4

```text
Vessel Recall、Vessel Precision、Vessel F1、误纳入率、迭代成本
```

- block 230 · paragraph · body

```text
统一终态：系统接收任意查询碎片后，先输出“Direct Neighbor Candidates（R2）”和“Same-Vessel Candidates（R1/R2）”，再形成“Predicted Vessel Set”，并在新成员加入后重新读取整个器物假设；当新增证据不足、风险过高或预算耗尽时停止，而不是为了追求找全强行扩展。
```

### 2.1 比赛必须实现与论文需要证明

- block 257 · table_cell_paragraph · body/table6/row9/cell1

```text
高磨损/风化鲁棒性
```

- block 258 · table_cell_paragraph · body/table6/row9/cell2

```text
至少展示清晰、轻度退化、严重退化三档真实或受控样本；同输入比较传统几何基线、简单AI基线与RelicWeave，展示何时传统精确匹配假设开始失效。
```

- block 259 · table_cell_paragraph · body/table6/row9/cell3

```text
冻结退化轴与配对样本，给出性能—退化强度曲线、置信区间、真实域确认和跨设备/材料守卫；不能只挑极端失败样本。
```

- block 260 · table_cell_paragraph · body/table6/row10/cell1

```text
整器物成员恢复
```

- block 261 · table_cell_paragraph · body/table6/row10/cell2

```text
给定一块碎片，界面同时输出R2邻片、R1同器物候选和器物成员集合；人工可逐项接受/驳回，系统更新成员集且保留版本历史。
```

- block 262 · table_cell_paragraph · body/table6/row10/cell3

```text
正式定义Fragment-to-Vessel Membership Recovery任务，建立Vessel Precision/Recall/F1、完整成员覆盖、错误成员注入和迭代成本基线。
```

- block 263 · table_cell_paragraph · body/table6/row11/cell1

```text
AI必要性证据
```

- block 264 · table_cell_paragraph · body/table6/row11/cell2

```text
不宣称所有样本都必须用AI；清晰小规模样本允许传统方法胜出。比赛重点证明在大库、退化、弱对应、R1无直接断口场景下，AI显著减少专家筛查。
```

- block 265 · table_cell_paragraph · body/table6/row11/cell3

```text
公平比较ICP/局部描述子/曲率/轮廓等传统方法、静态深度模型和关系模型；主张限定为“在哪些条件下学习方法产生额外价值”。
```

### 2.2 内部指标合同

- block 304 · table_cell_paragraph · body/table7/row12/cell1

```text
Vessel Recall
```

- block 305 · table_cell_paragraph · body/table7/row12/cell2

```text
预测器物成员集合中找回数据库内真实同器物成员的比例；分母为冻结且闭合的V_G(q)。
```

- block 306 · table_cell_paragraph · body/table7/row12/cell3

```text
长期核心目标；按母体等权宏平均，并报告成员数分层。
```

- block 307 · table_cell_paragraph · body/table7/row13/cell1

```text
Vessel Precision
```

- block 308 · table_cell_paragraph · body/table7/row13/cell2

```text
预测成员集合中真实同器物成员的比例。
```

- block 309 · table_cell_paragraph · body/table7/row13/cell3

```text
防止“把整个库都收进来”换高Recall；与Recall同时冻结阈值。
```

- block 310 · table_cell_paragraph · body/table7/row14/cell1

```text
Vessel F1
```

- block 311 · table_cell_paragraph · body/table7/row14/cell2

```text
Vessel Precision与Vessel Recall的调和平均。
```

- block 312 · table_cell_paragraph · body/table7/row14/cell3

```text
用于集合恢复单值摘要，不替代Precision/Recall与风险曲线。
```

- block 313 · table_cell_paragraph · body/table7/row15/cell1

```text
Degradation Robustness Curve
```

- block 314 · table_cell_paragraph · body/table7/row15/cell2

```text
同一底层query/gallery/GT在D0→Dn退化强度下的主指标轨迹。
```

- block 315 · table_cell_paragraph · body/table7/row15/cell3

```text
比较传统算法、静态AI和RelicWeave的性能下降速度；真实退化另单列确认。
```

- block 316 · table_cell_paragraph · body/table7/row16/cell1

```text
R2→R1 Context Gain
```

- block 317 · table_cell_paragraph · body/table7/row16/cell2

```text
同一输入下，加入GT/预测R2上下文前后R1或same-vessel指标差值。
```

- block 318 · table_cell_paragraph · body/table7/row16/cell3

```text
先做Oracle-R2上限，再做Predicted-R2与Corrupted-R2；若Oracle也无增益则暂停该机制。
```

### 2.2.2 器物成员恢复指标、完整分母与退化曲线

- block 326 · paragraph · body

```text
2.2.2 器物成员恢复指标、完整分母与退化曲线
```

- block 327 · paragraph · body

```text
对query q定义V_G(q)为冻结图库G中与q属于同一器物的全部可评成员，包含R1和R2但排除q自身；预测集合为V_hat(q)。VesselRecall=|V_hat∩V_G|/|V_G|，VesselPrecision=|V_hat∩V_G|/|V_hat|，VesselF1按二者调和平均。只有object membership已闭合、缺失实物去向已记录且UNKNOWN不被强行归类的母体，才进入Level 3主评测。天然残片若无法证明成员全集完整，可报告候选检索和专家工作流，但不能声称完整器物恢复率。
```

- block 328 · paragraph · body

```text
退化鲁棒性主实验必须使用paired/counterfactual设计：D0、D1…Dn共享同一母体、关系GT、query、gallery组成和基础随机种子，只改变预注册的磨损、崩缺、缺失、成像或重建退化轴。传统算法、静态学习基线和RelicWeave在相同合法观测权限下比较；不能给传统算法更差输入，也不能让模型读取clean/oracle信息。
```

### 2.4 痛点、应用价值与“为什么需要AI”的边界

- block 333 · paragraph · body

```text
2.4 痛点、应用价值与“为什么需要AI”的边界
```

- block 334 · paragraph · body

```text
V1.47不再用“AI比传统算法先进”作为价值论证。项目的真实痛点是：当碎片数量大、来源混杂、断口被长期风化磨损、局部对应缺失、R1本来就没有直接接触面时，专家需要在巨大的组合空间中反复筛查；传统几何方法在清晰且对应充分的样本上仍然是强基线，但其精确匹配假设在高退化和弱对应条件下可能失效。RelicWeave的目标是把机器用于海量筛选、弱证据融合、排序、不确定性与关系推理，把专家从“搜索者”转为“验证者”，而不是取消专家的最终判断。
```

- block 336 · table_cell_paragraph · body/table8/row1/cell1

```text
场景
```

- block 337 · table_cell_paragraph · body/table8/row1/cell2

```text
传统/人工方案
```

- block 338 · table_cell_paragraph · body/table8/row1/cell3

```text
RelicWeave应增加的能力
```

- block 339 · table_cell_paragraph · body/table8/row1/cell4

```text
可验证价值
```

- block 340 · table_cell_paragraph · body/table8/row2/cell1

```text
小规模、清晰、断口完整
```

- block 341 · table_cell_paragraph · body/table8/row2/cell2

```text
人工/ICP/曲率/局部描述子可能已足够
```

- block 342 · table_cell_paragraph · body/table8/row2/cell3

```text
AI不是必须；作为强基线和成本下限
```

- block 343 · table_cell_paragraph · body/table8/row2/cell4

```text
证明项目没有“为了AI而AI”
```

- block 344 · table_cell_paragraph · body/table8/row3/cell1

```text
大规模混合碎片库
```

- block 345 · table_cell_paragraph · body/table8/row3/cell2

```text
人工组合搜索随库规模快速变难
```

- block 346 · table_cell_paragraph · body/table8/row3/cell3

```text
向量检索+学习排序缩小候选空间
```

- block 347 · table_cell_paragraph · body/table8/row3/cell4

```text
减少专家浏览、比较与实物搬动
```

- block 348 · table_cell_paragraph · body/table8/row4/cell1

```text
高磨损/崩缺/风化
```

- block 349 · table_cell_paragraph · body/table8/row4/cell2

```text
精确几何对应和手工描述子受损
```

- block 350 · table_cell_paragraph · body/table8/row4/cell3

```text
多模态表征+不确定性+退化训练
```

- block 351 · table_cell_paragraph · body/table8/row4/cell4

```text
在证据残缺时保持更平缓的性能退化
```

- block 352 · table_cell_paragraph · body/table8/row5/cell1

```text
R1同器物非邻接
```

- block 353 · table_cell_paragraph · body/table8/row5/cell2

```text
断口没有直接对应，局部几何无法单独判断
```

- block 354 · table_cell_paragraph · body/table8/row5/cell3

```text
Vessel Memory+关系图+多跳身份推理
```

- block 355 · table_cell_paragraph · body/table8/row5/cell4

```text
从“找邻片”扩展到“找同器物成员”
```

- block 356 · table_cell_paragraph · body/table8/row6/cell1

```text
证据不足/高风险样本
```

- block 357 · table_cell_paragraph · body/table8/row6/cell2

```text
强行匹配会增加误导与不必要试拼
```

- block 358 · table_cell_paragraph · body/table8/row6/cell3

```text
校准、拒识、主动补采
```

- block 359 · table_cell_paragraph · body/table8/row6/cell4

```text
降低错误候选和脆弱实物反复操作
```

### A6.14 2025–2026 近邻任务与跨领域前沿工作增补参考池

- block 1051 · paragraph · body

```text
A6.14 2025–2026 近邻任务与跨领域前沿工作增补参考池
```

- block 1052 · paragraph · body

```text
本节是 A6 长期创新区的“外部思想增补池”，只记录能够改变本项目问题建模、记忆结构、关系推理、验证方式或实验设计的机制。所有条目均作为 RESEARCH_REFERENCE，不代表已经适用于 RelicWeave，更不代表已经验证有效。采用顺序固定为：先复现／理解原机制 → 映射到本项目的错误模式 → 提出最小可否定假设 → 单独消融 → 只有真实低质量与独立母体上成立后才允许进入主线。
```

- block 1054 · table_cell_paragraph · body/table26/row1/cell1

```text
参考工作
```

- block 1055 · table_cell_paragraph · body/table26/row1/cell2

```text
原工作关键机制
```

- block 1056 · table_cell_paragraph · body/table26/row1/cell3

```text
对 RelicWeave 的可借鉴点与价值
```

- block 1057 · table_cell_paragraph · body/table26/row1/cell4

```text
明确不直接照搬的边界
```

- block 1058 · table_cell_paragraph · body/table26/row2/cell1

```text
SARe: Structure-Aware Large-Scale 3D Fragment Reassembly（2026，arXiv:2603.21611）
```

- block 1059 · table_cell_paragraph · body/table26/row2/cell2

```text
联合预测 fracture-surface token probability 与 inter-fragment contact graph；推理期用几何一致性验证候选接触边，只固定可靠子结构，并对其余不确定部分重采样。
```

- block 1060 · table_cell_paragraph · body/table26/row2/cell3

```text
直接说明“大规模碎片下错误邻接会产生级联失败”，因此预测关系不能写成永久事实；本项目可借鉴“先预测—再验证—只软写入可靠结构—不确定部分允许重算”的闭环。
```

- block 1061 · table_cell_paragraph · body/table26/row2/cell4

```text
不直接搬其生成式完整装配流程；RelicWeave 的主问题是 R2 邻接候选与 R1 同器物非邻接检索，而非全局 6-DoF 完整拼装。
```

- block 1062 · table_cell_paragraph · body/table26/row3/cell1

```text
PuzzleFusion++: Auto-agglomerative 3D Fracture Assembly by Denoise and Verify（ICLR 2025）
```

- block 1063 · table_cell_paragraph · body/table26/row3/cell2

```text
从单碎片开始，经扩散模型求位姿、Transformer 验证 pair，再把可信碎片合并成更大组并迭代重复，作者明确将其类比为 auto-regressive / auto-agglomerative assembly。
```

- block 1064 · table_cell_paragraph · body/table26/row3/cell3

```text
支持“局部关系 → 局部组件 → 更大组件”的逐步扩展思想，可作为本项目从 R2 局部邻接扩展到同器物集合的强概念对照。
```

- block 1065 · table_cell_paragraph · body/table26/row3/cell4

```text
不能把“自回归碎片推理”本身当新颖点；其 hard merge 也不应直接复制，因为本项目的低质输入更容易发生错误传播。
```

- block 1066 · table_cell_paragraph · body/table26/row4/cell1

```text
GARF: Learning Generalizable 3D Reassembly for Real-World Fractures（ICCV 2025）
```

- block 1067 · table_cell_paragraph · body/table26/row4/cell2

```text
fracture-aware pretraining + flow matching + one-step preassembly，并用陶瓷、骨骼、蛋壳、石器等真实断裂数据检验跨域泛化。
```

- block 1068 · table_cell_paragraph · body/table26/row4/cell3

```text
强化“断口必须有专门预训练与真实断裂迁移验证”的原则；可为 R2 Local Memory 的断口 token、A12 合成到真实课程学习及跨材料评测提供强对照。
```

- block 1069 · table_cell_paragraph · body/table26/row4/cell4

```text
不把 flow matching 当作 R1 主干；其重点是位姿恢复，而本项目要保留 membership / retrieval 问题独立性。
```

- block 1070 · table_cell_paragraph · body/table26/row5/cell1

```text
Rectified Point Flow: Generic Point Cloud Pose Estimation（NeurIPS 2025 Spotlight）
```

- block 1071 · table_cell_paragraph · body/table26/row5/cell2

```text
把 pairwise registration 与 multi-part assembly 统一成条件生成的 point-wise rectified flow，并使用面向 overlap 的自监督编码器。
```

- block 1072 · table_cell_paragraph · body/table26/row5/cell3

```text
启发 R2 分支优先学习“接触／重叠相关局部几何”而非只学习通用对象语义；也可作为 3D 几何验证或辅助教师特征来源。
```

- block 1073 · table_cell_paragraph · body/table26/row5/cell4

```text
不把 point flow 直接当成 R1 身份检索器；R1 可能完全没有直接接触或 overlap。
```

- block 1074 · table_cell_paragraph · body/table26/row6/cell1

```text
Combinative Matching for Geometric Shape Assembly（ICCV 2025 Highlight）
```

- block 1075 · table_cell_paragraph · body/table26/row6/cell2

```text
显式同时建模“相同表面形状”与“相反体积占据”，并通过等变方向估计减少局部匹配歧义。
```

- block 1076 · table_cell_paragraph · body/table26/row6/cell3

```text
非常适合转化为 R2 高成本物理 verifier：不仅看表面像不像，还检查几何互补与空间占据是否真的允许咬合。
```

- block 1077 · table_cell_paragraph · body/table26/row6/cell4

```text
只用于接触验证与局部互补证据，不应把“可咬合”误写成同器物身份的全部依据。
```

- block 1078 · table_cell_paragraph · body/table26/row7/cell1

```text
TORA: Topological Representation Alignment for 3D Shape Assembly（2026，arXiv:2604.04050）
```

- block 1079 · table_cell_paragraph · body/table26/row7/cell2

```text
从冻结的预训练 3D encoder 蒸馏关系／拓扑结构到 flow backbone；使用 token cosine 或 CKA 对齐，并报告 geometry/contact-centric teacher property 比语义分类能力更关键。
```

- block 1080 · table_cell_paragraph · body/table26/row7/cell3

```text
支持本项目把 geometry/contact relation token 独立保留，并允许用教师关系结构训练主干，而不是把所有 3D 信息压成一个 global semantic vector。
```

- block 1081 · table_cell_paragraph · body/table26/row7/cell4

```text
当前作为预印本思想来源；若采用必须单独验证 teacher 选择、蒸馏损失和推理增益，不能因“拓扑对齐”名称直接写成贡献。
```

- block 1082 · table_cell_paragraph · body/table26/row8/cell1

```text
Jigsaw++: Imagining Complete Shape Priors for Object Reassembly（ICCV 2025）
```

- block 1083 · table_cell_paragraph · body/table26/row8/cell2

```text
从部分组装结果生成完整 shape prior，并通过 retargeting 把完整对象先验与现有 assembly 结果连接。
```

- block 1084 · table_cell_paragraph · body/table26/row8/cell3

```text
支持建立 Vessel Identity Memory / Vessel Latent：R1 的远距离同器物判断不应只看 pair，应利用“当前已知碎片共同暗示的器物整体”。
```

- block 1085 · table_cell_paragraph · body/table26/row8/cell4

```text
其论文也指出如何把生成的完整形状进一步作为后续重组指导仍是开放方向，因此本项目若使用必须以“先验能否改善 R1 检索”做独立验证。
```

- block 1086 · table_cell_paragraph · body/table26/row9/cell1

```text
Beyond Reassembly: Fractured Object Recovery with Missing Parts（CVPR 2026）
```

- block 1087 · table_cell_paragraph · body/table26/row9/cell2

```text
把已存在碎片与 missing tokens 一起交给 Transformer，联合进行现有部分重组与缺失部分预测；两项任务可互相促进。
```

- block 1088 · table_cell_paragraph · body/table26/row9/cell3

```text
说明“当前可见碎片”与“尚未观察到的器物结构”可以在同一潜空间互相约束。可借鉴为 Vessel Latent 中的 missing/unknown slots，而不是强迫当前组件已经完整。
```

- block 1089 · table_cell_paragraph · body/table26/row9/cell4

```text
不直接把 missing-part generation 设为首版任务；只研究其作为 R1 检索全局先验是否带来可归因增益。
```

- block 1090 · table_cell_paragraph · body/table26/row10/cell1

```text
MHopReg: Efficient Hierarchical Multi-Hop Graph Search for Point Cloud Registration（CVPR 2026）
```

- block 1091 · table_cell_paragraph · body/table26/row10/cell2

```text
在 compatibility graph 上预测对应置信度，从平衡 seed 出发做 hierarchical multi-hop expansion，再结合几何一致性与空间覆盖排序多假设。
```

- block 1092 · table_cell_paragraph · body/table26/row10/cell3

```text
与“高置信 R2 seed → 多跳扩展同器物候选”的图搜索逻辑高度相似。可把它抽象为 Contact-Conditioned Identity Expansion，而不需要复制其 registration 目标。
```

- block 1093 · table_cell_paragraph · body/table26/row10/cell4

```text
多跳只能增加 same-vessel 先验，不能把 R2 当传递关系；所有扩展必须保留类型与不确定性。
```

- block 1094 · table_cell_paragraph · body/table26/row11/cell1

```text
MV-RoMa: From Pairwise Matching into Multi-View Track Reconstruction（2026，arXiv:2603.27542）
```

- block 1095 · table_cell_paragraph · body/table26/row11/cell2

```text
指出 pairwise matching 直接串联会形成碎裂且几何不一致的轨迹；把 pairwise 结果当几何先验后，再进行 multi-view joint refinement。
```

- block 1096 · table_cell_paragraph · body/table26/row11/cell3

```text
直接支持本项目“预测 R2 后不能一路 hard-chain”的设计：pairwise edge 只作为 prior，加入新碎片后应联合重读受影响子图并允许旧边降权或撤销。
```

- block 1097 · table_cell_paragraph · body/table26/row11/cell4

```text
不是碎片论文，借的是“pairwise prior → joint refinement”的机制，而不是图像匹配模块本身。
```

- block 1098 · table_cell_paragraph · body/table26/row12/cell1

```text
Bag of Bags: Adaptive Visual Vocabularies for Genizah Join Image Retrieval（CVPRW 2026）
```

- block 1099 · table_cell_paragraph · body/table26/row12/cell2

```text
给定手稿碎片图像，检索来自同一物理手稿的其他碎片；每个 fragment 保留自己的 local visual vocabulary，并以 Chamfer / OT 做 set-to-set 比较，再用 shortlist→rerank 提高效率。
```

- block 1100 · table_cell_paragraph · body/table26/row12/cell3

```text
任务形式与 R1“同一物理器物、但未必直接接触”的检索很接近。它支持“一块碎片 = 一组局部原型／token，而不是一个 global embedding”，并支持粗检后局部集合重排。
```

- block 1101 · table_cell_paragraph · body/table26/row12/cell4

```text
文化遗产对象与视觉线索不同，不能直接复用其二值化／connected component 管线；只借 local vocabulary 与 set-to-set retrieval 思想。
```

- block 1102 · table_cell_paragraph · body/table26/row13/cell1

```text
Mitigating spurious features by contrastive learning in pottery sherd recognition（npj Heritage Science, 2026）
```

- block 1103 · table_cell_paragraph · body/table26/row13/cell2

```text
在河姆渡陶片数据中研究 spurious feature；采用 supervised contrastive learning、Triplet-center loss 与 flooding，目标是减轻模型依赖与任务无关的捷径特征。
```

- block 1104 · table_cell_paragraph · body/table26/row13/cell3

```text
提醒本项目 R2 与 R1 的有效证据不同：某些边缘／形状／纹样可能在训练集相关，却不是稳定的“同器物”因果证据。需要关系类型条件化的特征使用和 shortcut 审计。
```

- block 1105 · table_cell_paragraph · body/table26/row13/cell4

```text
其任务是分类而非邻接／同器物关系；只能作为鲁棒表征与反捷径训练参考。
```

- block 1106 · table_cell_paragraph · body/table26/row14/cell1

```text
Coconut / Chain of Continuous Thought（Hao et al., arXiv:2412.06769；ICLR 2025 workshop）
```

- block 1107 · table_cell_paragraph · body/table26/row14/cell2

```text
不把中间推理 hidden state 解码成离散文本，而把最后 hidden state 直接作为下一轮输入 embedding；连续 latent 可同时承载多个潜在后续分支。
```

- block 1108 · table_cell_paragraph · body/table26/row14/cell3

```text
这是“不要只把 P(R2) 标量喂回主干”的关键跨域依据：应保留 relation latent、局部证据与不确定性，让下一轮 R1/R2 判断读取连续关系状态。
```

- block 1109 · table_cell_paragraph · body/table26/row14/cell4

```text
不能声称把 Coconut 用于碎片就是创新；必须证明 latent relation feedback 比 scalar feedback、普通 GRU/循环和等 FLOPs 深网更有效。
```

- block 1110 · table_cell_paragraph · body/table26/row15/cell1

```text
Titans: Learning to Memorize at Test Time（NeurIPS 2025）
```

- block 1111 · table_cell_paragraph · body/table26/row15/cell2

```text
从记忆视角区分精确但局部的 attention 短期记忆与可持续写入的 neural long-term memory。
```

- block 1112 · table_cell_paragraph · body/table26/row15/cell3

```text
支持把“当前候选竞争的精细局部证据”和“跨多轮稳定的器物身份摘要”分成不同时间尺度，而不是把所有信息塞进一个 recurrent state。
```

- block 1113 · table_cell_paragraph · body/table26/row15/cell4

```text
不直接照搬神经长期记忆实现；本项目首先用显式 Evidence Bank + 可控 latent memory 建立可审计版本。
```

- block 1114 · table_cell_paragraph · body/table26/row16/cell1

```text
VisMem: Latent Vision Memory Unlocks Potential of Vision-Language Models（CVPR 2026）
```

- block 1115 · table_cell_paragraph · body/table26/row16/cell2

```text
建立短期 fine-grained perceptual memory 与长期 semantic memory，在推理过程中动态调用，以减轻长推理时视觉细节遗失。
```

- block 1116 · table_cell_paragraph · body/table26/row16/cell3

```text
直接支持“R2 Local Memory 保存断口／3D 细节，Vessel Memory 保存稳定器物身份”的双记忆分工，避免深层推理把局部断口证据冲淡。
```

- block 1117 · table_cell_paragraph · body/table26/row16/cell4

```text
其场景是 VLM；本项目必须证明双记忆对碎片关系检索的特定错误模式有效，而非只因模型更大。
```

- block 1118 · table_cell_paragraph · body/table26/row17/cell1

```text
WorldMM: Dynamic Multimodal Memory Agent for Long Video Reasoning（CVPR 2026）
```

- block 1119 · table_cell_paragraph · body/table26/row17/cell2

```text
构造 episodic、semantic、visual 多种互补记忆，并由 adaptive retrieval agent 迭代选择需要读取哪类记忆，直到证据足够。
```

- block 1120 · table_cell_paragraph · body/table26/row17/cell3

```text
与 A6 既有 Active Evidence Routing 高度一致，可进一步用于“候选当前最缺哪类证据，就读哪类碎片／局部／关系记忆”，而不是每轮固定全读。
```

- block 1121 · table_cell_paragraph · body/table26/row17/cell4

```text
不引入语言 Agent 本身；只借动态多记忆检索和“证据足够才停止”的计算策略。
```

- block 1123 · paragraph · body

```text
增补参考池的统一结论不是“把这些模型都接起来”，而是抽取五条可测试的设计原则：① 关系预测必须可验证、可撤销，不能 hard commit；② R2 的局部接触证据与 R1 的器物身份证据需要不同记忆和不同读写策略；③ pairwise 结果只能作为多轮／多碎片联合推理的 prior；④ 一块碎片应保留局部 token 集合和 provenance，而不是被压成单一全局向量；⑤ 迭代反馈应优先反馈连续 latent relation state 与不确定性，而不是只反馈一个概率标量。
```

### A6.15 新核心候选：Uncertainty-Aware Iterative Fragment Relational Memory Network（UA-IFRMN）

- block 1124 · paragraph · body

```text
A6.15 新核心候选：Uncertainty-Aware Iterative Fragment Relational Memory Network（UA-IFRMN）
```

- block 1125 · paragraph · body

```text
中文暂定名：不确定性感知的迭代碎片关系记忆网络。它不是当前稳定主干的替代品，而是登记在长期创新区的 P0 研究候选。其目标是把原本一次性的 pairwise R0/R1/R2 打分，改造成“局部邻接发现 → 软关系写入 → 多跳同器物扩展 → 新证据联合重读 → 旧关系可修正”的迭代关系推理过程。
```

- block 1126 · paragraph · body

```text
核心科学问题：在真实低质量、断口缺失、纹样不完整和 3D 不稳定的条件下，模型能否利用已经发现的高置信直接历史邻接 R2，构建带不确定性的关系上下文，从而提高同器物但非直接邻接 R1 的检索，同时避免错误 R2 被循环放大为器物级错误？
```

- block 1127 · paragraph · body

```text
这里的“自回归”只保留“上一轮内部结果会影响下一轮推理”这一抽象，不采用离散单路径 hard autoregression。更准确的机制名称为 Contact-Conditioned Identity Expansion + Reversible Relational Memory：直接接触证据先形成局部 relation latent，再作为同器物身份扩展的条件；所有写入都带 posterior、quality、provenance 和 revision 权限。
```

- block 1129 · table_cell_paragraph · body/table27/row1/cell1

```text
组成
```

- block 1130 · table_cell_paragraph · body/table27/row1/cell2

```text
建议定义
```

- block 1131 · table_cell_paragraph · body/table27/row1/cell3

```text
为什么需要
```

- block 1132 · table_cell_paragraph · body/table27/row2/cell1

```text
Fragment Token Bank F_i
```

- block 1133 · table_cell_paragraph · body/table27/row2/cell2

```text
每块碎片保留 token set，而不是单 global vector。建议至少含 global、fracture-local、surface/pattern、material、curvature/profile、thickness、3D local patch、quality/provenance 等槽位。
```

- block 1134 · table_cell_paragraph · body/table27/row2/cell3

```text
避免 R2 需要的断口细节和 R1 需要的器物身份证据互相覆盖；也方便按关系类型选择性读取。
```

- block 1135 · table_cell_paragraph · body/table27/row3/cell1

```text
R2 Local Memory M_R2
```

- block 1136 · table_cell_paragraph · body/table27/row3/cell2

```text
保存候选直接邻接的边级 latent e_ij、R0/R1/R2/UNKNOWN posterior、几何互补、fracture visibility、pose/gap/contact、质量与来源。
```

- block 1137 · table_cell_paragraph · body/table27/row3/cell3

```text
给后续 R1 推理提供“已经确认到什么局部组件”的精细上下文，但不把概率当事实。
```

- block 1138 · table_cell_paragraph · body/table27/row4/cell1

```text
Vessel Identity Memory M_V
```

- block 1139 · table_cell_paragraph · body/table27/row4/cell2

```text
从当前一组高可信 same-vessel 碎片中形成器物级 latent / token pool，保存材质、壁厚分布、曲率趋势、器形 profile、纹样体系和稳定全局先验。
```

- block 1140 · table_cell_paragraph · body/table27/row4/cell3

```text
解决口沿与底足等远距离 R1 pair 局部外观完全不相似的问题；判断目标从 pair similarity 升级为 candidate 与当前 vessel hypothesis 的兼容性。
```

- block 1141 · table_cell_paragraph · body/table27/row5/cell1

```text
Soft Typed Relation Graph G_t
```

- block 1142 · table_cell_paragraph · body/table27/row5/cell2

```text
节点是碎片或当前局部组件；边保存 R0/R1/R2/UNKNOWN 分布、latent relation、evidence support/contradiction、质量和时间版本。
```

- block 1143 · table_cell_paragraph · body/table27/row5/cell3

```text
允许多跳关系推理，同时保持“R2 不传递”的类型约束；图是 prior 与证据账本，不是硬 GT。
```

- block 1144 · table_cell_paragraph · body/table27/row6/cell1

```text
Hypothesis Set H_t
```

- block 1145 · table_cell_paragraph · body/table27/row6/cell2

```text
允许同时保留多个器物／关系假设或多个高概率边，而不是第一轮就只留一个赢家。
```

- block 1146 · table_cell_paragraph · body/table27/row6/cell3

```text
借鉴 continuous latent 可保留多个潜在分支的思想，降低早期错误导致整条推理链塌缩。
```

- block 1147 · table_cell_paragraph · body/table27/row7/cell1

```text
Persistent Evidence Bank M_E
```

- block 1148 · table_cell_paragraph · body/table27/row7/cell2

```text
原始 2D、断口 patch、可用 3D、质量指标、source_id、采集版本只读保存，任何循环都可回读。
```

- block 1149 · table_cell_paragraph · body/table27/row7/cell3

```text
保证“State != Evidence”；当关系被质疑时可以回到原始证据，而不是只在已经被模型过滤过的 hidden state 上自证。
```

### A6.15.1 UA-IFRMN 的一次完整推理循环

- block 1151 · paragraph · body

```text
A6.15.1 UA-IFRMN 的一次完整推理循环
```

- block 1152 · paragraph · body

```text
Step 0 — 编码而不压扁：对 query 和候选库生成 Fragment Token Bank；静态 encoder 可沿用现有成熟主干，先不改变 backbone。
```

- block 1153 · paragraph · body

```text
Step 1 — 双路粗检：同时产生高召回 same-vessel shortlist 与 R2 contact shortlist。前者防止“只沿邻片链才能发现远端碎片”，后者为关系扩展提供局部结构 seed。
```

- block 1154 · paragraph · body

```text
Step 2 — 形成 Soft R2 edges：relation head 输出 R0/R1/R2/UNKNOWN posterior 与 relation latent；3D 可用时再通过几何互补／接触 verifier 产生额外证据，但 verifier 不直接覆盖网络 posterior。
```

- block 1155 · paragraph · body

```text
Step 3 — 不确定性感知写入：只有满足质量和可比较条件的证据才进入 M_R2；其写入是 soft 的，保存 posterior、置信区间／校准量、source 与时间版本，不做不可逆 hard merge。
```

- block 1156 · paragraph · body

```text
Step 4 — Contact-Conditioned Identity Expansion：以高置信 R2 seed 或局部组件为起点，在 G_t 上做多跳候选扩展；扩展只提高 same-vessel prior，不直接把多跳终点标成 R1 或 R2。
```

- block 1157 · paragraph · body

```text
Step 5 — Candidate-conditioned recurrent reasoning：对每个待判候选读取其自身 token、相关 R2 Local Memory、Vessel Memory 与关系图路径，更新 R0/R1/R2/UNKNOWN posterior。
```

- block 1158 · paragraph · body

```text
Step 6 — Joint reread / revise：一旦新碎片被高置信接受，重新计算与该局部组件相关的旧边；允许 old R2 下降、R1/R2 互换、候选休眠或恢复。
```

- block 1159 · paragraph · body

```text
Step 7 — 动态停止或继续：当 Top-K、typed relation graph 与 vessel latent 连续多轮稳定且证据预算已足够时停止；若仍冲突则继续读 Evidence Bank，或输出 UNKNOWN / 补采建议。
```

### A6.16 从 R2 到 R1 的关系代数：允许“身份传播”，禁止“邻接传播”

- block 1160 · paragraph · body

```text
A6.16 从 R2 到 R1 的关系代数：允许“身份传播”，禁止“邻接传播”
```

- block 1161 · paragraph · body

```text
UA-IFRMN 必须显式尊重现行标签定义：R2 是原碎裂事件当前叶子片间的直接历史邻接，R1 是同器物但无直接历史断裂接触。因此，A—B 为 R2、B—C 为 R2，并不能推出 A—C 为 R2；它只能为 “A 与 C 属于同一器物” 提供强结构证据。最终 A—C 是 R1、R2 还是 UNKNOWN，仍要由直接接触证据和历史邻接真值判定。
```

- block 1163 · table_cell_paragraph · body/table28/row1/cell1

```text
关系组合
```

- block 1164 · table_cell_paragraph · body/table28/row1/cell2

```text
允许的推理
```

- block 1165 · table_cell_paragraph · body/table28/row1/cell3

```text
设计意义
```

- block 1166 · table_cell_paragraph · body/table28/row2/cell1

```text
R2(A,B) + R2(B,C)
```

- block 1167 · table_cell_paragraph · body/table28/row2/cell2

```text
same-vessel(A,C) prior ↑；A-C 的直接邻接类型仍未知。
```

- block 1168 · table_cell_paragraph · body/table28/row2/cell3

```text
最典型的“局部接触链 → 器物身份扩展”。
```

- block 1169 · table_cell_paragraph · body/table28/row3/cell1

```text
R2(A,B) + R1(B,C)
```

- block 1170 · table_cell_paragraph · body/table28/row3/cell2

```text
same-vessel(A,C) prior ↑，但强度应低于双高可信 R2，并受 B-C 证据质量控制。
```

- block 1171 · table_cell_paragraph · body/table28/row3/cell3

```text
允许 R1 参与身份传播，但避免弱关系无限扩散。
```

- block 1172 · table_cell_paragraph · body/table28/row4/cell1

```text
R1(A,B) + R1(B,C)
```

- block 1173 · table_cell_paragraph · body/table28/row4/cell2

```text
只能作为 soft same-vessel 支持；不能做硬传递。
```

- block 1174 · table_cell_paragraph · body/table28/row4/cell3

```text
R1 本身可能来自外观／材质相似，错误相关风险更高。
```

- block 1175 · table_cell_paragraph · body/table28/row5/cell1

```text
R2 路径 + 强材质／器型矛盾
```

- block 1176 · table_cell_paragraph · body/table28/row5/cell2

```text
触发 joint reread 和 hypothesis revision，而不是强制维持同器物。
```

- block 1177 · table_cell_paragraph · body/table28/row5/cell3

```text
用反证抑制“图一旦连通就全部同器物”的灾难。
```

- block 1178 · table_cell_paragraph · body/table28/row6/cell1

```text
多条独立 R2 路径指向同一候选
```

- block 1179 · table_cell_paragraph · body/table28/row6/cell2

```text
可增加 same-vessel belief，但必须做 source de-correlation。
```

- block 1180 · table_cell_paragraph · body/table28/row6/cell3

```text
避免由同一重建／同一照片派生的多条证据被重复计权。
```

- block 1182 · paragraph · body

```text
研究实现上建议把 same-vessel 与 direct-contact 解耦成两个相关但不同的头：P_same(i,j) 表示器物身份兼容，P_R2(i,j) 表示直接历史邻接；随后由 typed relation head 在 R0/R1/R2/UNKNOWN 上给出最终分布。这样多跳图只影响 P_same 或 vessel compatibility，不会错误地让 R2 具备传递性。
```

### A6.17 为什么不能只把“邻片概率”喂回去：Scalar Feedback、Latent Feedback 与多假设记忆

- block 1183 · paragraph · body

```text
A6.17 为什么不能只把“邻片概率”喂回去：Scalar Feedback、Latent Feedback 与多假设记忆
```

- block 1184 · paragraph · body

```text
用户提出的原始思路“预测邻片后，把邻片预测作为下一轮输入，再判断同器物非邻片”应保留为最小基线，但正式候选必须把“反馈什么”做成分层实验。单一 P(R2) 只表达最终置信度，不包含模型是依据断口、几何、纹样还是质量得出的结论，也无法区分“高分但证据冲突”和“高分且多证据一致”。
```

- block 1186 · table_cell_paragraph · body/table29/row1/cell1

```text
反馈层级
```

- block 1187 · table_cell_paragraph · body/table29/row1/cell2

```text
输入下一轮的内容
```

- block 1188 · table_cell_paragraph · body/table29/row1/cell3

```text
研究价值
```

- block 1189 · table_cell_paragraph · body/table29/row1/cell4

```text
主要风险
```

- block 1190 · table_cell_paragraph · body/table29/row2/cell1

```text
B1 Scalar Feedback
```

- block 1191 · table_cell_paragraph · body/table29/row2/cell2

```text
只把 P(R2)、margin、quality 等少量标量反馈给下一轮。
```

- block 1192 · table_cell_paragraph · body/table29/row2/cell3

```text
最便宜、最可解释，是用户原始想法的直接实现；必须保留为基线。
```

- block 1193 · table_cell_paragraph · body/table29/row2/cell4

```text
信息瓶颈最大，无法携带局部证据结构。
```

- block 1194 · table_cell_paragraph · body/table29/row3/cell1

```text
B2 Latent Relation Feedback
```

- block 1195 · table_cell_paragraph · body/table29/row3/cell2

```text
反馈 e_ij relation latent + typed posterior + provenance mask。
```

- block 1196 · table_cell_paragraph · body/table29/row3/cell3

```text
对应 continuous latent reasoning 思想；允许下一轮利用“为什么像邻片”的连续内部表示。
```

- block 1197 · table_cell_paragraph · body/table29/row3/cell4

```text
latent 可能学到不可解释捷径，需要 probe 和 corruption test。
```

- block 1198 · table_cell_paragraph · body/table29/row4/cell1

```text
B3 Neighbor Token Set
```

- block 1199 · table_cell_paragraph · body/table29/row4/cell2

```text
将高可信邻片的局部 token set 作为可查询上下文，而不是压成一个 latent。
```

- block 1200 · table_cell_paragraph · body/table29/row4/cell3

```text
保留断口／纹样／3D 多区域证据，接近 set-to-set retrieval。
```

- block 1201 · table_cell_paragraph · body/table29/row4/cell4

```text
计算和显存增加，需 K/L 预算。
```

- block 1202 · table_cell_paragraph · body/table29/row5/cell1

```text
B4 Soft Multi-Hypothesis Memory
```

- block 1203 · table_cell_paragraph · body/table29/row5/cell2

```text
同时保留多个关系／器物假设，以权重而非 one-hot winner 表示。
```

- block 1204 · table_cell_paragraph · body/table29/row5/cell3

```text
避免第一步错边后全链路 collapse；允许后续证据翻案。
```

- block 1205 · table_cell_paragraph · body/table29/row5/cell4

```text
需要假设裁剪和去重，否则复杂度膨胀。
```

- block 1206 · table_cell_paragraph · body/table29/row6/cell1

```text
B5 Joint Graph Reread
```

- block 1207 · table_cell_paragraph · body/table29/row6/cell2

```text
新证据加入后，重新更新受影响子图和 Vessel Memory。
```

- block 1208 · table_cell_paragraph · body/table29/row6/cell3

```text
解决 pairwise chaining 不一致；旧预测不是不可撤销 token。
```

- block 1209 · table_cell_paragraph · body/table29/row6/cell4

```text
必须限制更新半径／候选数，避免全图 O(N²) 重算。
```

- block 1211 · paragraph · body

```text
因此推荐研究顺序固定为 B1 → B2 → B3 → B4/B5。只有 B2 在同输入、同候选池、相近 FLOPs 下显著优于 B1，才能说明“连续 relation latent”本身具有价值；否则不允许仅因为结构更复杂而升级主干。
```

### A6.18 双记忆与器物潜变量：R2 Local Memory × Vessel Identity Memory

- block 1212 · paragraph · body

```text
A6.18 双记忆与器物潜变量：R2 Local Memory × Vessel Identity Memory
```

- block 1213 · paragraph · body

```text
R2 与 R1 的核心证据分布不同。R2 更依赖断口局部互补、接触几何、局部纹理连续；R1 可能没有任何直接接触，反而依赖材质、壁厚、器形曲率、纹样体系、制造痕迹以及当前已恢复器物的整体先验。因此不建议让同一个 memory slot 同时承担两类关系。
```

- block 1215 · table_cell_paragraph · body/table30/row1/cell1

```text
记忆层
```

- block 1216 · table_cell_paragraph · body/table30/row1/cell2

```text
保存内容
```

- block 1217 · table_cell_paragraph · body/table30/row1/cell3

```text
主要服务目标
```

- block 1218 · table_cell_paragraph · body/table30/row1/cell4

```text
主要思想来源
```

- block 1219 · table_cell_paragraph · body/table30/row2/cell1

```text
短时／局部：R2 Local Memory
```

- block 1220 · table_cell_paragraph · body/table30/row2/cell2

```text
断口 patch、局部 3D、法线／曲率、互补场、contact/gap/penetration、局部纹样连续、fracture visibility、质量。
```

- block 1221 · table_cell_paragraph · body/table30/row2/cell3

```text
高精度直接邻接验证、局部组件形成、反证。
```

- block 1222 · table_cell_paragraph · body/table30/row2/cell4

```text
参考 VisMem 的 fine-grained short-term visual memory、GARF 的 fracture-aware 表征、Combinative Matching 的几何互补。
```

- block 1223 · table_cell_paragraph · body/table30/row3/cell1

```text
长时／器物：Vessel Identity Memory
```

- block 1224 · table_cell_paragraph · body/table30/row3/cell2

```text
材质、釉色／纹样族、壁厚统计、器型 profile、曲率趋势、已确认组件的全局关系、missing/unknown slots、稳定 provenance。
```

- block 1225 · table_cell_paragraph · body/table30/row3/cell3

```text
远距离 R1 检索、同器物候选排序、抑制“只看断口”造成的漏检。
```

- block 1226 · table_cell_paragraph · body/table30/row3/cell4

```text
参考 Titans 的短／长期记忆分工、Jigsaw++ 完整 shape prior、Beyond Reassembly missing tokens。
```

- block 1227 · table_cell_paragraph · body/table30/row4/cell1

```text
证据源：Persistent Evidence Bank
```

- block 1228 · table_cell_paragraph · body/table30/row4/cell2

```text
原始图像、局部 patch、3D、质量和采集版本，不被循环覆盖。
```

- block 1229 · table_cell_paragraph · body/table30/row4/cell3

```text
任何关系被质疑时可重新取证；防止 self-confirmation。
```

- block 1230 · table_cell_paragraph · body/table30/row4/cell4

```text
与 A6.5 既有 Evidence Bank 一致，本节只扩展其在 R2→R1 循环中的角色。
```

- block 1232 · paragraph · body

```text
Vessel Memory 不等于“把所有已接受碎片做平均池化”。建议至少比较：mean pooling、attention pooling、slot-based memory、set transformer／Perceiver-style query，以及带 missing slots 的 vessel token。任何复杂版本都必须对照简单 pooling，防止“多参数 = 更好”的假象。
```

### A6.19 错误传播控制：Predict → Verify → Soft Write → Reread → Revise

- block 1233 · paragraph · body

```text
A6.19 错误传播控制：Predict → Verify → Soft Write → Reread → Revise
```

- block 1234 · paragraph · body

```text
这条创新线最大的风险不是“能不能利用正确 R2”，而是“错误 R2 会不会污染后续 R1”。因此误差传播本身必须成为论文级评测对象，而不是部署阶段再修。SARe 的 many-fragment cascading failure、MV-RoMa 的 pairwise chaining inconsistency 以及本项目既有反自证规则共同要求：任何关系写入都必须可撤销、可追溯、可重新验证。
```

- block 1236 · table_cell_paragraph · body/table31/row1/cell1

```text
控制机制
```

- block 1237 · table_cell_paragraph · body/table31/row1/cell2

```text
实施约束
```

- block 1238 · table_cell_paragraph · body/table31/row1/cell3

```text
目的
```

- block 1239 · table_cell_paragraph · body/table31/row2/cell1

```text
Soft Write
```

- block 1240 · table_cell_paragraph · body/table31/row2/cell2

```text
边只写 posterior + latent + quality + provenance，不写 one-hot 真值。
```

- block 1241 · table_cell_paragraph · body/table31/row2/cell3

```text
降低早期错误的不可逆性。
```

- block 1242 · table_cell_paragraph · body/table31/row3/cell1

```text
Geometric Verification
```

- block 1243 · table_cell_paragraph · body/table31/row3/cell2

```text
有合格 3D 时，用局部互补、gap/contact/penetration、相反体积占据等进行独立物理检查。
```

- block 1244 · table_cell_paragraph · body/table31/row3/cell3

```text
把“网络觉得像”与“物理上能接触”分开。
```

- block 1245 · table_cell_paragraph · body/table31/row4/cell1

```text
Joint Reread
```

- block 1246 · table_cell_paragraph · body/table31/row4/cell2

```text
新碎片加入后，重算与受影响组件相关的旧边。
```

- block 1247 · table_cell_paragraph · body/table31/row4/cell3

```text
允许 P(R2) 0.82 → 0.41，而不是永久自证。
```

- block 1248 · table_cell_paragraph · body/table31/row5/cell1

```text
Candidate Dormancy / Resurrection
```

- block 1249 · table_cell_paragraph · body/table31/row5/cell2

```text
低分但证据不足的候选进入 Dormant，不直接永久删除；新证据可复活。
```

- block 1250 · table_cell_paragraph · body/table31/row5/cell3

```text
适应低质输入与遮挡。
```

- block 1251 · table_cell_paragraph · body/table31/row6/cell1

```text
Multi-Hypothesis Retention
```

- block 1252 · table_cell_paragraph · body/table31/row6/cell2

```text
在高不确定时保留多个图假设或边分布。
```

- block 1253 · table_cell_paragraph · body/table31/row6/cell3

```text
避免单路径 autoregression 的早期塌缩。
```

- block 1254 · table_cell_paragraph · body/table31/row7/cell1

```text
Source De-correlation
```

- block 1255 · table_cell_paragraph · body/table31/row7/cell2

```text
相同照片派生的 2D、3D、重建置信度标记同源。
```

- block 1256 · table_cell_paragraph · body/table31/row7/cell3

```text
防止一条错误观测以多种“证据”形式被重复放大。
```

- block 1257 · table_cell_paragraph · body/table31/row8/cell1

```text
Abstain / UNKNOWN
```

- block 1258 · table_cell_paragraph · body/table31/row8/cell2

```text
posterior 不稳定、强冲突或 evidence coverage 不足时输出 UNKNOWN / 补采。
```

- block 1259 · table_cell_paragraph · body/table31/row8/cell3

```text
错误控制优先于强迫形成完整关系图。
```

### A6.20 训练路线：Oracle 关系上限 → 预测关系闭环 → 人工腐化鲁棒性

- block 1261 · paragraph · body

```text
A6.20 训练路线：Oracle 关系上限 → 预测关系闭环 → 人工腐化鲁棒性
```

- block 1262 · paragraph · body

```text
训练不得从一开始就把完整 UA-IFRMN 端到端同时打开。否则任何增益都无法判断来自“R2 上下文真的有用”、更大模型、更大计算还是标签泄漏。建议按下面顺序建立证据。
```

- block 1264 · table_cell_paragraph · body/table32/row1/cell1

```text
阶段
```

- block 1265 · table_cell_paragraph · body/table32/row1/cell2

```text
训练／输入设置
```

- block 1266 · table_cell_paragraph · body/table32/row1/cell3

```text
必须回答的问题
```

- block 1267 · table_cell_paragraph · body/table32/row2/cell1

```text
T0 Pairwise baseline
```

- block 1268 · table_cell_paragraph · body/table32/row2/cell2

```text
完全不使用关系记忆。输入 q,c，输出 R0/R1/R2/UNKNOWN。
```

- block 1269 · table_cell_paragraph · body/table32/row2/cell3

```text
冻结最强静态基线。
```

- block 1270 · table_cell_paragraph · body/table32/row3/cell1

```text
T1 Oracle-R2 context
```

- block 1271 · table_cell_paragraph · body/table32/row3/cell2

```text
第二阶段只给 GT R2 邻片／局部组件，不给模型自己预测的边。
```

- block 1272 · table_cell_paragraph · body/table32/row3/cell3

```text
回答最关键问题：如果邻片信息正确，R1 是否存在足够大的可利用上限？若无明显增益，整条路线停止。
```

- block 1273 · table_cell_paragraph · body/table32/row4/cell1

```text
T2 Scalar predicted-R2
```

- block 1274 · table_cell_paragraph · body/table32/row4/cell2

```text
使用模型自己的 P(R2) 标量反馈。
```

- block 1275 · table_cell_paragraph · body/table32/row4/cell3

```text
验证用户原始想法能否在最小复杂度下成立。
```

- block 1276 · table_cell_paragraph · body/table32/row5/cell1

```text
T3 Latent predicted-R2
```

- block 1277 · table_cell_paragraph · body/table32/row5/cell2

```text
反馈 e_R2 relation latent 与证据 mask。
```

- block 1278 · table_cell_paragraph · body/table32/row5/cell3

```text
检验 continuous relation state 是否比 scalar 真正多提供信息。
```

- block 1279 · table_cell_paragraph · body/table32/row6/cell1

```text
T4 Scheduled / mixed memory
```

- block 1280 · table_cell_paragraph · body/table32/row6/cell2

```text
训练时混合 GT、predicted、incomplete memory，逐步降低 GT 比例。
```

- block 1281 · table_cell_paragraph · body/table32/row6/cell3

```text
减少 train-test distribution shift。
```

- block 1282 · table_cell_paragraph · body/table32/row7/cell1

```text
T5 Corrupted memory curriculum
```

- block 1283 · table_cell_paragraph · body/table32/row7/cell2

```text
主动注入 false R2、missed R2、wrong same-vessel、低质量边、缺失 3D、冲突证据。
```

- block 1284 · table_cell_paragraph · body/table32/row7/cell3

```text
强迫模型把 memory 当证据而非真理，并训练 revision。
```

- block 1285 · table_cell_paragraph · body/table32/row8/cell1

```text
T6 Joint reread
```

- block 1286 · table_cell_paragraph · body/table32/row8/cell2

```text
允许新节点进入后回看旧边，加入 revision supervision。
```

- block 1287 · table_cell_paragraph · body/table32/row8/cell3

```text
验证可反悔机制是否真的降低级联错误。
```

- block 1288 · table_cell_paragraph · body/table32/row9/cell1

```text
T7 Vessel latent / shape prior
```

- block 1289 · table_cell_paragraph · body/table32/row9/cell2

```text
在前面全部有效后，再加入器物级 latent 或 missing slots。
```

- block 1290 · table_cell_paragraph · body/table32/row9/cell3

```text
把全局先验与关系记忆的增益分开归因。
```

- block 1292 · paragraph · body

```text
A12 可控合成碎片实验室应为本路线生成专门 episode，而不是只增加总样本量：同一母体生成完整 R2 图与 R1 集合；然后分别制造 0%、5%、10%、20%、30% 错边，或只破坏一个关系证据轴，形成严格配对的 corruption ladder。真实数据必须保留独立母体确认集，合成数据只能用于预训练、机制压力测试和错误模式覆盖，不能代替真实成立证据。
```

### A6.20.1 候选损失项：先作为可拆卸假设，不一次全部启用

- block 1293 · paragraph · body

```text
A6.20.1 候选损失项：先作为可拆卸假设，不一次全部启用
```

- block 1294 · paragraph · body

```text
可维护以下损失池：L_same（同器物 membership）、L_R2（直接历史邻接）、L_contact（可比较条件下的接触／互补）、L_rank（候选排序）、L_comp（relation composition 一致性）、L_calib（posterior 校准）、L_revision（错误边被新证据推翻时的修正监督）、L_memory（vessel/local memory 一致性）以及可选 L_distill（TORA-like relation structure distillation）。任何一次正式消融只允许新增一个主要损失项，并报告其对 R1、R2、误导风险和计算的独立影响。
```

- block 1295 · paragraph · body

```text
一个重要约束是：L_comp 只鼓励 R2 路径提高 same-vessel belief，不允许把 R2 传递为 R2。即使 A-B 与 B-C 都是 R2，也不能把 A-C 直接监督为 R2；A-C 的直接邻接标签仍由历史真值单独决定。
```

### A6.21 必做实验矩阵：先证明“邻片上下文有信息”，再证明“新机制能安全利用它”

- block 1296 · paragraph · body

```text
A6.21 必做实验矩阵：先证明“邻片上下文有信息”，再证明“新机制能安全利用它”
```

- block 1298 · table_cell_paragraph · body/table33/row1/cell1

```text
实验
```

- block 1299 · table_cell_paragraph · body/table33/row1/cell2

```text
最低对照
```

- block 1300 · table_cell_paragraph · body/table33/row1/cell3

```text
核心观测
```

- block 1301 · table_cell_paragraph · body/table33/row1/cell4

```text
否定／进入条件
```

- block 1302 · table_cell_paragraph · body/table33/row2/cell1

```text
Oracle-R2 上限实验
```

- block 1303 · table_cell_paragraph · body/table33/row2/cell2

```text
Pairwise R1 vs Pairwise + GT R2 context
```

- block 1304 · table_cell_paragraph · body/table33/row2/cell3

```text
R1 Hit@K / same-vessel Hit@K / CovRecall
```

- block 1305 · table_cell_paragraph · body/table33/row2/cell4

```text
若 GT R2 也不能稳定提升 R1，则暂停 UA-IFRMN。
```

- block 1306 · table_cell_paragraph · body/table33/row3/cell1

```text
Scalar vs Latent Feedback
```

- block 1307 · table_cell_paragraph · body/table33/row3/cell2

```text
P(R2) 标量 vs e_R2 latent，同候选池同 FLOPs
```

- block 1308 · table_cell_paragraph · body/table33/row3/cell3

```text
R1、R2、ECE/Brier、时延
```

- block 1309 · table_cell_paragraph · body/table33/row3/cell4

```text
只有 latent 显著优于 scalar 才保留连续反馈。
```

- block 1310 · table_cell_paragraph · body/table33/row4/cell1

```text
单邻片 vs 多邻片集合
```

- block 1311 · table_cell_paragraph · body/table33/row4/cell2

```text
Top1 R2 context vs Top-K neighbor token set
```

- block 1312 · table_cell_paragraph · body/table33/row4/cell3

```text
R1、覆盖、多邻片真值恢复
```

- block 1313 · table_cell_paragraph · body/table33/row4/cell4

```text
证明 set context 是否真实有价值。
```

- block 1314 · table_cell_paragraph · body/table33/row5/cell1

```text
Pairwise chaining vs Soft Graph
```

- block 1315 · table_cell_paragraph · body/table33/row5/cell2

```text
直接把边串起来 vs typed soft graph
```

- block 1316 · table_cell_paragraph · body/table33/row5/cell3

```text
级联错误率、R1、错误图连通率
```

- block 1317 · table_cell_paragraph · body/table33/row5/cell4

```text
Soft graph 必须明显减少错误传播。
```

- block 1318 · table_cell_paragraph · body/table33/row6/cell1

```text
Hard Commit vs Reversible Memory
```

- block 1319 · table_cell_paragraph · body/table33/row6/cell2

```text
接受后不可撤销 vs joint reread/revise
```

- block 1320 · table_cell_paragraph · body/table33/row6/cell3

```text
wrong→correct、correct→wrong、最终命中
```

- block 1321 · table_cell_paragraph · body/table33/row6/cell4

```text
可反悔机制必须提高恢复率且不显著伤害 clean。
```

- block 1322 · table_cell_paragraph · body/table33/row7/cell1

```text
无 Vessel Memory vs Vessel Memory
```

- block 1323 · table_cell_paragraph · body/table33/row7/cell2

```text
只有 R2 local context vs 加器物 latent
```

- block 1324 · table_cell_paragraph · body/table33/row7/cell3

```text
远距离 R1、口沿↔底足等异部位子集
```

- block 1325 · table_cell_paragraph · body/table33/row7/cell4

```text
验证全局器物先验是否补足局部相似不足。
```

- block 1326 · table_cell_paragraph · body/table33/row8/cell1

```text
无 Local Memory vs Dual Memory
```

- block 1327 · table_cell_paragraph · body/table33/row8/cell2

```text
单一 vessel latent vs R2 Local + Vessel 双记忆
```

- block 1328 · table_cell_paragraph · body/table33/row8/cell3

```text
R2 精度、R1、局部断口保持率
```

- block 1329 · table_cell_paragraph · body/table33/row8/cell4

```text
证明分层记忆而非单一大向量更合理。
```

- block 1330 · table_cell_paragraph · body/table33/row9/cell1

```text
R2 corruption curve
```

- block 1331 · table_cell_paragraph · body/table33/row9/cell2

```text
错边率 0/5/10/20/30%
```

- block 1332 · table_cell_paragraph · body/table33/row9/cell3

```text
R1 Hit@K、误导率、校准、revision success
```

- block 1333 · table_cell_paragraph · body/table33/row9/cell4

```text
优良模型曲线应比 hard autoregressive 明显更平缓。
```

- block 1334 · table_cell_paragraph · body/table33/row10/cell1

```text
关系类型交换压力测试
```

- block 1335 · table_cell_paragraph · body/table33/row10/cell2

```text
把部分 R1 伪装成 R2、R2 伪装成 R1
```

- block 1336 · table_cell_paragraph · body/table33/row10/cell3

```text
类型鲁棒性与 same-vessel 稳定性
```

- block 1337 · table_cell_paragraph · body/table33/row10/cell4

```text
检查模型是否真正理解 direct-contact 与 identity 的区别。
```

- block 1338 · table_cell_paragraph · body/table33/row11/cell1

```text
来源捷径审计
```

- block 1339 · table_cell_paragraph · body/table33/row11/cell2

```text
遮蔽／打乱纹样、边界、材质、背景、采集台特征
```

- block 1340 · table_cell_paragraph · body/table33/row11/cell3

```text
各 subgroup 性能与 representation probe
```

- block 1341 · table_cell_paragraph · body/table33/row11/cell4

```text
避免“同器物”被数据采集捷径替代。
```

- block 1342 · table_cell_paragraph · body/table33/row12/cell1

```text
等预算对照
```

- block 1343 · table_cell_paragraph · body/table33/row12/cell2

```text
UA-IFRMN vs 等参数／等 FLOPs 静态深网、GRU、普通循环
```

- block 1344 · table_cell_paragraph · body/table33/row12/cell3

```text
全部任务指标 + GPU 小时 + P95 时延
```

- block 1345 · table_cell_paragraph · body/table33/row12/cell4

```text
证明增益来自关系记忆机制而非更多算力。
```

- block 1347 · paragraph · body

```text
推荐把 Oracle-R2 gap 作为第一道 go/no-go 门。它直接测量“正确邻接上下文最多能给 R1 带来多少信息”。只有这个上限足够大，后续关于 latent feedback、图记忆、vessel memory 和 multi-hop reasoning 的工程投入才有意义。第二道门是 predicted-R2 与 corruption curve：如果真实预测边一加入就把 R1 拖垮，则优先研究校准、验证和 revision，而不是继续扩主干。
```

### A6.22 可形成的研究主张与明确禁写项

- block 1348 · paragraph · body

```text
A6.22 可形成的研究主张与明确禁写项
```

- block 1349 · paragraph · body

```text
现阶段不得写“首次将自回归用于碎片重建”：PuzzleFusion++ 已经明确采用 auto-agglomerative、类 autoregressive 的逐步组装。也不得写“首次把预测碎片关系反馈给下一轮”：SARe 已经使用接触图、几何验证与可靠子结构反馈／重采样。任何论文新颖性都必须避开这两个宽泛表述。
```

- block 1350 · paragraph · body

```text
当前更有希望、但仍需实验证明的主张是：在“同器物非邻接检索”问题上，利用直接历史邻接 R2 构建带不确定性、可修正的 typed relation memory，并通过 contact-conditioned multi-hop identity expansion 与 vessel-level latent context 提高 R1 检索；同时显式测量和抑制错误 R2 的级联传播。
```

- block 1351 · paragraph · body

```text
可暂定英文机制描述：Uncertainty-Aware Iterative Fragment Relational Memory Network (UA-IFRMN) for Contact-Conditioned Identity Expansion。正式投稿前必须再次检索同题工作，并以当时最新文献决定名称与新颖性措辞。
```

- block 1353 · table_cell_paragraph · body/table34/row1/cell1

```text
类别
```

- block 1354 · table_cell_paragraph · body/table34/row1/cell2

```text
内容
```

- block 1355 · table_cell_paragraph · body/table34/row2/cell1

```text
可以研究
```

- block 1356 · table_cell_paragraph · body/table34/row2/cell2

```text
R2 作为局部结构 seed 是否显著提高 R1；soft typed graph 是否比 pair chaining 更稳；latent relation feedback 是否比 scalar feedback 更有效；Vessel Memory 是否改善远距离 R1；可反悔机制是否降低级联错误。
```

- block 1357 · table_cell_paragraph · body/table34/row3/cell1

```text
不能预先声称
```

- block 1358 · table_cell_paragraph · body/table34/row3/cell2

```text
UA-IFRMN 已经优于 SOTA；R2→R1 一定有效；循环／CTM 本身就是创新；自回归思想首次用于碎片；完整器物 prior 一定能帮助低质陶片。
```

- block 1359 · table_cell_paragraph · body/table34/row4/cell1

```text
必须保留的失败解释
```

- block 1360 · table_cell_paragraph · body/table34/row4/cell2

```text
Oracle-R2 无上限；predicted-R2 噪声抵消收益；Vessel Memory 形成 shortcut；多跳扩展造成 graph over-smoothing；relation latent 无法优于标量；可反悔机制成本过高。
```

### A6.23 创新账本增补：UA-IFRMN 关系记忆路线

- block 1362 · paragraph · body

```text
A6.23 创新账本增补：UA-IFRMN 关系记忆路线
```

- block 1363 · paragraph · body

```text
以下编号从现有 INNO-31 之后顺延，只新增、不覆盖旧条目。全部状态初始为 RESEARCH_CANDIDATE 或 IDEA，待冻结实验后再流转。
```

- block 1365 · table_cell_paragraph · body/table35/row1/cell1

```text
ID
```

- block 1366 · table_cell_paragraph · body/table35/row1/cell2

```text
创新候选
```

- block 1367 · table_cell_paragraph · body/table35/row1/cell3

```text
当前优先级
```

- block 1368 · table_cell_paragraph · body/table35/row1/cell4

```text
状态
```

- block 1369 · table_cell_paragraph · body/table35/row2/cell1

```text
INNO-32
```

- block 1370 · table_cell_paragraph · body/table35/row2/cell2

```text
UA-IFRMN：Uncertainty-Aware Iterative Fragment Relational Memory Network。
```

- block 1371 · table_cell_paragraph · body/table35/row2/cell3

```text
P0 核心
```

- block 1372 · table_cell_paragraph · body/table35/row2/cell4

```text
RESEARCH_CANDIDATE
```

- block 1373 · table_cell_paragraph · body/table35/row3/cell1

```text
INNO-33
```

- block 1374 · table_cell_paragraph · body/table35/row3/cell2

```text
Contact-Conditioned Identity Expansion：用高置信 R2 局部接触结构作为 R1 同器物身份扩展条件。
```

- block 1375 · table_cell_paragraph · body/table35/row3/cell3

```text
P0 核心
```

- block 1376 · table_cell_paragraph · body/table35/row3/cell4

```text
RESEARCH_CANDIDATE
```

- block 1377 · table_cell_paragraph · body/table35/row4/cell1

```text
INNO-34
```

- block 1378 · table_cell_paragraph · body/table35/row4/cell2

```text
Soft Typed Relation Graph Memory：R0/R1/R2/UNKNOWN + latent + quality + provenance 的可修正关系图。
```

- block 1379 · table_cell_paragraph · body/table35/row4/cell3

```text
P0 核心
```

- block 1380 · table_cell_paragraph · body/table35/row4/cell4

```text
RESEARCH_CANDIDATE
```

- block 1381 · table_cell_paragraph · body/table35/row5/cell1

```text
INNO-35
```

- block 1382 · table_cell_paragraph · body/table35/row5/cell2

```text
Latent Relation Feedback：反馈连续 relation latent，而非只反馈 P(R2) 标量。
```

- block 1383 · table_cell_paragraph · body/table35/row5/cell3

```text
P1 高潜
```

- block 1384 · table_cell_paragraph · body/table35/row5/cell4

```text
RESEARCH_CANDIDATE
```

- block 1385 · table_cell_paragraph · body/table35/row6/cell1

```text
INNO-36
```

- block 1386 · table_cell_paragraph · body/table35/row6/cell2

```text
Dual Relational Memory：R2 Local Memory + Vessel Identity Memory 分工。
```

- block 1387 · table_cell_paragraph · body/table35/row6/cell3

```text
P0 架构
```

- block 1388 · table_cell_paragraph · body/table35/row6/cell4

```text
RESEARCH_CANDIDATE
```

- block 1389 · table_cell_paragraph · body/table35/row7/cell1

```text
INNO-37
```

- block 1390 · table_cell_paragraph · body/table35/row7/cell2

```text
Reversible Joint Reread：新证据进入后联合重读受影响子图，允许旧边降权／撤销／改型。
```

- block 1391 · table_cell_paragraph · body/table35/row7/cell3

```text
P0 可靠性
```

- block 1392 · table_cell_paragraph · body/table35/row7/cell4

```text
RESEARCH_CANDIDATE
```

- block 1393 · table_cell_paragraph · body/table35/row8/cell1

```text
INNO-38
```

- block 1394 · table_cell_paragraph · body/table35/row8/cell2

```text
Soft Multi-Hypothesis Vessel Memory：高不确定时保留多个关系／器物假设，避免早期单路径塌缩。
```

- block 1395 · table_cell_paragraph · body/table35/row8/cell3

```text
P2 储备
```

- block 1396 · table_cell_paragraph · body/table35/row8/cell4

```text
IDEA
```

- block 1397 · table_cell_paragraph · body/table35/row9/cell1

```text
INNO-39
```

- block 1398 · table_cell_paragraph · body/table35/row9/cell2

```text
Relation Composition Regularization：R2 多跳只提升 same-vessel belief，不错误传播 R2 类型。
```

- block 1399 · table_cell_paragraph · body/table35/row9/cell3

```text
P1 高潜
```

- block 1400 · table_cell_paragraph · body/table35/row9/cell4

```text
RESEARCH_CANDIDATE
```

- block 1401 · table_cell_paragraph · body/table35/row10/cell1

```text
INNO-40
```

- block 1402 · table_cell_paragraph · body/table35/row10/cell2

```text
Oracle-to-Predicted Relation Curriculum：GT R2 → 混合 memory → predicted R2 的课程训练。
```

- block 1403 · table_cell_paragraph · body/table35/row10/cell3

```text
P1 训练
```

- block 1404 · table_cell_paragraph · body/table35/row10/cell4

```text
RESEARCH_CANDIDATE
```

- block 1405 · table_cell_paragraph · body/table35/row11/cell1

```text
INNO-41
```

- block 1406 · table_cell_paragraph · body/table35/row11/cell2

```text
Relation Corruption Robustness Curriculum：按错边率与错边类型系统训练 memory-as-evidence 而非 memory-as-truth。
```

- block 1407 · table_cell_paragraph · body/table35/row11/cell3

```text
P0 可靠性
```

- block 1408 · table_cell_paragraph · body/table35/row11/cell4

```text
RESEARCH_CANDIDATE
```

- block 1409 · table_cell_paragraph · body/table35/row12/cell1

```text
INNO-42
```

- block 1410 · table_cell_paragraph · body/table35/row12/cell2

```text
Vessel Latent / Missing Slots：从已知碎片形成器物级潜变量，并显式保留未知／缺失结构。
```

- block 1411 · table_cell_paragraph · body/table35/row12/cell3

```text
P1 高风险高收益
```

- block 1412 · table_cell_paragraph · body/table35/row12/cell4

```text
IDEA
```

- block 1413 · table_cell_paragraph · body/table35/row13/cell1

```text
INNO-43
```

- block 1414 · table_cell_paragraph · body/table35/row13/cell2

```text
Fragment Local Vocabulary Set-to-Set Rerank：用局部 token 集合／OT或Chamfer类集合距离增强 R1 精排。
```

- block 1415 · table_cell_paragraph · body/table35/row13/cell3

```text
P2 储备
```

- block 1416 · table_cell_paragraph · body/table35/row13/cell4

```text
IDEA
```

- block 1417 · table_cell_paragraph · body/table35/row14/cell1

```text
INNO-44
```

- block 1418 · table_cell_paragraph · body/table35/row14/cell2

```text
Complementarity-Aware R2 Verifier：相同表面形状 + 相反体积占据 + 接触／穿透约束的高成本物理核验。
```

- block 1419 · table_cell_paragraph · body/table35/row14/cell3

```text
P1 可靠性
```

- block 1420 · table_cell_paragraph · body/table35/row14/cell4

```text
RESEARCH_CANDIDATE
```

- block 1421 · table_cell_paragraph · body/table35/row15/cell1

```text
INNO-45
```

- block 1422 · table_cell_paragraph · body/table35/row15/cell2

```text
Topology/Relation Distillation：从 geometry/contact-centric 3D teacher 蒸馏关系结构到主干。
```

- block 1423 · table_cell_paragraph · body/table35/row15/cell3

```text
P2 储备
```

- block 1424 · table_cell_paragraph · body/table35/row15/cell4

```text
IDEA
```

### A6.24 本次增补的外部来源与复现优先级

- block 1426 · paragraph · body

```text
A6.24 本次增补的外部来源与复现优先级
```

- block 1427 · paragraph · body

```text
来源分为两类：会议／期刊正式论文用于建立强对照，2026 年预印本用于跟踪最新方向。预印本在正式投稿前必须再次核验版本、发表状态和结论；不得把预印本结果写成社区共识。建议优先阅读／复现顺序为：SARe → PuzzleFusion++ → GARF → Combinative Matching / Rectified Point Flow → MHopReg → Jigsaw++ / Beyond Reassembly → Bag of Bags → Coconut / VisMem / WorldMM / Titans → TORA / MV-RoMa。
```

- block 1428 · paragraph · body

```text
1. Jia et al. SARe: Structure-Aware Large-Scale 3D Fragment Reassembly. arXiv:2603.21611, 2026.
```

- block 1429 · paragraph · body

```text
2. Wang, Chen, Furukawa. PuzzleFusion++: Auto-agglomerative 3D Fracture Assembly by Denoise and Verify. ICLR 2025.
```

- block 1430 · paragraph · body

```text
3. Li et al. GARF: Learning Generalizable 3D Reassembly for Real-World Fractures. ICCV 2025.
```

- block 1431 · paragraph · body

```text
4. Sun et al. Rectified Point Flow: Generic Point Cloud Pose Estimation. NeurIPS 2025 Spotlight; arXiv:2506.05282.
```

- block 1432 · paragraph · body

```text
5. Lee et al. Combinative Matching for Geometric Shape Assembly. ICCV 2025 Highlight. DOI: 10.1109/ICCV51701.2025.00890.
```

- block 1433 · paragraph · body

```text
6. Lee et al. TORA: Topological Representation Alignment for 3D Shape Assembly. arXiv:2604.04050, 2026.
```

- block 1434 · paragraph · body

```text
7. Lu, Hua, Huang. Jigsaw++: Imagining Complete Shape Priors for Object Reassembly. ICCV 2025.
```

- block 1435 · paragraph · body

```text
8. Xu et al. Beyond Reassembly: Fractured Object Recovery with Missing Parts. CVPR 2026.
```

- block 1436 · paragraph · body

```text
9. Wu et al. MHopReg: Efficient Hierarchical Multi-Hop Graph Search for Point Cloud Registration. CVPR 2026.
```

- block 1437 · paragraph · body

```text
10. Lee, Kang, Yoo. MV-RoMa: From Pairwise Matching into Multi-View Track Reconstruction. arXiv:2603.27542, 2026.
```

- block 1438 · paragraph · body

```text
11. Gogawale et al. Bag of Bags: Adaptive Visual Vocabularies for Genizah Join Image Retrieval. CVPR Workshops 2026.
```

- block 1439 · paragraph · body

```text
12. Yu et al. Mitigating spurious features by contrastive learning in pottery sherd recognition. npj Heritage Science 14, 135 (2026).
```

- block 1440 · paragraph · body

```text
13. Hao et al. Training Large Language Models to Reason in a Continuous Latent Space (Coconut). arXiv:2412.06769; ICLR 2025 Workshop.
```

- block 1441 · paragraph · body

```text
14. Behrouz, Zhong, Mirrokni. Titans: Learning to Memorize at Test Time. NeurIPS 2025.
```

- block 1442 · paragraph · body

```text
15. Yu et al. VisMem: Latent Vision Memory Unlocks Potential of Vision-Language Models. CVPR 2026.
```

- block 1443 · paragraph · body

```text
16. Yeo et al. WorldMM: Dynamic Multimodal Memory Agent for Long Video Reasoning. CVPR 2026.
```

- block 1444 · paragraph · body

```text
本次 A6 增补状态：仅完成长期创新区的思想登记、架构假设、参考映射与最小实验合同；未改变 A1–A5、A7 以后正文、现有历史实验判决、A12 合成平台事实状态或比赛稳定主线。
```

### A6.25 Whole-Vessel Membership Recovery：从一块碎片恢复整个器物成员集合

- block 1445 · paragraph · body

```text
A6.25 Whole-Vessel Membership Recovery：从一块碎片恢复整个器物成员集合
```

- block 1446 · paragraph · body

```text
长期主任务定义为Fragment-to-Vessel Membership Recovery：输入任意查询碎片q和混合图库G，输出G中与q属于同一器物的预测成员集合V_hat(q)，并区分其中直接历史邻接R2与非直接邻接R1。该任务不要求一次性输出完整几何装配；它首先研究“哪些碎片属于一起”，再把几何装配作为可选后续。这样既贴合专家实际搜索负担，也把研究问题从pairwise similarity提升为set recovery与relational retrieval。
```

- block 1448 · table_cell_paragraph · body/table36/row1/cell1

```text
阶段
```

- block 1449 · table_cell_paragraph · body/table36/row1/cell2

```text
核心操作
```

- block 1450 · table_cell_paragraph · body/table36/row1/cell3

```text
研究意义
```

- block 1451 · table_cell_paragraph · body/table36/row2/cell1

```text
Seed retrieval
```

- block 1452 · table_cell_paragraph · body/table36/row2/cell2

```text
从q召回高置信R2和same-vessel种子
```

- block 1453 · table_cell_paragraph · body/table36/row2/cell3

```text
建立第一批可靠局部证据；不追求一次找全。
```

- block 1454 · table_cell_paragraph · body/table36/row3/cell1

```text
Local component formation
```

- block 1455 · table_cell_paragraph · body/table36/row3/cell2

```text
把通过验证的R2软写入R2 Local Memory
```

- block 1456 · table_cell_paragraph · body/table36/row3/cell3

```text
得到局部组件，但R2不传递。
```

- block 1457 · table_cell_paragraph · body/table36/row4/cell1

```text
Vessel hypothesis
```

- block 1458 · table_cell_paragraph · body/table36/row4/cell2

```text
由已接受/高置信成员建立Vessel Identity Memory
```

- block 1459 · table_cell_paragraph · body/table36/row4/cell3

```text
形成材质、壁厚、曲率、纹样体系和器型趋势等器物级条件。
```

- block 1460 · table_cell_paragraph · body/table36/row5/cell1

```text
Database re-search
```

- block 1461 · table_cell_paragraph · body/table36/row5/cell2

```text
用q + 当前器物假设重新扫描全库
```

- block 1462 · table_cell_paragraph · body/table36/row5/cell3

```text
寻找与q不接触但与整体器物假设兼容的R1。
```

- block 1463 · table_cell_paragraph · body/table36/row6/cell1

```text
Joint reread
```

- block 1464 · table_cell_paragraph · body/table36/row6/cell2

```text
新成员加入后重读旧边、冲突与缺失证据
```

- block 1465 · table_cell_paragraph · body/table36/row6/cell3

```text
允许早期关系降级、撤回或恢复，控制级联错误。
```

- block 1466 · table_cell_paragraph · body/table36/row7/cell1

```text
Stop/abstain
```

- block 1467 · table_cell_paragraph · body/table36/row7/cell2

```text
边际收益低、风险高、预算耗尽或无新证据时停止
```

- block 1468 · table_cell_paragraph · body/table36/row7/cell3

```text
避免为了高Recall无限扩张集合。
```

### A6.26 High-Degradation Robust Retrieval：高磨损、风化与部分观测下的鲁棒碎片检索

- block 1470 · paragraph · body

```text
A6.26 High-Degradation Robust Retrieval：高磨损、风化与部分观测下的鲁棒碎片检索
```

- block 1471 · paragraph · body

```text
第二条核心研究主线是“证据被物理过程破坏后模型还能保留多少检索能力”。传统几何算法在完整断口、可靠3D和高重叠条件下必须作为强基线；RelicWeave的研究价值不在于清晰样本多赢几个百分点，而在于随着断口磨圆、崩缺、表面侵蚀、纹样缺失、成像噪声和3D重建伪影增强，性能下降是否显著慢于传统精确匹配和普通静态网络。
```

- block 1473 · table_cell_paragraph · body/table37/row1/cell1

```text
退化层级
```

- block 1474 · table_cell_paragraph · body/table37/row1/cell2

```text
控制内容
```

- block 1475 · table_cell_paragraph · body/table37/row1/cell3

```text
要回答的问题
```

- block 1476 · table_cell_paragraph · body/table37/row2/cell1

```text
D0 Clean
```

- block 1477 · table_cell_paragraph · body/table37/row2/cell2

```text
断口与表面证据完整
```

- block 1478 · table_cell_paragraph · body/table37/row2/cell3

```text
建立传统方法和学习方法的上限；允许传统法胜出。
```

- block 1479 · table_cell_paragraph · body/table37/row3/cell1

```text
D1 Mild wear
```

- block 1480 · table_cell_paragraph · body/table37/row3/cell2

```text
轻度磨圆/轻纹理损伤
```

- block 1481 · table_cell_paragraph · body/table37/row3/cell3

```text
观察第一处性能分离点。
```

- block 1482 · table_cell_paragraph · body/table37/row4/cell1

```text
D2 Local chipping
```

- block 1483 · table_cell_paragraph · body/table37/row4/cell2

```text
局部崩边/缺口
```

- block 1484 · table_cell_paragraph · body/table37/row4/cell3

```text
测试局部对应丢失时的多模态补偿。
```

- block 1485 · table_cell_paragraph · body/table37/row5/cell1

```text
D3 Partial fracture loss
```

- block 1486 · table_cell_paragraph · body/table37/row5/cell2

```text
20–40%断口信息不可见或缺失
```

- block 1487 · table_cell_paragraph · body/table37/row5/cell3

```text
测试partial observation与拒识。
```

- block 1488 · table_cell_paragraph · body/table37/row6/cell1

```text
D4 Severe mixed degradation
```

- block 1489 · table_cell_paragraph · body/table37/row6/cell2

```text
磨损+崩缺+表面退化+成像噪声
```

- block 1490 · table_cell_paragraph · body/table37/row6/cell3

```text
测试关系上下文和Vessel Memory是否提供额外鲁棒性。
```

- block 1491 · table_cell_paragraph · body/table37/row7/cell1

```text
D5 Real domain
```

- block 1492 · table_cell_paragraph · body/table37/row7/cell2

```text
真实自然风化/真实采集误差
```

- block 1493 · table_cell_paragraph · body/table37/row7/cell3

```text
只作为独立确认；不能用合成D级替代。
```

### A6.27 统一论文路线：共享一个问题族，不把所有创新强塞进一篇论文

- block 1495 · paragraph · body

```text
A6.27 统一论文路线：共享一个问题族，不把所有创新强塞进一篇论文
```

- block 1496 · paragraph · body

```text
V1.47把科研方向整理成一个问题族：低质量碎片如何从局部接触证据逐步恢复器物身份。具体投稿时只选择证据最强的一条主贡献，其他机制降为支撑或后续工作。文化遗产是高价值真实场景，但CVPR级论文必须把任务抽象为可推广的视觉问题，并用强基线、真实退化、机制消融和跨域/跨采集验证证明贡献。
```

- block 1498 · table_cell_paragraph · body/table38/row1/cell1

```text
论文候选
```

- block 1499 · table_cell_paragraph · body/table38/row1/cell2

```text
核心问题
```

- block 1500 · table_cell_paragraph · body/table38/row1/cell3

```text
必须证据
```

- block 1501 · table_cell_paragraph · body/table38/row1/cell4

```text
止损条件
```

- block 1502 · table_cell_paragraph · body/table38/row2/cell1

```text
PAPER-A：Robust Fragment Retrieval under Physical Degradation
```

- block 1503 · table_cell_paragraph · body/table38/row2/cell2

```text
退化鲁棒检索
```

- block 1504 · table_cell_paragraph · body/table38/row2/cell3

```text
性能—退化强度曲线；传统几何/静态AI/新方法公平对照；Synthetic→Real。
```

- block 1505 · table_cell_paragraph · body/table38/row2/cell4

```text
若真实退化没有稳定增益，转为数据/应用论文。
```

- block 1506 · table_cell_paragraph · body/table38/row3/cell1

```text
PAPER-B：Contact-Conditioned Vessel Identity Expansion
```

- block 1507 · table_cell_paragraph · body/table38/row3/cell2

```text
R2→R1 / UA-IFRMN
```

- block 1508 · table_cell_paragraph · body/table38/row3/cell3

```text
Oracle-R2→Predicted-R2→Corrupted-R2；证明局部接触上下文对R1有信息且可安全利用。
```

- block 1509 · table_cell_paragraph · body/table38/row3/cell4

```text
若Oracle-R2都不能提升R1，停止该主张。
```

- block 1510 · table_cell_paragraph · body/table38/row4/cell1

```text
PAPER-C：Fragment-to-Vessel Membership Recovery
```

- block 1511 · table_cell_paragraph · body/table38/row4/cell2

```text
整器物成员恢复新任务/集合检索
```

- block 1512 · table_cell_paragraph · body/table38/row4/cell3

```text
Vessel Precision/Recall/F1；不同成员数和库规模；set/graph/metric学习强基线。
```

- block 1513 · table_cell_paragraph · body/table38/row4/cell4

```text
若任务GT无法闭合或只在单器型有效，先不宣称通用任务。
```

- block 1514 · table_cell_paragraph · body/table38/row5/cell1

```text
PAPER-D：Physics-Guided Synthetic-to-Real Pretraining
```

- block 1515 · table_cell_paragraph · body/table38/row5/cell2

```text
A12/VesselForge/PG-Frag
```

- block 1516 · table_cell_paragraph · body/table38/row5/cell3

```text
物理合理碎裂+退化预训练是否降低真实样本需求并提升跨域鲁棒性。
```

- block 1517 · table_cell_paragraph · body/table38/row5/cell4

```text
若synthetic-pretrain无真实收益，只保留为实验基础设施。
```

- block 1518 · table_cell_paragraph · body/table38/row6/cell1

```text
PAPER-E：Active Evidence Acquisition
```

- block 1519 · table_cell_paragraph · body/table38/row6/cell2

```text
候选条件主动补采
```

- block 1520 · table_cell_paragraph · body/table38/row6/cell3

```text
同照片/同时间预算下减少错误并提高成员恢复。
```

- block 1521 · table_cell_paragraph · body/table38/row6/cell4

```text
没有可交互真实数据前不作为主论文。
```

### A6.28 顶会级研究门槛与禁止性表述

- block 1523 · paragraph · body

```text
A6.28 顶会级研究门槛与禁止性表述
```

- block 1524 · paragraph · body

```text
进入CVPR/ICCV等主会级主线前至少需要：①真实或可信独立域数据，不能只靠合成；②与传统几何、强检索、set/graph模型和最接近碎片方法的同输入对照；③预注册或冻结的主指标和独立确认；④机制消融能够排除“只是更多参数/更多照片/更多计算”；⑤退化、库规模、成员数和hard negative分层；⑥失败案例与适用域。禁止写“首次使用自回归做碎片”“首次把预测关系反馈回网络”等高风险新颖性断言；真正可能成立的主张应收敛到高退化下的关系记忆、R2条件的器物身份扩展或整器物成员恢复。
```

### EXP10 高磨损/风化鲁棒性基准

- block 1579 · paragraph · body

```text
EXP10 高磨损/风化鲁棒性基准
```

- block 1580 · paragraph · body

```text
冻结同一批query、gallery、GT、训练预算和观测权限，建立D0→Dn配对退化阶梯。最低对照包括人工可观察性、ICP/GICP或等价传统配准、FPFH/SHOT或其他合法局部描述子、曲率/轮廓基线、静态深度检索和当前RelicWeave。主输出为Hit/CovRecall/Same-Vessel与Vessel指标随退化强度的曲线、失败转移点和真实域确认。清晰档传统算法强不算失败；只有高退化档出现稳定且可归因优势，才能写“AI在该场景增加价值”。
```

### EXP11 整器物成员恢复（Vessel Membership Recovery）

- block 1581 · paragraph · body

```text
EXP11 整器物成员恢复（Vessel Membership Recovery）
```

- block 1582 · paragraph · body

```text
只使用member set闭合的母体。给定单个query，系统从空或最小seed开始迭代检索，输出R2、R1和最终V_hat(q)。比较pairwise retrieval、简单聚类/metric learning、set/graph baseline、静态vessel prototype和UA-IFRMN候选。报告Vessel Precision/Recall/F1、完整找回率、首个错误成员进入轮次、迭代次数、查询墙钟和专家需要核验的候选数。不同器物成员数、图库规模、材质和器型分层。
```

### EXP12 R2→R1关系上下文与错误传播

- block 1583 · paragraph · body

```text
EXP12 R2→R1关系上下文与错误传播
```

- block 1584 · paragraph · body

```text
第一步Oracle-R2：只替换关系上下文，不改视觉输入，验证真实邻接上下文能否提升R1/same-vessel；第二步Predicted-R2：换成模型预测并保留posterior、quality与relation latent；第三步Corrupted-R2：按0/5/10/20/30%注入错边、漏边和不完整memory。比较Scalar Feedback、Latent Feedback、Neighbor Set、Soft Graph、Vessel Memory与Reversible Memory。若Oracle无增益则暂停；若预测闭环增益只在无错边成立，则不能进入部署。
```

### A12.21 V1.47退化性能曲线：把SyntheticLab变成“物理退化压力测试仪”

- block 2200 · paragraph · body

```text
A12.21 V1.47退化性能曲线：把SyntheticLab变成“物理退化压力测试仪”
```

- block 2201 · paragraph · body

```text
A12新增一类paired counterfactual release：同一clean母体、同一碎片关系、同一query/gallery与基础随机种子，沿磨损、崩缺、表面侵蚀、遮挡、图像质量、3D缺失/增生噪点等单轴或预注册组合轴生成D0→Dn观测。每个release必须同时提供传统算法合法输入、学习模型合法输入和TruthPack，但TruthPack只供评测。输出不仅是某一档准确率，而是每个方法的性能—退化强度曲线、临界失效点、AUC/斜率型诊断和真实域对应样本。
```

### A12.22 Whole-Vessel Episode Generator：为整器物成员恢复生成完整关系世界

- block 2202 · paragraph · body

```text
A12.22 Whole-Vessel Episode Generator：为整器物成员恢复生成完整关系世界
```

- block 2203 · paragraph · body

```text
每个合成母体除R2边外，还必须导出完整member set、R1/R2 typed relation graph、可见/不可见断面、缺失材料和母体级属性。episode生成器把多个母体混成gallery，随机选择query并控制同器物成员数、R1/R2比例、hard negative密度、器型相似度、材质相似度和退化分布；训练端只看合法Obs，评测端用完整Truth计算Vessel Precision/Recall/F1及多轮扩展轨迹。这样A12的数据价值从“更多pair”升级为“可控整器物关系规模”。
```

### A12.23 Synthetic-to-Real与数据充分性：最终只以真实域收益决定扩容

- block 2204 · paragraph · body

```text
A12.23 Synthetic-to-Real与数据充分性：最终只以真实域收益决定扩容
```

- block 2205 · paragraph · body

```text
合成预训练的正式价值判断改为三条：①在相同真实标注量下是否提高真实高退化R2/R1与Vessel指标；②达到同一真实目标性能所需的真实母体/碎片量是否下降；③跨相机、材料、器型或自然风化域是否更稳。若10万/50万合成碎片不能在这些真实指标上带来收益，则停止扩容并审计生成分布、shortcut和任务错位，不用合成规模本身作为成果。
```

### B2.3 器物成员集合GT与关系闭合

- block 2267 · paragraph · body

```text
B2.3 器物成员集合GT与关系闭合
```

- block 2268 · paragraph · body

```text
Level 3评测要求每个eligible object拥有member_manifest：object_id、全部已入库fragment_id、已知missing_fragment/碎屑去向、member_set_complete、R2边集合、R1定义域、UNKNOWN/争议关系、复核者、label_version与hash。V_G(q)从该manifest派生，不能从模型结果反推。若某母体只知道若干邻接但不知道是否还有同器物碎片遗失或未入库，则只能参加Level 1/2的限定评测，不能进入完整成员恢复主分母。
```

- block 2269 · paragraph · body

```text
R1是“同器物且无直接历史断裂接触”，不是“暂时拼不上”。因此member_set闭合和R2关系闭合必须分开审计：先确认哪些fragment属于该object，再确认哪些pair有历史直接接触。R2缺边不能自动把pair改成R1；证据不足保留UNKNOWN。
```

### B3 必须采到的数据

- block 2299 · table_cell_paragraph · body/table59/row10/cell1

```text
器物成员GT
```

- block 2300 · table_cell_paragraph · body/table59/row10/cell2

```text
object_id、member_manifest、member_set_complete、全部fragment_id、missing/UNKNOWN、R1/R2关系图、复核与版本hash
```

- block 2301 · table_cell_paragraph · body/table59/row10/cell3

```text
未闭合只做邻片/同器物候选诊断，不进入Whole-Vessel主评测
```

### D6.5 器物成员恢复页（V1.47新增）

- block 3105 · paragraph · body

```text
D6.5 器物成员恢复页（V1.47新增）
```

- block 3106 · paragraph · body

```text
结果页采用“三层视图”而不是把所有候选混在一个Top-K：第一栏Direct Neighbor Candidates只显示R2及局部接触证据；第二栏Same-Vessel Candidates显示R1/R2同器物成员及器物身份支持；第三栏Predicted Vessel Set显示当前已纳入成员、待核验成员、被驳回成员、UNKNOWN、Vessel Precision/Recall仅在有GT的评测模式显示。用户接受/驳回某成员后生成新的revision，系统可以重新检索全库并显示“新增成员导致哪些旧关系被加强、削弱或撤回”。
```

- block 3107 · paragraph · body

```text
比赛演示默认从一块新query开始：采集/导入→全库粗检→R2邻片→形成初始Vessel Memory→发现R1远距离成员→人工核验→成员集更新或停止。若当前模型尚未通过Level 3验证，界面必须标“研究模式/成员候选”，不得把候选集合称为已恢复器物。
```

### D10.2 应用价值、社会价值与AI必要性的证据矩阵

- block 3188 · paragraph · body

```text
D10.2 应用价值、社会价值与AI必要性的证据矩阵
```

- block 3190 · table_cell_paragraph · body/table82/row1/cell1

```text
价值维度
```

- block 3191 · table_cell_paragraph · body/table82/row1/cell2

```text
必须记录
```

- block 3192 · table_cell_paragraph · body/table82/row1/cell3

```text
希望证明的结论
```

- block 3193 · table_cell_paragraph · body/table82/row1/cell4

```text
禁止夸大
```

- block 3194 · table_cell_paragraph · body/table82/row2/cell1

```text
专家搜索负担
```

- block 3195 · table_cell_paragraph · body/table82/row2/cell2

```text
完成一个任务的人时/墙钟、浏览候选数
```

- block 3196 · table_cell_paragraph · body/table82/row2/cell3

```text
RelicWeave相对人工和传统候选是否减少筛查
```

- block 3197 · table_cell_paragraph · body/table82/row2/cell4

```text
机器负责搜索，专家负责最终确认
```

- block 3198 · table_cell_paragraph · body/table82/row3/cell1

```text
实物操作风险
```

- block 3199 · table_cell_paragraph · body/table82/row3/cell2

```text
拿取、翻转、实体试拼次数
```

- block 3200 · table_cell_paragraph · body/table82/row3/cell3

```text
数字筛选后是否减少无意义实体操作
```

- block 3201 · table_cell_paragraph · body/table82/row3/cell4

```text
对脆弱碎片的保护价值
```

- block 3202 · table_cell_paragraph · body/table82/row4/cell1

```text
高退化可用性
```

- block 3203 · table_cell_paragraph · body/table82/row4/cell2

```text
D0→Dn的Hit/Cov/Vessel曲线
```

- block 3204 · table_cell_paragraph · body/table82/row4/cell3

```text
传统方法何时明显下降，RelicWeave是否更平缓
```

- block 3205 · table_cell_paragraph · body/table82/row4/cell4

```text
AI只在传统假设失效场景主张必要性
```

- block 3206 · table_cell_paragraph · body/table82/row5/cell1

```text
整器物恢复
```

- block 3207 · table_cell_paragraph · body/table82/row5/cell2

```text
Vessel Precision/Recall/F1、完整找回率
```

- block 3208 · table_cell_paragraph · body/table82/row5/cell3

```text
能否从单片找回数据库中的同器物成员
```

- block 3209 · table_cell_paragraph · body/table82/row5/cell4

```text
从局部拼接工具升级为器物身份恢复工具
```

- block 3210 · table_cell_paragraph · body/table82/row6/cell1

```text
经济/部署成本
```

- block 3211 · table_cell_paragraph · body/table82/row6/cell2

```text
建库人时、设备摊销、推理、维护、专家复核
```

- block 3212 · table_cell_paragraph · body/table82/row6/cell3

```text
节省的专家时间是否覆盖新增数据和系统成本
```

- block 3213 · table_cell_paragraph · body/table82/row6/cell4

```text
不把“候选缩小”直接换算成ROI
```

- block 3214 · table_cell_paragraph · body/table82/row7/cell1

```text
社会/文化价值
```

- block 3215 · table_cell_paragraph · body/table82/row7/cell2

```text
可恢复器物信息、可减少遗漏、可审计证据
```

- block 3216 · table_cell_paragraph · body/table82/row7/cell3

```text
是否提高文物数字整理与研究效率
```

- block 3217 · table_cell_paragraph · body/table82/row7/cell4

```text
定性价值须由真实从业者访谈/任务证据支持
```

### 10 国赛与CVPR交付计划

- block 3522 · paragraph · body

```text
比赛主交付统一围绕“真实碎片搜索负担”而不是算法名：现场从一块新query开始，完成采集/导入与QA、全库检索、R2邻片候选、R1同器物候选、器物成员集合或证据不足停止，并保留人工核验和版本日志。高磨损场景必须提供传统算法/规则基线和学习方法的公平对照，解释为什么简单样本不需要AI、为什么大库/退化/R1场景需要学习与关系推理。自动采集台、3D、RL、CTM和UA-IFRMN都只有在实测收益成立后才进入比赛主展示。
```

- block 3523 · paragraph · body

```text
论文主交付从“系统功能清单”收敛为一个清楚科学问题。候选主线按证据强度排序：A 高退化条件下的Robust Fragment Retrieval；B R2条件的Contact-Conditioned Vessel Identity Expansion与UA-IFRMN；C Fragment-to-Vessel Membership Recovery；D Physics-Guided Synthetic-to-Real Pretraining；E Active Evidence Acquisition。一次投稿只选一条主贡献，其余作为必要支撑或后续工作；文化遗产应用价值不能替代通用视觉问题、强基线和可归因机制证据。
```

### 10.1 竞赛方向：用“真痛点→真操作→真改进”组织叙事

- block 3526 · paragraph · body

```text
10.1 竞赛方向：用“真痛点→真操作→真改进”组织叙事
```

- block 3527 · paragraph · body

```text
竞赛陈述固定从现实流程开始：海量混合碎片中，专家首先要解决“哪些值得比较、哪些属于同一器物”，而不是直接面对已知正确pair。项目展示顺序应是人工/传统方案的可用边界→高磨损和大库带来的失败→RelicWeave如何缩小候选→如何找到R1远距离成员→如何恢复器物成员集合→专家如何最终确认。技术先进性服务于这个工作流，不把CTM、Transformer、CUDA或硬件数量当价值本身。
```

- block 3529 · table_cell_paragraph · body/table92/row1/cell1

```text
竞赛叙事块
```

- block 3530 · table_cell_paragraph · body/table92/row1/cell2

```text
核心内容
```

- block 3531 · table_cell_paragraph · body/table92/row1/cell3

```text
验收/边界
```

- block 3532 · table_cell_paragraph · body/table92/row2/cell1

```text
痛点证据
```

- block 3533 · table_cell_paragraph · body/table92/row2/cell2

```text
库规模、人工耗时、候选浏览/实物操作、退化样本失败
```

- block 3534 · table_cell_paragraph · body/table92/row2/cell3

```text
至少有真实任务或相关从业者访谈；无行业数据时明确标内部试验。
```

- block 3535 · table_cell_paragraph · body/table92/row3/cell1

```text
AI必要性
```

- block 3536 · table_cell_paragraph · body/table92/row3/cell2

```text
传统算法清晰样本基线 + 高退化/弱对应对照
```

- block 3537 · table_cell_paragraph · body/table92/row3/cell3

```text
允许传统法在D0强；重点看高退化、大库和R1。
```

- block 3538 · table_cell_paragraph · body/table92/row4/cell1

```text
技能展示
```

- block 3539 · table_cell_paragraph · body/table92/row4/cell2

```text
真实采集/QA、模型推理、设备/软件联调、故障恢复、证据核验
```

- block 3540 · table_cell_paragraph · body/table92/row4/cell3

```text
四岗位都有可见技术操作，避免纯PPT讲算法。
```

- block 3541 · table_cell_paragraph · body/table92/row5/cell1

```text
应用价值
```

- block 3542 · table_cell_paragraph · body/table92/row5/cell2

```text
节省筛查时间、减少无意义试拼、提高成员找回、降低遗漏
```

- block 3543 · table_cell_paragraph · body/table92/row5/cell3

```text
全部按完整工作流分母测，不把局部模型指标冒充ROI。
```

- block 3544 · table_cell_paragraph · body/table92/row6/cell1

```text
创新展示
```

- block 3545 · table_cell_paragraph · body/table92/row6/cell2

```text
高退化鲁棒性、整器物成员恢复、关系记忆/主动补采中的已验证部分
```

- block 3546 · table_cell_paragraph · body/table92/row6/cell3

```text
研究候选未通过就标实验模式，不冒充稳定能力。
```

### 10.2 论文方向：一套数据底座，多条可独立收敛的研究问题

- block 3548 · paragraph · body

```text
10.2 论文方向：一套数据底座，多条可独立收敛的研究问题
```

- block 3549 · paragraph · body

```text
优先顺序由实验决定而不是由想法“看起来高级”决定。先跑EXP10退化曲线和EXP11整器物任务，确认问题本身有足够难度和方法空间；再用EXP12判断R2上下文是否真的给R1带来信息。若Oracle-R2上限明显、Predicted-R2能在错边下保持收益，则UA-IFRMN可升级为方法主线；若关系机制不成立，但A12的物理退化预训练在真实域稳定增益，则把Synthetic-to-Real转为主线。
```

- block 3550 · paragraph · body

```text
顶会目标不要求一次把比赛系统所有模块写进论文。最强版本应围绕一个可以被其他视觉任务理解的问题：高退化partial observation、typed relational reasoning、set membership recovery或physics-guided sim-to-real。数据、代码、协议、强基线和负结果比系统模块数量更重要。
```

### 10.3 竞赛与论文共享的证据底座，但结论严格分开

- block 3551 · paragraph · body

```text
10.3 竞赛与论文共享的证据底座，但结论严格分开
```

- block 3552 · paragraph · body

```text
两条路线共享真实数据身份、member/neighbor GT、冻结split、退化压力测试、传统/学习基线和工作流日志。比赛可以强调专家减负、社会价值、可操作性与系统完整；论文只能强调被独立实验支持的方法/任务贡献。比赛演示成功不等于论文创新成立，论文模型增益也不自动证明真实工作流节时。
```

### 11 本次归位与历史记录

- block 3596 · paragraph · body

```text
V1.47统一“高退化鲁棒检索→R2邻片→R1同器物→整器物成员恢复”的最新主线，新增Vessel Membership指标、性能—退化曲线、Oracle/Predicted/Corrupted-R2验证、成员GT、整器物UI和竞赛/论文双路线。该更新覆盖了现行正文中仅以“找到一个邻片”为最终目标的旧叙事，但不删除其仍有效的邻片指标；旧Hit/Cov仍作为Level 1核心指标。历史实验数据、旧FAIL/STOP/NOT_*、A12/VesselForge/PG-Frag接口和已冻结数值全部保留，不因最终目标升级而改写。
```

### BASELINE→USER replacement and deletion context

REPLACED BASELINE block 1 · 
```text
V1.46 A12双子基础设施整合版 2026年10月5日
```

REPLACEMENT USER block 1 · 
```text
V1.47 整器物成员恢复 × 高退化鲁棒检索 × 竞赛/论文双主线整合版  2026年10月7日
```

REPLACED BASELINE block 2 · 
```text
我们研究低质量部分观测下的碎片邻接候选检索。系统从真实碎片照片出发，在混合碎片库中提出值得人工核验的邻片候选；证据不足时，提出有成本约束的补采建议或停止推荐。比赛交付可运行、可恢复的辅助系统，研究交付能够经独立对照验证的方法机制。
```

REPLACEMENT USER block 2 · 
```text
我们研究真实低质量、部分观测与物理退化条件下的文物/器物碎片检索与器物成员恢复。系统从任意一块查询碎片出发，先在混合碎片库中提出直接历史邻片R2候选，再联合二维外观、断口、三维几何、材质、纹样、壁厚、曲率和已发现关系，检索同器物但非直接邻接的R1成员；长期目标是在给定数据库范围内恢复该器物的高置信成员集合。证据不足时系统拒绝强判、给出缺失证据与有成本约束的补采建议。比赛交付强调真实工作流、专家减负与可解释候选；论文交付强调高退化鲁棒检索、R2→R1关系推理、整器物成员恢复和Synthetic-to-Real的可归因机制。
```

REPLACED BASELINE block 88 · 1 文档体系与现行口径
```text
本文件包含总纲、四岗位完整执行正文、软硬件、联调、验收、完整合成实验室、历史附录以及两个独立三维基础设施子项目方案，现行版本统一V1.46。A12给出合成实验编排、预训练与诊断总览；附录G规定A12编排层、退化层、数据与训练流程；附录I规定VesselForge完整方案；附录J规定PG-Frag完整方案；附录H继续保留V1.44问题修订与验收索引。原历史数值、FAIL、STOP和旧协议保留，不能按新口径直接改写。
```

REPLACEMENT USER block 88 · 1 文档体系与现行口径
```text
本文件包含总纲、四岗位完整执行正文、软硬件、联调、验收、完整合成实验室、历史附录以及两个独立三维基础设施子项目方案，现行版本统一V1.47。总纲第2章给出最新统一任务、应用价值边界和评测合同；A6维护长期科研创新；A8把科研假设转成实验卡；A12与附录G负责合成、退化、预训练和诊断；附录I/J分别规定VesselForge与PG-Frag。附录A至F及历史实验段落继续作为冻结证据保留，旧数值与判决不能按V1.47的新目标直接改写。
```

REPLACED BASELINE block 185 · 2 合并主线与边界
```text
主问题是给定真实可获得的观测、候选检查预算和误导风险，如何找回邻片并识别观察不足。输入包括整片2D、断口2D和质量信息；合格3D、可信上下文是可选增强。输出包括有序候选、来源可追溯的证据、待核验状态、补采或停止原因。
```

REPLACEMENT USER block 207 · 2 合并主线与边界
```text
主问题升级为：给定一块真实可获得观测的查询碎片q、一个混合碎片数据库G、候选检查预算和误导风险约束，先可靠找回直接历史邻片R2并识别观察不足，再利用碎片自身多模态证据、已发现局部关系和器物级上下文检索R1，最终尽可能恢复G中与q属于同一物理器物的成员集合V(q)。输入仍以整片2D、断口2D和质量信息为基础；合格3D、可信上下文和主动补采是可选增强。输出从单一Top-K扩展为R2邻片候选、R1同器物非邻片候选、器物成员集合、来源可追溯证据、UNKNOWN/拒识、补采或停止原因。
```

REPLACED BASELINE block 2589 · D10 用户价值测试与成本
```text
比较人工流程、人工加简单候选及人工加新方法证据三种条件。不同难度匹配任务随机交叉分配，避免同一人重复同题记忆优势。记录正确判断耗时、看过候选数、误配漏配、补拍和退出。
```

REPLACEMENT USER block 3182 · D10 用户价值测试与成本
```text
用户价值试验升级为四类条件：纯人工；人工+传统几何/规则候选；人工+静态学习候选；人工+RelicWeave关系/器物成员证据。任务分为直接邻片查找、同器物成员发现和整器物成员恢复三种难度，并按清晰/高退化分层。不同条件随机交叉或顺序平衡，避免同一人重复同题记忆优势。记录正确判断耗时、看过候选数、实物拿取/试拼次数、误配漏配、补拍、退出和最终成员集合质量。
```

REPLACED BASELINE block 2952 · 历史附录使用说明
```text
以下A至F为原实验及工程历史，Q等级、指标、阈值、模型名、资源和判决按当时协议解释，不直接与V1.45合并。当前新工作用第4至9章、G与H，不恢复归档未定义编号或旧门。
```

REPLACEMENT USER block 3604 · 历史附录使用说明
```text
以下A至F为原实验及工程历史，Q等级、指标、阈值、模型名、资源和判决按当时协议解释，不直接与V1.47的新Level 2/3任务合并。V1.47新增的整器物成员恢复、退化鲁棒性与R2→R1指标只对新冻结实验生效；除非专门复跑并保存新manifest，不能从旧Hit@K或旧pair实验反推Vessel Recall、真实高磨损鲁棒性或UA-IFRMN有效。当前新工作用第4至10章、G/H/I/J；历史附件继续用于重现、审计与保护原始证据。
```

DELETED BASELINE block 5 · 
```text
本版在V1.45基础上将A12进一步重构为“合成实验编排与研究层”，正式接入两个可独立演化的三维基础设施子项目：VesselForge负责完整器物、语义纹样、材质与Physics-Ready资产，PG-Frag负责材料/事件驱动的损伤、裂纹、碎裂、断面与碎片动力学。A12不再把器型几何内核和断裂求解器写死在自身代码中，而通过版本化Asset/Job/Result合同调用两个子项目，再完成磨损、成像/重建退化、ObsPack适配、关系采样、预训练与瓶颈诊断。原V1.45的历史数值、FAIL、STOP与NOT_ESTABLISHED判决不变；新增架构与子项目方案仍须按各自Benchmark验收。
```

DELETED BASELINE block 2898 · 10 国赛与CVPR交付计划
```text
比赛主交付包括真实新查询流程、原图与GT审计、稳定基线或成立的新方法、风险与不足、补采增强、四人操作、离线恢复、实测价值和明确适用域。自动采集台、3D、RL及CTM不全部列为最低交付。
```

DELETED BASELINE block 2899 · 10 国赛与CVPR交付计划
```text
论文主交付包括科学问题、最接近工作、同输入强基线、独立主结果、机制消融、质量与缺失、开放库、成本、失败及复现。METHOD-H1局部互补或METHOD-H3候选条件补采选择证据较强者为核心，架构复杂度不是必要条件。
```

## CURRENT_CLOSEOUT→USER

### (no heading)

- block 5 · paragraph · body

```text
V1.47在V1.46双子基础设施版本上统一最新项目主线：将长期最终目标从“找一名邻片”明确升级为“Fragment-to-Vessel Retrieval / Vessel Membership Recovery”，新增高磨损与风化证据下的鲁棒检索主线、传统算法与学习方法的公平退化对照、R2局部接触到R1器物身份扩展、整器物成员级指标、比赛价值验证与CVPR级研究收敛路线。VesselForge、PG-Frag与A12的职责边界保持不变；A12增加对退化性能曲线、完整器物关系episode和Synthetic-to-Real的专门支撑。所有历史实验数值、FAIL、STOP、NOT_SUPPORTED、NOT_ESTABLISHED与冻结协议继续原样保护；本版只更新现行目标、研究候选、实验合同、数据GT、产品展示和交付口径，不用新叙事改写旧结果。
```

### 1.3 V1.47信息优先级与历史数据保护规则

- block 184 · paragraph · body

```text
1.3 V1.47信息优先级与历史数据保护规则
```

- block 185 · paragraph · body

```text
V1.47采用“现行执行正文覆盖过时规划、历史证据只增不改”的双层治理。新的最终目标、比赛叙事和论文方向可以更新现行正文，但不得把历史实验重新解释成已经支持新主张。任何旧结论若与现行任务定义不完全一致，保留原文并标明其适用数据、指标和当时协议；只有新的冻结实验才能产生新的证据结论。
```

- block 187 · table_cell_paragraph · body/table4/row1/cell1

```text
信息层
```

- block 188 · table_cell_paragraph · body/table4/row1/cell2

```text
主要位置
```

- block 189 · table_cell_paragraph · body/table4/row1/cell3

```text
V1.47处理规则
```

- block 190 · table_cell_paragraph · body/table4/row2/cell1

```text
现行目标与执行口径
```

- block 191 · table_cell_paragraph · body/table4/row2/cell2

```text
总纲第1–10章、A1–A12及B/C/D执行正文
```

- block 192 · table_cell_paragraph · body/table4/row2/cell3

```text
允许更新；V1.47优先，用于现在做什么、为什么做、如何验收。
```

- block 193 · table_cell_paragraph · body/table4/row3/cell1

```text
长期科研候选
```

- block 194 · table_cell_paragraph · body/table4/row3/cell2

```text
A6创新维护区、A12研究支线
```

- block 195 · table_cell_paragraph · body/table4/row3/cell3

```text
允许追加、降级、停止；RESEARCH_CANDIDATE不等于已实现或已证明。
```

- block 196 · table_cell_paragraph · body/table4/row4/cell1

```text
冻结实验数据
```

- block 197 · table_cell_paragraph · body/table4/row4/cell2

```text
附录A/B/C及正文引用的历史数值、hash、FAIL/STOP/NOT_*
```

- block 198 · table_cell_paragraph · body/table4/row4/cell3

```text
只允许补充来源、解释边界和新复算记录；禁止删除、润色或用新口径覆盖旧数值。
```

- block 199 · table_cell_paragraph · body/table4/row5/cell1

```text
旧规划与旧默认值
```

- block 200 · table_cell_paragraph · body/table4/row5/cell2

```text
历史附录中的旧设备、排期、岗位、下一步建议
```

- block 201 · table_cell_paragraph · body/table4/row5/cell3

```text
不再指导现行执行；为可追溯性保留，不与V1.47现行口径并列使用。
```

- block 202 · table_cell_paragraph · body/table4/row6/cell1

```text
新任务扩展
```

- block 203 · table_cell_paragraph · body/table4/row6/cell2

```text
整器物成员恢复、高退化鲁棒检索、R2→R1关系推理
```

- block 204 · table_cell_paragraph · body/table4/row6/cell3

```text
从V1.47起生效；除非专门复跑，不能反向声称旧实验已经验证这些目标。
```

### 2.0 最新统一任务定义：从邻片检索到整器物成员恢复

- block 210 · paragraph · body

```text
2.0 最新统一任务定义：从邻片检索到整器物成员恢复
```

- block 211 · paragraph · body

```text
长期最终目标不是“自动把文物粘好”，而是把专家面对的组合搜索问题分成三个可验证层级：先找直接邻片，再找同器物非邻片，最后从任意一片出发恢复数据库范围内的器物成员集合。Level 3只承诺“数据库中已存在碎片的成员恢复”，不等价于几何全自动装配、缺失部分生成或物理修复。
```

- block 213 · table_cell_paragraph · body/table5/row1/cell1

```text
任务层级
```

- block 214 · table_cell_paragraph · body/table5/row1/cell2

```text
输入→输出
```

- block 215 · table_cell_paragraph · body/table5/row1/cell3

```text
主要证据/机制
```

- block 216 · table_cell_paragraph · body/table5/row1/cell4

```text
核心评价
```

- block 217 · table_cell_paragraph · body/table5/row2/cell1

```text
Level 1：R2 Neighbor Retrieval
```

- block 218 · table_cell_paragraph · body/table5/row2/cell2

```text
q + G → 直接历史邻片候选
```

- block 219 · table_cell_paragraph · body/table5/row2/cell3

```text
断口、局部2D/3D、几何互补、接触证据
```

- block 220 · table_cell_paragraph · body/table5/row2/cell4

```text
any@M、Hit@K、CovRecall@K、误导/拒识
```

- block 221 · table_cell_paragraph · body/table5/row3/cell1

```text
Level 2：Same-Vessel Retrieval
```

- block 222 · table_cell_paragraph · body/table5/row3/cell2

```text
q + G → R1 + R2同器物候选
```

- block 223 · table_cell_paragraph · body/table5/row3/cell3

```text
材质、纹样、壁厚、曲率、器型先验、R2上下文
```

- block 224 · table_cell_paragraph · body/table5/row3/cell4

```text
SameVessel Hit@K、Precision/Recall、R1专门召回
```

- block 225 · table_cell_paragraph · body/table5/row4/cell1

```text
Level 3：Vessel Membership Recovery
```

- block 226 · table_cell_paragraph · body/table5/row4/cell2

```text
q + G → 预测成员集合 V_hat(q)
```

- block 227 · table_cell_paragraph · body/table5/row4/cell3

```text
UA-IFRMN关系记忆、Vessel Memory、多轮重检索与可修正关系图
```

- block 228 · table_cell_paragraph · body/table5/row4/cell4

```text
Vessel Recall、Vessel Precision、Vessel F1、误纳入率、迭代成本
```

- block 230 · paragraph · body

```text
统一终态：系统接收任意查询碎片后，先输出“Direct Neighbor Candidates（R2）”和“Same-Vessel Candidates（R1/R2）”，再形成“Predicted Vessel Set”，并在新成员加入后重新读取整个器物假设；当新增证据不足、风险过高或预算耗尽时停止，而不是为了追求找全强行扩展。
```

### 2.1 比赛必须实现与论文需要证明

- block 257 · table_cell_paragraph · body/table6/row9/cell1

```text
高磨损/风化鲁棒性
```

- block 258 · table_cell_paragraph · body/table6/row9/cell2

```text
至少展示清晰、轻度退化、严重退化三档真实或受控样本；同输入比较传统几何基线、简单AI基线与RelicWeave，展示何时传统精确匹配假设开始失效。
```

- block 259 · table_cell_paragraph · body/table6/row9/cell3

```text
冻结退化轴与配对样本，给出性能—退化强度曲线、置信区间、真实域确认和跨设备/材料守卫；不能只挑极端失败样本。
```

- block 260 · table_cell_paragraph · body/table6/row10/cell1

```text
整器物成员恢复
```

- block 261 · table_cell_paragraph · body/table6/row10/cell2

```text
给定一块碎片，界面同时输出R2邻片、R1同器物候选和器物成员集合；人工可逐项接受/驳回，系统更新成员集且保留版本历史。
```

- block 262 · table_cell_paragraph · body/table6/row10/cell3

```text
正式定义Fragment-to-Vessel Membership Recovery任务，建立Vessel Precision/Recall/F1、完整成员覆盖、错误成员注入和迭代成本基线。
```

- block 263 · table_cell_paragraph · body/table6/row11/cell1

```text
AI必要性证据
```

- block 264 · table_cell_paragraph · body/table6/row11/cell2

```text
不宣称所有样本都必须用AI；清晰小规模样本允许传统方法胜出。比赛重点证明在大库、退化、弱对应、R1无直接断口场景下，AI显著减少专家筛查。
```

- block 265 · table_cell_paragraph · body/table6/row11/cell3

```text
公平比较ICP/局部描述子/曲率/轮廓等传统方法、静态深度模型和关系模型；主张限定为“在哪些条件下学习方法产生额外价值”。
```

### 2.2 内部指标合同

- block 304 · table_cell_paragraph · body/table7/row12/cell1

```text
Vessel Recall
```

- block 305 · table_cell_paragraph · body/table7/row12/cell2

```text
预测器物成员集合中找回数据库内真实同器物成员的比例；分母为冻结且闭合的V_G(q)。
```

- block 306 · table_cell_paragraph · body/table7/row12/cell3

```text
长期核心目标；按母体等权宏平均，并报告成员数分层。
```

- block 307 · table_cell_paragraph · body/table7/row13/cell1

```text
Vessel Precision
```

- block 308 · table_cell_paragraph · body/table7/row13/cell2

```text
预测成员集合中真实同器物成员的比例。
```

- block 309 · table_cell_paragraph · body/table7/row13/cell3

```text
防止“把整个库都收进来”换高Recall；与Recall同时冻结阈值。
```

- block 310 · table_cell_paragraph · body/table7/row14/cell1

```text
Vessel F1
```

- block 311 · table_cell_paragraph · body/table7/row14/cell2

```text
Vessel Precision与Vessel Recall的调和平均。
```

- block 312 · table_cell_paragraph · body/table7/row14/cell3

```text
用于集合恢复单值摘要，不替代Precision/Recall与风险曲线。
```

- block 313 · table_cell_paragraph · body/table7/row15/cell1

```text
Degradation Robustness Curve
```

- block 314 · table_cell_paragraph · body/table7/row15/cell2

```text
同一底层query/gallery/GT在D0→Dn退化强度下的主指标轨迹。
```

- block 315 · table_cell_paragraph · body/table7/row15/cell3

```text
比较传统算法、静态AI和RelicWeave的性能下降速度；真实退化另单列确认。
```

- block 316 · table_cell_paragraph · body/table7/row16/cell1

```text
R2→R1 Context Gain
```

- block 317 · table_cell_paragraph · body/table7/row16/cell2

```text
同一输入下，加入GT/预测R2上下文前后R1或same-vessel指标差值。
```

- block 318 · table_cell_paragraph · body/table7/row16/cell3

```text
先做Oracle-R2上限，再做Predicted-R2与Corrupted-R2；若Oracle也无增益则暂停该机制。
```

### 2.2.2 器物成员恢复指标、完整分母与退化曲线

- block 326 · paragraph · body

```text
2.2.2 器物成员恢复指标、完整分母与退化曲线
```

- block 327 · paragraph · body

```text
对query q定义V_G(q)为冻结图库G中与q属于同一器物的全部可评成员，包含R1和R2但排除q自身；预测集合为V_hat(q)。VesselRecall=|V_hat∩V_G|/|V_G|，VesselPrecision=|V_hat∩V_G|/|V_hat|，VesselF1按二者调和平均。只有object membership已闭合、缺失实物去向已记录且UNKNOWN不被强行归类的母体，才进入Level 3主评测。天然残片若无法证明成员全集完整，可报告候选检索和专家工作流，但不能声称完整器物恢复率。
```

- block 328 · paragraph · body

```text
退化鲁棒性主实验必须使用paired/counterfactual设计：D0、D1…Dn共享同一母体、关系GT、query、gallery组成和基础随机种子，只改变预注册的磨损、崩缺、缺失、成像或重建退化轴。传统算法、静态学习基线和RelicWeave在相同合法观测权限下比较；不能给传统算法更差输入，也不能让模型读取clean/oracle信息。
```

### 2.4 痛点、应用价值与“为什么需要AI”的边界

- block 333 · paragraph · body

```text
2.4 痛点、应用价值与“为什么需要AI”的边界
```

- block 334 · paragraph · body

```text
V1.47不再用“AI比传统算法先进”作为价值论证。项目的真实痛点是：当碎片数量大、来源混杂、断口被长期风化磨损、局部对应缺失、R1本来就没有直接接触面时，专家需要在巨大的组合空间中反复筛查；传统几何方法在清晰且对应充分的样本上仍然是强基线，但其精确匹配假设在高退化和弱对应条件下可能失效。RelicWeave的目标是把机器用于海量筛选、弱证据融合、排序、不确定性与关系推理，把专家从“搜索者”转为“验证者”，而不是取消专家的最终判断。
```

- block 336 · table_cell_paragraph · body/table8/row1/cell1

```text
场景
```

- block 337 · table_cell_paragraph · body/table8/row1/cell2

```text
传统/人工方案
```

- block 338 · table_cell_paragraph · body/table8/row1/cell3

```text
RelicWeave应增加的能力
```

- block 339 · table_cell_paragraph · body/table8/row1/cell4

```text
可验证价值
```

- block 340 · table_cell_paragraph · body/table8/row2/cell1

```text
小规模、清晰、断口完整
```

- block 341 · table_cell_paragraph · body/table8/row2/cell2

```text
人工/ICP/曲率/局部描述子可能已足够
```

- block 342 · table_cell_paragraph · body/table8/row2/cell3

```text
AI不是必须；作为强基线和成本下限
```

- block 343 · table_cell_paragraph · body/table8/row2/cell4

```text
证明项目没有“为了AI而AI”
```

- block 344 · table_cell_paragraph · body/table8/row3/cell1

```text
大规模混合碎片库
```

- block 345 · table_cell_paragraph · body/table8/row3/cell2

```text
人工组合搜索随库规模快速变难
```

- block 346 · table_cell_paragraph · body/table8/row3/cell3

```text
向量检索+学习排序缩小候选空间
```

- block 347 · table_cell_paragraph · body/table8/row3/cell4

```text
减少专家浏览、比较与实物搬动
```

- block 348 · table_cell_paragraph · body/table8/row4/cell1

```text
高磨损/崩缺/风化
```

- block 349 · table_cell_paragraph · body/table8/row4/cell2

```text
精确几何对应和手工描述子受损
```

- block 350 · table_cell_paragraph · body/table8/row4/cell3

```text
多模态表征+不确定性+退化训练
```

- block 351 · table_cell_paragraph · body/table8/row4/cell4

```text
在证据残缺时保持更平缓的性能退化
```

- block 352 · table_cell_paragraph · body/table8/row5/cell1

```text
R1同器物非邻接
```

- block 353 · table_cell_paragraph · body/table8/row5/cell2

```text
断口没有直接对应，局部几何无法单独判断
```

- block 354 · table_cell_paragraph · body/table8/row5/cell3

```text
Vessel Memory+关系图+多跳身份推理
```

- block 355 · table_cell_paragraph · body/table8/row5/cell4

```text
从“找邻片”扩展到“找同器物成员”
```

- block 356 · table_cell_paragraph · body/table8/row6/cell1

```text
证据不足/高风险样本
```

- block 357 · table_cell_paragraph · body/table8/row6/cell2

```text
强行匹配会增加误导与不必要试拼
```

- block 358 · table_cell_paragraph · body/table8/row6/cell3

```text
校准、拒识、主动补采
```

- block 359 · table_cell_paragraph · body/table8/row6/cell4

```text
降低错误候选和脆弱实物反复操作
```

### A6.14 2025–2026 近邻任务与跨领域前沿工作增补参考池

- block 1051 · paragraph · body

```text
A6.14 2025–2026 近邻任务与跨领域前沿工作增补参考池
```

- block 1052 · paragraph · body

```text
本节是 A6 长期创新区的“外部思想增补池”，只记录能够改变本项目问题建模、记忆结构、关系推理、验证方式或实验设计的机制。所有条目均作为 RESEARCH_REFERENCE，不代表已经适用于 RelicWeave，更不代表已经验证有效。采用顺序固定为：先复现／理解原机制 → 映射到本项目的错误模式 → 提出最小可否定假设 → 单独消融 → 只有真实低质量与独立母体上成立后才允许进入主线。
```

- block 1054 · table_cell_paragraph · body/table26/row1/cell1

```text
参考工作
```

- block 1055 · table_cell_paragraph · body/table26/row1/cell2

```text
原工作关键机制
```

- block 1056 · table_cell_paragraph · body/table26/row1/cell3

```text
对 RelicWeave 的可借鉴点与价值
```

- block 1057 · table_cell_paragraph · body/table26/row1/cell4

```text
明确不直接照搬的边界
```

- block 1058 · table_cell_paragraph · body/table26/row2/cell1

```text
SARe: Structure-Aware Large-Scale 3D Fragment Reassembly（2026，arXiv:2603.21611）
```

- block 1059 · table_cell_paragraph · body/table26/row2/cell2

```text
联合预测 fracture-surface token probability 与 inter-fragment contact graph；推理期用几何一致性验证候选接触边，只固定可靠子结构，并对其余不确定部分重采样。
```

- block 1060 · table_cell_paragraph · body/table26/row2/cell3

```text
直接说明“大规模碎片下错误邻接会产生级联失败”，因此预测关系不能写成永久事实；本项目可借鉴“先预测—再验证—只软写入可靠结构—不确定部分允许重算”的闭环。
```

- block 1061 · table_cell_paragraph · body/table26/row2/cell4

```text
不直接搬其生成式完整装配流程；RelicWeave 的主问题是 R2 邻接候选与 R1 同器物非邻接检索，而非全局 6-DoF 完整拼装。
```

- block 1062 · table_cell_paragraph · body/table26/row3/cell1

```text
PuzzleFusion++: Auto-agglomerative 3D Fracture Assembly by Denoise and Verify（ICLR 2025）
```

- block 1063 · table_cell_paragraph · body/table26/row3/cell2

```text
从单碎片开始，经扩散模型求位姿、Transformer 验证 pair，再把可信碎片合并成更大组并迭代重复，作者明确将其类比为 auto-regressive / auto-agglomerative assembly。
```

- block 1064 · table_cell_paragraph · body/table26/row3/cell3

```text
支持“局部关系 → 局部组件 → 更大组件”的逐步扩展思想，可作为本项目从 R2 局部邻接扩展到同器物集合的强概念对照。
```

- block 1065 · table_cell_paragraph · body/table26/row3/cell4

```text
不能把“自回归碎片推理”本身当新颖点；其 hard merge 也不应直接复制，因为本项目的低质输入更容易发生错误传播。
```

- block 1066 · table_cell_paragraph · body/table26/row4/cell1

```text
GARF: Learning Generalizable 3D Reassembly for Real-World Fractures（ICCV 2025）
```

- block 1067 · table_cell_paragraph · body/table26/row4/cell2

```text
fracture-aware pretraining + flow matching + one-step preassembly，并用陶瓷、骨骼、蛋壳、石器等真实断裂数据检验跨域泛化。
```

- block 1068 · table_cell_paragraph · body/table26/row4/cell3

```text
强化“断口必须有专门预训练与真实断裂迁移验证”的原则；可为 R2 Local Memory 的断口 token、A12 合成到真实课程学习及跨材料评测提供强对照。
```

- block 1069 · table_cell_paragraph · body/table26/row4/cell4

```text
不把 flow matching 当作 R1 主干；其重点是位姿恢复，而本项目要保留 membership / retrieval 问题独立性。
```

- block 1070 · table_cell_paragraph · body/table26/row5/cell1

```text
Rectified Point Flow: Generic Point Cloud Pose Estimation（NeurIPS 2025 Spotlight）
```

- block 1071 · table_cell_paragraph · body/table26/row5/cell2

```text
把 pairwise registration 与 multi-part assembly 统一成条件生成的 point-wise rectified flow，并使用面向 overlap 的自监督编码器。
```

- block 1072 · table_cell_paragraph · body/table26/row5/cell3

```text
启发 R2 分支优先学习“接触／重叠相关局部几何”而非只学习通用对象语义；也可作为 3D 几何验证或辅助教师特征来源。
```

- block 1073 · table_cell_paragraph · body/table26/row5/cell4

```text
不把 point flow 直接当成 R1 身份检索器；R1 可能完全没有直接接触或 overlap。
```

- block 1074 · table_cell_paragraph · body/table26/row6/cell1

```text
Combinative Matching for Geometric Shape Assembly（ICCV 2025 Highlight）
```

- block 1075 · table_cell_paragraph · body/table26/row6/cell2

```text
显式同时建模“相同表面形状”与“相反体积占据”，并通过等变方向估计减少局部匹配歧义。
```

- block 1076 · table_cell_paragraph · body/table26/row6/cell3

```text
非常适合转化为 R2 高成本物理 verifier：不仅看表面像不像，还检查几何互补与空间占据是否真的允许咬合。
```

- block 1077 · table_cell_paragraph · body/table26/row6/cell4

```text
只用于接触验证与局部互补证据，不应把“可咬合”误写成同器物身份的全部依据。
```

- block 1078 · table_cell_paragraph · body/table26/row7/cell1

```text
TORA: Topological Representation Alignment for 3D Shape Assembly（2026，arXiv:2604.04050）
```

- block 1079 · table_cell_paragraph · body/table26/row7/cell2

```text
从冻结的预训练 3D encoder 蒸馏关系／拓扑结构到 flow backbone；使用 token cosine 或 CKA 对齐，并报告 geometry/contact-centric teacher property 比语义分类能力更关键。
```

- block 1080 · table_cell_paragraph · body/table26/row7/cell3

```text
支持本项目把 geometry/contact relation token 独立保留，并允许用教师关系结构训练主干，而不是把所有 3D 信息压成一个 global semantic vector。
```

- block 1081 · table_cell_paragraph · body/table26/row7/cell4

```text
当前作为预印本思想来源；若采用必须单独验证 teacher 选择、蒸馏损失和推理增益，不能因“拓扑对齐”名称直接写成贡献。
```

- block 1082 · table_cell_paragraph · body/table26/row8/cell1

```text
Jigsaw++: Imagining Complete Shape Priors for Object Reassembly（ICCV 2025）
```

- block 1083 · table_cell_paragraph · body/table26/row8/cell2

```text
从部分组装结果生成完整 shape prior，并通过 retargeting 把完整对象先验与现有 assembly 结果连接。
```

- block 1084 · table_cell_paragraph · body/table26/row8/cell3

```text
支持建立 Vessel Identity Memory / Vessel Latent：R1 的远距离同器物判断不应只看 pair，应利用“当前已知碎片共同暗示的器物整体”。
```

- block 1085 · table_cell_paragraph · body/table26/row8/cell4

```text
其论文也指出如何把生成的完整形状进一步作为后续重组指导仍是开放方向，因此本项目若使用必须以“先验能否改善 R1 检索”做独立验证。
```

- block 1086 · table_cell_paragraph · body/table26/row9/cell1

```text
Beyond Reassembly: Fractured Object Recovery with Missing Parts（CVPR 2026）
```

- block 1087 · table_cell_paragraph · body/table26/row9/cell2

```text
把已存在碎片与 missing tokens 一起交给 Transformer，联合进行现有部分重组与缺失部分预测；两项任务可互相促进。
```

- block 1088 · table_cell_paragraph · body/table26/row9/cell3

```text
说明“当前可见碎片”与“尚未观察到的器物结构”可以在同一潜空间互相约束。可借鉴为 Vessel Latent 中的 missing/unknown slots，而不是强迫当前组件已经完整。
```

- block 1089 · table_cell_paragraph · body/table26/row9/cell4

```text
不直接把 missing-part generation 设为首版任务；只研究其作为 R1 检索全局先验是否带来可归因增益。
```

- block 1090 · table_cell_paragraph · body/table26/row10/cell1

```text
MHopReg: Efficient Hierarchical Multi-Hop Graph Search for Point Cloud Registration（CVPR 2026）
```

- block 1091 · table_cell_paragraph · body/table26/row10/cell2

```text
在 compatibility graph 上预测对应置信度，从平衡 seed 出发做 hierarchical multi-hop expansion，再结合几何一致性与空间覆盖排序多假设。
```

- block 1092 · table_cell_paragraph · body/table26/row10/cell3

```text
与“高置信 R2 seed → 多跳扩展同器物候选”的图搜索逻辑高度相似。可把它抽象为 Contact-Conditioned Identity Expansion，而不需要复制其 registration 目标。
```

- block 1093 · table_cell_paragraph · body/table26/row10/cell4

```text
多跳只能增加 same-vessel 先验，不能把 R2 当传递关系；所有扩展必须保留类型与不确定性。
```

- block 1094 · table_cell_paragraph · body/table26/row11/cell1

```text
MV-RoMa: From Pairwise Matching into Multi-View Track Reconstruction（2026，arXiv:2603.27542）
```

- block 1095 · table_cell_paragraph · body/table26/row11/cell2

```text
指出 pairwise matching 直接串联会形成碎裂且几何不一致的轨迹；把 pairwise 结果当几何先验后，再进行 multi-view joint refinement。
```

- block 1096 · table_cell_paragraph · body/table26/row11/cell3

```text
直接支持本项目“预测 R2 后不能一路 hard-chain”的设计：pairwise edge 只作为 prior，加入新碎片后应联合重读受影响子图并允许旧边降权或撤销。
```

- block 1097 · table_cell_paragraph · body/table26/row11/cell4

```text
不是碎片论文，借的是“pairwise prior → joint refinement”的机制，而不是图像匹配模块本身。
```

- block 1098 · table_cell_paragraph · body/table26/row12/cell1

```text
Bag of Bags: Adaptive Visual Vocabularies for Genizah Join Image Retrieval（CVPRW 2026）
```

- block 1099 · table_cell_paragraph · body/table26/row12/cell2

```text
给定手稿碎片图像，检索来自同一物理手稿的其他碎片；每个 fragment 保留自己的 local visual vocabulary，并以 Chamfer / OT 做 set-to-set 比较，再用 shortlist→rerank 提高效率。
```

- block 1100 · table_cell_paragraph · body/table26/row12/cell3

```text
任务形式与 R1“同一物理器物、但未必直接接触”的检索很接近。它支持“一块碎片 = 一组局部原型／token，而不是一个 global embedding”，并支持粗检后局部集合重排。
```

- block 1101 · table_cell_paragraph · body/table26/row12/cell4

```text
文化遗产对象与视觉线索不同，不能直接复用其二值化／connected component 管线；只借 local vocabulary 与 set-to-set retrieval 思想。
```

- block 1102 · table_cell_paragraph · body/table26/row13/cell1

```text
Mitigating spurious features by contrastive learning in pottery sherd recognition（npj Heritage Science, 2026）
```

- block 1103 · table_cell_paragraph · body/table26/row13/cell2

```text
在河姆渡陶片数据中研究 spurious feature；采用 supervised contrastive learning、Triplet-center loss 与 flooding，目标是减轻模型依赖与任务无关的捷径特征。
```

- block 1104 · table_cell_paragraph · body/table26/row13/cell3

```text
提醒本项目 R2 与 R1 的有效证据不同：某些边缘／形状／纹样可能在训练集相关，却不是稳定的“同器物”因果证据。需要关系类型条件化的特征使用和 shortcut 审计。
```

- block 1105 · table_cell_paragraph · body/table26/row13/cell4

```text
其任务是分类而非邻接／同器物关系；只能作为鲁棒表征与反捷径训练参考。
```

- block 1106 · table_cell_paragraph · body/table26/row14/cell1

```text
Coconut / Chain of Continuous Thought（Hao et al., arXiv:2412.06769；ICLR 2025 workshop）
```

- block 1107 · table_cell_paragraph · body/table26/row14/cell2

```text
不把中间推理 hidden state 解码成离散文本，而把最后 hidden state 直接作为下一轮输入 embedding；连续 latent 可同时承载多个潜在后续分支。
```

- block 1108 · table_cell_paragraph · body/table26/row14/cell3

```text
这是“不要只把 P(R2) 标量喂回主干”的关键跨域依据：应保留 relation latent、局部证据与不确定性，让下一轮 R1/R2 判断读取连续关系状态。
```

- block 1109 · table_cell_paragraph · body/table26/row14/cell4

```text
不能声称把 Coconut 用于碎片就是创新；必须证明 latent relation feedback 比 scalar feedback、普通 GRU/循环和等 FLOPs 深网更有效。
```

- block 1110 · table_cell_paragraph · body/table26/row15/cell1

```text
Titans: Learning to Memorize at Test Time（NeurIPS 2025）
```

- block 1111 · table_cell_paragraph · body/table26/row15/cell2

```text
从记忆视角区分精确但局部的 attention 短期记忆与可持续写入的 neural long-term memory。
```

- block 1112 · table_cell_paragraph · body/table26/row15/cell3

```text
支持把“当前候选竞争的精细局部证据”和“跨多轮稳定的器物身份摘要”分成不同时间尺度，而不是把所有信息塞进一个 recurrent state。
```

- block 1113 · table_cell_paragraph · body/table26/row15/cell4

```text
不直接照搬神经长期记忆实现；本项目首先用显式 Evidence Bank + 可控 latent memory 建立可审计版本。
```

- block 1114 · table_cell_paragraph · body/table26/row16/cell1

```text
VisMem: Latent Vision Memory Unlocks Potential of Vision-Language Models（CVPR 2026）
```

- block 1115 · table_cell_paragraph · body/table26/row16/cell2

```text
建立短期 fine-grained perceptual memory 与长期 semantic memory，在推理过程中动态调用，以减轻长推理时视觉细节遗失。
```

- block 1116 · table_cell_paragraph · body/table26/row16/cell3

```text
直接支持“R2 Local Memory 保存断口／3D 细节，Vessel Memory 保存稳定器物身份”的双记忆分工，避免深层推理把局部断口证据冲淡。
```

- block 1117 · table_cell_paragraph · body/table26/row16/cell4

```text
其场景是 VLM；本项目必须证明双记忆对碎片关系检索的特定错误模式有效，而非只因模型更大。
```

- block 1118 · table_cell_paragraph · body/table26/row17/cell1

```text
WorldMM: Dynamic Multimodal Memory Agent for Long Video Reasoning（CVPR 2026）
```

- block 1119 · table_cell_paragraph · body/table26/row17/cell2

```text
构造 episodic、semantic、visual 多种互补记忆，并由 adaptive retrieval agent 迭代选择需要读取哪类记忆，直到证据足够。
```

- block 1120 · table_cell_paragraph · body/table26/row17/cell3

```text
与 A6 既有 Active Evidence Routing 高度一致，可进一步用于“候选当前最缺哪类证据，就读哪类碎片／局部／关系记忆”，而不是每轮固定全读。
```

- block 1121 · table_cell_paragraph · body/table26/row17/cell4

```text
不引入语言 Agent 本身；只借动态多记忆检索和“证据足够才停止”的计算策略。
```

- block 1123 · paragraph · body

```text
增补参考池的统一结论不是“把这些模型都接起来”，而是抽取五条可测试的设计原则：① 关系预测必须可验证、可撤销，不能 hard commit；② R2 的局部接触证据与 R1 的器物身份证据需要不同记忆和不同读写策略；③ pairwise 结果只能作为多轮／多碎片联合推理的 prior；④ 一块碎片应保留局部 token 集合和 provenance，而不是被压成单一全局向量；⑤ 迭代反馈应优先反馈连续 latent relation state 与不确定性，而不是只反馈一个概率标量。
```

### A6.15 新核心候选：Uncertainty-Aware Iterative Fragment Relational Memory Network（UA-IFRMN）

- block 1124 · paragraph · body

```text
A6.15 新核心候选：Uncertainty-Aware Iterative Fragment Relational Memory Network（UA-IFRMN）
```

- block 1125 · paragraph · body

```text
中文暂定名：不确定性感知的迭代碎片关系记忆网络。它不是当前稳定主干的替代品，而是登记在长期创新区的 P0 研究候选。其目标是把原本一次性的 pairwise R0/R1/R2 打分，改造成“局部邻接发现 → 软关系写入 → 多跳同器物扩展 → 新证据联合重读 → 旧关系可修正”的迭代关系推理过程。
```

- block 1126 · paragraph · body

```text
核心科学问题：在真实低质量、断口缺失、纹样不完整和 3D 不稳定的条件下，模型能否利用已经发现的高置信直接历史邻接 R2，构建带不确定性的关系上下文，从而提高同器物但非直接邻接 R1 的检索，同时避免错误 R2 被循环放大为器物级错误？
```

- block 1127 · paragraph · body

```text
这里的“自回归”只保留“上一轮内部结果会影响下一轮推理”这一抽象，不采用离散单路径 hard autoregression。更准确的机制名称为 Contact-Conditioned Identity Expansion + Reversible Relational Memory：直接接触证据先形成局部 relation latent，再作为同器物身份扩展的条件；所有写入都带 posterior、quality、provenance 和 revision 权限。
```

- block 1129 · table_cell_paragraph · body/table27/row1/cell1

```text
组成
```

- block 1130 · table_cell_paragraph · body/table27/row1/cell2

```text
建议定义
```

- block 1131 · table_cell_paragraph · body/table27/row1/cell3

```text
为什么需要
```

- block 1132 · table_cell_paragraph · body/table27/row2/cell1

```text
Fragment Token Bank F_i
```

- block 1133 · table_cell_paragraph · body/table27/row2/cell2

```text
每块碎片保留 token set，而不是单 global vector。建议至少含 global、fracture-local、surface/pattern、material、curvature/profile、thickness、3D local patch、quality/provenance 等槽位。
```

- block 1134 · table_cell_paragraph · body/table27/row2/cell3

```text
避免 R2 需要的断口细节和 R1 需要的器物身份证据互相覆盖；也方便按关系类型选择性读取。
```

- block 1135 · table_cell_paragraph · body/table27/row3/cell1

```text
R2 Local Memory M_R2
```

- block 1136 · table_cell_paragraph · body/table27/row3/cell2

```text
保存候选直接邻接的边级 latent e_ij、R0/R1/R2/UNKNOWN posterior、几何互补、fracture visibility、pose/gap/contact、质量与来源。
```

- block 1137 · table_cell_paragraph · body/table27/row3/cell3

```text
给后续 R1 推理提供“已经确认到什么局部组件”的精细上下文，但不把概率当事实。
```

- block 1138 · table_cell_paragraph · body/table27/row4/cell1

```text
Vessel Identity Memory M_V
```

- block 1139 · table_cell_paragraph · body/table27/row4/cell2

```text
从当前一组高可信 same-vessel 碎片中形成器物级 latent / token pool，保存材质、壁厚分布、曲率趋势、器形 profile、纹样体系和稳定全局先验。
```

- block 1140 · table_cell_paragraph · body/table27/row4/cell3

```text
解决口沿与底足等远距离 R1 pair 局部外观完全不相似的问题；判断目标从 pair similarity 升级为 candidate 与当前 vessel hypothesis 的兼容性。
```

- block 1141 · table_cell_paragraph · body/table27/row5/cell1

```text
Soft Typed Relation Graph G_t
```

- block 1142 · table_cell_paragraph · body/table27/row5/cell2

```text
节点是碎片或当前局部组件；边保存 R0/R1/R2/UNKNOWN 分布、latent relation、evidence support/contradiction、质量和时间版本。
```

- block 1143 · table_cell_paragraph · body/table27/row5/cell3

```text
允许多跳关系推理，同时保持“R2 不传递”的类型约束；图是 prior 与证据账本，不是硬 GT。
```

- block 1144 · table_cell_paragraph · body/table27/row6/cell1

```text
Hypothesis Set H_t
```

- block 1145 · table_cell_paragraph · body/table27/row6/cell2

```text
允许同时保留多个器物／关系假设或多个高概率边，而不是第一轮就只留一个赢家。
```

- block 1146 · table_cell_paragraph · body/table27/row6/cell3

```text
借鉴 continuous latent 可保留多个潜在分支的思想，降低早期错误导致整条推理链塌缩。
```

- block 1147 · table_cell_paragraph · body/table27/row7/cell1

```text
Persistent Evidence Bank M_E
```

- block 1148 · table_cell_paragraph · body/table27/row7/cell2

```text
原始 2D、断口 patch、可用 3D、质量指标、source_id、采集版本只读保存，任何循环都可回读。
```

- block 1149 · table_cell_paragraph · body/table27/row7/cell3

```text
保证“State != Evidence”；当关系被质疑时可以回到原始证据，而不是只在已经被模型过滤过的 hidden state 上自证。
```

### A6.15.1 UA-IFRMN 的一次完整推理循环

- block 1151 · paragraph · body

```text
A6.15.1 UA-IFRMN 的一次完整推理循环
```

- block 1152 · paragraph · body

```text
Step 0 — 编码而不压扁：对 query 和候选库生成 Fragment Token Bank；静态 encoder 可沿用现有成熟主干，先不改变 backbone。
```

- block 1153 · paragraph · body

```text
Step 1 — 双路粗检：同时产生高召回 same-vessel shortlist 与 R2 contact shortlist。前者防止“只沿邻片链才能发现远端碎片”，后者为关系扩展提供局部结构 seed。
```

- block 1154 · paragraph · body

```text
Step 2 — 形成 Soft R2 edges：relation head 输出 R0/R1/R2/UNKNOWN posterior 与 relation latent；3D 可用时再通过几何互补／接触 verifier 产生额外证据，但 verifier 不直接覆盖网络 posterior。
```

- block 1155 · paragraph · body

```text
Step 3 — 不确定性感知写入：只有满足质量和可比较条件的证据才进入 M_R2；其写入是 soft 的，保存 posterior、置信区间／校准量、source 与时间版本，不做不可逆 hard merge。
```

- block 1156 · paragraph · body

```text
Step 4 — Contact-Conditioned Identity Expansion：以高置信 R2 seed 或局部组件为起点，在 G_t 上做多跳候选扩展；扩展只提高 same-vessel prior，不直接把多跳终点标成 R1 或 R2。
```

- block 1157 · paragraph · body

```text
Step 5 — Candidate-conditioned recurrent reasoning：对每个待判候选读取其自身 token、相关 R2 Local Memory、Vessel Memory 与关系图路径，更新 R0/R1/R2/UNKNOWN posterior。
```

- block 1158 · paragraph · body

```text
Step 6 — Joint reread / revise：一旦新碎片被高置信接受，重新计算与该局部组件相关的旧边；允许 old R2 下降、R1/R2 互换、候选休眠或恢复。
```

- block 1159 · paragraph · body

```text
Step 7 — 动态停止或继续：当 Top-K、typed relation graph 与 vessel latent 连续多轮稳定且证据预算已足够时停止；若仍冲突则继续读 Evidence Bank，或输出 UNKNOWN / 补采建议。
```

### A6.16 从 R2 到 R1 的关系代数：允许“身份传播”，禁止“邻接传播”

- block 1160 · paragraph · body

```text
A6.16 从 R2 到 R1 的关系代数：允许“身份传播”，禁止“邻接传播”
```

- block 1161 · paragraph · body

```text
UA-IFRMN 必须显式尊重现行标签定义：R2 是原碎裂事件当前叶子片间的直接历史邻接，R1 是同器物但无直接历史断裂接触。因此，A—B 为 R2、B—C 为 R2，并不能推出 A—C 为 R2；它只能为 “A 与 C 属于同一器物” 提供强结构证据。最终 A—C 是 R1、R2 还是 UNKNOWN，仍要由直接接触证据和历史邻接真值判定。
```

- block 1163 · table_cell_paragraph · body/table28/row1/cell1

```text
关系组合
```

- block 1164 · table_cell_paragraph · body/table28/row1/cell2

```text
允许的推理
```

- block 1165 · table_cell_paragraph · body/table28/row1/cell3

```text
设计意义
```

- block 1166 · table_cell_paragraph · body/table28/row2/cell1

```text
R2(A,B) + R2(B,C)
```

- block 1167 · table_cell_paragraph · body/table28/row2/cell2

```text
same-vessel(A,C) prior ↑；A-C 的直接邻接类型仍未知。
```

- block 1168 · table_cell_paragraph · body/table28/row2/cell3

```text
最典型的“局部接触链 → 器物身份扩展”。
```

- block 1169 · table_cell_paragraph · body/table28/row3/cell1

```text
R2(A,B) + R1(B,C)
```

- block 1170 · table_cell_paragraph · body/table28/row3/cell2

```text
same-vessel(A,C) prior ↑，但强度应低于双高可信 R2，并受 B-C 证据质量控制。
```

- block 1171 · table_cell_paragraph · body/table28/row3/cell3

```text
允许 R1 参与身份传播，但避免弱关系无限扩散。
```

- block 1172 · table_cell_paragraph · body/table28/row4/cell1

```text
R1(A,B) + R1(B,C)
```

- block 1173 · table_cell_paragraph · body/table28/row4/cell2

```text
只能作为 soft same-vessel 支持；不能做硬传递。
```

- block 1174 · table_cell_paragraph · body/table28/row4/cell3

```text
R1 本身可能来自外观／材质相似，错误相关风险更高。
```

- block 1175 · table_cell_paragraph · body/table28/row5/cell1

```text
R2 路径 + 强材质／器型矛盾
```

- block 1176 · table_cell_paragraph · body/table28/row5/cell2

```text
触发 joint reread 和 hypothesis revision，而不是强制维持同器物。
```

- block 1177 · table_cell_paragraph · body/table28/row5/cell3

```text
用反证抑制“图一旦连通就全部同器物”的灾难。
```

- block 1178 · table_cell_paragraph · body/table28/row6/cell1

```text
多条独立 R2 路径指向同一候选
```

- block 1179 · table_cell_paragraph · body/table28/row6/cell2

```text
可增加 same-vessel belief，但必须做 source de-correlation。
```

- block 1180 · table_cell_paragraph · body/table28/row6/cell3

```text
避免由同一重建／同一照片派生的多条证据被重复计权。
```

- block 1182 · paragraph · body

```text
研究实现上建议把 same-vessel 与 direct-contact 解耦成两个相关但不同的头：P_same(i,j) 表示器物身份兼容，P_R2(i,j) 表示直接历史邻接；随后由 typed relation head 在 R0/R1/R2/UNKNOWN 上给出最终分布。这样多跳图只影响 P_same 或 vessel compatibility，不会错误地让 R2 具备传递性。
```

### A6.17 为什么不能只把“邻片概率”喂回去：Scalar Feedback、Latent Feedback 与多假设记忆

- block 1183 · paragraph · body

```text
A6.17 为什么不能只把“邻片概率”喂回去：Scalar Feedback、Latent Feedback 与多假设记忆
```

- block 1184 · paragraph · body

```text
用户提出的原始思路“预测邻片后，把邻片预测作为下一轮输入，再判断同器物非邻片”应保留为最小基线，但正式候选必须把“反馈什么”做成分层实验。单一 P(R2) 只表达最终置信度，不包含模型是依据断口、几何、纹样还是质量得出的结论，也无法区分“高分但证据冲突”和“高分且多证据一致”。
```

- block 1186 · table_cell_paragraph · body/table29/row1/cell1

```text
反馈层级
```

- block 1187 · table_cell_paragraph · body/table29/row1/cell2

```text
输入下一轮的内容
```

- block 1188 · table_cell_paragraph · body/table29/row1/cell3

```text
研究价值
```

- block 1189 · table_cell_paragraph · body/table29/row1/cell4

```text
主要风险
```

- block 1190 · table_cell_paragraph · body/table29/row2/cell1

```text
B1 Scalar Feedback
```

- block 1191 · table_cell_paragraph · body/table29/row2/cell2

```text
只把 P(R2)、margin、quality 等少量标量反馈给下一轮。
```

- block 1192 · table_cell_paragraph · body/table29/row2/cell3

```text
最便宜、最可解释，是用户原始想法的直接实现；必须保留为基线。
```

- block 1193 · table_cell_paragraph · body/table29/row2/cell4

```text
信息瓶颈最大，无法携带局部证据结构。
```

- block 1194 · table_cell_paragraph · body/table29/row3/cell1

```text
B2 Latent Relation Feedback
```

- block 1195 · table_cell_paragraph · body/table29/row3/cell2

```text
反馈 e_ij relation latent + typed posterior + provenance mask。
```

- block 1196 · table_cell_paragraph · body/table29/row3/cell3

```text
对应 continuous latent reasoning 思想；允许下一轮利用“为什么像邻片”的连续内部表示。
```

- block 1197 · table_cell_paragraph · body/table29/row3/cell4

```text
latent 可能学到不可解释捷径，需要 probe 和 corruption test。
```

- block 1198 · table_cell_paragraph · body/table29/row4/cell1

```text
B3 Neighbor Token Set
```

- block 1199 · table_cell_paragraph · body/table29/row4/cell2

```text
将高可信邻片的局部 token set 作为可查询上下文，而不是压成一个 latent。
```

- block 1200 · table_cell_paragraph · body/table29/row4/cell3

```text
保留断口／纹样／3D 多区域证据，接近 set-to-set retrieval。
```

- block 1201 · table_cell_paragraph · body/table29/row4/cell4

```text
计算和显存增加，需 K/L 预算。
```

- block 1202 · table_cell_paragraph · body/table29/row5/cell1

```text
B4 Soft Multi-Hypothesis Memory
```

- block 1203 · table_cell_paragraph · body/table29/row5/cell2

```text
同时保留多个关系／器物假设，以权重而非 one-hot winner 表示。
```

- block 1204 · table_cell_paragraph · body/table29/row5/cell3

```text
避免第一步错边后全链路 collapse；允许后续证据翻案。
```

- block 1205 · table_cell_paragraph · body/table29/row5/cell4

```text
需要假设裁剪和去重，否则复杂度膨胀。
```

- block 1206 · table_cell_paragraph · body/table29/row6/cell1

```text
B5 Joint Graph Reread
```

- block 1207 · table_cell_paragraph · body/table29/row6/cell2

```text
新证据加入后，重新更新受影响子图和 Vessel Memory。
```

- block 1208 · table_cell_paragraph · body/table29/row6/cell3

```text
解决 pairwise chaining 不一致；旧预测不是不可撤销 token。
```

- block 1209 · table_cell_paragraph · body/table29/row6/cell4

```text
必须限制更新半径／候选数，避免全图 O(N²) 重算。
```

- block 1211 · paragraph · body

```text
因此推荐研究顺序固定为 B1 → B2 → B3 → B4/B5。只有 B2 在同输入、同候选池、相近 FLOPs 下显著优于 B1，才能说明“连续 relation latent”本身具有价值；否则不允许仅因为结构更复杂而升级主干。
```

### A6.18 双记忆与器物潜变量：R2 Local Memory × Vessel Identity Memory

- block 1212 · paragraph · body

```text
A6.18 双记忆与器物潜变量：R2 Local Memory × Vessel Identity Memory
```

- block 1213 · paragraph · body

```text
R2 与 R1 的核心证据分布不同。R2 更依赖断口局部互补、接触几何、局部纹理连续；R1 可能没有任何直接接触，反而依赖材质、壁厚、器形曲率、纹样体系、制造痕迹以及当前已恢复器物的整体先验。因此不建议让同一个 memory slot 同时承担两类关系。
```

- block 1215 · table_cell_paragraph · body/table30/row1/cell1

```text
记忆层
```

- block 1216 · table_cell_paragraph · body/table30/row1/cell2

```text
保存内容
```

- block 1217 · table_cell_paragraph · body/table30/row1/cell3

```text
主要服务目标
```

- block 1218 · table_cell_paragraph · body/table30/row1/cell4

```text
主要思想来源
```

- block 1219 · table_cell_paragraph · body/table30/row2/cell1

```text
短时／局部：R2 Local Memory
```

- block 1220 · table_cell_paragraph · body/table30/row2/cell2

```text
断口 patch、局部 3D、法线／曲率、互补场、contact/gap/penetration、局部纹样连续、fracture visibility、质量。
```

- block 1221 · table_cell_paragraph · body/table30/row2/cell3

```text
高精度直接邻接验证、局部组件形成、反证。
```

- block 1222 · table_cell_paragraph · body/table30/row2/cell4

```text
参考 VisMem 的 fine-grained short-term visual memory、GARF 的 fracture-aware 表征、Combinative Matching 的几何互补。
```

- block 1223 · table_cell_paragraph · body/table30/row3/cell1

```text
长时／器物：Vessel Identity Memory
```

- block 1224 · table_cell_paragraph · body/table30/row3/cell2

```text
材质、釉色／纹样族、壁厚统计、器型 profile、曲率趋势、已确认组件的全局关系、missing/unknown slots、稳定 provenance。
```

- block 1225 · table_cell_paragraph · body/table30/row3/cell3

```text
远距离 R1 检索、同器物候选排序、抑制“只看断口”造成的漏检。
```

- block 1226 · table_cell_paragraph · body/table30/row3/cell4

```text
参考 Titans 的短／长期记忆分工、Jigsaw++ 完整 shape prior、Beyond Reassembly missing tokens。
```

- block 1227 · table_cell_paragraph · body/table30/row4/cell1

```text
证据源：Persistent Evidence Bank
```

- block 1228 · table_cell_paragraph · body/table30/row4/cell2

```text
原始图像、局部 patch、3D、质量和采集版本，不被循环覆盖。
```

- block 1229 · table_cell_paragraph · body/table30/row4/cell3

```text
任何关系被质疑时可重新取证；防止 self-confirmation。
```

- block 1230 · table_cell_paragraph · body/table30/row4/cell4

```text
与 A6.5 既有 Evidence Bank 一致，本节只扩展其在 R2→R1 循环中的角色。
```

- block 1232 · paragraph · body

```text
Vessel Memory 不等于“把所有已接受碎片做平均池化”。建议至少比较：mean pooling、attention pooling、slot-based memory、set transformer／Perceiver-style query，以及带 missing slots 的 vessel token。任何复杂版本都必须对照简单 pooling，防止“多参数 = 更好”的假象。
```

### A6.19 错误传播控制：Predict → Verify → Soft Write → Reread → Revise

- block 1233 · paragraph · body

```text
A6.19 错误传播控制：Predict → Verify → Soft Write → Reread → Revise
```

- block 1234 · paragraph · body

```text
这条创新线最大的风险不是“能不能利用正确 R2”，而是“错误 R2 会不会污染后续 R1”。因此误差传播本身必须成为论文级评测对象，而不是部署阶段再修。SARe 的 many-fragment cascading failure、MV-RoMa 的 pairwise chaining inconsistency 以及本项目既有反自证规则共同要求：任何关系写入都必须可撤销、可追溯、可重新验证。
```

- block 1236 · table_cell_paragraph · body/table31/row1/cell1

```text
控制机制
```

- block 1237 · table_cell_paragraph · body/table31/row1/cell2

```text
实施约束
```

- block 1238 · table_cell_paragraph · body/table31/row1/cell3

```text
目的
```

- block 1239 · table_cell_paragraph · body/table31/row2/cell1

```text
Soft Write
```

- block 1240 · table_cell_paragraph · body/table31/row2/cell2

```text
边只写 posterior + latent + quality + provenance，不写 one-hot 真值。
```

- block 1241 · table_cell_paragraph · body/table31/row2/cell3

```text
降低早期错误的不可逆性。
```

- block 1242 · table_cell_paragraph · body/table31/row3/cell1

```text
Geometric Verification
```

- block 1243 · table_cell_paragraph · body/table31/row3/cell2

```text
有合格 3D 时，用局部互补、gap/contact/penetration、相反体积占据等进行独立物理检查。
```

- block 1244 · table_cell_paragraph · body/table31/row3/cell3

```text
把“网络觉得像”与“物理上能接触”分开。
```

- block 1245 · table_cell_paragraph · body/table31/row4/cell1

```text
Joint Reread
```

- block 1246 · table_cell_paragraph · body/table31/row4/cell2

```text
新碎片加入后，重算与受影响组件相关的旧边。
```

- block 1247 · table_cell_paragraph · body/table31/row4/cell3

```text
允许 P(R2) 0.82 → 0.41，而不是永久自证。
```

- block 1248 · table_cell_paragraph · body/table31/row5/cell1

```text
Candidate Dormancy / Resurrection
```

- block 1249 · table_cell_paragraph · body/table31/row5/cell2

```text
低分但证据不足的候选进入 Dormant，不直接永久删除；新证据可复活。
```

- block 1250 · table_cell_paragraph · body/table31/row5/cell3

```text
适应低质输入与遮挡。
```

- block 1251 · table_cell_paragraph · body/table31/row6/cell1

```text
Multi-Hypothesis Retention
```

- block 1252 · table_cell_paragraph · body/table31/row6/cell2

```text
在高不确定时保留多个图假设或边分布。
```

- block 1253 · table_cell_paragraph · body/table31/row6/cell3

```text
避免单路径 autoregression 的早期塌缩。
```

- block 1254 · table_cell_paragraph · body/table31/row7/cell1

```text
Source De-correlation
```

- block 1255 · table_cell_paragraph · body/table31/row7/cell2

```text
相同照片派生的 2D、3D、重建置信度标记同源。
```

- block 1256 · table_cell_paragraph · body/table31/row7/cell3

```text
防止一条错误观测以多种“证据”形式被重复放大。
```

- block 1257 · table_cell_paragraph · body/table31/row8/cell1

```text
Abstain / UNKNOWN
```

- block 1258 · table_cell_paragraph · body/table31/row8/cell2

```text
posterior 不稳定、强冲突或 evidence coverage 不足时输出 UNKNOWN / 补采。
```

- block 1259 · table_cell_paragraph · body/table31/row8/cell3

```text
错误控制优先于强迫形成完整关系图。
```

### A6.20 训练路线：Oracle 关系上限 → 预测关系闭环 → 人工腐化鲁棒性

- block 1261 · paragraph · body

```text
A6.20 训练路线：Oracle 关系上限 → 预测关系闭环 → 人工腐化鲁棒性
```

- block 1262 · paragraph · body

```text
训练不得从一开始就把完整 UA-IFRMN 端到端同时打开。否则任何增益都无法判断来自“R2 上下文真的有用”、更大模型、更大计算还是标签泄漏。建议按下面顺序建立证据。
```

- block 1264 · table_cell_paragraph · body/table32/row1/cell1

```text
阶段
```

- block 1265 · table_cell_paragraph · body/table32/row1/cell2

```text
训练／输入设置
```

- block 1266 · table_cell_paragraph · body/table32/row1/cell3

```text
必须回答的问题
```

- block 1267 · table_cell_paragraph · body/table32/row2/cell1

```text
T0 Pairwise baseline
```

- block 1268 · table_cell_paragraph · body/table32/row2/cell2

```text
完全不使用关系记忆。输入 q,c，输出 R0/R1/R2/UNKNOWN。
```

- block 1269 · table_cell_paragraph · body/table32/row2/cell3

```text
冻结最强静态基线。
```

- block 1270 · table_cell_paragraph · body/table32/row3/cell1

```text
T1 Oracle-R2 context
```

- block 1271 · table_cell_paragraph · body/table32/row3/cell2

```text
第二阶段只给 GT R2 邻片／局部组件，不给模型自己预测的边。
```

- block 1272 · table_cell_paragraph · body/table32/row3/cell3

```text
回答最关键问题：如果邻片信息正确，R1 是否存在足够大的可利用上限？若无明显增益，整条路线停止。
```

- block 1273 · table_cell_paragraph · body/table32/row4/cell1

```text
T2 Scalar predicted-R2
```

- block 1274 · table_cell_paragraph · body/table32/row4/cell2

```text
使用模型自己的 P(R2) 标量反馈。
```

- block 1275 · table_cell_paragraph · body/table32/row4/cell3

```text
验证用户原始想法能否在最小复杂度下成立。
```

- block 1276 · table_cell_paragraph · body/table32/row5/cell1

```text
T3 Latent predicted-R2
```

- block 1277 · table_cell_paragraph · body/table32/row5/cell2

```text
反馈 e_R2 relation latent 与证据 mask。
```

- block 1278 · table_cell_paragraph · body/table32/row5/cell3

```text
检验 continuous relation state 是否比 scalar 真正多提供信息。
```

- block 1279 · table_cell_paragraph · body/table32/row6/cell1

```text
T4 Scheduled / mixed memory
```

- block 1280 · table_cell_paragraph · body/table32/row6/cell2

```text
训练时混合 GT、predicted、incomplete memory，逐步降低 GT 比例。
```

- block 1281 · table_cell_paragraph · body/table32/row6/cell3

```text
减少 train-test distribution shift。
```

- block 1282 · table_cell_paragraph · body/table32/row7/cell1

```text
T5 Corrupted memory curriculum
```

- block 1283 · table_cell_paragraph · body/table32/row7/cell2

```text
主动注入 false R2、missed R2、wrong same-vessel、低质量边、缺失 3D、冲突证据。
```

- block 1284 · table_cell_paragraph · body/table32/row7/cell3

```text
强迫模型把 memory 当证据而非真理，并训练 revision。
```

- block 1285 · table_cell_paragraph · body/table32/row8/cell1

```text
T6 Joint reread
```

- block 1286 · table_cell_paragraph · body/table32/row8/cell2

```text
允许新节点进入后回看旧边，加入 revision supervision。
```

- block 1287 · table_cell_paragraph · body/table32/row8/cell3

```text
验证可反悔机制是否真的降低级联错误。
```

- block 1288 · table_cell_paragraph · body/table32/row9/cell1

```text
T7 Vessel latent / shape prior
```

- block 1289 · table_cell_paragraph · body/table32/row9/cell2

```text
在前面全部有效后，再加入器物级 latent 或 missing slots。
```

- block 1290 · table_cell_paragraph · body/table32/row9/cell3

```text
把全局先验与关系记忆的增益分开归因。
```

- block 1292 · paragraph · body

```text
A12 可控合成碎片实验室应为本路线生成专门 episode，而不是只增加总样本量：同一母体生成完整 R2 图与 R1 集合；然后分别制造 0%、5%、10%、20%、30% 错边，或只破坏一个关系证据轴，形成严格配对的 corruption ladder。真实数据必须保留独立母体确认集，合成数据只能用于预训练、机制压力测试和错误模式覆盖，不能代替真实成立证据。
```

### A6.20.1 候选损失项：先作为可拆卸假设，不一次全部启用

- block 1293 · paragraph · body

```text
A6.20.1 候选损失项：先作为可拆卸假设，不一次全部启用
```

- block 1294 · paragraph · body

```text
可维护以下损失池：L_same（同器物 membership）、L_R2（直接历史邻接）、L_contact（可比较条件下的接触／互补）、L_rank（候选排序）、L_comp（relation composition 一致性）、L_calib（posterior 校准）、L_revision（错误边被新证据推翻时的修正监督）、L_memory（vessel/local memory 一致性）以及可选 L_distill（TORA-like relation structure distillation）。任何一次正式消融只允许新增一个主要损失项，并报告其对 R1、R2、误导风险和计算的独立影响。
```

- block 1295 · paragraph · body

```text
一个重要约束是：L_comp 只鼓励 R2 路径提高 same-vessel belief，不允许把 R2 传递为 R2。即使 A-B 与 B-C 都是 R2，也不能把 A-C 直接监督为 R2；A-C 的直接邻接标签仍由历史真值单独决定。
```

### A6.21 必做实验矩阵：先证明“邻片上下文有信息”，再证明“新机制能安全利用它”

- block 1296 · paragraph · body

```text
A6.21 必做实验矩阵：先证明“邻片上下文有信息”，再证明“新机制能安全利用它”
```

- block 1298 · table_cell_paragraph · body/table33/row1/cell1

```text
实验
```

- block 1299 · table_cell_paragraph · body/table33/row1/cell2

```text
最低对照
```

- block 1300 · table_cell_paragraph · body/table33/row1/cell3

```text
核心观测
```

- block 1301 · table_cell_paragraph · body/table33/row1/cell4

```text
否定／进入条件
```

- block 1302 · table_cell_paragraph · body/table33/row2/cell1

```text
Oracle-R2 上限实验
```

- block 1303 · table_cell_paragraph · body/table33/row2/cell2

```text
Pairwise R1 vs Pairwise + GT R2 context
```

- block 1304 · table_cell_paragraph · body/table33/row2/cell3

```text
R1 Hit@K / same-vessel Hit@K / CovRecall
```

- block 1305 · table_cell_paragraph · body/table33/row2/cell4

```text
若 GT R2 也不能稳定提升 R1，则暂停 UA-IFRMN。
```

- block 1306 · table_cell_paragraph · body/table33/row3/cell1

```text
Scalar vs Latent Feedback
```

- block 1307 · table_cell_paragraph · body/table33/row3/cell2

```text
P(R2) 标量 vs e_R2 latent，同候选池同 FLOPs
```

- block 1308 · table_cell_paragraph · body/table33/row3/cell3

```text
R1、R2、ECE/Brier、时延
```

- block 1309 · table_cell_paragraph · body/table33/row3/cell4

```text
只有 latent 显著优于 scalar 才保留连续反馈。
```

- block 1310 · table_cell_paragraph · body/table33/row4/cell1

```text
单邻片 vs 多邻片集合
```

- block 1311 · table_cell_paragraph · body/table33/row4/cell2

```text
Top1 R2 context vs Top-K neighbor token set
```

- block 1312 · table_cell_paragraph · body/table33/row4/cell3

```text
R1、覆盖、多邻片真值恢复
```

- block 1313 · table_cell_paragraph · body/table33/row4/cell4

```text
证明 set context 是否真实有价值。
```

- block 1314 · table_cell_paragraph · body/table33/row5/cell1

```text
Pairwise chaining vs Soft Graph
```

- block 1315 · table_cell_paragraph · body/table33/row5/cell2

```text
直接把边串起来 vs typed soft graph
```

- block 1316 · table_cell_paragraph · body/table33/row5/cell3

```text
级联错误率、R1、错误图连通率
```

- block 1317 · table_cell_paragraph · body/table33/row5/cell4

```text
Soft graph 必须明显减少错误传播。
```

- block 1318 · table_cell_paragraph · body/table33/row6/cell1

```text
Hard Commit vs Reversible Memory
```

- block 1319 · table_cell_paragraph · body/table33/row6/cell2

```text
接受后不可撤销 vs joint reread/revise
```

- block 1320 · table_cell_paragraph · body/table33/row6/cell3

```text
wrong→correct、correct→wrong、最终命中
```

- block 1321 · table_cell_paragraph · body/table33/row6/cell4

```text
可反悔机制必须提高恢复率且不显著伤害 clean。
```

- block 1322 · table_cell_paragraph · body/table33/row7/cell1

```text
无 Vessel Memory vs Vessel Memory
```

- block 1323 · table_cell_paragraph · body/table33/row7/cell2

```text
只有 R2 local context vs 加器物 latent
```

- block 1324 · table_cell_paragraph · body/table33/row7/cell3

```text
远距离 R1、口沿↔底足等异部位子集
```

- block 1325 · table_cell_paragraph · body/table33/row7/cell4

```text
验证全局器物先验是否补足局部相似不足。
```

- block 1326 · table_cell_paragraph · body/table33/row8/cell1

```text
无 Local Memory vs Dual Memory
```

- block 1327 · table_cell_paragraph · body/table33/row8/cell2

```text
单一 vessel latent vs R2 Local + Vessel 双记忆
```

- block 1328 · table_cell_paragraph · body/table33/row8/cell3

```text
R2 精度、R1、局部断口保持率
```

- block 1329 · table_cell_paragraph · body/table33/row8/cell4

```text
证明分层记忆而非单一大向量更合理。
```

- block 1330 · table_cell_paragraph · body/table33/row9/cell1

```text
R2 corruption curve
```

- block 1331 · table_cell_paragraph · body/table33/row9/cell2

```text
错边率 0/5/10/20/30%
```

- block 1332 · table_cell_paragraph · body/table33/row9/cell3

```text
R1 Hit@K、误导率、校准、revision success
```

- block 1333 · table_cell_paragraph · body/table33/row9/cell4

```text
优良模型曲线应比 hard autoregressive 明显更平缓。
```

- block 1334 · table_cell_paragraph · body/table33/row10/cell1

```text
关系类型交换压力测试
```

- block 1335 · table_cell_paragraph · body/table33/row10/cell2

```text
把部分 R1 伪装成 R2、R2 伪装成 R1
```

- block 1336 · table_cell_paragraph · body/table33/row10/cell3

```text
类型鲁棒性与 same-vessel 稳定性
```

- block 1337 · table_cell_paragraph · body/table33/row10/cell4

```text
检查模型是否真正理解 direct-contact 与 identity 的区别。
```

- block 1338 · table_cell_paragraph · body/table33/row11/cell1

```text
来源捷径审计
```

- block 1339 · table_cell_paragraph · body/table33/row11/cell2

```text
遮蔽／打乱纹样、边界、材质、背景、采集台特征
```

- block 1340 · table_cell_paragraph · body/table33/row11/cell3

```text
各 subgroup 性能与 representation probe
```

- block 1341 · table_cell_paragraph · body/table33/row11/cell4

```text
避免“同器物”被数据采集捷径替代。
```

- block 1342 · table_cell_paragraph · body/table33/row12/cell1

```text
等预算对照
```

- block 1343 · table_cell_paragraph · body/table33/row12/cell2

```text
UA-IFRMN vs 等参数／等 FLOPs 静态深网、GRU、普通循环
```

- block 1344 · table_cell_paragraph · body/table33/row12/cell3

```text
全部任务指标 + GPU 小时 + P95 时延
```

- block 1345 · table_cell_paragraph · body/table33/row12/cell4

```text
证明增益来自关系记忆机制而非更多算力。
```

- block 1347 · paragraph · body

```text
推荐把 Oracle-R2 gap 作为第一道 go/no-go 门。它直接测量“正确邻接上下文最多能给 R1 带来多少信息”。只有这个上限足够大，后续关于 latent feedback、图记忆、vessel memory 和 multi-hop reasoning 的工程投入才有意义。第二道门是 predicted-R2 与 corruption curve：如果真实预测边一加入就把 R1 拖垮，则优先研究校准、验证和 revision，而不是继续扩主干。
```

### A6.22 可形成的研究主张与明确禁写项

- block 1348 · paragraph · body

```text
A6.22 可形成的研究主张与明确禁写项
```

- block 1349 · paragraph · body

```text
现阶段不得写“首次将自回归用于碎片重建”：PuzzleFusion++ 已经明确采用 auto-agglomerative、类 autoregressive 的逐步组装。也不得写“首次把预测碎片关系反馈给下一轮”：SARe 已经使用接触图、几何验证与可靠子结构反馈／重采样。任何论文新颖性都必须避开这两个宽泛表述。
```

- block 1350 · paragraph · body

```text
当前更有希望、但仍需实验证明的主张是：在“同器物非邻接检索”问题上，利用直接历史邻接 R2 构建带不确定性、可修正的 typed relation memory，并通过 contact-conditioned multi-hop identity expansion 与 vessel-level latent context 提高 R1 检索；同时显式测量和抑制错误 R2 的级联传播。
```

- block 1351 · paragraph · body

```text
可暂定英文机制描述：Uncertainty-Aware Iterative Fragment Relational Memory Network (UA-IFRMN) for Contact-Conditioned Identity Expansion。正式投稿前必须再次检索同题工作，并以当时最新文献决定名称与新颖性措辞。
```

- block 1353 · table_cell_paragraph · body/table34/row1/cell1

```text
类别
```

- block 1354 · table_cell_paragraph · body/table34/row1/cell2

```text
内容
```

- block 1355 · table_cell_paragraph · body/table34/row2/cell1

```text
可以研究
```

- block 1356 · table_cell_paragraph · body/table34/row2/cell2

```text
R2 作为局部结构 seed 是否显著提高 R1；soft typed graph 是否比 pair chaining 更稳；latent relation feedback 是否比 scalar feedback 更有效；Vessel Memory 是否改善远距离 R1；可反悔机制是否降低级联错误。
```

- block 1357 · table_cell_paragraph · body/table34/row3/cell1

```text
不能预先声称
```

- block 1358 · table_cell_paragraph · body/table34/row3/cell2

```text
UA-IFRMN 已经优于 SOTA；R2→R1 一定有效；循环／CTM 本身就是创新；自回归思想首次用于碎片；完整器物 prior 一定能帮助低质陶片。
```

- block 1359 · table_cell_paragraph · body/table34/row4/cell1

```text
必须保留的失败解释
```

- block 1360 · table_cell_paragraph · body/table34/row4/cell2

```text
Oracle-R2 无上限；predicted-R2 噪声抵消收益；Vessel Memory 形成 shortcut；多跳扩展造成 graph over-smoothing；relation latent 无法优于标量；可反悔机制成本过高。
```

### A6.23 创新账本增补：UA-IFRMN 关系记忆路线

- block 1362 · paragraph · body

```text
A6.23 创新账本增补：UA-IFRMN 关系记忆路线
```

- block 1363 · paragraph · body

```text
以下编号从现有 INNO-31 之后顺延，只新增、不覆盖旧条目。全部状态初始为 RESEARCH_CANDIDATE 或 IDEA，待冻结实验后再流转。
```

- block 1365 · table_cell_paragraph · body/table35/row1/cell1

```text
ID
```

- block 1366 · table_cell_paragraph · body/table35/row1/cell2

```text
创新候选
```

- block 1367 · table_cell_paragraph · body/table35/row1/cell3

```text
当前优先级
```

- block 1368 · table_cell_paragraph · body/table35/row1/cell4

```text
状态
```

- block 1369 · table_cell_paragraph · body/table35/row2/cell1

```text
INNO-32
```

- block 1370 · table_cell_paragraph · body/table35/row2/cell2

```text
UA-IFRMN：Uncertainty-Aware Iterative Fragment Relational Memory Network。
```

- block 1371 · table_cell_paragraph · body/table35/row2/cell3

```text
P0 核心
```

- block 1372 · table_cell_paragraph · body/table35/row2/cell4

```text
RESEARCH_CANDIDATE
```

- block 1373 · table_cell_paragraph · body/table35/row3/cell1

```text
INNO-33
```

- block 1374 · table_cell_paragraph · body/table35/row3/cell2

```text
Contact-Conditioned Identity Expansion：用高置信 R2 局部接触结构作为 R1 同器物身份扩展条件。
```

- block 1375 · table_cell_paragraph · body/table35/row3/cell3

```text
P0 核心
```

- block 1376 · table_cell_paragraph · body/table35/row3/cell4

```text
RESEARCH_CANDIDATE
```

- block 1377 · table_cell_paragraph · body/table35/row4/cell1

```text
INNO-34
```

- block 1378 · table_cell_paragraph · body/table35/row4/cell2

```text
Soft Typed Relation Graph Memory：R0/R1/R2/UNKNOWN + latent + quality + provenance 的可修正关系图。
```

- block 1379 · table_cell_paragraph · body/table35/row4/cell3

```text
P0 核心
```

- block 1380 · table_cell_paragraph · body/table35/row4/cell4

```text
RESEARCH_CANDIDATE
```

- block 1381 · table_cell_paragraph · body/table35/row5/cell1

```text
INNO-35
```

- block 1382 · table_cell_paragraph · body/table35/row5/cell2

```text
Latent Relation Feedback：反馈连续 relation latent，而非只反馈 P(R2) 标量。
```

- block 1383 · table_cell_paragraph · body/table35/row5/cell3

```text
P1 高潜
```

- block 1384 · table_cell_paragraph · body/table35/row5/cell4

```text
RESEARCH_CANDIDATE
```

- block 1385 · table_cell_paragraph · body/table35/row6/cell1

```text
INNO-36
```

- block 1386 · table_cell_paragraph · body/table35/row6/cell2

```text
Dual Relational Memory：R2 Local Memory + Vessel Identity Memory 分工。
```

- block 1387 · table_cell_paragraph · body/table35/row6/cell3

```text
P0 架构
```

- block 1388 · table_cell_paragraph · body/table35/row6/cell4

```text
RESEARCH_CANDIDATE
```

- block 1389 · table_cell_paragraph · body/table35/row7/cell1

```text
INNO-37
```

- block 1390 · table_cell_paragraph · body/table35/row7/cell2

```text
Reversible Joint Reread：新证据进入后联合重读受影响子图，允许旧边降权／撤销／改型。
```

- block 1391 · table_cell_paragraph · body/table35/row7/cell3

```text
P0 可靠性
```

- block 1392 · table_cell_paragraph · body/table35/row7/cell4

```text
RESEARCH_CANDIDATE
```

- block 1393 · table_cell_paragraph · body/table35/row8/cell1

```text
INNO-38
```

- block 1394 · table_cell_paragraph · body/table35/row8/cell2

```text
Soft Multi-Hypothesis Vessel Memory：高不确定时保留多个关系／器物假设，避免早期单路径塌缩。
```

- block 1395 · table_cell_paragraph · body/table35/row8/cell3

```text
P2 储备
```

- block 1396 · table_cell_paragraph · body/table35/row8/cell4

```text
IDEA
```

- block 1397 · table_cell_paragraph · body/table35/row9/cell1

```text
INNO-39
```

- block 1398 · table_cell_paragraph · body/table35/row9/cell2

```text
Relation Composition Regularization：R2 多跳只提升 same-vessel belief，不错误传播 R2 类型。
```

- block 1399 · table_cell_paragraph · body/table35/row9/cell3

```text
P1 高潜
```

- block 1400 · table_cell_paragraph · body/table35/row9/cell4

```text
RESEARCH_CANDIDATE
```

- block 1401 · table_cell_paragraph · body/table35/row10/cell1

```text
INNO-40
```

- block 1402 · table_cell_paragraph · body/table35/row10/cell2

```text
Oracle-to-Predicted Relation Curriculum：GT R2 → 混合 memory → predicted R2 的课程训练。
```

- block 1403 · table_cell_paragraph · body/table35/row10/cell3

```text
P1 训练
```

- block 1404 · table_cell_paragraph · body/table35/row10/cell4

```text
RESEARCH_CANDIDATE
```

- block 1405 · table_cell_paragraph · body/table35/row11/cell1

```text
INNO-41
```

- block 1406 · table_cell_paragraph · body/table35/row11/cell2

```text
Relation Corruption Robustness Curriculum：按错边率与错边类型系统训练 memory-as-evidence 而非 memory-as-truth。
```

- block 1407 · table_cell_paragraph · body/table35/row11/cell3

```text
P0 可靠性
```

- block 1408 · table_cell_paragraph · body/table35/row11/cell4

```text
RESEARCH_CANDIDATE
```

- block 1409 · table_cell_paragraph · body/table35/row12/cell1

```text
INNO-42
```

- block 1410 · table_cell_paragraph · body/table35/row12/cell2

```text
Vessel Latent / Missing Slots：从已知碎片形成器物级潜变量，并显式保留未知／缺失结构。
```

- block 1411 · table_cell_paragraph · body/table35/row12/cell3

```text
P1 高风险高收益
```

- block 1412 · table_cell_paragraph · body/table35/row12/cell4

```text
IDEA
```

- block 1413 · table_cell_paragraph · body/table35/row13/cell1

```text
INNO-43
```

- block 1414 · table_cell_paragraph · body/table35/row13/cell2

```text
Fragment Local Vocabulary Set-to-Set Rerank：用局部 token 集合／OT或Chamfer类集合距离增强 R1 精排。
```

- block 1415 · table_cell_paragraph · body/table35/row13/cell3

```text
P2 储备
```

- block 1416 · table_cell_paragraph · body/table35/row13/cell4

```text
IDEA
```

- block 1417 · table_cell_paragraph · body/table35/row14/cell1

```text
INNO-44
```

- block 1418 · table_cell_paragraph · body/table35/row14/cell2

```text
Complementarity-Aware R2 Verifier：相同表面形状 + 相反体积占据 + 接触／穿透约束的高成本物理核验。
```

- block 1419 · table_cell_paragraph · body/table35/row14/cell3

```text
P1 可靠性
```

- block 1420 · table_cell_paragraph · body/table35/row14/cell4

```text
RESEARCH_CANDIDATE
```

- block 1421 · table_cell_paragraph · body/table35/row15/cell1

```text
INNO-45
```

- block 1422 · table_cell_paragraph · body/table35/row15/cell2

```text
Topology/Relation Distillation：从 geometry/contact-centric 3D teacher 蒸馏关系结构到主干。
```

- block 1423 · table_cell_paragraph · body/table35/row15/cell3

```text
P2 储备
```

- block 1424 · table_cell_paragraph · body/table35/row15/cell4

```text
IDEA
```

### A6.24 本次增补的外部来源与复现优先级

- block 1426 · paragraph · body

```text
A6.24 本次增补的外部来源与复现优先级
```

- block 1427 · paragraph · body

```text
来源分为两类：会议／期刊正式论文用于建立强对照，2026 年预印本用于跟踪最新方向。预印本在正式投稿前必须再次核验版本、发表状态和结论；不得把预印本结果写成社区共识。建议优先阅读／复现顺序为：SARe → PuzzleFusion++ → GARF → Combinative Matching / Rectified Point Flow → MHopReg → Jigsaw++ / Beyond Reassembly → Bag of Bags → Coconut / VisMem / WorldMM / Titans → TORA / MV-RoMa。
```

- block 1428 · paragraph · body

```text
1. Jia et al. SARe: Structure-Aware Large-Scale 3D Fragment Reassembly. arXiv:2603.21611, 2026.
```

- block 1429 · paragraph · body

```text
2. Wang, Chen, Furukawa. PuzzleFusion++: Auto-agglomerative 3D Fracture Assembly by Denoise and Verify. ICLR 2025.
```

- block 1430 · paragraph · body

```text
3. Li et al. GARF: Learning Generalizable 3D Reassembly for Real-World Fractures. ICCV 2025.
```

- block 1431 · paragraph · body

```text
4. Sun et al. Rectified Point Flow: Generic Point Cloud Pose Estimation. NeurIPS 2025 Spotlight; arXiv:2506.05282.
```

- block 1432 · paragraph · body

```text
5. Lee et al. Combinative Matching for Geometric Shape Assembly. ICCV 2025 Highlight. DOI: 10.1109/ICCV51701.2025.00890.
```

- block 1433 · paragraph · body

```text
6. Lee et al. TORA: Topological Representation Alignment for 3D Shape Assembly. arXiv:2604.04050, 2026.
```

- block 1434 · paragraph · body

```text
7. Lu, Hua, Huang. Jigsaw++: Imagining Complete Shape Priors for Object Reassembly. ICCV 2025.
```

- block 1435 · paragraph · body

```text
8. Xu et al. Beyond Reassembly: Fractured Object Recovery with Missing Parts. CVPR 2026.
```

- block 1436 · paragraph · body

```text
9. Wu et al. MHopReg: Efficient Hierarchical Multi-Hop Graph Search for Point Cloud Registration. CVPR 2026.
```

- block 1437 · paragraph · body

```text
10. Lee, Kang, Yoo. MV-RoMa: From Pairwise Matching into Multi-View Track Reconstruction. arXiv:2603.27542, 2026.
```

- block 1438 · paragraph · body

```text
11. Gogawale et al. Bag of Bags: Adaptive Visual Vocabularies for Genizah Join Image Retrieval. CVPR Workshops 2026.
```

- block 1439 · paragraph · body

```text
12. Yu et al. Mitigating spurious features by contrastive learning in pottery sherd recognition. npj Heritage Science 14, 135 (2026).
```

- block 1440 · paragraph · body

```text
13. Hao et al. Training Large Language Models to Reason in a Continuous Latent Space (Coconut). arXiv:2412.06769; ICLR 2025 Workshop.
```

- block 1441 · paragraph · body

```text
14. Behrouz, Zhong, Mirrokni. Titans: Learning to Memorize at Test Time. NeurIPS 2025.
```

- block 1442 · paragraph · body

```text
15. Yu et al. VisMem: Latent Vision Memory Unlocks Potential of Vision-Language Models. CVPR 2026.
```

- block 1443 · paragraph · body

```text
16. Yeo et al. WorldMM: Dynamic Multimodal Memory Agent for Long Video Reasoning. CVPR 2026.
```

- block 1444 · paragraph · body

```text
本次 A6 增补状态：仅完成长期创新区的思想登记、架构假设、参考映射与最小实验合同；未改变 A1–A5、A7 以后正文、现有历史实验判决、A12 合成平台事实状态或比赛稳定主线。
```

### A6.25 Whole-Vessel Membership Recovery：从一块碎片恢复整个器物成员集合

- block 1445 · paragraph · body

```text
A6.25 Whole-Vessel Membership Recovery：从一块碎片恢复整个器物成员集合
```

- block 1446 · paragraph · body

```text
长期主任务定义为Fragment-to-Vessel Membership Recovery：输入任意查询碎片q和混合图库G，输出G中与q属于同一器物的预测成员集合V_hat(q)，并区分其中直接历史邻接R2与非直接邻接R1。该任务不要求一次性输出完整几何装配；它首先研究“哪些碎片属于一起”，再把几何装配作为可选后续。这样既贴合专家实际搜索负担，也把研究问题从pairwise similarity提升为set recovery与relational retrieval。
```

- block 1448 · table_cell_paragraph · body/table36/row1/cell1

```text
阶段
```

- block 1449 · table_cell_paragraph · body/table36/row1/cell2

```text
核心操作
```

- block 1450 · table_cell_paragraph · body/table36/row1/cell3

```text
研究意义
```

- block 1451 · table_cell_paragraph · body/table36/row2/cell1

```text
Seed retrieval
```

- block 1452 · table_cell_paragraph · body/table36/row2/cell2

```text
从q召回高置信R2和same-vessel种子
```

- block 1453 · table_cell_paragraph · body/table36/row2/cell3

```text
建立第一批可靠局部证据；不追求一次找全。
```

- block 1454 · table_cell_paragraph · body/table36/row3/cell1

```text
Local component formation
```

- block 1455 · table_cell_paragraph · body/table36/row3/cell2

```text
把通过验证的R2软写入R2 Local Memory
```

- block 1456 · table_cell_paragraph · body/table36/row3/cell3

```text
得到局部组件，但R2不传递。
```

- block 1457 · table_cell_paragraph · body/table36/row4/cell1

```text
Vessel hypothesis
```

- block 1458 · table_cell_paragraph · body/table36/row4/cell2

```text
由已接受/高置信成员建立Vessel Identity Memory
```

- block 1459 · table_cell_paragraph · body/table36/row4/cell3

```text
形成材质、壁厚、曲率、纹样体系和器型趋势等器物级条件。
```

- block 1460 · table_cell_paragraph · body/table36/row5/cell1

```text
Database re-search
```

- block 1461 · table_cell_paragraph · body/table36/row5/cell2

```text
用q + 当前器物假设重新扫描全库
```

- block 1462 · table_cell_paragraph · body/table36/row5/cell3

```text
寻找与q不接触但与整体器物假设兼容的R1。
```

- block 1463 · table_cell_paragraph · body/table36/row6/cell1

```text
Joint reread
```

- block 1464 · table_cell_paragraph · body/table36/row6/cell2

```text
新成员加入后重读旧边、冲突与缺失证据
```

- block 1465 · table_cell_paragraph · body/table36/row6/cell3

```text
允许早期关系降级、撤回或恢复，控制级联错误。
```

- block 1466 · table_cell_paragraph · body/table36/row7/cell1

```text
Stop/abstain
```

- block 1467 · table_cell_paragraph · body/table36/row7/cell2

```text
边际收益低、风险高、预算耗尽或无新证据时停止
```

- block 1468 · table_cell_paragraph · body/table36/row7/cell3

```text
避免为了高Recall无限扩张集合。
```

### A6.26 High-Degradation Robust Retrieval：高磨损、风化与部分观测下的鲁棒碎片检索

- block 1470 · paragraph · body

```text
A6.26 High-Degradation Robust Retrieval：高磨损、风化与部分观测下的鲁棒碎片检索
```

- block 1471 · paragraph · body

```text
第二条核心研究主线是“证据被物理过程破坏后模型还能保留多少检索能力”。传统几何算法在完整断口、可靠3D和高重叠条件下必须作为强基线；RelicWeave的研究价值不在于清晰样本多赢几个百分点，而在于随着断口磨圆、崩缺、表面侵蚀、纹样缺失、成像噪声和3D重建伪影增强，性能下降是否显著慢于传统精确匹配和普通静态网络。
```

- block 1473 · table_cell_paragraph · body/table37/row1/cell1

```text
退化层级
```

- block 1474 · table_cell_paragraph · body/table37/row1/cell2

```text
控制内容
```

- block 1475 · table_cell_paragraph · body/table37/row1/cell3

```text
要回答的问题
```

- block 1476 · table_cell_paragraph · body/table37/row2/cell1

```text
D0 Clean
```

- block 1477 · table_cell_paragraph · body/table37/row2/cell2

```text
断口与表面证据完整
```

- block 1478 · table_cell_paragraph · body/table37/row2/cell3

```text
建立传统方法和学习方法的上限；允许传统法胜出。
```

- block 1479 · table_cell_paragraph · body/table37/row3/cell1

```text
D1 Mild wear
```

- block 1480 · table_cell_paragraph · body/table37/row3/cell2

```text
轻度磨圆/轻纹理损伤
```

- block 1481 · table_cell_paragraph · body/table37/row3/cell3

```text
观察第一处性能分离点。
```

- block 1482 · table_cell_paragraph · body/table37/row4/cell1

```text
D2 Local chipping
```

- block 1483 · table_cell_paragraph · body/table37/row4/cell2

```text
局部崩边/缺口
```

- block 1484 · table_cell_paragraph · body/table37/row4/cell3

```text
测试局部对应丢失时的多模态补偿。
```

- block 1485 · table_cell_paragraph · body/table37/row5/cell1

```text
D3 Partial fracture loss
```

- block 1486 · table_cell_paragraph · body/table37/row5/cell2

```text
20–40%断口信息不可见或缺失
```

- block 1487 · table_cell_paragraph · body/table37/row5/cell3

```text
测试partial observation与拒识。
```

- block 1488 · table_cell_paragraph · body/table37/row6/cell1

```text
D4 Severe mixed degradation
```

- block 1489 · table_cell_paragraph · body/table37/row6/cell2

```text
磨损+崩缺+表面退化+成像噪声
```

- block 1490 · table_cell_paragraph · body/table37/row6/cell3

```text
测试关系上下文和Vessel Memory是否提供额外鲁棒性。
```

- block 1491 · table_cell_paragraph · body/table37/row7/cell1

```text
D5 Real domain
```

- block 1492 · table_cell_paragraph · body/table37/row7/cell2

```text
真实自然风化/真实采集误差
```

- block 1493 · table_cell_paragraph · body/table37/row7/cell3

```text
只作为独立确认；不能用合成D级替代。
```

### A6.27 统一论文路线：共享一个问题族，不把所有创新强塞进一篇论文

- block 1495 · paragraph · body

```text
A6.27 统一论文路线：共享一个问题族，不把所有创新强塞进一篇论文
```

- block 1496 · paragraph · body

```text
V1.47把科研方向整理成一个问题族：低质量碎片如何从局部接触证据逐步恢复器物身份。具体投稿时只选择证据最强的一条主贡献，其他机制降为支撑或后续工作。文化遗产是高价值真实场景，但CVPR级论文必须把任务抽象为可推广的视觉问题，并用强基线、真实退化、机制消融和跨域/跨采集验证证明贡献。
```

- block 1498 · table_cell_paragraph · body/table38/row1/cell1

```text
论文候选
```

- block 1499 · table_cell_paragraph · body/table38/row1/cell2

```text
核心问题
```

- block 1500 · table_cell_paragraph · body/table38/row1/cell3

```text
必须证据
```

- block 1501 · table_cell_paragraph · body/table38/row1/cell4

```text
止损条件
```

- block 1502 · table_cell_paragraph · body/table38/row2/cell1

```text
PAPER-A：Robust Fragment Retrieval under Physical Degradation
```

- block 1503 · table_cell_paragraph · body/table38/row2/cell2

```text
退化鲁棒检索
```

- block 1504 · table_cell_paragraph · body/table38/row2/cell3

```text
性能—退化强度曲线；传统几何/静态AI/新方法公平对照；Synthetic→Real。
```

- block 1505 · table_cell_paragraph · body/table38/row2/cell4

```text
若真实退化没有稳定增益，转为数据/应用论文。
```

- block 1506 · table_cell_paragraph · body/table38/row3/cell1

```text
PAPER-B：Contact-Conditioned Vessel Identity Expansion
```

- block 1507 · table_cell_paragraph · body/table38/row3/cell2

```text
R2→R1 / UA-IFRMN
```

- block 1508 · table_cell_paragraph · body/table38/row3/cell3

```text
Oracle-R2→Predicted-R2→Corrupted-R2；证明局部接触上下文对R1有信息且可安全利用。
```

- block 1509 · table_cell_paragraph · body/table38/row3/cell4

```text
若Oracle-R2都不能提升R1，停止该主张。
```

- block 1510 · table_cell_paragraph · body/table38/row4/cell1

```text
PAPER-C：Fragment-to-Vessel Membership Recovery
```

- block 1511 · table_cell_paragraph · body/table38/row4/cell2

```text
整器物成员恢复新任务/集合检索
```

- block 1512 · table_cell_paragraph · body/table38/row4/cell3

```text
Vessel Precision/Recall/F1；不同成员数和库规模；set/graph/metric学习强基线。
```

- block 1513 · table_cell_paragraph · body/table38/row4/cell4

```text
若任务GT无法闭合或只在单器型有效，先不宣称通用任务。
```

- block 1514 · table_cell_paragraph · body/table38/row5/cell1

```text
PAPER-D：Physics-Guided Synthetic-to-Real Pretraining
```

- block 1515 · table_cell_paragraph · body/table38/row5/cell2

```text
A12/VesselForge/PG-Frag
```

- block 1516 · table_cell_paragraph · body/table38/row5/cell3

```text
物理合理碎裂+退化预训练是否降低真实样本需求并提升跨域鲁棒性。
```

- block 1517 · table_cell_paragraph · body/table38/row5/cell4

```text
若synthetic-pretrain无真实收益，只保留为实验基础设施。
```

- block 1518 · table_cell_paragraph · body/table38/row6/cell1

```text
PAPER-E：Active Evidence Acquisition
```

- block 1519 · table_cell_paragraph · body/table38/row6/cell2

```text
候选条件主动补采
```

- block 1520 · table_cell_paragraph · body/table38/row6/cell3

```text
同照片/同时间预算下减少错误并提高成员恢复。
```

- block 1521 · table_cell_paragraph · body/table38/row6/cell4

```text
没有可交互真实数据前不作为主论文。
```

### A6.28 顶会级研究门槛与禁止性表述

- block 1523 · paragraph · body

```text
A6.28 顶会级研究门槛与禁止性表述
```

- block 1524 · paragraph · body

```text
进入CVPR/ICCV等主会级主线前至少需要：①真实或可信独立域数据，不能只靠合成；②与传统几何、强检索、set/graph模型和最接近碎片方法的同输入对照；③预注册或冻结的主指标和独立确认；④机制消融能够排除“只是更多参数/更多照片/更多计算”；⑤退化、库规模、成员数和hard negative分层；⑥失败案例与适用域。禁止写“首次使用自回归做碎片”“首次把预测关系反馈回网络”等高风险新颖性断言；真正可能成立的主张应收敛到高退化下的关系记忆、R2条件的器物身份扩展或整器物成员恢复。
```

### EXP10 高磨损/风化鲁棒性基准

- block 1579 · paragraph · body

```text
EXP10 高磨损/风化鲁棒性基准
```

- block 1580 · paragraph · body

```text
冻结同一批query、gallery、GT、训练预算和观测权限，建立D0→Dn配对退化阶梯。最低对照包括人工可观察性、ICP/GICP或等价传统配准、FPFH/SHOT或其他合法局部描述子、曲率/轮廓基线、静态深度检索和当前RelicWeave。主输出为Hit/CovRecall/Same-Vessel与Vessel指标随退化强度的曲线、失败转移点和真实域确认。清晰档传统算法强不算失败；只有高退化档出现稳定且可归因优势，才能写“AI在该场景增加价值”。
```

### EXP11 整器物成员恢复（Vessel Membership Recovery）

- block 1581 · paragraph · body

```text
EXP11 整器物成员恢复（Vessel Membership Recovery）
```

- block 1582 · paragraph · body

```text
只使用member set闭合的母体。给定单个query，系统从空或最小seed开始迭代检索，输出R2、R1和最终V_hat(q)。比较pairwise retrieval、简单聚类/metric learning、set/graph baseline、静态vessel prototype和UA-IFRMN候选。报告Vessel Precision/Recall/F1、完整找回率、首个错误成员进入轮次、迭代次数、查询墙钟和专家需要核验的候选数。不同器物成员数、图库规模、材质和器型分层。
```

### EXP12 R2→R1关系上下文与错误传播

- block 1583 · paragraph · body

```text
EXP12 R2→R1关系上下文与错误传播
```

- block 1584 · paragraph · body

```text
第一步Oracle-R2：只替换关系上下文，不改视觉输入，验证真实邻接上下文能否提升R1/same-vessel；第二步Predicted-R2：换成模型预测并保留posterior、quality与relation latent；第三步Corrupted-R2：按0/5/10/20/30%注入错边、漏边和不完整memory。比较Scalar Feedback、Latent Feedback、Neighbor Set、Soft Graph、Vessel Memory与Reversible Memory。若Oracle无增益则暂停；若预测闭环增益只在无错边成立，则不能进入部署。
```

### A12.21 V1.47退化性能曲线：把SyntheticLab变成“物理退化压力测试仪”

- block 2200 · paragraph · body

```text
A12.21 V1.47退化性能曲线：把SyntheticLab变成“物理退化压力测试仪”
```

- block 2201 · paragraph · body

```text
A12新增一类paired counterfactual release：同一clean母体、同一碎片关系、同一query/gallery与基础随机种子，沿磨损、崩缺、表面侵蚀、遮挡、图像质量、3D缺失/增生噪点等单轴或预注册组合轴生成D0→Dn观测。每个release必须同时提供传统算法合法输入、学习模型合法输入和TruthPack，但TruthPack只供评测。输出不仅是某一档准确率，而是每个方法的性能—退化强度曲线、临界失效点、AUC/斜率型诊断和真实域对应样本。
```

### A12.22 Whole-Vessel Episode Generator：为整器物成员恢复生成完整关系世界

- block 2202 · paragraph · body

```text
A12.22 Whole-Vessel Episode Generator：为整器物成员恢复生成完整关系世界
```

- block 2203 · paragraph · body

```text
每个合成母体除R2边外，还必须导出完整member set、R1/R2 typed relation graph、可见/不可见断面、缺失材料和母体级属性。episode生成器把多个母体混成gallery，随机选择query并控制同器物成员数、R1/R2比例、hard negative密度、器型相似度、材质相似度和退化分布；训练端只看合法Obs，评测端用完整Truth计算Vessel Precision/Recall/F1及多轮扩展轨迹。这样A12的数据价值从“更多pair”升级为“可控整器物关系规模”。
```

### A12.23 Synthetic-to-Real与数据充分性：最终只以真实域收益决定扩容

- block 2204 · paragraph · body

```text
A12.23 Synthetic-to-Real与数据充分性：最终只以真实域收益决定扩容
```

- block 2205 · paragraph · body

```text
合成预训练的正式价值判断改为三条：①在相同真实标注量下是否提高真实高退化R2/R1与Vessel指标；②达到同一真实目标性能所需的真实母体/碎片量是否下降；③跨相机、材料、器型或自然风化域是否更稳。若10万/50万合成碎片不能在这些真实指标上带来收益，则停止扩容并审计生成分布、shortcut和任务错位，不用合成规模本身作为成果。
```

### B2.3 器物成员集合GT与关系闭合

- block 2267 · paragraph · body

```text
B2.3 器物成员集合GT与关系闭合
```

- block 2268 · paragraph · body

```text
Level 3评测要求每个eligible object拥有member_manifest：object_id、全部已入库fragment_id、已知missing_fragment/碎屑去向、member_set_complete、R2边集合、R1定义域、UNKNOWN/争议关系、复核者、label_version与hash。V_G(q)从该manifest派生，不能从模型结果反推。若某母体只知道若干邻接但不知道是否还有同器物碎片遗失或未入库，则只能参加Level 1/2的限定评测，不能进入完整成员恢复主分母。
```

- block 2269 · paragraph · body

```text
R1是“同器物且无直接历史断裂接触”，不是“暂时拼不上”。因此member_set闭合和R2关系闭合必须分开审计：先确认哪些fragment属于该object，再确认哪些pair有历史直接接触。R2缺边不能自动把pair改成R1；证据不足保留UNKNOWN。
```

### B3 必须采到的数据

- block 2299 · table_cell_paragraph · body/table59/row10/cell1

```text
器物成员GT
```

- block 2300 · table_cell_paragraph · body/table59/row10/cell2

```text
object_id、member_manifest、member_set_complete、全部fragment_id、missing/UNKNOWN、R1/R2关系图、复核与版本hash
```

- block 2301 · table_cell_paragraph · body/table59/row10/cell3

```text
未闭合只做邻片/同器物候选诊断，不进入Whole-Vessel主评测
```

### D6.5 器物成员恢复页（V1.47新增）

- block 3105 · paragraph · body

```text
D6.5 器物成员恢复页（V1.47新增）
```

- block 3106 · paragraph · body

```text
结果页采用“三层视图”而不是把所有候选混在一个Top-K：第一栏Direct Neighbor Candidates只显示R2及局部接触证据；第二栏Same-Vessel Candidates显示R1/R2同器物成员及器物身份支持；第三栏Predicted Vessel Set显示当前已纳入成员、待核验成员、被驳回成员、UNKNOWN、Vessel Precision/Recall仅在有GT的评测模式显示。用户接受/驳回某成员后生成新的revision，系统可以重新检索全库并显示“新增成员导致哪些旧关系被加强、削弱或撤回”。
```

- block 3107 · paragraph · body

```text
比赛演示默认从一块新query开始：采集/导入→全库粗检→R2邻片→形成初始Vessel Memory→发现R1远距离成员→人工核验→成员集更新或停止。若当前模型尚未通过Level 3验证，界面必须标“研究模式/成员候选”，不得把候选集合称为已恢复器物。
```

### D10.2 应用价值、社会价值与AI必要性的证据矩阵

- block 3188 · paragraph · body

```text
D10.2 应用价值、社会价值与AI必要性的证据矩阵
```

- block 3190 · table_cell_paragraph · body/table82/row1/cell1

```text
价值维度
```

- block 3191 · table_cell_paragraph · body/table82/row1/cell2

```text
必须记录
```

- block 3192 · table_cell_paragraph · body/table82/row1/cell3

```text
希望证明的结论
```

- block 3193 · table_cell_paragraph · body/table82/row1/cell4

```text
禁止夸大
```

- block 3194 · table_cell_paragraph · body/table82/row2/cell1

```text
专家搜索负担
```

- block 3195 · table_cell_paragraph · body/table82/row2/cell2

```text
完成一个任务的人时/墙钟、浏览候选数
```

- block 3196 · table_cell_paragraph · body/table82/row2/cell3

```text
RelicWeave相对人工和传统候选是否减少筛查
```

- block 3197 · table_cell_paragraph · body/table82/row2/cell4

```text
机器负责搜索，专家负责最终确认
```

- block 3198 · table_cell_paragraph · body/table82/row3/cell1

```text
实物操作风险
```

- block 3199 · table_cell_paragraph · body/table82/row3/cell2

```text
拿取、翻转、实体试拼次数
```

- block 3200 · table_cell_paragraph · body/table82/row3/cell3

```text
数字筛选后是否减少无意义实体操作
```

- block 3201 · table_cell_paragraph · body/table82/row3/cell4

```text
对脆弱碎片的保护价值
```

- block 3202 · table_cell_paragraph · body/table82/row4/cell1

```text
高退化可用性
```

- block 3203 · table_cell_paragraph · body/table82/row4/cell2

```text
D0→Dn的Hit/Cov/Vessel曲线
```

- block 3204 · table_cell_paragraph · body/table82/row4/cell3

```text
传统方法何时明显下降，RelicWeave是否更平缓
```

- block 3205 · table_cell_paragraph · body/table82/row4/cell4

```text
AI只在传统假设失效场景主张必要性
```

- block 3206 · table_cell_paragraph · body/table82/row5/cell1

```text
整器物恢复
```

- block 3207 · table_cell_paragraph · body/table82/row5/cell2

```text
Vessel Precision/Recall/F1、完整找回率
```

- block 3208 · table_cell_paragraph · body/table82/row5/cell3

```text
能否从单片找回数据库中的同器物成员
```

- block 3209 · table_cell_paragraph · body/table82/row5/cell4

```text
从局部拼接工具升级为器物身份恢复工具
```

- block 3210 · table_cell_paragraph · body/table82/row6/cell1

```text
经济/部署成本
```

- block 3211 · table_cell_paragraph · body/table82/row6/cell2

```text
建库人时、设备摊销、推理、维护、专家复核
```

- block 3212 · table_cell_paragraph · body/table82/row6/cell3

```text
节省的专家时间是否覆盖新增数据和系统成本
```

- block 3213 · table_cell_paragraph · body/table82/row6/cell4

```text
不把“候选缩小”直接换算成ROI
```

- block 3214 · table_cell_paragraph · body/table82/row7/cell1

```text
社会/文化价值
```

- block 3215 · table_cell_paragraph · body/table82/row7/cell2

```text
可恢复器物信息、可减少遗漏、可审计证据
```

- block 3216 · table_cell_paragraph · body/table82/row7/cell3

```text
是否提高文物数字整理与研究效率
```

- block 3217 · table_cell_paragraph · body/table82/row7/cell4

```text
定性价值须由真实从业者访谈/任务证据支持
```

### 10 国赛与CVPR交付计划

- block 3522 · paragraph · body

```text
比赛主交付统一围绕“真实碎片搜索负担”而不是算法名：现场从一块新query开始，完成采集/导入与QA、全库检索、R2邻片候选、R1同器物候选、器物成员集合或证据不足停止，并保留人工核验和版本日志。高磨损场景必须提供传统算法/规则基线和学习方法的公平对照，解释为什么简单样本不需要AI、为什么大库/退化/R1场景需要学习与关系推理。自动采集台、3D、RL、CTM和UA-IFRMN都只有在实测收益成立后才进入比赛主展示。
```

- block 3523 · paragraph · body

```text
论文主交付从“系统功能清单”收敛为一个清楚科学问题。候选主线按证据强度排序：A 高退化条件下的Robust Fragment Retrieval；B R2条件的Contact-Conditioned Vessel Identity Expansion与UA-IFRMN；C Fragment-to-Vessel Membership Recovery；D Physics-Guided Synthetic-to-Real Pretraining；E Active Evidence Acquisition。一次投稿只选一条主贡献，其余作为必要支撑或后续工作；文化遗产应用价值不能替代通用视觉问题、强基线和可归因机制证据。
```

### 10.1 竞赛方向：用“真痛点→真操作→真改进”组织叙事

- block 3526 · paragraph · body

```text
10.1 竞赛方向：用“真痛点→真操作→真改进”组织叙事
```

- block 3527 · paragraph · body

```text
竞赛陈述固定从现实流程开始：海量混合碎片中，专家首先要解决“哪些值得比较、哪些属于同一器物”，而不是直接面对已知正确pair。项目展示顺序应是人工/传统方案的可用边界→高磨损和大库带来的失败→RelicWeave如何缩小候选→如何找到R1远距离成员→如何恢复器物成员集合→专家如何最终确认。技术先进性服务于这个工作流，不把CTM、Transformer、CUDA或硬件数量当价值本身。
```

- block 3529 · table_cell_paragraph · body/table92/row1/cell1

```text
竞赛叙事块
```

- block 3530 · table_cell_paragraph · body/table92/row1/cell2

```text
核心内容
```

- block 3531 · table_cell_paragraph · body/table92/row1/cell3

```text
验收/边界
```

- block 3532 · table_cell_paragraph · body/table92/row2/cell1

```text
痛点证据
```

- block 3533 · table_cell_paragraph · body/table92/row2/cell2

```text
库规模、人工耗时、候选浏览/实物操作、退化样本失败
```

- block 3534 · table_cell_paragraph · body/table92/row2/cell3

```text
至少有真实任务或相关从业者访谈；无行业数据时明确标内部试验。
```

- block 3535 · table_cell_paragraph · body/table92/row3/cell1

```text
AI必要性
```

- block 3536 · table_cell_paragraph · body/table92/row3/cell2

```text
传统算法清晰样本基线 + 高退化/弱对应对照
```

- block 3537 · table_cell_paragraph · body/table92/row3/cell3

```text
允许传统法在D0强；重点看高退化、大库和R1。
```

- block 3538 · table_cell_paragraph · body/table92/row4/cell1

```text
技能展示
```

- block 3539 · table_cell_paragraph · body/table92/row4/cell2

```text
真实采集/QA、模型推理、设备/软件联调、故障恢复、证据核验
```

- block 3540 · table_cell_paragraph · body/table92/row4/cell3

```text
四岗位都有可见技术操作，避免纯PPT讲算法。
```

- block 3541 · table_cell_paragraph · body/table92/row5/cell1

```text
应用价值
```

- block 3542 · table_cell_paragraph · body/table92/row5/cell2

```text
节省筛查时间、减少无意义试拼、提高成员找回、降低遗漏
```

- block 3543 · table_cell_paragraph · body/table92/row5/cell3

```text
全部按完整工作流分母测，不把局部模型指标冒充ROI。
```

- block 3544 · table_cell_paragraph · body/table92/row6/cell1

```text
创新展示
```

- block 3545 · table_cell_paragraph · body/table92/row6/cell2

```text
高退化鲁棒性、整器物成员恢复、关系记忆/主动补采中的已验证部分
```

- block 3546 · table_cell_paragraph · body/table92/row6/cell3

```text
研究候选未通过就标实验模式，不冒充稳定能力。
```

### 10.2 论文方向：一套数据底座，多条可独立收敛的研究问题

- block 3548 · paragraph · body

```text
10.2 论文方向：一套数据底座，多条可独立收敛的研究问题
```

- block 3549 · paragraph · body

```text
优先顺序由实验决定而不是由想法“看起来高级”决定。先跑EXP10退化曲线和EXP11整器物任务，确认问题本身有足够难度和方法空间；再用EXP12判断R2上下文是否真的给R1带来信息。若Oracle-R2上限明显、Predicted-R2能在错边下保持收益，则UA-IFRMN可升级为方法主线；若关系机制不成立，但A12的物理退化预训练在真实域稳定增益，则把Synthetic-to-Real转为主线。
```

- block 3550 · paragraph · body

```text
顶会目标不要求一次把比赛系统所有模块写进论文。最强版本应围绕一个可以被其他视觉任务理解的问题：高退化partial observation、typed relational reasoning、set membership recovery或physics-guided sim-to-real。数据、代码、协议、强基线和负结果比系统模块数量更重要。
```

### 10.3 竞赛与论文共享的证据底座，但结论严格分开

- block 3551 · paragraph · body

```text
10.3 竞赛与论文共享的证据底座，但结论严格分开
```

- block 3552 · paragraph · body

```text
两条路线共享真实数据身份、member/neighbor GT、冻结split、退化压力测试、传统/学习基线和工作流日志。比赛可以强调专家减负、社会价值、可操作性与系统完整；论文只能强调被独立实验支持的方法/任务贡献。比赛演示成功不等于论文创新成立，论文模型增益也不自动证明真实工作流节时。
```

### 11 本次归位与历史记录

- block 3596 · paragraph · body

```text
V1.47统一“高退化鲁棒检索→R2邻片→R1同器物→整器物成员恢复”的最新主线，新增Vessel Membership指标、性能—退化曲线、Oracle/Predicted/Corrupted-R2验证、成员GT、整器物UI和竞赛/论文双路线。该更新覆盖了现行正文中仅以“找到一个邻片”为最终目标的旧叙事，但不删除其仍有效的邻片指标；旧Hit/Cov仍作为Level 1核心指标。历史实验数据、旧FAIL/STOP/NOT_*、A12/VesselForge/PG-Frag接口和已冻结数值全部保留，不因最终目标升级而改写。
```

### CURRENT_CLOSEOUT→USER replacement and deletion context

REPLACED BASELINE block 1 · 
```text
V1.47 A12／VesselForge／PG-Frag 收口版 2026年10月7日
```

REPLACEMENT USER block 1 · 
```text
V1.47 整器物成员恢复 × 高退化鲁棒检索 × 竞赛/论文双主线整合版  2026年10月7日
```

REPLACED BASELINE block 2 · 
```text
我们研究低质量部分观测下的碎片邻接候选检索。系统从真实碎片照片出发，在混合碎片库中提出值得人工核验的邻片候选；证据不足时，提出有成本约束的补采建议或停止推荐。比赛交付可运行、可恢复的辅助系统，研究交付能够经独立对照验证的方法机制。
```

REPLACEMENT USER block 2 · 
```text
我们研究真实低质量、部分观测与物理退化条件下的文物/器物碎片检索与器物成员恢复。系统从任意一块查询碎片出发，先在混合碎片库中提出直接历史邻片R2候选，再联合二维外观、断口、三维几何、材质、纹样、壁厚、曲率和已发现关系，检索同器物但非直接邻接的R1成员；长期目标是在给定数据库范围内恢复该器物的高置信成员集合。证据不足时系统拒绝强判、给出缺失证据与有成本约束的补采建议。比赛交付强调真实工作流、专家减负与可解释候选；论文交付强调高退化鲁棒检索、R2→R1关系推理、整器物成员恢复和Synthetic-to-Real的可归因机制。
```

REPLACED BASELINE block 88 · 1 文档体系与现行口径
```text
本文件包含总纲、四岗位完整执行正文、软硬件、联调、验收、完整合成实验室、历史附录以及两个独立三维基础设施子项目方案，现行版本统一V1.46。A12给出合成实验编排、预训练与诊断总览；附录G规定A12编排层、退化层、数据与训练流程；附录I规定VesselForge完整方案；附录J规定PG-Frag完整方案；附录H继续保留V1.44问题修订与验收索引。原历史数值、FAIL、STOP和旧协议保留，不能按新口径直接改写。
```

REPLACEMENT USER block 88 · 1 文档体系与现行口径
```text
本文件包含总纲、四岗位完整执行正文、软硬件、联调、验收、完整合成实验室、历史附录以及两个独立三维基础设施子项目方案，现行版本统一V1.47。总纲第2章给出最新统一任务、应用价值边界和评测合同；A6维护长期科研创新；A8把科研假设转成实验卡；A12与附录G负责合成、退化、预训练和诊断；附录I/J分别规定VesselForge与PG-Frag。附录A至F及历史实验段落继续作为冻结证据保留，旧数值与判决不能按V1.47的新目标直接改写。
```

REPLACED BASELINE block 185 · 2 合并主线与边界
```text
主问题是给定真实可获得的观测、候选检查预算和误导风险，如何找回邻片并识别观察不足。输入包括整片2D、断口2D和质量信息；合格3D、可信上下文是可选增强。输出包括有序候选、来源可追溯的证据、待核验状态、补采或停止原因。
```

REPLACEMENT USER block 207 · 2 合并主线与边界
```text
主问题升级为：给定一块真实可获得观测的查询碎片q、一个混合碎片数据库G、候选检查预算和误导风险约束，先可靠找回直接历史邻片R2并识别观察不足，再利用碎片自身多模态证据、已发现局部关系和器物级上下文检索R1，最终尽可能恢复G中与q属于同一物理器物的成员集合V(q)。输入仍以整片2D、断口2D和质量信息为基础；合格3D、可信上下文和主动补采是可选增强。输出从单一Top-K扩展为R2邻片候选、R1同器物非邻片候选、器物成员集合、来源可追溯证据、UNKNOWN/拒识、补采或停止原因。
```

REPLACED BASELINE block 2591 · D10 用户价值测试与成本
```text
比较人工流程、人工加简单候选及人工加新方法证据三种条件。不同难度匹配任务随机交叉分配，避免同一人重复同题记忆优势。记录正确判断耗时、看过候选数、误配漏配、补拍和退出。
```

REPLACEMENT USER block 3182 · D10 用户价值测试与成本
```text
用户价值试验升级为四类条件：纯人工；人工+传统几何/规则候选；人工+静态学习候选；人工+RelicWeave关系/器物成员证据。任务分为直接邻片查找、同器物成员发现和整器物成员恢复三种难度，并按清晰/高退化分层。不同条件随机交叉或顺序平衡，避免同一人重复同题记忆优势。记录正确判断耗时、看过候选数、实物拿取/试拼次数、误配漏配、补拍、退出和最终成员集合质量。
```

REPLACED BASELINE block 2955 · 历史附录使用说明
```text
以下A至F为原实验及工程历史，Q等级、指标、阈值、模型名、资源和判决按当时协议解释，不直接与V1.45合并。当前新工作用第4至9章、G与H，不恢复归档未定义编号或旧门。
```

REPLACEMENT USER block 3604 · 历史附录使用说明
```text
以下A至F为原实验及工程历史，Q等级、指标、阈值、模型名、资源和判决按当时协议解释，不直接与V1.47的新Level 2/3任务合并。V1.47新增的整器物成员恢复、退化鲁棒性与R2→R1指标只对新冻结实验生效；除非专门复跑并保存新manifest，不能从旧Hit@K或旧pair实验反推Vessel Recall、真实高磨损鲁棒性或UA-IFRMN有效。当前新工作用第4至10章、G/H/I/J；历史附件继续用于重现、审计与保护原始证据。
```

DELETED BASELINE block 5 · 
```text
V1.47（2026年10月7日）为 A12、VesselForge 与 PG-Frag 的实现收口和证据归位版：维持三项目的独立边界，补入本轮实现状态、诊断证据及资格缺口。PG-Frag 当前仅有 virgin elastic 固定裂面 bridge 与未形成断开的开口历史 toy；12 状态中 step_index=0..7 尚非全点损伤（step_index=7 的 D 范围为 2/3–1），只有 step_index=8..11 全点 D=1，但 bulk 仍承载。moving-front 单次运行因审计字段错配在 wrench、KKT、G 之前停止。VesselForge 证据限于解析族、几何候选、条件证明、理想曲线距离和来源审阅；A12 计数仍以软件 QA 与未校准数据为主。本次未新增模型成绩或完整物理合格包；历史指标、FAIL、STOP、NOT_ESTABLISHED 判决和既有导航继续保留。
```

DELETED BASELINE block 1594 · A12.19 实施输出与研究判断
```text
A12.19 当前状态（2026-10-07）：本节所列 Release 能力仍是目标接口与验收清单，不代表已完成发布。当前 31 个退化轴、155 个档位/检查组合属于软件 QA；其中 9 个轴有测量记录、36 个非零级别，均来自 1 个母体且未校准。16 个纹样族 ID 尚无经历史样式验证的族，12 个材料 ID 尚无经物理校准的材料。端到端检索收益、真实迁移、真实样本需求下降和规模交付均未建立，完整物理合格包为 0。负责人给出的工程进度估计仍为 PG-Frag 25–35%、VesselForge 30–40%、A12 30–40%；这些比例是工程判断，不代表物理准确度或资格覆盖率。
```

DELETED BASELINE block 1623 · A12.20 双子项目的独立性、非锁定与升级规则
```text
A12.20 当前实施与资格边界（2026-10-07）：独立仓库、公共合同与可替换后端是架构边界；局部源代码接受或诊断 toy 不等于完整实现或项目资格。PG-Frag 的固定界面与开口控制仍未形成断口分离；moving-front 在合同字段错误处停止。VesselForge 尚无历史器型、生产几何、唇口或实体全局壁厚资格。A12 仍承担观测、权限、关系、训练与诊断编排，不复制两个子项目的内核。
```

DELETED BASELINE block 2900 · 10 国赛与CVPR交付计划
```text
比赛主交付包括真实新查询流程、原图与GT审计、稳定基线或成立的新方法、风险与不足、补采增强、四人操作、离线恢复、实测价值和明确适用域。自动采集台、3D、RL及CTM不全部列为最低交付。
```

DELETED BASELINE block 2901 · 10 国赛与CVPR交付计划
```text
论文主交付包括科学问题、最接近工作、同输入强基线、独立主结果、机制消融、质量与缺失、开放库、成本、失败及复现。METHOD-H1局部互补或METHOD-H3候选条件补采选择证据较强者为核心，架构复杂度不是必要条件。
```

DELETED BASELINE block 2947 · 11 本次归位与历史记录
```text
V1.47（2026-10-07）收口记录：本次更新实施状态、证据边界与后续资格门，并在不改历史文字、数值或导航的前提下修复缺失的东亚字体映射、A12.17 第 39 表深色表头字色及活动版本页眉/日期页脚；未新增模型成绩或完整物理合格包。moving-front 单次运行因审计字段错配在 wrench/KKT/G 前停止，未重试；objectivity 与 native C4 均为经独立审阅接受的 SOURCE_ONLY；VesselForge 解析/几何证据和 A12 软件 QA 仍未达到生产或物理资格。V1.46 全文及导航保持原样，历史指标、FAIL、STOP 与 NOT_ESTABLISHED 判决不变。备份交付回执固定于 `relicweave-synlab/docs/handover/20261007/BACKUP_DELIVERY_RECEIPT.json`；该后置 sidecar 将记录最终三仓 HEAD 与文件清单，不写入本记录以避免循环引用。
```

DELETED BASELINE block 4207 · 附录G A12可控合成碎片实验室完整实现方法（双子项目编排层）
```text
G0 当前状态（2026-10-07）：本规则已明确底层内核归属，但当前只是局部实现与来源证据归位，不表示端到端 Asset→Job/Result→Release 链路已完整验收。PG-Frag bridge/opening 是诊断 toy；moving-front 因审计字段错配停止。VesselForge native C4 仅完成 driver/runner 来源审阅，未运行 CAD 或 STEP，也没有实体级 wall/lip 结论。
```

DELETED BASELINE block 6093 · G22.6 1000片精度与资源基准
```text
G31.1 V1.47 收口核对（2026-10-07）：本节列出的专项签收项目仍是待完成的资格门。当前 31 轴与 155 项 QA 记录没有替代逐档物理校准；16 个纹样族 ID 没有历史样式验证；原方案所列四个必做碎裂后端、完整三方发布谱系、真实检索对照和规模资源实测仍未整体签收。局部来源审阅、几何证明和诊断运行仅按各自范围记录，不晋级为完整程序或物理资格。
```

DELETED BASELINE block 6297 · 附录I VesselForge：通用三维器物与纹样生成平台（独立子项目方案）
```text
VesselForge 当前状态（2026-10-07）：已有 bowl/beaker/jar 三个解析参数族、两个默认 CAD 实例，以及局部二维几何候选与理想曲线距离证据；仍有 0 个经历史参考验证的器型族、0 个经资格确认的生产实体和 0 个校准材料/真实纹样外观。最新 native C4 来源审阅为 SOURCE_ACCEPTED，仅接受源代码合同，CAD/STEP 未运行。
```

DELETED BASELINE block 6749 · 附录J PG-Frag：通用三维物理断裂与碎片生成引擎（独立子项目方案）
```text
PG-Frag 当前状态（2026-10-07）：固定裂面 virgin elastic bridge 与开口历史控制均为诊断 toy，未证明裂纹增长或碎片分离。12 状态轨迹中 step_index=0..7 均非全点损伤；step_index=6 的 D 范围为 0–1，step_index=7 为 2/3–1；仅 step_index=8..11（第 9–12 个状态）全点 D=1。bulk 仍承载，未形成 fragment disconnect。moving-front 唯一获准尝试因 schema 字段错配失败并按单次失败规则停止；没有 wrench、KKT、G 或 primary result。当前证据不构成材料校准、方向/网格偏差收敛、动态多接触或完整三维物理断裂资格。后续算法方向采用连续 MLS 与 support-topology-restricted H/front PU enrichment，停止将 Bool-only 作为主路线；这是基于有限裂片两侧可见支撑集突变和 ghost-jump 反例的工程路线修正，不是已证明的新颖性或物理资格。
```
