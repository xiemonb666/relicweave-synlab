# RelicWeave V1.44 接续与验收矩阵（2026-10-03）

本文件记录 root 已复核的最新状态与下一步验收条件。较早实施日志、旧测试计数与历史 FAIL 均保留在原位置。PENDING 表示尚未关闭，不表示任务停止；各 replacement run 按其真实状态分别追踪。

A12 仍是受控合成数据、观测/退化、预训练与 A7 诊断入口。A12 不替换主流程 A3/A4 的真实邻接检索、证据拒绝、补采或 STOP。

## 已接受的局部范围

VF canonical STEP BRep 语义原型：26/26 faces 分类，38,486/38,486 三角形映射，UNKNOWN=0；handle paint mislabel 198→0、non-base handle albedo 23→0。新结果与 canonical3 的 vertices、faces、triangle→BRep lineage 逐位相同。whole/lower-root Blender EXR depth mismatch=0、最大差值=0.0 mm；16 tests PASS；四带/三带 generate 与 validate 各退出 0。602 个 trimmed-face 样本最大偏差 0.0196136578 mm，目标 0.10 mm。有限采样不证明全局 Hausdorff、全局最小壁厚或整器真实度。C0 折角、把手根部、全局壁厚、材质校准和历史样式仍未通过。

A12 adapter/camera 32 tests PASS，depth/noise 71 tests PASS，frozen parity 2 tests PASS。legacy appearance 套件仍为 29 PASS / 4 FAIL，原失败保留，见下表。jobs guard/scheduler/cancel 为 22 PASS；既有 jobs API 为 12 PASS / 1 conditional SKIP。PG 有 19 unit tests PASS、physics/time source SHA 20/20、5 个 headless I/O 文件变化、63 个 normalized source files 一致。wheel 解包到 non-editable install layout 后 CLI smoke PASS；wheel SHA256 为 0bdd3077aa79f69111d3df13a78dd2627b472e17f2db458683d4d2e15295e634。这些局部结果均不扩展为 pip install、clean-machine、remote CI、GPU 或完整物理链验收。

## 当前任务与验收矩阵

| ID / 工作项 | 当前状态 | 已有证据与边界 | 关闭验收 / 下一步 |
|---|---|---|---|
| VF-S1 canonical STEP BRep 语义 | 狭义原型 PASS | 26 faces、38,486 triangles、UNKNOWN=0；误标计数 198→0 与 23→0；网格/lineage 逐位相同；whole/lower-root depth parity 0 mismatch；16 tests PASS；四带/三带 CLI generate+validate exit 0；602 sampled trimmed-face max deviation 0.0196136578 mm ≤0.10 mm。 | 仅接受该原型的面语义、网格保持与深度 parity。C0 profile、把手根部过渡、全局壁厚、材料、历史样式及真实断裂仍 PENDING。有限样本不是全局 Hausdorff 证明。 |
| VF smooth-CAD 3D shell candidate | 候选 FAIL；替代表示 PENDING | candidate_default_wall4/smooth_cad_spike_report.json 报告 max sampled mesh deviation 0.1184320427 mm >0.10 mm，native volumetric halfsection 无效/为空。root 查看 whole 与内截面图后确认内 offset 底部回折并与 floor 相交。报告中的 192 个 sidewall normal rays 均有命中，sampled wall min/max 为 3.9721/4.0015 mm；这只是有限 wall-ray 样本，不是 whole geometry PASS。 | 不提升该 3D candidate。第二种 2D 表示仍在调查，需提交自身有效性、whole/joint 图与误差证据后再裁决。来源报告的 byte-exact 副本和 SHA 见 evidence index。 |
| VF volume representation follow-up | FAIL + PENDING rerun | root 报告 h8 版本有 1,313 cells、相对误差 2.034%，超过原 1% 精度门槛；h6 原始预算下为 SKIP。 | root 已将单次静态 cell cap 提高到 10,000，重跑原第二尺寸；不改 1% 精度门槛。拿到新结果前保持 PENDING。 |
| A12 adapter / camera | PASS，32 tests | forge adapter/camera 本地测试；证据日志和源 SHA 见 evidence index。 | 不据此声称生产外观、断裂或实机相机链路已闭合。 |
| A12 depth/noise 与 frozen parity | PASS，71 + 2 tests | targeted depth/noise 71 passed；独立 frozen contract parity 2 passed。 | 仅覆盖本地相机/深度噪声与 frozen contract 测试范围。 |
| A12 continuous painted preview | root 已接受窄范围 preview/oracle | root 实看 512/320 四带与 512 三带反事实图。独立 Float64 scalar Moller–Trumbore pixel-center ray oracle：depth max error ≤7.63e-6 mm，RGB max error 2.974e-8 linear；SS=1/2 与 non-zero distortion 均在新 40-PASS target 中通过。same geometry、depth、IDs、surface tags、visibility 与 uncertainty 精确 parity；preview 不含 truth fields。报告/图/日志见 evidence index。 | 接受的范围是连续绘制预览、独立 ray oracle 与几何输出 parity。默认与 frozen 小回归仍待补测后 root 再裁决；不代表真实 style/material、per-face field 补齐或 full deploy 安全。 |
| A12 continuous sampler 历史结果 | 初轮 FAIL 保留；旧 38-PASS 不接受 | 初轮 targeted log 为 3 FAIL / 27 PASS。随后一份 38 PASS 因 oracle 坐标错误被拒：独立 Moller oracle 在未平移的原始 K 上又加 half-pixel，未抵消 _scaled_frame 内已有的 +0.5，导致错误射线偏半像素；拒绝原因不是复用 renderer。 | 保留旧失败与被拒 38-PASS 记录。新 40-PASS 仅支持上行的窄目标；default/frozen 回归未完成前不关闭该工作项。 |
| A12 legacy appearance suite | FAIL 保留，29 PASS / 4 FAIL | 最终 legacy appearance 日志保留 4 个失败：lamp-state selection、default SNR、frozen fast path/albedo texture、gradient prediction。旧 per-face approximation 中窄红带仍为零三角形；新连续 shader preview 不改变这条记录。 | 修复后重跑原 suite 并保留原判据。不要与 private continuous sampler target 合并计数。 |
| Jobs control targeted suite | PASS，22 tests | guard/scheduler/cancellation targeted suite 22 passed。 | 只代表这些本地测试通过。 |
| Existing jobs API suite | PASS with one conditional skip | 12 passed / 1 conditional skip。 | 记录 skip 条件；在目标环境具备时补跑。DAG enqueue 非原子与旧 store event revision 另列 OPEN。 |
| PG core / native OSB branch | 局部接口与数值检查 PASS；物理解释 PENDING | 19 unit tests PASS；physics/time source SHA 20/20；5 headless I/O source files changed；63 normalized source files 一致。OSB branch 576 points、20,780 native pairs、5,236 broken pairs、endpoint components 432/144、endpoint mass 全保留。points.csv、bond_states.csv、components.csv 与 data_dictionary.json 均原样保存在 evidence bundle，可重算原始列。 | 仅限 uniform_box_bar_fixture 与 UNVALIDATED toy parameters。没有 VF volume、裂面重建、陶瓷标定、接触、历史 R2 或完整能量账本；GPU NOT_IMPLEMENTED。不得外推为 impact/ceramic/R2。 |
| PG wheel package smoke | 直接解包布局 PASS | wheel SHA256 为 0bdd3077aa79f69111d3df13a78dd2627b472e17f2db458683d4d2e15295e634；直接 unpack 到 non-editable install layout 后 CLI smoke 成功。 | 不表示 pip install、clean-machine install 或 remote CI 通过。 |
| Luna native double-body no-failure | PENDING；replacement run active | 范围为 bounded three-case native contact；目前没有 root 接受的最终结果。 | 提交三个 case 原始结果、状态、稳定性/步长与接触不变量证据，按任务书门限由 root 验收。 |
| Luna C2 shell candidate | 第二表示 PENDING | 当前 3D smooth-shell candidate 已 FAIL，不能把 C2 或 192 个 wall-ray PASS 当作 whole geometry PASS。 | 第二表示的 C2 连续性、validity、mesh deviation 与 whole/joint 视图须各自验收；production source 保持只读。 |
| A12 deploy boundary / strict v2 | Legacy 实包 INVALID_DEPLOY_TRUTH_LEAK；strict-v2 PENDING | 实际 deploy/queries.parquet 含 lineage、mother、fragment、historical_N_G 等 answer-bearing columns；deploy_index.json 以 raw lineage/mother-style IDs 为索引 key。export_manifest.json 的 features_carry_answer_fields=false 来自漏 alias 的 exact-name scan，不可用作无泄漏证明。具体源文件、SHA、受影响测试及其边界见 evidence index。 | luna_deploy_boundary 正在做版本化 strict scanner 与小测试。旧包在 strict-v2 修复/验证前保持 INVALID_DEPLOY_TRUTH_LEAK / PENDING；API allowlist PASS 只覆盖 allowlist，不证明真实导出或模型 vector 无 truth。此文档 owner 不修改 exporter/source。 |
| Realism / material calibration | PENDING / UNKNOWN | [现实效果验收依据](REALISM_ACCEPTANCE_20261003.md) 将数学几何、数值物理、来源/校准与实物形貌分层。视觉仅限展示。E/Gc 等候选原值保留，实际 calibration 为 UNKNOWN / UNVALIDATED。 | 按现实验收文件提供同批材料、可追溯来源、误差和匹配真实形貌后再更新；不把候选值改成测量事实。 |
| A12 DAG/store concurrency | OPEN | DAG enqueue 仍非原子；旧 store event revision 未解决。 | 需要原子性/回放兼容判据、失败注入或并发证据与兼容迁移结论。 |
| GPU path | NOT_IMPLEMENTED | 当前 PG native fixture 使用 CPU，没有 GPU 实现或验收证据。 | 另行实现，并比较同一小例 CPU/GPU 精度、稳定性、复现性和资源。 |
| VF → PG → ageing → capture/reconstruction full chain | PENDING | 局部 VF / PG / A12 检查不能证明完整物理断裂→遗存退化→低成本观测→reconstruction；材料参数未校准。 | 分阶段保留 versioned inputs、validity、lineage、真实参考与误差。主 A3/A4 workflow 继续由主仓负责。 |

## Evidence bundle 与复算

少量证据副本与 source/copy SHA 见 [evidence/20261003/index.md](evidence/20261003/index.md)。bundle 保存 raw PG 数值列、根审阅图、局部报告和日志；path-normalized copy 有自己的 copy SHA，不冒充原文件 SHA。旧 deploy truth-bearing 实包只记录路径/哈希/字段证据，不复制敏感行或索引值。大型 VF STEP/NPZ 不复制；source hashes 和复现命令见索引。

## 状态更新纪律

1. 更新时记录来源文件名、源路径、输入版本/哈希、测试命令和退出摘要。
2. 初始 FAIL、修复前结果及被拒证据保留并标记状态；新通过只更新对应范围，不删除失败历史。
3. PASS 必须带范围；PENDING、FAIL、NOT_IMPLEMENTED、NOT_RUN 分开记录。replacement run 尚在进行时标 PENDING，不把所有任务合并为 BLOCKED。
4. 不扩张材料、R2、GPU、实拍、deploy 安全或主 A3/A4 结论，除非各自门槛已由 root 复核。