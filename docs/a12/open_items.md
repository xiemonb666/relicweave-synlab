# A12 未完成项清单与在修追踪

**文档目的**：把"还没修好的东西"变成**可追踪、可验收、可复算**的清单，避免口头记忆。
**快照时间**：2026-10-02 17:0x（本地）。
**数据基线**：最新库 `data/a12_trainable/store`（463 资产）· 最新包 `data/a12_exports/negfix/next_experiment/training_package` · 旧代已归档 `data/_archive_pre_fix/`（36.3 GB）。
**相关文档**：`precision_audit.md`（精度实测）· `modality_census.md`（模态普查）· `rig_contract.md` + `configs/a12/capture_contract.json`（扫描台契约）· `decision_record.md`（18 项裁决）· `relation_negatives.md`（负例与 rank 首训）· `fracture_realism.md` / `fracture_calibration.md`（断口）· `training_run.md` / `export_guide.md`（训练与导出）。

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

## 复算入口

```powershell
$py = ".venv\Scripts\python.exe"
& $py tools\load_package.py --package data\a12_exports\negfix\next_experiment\training_package
& $py tools\check_data_quality.py --store data\a12_trainable\store      # 0=可训练 / 3=不可训练
& $py -m synlab.cli acceptance --profile SANDBOX_CORE --json
& $py data\a12\reports\precision_audit.json  # 见 precision_audit.md 的探针清单
```

**跟踪纪律**：在修项完成后，其行应从第一部分移到"已完成"，并在对应专项文档留 before/after 实测；未开工项开工时补上"负责 + 硬指标"两列。
