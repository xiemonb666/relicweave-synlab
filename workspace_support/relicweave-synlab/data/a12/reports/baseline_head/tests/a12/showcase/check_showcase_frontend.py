"""前端构建与展示页路由的验收脚本（真实退出码，沿用 `tests/a12/api_ui/check_frontend.py` 的做法）。

```powershell
python tests/a12/showcase/check_showcase_frontend.py
python tests/a12/showcase/check_showcase_frontend.py --skip-build   # 只检查已有 dist
```

它真实执行 `tsc --noEmit` 与 `vite build`，然后断言构建产物里：

* 存在 `/synlab/showcase` 路由字面量与导航文案“合成数据展示”；
* 展示页/分区/碎片视口组件文件都在；
* 默认构建里**没有** fixture 数据；
* 展示页的关键契约字符串（只读路由前缀、失败码、显示编码说明）确实进了 bundle。
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
FRONTEND = REPO_ROOT / "frontend"

#: 展示页必须存在的源码文件
SOURCE_FILES = (
    "src/pages/Showcase.tsx",
    "src/api/showcase.ts",
    "src/components/showcase/sections.tsx",
    "src/components/showcase/FragmentAssemblyViewport.tsx",
    "src/styles-showcase.css",
)

#: 展示页必须出现的字面量/文案。
#: 注意：错误码（如 `SHOWCASE_KEY_NOT_ALLOWED`、`FRACTURE_CONSERVATION_FAIL`、`PRECISION_NOT_REALIZED`）
#: 是**数据**里的事实，不是前端源码里的常量——它们由 `test_showcase_api.py` 与清单断言覆盖，
#: 因此不放进 bundle 断言（否则会为了让测试通过而往源码里塞死字符串）。
BUNDLE_TOKENS = (
    "synlab/showcase",
    "合成数据展示",
    "/showcase/manifest",
    "/showcase/asset/",
    "PROCESS_KILLED",
    "OPERATOR_NOT_REALIZED",
    "warped_partition",
    "fracture_modes",
    "显示编码",
    "爆炸",
    "原位",
    "source_face_coverage",
)


def run(cmd: list[str], *, cwd: Path) -> tuple[int, str]:
    print(f"$ {' '.join(cmd)}  (cwd={cwd})")
    completed = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                               encoding="utf-8", errors="replace", shell=False)
    output = (completed.stdout or "") + (completed.stderr or "")
    print(output.strip()[-4000:])
    return completed.returncode, output


def node_exe() -> str:
    found = shutil.which("node")
    if not found:
        raise SystemExit("找不到 node 可执行文件；本脚本需要 Node.js 运行时")
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-build", action="store_true", help="跳过 tsc/vite，只检查已有 dist")
    args = parser.parse_args()

    node = node_exe()
    results: list[dict[str, object]] = []
    ok = True

    if not args.skip_build:
        code, _ = run([node, str(FRONTEND / "node_modules" / "typescript" / "bin" / "tsc"),
                       "--noEmit"], cwd=FRONTEND)
        results.append({"cmd": "tsc --noEmit", "exit": code})
        ok = ok and code == 0

        code, _ = run([node, str(FRONTEND / "node_modules" / "vite" / "bin" / "vite.js"), "build"],
                      cwd=FRONTEND)
        results.append({"cmd": "vite build", "exit": code})
        ok = ok and code == 0

    print("\n== 展示页源码文件 ==")
    missing_files = []
    for relative in SOURCE_FILES:
        present = (FRONTEND / relative).is_file()
        print(f"  {'OK ' if present else 'MISS'} {relative}")
        if not present:
            missing_files.append(relative)
    ok = ok and not missing_files
    results.append({"missing_source_files": missing_files})

    dist = FRONTEND / "dist"
    index = dist / "index.html"
    assets = sorted((dist / "assets").glob("*")) if (dist / "assets").is_dir() else []
    js = next((a for a in assets if a.suffix == ".js"), None)
    css = next((a for a in assets if a.suffix == ".css"), None)
    print(f"\n== dist ==\n  index.html={index.is_file()}  js={js.name if js else None}  "
          f"css={css.name if css else None}")
    ok = ok and index.is_file() and js is not None and css is not None
    results.append({"dist_assets": [a.name for a in assets]})

    if js is not None:
        bundle = js.read_text(encoding="utf-8", errors="replace")
        print("\n== bundle 关键字符串 ==")
        missing_tokens = []
        for token in BUNDLE_TOKENS:
            present = token in bundle
            print(f"  {'OK ' if present else 'MISS'} {token}")
            if not present:
                missing_tokens.append(token)
        ok = ok and not missing_tokens
        results.append({"missing_bundle_tokens": missing_tokens})

        data_markers = ("store_fixture", "fixtureJobs", "fixtureCapabilities")
        present_markers = [marker for marker in data_markers if marker in bundle]
        print(f"\n== fixture 泄漏检查 ==\n  出现在 bundle: {present_markers or '无'}")
        ok = ok and not present_markers
        results.append({"fixture_data_in_bundle": present_markers})

    app = (FRONTEND / "src" / "App.tsx").read_text(encoding="utf-8")
    route_ok = 'path="synlab/showcase"' in app
    print(f"\n== App.tsx 路由表 ==\n  {'OK ' if route_ok else 'MISS'} /synlab/showcase")
    ok = ok and route_ok

    layout = (FRONTEND / "src" / "components" / "Layout.tsx").read_text(encoding="utf-8")
    nav_ok = "'/synlab/showcase'" in layout and "合成数据展示" in layout
    print(f"  {'OK ' if nav_ok else 'MISS'} 导航入口「合成数据展示」")
    ok = ok and nav_ok

    # 展示页/生成器/API 路由都必须真的存在（不是只写了文案）
    python_bits = {
        "tools/build_demo_assets.py": REPO_ROOT / "tools" / "build_demo_assets.py",
        "synlab/api/routers/showcase.py": REPO_ROOT / "synlab" / "api" / "routers" / "showcase.py",
        "docs/a12/showcase.md": REPO_ROOT / "docs" / "a12" / "showcase.md",
    }
    print("\n== 后端/文档文件 ==")
    for label, path in python_bits.items():
        present = path.is_file()
        print(f"  {'OK ' if present else 'MISS'} {label}")
        ok = ok and present

    results.append({"missing_in_app": [] if route_ok else ["/synlab/showcase"]})
    print("\n== 结果 ==")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"OVERALL: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
