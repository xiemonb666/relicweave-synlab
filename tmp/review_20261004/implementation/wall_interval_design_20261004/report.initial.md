# P03 壁厚区间算法审查

日期：2026-10-04。仅静态阅读源码和已有报告；未运行 operator、solver、测试或 Git 命令，未改生产代码。此报告是供主负责人裁决的算法设计稿。

## 源码定位与证据

仓库根目录是 `relicweave-synlab`。SHA256 是分析时对下列文件原始内容计算的散列；本次按任务要求没有读取 Git revision。

| 文件 | 相关位置 | SHA256 |
|---|---:|---|
| `synlab/degrade/narrowband.py` | `_offset_body` 270；`paired_thickness` 368–419 | `31E5E44F198F357991768C2AC1EC08DF4115A5E5E5C9BADCF903F82B1F9C5A8A` |
| `synlab/degrade/physical_narrowband.py` | `_assemble` 44；dispatch 121–131；P03 `_erode_interface` 228–345 | `88844F78AF2366B2BDABDF2AB6B5DCC12DF7579C91F5CC0A38873BD021D6A19D` |
| `synlab/degrade/axes.py` | recipe/dispatch 341–398；P03 declaration 557–579 | `852DC3A0C9335210E7AD91C167B73E7A5400C0884EE15A245682DD953B7121C6` |
| `synlab/physical/sdf.py` | `_SceneCache.cast` 267–319 | `FD433876FA4DF84D2316C93DBBE521E1094241829D5FCCF93CEDEEAC02467B1D` |
| `data/a12_degrade/store/reports/degrade_diversity/LIN0000_V02_M01_PAT02.json` | P03 L1 record, around 318–345 | `F0E9B848564C88C7F2E9B7FE9F9535C1543C271BB8F8AEF877A77FDD7A707B97` |

实际调用链：`apply_axis` → `_PhysicalAxis._apply` → `physical_result` → `run_narrowband_damage` → `_erode_interface` → `NB.paired_thickness`。P03 在 `axes.py:564` 将 `MIN_WALL_MM = 0.6` 写进 recipe 的 `qa.min_wall_thickness_mm`；P03 在 `physical_narrowband.py:247–275` 读取它，但只用它决定是否启用相对损失循环，没有检查受损壁厚是否达到 0.6 mm。

`paired_thickness` 的关键错误在 `narrowband.py:399–404`：源表面点为 `p`、外法线为 `n`，射线起点取 `p + eps*n`，这是表面外侧；随后沿 `-n` 进入源体。源体的首个命中是刚离开的同一表面，返回距离约为 `eps`，再加一次 `eps` 后得到约 `2*eps`，不是壁厚。受损体的首命中可能是退蚀后的近侧入口，因此源/受损数字不是对应的源侧/内侧区间。反过来只把 `+` 改成 `-` 也不能修复材料站对应：受损后原点可能在受损体外，最近命中仍可能是入口。

另有三条静默通过路径：

1. `scene_for(...).cast` 在 `sdf.py:308–315` 调用 `RaycastingScene.cast_rays` 并只取每条射线的第一个 `t_hit`；没有构造入口/出口区间。
2. `narrowband.py:404` 只保留 `src`、`dst` 同时有限且为正的样本；失败样本没有原因计数。`samples` 始终返回请求的 `n_samples`，即便 ROI 掩码已过滤掉大量点；因此 `paired/samples` 也不能区分 ROI 抽样损失和射线失败。没有任何有效配对时，函数返回 0 违规率。
3. `_erode_interface` 以 `violation_fraction <= budget` 作为守卫条件。`thickness_guard_satisfied` 仅据此赋值；`hard`（328 行）只看有体积损失和 body 水密性，然后 `_assemble` 将 `realized=True` 映射成 QA `PASS`（44–62 行）。守卫失败或不可测都不能可靠阻止 PASS。

已有可复核报告已表现出假量：同一 P03 L1 记录 `min_thickness_mm=0.006728`、`undamaged_min_thickness_mm=0.001999`、`max_local_thickness_drop_mm=-0.004728`、`thickness_violation_fraction=0`、`thickness_guard_mm=0.6`、`thickness_guard_satisfied=1`，且 `realized=true`。这足以证明当前的 0.6 mm 没有被绝对核验。任务交接还记录了一次 400 请求样本只保留 164 个配对；本次没有重跑，不推断实际样本的通过率或应有 PASS 数。

另一个容易误读的量：`physical_narrowband.py:303–305` 的 `planned_max_recession_mm` 与 `measured_max_recession_mm` 都等于 `depth * scale`；几何独立量是后面的 `measured_max_vertex_shift_mm`。应把参数值与实测位移分开命名，不把前者当厚度证据。

## 建议算法：沿可信壁向构造材料区间

建议以“源侧局部连续材料区间”和“同一条壁向射线在最终受损体中的对应连续区间”作为测量对象。指标只在采样处有可信壁向时叫壁厚；它不是把某条射线穿过的所有实体长度相加。

1. **限定适用面和壁向。** 每个站点保存 source face id、重心坐标（barycentric coordinates）和点 `p`。方向 `w` 必须来自明确的 outer/inner CAD 对应、材料局部壁向映射，或有可信外壁语义的源面法线。P03 的 `interface`/断口/ROI 边缘法线本身不能证明是器壁法线；缺少可信壁向时返回 `UNKNOWN/WALL_DIRECTION_UNMAPPED`，不能用它生成壁厚 PASS。若已有 CAD 内外壁配对映射，优先直接沿配对向量测量并用射线区间作几何复核。
2. **对 ROI 面做确定的面积加权抽样。** 直接从 ROI 三角形按面积选面并在面内取重心随机点，使 `requested_samples=400` 代表 400 个 ROI 站点。当前“全体表面抽 400 再过滤 face_mask”的写法应移除。每个站点固定 seed 并记录 face/barycentric 站点标识，源和受损体复用同一射线。
3. **在源体和最终受损实体上枚举交点。** 对两者从 `o=p+eps*w` 沿 `d=-w` 求有界射线（上限取局部包围盒对角线加余量）。现有 Open3D 场景接口只返回最近命中；可在同一场景上重复调用既有 `cast_rays`，每次沿射线越过已合并的命中事件继续查询，直到上限或交点上限。对命中距离排序，并以局部尺度和 float32 精度定合并容差；同一平面/共享边的重合三角形命中先聚类。用相邻事件之间的 inside/outside 状态确认真实穿越：状态不变的是切触/掠射事件，不算材料区间；状态变化才构成进入/离开边界。超过容差可分辨率的极薄区间、事件数超限或状态不确定时计入 ambiguous，而非忽略。
4. **选择一个源材料区间并只比较它。** 找到紧邻采样站点、包含源表面入口的源区间 `[a_s,b_s]`；它的长度是源局部弦厚 `t_s=b_s-a_s`。受损体中只允许匹配与该源区间重叠且位于其内的一个连续区间 `[a_d,b_d]`。唯一匹配时 `t_d=b_d-a_d`、`loss=t_s-t_d`。受损区间为空代表该站点穿孔/材料已完全去除，`t_d=0` 并标记 `PERFORATED`；多段区间代表破裂/穿孔分割，标记 `SPLIT_INTERVAL`，不可把段长相加或随意挑最长一段。多个候选、非嵌套或站点对应不唯一均为 `UNKNOWN/AMBIGUOUS_MATCH`。这避免跨空气腔把多个壁段相加，也防止用别的壳层补上丢失区间。
5. **验证与守卫最终几何。** 受损体应是 P03 裁剪/接受后的输出（当前 `intersect_with_source` 在测厚之后调用），或在裁剪后做一次最终复核。测量前检查 source/result 是有限、非退化、闭合且 winding 一致的体；异常 mesh 不提供可通过的厚度 QA。壁向不适用、射线切触、源区间缺失、交点不稳定、命中上限、coverage 不足全部保留为原因计数并降为 UNKNOWN。闭合有效体中，原源区间对应受损段确实为空或被分裂，是可观测的物理 FAIL（穿孔）。

局部法线射线在平缓、可信的器壁面、浅层法向侵蚀时近似代表材料站；它不保证任意弯曲壁上的严格拉格朗日配对。断口边缘的三角面法线尤其可能横切器壁、沿器壁擦过或指向相邻碎片。若没有 inner/outer 对应和面语义，就应把这个限制表达为 `UNKNOWN`，不要将“弦长”包装成可信的“壁厚”。这也适用于 RelicWeave 的裂片数据：碎片边缘方向本身不是器壁法向。

## 返回结构与 QA 语义

建议新结构明确版本和适用性，不保留当前错误含义的 `min_thickness_mm` 名称：

```json
{
  "wall_interval_schema": "material_interval_v1",
  "status": "PASS | FAIL | UNKNOWN",
  "direction_source": "inner_outer_map | classified_outer_normal | unmapped",
  "requested_samples": 400,
  "roi_samples": 400,
  "source_intervals_valid": 0,
  "paired_valid": 0,
  "coverage_fraction": 0.0,
  "invalid_counts": {"source_miss": 0, "grazing": 0, "ambiguous": 0, "open_mesh": 0},
  "perforated_samples": 0,
  "min_source_wall_interval_mm": null,
  "p05_source_wall_interval_mm": null,
  "min_remaining_wall_interval_mm": null,
  "p05_remaining_wall_interval_mm": null,
  "max_loss_mm": null,
  "max_loss_fraction": null,
  "fraction_over_50pct_loss": null,
  "absolute_min_guard_mm": 0.6,
  "absolute_guard_pass": false,
  "relative_violation_budget": 0.01
}
```

字段示例值只是结构示例，不是对真实 400 样本的预测。最终数据应有真实数值或 `null`，不能用 0 伪装缺测。

* `PASS`：壁向适用、mesh/区间解析有效、ROI 覆盖达到预先冻结的门槛（建议起步门槛 95%，并报告全部 unknown 数）、没有 perforated/split interval、`min_remaining_wall_interval_mm >= 0.6`，且 `fraction_over_50pct_loss <= 0.01`。coverage 门槛只是抽样质量门，不声称 400 点证明全局最小值。
* `FAIL`：有效闭合几何表明样点穿孔/区间断裂、绝对壁厚低于 0.6 mm，或相对损失预算超限。可测量的厚度 FAIL 可按既有 scale 循环减小深度再复测；超过迭代次数仍失败必须最终失败。
* `UNKNOWN`：壁向无映射、源样点无法选定唯一材料区间、raycast/mesh/open-shell 有歧义，或有效覆盖不足。未知状态不可进入下一级“厚度通过”分支，也不能仅通过降低 erosion 深度解决结构性未知。P03 的最终物理 QA 对 UNKNOWN 应结构化失败（`realized=false`），同时保留厚度子 QA 为 `UNKNOWN`，不能冒充可测的厚度 FAIL。

建议在每个 P03 `attempts[]` 记录 status、paired/ROI 数、coverage、perforated/ambiguous 数和当前绝对/相对 guard；只有该次 `PASS` 才允许 break。`_assemble` 的 `qa.status`、`realized` 和 failure code 必须由厚度 guard 状态参与决定；目前的“体积损失 + watertight”不够。通过前需对最终 accepted mesh 再核验。

## 兼容迁移与可用 API

`paired_thickness` 的生产唯一直接调用者是 `physical_narrowband._erode_interface`（268 行）。迁移时同步改：P03 attempts（270–275）、P03 measurements/units/details（312–340）、`_assemble` `qa.status`（44–62）、`_PhysicalAxis._apply` 对 `result.qa.realized` 的提升（axes.py 414–435）、审计列及 `docs/a12/degrade_axes.md` 中把相对损失 0.0 写成 PASS 证据的旧说明。删除或版本化迁移 `min_thickness_mm`、`undamaged_min_thickness_mm`、`max_local_thickness_drop_mm`、`thickness_violation_fraction` 旧语义；不要继续兼容地把 entry 距离塞回这些字段。旧报告的厚度列应标成 legacy/unverified，并在小范围复核时重算，不能沿用为物理验证结果。`thickness_guard_mm` 保留为声明的绝对阈值，新增对它的实测比较。

`pyproject.toml` 声明 `trimesh>=4.4`；当前 `synlab/physical/sdf.py` 的真实射线后端是可选外部依赖 `open3d==0.19.0`。已有 `_SceneCache.cast` 包装 Open3D `RaycastingScene.cast_rays`，可重复调用该 API 实现小样本全交点扫描；无需增加或安装依赖。`trimesh.sample.sample_surface` 可作基础表面抽样，但为了保证恰好抽到 ROI，应直接基于 ROI 面积加权抽面并生成面内重心坐标。这里仅识别接口，未安装、导入或运行任何依赖。

## 最小验收矩阵（tiny 几何，不跑生产数据）

数值以 mm 为单位。1.0 mm 方壳侧壁可用外盒 `10×10×10`、内腔 `8×8×8` 的封闭布尔壳，沿侧壁法线测试。表中 PASS/FAIL/UNKNOWN 是新的 interval guard 状态，不是当前实现的实测结果。

| # | Fixture / 输入 | 预期区间与状态 | 必须锁定的行为 |
|---|---|---|---|
| 1 | 完整封闭 1 mm 方壳；源与受损相同 | source=1.0、damaged=1.0；PASS | 首次入口之后继续找出口，不能报约 `2*eps`；精确已知厚度可回归。 |
| 2 | 同一壳的外侧均匀退蚀 0.2 mm，内侧不动 | source=1.0、damaged=0.8、loss=0.2；PASS | 固定站点同一射线；绝对阈值和 50% 相对损失规则均通过。 |
| 3 | 同一壳外侧均匀退蚀 0.5 mm，绝对门槛 0.6 mm | source=1.0、damaged=0.5；FAIL | 虽恰为 50%（旧规则 `>` 可能不计违规），仍因绝对最薄壁低于 0.6 而失败。 |
| 4 | 1 mm 壳上一处局部贯穿小孔，样点落在孔中心 | 对应源段 1.0、受损段 0；FAIL / perforated | 不可将缺失射线删除后算 0 违规；穿孔不能被附近第二面/第二段补成厚度。 |
| 5 | 模拟 raycast miss，或输入 mesh 开口导致 damaged interval 不可信 | UNKNOWN，`paired_valid`/coverage 下降并记录 miss/open 原因 | 与有效闭合体中的真实“区间为空”区分；不得返回零厚度/零违规的 PASS。 |
| 6 | 射线与壁相切、沿面共面或击中共享三角边 | grazing/ambiguous 计数；本样点 UNKNOWN（整体依门槛） | 同距离重复三角命中要聚类；切触前后 occupancy 不变，不可误配 entry/exit。 |
| 7 | 壳体内部有空气腔，射线穿过第一段 1 mm 壁、空腔、第二段 1 mm 壁 | 只返回样点所属的 1 mm 区间，不得返回 2 mm 总长；第一壁退蚀后仅报其剩余段 | 多区间按包含源站点的材料段配对，禁止跨空腔求和。 |
| 8 | 全局 inverted winding / 不闭合或非流形的壳 | UNKNOWN 或在实体前置检查时结构性 FAIL；绝不 PASS | 验证 winding/闭合前置条件；不能靠异常法线符号让方向反转后仍配错区间。 |

该矩阵是实现前的最小验收定义。当前阶段没有实施测试，也没有根据现有 400 样本推定 PASS 数。
