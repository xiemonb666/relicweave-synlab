# V1.44 扫描台采集契约与「扫描台模态 × 合成覆盖」对照矩阵

> **性质**：只读固化 + 对照，**不新增文档要求**。
> **权威输入**：`RelicWeave_V1.44_Optimized_Complete_Plan.docx` 的深读产物 `docs/a12/v144_project_core.md`（1122 行 / 12 章）、
> 本仓模态普查 `docs/a12/modality_census.md`、以及证据目录 `data/a12/reports/`。
> **机器可读副本**：`configs/a12/capture_contract.json`（19 个顶层段、**108** 个 `spec` 字段、**133** 处 `source` 指针）。
> **source 指针约定**：`T###/p####` = docx body 顺序第 ### 个表格 / 第 #### 个段落（1 基；全文档 **128 表 / 1807 段 / 357 标题**，
> 见 `data/a12/reports/docx_structural_check.json`）。本文件与 `data/a12/reports/tables/t001-t128.md` 使用同一编号。
> **诚实规则**：每个数字都给指针；文档未明确的一律写 `unspecified` 并给**兜底假设**（显式标注"这是我们的假设"）；
> 文档明写"拿不到"的项在 §8 单列，合成侧不得声称拥有。

---

## 0. 标注约定

| 标记 | 含义 |
|---|---|
| `【文档】` | 文档明写，可直接作为要求引用 |
| `【文档·候选】` | 文档明写，但自我标注为候选／起点／非冻结门，须实测后冻结 |
| `【文档·不承诺】` | 文档明写"拿不到"或"不承诺" |
| `【未明确】` | 文档未给值；后续给出的是**我们的兜底假设** |
| `【工程约定】` | 本契约为了可执行性补的字段命名／映射，**不是**文档原文 |

---

## 1. 相机（C3 / C3.1 / C3.2）

| 项 | 值 | 标记 | source |
|---|---|---|---|
| 开发板 | Luckfox Pico RV1103 | 【文档】 | `p0504` |
| 相机模组 | SC3336 B（SC3336B）；官方页 `https://wiki.luckfox.com/SC3336-3MP-Camera/` | 【文档】 | `p0504` / `p0607` |
| 输出分辨率（标称） | 2304 × 1296 | 【文档】 | `p0504` |
| 对焦 | 手动对焦（manual focus） | 【文档】 | `p0504` / `p0607` |
| 快门 | 滚动快门（rolling shutter） | 【文档】 | `p0504` |
| 水平视场 | 约 84° | 【文档】 | `p0504` |
| 像素数的含义 | "约 300 万像素仅说明采样数量，不保证断口实际分辨率" | 【文档】 | `p0504` |
| 采图适配器必须验证 | 实际输出 2304×1296 或当前真实分辨率、支持的曝光／增益／白平衡／对焦模式、原图字节与时间；**不能**把 3MP 传感器默认 1080p 视频截图写成 3MP 原图 | 【文档】 | `p0509` |
| A 节点角色 | 细节节点，轻量升降滑架；断口边缘、凹槽和局部疑点；手动对焦，自动动作限于清晰工作范围 | 【文档】 | `t050` |
| B 节点角色 | 概览节点，固定斜上方约 30–45°；整片、纹饰、样品定位和补充角度 | 【文档】 | `t050` |
| 硬同步双目 | **不宣称**（两路依次拍摄） | 【文档·不承诺】 | `t050` |
| 镜头型号／焦距 | `spec: unspecified` | 【未明确】 | 见 §9.1 |

---

## 2. 工作距离与实际分辨率（C3.1 / C3.2 / C10.1）

**验收距离**【文档】`p0511`：从 **10 / 15 / 20 / 25 cm** 测起；机械安全且能对焦时再测 **5–10 cm 局部近摄**。
不假定最近位置可用；逐距离检查焦点、中心／边缘及不同深度。光学工作距离须**注明测法**，镜头前沿与样品**净空另记**。

**理想针孔公式**【文档】`p0518`：`d_ideal = a × N_x / [2 p × tan(FOV_h/2)]`，只生成距离候选，再受焦点、景深、覆盖、净空与质量约束。

**分辨率表**【文档】`t051`（按 84° 视场与 2304 横像素的理想针孔计算；近摄与畸变须实测）：

| 距离例子 | 理想水平覆盖 mm | mm/px | 0.2mm 结构像素数 |
|---|---|---|---|
| 50 mm | 90.0 | **0.039** | 5.12 |
| 100 mm | 180.1 | **0.078** | 2.56 |
| 150 mm | 270.1 | **0.117** | 1.71 |
| 200 mm | 360.2 | **0.156** | 1.28 |
| 250 mm | 450.2 | **0.195** | 1.02 |

**采样目标**【文档】`p0517`：
- **0.2 mm 结构 ≥ 4 px** = **pilot 采样起点**（不是识别定理）；
- **6–8 px** = **细节候选目标**；
- 明确**不是** 0.2 mm 测量精度承诺；真实最小结构由样片和误差干预确定。

**必须分开报告**【文档】`p0515`：采样 `px_per_mm`、可辨结构尺寸 `r_eff_mm`、毫米测量误差、检索收益。
**辅助算术情景**【文档】`p0512`：覆盖 100 mm 时 0.043 mm/px 只是算术情景。

**分辨率工作档**【文档】`p0579`/`p0580`：提供 **GLOBAL / MID / LOCAL** 实测档，动作只选**档位 ID**。
`resolution_profile` 含 camera、镜头、输出分辨率、`focus_setting`、U 距离区间、Z／俯仰／装夹、灯态、实测 `px_per_mm`、`r_eff_mm`、有效 ROI、景深覆盖、曝光、`calibration_rev`、QA。
固定焦点 U 移动更新外参；镜头或焦点变化验证／更新内参；位置无可信测量则标估计，不用于精确物理残差。

**景深数值**：`spec: unspecified`（见 §9.3）。

---

## 3. 灯光（C5 / C5.1）

| 项 | 值 | 标记 | source |
|---|---|---|---|
| 灯组 | 四组**同色温白光**灯位于**左、右、前上方、后上方**，单独开关或调光 | 【文档】 | `p0535` |
| 选型规则 | 先选低压同批白光，**标称 CRI ≥ 90 作为候选**，实际用色卡及样片检查 | 【文档·候选】 | `p0535` |
| 灯控 | 额定电流足够且 3.3V 输入能可靠导通的 MOS 模块；GPIO 只发控制信号 | 【文档】 | `p0535` |
| 色温 K 值 | `spec: unspecified` | 【未明确】 | 见 §9.5 |

**实拍灯态 5 枚举**【文档】`t053`：

| 模式 | 灯组与偏振 | 用途 |
|---|---|---|
| `WHITE_DIFFUSE` | 多灯均匀白光，灯前偏振可移开 | 轮廓、颜色和基础纹饰 |
| `LEFT_GRAZE` | 左侧低角度灯 | 断口起伏和裂纹 |
| `RIGHT_GRAZE` | 右侧低角度灯 | 验证另一方向纹理与阴影 |
| `CROSS_POL` | 灯前与镜头前偏振轴交叉调整 | 降低部分釉面高光 |
| `NORMAL_REFLECT` | 普通白光观察 | 保留光泽等材质证据 |

**灯态分组规则**【文档】`p0543`：2D 可切掠光／普通光／交叉偏振补充信息。**MVS 子组保持已验证的灯态、曝光与焦点，保存 `camera_group_id`**；切灯或改焦点**分组重建**并明确内参共享资格；新增帧须有有效覆盖／基线，素面或反光失败仍保留全分母。

**偏振**：`polarizer_auto = false`【文档】`p0577`——手动偏振不冒充自动；无角传感器的**实测角为 null**【文档】`t044`。

**光度立体法向**：文档只写"MVS 低频深度 + **可选** Photometric Stereo 法向／normal-guided refinement"【文档·候选】`t096`——**不是采集台保证能力**。

---

## 4. 机械（C4 / C4.1 / C4.2 / H4）

| 项 | 值 | 标记 | source |
|---|---|---|---|
| 外形起点 | 约 **450 × 350 × 450 mm**，按实测视场、近远行程与净空修订 | 【文档·候选】 | `p0520` |
| 旋转轴 | 低压双极步进＋同步带或联轴器，独立承载轴承；负载、偏心、跳动和回差实测 | 【文档】 | `t052` |
| Z 升降 | 完整丝杆导轨模组，**有效行程 150–200 mm**；导轨承受侧向力（不只买丝杆） | 【文档】 | `t052` |
| U 近远轴 | **基础必配手动光轴导轨，约 150 mm，预留 100–200 mm 适配**；丝杆、刻度、锁紧、止挡；焦点与净空验收 | 【文档】 | `t052` |
| U 轴移动对象 | **整相机模组及镜头一起移动** | 【文档】 | `p0005` |
| 俯仰 | 基础版锁紧支架；升级位置舵机＋支撑轴承；转轴靠近相机重心 | 【文档】 | `t052` |
| 左右 | 横梁长孔或手动滑移，固定后登记；**不作为基础版自动能力** | 【文档】 | `t052` |
| 样品托架 | 软垫三点托架，可更换；不压断口，不遮主要观察面 | 【文档】 | `t052` |
| 相机前沿净空 | **20 mm**；仅是**候选守卫**，按实物尺度冻结；**与光学工作距离分字段** | 【文档·候选】 | `p0531` |
| P95 位置误差 | **0.5 mm**；**仅候选**，按景深与密度收紧 | 【文档·候选】 | `p0533` |
| H4 复述 | 150 mm 行程、20 mm 净空、0.5 mm 重复误差、0.2 mm 示例结构**是测试候选，按实物和任务冻结，不写成已测** | 【文档·候选】 | `p1796` |
| 回零测试 | 每点 10 次进退回零；测刻度、画面漂移、清晰度及耗时 | 【文档】 | `p0533` |
| 无编码器 | 开环估计；回报 `commanded_position` 及 `position_estimated=true`，**不伪称实测位置** | 【文档】 | `p0533` / `p0563` |
| 命令单位 | 绝对位置；通信可用旋转毫度＋直线微米整数；内部步数映射保存取整余量 | 【文档】 | `p0563` |
| 标定版本联动 | **移动支架或装夹更新 `rig_calibration_rev`** | 【文档】 | `p0531` |
| 无限连续旋转 | **不可**（不边转边拍；Global 3D 不采用单圈 360°） | 【文档·不承诺】 | `p0432` / `p1156` |

**预算**【文档】`t054` / `t055` / `p0005` / `p0495` / `p0550`：

| 档 | 额度 | 语义 |
|---|---|---|
| 基础 | **1195 元** | 旋转 Z 自动 ＋ **必配手动 U** |
| 双节点 | **1435 元** | 第二固定概览节点（+240） |
| 增强 | **1800 元** | 含 U 电动化（+150，累计 1585）、自动俯仰（+100，累计 1685）、余量（+115） |
| **硬上限** | **2000 元** | 采购硬上限 |

均为**工程额度，不是商家报价**；规格与价格须核实，须含运费、工具、加工与返工。
**超额延期优先序**【文档】`p0547`：先延期第二节点、自动俯仰或 U 电机，保留单节点旋转 Z 自动＋U 手动细调；**限位、防坠、线束保护和清晰度资格不删**。

---

## 5. 图像与元数据（B6 / D3）

**capture 记录最少字段**【文档】`t044`：
`capture_id、session_id、fragment_id、surface_id、path、sha256、device_id、calibration_id、quality_tier、timestamp`（整片 `surface_id` 可 null）

**capture 扩展字段**【文档】`t044`（9 个）：
`width、height、exposure_s、iso、focus_mode、light_mode、polarizer_state、angle_cmd_deg、angle_measured_deg`
约束：**无角传感器的实测角为 null**。

**标定字段**：

| 字段 | 内容 | 标记 | source |
|---|---|---|---|
| 内参 | `fx / fy / cx / cy` + **畸变参数** | 【文档】 | `p1163` |
| 逐稳定工况 | 每一种稳定**镜头／分辨率／对焦距离**工况都要保存独立相机标定；同一工况可共享或强约束内参，但焦距、镜头或近摄距离明显变化时**禁止盲目共享** | 【文档】 | `p1163` |
| `intrinsics_profile_id` | 存在；`rig_service` 把 ActionProposal 映射到已验收的 `intrinsics_profile_id` | 【文档】 | `p0574` / `p0638` |
| `rig_calibration_rev` | 存在；移动支架或装夹即更新 | 【文档】 | `p0531` |
| `calibration_id` | 物理更换镜头／焦段／近摄附件**产生新的 `calibration_id`**；相机参数变化新建工况和标定 ID | 【文档】 | `p0427` / `t045` |
| `px_per_mm` | **实测**（非标称）；`resolution_profile` 必含实测 `px_per_mm` 与 `r_eff_mm` | 【文档】 | `p0579` / `p0515` |
| `working_distance_mm` | 光学工作距离须注明测法 | 【文档】 | `p0511` |
| U 三类位置 | **命令位置、估计位置和实测位置分别记录**；无编码器则实测字段 null | 【文档】 | `p0591` / `p0577` |
| `focus_setting_id` | 存在；capabilities 含 `focus_settings` | 【文档】 | `p0577` / `p0638` |
| `clearance_mm` | 20（候选）；与光学工作距离**分字段** | 【文档·候选】 | `p0531` |
| 尺度基准 | 每次正式采集必须含**可追溯尺度基准**（高精度标尺／AprilTag／ArUco／coded target／标定板），并在重建后**自动检查绝对尺度漂移** | 【文档】 | `p1163` |
| 尺度漂移指标 | 已知标尺／marker 尺寸与重建尺寸偏差；**每次采集必报** | 【文档】 | `t097` |
| 全局 vs 局部内参 | 若近摄导致明显 focus breathing，应把 Global 与 Fracture 近摄视为**两套独立标定工况** | 【文档·候选】 | `p1155` |

> 【工程约定】`u_cmd_mm / u_scale_read_mm / u_encoder_mm` 是本契约对 `p0563` + `p0577` + `p0591` 三处口径的**合并命名**；
> 文档原文只说 commanded / estimated / 实测位置与"刻度读数来源"并存，**未给这三个确切字段名**。

---

## 6. 采集清单（B3 / B4.2 / B6 / C15 与 3D 强化专项）

| 采集项 | 要求 | 数量／精度 | 标记 | source |
|---|---|---|---|---|
| 整片 2D | 正面、反面、侧壁、轮廓及断口概览 | 名目明写；**6–10 张**为【工程约定】计数映射 | 【文档】+【工程约定】 | `t042` / `p0429`–`p0431` |
| 断口局部 2D | 逐真实断口多角度近摄；实际断裂表面、两侧壁、厚度变化、边缘 | **3–6 个有效方向／断口**为【工程约定】补齐目标（文档只说"多角度"） | 【文档】+【工程约定】 | `t042` / `p0431` / `p0881` |
| 身份审计照 + 标尺 | 核对 `fragment_id` 并拍身份审计照；ID 卡、标尺、标定板 | **1 组／片** | 【文档】 | `p0429` / `t040` |
| 质量配对 | 同片清晰／日常／差质量真实观察 | 三档；**每档 ≥ 2 会话**为【工程约定】；禁止用压缩副本代替独立实拍 | 【文档】+【工程约定】 | `t042` / `p0880` / `p1170` |
| 重复会话 | 重新装夹后的身份、时间和参数；新 session，不沿用旧位姿 | — | 【文档】 | `t042` |
| **Global 3D** | **约 120–240 张／片；3–4 层环绕；75–85% 重叠** | 候选起始范围（**非冻结门**） | 【文档·候选】 | `t095` / `p1156` |
| **Fracture-local 3D** | **约 60–150 张／断口；小半球多倾角覆盖**；多方位角 + 约 **±10°/±20°/±30°/±40°** 倾角 | 数量**不是硬门**，由 coverage、repeat error、下游 registration 增益决定 | 【文档·候选】 | `t095` / `p1157` |
| 点云 | **整片 2048–8192 点** + **断口 ROI 独立 2048–8192 点**，各一份 | 记录**实际有效点数**；不足时 `valid mask` 与点权重保持真实，不重复填点伪装有效密度 | 【文档】 | `p1496` |
| MVS 子集 | 约 **20 母体 / 400 片 / 每片 30–120 重叠帧**；分层：素面、釉面、薄片、近摄、支撑遮挡 | **全部尝试入分母**；不把 12 帧训练预算当 MVS 保证；固定灯态曝光焦点，改焦点分相机组 | 【文档】 | `p1500` / `p0473` |
| 重复扫描 QC | 同片／同断口**至少 3 次**独立采集与重建（**最好重新装夹**），刚性 registration 对齐后比较几何 | ≥3 次 | 【文档】 | `p1170` |
| 采集 SOP 8 步 | 见 `configs/a12/capture_contract.json` → `capture_checklist.sop_order` | — | 【文档】 | `p0429`–`p0436` |
| 自动翻面 | **无** | — | 【文档·不承诺】 | `p0434` / `t045` |

**单件采集时间**：`spec: unspecified`（见 §9.6）——文档要求测"每片采集/计算时间"、动作时间、P95 时延，但**未给数值门**。

---

## 7. 掩码 / 质量 / 账本

### 7.1 区域 mask

- **片体和区域分割 mask**：整数 ID；区域含 **内外壁 / 断面 / 支撑 / 无效区**【文档】`t101(D09)`。
- **无损**：整数 ID **无有损压缩**；ROI 优先坐标按需 crop【文档】`t117`。
- **渲染规则**：优先使用**无阴影、无色彩管理和无抗锯齿混色**的整数 ID 通道或独立标签渲染；**检查 PNG 中 ID 严格可恢复**；Cryptomatte 可作替换但先验收边界像素【文档】`p1481`。
- **缺视图**：用 `presence`；**不塞一张零图假装已拍摄**【文档】`t104`。

### 7.2 8 项质量向量

**建议从单一 `q∈[0,1]` 提升为特征级可靠性向量**【文档】`p0236`：

| # | 分量 | 说明 |
|---|---|---|
| 1 | `blur` | 模糊 |
| 2 | `exposure` | 曝光 |
| 3 | `coverage` | 覆盖 |
| 4 | `occlusion` | 遮挡 |
| 5 | `reconstruction_confidence` | 重建置信度 |
| 6 | `point_density` | 点密度 |
| 7 | `normal_stability` | 法向稳定性 |
| 8 | `curvature_stability` | 曲率稳定性 |

> 质量头**只描述"这份证据有多可用"**，不得直接借 R2 标签把"邻接"偷换成"清晰"【文档】`p0236`。
> 存储：每视图和每区域命名的 `float32` 向量；**每项附 `valid` 及来源为 `OBS_EST` 或 `GT_ORACLE`**【文档】`t104`。
> 权限：**质量标签与邻接标签分离**；可观察质量输入 + 独立 oracle 诊断，字段权限分离【文档】`t032` / `t101(D16)`。

另有一份 **14 维退化向量 D**【文档】`p0365`：`[fracture_smoothing, edge_rounding, fracture_missing, texture_loss, blur, glare, exposure, view_coverage, point_dropout, mesh_holes, depth_noise, normal_noise, curvature_noise, calibration_error]`。
每个分量保留**物理或数值单位、随机种子和操作顺序**；"不要只存一个 `quality=0.7`"。

### 7.3 Q1 / Q2 / Q3 验收

| 级别 | 要求 | source |
|---|---|---|
| **Q1 现场验收** | 照片解码、身份对应、关键断口可见、明显失焦高光不过关 | `p0464` |
| **Q2 当日入库** | 图与 mask、ID 引用、哈希、关系对称、单位和版本一致 | `p0464` |
| **Q3 研究验收** | split 隔离、关系完整性、确认封存和指标分母可追溯 | `p0464` |

### 7.4 3D 质量下限（"Q2 当量"）

| 项 | 值 | 标记 |
|---|---|---|
| 有效点比例 | **≥ 50%** | 【工程约定·假设】 |
| σ（局部/深度残差） | **≤ 0.2 mm** | 【工程约定·假设】 |
| 孔洞 | **≤ 2 个，r ≤ 3 mm** | 【工程约定·假设】 |

> **这组阈值文档没有明写**。文档给出的相邻口径是：G16 轴分层（`G01` 深度误差 RMS 0–1mm 分层、`G02` 点云 8192→512、`G03` 局部覆盖 100→20%）【文档】`t109`；
> Fracture-local 必报"局部 surface repeat error、normal repeatability、coverage、边界误差、真实邻片闭合残差"【文档】`t093`；
> 每次采集必报 **Scale drift** 与 **Coverage/confidence**（区分"没看到"与"确实没有结构"）【文档】`t097`。
> → **≥50% / σ≤0.2mm / ≤2 个 r≤3mm 孔洞 是本契约提出的 Q2 当量下限，属补齐方案，不是文档明写的门。**

### 7.5 账本 11 类与完整数据链

**11 类**【文档】`t044`（该表共 12 行 = 表头 + 11 条目：10 个文件 + `capture` 扩展）：

| # | 文件 | 最少字段 | 约束 |
|---|---|---|---|
| 1 | `objects.csv` | object_id、family_id、material、source、permission_id、split | 母体与近重复组一致划分 |
| 2 | `fragments.csv` | fragment_id、object_id、bag_id、surface_ids、size_mm | 唯一实物身份，尺寸可 null |
| 3 | `surfaces.jsonl` | surface_id、fragment_id、view_ids、visibility、occlusion_reason、mask_paths | observed／partial／not_observed |
| 4 | `captures.jsonl` | capture_id、session_id、fragment_id、surface_id、path、sha256、device_id、calibration_id、quality_tier、timestamp | 整片 surface_id 可 null |
| 5 | **`capture` 扩展** | width、height、exposure_s、iso、focus_mode、light_mode、polarizer_state、angle_cmd_deg、angle_measured_deg | 无角传感器的实测角为 null |
| 6 | `relations.csv` | frag_a、surface_a、frag_b、surface_b、label、evidence_paths、reviewers、label_version | 对称，UNKNOWN 不自动转负 |
| 7 | `queries.csv` | query_id、capture_ids、gallery_version、mate_status、gt_relation_version | GT 字段仅评测进程使用 |
| 8 | `geometry.jsonl` | geometry_id、fragment_id、path、unit、frame_id、transform、method、config_hash、qc | 原始与展示几何分开 |
| 9 | `transitions.jsonl` | episode_id、step_id、observation_revision、action、next_capture_id、duration_ms、failure_code、policy_version | 成功与失败动作都记录 |
| 10 | `manifests.jsonl` | path、size_bytes、sha256、schema_version、created_at | 相对路径，哈希对应当前字节 |
| 11 | `cost_log.csv` | task_id、operator、start、end、action、result、failure_reason | 人时、机器时和墙钟分开 |

**完整数据链**（每一环都要可追溯）【文档】`p0459` / `p0472` / `t093` / `t096` / `t097` / `t104` / `p0638`：

原始图（不可变） → mask（整数 ID 无损） → 内外参（K 3×3 / pose 4×4；原始与 crop 后内参**分别存**） → 标定版本（`calibration_id` / `intrinsics_profile_id` / `rig_calibration_rev`） → sparse（SfM：reprojection error、track length、triangulation angle） → depth（float32 或定义 scale 的 uint16；**先区分相机 z 和光线距离**；invalid mask 独立） → normal（观测估计单位法向 + `normal_valid` + 邻域与误差） → dense cloud（含 depth confidence、coverage、有效像素比例） → **raw mesh 与 processed mesh**（原始与展示几何分开，补洞版单独标记） → **Global↔Local 变换**（local mesh 刚性回挂 global，**同时保留独立 local 原始结果**；fusion residual、scale consistency、变换版本） → scale（可追溯尺度基准 + scale drift 每次必报） → coverage + confidence → QC（Q1/Q2/Q3、repeat error、下游保留率）

**文件事务**【文档】`p0625`：原图上传先写临时文件，确认字节、尺寸、hash 和身份后**原子重命名**，再提交数据库；任一步失败标失败或待恢复，**不留下 saved 但文件不存在的记录**。
**GT 隔离**【文档】`p0626`：GT 存独立标注／评测目录和权限边界；公开查询界面和算法输入**不返回** `object_id`、完整装配或 `relations`。

---

## 8. 文档明确"拿不到"的项（合成侧不得声称拥有）

| 能力 | 可得 | 文档原文口径 | source |
|---|---|---|---|
| 光度立体法向 | **否** | 只写"**可选** Photometric Stereo 法向／normal-guided refinement" | `t096` |
| 自动偏振角 `polarizer_auto` | **否** | capabilities 含该字段；**手动偏振不冒充自动** | `p0577` |
| 0.1 mm 绝对精度 | **否** | "不是 0.2mm 测量精度承诺"；"无可信参考不虚报毫米误差，只给可核重复一致性" | `p0517` / `p0473` |
| 硬同步双目 | **否** | "两路依次拍摄，不宣称硬同步双目" | `t050` |
| 可靠深度 | **否** | "3D 不合格 → 标缺失，走经验证 2D"；缺失**不填 0 分** | `t073` / `t023` |
| 无限连续旋转 | **否** | "不边转边拍"；"Global 3D 不采用单圈 360° 作为正式采集" | `p0432` / `p1156` |
| 自动翻面 | **否** | "支撑遮面时**人工翻面**或换支撑，建立新 session" | `p0434` |
| 出土上下文 | **否** | 只有"**受限的模拟出土上下文**"，有缺失冲突和噪声，**不能等价母体 ID**；真实侧"坑位/层位**只有真实可信字段时才使用**"；模型输入**不包含**母体 ID、袋号 | `t101(D23)` / `p1146` / `p0412` |
| 结构光扫描 | **否** | 文档**全文未出现**结构光／structured light（命中 0 处） | — |

---

## 9. 兜底默认值（**这些是我们的假设，不是文档要求**）

> 文档对下列各项**未给出任何数值**。为让契约可执行，本文件补一个"市面常规默认值"，
> 并在 `configs/a12/capture_contract.json` 中统一写成 `"spec": "unspecified"` + `"fallback_mainstream"`（带 `"assumption": true`）。
> **实测或文档明确后必须替换，不得把兜底值当作文档要求引用。**

| # | 字段 | 文档实际写了什么 | **我们的兜底假设** |
|---|---|---|---|
| 9.1 | 镜头型号／焦距 | 只说"必要时验证兼容窄视场或可调焦镜头"（`p0518`）；更换镜头产生新 `calibration_id`（`p0427`） | SC3336B 原厂 M12 定焦（约 f=3.6mm 等效），或兼容可调焦 M12 |
| 9.2 | 畸变模型与阶数 | 只要求"畸变参数"、逐稳定工况标定（`p1163` / `p0579` / `t096`） | Brown–Conrady：`k1, k2, p1, p2`（必要时 `k3`），即 OpenCV 5 参标准模型 |
| 9.3 | 景深数值 | 景深被列为**必测/必检查**项（`p0504`/`p0511`/`p0515`/`p0518`/`p0533`/`p0579`），并给定性规则"宁可稍远拍高分辨率再裁 ROI，也不要让前缘/后缘大面积离焦"（`p1159`）；**无任何数值** | 近摄 5–10cm 档按 ~±3–8 mm 可用景深设计 |
| 9.4 | 色温 K 值 | 只说"四组**同色温**白光""先选低压**同批**白光"、CRI≥90 候选（`p0535`） | 5500–6500 K 高显色白光 |
| 9.5 | 单件采集时间 | 要求测量"每片采集/计算时间""动作时间""耗时""P95 时延"（`p0881`/`p0580`/`p0680`/`p0661`），**无数值门** | 整片 2D 8–15 min；Global 3D 30–60 min；Fracture-local 每断口 15–30 min |
| 9.6 | 计数映射：整片 6–10 / 断口 3–6 / 每档 ≥2 会话 | 只给内容名目与"多角度""至少两次重复"，未给正式数字门 | 见 §6 表，均标【工程约定】 |
| 9.7 | 3D "Q2 当量"下限 | 只给 G16 轴分层与必报指标（`t109`/`t093`/`t097`） | ≥50% 有效点、σ≤0.2 mm、≤2 个 r≤3mm 孔洞（见 §7.4） |
| 9.8 | `u_cmd_mm / u_scale_read_mm / u_encoder_mm` 命名 | 只要求命令/估计/实测三类位置分别记录（`p0563`/`p0577`/`p0591`） | 本契约的字段命名 |

---

## 10. 对照矩阵：扫描台模态 × 合成侧覆盖

**判定口径**
- **覆盖**：合成侧已有可复算产物，语义与扫描台要求同义，且证据可指。
- **部分**：字段/产物存在但语义、粒度、单位或权限不匹配，或只覆盖了要求的一部分。
- **缺失**：合成侧**无**对应产物或对应产物在语义上不是同一件事。

**合成侧现状来源**：一律引用 `docs/a12/modality_census.md`（"普查 §x.y"）及其证据脚本 `data/a12/reports/modality_census/probe_*.txt`。

| # | 扫描台模态 | 扫描台要求（必需/可选 + 数量精度） | 合成侧现状（普查结论 + 证据路径） | 覆盖判定 | 补齐方案（模块 + 字段） | 优先级 |
|---|---|---|---|---|---|---|
| 1 | 整片 2D（正/反/侧壁/轮廓/断口概览） | **必需**；6–10 张/片（含概览与补充角度） | 可产出：`obs_result` 37 件 / 412 帧；`(768,1024,3)`×396；`(192,256,3)`×16；12 视图×33 件（普查 §2.1/§2.3，`probe_11_imagery.txt`） | **部分** | `synlab/observe`：补"面枚举"元数据（正/反/侧壁/轮廓/断口概览）与每片张数门；`obs_result.meta` 加 `fragment_view_role` 枚举 | P2 |
| 2 | **断口局部 2D（3–6 有效方向/断口）** | **必需**；每真实断口多角度近摄 | **不可**：rim(tag=2) 像素 = **0 / 312 213 504**（`obs_result`）与 **0 / 313 786 368**（`label_bundle`）；根因 `synlab/physical/api.py:522-531` 把 `origin_kind` 全写 2=AMBIGUOUS（普查 §3.2，`probe_06_rim.txt`） | **缺失** | ①修 `synlab/physical/api.py` 的 `origin_kind` 分支；②`synlab/observe/render.py` 按 `interface_id≥0` 输出断面 tag；③新增 `fracture_local` 视图环（±10/20/30/40°）；④`observe/routes.py` 加 `local_fracture_view` 枚举与 ROI | **P0** |
| 3 | 局部近摄 U 距离档（10/15/20/25cm + 5–10cm） | **必需**；实测 px_per_mm 与 r_eff_mm | `configs/a12/camera_profiles.json` 有 3 档（GLOBAL/MID/LOCAL）u_position 0/60/120mm，工作距离 420/360/300mm；**3/3 `calibrated=false`、`STRESS_UNCALIBRATED`**（普查 §5.4） | **部分** | `configs/a12/camera_profiles.json`：加 50/100/150/200/250mm 五档（对齐 `t051`）与 `px_per_mm`/`r_eff_mm`/`dof_mm` 字段；**单位与量纲对齐 mm/px** | P1 |
| 4 | **分辨率档 GLOBAL/MID/LOCAL 与 mm/px** | **必需**；实测档位 ID，动作只选档位 | 档位存在但**无 px_per_mm**；观测分辨率只有 1024 长边（768×1024）；普查 §2.3 无 mm/px 字段 | **部分** | `synlab/observe/routes.py` + `synlab/cameras/profiles.py`：`resolution_profile` 加 `px_per_mm`、`r_eff_mm`、`dof_cover_mm`、`effective_roi`；`reports/` 出 mm/px 报表 | P1 |
| 5 | **断口局部 3D（60–150 张/断口 / 小半球）** | **必需**（候选起始范围，非冻结门）；±10–40° 倾角 | **不可**：非平面断裂面后端 `warped_partition`/`fracture_modes` = `OPERATOR_NOT_REALIZED`；`rough_shared_cut` = `PRECISION_BUDGET_EXCEEDED` / `PROCESS_KILLED`（普查 §3.5）；只有平面共享切与二次破碎可用 | **缺失** | `synlab/fracture`：实现共形/起伏断面后端；`synlab/observe/imaging.py` + `routes.py`：小半球视角生成器（`local_hemisphere` 采样）；`reports/` 出 local 覆盖与 repeat error | **P0** |
| 6 | **Global 3D（120–240 张 / 3–4 层 / 75–85% 重叠）** | **必需**（候选起始范围） | 视图数只有 **12 视图×33 件、4 视图×4 件**（普查 §2.3），远低于 120–240 张；无"层"概念 | **缺失** | `synlab/observe/routes.py`：多高度环绕轨（3–4 层）× 每层多方位 = 120–240 帧；`configs/a12/*.yaml` observation 段加 `shell_layers` / `overlap_pct`；`reports/` 出重叠率热图 | **P0** |
| 7 | **断口 ROI 点云（2048–8192 点，独立一份）** | **必需**；整片与断口 ROI 各一份 | 只有整片融合点云（`obs_fused_geometry` 32 件，每资产 1 份 `points/normals/point_valid`）；**无断口 ROI 独立点云**（普查 §2.2 末行、§3.3） | **缺失** | `synlab/observe/`：新增 `roi_cloud` 通道（`roi_points/roi_normals/roi_point_valid`，2048–8192）；`synlab/storage/export.py` 的 `deploy/geometry/index.json` 加 ROI 数组 | **P0** |
| 8 | 全片点云 2048–8192 点 | **必需** | 有 `points/normals/point_valid/normal_valid/scale_valid/frame_id`；`shard_0000.npz` 实测 **89 082 点**（普查 §7.3）——数量在区间内但**远超上界** | **部分** | `synlab/observe/`：加"按 2048–8192 抽稀"的 `point_budget` 档并与 `valid` 解耦；`reports/` 报实际有效点数 | P2 |
| 9 | 深度（相机 z, mm）与可见性 | **必需**；先区分相机 z 与光线距离；invalid mask 独立 | 有：`depth_z [H,W] float32`（**相机 z, mm**）412/412 帧；`uncertain_mask` 占 13.83%（普查 §2.2/§2.4） | **覆盖** | 无需补齐；但 deploy 包把它列入 `forbidden_channels`，属权限设计（见 #22） | — |
| 10 | 法向（观测估计 + `normal_valid` + 邻域误差） | **必需**（**观测估计**法向，非 GT） | 有：`normals`/`normal_valid`（`obs_fused_geometry` 32 件）；权威 mesh **不存**法线，下游按需重算（普查 §1.1/§2.2） | **覆盖** | 无需补齐；补 `estimate_neighborhood` 与 `normal_error` 字段以对齐 `t104` | P3 |
| 11 | **内外壁/断面/支撑/无效区区域 mask 整数 ID** | **必需**；整数 ID + 无损 | 只有**布尔** mask：`deployment_mask`/`roi`/`uncertain_mask`（普查 §2.2）；`id_map` 是**逐面 ID**不是区域 ID；`surface_tag` 只有 −1 与 0（rim 0 像素，普查 §3.2） | **缺失** | `synlab/observe/render.py`：输出整数区域 ID 通道（枚举 0..4 = 内外壁/断面/支撑/无效）；`t117` 规则"整数 ID 无有损压缩"落到 `synlab/degrade/api.py` 的 mask 写出；`label_bundle` 加 `region_id_map` | **P0** |
| 12 | **8 项质量向量（blur/exposure/coverage/occlusion/recon-conf/point-density/normal-stability/curvature-stability）** | **必需**；每视图+每区域命名 float32 向量，每项附 `valid` 与来源 | `synlab/observe/quality.py` 的 `estimate_quality` 实测键组为 `blur`/`exposure`/`density`/`holes`（`blur_laplacian_p95`、`overexposed_fraction`、`point_valid_fraction`、`hole_ratio_max`、`view_coverage_mean`、`roi_coverage_mean`…，`quality.py:230-234`）→ **命名与 8 项不对齐**，且缺 `occlusion`、`reconstruction_confidence`、`normal_stability`、`curvature_stability` | **缺失** | `synlab/observe/quality.py`：按 8 项重命名并补齐 4 个缺项（`occlusion` 从遮挡体/不确定像素推、`reconstruction_confidence` 从 depth confidence、`normal_stability`/`curvature_stability` 从局部法向/曲率场）；每个键带 `unit/valid/source(OBS_EST\|GT_ORACLE)`；`synlab/schemas` 加向量 schema | **P0** |
| 13 | Q1 / Q2 / Q3 三级验收 | **必需** | `synlab/qc/acceptance.py` + `qa_protocol_v1.json` + store 的 `qa_status`（`QA_PASS/QA_FAIL/QA_PENDING`）；实测 `visible_labels` 23/41 FAIL、`physical_result` 14/30 FAIL（普查 §6.2）——**没有 Q1/Q2/Q3 三级标签** | **部分** | `configs/a12/qa_protocol_v1.json`：把现有门映射为 Q1/Q2/Q3 三层并加 `q_level` 字段；`synlab/qc/acceptance.py` 出三级判定；`reports/` 出三级分布 | P1 |
| 14 | **SY-Q 映射（SY-Q0_OBS…SY-Q5 ↔ Q1–Q3）** | 文档并行维护两套命名 | 合成侧有 `SY-Q0_OBS…SY-Q5`（`t031`/`t110`）；实现侧 `synlab/degrade/axes.py` 31 轴 + 5 档，**无 SY-Q 档位对象**，也无到 Q1–Q3 的映射表（普查 §4.4） | **缺失** | `synlab/degrade/registry.py`：加 `sy_q_profile` 组合对象（Q0–Q5 = 轴档位的具名组合）；`configs/a12/` 加 `sy_q_mapping.json` 建立 SY-Q↔Q1–Q3 对照；`synlab/qc/` 读该表 | **P1** |
| 15 | 标定：`fx/fy/cx/cy` + 畸变（逐稳定工况） | **必需**；逐稳定工况独立标定 | 有 `K [3,3]` 与 `dist [5]` 逐帧；`dist` 412/412 帧非零；但 `calibration_id`/`intrinsics_profile_id` 语义**"calibrated=false / STRESS_UNCALIBRATED"**（普查 §2.4/§5.4） | **部分** | `synlab/cameras/profiles.py`：加 `intrinsics_profile_id` 与 `per_condition` 标定对象；`configs/a12/camera_profiles.json` 把 `calibrated` 与 `calibration_refs` 接到真实工况而非常量 false | P1 |
| 16 | **标定版本与尺度漂移字段** | **必需**；`calibration_rev`/`intrinsics_profile_id`/`rig_calibration_rev` + **每次采集必报 scale drift** | 无 `calibration_rev`/`rig_calibration_rev` 字段；尺度是**渲染器构造的虚拟 mm**（`routes.py:910`），`scale_valid=true` 但**无比例尺参照物**（普查 §5.4）；`G06` 轴可注入 `ratio_error 0→0.05`（普查 §4.2） | **缺失** | `synlab/roles.py` + `pipeline.py`：加 `calibration_rev`/`rig_calibration_rev`/`intrinsics_profile_id` 到资产 meta；`synlab/qc/` 加 `scale_drift` 度量（对齐 `t097`"每次采集必报"）；`reports/` 出 scale_drift 表 | **P0** |
| 17 | **Global↔Local 变换 + raw vs processed mesh** | **必需**；`t093`/`t096`/`t101(D13)` | **无 fusion 产物**：`geometry.jsonl` 语义只在 `t044` 文档层；资产侧 `frame` 只有 `W_mm`/`F_mm`/`S_mm`/`C_mm`/`pixel_cv_center`，**无 fusion residual / scale consistency / 变换版本**；`D13`"保留 raw 版本、补洞版单独标记"在 storage role 里**无 raw/processed 标记**（普查 §6.1、§1.1） | **缺失** | `synlab/storage/release.py` + `roles.py`：加 `transform`（4×4 Global↔Local）、`fusion_residual`、`scale_consistency`、`transform_rev`；mesh role 加 `geometry_variant ∈ {raw, processed, hole_filled}` | **P0** |
| 18 | **raw vs processed mesh（另列）** | **必需**；"原始与展示几何分开""补洞版单独标记" | 展示层 `display_lod_glb` 与权威 mesh 是不同 role，但**没有 raw/processed 的显式标记字段**；GLB 只有 L0（L1/L2 缺 `fast_simplification`）（普查 §1.2/§1.3） | **缺失** | 与 #17 合并实施：`roles.py` 加 `geometry_variant`；`synlab/storage/export.py` 的 `deploy/geometry/index.json` 加该字段 | P1 |
| 19 | **11 类账本（objects/fragments/surfaces/captures/relations/queries/geometry/transitions/manifests/cost_log + capture 扩展）** | **必需**；逐类最少字段 + 约束 | 实现是**单个 `metadata.sqlite` + blob 目录**（`synlab/storage/store.py`，`assets` 表 894 行），**不是 11 个具名账本文件**；最接近的是训练包的 `queries.parquet`/`relations.parquet`/`labels/*.parquet`（普查 §7.2）与 `roles.py` 的 role 枚举——**无 `cost_log`、无 `transitions` 产物**（`episode_trace` 0 件，普查 §5.3） | **缺失** | `synlab/storage/export.py`：新增 11 类账本导出器（`objects.csv`…`cost_log.csv`）；`synlab/jobs/` 出 `cost_log`（人时/机器时/墙钟分列）；`synlab/episodes/` 出 `transitions.jsonl`（当前 0 件，需先有 episode 运行） | **P0** |
| 20 | **灯态 5 枚举（WHITE_DIFFUSE/LEFT_GRAZE/RIGHT_GRAZE/CROSS_POL/NORMAL_REFLECT）** | **必需**；5 枚举 + `camera_group_id` 分组 | 合成侧 `obs_view.payload.scene.light` 是**符号字符串 `"ObsSpec.resolved_light"`**（不是枚举值）；渲染光照模型是 **Lambert + ambient**，代码自述"View-dependent term is omitted on purpose … No specular claim is made"（`render.py:321-323`）；`I06` 只按 `saturation_target` 调光照/BRDF 尺度（普查 §5.3、§4.2） | **缺失** | `synlab/observe/`：定义 5 个 `light_mode` 枚举（对齐 `t053`）并落到 `obs_view.meta.light_mode`；`synlab/degrade/axes.py:I06` 扩展为 5 灯位；加 `camera_group_id` 支持 MVS 分组 | **P0** |
| 21 | MVS 子集（20 母体 / 400 片 / 30–120 帧） | **必需**；全部尝试入分母 | `data/a12/reports/mvs_subset.json`：`attempted=4`、`frames_per_fragment=4`、**`dense_points=0`、`depth_maps=0`、`failure_code=MVS_NOT_AVAILABLE`**（`has_patch_match_stereo=false`）；稀疏仅 **107** 点、2/4 帧注册（普查 §8） | **缺失** | `synlab/observe/mvs_subset.py`：把 30–120 帧/片与 20 母体/400 片规模写进子集清单；**稠密 MVS 需先解决 `patch_match_stereo` 缺失**（换 pycolmap 构建或走 `stereo_fusion` 替代路径），并在 `reports/` 报 `dense_status` | P1 |
| 22 | 部署侧通道白名单（RGB + 部署 mask + u 位置；禁 depth/id_map/surface_tag/K/T） | **必需**（权限分离） | `deploy/obs/index.json`：白名单 3 通道、`forbidden_channels` 8 项（普查 §7.4）——**与扫描台一致** | **覆盖** | 无需补齐；但需注意 #2 的断面在**源侧**就渲染不出来，白名单本身没错 | — |
| 23 | 关系真值（R2 邻接 / R1 同器非邻接 / UNKNOWN） | **必需**；对称，UNKNOWN 不自动转负 | 有：`relations` 191 条 `{R2:56, R1:131, UNKNOWN:4}`；`clean_truth` 含完整断面几何；但 `physical_truth`/`visible_labels` 层**丢失 `iface_*`**（普查 §3.1/§6.3） | **部分** | `synlab/truth/api.py`：把 `iface_*`（断面面属性）下推到 physical/visible 层，否则退化后无法评测局部关系；`reports/relations.parquet` 保持 | P2 |
| 24 | 断裂面几何真值（面积/法向/间隙/配对对应） | **必需** | 有：`clean_truth` 55 件、`interface_count` 合计 **573**、断面面积合计 **428 358.8 mm²**、`corr_*` 11 键；断面法向 `iface_normals_a/b`（普查 §3.1） | **覆盖** | 无需补齐；但**无断面形貌粗糙度与脊线**（见 #25） | — |
| 25 | 断面粗糙度（Ra/Rq 谱）与脊线（ridge/crest） | **可选**（Fracture-local 优先保真的几何含 ridge/valley，`t093`） | **无**：全库无粗糙度标量/谱，无脊线提取（普查 §3.3） | **缺失** | `synlab/observe/`：新增断面形貌描述子（沿断面法向的功率谱 + 脊线/谷线提取）；`reports/` 出描述子统计 | P2 |
| 26 | 重复扫描 QC（同片/同断口 ≥3 次） | **必需**；≥3 次独立采集（最好重新装夹） | 重复观测存在（多 store、多 run），但**无"重复扫描 repeat error"度量产物**；`t097` 要求的 `Surface repeat error`/`Normal repeatability`/`Boundary repeat error` 在 `reports/` 中**无对应文件** | **缺失** | `synlab/diagnostics/` + `synlab/qc/`：实现三次重建两两刚性对齐的 `surface_repeat_error`(median/P90/P95)、`normal_repeatability`、`boundary_repeat_error`，出 `data/a12/reports/repeat_scan_qc.json` | **P1** |
| 27 | 出土上下文（遗址/层位/共存物/批次） | **可选/扩展**（受限模拟，不能等价母体 ID） | **无**：22 库 2206 资产 6977 键路径，考古关键字 **0** 命中；`observation.context` 只有 4 个采集键 `route/input_profile/n_views/scale_valid`；`X03` 轴的 "context" 就是这个 4 键 dict（普查 §5.1/§5.2/§5.3） | **缺失**（**符合文档口径**：真实侧"只有真实可信字段时才使用"） | 若要做：`synlab/observe/` 加**模拟**出土字段（`site_id/trench/locus/stratum/batch_id`）并在 `t101(D23)` 约束下做缺失+冲突+噪声扰动；**必须**在 `FORBIDDEN_FEATURE_FIELDS` 里保持与母体 ID 不可等价 | P3 |
| 28 | 主动观察 episode / `transitions.jsonl` | **必需**（账本第 9 类） | 契约存在但**产物 0 件**：22 库中 `episode_trace` = 0；`api_episodes` 0 行；动作空间 8 种（`STOP/U_MOVE/LOCAL_FRACTURE_FRAME/ADD_AZIMUTH/ADD_ELEVATION/TOGGLE_LIGHT/TOGGLE_POLARIZATION/RECLAMP_FLIP`）（普查 §5.3） | **缺失** | `synlab/episodes/`：跑通至少 1 个 episode 生成路径，落 `transitions.jsonl`（含 `next_capture_id`/`duration_ms`/`failure_code`/`policy_version`）；`roles.py:54` 已注册 role | P2 |
| 29 | 31 轴退化（实物 8 / 成像 10 / 重建 8 / 输入 5） | **必需**（pilot 每组先 2 轴） | 31 轴注册、**level 0 实测恒等 31/31**（载荷字节不变，store delta=0）；**28/31 有物化档位**；`P02/P04/P08` **零物化**；每族只跑默认变体；**无多轴 recipe 产物**（普查 §4.3/§4.4/§4.5） | **部分** | `configs/a12/degrade_recipes/`：补 `P02/P04/P08` 三轴配方；`synlab/degrade/api.py:run_recipe` 出多轴 recipe 产物；`reports/` 出 31×5 覆盖矩阵 | P1 |
| 30 | 真实物理尺度 / 比例尺参照物 | **必需**（每次正式采集含可追溯尺度基准） | **不可**：3/3 相机档位未标定；无比例尺参照物；尺度是渲染器构造的虚拟 mm（普查 §5.4） | **缺失**（**符合文档口径**） | 合成侧**不应声称**真实物理尺度。可做的是：`synlab/observe/` 在渲染场景里放**虚拟 coded target**（`p1164` 口径：coded targets 不进学习/匹配输入，必须剔除或 mask），用于验证尺度漂移算法本身 | P2 |
| 31 | 真实实拍照片（REAL_CAPTURE） | 扫描台的**存在理由** | **无**：`real_capture = "REAL_CAPTURE:PENDING"`；`env_report.json` `"no real capture dataset"`（普查 §8） | **缺失**（**不可由合成补齐**） | 只能在扫描台建成后采；合成侧只能出"上界仿真"，**不能**标为真实域 | — |
| 32 | 观测路线多样性（ideal_visible / proxy_scan / photo_mvs） | 扫描台要可对照的成像工况谱 | 代码定义 3 条路线，**生产库只有 `proxy_scan`（114/114，100%）**；`ideal_visible`/`photo_mvs` 库内 **0 件**；`photo_mvs` 唯一一次真实运行 = `STOP_SFM` 失败（普查 §2.1/§2.6） | **部分** | `synlab/observe/routes.py`：让 `ideal_visible` 与 `photo_mvs` 进入常规批次并落 store；修复 `photo_mvs` 的 `incremental_mapping` 无重建问题（提高纹理/特征或换 matcher） | P1 |
| 33 | 交付态图像（gamma/JPEG 之后的非线性交付态） | **必需**（`t044` capture 扩展含 `iso`/`exposure_s`；交付图与线性源必须分开） | **受限**：`obs_view` 实测 `encoding` **全部 `LINEAR`（183/183）**，**从未物化** gamma/JPEG 之后的交付态图像；`imaging.py:340-356` 的 `camera_response`（LINEAR/BT709/SRGB/POWER）**代码可做但库内无产物**（普查 §2.4/§2.6/§8） | **缺失** | `synlab/observe/imaging.py` + `degrade/axes.py`：新增"交付态"路径（γ/SRGB + JPEG 往返）并落 `obs_view`；`data_contract.md` 的"禁止把 gamma/JPEG 当线性源"约束需同时保留 | P1 |
| 34 | 导出包可信性（可程序化对照的前提） | **必需**（条款草案第 1/3 条要求"可程序化对照"） | **受限**：普查独立复算（`probe_15_export_defects.py`）确认 **3 处静默缺陷**——① `tokens` **有效秩 = 1**（`tokens[:,k] = flat*(1-1e-6*k)`，`sv[1]/sv[0] ≤ 6.77e-09`）；② `view_pos.npy`（声明"u position mm"）**31/31 全零**；③ `frame_id == arange(n) % n_views` **31/31** 是行号计数器。另 `valid.npy` 真值比例 0.000386–0.264235，`valid` 与"tiles 非黑"的 IoU 塌到 0.0012–0.0053（普查 §7.7） | **缺失** | `synlab/storage/export.py`：修 `tokens` 写入（或用 `token_input`）、打通 `u_position_mm` 到 `view_pos`、把 `frame_id` 改为真实视角/坐标系 id；`synlab/qc/loader_probe.py` 加这 3 项的回归断言；`reports/` 出 `valid` 一致性报告 | **P0** |
| 35 | 训练可用性与合法负样本（"≥3 次重复扫描/可复算"的执行前提） | **必需**（`t042` 关系证据；条款要求可复算） | **无**：`data/a12_trainable` 被判 **`verdict = "not_trainable"`、`trainable = false`**；15 项检查 4 PASS / 4 FAIL / 6 MISSING / 1 N/A；`first_cause = semantics.mask_semantics`（`33/65` 记 `coc_units_v2`）；`0 effective queries: 0 encodable positive pairs, 0 eligible legal negatives`；`relations.parquet` 的 `eligible_as_negative = False` **150/150**、`has_observation = False` **150/150**（R2 对**只有一侧被渲染**）；`store/releases` 空、`runs` 全 `PENDING`；全仓唯一真实训练 = **3 步 CPU smoke**（`PIPELINE_OK_DATA_INSUFFICIENT`）（普查 §7.8/§8） | **缺失** | `synlab/relations/gallery.py` + `sampler.py`：让 R2 对**两侧都渲染**并产出 legal negative；`synlab/qc/data_quality.py` 的 `semantics.mask_semantics` / `damage_semantics` / `obs_semantics` 三项 FAIL 逐项修；`storage/release.py` 冻结首个 release；`reports/` 出 15 项检查明细 | **P0** |

**矩阵行数汇总**（共 **35** 行 = 覆盖 **4** + 部分 **9** + 缺失 **22**）：

| 判定 | 行数 | 行号 |
|---|---|---|
| **覆盖** | **4** | #9 深度与可见性、#10 观测法向、#22 部署通道白名单、#24 断裂面几何真值 |
| **部分** | **9** | #1 整片 2D、#3 U 距离档、#4 分辨率档、#8 全片点云、#13 Q1–Q3、#15 标定内参、#23 关系真值、#29 31 轴退化、#32 观测路线多样性 |
| **缺失** | **22** | #2 断口局部 2D、#5 断口局部 3D、#6 Global 3D、#7 断口 ROI 点云、#11 区域 mask 整数 ID、#12 8 项质量向量、#14 SY-Q↔Q 映射、#16 标定版本与尺度漂移、#17 Global↔Local、#18 raw vs processed、#19 11 类账本、#20 灯态 5 枚举、#21 MVS 子集、#25 断面粗糙度/脊线、#26 重复扫描 QC、#27 出土上下文、#28 episode/transitions、#30 真实物理尺度、#31 真实实拍、#33 交付态图像、#34 导出包可信性、#35 训练可用性与合法负样本 |

### TOP 10 缺失项与建议优先级

| 排名 | 缺失项（行号） | 优先级 | 为什么排这个位置 |
|---|---|---|---|
| 1 | **断口局部 2D（3–6 方向/断口）**（#2） | **P0** | 断面在 2D 里 rim 像素 = **0 / 312 213 504**，直接使"断口局部关系"这一主任务在合成侧**无输入**；根因是单一代码点（`physical/api.py:522-531`），修复杠杆最大 |
| 2 | **区域 mask 整数 ID（内外壁/断面/支撑/无效）**（#11） | **P0** | 现有 mask 全是**布尔**（`deployment_mask`/`roi`/`uncertain_mask`），与 `t101(D09)`+`t117`+`p1481` 的整数 ID 无损要求不是同一件事；它是质量向量与 ROI 点云的前置 |
| 3 | **8 项质量向量**（#12） | **P0** | 现有 `estimate_quality` 键组是 `blur/exposure/density/holes`，**缺 4 项**且命名不对齐；质量头是 CTM 的 write/retain/correct 门控输入（INNO-05/INNO-12） |
| 4 | **训练可用性与合法负样本**（#35） | **P0** | `verdict = not_trainable`、`0 effective queries`、R2 对只有一侧被渲染导致 `eligible_as_negative = False` **150/150**；**在这条修好之前，矩阵里任何"覆盖"都无法被下游复算验证** |
| 5 | **导出包可信性 3 缺陷**（#34） | **P0** | `tokens` 有效秩 = 1、`view_pos` 全零、`frame_id` 是行号计数器——条款草案第 1/3 条要求"字段级同义 + 可程序化对照"，这 3 项使对照本身不可信 |
| 6 | **标定版本与尺度漂移字段**（#16） | **P0** | 无 `calibration_rev`/`rig_calibration_rev`/`intrinsics_profile_id`，`calibrated=false`；`t097` 要求"每次采集必报 scale drift"，缺失则所有毫米级主张不可引用 |
| 7 | **Global↔Local 变换 + raw vs processed mesh**（#17/#18） | **P0** | `t093`/`t096` 的 fusion residual、scale consistency、变换版本**全无产物**；没有它，局部高精模型无法回挂整片坐标系 |
| 8 | **11 类账本**（#19） | **P0** | 实现是单个 `metadata.sqlite` + blob，**无 `cost_log`、无 `transitions.jsonl` 产物**；账本是 `t044` 的硬清单，也是"合成 ≥ 扫描台"可程序化对照的落地载体 |
| 9 | **灯态 5 枚举**（#20） | **P0** | 合成侧 `scene.light` 是符号字符串，渲染是 **Lambert+ambient 且明确不宣称镜面**；与 `t053` 的 5 枚举不是同一对象，CROSS_POL 更无法表达 |
| 10 | **Global 3D（120–240 张 / 3–4 层 / 75–85% 重叠）**（#6） | **P0** | 现状只有 **12 视图×33 件**，差一个数量级；且 `p1156` 明写"12 视角不等价于真实 MVS 照片数" |

> **紧随其后的 P0**：`断口局部 3D`（#5，非平面断面后端全部 `OPERATOR_NOT_REALIZED`）、`断口 ROI 点云`（#7，只有整片一份）。
> 第二梯队（**P1**）：`SY-Q↔Q1–Q3 映射`（#14）、`MVS 子集`（#21）、`重复扫描 QC`（#26）、`Q1–Q3 三级验收`（#13）、`交付态图像`（#33）、`分辨率档与 mm/px`（#4）、`U 距离档`（#3）、`标定内参逐工况`（#15）、`31 轴 P02/P04/P08 物化`（#29）、`观测路线多样性`（#32）、`raw vs processed 标记`（#18）。
> 第三梯队（**P2/P3**）：`断面粗糙度/脊线`（#25）、`episode/transitions`（#28）、`整片 2D 面枚举`（#1）、`全片点云抽稀`（#8）、`关系真值下推`（#23）、`真实物理尺度`（#30，**不可由合成补齐**）、`出土上下文`（#27，可选/扩展）、`真实实拍`（#31，**不可由合成补齐**）。

---

## 11. 条款草案：「合成 ≥ 扫描台」

> **重要免责**：文档**没有**这条显式要求。全文对"合成 ≥ 扫描台"类表述的检索只命中 **2 处无关句**
> （`p1488` 的"最佳仿真动作**超实物域只算上界**"、`p1156` 的"12 视角只是训练缓存预算，**不等价于**真实 MVS 所需照片数量"）。
> 下面是可以直接引用进计划的**条款草案**，建议补在 **A12.7 / G14.4 / B3 / G3**。

### 11.1 条款正文（草案 v1）

**条款（合成覆盖不得低于扫描台可得模态）**

1. **覆盖方向**：对本文档 B3 / B6 / C3–C11 / C10.1 所列的**每一条扫描台可得模态**，合成侧必须存在**语义同义、可程序化对照**的对应产物。
   对照以字段级**同义映射表**为准，映射表随 `configs/a12/capture_contract.json` 版本冻结；新增扫描台字段而未同步映射表时，视为**覆盖缺口**，不得默认通过。
2. **可更多不可更少**：合成侧允许**多于**扫描台可得模态（例如干净的完整装配真值、逐点对应、31 轴退化、理想可见基线），但**不得少于**扫描台在合格工况下真实可得的模态集合。
   "多于"的部分必须在 schema 中显式标为**合成专有**（`synthetic_only: true`）并进入 `FORBIDDEN_FEATURE_FIELDS` 白名单管控，**不得**以任何形式进入部署式输入。
3. **同义而非同名**：映射的判据是**语义、单位、坐标系与权限**四项同时成立；仅字段名相同不构成覆盖。
   不满足时只能记为**部分覆盖**，并须在 `reports/` 中给出差值（单位换算、坐标系变换或权限差异）。
4. **超实物域只作上界**：任何超出扫描台物理可达范围的仿真（`p1488`：最佳仿真动作超实物域；`p1156`：12 视角不等价于真实 MVS 照片数）**只能作为性能上界**陈述，
    **不得**当作扫描台可达能力的证据，**不得**用于"合成已覆盖"的判定，也**不得**替代"扫描台拿不到"清单（§8）中的任何一项。
5. **拿不到项不得伪造**：§8 列出的 9 类"文档明确拿不到"的项（光度立体法向、自动偏振角、0.1mm 绝对精度、硬同步双目、可靠深度、无限连续旋转、自动翻面、出土上下文、结构光），
   合成侧**不得**在产物、字段或文档中声称拥有其等价能力；可以构造其**上界仿真**并显式标注。
6. **验收方式**：以 §10 的对照矩阵为检查表，逐行要求"覆盖 / 部分 / 缺失"三态；
   **只要存在任何"缺失"行且该行对应扫描台的必需模态，本条款即判不通过**；"部分"行须给出补齐计划与负责人。
7. **诚实性**：矩阵与映射表必须随代码版本更新（版本一致性检查进 CI）；`unspecified` 字段一律给兜底假设并显式标注为假设（见 §9），**不得**把兜底值写成文档要求。

### 11.2 建议落点

| 建议落点 | 理由 | source |
|---|---|---|
| **A12.7** | 合成实验室的模态覆盖口径应与扫描台契约同源 | 与 A12 章"数据产品 D01–D24"直接衔接（`t101`） |
| **G14.4** | 该节已写"camera_spec 引用实测 GLOBAL／MID／LOCAL 的距离、焦点、FOV、有效 ROI 及景深；U 沿光轴改变外参，不用 resize 模拟物理靠近" | `p1488` |
| **B3** | B3 是"必须采到的数据"的唯一权威清单，是条款第 1 条的分母 | `t042` |
| **G3** | G3 是合成"数据产品"编号表（D01–D24），是条款第 2 条"合成专有"标注的落点 | `t101` |

---

## 12. 需人工裁决清单

> 以下为**文档内部矛盾**或**文档未明确**、无法在只读契约中单方面决定的项。每项给出两方证据与建议裁决方向。

| # | 项 | 冲突/缺口 | 证据 | 建议裁决方向 |
|---|---|---|---|---|
| **1** | **`ActionProposal` 两处字段集** | **字段集不一致**：一处含 `query_id/evidence_revision/action_id/target_region/camera_id/目标姿态或相对转角/light_mode/预期成本/理由`（**9 项**）；另一处含 `u_profile_id/distance_mode/focus_setting_id/intrinsics_profile_id/expected_roi`（**5 项**）；两集**交集为空** | `p0276`（A7.2）vs `p0638`（D5.1）；第三处 `p0574`（C10）用 `pose_id/u_profile_id/light_mode/intrinsics_profile_id` | **合并为超集**（14 项 + `pose_id`），并声明 `u_*`/`focus_*`/`intrinsics_*` 仅在 U 相关动作时必填；`target_region`/`expected_roi` 统一为一个 `expected_roi` 字段 |
| **2** | **出土上下文字段规格** | 只有"受限的模拟出土上下文，有缺失冲突和噪声，**不能等价母体 ID**"（`t101-D23`），**未给字段名、类型、缺失率**；另一处只给"模拟出土区、层位、袋号/坑位等**可控元数据**" | `t101(D23)` / `t088` / `p1146` / `p0412`；合成侧合成器实测 **0 命中**（普查 §5.2） | 定为**可选/扩展模态**：先冻结 5 字段（`site_id/trench/locus/stratum/batch_id`）+ 缺失≤50%（对齐 `X03` 轴 `missing_rate 0→0.5`），并强制进入 `FORBIDDEN_FEATURE_FIELDS` |
| **3** | **最终 M（候选预算）** | 文档多处使用 `M` / `Top-M` / `any@M` / `PoolCov@M`，**未给最终 M 的数值**；历史实验里 M=22k 与 full 并列 | `p0108`（2.2.1 公式）/`t007`（retrieve 输入含 M）/`p1093`/`p1106`（CEIL 22k=0.9489、full=0.9474） | 需人工定：**M 是"每 query 初检池大小"还是"图库大小"**；建议冻结 `M ∈ {1k, 10k, 50k, 100k}` 分层并在 `metrics_contract` 固定，与 `G18.4` 的 1k/10k/100k 库口径一致 |
| **4** | **停止 δ / K** | 只有"先固定最多 **4 tick** 规则：TopK 稳定且分数变化**小于开发冻结 δ** 连续两轮才停"——**δ 没有数值**，且"开发冻结"未给冻结时点与冻结方式 | `p0269`（A6.13） | 由 A 岗在开发集上冻结 δ（建议给 δ 的搜索范围与选择规则），并把 δ 与 4-tick 上限一起写进 `experiment_spec` |
| **5** | **`PairOutput` schema** | 只有"**至少**包括 `candidate_id/rank_score/score_type/support_regions/conflict_regions/observability/model_version/evidence_revision`"（8 项），**未给类型、取值范围、`score_type` 枚举** | `p0167`（A4.8）；与 `t007` 的 `score_pairs`/`calibrate_output` 输出口径需对齐；与 `t126` 的 schema 合同行需对齐 | 定为 **schema 冻结项**：给 8 字段的 dtype 与 `score_type ∈ {ranking_score, calibrated_prob}` 枚举；`support_regions`/`conflict_regions` 需与 `t053` 灯态、`t042` 区域 mask 的 ID 空间对齐 |
| **6** | **R1 误排分母** | 只说"R1 误排**可先**定义为 Top10 中 R1 数量**除有效候选位数量**，并**另报** R1 排在第一名或首名 R2 之前的查询比例。UNKNOWN 位单独统计且不强当 R1，定义**写入 `metrics_contract`**"——即**正式定义尚未冻结** | `p0330`（A9.1）；分母另受 `p0108`（全库 `N_G` 分母）与 `p0329`（误荐率/接受后风险两个分母不能混用）约束 | 需人工定：**"有效候选位"是否含不足 Top-K 时的空位**、**UNKNOWN 位是否计入分母**；建议同时报 `R1@10 / |valid slots|` 与 `R1-first-query ratio` 两个数，主指标取前者 |
| **7** | **最终论文主指标清单** | 一处说"**最终论文主指标数量有限**，其他指标作为诊断"（**未给清单**）；另一处列出主任务为 `Hit@10 / CovRecall@10 / any@M` 并**附带** R1 误排、mate-absent 风险、校准和推理成本 | `p0330` vs `p0377`（A12.10）；另 `p0108`–`p0109` 给 EffectiveHit/EffectiveCov/接受率 | 需人工冻结**主指标 3–4 个**（建议 `Hit@10`、`CovRecall@10`、`any@M`、`EffectiveHit`），其余列诊断表；冻结后写进 `metrics_contract` |
| **8** | **镜头型号/焦距** | 全文未给；只说"必要时验证兼容窄视场或可调焦镜头" | `p0518`；B13 只给 SC3336B 官方页（`p0491`/`p0607`）；`p1223` 只给 2304×1296、手动对焦、1/2.8"、MIPI | 由 C 岗按 C3.1 实测选定（见 §9.1 兜底） |
| **9** | **畸变模型与阶数** | 只要求"畸变参数"、逐工况独立标定，未给模型 | `p1163`/`p0579`/`t096` | 建议冻结 Brown–Conrady 5 参（见 §9.2 兜底）；`t096` 另要求"检查近摄焦距/畸变是否需**单独模型**"，即可能 Global 与 Local 用不同阶数——需人工定 |
| **10** | **景深数值** | 景深被列为必测项但**无任何数值** | `p0504`/`p0511`/`p0515`/`p0518`/`p0533`/`p0579` + 定性规则 `p1159` | 由 C 岗实测冻结（见 §9.3 兜底） |
| **11** | **色温 K** | 只说"同色温白光""同批白光"、CRI≥90 候选 | `p0535` | 建议冻结 5500–6500 K 并**用色卡核对**（见 §9.4 兜底） |
| **12** | **单件采集时间** | 要求测但**无数值门**；同时禁止"承诺几分钟内完成密集 3D" | `p0881`/`p0580`/`p0680`/`p0661` | 由 B/C 岗实测后写回（见 §9.5 兜底）；**不得**先写目标值再当成绩 |
| **13** | **结构光是否在范围内** | **文档全文未出现**"结构光/structured light"（命中 **0** 处）；但任务书要求列入裁决 | 全文检索 0 命中；相邻硬件只有"专用微距、自动多方向光、精密转台、FractureScan 主动加密采集"（`t094`-P2，且需 Gate 批准） | 建议**明确排除**：结构光不在 V1.44 采集台范围内；若未来引入，须走 P2 的"按 Gate 批准"路径并重开采集契约 |
| **14** | **SY-Q 与 Q1–Q3 的映射** | 文档并行维护两套质量命名（`SY-Q0_OBS…SY-Q5` 与 `Q1/Q2/Q3`），**未给映射表** | `t031`/`t110`（SY-Q）vs `p0464`（Q1/Q2/Q3）；`t126` 的"质量"合同行只写 SY-Q | 需人工给一张映射表（建议按"数据可用性"而非"退化强度"对齐：SY-Q0→Q1、SY-Q1/Q2→Q2、SY-Q3/Q4/Q5→Q3，但 SY-Q5 是消融不是更差工况，须单列） |
| **15** | **质量向量 vs 退化向量的关系** | 两份清单并行：**8 项质量向量**（`p0236`，观测侧"证据有多可用"）与 **14 维退化向量 D**（`p0365`，生成侧"注入了什么损失"）；**未说明二者是否同一 schema** | `p0236` vs `p0365`；`t104` 只说"每视图和每区域命名的 float32 向量，每项附 `valid` 及来源为 `OBS_EST` 或 `GT_ORACLE`" | 需人工定：建议**保持两份独立**（观测侧 8 项 vs 生成侧 14 项），并建立"退化轴 → 质量分量"的预期影响表用于诊断，**不合并** |
| **16** | **仿真首版物理尺寸 vs 真实样片尺寸** | 仿真首版候选"最大尺寸 80–300 mm、正常壁厚 **2–10 mm**"，且明确"参数属于仿真覆盖预算，真实采集后以尺寸分布校准，**不自动称为出土文物分布**"；但 B3/C3.1 的采集对象尺寸范围未给 | `p1353` vs `t042`/`p0511` | 需人工定**真实样片的尺寸/壁厚门限**；在此之前仿真尺寸只能作覆盖预算，不得当目标分布 |
| **17** | **`physical_component` 的 `F_mm` 局部帧与 `magnitude` 语义** | 普查实测 `physical_component` 55 件全在 `F_mm`（构件局部帧，**不是世界帧**）且 `origin_kind` **100% = 2 (AMBIGUOUS)**；同时存在 `origin_kind==1` 与 `interface_id>=0` 两种"断面"定义且**有 506/3610 = 14.0% 冲突** | 普查 §1.1/§3.2/§3.4；根因 `synlab/physical/api.py:522-531` | 需人工定：**断面的权威定义取哪一个**（建议取 `origin_kind==1`，并把 `interface_id>=0` 降为辅助；冲突面单列 `ambiguous`），以及是否强制把 physical 结果回挂世界帧 |
| **18** | **`loss_mask ≡ valid ≡ (kind=="R2")` 是否冗余** | 普查实测三者完全相同（`relations.parquet` 150 行：`False=117/True=33` 与 `kind R1=117/R2=33` 一一对应）；`visible.parquet` 则**根本没有**这三列 | 普查 §6.4/§7.2 | 需人工定：`loss_mask` 是否保留为独立语义（为将来 TINY_CONTACT/UNKNOWN 留位）还是删除；`visible` 层缺列是否补齐 |

**合计 18 项需人工裁决。**

**最关键 3 条**：
1. **#1 `ActionProposal` 两处字段集（`p0276` vs `p0638`）** —— 两个集合**交集为空**，直接决定 A/C/D 三岗的动作接口能否联调；不裁决则 `rig_service`、评测器与前端三方各按一套字段实现。
2. **#4 停止 δ / K 与 #3 最终 M** —— 这两个数同时是**机制实验的停止规则**和**主指标的预算口径**；不冻结则"多轮审议 vs 静态"的主比较与所有 `any@M`/`PoolCov@M` 结果都不可复算。
3. **#14 SY-Q 与 Q1–Q3 映射 + #7 最终论文主指标清单** —— 质量口径与指标清单是论文主张的**分母**；两套命名并行且主指标数未定，会把"合成 ≥ 扫描台"的覆盖判定也拖成不可裁决。

---

## 附：本文件与 `configs/a12/capture_contract.json` 的对应

| 本文件章节 | 契约 JSON 段 |
|---|---|
| §1 相机 | `camera` |
| §2 工作距离与分辨率 | `working_distance_and_resolution` |
| §3 灯光 | `lighting` |
| §4 机械 | `mechanics` / `budget_cny` |
| §5 图像与元数据 | `image_and_metadata` / `calibration` / `tool_capabilities_contract` / `action_proposal` |
| §6 采集清单 | `capture_checklist` |
| §7 掩码/质量/账本 | `mask_and_quality` / `ledger` |
| §8 拿不到项 | `explicitly_unavailable` |
| §9 兜底默认值 | `unspecified_with_fallback` |

**计数**：契约 JSON **108** 个 `spec` 字段 / **133** 处 `source` 指针 / **11** 处 `unspecified` / **11** 处 `fallback_mainstream`（其中 **5** 处带 `"assumption": true`）。
引用覆盖（去重实测）：**33 个表格**（`t001, t007, t023, t031, t032, t040, t042, t044, t045, t050–t055, t057, t059, t062, t072, t073, t088, t093–t097, t101, t104, t109, t110, t117, t126, t128`）+ **68 个段落**（`p0005 … p1796`）。
对应文档章节：**C3–C15（第 6 章 DIY 采集台）**、**B3–B9（第 5 章数据采集与标注）**、**D3–D5（第 7 章前后端与元数据账本）**、**A4/A6/A7/A9.1/A12.6/A12.10（第 4 章与附录 A/G）**、**G14–G15/G17/G23（附录 G 合成实验室）**、**H2/H4/H6（附录 H 统一实施合同）**、以及 **3D 重建质量强化专项**（`p1155`–`p1176`）。
