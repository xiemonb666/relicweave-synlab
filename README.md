# relicweave-synlab — A12 可控合成碎片实验室

按 `A12_Codex_Execution_Plan_V1.2.md`（V1.2，2026-10-01）实现的**独立**工程：参数化母体 →
程序纹样 → 共享断裂 → 分层真值 → 物理损伤 → 观测/重建 → 特征与标签 → 不可变发布 →
预训练与退化诊断，外加 31 轴退化算子、关系库、主动观察 episode 与 12 页操作界面。

> **集成状态：`MAIN_REPO_INTEGRATION_PENDING`。**
> 会话工作目录内不存在主仓库、`AGENTS.md`、现成 `ObsPack`/`FeaturePack` 或 A3/A4 schema，
> 因此本工程按计划 §0.1 第 4 条独立建立，并提供 `a12.obs.v1` 特征合同与待接入的适配器。
> 详见 `docs/a12/repo_inventory.md` 与 `docs/a12/contract_diff.json`。

## 快速开始

```powershell
$root = "C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab"
$py   = "$root\.venv\Scripts\python.exe"   # Python 3.12.14

& $py -m pytest tests -q                      # 全部测试
& $py -m synlab.cli doctor --json             # 能力核验 + env_report
& $py -m synlab.cli validate --config configs/a12/sandbox.yaml --json
& $py -m synlab.cli generate --config configs/a12/sandbox.yaml --json
& $py -m synlab.cli acceptance --profile SANDBOX_CORE --json
```

完整流程见 `docs/a12/runbook.md`。

## 文档

| 文件 | 内容 |
|---|---|
| `docs/a12/repo_inventory.md` | M00 仓库清单、设备与能力核验结果 |
| `docs/a12/contract_diff.json` | 外部合同缺失与 `a12.obs.v1` 独立入口 |
| `docs/a12/interfaces.md` | 模块间冻结接口 |
| `docs/a12/architecture.md` | 架构与模块职责 |
| `docs/a12/data_contract.md` | 六种 Pack、坐标、白名单、随机性 |
| `docs/a12/reuse_manifest.json` | 开源复用矩阵、版本、PoC、CUSTOM_GAP 证据 |
| `docs/a12/backend_capabilities.json` | 外部后端实测能力（含缺失项） |
| `docs/a12/env_report.json` | `synlab doctor` 实测报告 |
| `docs/a12/runbook.md` | 运行手册与已知阻塞 |
| `docs/a12/acceptance_report.md` | A01–A36 验收报告（由实跑生成） |
| `docs/a12/status_matrix.csv` | 模块 × 状态 × 证据 |
| `docs/a12/algorithm_registry.md` | 器型/材料/纹样/后端/轴注册表 |
| `docs/a12/experiment_protocols/` | E-SYN-01–08 预注册协议与确认注册表 |

## 诚实性约定

* 每个门面函数返回真实结果或 `SynLabError`；禁止随机曲线、假进度、空实现、固定图片。
* 零强度必须是真恒等（原字节/hash）。
* 缺失的外部能力（Blender、实拍数据、CUDA）在 `env_report` / `backend_capabilities` /
  验收报告中显式标 `MISSING`/`PENDING`，替代路线单独命名（例如 `SOFTWARE_RASTERIZER`）。
* 模块状态：`SPECIFIED / IMPLEMENTED / QA_PASSED / VALIDATED / RELEASED / PENDING / MISSING`；
  验收项：`PASS / FAIL / PENDING / NOT_RUN / NA`。

## 依赖

见 `requirements.lock.txt`（`pip freeze`）。本机实测：pandas 3.x、torch 2.14、open3d 0.20 的
编译扩展在本机会 `STATUS_DLL_INIT_FAILED`，因此固定为 pandas 2.2.3 / torch 2.5.1+cpu /
open3d 0.19.0；外部后端使用 gmsh 4.15.2、pycolmap 3.11.1、faiss-cpu 1.15.1。
Blender 无 Windows/CPython 3.12 wheel，渲染由其软件光栅渲染器承担并登记为 `CUSTOM_GAP`。

## 目录

```
synlab/          核心实现（schemas, storage, jobs, mothers, materials, patterns, fracture,
                 truth, physical, cameras, observe, degrade, relations, training,
                 diagnostics, episodes, qc, api, cli.py, pipeline.py, doctor.py, registry.py）
blender_scripts/ Blender 渲染 worker 适配器（当前环境缺失 Blender，保留为可插拔目标）
configs/a12/     生成/训练/诊断/池/相机/物理配方/QA 协议配置
frontend/        React + TypeScript + Vite 的 12 页界面
tests/a12/       契约、几何、纹样、真值、算子、池、训练、诊断、恢复、API、UI 测试
tools/           run_evidence.py（证据链）、gen_status_matrix.py（状态矩阵）
docs/a12/        上述文档
```
