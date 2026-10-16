"""真实端到端运行器（Playwright）。

调用仓库里**已经安装**的 `@playwright/test`（`frontend/node_modules`）与构建产物 `frontend/dist`，
并让 Playwright 自己拉起：
1. 真实后端：`.venv/Scripts/python.exe tests/a12/api_ui/_serve.py --store-root <store> --port 8081`;
2. 构建产物预览：`vite preview --host 127.0.0.1 --port 4178`（`/api` 反代到后端）。

> Playwright 的用例文件必须能解析 `@playwright/test`，因此用例与配置放在 `frontend/`
> （那里有 node_modules），本脚本只是把入口固定到 `tests/a12/api_ui/**` 下的文档化命令。

用法::

    python tests/a12/api_ui/run_e2e.py                     # 用默认演示数据根 data/a12_demo/store
    python tests/a12/api_ui/run_e2e.py --store-root data/a12
    python tests/a12/api_ui/run_e2e.py --skip-build        # 不重新构建 dist

退出码：0 = 全部通过；非 0 = 测试失败或环境缺失（并在输出里给出原因）。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
FRONTEND = REPO_ROOT / "frontend"
DEFAULT_PYTHON = REPO_ROOT / ".venv" / "Scripts" / "python.exe"


def playwright_command() -> list[str] | None:
    """返回可直接执行的 `playwright test` 命令（pnpm / corepack / npm 任选其一）。"""
    pnpm = shutil.which("pnpm.cmd") or shutil.which("pnpm")
    if pnpm:
        return [pnpm, "exec", "playwright", "test"]
    corepack = shutil.which("corepack.cmd") or shutil.which("corepack")
    if corepack:
        return [corepack, "pnpm@11.7.0", "exec", "playwright", "test"]
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if npm:
        return [npm, "exec", "--", "playwright", "test"]
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store-root", default=str(REPO_ROOT / "data" / "a12_demo" / "store"))
    parser.add_argument("--backend-port", type=int, default=8081)
    parser.add_argument("--preview-port", type=int, default=4178)
    parser.add_argument("--skip-build", action="store_true")
    args = parser.parse_args()

    node = shutil.which("node")
    if not node:
        print("找不到 node；无法运行 Playwright", file=sys.stderr)
        return 2

    playwright = FRONTEND / "node_modules" / "@playwright" / "test"
    if not playwright.is_dir():
        print(
            "frontend/node_modules/@playwright/test 不存在：\n"
            "  先执行  corepack pnpm@11.7.0 add -D @playwright/test@1.63.0\n"
            "  再执行  corepack pnpm@11.7.0 exec playwright install chromium",
            file=sys.stderr,
        )
        return 2

    if not args.skip_build:
        for cmd in (
            [node, str(FRONTEND / "node_modules" / "typescript" / "bin" / "tsc"), "--noEmit"],
            [node, str(FRONTEND / "node_modules" / "vite" / "bin" / "vite.js"), "build"],
        ):
            print(f"$ {' '.join(cmd)}")
            completed = subprocess.run(cmd, cwd=str(FRONTEND))
            if completed.returncode != 0:
                print(f"构建失败（exit {completed.returncode}）", file=sys.stderr)
                return completed.returncode

    cmd = playwright_command()
    if cmd is None:
        print("找不到 pnpm/corepack/npm；无法启动 playwright test", file=sys.stderr)
        return 2

    env = dict(os.environ)
    env["SYNLAB_E2E_STORE"] = args.store_root
    env["SYNLAB_E2E_BACKEND_PORT"] = str(args.backend_port)
    env["SYNLAB_E2E_PREVIEW_PORT"] = str(args.preview_port)
    env["SYNLAB_E2E_PYTHON"] = str(DEFAULT_PYTHON if DEFAULT_PYTHON.is_file() else sys.executable)

    print(f"$ {' '.join(cmd)}  (cwd={FRONTEND})")
    completed = subprocess.run(cmd, cwd=str(FRONTEND), env=env)
    print(f"playwright exit={completed.returncode}")
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
