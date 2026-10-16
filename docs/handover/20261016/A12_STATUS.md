# A12 / SynLab 状态与交接（2026-10-16）

**状态：开发暂停。** 本页是停更时的 A12 范围记录，整理可追溯证据、边界和待办；本轮只更新文档，没有运行求解器或测试。继续实现需要用户重新启动开发。

## 范围与总目标

`relicweave-synlab` 是 RelicWeave 三个工程部分之一，不代表整个项目，也不取代另外两个仓库：

| 仓库 | 职责 | 当前边界 |
|---|---|---|
| `vesselforge/` | 有来源的器物几何、CAD、语义面和几何资产包 | CAD/几何 QA 通过不等于已匹配真实日用或考古器物 |
| `pgfrag/` | 材料/事件求解和断裂结果试验，含 Peridynamics.jl 与独立 Akantu 研究路线 | 控制算例不等于新母器的物理破裂或材料校准 |
| `relicweave-synlab/`（本仓库） | A12 的合成数据、外观、观测、退化、关系、episode、训练、诊断和发布 | 不拥有 VesselForge CAD 或 PG-Frag 求解器内核 |

项目要求覆盖日常器与考古器，每一器族都要有可核对的真实形制参考、有意义的专属纹样/布局、公共与器专属参数、源感知材质和相应工艺约束；引入的外部资源也需逐项精修审阅。最终仍需真实器形与材料上的原生断裂证据。当前 A12 有程序化基线和少量 source-guided 样例，远未满足这一整体目标。

## 按交付物记录的进度

| 交付物 | 已有证据 | 状态与限制 |
|---|---|---|
| A12 合成与学习底座 | 既有母体 V01–V24、材料 M01–M12、PAT01–PAT16、断裂/真值/观测、31 轴退化、relations、episode、训练、诊断与发布模块及其各自测试/审计。可从 [`docs/a12/architecture.md`](../../a12/architecture.md)、[`docs/a12/runbook.md`](../../a12/runbook.md) 进入。 | 保留为 SynLab 广泛的软件基线。族注册和软件 QA 不证明真实器物覆盖、材料校准、真实断裂或训练资格。旧 [`docs/a12/status.md`](../../a12/status.md) 是较早的 A12 快照，不是本页 10 月 16 日新切片的验收替代品。 |
| 24 器型参数接口 | [`synlab/mothers/design_space.py`](../../../synlab/mothers/design_space.py) 包装 V01–V24 已有模型；对共同字段、器专属字段、请求/解析/实际值及同种子几何效应提供可查记录。已有 V01/V04/V06/V09 的默认与单字段例子，见 [`DESIGN_SPACE_20261015.md`](../../a12/DESIGN_SPACE_20261015.md)。 | **参数空间接口可用，不表示 24 个真实器型已经验收。** 当前 24 项仍为 `SYNTHETIC_CONTROL` / `PARAMETRIC_CANDIDATE`，没有 24 种来源测量或历史类型资格。审计还发现 V23 的若干继承字段为 no-op，及其他 `shape_parameters` 元数据不一致；须逐项裁决和修复。 |
| VesselForge 形状与参考生成器 | [`synlab/integrations/reference_generator.py`](../../../synlab/integrations/reference_generator.py) 读取实际 VesselForge 候选形状，并把几何、材料和纹样组合成可重放的研究包。10 月 16 日续程记录了 6 个早期包和 3 个 PBR 变体；新包见 [`bluewhite_reference_generation`](../../../experiments/continuation_20261016/bluewhite_reference_generation/README.md)。 | 这是对实际 VF 候选形状的集成，不是完整器类目录或器物复刻。已有曲面仍包含未测壁厚/底足等假设；几何预览与格式检查不能替代真实参考形状对比。 |
| 来源材质 | [`docs/a12/REFERENCE_MATERIALS_20261015.md`](../../a12/REFERENCE_MATERIALS_20261015.md) 记录 Aberdeen celadon、Met Jun stoneware、Met 50899 porcelain 和 Smithsonian unglazed Colonoware 四个有名来源的外观配方；新的引用路径能把语义面上的釉层外观与胎体/新断面分开。 | 轮廓/表面外观字段是设计代理值，不是对象的色度/BRDF 或釉料测量；物理釉厚与制作过程未证实。密度、弹性、强度、韧度和断裂能等材料力学仍为 `UNKNOWN`。 |
| 有来源意义的纹样 | [`docs/a12/REFERENCE_PATTERN_STYLES_20261015.md`](../../a12/REFERENCE_PATTERN_STYLES_20261015.md) 有 Hasami Tokusa（木贼纹的来源描述）与 Met Jun plain 两条可构建路线。Hacilar chevron 目前是研究候选，不会用三角替代人字纹。 | Tokusa 是源信息约束的周期笔触近似；Jun plain 只表达素面。它们没有校准笔触、颜料、釉层、烧成或完整器物布局。其他来源器族仍须精修内容与位置。 |
| Met 50899 青花局部 | [`bluewhite_reference_generation`](../../../experiments/continuation_20261016/bluewhite_reference_generation/README.md) 以 Met 29.149.50 / object 50899 的公开已烧成照片蓝色差异提取局部掩模，并在器外壁有限面板上组合明度、瓷质外观和传输场。 | 仅为部分照片投影。不是完整龙纹/环绕图、不可见面的推断、烧前笔触恢复、光学校准或真实扩散化学。照片来源限定了可作的解释。 |
| 源分辨率静态笔触 | [`bluewhite_source_resolution`](../../../experiments/continuation_20261016/bluewhite_source_resolution/README.md) 新增可选 `source_resolved_stationary_v1`：静止的 75% 部分从不可变的全分辨率来源掩模取样，迁移的 25% 部分从有限体积 (FV) 网格取样；零传输能重现来源场。两个输出包共 **27,304,078 bytes**，FV field **240 × 1024**，连续纹理 **480 × 2048**。 | legacy `grid_bilinear_v1` 仍是默认值。浮点场质量口径为 `DISCRETE_GRID_MASS_ONLY`；没有主张连续来源场的质量积分相等或细网格收敛。几何数组 hash 与较早 v6 witness 相同，但 source-section hash 不同；这组包**未**绑定到 `run05` 的精确原生链，也没有运行断裂。 |
| 原生弱缝与观测 | 已有预置弱缝的 Akantu 研究 packet 及 6 张 A12 RGB-D 研究视图；有关来源绑定和资格边界见[续程审计](../../../../docs/continuation/20261016/generic_binding_audit/REPORT.md)与[全项目状态](../../../../docs/continuation/20261016/STATUS.md)。 | packet 明确为 `PREINSERTED_WEAK_SEAM_UNCALIBRATED`，`physical_pass=false`、`pretrain_eligible=false`。它是研究/control 数据，不是校准陶瓷或可训练资格。针对新审阅母器的真实物理破裂尚未跑通。 |
| 整体物理交付 | 续程状态记录旧控制案例具有原生演化、独立历史读回、两个闭合片和六张 RGB-D；另有全尺寸几何的零步预检与 run05 网格证明。 | 全尺寸预检不是裂纹演化。新母器上的原生物理事件、来源/面祖先链、材料和网格收敛、碎片/观测及独立审核尚缺。全项目经资格认定的物理包仍为 **0**。 |

### 10 月 16 日测试证据

续程状态记录 root 对 source-resolution、panel、generator、underglaze 和 reference-material 路径运行了 **55 项 focused checks，exit 0**。这只支持所述切片；不是全仓 pytest、整个 A12 acceptance 或真实物理合格的证明。早期 checkpoint 也有另外的 focused 结果，不能与本轮 55 项合并成一次全量验收。证据入口：[`docs/continuation/20261016/STATUS.md`](../../../../docs/continuation/20261016/STATUS.md)。

外部资源仍需按源许可、拓扑、语义和用途逐一审阅。例如 Apsida SHM 17946:0047 的 refined v3 虽修掉孤岛、零面积面和反向重合面，仍有 7 个 pinched vertex links；当前结论是仅可作视觉参考，不能直接作为实体仿真网格，见 [`REALITY_GAP_INVENTORY.md`](../../../../docs/continuation/20261015/REALITY_GAP_INVENTORY.md)。

## 尚未完成的工作

1. **真实器族与参数。** 为日常和考古器族补充逐件引用、完整可见轮廓/扫描、比例与坐标系；区分来源事实、视觉推断、生成器选择和 unknown。每族要审阅多项公共控制与器专属控制的真实几何效果，排除 no-op 字段，不能把 V01–V24 registry 数当成 24 个有来源类别。
2. **形体覆盖和精修。** 将来源形状接入可追溯的 VesselForge 几何输入；逐一验口沿、壁、底/足、把手/流嘴、连接和最小壁厚。按用途检查导入资源、许可、拓扑和源面语义。没有来源尺寸的部分保留 unknown，不用默认曲线填成“真实”。
3. **材质校准。** 继续完善釉/胎体和语义表面映射；把呈现用颜色、粗糙度、IOR 等与来源测量分开。物理求解所需力学参数须来自可比制样/过程并记录不确定度，不能从对象名称或跨配方论文借值。
4. **纹样与工艺。** 为器物确定有出处的纹样含义、真实布局和表面区域；细化笔画、留白、比例、刷痕、颜料和工艺参数。Tokusa/Jun/Met 50899 是窄切片；Met 50899 不能代替完整龙纹或历史重建。对暂不能映射的来源继续显式阻止错误替代。
5. **青花外观。** 在完成纹样内容与连续布局审阅后再迭代扩散、图像和材质构成；区分外观代理与高温烧成/釉下扩散化学。保留 legacy 默认与 opt-in 来源模式，后续质量主张需要独立采样/误差证据。
6. **真实母器物理破裂。** 把经审阅的 VF 母器与 PG 网格、源面、节点和 A12 观测作显式身份绑定；然后再做授权的 native run、材料/网格/方向收敛、能量与接触审计、独立碎片重建、RGB-D 质量审阅。弱缝预置和零步成本预检都不能替代该链。
7. **训练和发布资格。** 重新审核来源/物理标签、观察泄漏、训练包来源和释放门。只有实际母器物理数据及其所有数据闸门独立通过后，才讨论其 `PRETRAIN` 或发布资格。

## 恢复工作的建议顺序

恢复时先建立“来源事实 → 几何 → 语义/材质 → 纹样 → 物理”的逐器族验收表，并由用户审阅来源和形态样例；之后在 VesselForge 固化来源绑定与共用/器专属参数，再由 SynLab 组合经过审阅的材质与纹样；最后才把冻结的几何传给 PG-Frag/Akantu 做真实母器事件，并让 A12 消费已通过独立资格的观察/真值。每个阶段保留未测信息，不把上游的形状 QA、材质显示或数值运行提升成下游物理/训练结论。

这只是交接建议，不代表工作已开始或已有新实验授权。暂停期间只维护状态、引用和可复查记录。

## 主要入口

- A12 架构与模块：[architecture](../../a12/architecture.md)、[runbook](../../a12/runbook.md)、[design-space 证据](../../a12/DESIGN_SPACE_20261015.md)
- 来源材质与纹样：[materials](../../a12/REFERENCE_MATERIALS_20261015.md)、[patterns](../../a12/REFERENCE_PATTERN_STYLES_20261015.md)
- 最新青花切片：[source-resolution README](../../../experiments/continuation_20261016/bluewhite_source_resolution/README.md)、[reference-generation README](../../../experiments/continuation_20261016/bluewhite_reference_generation/README.md)
- 跨仓当前状态：[2026-10-16 continuation status](../../../../docs/continuation/20261016/STATUS.md)、[generic binding audit](../../../../docs/continuation/20261016/generic_binding_audit/REPORT.md)
