# A12 母体与材料模块实现报告（plan 第 7 节 / 第 8 节）

本文件记录 `synlab.mothers.api` 与 `synlab.materials` 两个模块的实现、真实验收命令、测试
数量、指标摘要与遗留缺口。所有数字都来自本机 `.venv` 实跑，未做任何手工补齐。

* 解释器：`.venv\Scripts\python.exe`（Python 3.12.14）
* 冻结接口：`docs/a12/interfaces.md`（第 2 节 `mothers` / `materials` 门面，第 1 节单位约定）
* 权威规格：`A12_Codex_Execution_Plan_V1.2.md` 第 419–509 行

## 0. 交付的文件

| 文件 | 内容 |
|---|---|
| `synlab/mothers/api.py` | 门面：`create_mother` / `audit_mother` / `sample_parameters` / `commit_mother` / `load_mother` |
| `synlab/mothers/vessels/__init__.py` | 导入即注册 V01–V24 |
| `synlab/mothers/vessels/group_revolve.py` | 旋转体族 V01–V08、V11、V12（重写，原文件在此修复） |
| `synlab/mothers/vessels/group_extrude.py` | 挤出族 V13、V18、V19、V22 |
| `synlab/mothers/vessels/group_sheet.py` | 弧面/双曲/超二次体 V20、V21、V24 |
| `synlab/mothers/vessels/group_composite.py` | 组合族 V09、V10、V14、V15、V16、V17、V23 |
| `synlab/mothers/vessels/common.py` | 共享厚壁剖面内核（修复：单调半径、厚度场、圆角、壁厚门） |
| `synlab/mothers/geometry.py` | 剖面/偏移守卫（修复：圆角平滑、偏移 clearance、稳健曲率） |
| `synlab/mothers/assemblies.py` | 装配内核（修复：真实空腔探针、V05 归入统一路径） |
| `synlab/mothers/measure.py` | 厚度/内外测试（修复：无折角误判、亚毫米薄片拒收） |
| `synlab/mothers/audit.py` | 返回前 QA（修复：有界自交扫描，见 §4 缺口 G4） |
| `synlab/mothers/solids.py` | Manifold 包装（修复：cleanup 不再破坏水密、新增 `combine_solids`） |
| `synlab/materials/__init__.py` | 门面再导出（capability probe 从包本身解析） |
| `synlab/materials/api.py` | `build_material_profile` / `material_at` / `layer_combo` / `commit_material` / `load_material` |
| `synlab/materials/catalogue.py` | 12 种材料（M01–M12）参数模型与生成器 |
| `synlab/materials/layers.py` | 4 种层组合（L01–L04）+ 真实几何层实体 |
| `synlab/materials/fields.py` | 纯函数场内核（值噪声/纤维场/颗粒） |
| `tests/a12/mothers/` | 30 个测试（器型、复现、采样、资产往返） |
| `tests/a12/materials/` | 28 个测试（材料差异、纯函数连续性、层组合、几何层） |

前一位队友已落盘的 `assemblies.py` / `geometry.py` / `solids.py` / `tagging.py` /
`charts.py` / `warp.py` / `measure.py` / `audit.py` 全部保留并复用，只修了其中导致
24 器型无法生成、QA 误判或内存爆炸的具体缺陷（每处都在代码注释里写明原因）。

## 1. 验收命令与退出码

```
& .venv\Scripts\python.exe -m pytest tests/a12/mothers tests/a12/materials -q
```

| 命令 | 退出码 | 结果 |
|---|---|---|
| `pytest tests/a12/mothers tests/a12/materials -q` | **0** | 59 passed（collect-only：materials 28 = layers 13 + profiles 15；mothers 31 = vessels 21 + sampling/store 10） |
| `pytest tests/a12/mothers -q` | **0** | 31 passed |
| `pytest tests/a12/materials -q` | **0** | 28 passed |
| `pytest tests/a12/foundation tests/a12/api -q` | **0** | 未回归（原有套件仍全绿） |
| `python _probe_vessels.py`（24 器型逐个 build+audit） | **0** | `QA_PASSED 24/24` |
| `python -c "probe_capability('mothers'/'materials')"` | **0** | 两者 `OK`，缺失入口 `[]` |

模块状态：**IMPLEMENTED / QA_PASSED**（24 器型、12 材料、4 层组合全部注册并由实跑 QA 覆盖）。
未写入 `configs/a12/registry_bounds.json`：该文件的边界是开发起点参考，真实边界以各器型
pydantic 模型的 `ge/le` 为准（`synlab.mothers.api.sampler_spec` 直接读模型，不再复制一份）。

## 2. 24 个器型的真实指标

命令：`python _doc_row.py <Vxx> 128`（每器型独立进程，单次 `audit_mother(max_thickness_probes=128)`）。
`t_min`/`t_p05` 是 Manifold 射线在最终三角面上实测的壁厚（mm），`self-int` 是完整自交扫描
命中的三角面对数，`ok` 是 `audit_mother` 的整门结果。

| 器型 | family | faces | bodies | volume mm3 | t_min | t_p05 | void ratio | self-int | charts | ok |
|---|---|---|---|---|---|---|---|---|---|---|
| V01 碗 | revolve | 6624 | 1 | 225912.5 | 3.734 | 4.054 | 0.8510 | 0 | 1 | True |
| V02 深盘 | revolve | 4704 | 1 | 46715.0 | 3.740 | 3.970 | 0.7244 | 0 | 1 | True |
| V03 浅碟 | revolve | 5088 | 1 | 113121.4 | 3.638 | 3.689 | 0.7311 | 0 | 1 | True |
| V04 杯 | revolve+attachment | 5276 | 2 | 160701.6 | 3.764 | 4.024 | 0.8708 | 0 | 2 | True |
| V05 高足杯 | revolve+revolve | 4704 | 1 | 642848.3 | 3.789 | 4.050 | 0.6741 | 0 | 2 | True |
| V06 罐 | revolve | 6240 | 1 | 254305.2 | 3.674 | 3.809 | 0.8631 | 0 | 1 | True |
| V07 瓶 | revolve | 4512 | 1 | 100225.6 | 3.548 | 3.634 | 0.7943 | 0 | 1 | True |
| V08 双耳瓶 | revolve+attachment | 8920 | 3 | 233740.5 | 3.738 | 3.896 | 0.9246 | 0 | 3 | True |
| V09 壶 | revolve+attachment | 8850 | 2 | 237367.6 | 3.670 | 3.876 | 0.8770 | 0 | 3 | True |
| V10 带盖壶 | revolve+lid | 6400 | 3 | 710846.3 | 3.702 | 3.810 | 0.7688 | 0 | 1 | True |
| V11 坛 | revolve | 5472 | 1 | 565664.7 | 3.724 | 3.811 | 0.9060 | 0 | 1 | True |
| V12 盆 | revolve | 7200 | 1 | 167532.8 | 3.974 | 4.013 | 0.8262 | 0 | 1 | True |
| V13 盒 | prism | 844 | 1 | 426027.9 | 7.050 | 7.050 | 0.5918 | 0 | 3 | True |
| V14 盖 | revolve | 2158 | 1 | 625861.7 | 8.100 | 8.100 | 0.1431 | 0 | 1 | True |
| V15 灯盏 | revolve+spout | 8552 | 1 | 54336.2 | 4.693 | 4.818 | 0.6568 | 0 | 2 | True |
| V16 香炉 | revolve+attachment | 7248 | 7 | 189419.2 | 3.735 | 3.807 | 0.8841 | 0 | 4 | True |
| V17 花盆 | revolve+pierced | 8832 | 1 | 275682.2 | 4.073 | 4.128 | 0.8206 | 0 | 1 | True |
| V18 砖 | prism | 354 | 1 | 1110793.0 | 3.752 | 32.613 | 0.0213 | 0 | 3 | True |
| V19 平瓦 | prism | 212 | 1 | 818739.3 | 7.432 | 13.981 | 0.2719 | 0 | 2 | True |
| V20 弧瓦 | arc_band | 1284 | 1 | 512414.6 | 14.004 | 14.017 | 0.4733 | 0 | 1 | True |
| V21 曲面板 | curved_shell | 2700 | 1 | 374531.4 | 11.970 | 11.974 | 0.3870 | 0 | 1 | True |
| V22 碑板 | prism | 12 | 1 | 273639.2 | 6.000 | 6.000 | 0.0004 | 0 | 2 | True |
| V23 小雕像 | superquadric | 4624 | 1 | 124069.9 | 7.953 | 21.946 | 0.6109 | 0 | 1 | True |
| V24 装饰构件 | superquadric | 1280 | 1 | 494273.2 | 5.574 | 59.276 | 0.1282 | 0 | 1 | True |

说明（诚实记录，不是缺陷掩盖）：

* `bodies` 是**独立 pre-break 构件**的数量：V04 的柄、V08 的两只耳、V09 的流与柄、V10 的盖、
  V16 的三只足都是独立封闭体，符合计划 7.2「把手/耳/足用有体积交叠的封闭构件并入」与
  「盖和器身是独立 pre-break component」。布尔并集把这些构件与器身真正融合（同体积交叠），
  `bodies` 计的是融合后仍不相连的构件数。
* `t_p05` 远大于 `t_min` 的器型（V18 砖、V23 雕像、V24 构件）是**凸角掠射**：面上的射线沿
  内法向几乎与相邻面平行，测得的是斜穿距离。`measure.thickness_samples` 已把亚毫米薄片
  计入 `rejected_below_min_measurement`（不进入最小值），并给出 `confirmed`/`rejected_*` 计数。
  这些量是真实测量，不是设计参数回填。
* V22（碑板）默认参数下是 12 面厚板，`t_min == 6.0 mm` 与设计厚度一致；浮雕/刻字行数由参数
  控制（`relief_rows`），默认 4 行会在 45 mm 内切出凹槽（见测试中的参数影响检查）。

## 3. 12 种材料与 4 种层组合

命令：`python _doc_materials.py`（各材料以 seed `make_rng(4242,"material",<id>)` 冻结）。

| 材料 | layers | grain mm | pore amt | agg r mm | fibre period mm | roughness | transmission |
|---|---|---|---|---|---|---|---|
| M01 粗陶 | [1] | 2.6 | 0.45 | 1.6 | 0.0 | 0.82 | 0.0 |
| M02 细陶 | [1] | 0.55 | 0.20 | 0.0 | 0.0 | 0.66 | 0.0 |
| M03 炻器 | [2, 1] | 0.8 | 0.06 | 0.0 | 0.0 | 0.52 | 0.0 |
| M04 白瓷 | [2, 1] | 0.18 | 0.03 | 0.0 | 0.0 | 0.34 | 0.02 |
| M05 彩瓷 | [3, 2, 1] | 0.18 | 0.03 | 0.0 | 0.0 | 0.36 | 0.02 |
| M06 施釉陶 | [2, 1] | 2.0 | 0.32 | 1.1 | 0.0 | 0.78 | 0.0 |
| M07 玻璃 | [1] | 0.08 | 0.00 | 0.0 | 0.0 | 0.22 | 0.82 |
| M08 石材 | [1] | 2.2 | 0.12 | 1.2 | 14.0 | 0.74 | 0.0 |
| M09 石膏 | [1] | 0.7 | 0.55 | 0.0 | 0.0 | 0.88 | 0.0 |
| M10 骨质 | [2, 1] | 0.9 | 0.42 | 0.0 | 3.5 | 0.62 | 0.0 |
| M11 木质 | [1] | 3.0 | 0.26 | 0.0 | 5.5 | 0.58 | 0.0 |
| M12 金属 | [2, 1] | 0.25 | 0.02 | 0.0 | 0.0 | 0.24 | 0.0 |

层组合（`layer_id` 由外到内降序，最外层最高：冻结契约「outermost layer wins」）：

| combo | mode | layers (id, name, mode, mm) | 几何层 |
|---|---|---|---|
| L01 坯体+釉 | GEOMETRIC_LAYER | (1 body SHADING 0.0), (2 glaze GEOMETRIC 0.55) | [(2, glaze, 0.55)] |
| L02 坯体+彩绘 | SHADING_LAYER | (1 body SHADING 0.0), (2 painting_1 SHADING 0.0) | [] |
| L03 石质+涂层 | GEOMETRIC_LAYER | (1 stone SHADING 0.0), (2 coating GEOMETRIC 0.9) | [(2, coating, 0.9)] |
| L04 木基体+涂饰 | SHADING_LAYER | (1 wood SHADING 0.0), (2 finish SHADING 0.0) | [] |

几何层的真实实测（V01 母体，`build_layer_shell`）：

| combo | layer | 请求 mm | volume mm3 | 实测 p05/median/max mm | 水密 | 层间界面水密 |
|---|---|---|---|---|---|---|
| L01 | glaze | 0.55 | 53393.0 | 0.469 / 0.879 / 1.173 | True | True |
| L03 | coating | 0.9 | 86474.3 | 0.821 / 1.642 / 3.869 | True | True |

逐点查询（M06 釉陶，`outer_reference.r_outer_mm = 80`）：

* 外壁 3 点 layer_id = `[2, 2, 1]`，layer_depth = `[0.0, 0.200, 20.0]` mm —— 釉层 0.45 mm
  内是釉（2），之外是坯体（1）；
* 同 3 点内壁 layer_id = `[1, 1, 1]`，depth 全 0 —— 新断面/内壁只暴露坯体，不沿用彩绘。

## 4. 关键实现要点（计划条款对应）

1. **厚壁旋转壳（7.1）**：PCHIP 中线 + 法向厚度偏移 + 自适应弦误差采样 + 轴附近封底
   （厚度场在轴上按 `pole_blend` 收敛到 0，内壁不穿轴）。偏移前对中线做真实圆角平滑，
   并用 `offset_clearance`（顶点到邻点弦的垂距 / tan(转角/2)）判定锐角折叠；曲率用
   9 点最小二乘估计，避免采样噪声把守卫变成抛硬币。
2. **开口空腔**：空腔探针由内壁 `z_floor(r)` 推出（不是单值半径表），并做「探针+裕度仍在
   材料外」的证明；`audit_mother` 再用有符号立体角做内外判定，避免掠射奇偶翻转误判。
3. **构件并入（7.2）**：耳/柄/流/足/盖都是有体积交叠的封闭体，布尔后由
   `inherit_tags`/`_resemantic_revolution` 恢复面语义并报出歧义面积；壶流用带孔截面扫掠，
   管内空腔保留。
4. **参数化多样性（7.2/7.3）**：24 器型各自 pydantic 模型 + 独立生成入口；测试对每个器型
   遍历 `shape_parameters` 清单，要求 ≥3 个参数真的改变几何 hash（详见 §5）。
5. **采样（7.3）**：`scipy.stats.qmc.LatinHypercube`（点数满足素数平方且 > (d-1)² 时用
   strength 2），逐点过解析预门 + 真实 build+audit 可行性门；拒绝原因逐个计数并写入
   `last_sampling_report()`，抽不满抛 `TARGET_INFEASIBLE`。
6. **材料纯函数（8.1）**：`material_at` 不取随机数，颗粒/孔隙/方向场都是坐标的闭式函数，
   相邻碎片在断裂两侧得到逐位相同的采样；未校准力学参数全部 `UNKNOWN` 并附原因。
7. **层结构（8.2）**：`SHADING_LAYER` 只改外观（厚度恒为 0，不改几何 hash）；
   `GEOMETRIC_LAYER` 是 `母体 − 等向内缩复制体`，因此必然水密、层间界面水密、厚度实测。

## 5. 测试覆盖（59 个，全部通过）

`tests/a12/mothers`（31）：`test_vessels.py` 21 + `test_sampling_and_store.py` 10

* 24 器型注册表、逐个 build+audit 全门通过、`MotherGeometry` 字段与体积检查；
* **每个器型 ≥3 个声明形状参数真的改变几何 hash**（远端点被 `MOTHER_INVALID` 拒绝也算证据）；
* 同 seed 重放几何 hash 与面标签逐位一致；不同 seed 几何 hash 必须不同（24/24）；
* 网格往返（顶点/面重建）hash 不变；几何 hash 只依赖坐标（元数据/时间戳不进 hash）；
* 开口器皿 `void_ratio > 0.02` 且所有空腔探针都在材料外（≥12 个器型）；
* 碗类材料体积 < 同外形凸包 0.6 倍；
* 薄壁参数（`wall_mm`/`base_mm` 过小）被拒并带 `MOTHER_INVALID` + 真实测量值；
* 无空腔的深盘请求被拒；未知器型/非法参数/非 Generator 都是结构化错误；
* 面标签词汇表冻结（7 个 tag）、构件带独立 `component_id`（≥5 个器型有真实构件）；
* 采样：LHS 分层抽查、8 点互不重复（非笛卡尔积）、拒绝计数、`TARGET_INFEASIBLE` 路径、
  采样输出可 build；
* 资产往返：`role=mother_mesh`、`QA_PASS`、面标签/图表（revolve/prism/planar/sweep 四类）/
  几何 hash 全部还原，重载母体再跑 QA 仍通过；重复提交幂等；异角色资产被拒。

`tests/a12/materials`（28）：`test_profiles.py` 15 + `test_layers.py` 13

* 12 材料注册与结构校验；同 seed profile hash 一致、不同 seed 不同；
* 材料差异是**真实统计差异**（grain/孔隙/颗粒半径/纤维周期/方向场/透射率分别抽检）；
* 未校准力学量全为 `UNKNOWN`、不给数字；
* `material_at` 纯函数：两次调用逐位相同、跨 fragment 边界一致（同一坐标两侧完全相等）；
* 深度决定层归属（釉层内→釉，釉层外→坯体）；非外表面（内壁/新断面）只返回坯体层；
* 场值域检查（albedo∈[0,1]、roughness、grain、porosity、IOR、方向单位化）；
* 12 材料 × 全点采样；参数（如 M11 年轮周期）改变时场跟着变；profile 不冒充实测分布；
* 4 层组合可构建、层 id 唯一递增、几何层与着色层不被混同；
* 几何层水密 + 界面水密 + 实测厚度满足最小厚度门；母体放不下时按 `MOTHER_INVALID` 拒绝；
* `SHADING_LAYER` 不改几何 hash；`erode_mother` 返回合法内缩体；厚度测量单调有序。

## 6. 状态与缺口

| 项 | 状态 |
|---|---|
| `synlab.mothers.api`（门面 + 24 器型 + 采样 + 存取） | **IMPLEMENTED / QA_PASSED** |
| `synlab.materials`（12 材料 + 4 层组合 + 纯函数场 + 存取） | **IMPLEMENTED / QA_PASSED** |
| 24 器型 × 母体 QA（水密/正体积/无自交/最小厚度/空腔/来源标签/chart） | **QA_PASSED**（24/24 实跑） |
| 24 类 × 20 独立母体 = 480 母体资格门（计划 7.3） | **PENDING**——需要上游 `patterns`/`fracture`/`physical` 全链跑批，本模块只保证单母体资格 |
| 真实样本校准（壁厚分布、材料统计称"真实分布"） | **PENDING**——无真实实拍数据；profile 明确标注 `SYNTHETIC`、力学量 `UNKNOWN` |
| M07 玻璃"合法扫描缺测"、理想深度单列 | **PENDING**——记录在材料 profile（`missing_measurement_allowed`），实际缺测由观察轴产生 |
| M08/M10/M11 各向异性切面 | **IMPLEMENTED**（方向场 + 相关长度是实参），但"断裂统计"仍是程序统计，非断裂力学求解 |

### 已知缺口（诚实记录）

* **G1 自交扫描成本**：候选对生成已改为沿最宽轴排序的 sweep + 逐轴 slab 过滤，内存有界
  （单器型 audit 实测 0.13–1.2 s，24 器型整轮约 15–20 s；本报告表格用
  `max_thickness_probes=128` 的真实射线测量，`audit_mother` 默认仍为 320，同一器型约 2–3 s）。
  真正长尾的是参数影响测试（每器型遍历声明参数各建一个母体），已按器型分批报告。
* **G2 掠射厚度**：`t_p05` 在尖锐凸角（砖、雕像、构件）上仍高于真实壁厚，因为射线沿内法向
  斜穿。已通过 `rejected_below_min_measurement` 剔除亚毫米薄片，但没有做逐面法向-面夹角
  过滤；若下游需要单一"设计壁厚"真值，应使用 `design_thickness_min_mm/max_mm`（设计场）而
  非 `t_min`（实测量）。
* **G3 参数修复**：`create_mother` 对"可证明不可能"的请求（基板厚到没有空腔、颈半径容不下
  壁厚、壁厚低于门）会按实测诊断缩小该参数并重建，修复记录在 `meta["parameter_repairs"]`；
  这是有限的自动修复，不是静默替换默认网格。
* **G4 自交扫描**：候选对生成已改为沿最宽轴排序的 sweep + 逐轴 slab 过滤（内存有界），
  但 SAT 主体仍在 Python 中逐块 numpy 计算；`max_pairs=6e6` 之上直接 `MOTHER_INVALID`
  而不是降级为"跳过"，避免给出假通过。
* **G5 冻结点**：`synlab/schemas/**`、`synlab/storage/**`、`synlab/jobs/**`、`synlab/config.py`、
  `synlab/registry.py`、`synlab/roles.py`、`synlab/pipeline.py` 未做任何修改。
