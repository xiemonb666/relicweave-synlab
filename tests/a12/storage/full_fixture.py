"""A tiny *real* store used by the ``export_full`` tests.

The store is written through :meth:`synlab.storage.store.AssetStore.commit_asset`, the same
writer production uses, so the tests exercise the exporter on real store bytes instead of on
hand-built dictionaries.  The payloads are deliberately small (8x8 observations, 2 triangles)
and their *content* is a fixture: what is asserted is the exporter's bookkeeping, never a
claim about the production library.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
for path in (str(REPO_ROOT),):
    if path not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

from synlab.storage.store import QA_PASS, QA_PENDING, AssetStore  # noqa: E402

FRAGMENT_A = "LIN9000_V01_M01_PAT01_E01-m"
FRAGMENT_B = "LIN9000_V01_M01_PAT01_E01-p"
MOTHER = "LIN9000_V01_M01_PAT01"
EVENT = "LIN9000_V01_M01_PAT01_E01"
OBSERVATION = "obs_fixture000000000000"


def _mesh(n_vertices: int = 5, n_faces: int = 3) -> dict[str, np.ndarray]:
    vertices = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0],
                         [0.0, 0.0, 1.0], [1.0, 1.0, 1.0]], dtype=np.float64)[:n_vertices]
    faces = np.array([[0, 1, 2], [0, 1, 3], [1, 3, 4]], dtype=np.int32)[:n_faces]
    return {"vertices": vertices, "faces": faces}


def build_store(root: Path) -> dict[str, Any]:
    """Commit a small but structurally complete set of assets; return the committed ids."""
    store = AssetStore(root)
    ids: dict[str, Any] = {}

    mother = _mesh(5, 3)
    ids["mother_mesh"] = store.commit_asset(
        role="mother_mesh", schema="synlab.mother.v1", unit="mm", frame="W_mm",
        payload={
            "mesh.vertices": mother["vertices"], "mesh.faces": mother["faces"],
            "mesh.face__surface_tag": np.array([0, 1, 2], dtype=np.int32),
            "mesh.face__component_id": np.array([0, 0, 0], dtype=np.int32),
        },
        meta={"mother_id": MOTHER, "vessel_id": "V01"}, qa_status=QA_PASS,
        lineage_id=MOTHER, split="train",
    ).asset_id

    fragment_ids: list[str] = []
    for index, fragment in enumerate((FRAGMENT_A, FRAGMENT_B)):
        mesh = _mesh(5, 3)
        origin = np.array([0, 1, 1], dtype=np.uint8) if index == 0 else np.array([0, 0, 0],
                                                                                dtype=np.uint8)
        fragment_ids.append(store.commit_asset(
            role="fragment_mesh", schema="synlab.fragment.v1", unit="mm", frame="W_mm",
            payload={
                "mesh.vertices": mesh["vertices"], "mesh.faces": mesh["faces"],
                "mesh.face__origin_kind": origin,
                "mesh.face__interface_id": np.array([-1, 0, 0], dtype=np.int32),
                "mesh.face__side": np.array([-1, 1, 1], dtype=np.int8),
                "mesh.face__ambiguous": np.zeros(3, dtype=np.uint8),
            },
            meta={"fragment_id": fragment, "event_id": EVENT, "area_mm2": 12.5},
            qa_status=QA_PASS, ancestry=[mother], lineage_id=MOTHER, split="train",
        ).asset_id)
    ids["fragment_meshes"] = fragment_ids

    height, width = 8, 8
    rng = np.random.default_rng(7)
    tags = np.full((height, width), -1, dtype=np.int16)
    tags[2:5, 2:5] = 0
    tags[2, 2] = 2                                  # one real rim pixel in the fixture
    payload: dict[str, Any] = {
        "v000.rgb": rng.integers(0, 256, size=(height, width, 3), dtype=np.uint8),
        "v000.rgb_linear": rng.random((height, width, 3), dtype=np.float32),
        "v000.depth_z": np.full((height, width), 42.0, dtype=np.float32),
        "v000.id_map": np.where(tags >= 0, 3, -1).astype(np.int32),
        "v000.surface_tag": tags,
        "v000.deployment_mask": tags >= 0,
        "v000.roi": np.zeros((height, width), dtype=bool),
        "v000.uncertain_mask": np.zeros((height, width), dtype=bool),
        "v000.K": np.eye(3, dtype=np.float64),
        "v000.T_WC": np.eye(4, dtype=np.float64),
        "v000.dist": np.zeros(5, dtype=np.float64),
        "points": rng.random((6, 3), dtype=np.float32),
        "normals": np.tile(np.array([[0.0, 0.0, 1.0]], dtype=np.float32), (6, 1)),
        "point_valid": np.ones(6, dtype=bool),
        "normal_valid": np.ones(6, dtype=bool),
    }
    ids["obs_result"] = store.commit_asset(
        role="obs_result", schema="synlab.obs.v1", unit="mm", frame="S_mm", payload=payload,
        meta={"fragment_id": FRAGMENT_A, "mother_id": MOTHER, "observation_id": OBSERVATION,
              "route": "proxy_scan", "n_points": 6},
        qa_status=QA_PASS, ancestry=[fragment_ids[0]], lineage_id=MOTHER, split="train",
    ).asset_id

    ids["clean_truth"] = store.commit_asset(
        role="clean_truth", schema="synlab.truth.clean.v1", unit="mm", frame="W_mm",
        payload={
            "iface_id": np.array([0, 1], dtype=np.int64),
            "iface_area_mm2": np.array([10.5, 2.0], dtype=np.float64),
            "iface_offset": np.array([0, 2, 4], dtype=np.int64),
            "corr_point_a": rng.random((4, 3), dtype=np.float64),
            "corr_point_b": rng.random((4, 3), dtype=np.float64),
            "corr_valid": np.array([True, True, False, True]),
            "corr_fragment_ids": np.array([FRAGMENT_A, FRAGMENT_B], dtype="<U27"),
        },
        meta={"fragment_ids": [FRAGMENT_A, FRAGMENT_B], "mother_id": MOTHER, "event_id": EVENT},
        qa_status=QA_PASS, ancestry=fragment_ids, lineage_id=MOTHER, split="train",
    ).asset_id
    ids["label_bundle"] = store.commit_asset(
        role="label_bundle", schema="synlab.labels.v1", unit="1", frame="W_mm",
        payload={
            "label__surface_tag_map__0": tags.copy(),
            "label__research_id_map__0": np.where(tags >= 0, 3, -1).astype(np.int32),
        },
        meta={"fragment_id": FRAGMENT_A, "mother_id": MOTHER, "observation_id": OBSERVATION},
        qa_status=QA_PASS, ancestry=[ids["clean_truth"]], lineage_id=MOTHER, split="train",
    ).asset_id

    # feature_bundle carries only an observation_id: it must be associated through the
    # observation map, not through a fragment_id it does not have.
    ids["feature_bundle"] = store.commit_asset(
        role="feature_bundle", schema="a12.obs.v1", unit="mm", frame="S_mm",
        payload={
            "point_cloud__xyz": rng.random((6, 3), dtype=np.float32),
            "point_cloud__valid": np.ones(6, dtype=bool),
            "quality__names": np.array(["blur", "exposure"], dtype="<U21"),
            "quality__values": np.array([0.25, 0.5], dtype=np.float32),
            "quality__valid": np.array([True, False]),
        },
        meta={"observation_id": OBSERVATION, "run_id": "run_fixture"},
        qa_status=QA_PASS, lineage_id=MOTHER, split="train",
    ).asset_id

    # metadata-only asset: its whole payload is meta.json
    ids["provenance"] = store.commit_asset(
        role="provenance", schema="synlab.provenance.v1", unit="1", frame="none",
        payload={"code_fingerprint": {"commit": "fixture", "dirty": False},
                 "backend_fingerprints": {"numpy": np.__version__}, "seed_ref": "fixture:7"},
        meta={}, qa_status=QA_PASS, lineage_id=MOTHER, split="train",
    ).asset_id

    # a store-scoped asset that belongs to no fragment at all
    ids["qa_report"] = store.commit_asset(
        role="qa_report", schema="synlab.qa.v1", unit="1", frame="none",
        payload={"probe": np.zeros((3, 4), dtype=np.float64)},
        meta={}, qa_status=QA_PENDING, lineage_id=None, split=None,
    ).asset_id
    return {"root": root, "ids": ids, "fragments": [FRAGMENT_A, FRAGMENT_B],
            "mother": MOTHER, "observation": OBSERVATION}


@pytest.fixture(scope="session")
def full_store(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    root = tmp_path_factory.mktemp("full_store")
    return build_store(root)


@pytest.fixture(scope="session")
def full_package(tmp_path_factory: pytest.TempPathFactory, full_store: dict[str, Any]) -> Path:
    from synlab.storage.export_full import export_full_package

    out = tmp_path_factory.mktemp("full_package") / "package"
    export_full_package(full_store["root"], out)
    return out


@pytest.fixture(scope="session")
def real_package() -> Path:
    """The real ``data/a12_exports/full`` package when this checkout has one."""
    candidate = REPO_ROOT / "data/a12_exports/full"
    if not (candidate / "manifest.json").is_file():
        pytest.skip("no real full package in this checkout")
    return candidate
