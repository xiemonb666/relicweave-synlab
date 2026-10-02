# 观测侧证据：真实 COLMAP MVS 子集与像素/展示合同（A14 / A24 / A25）

本文件记录 **真实命令、退出码与实测数值**，对应计划第 14 节（观测几何、G01–G07、G08、
实际 MVS 子集 14.4）与第 30.3 节（像素中心、缩放与展示单位），阈值取自
`configs/a12/qa_protocol_v1.json`。

新增模块（本任务写入范围内）：

| 文件 | 作用 |
|---|---|
| `synlab/cameras/audit.py` | `audit_pixel_contract(store=None) -> dict`，A25 报告生产者 |
| `synlab/observe/mvs_subset.py` | `run_mvs_subset(...)`（A14）、`audit_source_dependency(...)`（A24） |
| `tests/a12/observe/run_mvs_evidence.py` | 证据运行器（三步、退出码见下） |
| `tests/a12/observe/test_pixel_contract.py`、`test_mvs_subset.py` | 可复跑验收测试 |

报告落盘位置（`synlab.qc.acceptance` 的 `Ctx.report()` 从 `<store_root>/reports/` 读取）：

- `data/a12/reports/pixel_contract.json`（A25）
- `data/a12/reports/mvs_subset.json`（A14）
- `data/a12/reports/source_dependency_audit.json`（A24）
- 中间产物：`data/a12/reports/mvs/**`（帧 PNG、掩码、COLMAP 数据库、稀疏/稠密工作区、
  每步日志与 argv JSON）

> 说明：本次没有向 `data/a12_demo/**` 写入任何文件。`_report_roots()` 只在 store 不是
> 那个只读演示库时才把报告镜像到 `<store_root>/reports/`。

---

## 1. 环境与能力探测（实测，不假设）

```
pycolmap 3.11.1
has_cuda = False
has_patch_match_stereo = False        # 该构建根本不导出该符号
has_stereo_fusion = True
standalone colmap binary = None       # 本机没有独立 colmap 可执行文件
```

因此：稀疏 SfM 可以真跑；`patch_match_stereo` 不可用 → dense 阶段按计划 14.4 记为
`MVS_NOT_AVAILABLE`，**绝不用 clean mesh 或理想深度回填**。`stereo_fusion` 仍然真跑
（它存在），并在日志里如实记录 0 点融合的原因。

另外一个必须记录的实测事实：`pycolmap 3.11.1` 的 `match_exhaustive(db, device=cpu)`
用 **默认实参** 构造的 `SiftMatchingOptions` 是零值（`max_num_matches=0`），COLMAP 会
`CHECK failed: max_num_matches > 0` 直接 **abort 整个进程**（实测退出码
`-1073740791`）。本模块因此显式构造 `SiftMatchingOptions()` 并逐字段赋值后传入。
（`synlab/observe/routes.py::route_photo_mvs` 走的是默认实参那条路，属于本任务写入范围外，
仅在此记录现象。）

---

## 2. 命令与退出码

全部在仓库根执行，Python 为 `.venv\Scripts\python.exe`。

| # | 命令 | 退出码 |
|---|---|---|
| 1 | `python tests/a12/observe/run_mvs_evidence.py --skip-mvs --skip-source` | **4**（A25 合同未全绿，见 §4.4） |
| 2 | `python tests/a12/observe/run_mvs_evidence.py --frames 12 --width 800 --height 600 --skip-pixel --skip-source` | **0** |
| 3 | `python tests/a12/observe/run_mvs_evidence.py --skip-pixel --skip-mvs --audit-frames 4` | **0** |
| 4 | `python -m pytest tests/a12/observe/test_pixel_contract.py -q` | **0**（8 passed） |
| 5 | `python -m pytest tests/a12/observe/test_mvs_subset.py -q -k "<单项>"` | **0**（逐项，见 §6） |

退出码约定：`0` 该步跑完并写出报告；`3` 抛异常（保留已落盘的中间证据）；`4` 像素/展示合同
`ok=false`。注意第 2 步退出码是 `0` 而报告里 `pipeline_ok=true / dense_status=MVS_NOT_AVAILABLE`
——**稠密阶段不可用是实测结论，不是崩溃**，因此不当作命令失败。

---

## 3. A14：实际 MVS 子集（`data/a12/reports/mvs_subset.json`）

### 3.1 输入：真实母体 + 软件光栅多视图帧

- 母体：`data/a12_demo/store` 已提交资产 `asset_167bef6a43a93438ec26`
  （`source=COMMITTED_ASSET`，`mother_id=a12_demo_V01`，`V01/M03`，7008 面，
  几何 hash `sha256:510bb321…`）。store 里没有母体时会调用真实
  `synlab.mothers.api.create_mother`（本任务未触发该分支）。
- 帧：`synlab.observe.routes.render_views` 的软件光栅，12 帧（3 方位 × 4 层高），
  交付尺寸 800×600，`SIMPLE_RADIAL`，工作距离 220 mm，0.0804 mm/px；
  写出真实 PNG（`data/a12/reports/mvs/subset/mother_00/images/m00_v_00{0..11}.png`）
  与部署掩码（`masks/m00_v_000.png.png`，COLMAP 掩码命名约定）。

渲染参数选择（均记录在报告 `config` 与每帧元数据里）：

- `effective_gain = 1e4`：**实测发现** `ImagingSpec` 默认 `effective_gain=1.0` 时
  `Poisson(g·x)/g` 的每像素平均光子数 < 1，800×600 渲染退化成 1–2 px 的饱和噪点，
  SIFT 在 8 视图上只匹配到 30 个特征对（`view_000` 只有 7 种颜色）。
  把光子尺度显式设为 1e4 后恢复为可匹配的表面纹理。
- `coc_px_threshold = 1e6`：渲染器的 CoC 启发式（`render.py::circle_of_confusion_px`）
  在 f_px≈547 时对 220 mm 处物体给出 CoC p95 ≈ 239 px，默认阈值 0.75 px 会把整个物体
  判为 `uncertain`，部署掩码覆盖率降到 5e-5（`deployment_mask_from_render` 之后近乎全黑）。
  阈值提高后掩码覆盖率 = 0.129（记录在 `mothers[].mean_mask_coverage`）。
  这两项都是**渲染配置**，不是对观测流程的修改。

### 3.2 真实 pycolmap 流水线（每步 argv、日志、状态全部落盘）

| # | 阶段（argv 见 `argv_log`） | 状态 | 秒 | 捕获的 COLMAP 日志 |
|---|---|---|---|---|
| 1 | `pycolmap.extract_features`（掩码开启，`mask_path=masks`） | OK | 2.88 | 6862 B |
| 2 | `pycolmap.match_exhaustive`（`max_num_matches=32768`, `device=cpu`） | OK | 1.59 | 687 B |
| 3 | `pycolmap.incremental_mapping`（`multiple_models=0`） | OK | 1.39 | 83654 B |
| 4 | `pycolmap.extract_features`（掩码关闭，重试） | OK | 3.17 | 6802 B |
| 5 | `pycolmap.match_exhaustive` | OK | 4.87 | 680 B |
| 6 | `pycolmap.incremental_mapping` | OK | 6.23 | 80709 B |
| 7 | `pycolmap.undistort_images`（→ 真实 COLMAP dense 工作区） | OK | 0.57 | 1574 B |
| 8 | `pycolmap.stereo_fusion` | OK | 0.04 | 4466 B |

日志文件：`data/a12/reports/mvs/subset/logs/NN_<stage>.log`（fd 级重定向捕获 C++/glog 输出），
每步同时写 `NN_<stage>.json`（argv、状态、秒、返回码、日志字节数、日志尾部、异常栈）。
`undistort_images` 产出的工作区含 `sparse/`、`images/`、`stereo/patch-match.cfg`、
`stereo/fusion.cfg`、`stereo/{depth_maps,normal_maps,consistency_graphs}/` 以及 COLMAP 生成的
`run-colmap-geometric.sh` / `run-colmap-photometric.sh`。

### 3.3 实测结果

| 指标 | 实测值 |
|---|---|
| `attempted`（分母） | 12 |
| `registered_frames` / 注册帧率 | **12 / 12 = 1.000** |
| `sparse_points` | **1824** |
| `reprojection_error_px`（均值） | **0.4543 px** |
| 平均 track 长度 / 每注册帧观测数 | 5.887 / 894.8 |
| 估计相机 | `SIMPLE_RADIAL`，800×600（单相机，`CameraMode.SINGLE`） |
| `dense_points` | **0** |
| `dense_status` / `failure_code` | `MVS_NOT_AVAILABLE` |
| `seconds`（整跑） | **30.82 s** |
| `data_scope` / `real_capture` / `real_calibration_ok` | `SYNTHETIC_RENDER` / `REAL_CAPTURE:PENDING` / `false` |

两次尝试（`attempts`）如实保留：

| 尝试 | 掩码 | 掩码覆盖率 | 注册帧 | 稀疏点 | 重投影 |
|---|---|---|---|---|---|
| `m00` | 使用 | 0.135 | 2 / 12 | 274 | 0.175 px |
| `m00_nomask` | 未使用 | 0.135 | **12 / 12** | 1824 | 0.454 px |

上述数值来自最终一次运行（`data/a12/reports/mvs_subset.json` 的时间戳）。同一配置重复运行
时点数在 ±0.2% 内浮动（本机观测：1824 / 1827 点，重投影 0.4543 / 0.4548 px），
原因是 COLMAP 匹配阶段的 RANSAC 验证在本构建上不可逐位重复（§4 有量化）。

即：部署掩码把 SIFT 特征饿死（只在 13.5% 的“确定”像素里提特征），本模块据此重试一次并
把两次尝试都写进报告 —— 没有把失败那次丢掉，也没有把成功那次伪装成唯一一次。

稠密阶段失败原因（原样保留在 `dense.failure_reason`）：

> `pycolmap 3.11.1 exposes no patch_match_stereo symbol (has_cuda=False, standalone colmap
> binary=None); the dense MVS stage cannot be executed here and is not reported as a
> successful dense run`
> `stereo_fusion produced 0 dense points because the patch-match depth/normal maps do not
> exist on this host`

`stereo_fusion` 确实执行了，输出 PLY 只有 242 B（0 点），日志里 COLMAP 自己说
`Could not fuse any points. This is likely caused by incorrect settings - filtering must be
enabled for the last call to patch match stereo.` —— 这是实测日志，不是推断。

### 3.4 合法失败路径

- 抽特征/匹配/`mapper` 抛异常，或 `incremental_mapping` 无模型，或
  `registered_frames < min_registered_frames` → **`STOP_SFM`**（保留分母，写 `failures`）。
  实测示例：4 帧/480×360 的冒烟配置只注册 2 帧（`< 3`）→ `STOP_SFM`，报告仍完整落盘。
- `undistort_images` 失败或没有 `sparse/` → **`MVS_FAILED`**。
- `patch_match_stereo` 符号缺失 / 无 CUDA / 融合 0 点 → **`MVS_NOT_AVAILABLE`**。
- 任何情况下都不会用 clean mesh、渲染深度或理想内外参填补重建结果；重建输入只有
  已交付的 PNG 与掩码（§4 用实验证明）。

### 3.5 计划 14.4 的规模缺口（不掩饰）

计划要求“先用 2 母体 / 20 片验证真实管线，再冻结约 20 母体 / 400 片”，每片 30–120 有重叠帧。
本机（会被直接杀掉的重负载 Python + 31 GB 内存）实跑的是 **1 母体 × 1 整片表面 × 12 帧**，
报告 `subset` 字段显式记录 `plan_frames_per_fragment=[30,120]`、
`planned_full_subset={"mothers":2,"fragments":20}`、`fragment_kind=WHOLE_MOTHER_SURFACE`。

---

## 4. A24：来源依赖审计（`data/a12/reports/source_dependency_audit.json`）

这一项是**实验**，不是读代码：给同一条流水线 4 帧真实渲染图，把“真值位姿表”放在
它可能被读到的两个位置（工作区规范路径 `gt_poses_corrupted.json` 与
`SYNLAB_GT_POSES` 环境变量）并注入 37° 旋转 + 668 mm 平移，然后比较重建结果。

| 条件 | 注册帧 | 稀疏点 | 重投影 px | matches | keypoints hash（前 8） |
|---|---|---|---|---|---|
| `true`（真值表） | 2 | 560 | 0.1632 | 2816 | `a36bce83` |
| `repeat2/3/4`（同输入重复 3 次） | 2 | 561/560/560 | 0.1571/0.1632/0.1632 | 2817/2822/2812 | `a36bce83`（全部相同） |
| `corrupt`（错误真值表） | 2 | 559 | 0.1612 | 2818 | `a36bce83`（**与 true 逐位相同**） |
| `control`（镜像翻转图，负对照） | 2 | 566 | 0.1629 | 2851 | `c099b885`（**不同**） |

- 特征提取是**逐位可重复**的：真值/错误真值/重复四次的 `keypoints_hash` 完全一致
  （4826 个关键点/帧组），镜像对照则不同 → 说明该判据对输入敏感（不是空判据）。
- 匹配阶段的 RANSAC 验证在本构建上不可逐位重复（同输入 4 次 `matches` = 2816–2822），
  因此重建比较用的是**实测重复带**：点数带 = [560,561]，重投影带 = [0.1571,0.1632]；
  容差 = `max(1% 点数, 带+2)` = 6 点、`max(1e-3, 3×带)` = 0.0185 px。
  错误真值条件的偏差 = **1 点 / 0.0020 px**，落在带内。
- `pose_priors` 表在真值与错误真值两个数据库里都是 **0 行**（没有任何 EXIF/先验位姿进入 SfM）。
- SfM 输入目录只含 `.png`（帧与掩码），`forbidden_artefacts = []`（无 `.npy/.npz/.pfm/depth*/scale*`）。
- 尺度来源记为 `kind=NONE`：COLMAP SfM 本身无尺度，本流程不提供任何尺度靶，
  重建停留在任意单位，报告不对 mm 作任何声称。
- 帧的 `source_kind` 全部是 `SENSOR_SIM`（模拟器渲染），`real_capture` 为 `PENDING`。
- 整跑 16.4 s，18 个阶段（4 次同输入 + 1 次错误真值 + 1 次镜像对照，各 3 阶段）
  的 argv 与日志全部落盘在 `data/a12/reports/mvs/source_audit/logs/`。

审计 5 项检查全部 PASS（`data/a12/reports/source_dependency_audit.json` 的
`checks.{frame_source_kind,gt_pose_invariance,control_is_sensitive,pose_priors_empty,no_depth_or_scale_input}`）。

> 审计使用的帧集刻意选成**单方位 4 视图强重叠簇**（`--audit-frames 4`）。原因也是实测：
> 12 视图那种“两方位簇”的图在 `mapper` 初始像对抽签下会在 2/3/8 帧之间跳变，
> 重建级比较就失去意义；特征级判据不受影响，仍然逐位精确。

---

## 5. A25：像素中心 / 缩放 / EXIF / COLMAP 往返 / 100 mm GLB（`data/a12/reports/pixel_contract.json`）

阈值：`A02_max_px_error = 0.05`、`A02_max_mm_error = 0.001`（读自
`configs/a12/qa_protocol_v1.json`）；展示层 100 mm 立方体 `≤ 1e-9 m`（计划 30.3 / 20.14.1）。

### 5.1 实测误差

| 检查 | 实测 | 判定 |
|---|---|---|
| `cx_colmap = cx_cv + 0.5` / `cy` | 0.5 / 0.5（精确） | PASS |
| K 往返、像素往返（`colmap_convention`→`colmap_unconvention`、`to/from_colmap_pixels`） | 0.0 / 0.0 px | PASS |
| **真实 pycolmap 相机往返**（`pycolmap.Camera(PINHOLE)` 的 `img_from_cam`/`cam_from_img` 对同一点） | 正/反向各 **0.0 px**，归一化 0.0 | PASS |
| 非整数缩放 0.37/0.63 | 2.8e-14 px / 1.2e-13 mm | PASS |
| 奇数→偶数 641×481→320×240 | 2.8e-14 px / 1.3e-13 mm | PASS |
| 偶数→奇数放大 1.7/1.3 | 1.1e-13 px / 1.3e-13 mm | PASS |
| 非零 crop 原点 (37,19) / (64,48) | ≤5.7e-14 px / ≤1.3e-13 mm | PASS |
| crop + 非整数缩放 (13,7,1.25,0.8) | 1.1e-13 px / 1.2e-13 mm | PASS |
| letterbox（每例再加 pad (23,41)） | ≤1.1e-13 px / ≤1.3e-13 mm，`K''=A K`，纯平移 | PASS |
| **非零畸变**（OPENCV `k1=-0.12,k2=0.031,p1=0.0021,p2=-0.0016,k3=-0.0042` + 0.5 缩放） | 0.0 px / 1.2e-13 mm | PASS |
| EXIF 1–8 全档：像素实际搬移 + `K_new = A K` + 尺寸交换 | 8/8 通过，标记像素 (111,222)→(258,111) 精确落位 | PASS |
| 展示层 100 mm 立方体 → GLB 边 | 12 条边均值 0.10000000000000002 m，**最大误差 0.0 m** | PASS |
| 展示层反算 UI 量尺 | **100.0 mm**（误差 0.0），往返误差 0.0 mm | PASS |
| 变换只应用一次（双重应用可检出） | 组合矩阵误差 0.0，二次应用后尺寸 ×1e-3 → 可检出 | PASS |
| 前端 `frontend/src/lib/display.ts` 的两个矩阵与后端常量逐元素一致 | 一致，`MM_PER_M=1000` | PASS |

### 5.2 唯一失败项：`synlab/api/display.py::authority_to_display`（写入范围外）

`audit_pixel_contract` 还对着 GLB 派生路径用的矩阵检查了同名辅助函数：

```
authority_to_display(100 mm 立方体顶点) / transform_vertices(同一点) = 1e6
```

即该函数把 mm→m 写成了 `×1000`（正好是“反向矩阵应用两次”的 1e6 因子），与它自己的
docstring、`T_DISPLAY_AUTHORITY`（0.001 对角）以及前端 `display.ts` 都矛盾。
**但它在生产代码里没有任何调用点**：GLB 导出走
`transform_vertices`（`synlab/api/handlers.py:550`、`tools/build_demo_assets.py:402`），
量尺反算走 `display_to_authority`（本次实测 100.0 mm、往返 0.0 mm 都正确）。

因此 A25 的 `ok=false` / `status=FAIL`，`metrics.failing_checks=["display"]`，
`metrics.blocking_defects[0]` 给出文件、函数、实测比例、期望语义与一行修法。
`audit.py` 不在本任务允许的写入范围内修改 `synlab/api/display.py`，故如实上报：

```python
# synlab/api/display.py:69-71 现状（错）        建议
out[:, 0] = points[:, 0] * MM_PER_M * scale   →  points[:, 0] / MM_PER_M * scale
out[:, 1] = points[:, 2] * MM_PER_M * scale   →  points[:, 2] / MM_PER_M * scale
out[:, 2] = -points[:, 1] * MM_PER_M * scale  →  -points[:, 1] / MM_PER_M * scale
```

修好后重跑第 1 条命令即可让 A25 转为 PASS（其余检查已全绿）。

### 5.3 验收项实测状态（`synlab.qc.acceptance`，`--root data/a12`）

| 项 | 现状 | 依据 |
|---|---|---|
| **A14** 实际 MVS 子集 | **PENDING** | `pipeline_ok=true`（12/12 注册）+ `real_calibration_ok=false` ⇒ pipeline=PASS、real_calibration=PENDING ⇒ 总状态 PENDING（计划 14.4：无实拍数据不得给校准结论） |
| **A24** 观测来源/DAG | **PASS** | 5 项来源依赖检查全绿 |
| **A25** 坐标/展示 | **FAIL** | 除 §5.2 外全部通过；失败项指向写入范围外的 `synlab/api/display.py` |

---

## 6. 可复跑测试

```
.venv\Scripts\python.exe -m pytest tests/a12/observe/test_pixel_contract.py -q     # 8 passed, exit 0
.venv\Scripts\python.exe -m pytest tests/a12/observe/test_mvs_subset.py -q         # 见下
```

`test_pixel_contract.py`（8 项）一次跑完通过。`test_mvs_subset.py`（7 项，含 4 项 `slow`）
在同一进程里连跑时**两次被本机直接杀掉**（无 traceback，`exit -1`，与 §7 第 3 条记录的现象一致），
因此按测试逐项运行、全部通过：

```
pytest tests/a12/observe/test_mvs_subset.py -q -k "images_and_stage_logs"      # exit 0
pytest tests/a12/observe/test_mvs_subset.py -q -k "dense_stage_is_never_faked" # exit 0
pytest tests/a12/observe/test_mvs_subset.py -q -k "source_dependency"          # exit 0
```

测试断言的都是**实测判据**而不是快照：A25 的 px/mm 误差、8 档 EXIF 像素搬移、
100 mm 立方体 ≤1e-9 m、A14 的报告字段与真实图像/日志文件存在性、
“无 PatchMatch 时 dense 必须停”的诚实性、A24 的五项来源检查。

---

## 7. 缺口与后续动作

1. **无实拍数据** → `A14.real_calibration` 保持 `PENDING`，`real_capture=REAL_CAPTURE:PENDING`，
   `real_calibration_ok=false`。合成渲染子集与实拍子集必须继续分开登记（计划 14.4）。
2. **稠密 MVS 不可用**：本机 pycolmap 3.11.1 无 `patch_match_stereo` 且 `has_cuda=False`，
   也没有独立 `colmap` 可执行文件。要拿到 dense 点云，需要装带 CUDA 的 pycolmap 或
   COLMAP 命令行版；在此之前 `dense_points` 只能为 0 并记 `MVS_NOT_AVAILABLE`。
3. **规模**：1 母体 × 1 整片 × 12 帧，未达计划 2 母体/20 片/每片 30–120 帧。
   本机对重负载 Python 会直接杀进程（本轮实测多次无 traceback 的 `exit -1`），
   故按“每步单独进程、立即落盘、控制规模”执行。
4. **片级子集**：本次片段是“整片母体表面”（`fragment_kind=WHOLE_MOTHER_SURFACE`）；
   断裂后的 20 片代表清单（素面/重复纹样/釉面/薄片/U 近档/支撑遮挡）尚未跑。
5. **掩码**：部署掩码在 12 帧上只覆盖 13.5% 的“确定”像素，直接把 SIFT 饿到 2/12 注册；
   实际使用需要重新审定 `render.py` 的 CoC 阈值/掩码生成策略（属观测层其他文件，
   本次只在报告与本文档记录，并保留两次尝试的分母）。
6. **匹配阶段不可逐位重复**：`match_exhaustive` 的 RANSAC 验证在同输入下 matches 浮动
   ±0.1%；A24 已用“实测重复带 + 负对照”的方式给出可判定结论，但这意味着任何
   “逐位相等”式的 SfM 回归判据在本机构建上都不成立。
7. **越界缺陷**：`synlab/api/display.py::authority_to_display` 的 1e6 尺度错误（§5.2），
   以及 `render.py` 默认 `effective_gain=1.0` 造成的“光子饥饿”渲染（§3.1）——
   两者都在本任务写入范围之外，仅记录并给出最小修法。
