# A12 下一批实验数据：批产执行报告

- 本文件由本轮真实执行产出，所有数字都能从 `data/a12/metadata.sqlite`、`data/a12/reports/next_experiment_batches.json`
  与 `data/a12/reports/next_experiment*` 下的日志复算；复算脚本见文末「复现步骤」。
- 规格来源：`docs/a12/v144_data_requirements.md`（队友抽取）+ `configs/a12/next_experiment.yaml`。
- 本报告只写真实计数与真实失败；accepted 一律指"真实提交且 `label_bundle` 为 `QA_PASS`"的谱系。

---

## 0. 一句话结论

本轮按 `configs/a12/next_experiment.yaml` 在 `data/a12` 上真实产出了 **N_ACCEPTED 条独立谱系**
（每条 ≥2 片、12 观测、≥1 个 R2 对），并跑通了 pool / 导出包 / loader_probe。
**未达成的部分（纹样族覆盖、各轴 ≥20 母体、PILOT release 冻结）在 §6 逐条给出真实原因与最小修法。**

---

## 1. 环境与前置校验（命令 + 退出码）

| # | 命令 | 退出码 | 结果 |
|---|---|---|---|
| 1 | `.venv\Scripts\python.exe -m synlab.cli doctor --root data/a12 --out data/a12/reports/env_report.json --capabilities-out data/a12/reports/backend_capabilities.json --json` | **0** | 39 PASS / 0 FAIL / 0 MISSING；`backend:blender_render` = PASS（`BLENDER_BIN` = `third_party/blender-5.2.2-windows-x64/blender.exe`） |
| 2 | `.venv\Scripts\python.exe -m synlab.cli validate --config configs/a12/next_experiment.yaml --json` | **0** | `OK`，`warnings: []`，`spec_hash: sha256:aa231f9ced9b98bbdeaeedd668f37fb2d767ab979ace0a5beaf8f53f804005c0` |

> 这一条直接**解除**了 `docs/a12/v144_data_requirements.md` §8.2 的风险 R3（"本机无 Blender/bpy，
> `renderer: auto` 会退回软件光栅器"）。实测 Blender 真实可用，`renderer: auto` 走真实渲染。

---

## 2. 生成配置的关键参数（含相对草案的 6 处改动）

`configs/a12/next_experiment.yaml`，schema `synlab.v3`；文件头 (1)–(6) 记录了每处改动及其实测依据。

| 字段 | 草案值 | **本轮执行值** | 依据 |
|---|---|---|---|
| `fracture.backend` | `rough_shared_cut` | **`plane_shared_cut`** | rough 在 0.01 mm 预算下实测 `realized_error_mm≈0.226`（R2），会把整批打成 `PRECISION_NOT_REALIZED` |
| `dataset.target_mothers` | 100 | **120** | 实测每母体 ≈23–414 s（瓶颈 100% 在 `physical` 阶段），120 是本机机时内可承受的量 |
| `dataset.target_fragments_estimate` | 2000 | **240** | 实测每母体真实产出 2–12 片；该字段只用于预算估算，不参与切割 |
| `fracture.target_piece_range` | `[12, 28]` | **`[2, 4]`** | 实测该字段**不被 fracture 代码读取**（`synlab/fracture/api.py::_coerce_spec` / `fracture_event`）；真实片数由后端与连通分量决定。写成实测区间 |
| `fracture.secondary_probability` | 0.15 | **0.0** | 同上：该字段在本构建无执行点；留 0.15 会让文档暗示"15% 母体二次破碎"而实际不会 |
| `resources.cpu_workers` | 4 | **2** | 本机 2 物理核；pipeline 逐母体串行，`cpu_workers` 不影响墙钟 |

保持文档值未改的关键项：`observation.views_per_fragment: 12`、`image_long_edge_px: 1024`、
`point_count: 8192`、`renderer: auto`、`master_seed: 20261001`、`shape_lineage_split: {train: 0.8, dev: 0.1, confirm: 0.1}`、
`vessel_ids: V01–V24`、`material_ids: M01–M12`、`pattern_ids: PAT01–PAT16`、`layer_combo_ids: L01–L04`。

> 实测备注：`image_long_edge_px` 512 与 1024 在本机的**总耗时几乎相同**（瓶颈是 `physical` 的 SDF/marching-cubes，
> 不是渲染），因此没有理由降规格；512 px 只在探针阶段用于标定，正式批次一律 1024。

### 2.1 为什么用 `tools/batch_generate.py` 而不是直接 `synlab.cli generate`

`run_generation` 会**一次把 `target_mothers` 全部母体建完**。本机每母体 1.5–7 分钟，120 母体不可能在一个进程里跑完
（宿主会杀长重负载进程，退出码 -1/1，无 traceback）。新增的 `tools/batch_generate.py`：

1. 用与 `run_generation` **同一个** `plan_generation` 建计划（计划只由 `master_seed`、四个 ID 列表与 `target_mothers`
   决定，与"已经跑过多少母体"无关）→ 分批不会移动任何谱系；
2. 问 store 哪些谱系已 accepted，跳过它们（`--resume`）；
3. 一次最多建 `--batch` 个母体，**每建完一个母体就把一行进度写盘**到
   `data/a12/reports/next_experiment_batches.json`；被宿主杀掉时最多丢在飞的那一个母体，账本仍记着它是谁；
4. 失败进真实分母（planned/attempted/accepted/failed），不静默重试；只有 accepted 才算完成；
5. 新增 `--expect-config-sha256`：配置一变就中止（见 §7.1，这条护栏是本轮踩到坑之后加的）。

---

## 3. 分批产数：每批计数与耗时

命令（每批一次，跑完立刻用 `--resume` 续下一批）：

```
.venv\Scripts\python.exe tools\batch_generate.py ^
  --config configs\a12\next_experiment.yaml --root data\a12 ^
  --batch 6 --resume ^
  --expect-config-sha256 sha256:8186653101612cbc20e9eeba3f60ffbc241e3d1e3ebd690fdecb60746ab1fb16
```

原始日志：`data/a12/reports/next_experiment/batch_NN.out` / `batch_NN.err` / `batch_runner.log`。

BATCH_TABLE_PLACEHOLDER

---

## 4. 最终覆盖矩阵

COVERAGE_PLACEHOLDER

---

## 5. 池、导出包与 loader

POOL_EXPORT_PLACEHOLDER

---

## 6. 缺口（为什么某些轴/后端/维度没进这批）

GAPS_PLACEHOLDER

---

## 7. 阻塞与最小修法（不修改 `synlab/**` 的前提下）

BLOCKERS_PLACEHOLDER

---

## 8. 复现步骤

REPRO_PLACEHOLDER
