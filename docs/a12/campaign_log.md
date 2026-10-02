# A12 持续批量合成数据 — campaign log

**这一篇只写真数。** 每个计数都来自 `AssetStore` 的资产记录、`tools/batch_generate.py` 的 ledger，
或确定性 plan；没有任何"估计/接近/应该"。被宿主杀掉的批记 `PROCESS_KILLED` 并续跑；失败的谱系进分母，
不改数据、不放宽闸门。

- 生成器：`tools/batch_generate.py`（未修改其测量逻辑；仅由 `data/a12_campaign/_run_batch_pinned.py` 外包一层代码指纹）
- 写域：`data/a12_campaign/**`（新库 `store/`、`store_control/`）、`data/a12/reports/**`、本文件
- 未触碰：`synlab/**`、`configs/**`、`frontend/**`、`data/a12/**`、`data/a12_demo/**`

---

## 1. 世代指纹（open-time fingerprint）

写入 `data/a12_campaign/campaign_manifest.json`。

| 项 | 值 |
|---|---|
| git HEAD | `c3a149f6aee73245db7c3540e55c0292da2d1a66` (`snapshot: land the geometry, relations, training, observe and acceptance work streams`, 2026-10-02 12:06:54 +0800) |
| 工作区 | **dirty，38 个已修改文件**（`synlab/**` 17 个 + `frontend/**` 4 个 + `tests/**` 2 个 + 其余） |
| `REGISTRY.fingerprint()` | `sha256:05f69981b63e739f8533b51cee98e54f296fba89d823abf8779814ef2b9624fb` |
| registry 计数 | vessel 24/24 IMPLEMENTED、material 12/12、layer_combo 4/4、pattern 16/16、axis 31/31、fracture_backend 5（3 IMPLEMENTED / 1 PENDING / 1 MISSING） |
| `load_all()` 导入错误 | **0** |
| 使用的 config | `configs/a12/realistic.yaml` = `sha256:d9d0c25ff7b4d0541450975a6cbed80c6a8275f68e1a2b03398935ab35240116` |
| 冻结基线 | `configs/a12/next_experiment.yaml` = `sha256:8186653101612cbc20e9eeba3f60ffbc241e3d1e3ebd690fdecb60746ab1fb16` — **实测未改动（与任务书给的 sha256 一致）** |
| `validate` 退出码 | **0**（`python -m synlab.cli validate --config configs/a12/realistic.yaml` → `OK`，spec_hash `sha256:6512bbce6ad6eea0ca257c66e309a7402bb585f90b13e7f3ebb748862e63986c`） |
| plan | job `job_34d5b488084742780ca32643`，planned **120** 母体（train 99 / dev 10 / confirm 11） |

`realistic.yaml` 已存在（另一名队友在建），按任务书**优先使用它**；冻结基线作为对照（见 §4）。

### 1.1 代码身份是移动靶（实测，不是推测）

`synlab/observe/quality.py`、`features.py`、`pipeline.py`、`fracture/voronoi_event.py`、
`storage/export.py`、`api/routers/synthesis.py`、`observe/routes.py` 等 **11 个模块在同一分钟内被重写**
（实测 mtime 13:08:17–13:08:44）。Python 在进程启动时载入模块，因此**同一 config 的两批可能由两版代码产出，
计数不可比**。

对策：`data/a12_campaign/_run_batch_pinned.py` 在子进程**启动前**与**退出后**各对
`synlab/**/*.py` + `tools/batch_generate.py`（175 个文件）做一次 sha256，落
`data/a12_campaign/logs/<batch>.code.json`，并记录 `code_stable_during_batch`。
`data/a12_campaign/_readiness.py` 是只读就绪探针（语法编译 + 静默窗口 + plan 可加载），退出码 0=READY / 3=NOT_READY。

---

## 2. 真实失败（进分母）

### 2.1 `KeyError: 'nn_spacing_p95'` — 曾使**全部**谱系失败（含任务书给的"已知可跑通"两条）

批 1（`configs/a12/realistic.yaml`，`--batch 4 --resume`）：

| # | 谱系 | 结果 | 真实错误码 | frag | obs | r2 | 耗时 |
|---|---|---|---|---|---|---|---|
| 1 | `LIN0000_V10_M11_PAT15` | FAILED | `UNEXPECTED` / `KeyError: 'nn_spacing_p95'` | 6 | 72 | None | 139.8 s |
| 2 | `LIN0001_V21_M06_PAT16` | FAILED | `UNEXPECTED` / `KeyError: 'nn_spacing_p95'` | 2 | 24 | None | 99.5 s |
| 3 | `LIN0002_V23_M07_PAT12` | FAILED | `UNEXPECTED` / `KeyError: 'nn_spacing_p95'` | 3 | 36 | None | 99.0 s |
| 4 | （第 4 条母体） | **PROCESS_KILLED** | 宿主杀进程 `exit -1`，未落 ledger | — | — | — | — |

> 第 2、3 条正是任务书标注为 frag=2/3、obs=24/36、r2=1/2 **可跑通**的那两条，观测数完全对上
> （24/36），但 accepted 为 false —— 即 observe 之后的下游阶段抛异常。

**真实机理（读代码得出，非猜测）**：`synlab/observe/quality.py::estimate_quality` 只在
`points is not None` 且 `n_pts >= 2` 时写 `nn_spacing_p95`（旧版第 172–174 行），而
`n_pts < 2`（0 或 1 点）这一分支旧版只写了 `nn_spacing_median`。`photo_mvs` 路线在
pycolmap SfM 失败时以 `STOP_SFM` 收尾并交出**空点云**，于是
`synlab/observe/features.py::_quality_features` 的固定 key 元组解包抛 KeyError，
在 observe 已成功、frag/obs 已计入之后**整条谱系作废**。

现场证据：日志里 pycolmap 打印
`W20261002 ... incremental_pipeline.cc:259] No images with matches found in the database`
与 `=> No good initial image pair found.`。

**修复来自队友（不是本 session 改的）**：13:08:26 `quality.py` / `features.py` 被改动，
正是"每个分支都写全 key + 缺失条目降级为 invalid 而不抛异常"。本 session 对 `synlab/**` **零写入**。

**因此下面的批次必须按代码身份分开读**：
- 批 1 跑在 13:08:26 **之前**的修订上 → 3/3 失败于 `KeyError`；
- 13:08:26 之后重跑的两批（`control_01`、`realistic_03`）撞上**更早的**语法级故障（见 2.2）。

### 2.2 `IndentationError` in `synlab/observe/routes.py` — 半保存状态

13:09 之后启动的两批，每条母体在 **0.5 s 内**失败：

```
IndentationError: expected an indented block after 'if' statement on line 275 (routes.py, line 277)
```

这是队友正在编辑中的半保存文件，与生成逻辑无关；两批各自连跑 4 条只会得到 4 条完全相同的导入失败，
故**主动停止**（未把这些计入"生成失败"分母，它们没有产出任何母体；ledger 里逐条留痕）。

### 2.3 其他真实失败（历史，来自任务书与我方实测）

- `LIN0000_V10_M11_PAT15` 曾报 `FRACTURE_CONSERVATION_FAIL`；本次实测它先走完了 fracture（frag=6）
  与 observe（obs=72），最终死在 `KeyError`。**同一谱系，不同首因，说明失败码随代码版本漂移。**

---

## 3. 方法：每批怎么记

1. `_readiness.py` 确认 READY（0）；
2. `_run_batch_pinned.py --name <批名>` 调 `tools/batch_generate.py --batch N --resume --ledger ...`，
   同时落代码指纹 sidecar；
3. `_append_batches.py` 把 ledger 里**每条母体**的真实结果追加进
   `data/a12/reports/campaign_batches.json`（追加式；因为 `run_id` 由 plan job id 派生、每次调用相同，
   批次按**母体之间的真实时间间隔**切分，被杀的批记 `killed_by_host: true`）；
4. `_survey.py` 汇总多元化矩阵 → `data/a12_campaign/campaign_survey.json`；
5. 质量闸门：`tools/check_data_quality.py --store <root>`，记录退出码与首因。

---

## 4. （待补）批次表与多元化矩阵

代码稳定后逐批追加。当前**已被 store 提交的真实资产**（用于证明分母不是 0）：

| 指标 | realistic store | control store |
|---|---|---|
| accepted 谱系 | 见 §5 | 见 §5 |

> 本节在批次跑完后由 `_append_batches.py` + `_survey.py` 的真数填充；在填之前不写任何数字。

---

## 5. （待补）质量闸门逐次结论 / 失败原因分布 / 距"可训练"还差什么

见文末收尾章节。
