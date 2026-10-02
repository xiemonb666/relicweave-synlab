# docs/a12/repo_inventory.md — M00 仓库清单与能力核验

**生成时间**：2026-10-01（会话内实测）
**状态**：`MAIN_REPO_INTEGRATION_PENDING`

## 1. 当前工作目录与 Git 状态

| 项 | 实测值 |
|---|---|
| 会话工作目录 | `C:\Users\xiemo\Desktop\ShardForge` |
| 该目录内容（核验时） | `A12_Codex_Execution_Plan_V1.2.md`（212,666 B）、`RelicWeave_V1.44_Optimized_Complete_Plan.docx`（546,163 B） |
| 是否存在主仓库 | **否**。目录内没有 `.git`、没有 `AGENTS.md`、没有 README、没有依赖清单、没有现有测试、没有 `ObsPack`/`FeaturePack`/编码器/检索/FastAPI 前端代码 |
| 处理依据 | 计划 §0.1 第 4 条：仓库不存在 → 建立独立 `relicweave-synlab` 工程，完成核心模块，提供 `ObsPackAdapter` 与独立浅基线，并标记 `MAIN_REPO_INTEGRATION_PENDING`，不得假装已接入主项目 |

核验命令与结果：

```text
> Get-ChildItem C:\Users\xiemo\Desktop\ShardForge
A12_Codex_Execution_Plan_V1.2.md     212666
RelicWeave_V1.44_Optimized_Complete_Plan.docx  546163
```

## 2. 实际使用的解释器与设备（实测）

| 项 | 实测值 | 备注 |
|---|---|---|
| 项目解释器 | `relicweave-synlab\.venv\Scripts\python.exe` → **Python 3.12.14** | 由 DSH 运行时自带 CPython 3.12.14 创建 venv（计划要求 3.11/3.12，符合） |
| 宿主机 Python | 无 `python`/`py` 在 PATH；另有 anaconda base 3.13.9（未用于本项目） | 所有命令必须用 venv 绝对路径 |
| CPU / 内存 | 16 逻辑核 / 33.4 GB RAM | 计划目标机（Ryzen 9 9950X3D / 48 GB）未发现，按实机调整 |
| GPU | NVIDIA GeForce RTX 5060 Laptop **8151 MiB**，驱动 596.21 | 计划目标 RTX 5090 32 GB 未发现 |
| 磁盘 | C: 已用 527 GB / 可用 398 GB | |
| Node / 包管理器 | Node v24.14.1；pnpm 3（DSH 内置路径） | 前端用 Vite |

## 3. 能力核验结论（M00 / §30.1）

实测见 `docs/a12/env_report.json` 与 `docs/a12/backend_capabilities.json`（由 `synlab doctor --json` 生成）。
关键结论：

| 能力 | 状态 | 证据 / 替代路线 |
|---|---|---|
| NumPy/SciPy/scikit-image/OpenCV/Pillow/pyarrow/pandas/Pydantic/Typer/FastAPI | 可用 | `synlab doctor` 导入检查 PASS |
| trimesh 5.1.0 + manifold3d 3.5.4 布尔 | 可用（真实执行） | 100 mm 盒体切割与薄壳切割守恒检查 PASS |
| manifold3d 来源属性（run/original/face id） | 见 `backend_capabilities.json` | 项目**自行**为每个输入三角保存显式 `source_triangle`（计划 §30.5 要求，不依赖库属性） |
| Gmsh 4.15.2 | 可用（真实执行） | 两体 PLC 分片 → 共形四面体网格 PoC |
| pycolmap 3.11.1（COLMAP 库） | 可用 | 独立 `colmap` 可执行文件**不存在**；照片重建用 `pycolmap` |
| Open3D 0.19.0 | 可用 | 闭合实体 signed distance PoC |
| faiss-cpu 1.15.1 | 可用 | 仅作可选精确索引，主路径用 NumPy 分块精确内积 |
| PyTorch | **2.5.1+cpu（无 CUDA）** | 计划要求与现有 PyTorch/CUDA 环境一致；本机**没有** CUDA 版 torch，训练与 GPU 相关结论只能按 CPU 规模报告 |
| **Blender** | **缺失** | 无 binary；`pip install bpy` 无 Windows/CPython 3.12 wheel（实测 `No matching distribution found`）。渲染走项目自研软件光栅渲染器（记为 `CUSTOM_GAP`，见 `reuse_manifest.json`），Blender adapter 保留为可插拔目标并报 `ENV_CAPABILITY_MISSING` |
| 真实实拍数据 | **缺失** | PHONE_RGB 校准与真实迁移保持 `PENDING`/`REAL_DATA_PENDING`；实际 MVS 子集只能在合成渲染图上真实运行 |

依赖版本锁定：`requirements.lock.txt`（`pip freeze`）。注意本机实测：pandas 3.x / torch 2.14 / open3d 0.20 的编译扩展在本机 `STATUS_DLL_INIT_FAILED`，已固定到 pandas 2.2.3 / torch 2.5.1+cpu / open3d 0.19.0；该偏离已记录，升级后必须重跑受影响资格。

## 4. 现有可复用模块（主项目侧）

无。因此：

* 所有 `ObsPack`/`FeaturePack`/loader/编码器/检索/路由/前端均为**本工程新建**，并通过适配器边界（`a12.obs.v1` 特征合同 + `ObsPackAdapter`）与未来主仓对接；
* 未读取到 V1.45/A3/A4 的真实接口文件（附件只有 V1.44 Word 计划文档，未发现 schema 文件），因此**不能**声称 `rw-schema-1.1` 兼容；
* `docs/a12/contract_diff.json` 记录：`external_contract_ref = null`、`feature_schema = a12.obs.v1`、缺失字段全部标 `PENDING`。

## 5. 本工程目录与职责

见 `docs/a12/architecture.md` 与计划 §3.2 的映射表（本工程完全采用计划目标目录 `synlab/*`，未做重命名）。

## 6. 测试入口

```powershell
$py = "C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\.venv\Scripts\python.exe"
& $py -m pytest tests -q          # 全部单元/性质/契约测试
& $py -m synlab.cli doctor --json # 能力核验并写 env_report/backend_capabilities
```

## 7. 未完成与阻塞（诚实声明）

1. 主仓集成未完成（无主仓、无 A3/A4 schema）。
2. Blender 渲染后端缺失；软件光栅渲染器为替代路线，语义（线性 RGB/整数 ID/深度）由 doctor 与 A12 验收项实测。
3. 无 CUDA torch、无实拍数据：GPU 规模训练、PHONE_RGB 校准、真实迁移为 `PENDING`。
4. 计划 §1.3 的 L2（480 母体）/L3（1/5/10 万片）规模属于运行产物，本会话只按实际可承担规模运行并如实报告计数。
