# A12 状态板：已完成 / 未完成

**快照**：2026-10-02 夜（本地）。**本文件是状态的唯一权威清单**；细节见 `open_items.md`（未开工/在修追踪）、`engineering_policy.md`（算法选型政策）、`precision_audit.md`（实测精度）、`decision_record.md`（口径裁决）、各专项文档。
**数据基线**：最新库 `data/a12_trainable/store`（463 资产）· 最新包 `data/a12_exports/negfix/next_experiment/training_package` · 旧代归档 `data/_archive_pre_fix/`（36.3 GB）。
**服务**：后端 `127.0.0.1:8077` → `data/a12_trainable/store`（health/registry/assets 200）· 前端预览 `http://localhost:4188/synlab/showcase`（200）· 周期提交循环每 15 分钟推送 GitHub。

---

## 一、已完成（均有实测证据）

### 平台与契约
| 项 | 证据 |
|---|---|
| 独立仓库 `relicweave-synlab` + 特征契约 `a12.obs.v1` | 已推送（`main`，20+ commits） |
| 结果信封 · canonical JSON/hashing · seed64 子流（PCG64）· 内容寻址 `AssetStore` · SQLite WAL 调度器（租约/围栏） | 全部落地 |
| Release profiles + `PROFILE_GATES` | SANDBOX_CORE 6 门真冻结（`scope_pending=[]`、`gate_overrides=[]`）；PILOT 诚实拒绝（10/12） |
| 6 asset packs；特征/标签/来源分离；`FORBIDDEN_FEATURE_FIELDS` | 泄漏门在跑，`bag_id` 已按裁决声明为采集上下文（命中 1→0 + 反例测试） |
| **采集契约** `capture_contract.json`（108 规格字段 / 133 文档指针）+ `rig_contract.md`（468 行）+ 35 行覆盖矩阵 | 覆盖 4 / 部分 9 / 缺失 22，已冻结 |
| **18 项裁决**落档 + `decision_defaults.json` + **工程政策 R1–R5** | `decision_record.md` / `engineering_policy.md` |
| **全链精度审计** | `precision_audit.md`（84 KB，8 节 + TOP5 + **两代 store 并排**） |

### 生成链（1–10 步）
| 项 | 证据 |
|---|---|
| 母体 **24 品种** | `audit_mother` **24/24 QA_PASS**；壁面夹逼缺陷已删；**V10 多壳守恒修复**（逐壳切割：6 片全水密、守恒 1.08e-07、单壳器型逐位不变） |
| 材料 **12 种** + 釉层 4 层 | grain 0.08–3.0 mm、孔隙 0–0.55、纤维周期 M08=14/M10=3.5/M11=5.5 mm、M07 透射 0.82；釉层真实厚度 **0.743/1.188/1.634 mm** |
| 花纹 **16 族** | 接缝 **0.0**、三维↔二维 **0.0/255** |
| **多块碎裂** | 后端 `warp_voronoi_cut`（默认）：**2–22 片**；片数律 **β=0.588±0.054、N0=2.5295、R²=0.8632**（平均误差 0.59 片）；38 点审计全达标（体积差 9.06e-08、重叠 0.0、**gap P95 1.97e-05 mm**、**共轭 P95 0.0**、水密 38/38）；接受率 **0.3125→0.8125**；4 片 **0.798 s**（比平面快 4–4.5×） |
| **三角化修复** | 16 组合面积全 **1.000000**；**平面逐位回归通过**；坏边 **8993→4369（−51%）**、**"用 1 次"边消失** |
| 三层真值（clean/physical/visible） | 已落地并分层提交 |
| **两端观测** | 12 obs/谱系、**6/6 R2 两端有观测**、`obs_semantics=physical_side_v2` 齐全 |
| 观测 3 路线 + 相机档 | **CoC 单位修复**（掩码 0.26–7.2% → **81–89%**；修复后 mask/物体 **99.27%**、uncertain **0.072%**）；**断面 2D 从 0 → 5.32%/6.67% 像素** |
| 退化 **31 轴 × 5 档** | **155/155 PASS**、**level 0 恒等 31/31**（hash 相等）；P03 漂移 **0.354 → 0.000348 mm（1018×）**、watertight False/43 边 → **True/0 边** |
| 关系与负例 | **合法负例 440**（`mate_absent` 规则；"自带邻片"1120→0，抽样 24/24 一致）；导出方向性补全 **1794→3588 行** |
| 出土上下文包 | `simulated=true`，含出土区/网格/层位/层深/袋号/坑位/批次/共存物/尺度参考 |
| §8 synthetic extras 九类 | 已实现并带标注（`rig_obtainable`/`synthetic_only`/`claim_allowed`） |
| **断口 ROI 特写** | mm/px **0.28041→0.07300（3.84×）**；断面像素 **335 038 → 20 987 921（62.6×）**；断面/物体 **2.73% → 96.95%**；2048 档 0.2 mm = **5.48 px**（过 4 px 门） |

### 训练与导出
| 项 | 证据 |
|---|---|
| **rank 首次真正训练** | `effective_queries` **0 → 44**；**rank loss 6.32830→6.17352→6.05966** |
| quality 监督 | 由假 `zeros((1,1))` → **(3,1,14)/valid=42** |
| 分块冒烟 | 19.63 GiB → **4.69 GiB（1/4.2）**，3/3 步通过 |
| 训练包 | 数据卡（328 项抽查全相符）· 加载器（`--check` exit 0，篡改判 3）· quickstart exit 0（5.06 s）· **zarr 读回与 npz 逐字节一致 18/18** |
| **导出三缺陷修复** | tokens 有效秩 **1→256**；`view_pos` 全零→T_WC（误差 0.0 mm）；`frame_id` 行号→**真实匹配 97.9%** |

### 环境与工程
| 项 | 证据 |
|---|---|
| **CUDA torch** | 2.11.0+cu128，sm_120 可用；matmul **18.1×**、fp16 **74.8×**、conv2d **35.3×（逐位相同）** |
| Blender GPU | 打通（实测 CUDA 优于 OptiX）；渲染通道与 CPU 分类通道**逐位相同** |
| **周期提交循环** | `tools/commit_loop.py`，每 15 分钟 + 编译门控；已推送 20+ commits（**不是会话内临时**） |
| 旧数据治理 | `data/_archive_pre_fix/`（36.3 GB，移动而非删除） |
| 服务可用 | 后端切最新库、前端预览恢复（U13 展示页 200） |

---

## 二、未完成

### A. 断裂（**当前重点**）
| 项 | 现状 |
|---|---|
| **断口几何仍平** | `Ra=1.103e-07 mm`；3/4 具 `<1 mm` Ra **恰好 0.000**；深度图均匀无浮雕 → **SDF 线（`2040a4a8`）正在做** |
| 坡度/幅度 | 模型 σ_r0 0.41 mm vs λ_min 0.65 mm → **坡度 P95 53°**（目标几度~20°） |
| 分带 Ra 非零 | `>1 mm` / `0.25–1 mm` / `<0.25 mm` 三带未全非零 |
| **轮廓崩边/次级裂纹** | **全仓零实现** |
| 材料断裂模式映射 | 陶颗粒/瓷致密/玻璃贝壳/竹木纤维——**未做**；`M11` 出现同心环但读感似木纹贴图 |
| 釉层台阶 | 交付几何**只有 `origin_kind`+`interface_id`**，无层通道 → 台阶不存在；需生成侧切 L01/L03 |
| `warped_partition` | **PENDING**（`warped.py` 80 KB 有底子）；`fracture_modes` **MISSING（无源码）** |
| 外观 A1/A2/A3 | 在跑（`465a7644`）：背光断口 · 默认档 SNR<0.25 · **面片感 84% 来自 `procedural_albedo` 逐面色块** |

### B. 数据与监督
| 项 | 现状 |
|---|---|
| correspondence | **0/9 对两侧可定位**——`id_map` face_id 空间与 `corr_face_*` 不一致（`LIN0009` 有 21 373 标签 > 该 mesh 3 660 面） |
| contradiction | **结构性不可达**（`synlab/**` 无任何代码写该列，`contradiction_source` 是死参数） |
| 22/31 退化轴 | **无"声明→实测"配对**；G01 系统性 **8.14–13.06%**、G08 **20.2%** 曾被 PASS 掩盖（`5ac48163` 全轴审计中） |
| QA 收紧 N9 | `roi_external_drift` 不进 `failure_codes` → 0.354 mm 也报 PASS（`0e2e204e` 在做） |
| 一阶/二阶模态 | P02/P04/P08 等非默认变体物化不足（全轴审计中） |
| 花纹现实性 | 连续性达标，**装饰章法/真实釉色统计未做**；**A05 继承检查仍 FAIL** |
| 独立母体 | **1 / 20** |

### C. 材料与外观
| 项 | 现状 |
|---|---|
| 缺材料 | **瓦片 · 水晶 · 竹筒**（各需器型族 + 物理量 + 断裂模式） |
| 玻璃/水晶 | 透射折射渲染**未验证**（M07 沉闷） |
| 成像分辨率 | 渲染中位 **0.27193 mm/px** vs 契约 0.039–0.195；0.195 档仅 **3.33 px/λ_min** < 合同 4 px |
| 软件光栅器 | z 缓冲**非透视正确**（掠射面差 **35.6 mm**，目前靠射线投射绕开） |
| 纹理 | 程序化高频纹理与像素混叠（**摩尔纹**）——A3 一并修 |
| L1/L2 LOD | 未物化（`fast_simplification` 依赖反复） |
| 标定/尺度字段 | `calibration_id`/`rig_calibration_rev`/`intrinsics_profile_id`/`scale_drift`/`r_eff_mm` **各 0 命中**；`f` 三支并存 |

### D. 工程与发布
| 项 | 现状 |
|---|---|
| UI 合成向导 U14 | **未交付**（现有 12 页 + U13 展示页可用） |
| Blender 吞吐 | 每视图一进程（**启动占 22.2%**）；端到端最好 2.14×、等负载 1.02× |
| 稠密 MVS | `MVS_NOT_AVAILABLE`（pycolmap 无 `patch_match_stereo`/无 CUDA） |
| 验收 | **FAIL 4（A05/A06/A09*/A24）· PENDING 6 · NOT_RUN 6 · NA 7**（*A09 已修待重跑） |
| PILOT | **10/12**（差 `train_dev_lineage`、`leakage_audit`） |
| Release 代际 | 12 个旧 release 受几何修复影响，**未发新版**（应标 `superseded`） |
| 基线 | `acceptance_summary` 等**需重算** |
| 主仓集成 | A3/A4 schema 缺失 → `MAIN_REPO_INTEGRATION_PENDING` |
| 规模 | L0 100% · L1 ≈15% · **L2/L3 0%** |

---

## 三、当前并行战线（5 条）

| 队友 | 战线 | 写域 |
|---|---|---|
| `2040a4a8` | 断裂几何（SDF 隐式薄片） | 新建 `synlab/fracture/implicit/**` |
| `465a7644` | 外观 A1/A2/A3 | `synlab/observe/**` |
| `5ac48163` | 退化轴全轴审计 | `synlab/{physical,degrade}/**` |
| `0e2e204e` | 协议一致性 + QA 收紧 + 难负例表 | `synlab/qc/**` + 测试 |
| `d9e3caa9` | 合并"实验就绪"导出 | `synlab/storage/**` + tools |

**完成判据（断裂）**：① `hist=={"2"}`/坏边 0/水密 ② 平面逐位回归未破（已达标，须保持）③ rough 共享面 **P95 < 0.02 mm** ④ 形态学审计+共轭+`Ra`/`Rz` 有实测 ⑤ 坡度 **几度~20°** ⑥ **深度图出现真浮雕 + RGB 无程序化条纹 + 能辨认断口 + 材料间差异明显**（由 Lead 亲自判读）。
