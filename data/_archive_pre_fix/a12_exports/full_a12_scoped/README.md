# full 导出包（flavor=`full`，最大视图）

* 来源库：`data\a12`
* schema：`synlab.full_package_manifest.v1` / 消融索引 `synlab.ablation_index.v1`
* 选择：{"mode": "limit", "limit": 2, "available": 111, "fragments_exported": 2, "fragments_available": 111}
* 文件 **1427** 个 / **27520236** 字节；碎片 **2**；模态 present **101** / missing **9**
* 消融组 **35**：present 31 / partial 2 / missing 2

## 加载方式

```powershell
& .venv\Scripts\python.exe tools\load_full_package.py --package <本目录> --list-groups
& .venv\Scripts\python.exe tools\load_full_package.py --package <本目录> --groups G-IMG-RGB,G-FRAC-ATTR
& .venv\Scripts\python.exe tools\load_full_package.py --package <本目录> --check          # exit 0 = 一致 / 3 = 不一致
```

## 逐模态（present）

| modality_id | files | bytes | fragments | arrays | deploy | truth | derived |
|---|---:|---:|---:|---:|:--:|:--:|:--:|
| `clean_truth.corr_geometry` | 2 | 308358 | 1 | 17 | 否 | 是 | 否 |
| `clean_truth.iface_geometry` | 2 | 174507 | 1 | 12 | 否 | 是 | 否 |
| `clean_truth.relations` | 2 | 446 | 1 | 0 | 否 | 是 | 否 |
| `degrade_measurement.K` | 20 | 4780 | 1 | 1 | 否 | 否 | 否 |
| `degrade_measurement.mask` | 20 | 12841 | 1 | 2 | 否 | 否 | 否 |
| `degrade_measurement.modalities` | 19 | 549169 | 1 | 5 | 否 | 否 | 否 |
| `degrade_measurement.observed_est` | 20 | 5957 | 1 | 1 | 否 | 否 | 否 |
| `degrade_measurement.roi` | 20 | 5200 | 1 | 1 | 否 | 否 | 否 |
| `feature_bundle.curvature_field` | 3 | 63834 | 1 | 2 | 否 | 否 | 否 |
| `feature_bundle.density_field` | 3 | 60750 | 1 | 2 | 否 | 否 | 否 |
| `feature_bundle.global_rgb` | 2 | 100548 | 1 | 1 | 否 | 否 | 否 |
| `feature_bundle.global_valid` | 2 | 442 | 1 | 1 | 否 | 否 | 否 |
| `feature_bundle.normal_field` | 3 | 190761 | 1 | 2 | 否 | 否 | 否 |
| `feature_bundle.pixel_valid` | 2 | 2762 | 1 | 1 | 否 | 否 | 否 |
| `feature_bundle.point_cloud` | 3 | 190098 | 1 | 2 | 否 | 否 | 否 |
| `feature_bundle.quality` | 3 | 2571 | 1 | 3 | 否 | 否 | 否 |
| `feature_bundle.roi_weight` | 3 | 801 | 1 | 1 | 否 | 否 | 否 |
| `feature_bundle.token_index` | 3 | 3603 | 1 | 1 | 否 | 否 | 否 |
| `feature_bundle.view_tokens` | 3 | 786 | 1 | 1 | 否 | 否 | 否 |
| `fragment_mesh.face_attrs` | 6 | 114282 | 1 | 6 | 否 | 否 | 否 |
| `fragment_mesh.faces` | 6 | 149631 | 1 | 1 | 否 | 否 | 否 |
| `fragment_mesh.interface_faces` | 6 | 655116 | 1 | 7 | 否 | 否 | 是 |
| `fragment_mesh.vertices` | 6 | 208482 | 1 | 1 | 否 | 否 | 否 |
| `label_bundle.research_id_map` | 3 | 386886 | 1 | 4 | 否 | 否 | 否 |
| `label_bundle.surface_tag_map` | 3 | 31416 | 1 | 4 | 否 | 否 | 否 |
| `material_profile.profile` | 3 | 3836 | 3 | 1 | 否 | 否 | 否 |
| `mother_mesh.face_attrs` | 6 | 67995 | 3 | 3 | 否 | 否 | 否 |
| `mother_mesh.faces` | 6 | 134578 | 3 | 1 | 否 | 否 | 否 |
| `mother_mesh.vertices` | 6 | 370348 | 3 | 1 | 否 | 否 | 否 |
| `obs_fused_geometry.K` | 32 | 7648 | 1 | 1 | 是 | 否 | 否 |
| `obs_fused_geometry.depth_error_field` | 4 | 48496 | 1 | 1 | 否 | 否 | 否 |
| `obs_fused_geometry.dist` | 32 | 8320 | 1 | 1 | 否 | 否 | 否 |
| `obs_fused_geometry.frames.K` | 32 | 30784 | 1 | 4 | 是 | 否 | 否 |
| `obs_fused_geometry.frames.T_WC` | 32 | 41248 | 1 | 4 | 否 | 否 | 否 |
| `obs_fused_geometry.frames.depth_z` | 32 | 772320 | 1 | 4 | 是 | 否 | 否 |
| `obs_fused_geometry.frames.dist` | 32 | 33472 | 1 | 4 | 否 | 否 | 否 |
| `obs_fused_geometry.frames.mask` | 32 | 39648 | 1 | 4 | 否 | 否 | 否 |
| `obs_fused_geometry.mesh` | 32 | 352834 | 1 | 2 | 否 | 否 | 否 |
| `obs_fused_geometry.mesh_faces` | 4 | 2431 | 1 | 1 | 否 | 否 | 否 |
| `obs_fused_geometry.normals` | 32 | 565935 | 1 | 1 | 是 | 否 | 否 |
| `obs_fused_geometry.point_valid` | 32 | 7849 | 1 | 1 | 是 | 否 | 否 |
| `obs_fused_geometry.point_view` | 32 | 12960 | 1 | 1 | 否 | 否 | 否 |
| `obs_fused_geometry.points` | 32 | 473956 | 1 | 1 | 是 | 否 | 否 |
| `obs_fused_geometry.priority_order` | 32 | 84576 | 1 | 1 | 否 | 否 | 否 |
| `obs_fused_geometry.reference_points` | 32 | 609216 | 1 | 1 | 否 | 是 | 否 |
| `obs_fused_geometry.refusion_points` | 8 | 78002 | 1 | 1 | 否 | 否 | 否 |
| `obs_fused_geometry.roi` | 32 | 7337 | 1 | 1 | 是 | 否 | 否 |
| `obs_fused_geometry.spurious_mask` | 4 | 1034 | 1 | 1 | 否 | 否 | 否 |
| `obs_result.K` | 1 | 866 | 1 | 4 | 是 | 否 | 否 |
| `obs_result.T_WC` | 1 | 1203 | 1 | 4 | 否 | 否 | 否 |
| `obs_result.deployment_mask` | 1 | 2193 | 1 | 4 | 是 | 否 | 否 |
| `obs_result.depth_z` | 1 | 243955 | 1 | 4 | 是 | 否 | 否 |
| `obs_result.dist` | 1 | 934 | 1 | 4 | 否 | 否 | 否 |
| `obs_result.id_map` | 1 | 128850 | 1 | 4 | 否 | 否 | 否 |
| `obs_result.normal_valid` | 1 | 255 | 1 | 1 | 否 | 否 | 否 |
| `obs_result.normals` | 1 | 64056 | 1 | 1 | 否 | 否 | 否 |
| `obs_result.point_valid` | 1 | 253 | 1 | 1 | 否 | 否 | 否 |
| `obs_result.points` | 1 | 64019 | 1 | 1 | 否 | 否 | 否 |
| `obs_result.rgb` | 1 | 51181 | 1 | 4 | 是 | 否 | 否 |
| `obs_result.rgb_linear` | 1 | 71520 | 1 | 4 | 否 | 否 | 否 |
| `obs_result.roi` | 1 | 1098 | 1 | 4 | 是 | 否 | 否 |
| `obs_result.surface_tag` | 1 | 10400 | 1 | 4 | 否 | 否 | 否 |
| `obs_result.uncertain_mask` | 1 | 7077 | 1 | 4 | 是 | 否 | 否 |
| `obs_view.frames.K` | 48 | 44045 | 1 | 4 | 是 | 否 | 否 |
| `obs_view.frames.T_WC` | 48 | 58881 | 1 | 4 | 否 | 否 | 否 |
| `obs_view.frames.deployment_mask` | 48 | 52296 | 1 | 4 | 是 | 否 | 否 |
| `obs_view.frames.depth_z` | 48 | 818549 | 1 | 4 | 是 | 否 | 否 |
| `obs_view.frames.dist` | 48 | 47904 | 1 | 4 | 否 | 否 | 否 |
| `obs_view.frames.pixel_transform` | 4 | 4200 | 1 | 4 | 否 | 否 | 否 |
| `obs_view.frames.research_mask` | 48 | 60053 | 1 | 4 | 否 | 否 | 否 |
| `obs_view.frames.rgb` | 48 | 1126257 | 1 | 4 | 是 | 否 | 否 |
| `obs_view.frames.rgb_linear` | 48 | 12955259 | 1 | 4 | 否 | 否 | 否 |
| `obs_view.frames.valid_mask` | 48 | 57543 | 1 | 4 | 否 | 否 | 否 |
| `pattern_channels.albedo` | 9 | 25516 | 4 | 1 | 否 | 否 | 否 |
| `pattern_channels.height_mm` | 9 | 2065 | 4 | 1 | 否 | 否 | 否 |
| `pattern_channels.pattern_region` | 9 | 2812 | 4 | 1 | 否 | 否 | 否 |
| `pattern_channels.roughness` | 9 | 4474 | 4 | 1 | 否 | 否 | 否 |
| `pattern_recipe.recipe` | 9 | 410881 | 4 | 0 | 否 | 否 | 否 |
| `physical_component.appearance` | 16 | 785244 | 1 | 11 | 否 | 否 | 否 |
| `physical_component.measurement` | 1 | 872442 | 1 | 3 | 否 | 否 | 否 |
| `physical_component.mesh` | 16 | 1535630 | 1 | 2 | 否 | 否 | 否 |
| `physical_component.mesh_face_attrs` | 16 | 4796 | 1 | 1 | 否 | 否 | 否 |
| `physical_truth.corr_geometry` | 2 | 308358 | 1 | 17 | 否 | 是 | 否 |
| `physical_truth.relations` | 2 | 446 | 1 | 0 | 否 | 是 | 否 |
| `provenance.fingerprints` | 3 | 24487 | 1 | 0 | 否 | 否 | 否 |
| `qa_report.probe` | 2 | 486 | 1 | 1 | 否 | 否 | 否 |
| `query_roster.queries` | 1 | 6035 | 1 | 0 | 否 | 否 | 否 |
| `relation_pool.event_ids` | 2 | 936 | 1 | 1 | 否 | 否 | 否 |
| `relation_pool.fragment_ids` | 2 | 1108 | 1 | 1 | 否 | 否 | 否 |
| `relation_pool.hist_ids` | 2 | 590 | 1 | 1 | 否 | 否 | 否 |
| `relation_pool.hist_offsets` | 2 | 460 | 1 | 1 | 否 | 否 | 否 |
| `relation_pool.is_tiny` | 2 | 424 | 1 | 1 | 否 | 否 | 否 |
| `relation_pool.lineage_ids` | 2 | 934 | 1 | 1 | 否 | 否 | 否 |
| `relation_pool.mother_ids` | 2 | 930 | 1 | 1 | 否 | 否 | 否 |
| `relation_pool.quality_tier` | 2 | 444 | 1 | 1 | 否 | 否 | 否 |
| `relation_pool.query_fragment_ids` | 2 | 1018 | 1 | 1 | 否 | 否 | 否 |
| `relation_pool.relations` | 2 | 3030 | 1 | 7 | 否 | 否 | 否 |
| `relation_pool.splits` | 2 | 550 | 1 | 1 | 否 | 否 | 否 |
| `relation_pool.verified` | 2 | 428 | 1 | 1 | 否 | 否 | 否 |
| `visible_labels.relations` | 2 | 4 | 1 | 0 | 否 | 是 | 否 |
| `visible_labels.visible_counts` | 2 | 1404 | 1 | 2 | 否 | 是 | 否 |

## 缺失模态与解锁条件

| modality_id | 缺什么才能有 |
|---|---|
| `context_pack.excavation` | materialise a context_pack asset (role context_pack, schema synlab.context.v1); 0 such assets exist in any store of this checkout |
| `cutter_mesh.mesh` | commit a cutter_mesh asset (role registered, 0 products in every store) |
| `degrade_measurement.meta_arrays` | run a degradation axis and commit its degrade_measurement |
| `display_lod_glb.glb_scene` | materialise a display_lod_glb asset (today only data/a12_demo/store has them) |
| `display_lod_glb.lod_level_L1` | install fast_simplification and export L1 into the GLB scene graph; today lod_notes records 'L1 skipped: ModuleNotFoundError: No module named fast_simplification' or 'L1/L2 measured only (not exported as scene nodes)' |
| `display_lod_glb.lod_level_L2` | same as L1: the simplification dependency is absent and the levels are measured but not written as scene nodes |
| `episode_trace.transitions` | run at least one episode and commit an episode_trace asset; the role is registered but has 0 products in every store |
| `mvs_result.sparse` | run the photo_mvs route to completion; the only recorded run failed with STOP_SFM (incremental_mapping returned no reconstruction) |
| `physical_result.measurement` | run a physical operator and commit its physical_result |

## 消融组

| group_id | 可用性 | 模态数(有/缺) | 字段数 | 权限 | 问题 |
|---|---|---:|---:|:--:|---|
| `G-GEOM-MOTHER` | present | 3/0 | 5 | research | 母体全局几何是否是检索/配准的有效先验，还是只增加输入维度？ |
| `G-GEOM-FRAG` | present | 2/0 | 2 | research | 碎片 3D 几何（含顶点/面）是否比纯 2D 观测带来净增益？ |
| `G-GEOM-PHYS` | partial | 2/1 | 3 | research | 把退化后的 physical_component 几何当输入，是否抵消（负收益）或补偿 2D 退化？ |
| `G-FRAC-ATTR` | present | 3/0 | 10 | research | 断面面属性是断面定位的最小充分信号吗？ |
| `G-FRAC-IFACE-DERIVED` | present | 1/0 | 7 | research | 从权威面属性派生的断面几何，能否单独支撑断面级监督（替代缺失的独立断面资产）？ |
| `G-FRAC-IFACE-TRUTH` | present | 1/0 | 12 | research | 断面级真值（面积/间隙/法向）是否是配对断口监督的必要项？ |
| `G-FRAC-CORR` | present | 2/0 | 34 | research | 逐点对应监督（corr_point_a/b）对互补性学习的边际收益是多少？ |
| `G-IMG-RGB` | present | 2/0 | 8 | deploy | 交付态 RGB 单独能把 Hit@10 做到多少（部署基线）？ |
| `G-IMG-LINEAR` | present | 2/0 | 8 | research | 线性辐射通道（ISP 之前）是否比交付 RGB 有额外信息？ |
| `G-IMG-DEPTH` | present | 3/0 | 9 | deploy | 相机 z 深度是否带来正收益，还是只泄露渲染器构造？ |
| `G-IMG-IDMAP` | present | 1/0 | 4 | research | 逐面 ID 是监督信号还是捷径（是否把答案直接喂给模型）？ |
| `G-IMG-TAG` | present | 1/0 | 4 | research | surface_tag 图里 rim 像素为 0 时，该通道是否完全无信息？ |
| `G-MASK-DEPLOY` | present | 2/0 | 8 | deploy | 只保留部署可获取像素是否显著降低指标（部署代价的量化）？ |
| `G-MASK-ROI` | present | 3/0 | 9 | research | 限制到 ROI 是否提高精度（信噪比换召回）？ |
| `G-MASK-UNCERTAIN` | present | 1/0 | 4 | deploy | 剔不确定像素（混合/景深/深度边）是否净收益？ |
| `G-CAM-K` | present | 2/0 | 8 | deploy | 给真值内参是否比'未标定档'显著提高（标定价值上限）？ |
| `G-CAM-POSE` | present | 2/0 | 8 | research | 真值位姿是必要条件还是可被特征匹配替代？ |
| `G-CAM-DIST` | present | 2/0 | 8 | research | 显式畸变是先验还是噪声源？ |
| `G-PC-FUSED` | present | 10/0 | 11 | deploy | 点云/法向是否是 2D 之外的互补证据？ |
| `G-PC-REFERENCE` | present | 1/0 | 1 | research | 把干净参考点云当输入是否造成泄漏型虚高（预期负收益）？ |
| `G-FEAT-FIELDS` | present | 5/0 | 9 | research | 显式特征场是否比原始点云更有效？ |
| `G-QUALITY` | present | 1/0 | 3 | research | 质量向量（11 通道）是否改善门控与拒识？ |
| `G-TOKENS` | present | 2/0 | 2 | research | token 缓存是否携带独立信息（已知有效秩=1 的疑问）？ |
| `G-LABEL-CLEAN` | present | 2/0 | 29 | research | 干净层真值参与预训练是否正收益（还是只教合成捷径）？ |
| `G-LABEL-PHYSICAL` | present | 2/0 | 19 | research | 退化后的 physical 层监督是否比 clean 层更贴近部署？ |
| `G-LABEL-VISIBLE` | present | 1/0 | 2 | research | 可见性标签是否改善拒识与阈值选择？ |
| `G-LABEL-BUNDLE` | present | 2/0 | 8 | research | 像素级 id/tag 标签图作为辅助监督是否正收益？ |
| `G-REL-POOL` | present | 2/0 | 7 | research | 关系表（R1/R2/UNKNOWN）与冻结 roster 是否是可复算评测的前提？ |
| `G-DEGRADE-PHYSICAL` | present | 2/0 | 13 | research | 各物理磨损轴分别造成多大性能下降（敏感度曲线）？ |
| `G-DEGRADE-IMAGING` | present | 3/0 | 12 | research | 模糊/噪声/曝光/白平衡/JPEG 各轴的性能代价是多少？ |
| `G-DEGRADE-GEOMETRY` | present | 3/0 | 3 | research | 深度误差/稀疏/空洞/位姿漂移/简化/尺度/标定/伪影各自的代价？ |
| `G-DEGRADE-PROTOCOL` | partial | 3/1 | 8 | research | 分支缺失/边界误差/上下文缺失/估计偏差/留出工况的影响？ |
| `G-CONTEXT` | missing | 0/1 | 0 | research | 受限的模拟出土上下文是否有正收益（文档要求不能等价母体 ID）？ |
| `G-DISPLAY-LOD` | missing | 0/3 | 0 | deploy | L0 与 L1/L2 的差别是否影响几何侧实验（L1/L2 当前不可得）？ |
| `G-PROVENANCE` | present | 4/0 | 2 | research | 没有 provenance 的实验结果能否被复算（对照组必须失败）？ |

> 本文件由 `synlab/storage/export_full.py` 从 manifest 自动生成；每个数字都可在 `manifest.json` 中复算。
