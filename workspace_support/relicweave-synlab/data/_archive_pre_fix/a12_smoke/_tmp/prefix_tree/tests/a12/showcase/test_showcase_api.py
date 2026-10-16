"""展示只读路由的真实测试（FastAPI ``TestClient``，数据来自真实生成器）。

覆盖：

* `GET /showcase/manifest`：真实清单 / 未生成时的 ``NOT_RUN``（不返回假数据）；
* `GET /showcase/asset/{asset_id}/{key}`：白名单 key 的 Content-Type、sha256 响应头、
  未知 key（``SHOWCASE_KEY_NOT_ALLOWED``）、未知资产（``NOT_FOUND``）、
  不存在的 payload key（``NOT_FOUND``）、key 与文件类型不匹配（``SHOWCASE_KEY_MISMATCH``）；
* 角色策略：``deployment_client`` 也必须能只读浏览展示页（真值路由策略不变）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[3]
TOOLS = REPO_ROOT / "tools"
for path in (str(REPO_ROOT), str(TOOLS)):
    if path not in sys.path:
        sys.path.insert(0, path)

import build_demo_assets as gen  # noqa: E402

PREFIX = "/api/synlab"


@pytest.fixture(scope="module")
def demo_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("showcase_api_demo")
    code = gen.main(["--only", "mothers", "--limit", "1", "--inline", "--demo-root", str(root)])
    assert code == 0
    return root


@pytest.fixture()
def client(demo_root: Path, tmp_path: Path) -> TestClient:
    from synlab.api import create_app

    # 会话的 store_root 是一个**空**目录：展示路由必须自己解析演示数据根，
    # 不能偷偷读会话资产库。
    app = create_app(tmp_path / "session_store", role="deployment_client",
                     showcase_root=demo_root)
    return TestClient(app)


def _manifest(demo_root: Path) -> dict:
    return json.loads((demo_root / gen.MANIFEST_NAME).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------- manifest


def test_manifest_returns_real_entries(client: TestClient, demo_root: Path) -> None:
    from synlab.api.routers import showcase as showcase_router

    assert gen.GENERATOR_COMMAND == showcase_router.GENERATOR_COMMAND, \
        "生成器与展示 API 必须声明同一条生成命令"

    response = client.get(f"{PREFIX}/showcase/manifest")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["status"] == "OK"
    assert body["read_only"] is True
    assert body["generator_command"] == gen.GENERATOR_COMMAND
    assert body["manifest_path"].endswith(gen.MANIFEST_NAME)
    assert body["counts"]["entries"] == len(body["entries"]) > 0
    assert len(body["axis_catalog"]) == 31
    assert body["summary"]["entry_count"] == len(body["entries"])
    # 返回的条目必须与磁盘上的清单逐字段一致（不做任何加工）
    on_disk = _manifest(demo_root)
    assert [e["entry_id"] for e in body["entries"]] == [e["entry_id"] for e in on_disk["entries"]]
    assert body["entries"][0]["metrics"] == on_disk["entries"][0]["metrics"]


def test_manifest_not_run_is_explicit(tmp_path: Path) -> None:
    from synlab.api import create_app

    empty = tmp_path / "no_demo"
    empty.mkdir()
    app = create_app(tmp_path / "session_store", role="researcher", showcase_root=empty)
    client = TestClient(app)
    response = client.get(f"{PREFIX}/showcase/manifest")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "NOT_RUN"
    assert body["entries"] == []
    assert body["counts"]["entries"] == 0
    assert "build_demo_assets.py" in body["empty_reason"]
    assert body["generator_command"] == gen.GENERATOR_COMMAND


def test_explicit_showcase_root_is_strict(tmp_path: Path) -> None:
    """显式 showcase_root 不得回退到仓库默认位置（否则部署时会把别的数据集当成自己的）。"""
    from synlab.api.routers.showcase import ShowcaseLocator

    empty = tmp_path / "empty"
    empty.mkdir()
    locator = ShowcaseLocator(tmp_path / "session_store", empty)
    assert locator.candidate_roots() == [empty]
    manifest_path, root = locator.resolve()
    assert manifest_path is None
    assert root == empty
    assert locator.store() is None


def test_manifest_available_to_deployment_role(client: TestClient) -> None:
    """展示页是部署只读能力：deployment_client 必须能读，且不因此获得研究真值。"""
    assert client.get(f"{PREFIX}/showcase/manifest").status_code == 200
    truth = client.get(f"{PREFIX}/research/assets/asset_00000000000000000000/truth")
    assert truth.status_code == 403
    assert truth.json()["error"]["code"] == "TRUTH_ROUTE_UNMOUNTED"


# ---------------------------------------------------------------------------- asset


def _first_asset(demo_root: Path, kind: str, artifact: str) -> tuple[str, str]:
    for entry in _manifest(demo_root)["entries"]:
        if entry["kind"] != kind:
            continue
        raw = (entry.get("artifacts") or {}).get(artifact)
        if isinstance(raw, dict) and raw.get("asset_id"):
            return raw["asset_id"], str(raw.get("key") or artifact)
    raise AssertionError(f"演示集里没有 {kind}/{artifact} 资产")


def test_glb_key_serves_gltf_binary_with_hash(client: TestClient, demo_root: Path) -> None:
    asset_id, _ = _first_asset(demo_root, "mother", "glb")
    response = client.get(f"{PREFIX}/showcase/asset/{asset_id}/glb")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("model/gltf-binary")
    assert response.headers["X-SynLab-Asset-Id"] == asset_id
    assert response.headers["X-SynLab-File-Key"] == "glb"
    digest = response.headers["X-SynLab-File-Sha256"]
    assert digest.startswith("sha256:")
    assert response.headers["X-SynLab-Showcase-Key"] == "glb"
    assert response.content[:4] == b"glTF", "GLB 头必须是真实的 glTF 魔数"


def test_meta_key_serves_json(client: TestClient, demo_root: Path) -> None:
    asset_id, _ = _first_asset(demo_root, "mother", "glb")
    response = client.get(f"{PREFIX}/showcase/asset/{asset_id}/meta")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    payload = response.json()
    assert "meta" in payload and "qa" in payload


def test_arrays_key_reports_missing_payload(client: TestClient, demo_root: Path) -> None:
    """派生 GLB 资产没有 npz：必须是结构化 404，而不是空文件。"""
    asset_id, _ = _first_asset(demo_root, "mother", "glb")
    response = client.get(f"{PREFIX}/showcase/asset/{asset_id}/arrays")
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "NOT_FOUND"
    assert "available" in error["details"]


def test_unknown_key_is_structured_400(client: TestClient, demo_root: Path) -> None:
    asset_id, _ = _first_asset(demo_root, "mother", "glb")
    response = client.get(f"{PREFIX}/showcase/asset/{asset_id}/bogus")
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "SHOWCASE_KEY_NOT_ALLOWED"
    assert error["details"]["whitelist"] == ["arrays", "glb", "meta", "png"]
    assert error["request_id"]


def test_unknown_asset_is_404(client: TestClient) -> None:
    response = client.get(f"{PREFIX}/showcase/asset/asset_00000000000000000000/glb")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_unknown_payload_name_is_404_with_available_list(client: TestClient, demo_root: Path) -> None:
    asset_id, _ = _first_asset(demo_root, "mother", "glb")
    response = client.get(f"{PREFIX}/showcase/asset/{asset_id}/glb", params={"name": "nope"})
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "NOT_FOUND"
    assert "glb" in error["details"]["available"]


def test_key_type_mismatch_is_structured(client: TestClient, demo_root: Path) -> None:
    asset_id, _ = _first_asset(demo_root, "mother", "glb")
    response = client.get(f"{PREFIX}/showcase/asset/{asset_id}/png", params={"name": "glb"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "SHOWCASE_KEY_MISMATCH"


def test_png_key_serves_image_png(client: TestClient, demo_root: Path) -> None:
    """小规模数据集里可能没有纹样 PNG；有就检查真实 PNG 字节，没有就说明原因。"""
    entries = _manifest(demo_root)["entries"]
    channel = next((e for e in entries
                    if (e.get("artifacts") or {}).get("channels", {}).get("asset_id")), None)
    if channel is None:
        pytest.skip("本次小规模数据集没有纹样通道资产（--only mothers）")
    asset_id = channel["artifacts"]["channels"]["asset_id"]
    keys = channel["artifacts"]["channels"].get("keys") or {}
    payload_key = keys.get("albedo", "albedo_png")
    response = client.get(f"{PREFIX}/showcase/asset/{asset_id}/png", params={"name": payload_key})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")
    assert response.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_showcase_routes_do_not_touch_session_store(client: TestClient, tmp_path: Path) -> None:
    """展示路由读的是演示资产库：会话 store_root 里不应出现任何资产。"""
    from synlab.storage.store import AssetStore

    session_store = AssetStore(tmp_path / "session_store")
    assert session_store.count_assets() == 0
    client.get(f"{PREFIX}/showcase/manifest")
    client.get(f"{PREFIX}/showcase/asset/asset_00000000000000000000/glb")
    assert session_store.count_assets() == 0, "只读展示路由不应该往会话资产库写任何东西"
