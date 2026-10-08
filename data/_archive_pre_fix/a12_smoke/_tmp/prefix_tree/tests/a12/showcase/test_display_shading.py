"""展示 GLB 的**显示着色**真实测试：平滑法线 / 断面分色 / 显示↔权威边界。

覆盖（全部对着真实生成器的产出，不做任何模拟）：

* 母体展示 GLB 的每个 primitive 都带 ``NORMAL``，长度为单位向量，且与**权威网格**
  用同一套规则（面积加权 + 角度阈值 + 保持绕向）复算出来的法线一致；
* 碎裂展示 GLB 的断面分组**来自权威面属性** ``origin_kind`` / ``interface_id``：
  每个 primitive 的三角面集合与权威分组逐字节一致，分组之外的几何没有被改动；
* 展示 GLB 不带简化层级（场景里只有一个 L0 类节点），保证“没有声称几何更精细”。

关键点：本文件里的 GLB 解析与几何比较都是**自己写的**（struct + json + numpy 字节比较），
不复用 ``tools/build_demo_assets.py`` 的解析/校验函数，避免“用被测量的代码去验证它自己”。
"""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
TOOLS = REPO_ROOT / "tools"
for path in (str(REPO_ROOT), str(TOOLS)):
    if path not in sys.path:
        sys.path.insert(0, path)

import build_demo_assets as gen  # noqa: E402

VESSEL = "V01"
BACKEND = "plane_shared_cut"

_COMPONENT_DTYPES = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16,
                     5125: np.uint32, 5126: np.float32}
_TYPE_WIDTHS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}


# ---------------------------------------------------------------------------- 独立 GLB 解析
def read_glb(path: Path) -> dict:
    """把 GLB 拆成 ``{"json": ..., "primitives": [...]}``（独立实现，不用被测代码）。"""
    data = path.read_bytes()
    magic, _version, length = struct.unpack_from("<III", data, 0)
    assert magic == 0x46546C67, f"{path} 不是 GLB"
    offset, tree, binary = 12, None, b""
    while offset < min(length, len(data)):
        chunk_len, chunk_type = struct.unpack_from("<II", data, offset)
        offset += 8
        chunk = data[offset:offset + chunk_len]
        offset += chunk_len
        if chunk_type == 0x4E4F534A:
            tree = json.loads(chunk.decode("utf-8"))
        elif chunk_type == 0x004E4942:
            binary = chunk
    assert tree is not None, f"{path} 没有 JSON chunk"

    def accessor(index: int) -> np.ndarray:
        spec = tree["accessors"][index]
        dtype = np.dtype(_COMPONENT_DTYPES[spec["componentType"]])
        width = _TYPE_WIDTHS[spec["type"]]
        view = tree["bufferViews"][spec["bufferView"]]
        base = int(view.get("byteOffset", 0)) + int(spec.get("byteOffset", 0))
        count = int(spec["count"])
        stride = int(view.get("byteStride") or dtype.itemsize * width)
        if stride == dtype.itemsize * width:
            flat = np.frombuffer(binary, dtype=dtype, count=count * width, offset=base)
        else:
            flat = np.concatenate([
                np.frombuffer(binary, dtype=dtype, count=width, offset=base + i * stride)
                for i in range(count)])
        return flat.reshape(count, width) if width > 1 else flat

    primitives = []
    for node in tree.get("nodes", []):
        if "mesh" not in node:
            continue
        for primitive in tree["meshes"][node["mesh"]].get("primitives", []):
            material_index = primitive.get("material")
            attributes = primitive.get("attributes", {})
            primitives.append({
                "node": str(node.get("name")),
                "material": (tree["materials"][material_index].get("name")
                             if material_index is not None else None),
                "attributes": sorted(attributes),
                "positions": accessor(attributes["POSITION"]).astype(np.float64),
                "positions_f32": accessor(attributes["POSITION"]),
                "normals": (accessor(attributes["NORMAL"]).astype(np.float64)
                            if "NORMAL" in attributes else None),
                "indices": (accessor(primitive["indices"]).astype(np.int64).reshape(-1, 3)
                            if "indices" in primitive else None),
            })
    return {"json": tree, "primitives": primitives}


# ---------------------------------------------------------------------------- 几何比较工具
def position_key_multiset(positions: np.ndarray) -> list[bytes]:
    """顶点位置的**多重集**（float32 字节，逐位比较；重复顶点也保留重复计数）。"""
    return sorted(np.ascontiguousarray(np.asarray(positions, dtype=np.float32)).reshape(
        len(positions), -1).view(np.dtype((np.void, 12))).reshape(-1).tolist())


def triangle_key_set(positions: np.ndarray, faces: np.ndarray) -> set[bytes]:
    """三角面的**集合**（每个面 9 个 float32 的字节，与顶点编号无关 → 对重排免疫）。"""
    tri = np.asarray(positions, dtype=np.float32)[np.asarray(faces, dtype=np.int64)]
    flat = np.ascontiguousarray(tri.reshape(len(tri), -1))
    return set(flat.view(np.dtype((np.void, flat.shape[1] * 4))).reshape(-1).tolist())


def normals_by_position(positions: np.ndarray, normals: np.ndarray) -> dict[bytes, np.ndarray]:
    """位置（float32 字节）→ 该位置上的所有法线（允许同一位置有多个分裂顶点）。"""
    out: dict[bytes, list[np.ndarray]] = {}
    keys = np.ascontiguousarray(np.asarray(positions, dtype=np.float32)).view(
        np.dtype((np.void, 12))).reshape(-1)
    for key, normal in zip(keys.tolist(), np.asarray(normals, dtype=np.float64)):
        out.setdefault(key, []).append(normal)
    return {key: np.asarray(rows) for key, rows in out.items()}


def min_angle_deg(normal: np.ndarray, candidates: np.ndarray) -> float:
    cosines = np.clip(candidates @ normal, -1.0, 1.0)
    return float(np.degrees(np.arccos(cosines.max())))


def area_mm2(positions: np.ndarray, faces: np.ndarray) -> float:
    tri = np.asarray(positions, dtype=np.float64)[np.asarray(faces, dtype=np.int64)]
    return float(0.5 * np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0],
                                               tri[:, 2] - tri[:, 0]), axis=1).sum()) * 1e6


# ---------------------------------------------------------------------------- fixtures
@pytest.fixture(scope="module")
def demo(tmp_path_factory: pytest.TempPathFactory) -> dict:
    """真实跑一遍母体 + 一个真实碎裂事件（inline，便于直接拿到权威对象做对照）。"""
    root = tmp_path_factory.mktemp("showcase_shading")
    assert gen.main(["--only", "mothers", "--limit", "1", "--inline",
                     "--demo-root", str(root)]) == 0
    assert gen.main(["--only", "fracture", "--limit", "1", "--inline",
                     "--demo-root", str(root)]) in (0, 1)

    from synlab.fracture.api import FractureSpec, fracture_event
    from synlab.mothers.api import load_mother
    from synlab.seeds import make_rng
    from synlab.storage.store import AssetStore

    manifest = json.loads((root / gen.MANIFEST_NAME).read_text(encoding="utf-8"))
    entries = {entry["entry_id"]: entry for entry in manifest["entries"]}
    mother_entry = entries[f"mother:{VESSEL}"]
    fracture_entry = entries[f"fracture:{VESSEL}:{BACKEND}"]
    store = AssetStore(root / gen.STORE_DIRNAME)

    mother = load_mother(store, mother_entry["asset_id"])
    rng = make_rng(gen.MASTER_SEED, gen.LINEAGE_ID, "fracture", VESSEL, BACKEND)
    result = fracture_event(mother, FractureSpec(backend=BACKEND), rng,
                            event_id=f"{gen.LINEAGE_ID}_{VESSEL}_{BACKEND}")
    return {"root": root, "manifest": manifest, "entries": entries, "store": store,
            "mother": mother, "fracture": result, "store_dir": root / gen.STORE_DIRNAME}


def glb_path(demo: dict, asset_id: str) -> Path:
    return demo["store_dir"] / "assets" / asset_id / "glb.bin"


def fragment_records(entry: dict) -> list[dict]:
    return list((entry.get("metrics") or {}).get("fragments") or [])


# ---------------------------------------------------------------------------- 母体法线
def test_mother_display_glb_has_authority_normals(demo: dict) -> None:
    from synlab.api import display

    entry = demo["entries"][f"mother:{VESSEL}"]
    asset_id = entry["artifacts"]["glb"]["metrics"]["glb_asset_id"]
    glb = read_glb(glb_path(demo, asset_id))
    assert glb["primitives"], "母体展示 GLB 里没有任何 primitive"

    mesh = demo["mother"].mesh
    positions_display = display.transform_vertices(np.asarray(mesh.vertices, dtype=np.float64))
    faces = np.asarray(mesh.faces, dtype=np.int64)
    for primitive in glb["primitives"]:
        assert "NORMAL" in primitive["attributes"], \
            f"{primitive['node']} 缺 NORMAL（three.js GLTFLoader 会设 flatShading）"
        assert primitive["normals"].shape == primitive["positions"].shape
        lengths = np.linalg.norm(primitive["normals"], axis=1)
        assert np.all(np.isfinite(lengths)) and np.abs(lengths - 1.0).max() < 1e-5
        # 几何：位置多重集与权威**逐位**一致（float32 字节），三角面集合也逐位一致
        assert position_key_multiset(primitive["positions"]) == \
            position_key_multiset(positions_display)
        assert triangle_key_set(primitive["positions"], primitive["indices"]) == \
            triangle_key_set(positions_display, faces)

        # 法线：与权威网格按同一规则复算、再旋转到展示坐标系的结果一致
        authority_normals, stats = gen._authority_vertex_normals(
            mesh, angle_threshold_deg=gen.DISPLAY_NORMAL_ANGLE_DEG)
        assert stats["flipped_vs_trimesh_vertex_normals"] == 0, "法线方向与绕向不一致"
        rotation = np.asarray(display.T_DISPLAY_AUTHORITY, dtype=np.float64)[:3, :3]
        expected = authority_normals @ rotation.T
        expected /= np.where(np.linalg.norm(expected, axis=1, keepdims=True) > 0,
                             np.linalg.norm(expected, axis=1, keepdims=True), 1.0)
        candidates = normals_by_position(positions_display, expected)
        keys = np.ascontiguousarray(primitive["positions_f32"]).view(
            np.dtype((np.void, 12))).reshape(-1)
        angles = [min_angle_deg(normal, candidates[key])
                  for key, normal in zip(keys.tolist(), primitive["normals"])]
        assert max(angles) < 0.05, f"GLB 法线与权威复算值最大夹角 {max(angles)}°"

    metrics = entry["artifacts"]["glb"]["metrics"]
    assert metrics["normals"]["all_primitives_have_normal"] is True
    assert metrics["normals"]["angle_threshold_deg"] == gen.DISPLAY_NORMAL_ANGLE_DEG
    assert metrics["geometry_unchanged"]["winding_matches_authority"] is True
    assert metrics["geometry_unchanged"]["mismatches"] == []
    assert metrics["geometry_unchanged"]["position_max_abs_error_vs_authority_m"] < 1e-6
    assert metrics["scene_nodes"] == ["L0"], "展示场景只应包含一个 L0 节点"
    assert {"L1", "L2"} <= set(metrics["lod_levels"]), "简化的实测值必须照实记录"
    assert metrics["lod_levels"]["L1"]["exported_as_scene_node"] is False
    assert metrics["lod_levels"]["L2"]["exported_as_scene_node"] is False


def test_mother_normals_are_smoothed_not_flat(demo: dict) -> None:
    """平滑真的发生了：不是每个顶点法线都等于某个相邻面的面法线。"""
    entry = demo["entries"][f"mother:{VESSEL}"]
    asset_id = entry["artifacts"]["glb"]["metrics"]["glb_asset_id"]
    primitive = read_glb(glb_path(demo, asset_id))["primitives"][0]
    tri = primitive["positions"][primitive["indices"]]
    raw = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    norm = np.linalg.norm(raw, axis=1, keepdims=True)
    face_normals = raw / np.where(norm > 0, norm, 1.0)
    dots = np.abs(primitive["normals"] @ face_normals.T)
    flat_matches = int((dots > 1 - 1e-6).any(axis=1).sum())
    assert flat_matches < len(primitive["normals"]), \
        "所有顶点法线都等于某个面法线 → 仍然是平色块渲染"


# ---------------------------------------------------------------------------- 断面分色
def test_fracture_surface_groups_come_from_authority_face_attrs(demo: dict) -> None:
    from synlab.api import display
    from synlab.schemas.runtime import ORIGIN_INTERFACE
    from synlab.storage.mesh_io import face_attrs

    entry = demo["entries"][f"fracture:{VESSEL}:{BACKEND}"]
    assert entry["status"] == "OK", entry.get("failure")
    records = fragment_records(entry)
    assert len(records) == len(demo["fracture"].fragments) >= 2

    new_faces_total = 0
    for record, fragment in zip(records, demo["fracture"].fragments):
        mesh = fragment.mesh
        attrs = face_attrs(mesh) or {}
        origin = np.asarray(attrs["origin_kind"], dtype=np.int64)
        interface = np.asarray(attrs["interface_id"], dtype=np.int64)
        area = np.asarray(mesh.area_faces, dtype=np.float64)
        expected_new = (origin == ORIGIN_INTERFACE) | (interface >= 0)
        expected_mother = ~expected_new
        new_faces_total += int(expected_new.sum())

        groups = record["surface_groups"]
        assert set(groups) == {"new_fracture_surface", "original_mother_surface"}, groups
        assert groups["new_fracture_surface"]["faces"] == int(expected_new.sum())
        assert groups["original_mother_surface"]["faces"] == int(expected_mother.sum())
        assert groups["new_fracture_surface"]["area_mm2"] == pytest.approx(
            float(area[expected_new].sum()), rel=1e-12)
        assert groups["original_mother_surface"]["area_mm2"] == pytest.approx(
            float(area[expected_mother].sum()), rel=1e-12)
        assert record["surface_group_source"].startswith("authority face attributes")
        assert record["surface_group_check"]["display_face_counts_match_authority"] is True
        assert record["surface_group_check"]["display_areas_match_authority"] is True

        positions_display = display.transform_vertices(np.asarray(mesh.vertices, dtype=np.float64))
        faces = np.asarray(mesh.faces, dtype=np.int64)
        glb = read_glb(glb_path(demo, record["glb"]["asset_id"]))
        by_material = {primitive["material"]: primitive for primitive in glb["primitives"]}
        assert set(by_material) == {
            gen.DISPLAY_SURFACE_STYLES["new_fracture_surface"]["material"],
            gen.DISPLAY_SURFACE_STYLES["original_mother_surface"]["material"],
        }, sorted(by_material)

        expected_triangles = {
            gen.DISPLAY_SURFACE_STYLES["new_fracture_surface"]["material"]:
                triangle_key_set(positions_display, faces[expected_new]),
            gen.DISPLAY_SURFACE_STYLES["original_mother_surface"]["material"]:
                triangle_key_set(positions_display, faces[expected_mother]),
        }
        for material, primitive in by_material.items():
            assert "NORMAL" in primitive["attributes"], primitive["node"]
            assert np.abs(np.linalg.norm(primitive["normals"], axis=1) - 1.0).max() < 1e-5
            # 关键断言：这个 primitive 真的就是权威面属性分出来的那一组面（逐字节）
            assert triangle_key_set(primitive["positions"], primitive["indices"]) == \
                expected_triangles[material], material
            assert len(primitive["indices"]) == groups[
                "new_fracture_surface" if material.endswith("new_fracture_surface")
                else "original_mother_surface"]["faces"]

        # 整块几何（两个 primitive 合起来）与权威逐位一致
        all_faces = np.concatenate([primitive["indices"] for primitive in glb["primitives"]])
        all_positions = np.concatenate([primitive["positions"] for primitive in glb["primitives"]])
        assert len(all_faces) == len(faces)
        assert area_mm2(all_positions, all_faces) == pytest.approx(float(area.sum()), rel=1e-6)

        check = record["display_geometry_check"]
        assert check["triangles_in_glb"] == check["authority_faces"] == len(faces)
        assert check["winding_matches_authority"] is True
        assert check["mismatches"] == []
        assert check["position_max_abs_error_vs_authority_m"] < 1e-6
    assert new_faces_total > 0, "这次真实断裂必须真的产生新断面面"


def test_fracture_split_is_display_only(demo: dict) -> None:
    """分组只改材质与分组：面数守恒、没有多余/缺失的面，权威面属性是唯一依据。"""
    entry = demo["entries"][f"fracture:{VESSEL}:{BACKEND}"]
    for record in fragment_records(entry):
        groups = record["surface_groups"]
        assert sum(row["faces"] for row in groups.values()) == record["faces"]
        assert record["display_geometry_check"]["authority_faces"] == record["faces"]
        assert record["glb"]["metrics"]["triangles"] == record["faces"]
        assert record["glb"]["metrics"]["surface_group_source"].startswith(
            "authority face attributes")
        assert record["glb"]["metrics"]["normals"]["all_primitives_have_normal"] is True
        assert record["glb"]["metrics"]["scene_nodes"] == [
            "original_mother_surface", "new_fracture_surface"]
