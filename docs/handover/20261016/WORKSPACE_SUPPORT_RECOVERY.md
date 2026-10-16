# workspace_support 恢复说明

A12 发布仓库将共享续接材料和根级实验支持材料分开放置：[`workspace_support/docs/continuation/`](../../../workspace_support/docs/continuation/) 保存共享 workspace 的续接文档副本；[`workspace_support/experiments/`](../../../workspace_support/experiments/) 保存根级实验脚本、冻结输入和小型证据/回执。A12 的 [`docs/continuation/`](../../continuation/) 是面向发布阅读的续接文档副本。不要把 support 归档当成新的实验结果，也不要将候选、snapshot 或 read-only binding 升格为物理资格。

若后续确需把 support 归档恢复到共享 workspace，先从 A12 仓库根目录运行只读预检：

```powershell
.\.venv\Scripts\python.exe tools/handover/archive_workspace_support.py restore --workspace .. --dry-run
```

脚本位置为 [`tools/handover/archive_workspace_support.py`](../../../tools/handover/archive_workspace_support.py)。在没有项目虚拟环境时，可将解释器替换为已配置的 Python。`--dry-run` 只报告待复制文件和冲突，不执行复制；检查输出与归档 manifest 后，再执行不带 `--dry-run` 的恢复命令。

主代理已完成行政归档：清单内 2,667 个源文件/小型证据，共 98,808,266 bytes，逐文件 SHA-256 检查通过。当前工作区的只读恢复检查没有冲突，最终归档针对空工作区的只读检查列出 2,667 个待复制文件；本轮没有实际恢复复制，也没有启动求解器。Windows 克隆时须启用 Git `core.longpaths=true`，具体命令见 [`workspace_support/README.md`](../../../workspace_support/README.md)。
