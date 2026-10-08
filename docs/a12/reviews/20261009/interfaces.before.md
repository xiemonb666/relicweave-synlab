# A12 冻结接口契约（模块间唯一权威）

本文件是 `relicweave-synlab` 各模块之间**已冻结的接口**。任何模块都不得自行重定义下列
类型、函数名、资产角色或单位；需要变更时必须同时修改本文件并由 Lead 复核。

权威定义在代码中（本文件只是索引与约定）：

| 契约 | 文件 |
|---|---|
| 错误码 / Result | `synlab/errors.py` |
| 稳定随机数 | `synlab/seeds.py` |
| canonical JSON / hash / code fingerprint | `synlab/canonical.py` |
| 运行期类型（Chart/MotherGeometry/Fragment/...） | `synlab/schemas/runtime.py` |
| 配置 schema（synlab.v3 / train.v1 / diagnose.v1） | `synlab/schemas/spec.py` |
| 注册表（器型/材料/纹样/断裂/轴） | `synlab/registry.py` |
| 资产库 / 发布 / 网格序列化 | `synlab/storage/{store,release,mesh_io}.py` |
| 调度 / 租约 / 预算 | `synlab/jobs/{scheduler,leases,resources,state}.py` |
| 资产角色与单位常量 | `synlab/roles.py` |

## 0. 环境

* 解释器：`C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\.venv\Scripts\python.exe`（Python 3.12.14）
* 已安装：numpy, scipy, scikit-image, opencv-python-headless, pillow, pyarrow, pandas, pydantic,
  typer, sqlalchemy, trimesh 5.1, manifold3d 3.5.4, shapely, svgpathtools, fastapi, uvicorn,
  httpx, networkx, jsonschema, torch 2.14.1+cpu, **gmsh 4.15.2, open3d 0.20.0, pycolmap 4.2.1, faiss-cpu 1.15.1**
* 不存在：Blender（`bpy` 无 Windows/py3.12 wheel）、独立 COLMAP 可执行文件（用 `pycolmap` 库）、真实实拍数据、CUDA torch（仅 CPU）
* 运行测试：`& .venv\Scripts\python.exe -m pytest tests -q`

## 1. 通用约定

* 权威几何单位 **毫米**、右手系。Blender/GLB 的米制只在显示层经 `T_display_authority` 转换。
* 图像像素中心约定：OpenCV（左上像素中心 = (0,0)）；导出 COLMAP 时 `cx+0.5, cy+0.5`（plan 30.3）。
* 每个随机子流用 `synlab.seeds.make_rng(master_seed, lineage_id, module)`；
  `pattern.evaluate` **禁止**取随机数。
* 所有可进入模型的字段必须带 `value + unit/frame + source_kind + source_ref + valid`。
* 失败一律抛 `synlab.errors.SynLabError(ErrorCode.X, ...)`；禁止返回空 mesh/假数据。
* 网格面级语义必须随 mesh 保存：`synlab.storage.mesh_io.with_face_attrs(mesh, surface_tag=..., ...)`
  写入 `mesh.metadata["face_attr_arrays"]`，经 `mesh_arrays()`/`arrays_to_mesh()` 往返不丢。

## 2. 每个模块必须导出的门面（`<pkg>/api.py`）

所有模块的 `api.py` 至少导出下列函数（返回 runtime dataclass，抛结构化错误）：

| 模块 | 函数 |
|---|---|
| `synlab.mothers.api` | `create_mother(vessel_id, material_id, params, rng, *, mother_id) -> MotherGeometry`；`audit_mother(mother) -> dict`；`sample_parameters(vessel_id, n, rng) -> list[dict]` |
| `synlab.materials.api` | `build_material_profile(material_id, params, rng) -> dict`；`material_at(profile, points_mm, surface_tag) -> MaterialSample`；`layer_combo(combo_id, params, rng) -> list[LayerSpec]`；`commit_material(store, ...)` |
| `synlab.patterns.api` | `build_pattern(mother, spec, rng) -> PatternRecipe`；`evaluate(recipe, mother, points_mm, surface_tag) -> PatternChannels`；`apply_pattern_geometry(mother, recipe, channels, ...) -> MotherGeometry`；`audit_pattern(...) -> dict` |
| `synlab.fracture.api` | `fracture_event(mother, spec, rng, *, event_id) -> FractureResult`；`make_closed_cutter(mother, spec, rng, basis=None) -> CutterResult`；`audit_fracture(result, mother) -> dict` |
| `synlab.truth.api` | `finalize_clean_truth(mother, result) -> CleanTruth`；`update_residual_truth(clean, physical) -> PhysicalTruth`；`update_visibility_truth(physical_truth, observations) -> VisibleLabels` |
| `synlab.physical.api` | `apply_damage(clean_truth, fragment, recipe, rng) -> PhysicalResult`；`audit_physical(result, clean) -> dict` |
| `synlab.cameras.api` | `camera_profiles() -> list[CameraProfile]`；`make_view_frames(profile, target_bbox, count, rng, *, tier_mix) -> list[ViewFrame]`；`project(points_mm, K, T_WC) -> (uv, z)`；`pixel_transform_crop_resize(...) -> (K_new, A)` |
| `synlab.observe.api` | `observe(physical, compiled, rngs, *, route) -> ObservationResult`；`adapt_observed_features(obs, contract) -> dict`；`estimate_quality(obs) -> dict` |
| `synlab.degrade.api` | `compile_recipe(spec) -> CompiledRecipe`；`apply_axis(axis_id, level, source, store, *, rng, variant) -> (output_ref, Measurement)`；`audit_axis(axis_id, levels, store, ...) -> dict`；`AXIS_REGISTRY` |
| `synlab.relations.api` | `build_pool(store, release, spec) -> GallerySpec`；`sample_training_batch(pool, sampler_cfg, rng) -> dict`；`mine_hard_negatives(...) -> list` |
| `synlab.training.api` | `train(spec, store) -> dict`；`evaluate(checkpoint_ref, pool_ref, ...) -> dict`；`resume(run_ref, store) -> dict` |
| `synlab.diagnostics.api` | `run_diagnosis(spec, store) -> dict`；`pool_metrics(...)`；`paired_bootstrap(...)`；`clopper_pearson_upper(e, n, alpha)` |
| `synlab.episodes.api` | `EpisodeEnv(store, pool, cameras)`；`available_actions(state)`；`step(state, action)` |
| `synlab.api.app` | `create_app(store_root, *, role) -> FastAPI` |

`commit_*` 约定：需要持久化的模块额外导出 `commit_<name>(store, obj, *, lineage_id, split, ancestry) -> AssetRecord`
与 `load_<name>(store, asset_id) -> obj`，角色名取自 `synlab/roles.py`。

## 3. 主轴与断裂后端 ID

* 器型 `V01..V24`、材料 `M01..M12`、层组合 `L01..L04`、纹样 `PAT01..PAT16`
* 断裂后端：`plane_shared_cut`、`rough_shared_cut`、`warped_partition`、`secondary_fracture`（必做），`fracture_modes`（选配）
* 退化轴：`P01..P08`、`I01..I10`、`G01..G08`、`X01..X05`（共 31）
* 每轴五档 level 0..4，level 0 必须是**真恒等**（返回原 asset 引用/字节，不重采样）
* 每个 variant 必须声明 `factor_kind ∈ {SINGLE_PARAMETER, ONE_DIMENSIONAL_RECIPE, BUNDLED_STRESS, CATEGORICAL_SHIFT}`

## 4. 诚实状态规则

模块状态只允许 `SPECIFIED / IMPLEMENTED / QA_PASSED / VALIDATED / RELEASED / PENDING / MISSING`。
未运行写 `NOT_RUN`；不适用写 `NA`。**禁止**用随机曲线、假进度、空实现、固定图片、预填排行榜冒充结果。
外部后端缺失（Blender/实拍数据/CUDA）必须报 `ENV_CAPABILITY_MISSING` 或 `PENDING`，并记录替代路线。
