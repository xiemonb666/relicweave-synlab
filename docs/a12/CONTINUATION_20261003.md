# RelicWeave V1.44 接续与验收矩阵（2026-10-03）

本文件给后续接手者使用，记录截至 2026-10-03 晚间的最新证据边界与待办。它只更新当前状态摘要；较早的实施日志、历史 `FAIL`、旧测试计数和旧数值仍留在原位置作审计记录。带 `PENDING` 的任务不是完成状态，也不表示工作已停止。

V1.44 的产品目标仍以总计划和用户裁决为准。A12 是受控合成数据、观测/退化、预训练和 A7 诊断入口；它不取代主 A3/A4 真实邻接检索、证据拒绝、补采和 STOP 流程。

| ID / 工作项 | 当前状态 | 已有证据和边界 | 关闭验收 / 下一步 |
|---|---|---|---|
| VF-S1 canonical STEP BRep 语义 | 狭义原型 `PASS` | 26/26 faces 分类，38,486/38,486 三角形映射，UNKNOWN=0；handle paint mislabel 198→0、non-base handle albedo 23→0；canonical3 与新包的 vertices、faces、triangle→BRep lineage 逐位相同。whole/lower-root Blender EXR depth mismatch=0、最大差=0.0 mm；16 tests PASS；四带/三带 generation 与 validation 各自退出 0。602 个 trimmed-face samples 最大偏差 0.0196136578 mm ≤ 0.10 mm。 | 接受范围仅为该 prototype 的面语义/网格保持/渲染深度 parity。C0 profile corner、abrupt handle-root、全局壁厚、材料参数、historical style 和真实断裂仍 `PENDING`。有限采样不等于全局 Hausdorff 证明。 |
| A12 adapter / camera | `PASS`，32 tests | 原日志为 forge adapter camera asset final；生产接线仍是适配器边界。 | 复用当前适配接口；不要据此声称生产外观、断裂或真实相机闭环。 |
| A12 depth/noise 与 frozen parity | `PASS`，71 + 2 tests | targeted depth/noise 为 71 passed；独立 frozen contract parity 为 2 passed。日志副本和源 SHA 见证据索引。 | 结论仅覆盖该相机/深度噪声和 frozen contract 测试范围。 |
| A12 legacy appearance suite | `FAIL` 保留，29 passed / 4 failed | 当前最终日志仍有 4 个失败：灯态选择、默认 SNR、冻结 fast path 与 albedo 纹理、梯度预测。四项失败继续作为未完成项；不得与另一条私有 sampler 任务混算。 | 修复后重跑原有 suite，并按原判据保留所有失败。连续 shader 的四带可见，不代表 per-face approximation 已补齐；窄红带在 per-face 字段中仍为零三角形。 |
| jobs control targeted suite | `PASS`，22 tests | Guard / scheduler / cancellation 的 targeted suite 为 22 passed。 | 只代表这些本地测试通过。 |
| existing jobs API suite | `PASS` with one conditional skip | 12 passed / 1 conditional skip。 | 记录 skip 条件并在目标环境具备时补跑。剩余的 DAG enqueue 非原子及旧 store event revision 必须分别形成修复与迁移证据。 |
| PG core and native OSB branch | 局部接口/数值检查 `PASS`；物理解释仍 `PENDING` | PG 有 19 unit tests PASS，physics/time source SHA 20/20，5 个 headless I/O source files changed，63 normalized source files一致。native OSB branch 输出 576 points、20,780 native pairs、5,236 broken pairs、endpoint components 432/144、总 endpoint mass 保留。原始 points、bond states、components 和 data dictionary 在 evidence/20261003/pg/osb_fracture_branch_001/output，可据原列复算。 | 这是 `uniform_box_bar_fixture` 与 uncalibrated toy parameters。没有 VF volume、裂纹面重建、陶瓷标定、接触、历史 R2 或完整能量账本；GPU 为 `NOT_IMPLEMENTED`。不得外推为冲击、陶瓷或 R2 结论。 |
| PG wheel package smoke | 局部解包布局 `PASS` | wheel SHA256 为 `0bdd3077aa79f69111d3df13a78dd2627b472e17f2db458683d4d2e15295e634`。将 wheel 直接解包到非 editable install layout 后运行 CLI smoke 成功；结果 JSON 在证据包内。 | 不表示 `pip install` 成功、干净机器安装成功或 remote CI 通过。独立 wheel/clean-machine/remote-CI 验收仍未完成。 |
| Luna native double-body no-failure | `PENDING`，replacement run active | 目标为 native contact 的 bounded three-case 检查；目前没有最终接受结果。 | 返回 3 个 case 的原始结果、状态、稳定性/步长和接触不变量证据；root 核对任务书门限后再标记。 |
| Luna C2 shell candidate | `PENDING`，production read-only | 目标是只读生产代码，产出 C2 shell 候选。 | 提交候选路径、C2 连续性测量、几何有效性/偏差数据和 whole/joint 视图；root 审核候选，不据候选报告生产代码已修改或已验收。 |
| Luna private continuous-paint sampler | `PENDING`，oracle correction and reruns active | 首轮结果为 3 FAIL / 27 PASS。后续 38 PASS 提交被 root 拒绝：half-pixel oracle 不独立，复用了被测 renderer。它不是有效验收。当前正在修独立 oracle，并重测 SS=1、SS=2 与 distance cases。 | 必须提供独立 half-pixel oracle、实际四带命中/材料坐标记录、truth-boundary 检查，以及 SS=1/2/distance 的完整新日志；root 复核后更新状态。 |
| A12 DAG/store concurrency | `OPEN` | DAG enqueue 仍非原子；旧 store event revision 尚未解决。 | 负责人提出原子性/重放兼容的判据，给出失败注入或并发证据及兼容迁移结论后再关闭。 |
| GPU path | `NOT_IMPLEMENTED` | 现有 PG native fixture 使用 CPU；GPU 没有可运行实现或验收证据。 | 单独实现并比较同一小例的 CPU/GPU 精度、稳定性、复现性和资源后才可变更状态。 |
| VF → PG → A12 full chain and real-world validation | `PENDING` | 现在的局部 VF / PG / A12 checks 不能证明完整物理断裂 → 遗存退化 → 低成本观测 → reconstruction 链；材料参数仍未标定。 | 后续逐阶段保留 versioned inputs、validity、lineage、真实参考及误差；主 A3/A4 evidence workflow 继续由主仓裁决。 |

## Evidence bundle and recalculation

本次保留的审阅包在 [evidence/20261003/index.md](evidence/20261003/index.md)。它有少量 path-normalized reports/logs、三个审阅用 PNG 和 PG branch 的四个原始输出文件；总计 2,518,028 bytes。原始 PG CSV/JSON 与源 SHA 完全一致；normalized JSON 与合并日志有自己的副本 SHA，不应误当成原文件字节相同。VF 大型 STEP/NPZ 未复制，只记录源摘要、规范生成命令和本地复算路径。

## 状态更新纪律

1. 把最新 owner run 的源路径、输入版本/哈希、测试命令和完整退出摘要补到 evidence index，再更新本表。
2. 初始 FAIL 与修复前结果保留并明确标为旧代，不得改写为 PASS；新通过结果只替代当前状态，不删除失败历史。
3. `PASS` 必须带范围；`PENDING`、`FAIL`、`NOT_IMPLEMENTED`、`NOT_RUN` 分开记录。replacement agent 正在工作时保持 `PENDING`，不要写成全部阻塞。
4. 不扩张材料、R2、GPU、实拍或主 A3/A4 结论，除非各自的验收数据已经出现并由 root 接受。
