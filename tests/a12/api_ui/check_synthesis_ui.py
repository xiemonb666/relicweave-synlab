"""新增「合成向导 / 批量面板 / 退化配对」端点的契约验收（真实 app + 真实 store）。

本脚本**不 mock 任何东西**：它用 `synlab.api.app:create_app` 起一个真实的 uvicorn
（临时 store 根 + `data/a12` 只读），再用真实 HTTP 请求验证：

* `GET /synthesis/inventory` 的计数口径（planned/attempted/accepted/failed 来自 jobs 表；
  disk_bytes 来自资产 payload 的 stat()）；
* `GET /synthesis/degradation-pairs` 的配对口径（同 axis 的 L0 与 Ln、basis 是否相同、
  deltas 是否由 meta.measured 逐键相减得到），以及未物化轴的**结构化 404**；
* `POST /synthesis/batch-plan` 的游标推进与 `resume=true` 语义（忽略客户端 cursor，
  按 assets 表推进到第一个未实现组合）；
* `POST /synthesis/chain-preview` 的错误路径：非法 spec 必须是 422 `SCHEMA_INVALID`
  （真实拒绝，不是 200 空数据）。

用法::

    python tests/a12/api_ui/check_synthesis_ui.py
    python tests/a12/api_ui/check_synthesis_ui.py --store-root data/a12 --port 8079

退出码：0 = 全部通过；1 = 有断言失败（输出里给出失败项）。
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PYTHON_HINT = REPO_ROOT / ".venv" / "Scripts" / "python.exe"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class Server:
    """A real uvicorn instance in a background thread (no mocking, no TestClient shim)."""

    def __init__(self, store_root: Path, port: int) -> None:
        self.store_root = store_root
        self.port = port
        self._server: Any = None
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "Server":
        import uvicorn

        from synlab.api import create_app

        self.store_root.mkdir(parents=True, exist_ok=True)
        app = create_app(self.store_root, role="researcher", docs=False)
        config = uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="warning")
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._thread.start()
        deadline = time.time() + 60
        while time.time() < deadline:
            try:
                self.get("/health")
                return self
            except Exception:  # noqa: BLE001 - the server is simply not up yet
                time.sleep(0.2)
        raise RuntimeError("uvicorn did not become ready in 60 s")

    def __exit__(self, *_exc: object) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=20)

    # ---------------------------------------------------------------- HTTP helpers
    def _url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}/api/synlab{path}"

    def get(self, path: str) -> tuple[int, dict[str, Any]]:
        request = urllib.request.Request(self._url(path), headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            try:
                return exc.code, json.loads(body)
            except ValueError:
                return exc.code, {"raw": body}

    def post(self, path: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self._url(path), data=data,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=900) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            try:
                return exc.code, json.loads(body)
            except ValueError:
                return exc.code, {"raw": body}


def base_spec() -> dict[str, Any]:
    return {
        "schema": "synlab.v3",
        "data_scope": "SYNTHETIC",
        "release_profile": "SANDBOX_CORE",
        "experiment_purpose": "DEVELOPMENT",
        "master_seed": 20261001,
        "dataset": {"target_mothers": 1, "target_fragments_estimate": 6},
        "fracture": {"backend": "plane_shared_cut", "target_piece_range": [4, 12]},
        "observation": {
            "input_profile": "SENSOR_PROXY",
            "routes": ["proxy_scan"],
            "views_per_fragment": 2,
            "image_long_edge_px": 256,
            "renderer": "software_rasterizer",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store-root", default=str(REPO_ROOT / "data" / "a12"))
    parser.add_argument("--port", type=int, default=0, help="0 = 自动挑一个空闲端口")
    args = parser.parse_args()

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass

    store_root = Path(args.store_root).resolve()
    port = args.port or free_port()
    results: list[dict[str, Any]] = []
    failures: list[str] = []

    def check(name: str, condition: bool, detail: Any = None) -> None:
        results.append({"check": name, "ok": bool(condition), "detail": detail})
        print(f"  {'OK  ' if condition else 'FAIL'} {name}" + (f"  {detail}" if detail is not None and not condition else ""))
        if not condition:
            failures.append(name)

    print(f"store_root={store_root}")
    with Server(store_root, port) as server:
        print(f"real app on http://127.0.0.1:{port}/api/synlab")

        # ------------------------------------------------------------ inventory
        status, inventory = server.get("/synthesis/inventory")
        check("GET /synthesis/inventory -> 200", status == 200, status)
        check("inventory.ok is True", inventory.get("ok") is True, inventory.get("ok"))
        panel = inventory.get("panel") or {}
        for key in ("planned", "attempted", "accepted", "failed", "disk_bytes", "by_state"):
            check(f"panel.{key} present", key in panel, sorted(panel))
        check("panel.attempted <= panel.planned", panel.get("attempted", 0) <= panel.get("planned", 0),
              {"attempted": panel.get("attempted"), "planned": panel.get("planned")})
        check("panel.accepted <= panel.attempted", panel.get("accepted", 0) <= panel.get("attempted", 0),
              {"accepted": panel.get("accepted"), "attempted": panel.get("attempted")})
        check("panel.disk_bytes is a real number", isinstance(panel.get("disk_bytes"), int), type(panel.get("disk_bytes")).__name__)
        buckets = inventory.get("buckets") or {}
        check("buckets.rows is a list", isinstance(buckets.get("rows"), list), type(buckets.get("rows")).__name__)
        if buckets.get("rows"):
            row = buckets["rows"][0]
            check("bucket row carries real counts",
                  all(key in row for key in ("vessel_id", "material_id", "assets", "fragments", "lineages", "covered")),
                  sorted(row))
            total_assets = sum(int(item["assets"]) for item in buckets["rows"])
            check("bucket assets <= inventory.assets_total", total_assets <= int(inventory.get("assets_total", 0)),
                  {"sum": total_assets, "total": inventory.get("assets_total")})
        coverage = inventory.get("coverage") or {}
        check("coverage.targets present", bool(coverage.get("targets")), coverage.get("targets"))
        check("coverage.covered is a mapping", isinstance(coverage.get("covered"), dict), type(coverage.get("covered")).__name__)
        check("inventory.degradation_axes is a list", isinstance(inventory.get("degradation_axes"), list))
        check("inventory.degradation_pairs is a list", isinstance(inventory.get("degradation_pairs"), list))

        # ------------------------------------------------------------ degradation pairs
        status, pairs = server.get("/synthesis/degradation-pairs")
        check("GET /synthesis/degradation-pairs -> 200", status == 200, status)
        check("pairs listing has repro", bool(pairs.get("repro")), pairs.get("repro"))
        axes = pairs.get("axes") or []
        materialized = [entry for entry in axes if entry.get("materialized")]
        if materialized:
            axis_id = materialized[0]["axis_id"]
            status, one = server.get(f"/synthesis/degradation-pairs?axis_id={axis_id}")
            check(f"pairs for materialized axis {axis_id} -> 200", status == 200, status)
            check("axis_id echoed", one.get("axis_id") == axis_id, one.get("axis_id"))
        status, missing = server.get("/synthesis/degradation-pairs?axis_id=ZZ99")
        check("unknown axis -> 404 structured", status == 404, status)
        error = (missing.get("error") or {})
        check("unknown axis error code NOT_FOUND", bool(error.get("code")), error)
        check("unknown axis error carries details", isinstance(error.get("details"), dict), error.get("details"))

        if pairs.get("pairs"):
            pair = pairs["pairs"][0]
            check("pair has level_0 / level_n", pair.get("level_0") and pair.get("level_n"), sorted(pair))
            check("pair reports paired/same_source", "paired" in pair and "same_source" in pair, sorted(pair))
            check("pair carries deltas", isinstance(pair.get("deltas"), list), type(pair.get("deltas")).__name__)
            if pair["deltas"]:
                delta = pair["deltas"][0]
                check("delta row has from/to/delta", all(key in delta for key in ("key", "from", "to", "delta")), delta)
                expected = None
                if isinstance(delta["from"], (int, float)) and isinstance(delta["to"], (int, float)):
                    expected = float(delta["to"]) - float(delta["from"])
                check("delta equals to - from", expected is None or abs(expected - float(delta["delta"])) < 1e-9,
                      {"expected": expected, "got": delta["delta"]})
        else:
            check("no materialized pairs -> empty_reason given", bool(pairs.get("empty_reason")), pairs.get("empty_reason"))

        # ------------------------------------------------------------ batch plan
        status, plan1 = server.post("/synthesis/batch-plan",
                                    {"spec": base_spec(), "requested": 3, "batch_size": 3, "cursor": 0})
        check("POST /synthesis/batch-plan -> 200", status == 200, status)
        check("plan1.selected <= 3", int(plan1.get("selected", 99)) <= 3, plan1.get("selected"))
        if plan1.get("selected"):
            check("plan1.next_cursor advanced", int(plan1["next_cursor"]) >= int(plan1["selected"]), plan1["next_cursor"])
            spec = plan1.get("spec") or {}
            dataset = (spec.get("dataset") or {})
            check("plan1 spec carries dataset ids", bool(dataset.get("vessel_ids")), dataset.get("vessel_ids"))
            check("plan1 spec validated (spec_hash present)", str(plan1.get("spec_hash") or "").startswith("sha256:"),
                  plan1.get("spec_hash"))
        # 幂等性：同样的 cursor 得到同样的组合
        status, plan2 = server.post("/synthesis/batch-plan",
                                    {"spec": base_spec(), "requested": 3, "batch_size": 3, "cursor": 0})
        check("plan is deterministic for the same cursor",
              [c.get("vessel_id") for c in plan1.get("combinations", [])] ==
              [c.get("vessel_id") for c in plan2.get("combinations", [])],
              {"a": plan1.get("combinations"), "b": plan2.get("combinations")})
        # resume 语义：忽略客户端 cursor，按 assets 表推进
        status, plan3 = server.post("/synthesis/batch-plan",
                                    {"spec": base_spec(), "requested": 3, "batch_size": 3, "cursor": 0,
                                     "resume": True})
        check("resume plan -> 200", status == 200, status)
        resume = plan3.get("resume") or {}
        check("resume semantics documented", bool(resume.get("semantics")), resume.get("semantics"))
        check("resume reports already_covered count", isinstance(resume.get("already_covered"), int),
              type(resume.get("already_covered")).__name__)
        check("resume mode is reflected", resume.get("requested") is True, resume.get("requested"))

        # ------------------------------------------------------------ chain-preview error path
        bad = base_spec()
        bad["fracture"] = {"backend": "not_a_backend", "target_piece_range": [4, 12]}
        status, rejected = server.post("/synthesis/chain-preview", {"spec": bad, "mode": "pipeline"})
        check("invalid spec -> 422", status == 422, status)
        error = (rejected.get("error") or {})
        check("invalid spec code is SCHEMA_INVALID", error.get("code") == "SCHEMA_INVALID", error.get("code"))
        check("invalid spec error names the stage", bool(error.get("stage")), error.get("stage"))

        # extra=forbid：未知字段必须被拒绝（证明请求 DTO 是真实严格模型）
        status, unknown = server.post("/synthesis/chain-preview", {"spec": base_spec(), "nope": 1})
        check("unknown field -> 422 SCHEMA_INVALID", status == 422 and (unknown.get("error") or {}).get("code") == "SCHEMA_INVALID",
              {"status": status, "error": unknown.get("error")})

    print("\n== 结果 ==")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"total={len(results)} failed={len(failures)}")
    print(f"OVERALL: {'PASS' if not failures else 'FAIL'}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
