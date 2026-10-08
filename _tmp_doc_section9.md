## 9. 生成链接入：退化多样性（`degrade_diversity`，2026-10-02 追加）

§1–§8 说的是**模块级**的 31 轴算子与它们的审计；本节说的是**数据级**的事：让生成链
（`run_generation` → `build_one_mother`）在一条谱系生成完成后，按配置在**该谱系自己的**
几何/观测上真的产出「轴 × 档位」退化资产，并把计数、basis、逐档实测写到盘上。

### 9.1 配置：`configs/a12/degrade_diversity.yaml`（新文件；`next_experiment.yaml` 未动）

| 字段 | 值 | 含义 |
|---|---|---|
| `schema` | `synlab.degrade_diversity.v1` | 配置模式，`load_diversity_config` 逐条校验 |
| `enabled` | `true` | `false` 时整步入 no-op（且不读盘） |
| `data_semantics` | `degrade_diversity_v1` | 写入每个退化资产 `meta.degrade_diversity` 的语义标签 |
| `levels` | `[0, 1, 2, 3, 4]` | 每轴默认档位；**必须含 level 0**（缺 level 0 直接报错） |
| `per_lineage.max_axes` | `9` | 一条谱系物化多少条轴 |
| `per_lineage.selection` | `declared` | `declared`=声明顺序前 N 条；`rotate`=以 `mother_index` 起轮转（多谱系批量时用固定轮转覆盖全部轴） |
| `axes[]` | 9 条（下表） | 每条声明 `axis_id / family / stage / variant / note` |
| `roles.source` / `roles.variant` | `degrade_source` / `degrade_variant` | 角色声明（代码常量同值） |

| 轴 | 阶段（注册表） | variant | 语义 |
|---|---|---|---|
| `P03` | PHYSICAL | `smooth_recession_field` | 几何磨损（界面 ROI 平滑退让，窄带后端） |
| `I01` | OPTICS | `gaussian_psf` | 光学模糊（高斯 PSF 离焦） |
| `I03` | SENSOR | `photon_scale` | 传感器噪声（光子量级 + 读出噪声） |
| `I05` | ISP | `fixed_direction_wb` | 白平衡（固定方向色偏） |
| `I09` | ISP | `antialiased_downsample` | 分辨率降采样（抗混叠） |
| `G05` | GEOMETRY_OBS | `qem_decimation` | 观测几何简化（QEM 抽面 + Hausdorff 预算） |
| `G08` | GEOMETRY_OBS | `bump` | 观测几何伪影（标注型凸起，只改观测侧） |
| `X01` | FEATURE_PROTOCOL | `presence_removal` | 协议：模态缺失（`present=false`，不零填充） |
| `X04` | FEATURE_PROTOCOL | `regression_bias` | 协议：估计回归偏置（`bias = bias_sigma × 实测通道 std`） |

`load_diversity_config` 的硬错误（**逐条报错，不静默跳过**）：未知 `axis_id`；`family` ≠ axis_id 首字母；
`stage` 与注册表不一致；variant 未注册；档位超出 `LEVEL_COUNT`；缺 level 0；同一轴声明两次；
`selection` 不在白名单。

### 9.2 接入点（`synlab/pipeline.py`，最小改动）

| 位置 | 内容 |
|---|---|
| `build_one_mother(..., degrade_cfg=None)` | 新增**第 9 步**：`if degrade_cfg is not None: _materialize_degrade_diversity(...)` |
| `run_generation(..., degrade_diversity=None)` | 解析开关并透传；覆盖层新增 `degrade_diversity` 计数块（`_degrade_diversity_totals`） |
| `_resolve_degrade_diversity(override)` | `None`→读环境变量 `SYNLAB_DEGRADE_DIVERSITY`（未设 = **完全跳过，不读任何配置**）；`True`→默认配置；字符串→配置路径；`False`→关 |
| `_materialize_degrade_diversity(...)` | 取本谱系真实资产做源，调 `materialize_lineage_diversity`，把 summary/资产 id/报告路径写进 coverage row |

**向后兼容**：未显式要求时该步不读配置、不提交资产、不改任何既有资产 id；`pytest tests/a12/integration`
的 L0 全链测试（不传开关）行为逐位不变。

`synlab/degrade/diversity.py`（新文件，在 `synlab/degrade/**` 内）：

* `load_diversity_config` / `DiversityConfig.axes_for_lineage`
* `load_p_family_source`：P 族源 = 本谱系**靶碎片 mesh 资产**（`fragment_mesh`）读回成 bundle，
  **不重新提交**，level 0 直接引用它；
* `commit_observation_sources`：I/G/X 族源 = 本谱系**主观测**经 `bundles_from_observation` 投影后
  以 `degrade_source` 提交，**读回后的 bundle** 才是退化源（`source_hash` 就是 level 0 引用的字节）；
* `materialize_lineage_diversity`：逐轴冻结一次 basis、逐档 apply → 提交 → **每档写盘**；
* `summarize_report` / `asset_bytes` / `directory_bytes`。

**资产契约**（每档，`role = degrade_variant`，**绝不是 `feature_bundle`**）：
`meta` 含 `axis_id / family / stage / substage / variant / level / factor_kind / basis_id /
basis_seed_ref / planned / measured / units / realized / identity / source_hash / result_hash /
source_asset_id / source_kind / status / label_invalidations / label_status / calibration_status /
data_semantics / degrade_diversity`，`ancestry=[source_asset_id]`（release closure 可从 variant 走回源资产）。
`qa_status` = 算子自己的判定（`realized` → `QA_PASS`，否则 `QA_FAIL` 且带 `failure_codes`），
所以退化资产能进 release scope，而不会被留在 `QA_PENDING` 里假装是数据。
**level 0 不提交资产**：返回源资产记录，`identity=true`、`result_hash == source_hash`、
`identity_reference_ok=true`。

### 9.3 命令与退出码

| 命令 | 退出码 | 结果 |
|---|---|---|
| `& .venv\Scripts\python.exe _tmp_run_degrade_diversity.py 1 n1`（沙箱谱系 + 退化多样性） | **0** | 1/1 谱系 accepted；见 §9.4 |
| `& .venv\Scripts\python.exe _tmp_analyze_degrade_diversity.py` | **0** | 逐轴/逐档实测 → `data/a12_reports/degrade_diversity_measurements.json` |
| `& .venv\Scripts\python.exe _tmp_export_degrade_diversity.py` | **0** | 冻结 release + 导出训练包 → 见 §9.6 |
| `& .venv\Scripts\python.exe -m pytest tests/a12/operators/test_diversity.py -q` | **0** | 17 passed |
| `& .venv\Scripts\python.exe -m pytest tests/a12/operators tests/a12/integration -q` | 见 §9.7 | — |

### 9.4 单谱系实测（`data/a12_degrade/store`）

```
lineage   LIN0000_V02_M01_PAT02   split=train   accepted=1
axes      9/9 物化（8 OK，1 有档位未达成 → G05 L1–L3 FAILED，见 §9.7）
levels    45 planned = 9×5；42 OK（含 9 个 identity）；3 FAILED；0 NA
assets    33 个 degrade_variant + 3 个 degrade_source（I/G/X）+ level 0 复用靶碎片/观测资产
identity  9/9 identity_reference_ok；9/9 bytes_unchanged（result_hash == source_hash）
basis     9/9 轴五档同一 basis_id（basis_shared_per_axis=true）
耗时      退化多样性 9.63 s（整条谱系 130.6 s，wall 141.5 s）
磁盘      整库 96.2 MB；其中退化层 76.4 MB（variant 70.4 MB + source 6.1 MB），谱系自身产物 ~19.8 MB
```

逐轴（`sec`=该轴 5 档总耗时，`bytes`=提交的 variant 字节）：

| 轴 | 状态 | basis_id | 档位 | sec | bytes |
|---|---|---|---|---|---|
| P03 | OK | `a1b74d9bec…` | 0I 1O 2O 3O 4O | 3.00 | 485 888 |
| I01 | OK | `d00be4185b…` | 0I 1O 2O 3O 4O | 0.49 | 17 367 552 |
| I03 | OK | `cc85d2e7ee…` | 0I 1O 2O 3O 4O | 0.88 | 17 376 661 |
| I05 | OK | `29551a7dc2…` | 0I 1O 2O 3O 4O | 0.61 | 17 378 149 |
| I09 | OK | `7a1b9fff85…` | 0I 1O 2O 3O 4O | 0.41 | 8 201 837 |
| G05 | **FAILED** | `7cd6999555…` | 0I 1F 2F 3F 4O | 3.65 | 1 158 407 |
| G08 | OK | `d50a79957e…` | 0I 1O 2O 3O 4O | 0.27 | 4 544 419 |
| X01 | OK | `2a48e6b469…` | 0I 1O 2O 3O 4O | 0.12 | 1 459 890 |
| X04 | OK | `0b10028703…` | 0I 1O 2O 3O 4O | 0.13 | 2 400 723 |

（`I`=IDENTITY，`O`=OK/REALIZED，`F`=FAILED；完整 basis_id 与逐档 `asset_id` 见
`data/a12_reports/degrade_diversity_measurements.json`。）

### 9.5 逐档实测（同一轴五档，同一 basis，真实测量）

**P03 几何磨损**（declared `depth_mm` → 实测顶点位移，单位 mm；ROI 1214 面）

| 档 | planned depth | applied | 实测最大退让 | 实测最大顶点位移 | 实测平均顶点位移 | 丢失体积 mm³ |
|---|---|---|---|---|---|---|
| L0 | 0（恒等） | — | — | — | — | 0（引用源字节） |
| L1 | 0.05 | 0.05 | 0.05 | 0.046209 | 见 JSON | 12.93 |
| L2 | 0.10 | 0.10 | 0.10 | 0.090767 | 见 JSON | 25.98 |
| L3 | 0.25 | 0.25 | 0.25 | 0.222752 | 见 JSON | 64.86 |
| L4 | 0.50 | 0.50 | 0.50 | 0.442003 | 见 JSON | 129.79 |

**I01 模糊**（高斯 PSF）

| 档 | planned σ (px) | 清晰度（前） | 清晰度（后） | 下降比 | 梯度能量（前→后） |
|---|---|---|---|---|---|
| L0 | 0（恒等） | 0.385249 | — | — | — |
| L1 | 0.5 | 0.385249 | 0.098295 | 0.744855 | 0.537061 → 0.315551 |
| L2 | 1.0 | 0.385249 | 0.002498 | 0.993517 | 0.537061 → 0.091012 |
| L3 | 2.0 | 0.385249 | 0.000099 | 0.999744 | 0.537061 → 0.025371 |
| L4 | 4.0 | 0.385249 | 0.000007 | 0.999982 | 0.537061 → 0.007123 |

**I03 传感器噪声**（`photon_scale`）

| 档 | planned `photon_gain` | 实测噪声 σ（前） | 实测噪声 σ（后） | σ 增量 |
|---|---|---|---|---|
| L0 | 0（恒等） | — | — | — |
| L1 | 16000 | 0.0 | 0.0055610 | 0.0055610 |
| L2 | 8000 | 0.0 | 0.0055699 | 0.0055699 |
| L3 | 4000 | 0.0 | 0.0055527 | 0.0055527 |
| L4 | 1000 | 0.0 | 0.0055712 | 0.0055712 |

> **如实记录**：四档的 σ 在 0.00555–0.00557 之间（≈1.4/255），**在交付的 8 位 RGB 上无法区分**。
> 算子的 `realized` 判据是「σ 增大」，四档都满足，所以资产是 QA_PASS；但档位间的**强度差没有被
> 8 位量化表达出来**——这是缺口，不是成功（见 §9.7）。

**I09 降采样 / I05 白平衡 / G08 观测伪影 / X01 协议 / X04 协议 / G05 抽面**（同表其余轴）

| 轴 | L1 | L2 | L3 | L4 |
|---|---|---|---|---|
| I09 长边 px（前 256） | 192 | 128 | 64 | 32 |
| I09 `resize_realized` | 0.75 | 0.50 | 0.25 | 0.125 |
| I05 R/G 比值（前 1.067495） | 1.094183 | 1.120870 | 1.174245 | 1.280994 |
| G05 面数（前 1880） | FAILED（预算 0.01 mm） | FAILED（0.025） | FAILED（0.05） | 1645（Hausdorff 0.0759 mm，预算 0.1） |
| G08 实测最大位移 mm（planned 0.4/0.8/1.4/2.2） | 0.314027 | 0.701519 | 1.200755 | 1.005666 |
| X04 均值位移（= −`bias_sigma`×实测 std 6993.708） | −349.685 | −699.371 | −1398.742 | −2447.798 |
| X01 缺失模态数（共 4） | 1 | 2 | 3 | 4 |

### 9.6 导出与训练包 + 邻片检索角色

`_tmp_export_degrade_diversity.py`：`audit_run` + `write_audit_report` → `evaluate_gates(evidence_dirs=["data/a12"])`
→ `ReleaseManager.freeze` → `export_training_package`。计数见 `data/a12_reports/degrade_diversity_export.json`。

* 训练包根部新增 `degrade/index.json`、`degrade/variants.json`、`degrade/sources.json`
  （**不放进任何 view**，因此 deploy 视图的字段扫描不会把它误认成特征通道），
  manifest 新增 `degrade_diversity` 块与 `counts.degrade_*` 计数。
* 导出字段：`asset_id / role / schema / unit / frame / qa_status / lineage_id / split / blob_hash`
  + `axis_id / family / stage / substage / variant / level / factor_kind / basis_id / basis_seed_ref /
  planned / measured / units / realized / identity / source_hash / result_hash / source_asset_id /
  source_kind / status / label_invalidations / label_status / calibration_status`。
* **邻片检索里的角色**（写进 `degrade/index.json.retrieval_role`，供 pool 构建器按字段取用）：
  * 同 `source_asset_id`、不同 `level` → **同一个物理碎片的两种退化**：是「同实例」正例
    （退化不变性/查询侧增广的多样性来源），**不是** R2 配对正例；
  * 不同 `source_asset_id` → 跨退化等级的匹配才是难负例：同一实例在 L0 与 L4 仍须排在它们之上；
  * 明确禁止：把同源不同档当成 mate 任务的 R1/R0 负例（那是同一实例，会把标签噪声注进负例池）。

### 9.7 仍缺口（实测，未改 NA）

* **G05 三档不可达**：本谱系观测网格（1880 面）上，预算 0.01/0.025/0.05 mm 的 QEM 抽面
  `OPERATOR_NOT_REALIZED`（最后实测 Hausdorff 0.0709 mm、ROI 保留 0.995），只有 0.1 mm 档成功
  （1645 面、Hausdorff 0.0759 mm、ROI 保留 0.339）。三档**留在分母**（`levels_failed=3`），没有改成 NA。
* **I03 档位在 8 位交付上不可分**（§9.5）：σ 0.00555–0.00557；需要线性/高位深交付或更大的
  gain 跨度才能把四档分开。
* **G08 L4 非单调**：planned 2.2 mm 的实测最大位移 1.005666 mm < L3 的 1.200755 mm，
  `n_added_faces=0`（凸起靠顶点位移实现），声明高度与实测位移在 L3/L4 已脱钩。
* **一条谱系**：本次只跑了 1 条（第二条在宿主杀进程时中断，见下）；`rotate` 选择的多谱系覆盖
  尚未在真实批量上验证。
* **宿主杀进程（实测 3 次）**：`run_generation` 在收尾/第二条谱系时被宿主以 `exit=-1` 杀掉
  （无 traceback）；已用「每档写盘 + 每母体刷 ledger + 重试」规避，但**批量生成仍需按谱系断点续跑**。
* **并发编辑风险（实测）**：`synlab/pipeline.py` 在本次工作期间被另一名队友同时修改，先后出现
  `SCHEMA_LABELS`、`SCHEMA_PROVENANCE` 未导入导致的 `NameError`；本次只在 pipeline 里补了
  `SCHEMA_LABELS` 的 1 行导入（其余用 scratch runner 注入 roles 常量绕过），**未改任何队友的语义**。
* **probe 渲染的上游拒绝**：`observe.routes.resolve_target` 新增
  `OBS_TARGET_PROVENANCE_MISSING` 拒绝无面级 provenance 的渲染目标；`observe_probe` 的探针盒
  因此被拒（连带 40+ 个算子测试）。已在 `synlab/degrade/api.py` 让探针盒声明
  `origin_kind=0/interface_id=-1`（`ORIGIN_TO_TAG[0]==0`，渲染结果与原行为数值一致，
  只是把「没有断裂面」变成测量而不是缺通道）。
