# V1.46 总方案只读盘点与最小更新候选

审阅对象：`RelicWeave_V1.46_A12_VesselForge_PGFrag_Integrated_NavFixed.docx`  
SHA-256：`15978a3956fa33e8048cc54c1dad6878a7e19d9c71b84415dcaf8732f041a3b4`（733,634 bytes；只读复核后原件哈希未变）  
提取目录：`tmp/review_20261005/plan_inventory/`

本阶段只解析了 DOCX 包和 `word/document.xml`，没有修改源文档、运行代码测试或渲染页面。完整段落、表格和导航结构见同目录 `plan_inventory.json` 与 `extract.txt`。

## 文档结构与可用锚点

`document.xml` 有 6,846 个段落、176 张表、1,341 行和 4,503 个单元格。提取器按 XML 顺序给段落编号，表格单元格也保留在全局段落索引内。

导航是静态目录：P0007「文档导航」，没有 Word TOC 字段；共有 80 个内部超链接，全部指向现有书签，520 个书签起点，没有外链关系。A12 总览是 P1102（`RW_NAVFIX_015`），附录G是 P4000（`RW_NAVFIX_076`），VesselForge 是 P6016（`RW_NAVFIX_078`），PG-Frag 是 P6429（`RW_NAVFIX_079`）。其余精确目标和正文短引文在 JSON 中。后续插入后 P 序号会顺延，因此作者应以原段落文本和现有书签作为定位依据。

## 方向评估

总目标内部一致。开头写「我们研究低质量部分观测下的碎片邻接候选检索。系统从真实碎片照片出发，在混合碎片库中提出值得人工核验的邻片候选；证据不足时，提出有成本约束的补采建议或停止推荐。比赛交付可运行、可恢复的辅助系统，研究交付能够经独立对照验证的方法机制。」；主合同 P0180 又把输入、候选检查预算、可追溯证据、补采或停止连成一条任务。A12、VesselForge 和 PG-Frag 应继续作为该任务的可控实验基础设施。

当前文件也已经给出正确的资格区分：P0004 说明手机加现有转盘是当前采集方式，并明确「当前实际采集方式是手机加现有转盘，由人员调整角度、停止转动并拍照。手机采集正在作为第一阶段推进；样本量、采集合格率、邻接真值完整度及真实检索效果仍须用交付记录确认。我们尚未证明DIY台、主动补采、循环主干或强化学习有效，也未将它们记为已实现」；P0178 说明「进度报告采用任务状态与证据结论双列：NOT_STARTED、IN_PROGRESS、DONE表示工作状态；SUPPORTED、NOT_ESTABLISHED、NOT_SUPPORTED、STOP表示实验结论。模拟跑通、代码可执行、实物动作成功、任务效果改善和独立研究结论是五种不同成果。」。这套口径应继续覆盖新增内容。

主要风险是开篇 P0006 将三个子项目写成已接入后再完成退化、观测、关系采样、预训练的连续架构，而后文A12大规模预训练、通用VesselForge和通用PG-Frag又包含长远功能与验收规范。即使这些章节是目标设计，读者也可能把架构宣言、局部测试PASS或单次实验结果误当成全链已运行或科学资格已取得。最小修订应补有日期的实现状态和门槛，不覆盖历史记录、不把方案描述整体改成过去式。

A12.7 的 GT/标签隔离设计很强，但现有全链审计揭示执行证据不足：审计报告为 `INCOMPLETE`、30 blockers、已审计碎片行数0、producer/source binding `UNKNOWN`；规范化行由调用方提供，报告没有读取 producer payload，也没有核对实际模型输入张量。因此哈希、元数据、字段白名单声明或聚合计数都不能证明生产者到导出的行级谱系和推理时GT隔离已经成立。

物理资格也要与工程接口分开。只读链审计明确 `physics_qualified=false`、`pretrain_qualified=false`。当前的圆柱浮雕、弹性响应、仿射阈值和受控 cohesive 门分别是窄诊断；不能推导为真实母型泛化、校准陶瓷、自由断裂、裂面几何或训练可用碎片全链。附录J的多后端路线适合作为技术候选表；要求首条最小链一开始实现全部求解器会无证据地扩大范围。

## 证据校准

A12：现有审计 `tmp/review_20261004/implementation/forge_chain_audit_20261004/v2_current_chain_audit.json` 记录30个阻断、0条已审计fragment row、source binding `UNKNOWN`，physics/pretrain资格均为false。它还记录了导出闭合未通过和退化行/来源为0。局部模块测试与runtime/schema门槛可报告为窄通过，但不能替代A3/A4接入、producer payload逐行回读、GT输入隔离或训练包放行。

VesselForge：`vesselforge/experiments/surface_ornament_route_20261004/RUN02_REVIEW_AND_QUALITY_GAP.md` 记录一个闭合圆柱样例、6,402个顶点、12,800个三角面和纹样映射机制通过；同一审查拒绝其为高质量网格，且明示未做真实器物、全局壁厚、PBR/材料或物理资格。壁厚代码的39项窄测试为PASS，但保留STEP资产绑定收据为FAIL，原因 `CANONICAL_BREP_FACE_BOUNDS_MISMATCH:0`，0个站点绑定。两种结果必须并列，不能只报告单元测试。

PG-Frag：`pgfrag/experiments/pd_loaded_diagnostics_20261004/manifest.json` 对A8只放行“加载响应”窄门：9个采样状态、最大位移约21 nm、非零速度/内力、没有键断裂转变。另有8/8 bond-visibility窄库测试通过，但native/全链集成未通过。`pgfrag/tmp/review_20261005/native_resume/native_resume_audit.json` 对B3放行仿射变形下的原生阈值状态审计：3态、每态6,124条有向状态行/3,062对规范键，632对规范键发生状态转变（1,264条有向记录）；没有时间积分、自由裂纹或碎片。受控 cohesive 记录也限定为界面能力门，D分支和半时间步旧失败继续保留。以上不构成材料校准或整机physics qualification。

渲染前置条件检查：指定 bundled Python 可运行，Documents renderer 路径是 `C:\Users\xiemo\.codex\plugins\cache\openai-primary-runtime\documents\26.909.12148\skills\documents\render_docx.py`。它在 Windows 上从 PATH 找 `soffice.exe`；本次只读检查未在 bundled `dependencies\bin\override`、fallback、PATH或常见 Program Files 位置找到 LibreOffice，因此本阶段未渲染。页面视觉检查由主代理另行安排。

## 最小更新候选

候选共有 8 个插入点、21 个普通正文段，已在 `plan_inventory.json.review.candidate_insertions` 给出精确原段索引、文本前缀、邻接样式、加粗标签、完整建议文字和证据文件。建议只追加普通正文段，不加新标题编号或书签，保留当前静态目录与所有旧段落/表格：

- 在 P0006 后写明“架构和验收条款是目标，不代表已接通或取得资格”。
- 在 P1104 后写A12日期进度：全链`INCOMPLETE`、30 gaps、0行、source binding `UNKNOWN`、合格高仿真训练包0，并区分窄测试、迁移及A3/A4接入状态。
- 在A12.7末尾补producer payload逐行比对、单位/坐标/哈希/谱系以及运行时张量审计要求。
- 在附录G导读后写全链放行顺序；任何门失败或未知都不允许预训练资格。
- 在附录I/J开篇并列记录VesselForge与PG-Frag的日期状态和窄试验界限。
- 在J10明确先落一个通过独立门的native后端，多后端表保留为候选路线。
- 在J20.2后补独立重网格、点格旋转、亚体素平移以及`h`、`δ`、过程区、时间步、能量和裂纹方向门；不固定碎片数，不用预绘裂纹代替物理求解。

正文候选在等待主代理按最终证据冻结后批准；本阶段没有改写或导出 DOCX。


## Applied copy and structural audit

Created RelicWeave_V1.46_Implementation_Update_20261005.docx from the unchanged source (SHA-256 15978a3956fa33e8048cc54c1dad6878a7e19d9c71b84415dcaf8732f041a3b4). Output SHA-256: 85f3bb0e6115e208ce51c666d77ee756a4e2b74d67e8d039283574bb6764b531. Only word/document.xml changed; all 23 package parts remain present and all other parts are byte-identical. The 20 inserted paragraphs preserve the original paragraph sequence, 176 tables, 1,341 rows, 4,503 cells, 520 bookmark starts/ends, 80 internal hyperlinks, 0 broken internal anchors, and 2 drawings. The original table subtrees are byte-identical. The source document was not modified. See structural_audit.json and patch_content.json for exact insertion indices and text.
