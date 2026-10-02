"""前端构建与路由验收脚本（可重复执行，输出真实退出码）。

本脚本**不 mock 任何东西**：它调用仓库里真实的 `node` + `node_modules`，执行
`tsc --noEmit` 与 `vite build`，然后检查产物里是否真的包含 12 个路由、是否误把
fixture 数据打进默认构建。

用法::

    python tests/a12/api_ui/check_frontend.py
    python tests/a12/api_ui/check_frontend.py --skip-build      # 只检查已有 dist
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
FRONTEND = REPO_ROOT / "frontend"

#: 计划 20.2–20.13 的 12 个页面路由
ROUTES = (
    "/synlab",
    "/synlab/mothers/new",
    "/synlab/patterns",
    "/synlab/fracture",
    "/synlab/degradation",
    "/synlab/camera-profiles",
    "/synlab/jobs",
    "/synlab/releases",
    "/synlab/training",
    "/synlab/diagnostics",
    "/synlab/episodes",
    "/synlab/quality",
)

#: 计划 20.1 要求的统一组件
COMPONENTS = (
    "SchemaForm",
    "AssetBrowser",
    "SceneViewport",
    "CompareViewport",
    "MeasuredQualityTable",
    "CoverageMatrix",
    "JobTimeline",
    "ResourceBudgetCard",
    "RunSelector",
    "MetricChart",
    "FailureDrawer",
    "ProvenanceDrawer",
)#: 本次补齐降级项新增的组件（真实数组视图 / 负控 / 相机 U 预览 / I09 外参核对）
NEW_COMPONENTS = (
    "RealArrayHeatmap",
    "PointCloudDiffView",
    "DegradationDiffPanel",
    "PatternChannelViewer",
    "SurfaceTagView",
    "NegativeControlPanel",
    "CameraUPreviewPanel",
    "I09ExtrinsicsCheck",
)

#: 真实数组解析与分析的 lib（浏览器内解码后端 npz / 统计 / 色标）
NEW_LIBS = (
    "lib/npz.ts",
    "lib/assetData.ts",
    "lib/analysis.ts",
)

#: 端到端（Playwright）用例与配置
E2E_FILES = (
    FRONTEND / "playwright.config.ts",
    FRONTEND / "e2e" / "ui-real-backend.spec.ts",
)

#: 操作逻辑改版新增的组件与 lib（合成向导 / 批量面板 / 退化配对 / 断面视图 / 错误卡 / YAML）
SYNTHESIS_FILES = (
    "pages/SynthesisWizard.tsx",
    "components/BatchSynthesisPanel.tsx",
    "components/DegradationPairPanel.tsx",
    "components/FracturePreviewPanel.tsx",
    "components/FragmentMeshViewport.tsx",
    "components/RgbFrameView.tsx",
    "components/AsyncOperation.tsx",
    "lib/yaml.ts",
)

#: 新增页面路由（U14 合成向导）
SYNTHESIS_ROUTES = ("/synlab/synthesis",)

#: 新增端点的契约验收脚本（真实 app + 真实 store，见 --help）
SYNTHESIS_CHECKER = REPO_ROOT / "tests" / "a12" / "api_ui" / "check_synthesis_ui.py"


def run(cmd: list[str], *, cwd: Path) -> tuple[int, str]:
    print(f"$ {' '.join(cmd)}  (cwd={cwd})")
    completed = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8",
                               shell=False)
    output = (completed.stdout or "") + (completed.stderr or "")
    # 子进程输出里含非 GBK 字符（例如 vite 的 ✓）；控制台编码不支持时不能因此崩掉。
    safe_print(output.strip()[-4000:])
    return completed.returncode, output


def safe_print(text: str) -> None:
    """按控制台真实编码打印，无法编码的字符用占位符替换（脚本本身不许因输出而失败）。"""
    stream = sys.stdout
    encoding = getattr(stream, "encoding", None) or "utf-8"
    try:
        print(text)
    except UnicodeEncodeError:
        buffer = text.encode(encoding, errors="replace")
        stream.write(buffer.decode(encoding, errors="replace") + "\n")


def node_exe() -> str:
    found = shutil.which("node")
    if not found:
        raise SystemExit("找不到 node 可执行文件；本脚本需要 Node.js 运行时")
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-build", action="store_true", help="跳过 tsc/vite，只检查已有 dist")
    args = parser.parse_args()

    # Windows 控制台默认 GBK；先切到 UTF-8，避免打印子进程输出时崩掉。
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass

    node = node_exe()
    results: list[dict[str, object]] = []
    ok = True

    if not args.skip_build:
        code, _ = run([node, str(FRONTEND / "node_modules" / "typescript" / "bin" / "tsc"), "--noEmit"],
                      cwd=FRONTEND)
        results.append({"cmd": "tsc --noEmit", "exit": code})
        ok = ok and code == 0

        code, _ = run([node, str(FRONTEND / "node_modules" / "vite" / "bin" / "vite.js"), "build"],
                      cwd=FRONTEND)
        results.append({"cmd": "vite build", "exit": code})
        ok = ok and code == 0

    dist = FRONTEND / "dist"
    index = dist / "index.html"
    print(f"\n== dist ==")
    print(f"index.html exists: {index.is_file()}")
    ok = ok and index.is_file()

    assets = sorted((dist / "assets").glob("*")) if (dist / "assets").is_dir() else []
    for asset in assets:
        print(f"  {asset.name}  {asset.stat().st_size} bytes")
    js = next((a for a in assets if a.suffix == ".js"), None)
    css = next((a for a in assets if a.suffix == ".css"), None)
    ok = ok and js is not None and css is not None
    results.append({"dist_assets": [a.name for a in assets]})

    if js is not None:
        bundle = js.read_text(encoding="utf-8", errors="replace")
        missing_routes = [route for route in ROUTES if f'"{route}"' not in bundle]
        # /synlab 会作为其它路由的前缀出现，"synlab/mothers/new" 这类短串也可作为兜底
        missing_routes = [
            route for route in missing_routes
            if route.strip("/") not in bundle
        ]
        print(f"\n== 路由检查（bundle 中出现的字面量）==")
        for route in ROUTES:
            present = route in bundle or route.strip("/") in bundle
            print(f"  {'OK ' if present else 'MISS'} {route}")
        ok = ok and not missing_routes
        results.append({"missing_routes": missing_routes})

        print(f"\n== 组件检查（源码文件）==")
        src = FRONTEND / "src"
        missing_components = [name for name in COMPONENTS if not (src / "components" / f"{name}.tsx").is_file()
                              and not (src / "components" / f"{name}.tsx".replace(".tsx", ".tsx")).is_file()]
        for name in COMPONENTS:
            present = (src / "components" / f"{name}.tsx").is_file()
            print(f"  {'OK ' if present else 'MISS'} src/components/{name}.tsx")
        ok = ok and not missing_components
        results.append({"missing_components": missing_components})

        print(f"\n== 新增组件检查（补齐降级项：真实数组视图 / 负控 / U 预览 / I09）==")
        missing_new = [name for name in NEW_COMPONENTS if not (src / "components" / f"{name}.tsx").is_file()]
        for name in NEW_COMPONENTS:
            present = (src / "components" / f"{name}.tsx").is_file()
            print(f"  {'OK ' if present else 'MISS'} src/components/{name}.tsx")
        ok = ok and not missing_new
        results.append({"missing_new_components": missing_new})

        print(f"\n== 新增 lib 检查（npz 解码 / 资产数组加载 / 分析）==")
        missing_libs = [rel for rel in NEW_LIBS if not (src / rel).is_file()]
        for rel in NEW_LIBS:
            present = (src / rel).is_file()
            print(f"  {'OK ' if present else 'MISS'} src/{rel}")
        ok = ok and not missing_libs
        results.append({"missing_new_libs": missing_libs})

        print(f"\n== 端到端（Playwright）用例文件 ==")
        missing_e2e = [str(path.relative_to(REPO_ROOT)) for path in E2E_FILES if not path.is_file()]
        for path in E2E_FILES:
            present = path.is_file()
            print(f"  {'OK ' if present else 'MISS'} {path.relative_to(REPO_ROOT)}")
        # 用例文件缺失不算失败（Playwright 是可选环境），但要如实记录
        results.append({"missing_e2e_files": missing_e2e})

        print(f"\n== 操作逻辑改版文件检查（向导 / 批量 / 退化配对 / 断面视图 / YAML）==")
        missing_synthesis = [rel for rel in SYNTHESIS_FILES if not (src / rel).is_file()]
        for rel in SYNTHESIS_FILES:
            present = (src / rel).is_file()
            print(f"  {'OK ' if present else 'MISS'} src/{rel}")
        ok = ok and not missing_synthesis
        results.append({"missing_synthesis_files": missing_synthesis})

        print(f"\n== 新增路由检查（U14 合成向导 /synlab/synthesis）==")
        for route in SYNTHESIS_ROUTES:
            present = route in bundle
            print(f"  {'OK ' if present else 'MISS'} {route}")
            ok = ok and present
        results.append({"missing_synthesis_routes": [r for r in SYNTHESIS_ROUTES if r not in bundle]})

        print(f"\n== 新增端点契约脚本 ==")
        checker_present = SYNTHESIS_CHECKER.is_file()
        print(f"  {'OK ' if checker_present else 'MISS'} {SYNTHESIS_CHECKER.relative_to(REPO_ROOT)}")
        results.append({"synthesis_checker_present": checker_present})

        print(f"\n== fixture 泄漏检查（默认构建不得包含 fixture 数据）==")
        # fixture 数据只在 VITE_SYNLAB_FIXTURES=1 时通过动态 import 进入产物；
        # 默认构建里 import.meta.env.VITE_SYNLAB_FIXTURES 被静态替换为 ""，整个分支被消除。
        data_markers = ("store_fixture", "fixtureJobs", "fixtureCapabilities")
        present_markers = [marker for marker in data_markers if marker in bundle]
        # fixture 的说明文案是常驻 UI 标签（FixtureBanner 的 props），不算数据
        label_present = "FIXTURE 模式" in bundle
        print(f"  fixture 数据标记出现在 bundle: {present_markers or '无'}")
        print(f"  fixture 说明文案（常驻 UI 标签，允许）: {label_present}")
        ok = ok and not present_markers
        results.append({"fixture_data_in_bundle": present_markers, "fixture_label_present": label_present})

        print(f"\n== 关键契约字符串 ==")
        for token in ("display_to_authority", "mm / Z-up", "m / Y-up", "display_lod_glb",
                      "DEPENDENCY_CAPABILITY_MISSING", "Last-Event-ID"):
            present = token in bundle
            print(f"  {'OK ' if present else 'MISS'} {token}")
            ok = ok and present

    # 检查 12 个路由 + U14 向导都在路由表里（源码级）
    app = (FRONTEND / "src" / "App.tsx").read_text(encoding="utf-8")
    all_routes = tuple(ROUTES) + tuple(SYNTHESIS_ROUTES)
    missing_in_app = [route for route in all_routes if f'path="{route.lstrip("/")}"' not in app]
    print(f"\n== App.tsx 路由表 ==")
    for route in all_routes:
        present = f'path="{route.lstrip("/")}"' in app
        print(f"  {'OK ' if present else 'MISS'} {route}")
    ok = ok and not missing_in_app
    results.append({"missing_in_app": missing_in_app})

    print("\n== 结果 ==")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"OVERALL: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
