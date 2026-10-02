"""`tools/build_demo_assets.py` 的真实小规模运行、幂等性与 `demo_manifest.json` 结构。

这些测试**不 mock 任何东西**：它们在 ``tmp_path`` 里用真实参数跑真实生成器
（``--only mothers --limit 1 --inline``），然后检查真实产物。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
TOOLS = REPO_ROOT / "tools"
for path in (str(REPO_ROOT), str(TOOLS)):
    if path not in sys.path:
        sys.path.insert(0, path)

import build_demo_assets as gen  # noqa: E402  (需要上面的 sys.path)

REPO_DEMO_ROOT = REPO_ROOT / "data" / "a12_demo"


@pytest.fixture(scope="module")
def small_demo_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """跑一次真实的小规模生成（1 个母体），返回演示数据根。"""
    demo_root = tmp_path_factory.mktemp("a12_demo_small")
    code = gen.main(["--only", "mothers", "--limit", "1", "--inline",
                     "--demo-root", str(demo_root)])
    assert code == 0, "小规模生成器应当全部 OK（一个母体）"
    return demo_root


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------- 真实产物


def test_generator_writes_manifest_and_store(small_demo_root: Path) -> None:
    manifest_path = small_demo_root / gen.MANIFEST_NAME
    assert manifest_path.is_file(), "生成器必须写出 demo_manifest.json"
    assert (small_demo_root / gen.STORE_DIRNAME / "metadata.sqlite").is_file(), \
        "生成器必须建立独立的演示资产库（不污染 data/a12）"

    data = _load(manifest_path)
    assert data["schema"] == gen.MANIFEST_SCHEMA
    assert data["manifest_path"].endswith(gen.MANIFEST_NAME)
    assert data["demo_root"] and data["store_root"]
    assert data["master_seed"] == gen.MASTER_SEED
    assert isinstance(data["entries"], list) and data["entries"], "至少要有一条真实条目"
    assert isinstance(data["axis_catalog"], list) and len(data["axis_catalog"]) == 31, \
        "axis_catalog 必须覆盖 31 个退化轴（未生成的轴也要列出 NA 原因）"
    assert data["runs"] and data["runs"][-1]["units_executed"] >= 1


def test_entry_structure_is_honest(small_demo_root: Path) -> None:
    data = _load(small_demo_root / gen.MANIFEST_NAME)
    for entry in data["entries"]:
        for key in ("entry_id", "kind", "title", "status", "metrics", "artifacts"):
            assert key in entry, f"{entry.get('entry_id')} 缺少字段 {key}"
        assert entry["status"] in {"OK", "BLOCKED", "FAILED", "NA"}
        if entry["status"] != "OK":
            assert entry["failure"], f"{entry['entry_id']} 非 OK 却没有记录失败原因"
            assert entry["failure"]["code"], "失败必须带稳定错误码"
            assert entry["failure"]["message"], "失败必须带可读 message"
        else:
            assert entry["failure"] is None


def test_mother_entry_carries_real_measured_numbers(small_demo_root: Path) -> None:
    data = _load(small_demo_root / gen.MANIFEST_NAME)
    mothers = [e for e in data["entries"] if e["kind"] == "mother"]
    assert mothers, "小规模生成至少要有一个母体条目"
    entry = mothers[0]
    assert entry["status"] == "OK"
    assert str(entry["asset_id"]).startswith("asset_")
    assert entry["role"] == "mother_mesh"
    assert entry["unit"] == "mm" and entry["frame"] == "W_mm"

    metrics = entry["metrics"]
    assert metrics["faces"] > 0 and metrics["vertices"] > 0, "面数/顶点必须来自真实网格"
    assert metrics["volume_mm3"] > 0, "体积必须是实测值"
    assert metrics["qa_state"] in {"QA_PASSED", "QA_FAILED"}, "QA 状态必须来自 audit_mother"
    assert metrics["qa_metrics"], "audit_mother 的 metrics 必须落盘（不是空字典）"

    # 展示 GLB：必须是真实的米制 / Y-up 派生资产，且给出真实字节数
    glb = entry["artifacts"]["glb"]
    assert str(glb["asset_id"]).startswith("asset_")
    assert glb["key"] == "glb"
    assert glb["metrics"]["glb_bytes"] > 0
    assert len(glb["metrics"]["authority_extent_mm"]) == 3
    assert len(glb["metrics"]["display_extent_m"]) == 3
    # mm → m：展示尺寸应当正好是权威尺寸的 1/1000（三轴重排）
    authority = sorted(round(v, 6) for v in glb["metrics"]["authority_extent_mm"])
    display = sorted(round(v * 1000.0, 6) for v in glb["metrics"]["display_extent_m"])
    assert authority == pytest.approx(display, rel=1e-6, abs=1e-3), \
        "派生 GLB 必须严格按 T_display_authority 缩放（米 / Y-up）"


def test_generator_is_idempotent(small_demo_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """再跑一次同样的命令：不重跑已 OK 的单元，条目与资产 id 不变。"""
    before = _load(small_demo_root / gen.MANIFEST_NAME)
    before_pairs = [(e["entry_id"], e["status"], e.get("asset_id")) for e in before["entries"]]
    before_runs = len(before["runs"])

    code = gen.main(["--only", "mothers", "--limit", "1", "--inline",
                     "--demo-root", str(small_demo_root)])
    assert code == 0
    after = _load(small_demo_root / gen.MANIFEST_NAME)
    after_pairs = [(e["entry_id"], e["status"], e.get("asset_id")) for e in after["entries"]]

    assert after_pairs == before_pairs, "幂等性：条目与 asset_id 必须完全不变"
    assert len(after["runs"]) == before_runs + 1, "每次都追加一条真实 run 记录"
    assert after["runs"][-1]["units_executed"] == 0, "第二次运行不应该重跑任何单元"
    out = capsys.readouterr().out
    assert "[skip]" in out and "已 OK" in out


def test_force_rerun_produces_same_asset_ids(small_demo_root: Path) -> None:
    """--force 重跑：内容寻址的资产 id 必须与第一次完全一致（同样的种子与参数）。"""
    data = _load(small_demo_root / gen.MANIFEST_NAME)
    mother = next(e for e in data["entries"] if e["kind"] == "mother")
    before = (mother["asset_id"], mother["artifacts"]["glb"]["asset_id"])

    code = gen.main(["--only", "mothers", "--limit", "1", "--inline", "--force",
                     "--demo-root", str(small_demo_root)])
    assert code == 0
    data = _load(small_demo_root / gen.MANIFEST_NAME)
    mother = next(e for e in data["entries"] if e["kind"] == "mother")
    after = (mother["asset_id"], mother["artifacts"]["glb"]["asset_id"])
    assert after == before, "内容寻址：同一输入的 asset_id 必须可复现"


def test_asset_ids_exist_in_the_demo_store(small_demo_root: Path) -> None:
    """清单里每个 asset_id 都必须能在演示资产库里真实取到（不是编出来的 id）。"""
    from synlab.storage.store import AssetStore

    data = _load(small_demo_root / gen.MANIFEST_NAME)
    store = AssetStore(small_demo_root / gen.STORE_DIRNAME)
    checked = 0
    for entry in data["entries"]:
        ids = []
        if entry.get("asset_id"):
            ids.append(entry["asset_id"])
        for artifact in (entry.get("artifacts") or {}).values():
            if isinstance(artifact, dict) and artifact.get("asset_id"):
                ids.append(artifact["asset_id"])
        for asset_id in ids:
            record = store.get_asset(asset_id)
            assert record.role, f"{asset_id} 没有 role"
            assert record.files, f"{asset_id} 没有任何 payload 文件"
            checked += 1
    assert checked >= 2, "至少应当检查母体资产与它的派生 GLB"


def test_axis_catalog_lists_na_axes_with_reason(small_demo_root: Path) -> None:
    data = _load(small_demo_root / gen.MANIFEST_NAME)
    catalog = data["axis_catalog"]
    ids = [item.get("axis_id") for item in catalog]
    assert sorted(ids) == sorted(
        [f"P{i:02d}" for i in range(1, 9)]
        + [f"I{i:02d}" for i in range(1, 11)]
        + [f"G{i:02d}" for i in range(1, 9)]
        + [f"X{i:02d}" for i in range(1, 6)]
    ), "axis_catalog 必须恰好覆盖 31 个真实注册轴"
    for item in catalog:
        if not item["generated"]:
            assert item["status"] == "NA"
            assert item.get("na_reason"), f"{item['axis_id']} 是 NA 但没有写原因"
        assert item.get("stage"), f"{item['axis_id']} 缺少真实 stage 声明"


# ---------------------------------------------------------------------------- 仓库里的真实数据集（存在才检查）


@pytest.mark.skipif(not (REPO_DEMO_ROOT / gen.MANIFEST_NAME).is_file(),
                    reason="仓库里还没有生成 data/a12_demo/demo_manifest.json")
def test_repo_dataset_manifest_is_consistent() -> None:
    from synlab.storage.store import AssetStore

    data = _load(REPO_DEMO_ROOT / gen.MANIFEST_NAME)
    counts = data["counts"]
    assert counts["entries"] == len(data["entries"])
    statuses = {"OK": 0, "FAILED": 0, "BLOCKED": 0, "NA": 0}
    for entry in data["entries"]:
        statuses[entry["status"]] = statuses.get(entry["status"], 0) + 1
    assert counts["total"] == statuses, "counts.total 必须与 entries 的真实状态统计一致"

    store = AssetStore(REPO_DEMO_ROOT / gen.STORE_DIRNAME)
    for entry in data["entries"]:
        if entry.get("asset_id"):
            store.get_asset(entry["asset_id"])  # 不存在就会抛 SynLabError


@pytest.mark.skipif(not (REPO_DEMO_ROOT / gen.MANIFEST_NAME).is_file(),
                    reason="仓库里还没有生成 data/a12_demo/demo_manifest.json")
def test_repo_dataset_has_no_fabricated_images() -> None:
    """所有 PNG 产物都必须是资产库里真实存在、可解析的非空 PNG。"""
    from PIL import Image

    from synlab.storage.store import AssetStore

    data = _load(REPO_DEMO_ROOT / gen.MANIFEST_NAME)
    store = AssetStore(REPO_DEMO_ROOT / gen.STORE_DIRNAME)
    png_keys: list[tuple[str, str]] = []
    for entry in data["entries"]:
        for artifact in (entry.get("artifacts") or {}).values():
            if isinstance(artifact, dict) and isinstance(artifact.get("keys"), dict):
                for key in artifact["keys"].values():
                    png_keys.append((artifact["asset_id"], str(key)))
    if not png_keys:
        pytest.skip("本次数据集没有纹样通道 PNG 资产")
    for asset_id, key in png_keys:
        record = store.get_asset(asset_id)
        assert key in record.files, f"{asset_id} 里没有 {key}"
        path = store.root / Path(*record.files[key].split("/"))
        assert path.is_file() and path.stat().st_size > 0
        with Image.open(path) as image:
            assert image.format == "PNG"
            assert image.size[0] > 0 and image.size[1] > 0
