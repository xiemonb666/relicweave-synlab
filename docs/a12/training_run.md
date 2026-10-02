# A12 训练链路：真实包冒烟、契约修复与可用性结论

本文件记录 `synlab/training/**` 的训练链路修复与**真实数据冒烟**。所有数字都来自本文件列出的
命令在本次运行中的实测输出；凡是没有真实数据支撑的部分一律标 **未实测**，不用曲线、精度或
吞吐量填补。

* 产物报告：`data/a12/reports/training_smoke.json`（schema `synlab.training.smoke.v1`）
* 真实 checkpoint：`data/a12/reports/real_package_smoke_step3.pt`（step 3）
* 数据来源：`data/a12_exports/closed_loop/training_package`（`release_id=rel_852ab2a1e4c3_1790905541`，
  `release_manifest_hash=sha256:c86c14af36e243fef2b2ba5e5a909d73555ddcfcb79aa9899cd3d2f9a3b01ddd`）
* 运行环境：CPU only（`cuda_available=false`）、fp32、`torch 2.5.1+cpu`、`device=cpu`

> **本文件已按"训练监督修复"重测。** §1–§5 的数字凡与修复前不同者，均已就地更新为
> 重测值，并在该处标注"修复后"；**逐任务监督的权威结论在 §8–§12**（含每个任务的
> `n_valid / n_allowed`、被哪个条件否掉、代码位置、仍未解锁项及其数据前提）。
> 修复前的对照报告留存为 `data/a12/reports/training_smoke_before.json`，
> 逐任务 before/after 汇总为 `data/a12/reports/training_supervision_after.json`。
> （§7 是**另一并行任务**在同一期间追加的"训练前质量闸门"一节，与本节的编号互不冲突。）

---

## 1. 命令与退出码（实测）

| 命令（工作目录 = 仓库根） | 实测结果 |
|---|---|
| `& .venv\Scripts\python.exe -m pytest tests/a12/training -q` | **exit 0**；**33 passed**（修复前 24 passed；新增 `test_supervision_contract.py` 12 例） |
| `& .venv\Scripts\python.exe -m pytest tests/a12/qc tests/a12/training -q` | **exit 0**；**84 passed**（`tests/a12/qc` 同期由另一任务扩展，故总数不等于"37"；两套件各自 exit 0） |
| `& .venv\Scripts\python.exe data\a12\reports\reexport_training_package.py --store data/a12_exports/closed_loop/store --release rel_852ab2a1e4c3_1790905541 --out data/a12_exports/closed_loop/training_package` | **exit 0**；2.14 s（55 文件、3,998,691 B） |
| `& .venv\Scripts\python.exe -c "from synlab.training.smoke import run_smoke; run_smoke(...)"` | **exit 0**；见 §2 与 §7；`status=PIPELINE_OK_DATA_INSUFFICIENT`、`ok=true` |
| `& .venv\Scripts\python.exe data\a12\reports\build_training_supervision_after.py --export-exit 0 --smoke-exit 0 --pytest-exit 0` | **exit 0**；`data/a12/reports/training_supervision_after.json` |
| `& .venv\Scripts\python.exe -m pytest tests/a12/relations -q` | **exit 0**；59 passed（该套件由另一任务维护） |
| `& .venv\Scripts\python.exe -m pytest "tests/a12/relations/test_sampler.py::test_rows_feed_training_batch" -q` | **exit 0**（本次修复前该用例为 exit 1 的原始缺陷） |
| `& .venv\Scripts\python.exe -m pytest tests/a12/integration -q` | **exit 1**；36 passed / 4 failed，4 例全在 `tests/a12/integration/test_l0_loop.py`，且全部由 `synlab/physical/api.py::close_numerical_pinholes` 的 `np.vstack` 形状不匹配（3 vs 4）引发——**并行任务在 `synlab/physical/**`+`synlab/fracture/**` 的在建改动，不在本任务写入范围**；`tests/a12/integration/test_closed_loop.py`（真正走导出包与分离扫描的那一套）全部通过 |

`tests/a12/training` 修复后的 33 个用例（`pytest --collect-only -q` 实测）：
`test_batch_lookup_contract.py`(5)、`test_model_contracts.py`(5)、`test_real_package_smoke.py`(7)、
`test_sampler_cfg_spec_views.py`(4)、`test_supervision_contract.py`(12，本次新增)。修复前为 24 例。

重跑冒烟的方式（约 4 s，CPU）：

```powershell
cd C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab
& .venv\Scripts\python.exe -c @"
from synlab.training.smoke import run_smoke
r = run_smoke('data/a12_exports/closed_loop/training_package', steps=3,
              out_dir='data/a12/reports', include_loader_probe=True)
print(r['status'], r['ok'], r['steps']['loss_sequence'])
"@
```

---

## 2. `training_smoke.json` 的真实内容

### 2.1 状态与自检

| 字段 | 真实值 | 含义 |
|---|---|---|
| `status` | `PIPELINE_OK_DATA_INSUFFICIENT` | 链路本身跑通，但真实数据不足以产生监督信号 |
| `ok` | `true` | `checks` 五项全真 |
| `checks` | `batch_built / losses_finite / optimizer_steps_taken / package_files_verified / checkpoint_consistent` 全 `true` | 见 §2.5 |
| `wall_seconds` | 3.835 s | 含包校验、loader probe、3 步训练、checkpoint 往返 |

`ok=true` **不代表训练有效**：它只表示"读包 → 建 batch → 前向 → 反向 → optimizer →
存 checkpoint → 重载 → 复现"这条链路在真实字节上被走通。`status` 里的
`DATA_INSUFFICIENT` 才是对数据量的判断。

### 2.2 真实 batch 组成

| 项 | 真实值 |
|---|---|
| `n_queries` / `n_candidates` | 3 / 1 |
| `positives` | **3**（每个 query 恰有 1 个 R2 正例） |
| `negatives` | **0**（真实值，不是占位） |
| `effective_queries` | **0** |
| `queries_with_positive` / `queries_with_legal_negative` | 3 / 0 |
| `fragments` | 6（3 个有观测 `-m`，3 个无观测 `-p`） |
| `tokens` / `points` | 576 / 6049 |
| `r2_edges_exposed` | 3 |
| `tier_histogram` | `{"Q0": 6}`（全部未标定档） |
| `exclusion_histogram` | `none=3`，其余 0（本批次 0 个被排除候选） |

三行真实内容（`batch.rows`）：

```
LIN0000_V01_M01_PAT01_E01-m  positives=[LIN0000_V01_M01_PAT01_E01-p]  negatives=[]  rel=[2]
LIN0001_V02_M01_PAT01_E01-m  positives=[LIN0001_V02_M01_PAT01_E01-p]  negatives=[]  rel=[2]
LIN0002_V13_M01_PAT01_E01-m  positives=[LIN0002_V13_M01_PAT01_E01-p]  negatives=[]  rel=[2]
```

即：每个 query 的正例是它的 R2 配对，而**那个配对的片段恰好是 `-p`（modelled-but-unobserved）**。
`trainer.compute_losses` 的 `allowed = z_valid[q_idx] & z_valid[c_idx] & pair_valid` 因此对 3 个
pair 全为 `False` → `encodable_pairs=0`、`unencodable_pairs=3`。这是 `negatives=0` 之外**第二个**
独立的数据缺口。

张量形状（真实）：

```
pair_index [3,1,2]   pair_valid [3,1]   pos_mask [3,1]   neg_mask [3,1]
labels_relation [3,1]  label_pair_valid [3,1]  contradiction [3,1]  contradiction_valid [3,1]
corr_weight [3,1,192]  corr_row_valid [3,1,192]  corr_col_valid [3,1,192]  corr_kind [6,192]
quality_target [6,1,1] quality_target_valid [6,1,1] quality_tier [6]  lineage_cluster [6]
sample_keys [3]
```

### 2.3 真实 loss 序列与耗时

| step | combined loss | grad_norm | lr_after_step | view loss | n_valid(view) | quality loss | n_valid(quality) | 秒 |
|---|---|---|---|---|---|---|---|---|
| 1 | 0.235010027885437 | 5.177638053894043 | 7.5e-05 | 2.350001096725464 | 12 | 0.00019826821517199278 | 3 | 0.1109 |
| 2 | 0.23460811376571655 | 5.487186431884766 | 2.5e-05 | 2.345982074737549 | 12 | 0.00019813650578726083 | 3 | 0.0876 |
| 3 | 0.23429083824157715 | 5.751092433929443 | 0.0 | 2.3428092002868652 | 12 | 0.00019803800387308002 | 3 | 0.0902 |

* `optimizer_steps_taken = 3`，`steps.wall_seconds = 0.2887`（3 步纯训练，CPU）。
* loss 单调下降 3 步，来自 **两个**任务：`combined = 0.1 × view_loss + 0.05 × quality_loss`
  （例 step 1：`0.1 × 2.350001096725464 + 0.05 × 0.00019826821517199278 = 0.2350100278854371…`）。
  `view` 是同一片段不同视角的对比目标（修复前唯一有真实监督的任务）；`quality` 是修复后
  新接通的 D 任务（**修复后**；监督来源与量级见 §7.3，3 行的量级不足以支撑任何结论）。
* 另外 3 个任务每一步都被如实跳过，原因由**实测计数**给出、非人工豁免（**修复后**的措辞）：

| 任务 | 权重 | 跳过原因（修复后） | 标签侧可用量 | 通过全部掩码的量 |
|---|---|---|---|---|
| `rank` | 1.0 | `no_legal_negative_in_exported_relations` | 正例 3、合法负例 **0** | 0 |
| `correspondence` | 0.1 | `correspondence_labels_never_reached_token_space` | 包内对应样本 **3,587** | 0 |
| `contradiction` | 0.1 | `no_encodable_contradiction_pair_candidate_side_unobserved` | `contradiction_valid` 3 | 0 |
| `quality` | 0.05 | ——（**已启动**） | 3 | **3** |

  修复前的旧措辞（`no_encodable_positive_pair` / `no_correspondence_label` /
  `no_contradiction_label` / `no_valid_quality_target`）只说明"没有可训的监督"，把
  "标签不存在"和"标签存在但被掩码挡掉"混为一谈；§7 逐个拆开。

`trainer_metrics` 里 `steps=0 / samples=0 / legal_negatives=0 / throughput_samples_per_s=null`：
这是 `Trainer.fit()` 的计数器，而 `fit()` 在真实包上**如实拒绝**（`trainer_fit_refusal`：
`SynLabError` / `SCHEMA_INVALID` / `no effective query in the whole accumulation window`，
在第 1 个 microbatch 处抛出）。冒烟用的 3 步走的是等价的单 microbatch 路径，不是 `fit()`
被放宽。

### 2.4 模型与真实参数量

```
total 72,710 = encoder 47,940 + pair_head 24,770
encoder 47,940 = backbone_group 45,828 + head_group 2,682
```

`temperature=0.1`、`quality_input_dim=2`、`quality_target_dim=1`、
`initial_param_digest=sha256:76985b47f98e27d95fef51b4e6b623d3d1f9fceea7b628419194cb657aa63a74`。

### 2.5 checkpoint 一致性的数值证据

`checks.checkpoint_consistent` 现在的定义包含 5 个独立事实（本任务把后两项补进 `checks`，
避免"检查项存在但没人读"）：

| 证据 | 真实值 |
|---|---|
| 文件 vs 保存时的模型逐参数比较 `file_matches_model_at_save` | `ok=true`，`parameters_checked=37`，`mismatches=0` |
| 重载后 vs 文件逐参数比较 `model_state_vs_checkpoint` | `ok=true`，`parameters_checked=37`，`mismatches=0` |
| 保存前 / 重载后参数摘要 | 均为 `sha256:cd165c2d4a79d687237d0439971e092749bebe5544890e8717d44563f025021d`（**修复后**；`load_is_bitwise_identical=true`） |
| 存盘后再逐步（live）与独立重载后逐步（resumed） | loss 均 `0.23418079316616058`（delta `0.0`）、grad_norm 均 `5.900482177734375`、参数摘要均 `sha256:cd165c2d…021d`（`extra_step_digest_equal=true`） |
| 换数据发布必须拒绝 | `resume(release_hash="sha256:not-the-same-release")` → `SynLabError` / `REPLAY_MISMATCH` |

`payload_hash = sha256:6bde5f4dc117d2a47c8f8ade5f073cc69011be36027aa721dfeaccd7f56380d6`（**修复后**；
checkpoint 537,658 B，因为 quality 任务现在也带梯度、optimizer 状态随权重变化）。
该哈希可用 `synlab.training.trainer._hashable_state` + `synlab.canonical.hash_json`
从文件独立重算并**逐位吻合**（本次已复算）。`reproducibility_level =
EXACT_SAMPLER_SEQUENCE_AND_STEP_CPU_FP32_SAME_PROCESS`；`sampler_cursor` 记录
`master_seed=11`、`epoch=0`、`acknowledged_draws=0`、`pool_id=exported`、
`lineage_order_hash=[11,"lineage_order",6]`。

**独立复核（另起进程、从盘上重载 `real_package_smoke_step3.pt`）**：

* 文件 537,658 B；37 个参数与文件逐位相等（`mismatches=0`）。
* 重新执行"再前进一步"：live 与**第二次独立重载**的 loss（`0.23418079316616058`）、
  grad_norm（`5.900482177734375`）、参数摘要（`sha256:cd165c2d…021d`）三者全等，
  且两次构造的 batch 张量逐位相同（以上为**修复后**实测值）。
* 一个诚实的边界：`torch.save` 的**字节**输出对同一组权重并非逐位可复现——`payload_hash`
  不覆盖 `optimizer` / `scheduler` / `torch_rng_state` / `rng_state` 这四块，而这些块在两次
  运行间不同，文件哈希因此会变（修复前实测：`7cc8cf2c…` vs `7b0a8f48…`，字节数恒为 523,070；
  修复后字节数恒为 537,658）。所以一致性结论建立在**权重与 payload_hash 上，不是文件 sha256 上**；
  `file_matches_model_at_save` 这一项就是为"报告所描述的文件就是盘上这个文件"提供证据而加的。

### 2.6 `honesty` 字段的含义

```json
{
  "synthesised_labels": 0,
  "synthesised_negatives": 0,
  "tasks_skipped": ["contradiction", "correspondence", "rank"],
  "skipped_task_reasons": {"contradiction": "no_encodable_contradiction_pair_candidate_side_unobserved",
                           "correspondence": "correspondence_labels_never_reached_token_space",
                           "rank": "no_legal_negative_in_exported_relations"},
  "tasks_with_real_supervision": ["quality", "view"],
  "tasks_blocked_with_labels_present": ["contradiction", "correspondence", "rank"],
  "claim": "the pipeline (read -> batch -> forward -> backward -> optimizer -> checkpoint ->
            resume) is exercised on real bytes; no generalisation claim is made from this package"
}
```

`honesty` 是这份报告的**反向声明**：`synthesised_labels=0` / `synthesised_negatives=0` 表示
没有任何一个标签或负例是被造出来凑数的；`tasks_skipped` 逐个点名哪 3 个任务没有可用的监督；
`tasks_with_real_supervision` 点名真正启动了 loss 的两个任务；`tasks_blocked_with_labels_present`
把"有标签但被掩码挡掉"与"根本没有标签"分开（**修复后**新增的两个字段）；`claim` 明确声明本包
**只能**证明链路可跑，**不能**据此声称任何泛化能力、精度或曲线。
换句话说，读这份报告时应当把 `ok=true` 读成"管道健康"，把 `status` 与 `honesty` 读成
"模型几乎没学到东西，而且报告不假装学到了"。

---

## 3. `neighbours_lookup` 契约判定与修法

### 3.1 缺陷

`_build_lookup` 返回邻接 `dict`，而 `build_training_batch` / `_sample_rows` 把它当函数调用
（`neighbours_lookup(qid)`），于是任何非空 rows 都会在 `_sample_rows` 里
`TypeError: 'dict' object is not callable`。集成测试
`tests/a12/relations/test_sampler.py::test_rows_feed_training_batch` 用本地 wrapper 把它包成
函数才能跑通——该用例在修复前 exit 1。

### 3.2 哪一侧是契约：**callable 是契约，dict 是实现漂移**

四条独立证据同向：

1. **同一函数的 docstring**（`build_training_batch`，`batch.py:274`）写明接受
   "a callable/object with `relation(a, b) -> str` plus `neighbours(fid)`"——**函数**。
2. **`_build_lookup` 自己的 docstring**（`batch.py:514`）写明返回
   `(relation(q,c)->name, neighbours(q)->set, confirmed(q,c)->bool)`——三者都是 callable；
   另两个返回值 `relation_of` / `confirmed_of` 在修复前后都一直是函数。
3. **本仓库通行的 pool 协议**处处是 callable：`relations.gallery.RelationPool.neighbours(fid)`、
   `training.sampler.PoolIndex.neighbours(fid)`、`qc.loader_probe.ExportedRelationPool.neighbours(fid)`、
   `training.api` 的 `pool.neighbours(qid)`。
4. **冻结的消费方用法**：`tests/a12/relations/test_sampler.py:243` 的 wrapper 明确交出一个
   *函数*（`lambda fid: set(neighbours.get(fid, set()))`），而
   `docs/a12/relations_diagnostics_episodes.md` §5 **G1** 把该缺陷写成
   "`_build_lookup` 返回的是邻接 dict，而 `build_training_batch` … 把它当函数调用"，
   并给出修复方向"**需训练模块改一行**"。

即：**训练模块的调用方式是对的，返回 dict 是实现偏离了它自己的文档**。G1 里"调用方错"的措辞
在这一点上不准确，应以 docstring 与仓库协议为准。

### 3.3 修法（已落地）

`_build_lookup` 改为返回 callable 的 `_NeighboursIndex`（`dict` 子类）：

```python
class _NeighboursIndex(dict):
    def __call__(self, fragment_id: str) -> set[str]:
        return set(self.get(str(fragment_id), set()))
```

* 满足契约：`neighbours(q) -> set` 可调用，且返回的是**副本**（调用方无法通过返回值污染索引）。
* 保留映射读取：`tests/a12/relations/test_sampler.py` 的 wrapper 里有
  `neighbours.get(fid, set())`，该文件**不在本任务写入范围**，因此保留 `.get` 作为
  **兼容垫片，而不是契约**。它的 docstring 已写明这一点，并由
  `tests/a12/training/test_batch_lookup_contract.py` 双向钉住：既断言"消费者真的在调用"
  （给一个**没有** `.get` 的纯函数也能跑通），也断言"映射访问解析出同一份邻接"。
* 阈值/语义未变：历史 R2 仍不得充当普通负例（`assert_legal_negative` + 批次末尾的
  `negative_audit` 双重把关，`negative_is_r2_history` 必须全 False）。

同批修复的另外两个同一族接口漂移（都在允许范围内）：

* `_SamplerCfg.from_spec`：原用 `mix.get(...)` 读取 `negative_mix`，遇到 `api.resume` 重建出的
  属性视图 `_SpecView` 会得到 `None` 并 `TypeError: 'NoneType' object is not callable`——
  即**每次 `api.resume()` 都会在建第一个 batch 时崩**。现同时接受 mapping 与属性视图，
  且显式 `0.0` 不被误判为"缺省"。
* `FragmentEncoder.named_parameters` / `PairRefineHead.named_parameters`：传入已带尾点前缀时
  PyTorch 会再补一个点，产出 `global_branch..0.weight` 这类**与 `state_dict()` 键不匹配**的名字，
  任何逐参数比较/加载都会静默失配（旧报告里 `parameters_checked=1`、36 条
  "absent from checkpoint" 就是它）。现归一化掉尾点，使 `named_parameters` 的键与
  `state_dict()` 完全一致。

### 3.4 本次收尾额外修的两个真实缺陷

冒烟产物是旧的、且与 HEAD 不一致，重跑后暴露两个**与 lookup 无关**的真实失败，均已按最小改法修复：

1. **`synlab/training/adapter.py`（未观测片段的 token 配额广播越界）**
   `_prepare_tokens` 中当片段所有有效性掩码为 False（真实包里的 `-p` 就是这种"有几何、无观测"
   片段）时，`select_token_quota` 返回**空** `keep`，而 `dropped` 是全部 n 个 token，
   于是 `retrieval[:24] = upstream` 报
   `ValueError: could not broadcast input array from shape (24,) into shape (0,)`。
   修法：赋值长度对 `retrieval.size` 取 `min` 并右值同步切片——不改变任何正常路径的语义。
   失败用例 `test_model_contracts.py::test_encoder_forward_runs_and_masks_unobserved_fragments`。
2. **`synlab/training/smoke.py`（checkpoint 比较时机）**
   `_compare_checkpoint(resumed_trainer.model, payload)` 在**"再走一步"之后**才比较，
   而那一步是真实的 `optimizer.step()`（实测参数摘要由 `…dfaa91` 变为
   `sha256:5d43431b…` 之外的中间值、8 个 `global_branch` 参数确实变了），
   于是必然报 8 条 `value mismatch`。修法：把比较移到**刚 resume 完、尚未再走步**处
   （实测同一比较立刻由 8 条不匹配变为 `mismatches=0, parameters_checked=37`），
   并新增 `file_matches_model_at_save`，同时把这两项纳入 `checks.checkpoint_consistent`。

---

## 4. 可用性结论：当前数据能否支撑训练

**结论：当前数据不能支撑训练；它只能证明链路可跑。**

判断依据（全部为真实计数）：

| 维度 | 真实值（修复后） | 训练是否可用 |
|---|---|---|
| 包完整性 | 55/55 文件校验通过，3,998,691 B | 可用（读得进） |
| queries | 6 行（3 条真实关系行） | 严重不足 |
| positives（R2 边） | 3 | 存在，但**0 个可编码** |
| negatives（合法 R1/R0） | **0** | 完全缺失 |
| 可编码正例对 | **0**（`encodable_pairs=0`） | rank loss（权重 1.0）无法启动 |
| quality 目标 | `quality_target_valid.sum()=3`（标签侧可观测率） | **已启动**（权重 0.05，loss ≈ 1.98e-4） |
| correspondence 标签 | 包内已有 3,587 条真实对应样本；token 空间 0 条 | 标签已进包、被掩码挡掉（§7.4） |
| contradiction 标签 | 3 个有效，但 `& allowed` 后 0 | 无法启动（标签还全为同一类） |
| view 监督 | `n_valid=12`（3 观测片段 × 4 视角） | 可用（权重 0.1） |

两个互相独立的缺口同时存在，缺一不可：

1. **没有负例**：导出的 `relations.parquet` 只有 3 行且全是 `R2`
   （`relation_kind_histogram={"R2":3}`，`superseded_relations=18`），既没有确认的 R1，
   也没有可用的 R0 —— `rank` 任务的正/负对凑不出来。另一名队友正在补负例，**本包内仍为 0**。
2. **正例的对端不可编码**：6 个片段里 3 个有观测（`-m`）、3 个无观测（`-p`），而 3 条 R2
   恰好都把有观测的 `-m` 连到无观测的 `-p`。`allowed` 要求**两端都 `z_valid`**，
   于是正例虽然存在却编码不出向量。

只有 `view`（12 行）与 `quality`（3 行，**修复后**接通）有真实监督，因此上表的 loss 下降
主要来自 view 对比目标，**不能**读作"模型在学关系判别"；quality 那 3 行只能证明 D 任务的
监督通路是通的，不足以支撑任何精度结论。`honesty` 与 `status` 对此的表述是一致的，
逐任务的掩码拆解见 §7。

### 4.1 最小可行数据需求

以"能真正跑起来一个有监督的 rank 步"为单位（`effective_query = 1` 需要同一 query 同时具备
**≥1 个可编码正例**与**≥1 个合法负例**）：

| 规模 | 需求 | 说明 |
|---|---|---|
| **绝对最小（链路级）** | **1 个 query + 1 个 R2 正例 + 1 个合法负例**，三者**都必须有观测**（`token_valid` 非空且 `global_valid` 至少 1 个视角） | 1 个 lineage 就够；只求 `effective_queries ≥ 1`，不要统计意义 |
| **最小可训练（单步有意义）** | ≥ 2 个 lineage（每个 ≥1 query），每 query ≥1 可编码 R2 + ≥2 个合法负例（R1 优先，R1 不足时 R0 且**必须记 `r1_fallback_used`**） | `negative_mix` 默认 (R1,R0)=(0.5,0.5)，`legal_negative_limit` 默认 8 |
| **最小可评测** | 同 lineage 的 query **必须跨 lineage 划分**，否则 rank 学的只是同族记忆；≥3 lineage 才能做"留一族"对照 | `lineage_cluster` 已在批次里，可直接做分组切分 |
| **质量/对应/矛盾任务** | 分别需要：`quality_target_valid > 0` 的真实质量目标（**已具备，3 行**）；可落到 token 空间的对应边（当前 0）；`contradiction` 标签的**对端也必须可编码** | 第三项受同一 `allowed` 约束；对应边还缺一层投影（§7.4、§10） |

按维度汇总的**最小批产目标**（供数据批产参考，均为"下限"而非"够用"）：

| 维度 | 当前 | 最小下限 | 建议首批目标 |
|---|---|---|---|
| queries | 3（可编码 0） | 1 | ≥ 64，跨 ≥ 8 lineage |
| 可编码 positives | 0（名义 3） | 1 | ≥ 64（每 query ≥1） |
| 合法 negatives | **0** | 1 | ≥ 128（每 query ≥2，R1 优先） |
| 可编码片段比例 | 3/6 = 50% | 100% | ≥ 95%（`-p` 侧也要落地观测） |
| lineage（母体） | 3 | 1（链路）/ 3（评测） | ≥ 8，且按 lineage 分组划分 |
| quality 目标 | 0 | —（可后置） | ≥ 64 |
| correspondence 边 | 0 | —（可后置） | ≥ 64 对 |
| contradiction 标签 | 3（有效但被 `allowed` 挡掉） | 1（对端可编码） | ≥ 64 |

**关键点**：把 `-p` 侧补上观测，比单纯增加 query 行数更紧迫——当前正例是"有边但两端不全可编码"，
再多 query 也只会重复这个缺口。

---

## 5. 仍未解决项（诚实清单）

1. **数据缺口本身未解决**：`negatives=0`、`encodable_pairs=0`，本任务只做如实报告，
   没有、也不会用合成负例或标签去凑（`honesty.synthesised_negatives=0`、
   `synthesised_labels=0` 即是承诺）。
2. **`tests/a12/relations/test_multi_event_negatives.py` 的 2 例失败（已由该模块负责人修复）**：
   本次收尾期间 `tests/a12/relations` 一度 exit 1，失败在**另一并行任务（负例批产）**的在建模块，
   本任务未修改 `synlab/relations/**`。当时失败明细为：
   * `test_planning_gives_every_event_its_own_id_and_seed`：断言 `plan.events_total == 4`，
     实测 `7`（`"L1 also carries one unresolved-source event"`）；
   * `test_discrimination_reports_a_real_auc_and_a_clustered_interval`：断言
     `report["clusters"] == 2`，实测 `3`。

   两者都是**期望值与规划器/聚类实现不符**，与训练链路无关。收尾结束时该模块已被修改
   （`synlab/relations/multi_event.py`、`synlab/relations/negatives.py`、
   `tests/a12/relations/test_multi_event_negatives.py` 在本任务运行期间落地），
   复测 `tests/a12/relations` 为 **exit 0 / 59 passed**。
3. **`docs/a12/relations_diagnostics_episodes.md` §5 G1 的措辞与 §4.1 的阻塞标记仍是修复前的
   状态**（"需训练模块改一行"、"该文件不在本任务写入范围"）。该文件不在本任务写入范围，
   故未改动；**以本文件 §3 为准**：修复已落地，callable 是契约。
4. **`test_rows_feed_training_batch` 的本地 wrapper 仍在**（`tests/a12/relations/test_sampler.py:241-249`）。
   G1 说"修复后应删除该 wrapper"，但该文件不在本任务写入范围，故保留；它现在是冗余的
   （`_NeighboursIndex` 已可调用），删除与否由该文件负责人决定。
5. **批次列宽语义**：`excluded` 候选只在"存在更宽的行"时才拿到列
   （`build_training_batch` 里 `if slot >= c: continue`）。本包 3 行等宽（各 1 个正例），
   因此 `excluded_candidates=0` 是**列宽限制**而非"真的没有候选被排除"。已由
   `tests/a12/training/test_batch_lookup_contract.py::test_excluded_historical_neighbour_is_reported_as_known_r2`
   用"一宽一窄"两行钉住该语义。
6. **checkpoint 字节级不可复现**（§2.5）：`payload_hash` 不覆盖 optimizer / RNG 四块，
   两次保存同权重的文件 sha256 不同。当前的一致性证据因此建立在权重与 `payload_hash` 上。
   若要"文件 sha256 可复现"，需让 `payload_hash` 覆盖全部字段或对 payload 做规范化序列化——
   **未实施**（会改变 checkpoint 格式与既有哈希，超出本任务范围）。
7. **未实测项**：无 GPU（`cuda_available=false`），故所有结论仅对 CPU/fp32/same-process 成立；
   `throughput_samples_per_s=null`（`fit()` 被拒绝，没有可测吞吐）；未做任何精度/泛化评测，
   也没有 data loader 并行度、混精（`precision_downgrade_reason=null` 表示未降级）的实测。
8. **`_run_step` 的 accumulate 语义**：单 microbatch 路径用 `accumulate=1.0` 并在 docstring
   里写明理由（无 effective query，`fit()` 的有效 query 加权均值没有分母可除）。
   当数据补齐、`effective_queries > 0` 之后，这条路径应当切换到 `fit()` 的加权语义并重跑——
   **未实施**（当前无数据可验证）。

---

## 6. 复现命令（含退出码）

```powershell
cd C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab

# 1) 目标套件（必须 exit 0）
& .venv\Scripts\python.exe -m pytest tests/a12/qc tests/a12/training -q      # exit 0, 37 passed
& .venv\Scripts\python.exe -m pytest "tests/a12/relations/test_sampler.py::test_rows_feed_training_batch" -q   # exit 0

# 2) 真实包冒烟（重建 training_smoke.json 与 real_package_smoke_step3.pt）
& .venv\Scripts\python.exe -m synlab.training.smoke --help   # 见 synlab/training/smoke.py::main

# 3) relations 套件（当前 exit 0；收尾期间一度 exit 1，见 §5 第 2 条）
& .venv\Scripts\python.exe -m pytest tests/a12/relations -q                   # exit 0, 59 passed
```

证据文件（均在 `data/a12/reports/`）：`training_smoke.json`、
`real_package_smoke_step3.pt`、`pytest_qc_training_final.txt`、
`pytest_relations_after_fix.txt`、`pytest_relations_target_test.txt`。

---

## 7. 训练前先跑质量闸门（本次新增）

**拿任何 store / 导出包训练之前，先跑闸门判定它是否可训练**，不要靠人记住哪一批是修复前产出的
（掩码单位 / A09 损伤合法性 / 母体几何 / `-p` 侧观测四处语义变更留下的跨代数据）：

```powershell
& .venv\Scripts\python.exe tools\check_data_quality.py --store <store 根>       # exit 0=可训练 / 3=不可训练
& .venv\Scripts\python.exe tools\check_data_quality.py --package <导出包目录>    # 同上
```

退出码 `0` = 可训练，`3` = 不可训练（stdout 打印**首因**与逐项明细，每项都带真实分母与命中），
`2` = 目标既不是 store 也不是包。判定结果落 `data/a12/reports/data_quality_<store>.json`。
闸门**只读**、不修资产；检查项、阈值与阈值来源见 `synlab/qc/data_quality.py` 的模块 docstring 与
`docs/a12/dataset_registry.md` §1；逐 store / 逐包的实跑判定（本次扫描 21 个目标，
**全部为不可训练**，以及每个"缺什么才能变可训练"）见同文件 §2–§4。

> 本节追加时的实测计数（供 §6 第 1 条对照）：`pytest tests/a12/qc -q` → **exit 0, 51 passed**
> （原有 16 + 本次新增 35）；`pytest tests/a12/qc tests/a12/training -q` → **exit 0, 84 passed**
> （§6 记的 37 passed 是本次追加之前的基线；差额中 35 条来自 `tests/a12/qc/test_data_quality.py`，
> 其余来自并行任务在同一期间新增的 training 用例）。

---

## 8. 逐任务监督：诊断、掩码拆解与修法（**本节为权威**）

问题陈述：修复前 `combined = 0.1 × view_loss`，五个任务里只有一个真的在训。本节逐个回答
"每个任务有多少标签、多少能过掩码、被哪个条件否掉（含代码位置与实测计数）"。

### 8.0 掩码的真实结构（修复前后都没改）

`synlab/training/trainer.py::Trainer.compute_losses`：

```python
allowed = z_valid[q_idx] & z_valid[c_idx] & pair_valid     # trainer.py:359（修复前行号）
```

`allowed` 是**三个条件的合取**，所以一个"0"至少有两种含义。实测拆解
（`report["supervision"]["pair_mask"]`，见 `data/a12/reports/training_supervision_after.json`）：

| 合取项 | 实测计数 | 说明 |
|---|---|---|
| `pair_valid` | 3 | 3 条 R2 行都是已确认的正例 |
| `z_valid[query]` | 3 | 三个 `-m` 都有观测（4 视角 / 192 token / 1306·585·4158 点） |
| `z_valid[candidate]` | **0** | 三个 `-p` 全部"有建模、无观测"（`token_valid=0`、`global_valid=0`、`point_valid=0`） |
| `allowed` | **0** | 3 条 pair 全部被 `z_valid[candidate]==False` 否掉 |

即 `rejected_by = {"pair_valid==False": 0, "z_valid[query]==False": 0, "z_valid[candidate]==False": 3}`。
`allowed` 的语义本身是对的（一侧没有证据就不许打分，否则等于把零向量当测量值），**没有放宽它**。

### 8.1 逐任务诊断表（修复前，真实计数）

| 任务 | 修复前标签侧 `n_valid` | 修复前 `n_allowed` | 被哪个条件否掉（代码位置） |
|---|---|---|---|
| `view` | **12** | **12** | ——（`trainer.py:377` `view_infonce(view_valid=features.global_valid)`，不经过 `allowed`） |
| `rank` | 3（正例 3、合法负例 **0**） | 0 | 两道各自独立的门：① 导出的 `research/relations.parquet` 只有 3 行、全是 R2（`superseded_relations=18`），没有任何 `valid=true & loss_mask=true` 的 R1/R0；② `allowed`（`z_valid[candidate]==False`，`trainer.py:359`） |
| `correspondence` | **0**（包内） | 0 | ① 导出层没把 `corr_*` 写进包，且 `Trainer.build_batch`（`trainer.py:334`）调 `build_training_batch(...)` 时**没传 `correspondence=`**，于是 `batch.corr_weight` 全零；② 即使传了，`compute_losses`（`trainer.py:403-404`）还会用 `row_valid & tok_valid[q_idx] & allowed` 再挡一次，而候选侧 `tok_valid` 全 False |
| `quality` | **0** | 0 | 载荷侧 `quality`/`quality_valid` 是 `np.zeros((1,1))`（`synlab/qc/loader_probe.py::_observed_payload` 写死），包内也**没有**标签侧质量目标；`trainer.py:414` `if int(q_valid.sum()) == 0 -> skipped` |
| `contradiction` | **3**（`contradiction_valid` 3，全为类 1 "compatible"） | 0 | `trainer.py:434` `cont_valid = contradiction_valid & allowed`，被同一 `z_valid[candidate]==False` 挡掉；且 3 个标签同属一类（`label_histogram={"1":3}`、`classes_present=1`） |

### 8.2 修法（只改训练层与导出层，不改别的模块语义）

| # | 位置 | 改了什么 | 为什么这不是"造标签" |
|---|---|---|---|
| 1 | `synlab/storage/export.py`（新增 `_quality_rows` / `_correspondence_rows` / `SUPERVISION_LABEL_LAYERS`） | 研究视图新增两层标签：`research/labels/quality.parquet`（12 行 = 3 片段 × 4 视角）与 `research/labels/correspondence.parquet`（3,587 行） | 两个表都由 release 自己已存的资产算出：quality 行 = visible/truth 层 `per_view` 的真实计数与其比值（`target_value = visible / samples`）；correspondence 行 = clean/physical truth 的 `corr_*` 数组（`index_a/index_b/weight/valid/ambiguous/association_code/residual_mm`）。**只导出、不生成**；连"同一测量有多次提交时用了哪一次"都记进 manifest 的 `supervision_labels.quality.candidates` |
| 2 | `synlab/training/labels.py`（新文件） | `PackageLabelSource`：读上面两层标签，产出 `quality_target/valid` 与 correspondence 报告 | 缺失即 `valid=False`、`target=None`（§30.12：缺标签不是 0 值标签）；不插值、不回填 |
| 3 | `synlab/training/trainer.py::build_batch` | 把 `quality_target/quality_target_valid`（以及**只有**拿到真实 token 映射时才给的 `correspondence=`）真正传进 `build_training_batch` | 修复前最实的一条 bug：`build_training_batch` 早就支持这些参数，`build_batch` 一个都没传，所以包里有标签也永远进不了 batch |
| 4 | `synlab/training/trainer.py::compute_losses` | 跳过原因改为按实测计数生成（`_rank_skip_reason` / `_contradiction_skip_reason`），并把 correspondence 的原因区分为"包里没有标签"与"标签没进 token 空间" | 原因字符串来自刚测出的计数，不是常量 |
| 5 | `synlab/training/supervision.py`（新文件） | 逐任务 `n_valid / n_allowed / blocked_by / structural / unlock_condition`，外加 `plan_30_12` 不变量复核 | 度量的是 loss 真正用的那套掩码，**不修改**任何掩码 |
| 6 | `synlab/training/smoke.py` | 接上标签源、报告 `report["supervision"]` 与每任务的 `n_valid_labels`；`honesty` 增加 `tasks_with_real_supervision` / `tasks_blocked_with_labels_present` | 报告只输出实测值 |
| 7 | `synlab/training/losses.py::MultiTaskLoss.combine` | 每个任务同时报 `n_valid`（loss 真正消费的行数）、`n_allowed`、`n_valid_labels`（掩码前存在的标签行），跳过时也带 `diagnostics` | 让"被挡住"与"没标签"在报告里可区分 |

### 8.3 `view` 与 `quality`：修复后真的在训（真实数值）

| 任务 | 权重 | `n_valid` | `n_allowed` | step 1 loss | 监督来源 |
|---|---|---|---|---|---|
| `view` | 0.1 | 12 | 12 | 2.350001096725464 | 同片段跨视角正对（3 观测片段 × 4 视角） |
| `quality` | 0.05 | 3 | 3 | 0.00019826821517199278 | 标签侧可观测率 `observability_visible_rate`（GT_ORACLE，来自 visible/truth 层） |

`combined = 0.1×2.350001096725464 + 0.05×0.00019826821517199278 = 0.2350100278854371…`，
与 `steps.loss_sequence[0] = 0.235010027885437` 一致。

**quality 的诚实边界（必须一起读）**：3 个目标的真实值是
`LIN0000…-m = 0.034053`、`LIN0001…-m = 0.0`、`LIN0002…-m = 0.005480`
（`visible / samples` 的按视角均值，计数分别为 202/5932、0/6332、29/5292）。
3 行、其中两个接近 0，**不能**支撑任何精度或趋势结论；这一步只证明 D 任务的监督通路是通的。
另外当前观测侧输入本身是**全零**（loader 写死的 `quality = zeros((1,1))`，包内也没带 OBS_EST 通道），
所以这个 head 目前只能拟合一个常数——解锁条件见 §11。

### 8.4 `correspondence`：标签进包了，但落不到 token 空间

修复后：`n_valid_labels = 3,587`（真实对应样本，来自 3 条受监督 R2 对的 `corr_*` 数组；
`weight` 合计 7,893.206968、`valid` 3,586、`ambiguous` 1），`n_allowed = 0`。

跳过的原因由 `PackageLabelSource.correspondence_for` 实测给出（`blocked_by`）：

1. `one_side_of_every_labelled_pair_has_no_token_evidence` —— 3 条带标签的 pair 里，
   每一对都只有一侧有 token 证据（`pairs_with_both_sides_observable = 0`、
   `pairs_with_one_side_observable = 3`）；
2. `surface_sample_to_token_mapping_is_not_derivable_from_the_package` —— 对应样本是**表面点对**，
   而 loss 需要 `W[q,c,i,j]` 的 **token 下标**；把表面点投到 token 需要 `K/T_WC/id_map/depth_z`，
   这些通道按设计**不进部署视图**，包内也确实没有。因此没有构造 W，`corr_weight` 保持全零。

两条都不是"没有标签"：修复前的 `correspondence_labels_in_package = 0` 与
`no_correspondence_label` 是**导出层漏项**叠加**训练层漏传**造成的假象。

### 8.5 `rank` 与 `contradiction`：结构化不适用（有实测证据）

两个任务的标签都在、但都不能训，而且不是训练层能修的：

* `rank`：`n_valid_labels = 3`（正例 3 / 合法负例 0），`n_allowed = 0`；
  `structural.reason = no_legal_negative_in_exported_relation_table`，
  `evidence.positives_rejected_by = {"z_valid[candidate]==False": 3}`。
* `contradiction`：`n_valid_labels = 3`（全为类 1），`n_allowed = 0`；
  `reason = no_encodable_contradiction_pair_candidate_side_unobserved`
  （`diagnostics`：`n_labels_valid_before_encodability=3`、`n_labels_after_encodability=0`）。

**跨包的结构性证据**（`report["structural_evidence"]`，对全部真实导出包实测）：

| 包 | 关系行 | 两端都有观测的行 | 恰好一端有观测 | 受监督的 R1/R0 行 |
|---|---|---|---|---|
| `closed_loop/training_package`（rel_852ab2a1e4c3_1790905541） | 3（全 R2） | **0** | 3 | 0 |
| `next_experiment/training_package`（rel_nexp_1790913735） | 150（R2 33 + R1 117） | **0** | 58 | **0** |
| 合计 | **153** | **0** | 61 | 0 |

外加真实池 `data/a12/pools/sandbox_dev.json`：89 条边，`R1` 79 条**全部**
`valid=false, loss_mask=false`，`R2` 10 条才是有效对。也就是说：**在全部真实数据里，
没有任何一条关系行的两端都能编码**，也没有任何一条可用的 R1/R0 负例行。
所以 `rank` 与 `contradiction` 在当前计划的数据形态下**结构性不适用**，
不是"参数没调好"或"掩码太严"。

### 8.6 §30.12 语义的实测复核（全为 0 = 合规）

`report["supervision"]["plan_30_12"]`：

```json
{"unknown_rows_inside_supervision": 0, "unconfirmed_rows_inside_supervision": 0,
 "non_r2_relation_inside_pos_mask": 0, "r2_rows_inside_neg_mask": 0,
 "unknown_rows_with_a_contradiction_label": 0, "missing_contradiction_rows_marked_valid": 0,
 "invalid_quality_slots_with_a_nonzero_value": 0, "r1_fallback_rows": 0,
 "r1_code_present": false, "relation_codes_supervised": [2]}
```

`UNKNOWN` 恒不进监督（导出层 `loss_mask=false`、loader 用 `kind in NEGATIVE_KINDS and valid
and loss_mask` 过滤、批内 `assert_legal_negative` 再挡一次），缺标签恒为 `valid=false`
（`quality` 的缺失片段 `target=None`，不写 0 值监督）。

---

## 9. before / after 逐任务计数（真实数值）

来源：`data/a12/reports/training_smoke_before.json`（修复前）与
`data/a12/reports/training_smoke.json`（修复后），汇总为
`data/a12/reports/training_supervision_after.json`。

| 任务 | 权重 | before 标签侧 `n_valid` | before `n_allowed` | before loss | after `n_valid_labels` | after `n_allowed` | after loss | 结论 |
|---|---|---|---|---|---|---|---|---|
| `view` | 0.1 | 12 | 12 | 2.350001096725464 | 12 | 12 | 2.350001096725464 | 一直可用 |
| `quality` | 0.05 | **0** | 0 | `null` | **3** | **3** | **0.00019826821517199278** | **本次解锁** |
| `rank` | 1.0 | 3 | 0 | `null` | 3 | 0 | `null` | 结构化阻塞（缺合法负例 + 对端无观测） |
| `contradiction` | 0.1 | 3 | 0 | `null` | 3 | 0 | `null` | 结构化阻塞（对端无观测；标签还同类） |
| `correspondence` | 0.1 | **0** | 0 | `null` | **3587** | 0 | `null` | 标签已进包，仍被 token 映射挡住 |

`combined`：before `0.2350001186132431`（= 0.1×view）→ after
`[0.235010027885437, 0.23460811376571655, 0.23429083824157715]`
（= 0.1×view + 0.05×quality，三步单调下降）。`status` 仍为
`PIPELINE_OK_DATA_INSUFFICIENT`、`ok=true`（五项 checks 全真，含 checkpoint 往返一致性：
37 个参数逐位相等、live 与 resumed 的 loss 均为 `0.23418079316616058`）。

---

## 10. 命令与退出码（本节新增部分）

```powershell
cd C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab

# 1) 目标套件
& .venv\Scripts\python.exe -m pytest tests/a12/training -q                    # exit 0, 33 passed
& .venv\Scripts\python.exe -m pytest tests/a12/qc tests/a12/training -q       # exit 0, 84 passed

# 2) 真实包重导出（把 release 已有的监督写进包）+ 冒烟重跑
& .venv\Scripts\python.exe data\a12\reports\reexport_training_package.py `
    --store data/a12_exports/closed_loop/store --release rel_852ab2a1e4c3_1790905541 `
    --out data/a12_exports/closed_loop/training_package `
    --report data/a12/reports/reexport_summary.json                            # exit 0, 2.14 s

# 3) 逐任务监督报告（before/after + 解锁条件）
& .venv\Scripts\python.exe data\a12\reports\build_training_supervision_after.py `
    --export-exit 0 --export-seconds 2.1448 --smoke-exit 0 --smoke-seconds 2.334 `
    --pytest-exit 0                                                            # exit 0
```

冒烟本体（`training_smoke.json` 与 `real_package_smoke_step3.pt`）用 §6 第 2 条那条命令重跑，
实测 **exit 0**、`wall_seconds=2.334`、`steps.wall_seconds=0.2887`。

---

## 11. 修复后仍未解锁项及其数据前提

| 任务 | 现状（实测） | 解锁前提（按依赖顺序） |
|---|---|---|
| `rank` | `n_valid_labels=3`、`n_allowed=0` | ① **两个都观测的片段**：`-p` 侧补上观测（或导入每条谱系两侧都渲染的数据集），使正例对可编码；② **可用的负例行**：`valid=true & loss_mask=true` 的 R1/R0（当前 153 条关系行里 0 条，池里 79 条 R1 全 `valid=false`）；③ 满足①②后 `effective_queries ≥ 1`，`fit()` 才会接受该 accumulation window |
| `contradiction` | `n_valid_labels=3`（全类 1）、`n_allowed=0` | ① 同上的"两个都观测的片段"（矛盾标签监督在 pair logits 上，需要两端 embedding）；② 一个**真的"矛盾/不兼容"类**的标签来源——当前 3 个标签由关系类别导出（R1/R2 恒 compatible），`classes_present=1`，即便跑起来也只是单类 CE |
| `correspondence` | `n_valid_labels=3587`、`n_allowed=0` | ① 同上的"两个都观测的片段"；② 一份 **token 空间**的对应表：在 truth/observe 层用 `K/T_WC/id_map/depth_z` 把 `corr_*` 表面点投到交付视角的 token 上（这些通道属真值侧，不得进部署视图），导出成 `(q,c,i,j,weight)`；③ 满足①②后 `build_batch` 会自动把它传进 `build_training_batch(correspondence=...)`（通路已在 §8.2 第 3 条打通） |
| `quality`（已启动，但很弱） | 3 行、1 通道，目标值 0.034053 / 0.0 / 0.005480；输入侧全零 | ① **更多谱系**（每片段 1 行，3 行无法支撑结论）；② 观测侧输入要真：包内需带 obs 资产自己的 OBS_EST 11 通道，且 loader 把它读进 `a12.obs.v1` 载荷的 `quality`/`quality_valid`（`synlab/qc/loader_probe.py`，**本任务写入范围之外**）；③ 目标通道要随之变宽：`synlab.observe.quality.attach_oracle_comparison` 是计划里为此准备的 GT_ORACLE 通道，实测**全仓 0 个调用点**（所有 obs 资产都没有 `oracle_comparison` 块、`oracle_prefilled=false`），即"同通道 oracle 目标"当前确实不产生 |

**没有做的事（诚实清单）**：没有合成任何标签或负例（`synthesised_labels=0`、
`synthesised_negatives=0`）；没有放宽 `allowed`；没有把缺失标签写成 0 值监督；
没有为了"看起来启动"改动质量目标的量纲或数量。

---

## 12. 本节新增/改动的文件与测试

* 新增：`synlab/training/labels.py`、`synlab/training/supervision.py`、
  `data/a12/reports/reexport_training_package.py`、
  `data/a12/reports/build_training_supervision_after.py`、
  `tests/a12/training/test_supervision_contract.py`
* 改动：`synlab/storage/export.py`（两层监督标签 + manifest 的 `supervision_labels`）、
  `synlab/training/trainer.py`（标签源接线 + 实测跳过原因 + `supervision` 报告）、
  `synlab/training/smoke.py`（标签源、`report["supervision"]`、honesty 新字段）、
  `synlab/training/losses.py`（`n_allowed` / `n_valid_labels`）、
  `synlab/training/batch.py`（`meta=` 透传）、
  `tests/a12/training/test_real_package_smoke.py`（措辞断言随实测更新）
* 报告：`data/a12/reports/training_supervision_after.json`（本文件 §8–§11 的数字来源）、
  `data/a12/reports/reexport_summary.json`、`data/a12/reports/training_smoke_before.json`
