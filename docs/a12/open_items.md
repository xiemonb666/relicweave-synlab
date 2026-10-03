# 状态补充（2026-10-03）

VF 当前 prototype 已窄验收 canonical STEP BRep face 分类、连续 rest-coordinate 四带绘制及几何-only 深度 parity；器身 C0 折角、接头真实度、材料/历史样式仍 `PENDING`。A12 生产 appearance 仍未全闭环（4 项 appearance 测试失败）；A12 adapter/camera32 为 `PASS`，但 per-face 近似仍漏掉窄红带。GPU 路径未实现，完整物理断裂链未完成。PG owner 报告 physics/time SHA 20/20 和 OSB/BB 独立 API fixture 的真实 CLI 验证通过，最终 wheel 检查进行中；jobs 修复 19 项测试通过，仍在审查中。A12 既有 ageing、capture 和 reconstruction 能力为部分实现，新 VF/PG 接入与真实效果综合验证待完成。

详细文件路径、数值证据和责任边界见 [实现 ledger](INFRA_IMPLEMENTATION_20261003.md) 与 [PG-Frag v12 decisions](PGFRAG_V12_DECISIONS_20261003.md)。下方内容保留原 2026-10-02 历史快照，不以本补充覆盖旧记录。

# A12 未完成项清单与在修追踪

**文档目的**：把"还没修好的东西"变成**可追踪、可验收、可复算**的清单，避免口头记忆。
**快照时间**：2026-10-02 17:0x（本地）。
**数据基线**：最新库 `data/a12_trainable/store`（463 资产）· 最新包 `data/a12_exports/negfix/next_experiment/training_package` · 旧代已归档 `data/_archive_pre_fix/`（36.3 GB）。
**相关文档**：`precision_audit.md`（精度实测）· `modality_census.md`（模态普查）· `rig_contract.md` + `configs/a12/capture_contract.json`（扫描台契约）· `decision_record.md`（18 项裁决）· `relation_negatives.md`（负例与 rank 首训）· `fracture_realism.md` / `fracture_calibration.md`（断口）· `training_run.md` / `export_guide.md`（训练与导出）。

---

## 进度更新（2026-10-02 傍晚快照）

### ✅ 本轮已完成（6 项，均有真实数字与退出码）

| 原项 | 结果 |
|---|---|
| **S4** `bag_id` 表列声明 | 真实包重扫 answer hits **1 → 0**；反例测试证明**只豁免 `bag_id` 一个名字**，其余 13 个 forbidden 名仍命中；`pytest tests/a12/storage/test_s1_s4_smallfixes.py` **exit 0（18 passed）** |
| **S6** 补数据卡 | `negfix` `--write-card`/`--check` **exit 0**；`full` 新增 `--write-card`（写 `DATASET_CARD.md`，不覆盖 `README.md`）+ 把**读者产物登记为 declared**（否则写卡会把 `--check` 从 0 变 3）；`full --check` **exit 0** |
| **S7** quality 样本量 | **根因不是标签缺失**：`loader_probe._observed_payload` 把质量写死 `zeros((1,1))`，而 OBS_EST **14 通道一直在 obs metadata 里** → `FeatureBundle.quality` 由 `(3,1,1)/valid=0` → **(3,1,14)/valid=42** |
| **S10** `u_position` 口径 | profile `max_travel_mm` **120 → 150**（契约 t052 nominal）；并纠正误解：`view_pos := T_WC[0,3]` 是**相机中心 X**，非行程（同 fragment/同工作距离下 x 摆 145.82 mm、y 168.38 mm、z 仅 14.86 mm） |
| **A（三角化）** | `cut.py::_Quadtree.cell_triangles` 统一：**16 组合面积全 1.000000**、零/负面积三角 0、栅格化并集面积全 1.000、每胞 `hist ⊆ {1,2}`；**平面逐位回归通过**（`sha256:ddf8191e…`）；坏边 **8 993 → 4 369（−51%）**，**"用 1 次"边彻底消失** |
| **C2（断口 ROI 特写）** | `synlab/observe/fracture_roi.py`（1581 行）：每断口 **3–6 方向**、遮挡射线实测算力规划、标 `CLOSEUP_DECLARED_NOT_CALIBRATED`；`imaging_fracture_roi.yaml` 默认关闭、`validate` exit 0；**补上全仓 0 生产者的 `px_per_mm`/`r_eff_mm`/`dof_cover_mm`**；实测 **mm/px 0.28041 → 0.07300（3.84×）**、**断面像素 335 038 → 20 987 921（62.6×）**、断面/物体 2.73% → **96.95%**；96 Blender 视图 609.45 s、峰值显存 1260 MiB；新测试 **24 passed exit 0** |

### ✅ 第二轮完成（小修批次 **11/11 全部收口**）

| 原项 | 结果（真实数字） |
|---|---|
| **S3 导出方向性** | 根因：merged 以规范无序键为 key 只发一个角色 → 改为按角色各出一行（`direction`/`pair_key`，两行标签相同=对称）；**行数 1794 → 3588**、**`effective_queries` 20 → 44（2.2×）** |
| **S5 `mask_semantics`** | **更正 Lead 前提**：463 资产中 **115 个已带 `coc_units_v2`**；真缺口是 **`visible_labels` 0/9** → 已加 `_stamp_data_semantics`（分母 327→336） |
| **S8 contradiction** | **更正 Lead 两处前提**：当前包 748 **全部可编码**；类别只有 **2 类 + 1 掩码**。真阻塞：**`synlab/**` 无任何代码写 `row["contradiction"]`**（`contradiction_source` 是死参数）→ CONTRADICTING **结构性不可达**；交付解锁条件 + 哨兵测试，**未伪造标签** |
| **S9 整包冒烟 OOM** | 精确复现 `19629342720 bytes = 19.63 GiB`；新增 `tools/a12_chunked_smoke.py`（同一 Trainer/loss + 梯度累加，归一化逐字一致）→ **3/3 步、峰值 4.69 GiB、18.3 s（内存 1/4.2）**；chunk 下限 8 片 |
| **S2 难负例隔离** | 四条约束全落地（`conformance` 四键 true）；**实测不能并进 `relations.parquet`**（D10 检查器：表外违反 3 → 并入后 **883**）→ 独立记录集交付；**开/关对照 3 步零增益、梯度 +40%、捷径探针 `discriminative_power=0.0`** → **Lead 裁决：默认关闭** |
| **S11 P03 漂移** | **零损伤对照的漂移与全流程逐位相同**（`0.35424330830574036`）⇒ 与损伤场无关；根因是**声明（窄带轴）与实际路由（全局体素 level-set）矛盾** → 按声明路由到已有窄带算子：**drift 0.35424 → 0.000348 mm（1018×）**、lost_volume 319.31 → **32.88**、**watertight False/43 边 → True/0 边**、audit `[]`；反证"就地 Newton 投影"不是修法（边界边 43→90） |

### 🔧 在修（当前重点是断裂）

| 项 | 负责 | 状态 |
|---|---|---|
| ~~装配器 T 型接头消解~~ | ~~`f5dc45a0`~~ | ⛔ **已按 R1 关闭（Lead 裁决：不再死磕旧算法）**。保留成果：`cut.py` 三角化统一（16 组合面积全 1.0、平面逐位回归通过、坏边 −51%、**单用边消失**）——已提交固化（`99058c0` 等）。**丢弃**：在飞的 T 型接头消解改动（已归档 `data/a12_reports/tjunction/cut_inflight_*.py` 后回退到 HEAD）。证据 90 文件留档 `data/a12_reports/tjunction/`。替代路径：SDF 隐式断口。**最终结论（关闭时的实测）**：T 型接头消解**本身达标**（装配器自审 `hanging_corner_points=0`、`edges_missing_a_hanging_point=0`、`ambiguous_directed_edges=0`），坏边 8993→4369→2616→**1623（−82%）**，并修掉两个真 bug（**环形遍历方向**导致共享边同向 → 重复侧壁；**中点复用**拿"坐标==索引"比较恒假 → 中点重复发出）；**但刀体仍不水密**（`hist=={"2"}` 未达标），且**每轮都换新根因**：T 型接头 → **轮廓顶点度直方图 {2:3967, 4:933, 6:629, 8:61}**（轮廓环在同顶点分叉，共形度应为 2）。**平面路径逐位回归全绿**（`sha256:ddf8191e…`；box20 平面与零振幅 rough 均 `sha256:07d5a59a…`、`hist {"2":25344}`、坏边 0、水密）。单元需求实测 **163 393 / 164 002 / 284 263 / 411 394**（平面 4096、0.63 s）。按 **R1（三次补丁仍不收敛 + 每轮新根因）正式关闭**；未产出形态学渲染（**不用平面图冒充**，如实留空）。**结论落档**：`fracture_realism.md` §11 + `physical_layer_wiring.md` |
| **断裂外观链**：法向→明暗通路（Lambert dDN 11–112）、面片抑制、材料驱动、釉层台阶、A/B 出图 | `211126ea` | 进行中 |

### ⛔ 新发现的阻塞（第二轮新增，N9–N13）

| # | 项 | 证据 | 解锁/处理 |
|---|---|---|---|
| N9 | **`roi_external_drift` 不进 `failure_codes`** | 全局 P03 漂移 **0.354 mm 仍报 PASS**；audit 把该指标写进 checks 却不进失败码 | **Lead 裁决：收紧并纳入 failure_codes**（版本化 QA 变更 + 重跑）；旧包按"修复前一代"标注（与 `_archive_pre_fix` 同口径），**不放宽判据** → ✅ **已完成（`a12.qa.v2`）**：翻转 **246 条记录 / 117 文件**（含旧代归档 131/57），登记表 `data/a12_reports/n9_qa_v2_flips.json`；窄带 0.000348 mm 仍 PASS。**未做**：QA 版本戳尚未进落库资产（`physical/api.py::commit_physical` 未接线，排队） |
| N10 | **S2 类别未进包，且 240 行无监督角色** | 并入即违反 D10（+880 违规）；240 行"query 无邻片"在当前类别体系下无角色 | Lead 已同意新增**辅助表 `research/hard_negatives.parquet`**（独立于 D10 主表 + 更新列语义表）；240 行待新的监督定义 |
| N11 | **P02/P04 共用窄带适配路径但未逐轴复测** | S11 只实测 P03 | 逐轴复测（同一根因） |
| N12 | **历史导出的 P03 几何未追溯修复** | `data/a12_exports/**` 为旧路径产出 | 重导出（或按"修复前一代"标注并归档） |
| N13 | **漂移指标只有"采样点最大值"；`choose_spacing` 的 node budget 覆盖请求值** | 无 p95/p99 版本；请求 0.95 mm 实得 1.14 mm | 补分位版本；节点预算改为显式可声明 |

### ⚠️ 既有顺序相关测试失败（与本轮改动无关）

`tests/a12/qc/test_data_quality.py::test_store_sqlite_is_opened_read_only`：单独跑 **0**、整文件 **1**、把该文件第一个测试与它配对可复现 → 机制线索为 `AssetStore._init_db` 未关连接 + WAL 持久化 ⇒ **GC 时机相关**（标为假设）；该文件只 import `qc.data_quality`/`storage.store`/`roles`，均不在改动集内。

### 🖼 断裂视觉现状（Lead 已亲自看图判读）

`data/a12_reports/physical_layer/samples/` 存有 ROI 近摄样本（1024 与 2048 档 + 深度图 + ID 图）。判读结论：**深度图均匀无浮雕**（断口几何是平面，与 `Ra=1.103e-07 mm` 一致）；RGB 里的**放射纹是三角拓扑扇形着色伪影**（非物理 hackle）；满屏均匀面片；轮廓为四叉树台阶 → **"看得见、看得清，但不像真实断裂"**。样本源为 `data/a12/reports/blender/_work/fracture_roi_*`。

### ⛔ 新发现的阻塞（本轮新增条目）

| # | 项 | 证据 | 解锁条件 |
|---|---|---|---|
| N1 | **`id_map` face_id 空间与 `corr_face_*` 面索引不一致** | `LIN0009` 的 `-m` 侧 `id_map` 有 **21 373 个标签**，超出该 mesh 的 **3 660** 个面；导致 correspondence **0/9 对两侧可定位**（对得上的一侧很干净：334/505 样本、深度残差 0.40–0.49 mm） | 改 `synlab/observe/**`（现被两条线占用，排在 `6ee59756` 之后）；已排除"一侧无观测"（18 谱系两侧都有观测） |
| N2 | **软件光栅器深度非透视正确** | 掠射断面三角中心像素 **24.47 mm** vs 光轴射线投射 **60.09 mm**（差 **35.6 mm**）；Blender 差中位 0.0029 mm、>1 mm 的 0 个 | 修 z 缓冲/透视插值；当前以独立射线投射为准并同时记录两者 |
| N3 | **`<1 mm` 断口形貌在平面切割线上是几何零** | campaign 3/4 具 9 个 ROI 实测 **Ra 恰好 0.000**（三角面共面）；仅 V02/M01（`a12_iface`）有真实亚毫米形貌（`below_1mm` Ra **0.0795 mm**） | 形态学接线 + 水密（`6ee59756`） |
| N4 | **混合层级 T 型接头** | 顶层三角化自身 **14 154 条单用边**，全部落在单一层级；`_across_finer` 只问同层级 | 装配器级消解（`6ee59756`）；三个 split 谓词变体已实测更差并回退 |
| N5 | **交付长边规格**（1024 px 下 0.2 mm 仅 2.74 px） | 反解需 **≥1495 px**；2048 档实测 **5.48 px** 已过门 | **Lead 已裁决**：新增 **≥1536 px** 契约档，保留 1024 px 为廉价档，并写显式门 `z_max=0.2/4×f_px` |
| N6 | **粗糙度只能靠"法向→明暗"进入 RGB** | Ra=0.02 mm 要 ≥4 px 需 `mm/px ≤0.005` → 1024 px 下 z ≤4.11 mm 或 L ≥14951 px（任何真实镜头都不成立）；Lambert 实测 dDN **11–112** 码值 | 不再堆分辨率，改为**接线形态学**（N3） |
| N7 | **5–10 cm 近摄无真实内参标定**；近摄物距**超声明 U 行程** | 仅渲染几何精确；每视图标 `CLOSEUP_DECLARED_NOT_CALIBRATED` | 需新相机档位 + 实拍标定（B 类） |
| N8 | **ROI 视图族尚未进导出包** | `data/a12_roi/store` 已有 4 obs_result × 24 视图（12 整片 + 12 ROI） | 改 `storage/export.py` 纳入（避开并发写者后执行）；消融组 `ABL_ROI_VIEWS` |

---

## 第一部分：正在修（14 项）

| 组 | 项 | 负责 | 硬指标（验收） |
|---|---|---|---|
| **A** | `cut.py` 逐胞三角化统一（12 分支中 **8 个面积错**：0.75 空洞 / 1.25 退化 / 1.75 重叠，应=1.0） | `426a6303` | 13 组合面积和==1.0；`edge_use_histogram=={"2"}`；坏边 0；**平面后端逐位回归**（同母体同 seed 体积/哈希/gap/守恒一致）；随后 rough 的 `realized_error` 与 **gap P95 < 0.02 mm**、形态学后端审计+共轭+`Ra`/`Rz` |
| **B** | 断口形态学**接线**（已完成，默认关闭；未开抛 `OPERATOR_NOT_REALIZED`，不静默降级） | `bf22c8a8`（已交） | 模型层证据已出（Ra 0.3924/0.3770 mm vs 平面 1.103e-07）；**落地仍 FAIL**（刀体水密即拒），等 A |
| **C1** | 物理层三情形实测（plane / M03 炻器 / M07 玻璃）+ **断口渲染出图** | `8f8eeae1` | 三情形 `Ra`/`Rz`/相关长度/脊线密度 + 共轭 P95 + 审计；PNG（正面 + 断口特写，≥1024）与逐条观察结论 |
| **C2** | **断口 ROI 特写**（契约要求 3–6 方向/断口）+ 分辨率反解 + 补 `px_per_mm`/`r_eff_mm` 生产者 | `f0821adc` | 反解"要看见 Ra 需多少 mm/px"；ROI 视图真渲染并记录 mm/px；与整片同 basis；可开关 |
| **S1** | correspondence 标签投到 **token 空间**（3587 行、`n_allowed=0`） | `a15d8a2c` | `correspondence n_allowed > 0`；投不上记 `valid=false` + 原因 |
| **S2** | 难负例类别隔离（mate-present **1120 行**） | `a15d8a2c` | 独立类别 `HARD_NEGATIVE_MATE_PRESENT`、`eligible_as_negative=false`、不进主指标分母、query 侧 mate-present；开/关对照真实数字 |
| **S3** | 导出表**方向性补全**（约一半 (query,candidate) 监督丢失；6 个 roster 片段不在关系表） | `a15d8a2c` | before/after 行数与 `effective_queries` 对比 |
| **S4** | 部署视图**表列声明**（`bag_id` → `evidence_class="capture_context"`） | `a15d8a2c` | `features_carry_answer_fields=false`，**且反例测试证明真值通道/`iface_*`/`corr_*`/`id_map`/`T_WC` 仍被命中** |
| **S5** | `mask_semantics` **落库**（三代 store 资产 meta 全 None） | `a15d8a2c` | 新资产 meta==`coc_units_v2`；给新旧代判定脚本 |
| **S6** | `negfix`/`full` 包**补数据卡** | `a15d8a2c` | `--write-card` + `--check` 退出码 |
| **S7** | quality 监督样本（现 3–5 条；loader 曾写死 `zeros((1,1))`） | `a15d8a2c` | OBS_EST 通道真进包并被 loader 读入；before/after `n_valid/n_allowed` |
| **S8** | contradiction 可编码对（`contradiction_valid=3`、`&allowed=0`、`classes_present=1`） | `a15d8a2c` | 用真实数据构造四类齐全集合，或明确写"当前无法产生"的解锁条件（不伪造） |
| **S9** | 整包 CPU 冒烟 **OOM（21.4 GB）** | `a15d8a2c` | 分块/采样让全包 CPU 跑通 3 步；记录峰值内存；采样报分母 |
| **S10** | `u_position` 口径冲突（profile `max_travel_mm=120` vs 实测 **127.12 mm**） | `a15d8a2c` | 按契约（U 导轨 150 mm）统一 + 越界检查 + 实测最大行程 |
| **S11** | P03 全局 SDF **提取漂移**（`roi_external_drift 0.2866 mm`；lost 276.58 vs 线性 43.5 mm³） | `a15d8a2c` | 证据链 + 最小修法，或定量误差模型 + 建议默认走窄带 |

---

## 第二部分：未开工（21 项）

### A 类：需要新算法或较多工作（9 项）

| # | 项 | 现状证据 | 影响 | 需要做什么 |
|---|---|---|---|---|
| 1 | **`warped_partition`（非平面共形分割）** | `PENDING`；gmsh 共形 PLC 能力已验证过 | 四必做后端缺 1；断口仍无法共形起伏 | gmsh 共形 PLC + 统一 warp；两侧共享分割面几何；过 A06 同级审计 |
| 2 | **成像分辨率看不见断口** | 渲染实测中位 **0.27193 mm/px**（契约 0.039–0.195）；0.2 mm 仅 **0.74 px**；4 px 可分辨=**1.088 mm**；0.195 档仅 **3.33 px/λ_min(0.65 mm)** < 合同 4 px | 即使断口做出形貌，**模型在图像里也看不见** | profile 加五档对齐契约；写显式门 `z_max=0.2/4×f_px`（63.97/35.03/11.68 mm）；补 `r_eff_mm` 生产者；断口近摄 |
| 3 | **22/31 退化轴无"声明→实测"配对** | 只有 36 档/9 轴有配对量；**G01 系统性偏大 8.14–13.06%**、**G08 最大相对误差 20.2%**、P08 L1 11.1% 被 PASS 掩盖 | 用这些轴做实验→**施加量≠声明量**，结论不可信 | 照 P02/P03/P04 模式补独立验证通道；G01 加实测 RMS 反解；G08 补 `measured_spurious_height_mm` |
| 4 | **花纹现实性 + PAT07/PAT08 继承 FAIL (A05)** | 连续性已达标（接缝 0.0、三维↔二维 0.0/255）；但装饰章法/真实釉色统计未做；A05 仍 FAIL | 整片描述子线索弱；验收项未过 | 按真实纹样规则做分区与连续性；修 P07/P08 继承检查（**不放宽判据**） |
| 5 | **材料缺瓦片/水晶/竹筒** | 现有 12 种（粗陶/细陶/炻器/瓷/彩绘瓷/施釉陶/玻璃/石×2/石膏/木/金属） | 覆盖不足 | 各自需要：**一个器型族 + 一套物理量 + 一种断裂模式**（瓦=薄板；水晶=IOR/色散/解理脆断；竹=各向异性纤维 + 中空管 + 纵向劈裂） |
| 6 | **玻璃/水晶的透射折射渲染未验证** | M07 `transmission=0.82` 有字段；渲染路径未验证折射 | 玻璃类外观不真 | Blender Cycles 透射 BSDF + IOR/色散；软件光栅不支持→明确回落策略 |
| 7 | **L1/L2 简化网格未物化** | `display_lod_glb` 仅 demo 库 118 件；主库 0 件；`fast_simplification` 依赖反复 | 多尺度展示/训练缺 | 让 LOD 生成进入生成链并落库；或删除该展示承诺 |
| 8 | **Blender GPU 未达 3×** | 端到端最好 2.14×（等负载仅 1.02×）；瓶颈：render 42.7% + worker 非渲染 31.5% + **进程启动 22.2%**；均值下 `CUDA≈2.9×/OptiX≈1.8×`（单次 render） | 合成速度 | ①**每进程批量渲多视图**（省 12 次启动 + CUDA init）②按 pass 分派设备（实测 2.13×）③显式选 CUDA（实测 OptiX 更慢） |
| 9 | **UI 合成向导（U14）未交付** | `36703cde` 阵亡；现有 12 页 + U13 展示页可用 | 操作效率（批量合成/预览/断裂/退化预览） | 六步向导 + 真实单谱系预览 + 批量面板 + 覆盖矩阵；只用真实端点，缺能力显示错误码 |

### B 类：本机不可完成（8 项）

| # | 项 | 现状证据 | 解锁条件 |
|---|---|---|---|
| 10 | **真实实拍数据 + 真实标定** | `calibration_id`/`rig_calibration_rev`/`intrinsics_profile_id`/`scale_drift`/`r_eff_mm` 在 894+30+167+463 资产里**各 0 命中**；`f` 三支并存（3.125/3.6/2.77） | 需实拍标定板在 10/15/20/25 cm 实测（RMS ≤0.2 px、3 次 `fx` 散度 ≤0.2%、主点 ≤0.5 px） |
| 11 | **稠密 MVS** | pycolmap 3.11.1 **无 `patch_match_stereo` 符号**、`has_cuda=False`、无独立 colmap 二进制 → `MVS_NOT_AVAILABLE`；稀疏 12/12 注册、重投影 0.4543 px | 需带 CUDA 的 colmap/pycolmap 构建 |
| 12 | **主仓集成（A3/A4 schema）** | 无主仓 → `MAIN_REPO_INTEGRATION_PENDING` | 需主仓与契约 |
| 13 | **`fracture_modes` 后端** | **全仓无源码**；计划仅一行"选配/依赖许可"；MSVC 需提权（`winget` exit **1602**；CMake 用户级可装、LLVM 用户级无安装器） | ①给出库身份/仓库与许可证 ②管理员终端装 VS BuildTools（或改用免管理的 MinGW/MSYS2 便携链） |
| 14 | **L2/L3 规模** | L0 100% · L1 ≈15% · L2/L3 0%；本机杀长重负载进程 | 机时（480 母体 / 1–10 万片） |
| 15 | **真实迁移结论（T0–T3）** | 需真实数据 + 算力 | 实拍数据到位 |
| 16 | **独立母体 ≥20** | 当前 **1**（vs 要求 20） | 真实器型库/更多母体 |
| 17 | **A05/A06/A24 中依赖真实数据的部分** | A05 花纹继承、A06 守恒、A24 来源依赖 | 部分随实拍/后端解锁 |

### C 类：验收与发布收口（4 项）

| # | 项 | 现状证据 | 需要做什么 |
|---|---|---|---|
| 18 | **验收计数** | **PASS 13 / FAIL 4 / PENDING 6 / NOT_RUN 6 / NA 7**（A09 已由队友修成 PASS，`FAIL[3 codes]→PASS[]`，待重跑确认） | 重跑 `synlab acceptance`，逐项归类 FAIL/PENDING/NOT_RUN 原因 |
| 19 | **PILOT 12 门只过 10** | 差 `train_dev_lineage`（单 run 单 split）与 `leakage_audit`（A32 当前 NA） | 多 split 归属 + A32 真跑 |
| 20 | **12 个旧 release 未发新版** | 全部含 V01/V02 → 受几何修复影响；旧 manifest 未改写 | 标 `superseded` + 发新 `rel_*`（不改写旧 manifest） |
| 21 | **基线需重算** | `_baseline_acceptance.json`（UTF-16）与 `reports/_baseline/*` 是改前快照 | 几何修复后重算基线并标注"改前/改后" |

---

## 第三部分：已知小项（未成条目但需记账）

| 项 | 证据 | 处理建议 |
|---|---|---|
| 1 片输入抛**非结构化 `IndexError`** | `build_partition`（`min_pieces=2`） | 改为结构化 `SynLabError` |
| 高片数区仍有**不闭合胞** | V01 12 胞中 2 个；根因 `voronoi_frag.cell_hull_facets` 相邻面裁剪 | 按共享平面标签重做裁剪 |
| **接受率 0.8125** | 其余拒绝为 gap/法向超预算（V01 4 片 gap 0.1235 mm / 105.5°） | 记录分母 + 定向调参 |
| **α 不可分离** | 未触底点仅 3 个片数档 | 增加片数档以分离 |
| `nearest_surface_p95` **无冻结阈值** | 最差 0.247 mm | 冻结阈值或标为辅助量 |
| V13 **8 m 落高不可交付** | 实测拒绝 | 记录可交付范围 |
| V13 **壁厚对采样面数敏感** | 全采样 27.2 mm vs 等距 400 面 11.7 mm | 把采样参数写进事件 meta |
| 平面 `correlation_length` **无意义** | 返回 5.68/8.0 mm 噪声值 | signal_var 低于地板时返回 None |
| 形态学**振幅/坡度偏大** | σ_r0 0.41 mm vs λ_min 0.65 mm → 坡度 P95 **53°**（真实陶瓷几度~20°） | 加坡度合理性约束（已并入 `426a6303`） |
| `FractureConfig.backend` **Literal 未含形态学后端** | `synlab/schemas/spec.py:148` | 加入并记录（已并入 `426a6303`） |
| `capabilities` 端点在当前 server 变体返回 0 | 前端显示"未知"回退 | 对齐路由或前端标注 |

---

## 断裂外观层：实测结论与 Lead 裁决（记录，2026-10-02 晚）

**已交付**：`synlab/observe/fracture_appearance.py`（2.4k 行）· `configs/a12/imaging_fracture_appearance.yaml`（默认关闭，`validate` exit 0）· `docs/a12/fracture_appearance.md` · 图与表在 `data/a12_reports/physical_layer/` · 新测试 **21 passed exit 0**。

**法向通路（已证明）**：`render_appearance_view()` 用 `fracture.morphology.MorphologyHeightField` 的**解析梯度**做逐像素法线扰动，几何不动、逐视图记录几何哈希；与冻结 rasteriser 在 `FLAT/no-relief/FROZEN` 下 rgb/id/tag/depth **逐位相同**；夹取等价性到 **1e-12**。修掉真 bug：`render.py` 的 `world_normals` 实为**相机系**，扰动须在世界系（早期偏差 1.6%）。

**dDN 实测（8 档 mm/px，V02/M01 受光断口）**：Ra=0.02/0.08/0.4 mm → dDN rms **6.0 / 24.6 / 85.6**；**0.0365→0.2719 mm/px（7.4×）内变化 <2%** ⇒ **"法向通路与横向像素无关"已被实测确认**。

**材料差异（同一断口几何）**：M01 粗陶 41.6 · **M04 白瓷 61.6** · M07 玻璃 13.8 · M06 施釉陶 55.4 · M11 木质 55.3（颗粒像素 6/2/2/6/64）。反直觉但正确：**M04 的 Ra 小 17 倍却更"响"**（λ_min 0.2 vs 0.65 → 斜率主导）。非随机证据：PSD 斜率 **−3.199**、1/e 自相关 5.45 mm。

### 裁决 A1 · 背光断口（冻结光照下法向通路恒等于零）

实测：4 具中只有 V02/M01(+0.783)、V23/M07(+0.73) 的断口被照亮；V10/M11(**−0.796**)、V21/M06(+0.19) 基本无光 → **99.94% 像素被夹 0**，Ra=0.4 mm 也只给 dDN 8.25。
**裁决**：**不发明新光源**。近摄视图**从契约已有的 5 种灯态（`WHITE_DIFFUSE`/`LEFT_GRAZE`/`RIGHT_GRAZE`/`CROSS_POL`/`NORMAL_REFLECT`）中按断口法向择优选一**，并把**所选灯态写入视图元数据** → 台架可复现，不是"为合成调光"。

### 裁决 A2 · 出厂成像链泊松噪声淹没信号

实测：`effective_gain=1` → 噪声 **100.63** vs Ra=0.08 信号 **24.69**（SNR<0.25，交付图退化为 0/255 二值噪声）。
**裁决**：**这是默认档 bug，不是物理极限**。默认 profile 必须让 **Ra=0.08 的 SNR ≥ 10**，**逐档报告实测 SNR**；**禁止**用降噪后处理掩盖。

### 裁决 A3 · 面片来源与网格密度

实测：平滑法线让法向阶跃 4.50→2.53 DN，但**交付图 84% 的阶跃来自 `render.procedural_albedo` 的逐面色块**；λ_min 反解需 **L=0.0813 mm / 26 202 面每 mm²**（a12_iface 差 ~50×，plane 线差 **~10⁵×**）。
**裁决**：**几何不追 λ_min**（10⁵× 不可行且物理上不对），分两层：
- **几何层**只表达**粗尺度**（>0.25 mm 或 >1 mm 起伏，即 SDF 薄片的职责）；
- **亚网格尺度走明暗**（法向通路已实测有效且与分辨率无关）；
- **必须修 `procedural_albedo` 的逐面色块** → 改连续/带限纹理（进 `observe` 工单）。

### 裁决 A4 · 釉层几何与数字更正

实测：交付断口资产**只有 `origin_kind` + `interface_id`**，**无层/釉通道 → 台阶今天不存在于几何里**；审计釉层阻尼带已渲染（带宽 0.44 mm = 6.0 px，ON/OFF dDN rms 10.09，6.1% 像素）。
**数字更正**：`build_layer_shell(V01, L01)` 真实厚度 = **0.743 / 1.188 / 1.634 mm**；本文件与旧简报引用的 **0.469/0.879/1.173 mm 复现不出来**（只存在于 `mothers_materials.md` 正文与 `degrade/specs.py` 冻结常量，其生成脚本在树里和历史里都不存在）——**以 0.743/1.188/1.634 为准**。
**裁决**：**釉层台阶的立体感需要生成侧把 L01/L03 几何层切进碎片** → 加入 SDF/断裂工单。

### 仍未解决（外观层）

① 断口几何仍平（本层只证明"通路就绪、待几何供给"）② 预测 vs 实测差 **1.9×** 未定位 ③ 泊松噪声默认档（A2）④ 釉层台阶需生成侧供几何（A4）⑤ **Blender Cycles 交叉验证未做**（worker 不接受法线/凹凸输入；该分辨率下几何位移需 ~10⁵ 倍面数）⑥ `procedural_albedo` 逐面色块（A3，已进工单）。

## 复算入口

```powershell
$py = ".venv\Scripts\python.exe"
& $py tools\load_package.py --package data\a12_exports\negfix\next_experiment\training_package
& $py tools\check_data_quality.py --store data\a12_trainable\store      # 0=可训练 / 3=不可训练
& $py -m synlab.cli acceptance --profile SANDBOX_CORE --json
& $py data\a12\reports\precision_audit.json  # 见 precision_audit.md 的探针清单
```

**跟踪纪律**：在修项完成后，其行应从第一部分移到"已完成"，并在对应专项文档留 before/after 实测；未开工项开工时补上"负责 + 硬指标"两列。
