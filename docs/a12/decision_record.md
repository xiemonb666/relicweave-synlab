# A12 人工裁决记录（D1–D12）

> **性质**：**形式化 + 传播 + 校验**，不重新裁决。本文件逐条照写 Lead 对 `RelicWeave_V1.44` 总文档的裁决，
> 并补齐每条的**出处指针**、**影响面**、**落地动作**与**未落地前的临时口径**。
> **权威输入**：`docs/a12/rig_contract.md` §12「需人工裁决清单」（18 项）、`docs/a12/v144_project_core.md`
> （深读产物）、`configs/a12/capture_contract.json`、`data/a12/reports/rig_coverage_matrix.json`。
> **机器可读副本**：`configs/a12/decision_defaults.json`（**10** 个顶层段，每段带 `source` 与 `assumption`）。
> **只读校验**：`synlab/qc/decision_checks.py`（**13** 项检查）+ `tests/a12/qc/test_decision_checks.py`；
> 对现有库的实测报告见 `data/a12/reports/decision_checks_<store>.json`。
> **诚实规则**：文档没有的数值**一律不发明**——改为「可复算定义」或「标 `assumption` + 重标定条件」；
> 拿不到的模态不得声称拥有，合成独有项标 `synthetic_only`；未落地的项一律给「临时口径」；
> 校验只读，**不为让结果好看而放宽**，缺什么记 `MISSING`。

来源指针约定与 `rig_contract.md` 一致：`T###/p####` = docx body 顺序第 ### 个表格 / 第 #### 个段落（1 基）。

---

## 0. 覆盖对账：§12 的 18 项 → D1–D12

Lead 的裁决以 `D1`–`D12` 编号给出，`rig_contract.md` §12 以 18 行清单给出。两者先对账，避免丢项：

| §12 # | 清单行 | 归属 | 备注 |
|---|---|---|---|
| 1 | `ActionProposal` 两处字段集（p276 vs p638） | **D1** | 残余 `pose_id` 落位 → D12.4 |
| 2 | 出土上下文字段规格 | **D11** | 残余类型/单位/枚举/缺失率 → D12.6 |
| 3 | 最终 M（候选预算） | **D2** | |
| 4 | 停止 δ / K | **D2** | |
| 5 | `PairOutput` schema | **D9** | 残余 dtype / `score_type` 枚举 → D12.5 |
| 6 | R1 误排分母 | **D9** | |
| 7 | 最终论文主指标清单 | **D3** | |
| 8 | 镜头型号/焦距 | **D6** | |
| 9 | 畸变模型与阶数 | **D6** | 残余「近摄是否单独模型」由 D6 的单一模型族 + Gate B 重标定条款覆盖 |
| 10 | 景深数值 | **D6** | |
| 11 | 色温 K | **D6** | |
| 12 | 单件采集时间 | **D7** | |
| 13 | 结构光是否在范围内 | **D5** | |
| 14 | SY-Q 与 Q1–Q3 的映射 | **D3** | 残余 SY-Q5 消融归类 → D12.7 |
| 15 | 8 项质量向量 vs 14 维退化向量 | **D8** | |
| 16 | 仿真首版物理尺寸 vs 真实样片尺寸 | **D12.1** | **唯一未被 D1–D11 点名的整行** |
| 17 | `physical_component` 的 `F_mm` 局部帧 与 断面权威定义 | **D4** | 残余「是否强制回挂世界帧」→ D12.2 |
| 18 | `loss_mask ≡ valid ≡ (kind=="R2")` 是否冗余 | **D10** | 残余「`visible` 层缺列是否补齐」→ D12.3 |

**计数对账（不掩盖差异）**：Lead 的 D12 写「其余 **7** 项」。按 **D 条目数**计是 `18 − 11 = 7`；
按**清单行**核对，D1–D11 实际点名了 **17 行**，未点名的整行只有 **#16（1 行）**。
本记录**不因计数差异丢项**：D12 直接裁决 #16，并补齐 D1–D11 **未闭合的 6 个残余子问题**
（#1b / #2b / #5b / #14b / #17b / #18b），合计 **7 条 D12 条目**（D12.1–D12.7）。
每条残余都在 `decision_defaults.json` 的对应段里以 `unresolved[]` 落地，带 `status`、`temporary_rule`、`owner_decision`。

---

## D1 `ActionProposal` 字段冲突（p276 9 项 vs p638 5 项 vs p574 另一组）

**裁决**：**取并集 + 显式可选性**，不丢任何一侧。

- **必需核心**（6）：`query_id`、`evidence_revision`、`action_id`、`target_region`、`reason`、`expected_cost`
- **执行块**（可空但字段存在，5）：`u_profile_id`、`distance_mode`、`focus_setting_id`、`intrinsics_profile_id`、`expected_roi`
- **可选扩展**（3）：`camera_id`、`target_pose_or_relative_angle`、`light_mode`
- 每条字段标 `source`（`p0276` / `p0638` / `p0574`）与 `optional_extension` 标记。
- 理由（Lead 原文）：**p276 是「建议语义」、p638 是「台架执行参数」，舍弃任一侧都会让 A/C/D 岗断链。**

**出处指针**：`p0276`（A7.2，9 项）、`p0638`（D5.1，5 项）、`p0574`（C10，`pose_id/u_profile_id/light_mode/intrinsics_profile_id`）；
`docs/a12/rig_contract.md` §12 #1；`configs/a12/capture_contract.json:action_proposal`（`set_A_p0276` / `set_B_p0638` / `union_used_by_rig_service`）；
`docs/a12/v144_project_core.md` §4.7（p574 起）。

**影响面**：
- `rig_service` 动作接口与「未合格动作屏蔽」路径（p576：引用旧 `evidence_revision` 的动作**拒收**；翻面/改支撑开新 session）。
- 动作掩码依据（p576：轴 AUTO/MANUAL、状态、回零、装夹、限位、清晰距离、焦点档、灯态、剩余成本）。
- 前端提案表单与 A/C/D 三岗联调契约；`ActionProposal` → `pose_id/u_profile_id/light_mode/intrinsics_profile_id` 的映射表。
- 不影响：已落地的观测/退化/真值模块（本裁决只约束提案层）。

**落地动作**：
1. 字段集以 `decision_defaults.json:action_proposal` 为准（14 项 + 3 档 + 15 条 `source` 指针）。
2. 在 schema 层落一个提案类型（建议落点 `synlab/schemas/spec.py`，该文件的 `StrictModel` 家族已在用，`candidate_pool_size` 见 `:268`）。
3. 执行块「存在但可为 null」必须由 schema 强制（不得靠缺键表达可选）。

**未落地前的临时口径**：任何一侧按自己那套字段实现都不算违规，但**必须**在产物里同时保留另外两侧的字段位（哪怕 `null`），
并在 meta 里标注所用子集；`rig_service` 映射缺 `intrinsics_profile_id` 时不得静默降级。
残余 `pose_id`（p0574 映射集含它，Lead 的 14 项清单未含）**既不加入也不剔除**，记 `unmapped`（→ D12.4）。

**校验**：`defaults.action_proposal_union` —— 声明 **14/14**；代码侧 `ActionProposal` 生产者 **0**（结论 `FAIL`，定位见附录 B-1）。

---

## D2 最终 M 与停止 δ/K（文档无数值）

**裁决**：**不发明数字**，改为可复算定义。

- `M` := **本次评测所用池的规模**，逐 run 记录进结果（`any@M` / `PoolCov@M` 随 `M` 一起报）。
- `δ` := **当前样本量能分辨的最小差异** = **对象簇 bootstrap 95% CI 半宽**（= 该 run 主指标的统计分辨率），**在 dev 上冻结**并写入结果。
- `K` := 最少 **3** 轮，且**「连续两轮变化 < δ」才停**。
- **未冻结 δ 之前，任何「已收敛」结论不得写入能力主张。**

**出处指针**：`p0269`（A6.13：最多 4 tick；TopK 稳定且分数变化小于**开发冻结 δ**连续两轮才停——δ 无值）；
`p0108`（2.2.1 单一评测公式 / 完整分母）、`t007`（retrieve 输入含 M）、`p1093`/`p1106`（CEIL 22k=0.9489 / full=0.9474）；
`p0106`（性能与增益区间一律**母体簇配对双侧 95%**）；`docs/a12/v144_project_core.md` §2.1/§2.4/§9（U17/U18）；
`rig_coverage_matrix.json:human_adjudication` 最关键 3 条之 #2。

**影响面**：
- 所有 `any@M` / `PoolCov@M` 结果的可复算性；「多轮审议 vs 静态」的主比较（无 δ 则该比较不可复算）。
- 机制实验停止规则与 `experiment_spec`；「已收敛/已稳定」全部措辞。
- 附录 G 的 N×Q 曲面与预算口径（M 是候选预算的分母）。

**落地动作**：
1. 结果行增加 `M`（本次池规模）字段，与 `any@M`/`PoolCov@M` 同行写出。
2. 结果文件增加 `delta`（`(ci_high − ci_low)/2`，对象簇 bootstrap 双侧 95%）与冻结记录（冻结 split、冻结时间）。
3. 停止规则实现 `K=3` 下界 + 连续两轮 `< δ`；文档的「最多 4 tick」作为上界保留 → 有效窗口 `3 ≤ rounds ≤ 4`。
4. `δ` 冻结前，停止判定只允许用「最多 4 tick」上限。

**未落地前的临时口径**：`M` 允许以「可复算形式」出现（例如池的候选列表长度），但必须在同一行可导出；
`δ` **不得**用任何猜测值代替，`"已收敛"` 必须写成 `"δ 未冻结，收敛未判定"`。

**校验**：`metrics.m_and_delta_recorded` —— 现有结果行中报告 `any@M` 族的共 **9** 行（`metric_fixture.json`）；
`M` 可复算 **7/9**，`delta` **0/9** → `FAIL`（定位见附录 B-2）。
（`stat_fixture.json` 的 dev bootstrap 实测半宽 = `(0.060000 − 0.019000)/2 = 0.0205`，n_clusters=5，说明 δ **可算**、只是**未记录**。）

---

## D3 SY-Q ↔ Q1–Q3 与主指标清单

**裁决**：

1. **映射按单调对应**：`Q1 现场 ≈ SY-Q0/SY-Q1`、`Q2 当日入库 ≈ SY-Q2/SY-Q3`、`Q3 研究 ≈ SY-Q4/SY-Q5`；
   **SY-Q2 必须「实测统计校准」后才可声明等价**，未校准的记 `unmapped`。
2. **主指标清单冻结为文档点名的 7 项**：
   `any@50 宏`、`Hit@10 宏（含 95% 下界）`、`低质 Hit@10`、`新方法增益 ≥3pt（簇 CI 下界>0）`、
   `干净守卫下降 ≤2pt`、`无邻片误导率 ≤5%（95% 上界 ≤10%）`、`接受覆盖率 ≥80%`。
3. **工时 −30% 作为过程指标单列**（不进主指标清单）。

**出处指针**：`t005`（内部指标合同）、`docs/a12/v144_project_core.md` §2.3、`p0106`（统计规则）；
`p0330`（A9.1「最终论文主指标数量有限」未给清单）、`p0377`（A12.10）；`t031`/`t110`（SY-Q0_OBS…SY-Q5）、`p0464`（Q1/Q2/Q3）；
`docs/a12/v144_project_core.md` §10.3 第 5 项（两套质量命名的实测映射缺口）；`rig_contract.md` §12 #7 / #14。

**影响面**：
- 论文主表的口径与分母（主指标数未定会把「合成 ≥ 扫描台」的覆盖判定拖成不可裁决）。
- 质量口径：`clear`/`daily`/`poor` 三档与 SY-Q0–Q5 六档的对齐；SY-Q2 未校准不得当 Q2 等价物。
- 覆盖矩阵 #14 行（SY-Q↔Q 映射，判定「缺失」）与 #13（Q1–Q3 三级验收，判定「部分」）。
- 工时 −30% 从主指标移到过程指标，改变了「工作流价值」在论文主张里的地位（仍是内部目标）。

**落地动作**：
1. `decision_defaults.json:metric_contract` 冻结 7 项 + 过程指标 + 诊断清单（本记录即来源）。
2. SY-Q ↔ Q1–Q3 对照表落到 `configs/a12/`（覆盖矩阵 #14 的建议落点：`sy_q_mapping.json`），并由 `synlab/qc/` 读取。
3. SY-Q2 未校准时在产物中输出 `unmapped` 标记，不得输出等价声明。

**未落地前的临时口径**：任何主指标表必须**同时列出全部 7 项**（缺一即为口径不完整），
SY-Q2 一律标「未校准候选」，SY-Q5 单独列（→ D12.7）；工时对比必须标 `process`。

**校验**：`metrics.primary_metric_freeze` —— 主指标 **7/7** 冻结且过程指标单列 → `PASS`。

---

## D4 断面权威定义（实测 506/3610 = 14% 冲突）

**裁决**：**以 `interface_id >= 0` 为权威**（它是贯穿 clean truth 与 `corr_*` 的配对键）；`origin_kind` 降为**派生标签**。
要求：冲突计数必须**逐 run 上报**并由写入方修到 0，**不得静默**。

**出处指针**：`t101(D09)`（内外壁/断面/支撑/无效区整数 ID）、`t117`（整数 ID 无有损压缩）、`p1481`（ID 严格可恢复）；
`docs/a12/modality_census.md` §3.2/§3.4（506 / 3610 = 14.0%，资产 `asset_b50819155e25ffe898c9`）；
`tools/build_demo_assets.py:582`（现行**并集**口径）、`:589`（冲突计数）、`:620-621`（`new_surface_definition` 文案）；
`rig_contract.md` §12 #17。

**影响面**：
- **断面的一切下游**：区域 mask 整数 ID（`D09`）、断面 ROI 点云、断口局部 2D/3D、`iface_*` 真值、逐 `interface_id` 的断面面积与 `corr_*` 配对。
- 展示层 `display_lod_glb` 的断面分组（`surface_groups` 与 `surface_group_authority`）。
- 任何以「断面」为分母的统计（面积合计、法向互补、gap p95）。
- 覆盖矩阵 #2 / #7 / #11 / #24 行的判定与补齐方案。

**落地动作**：
1. 写入端把权威谓词改为 `interface_id >= 0`，`origin_kind` 仅作派生标签（`tools/build_demo_assets.py:584`）。
2. 冲突计数器保留（`:589` → `surface_group_authority.origin_interface_vs_interface_id_conflicts`），
   并把 `new_surface_definition` 文案改为 D4 口径（`:620-621`）。
3. 冲突**逐 run 上报**（分母 `faces_total` 同时上报），写入方修到 0。

**未落地前的临时口径**：冲突未到 0 前，以断面为分母的统计必须**同时**报 `conflicts` 与 `faces_total`，
并显式标注该口径混入比例。**主库实测：0 个 GLB 权威块（`NOT_APPLICABLE`）；demo 库实测 2128 / 18410 = 11.56%**（6 个 GLB，定位见附录 B-4）。

**校验**：`surface.authority_conflicts` —— `data/a12`：无 `display_lod_glb` 权威块 → `NOT_APPLICABLE`；
`data/a12_demo/store`：`2128/18410`（11.56%）→ `FAIL`；`data/a12_diversity/store`：`NOT_APPLICABLE`。

---

## D5 结构光 / 激光

**裁决**：文档 0 命中 → **v1 明确排除**（台架是摄影测量 + 多普通 RGB，文档也明确「可靠深度拿不到」）；
但**保留钩子**：合成深度只能作为**上界**提供，标 `synthetic_only`。

**出处指针**：全文检索「结构光 / structured light / laser」命中 **0** 处；`docs/a12/v144_project_core.md` §4.9（结构光/激光：文档未明确）、§9 U9；
`p0100`（多个普通 RGB 相机也**不自动**产生可信深度）；`t073`/`t023`（3D 不合格 → 标缺失，走经验证 2D，缺失不填 0 分）；
`t094-P2`（主动加密采集需 Gate 批准）；`rig_contract.md` §8 拿不到项 / §12 #13。

**影响面**：
- 台架模态清单与覆盖矩阵（结构光/激光**不入**矩阵行；列入即为越权主张）。
- 合成侧深度/法向通道的权限设计（部署白名单已把 `depth_z` 列入 `forbidden_channels`）。
- 论文与文档措辞：不得出现「结构光等价」类表述。

**落地动作**：
1. `decision_defaults.json:structured_light` 固定 `v1_excluded=true`、`excluded_modalities=[structured_light, laser_scan]`。
2. 保留钩子（`hook_retained`：`marker=synthetic_only`、`upper_bound_only=true`）与 4 条禁止用途。
3. 未来引入须走 `t094-P2` 的 Gate 批准路径并**重开采集契约**。

**未落地前的临时口径**：任何合成深度产物在钩子落地前都必须显式标 `synthetic_only` 且不得进入部署式输入；
无该通道时本裁决**零代码改动**。

**校验**：`structured_light.claim_free` —— `synlab/**` **179/179** 模块无正向主张（本校验器自身已排除，避免自指）→ `PASS`。

---

## D6 镜头 / 畸变 / 景深 / 色温（文档未明确）

**裁决**：按**假设**落地并标注。

- 由 SC3336B 的 **84° FOV** 与传感器尺寸**反推焦距**（**记录推导**）；
- 畸变用 **Brown–Conrady 2 阶径向 + 切向（OpenCV 5 参数）**；
- 景深由文档**工作距离 + 2.0 px 弥散圆 mark-out** 计算；
- 色温 **5500 K ± 500 / CRI ≥ 90**；
- 全部标 `assumption` + **「Gate B 实测后重标定」**。

**焦距推导（记录在案）**：`f = (W_sensor/2) / tan(FOV_h/2)`。
`1/2.8"` 光学格式对角 `16/2.8 = 5.7143 mm`（`p1223` 只给 2304×1296 / 手动对焦 / 1/2.8" / MIPI），
配文档自身的画幅 `2304:1296 = 16:9` → `W_sensor = 5.7143 × 16/√337 = 4.9804 mm`；
`f = 2.4902 / tan(42°) = **2.77 mm**`。
交叉核对：`t051` 的 50 mm 距离 → 理想水平覆盖 `2×50×tan(42°) = 90.04 mm`（文档表 **90.0**），说明文档用的就是同一针孔关系（`p0518`）。
该推导与 `capture_contract.json:camera.lens.fallback_mainstream` 的 **3.6 mm**（M12 市面定焦默认值）**不一致**；本记录只**记录**推导，**不改写**既有契约。

**景深（不发明数字）**：mark-out 判据 `c = 2.0 px × mm_per_px(d)`，`mm_per_px` 取文档 `t051`：
`d=50 → c=0.078 mm`、`100 → 0.156`、`150 → 0.234`、`200 → 0.312`、`250 → 0.390`。
`DOF ≈ 2·N·c(d)·d²/f²`（远小于超焦距时），`d` 接近/超过超焦距 `H = f²/(N·c)+f` 时按 `1/(1−(d/H)²)` 修正。
**缺口**：文档未给任何**光圈 f 值 N**，故景深数值**无法闭合** → `value: null`，标 `unspecified_until_aperture_known`。

**出处指针**：`p0504`（SC3336 B / 84° / 2304×1296 / 手动对焦）、`p0518`（理想针孔公式）、`t051`（分辨率表）、
`p0511`（10/15/20/25 cm + 5–10 cm）、`p0535`（同色温白光 / CRI≥90 候选）、`p1159`（景深定性规则）、`t096`（近摄是否单独模型）、
`docs/a12/v144_project_core.md` §9 U3/U4/U5/U6；`rig_contract.md` §9.1–§9.4 / §12 #8–#11。

**影响面**：
- `resolution_profile` 的 `px_per_mm` / `r_eff_mm` / 景深覆盖 / 有效 ROI（覆盖矩阵 #3、#4 行）。
- `K` 与 `dist` 的可信度：`calibrated=false` / `STRESS_UNCALIBRATED` 下所有毫米级主张。
- 合成侧相机档：`configs/a12/camera_profiles.json` 现有 3 档（`f_number: 8.0`、`depth_of_field_mm` 区间、
  `fov_mm` 320×240 / 250×188 / 180×135，隐含全水平 FOV ≈ 41.7°/…）与文档 **84°** 不同源，且 `calibrated=false`。
- 近摄标定分档（`p1155`：近摄 focus breathing 时 Global 与 Fracture 近摄视为两套独立工况）。

**落地动作**：
1. `decision_defaults.json:assumed_optics` 五项全部 `assumption: true` 且带 `relabel_after`。
2. `configs/a12/camera_profiles.json` + `synlab/cameras/profiles.py` 按 D6 的 f / 畸变 / c(2.0 px) / 色温重标，
   或**显式**标为 assumption 值。
3. Gate B 实测后逐项替换，替换时重开本记录条目。

**未落地前的临时口径**：本节所有数值**不得**作为文档要求引用（只作设计输入）；
景深在补齐光圈前不得给数值；`f≈2.77 mm` 与 3.6 mm 兜底值**并存**，引用时必须写明取自哪一支。

**校验**：无独立检查项（声明完整性由 `defaults.present` + `tests/a12/qc/test_decision_checks.py` 的 D6 用例覆盖）。

---

## D7 单件采集时间（文档无数值）

**裁决**：**不发明**；按文档的 `cost_log` 分列 **人时 / 机器时 / 墙钟**，由**真实会话测量**填入。

**出处指针**：`t044`（`cost_log.csv`：人时、机器时和墙钟**分开**）、`p0881`/`p0580`/`p0680`/`p0661`（要求测「每片采集/计算时间」「动作时间」「耗时」「P95 时延」但**无门**）、
`p1148`（十分钟现场流程**不承担**每片数百帧重建）；`docs/a12/v144_project_core.md` §4.10 / §9 U7；`rig_contract.md` §9.5 / §12 #12。

**影响面**：
- `cost_log.csv`（11 类账本第 11 类，覆盖矩阵 #19 行「缺失」）与 `transitions.jsonl` 的 `duration_ms`。
- 过程指标「工时 −30%」的可测性（D3）。
- 现场流程彩排目标（`t005`：20 次至少 19 次完成）与十分钟约束的可行性。

**落地动作**：
1. `decision_defaults.json:metric_contract.cost_accounting` 固定三列 `human_time` / `machine_time` / `wall_clock`，
   `per_fragment_capture_time_s: null`（`unspecified_measure_from_real_session`）。
2. 账本导出器补齐 `cost_log.csv`（现仓 `synlab/storage/export.py` 中 `cost_log` 命中 **0**）。
3. 真实会话产生的时间写回本记录与 `decision_defaults.json`。

**未落地前的临时口径**：不得先写目标值再当成绩；引用 `capture_contract.json` 的 8–15 min / 30–60 min 兜底估值时
**必须**标注「兜底估值，非文档要求、非实测」。

**校验**：无独立检查项（现状：`cost_log` 产物 **0**，见附录 B-7）。

---

## D8 8 项质量向量 vs 14 维退化向量

**裁决**：**两个不同空间**，禁止等同；要求映射表带方向（`estimated_from` / `drives`），未映射项记 `unmapped`。

- 观测侧 **8 项**（`p0236`）：`blur`、`exposure`、`coverage`、`occlusion`、`reconstruction_confidence`、`point_density`、`normal_stability`、`curvature_stability`
  ——「这份证据有多可用」。
- 生成侧 **14 维 `D`**（`p0365`）：`fracture_smoothing`、`edge_rounding`、`fracture_missing`、`texture_loss`、`blur`、`glare`、`exposure`、`view_coverage`、`point_dropout`、`mesh_holes`、`depth_noise`、`normal_noise`、`curvature_noise`、`calibration_error`
  ——「注入了什么损失」。
- 映射表：观测侧用 `estimated_from`，生成侧用 `drives`，`partial` 标部分覆盖，无对应者 `status: unmapped`。

**出处指针**：`p0236`（8 项）、`t104`（每视图/每区域的命名 `float32` 向量，每项附 `valid` 与来源 `OBS_EST`/`GT_ORACLE`）、
`p0365`（14 维 `D`）、`docs/a12/v144_project_core.md` §5.5 E6 / §10.3 第 9 项；`rig_contract.md` §7.2 / §12 #15。

**影响面**：
- 质量头（`D16`：可观察质量输入 + 独立 oracle 诊断、字段权限分离）与 CTM 的 write/retain/correct 门控（覆盖矩阵 #12 行「缺失」）。
- 退化轴的诊断口径：31 轴（`t109`）→ 14 维 `D`（`p0365`）→ 8 项质量（`p0236`）三级之间的可追溯性。
- 权限：`p0236` 明确**质量头不得借 R2 标签把「邻接」偷换成「清晰」**——映射表不得暗示这种等价。

**未映射项（实测 3 项）**：观测侧 `occlusion`（14 维里没有遮挡轴）；生成侧 `fracture_smoothing`、`edge_rounding`。

**落地动作**：
1. `decision_defaults.json:quality_mapping` 冻结两空间 + 22 条带方向映射 + `forbidden_equivalence`。
2. `synlab/observe/quality.py` 按 8 项重命名并补齐 4 个缺项（`occlusion` / `reconstruction_confidence` / `normal_stability` / `curvature_stability`）。
3. 14 维 `D` 的写出落点：`synlab/degrade/api.py` 的 recipe 测量输出（现仓 `depth_noise`/`curvature_noise` **0** 命中）。
4. 映射表只用于**诊断**（退化轴 → 质量分量的预期影响），**不合并**两套 schema。

**未落地前的临时口径**：现有 `quality` 键组（`blur_laplacian_p95` / `overexposed_fraction` / `point_valid_fraction` / `hole_ratio_max` / `view_coverage_mean` …）
一律视为**未对齐**，引用时必须给原名并标「非冻结 8 项名」；`partial` 关系不得当等价关系使用。

**校验**：
- `quality.mapping_direction` —— **22/22** 组件带方向、`unmapped` 声明 **3**、`forbidden_equivalence=true` → `PASS`。
- `quality.store_key_alignment` —— `data/a12`：8 项冻结名命中 **0/8**（观测到 18 个别名键）→ `FAIL`；
  `data/a12_demo/store` 无质量向量 → `MISSING`。

---

## D9 `PairOutput` schema 与 R1 误排分母

**裁决**：

- **分母** := **实际给出的候选位总数**（`Σ` 每 query 返回候选数）；不足 Top-K 的**空位不计入**。
- **`mate-absent` query 按文档退出 Hit / CovRecall 分母**（另有误导率分母：无邻片查询被接受推荐数 ÷ 无邻片查询总数）。
- **R1 误排** := 被判为可接受（**进 top-K 接受集**）的 **R1 对**占比 = `|R1 ∩ 接受集| / |接受集|`。
- 另报「R1 排在第一名或首名 R2 之前」的查询比例（不作主指标）；UNKNOWN 位单独统计且**不强当 R1**。

**出处指针**：`p0330`（A9.1：R1 误排 = Top10 中 R1 数量 ÷ **有效候选位数量**，定义写入 `metrics_contract`）、
`p0108`（全库 `N_G` 分母）、`p0329`（误荐率与接受后风险两个分母**不能混用**）、`p0106`（§2.2 第 5 条）、
`p0167`（A4.8 `PairOutput`「**至少包括**」8 项）；`rig_contract.md` §12 #5 / #6。

**`PairOutput` 字段（文档「至少包括」8 项）**：`candidate_id`、`rank_score`、`score_type`、`support_regions`、`conflict_regions`、
`observability`、`model_version`、`evidence_revision`。`score_type` 候选枚举 `{ranking_score, calibrated_prob}`（**未冻结**）。
`support_regions`/`conflict_regions` 须与 `t053` 灯态、`t042` 区域 mask 的 ID 空间对齐。

**影响面**：
- 无邻片误导率（主指标之一，D3）与接受后风险两个分母的口径分离。
- 接受集定义（谁进 top-K 接受集）直接决定 R1 误排与接受覆盖率（≥80%）两个主指标。
- `PairOutput` 是评测器与部署侧的交换 schema，8 项字段的类型/枚举未定会阻塞跨模块消费。

**落地动作**：
1. `decision_defaults.json:misdirection_denominator` 冻结分母、`mate-absent` 规则、R1 定义与两个分母不可混用条款。
2. 评测侧实现 R1 误排（接受集占比）并同时在产物里给出「实际给出的候选位总数」作为分母。
3. `PairOutput` 的 dtype / 枚举 / regions ID 空间对齐**未裁决** → 记 `unmapped`（→ D12.5）。

**未落地前的临时口径**：R1 误排必须**成对**报出 `R1@10 / |valid slots|` 与 `R1-first-query ratio` 两个数，
并显式声明空位是否计入；`PairOutput` 消费方必须对 8 字段做显式类型断言，不得假定。

**校验**：无独立检查项（声明由 `defaults.present` 覆盖；现状：`synlab/diagnostics/metrics.py` 有 `absent_false_accept`/`risk`，但**无** R1-接受集占比，见附录 B-9）。

---

## D10 `loss_mask` 冗余

**裁决**：

- `loss_mask` 是**唯一**监督门；
- `valid` 降为**派生别名**（写明兼容用途：仅为旧消费者兼容读法保留，**不得**被任何写入方独立定义或独立赋值）；
- `eligible_as_negative` **必须**由 `kind ∈ {R1, R0} ∧ loss_mask` 计算，**不得存在第二份「真值口径」**。

**出处指针**：`t042`（关系证据）、`t104`（每项附 `valid` 及来源）、
`synlab/storage/export.py:1119-1121`（`eligible_as_negative` 派生点）、`:581`（合法负样本口径）、`:1792`（`valid and loss_mask` 监督口径）、
`docs/a12/modality_census.md` §6.4/§7.2；`rig_contract.md` §12 #18。

**影响面**：
- 训练监督的**唯一口径**：`rank` 任务的合法负样本、`loss_mask` 与 `kind` 的耦合。
- **联动约束（实测）**：现有口径下 `loss_mask ≡ valid ≡ (kind == "R2")`（150/150），因此
  `eligible_as_negative` **结构恒为 0**，合法负样本供给为 0。这**不是 D10 违规**，而是 D10 的**联动后果**：
  要让 legal negative 非零，必须改变 `loss_mask` 语义或引入 `TINY_CONTACT`/`UNKNOWN` 位。
- 与 `rig_contract.md` §11.1 第 2 条（合成专有项白名单）无冲突。

**落地动作**：
1. `decision_defaults.json:loss_mask_authority` 冻结唯一门 + 派生别名 + 派生公式 + 「禁止第二份真值口径」条款。
2. 代码侧**已合规**（`export.py:1119-1121` 现为 `kind in NEGATIVE_KINDS and row["valid"] and row["loss_mask"]`）。
3. `valid` 的所有独立赋值点需改为 `loss_mask` 的别名（含 `:1792` 的监督读取处）。

**未落地前的临时口径**：任何下游**只**读 `loss_mask`；读到 `valid` 时必须视其为 `loss_mask` 的别名而不重新定义；
`visible` 层缺列**视为合规现状**（→ D12.3）。

**校验**：`relations.loss_mask_authority` —— 导出侧关系行 **156/156** 满足单门规则（`eligible` 由 `kind ∧ loss_mask` 派生、`valid == loss_mask`）→ `PASS`。
附带报告项 `relations.negative_supply` —— 负侧行 **117**，合法负样本 **0** → `FAIL`（report-only，联动约束）。

---

## D11 出土上下文字段规格（文档无字段级规格）

**裁决**：按**已落地实现**（`simulated=true` + **出土区 / 网格 / 层位 / 层深 / 袋号 / 坑位 / 批次 / 共存物 / 尺度参考 / 会话**）
**冻结为 v1 字段集**，并要求 `context_id` / `batch_id` / `bag_id` **可查询**。

**v1 字段集（24 项，来源 = 已落地实现，不是文档要求）**：
`simulated`、`schema`、`pack_id`、`context_id`*、`batch_id`*、`batch_index`、`batch_size`、`batch_rule`、
`bag_id`*、`pit_id`、`site_id`、`institution_id`、`excavation_area_id`、`grid_ref`、`unit_code`、
`stratum_id`、`stratum_depth_mm`（单位：mm below the simulated site datum）、
`session_id`、`operator_id`、`captured_at`、`site_notes`、`scale_reference`、`coexistent_counts`、`coexistence_scope`
（`*` = 三个查询键）。
**deploy / research 分层**：`deploy/context/packs.json`（pack 文档 + 计数式共存物）vs `research/context_membership.json`（真实 fragment id 列表）。
**禁止字段**（13 项，写入方逐层拒绝）：`lineage_id`、`mother_id`、`fragment_id`、`event_id`、`split`、`seed`、`seed_ref`、
`historical_R2`、`mate_present`、`relation`、`relations`、`interface_id`、`kind`。

**出处指针**：`t088`（附录 C4 自建数据分层最后一行：「**模拟**出土区、层位、袋号/坑位等可控元数据」）、
`t101(D23)`（受限的模拟出土上下文：有缺失冲突和噪声，**不能等价母体 ID**）、`p1146`（坑位/层位只有真实可信字段时才使用）、
`p0412`（模型输入不包含母体 ID、袋号）；已落地实现：`synlab/pipeline.py:1197-1246`（`ContextPlan.as_dict`）、
`synlab/storage/export.py:1263-1330`（pack 写出与字段单位）；`rig_contract.md` §12 #2。

**影响面**：
- 上下文分支能否训练/评测（覆盖矩阵 #27 行）；`Context Encoder` 的数据来源（`t092`：几乎完全依赖私有数据）。
- 权限边界：上下文**不得**等价母体 ID，且不得进入部署式输入的身份字段。
- `X03` 轴（上下文缺失/错误，字段级扰动 **0–50%**）的落点。

**落地动作**：
1. `decision_defaults.json:context_v1_fields` 冻结 v1 字段集 + 查询键 + 禁止字段 + deploy/research 分层。
2. 已落地的写入方保持；主库需产出 `context_pack`（现 `data/a12` 与 `data/a12_demo/store` **0** 件，`data/a12_diversity/store` **2** 件）。
3. 字段类型 / 单位 / 枚举 / **缺失率上限**未裁决 → 记 `unmapped`（→ D12.6）。

**未落地前的临时口径**：上下文字段一律带 `simulated=true`；缺失/冲突率按 `X03` 的 `0–50%` 记录**实际取值**而**不设门**；
引用上下文时不得与 `object_id`/`bag_id` 之外的母体身份字段等价。

**校验**：`context.v1_fields_queryable` —— 实现侧 **24/24** 字段 + **3/3** 查询键；
`data/a12_diversity/store`：context pack **2** 件、三键齐备 **2** → `PASS`；
`data/a12` / `data/a12_demo/store`：**0** 件 pack → `MISSING`（实现已落地但该库无可查询对象）。

---

## D12 其余 7 项

**裁决原则（Lead 原文三条总原则）**：
(i) **不发明**——文档没有的数值一律改为「可复算定义」或「标 `assumption` + 重标定条件」；
(ii) **不伪造**——拿不到的模态（§8 九类）不得声称拥有，合成独有项标 `synthetic_only`；
(iii) **可程序化对照**——凡涉及「合成 ≥ 扫描台」的判定，必须给出**语义 + 单位 + 坐标系 + 权限**四项同义判据。

**条目范围**：§12 唯一未被 D1–D11 点名的整行 **#16**（D12.1），加上 D1–D11 未闭合的 **6 个残余子问题**（D12.2–D12.7）。

| # | 项 | 出处 | 应用原则 | 结论 | 未落地前的临时口径 |
|---|---|---|---|---|---|
| **D12.1** | **#16 仿真首版物理尺寸 vs 真实样片尺寸门限** | `p1353`（仿真首版候选「最大尺寸 80–300 mm、正常壁厚 2–10 mm」，且明确「参数属于仿真覆盖预算，真实采集后以尺寸分布校准，**不自动称为出土文物分布**」）vs `t042`/`p0511`（采集对象尺寸范围**未给**） | (i) | 真实样片的尺寸/壁厚门限文档**没有** → **不发明门限**；仿真尺寸**只能作覆盖预算** | 仿真尺寸引用时必须标「仿真覆盖预算，未按真实样片校准」；不得当目标分布；不得据此写跨域尺寸主张 |
| **D12.2** | **#17b `physical_component` 的 `F_mm` 局部帧是否强制回挂世界帧** | 普查 §1.1/§3.4（实测 `physical_component` 55 件全在 `F_mm` 构件局部帧，**不是**世界帧）；`t093`/`t096`/`t101(D13)` 要求 Global↔Local 融合残差与变换版本 | (i)(iii) | D4 只裁决了**断面的权威定义**，未裁决是否强制回挂 → **记 `unmapped`** | 任何跨构件的毫米级比较**必须显式声明帧**（`F_mm`）并给出该构件的 4×4 变换；不得默认已在世界帧 |
| **D12.3** | **#18b `visible` 层是否补齐 `loss_mask`/`valid` 列** | 普查 §6.4/§7.2（`visible.parquet` **根本没有**这三列）；D10 只冻结唯一门与派生别名 | (i) | 文档未要求 `visible` 层承载监督门 → **不新增字段**，现状**视为合规** | 任何消费者**不得**从 `visible` 层推断监督资格，必须回到 `relations` 层读 `loss_mask` |
| **D12.4** | **#1b `pose_id` 的落位** | `p0574`（rig_service 映射集含 `pose_id`）vs Lead 的 D1 字段清单（14 项**不含**它） | (i) | 既不加入也不剔除 → **记 `unmapped`** | 写入方若产生 `pose_id`，必须**同时**保留 `u_profile_id`/`light_mode`/`intrinsics_profile_id`，并标 `pose_id` 为 p0574-only 扩展 |
| **D12.5** | **#5b `PairOutput` 8 字段的 dtype / `score_type` 枚举 / regions ID 空间对齐** | `p0167`（A4.8「至少包括」，**未给类型与枚举**） | (i) | 三类都**未裁决** → **记 `unmapped`** | 消费方必须显式声明 dtype 与枚举（候选 `{ranking_score, calibrated_prob}` 标「未冻结」）；两个 regions 字段必须显式声明所用 ID 空间（`t053` 灯态 / `t042` 区域 mask）与其版本 |
| **D12.6** | **#2b 出土上下文的字段类型 / 单位 / 枚举 / 缺失率上限** | `t088`（只给字段名，未给类型、单位、枚举、缺失率上限）；`t109` 的 `X03` 轴给字段级扰动 **0–50%** | (i)(ii) | 规格**未裁决** → **记 `unmapped`** | 一律标 `simulated=true`；缺失/冲突率按 `X03` 记录**实际取值**、**不设门**；不得把模拟上下文的缺失率当真实站点分布 |
| **D12.7** | **#14b SY-Q5（证据移除消融）在映射表中的归类** | `t110`/`p1511`（SY-Q5 = 证据移除的**结构性消融**，有多个子配置，**不是更差工况**）；D3 的单调映射未覆盖它 | (i)(ii) | **记 `unmapped`**，按消融**单列** | 不得并入 Q1–Q3 的任何等价声明；不得与 SY-Q0–SY-Q4 一起做单调排序；SY-Q5 产物须标 `ablation` 语义 |

**影响面**：D12.1 → 合成规模/尺寸预算与论文的跨域表述；D12.2 → Global↔Local 融合与所有毫米级主张；D12.3 → 标签层权限；
D12.4 → rig_service 接口；D12.5 → 评测器/部署交换 schema；D12.6 → 上下文分支与 `X03` 轴；D12.7 → 质量阶梯的消融解释。

**落地动作**：七条残余分别以 `unresolved[]` 落在 `decision_defaults.json` 的
`assumed_optics`（D12.1）、`surface_authority`（D12.2）、`loss_mask_authority`（D12.3）、`action_proposal`（D12.4）、
`misdirection_denominator.pair_output`（D12.5）、`context_v1_fields`（D12.6）、`metric_contract.sy_q_to_q_mapping`（D12.7），
每条带 `status: unmapped`、`temporary_rule`、`owner_decision`。

**未落地前的临时口径**：逐条见上表最右列——共同点是**不得静默**：未裁决项必须在产物里显式标 `unmapped` 并附临时口径。

**校验**：`tests/a12/qc/test_decision_checks.py::test_d12_residuals_are_named_by_owner_across_the_sections`
与 `::test_d12_every_residual_carries_a_temporary_rule` —— 要求 `D12.1`–`D12.7` **全部**出现且每条都有 `temporary_rule`。

---

## 附录 A：只读校验结果（真实分母 / 命中，未放宽）

命令（重定向，退出码另存）：

```powershell
& .venv\Scripts\python.exe -m pytest tests/a12/qc -q > data\a12\reports\pytest_qc_decision_checks.txt 2>&1
# 退出码 0；101 passed
& .venv\Scripts\python.exe <runner> > data\a12\reports\decision_checks_run.txt 2>&1
```

检查表（13 项；`数据/a12` = 主库，`a12_demo` = 带 GLB 权威块的库，`a12_diversity` = 带 context pack 的库）：

| check id | 裁决 | 主库命中/分母 | `a12_demo` | `a12_diversity` | 状态说明 |
|---|---|---|---|---|---|
| `defaults.present` | D1–D12 | **10/10** | 10/10 | 10/10 | `PASS` |
| `defaults.action_proposal_union` | D1 | **14/15**（声明 14/14，代码生产者 **0**） | 同 | 同 | `FAIL`（代码侧未落地） |
| `metrics.primary_metric_freeze` | D3 | **8/8** | 同 | 同 | `PASS` |
| `metrics.m_and_delta_recorded` | D2 | **0/9**（`M` 7/9、`delta` **0/9**） | 同 | 同 | `FAIL` |
| `surface.authority_conflicts` | D4 | **0/0** → `NOT_APPLICABLE` | **16282/18410**（冲突 **2128 / 18410 = 11.56%**，6 个 GLB） | `NOT_APPLICABLE` | `FAIL`（demo 库） |
| `relations.loss_mask_authority` | D10 | **156/156** | 156/156 | 156/156 | `PASS` |
| `relations.negative_supply` | D10 | **0/117** | 0/117 | 0/117 | `FAIL`（report-only，联动约束） |
| `relations.gate_columns_visible` | D12.3 | **0/3** | 0/3 | 0/3 | `MISSING`（report-only，残余未闭合） |
| `export.synthetic_only_marking` | D5 | **0/6** | 0/6 | 0/6 | `FAIL`（`synthetic_only` 标记 0 命中） |
| `quality.mapping_direction` | D8 | **22/22**（`unmapped` 3） | 同 | 同 | `PASS` |
| `quality.store_key_alignment` | D8 | **0/8** | 无质量向量 → `MISSING` | **0/8** | `FAIL` |
| `context.v1_fields_queryable` | D11 | **27/27**，pack **0** → `MISSING` | `MISSING` | **27/27**，pack **2/2 三键齐备** → `PASS` | 见 D11 |
| `structured_light.claim_free` | D5 | **179/179** | 同 | 同 | `PASS` |

**结论**：`verdict = partial`（三个库一致）。**已合规**：D3 主指标冻结、D8 映射方向、D10 单门规则、D5 排除与无越权主张、D11 实现侧字段集。
**未落地**：D1（无生产者）、D2（`δ` 全缺）、D4（冲突未修到 0）、D5（`synthetic_only` 标记缺失）、D8（质量名未对齐 / 14 维 `D` 无产物）、D11（主库无 pack）。

报告文件：`data/a12/reports/decision_checks_data__a12.json`、`decision_checks_data__a12_demo__store.json`、
`decision_checks_data__a12_diversity__store.json`、`decision_checks_run.txt`、`pytest_qc_decision_checks.txt`。

---

## 附录 B：需要代码侧改动才能生效的裁决（精确文件与位置；**本记录不改这些文件**）

| # | 裁决 | 文件 | 位置 | 需要的改动 |
|---|---|---|---|---|
| **B-1** | D1 | `synlab/schemas/spec.py` | 类族 `StrictModel`（`:20` 起；`candidate_pool_size` 见 `:268`） | 新增提案类型与 14 字段 schema（3 档 + 每字段 `source`/`optional_extension`）；现仓 `synlab/**` 中 `ActionProposal` 命中 **0** |
| **B-2** | D2 | `synlab/diagnostics/metrics.py` | `:247`（`gallery_size`）、`:266-267`（`pool_cov`/`any_at_m`）、`:377-382`（summary） | 结果行写出 `M`（本次池规模）与 `delta`（簇 bootstrap 95% CI 半宽） |
| | D2 | `synlab/diagnostics/runner.py` | `:472-474`（summary 键白名单） | 白名单加入 `M`/`delta` 并随结果落盘 |
| | D2 | `synlab/diagnostics/stats.py` | bootstrap 报告（`ci_low`/`ci_high`/`mean_delta`） | 显式输出 `delta := (ci_high − ci_low)/2` 与冻结元数据 |
| | D2 | `synlab/episodes/baselines.py`、`synlab/episodes/env.py` | `baselines.py:159`（`stop_when_no_gain`）、`env.py:52`（`DEFAULT_BUDGET`，`max_actions: 6`） | 实现 `K=3` 下界 + 「连续两轮变化 < δ」停止规则；δ 未冻结时只允许 4 tick 上限 |
| **B-3** | D3 | `synlab/degrade/registry.py`、`synlab/degrade/axes.py` | 全文件（`sy_q` 命中 **0**） | 新增 `sy_q_profile`（Q0–Q5 具名组合） |
| | D3 | `configs/a12/`（新增 `sy_q_mapping.json`） | — | SY-Q ↔ Q1–Q3 单调映射表（覆盖矩阵 #14 的建议落点） |
| | D3 | `configs/a12/qa_protocol_v1.json`、`synlab/qc/acceptance.py` | `qa_protocol_v1.json` 仅 A0x 工程阈值；`acceptance.py` 无 `any@50`/`Hit@10` 宏合同 | 冻结 7 项主指标 + 过程指标单列 |
| **B-4** | D4 | `tools/build_demo_assets.py` | `:584`（并集 `(origin_arr == ORIGIN_INTERFACE) \| (interface_arr >= 0)`）、`:589`（冲突计数）、`:620-621`（`new_surface_definition` 文案） | 权威谓词改为 `interface_id >= 0`，`origin_kind` 降为派生标签；冲突计数保留并逐 run 上报 |
| | D4 | `synlab/physical/api.py` | `:276`/`:341`（`origin_out`/类别统计）、`:751`（无 `origin` 通道 → 全 `ORIGIN_AMBIGUOUS`）、`:819`（污染体全 ambiguous）、`:821`/`:830`（`with_face_attrs`） | 断面标签的派生基准改为 `interface_id >= 0`；`origin_kind` 仅作派生标签 |
| | D4 | `synlab/observe/routes.py` | `:383-384`（`face_origin_kind` 回退读 `origin_kind`）、`:472-478`（`ORIGIN_TO_TAG` 映射） | 断面 `surface_tag` 输出以 `interface_id >= 0` 为准 |
| **B-5** | D5 | — | — | **零改动**；钩子通道不存在；若引入则落 `synlab/storage/export.py` 的 index 写出并标 `synthetic_only` |
| **B-6** | D6 | `configs/a12/camera_profiles.json` | 3 档 `f_number` / `depth_of_field_mm` / `fov_mm`（现隐含全水平 FOV ≈41.7°，与文档 84° 不同源）、`calibrated=false`、`STRESS_UNCALIBRATED` | 按 D6 的 `f≈2.77 mm` / Brown–Conrady 5 参 / `c=2.0 px` mark-out / `5500 K ± 500, CRI ≥ 90` 重标或显式标 assumption |
| | D6 | `synlab/cameras/profiles.py` | `transform_profile_u`（`focal_length_mm` 与焦点组漂移逻辑） | 内参与畸变档按 D6 重标；近摄分档待裁决 |
| **B-7** | D7 | `synlab/storage/export.py` | 全文件 `cost_log` 命中 **0**；11 类账本导出器尚未落地 | 新增 `cost_log.csv` 导出（人时/机器时/墙钟三列） |
| | D7 | `synlab/roles.py` | `:63`（有 `episode_trace`） | 如需 `cost_log` 角色须注册 |
| **B-8** | D8 | `synlab/observe/quality.py` | `:132`/`:138`/`:152`/`:201`/`:204`（实测键组）、`:244-249`（`groups` = blur/exposure/density/holes） | 按 8 项冻结名重命名并补 `occlusion` / `reconstruction_confidence` / `normal_stability` / `curvature_stability`，每键带 `unit`/`valid`/`source` |
| | D8 | `synlab/degrade/api.py`（+ `registry.py`） | 全文件 `depth_noise`/`curvature_noise` 命中 **0** | 落 14 维 `D`（含物理/数值单位、随机种子、操作顺序） |
| **B-9** | D9 | `synlab/diagnostics/metrics.py` | 风险与接受集字段已有（`absent_false_accept`/`risk`/`accepted`） | 新增 R1 误排 = `\|R1 ∩ 接受集\| / \|接受集\|`，分母改为「实际给出的候选位总数」 |
| **B-10** | D10 | `synlab/storage/export.py` | `:1119-1121`（派生，**已合规**）、`:1792`（监督读取）、`:1910`（`TRUTH_BEARING_FIELDS`） | 仅需把 `valid` 的其它独立赋值点改为 `loss_mask` 别名；D12.3 若裁决补列则改 visible 层写出 |
| **B-11** | D11 | `synlab/pipeline.py` | `:1197-1246`（`ContextPlan`）、`:1820`（step 8b 写 pack）、`:1347-1367`（身份字段） | 实现**已落地**；需让主库/演示库的批 layout 产出 `context_pack`（`data/a12_diversity/store` 已有 2 件） |
| **B-12** | D12.1 | `tools/build_demo_assets.py`、`data/a12/reports/` 相关尺寸报表 | — | 裁决前不改；引用处必须标「仿真覆盖预算」 |
| | D12.2 | `synlab/physical/api.py`、`synlab/storage/export.py` | `frame` 只有 `F_mm`/`W_mm` 等，无 4×4 `transform`/`fusion_residual` | 裁决前不改；跨构件比较必须显式声明帧 |
| | D12.4 | `synlab/schemas/spec.py`（随 B-1） | — | `pose_id` 落位待裁决 |
| | D12.5 | 评测/导出侧（`synlab/diagnostics/metrics.py`、`synlab/storage/export.py`） | — | `PairOutput` dtype/枚举/regions ID 空间待裁决 |
| | D12.6 | `synlab/pipeline.py`（`CONTEXT_VOCABULARY` / `plan_context`） | `:1126-1153`、`:1251-1307` | 缺失率门待裁决 |
| | D12.7 | `synlab/degrade/registry.py`（随 B-3） | — | SY-Q5 消融单列待裁决 |

---

## 附录 C：本记录不做什么

- **不重新裁决**：D1–D12 的裁决内容逐条来自 Lead；本记录只做形式化、传播与校验。
- **不发明数值**：`δ`、`M` 的最终值、景深、焦距（推导之外）、色温、单件时间、仿真尺寸门限、上下文缺失率上限均未给数值。
- **不改被禁区域**：`synlab/{fracture,observe,degrade,physical,mothers,patterns,truth,relations,training,storage,pipeline.py}/**`、
  其它 `configs/**`、`frontend/**`、`tools/**`、`data/a12/**`（除 `reports`）**一律未改**；
  附录 B 的改动点只是**定位**，留给后续实现。
- **不放宽校验**：`synlab/qc/decision_checks.py` 只读（SQLite `mode=ro`），缺失记 `MISSING`、分母为 0 记 `NOT_APPLICABLE`，
  阈值全部引用 `decision_defaults.json` 并在 `thresholds[]` 里带出处。
