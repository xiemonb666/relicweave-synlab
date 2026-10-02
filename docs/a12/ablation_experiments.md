# A12 消融 / 对照实验清单（可运行、可复算、可判正负收益）

> **性质**：实验设计文档。每条实验的自变量直接引用 full 导出包 `ablation_index.json` 的
> **组 id**；因变量一律引用 `docs/a12/v144_project_core.md` §2.2/§2.3 的**内部指标合同**；
> "当前是否可跑"由**真实导出包的组可用性**判定（`present` / `partial` / `missing`），
> `missing` 的组必须写出"缺什么才能有"。
>
> **不裁判决**：本文件不产生任何性能数字，也不把"能加载"写成"有增益"。
> 全部模态的当前真实计数与缺失清单见导出包内 `manifest.json`，以及汇总报告
> `data/a12/reports/full_export_report.json` 与 `data/a12/reports/full_export_report_a12_scoped.json`。
>
> 产线：`synlab/storage/export_full.py`（flavor=`full`）产出 `manifest.json` + `ablation_index.json`；
> 加载器 `tools/load_full_package.py`。本文件的人工部分只有"实验设计"。

---

## 1. 为什么需要这一层：可开关的数据维度

消融的前提是**能按维度开/关**。本仓此前的导出（`synlab/storage/export.py` 的
`export_training_package`）回答的是"训练作业**允许**消费什么"：它按视图通道白名单裁剪、
把名字不透明化、只导出一个关系表。那套包**无法**回答"把深度通道关掉会怎样"——被裁剪的通道
已经不在包里。

`flavor="full"` 换一个口径：**凡库里存在的都写出来**，按 `(role, 通道族)` 重组成可开关的
**模态**，再把模态归到**消融组**。裁剪被推迟到加载时（`--groups <id,...>`），
所以"没开"和"不存在"在证据上是两件事。

三层映射（每层都可程序化核对）：

```
底层数组 key  --family_of()-->  模态 modality_id = "<role>.<family>"
模态        --ABLATION_GROUPS--> 消融组 group_id（35 组）
组          --field_patterns-->  加载器实际读入的字段（"<modality_id>#<array key>"）
```

**诚实规则**（由 `synlab/storage/export_full.py` 实现、由 `tests/a12/storage` 钉住）：

1. 模态只有两种状态：`present`（有真实文件）或 `missing`（**必须**带 `unlock_condition`）；
   不存在"声明了但没数据"的通道。
2. 每个模态带 `deployment_view_allowed` + 理由；真值/标签角色**永不**可进部署视图，
   判定读自真实策略文件 `synlab/schemas/view_channels.json`（路径与字节哈希记进清单）。
3. `synthetic_only` 由资产自身元数据（`source_kind`/`data_scope`/`real_capture`）逐资产推出，
   并同时报出"声称真实采集的资产数"。
4. 唯一派生件是**断面子集**（`fragment_mesh.interface_faces`），公式写进 `derivation`；
   库里**不存在**的独立断面资产仍单独记 `missing`。

---

## 2. 可用性快照（实测，两个包互补）

| 包 | 来源库 | 选择 | 资产 | 碎片 | 文件 / 字节 | 模态 present/missing | 组 present/partial/missing | 耗时 |
|---|---|---|---|---|---|---|---|---|
| **A** `data/a12_exports/full` | `data/a12_campaign/store` | `mode=all` | 158 / 158 | 13 | **893 / 4 372 076 409 B** | **48 / 39** | 12 / 15 / **8** | 258.0 s |
| **B** `data/a12_exports/full_a12_scoped` | `data/a12`（主库） | `mode=limit, limit=2` | 171 / 894 | 2 | **1 427 / 27 520 236 B** | **101 / 9** | **31** / 2 / **2** | 45.2 s |

（文件数不含 `manifest.json`/`ablation_index.json`/`README.md`；`--check` 两包均 **exit 0**，
896 / 1430 个文件逐字节与清单一致。）

**两个包为什么都要有**：A 是"整库全碎片"的口径（能看真实分布、跨母体），
B 是"主库全模态"的口径（`data/a12` 才有 `obs_view`/`obs_fused_geometry`/`degrade_measurement`/
`relation_pool`/`query_roster`/`provenance`/受损 `physical_component`）。**没有任何单一库同时具备两者**，
这正是 full 导出要"逐库可跑"的原因。

### 2.1 组可用性（A / B 对照，决定每条实验"当前是否可跑"）

| 组 id | A | B | 字段数(A/B) | 权限 | 说明 |
|---|:--:|:--:|---|---|---|
| `G-GEOM-MOTHER` | present | present | 5 / 5 | research | 母体 mesh 顶点/面/面属性 |
| `G-GEOM-FRAG` | present | present | 2 / 2 | research | 碎片 mesh 顶点/面 |
| `G-GEOM-PHYS` | partial | partial | 5 / 3 | research | 有 `physical_component` 的 `payload.mesh`/`appearance` 之一，缺另一侧 |
| `G-FRAC-ATTR` | partial | **present** | 9 / 10 | research | B 里三类角色的面属性都在 |
| `G-FRAC-IFACE-DERIVED` | present | present | 7 / 7 | research | 派生断面子集（B：6 文件 / 0.66 MB） |
| `G-FRAC-IFACE-TRUTH` | present | present | 12 / 12 | research | `clean_truth` 的 `iface_*` |
| `G-FRAC-CORR` | present | present | 34 / 34 | research | `clean_truth`+`physical_truth` 的 `corr_*` |
| `G-IMG-RGB` | partial | **present** | 12 / 8 | **deploy** | B 同时有 `obs_result` 与 `obs_view` |
| `G-IMG-LINEAR` | partial | **present** | 12 / 8 | research | A 的最大单项 2.49 GB |
| `G-IMG-DEPTH` | partial | **present** | 12 / 9 | **deploy** | |
| `G-IMG-IDMAP` | present | present | 12 / 4 | research | |
| `G-IMG-TAG` | present | present | 12 / 4 | research | **A 的 rim≠0，B 的 rim=0**（见 2.2） |
| `G-MASK-DEPLOY` | partial | **present** | 12 / 8 | **deploy** | |
| `G-MASK-ROI` | partial | **present** | 12 / 9 | research | |
| `G-MASK-UNCERTAIN` | present | present | 12 / 4 | **deploy** | |
| `G-CAM-K` | partial | **present** | 12 / 8 | **deploy** | |
| `G-CAM-POSE` | partial | **present** | 12 / 8 | research | |
| `G-CAM-DIST` | partial | **present** | 12 / 8 | research | |
| `G-PC-FUSED` | partial | **present** | 4 / 11 | **deploy** | B 含重融合云与 `point_view/priority_order` |
| `G-PC-REFERENCE` | missing | **present** | 0 / 1 | research | 泄漏对照，B 里可加载 |
| `G-FEAT-FIELDS` | partial | **present** | 6 / 9 | research | |
| `G-QUALITY` | present | present | 3 / 3 | research | 11 通道 `quality__values` |
| `G-TOKENS` | partial | **present** | 1 / 2 | research | |
| `G-LABEL-CLEAN` | present | present | 29 / 29 | research | |
| `G-LABEL-PHYSICAL` | partial | **present** | 17 / 19 | research | |
| `G-LABEL-VISIBLE` | present | present | 7 / 2 | research | |
| `G-LABEL-BUNDLE` | present | present | 24 / 8 | research | 像素级 id/tag 标签图 |
| `G-REL-POOL` | missing | **present** | 0 / 7 | research | B 有 `relation_pool` + `query_roster` |
| `G-DEGRADE-PHYSICAL` | missing | **present** | 0 / 13 | research | P01/P03/P05/P06/P07 物化 |
| `G-DEGRADE-IMAGING` | missing | **present** | 0 / 12 | research | I01–I10 全覆盖 |
| `G-DEGRADE-GEOMETRY` | missing | **present** | 0 / 3 | research | G01–G08 全覆盖 |
| `G-DEGRADE-PROTOCOL` | missing | partial | 0 / 8 | research | X01–X05 全覆盖，缺 `degrade_measurement.meta_arrays` |
| `G-CONTEXT` | missing | **missing** | 0 / 0 | research | 全仓 0 个 `context_pack` |
| `G-DISPLAY-LOD` | missing | **missing** | 0 / 0 | deploy | 两个库都没有 `display_lod_glb` |
| `G-PROVENANCE` | partial | **present** | 1 / 2 | research | B 有 `provenance`+`qa_report` |

**汇总**：两包合计可加载 **33 / 35** 组；只剩 `G-CONTEXT` 与 `G-DISPLAY-LOD` 两处
（前者全仓无产物，后者要换 `data/a12_demo/store` 才有 GLB）。

### 2.2 三个必须一起读的实测（数字来源：包内 manifest，可复算）

1. **断面在 2D 中的可见性逐库不同**：
   * 包 A（campaign）：`obs_result.surface_tag` 的 `tag=2 (rim)` = **4 805 310 / 207 618 048 = 2.31%**；
     `label_bundle` 的 `tag=2` = **361 556 / 28 311 552 = 1.28%**。
   * 包 B（主库）：`tag` 直方图只有 `{-1, 0}`，**rim = 0 / 196 608**；`label_bundle` 同样 **rim = 0 / 589 824**。
   * 结论：`docs/a12/modality_census.md` §3.2 的"rim = 0"是**主库**结论；campaign 库**不成立**。
     **任何"断面在 2D 中不可见"的论断必须写明库名与分母。**
2. **退化档位真实计数**（包 B `degradation.materialised`）：31 轴注册（可复算），
   **28 轴有 level 1–4 物化**——`G01–G08`、`I01–I10`、`P01/P03/P05/P06/P07`、`X01–X05`；
   **`P02/P04/P08` 零物化**（与普查 §4.4 一致，但这里是**从导出包读出的**）。
3. **合法负例仍然为 0**（包 B 的关系池，逐对实测）：
   `relation_pool` = **66 对**：`R1 = 64`、`R2 = 2`；`valid = 2`、`loss_mask = 2`；
   **`kind∈{R0,R1} 且 valid 且 loss_mask` 的对数 = 0**。
   与 `docs/a12/training_run.md` §8.5 独立一致。

另外几个直接可用的观测实测（包 B，用于消融基线）：
`deployment_mask` 真值 **1 421 / 2 445 312 = 0.058%**；
`uncertain_mask` **63 130 / 196 608 = 32.1%**；
`valid_mask` **216 366 / 2 248 704 = 9.62%**；
`research_mask` **321 029 / 2 248 704 = 14.28%**；
`roi` **41 993 / 484 361 = 8.67%**；
`id_map` 背景像素 **129 172**，可见面 ID 去重 **17 122** 个。

### 2.3 一个必须先说的前提：主指标当前**算不出来**，而原因**不是**模态缺失

`any@50` / `Hit@10` / `CovRecall@10` / 无邻片误导率的分母需要
**冻结 roster + 图库关系表 + 每 query 的合法负例 + R2 对两端都有观测**。实测：

* roster 与关系表：包 B 有（`query_roster` 1 件 / `relation_pool` 2 件）；
* **合法负例 = 0**（见 2.2 第 3 条）；
* R2 对的两端观测：`docs/a12/training_run.md` §4/§8.5 实测"没有任何一条关系行两端都能编码"
  （`eligible_as_negative = False` 150/150、`z_valid[candidate]==False` 3/3）。

⇒ 以 `any@50`/`Hit@10` 为因变量的实验，在补齐**负例与双侧观测**之前一律只能报
`NOT_RUN`（核心文档 §2.2 第 8 条：未运行填 `NOT_RUN`，**不得填 0**）。
下表"当前是否可跑"因此分两列：**加载**（`--groups` 能取到真实张量）与**主指标**（分母成立）。

---

## 3. 评测与统计前提（引用核心文档，不新造）

| 项 | 取值 | 出处 |
|---|---|---|
| `any@50` | 有邻片查询中至少一名真邻片进入初检 50 池；正常质量内部目标宏值 **0.95** | 核心文档 §2.3 |
| `Hit@10` | 前 10 中至少一名库内真邻片；目标宏值 **0.90**，**95% 下界 0.85** | §2.3 |
| 低质 `Hit@10` | 日常低质查询对清晰库、独立母体；目标 **0.85** | §2.3 |
| `CovRecall@10` | 前 10 找回库内真邻片比例；**不低于冻结强基线** | §2.3 |
| 新方法主比较 | 增益 **≥3 个百分点**且**母体簇配对双侧 95% 区间下界 > 0** | §2.3 / §2.4 |
| 干净性能守卫 | 相对同池强基线下降 **≤2 个百分点** | §2.3 |
| 无邻片误导率 | mate-absent 被接受推荐 ÷ mate-absent 总数；目标 **≤5%**，95% 上界 ≤10% | §2.3 / §2.2 第 6 条 |
| 有邻片接受覆盖 | mate-present 中被接受输出比例；**≥80%**（不能靠全拒绝换低风险） | §2.3 |
| 工作流价值 | 拍摄＋补拍＋检查总任务时间**中位用时 −30%** | §2.3 |
| 聚合 | 先按母体内 query 平均，再对独立母体**等权宏平均** | §2.2 第 2 条 |
| 区间 | 母体簇配对双侧 95%；零事件单侧上界 `1−0.05^(1/n)`（n=20 → 13.9%） | §2.4 |
| 未运行 / 不适用 / 证据不足 | 分别填 `NOT_RUN` / `NOT_APPLICABLE` / `NOT_ESTABLISHED` | §2.2 第 8 条 |

**模型与五任务监督**（`docs/a12/training_run.md` §2.4/§8–§11，作为"哪些组合正收益"的载体）：

* 主干 `FragmentEncoder` + `PairRefineHead`，总参数 **72 710**，`temperature=0.1`；
* 批次张量：`global_rgb [N,V,3,H,W]`、`pixel_valid [N,V,H,W]`、`points/normals [N,P,3]`、
  `local_tokens [N,T,256]`、`quality [N,1,1]`、`scale_valid [N]`；
* 五任务权重：`rank` **1.0**、`view` 0.1、`correspondence` 0.1、`contradiction` 0.1、`quality` 0.05；
  实测**只有 `view` 与 `quality` 拿到过真实监督**，其余三个因"缺合法负例 / 对端无观测 /
  标签落不到 token 空间"被跳过。

**判定纪律**（核心文档 §3.1/p381，直接决定"正/负收益"口径）：

> 只有**在退化、hard negative 与真实微调后仍保持方向一致**的增益才能升级为核心候选；
> 只在合成 clean 上出现的提升 → **记为负结果或低优先级**。

**架构侧的三个已实测缺陷**（消融的零假设，来自 `docs/a12/modality_census.md` §7.7）：
`tokens` 有效秩 = 1、`view_pos` 全零、`frame_id` 是行号计数器。凡涉及 token / 相机位移 /
视角身份的组，**零假设必须是"无增益"**，出现增益才需要解释。

---

## 4. 实验清单（20 条）

约定：**自变量（IV）** = 组 id；**因变量（DV）** = 指标名＋门槛来源；
"可跑" = `加载`（A/B 哪个包能取到张量）/ `主指标`（分母是否成立）。

### E01 单模态地板：只给交付 RGB
* **假设**：交付态 RGB 单独即可支撑非平凡下界；它是部署基线，也是所有增益的分母。
* **IV**：`G-IMG-RGB`（on）＋其余全 off。
* **DV**：`any@50`、`Hit@10`、`CovRecall@10`（§2.3）；先算随机地板与 oracle 上界（§1.2 反捷径纪律）。
* **所需数据**：`obs_result.rgb` / `obs_view.frames.rgb`。
* **可跑**：加载 **A partial / B present**；主指标 **不可**。
* **缺什么**：合法负例 + R2 双侧观测（§2.3）。

### E02 碎片 3D 几何的净增量
* **假设**：碎片权威网格（mm/`W_mm`）在 2D 之外提供互补证据，`Hit@10` ≥ +3pt，且在退化档位方向一致。
* **IV**：`G-GEOM-FRAG`（on/off），E01 为底座。
* **DV**：`Hit@10` 增益（母体簇配对双侧 95% 下界 >0）、`CovRecall@10`、干净守卫 ≤2pt。
* **所需数据**：`fragment_mesh.vertices/faces`（A 34 文件 / 0.98 MB；B 12 文件）。
* **可跑**：加载 **A/B 均可**；主指标 **不可**。
* **缺什么**：同 E01；另需 `F_mm`↔`W_mm` 对齐用的位姿真值（A `G-CAM-POSE` partial，B present）。

### E03 母体先验是否有用
* **假设**：加入母体全局形状提升检索，或只是增加输入维度（**负结论同样有效**）。
* **IV**：`G-GEOM-MOTHER`（on/off）。
* **DV**：`Hit@10`、`CovRecall@10`；**母体泄漏审计**（`parent_id/object_id` 在 `FORBIDDEN_FEATURE_FIELDS` 内）。
* **所需数据**：`mother_mesh.*`（A 33 文件 / 0.80 MB；B 18 / 0.57 MB）。
* **可跑**：加载 **A/B 均可**；主指标 **不可**。
* **缺什么**：同 E01；且必须证明增益来自几何而非母体 ID。

### E04 断面面属性 vs 2D tag 图（四格对照）
* **假设**：断面可定位性来自逐面 `origin_kind/interface_id`，而非 2D `surface_tag`；两者同开才有正收益。
* **IV**：`G-FRAC-ATTR`（on/off）× `G-IMG-TAG`（on/off）。
* **DV**：`Hit@10`；断面可定位性（`findings.fracture_visible_in_2d`）；`contradiction` 损失。
* **所需数据**：`*.face__origin_kind/interface_id/side/ambiguous`（B 三类角色齐全：`present`）。
* **可跑**：加载 **B present**；主指标 **不可**。
* **缺什么**：同 E01；另：**A/B 的 rim 事实相反**（2.31% vs 0），四格必须在**同一个包**内跑，
  且报告里写明包与分母。

### E05 派生断面子集能否替代"独立断面资产"
* **假设**：`fragment_mesh.interface_faces`（`origin_kind==1` 派生）足以支撑断面级监督。
* **IV**：`G-FRAC-IFACE-DERIVED`（on/off），与 E04 联合。
* **DV**：断面面积一致性（派生 `iface_area_mm2` 求和 vs `clean_truth.iface_area_mm2`）、`Hit@10`。
* **所需数据**：`iface_face_index/faces/area_mm2/centroid/normal/vertices/vertex_index`。
* **可跑**：加载 **A/B 均可**（B 实测：1646 / 864 / 34 / 3316 个 INTERFACE 面，7 字段/件）；
  一致性核对 **可**；主指标 **不可**。
* **缺什么**：主指标分母；另外全仓**没有**独立断面 mesh role（`standalone_interface_asset.status = absent`），
  所以只能在特征层面验证"够用"，不得声称等价于扫描台断面件。

### E06 断面级真值（面积/间隙/法向）
* **假设**：`iface_*` 聚合真值是配对监督的必要项；去掉它 `correspondence`/`contradiction` 都退化。
* **IV**：`G-FRAC-IFACE-TRUTH`（on/off）。
* **DV**：配对断口面积一致性、R2 判定 AUROC、`Hit@10`。
* **所需数据**：`clean_truth.iface_*`（12 字段）。
* **可跑**：加载 **A/B 均可**；主指标 **不可**。
* **缺什么**：`physical_truth`/`visible_labels` 层**没有** `iface_*`（普查 §6.3 实测）→
  退化后无法评测局部关系；需把 `iface_*` 下推到 physical/visible 层（P2 缺口）。

### E07 逐点对应监督的边际收益
* **假设**：`corr_*` 逐点对应（权重 0.1）有可归因增益；只在 clean 有效、退化后消失则记负结果。
* **IV**：`G-FRAC-CORR`（on/off）。
* **DV**：`correspondence` 损失与其 `n_allowed`（`training_run.md` §8.4）、`Hit@10`、`CovRecall@10`。
* **所需数据**：34 个 `corr_*` 字段。
* **可跑**：加载 **A/B 均可**；损失**不可启动**（标签落不到 token 空间）。
* **缺什么**：一份 **token 空间**的对应表 `(q,c,i,j,weight)`；本包已含构造它所需的
  `G-CAM-K`/`G-CAM-POSE`/`G-IMG-IDMAP`/`G-IMG-DEPTH`（这正是 full 包相对训练包的增量）。

### E08 深度 / id_map 的捷径审计（**预期负收益**）
* **假设**：`depth_z` 与 `id_map` 是渲染器构造的答案通道，会在 clean 上虚高、在退化下崩塌
  —— 正是核心文档 §3.1 要求"保留为负结果"的情形。
* **IV**：`G-IMG-DEPTH`（on/off）、`G-IMG-IDMAP`（on/off）；对照 `G-CAM-POSE`。
* **DV**：clean 与退化档位的 `Hit@10` **差值**；捷径审计项（§3.2）。
* **所需数据**：`obs_result.depth_z`（A 830 MB）、`obs_result.id_map`（A 830 MB）、
  `obs_view`/`obs_fused_geometry` 的退化档位（B present）。
* **可跑**：加载 **A/B 均可**（退化档位只在 B）；主指标 **不可**。
* **缺什么**：主指标分母。另注意：真实策略把 `depth_z` 标为**可进部署视图**，
  但同一策略也给它 `CAVEAT_NOT_MEASURED_ON_REAL_RIG`，两者必须一起读。

### E09 融合点云 / 法向
* **假设**：观测点云与法向是 2D 之外的互补证据。
* **IV**：`G-PC-FUSED`（on/off）。
* **DV**：`Hit@10`、`CovRecall@10`、`surface repeat error` / `normal repeatability`（`t093`）。
* **所需数据**：`obs_result.points/normals/point_valid/normal_valid`、`obs_fused_geometry.*`（B 10 模态）。
* **可跑**：加载 **B present / A partial**；主指标 **不可**。
* **缺什么**：主指标分母；A 库缺 `obs_fused_geometry`。

### E10 干净参考点云 = 泄漏对照（**必须判为泄漏**）
* **假设**：`reference_points` 属特权信息，用它会得到虚高指标，不得计入部署收益。
* **IV**：`G-PC-REFERENCE`（on/off）。
* **DV**：`Hit@10`（预期虚高）＋**特权上界标注**（§2.6：E16/E20 高分是 privileged/oracle 上界，
  **严禁当作部署性能**）。
* **所需数据**：`obs_fused_geometry.reference_points`（B 32 文件 / 0.61 MB）。
* **可跑**：加载 **B present**；主指标 **不可**（但"是否虚高"的方向性检查需要指标）。
* **缺什么**：主指标分母。

### E11 特征场 vs 原始点云
* **假设**：显式法向/曲率/密度场比原始点云更有效（等价也是有用的负结论）。
* **IV**：`G-FEAT-FIELDS`（on/off），与 E09 对照。
* **DV**：`Hit@10`、`CovRecall@10`、法向稳定性。
* **所需数据**：`feature_bundle.{point_cloud,normal_field,curvature_field,density_field,roi_weight}`。
* **可跑**：加载 **B present / A partial**；主指标 **不可**。
* **缺什么**：主指标分母。

### E12 质量向量 → 拒识与误导率
* **假设**：质量向量改善"无邻片误导率"与"有邻片接受覆盖"的权衡。
* **IV**：`G-QUALITY`（on/off，权重 0.05）。
* **DV**：**无邻片误导率 ≤5%**、**有邻片接受覆盖 ≥80%**、`quality` 损失与 `n_valid`。
* **所需数据**：`quality__names/values/valid`（11 通道，B 实测通道名以 `blur_laplacian_p95` 开头）。
* **可跑**：加载 **A/B 均可**；拒识类指标 **不可**（`mate_present` 只有 `{None, False}`，
  两类查询都凑不齐，核心文档 §4.1 数据缺口表）。
* **缺什么**：① mate-present 与 mate-absent **两类查询都要有**；② 观测侧质量输入要真
  （`training_run.md` §11：包内需带 OBS_EST 通道，当前 loader 写死 `quality = zeros((1,1))`）。

### E13 token 缓存是否携带独立信息
* **假设**：`view_tokens`/`token_index` 若有效秩为 1，对指标无贡献（**预期负收益**）。
* **IV**：`G-TOKENS`（on/off），与"直接用 `token_input`/像素"对照。
* **DV**：`Hit@10`；token 有效秩（`sv[1]/sv[0]`）。
* **所需数据**：`feature_bundle.view_tokens`、`token_index`。
* **可跑**：加载 **B present**；主指标 **不可**。
* **缺什么**：主指标分母；零假设为"无增益"（训练包 `deploy/tokens` 有效秩 = 1，普查 §7.7 D1）。

### E14 监督层选择：clean vs physical（正/负收益分水岭）
* **假设**：clean 层监督只在合成 clean 上提升；换 physical 层后增益消失 ⇒ 按 §3.1 **记负结果**。
* **IV**：`G-LABEL-CLEAN` × `G-LABEL-PHYSICAL` × `G-LABEL-VISIBLE`，共 8 格。
* **DV**：`rank` 损失与 `effective_queries`、`Hit@10`、`CovRecall@10`；三档报告分层。
* **所需数据**：`clean_truth.*`（29 字段）、`physical_truth.*`（19 字段）、`visible_labels.*`。
* **可跑**：加载 **A/B 均可**；`rank` **不可启动**（0 合法负例，§2.2 第 3 条）。
* **缺什么**：合法负例 + 双侧观测（`training_run.md` §11 `rank` 解锁条件①②）。

### E15 部署掩码的真实代价
* **假设**：只保留部署可获取像素（实测覆盖率极低）会显著降低 `Hit@10`；差值即"部署代价"。
* **IV**：`G-MASK-DEPLOY`（on/off），与 `G-MASK-ROI`、`G-MASK-UNCERTAIN` 组合。
* **DV**：`Hit@10` 差值（部署 − 研究上界）、`any@50`。
* **所需数据**：`deployment_mask`（B 真值率 **0.058%**）、`roi`（8.67%）、`uncertain_mask`（32.1%）、
  `valid_mask`（9.62%）、`research_mask`（14.28%）。
* **可跑**：加载 **A/B 均可**；主指标 **不可**。
* **缺什么**：主指标分母；实验必须写明用的是哪一个掩码（可见性/研究 ROI/不可归属像素语义不同）。

### E16 退化轴敏感度曲线（4 个 stage 分列，共 28 轴 × 4 档）
* **假设**：各轴造成可测的性能下降，且**不可由 clean 表现外推**。
* **IV**：`G-DEGRADE-IMAGING`（I01–I10）、`G-DEGRADE-GEOMETRY`（G01–G08）、
  `G-DEGRADE-PHYSICAL`（P01/P03/P05/P06/P07）、`G-DEGRADE-PROTOCOL`（X01–X05），
  逐 `axis_id` × `level`（1–4）对照 level 0（恒等档，普查 §4.3 实测 31/31 恒等）。
* **DV**：`Hit@10`/`CovRecall@10` 随 level 的曲线；8 项质量向量分量；显式 `NOT_RUN`/`NOT_ESTABLISHED`。
* **所需数据**：`obs_view`（I 轴）、`obs_fused_geometry`（G 轴）、`physical_component`（P 轴）、
  `degrade_measurement`（X 轴）。
* **可跑**：加载 **B present（PROTOCOL partial）**；轴×档位矩阵 **可**（B 实测 28 轴 level 1–4）；
  主指标 **不可**。
* **缺什么**：主指标分母；`P02/P04/P08` 仍零物化；每族只跑了 `default_variant`（无多轴 recipe 产物）。

### E17 模拟出土上下文（**预期负收益 / 必须留反例**）
* **假设**：受限模拟上下文若带来增益，多半来自与母体 ID 的隐含等价；文档禁止这种等价。
* **IV**：`G-CONTEXT`（on/off），按 `X03` 的 `missing_context` / `conflicting_context` 分层。
* **DV**：`Hit@10`、上下文冲突率；**泄漏审计**（`FORBIDDEN_FEATURE_FIELDS` 含 `parent_id/object_id/bag_id`）。
* **所需数据**：`context_pack`（`synlab.context.v1`，`ROLE_CONTEXT_PACK`）。
* **可跑**：**不可**（A/B 都 `missing`；全仓 0 个 `context_pack`）。
* **缺什么**：物化 context_pack，且必须保持"不能等价母体 ID"（核心文档 `t101(D23)`）。

### E18 展示 LOD 是否影响几何侧实验
* **假设**：L0 与 L1/L2 的差别对几何指标无实质影响（成立则展示层可不进实验回路）。
* **IV**：`G-DISPLAY-LOD`（on/off）。
* **DV**：`surface repeat error`、`normal repeatability`、覆盖。
* **所需数据**：`display_lod_glb`（L0 scene + L1/L2 scene node）。
* **可跑**：**不可**（A/B 都 `missing`；`display_lod_glb` 只在 `data/a12_demo/store`，
  而该库没有 `fragment_mesh`）。
* **缺什么**：① 对 `data/a12_demo/store` 也跑一次 full 导出（GLB 载荷 19.2 MB，成本低）；
  ② 装 `fast_simplification` 让 L1/L2 真正进场景图。

### E19 provenance 缺失 = 不可复算（反例组，所有实验的准入条件）
* **假设**：没有 provenance 的结果无法复算；该组"on"是其余实验的准入条件。
* **IV**：`G-PROVENANCE`（on/off）。
* **DV**：可复算率、哈希一致性（`code_fingerprint`/`backend_fingerprints`/`spec_hash`）。
* **所需数据**：`provenance`、`qa_report`、`material_profile`、`pattern_channels`、`pattern_recipe`。
* **可跑**：加载 **B present / A partial**；复算核对 **可**。
* **缺什么**：主指标分母（但指纹核对本身已可做）。

### E20 关系表与 roster（所有检索实验的前提）
* **假设**：按冻结 roster 评测与随机划分显著不同；后者不可引用。
* **IV**：`G-REL-POOL`（on/off）。
* **DV**：`any@50`、`Hit@10`、`CovRecall@10`；并检查 `loss_mask ≡ valid ≡ (kind=="R2")` 的冗余（§6.4）。
* **所需数据**：`relation_pool.rel_*`（B：66 对 = R1 64 + R2 2）、`query_roster.queries`。
* **可跑**：加载 **B present / A missing**；**主指标仍不可**（合法负例 = 0，§2.2 第 3 条）。
* **缺什么**：≥1 条 `valid=true & loss_mask=true` 的 R1/R0 负例，且 R2 对两端都要有观测。

---

## 5. 正/负收益的判定表

| 组合 | 预期 | 判定方式 |
|---|---|---|
| RGB + 碎片几何 | **正**（若 ≥3pt 且 CI 下界 >0） | E01 vs E02，母体簇配对双侧 95% |
| RGB + 几何 + 断面属性 | **正** | E04 四格；再看 `G-IMG-TAG` 是否仍有独立贡献 |
| 断面属性 + 派生断面子集 | **正**（先过面积一致性） | E05 一致性核对先过，再谈指标 |
| 深度 / id_map | **负**（捷径） | E08：clean 虚高而退化崩塌 ⇒ 记负结果 |
| 干净参考点云 | **负**（泄漏） | E10：标 privileged，不计入部署收益 |
| token 缓存（秩 1） | **负** | E13：零假设为"无增益" |
| 模拟出土上下文 | **负 / 待证** | E17：在"不可等价母体 ID"约束下测试 |
| clean-only 监督 | **负**（迁移后消失） | E14：三档分层，跨档方向不一致即负结果 |
| 部署掩码 vs 全图 | **负**（部署代价） | E15：差值本身就是结论 |
| 退化轴单开 | **负**（单调下降） | E16：曲线需单调且不可由 clean 外推 |

**报告纪律**：每个组合都要同时报 ① 指标宏值＋母体簇配对区间；② `synthesised_labels=0` 与
跳过原因（`training_run.md` §2.6 的 `honesty` 字段）；③ 是 `NOT_RUN` 还是 `NOT_ESTABLISHED`。

---

## 6. 复算命令

```powershell
cd C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab

# 1) 包 A：整库全碎片（campaign）
& .venv\Scripts\python.exe -m synlab.storage.export_full `
    --store data/a12_campaign/store --out data/a12_exports/full

# 2) 包 B：主库全模态（2 碎片，选择记录在 manifest.selection）
& .venv\Scripts\python.exe -m synlab.storage.export_full `
    --store data/a12 --out data/a12_exports/full_a12_scoped --limit 2

# 3) 组清单与可用性
& .venv\Scripts\python.exe tools\load_full_package.py --package data/a12_exports/full --list-groups

# 4) 按组加载（打印真实形状与计数）
& .venv\Scripts\python.exe tools\load_full_package.py --package data/a12_exports/full_a12_scoped `
    --groups G-IMG-TAG,G-FRAC-ATTR,G-DEGRADE-IMAGING --verbose

# 5) 重新生成汇总报告（本文件 §2 的全部数字都来自这两份 JSON）
& .venv\Scripts\python.exe tools\load_full_package.py --package data/a12_exports/full `
    --report data/a12/reports/full_export_report.json
& .venv\Scripts\python.exe tools\load_full_package.py --package data/a12_exports/full_a12_scoped `
    --report data/a12/reports/full_export_report_a12_scoped.json

# 6) 一致性（exit 0 = 一致 / 3 = 不一致）
& .venv\Scripts\python.exe tools\load_full_package.py --package data/a12_exports/full --check

# 7) 测试（实测 exit 0，84 passed）
& .venv\Scripts\python.exe -m pytest tests/a12/storage -q
```

---

## 7. 仍然缺口（诚实清单）

1. **主指标分母不成立**：合法负例 **0**（包 B 关系池实测：R1 64 / R2 2，`valid&loss_mask` 全为 R2），
   且 R2 对无双侧观测 ⇒ `any@50`/`Hit@10`/误导率/接受覆盖 **一律 `NOT_RUN`**（E01–E16、E20 全受影响）。
   **这不是模态问题，任何 full 导出都无法解决**：需要数据侧补负例与双侧观测。
2. **`P02/P04/P08` 零物化**：31 轴里 28 轴有档位（包 B 实测），三轴仍缺；
   每族只跑 `default_variant`，无多轴 recipe 产物 ⇒ E16 只能做单轴单变体曲线。
3. **出土上下文不存在**：全仓 0 个 `context_pack` ⇒ E17 不可跑。
4. **L1/L2 不可得**：缺 `fast_simplification`；GLB 只有 L0 ⇒ E18 不可跑（且需要换库）。
5. **断面 2D 可见性逐库不同**：包 A rim = 2.31%、包 B（主库）rim = 0；结论必须带库名与分母。
6. **派生断面子集不是"独立断面资产"**：全仓仍无独立断面 mesh role，替代性只能在特征层面验证。
7. **`iface_*` 只存在于 clean 层**：退化后无法评测局部断面关系（P2 缺口）。
8. **`physical_component` 几何不完整**：两包 `G-GEOM-PHYS` 都是 `partial`
   （一侧有 `payload.mesh`、缺 `appearance`，或反之）。
9. **本文件不产生性能数字**：所有"预期正/负"都是**待验证假设**，
   只有跑完并附母体簇区间与 `honesty` 块之后才能写入结论。

---

## 8. 合并"实验就绪"包的消融索引（`experiment_ready/training_package/ablation_index.json`）

`tools/a12_experiment_ready_export.py --step ablation` 把 §4 的实验组与
`docs/a12/fracture_visible.md` §7.2 的 A/B/C/D 四组，落到**一个包内、机器可读**的索引上。
每条给：`dimension`（维度）、`group_id`、`switch_field`（**开关字段名**）、`availability`
（`present` / `missing`）、`files`、`hypothesis`（可检验假设）、`positive_gain` / `negative_gain`
（正/负收益判定指标）、`evidence`（该维度的实测计数）、`unlock_condition`。
`missing` 的条目**必须**带 `unlock_condition`，由
`tests/a12/storage/test_experiment_ready_export.py` 钉住（缺了就 fail，不允许静默）。

| 组 id | 维度 | 开关字段名 | 当前 | 实测证据（包内 `research/*/index.json`） |
|---|---|---|---|---|
| `ABL_ROI_VIEWS` | `observations.roi_view_family` | `observations.roi_views.enabled` | **present** | 4 体 × (12 整片 + 12 ROI) = **96 视图**、48/48 族分布、2 121 947 876 B |
| `ABL_SYNTHETIC_EXTRAS` | `observations.synthetic_extras` | `extras.enable_<modality_id>` | **present** | 9 模态 / 18 实例；`rig_obtainable 0/9`、`claim_allowed 0/9` |
| `ABL_CONTEXT` | `context.excavation` | `context.enabled` | **present** | 2 个 `context_pack`（`simulated=true`）、queries 表 14 列中 1 列（`bag_id`）为声明的采集上下文 |
| `ABL_DEGRADE` | `degrade.axis_levels` | `degrade.axes.<axis_id>.level` | **present** | 注册 **31 轴** / 有物化档位 **9 轴** / 变体 **33** / 源 **3** |
| `ABL_FRACTURE_IFACE` | `fracture.interface_channels` | `fracture.interface_channels.enabled` | **present** | 71 碎片扫描 / 63 有断面 / **86 442 面** / **582 patch** / `<1 mm` Ra 恰好 0 的 patch **13** |
| `ABL_HARD_NEGATIVES` | `relations.hard_negatives` | `negative_mix.hard_negative_weight` | **missing** | 全仓 0 个 `hard_negatives*.parquet`；类别只在线产出（`hard_negative_limit` 默认 0） |

### 8.1 与 §4 的 E 编号对应

| §4 的组 | 本索引 | 关系 |
|---|---|---|
| `G-IMG-RGB` / `G-IMG-DEPTH` / `G-MASK-DEPLOY`（E01/E08/E15） | ——（基础包 `deploy/`，不在本索引里） | 本索引只列**可开关的合并维度**；基础包的部署通道由 §2.1 的组覆盖 |
| `G-CONTEXT`（E17，两个 full 包都 `missing`） | **`ABL_CONTEXT`** | 本包把它从 `missing` 变成 **present**：`data/a12_context/store` 真的落了 2 个 `context_pack`。E17 的"预期负收益 / 必须留反例"判定方式不变，但"可跑"列从**不可**变成**可加载** |
| `G-DEGRADE-*`（E16，包 B 里 I/G/P/X 四族 28 轴） | **`ABL_DEGRADE`** | 本包按**注册表**给 31 轴（不是按物化了多少），所以"缺的轴"是可读的而不是消失的；实际物化仍只有 9 轴 33 档 |
| `G-FRAC-ATTR` / `G-FRAC-IFACE-TRUTH`（E04/E06） | **`ABL_FRACTURE_IFACE`** | 本包把"断面在哪"从 `tag` 图推进到**逐 patch 的平面残差与分带幅度**，并给出可直接切的 `<1 mm Ra == 0` 总体 |
| 无对应（视图族/分辨率） | **`ABL_ROI_VIEWS`** | 对应 `fracture_visible.md` §7.2 的 A/B/C 三组：A=整片±ROI、B=ROI 方向数 0/3/4/6、C=`mm/px` 0.0730 vs 0.0365 |
| 无对应（负例类别） | **`ABL_HARD_NEGATIVES`** | 对应 `docs/a12/smallfixes_report.md` §S2 的开/关对照（已实测**无增益**，建议保持关闭）；本包只如实登记缺口 |

### 8.2 判正负收益的口径（沿用 §3 与 §5，不新造）

* **正收益**：`Hit@10` 增益 ≥3 个百分点且母体簇配对双侧 95% 下界 >0，**并且在退化、hard negative
  与真实微调后方向一致**（核心文档 §3.1）；干净集上的提升单独出现 ⇒ **记负结果**。
* **负收益**：`NOT_RUN` / `NOT_ESTABLISHED` / `NOT_APPLICABLE` 三态照旧（§3 表），**不得填 0**。
* **本索引新增的两条可证伪预测**（来自本轮实测，不是估计）：
  1. `ABL_ROI_VIEWS` 组 C 档（分辨率翻倍）：因为同一批断面里 **566/582** 个 patch 的
     `<1 mm` Ra 本来就 >0、而 **13/582** 恰好为 0，所以"提高分辨率"应当只在有起伏的那一族上
     有收益、在恰好为 0 的那一族上**收益为 0**。这是一条可以直接按谱系分层的预测。
  2. `ABL_FRACTURE_IFACE`：把 patch 按 `planar`（整块共面）与 `ra_below_1mm_mm == 0` 两个
     实测标签分层后，断面定位增益应当**只出现在 `ra_below_1mm_mm > 0` 的子总体**；
     若在恰好为 0 的子总体上同样出现增益，说明模型读的是"平面"而不是"断口"**（预期负结果）**。

### 8.3 复算命令

```powershell
cd C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab

# 组清单（包内索引，机器可读）
& .venv\Scripts\python.exe -c "import json;d=json.load(open('data/a12_exports/experiment_ready/training_package/ablation_index.json',encoding='utf-8'));print(json.dumps(d['counts'],ensure_ascii=False));[print(g['group_id'],g['availability'],g['switch_field']) for g in d['groups']]"

# 组可用性 + 缺失原因
& .venv\Scripts\python.exe -m pytest tests/a12/storage/test_experiment_ready_export.py -q   # exit 0

# 完整证据（视图分离 / 数据卡复算 / before-after）
& .venv\Scripts\python.exe tools\a12_experiment_ready_evidence.py
#   -> data/a12_reports/experiment_ready_evidence.{json,txt}
```
