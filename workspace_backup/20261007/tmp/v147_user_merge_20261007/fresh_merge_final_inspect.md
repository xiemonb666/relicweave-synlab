## B2.3 器物成员集合GT与关系闭合 hits=[2167]
[2167] B2.3 器物成员集合GT与关系闭合
[2168] Level 3评测要求每个eligible object拥有member_manifest：object_id、全部已入库fragment_id、已知missing_fragment/碎屑去向、member_set_complete、R2边集合、R1定义域、UNKNOWN/争议关系、复核者、label_version与hash。V_G(q)从该manifest派生，不能从模型结果反推。若某母体只知道若干邻接但不知道是否还有同器物碎片遗失或未入库，则只能参加Level 1/2的限定评测，不能进入完整成员恢复主分母。
[2169] R1是“同器物且无直接历史断裂接触”，不是“暂时拼不上”。因此member_set闭合和R2关系闭合必须分开审计：先确认哪些fragment属于该object，再确认哪些pair有历史直接接触。R2缺边不能自动把pair改成R1；证据不足保留UNKNOWN。
[2170] 此处member_set闭合仅指冻结图库G中、排除query自身后，同一器物的已入库成员集合已闭合；不要求把所有物理上遗失或未采集的碎片补回。未入库碎片去向作为解释与审计元数据记录。成员集合闭合和R2直接邻接图闭合分别审核，R2漏边不改变member set，也不把缺失R2自动标成R1。
[2171] B3 必须采到的数据
## A6.16 从 R2 到 R1 hits=[1111]
[1111] A6.16 从 R2 到 R1 的关系代数：允许“身份传播”，禁止“邻接传播”
[1112] UA-IFRMN 必须显式尊重现行标签定义：R2 是原碎裂事件当前叶子片间的直接历史邻接，R1 是同器物但无直接历史断裂接触。因此，A—B 为 R2、B—C 为 R2，并不能推出 A—C 为 R2；它只能为 “A 与 C 属于同一器物” 提供强结构证据。最终 A—C 是 R1、R2 还是 UNKNOWN，仍要由直接接触证据和历史邻接真值判定。
[1113] 历史断裂/邻接真值只可作为离线训练标签、损失、按母体分组的split审计及评测标签；推理时只可使用合法ObsPack。GT标签用于离线监督是允许的，但GT pose、motherID、true relation graph与TruthPack不能进入在线特征、memory或candidate generator。provenance ID用于审计和去相关，不作为身份特征；姿态字段记录predicted_pose_hat及其不确定性。UNKNOWN表示认识论上的证据不足/拒判，不是第四种物理关系；应保持P_R2≤P_same，缺少R2证据不能推出R1。
[1114] 关系组合
[1115] 允许的推理
## 关系组合 hits=[1114]
[1114] 关系组合
[1115] 允许的推理
[1116] 设计意义
[1117] R2(A,B) + R2(B,C)
[1118] same-vessel(A,C) prior ↑；A-C 的直接邻接类型仍未知。
## typed relation head hits=[1132]
[1132] 研究实现上建议把 same-vessel 与 direct-contact 解耦成两个相关但不同的头：P_same(i,j) 表示器物身份兼容，P_R2(i,j) 表示直接历史邻接；随后由 typed relation head 在 R0/R1/R2/UNKNOWN 上给出最终分布。这样多跳图只影响 P_same 或 vessel compatibility，不会错误地让 R2 具备传递性。
[1133] A6.17 为什么不能只把“邻片概率”喂回去：Scalar Feedback、Latent Feedback 与多假设记忆
[1134] 用户提出的原始思路“预测邻片后，把邻片预测作为下一轮输入，再判断同器物非邻片”应保留为最小基线，但正式候选必须把“反馈什么”做成分层实验。单一 P(R2) 只表达最终置信度，不包含模型是依据断口、几何、纹样还是质量得出的结论，也无法区分“高分但证据冲突”和“高分且多证据一致”。
[1135] 推理资源须预先限定K、局部token数L、迭代数、假设数与重读半径，并报告单query P95时延、峰值VRAM/RAM和端到端FLOPs。RTX 5090规格不能代替目标负载实测；当前吞吐量仍未测，故资源可行性保持未确立。
[1136] 反馈层级
## 真值判定 hits=[1112]
[1112] UA-IFRMN 必须显式尊重现行标签定义：R2 是原碎裂事件当前叶子片间的直接历史邻接，R1 是同器物但无直接历史断裂接触。因此，A—B 为 R2、B—C 为 R2，并不能推出 A—C 为 R2；它只能为 “A 与 C 属于同一器物” 提供强结构证据。最终 A—C 是 R1、R2 还是 UNKNOWN，仍要由直接接触证据和历史邻接真值判定。
[1113] 历史断裂/邻接真值只可作为离线训练标签、损失、按母体分组的split审计及评测标签；推理时只可使用合法ObsPack。GT标签用于离线监督是允许的，但GT pose、motherID、true relation graph与TruthPack不能进入在线特征、memory或candidate generator。provenance ID用于审计和去相关，不作为身份特征；姿态字段记录predicted_pose_hat及其不确定性。UNKNOWN表示认识论上的证据不足/拒判，不是第四种物理关系；应保持P_R2≤P_same，缺少R2证据不能推出R1。
[1114] 关系组合
[1115] 允许的推理
[1116] 设计意义
## A12.21 V1.47退化性能曲线 hits=[2103]
[2103] A12.21 V1.47退化性能曲线：把SyntheticLab变成“物理退化压力测试仪”
[2104] A12新增一类paired counterfactual release：同一clean母体、同一碎片关系、同一query/gallery与基础随机种子，沿磨损、崩缺、表面侵蚀、遮挡、图像质量、3D缺失/增生噪点等单轴或预注册组合轴生成D0→Dn观测。每个release必须同时提供传统算法合法输入、学习模型合法输入和TruthPack，但TruthPack只供评测。输出不仅是某一档准确率，而是每个方法的性能—退化强度曲线、临界失效点、AUC/斜率型诊断和真实域对应样本。
[2105] 退化评测分开两条轨道：固定观测的合成扰动/历史GT回放用于配对诊断；真实磨损、材料流失、新崩边、二次断裂、事件变化与fragment leaf lineage作为新的物理事件/版本记录。后者更新current_fit_valid、evidence_visible和current-leaf relations，并保留历史R2事实及其版本，不以当前状态覆盖历史邻接真值。
[2106] A12.22 Whole-Vessel Episode Generator：为整器物成员恢复生成完整关系世界
[2107] 每个合成母体除R2边外，还必须导出完整member set、R1/R2 typed relation graph、可见/不可见断面、缺失材料和母体级属性。episode生成器把多个母体混成gallery，随机选择query并控制同器物成员数、R1/R2比例、hard negative密度、器型相似度、材质相似度和退化分布；训练端只看合法Obs，评测端用完整Truth计算Vessel Precision/Recall/F1及多轮扩展轨迹。这样A12的数据价值从“更多pair”升级为“可控整器物关系规模”。
## 退化评测分开两条轨道 hits=[2105]
[2105] 退化评测分开两条轨道：固定观测的合成扰动/历史GT回放用于配对诊断；真实磨损、材料流失、新崩边、二次断裂、事件变化与fragment leaf lineage作为新的物理事件/版本记录。后者更新current_fit_valid、evidence_visible和current-leaf relations，并保留历史R2事实及其版本，不以当前状态覆盖历史邻接真值。
[2106] A12.22 Whole-Vessel Episode Generator：为整器物成员恢复生成完整关系世界
[2107] 每个合成母体除R2边外，还必须导出完整member set、R1/R2 typed relation graph、可见/不可见断面、缺失材料和母体级属性。episode生成器把多个母体混成gallery，随机选择query并控制同器物成员数、R1/R2比例、hard negative密度、器型相似度、材质相似度和退化分布；训练端只看合法Obs，评测端用完整Truth计算Vessel Precision/Recall/F1及多轮扩展轨迹。这样A12的数据价值从“更多pair”升级为“可控整器物关系规模”。
[2108] A12.23 Synthetic-to-Real与数据充分性：最终只以真实域收益决定扩容
[2109] 合成预训练的正式价值判断改为三条：①在相同真实标注量下是否提高真实高退化R2/R1与Vessel指标；②达到同一真实目标性能所需的真实母体/碎片量是否下降；③跨相机、材料、器型或自然风化域是否更稳。若10万/50万合成碎片不能在这些真实指标上带来收益，则停止扩容并审计生成分布、shortcut和任务错位，不用合成规模本身作为成果。
## 分母边界补充 hits=[317]
[317] 分母边界补充：只有|V_G(q)|>0时才按常规闭合集合定义报告成员召回；此时若预测集合为空，Recall=0、Precision=NA、F1=0。若|V_G(q)|=0，应单独报告member-absent判定、false-inclusion数量/率及abstention；真值与预测都为空只记为correct-empty，不能把Precision、Recall或F1伪记为1。开世界样本及未通过完整工作流资格的样本分开计数，不并入Level 3闭合集合主分母。汇总按器物等权宏平均，区间按独立器物聚类估计；query加权均值仅作补充。
[318] 退化鲁棒性主实验必须使用paired/counterfactual设计：D0、D1…Dn共享同一母体、关系GT、query、gallery组成和基础随机种子，只改变预注册的磨损、崩缺、缺失、成像或重建退化轴。传统算法、静态学习基线和RelicWeave在相同合法观测权限下比较；不能给传统算法更差输入，也不能让模型读取clean/oracle信息。
[319] 2.3 创新收敛与止损
[320] 第一研究方向METHOD-H1为缺失感知的局部互补审议，第二METHOD-H3为候选条件的带成本补采。一次确认批次只选择一个主要机制比较，CTM、同步、路由与循环均为可替换组件。根据真实开发集及等预算收益选择；确认集只评已经锁定的比较。
[321] 保留新机制需要回答哪里失败、修改哪里、增益如何归因及哪个对照能否定解释。连续两轮没有可归因进展，保留稳定基线并停止该分支；不能用更多照片、更大模型或更复杂硬件同时变化制造无法解释的提升。
## Oracle-R2是特权离线诊断条件 hits=[1210]
[1210] Oracle-R2是特权离线诊断条件，用于检查已知关系上下文是否有信息；它不是严格的信息论上界，也不是可部署性能。比较时尽量匹配候选集合、上下文数量/质量与预算，并加入shuffle-neighbor对照及可行时的等量GT-R1对照。真实合格数据与闭合GT足以先做静态/上下文信息测试；物理pack只作为物理合成或物理预训练主张的门槛。
[1211] 阶段
[1212] 训练／输入设置
[1213] 必须回答的问题
[1214] T0 Pairwise baseline
## 尽量匹配 hits=[1210]
[1210] Oracle-R2是特权离线诊断条件，用于检查已知关系上下文是否有信息；它不是严格的信息论上界，也不是可部署性能。比较时尽量匹配候选集合、上下文数量/质量与预算，并加入shuffle-neighbor对照及可行时的等量GT-R1对照。真实合格数据与闭合GT足以先做静态/上下文信息测试；物理pack只作为物理合成或物理预训练主张的门槛。
[1211] 阶段
[1212] 训练／输入设置
[1213] 必须回答的问题
[1214] T0 Pairwise baseline