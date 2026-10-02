# A12 现实性差距表（合成观测 vs 真实可采集数据）

用途：本轮目标是把"合成数据尽量贴近真实可采集的数据"，训练任务是「输入一块碎片 → 检索其邻片
候选」，策略是先合成大数据预训练、再用真实数据微调。因此本表逐条对照"真实采集会有什么"与
"本仓库现在实际有什么"。

证据纪律
--------
* **现状**一列只写代码里真实存在的字段、注册表值或本轮实测值，并给出可复核的位置（文件:行/函数）
  或报告文件；没有实测的地方明确写"未实测"。
* **可否在合成侧补**只有三种答案：`可补`（不需要新数据，只需建模/接线）、`部分可补`
  （能补统计形态，补不出真实内容）、`不可补`（必须有真实对象/真实设备/真实标定）。
* `ideal_visible` / `proxy_scan` 的产物一律不称"真实采集"；本轮新增的 `photo_mvs` 路线也只是
  "真实 SfM 管线跑在合成渲染上"（`ROUTE_SPECS[photo_mvs].claim_boundary` 原文：
  `real SfM/dense pipeline on synthetic renders; REAL_CAPTURE pending`）。

复现入口
--------
| 内容 | 命令/文件 |
| --- | --- |
| 真实感配置 | `configs/a12/realistic.yaml`（`synlab.cli validate --config configs/a12/realistic.yaml` → exit 0） |
| 现实性桥接层 | `synlab/observe/realism.py`（档位表、畸变政策、掩码政策、标记） |
| 批量跑谱系 | `tests/a12/observe/run_realistic_lineage.py --mode run --leg realistic --only 2,3` |
| 同场景对照 | 同文件 `--leg control`（`ideal_visible` + 软件光栅器 + 恒等成像链） |
| 产物对照探针 | 同文件 `--mode probe --only 2`（软件光栅器，同一块已提交碎片，4 变体） |
| 汇总报告 | `data/a12/reports/realistic_pilot.json` |
| SfM 失败归因探针 | `data/a12/reports/_probe_sfm_matches.json`（同一批图像，开/关掩码各跑一次） |

---

## 1. 逐条差距表

### 1.1 相机内参（焦距/主点/像素尺度）

| | 内容 |
| --- | --- |
| 真实现状 | 每台设备用靶标标定得到 K，带标定残差；同一台手机不同对焦组的 K 不同 |
| 合成现状 | `synlab/cameras/profiles.py::_TIER_SPECS` 三个档位由**标称**参数算出：`CAM_MID_V3` = sensor_width 7.6 mm、focal 5.2 mm、f/2.2、image 4000×3000 ⇒ `f_x=f_y=2736.84 px`、`cx=1999.5, cy=1499.5`；字段 `calibrated=false`、`meta.calibration_status=UNCALIBRATED`、`meta.calibration_source=NOMINAL_SIM`、`meta.pending=[REAL_CALIBRATION_PENDING, FOCUS_GROUP_SWEEP_PENDING]` |
| 差距 | 数值是"像机会有的量级"，不是这台设备的实测；没有标定残差分布；`u` 移动改变 K 的映射（`transform_profile_u`：`group_delta = clip(0.06·Δu, ±0.25) mm`）是工程假设 |
| 可否 | **部分可补**（可补"标定误差"的统计形态，补不出真实 K） |
| 补法 | 给档位加一个标定残差模型（焦距比例误差、主点偏移、随 `u`/对焦组的耦合项），从公开手机标定数据取先验；把 `u_move_forbidden` 与残差一起写进 `ViewFrame.meta` |
| 代价 | 小（`cameras/profiles.py` + 一个残差采样函数；需先有先验来源，否则只能给"假设值"并标注为假设） |
| 补齐条件 | 在本机对真实手机跑一次靶标标定（≥15 张棋盘图），把结果写进新档位（`calibrated=true`、`calibration_refs` 指向靶标图像与残差报告） |

### 1.2 镜头畸变

| | 内容 |
| --- | --- |
| 真实现状 | 手机广角有 1–5 % 量级的径向畸变 + 切向项；未标定时它真实存在于交付图里 |
| 合成现状 | 三个档位都带 OpenCV `dist`：`CAM_MID_V3 = [-0.033, 0.008, 0.0006, -0.0005, -0.0018]`（k1,k2,p1,p2,k3）、`camera_model=OPENCV`；**软件光栅器直接投影出畸变**（实测轮廓：在档位原生 4000×3000 上畸变最大像素位移 `CAM_MID_V3=62.69 px`、`CAM_LOCAL_V3=72.01 px`、`CAM_GLOBAL_V3=99.70 px`，见 `realism.distortion_evidence`）；**Blender worker 渲染理想针孔，遇到非零畸变默认拒绝**（`synlab/observe/blender.py::build_config` → `ENV_CAPABILITY_MISSING`） |
| 差距 | 两条腿的"畸变"不对称：控制腿（软件）交付**带畸变**的图，真实感腿（Blender）按声明的 `distortion_policy=undistort` 交付**去畸变针孔**图（交付帧 `dist=None`、provenance 记录 `undistorted_from`）。而且 `undistort` 是"渲染针孔相机"而不是"渲染畸变图后 `cv2.undistort`"，因此**没有**真实去畸变的重采样损失与视场裁切 |
| 可否 | **可补** |
| 补法 | 二选一：(a) 对 Blender 渲染的线性图施加显式畸变重采样（把标称模型作用到图像上，K 同步）；(b) 该档位回落软件光栅器（此时畸变由后端直接投影，但失去 Cycles 光传输）。政策已由 `realism.resolve_distortion_policy` 强制显式声明，`policy=None` 直接抛 `EXPERIMENT_PROTOCOL_VIOLATION`，不存在静默默认 |
| 代价 | (a) 中等（渲染后加一步 warp + K 复核，需新增像素级测试）；(b) 小（换后端即可，但渲染质量下降） |
| 补齐条件 | 真实标定的畸变系数（含残差）才能把"去畸变"变成有依据的操作；否则只能声明为标称模型 |

### 1.3 曝光、噪声、传感器

| | 内容 |
| --- | --- |
| 真实现状 | ISO/快门/光圈决定散粒噪声与读出噪声，另有暗电流、PRNU、坏点、卷帘快门 |
| 合成现状 | `ImagingSpec` 有真实执行点：`exposure_ev`（在光子计数**之前**）、`effective_gain`（`y=Poisson(g·x)/g`）、`read_noise_sigma`、`sensor_saturation`、`black_level`、`digital_gain`、`white_balance`、`response`、`sharpening`、`denoise`（`synlab/observe/imaging.py`），每个阶段都写进观测的 `imaging_stages`。真实档位表见 `realism.AXIS_LEVELS`（与已注册轴逐字一致，测试 `test_level_ladders_are_the_registered_axis_ladders` 校验） |
| 差距 | (1) **冻结批产路径的成像链实际上是"光子饥饿"的**：`ObservationConfig` 没有任何成像字段，`pipeline._resolve_observe_spec` 不设 `effective_gain`，于是链条用默认 `1.0`。实测（`_probe_sfm_matches.json`）：控制腿交付的 1024×768 PNG 只有 **8 个灰度级**、Laplacian 方差 ≈2.1e4（噪声主导）、12 张图合计只匹配出 **66 对**、无法重建（`STOP_SFM`）。这不是"理想的真实图"，而是 1 bit 量级的噪声图。(2) 没有暗电流/PRNU/坏点/卷帘。(3) 噪声档位一旦选定就全批固定，不随 ISO/曝光时间变化 |
| 可否 | **可补**（形态）/ **部分可补**（真实噪声指纹） |
| 补法 | 已补：真实感档位把 `I03`（`photon_gain`+`read_sigma` 捆绑）开到 level 1 = 16000/0.002；要补噪声指纹需新增算子（暗电流、PRNU 增益场、坏点表），并让档位随"假设 ISO"变化 |
| 代价 | 小（档位接线，本轮已做）；新增算子为中等（每个算子要有 `measure` 的真实量，`synlab/degrade` 框架已给出接口） |
| 补齐条件 | 真实相机在固定 ISO/快门下拍平坦场（flat-field）与暗场，才能得到 PRNU/暗电流/读噪声的**实测**参数 |

### 1.4 模糊（PSF/景深/运动）

| | 内容 |
| --- | --- |
| 真实现状 | 镜头像差 + 衍射 + 离焦 + 手抖，PSF 随视场位置与深度变化 |
| 合成现状 | `ImagingSpec.defocus_sigma_px`（高斯 PSF）+ `defocus_depth_dependent`（按深度混合近/远两个 PSF）+ 曝光期运动积分（`motion_samples`/`motion_amplitude_px`）；真实感基线取 level 1 = 0.5 px |
| 差距 | PSF 不随视场位置变化（无像差模型）、衍射极限未与 f/# 挂钩、运动项默认关闭；深度相关只是两点混合，而 Blender 端的 `uncertain` 通道又用**标称** f/2.2 的 CoC 判定（见 1.12） |
| 可否 | **部分可补** |
| 补法 | 用一张 PSF 网格（视场位置 × 深度）替代单一 sigma；把 CoC 与已施加的 PSF 绑定（施加了多少模糊就标多少不确定） |
| 代价 | 中等（成像链扩展 + 逐像素 PSF 卷积的性能预算） |
| 补齐条件 | 真实镜头的 PSF/MTF 实测（刀口法或星点法）才能谈"像真实的模糊" |

### 1.5 压缩与编码

| | 内容 |
| --- | --- |
| 真实现状 | 手机交付 JPEG（通常 4:2:0 子采样、q≈85–95）或 HEIC |
| 合成现状 | `ImagingSpec.encode` = PNG/JPEG，`jpeg_quality` 可设；真实感基线 = JPEG q90（`ImagingSpec.jpeg_quality=90`），观测带 `ISP_PROXY`/`JPEG_PROXY` 标签 |
| 差距 | `jpeg_subsampling` 字段**不是**子采样开关：`imaging.py` 里非零时只加了 `cv2.IMWRITE_JPEG_OPTIMIZE`（优化霍夫曼表），因此交付图是 4:4:4，真机几乎总是 4:2:0；没有 HEIC、没有多代重压缩 |
| 可否 | **可补** |
| 补法 | 用 `cv2.imencode` 的 sampling factor 参数（或先做色度 2×2 平均再编码）实现 4:2:0，并把实测 `encoding_error_rms`/`blockiness` 写进测量块 |
| 代价 | 小 |
| 补齐条件 | 无需真实数据即可补形态；要"像这台手机"需要真机 JPEG 的量化表 |

### 1.6 色调曲线 / ISP

| | 内容 |
| --- | --- |
| 真实现状 | 相机把线性辐亮度经 OETF 编码成 sRGB/BT.709 交付值，再锐化/降噪/白平衡 |
| 合成现状 | 真实感基线已把 `response=SRGB` 打开（level>0 时），level 0 保持 `LINEAR` 以维持恒等断言；锐化/降噪/色彩矩阵有执行点但基线未开 |
| 差距 | 基线未开锐化/降噪（真机默认开）；没有镜头阴影校正、没有 HDR/多帧 |
| 可否 | **可补** |
| 补法 | 在 `realism.AXIS_LEVELS` 之外增补"交付属性"（如 `sharpening=0.2`、轻降噪），并像 `delivery_response` 一样写进 plan 与报告 |
| 代价 | 小 |
| 补齐条件 | 无需真实数据；要与真机一致需其 ISP 参数 |

### 1.7 光照

| | 内容 |
| --- | --- |
| 真实现状 | 非受控环境光（窗户/灯/阴影/互反射），色温未知 |
| 合成现状 | `ObsSpec.resolved_light()` 默认 = 单方向光（方向 `[-0.35,-0.62,-0.70]`、颜色 `[2.35,2.25,2.10]`）+ 环境项 `[0.30,0.30,0.33]`；Blender 端用真实 Cycles 传输（`max_bounces=4`、`samples=32`、无去噪），背景是常数线性色 `background_linear=(0.02,0.02,0.025)` |
| 差距 | 单一太阳式光源、无环境贴图、无地面/投影面、无阴影承接；真机的"环境"完全缺失 |
| 可否 | **部分可补** |
| 补法 | 用公开 HDRI 环境贴图 + 一个投影地面（Blender `extra_objects` 已支持额外物体）；光照参数化随机化 |
| 代价 | 中等（HDRI 资产与许可、渲染时间随环境光上升） |
| 补齐条件 | 要"像这次采集的光照"必须实测采集现场（HDRI 或至少色温/照度测量） |

### 1.8 材质与纹理

| | 内容 |
| --- | --- |
| 真实现状 | 真实陶瓷/金属的表面反射、釉面高光、污渍、磨损纹理 |
| 合成现状 | 程序化 `MaterialSpec`（逐面 albedo/roughness，`source_kind=SENSOR_SIM`）+ 纹样族几何/贴图；Blender 用 Principled BSDF 渲染 |
| 差距 | 没有实测 BRDF/反照率；纹样是程序化生成的，不是真实器物的纹样照片；釉面/污渍的统计形态可能相似但内容不同 |
| 可否 | **部分可补** |
| 补法 | 换成公开实测 BRDF/扫描纹理库（如陶瓷/陶土材质集），并把 albedo 来源标注为 `PUBLIC_MEASURED` 而不是 `SENSOR_SIM` |
| 代价 | 中等（资产引入 + 许可 + 与现有 `patterns` 管线的接口） |
| 补齐条件 | 要"内容真实"必须有真实碎片的纹理照片（多视角 + 偏振/交叉偏振去高光）；这属于真实数据采集，不在合成侧 |

### 1.9 遮挡与场景杂波

| | 内容 |
| --- | --- |
| 真实现状 | 手/工具/夹具/背景会遮挡目标；转台、标尺、垫片出现在画面里 |
| 合成现状 | `photo_mvs` 路线**刻意不渲染**背景/支撑/尺度条（`routes.py` 模块文档：为满足单一刚体场景假设）；Blender 端有 `extra_objects`（可加遮挡板/支撑板）与注入式重渲染（`degrade.make_probe_renderer`，I07 occluder 轴要求重渲染） |
| 差距 | 交付图里没有遮挡物、没有夹具、没有尺度参照；这既是"不真实"，也是"回避了真实管线必须处理的难点" |
| 可否 | **可补** |
| 补法 | 声明一个遮挡/夹具场景（Blender `extra_objects` + 软件端的 `is_target`/support 划分），并把被遮挡像素标进 `uncertain`/掩码；用 I07 轴做配对实验 |
| 代价 | 中等（场景资产 + 每个被遮挡视图都要重渲染 + 掩码要显式排除遮挡物而不是目标） |
| 补齐条件 | 无需真实数据；要匹配真实夹具需要夹具尺寸/材质实测 |

### 1.10 运动与手持

| | 内容 |
| --- | --- |
| 真实现状 | 手持抖动、转台转动中的运动模糊、卷帘 |
| 合成现状 | 12 视图是**静止**渲染；运动 PSF 有执行点（`motion_samples`/`motion_amplitude_px`）但真实感基线未开；`degrade` 的 I02 是方向核/曝光期积分两变体 |
| 差距 | 交付图无运动模糊（真机手持通常有 0.5–2 px 量级） |
| 可否 | **可补** |
| 补法 | 在 `realism` 的交付属性里开一个小的运动核（例如 I02 level 1 = 3 px 方向核），或把"多子曝光积分"接到 `motion_samples` |
| 代价 | 小 |
| 补齐条件 | 无需真实数据 |

### 1.11 尺度（绝对尺寸）

| | 内容 |
| --- | --- |
| 真实现状 | 单目 SfM 只有任意尺度；要毫米必须有尺度条/已知夹具/深度传感器 |
| 合成现状 | `photo_mvs` 交付 `scale_valid=false` 并写明理由（`scale_note`：SfM 任意单位、输入里没有可用尺度源）；`ideal_visible`/`proxy_scan` 交付 `scale_valid=true`（渲染器深度本身就是 mm）；`route_photo_mvs` 支持 `scale_target_radius_mm` 参数，给了就用 `SOURCE_CALIBRATED` 对齐尺度 |
| 差距 | **真实感腿反而丢了尺度**——这恰恰是真实的；但训练侧若默认"数据是 mm"就会踩坑。质量块把单位写成 `unknown`（`quality.point_cloud_diagonal.unit`），是对的 |
| 可否 | **可补** |
| 补法 | 在场景里放一个已知尺寸的尺度条/垫片（Blender `extra_objects`），或用 `scale_target_radius_mm` 声明一个真实夹具半径；两者都要在掩码里显式排除，否则又会污染单一刚体假设 |
| 代价 | 小–中 |
| 补齐条件 | 要"真实可采集"必须有真实尺度参照物；合成侧只能声明一个假设参照 |

### 1.12 标定误差与位姿误差

| | 内容 |
| --- | --- |
| 真实现状 | 标定残差 0.1–0.5 px 量级；夹具重复定位有平移/旋转误差 |
| 合成现状 | 三个档位的 `alignment_error_px_rms` **都是 0.0**（`cameras/profiles.py`）；`ViewFrame` 用参考位姿；`proxy_scan` 有 G04（每视图 SE(3) 漂移）与 G07（内参扰动）两个已实现轴 |
| 差距 | 真实感腿（`photo_mvs`）里位姿/内参是 COLMAP 从图像估出来的（有真实估计误差，可读 `backend_report.reconstruction.mean_reproj_error_px`），但**交付侧的声明**（`alignment_error_px_rms=0`）与"渲染用的参考位姿"仍然是无误差的；I07/G07 未接入批量路径 |
| 可否 | **可补** |
| 补法 | 把 `alignment_error_px_rms` 设为非零并让 `make_view_frames` 真的采样该误差；把 G04/G07 接进观测（或至少在报告里对已估位姿做与参考位姿的偏差统计） |
| 代价 | 小（采样 + 元数据）到中等（接线 G 轴） |
| 补齐条件 | 真实夹具重复定位实测才能给出误差量级 |

### 1.13 采集视角分布

| | 内容 |
| --- | --- |
| 真实现状 | 手持/转台视角非均匀：高度、方位、工作距离都有偏差与相关结构 |
| 合成现状 | `make_view_frames(profile, bbox, 12, rng, tiers=("GLOBAL","MID","LOCAL"), orbit=True)` = 3 层高度 × 4 方位（`DEFAULT_VIEW_COUNT=12`），工作距离由档位固定（`CAM_MID_V3` 的 220 mm），且 `orbit=True` 是规则轨道 |
| 差距 | 视角是理想格点；没有手持抖动、没有距离变化、没有覆盖偏置 |
| 可否 | **可补** |
| 补法 | 从声明的分布采样视角（`camera_profiles.json` 里已有 `reachable_actions`：`add_azimuth_view`/`add_height_view`/`move_u_near|mid|far`/`re_clamp_flip`），并记录每次采样的动作序列 |
| 代价 | 中等（新采样器 + 与 episodes 的接口一致性） |
| 补齐条件 | 要匹配真实采集习惯需要真实采集日志 |

### 1.14 掩码来源

| | 内容 |
| --- | --- |
| 真实现状 | 分割/背景减除得到的前景掩码，边界必然有误差；遮挡物、阴影、反光都会破坏它 |
| 合成现状 | `deployment_mask` 由 `deployment_mask_from_render` 从**渲染通道**得到（`id_map>=0 & visibility>0 & ~uncertain` 再腐蚀 1 px），并声明 `deployment_mask_source=RENDERED_FOREGROUND_ESTIMATE` |
| 差距 | 掩码是"数学上正确"的，没有估计误差；而且**CoC 判定会吃掉目标**：实测控制腿（流水线自己的 `coc_px_threshold = 0.75×f/2.2 = 1.65 px`）交付掩码只覆盖画面 0.14 %–2.6 %，而同一视图有 0.7 %–17 % 像素有有效深度；`_probe_sfm_matches.json` 实测：带该掩码时 12 张图**合计只有 12 个关键点**（SIFT），关掉掩码则每张 5000+ 关键点——掩码是 SfM 失败的直接原因之一 |
| 可否 | **可补**（形态）；真实掩码误差需要 X02 轴或真实分割模型 |
| 补法 | 真实感基线已声明 `mask_policy=foreground_silhouette`（关掉与交付图不一致的 CoC 判据，保留混合/深度边缘项），并把这个选择的实测代价写进报告；进一步可用 X02（掩码边界误差）轴注入误差，或用一个真实分割模型（如 SAM/背景减除）产掩码 |
| 代价 | 小（政策已接线）；用真实分割模型为中等 |
| 补齐条件 | 无需真实数据即可做形态；"像某个真实分割器"需要其权重与真机数据 |

### 1.15 深度来源

| | 内容 |
| --- | --- |
| 真实现状 | 深度来自 MVS/结构光/ToF，带空洞、噪声、尺度不确定 |
| 合成现状 | 观测的**逐视图 `depth_z` 始终是渲染器的精确深度**（`depth_semantics=camera_frame_z_mm`、`depth_source=RENDERER_EXACT_DEPTH_Z`），即使在 `photo_mvs` 路线上也一样；只有 `photo_mvs` 的融合点云来自 COLMAP 估计（`backend_report.dense.input=COLMAP_ESTIMATED_SPARSE`） |
| 差距 | 这是**最容易误导训练侧**的一条：读 `view.depth_z` 就拿到真值。它被声明了（`depth_source` 字段 + `truth_channels_role=research_label_only`），但没有强约束 |
| 可否 | **可补** |
| 补法 | 增加"交付深度"通道（由 SfM 深度先验/稀疏插值生成，`n_dense_points_before_fusion` 已是实测值），把渲染器精确深度保留为 research 通道并改名/改角色；训练侧只允许读交付通道 |
| 代价 | 中等（新通道 + 存储体积 + 训练/监督接口改动） |
| 补齐条件 | 无需真实数据 |

### 1.16 SfM / 稠密 MVS

| | 内容 |
| --- | --- |
| 真实现状 | COLMAP/OpenMVS 全流程，含 PatchMatch 稠密与融合 |
| 合成现状 | `photo_mvs` 真跑 pycolmap 3.11.1（extract/match/incremental/undistort），**稠密阶段不可用**：本机无 `patch_match_stereo` 符号、也没有独立 `colmap` 可执行文件，因此交付 `SPARSE_DEPTH_PRIOR` 并写 `failure_code=MVS_NOT_AVAILABLE`（`route_status` 也如实标 `MVS_NOT_AVAILABLE`，不是"成功"） |
| 差距 | 没有真正的稠密 MVS；"点云"是稀疏三角化的插值先验 |
| 可否 | **部分可补**（可换其它开源 MVS，如 OpenMVS，但仍需真实图像才是真实管线） |
| 补法 | 接入 OpenMVS/COLMAP 可执行文件；把稠密结果与稀疏先验的差异做成对照 |
| 代价 | 中等–大（外部二进制、显存/时间预算、许可） |
| 补齐条件 | 真实图像 + 完整稠密管线，才能声称"MVS 可用" |

### 1.17 数据规模与采集协议

| | 内容 |
| --- | --- |
| 真实现状 | 真实数据有采集协议（同一器物多视角、有重复、有失败重拍）、标注成本高 |
| 合成现状 | 计划 120 母体 / 240 片（`configs/a12/realistic.yaml` 沿用）；本轮真实感实测只跑 2 条谱系（`data/a12/reports/realistic_pilot.json`） |
| 差距 | 规模远小于"预训练"所需；真实数据为 0 |
| 可否 | **可补**（规模）/ **不可补**（真实数据本身） |
| 补法 | 提高 `target_mothers`、并行/分批（`tools/batch_generate.py` 的模式）；真实微调集必须另行采集 |
| 代价 | 与本机算力成正比（本轮实测：见第 2 节每阶段耗时） |
| 补齐条件 | 真实碎片 + 采集设备 + 标定流程 + 人工/半自动标注 |

### 1.18 未接线的声明字段（"写了但没人读"）

| 字段 | 现状（实测） |
| --- | --- |
| `observation.point_count` | schema 有（默认 8192），**无任何代码读取**；点云规模实际由 `route_params.voxel_mm`/SfM 决定 |
| `observation.persist_depth` | schema 有默认 `selected_qa_only`，**无代码读取**；实际每个视图的 `depth_z` 都写进 payload（因此本配置写 `all` 与事实一致） |
| `observation.persist_view_geometry` / `persist_fused_geometry` | 同上，**无代码读取**；视图几何与融合点云事实上总是写 |
| `dataset.degraded_recipe_refs` | 只被 `synlab/config.py::compile_spec` 用于"文件是否存在"的警告，**批量生成不应用任何 recipe**（`grep degraded_recipe_refs` 只有 config.py 与 schema）；31 轴 155 档在模块级全 PASS，但没接进 `pipeline.build_one_mother` |
| `observation.truth_channels_role` | 只在 schema 里；视图/目标元数据里的同名键由 `routes.py` 自己写死为 `research_label_only` |
| 影响 | 配置里写这些字段**不会**改变产物；本轮的 I 轴退化因此必须由 `synlab/observe/realism.py` 在观测阶段声明并接线（已在配置里说明），G/P 轴若要落档仍需把 `degrade` 接进批量路径 |

---

## 2. 本轮最小实测（realistic pilot）

> 数据来源：`data/a12/reports/realistic_pilot.json`、`data/a12/reports/_probe_sfm_matches.json`、
> `data/a12/reports/realism_timing_probe_blender.json`。所有数字都是本轮在这台机器上跑出来的。

<!-- PILOT-RESULTS -->

---

## 3. 改后仍然不像真实的地方 + 补齐条件

<!-- STILL-NOT-REAL -->
