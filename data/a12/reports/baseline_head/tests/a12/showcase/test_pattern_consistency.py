"""纹样一致性回归：卡片 PNG、器物 GLB 贴图与 provenance 必须是同一份冻结花纹。

三条硬指标（对应 ``docs/a12/pattern_consistency.md``）：

1. **栅格周期**：``u`` 用 ``u_k = (k + 0.5) / W``（周期 ``[0,1)``，不含端点 1），
   所以"回绕列差"就是普通相邻列差；接缝在 PNG 路径上闭合（``u=0`` 与 ``u=1`` 的
   1000 对采样完全一致），``evaluate`` 场本身的接缝色差 ≤ 1e-5；
2. **三维与二维一致**：对 ≥200 个母体表面顶点，比较"顶点在 GLB 贴图上的颜色"与
   "把同一 ``(u, s)`` 在卡片 albedo PNG 上双线性采样的颜色"，8-bit 最大误差 ≤ 2/255；
3. **provenance**：族名 / recipe hash / PNG 文件名 / 贴图 GLB 四者在清单、资产 meta 与
   GLB 字节里必须逐项一致（贴图**就是**那张 PNG，像素逐点相同）。

测试只读 ``data/a12_demo``（生成器输出）与仓库真实模块，不 mock 任何东西。
"""

from __future__ import annotations

import hashlib
import io
import json
import struct
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[3]
TOOLS = REPO_ROOT / "tools"
for path in (str(REPO_ROOT), str(TOOLS)):
    if path not in sys.path:
        sys.path.insert(0, path)

import build_demo_assets as gen  # noqa: E402  (需要上面的 sys.path)

from synlab.api import display  # noqa: E402
from synlab.mothers.api import load_mother  # noqa: E402
from synlab.patterns.api import evaluate, load_pattern  # noqa: E402
from synlab.patterns.charts import resolve_frame, to_chart_mm  # noqa: E402
from synlab.storage.store import AssetStore  # noqa: E402

DEMO_ROOT = REPO_ROOT / "data" / "a12_demo"
MANIFEST_PATH = DEMO_ROOT / gen.MANIFEST_NAME
STORE_ROOT = DEMO_ROOT / gen.STORE_DIRNAME

pytestmark = pytest.mark.skipif(
    not MANIFEST_PATH.is_file(), reason="仓库里还没有 data/a12_demo/demo_manifest.json")

#: 8-bit 显示编码下允许的最大颜色误差（题目硬指标）。
MAX_COLOR_ERROR_U8 = 2
#: 接缝允许的最大线性色差（与 synlab/patterns/audit.py 的容差一致）。
MAX_SEAM_COLOR_ERROR = 1e-5
SEAM_PAIRS = 1000


# ---------------------------------------------------------------------------------------
# 读取真实产物的小工具
# ---------------------------------------------------------------------------------------
def _manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _store() -> AssetStore:
    return AssetStore(STORE_ROOT)


def _pattern_entries() -> list[dict]:
    entries = [e for e in _manifest()["entries"] if e.get("kind") == "pattern"]
    assert entries, "清单里没有 kind=pattern 的条目"
    return sorted(entries, key=lambda e: e["family_id"])


def _asset_file(store: AssetStore, asset_id: str, key: str) -> Path:
    record = store.get_asset(asset_id)
    return store.root / Path(*record.files[key].split("/"))


def _png(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        return np.asarray(image.convert("RGBA"), dtype=np.uint8)


def _glb_parts(path: Path) -> tuple[dict, bytes]:
    raw = path.read_bytes()
    magic, _version, length = struct.unpack_from("<III", raw, 0)
    assert magic == 0x46546C67, f"{path} 不是 GLB"
    offset, doc, blob = 12, None, b""
    while offset < length:
        chunk_len, chunk_type = struct.unpack_from("<II", raw, offset)
        payload = raw[offset + 8: offset + 8 + chunk_len]
        if chunk_type == 0x4E4F534A:
            doc = json.loads(payload.decode("utf-8"))
        elif chunk_type == 0x004E4942:
            blob = payload
        offset += 8 + chunk_len
    assert doc is not None, f"{path} 没有 GLB JSON chunk"
    return doc, blob


_COMPONENT = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16,
              5125: np.uint32, 5126: np.float32}
_ITEMS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}


def _accessor(doc: dict, blob: bytes, index: int) -> np.ndarray:
    acc = doc["accessors"][index]
    view = doc["bufferViews"][acc["bufferView"]]
    dtype = np.dtype(_COMPONENT[acc["componentType"]])
    items = _ITEMS[acc["type"]]
    start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
    count = acc["count"]
    stride = view.get("byteStride")
    if stride and stride != dtype.itemsize * items:
        out = np.empty((count, items), dtype=dtype)
        for row in range(count):
            offset = start + row * stride
            out[row] = np.frombuffer(blob, dtype=dtype, count=items, offset=offset)
    else:
        out = np.frombuffer(blob, dtype=dtype, count=count * items, offset=start)
        out = out.reshape(count, items)
    if acc.get("normalized") and dtype.kind in "iu":
        info = np.iinfo(dtype)
        out = out.astype(np.float64) / float(max(abs(info.min), info.max))
    return out.copy()


def _bilinear(image: np.ndarray, u_texel: np.ndarray, v_texel: np.ndarray) -> np.ndarray:
    """双线性采样：x 方向按周期回绕（REPEAT），y 方向 clamp。

    约定与 GLSL 一致：``u_texel``/``v_texel`` 是"贴图坐标 × 图像尺寸"，即 texel ``(k, j)``
    的中心在 ``(k + 0.5, j + 0.5)``。因此：
    * GLB 贴图：直接传 ``(uv.u * W, uv.v * H)``（glTF 的 TEXCOORD_0 就是这个约定）；
    * 卡片 PNG：列中心是 ``u_k = (k + 0.5) / W``（传 ``u * W``），而行 ``j`` 的中心是
      ``s_j = s_lo + j * ds``（传 ``(s - s_lo) / ds + 0.5``）。
    """
    height, width = image.shape[0], image.shape[1]
    x = np.asarray(u_texel, dtype=np.float64) - 0.5
    y = np.clip(np.asarray(v_texel, dtype=np.float64) - 0.5, 0.0, height - 1.0)
    x0 = np.floor(x).astype(np.int64)
    y0 = np.floor(y).astype(np.int64)
    fx = (x - x0)[:, None]
    fy = (y - y0)[:, None]
    x0m = np.mod(x0, width)
    x1m = np.mod(x0 + 1, width)
    y0c = np.clip(y0, 0, height - 1)
    y1c = np.clip(y0 + 1, 0, height - 1)
    img = image.astype(np.float64)
    c00 = img[y0c, x0m]
    c10 = img[y0c, x1m]
    c01 = img[y1c, x0m]
    c11 = img[y1c, x1m]
    top = c00 * (1.0 - fx) + c10 * fx
    bottom = c01 * (1.0 - fx) + c11 * fx
    return top * (1.0 - fy) + bottom * fy


def _family_context(entry: dict) -> dict:
    """加载该族绑定的母体 / recipe / 图卡 / 栅格几何（与生成器同一条真实代码路径）。"""
    store = _store()
    manifest = _manifest()
    by_id = {e["entry_id"]: e for e in manifest["entries"]}
    mother = load_mother(store, by_id[entry["mother_entry"]]["asset_id"])
    recipe = load_pattern(store, entry["asset_id"])
    frame = resolve_frame(mother, str((recipe.meta.get("chart") or {}).get("surface_tag")
                                      or "outer_wall"))
    metrics = entry["metrics"]
    raster = metrics["raster"]
    plan = {
        "width": int(raster["width"]), "height": int(raster["height"]),
        "x_lo": 0.0 if raster["x_periodic"] else None,
        "x_span": float(raster["x_period_mm"]) if raster["x_periodic"] else None,
        "x_period_mm": (float(raster["x_period_mm"]) if raster["x_periodic"] else None),
        "x_periodic": bool(raster["x_periodic"]),
        "s_lo": float(raster["s_range_mm"][0]), "s_hi": float(raster["s_range_mm"][1]),
        "ds": (float(raster["s_range_mm"][1]) - float(raster["s_range_mm"][0]))
              / float(int(raster["height"]) - 1),
    }
    return {"store": store, "mother": mother, "recipe": recipe, "frame": frame,
            "metrics": metrics, "plan": plan, "entry": entry}


# ---------------------------------------------------------------------------------------
# 1) 栅格周期与连续性
# ---------------------------------------------------------------------------------------
def test_pattern_raster_grid_is_periodic_and_hole_free() -> None:
    """网格必须是周期采样：回绕列差与相邻列差同阶，且没有空洞像素。"""
    report: list[str] = []
    for entry in _pattern_entries():
        ctx = _family_context(entry)
        channels = entry["artifacts"]["channels"]
        albedo = _png(_asset_file(ctx["store"], channels["asset_id"], "albedo_png"))
        assert albedo.shape[1] == ctx["plan"]["width"]
        assert albedo.shape[0] == ctx["plan"]["height"]
        assert channels["keys"] == {"albedo": "albedo_png", "roughness": "roughness_png",
                                    "height_mm": "height_png"}

        rgb = albedo[:, :, :3]
        black = np.all(rgb <= 1, axis=2)
        assert not bool(np.any(black)), (
            f"{entry['entry_id']} 的 albedo PNG 有 {int(black.sum())} 个空洞像素"
            "（旧实现用随机采样分箱，未覆盖 bin 是黑的）")

        cols = rgb.astype(np.float64).mean(axis=(0, 2))
        adjacent = np.abs(np.diff(cols))
        wrap = float(abs(cols[0] - cols[-1]))
        assert adjacent.size > 10
        # "同阶"：回绕差必须落在相邻差的分布里（不能是整幅图的反差）
        assert wrap <= float(adjacent.max()) + 1e-9, (
            f"{entry['entry_id']} 回绕列差 {wrap:.4f} 超过最大相邻列差 "
            f"{float(adjacent.max()):.4f}：x 方向不是周期采样")
        assert wrap <= 3.0 * float(np.percentile(adjacent, 95)) + 1e-9

        # 与清单里记录的实测连续性一致（生成时算的就是这一个量）
        recorded = ctx["metrics"]["raster"]["continuity"]["albedo_linear"]
        assert recorded["column_wrap_abs"] <= max(recorded["column_adjacent_max_abs"], 1e-12)

        # 逆映射必须是精确的（图卡 (x,s) ↔ 母体毫米坐标）
        roundtrip = ctx["metrics"]["raster"]["inverse_roundtrip_mm"]
        assert roundtrip["x_max_mm"] < 1e-6, roundtrip
        assert roundtrip["s_max_mm"] < 1e-6, roundtrip
        report.append(
            f"{entry['family_id']}: {ctx['plan']['width']}x{ctx['plan']['height']} "
            f"wrap={wrap:.4f} adj_max={float(adjacent.max()):.4f} "
            f"adj_p95={float(np.percentile(adjacent, 95)):.4f}")
    print("\n".join(report))


# ---------------------------------------------------------------------------------------
# 2) 接缝：PNG 路径与 GLB 路径都必须闭合
# ---------------------------------------------------------------------------------------
def test_seam_is_closed_in_field_png_and_glb_path() -> None:
    """``u=0`` 与 ``u=1`` 的 1000 对点：场本身 ≤1e-5，PNG/GLB 采样路径完全一致。"""
    rng = np.random.default_rng(20261002)
    for entry in _pattern_entries():
        ctx = _family_context(entry)
        plan = ctx["plan"]
        if not plan["x_periodic"]:
            pytest.skip("该族图卡不是周期图卡，接缝检查不适用")
        period = plan["x_period_mm"]
        height = plan["height"]

        # (a) 场本身：同一 chart 上 u=0 与 u=1 的随机点对
        s_values = rng.uniform(plan["s_lo"], plan["s_hi"], size=SEAM_PAIRS)
        inverse, _kind = gen._chart_inverse(ctx["frame"])
        left = inverse(np.zeros(SEAM_PAIRS), s_values)
        right = inverse(np.full(SEAM_PAIRS, period), s_values)
        channels_left = evaluate(ctx["recipe"], ctx["mother"], left, int(ctx["frame"].tag))
        channels_right = evaluate(ctx["recipe"], ctx["mother"], right, int(ctx["frame"].tag))
        field_error = float(np.abs(np.asarray(channels_left.albedo, dtype=np.float64)
                                   - np.asarray(channels_right.albedo, dtype=np.float64)).max())
        assert field_error <= MAX_SEAM_COLOR_ERROR, (
            f"{entry['entry_id']} 场接缝线性色差 {field_error:.3e} > {MAX_SEAM_COLOR_ERROR}")

        # (b) PNG ＋ GLB 采样路径：同一张图在 u=0 与 u=1 处必须取到同一列
        albedo = _png(_asset_file(ctx["store"], entry["artifacts"]["channels"]["asset_id"],
                                  "albedo_png"))
        rows = (s_values - plan["s_lo"]) / plan["ds"] + 0.5
        left_px = _bilinear(albedo, np.zeros(SEAM_PAIRS), rows)
        right_px = _bilinear(albedo, np.full(SEAM_PAIRS, float(plan["width"])), rows)
        path_error = float(np.abs(left_px - right_px).max())
        assert path_error == 0.0, (
            f"{entry['entry_id']} 的 PNG/GLB 采样路径在接缝处不一致：{path_error}")
        # (c) GLB 里写下的 v 也必须严格落在 texel 中心范围内（REPEAT/CLAMP 无差异）
        bake = ctx["metrics"]["texture_bake"]
        v_lo, v_hi = bake["uv_v_range_gltf"]
        assert v_lo >= 0.5 / height - 1e-9 and v_hi <= 1.0 - 0.5 / height + 1e-9


# ---------------------------------------------------------------------------------------
# 3) 三维与二维一致（≥200 个母体表面顶点）
# ---------------------------------------------------------------------------------------
def _glb_textured_primitive(ctx: dict) -> dict:
    store = ctx["store"]
    glb_asset = ctx["entry"]["artifacts"]["pattern_glb"]["asset_id"]
    doc, blob = _glb_parts(_asset_file(store, glb_asset, "glb"))
    textured = None
    for mesh in doc["meshes"]:
        for prim in mesh["primitives"]:
            if "TEXCOORD_0" in (prim.get("attributes") or {}):
                textured = prim
    assert textured is not None, f"{glb_asset} 里没有任何带 TEXCOORD_0 的 primitive"
    assert "NORMAL" in textured["attributes"], "展示 GLB 必须带法线（否则会是逐面平色）"
    texture_index = doc["materials"][textured["material"]]["pbrMetallicRoughness"][
        "baseColorTexture"]["index"]
    image_index = doc["textures"][texture_index]["source"]
    view = doc["bufferViews"][doc["images"][image_index]["bufferView"]]
    start = view.get("byteOffset", 0)
    embedded = np.asarray(Image.open(io.BytesIO(
        blob[start:start + view["byteLength"]])).convert("RGBA"), dtype=np.uint8)
    return {
        "doc": doc, "blob": blob, "primitive": textured, "texture": embedded,
        "position": _accessor(doc, blob, textured["attributes"]["POSITION"]),
        "uv": _accessor(doc, blob, textured["attributes"]["TEXCOORD_0"]),
        "material": doc["materials"][textured["material"]],
    }


@pytest.mark.parametrize("family_index", range(len(_pattern_entries())))
def test_vertex_colour_matches_the_card_png(family_index: int) -> None:
    """器物顶点在 GLB 贴图上的颜色 vs 按同一 (u,s) 在卡片 PNG 上的双线性颜色。"""
    entry = _pattern_entries()[family_index]
    ctx = _family_context(entry)
    plan = ctx["plan"]
    primitive = _glb_textured_primitive(ctx)

    channels = entry["artifacts"]["channels"]
    card = _png(_asset_file(ctx["store"], channels["asset_id"], "albedo_png"))
    assert primitive["texture"].shape == card.shape, "GLB 内嵌贴图与卡片 PNG 尺寸不一致"
    pixel_diff = int(np.abs(primitive["texture"].astype(int) - card.astype(int)).max())
    assert pixel_diff == 0, (
        f"{entry['entry_id']} 的 GLB 贴图与卡片 albedo PNG 不是同一份像素（最大差 {pixel_diff}）")

    # 顶点位置：GLB 是米/Y-up，先回到权威毫米/Z-up，再取图卡坐标
    points_mm = display.display_to_authority(np.asarray(primitive["position"], dtype=np.float64))
    x_mm, s_mm = to_chart_mm(ctx["frame"], points_mm)
    if plan["x_periodic"]:
        u_expected = np.mod(x_mm, plan["x_period_mm"]) / plan["x_period_mm"]
    else:
        u_expected = (x_mm - x_mm.min()) / max(float(x_mm.max() - x_mm.min()), 1e-9)
    row_expected = (s_mm - plan["s_lo"]) / plan["ds"]
    v_expected = (np.clip(row_expected, 0.0, float(plan["height"] - 1)) + 0.5) / plan["height"]

    n = int(primitive["uv"].shape[0])
    assert n >= 200, (
        f"{entry['entry_id']} 的贴图 primitive 只有 {n} 个顶点，少于硬指标要求的 200 个")

    # UV ↔ 图卡坐标的映射（u 取模一周，v 是 texel 中心对齐）。
    # GLB 的 TEXCOORD_0 是 float32，容差取 1e-6（一个 texel 是 1/H ≈ 1e-2 量级）
    uv_tolerance = 1e-6
    du = np.abs(np.mod(primitive["uv"][:, 0] - u_expected + 0.5, 1.0) - 0.5)
    dv = np.abs(primitive["uv"][:, 1] - v_expected)
    assert float(du.max()) < uv_tolerance, f"UV.u 与图卡 u 不一致：max {float(du.max()):.3e}"
    assert float(dv.max()) < uv_tolerance, f"UV.v 与图卡 s 不一致：max {float(dv.max()):.3e}"

    # 颜色：GLB 贴图按 GLB 自带的 uv 采样 vs 卡片 PNG 按图卡 (u,s) 采样
    from_glb = np.rint(_bilinear(primitive["texture"],
                                 primitive["uv"][:, 0] * plan["width"],
                                 primitive["uv"][:, 1] * plan["height"]))
    from_png = np.rint(_bilinear(card, u_expected * plan["width"], row_expected + 0.5))
    diff = np.abs(from_glb - from_png).max(axis=1)
    p50, p90, p99 = (float(np.percentile(diff, q)) for q in (50, 90, 99))
    worst = float(diff.max())
    print(f"{entry['family_id']}: n_vertices={n} max={worst:.1f}/255 p99={p99:.1f} "
          f"p90={p90:.1f} p50={p50:.1f}")
    assert worst <= MAX_COLOR_ERROR_U8, (
        f"{entry['entry_id']} 顶点烘焙颜色与卡片 PNG 的最大 8-bit 误差 {worst:.1f}/255 "
        f"> {MAX_COLOR_ERROR_U8}/255")

    # 展示材质不能是 glTF 默认的金属材质（metalness=1 无环境贴图时会渲染成黑）
    material = primitive["material"]["pbrMetallicRoughness"]
    assert float(material.get("metallicFactor", 1.0)) == 0.0, (
        "展示 GLB 的贴图材质必须是非金属，否则浏览器里会渲染成一团黑")


# ---------------------------------------------------------------------------------------
# 4) provenance：族名 / recipe hash / PNG 文件名 / 贴图 GLB 四者一致
# ---------------------------------------------------------------------------------------
def test_provenance_family_recipe_png_glb_are_consistent() -> None:
    for entry in _pattern_entries():
        ctx = _family_context(entry)
        store = ctx["store"]
        metrics = entry["metrics"]
        provenance = metrics.get("provenance")
        assert provenance, f"{entry['entry_id']} 缺少 metrics.provenance"
        family = entry["family_id"]
        assert provenance["family_id"] == family == metrics["family_id"]

        channels = entry["artifacts"]["channels"]
        channels_record = store.get_asset(channels["asset_id"])
        glb_asset = entry["artifacts"]["pattern_glb"]["asset_id"]
        glb_record = store.get_asset(glb_asset)

        # recipe hash：清单 / recipe 资产 / PNG 资产 meta / GLB 资产 meta 四处一致
        recipe_hash = metrics["recipe_hash"]
        assert provenance["recipe_hash"] == recipe_hash
        assert store.get_asset(entry["asset_id"]).meta["recipe_hash"] == recipe_hash
        assert channels_record.meta["recipe_hash"] == recipe_hash
        assert glb_record.meta["recipe_hash"] == recipe_hash
        assert ctx["recipe"].meta["recipe_hash"] == recipe_hash

        # PNG 文件名：artifact keys 与资产 payload 文件名逐项一致，且 albedo 哈希可核对
        assert channels["keys"]["albedo"] == "albedo_png"
        albedo_path = _asset_file(store, channels["asset_id"], "albedo_png")
        digest = "sha256:" + hashlib.sha256(albedo_path.read_bytes()).hexdigest()
        assert metrics["texture_bake"]["texture_sha256"] == digest
        assert provenance["albedo_png_sha256"] == digest
        assert glb_record.meta["uv"]["texture_sha256"] == digest
        assert glb_record.meta["raster_asset"] == channels["asset_id"]
        assert provenance["raster_asset"] == channels["asset_id"]
        assert entry["artifacts"]["pattern_glb"]["raster_asset"] == channels["asset_id"]

        # 贴图 GLB 的工艺信息完整，且血缘指向同一个母体
        uv_meta = glb_record.meta["uv"]
        assert uv_meta["mode"] == "chart_texture"
        assert uv_meta["wall_faces"] > 0 and uv_meta["body_faces"] > 0
        assert glb_record.meta["family_id"] == family
        assert glb_record.meta["mother_entry"] == entry["mother_entry"]
        assert glb_record.meta["source_asset"] == metrics["mother_asset"]

        # 内嵌贴图就是那张 PNG 的像素（尺寸与内容，不是"看起来差不多"）
        primitive = _glb_textured_primitive(ctx)
        assert int(np.abs(primitive["texture"].astype(int)
                          - _png(albedo_path).astype(int)).max()) == 0
