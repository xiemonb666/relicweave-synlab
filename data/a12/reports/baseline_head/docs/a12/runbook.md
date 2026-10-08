# docs/a12/runbook.md — 运行手册（从头复现）

本手册的命令均已在本机实际执行过（除明确标注 PENDING 的项）。所有命令使用项目 venv 的绝对路径。

## 0. 环境

```powershell
$root = "C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab"
$py   = "$root\.venv\Scripts\python.exe"
```

环境由 CPython 3.12.14 创建 venv 并锁定依赖：

```powershell
& $py -m pip install -r "$root\requirements.lock.txt"
& $py -m pip install -e $root
```

## 1. 能力核验（必做第一步）

```powershell
& $py -m synlab.cli doctor --json
```

产物：`docs/a12/env_report.json`、`docs/a12/backend_capabilities.json`。
本机实测：38 项 PASS，0 项 FAIL，**1 项 MISSING：`backend:blender_render`**（无 Blender binary，
`pip install bpy` 在 Windows/CPython 3.12 无可用 wheel）。渲染走项目软件光栅渲染器，
Blender adapter 保留为可插拔目标。

## 2. 配置编译

```powershell
& $py -m synlab.cli validate --config configs/a12/sandbox.yaml --json
& $py -m synlab.cli budget   --config configs/a12/sandbox.yaml --json
```

`validate` 拒绝未知字段、未注册 ID、非法阶段顺序、缺失的 reuse 证据；
`budget` 按所有并发预留之和准入，容量不足返回 `BUDGET_EXCEEDED`。

## 3. SANDBOX 闭环（L0）

```powershell
& $py -m synlab.cli generate --config configs/a12/sandbox.yaml --json
```

真实产物：母体/材料/纹样/刀具体/碎片/CleanTruth/PhysicalPack/ObsPack/特征/标签/溯源 asset，
以及 `data/a12/reports/coverage.parquet`、`generation_<run>.json`。

## 4. 审计与发布

```powershell
& $py -m synlab.cli audit --run <run_id> --json
& $py -m synlab.cli registry --out docs/a12/registry.json
& $py -m synlab.cli release freeze --run <run_id> --protocol configs/a12/qa_protocol_v1.json --json
```

发布门按 `synlab/qc/gates.py` 从**实际证据**判定；任何 REQUIRED 门非 PASS 一律拒绝冻结。

## 5. 池、训练与诊断

```powershell
& $py -m synlab.cli build-pool --release <release_id> --config configs/a12/pool_dev.yaml --json
& $py -m synlab.cli train      --config configs/a12/train_sandbox.yaml --json
& $py -m synlab.cli evaluate   --config configs/a12/diagnose_sandbox.yaml --json
& $py -m synlab.cli diagnose   --config configs/a12/diagnose_sandbox.yaml --json
```

训练在 CPU（torch 2.5.1+cpu）上运行；规模与 GPU 相关结论按实际记录，不折算成 GPU 小时。

## 6. 31 轴与纹样审计

```powershell
& $py -m synlab.cli operator-audit --json
& $py -m synlab.cli pattern-audit  --json
```

每轴 level0 必须真恒等；效果未实测计失败，不适用计 NA，分母保留。

## 7. 恢复演练与备份

```powershell
& $py -m synlab.cli resume --run <run_id> --json
& $py -c "from synlab.storage.store import AssetStore, health_check; s=AssetStore('data/a12'); print(s.backup('backup/metadata.sqlite')); print(health_check('data/a12'))"
```

SQLite 一致备份使用官方 backup API；恢复先回到新数据根并审计，不直接改 hash 掩盖损坏。

## 8. 验收

```powershell
& $py -m synlab.cli acceptance --profile SANDBOX_CORE --json
& $py -m pytest tests -q
```

产物：`docs/a12/acceptance_report.md`、`data/a12/reports/acceptance_summary.json`、
`docs/a12/status_matrix.csv`。

## 9. 前端

```powershell
cd $root\frontend
npm install
npm run build
```

构建产物为静态 SPA；数据全部来自真实 API（`synlab api` 启动的服务），
后端能力缺失时页面显示具体阻塞原因而不是假数据。

## 10. 服务启动

```powershell
& $py -m uvicorn synlab.api.app:create_app --factory --port 8077
```

本机开发模式默认 `role=researcher`；部署包不挂载 research/truth 路由。

## 11. 已知阻塞（照实列出）

| 项 | 状态 | 说明 |
|---|---|---|
| Blender 渲染 | MISSING | 无 binary、无 bpy wheel；替代路线为软件光栅渲染器（CUSTOM_GAP 已登记） |
| 实拍数据 / PHONE_RGB 校准 | PENDING | 本机无真实照片数据，扫描声明限定为代理压力测试 |
| CUDA 训练 | MISSING | 仅 torch 2.5.1+cpu；GPU 规模与 GPU 小时不报告 |
| L2/L3 规模（480 母体 / 1e5 片） | PENDING | 运行产物，取决于实际机时；状态由 `scale_report` 决定 |
| 主仓集成 | PENDING | 无主仓与 A3/A4 schema，见 `contract_diff.json` |
