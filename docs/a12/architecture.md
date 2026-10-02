# docs/a12/architecture.md — 架构与模块职责

## 1. 总览

`relicweave-synlab` 是按 A12 计划 §3.2 目录落地的**独立工程**（无主仓，见 `repo_inventory.md`）。
数据流与计划 §3.1 的资产依赖图一致：

```
冻结配置与谱系划分 ─▶ 母体与连续花纹 ─▶ 共享断裂 ─▶ CleanTruth ─▶ 分层标签
                                        └─▶ 独立物理损伤 ─▶ 观测/重建 ─▶ 特征适配
标签与特征分别提交 ─▶ 不可变发布 ─▶ 预训练与诊断
```

关键设计约束：

1. **标签与特征分离**：`synlab/truth` 产出 `TruthPack`/标签；`synlab/observe/features.py` 只产出白名单特征。
   两者是不同 asset，`forward` 只读特征 asset。
2. **单写者元数据**：`synlab/storage/store.py` + `synlab/jobs/scheduler.py`，SQLite WAL，租约 + fencing。
3. **确定性**：所有随机子流由 `synlab/seeds.py` 从显式 key 派生，不依赖 worker 编号或完成顺序。
4. **真实或结构化错误**：任何阶段失败抛 `SynLabError`，由 `synlab/pipeline.py` 隔离到单个母体。

## 2. 模块表

| 路径 | 职责 | 关键入口 |
|---|---|---|
| `synlab/schemas/` | 配置 schema、六种 Pack、Result、运行期类型 | `spec.py`, `runtime.py` |
| `synlab/canonical.py` | canonical JSON、内容哈希、语义哈希、code fingerprint | `hash_json`, `interpretation_hash`, `code_fingerprint` |
| `synlab/seeds.py` | 稳定随机子流 | `seed64`, `derive_named_rngs`, `basis_id` |
| `synlab/registry.py` | 器型/材料/层/纹样/断裂/轴注册表 | `REGISTRY`, `register_*` |
| `synlab/storage/` | 内容寻址资产库、不可变发布、网格序列化、导出 | `AssetStore`, `ReleaseManager` |
| `synlab/jobs/` | 状态机、调度、租约、预算、恢复 | `Scheduler`, `LeaseManager`, `ResourceGuard` |
| `synlab/mothers/` | 24 品种参数化母体、chart、表面标签、参数采样 | `api.create_mother`, `audit_mother` |
| `synlab/materials/` | 12 材料族、4 层组合、纯函数材料场 | `api.material_at`, `layer_combo` |
| `synlab/patterns/` | 16 族程序纹样、周期场、几何浮雕/刻线、接缝审计 | `api.build_pattern`, `evaluate`, `apply_pattern_geometry` |
| `synlab/fracture/` | 共享刀具体、四后端、来源映射、事件树 | `api.fracture_event`, `make_closed_cutter` |
| `synlab/truth/` | Clean/Physical/Visible 三层真值与关系闭合 | `api.finalize_clean_truth`, `update_residual_truth` |
| `synlab/physical/` | P01–P08 只减材料算子与损伤账本 | `api.apply_damage`, `audit_physical` |
| `synlab/cameras/` | 相机档、U 物理位移、投影/像素合同 | `api.make_view_frames`, `project`, `pixel_transform_crop_resize` |
| `synlab/observe/` | 软件光栅渲染、成像链、三条观测路线、质量与特征适配 | `api.observe`, `adapt_observed_features` |
| `synlab/degrade/` | 31 轴 registry/compiler/apply/measure | `api.compile_recipe`, `apply_axis`, `audit_all_axes` |
| `synlab/relations/` | gallery、全 R2、训练采样、困难负例 | `api.build_pool`, `sample_training_batch` |
| `synlab/training/` | 双塔 + 精排头、五任务损失、课程、checkpoint | `api.train`, `evaluate`, `resume` |
| `synlab/diagnostics/` | 固定池评测、配对统计、风险与 N90/Qcrit | `api.run_diagnosis`, `stats.clopper_pearson_upper` |
| `synlab/episodes/` | 可达动作、成本、STOP、规则基线 | `api.EpisodeEnv` |
| `synlab/qc/` | run 审计、发布门、资源 profile、A01–A36 验收 | `audit_run`, `evaluate_gates`, `run_acceptance` |
| `synlab/api/` | FastAPI 路由、角色鉴权、SSE、分页 | `app.create_app` |
| `synlab/cli.py` | 第 22.4 节全部 CLI 入口 | `synlab <command>` |
| `frontend/` | U01–U12 页面（React + TS + Vite） | `frontend/src/features/synlab` |

## 3. 运行链（单母体）

`synlab/pipeline.py::build_one_mother` 严格按计划 §22.5 顺序执行：

```
derive_named_rngs → create_mother → audit_mother → material_at profile
→ build_pattern（断裂前冻结）→ apply_pattern_geometry（如需）
→ fracture_event → audit_fracture → finalize_clean_truth
→ apply_damage → update_residual_truth → observe
→ update_visibility_truth → adapt_observed_features
→ commit(features) / commit(labels) / commit(provenance)
```

每一步都写入 `coverage.parquet`（planned/attempted/accepted/quarantined + 拒绝原因 + 参数分位）。

## 4. 状态与诚实性

模块状态：`SPECIFIED / IMPLEMENTED / QA_PASSED / VALIDATED / RELEASED / PENDING / MISSING`。
未运行 = `NOT_RUN`，不适用 = `NA`。缺失的外部后端（Blender、实拍数据、CUDA）在
`docs/a12/backend_capabilities.json` 与验收报告中显式标 MISSING/PENDING，
**不会**被替代路线或 UI 文案掩盖。

## 5. 发布 profile

发布门定义在 `synlab/storage/release.py::PROFILE_GATES`，由 `synlab/qc/gates.py` 按**实际证据**判定：

| Profile | 含义 |
|---|---|
| SANDBOX_CORE | 小 fixture 闭环通过 |
| PILOT | train/dev 谱系 + 实际使用的算子过门 |
| CORE_COVERAGE | 24 器型/12 材料/4 层/16 纹样/四后端/31 轴 + 实际 MVS 子集 |
| SCALE_10K/50K/100K | 对应规模的已接受嵌套数据与可运行 loader/index |
| CALIBRATED_PHONE | 独立实拍 + PHONE_RGB MVS/尺度/掩码校准（本机 PENDING） |
| RESEARCH_EVIDENCE | 冻结协议的完整研究运行（结论允许 NOT_SUPPORTED） |
