# full 导出包（flavor=`full`，最大视图）

* 来源库：`data\a12_campaign\store`
* schema：`synlab.full_package_manifest.v1` / 消融索引 `synlab.ablation_index.v1`
* 选择：{"available": 13, "fragments_available": 13, "fragments_exported": 13, "mode": "all"}
* 文件 **893** 个 / **4372076409** 字节；碎片 **13**；模态 present **48** / missing **39**
* 消融组 **35**：present 12 / partial 15 / missing 8

## 加载方式

```powershell
& .venv\Scripts\python.exe tools\load_full_package.py --package <本目录> --list-groups
& .venv\Scripts\python.exe tools\load_full_package.py --package <本目录> --groups G-IMG-RGB,G-FRAC-ATTR
& .venv\Scripts\python.exe tools\load_full_package.py --package <本目录> --check          # exit 0 = 一致 / 3 = 不一致
```

## 逐模态（present）

| modality_id | files | bytes | fragments | arrays | deploy | truth | derived |
|---|---:|---:|---:|---:|:--:|:--:|:--:|
| `clean_truth.corr_geometry` | 10 | 2170126 | 4 | 17 | 否 | 是 | 否 |
| `clean_truth.iface_geometry` | 10 | 1183977 | 4 | 12 | 否 | 是 | 否 |
| `clean_truth.relations` | 10 | 13483 | 4 | 0 | 否 | 是 | 否 |
| `feature_bundle.curvature_field` | 11 | 5236 | 9 | 2 | 否 | 否 | 否 |
| `feature_bundle.global_rgb` | 11 | 28607387 | 9 | 1 | 否 | 否 | 否 |
| `feature_bundle.global_valid` | 11 | 2442 | 9 | 1 | 否 | 否 | 否 |
| `feature_bundle.normal_field` | 11 | 4928 | 9 | 2 | 否 | 否 | 否 |
| `feature_bundle.pixel_valid` | 11 | 671016 | 9 | 1 | 否 | 否 | 否 |
| `feature_bundle.point_cloud` | 11 | 4796 | 9 | 2 | 否 | 否 | 否 |
| `feature_bundle.quality` | 11 | 9386 | 9 | 3 | 否 | 否 | 否 |
| `feature_bundle.view_tokens` | 11 | 2398 | 9 | 1 | 否 | 否 | 否 |
| `fragment_mesh.face_attrs` | 34 | 281847 | 4 | 6 | 否 | 否 | 否 |
| `fragment_mesh.faces` | 34 | 384835 | 4 | 1 | 否 | 否 | 否 |
| `fragment_mesh.interface_faces` | 34 | 2246155 | 4 | 7 | 否 | 否 | 是 |
| `fragment_mesh.vertices` | 34 | 597760 | 4 | 1 | 否 | 否 | 否 |
| `label_bundle.research_id_map` | 3 | 113256438 | 3 | 12 | 否 | 否 | 否 |
| `label_bundle.surface_tag_map` | 3 | 284062 | 3 | 12 | 否 | 否 | 否 |
| `material_profile.profile` | 12 | 15372 | 5 | 1 | 否 | 否 | 否 |
| `mother_mesh.face_attrs` | 12 | 108162 | 5 | 3 | 否 | 否 | 否 |
| `mother_mesh.faces` | 12 | 217438 | 5 | 1 | 否 | 否 | 否 |
| `mother_mesh.vertices` | 12 | 616422 | 5 | 1 | 否 | 否 | 否 |
| `obs_result.K` | 22 | 56188 | 11 | 12 | 是 | 否 | 否 |
| `obs_result.T_WC` | 22 | 79128 | 11 | 12 | 否 | 否 | 否 |
| `obs_result.deployment_mask` | 22 | 1404842 | 11 | 12 | 是 | 否 | 否 |
| `obs_result.depth_z` | 22 | 830540260 | 11 | 12 | 是 | 否 | 否 |
| `obs_result.dist` | 22 | 60676 | 11 | 12 | 否 | 否 | 否 |
| `obs_result.id_map` | 22 | 830539732 | 11 | 12 | 否 | 否 | 否 |
| `obs_result.normal_valid` | 22 | 4796 | 11 | 1 | 否 | 否 | 否 |
| `obs_result.normals` | 22 | 4620 | 11 | 1 | 否 | 否 | 否 |
| `obs_result.point_valid` | 22 | 4752 | 11 | 1 | 否 | 否 | 否 |
| `obs_result.points` | 22 | 4576 | 11 | 1 | 否 | 否 | 否 |
| `obs_result.rgb` | 22 | 57212062 | 11 | 12 | 是 | 否 | 否 |
| `obs_result.rgb_linear` | 22 | 2491486228 | 11 | 12 | 否 | 否 | 否 |
| `obs_result.roi` | 22 | 783362 | 11 | 12 | 是 | 否 | 否 |
| `obs_result.surface_tag` | 22 | 2053054 | 11 | 12 | 否 | 否 | 否 |
| `obs_result.uncertain_mask` | 22 | 479150 | 11 | 12 | 是 | 否 | 否 |
| `pattern_channels.albedo` | 12 | 129128 | 5 | 1 | 否 | 否 | 否 |
| `pattern_channels.height_mm` | 12 | 4791 | 5 | 1 | 否 | 否 | 否 |
| `pattern_channels.pattern_region` | 12 | 6016 | 5 | 1 | 否 | 否 | 否 |
| `pattern_channels.roughness` | 12 | 45761 | 5 | 1 | 否 | 否 | 否 |
| `pattern_recipe.recipe` | 12 | 208624 | 5 | 0 | 否 | 否 | 否 |
| `physical_component.measurement` | 8 | 2746900 | 3 | 4 | 否 | 否 | 否 |
| `physical_result.measurement` | 8 | 9492 | 3 | 5 | 否 | 否 | 否 |
| `physical_truth.corr_geometry` | 8 | 1497161 | 3 | 17 | 否 | 是 | 否 |
| `physical_truth.relations` | 8 | 13001 | 3 | 0 | 否 | 是 | 否 |
| `physical_truth.truth_arrays` | 5 | 8067 | 3 | 6 | 否 | 是 | 否 |
| `visible_labels.relations` | 6 | 12 | 3 | 0 | 否 | 是 | 否 |
| `visible_labels.visible_counts` | 6 | 9282 | 3 | 7 | 否 | 是 | 否 |

## 缺失模态与解锁条件

| modality_id | 缺什么才能有 |
|---|---|
| `context_pack.excavation` | materialise a context_pack asset (role context_pack, schema synlab.context.v1); 0 such assets exist in any store of this checkout |
| `cutter_mesh.mesh` | commit a cutter_mesh asset (role registered, 0 products in every store) |
| `degrade_measurement.mask` | run a degradation axis and commit its degrade_measurement |
| `degrade_measurement.meta_arrays` | run a degradation axis and commit its degrade_measurement |
| `degrade_measurement.modalities` | run a degradation axis and commit its degrade_measurement |
| `degrade_measurement.observed_est` | run a degradation axis and commit its degrade_measurement |
| `display_lod_glb.glb_scene` | materialise a display_lod_glb asset (today only data/a12_demo/store has them) |
| `display_lod_glb.lod_level_L1` | install fast_simplification and export L1 into the GLB scene graph; today lod_notes records 'L1 skipped: ModuleNotFoundError: No module named fast_simplification' or 'L1/L2 measured only (not exported as scene nodes)' |
| `display_lod_glb.lod_level_L2` | same as L1: the simplification dependency is absent and the levels are measured but not written as scene nodes |
| `episode_trace.transitions` | run at least one episode and commit an episode_trace asset; the role is registered but has 0 products in every store |
| `feature_bundle.density_field` | produce a feature_bundle asset |
| `feature_bundle.roi_weight` | produce a feature_bundle asset carrying roi_weight |
| `feature_bundle.token_index` | produce a feature_bundle asset carrying token_index |
| `mvs_result.sparse` | run the photo_mvs route to completion; the only recorded run failed with STOP_SFM (incremental_mapping returned no reconstruction) |
| `obs_fused_geometry.depth_error_field` | materialise an obs_fused_geometry asset |
| `obs_fused_geometry.mesh` | materialise an obs_fused_geometry asset |
| `obs_fused_geometry.normals` | materialise an obs_fused_geometry asset |
| `obs_fused_geometry.point_valid` | materialise an obs_fused_geometry asset |
| `obs_fused_geometry.point_view` | materialise an obs_fused_geometry asset |
| `obs_fused_geometry.points` | materialise an obs_fused_geometry asset (G01..G08 axis run) |
| `obs_fused_geometry.priority_order` | materialise an obs_fused_geometry asset |
| `obs_fused_geometry.reference_points` | materialise an obs_fused_geometry asset carrying reference_points |
| `obs_fused_geometry.roi` | materialise an obs_fused_geometry asset |
| `obs_view.frames.K` | materialise an obs_view asset carrying K |
| `obs_view.frames.T_WC` | materialise an obs_view asset carrying T_WC |
| `obs_view.frames.deployment_mask` | materialise an obs_view asset carrying deployment_mask |
| `obs_view.frames.depth_z` | materialise an obs_view asset carrying depth_z |
| `obs_view.frames.dist` | materialise an obs_view asset carrying dist |
| `obs_view.frames.research_mask` | materialise an obs_view asset carrying research_mask |
| `obs_view.frames.rgb` | materialise an obs_view asset (degrade axis run) in this store |
| `obs_view.frames.rgb_linear` | materialise an obs_view asset carrying rgb_linear |
| `obs_view.frames.valid_mask` | materialise an obs_view asset carrying valid_mask |
| `physical_component.appearance` | produce a physical_component asset with a payload.appearance block |
| `physical_component.mesh` | produce a physical_component asset (P/I/G/X axis materialisation) |
| `physical_component.mesh_face_attrs` | produce a physical_component asset carrying payload.mesh.face__* arrays |
| `provenance.fingerprints` | commit a provenance asset for the run that produced these fragments |
| `qa_report.probe` | commit a qa_report asset |
| `query_roster.queries` | commit a query_roster asset for this pool |
| `relation_pool.relations` | commit a relation_pool asset for this batch |

## 消融组

| group_id | 可用性 | 模态数(有/缺) | 字段数 | 权限 | 问题 |
|---|---|---:|---:|:--:|---|
| `G-GEOM-MOTHER` | present | 3/0 | 5 | research | 母体全局几何是否是检索/配准的有效先验，还是只增加输入维度？ |
| `G-GEOM-FRAG` | present | 2/0 | 2 | research | 碎片 3D 几何（含顶点/面）是否比纯 2D 观测带来净增益？ |
| `G-GEOM-PHYS` | partial | 1/2 | 5 | research | 把退化后的 physical_component 几何当输入，是否抵消（负收益）或补偿 2D 退化？ |
| `G-FRAC-ATTR` | partial | 2/1 | 9 | research | 断面面属性是断面定位的最小充分信号吗？ |
| `G-FRAC-IFACE-DERIVED` | present | 1/0 | 7 | research | 从权威面属性派生的断面几何，能否单独支撑断面级监督（替代缺失的独立断面资产）？ |
| `G-FRAC-IFACE-TRUTH` | present | 1/0 | 12 | research | 断面级真值（面积/间隙/法向）是否是配对断口监督的必要项？ |
| `G-FRAC-CORR` | present | 2/0 | 34 | research | 逐点对应监督（corr_point_a/b）对互补性学习的边际收益是多少？ |
| `G-IMG-RGB` | partial | 1/1 | 12 | deploy | 交付态 RGB 单独能把 Hit@10 做到多少（部署基线）？ |
| `G-IMG-LINEAR` | partial | 1/1 | 12 | research | 线性辐射通道（ISP 之前）是否比交付 RGB 有额外信息？ |
| `G-IMG-DEPTH` | partial | 1/2 | 12 | deploy | 相机 z 深度是否带来正收益，还是只泄露渲染器构造？ |
| `G-IMG-IDMAP` | present | 1/0 | 12 | research | 逐面 ID 是监督信号还是捷径（是否把答案直接喂给模型）？ |
| `G-IMG-TAG` | present | 1/0 | 12 | research | surface_tag 图里 rim 像素为 0 时，该通道是否完全无信息？ |
| `G-MASK-DEPLOY` | partial | 1/1 | 12 | deploy | 只保留部署可获取像素是否显著降低指标（部署代价的量化）？ |
| `G-MASK-ROI` | partial | 1/2 | 12 | research | 限制到 ROI 是否提高精度（信噪比换召回）？ |
| `G-MASK-UNCERTAIN` | present | 1/0 | 12 | deploy | 剔不确定像素（混合/景深/深度边）是否净收益？ |
| `G-CAM-K` | partial | 1/1 | 12 | deploy | 给真值内参是否比'未标定档'显著提高（标定价值上限）？ |
| `G-CAM-POSE` | partial | 1/1 | 12 | research | 真值位姿是必要条件还是可被特征匹配替代？ |
| `G-CAM-DIST` | partial | 1/1 | 12 | research | 显式畸变是先验还是噪声源？ |
| `G-PC-FUSED` | partial | 4/6 | 4 | deploy | 点云/法向是否是 2D 之外的互补证据？ |
| `G-PC-REFERENCE` | missing | 0/1 | 0 | research | 把干净参考点云当输入是否造成泄漏型虚高（预期负收益）？ |
| `G-FEAT-FIELDS` | partial | 3/2 | 6 | research | 显式特征场是否比原始点云更有效？ |
| `G-QUALITY` | present | 1/0 | 3 | research | 质量向量（11 通道）是否改善门控与拒识？ |
| `G-TOKENS` | partial | 1/1 | 1 | research | token 缓存是否携带独立信息（已知有效秩=1 的疑问）？ |
| `G-LABEL-CLEAN` | present | 2/0 | 29 | research | 干净层真值参与预训练是否正收益（还是只教合成捷径）？ |
| `G-LABEL-PHYSICAL` | partial | 1/1 | 17 | research | 退化后的 physical 层监督是否比 clean 层更贴近部署？ |
| `G-LABEL-VISIBLE` | present | 1/0 | 7 | research | 可见性标签是否改善拒识与阈值选择？ |
| `G-LABEL-BUNDLE` | present | 2/0 | 24 | research | 像素级 id/tag 标签图作为辅助监督是否正收益？ |
| `G-REL-POOL` | missing | 0/2 | 0 | research | 关系表（R1/R2/UNKNOWN）与冻结 roster 是否是可复算评测的前提？ |
| `G-DEGRADE-PHYSICAL` | missing | 0/2 | 0 | research | 各物理磨损轴分别造成多大性能下降（敏感度曲线）？ |
| `G-DEGRADE-IMAGING` | missing | 0/3 | 0 | research | 模糊/噪声/曝光/白平衡/JPEG 各轴的性能代价是多少？ |
| `G-DEGRADE-GEOMETRY` | missing | 0/3 | 0 | research | 深度误差/稀疏/空洞/位姿漂移/简化/尺度/标定/伪影各自的代价？ |
| `G-DEGRADE-PROTOCOL` | missing | 0/4 | 0 | research | 分支缺失/边界误差/上下文缺失/估计偏差/留出工况的影响？ |
| `G-CONTEXT` | missing | 0/1 | 0 | research | 受限的模拟出土上下文是否有正收益（文档要求不能等价母体 ID）？ |
| `G-DISPLAY-LOD` | missing | 0/3 | 0 | deploy | L0 与 L1/L2 的差别是否影响几何侧实验（L1/L2 当前不可得）？ |
| `G-PROVENANCE` | partial | 2/2 | 1 | research | 没有 provenance 的实验结果能否被复算（对照组必须失败）？ |

> 本文件由 `synlab/storage/export_full.py` 从 manifest 自动生成；每个数字都可在 `manifest.json` 中复算。
