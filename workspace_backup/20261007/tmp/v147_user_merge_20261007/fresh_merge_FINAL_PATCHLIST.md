# Final planning-text patch list

These are the only eight paragraph text changes from fresh_merge_candidate.docx to fresh_merge_final_candidate.docx. They are confined to planning/specification sections; no protected closeout/status or historical paragraph changed.

## 1. B2.3 closed gallery membership

Paragraph index: 2168

Old text:

Level 3评测要求每个eligible object拥有member_manifest：object_id、全部已入库fragment_id、已知missing_fragment/碎屑去向、member_set_complete、R2边集合、R1定义域、UNKNOWN/争议关系、复核者、label_version与hash。V_G(q)从该manifest派生，不能从模型结果反推。若某母体只知道若干邻接但不知道是否还有同器物碎片遗失或未入库，则只能参加Level 1/2的限定评测，不能进入完整成员恢复主分母。

New text:

Level 3评测要求每个eligible object拥有member_manifest：object_id、全部已入库fragment_id、已知missing_fragment/碎屑去向、member_set_complete、R2边集合、R1定义域、UNKNOWN/争议关系、复核者、label_version与hash。V_G(q)从该manifest派生，不能从模型结果反推。仅当冻结图库G内的member归属尚未闭合时，母体才排除Level 3完整成员恢复主分母；原器物仍有碎片遗失或未入库不会自动排除，只须把已知去向作为审计信息记录。

## 2. A6.16 offline truth boundary

Paragraph index: 1112

Old text:

UA-IFRMN 必须显式尊重现行标签定义：R2 是原碎裂事件当前叶子片间的直接历史邻接，R1 是同器物但无直接历史断裂接触。因此，A—B 为 R2、B—C 为 R2，并不能推出 A—C 为 R2；它只能为 “A 与 C 属于同一器物” 提供强结构证据。最终 A—C 是 R1、R2 还是 UNKNOWN，仍要由直接接触证据和历史邻接真值判定。

New text:

UA-IFRMN 必须显式尊重现行标签定义：R2 是原碎裂事件当前叶子片间的直接历史邻接，R1 是同器物但无直接历史断裂接触。因此，A—B 为 R2、B—C 为 R2，并不能推出 A—C 为 R2；它只能为 “A 与 C 属于同一器物” 提供强结构证据。最终A—C的R0/R1/R2物理关系后验及独立UNKNOWN/abstention，仅在线由合法观测形成；历史邻接真值只作离线标签与评测，不进入在线推理。

## 3. A6.16 relation algebra clarification

Paragraph index: 1113

Old text:

历史断裂/邻接真值只可作为离线训练标签、损失、按母体分组的split审计及评测标签；推理时只可使用合法ObsPack。GT标签用于离线监督是允许的，但GT pose、motherID、true relation graph与TruthPack不能进入在线特征、memory或candidate generator。provenance ID用于审计和去相关，不作为身份特征；姿态字段记录predicted_pose_hat及其不确定性。UNKNOWN表示认识论上的证据不足/拒判，不是第四种物理关系；应保持P_R2≤P_same，缺少R2证据不能推出R1。

New text:

历史断裂/邻接真值只可作为离线训练标签、损失、按母体分组的split审计及评测标签；推理时只可使用合法ObsPack并产生预测关系后验或UNKNOWN/abstention。GT标签用于离线监督是允许的，但GT pose、motherID、true relation graph与TruthPack不能进入在线特征、memory或candidate generator。provenance ID用于审计和去相关，不作为身份特征；姿态字段记录predicted_pose_hat及其不确定性。UNKNOWN是独立的认识论拒判状态，不是第四种物理关系；物理关系后验只覆盖R0/R1/R2，保持P_R2≤P_same，缺少R2证据不能推出R1。同一器物same-vessel身份在闭合成员集合中构成等价/传递关系；直接邻接R2和同器物非邻接R1各自都不具传递性。下表是预测边的soft belief推理，不是历史GT事实或硬合并。

## 4. A6.16 table heading

Paragraph index: 1114

Old text:

关系组合

New text:

预测关系组合

## 5. A6.17 typed relation posterior

Paragraph index: 1132

Old text:

研究实现上建议把 same-vessel 与 direct-contact 解耦成两个相关但不同的头：P_same(i,j) 表示器物身份兼容，P_R2(i,j) 表示直接历史邻接；随后由 typed relation head 在 R0/R1/R2/UNKNOWN 上给出最终分布。这样多跳图只影响 P_same 或 vessel compatibility，不会错误地让 R2 具备传递性。

New text:

研究实现上建议把 same-vessel 与 direct-contact 解耦成两个相关但不同的头：P_same(i,j) 表示器物身份兼容，P_R2(i,j) 表示直接历史邻接；随后由typed relation head输出R0/R1/R2物理关系后验，并将认识论UNKNOWN/abstention作为独立拒判状态。这样多跳图只影响 P_same 或 vessel compatibility，不会错误地让 R2 具备传递性。

## 6. A12.21 fixed-observation and degradation semantics

Paragraph index: 2105

Old text:

退化评测分开两条轨道：固定观测的合成扰动/历史GT回放用于配对诊断；真实磨损、材料流失、新崩边、二次断裂、事件变化与fragment leaf lineage作为新的物理事件/版本记录。后者更新current_fit_valid、evidence_visible和current-leaf relations，并保留历史R2事实及其版本，不以当前状态覆盖历史邻接真值。

New text:

退化评测分开两条轨道：固定物理碎片及历史GT，仅改变观测条件，用于配对诊断；真实磨损、材料流失、新崩边、二次断裂、事件变化与fragment leaf lineage作为新的物理事件/版本记录。后者更新current_fit_valid、evidence_visible和current-leaf relations，并保留历史R2事实及其版本，不以当前状态覆盖历史邻接真值。D1–D4在物理量映射完成并校准前仅为压力配方/强度档，不得称为轻度或严重真实磨损或真实年代等级；D5是独立真实域确认，不是同一有序严重度轴的第五级。31条退化轴QA状态维持UNCAL。

## 7. 2.2.2 object-equal macro and cluster CI

Paragraph index: 317

Old text:

分母边界补充：只有|V_G(q)|>0时才按常规闭合集合定义报告成员召回；此时若预测集合为空，Recall=0、Precision=NA、F1=0。若|V_G(q)|=0，应单独报告member-absent判定、false-inclusion数量/率及abstention；真值与预测都为空只记为correct-empty，不能把Precision、Recall或F1伪记为1。开世界样本及未通过完整工作流资格的样本分开计数，不并入Level 3闭合集合主分母。汇总按器物等权宏平均，区间按独立器物聚类估计；query加权均值仅作补充。

New text:

分母边界补充：只有|V_G(q)|>0时才按常规闭合集合定义报告成员召回；此时若预测集合为空，Recall=0、Precision=NA、F1=0。若|V_G(q)|=0，应单独报告member-absent判定、false-inclusion数量/率及abstention；真值与预测都为空只记为correct-empty，不能把Precision、Recall或F1伪记为1。开世界样本及未通过完整工作流资格的样本分开计数，不并入Level 3闭合集合主分母。汇总先在每个器物内对query等权平均，再对器物等权宏平均；区间按独立器物聚类估计，若同批次或来源相关则按更高层来源簇估计。query加权均值仅作补充。

## 8. A6.20 mandatory Oracle controls

Paragraph index: 1210

Old text:

Oracle-R2是特权离线诊断条件，用于检查已知关系上下文是否有信息；它不是严格的信息论上界，也不是可部署性能。比较时尽量匹配候选集合、上下文数量/质量与预算，并加入shuffle-neighbor对照及可行时的等量GT-R1对照。真实合格数据与闭合GT足以先做静态/上下文信息测试；物理pack只作为物理合成或物理预训练主张的门槛。

New text:

Oracle-R2是特权离线诊断条件，用于检查已知关系上下文是否有信息；它不是严格的信息论上界，也不是可部署性能。比较必须匹配candidate pool、context count、quality、fields、budget与source correlation，并加入shuffle-neighbor对照及可行时的等量GT-R1对照；无法匹配则标为未决、不可归因。真实合格数据与闭合GT足以先做静态/上下文信息测试；物理pack只作为物理合成或物理预训练主张的门槛。
