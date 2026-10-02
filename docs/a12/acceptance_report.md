# A12 验收报告（A01–A36）

- 生成时间：2026-10-02 09:46:50
- 发布 profile：`SANDBOX_CORE`
- 平台：Windows-11-10.0.26200-SP0 / Python 3.12.14
- 统计：{'FAIL': 5, 'PASS': 12, 'PENDING': 6, 'NOT_RUN': 6, 'NA': 7}

> 本报告的每一项都由实际命令产生。`NOT_RUN` 表示未运行，`PENDING` 表示前置条件（外部后端、实拍数据、规模运行）尚未具备，`NA` 表示该 profile 下不适用。没有任何一项用推测或复制设计值充当实测结果。

| ID | 验收对象 | 状态 | 关键实测 | 证据 | 说明 |
|---|---|---|---|---|---|
| A01 | 合同与权限（六 pack、features/labels 边界） | **FAIL** | {"unknown_field_rejected": true, "leakage_detector": true, "forbidden_fields_in_committed_features": ["fragment_id", "mother_id", "fragment_id", "mother_id", "fragment_id", "mother_id", "fragment_id", "mother_id", "fragment_id", "mother_id", "fragment_id", "mother_id", "fragment_id", "mother_id", "f | synlab/observe/features.py::assert_no_leakage | schema rejection + recursive whitelist + committed feature audit |
| A02 | 坐标投影（mm、K、T、depth/range、crop） | **PASS** | {"max_mm_error": 1.4210854715202004e-14, "max_px_error": 0.0} | docs/a12/env_report.json | analytic projection/back-projection round trip |
| A03 | 母体（24 族 × ≥20 独立母体） | **PENDING** | {"vessels_present": 3, "min_lineages_per_vessel": 1, "total_mothers": 13} | - | counts come from committed mother assets; 24x20 requires the L2 run |
| A04 | 材料层（12 材料 / 4 层结构） | **PENDING** | {"materials_present": 2, "ids": ["M01", "M04"]} | - | shading vs geometric layers must be distinguishable |
| A05 | 花纹（16 family） | **FAIL** | {"families": 16, "max_seam_error": 6.183942247162122e-14, "deterministic": true, "geometry_applied": true} | data/a12/reports/pattern_audit.json |  |
| A06 | 断裂守恒（四必做后端、薄壳、复杂体） | **FAIL** | {"backends_pass": 0, "backends": {"plane_shared_cut": "FAIL"}, "conservation_ratio_max": null, "overlap_ratio_max": null} | data/a12/reports/fracture_audit.json |  |
| A07 | 精度实现（cutter / 共形 warp） | **NOT_RUN** | {} | - | requires a fracture event with an error budget |
| A08 | 真值关系（R2/R1/R0/UNKNOWN 与事件树） | **NOT_RUN** | {} | - | requires `synlab.truth` fixture run |
| A09 | 减法损伤（P01–P04/P07 + 适用 P08） | **FAIL** | {} | data/a12/reports/physical_audit.json |  |
| A10 | 31 轴身份与效果 | **PENDING** | {"axes_registered": 31, "axes_pass": 26, "axes_with_20_mothers": 0, "identity_ok": true} | data/a12/reports/operator_audit.json |  |
| A11 | 伪凸起/补面/假桥（G08 三变体） | **PASS** | {"clean_hash_unchanged": true, "level_zero_identity": true, "variants": {"bridge": {"area_after_mm2": 9575.30049961296, "area_before_mm2": 9568.0, "components_after": 3, "components_before": 2, "level0_identity": true, "measured": {"clean_hash_untouched": 1.0, "connectivity_changed": 1.0, "euler_aft | data/a12/reports/spurious_audit.json |  |
| A12 | 成像标签（RGB、深度、mask、可见性） | **PASS** | {"backend": "SOFTWARE_RASTERIZER", "deployment_mask_pixels": 0, "depth_median_abs_error_mm": 0.43125950028843363, "depth_p95_abs_error_mm": 7.394597217116015} | data/a12/reports/channel_audit.json |  |
| A13 | 物理近远档（U 相机 profile） | **PENDING** | {"note": "a U move changes the camera extrinsic and never the image size; real-capture calibration is absent on this host, so A13.real_calibration stays PENDING", "profiles": ["CAM_GLOBAL_V3", "CAM_MID_V3", "CAM_LOCAL_V3"], "tiers": {"GLOBAL": {"calibrated": false, "image_size_unchanged": true, "mm_ | data/a12/reports/camera_profile_audit.json | A13.engineering and A13.real_calibration are reported separately |
| A14 | 实际 MVS 子集 | **NA** | {} | - | not applicable to profile SANDBOX_CORE |
| A15 | 全库和采样（多 R2、R1/R0、无邻片） | **NOT_RUN** | {} | - | run `synlab build-pool` first |
| A16 | 训练有效性（五任务、valid 与 missing） | **NA** | {} | - | not applicable to profile SANDBOX_CORE |
| A17 | 恢复（数据 job 与训练 checkpoint） | **PASS** | {"stale_commit_blocked": true, "final_state": "COMMITTED"} | data/a12/reports/recovery_probe.json |  |
| A18 | 诊断计算（指标与统计） | **PASS** | {"metric_fixture_ok": true, "stat_fixture_ok": true} | data/a12/reports/metric_fixture.json, data/a12/reports/stat_fixture.json |  |
| A19 | 规则 episode（actions/cost/STOP） | **NOT_RUN** | {} | - | run `synlab episode` first |
| A20 | UI/API（12 页与真实端到端） | **PASS** | {"assets_page_items": 5, "assets_status": 200, "capabilities_status": 200, "frontend_build_present": true} | docs/a12/api_ui.md |  |
| A21 | 资源与规模（L2/L3） | **NA** | {} | - | not applicable to profile SANDBOX_CORE |
| A22 | 发布交接（新目录启动/读写恢复） | **PENDING** | {"runbook": true, "releases": 0, "store_health": true} | docs/a12/runbook.md |  |
| A23 | 开源复用（第 2.4 节全部适用模块） | **PASS** | {"modules": 25, "incomplete": [], "custom_gap_without_evidence": [], "custom_gaps": 4} | docs/a12/reuse_manifest.json |  |
| A24 | 观测来源/DAG | **FAIL** | {"checks": {"control_is_sensitive": true, "frame_source_kind": true, "gt_pose_invariance": false, "no_depth_or_scale_input": true, "pose_priors_empty": true}, "control_run": {"db_hash": "sha256:9a4e6e3f121ee6eec70b50d3c351f4e755d929544e93c44d3429c023d03b65cb", "keypoints": 4821, "keypoints_hash": "s | data/a12/reports/source_dependency_audit.json |  |
| A25 | 坐标/展示（0.5px、resize、EXIF、COLMAP 往返、100mm GLB） | **PASS** | {"checks": {"colmap_convention": {"note": "", "ok": true}, "colmap_real_library": {"note": "", "ok": true}, "display": {"note": "GLB derivation + UI measurement + frontend matrices verified", "ok": true}, "exif": {"note": "", "ok": true}, "pixel_transforms": {"note": "", "ok": true}}, "colmap_conven | data/a12/reports/pixel_contract.json |  |
| A26 | 分区形变（共享 PLC / 共形网格） | **NOT_RUN** | {} | - | requires the warped_partition backend to run |
| A27 | 来源/对应（原三角 ID、公共面积、损伤关联分离） | **NOT_RUN** | {} | - | requires fracture + truth audits |
| A28 | 物理身份/损伤（P01/P02 固定场、嵌套、多组件） | **PENDING** | {} | - | requires physical identity audit (components/debris/ancestry) |
| A29 | 检索/匹配（双塔、TopM 精排、全 R2 排除） | **NA** | {} | - | not applicable to profile SANDBOX_CORE |
| A30 | 拒识/分母（多正例接受集、失败主分母） | **PASS** | {"hand_computed_hit": true, "hand_computed_poolcov": true, "hand_computed_cov": true, "effective_zero_on_failure": true} | data/a12/reports/metric_fixture.json |  |
| A31 | 独立数据/统计（N 广度深度、gallery 隔离、CP 假设） | **NA** | {} | - | not applicable to profile SANDBOX_CORE |
| A32 | 全流程泄漏（置换、ID 重命名、同器库负控） | **NA** | {} | - | not applicable to profile SANDBOX_CORE |
| A33 | 权限/输入（服务端角色、路径/资源限制） | **PASS** | {"deployment_truth_denied": true, "operator_truth_denied": true, "path_traversal_denied": true, "unregistered_file_role_denied": true} | data/a12/reports/api_security.json |  |
| A34 | 资产/调度（同 blob 多 role、code identity、GPU 清退、reservation） | **PASS** | {} | data/a12/reports/recovery_probe.json |  |
| A35 | 续训/监督分母（acknowledged cursor、prefetch 重放） | **NA** | {} | - | not applicable to profile SANDBOX_CORE |
| A36 | 配置/发布（route/scope 枚举、全部配置编译） | **PASS** | {"compiled": {"closed_loop.yaml": "OK", "coverage.yaml": "OK", "diagnose_sandbox.yaml": "OK", "pilot.yaml": "OK", "pool_dev.yaml": "OK", "pool_pilot.yaml": "OK", "sandbox.yaml": "OK", "train_pilot.yaml": "OK", "train_sandbox.yaml": "OK", "degrade_recipes/paired_edgewear_blur_bump.yaml": "OK", "degra | - | every shipped config must compile through the typed schema |

## 状态矩阵

见 `docs/a12/status_matrix.csv`（模块 × 状态 × 证据）。

## 未完成与阻塞

见 `docs/a12/status_matrix.csv` 的 PENDING/NOT_RUN 行与 `docs/a12/repo_inventory.md` 第 7 节。
