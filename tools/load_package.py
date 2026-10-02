#!/usr/bin/env python
"""Training-package loader, data-card generator and independent package checker.

This module is the *entry point a consumer uses*: it reads a package written by
``synlab.storage.export.export_training_package`` with numpy/pandas/pyarrow only (no torch), it
can turn the package into a real batch with the same code path the trainer uses
(``synlab.qc.loader_probe`` + ``synlab.training.batch``), and it can generate the package's
``dataset_card.json`` / ``README.md`` **from a real scan of the bytes on disk** (never from a
literal in this file).

Three modes::

    python tools/load_package.py --package <dir>                  # card summary + tasks + batch
    python tools/load_package.py --package <dir> --write-card      # (re)generate the data card
    python tools/load_package.py --package <dir> --check           # verify, exit 0 / 3

Importable API (numpy/pandas)::

    from tools.load_package import (load_relations, load_arrays, iter_batches,
                                    load_labels, load_queries, read_zarr_array)

Why a separate loader instead of ``TrainingPackage`` alone: the packaged shards are npz/tar/parquet
only -- the zarr replica of the geometry is written by the exporter but was read by **no** code in
``synlab/training`` (0 occurrences of ``zarr`` there).  :func:`read_zarr_array` closes that gap and
:func:`zarr_npz_consistency` proves the two replicas agree array by array.

Exit codes: ``0`` fine, ``3`` the package or its data card does not hold up, ``2`` usage error.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
import sys
import tarfile
import time
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:                       # direct ``python tools/load_package.py``
    sys.path.insert(0, str(REPO_ROOT))

from synlab.canonical import hash_file                    # noqa: E402
from synlab.storage.export import TrainingPackage         # noqa: E402

EXIT_OK = 0
EXIT_INCONSISTENT = 3
EXIT_USAGE = 2

CARD_NAME = "dataset_card.json"
README_NAME = "README.md"
MANIFEST_NAME = "export_manifest.json"
CARD_SCHEMA = "synlab.dataset_card.v1"
#: Files a package always carries beside the manifest-declared set: the manifest itself (it can
#: not hash itself) and the two card artifacts this tool writes.  ``--check`` accepts exactly
#: these as extras; anything else present is a real inconsistency.
ALWAYS_EXTRA = (MANIFEST_NAME,)
CARD_ARTIFACTS = (CARD_NAME, README_NAME)

#: The five task losses (``synlab/training/losses.py`` ``TASK_ORDER``).
TASKS = ("view", "rank", "correspondence", "quality", "contradiction")

#: One line per packaged file family: what it is *for*, its unit and its coordinate frame.
FILE_PURPOSE: dict[str, dict[str, str]] = {
    "deploy/obs/index.json": {"purpose": "observation index: opaque name -> shard/member map",
                              "unit": "1", "frame": "-"},
    "deploy/geometry/index.json": {"purpose": "geometry index: points/normals/valid/frame_id per fragment",
                                   "unit": "1", "frame": "-"},
    "deploy/tokens/index.json": {"purpose": "token cache index: encoder, token dim, per-fragment token count",
                                 "unit": "1", "frame": "-"},
    "deploy/deploy_index.json": {"purpose": "opaque-name map for the deployment view (no label, no split)",
                                 "unit": "1", "frame": "-"},
    "deploy/queries.parquet": {"purpose": "query roster the model is asked to rank (fragment, gallery, status)",
                               "unit": "1", "frame": "-"},
    "research/relations.parquet": {"purpose": "supervised relation table: kind/valid/loss_mask per pair",
                                   "unit": "mm^2 for area_mm2", "frame": "S_mm"},
    "research/labels/clean.parquet": {"purpose": "clean-truth label rows (relation/interface level)",
                                      "unit": "mm^2 for area_mm2", "frame": "S_mm"},
    "research/labels/physical.parquet": {"purpose": "physical-truth label rows (component level)",
                                         "unit": "mm^2 for area_mm2", "frame": "S_mm"},
    "research/labels/visible.parquet": {"purpose": "visible-layer label rows (what the render showed)",
                                        "unit": "1", "frame": "-"},
    "research/labels/quality.parquet": {"purpose": "label-side observability target per fragment x view (task D)",
                                        "unit": "1 (rate)", "frame": "-"},
    "research/labels/correspondence.parquet": {"purpose": "real many-to-many surface correspondence samples (task C)",
                                               "unit": "mm for residual_mm, 1 for weight",
                                               "frame": "S_mm"},
    "research/labels/query_map.json": {"purpose": "maps deployment opaque names back to real ids (research only)",
                                       "unit": "1", "frame": "-"},
    "deploy/obs/shard": {"purpose": "per-fragment delivered observation: RGB tiles, deployment mask, view position",
                         "unit": "count for tiles, 1 for masks, mm for view_pos", "frame": "S_mm"},
    "deploy/geometry/shard": {"purpose": "per-fragment point cloud with validity masks and frame ids",
                              "unit": "mm for points/normals", "frame": "S_mm"},
    "deploy/tokens/shard": {"purpose": "per-fragment frozen token cache (identity block-mean encoder)",
                            "unit": "1 (linear 0..1 RGB means)", "frame": "image grid"},
    "deploy/zarr": {"purpose": "zarr v3 replica of the geometry shards (chunked, zstd)",
                    "unit": "mm for points/normals", "frame": "S_mm"},
    "deploy/degrade": {"purpose": "degradation-diversity index (axis x level variants of the release)",
                       "unit": "1", "frame": "-"},
    # ---- the merged experiment-ready dimensions (tools/a12_experiment_ready_export.py) --------
    "research/roi_views": {"purpose": "whole-slice + fracture-ROI close-up view family, copied "
                                      "from data/a12_roi/store; one npz per body plus its own "
                                      "observation metadata (research side: the payload carries "
                                      "id_map/surface_tag/T_WC/dist)",
                           "unit": "count for rgb, mm for depth_z/K/T_WC/depth, 1 for masks",
                           "frame": "S_mm"},
    "research/synthetic_extras": {"purpose": "nine bench-unobtainable modalities as declared "
                                              "upper-bound simulations (claim_ban applies)",
                                   "unit": "per-modality (see the index)", "frame": "W_mm"},
    "research/context": {"purpose": "simulated excavation context pack metadata "
                                    "(area/grid/layer/bag/coexistence/scale reference)",
                         "unit": "1", "frame": "-"},
    "research/degrade": {"purpose": "the 31-axis degradation registry with its materialised "
                                    "variants and the producer's own index",
                         "unit": "per-variant (see the index)", "frame": "S_mm / W_mm"},
    "research/fracture": {"purpose": "fracture-surface channels and per-patch amplitude "
                                     "statistics selected by face__origin_kind == INTERFACE",
                          "unit": "mm for areas/residuals/amplitudes", "frame": "W_mm"},
    "research/hard_negatives.index.json": {"purpose": "the recorded gap: no hard-negative table "
                                                      "exists, with its unlock condition",
                                           "unit": "1", "frame": "-"},
    "ablation_index.json": {"purpose": "one row per switchable data dimension: switch field, "
                                       "hypothesis, positive/negative gain yardsticks",
                            "unit": "1", "frame": "-"},
    "export_manifest.json": {"purpose": "package manifest: per-file sha256, counts, views",
                             "unit": "1", "frame": "-"},
}

#: Array/channel dictionary facts that a scan can not infer from bytes alone.
ARRAY_SEMANTICS: dict[str, dict[str, Any]] = {
    "points": {"meaning": "delivered proxy-scan surface samples of the fragment",
               "unit": "mm", "frame": "S_mm (scan frame)", "label": False},
    "normals": {"meaning": "unit surface normals of the samples", "unit": "1", "frame": "S_mm",
                "label": False},
    "point_valid": {"meaning": "the sample survived the observation route", "unit": "1",
                    "frame": "-", "label": False},
    "normal_valid": {"meaning": "the normal estimate is usable", "unit": "1", "frame": "-",
                     "label": False},
    "scale_valid": {"meaning": "the fragment carries a physical scale", "unit": "1", "frame": "-",
                    "label": False},
    "frame_id": {"meaning": "index of the delivered view whose depth matches this point "
                            "(-1 = no delivered view explains it)",
                 "unit": "1 (view index)", "frame": "-", "label": False},
    "tokens": {"meaning": "frozen identity block-mean features of the delivered RGB "
                          "(one token per view x block x channel)",
               "unit": "1 (linear 0..1)", "frame": "image grid", "label": False},
    "token_valid": {"meaning": "the token is usable", "unit": "1", "frame": "-", "label": False},
    "token_view": {"meaning": "which delivered view the token came from", "unit": "1",
                   "frame": "-", "label": False},
    "token_input": {"meaning": "coarse 4x4 block mean of each view (provenance of the token cache)",
                    "unit": "1 (linear 0..1)", "frame": "image grid", "label": False},
    "tile_valid": {"meaning": "per-pixel deployment mask of the delivered tiles", "unit": "1",
                   "frame": "image grid", "label": False},
    "rgb": {"meaning": "delivered RGB view (uint8)", "unit": "count", "frame": "image grid",
            "label": False},
    "valid": {"meaning": "per-pixel deployment mask", "unit": "1", "frame": "image grid",
              "label": False},
    "view_pos": {"meaning": "camera slide coordinate of the delivered view", "unit": "mm",
                 "frame": "S_mm", "label": False},
}

#: Column semantics of the research tables; ``label`` marks supervision (answer-side) columns.
COLUMN_SEMANTICS: dict[str, dict[str, Any]] = {
    "label_layer": {"meaning": "which truth layer produced the row", "label": False},
    "asset_id": {"meaning": "store asset the row was derived from", "label": False},
    "lineage": {"meaning": "lineage (mother vessel) the row belongs to", "label": True},
    "split": {"meaning": "train/dev/confirm assignment of the lineage", "label": True},
    "passed": {"meaning": "the layer's own gate for this row", "label": True},
    "fragment_id": {"meaning": "fragment the row is about", "label": False},
    "role": {"meaning": "row role inside the layer", "label": False},
    "detail": {"meaning": "layer-specific payload of the row", "label": True},
    "candidate_id": {"meaning": "candidate fragment of a relation row", "label": True},
    "kind": {"meaning": "relation kind R2/R1/R0/TINY/UNKNOWN", "label": True},
    "area_mm2": {"meaning": "shared cut-face area of the pair", "unit": "mm^2", "label": True},
    "valid": {"meaning": "the row's measurement is usable", "label": True},
    "loss_mask": {"meaning": "the row may enter a loss (UNKNOWN never may)", "label": True},
    "reason": {"meaning": "why the row got this kind/mask", "label": True},
    "unique_source_triangle": {"meaning": "the cut face has one unambiguous source triangle",
                               "label": True},
    "query": {"meaning": "query fragment of the pair", "label": True},
    "candidate": {"meaning": "candidate fragment of the pair", "label": True},
    "pool_id": {"meaning": "relation pool the row came from", "label": False},
    "lineage_cluster": {"meaning": "lineage cluster used for grouped splits", "label": True},
    "eligible_as_negative": {"meaning": "kind in {R1,R0} and valid and loss_mask", "label": True},
    "has_observation": {"meaning": "both sides of the pair carry a delivered observation",
                        "label": False},
    "query_id": {"meaning": "query key as the roster spells it", "label": False},
    "mother": {"meaning": "mother (vessel) id", "label": True},
    "fragment": {"meaning": "fragment the query is about", "label": False},
    "gallery": {"meaning": "gallery the query is drawn from", "label": False},
    "historical_N_G": {"meaning": "historical negative-gallery size for the query", "label": False},
    "status": {"meaning": "roster status (FROZEN/...)", "label": False},
    "applicability": {"meaning": "views/scale validity the query really has", "label": False},
    "fragment_a": {"meaning": "first fragment of a correspondence sample", "label": False},
    "fragment_b": {"meaning": "second fragment of a correspondence sample", "label": False},
    "index_a": {"meaning": "surface sample index on side A", "label": True},
    "index_b": {"meaning": "surface sample index on side B", "label": True},
    "weight": {"meaning": "non-negative edge weight of the correspondence", "label": True},
    "sample_valid": {"meaning": "the sample survived the correspondence estimator", "label": True},
    "ambiguous": {"meaning": "the sample has more than one plausible match", "label": True},
    "association_code": {"meaning": "how the match was established", "label": True},
    "residual_mm": {"meaning": "distance between the matched surface samples", "unit": "mm",
                    "label": True},
    "interface_id": {"meaning": "cut interface the sample belongs to", "label": True},
    "relation_kind": {"meaning": "relation kind of the pair the sample came from", "label": True},
    "source_kind": {"meaning": "which layer/asset produced the row", "label": False},
    "source_ref": {"meaning": "reference inside the source layer", "label": False},
    "view_id": {"meaning": "delivered view the measurement is about", "label": False},
    "samples": {"meaning": "surface samples considered in the view", "label": False},
    "projected": {"meaning": "samples that projected into the view", "label": False},
    "depth_ok": {"meaning": "samples whose depth agreed with the rendered depth", "label": False},
    "id_ok": {"meaning": "samples whose id matched the rendered id map", "label": False},
    "not_uncertain": {"meaning": "samples outside the renderer's uncertain mask", "label": False},
    "deployment_ok": {"meaning": "samples inside the deployment mask", "label": False},
    "visible": {"meaning": "samples that survived every visibility criterion", "label": True},
    "target_channel": {"meaning": "name of the measured channel", "label": True},
    "target_unit": {"meaning": "unit of target_value", "unit": "1", "label": True},
    "target_value": {"meaning": "the supervised quality target (observability rate)",
                     "unit": "rate 0..1", "label": True},
    "visible_rate": {"meaning": "visible/samples", "unit": "rate 0..1", "label": False},
    "depth_ok_rate": {"meaning": "depth_ok/samples", "unit": "rate 0..1", "label": False},
    "id_ok_rate": {"meaning": "id_ok/samples", "unit": "rate 0..1", "label": False},
    "not_uncertain_rate": {"meaning": "not_uncertain/samples", "unit": "rate 0..1", "label": False},
    "deployment_ok_rate": {"meaning": "deployment_ok/samples", "unit": "rate 0..1",
                           "label": False},
    # simulated excavation context (deployment-side acquisition metadata, plan t088).  ``bag_id``
    # is *also* a name in roles.FORBIDDEN_FEATURE_FIELDS (the model-forward-pass rule).  The Lead
    # ruling of 2026-10-02 classifies it as capture context: it is declared in
    # synlab/schemas/view_channels.json with evidence_class=capture_context / rig_obtainable=true /
    # claim_allowed=true, so separation.answer_field_scan no longer counts it as an answer field
    # and the package reports it under separation.capture_context_scan instead.
    "context_id": {"meaning": "simulated excavation context the query belongs to", "label": False},
    "batch_id": {"meaning": "simulated find batch of the query", "label": False},
    "bag_id": {"meaning": "simulated find bag of the query: declared acquisition context "
                          "(evidence_class=capture_context), not an answer field",
               "label": False},
    "stratum_id": {"meaning": "simulated stratum of the query", "label": False},
    "excavation_area_id": {"meaning": "simulated excavation area of the query", "label": False},
    # ---- S3 direction completion (both role assignments of every unordered pair) --------------
    "direction": {"meaning": "which role assignment this row is: 'canonical' (query=a) or "
                             "'reverse' (query=b); the kind/valid/loss_mask labels of a pair are "
                             "identical in both directions",
                  "label": False},
    "pair_key": {"meaning": "canonical unordered pair key 'a|b' shared by the two direction rows",
                 "label": False},
    # ---- the merged fracture-interface dimension (research/fracture/*.parquet) ----------------
    "lineage_id": {"meaning": "lineage (mother vessel) the row belongs to", "label": True},
    "qa_status": {"meaning": "store QA verdict of the asset the row was measured from",
                  "label": False},
    "n_faces": {"meaning": "faces in the mesh (or in the interface patch)", "label": False},
    "n_interface_faces": {"meaning": "faces whose face__origin_kind is ORIGIN_INTERFACE",
                          "label": False},
    "interface_fraction": {"meaning": "n_interface_faces / n_faces", "unit": "rate 0..1",
                           "label": False},
    "interface_ids": {"meaning": "the face__interface_id values present on this fragment",
                      "label": False},
    "n_patches": {"meaning": "interface patches (one per distinct face__interface_id)",
                  "label": False},
    "planar_geometry": {"meaning": "every interface patch of the fragment is numerically coplanar "
                                   "(max |vertex - area-weighted patch plane| <= 1e-9 mm)",
                        "label": False},
    "planar_patches": {"meaning": "how many of the fragment's patches are coplanar", "label": False},
    "planar": {"meaning": "this patch is numerically coplanar", "label": False},
    "planar_geometry_rule": {"meaning": "the written rule that makes planar_geometry reproducible",
                             "label": False},
    "why_planar_is_null": {"meaning": "why planarity could not be measured for this fragment",
                           "label": False},
    "patch_residual_max_mm": {"meaning": "largest patch plane residual of the fragment",
                              "unit": "mm", "label": False},
    "patch_ra_below_1mm_min_mm": {"meaning": "smallest below_1mm Ra over the fragment's patches",
                                  "unit": "mm", "label": False},
    "patch_ra_below_1mm_max_mm": {"meaning": "largest below_1mm Ra over the fragment's patches",
                                  "unit": "mm", "label": False},
    "plane_residual_max_mm": {"meaning": "largest |vertex - area-weighted patch plane|",
                              "unit": "mm", "label": False},
    "plane_residual_rms_mm": {"meaning": "RMS of the same plane residual", "unit": "mm",
                              "label": False},
    "centroid_height_ra_mm": {"meaning": "area-weighted mean |face-centroid height| over the patch "
                                         "plane", "unit": "mm", "label": False},
    "n_height_samples": {"meaning": "patch vertices the amplitude statistics were computed on",
                         "label": False},
    "plane": {"meaning": "whole-patch amplitude statistics (Ra/Rq/Rz/Rt) relative to the fitted "
                         "plane", "label": False},
    "mean_normal": {"meaning": "area-weighted mean unit normal of the patch", "unit": "1",
                    "label": False},
    "plane_centre_mm": {"meaning": "area-weighted centroid of the patch", "unit": "mm",
                        "label": False},
    "ra_below_5mm_mm": {"meaning": "Ra of the locally detrended field below a 5 mm ball",
                        "unit": "mm", "label": False},
    "ra_below_1mm_mm": {"meaning": "Ra of the locally detrended field below a 1 mm ball (the band "
                                   "docs/a12/fracture_visible.md 2.3 reports)",
                        "unit": "mm", "label": False},
    "ra_below_0.25mm_mm": {"meaning": "Ra of the locally detrended field below a 0.25 mm ball",
                           "unit": "mm", "label": False},
    "rq_below_5mm_mm": {"meaning": "Rq of the locally detrended field below a 5 mm ball",
                        "unit": "mm", "label": False},
    "rq_below_1mm_mm": {"meaning": "Rq of the locally detrended field below a 1 mm ball",
                        "unit": "mm", "label": False},
    "rq_below_0.25mm_mm": {"meaning": "Rq of the locally detrended field below a 0.25 mm ball",
                           "unit": "mm", "label": False},
    "fracture_signal_channels": {"meaning": "the face__* channels this mesh really carries",
                                 "label": False},
}


# --------------------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------------------
def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, np.ndarray):
        return _jsonable(value.tolist())
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def sha256_file(path: Path, *, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(chunk), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def git_head() -> dict[str, Any]:
    """Real ``git HEAD`` + dirty flag of the checkout this card was generated in."""
    try:
        head = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=30)
        status = subprocess.run(["git", "-C", str(REPO_ROOT), "status", "--porcelain"],
                                capture_output=True, text=True, timeout=60)
        if head.returncode != 0:
            return {"head": "missing", "dirty": None,
                    "reason": f"git rev-parse failed: {head.stderr.strip()[:200]}"}
        porcelain = status.stdout.strip().splitlines()
        return {"head": head.stdout.strip(), "dirty": bool(porcelain),
                "dirty_entries": len(porcelain),
                "source": "git rev-parse HEAD / git status --porcelain"}
    except (OSError, subprocess.SubprocessError) as exc:      # pragma: no cover - env dependent
        return {"head": "missing", "dirty": None, "reason": f"{type(exc).__name__}: {exc}"}


def registry_fingerprint() -> dict[str, Any]:
    try:
        from synlab.registry import REGISTRY

        return {"fingerprint": REGISTRY.fingerprint(),
                "source": "synlab.registry.REGISTRY.fingerprint()"}
    except Exception as exc:                                   # pragma: no cover
        return {"fingerprint": "missing", "reason": f"{type(exc).__name__}: {exc}"}


# --------------------------------------------------------------------------------------
# package access
# --------------------------------------------------------------------------------------
def resolve_package(package: str | Path) -> Path:
    """Accept a package dir (or a parent that contains exactly one ``training_package``)."""
    path = Path(package)
    if (path / "export_manifest.json").is_file():
        return path
    if path.is_dir():
        nested = sorted(p for p in path.glob("*/training_package")
                        if (p / "export_manifest.json").is_file())
        if len(nested) == 1:
            return nested[0]
    raise FileNotFoundError(f"{path} is not a training package (no export_manifest.json)")


class Package:
    """Thin, cache-free reader around ``TrainingPackage`` with pandas tables."""

    def __init__(self, root: str | Path):
        self.path = resolve_package(root)
        self.inner = TrainingPackage(self.path)
        self.manifest: dict[str, Any] = self.inner.manifest
        self._relations: pd.DataFrame | None = None
        self._queries: pd.DataFrame | None = None
        self._labels: dict[str, pd.DataFrame] = {}

    # ---- indexes ---------------------------------------------------------------
    @property
    def obs_index(self) -> dict[str, Any]:
        return self.inner.observation_index()

    @property
    def geometry_index(self) -> dict[str, Any]:
        path = self.path / "deploy/geometry/index.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"rows": {}}

    @property
    def token_index(self) -> dict[str, Any]:
        path = self.path / "deploy/tokens/index.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"rows": {}}

    @property
    def deploy_index(self) -> dict[str, Any]:
        path = self.path / "deploy/deploy_index.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"rows": {}}

    # ---- tables ----------------------------------------------------------------
    def _table(self, relative: str) -> pd.DataFrame:
        path = self.path / relative
        if not path.exists():
            return pd.DataFrame()
        return pd.read_parquet(path)

    @property
    def relations(self) -> pd.DataFrame:
        if self._relations is None:
            self._relations = self._table("research/relations.parquet")
        return self._relations

    @property
    def queries(self) -> pd.DataFrame:
        if self._queries is None:
            self._queries = self._table("deploy/queries.parquet")
        return self._queries

    def labels(self, layer: str) -> pd.DataFrame:
        if layer not in self._labels:
            self._labels[layer] = self._table(f"research/labels/{layer}.parquet")
        return self._labels[layer]

    @property
    def label_layers(self) -> list[str]:
        directory = self.path / "research/labels"
        if not directory.is_dir():
            return []
        return sorted(p.stem for p in directory.glob("*.parquet"))

    # ---- fragment ids ----------------------------------------------------------
    def fragment_ids(self) -> list[str]:
        """Query fragments first (the roster order), then every candidate the tables name."""
        ids: list[str] = []
        if not self.queries.empty and "fragment" in self.queries.columns:
            ids.extend(str(v) for v in self.queries["fragment"].tolist() if str(v))
        elif not self.queries.empty and "query_id" in self.queries.columns:
            ids.extend(str(v).split("::", 1)[-1] for v in self.queries["query_id"].tolist())
        for column in ("candidate",):
            if not self.relations.empty and column in self.relations.columns:
                ids.extend(str(v) for v in self.relations[column].tolist() if str(v))
        return [f for f in dict.fromkeys(ids) if f]

    # ---- arrays ----------------------------------------------------------------
    def obs_arrays(self, fragment_id: str) -> dict[str, np.ndarray]:
        """Every member of the fragment's observation shard (not just the three from 0.x)."""
        entry = (self.obs_index.get("rows") or {}).get(fragment_id)
        if entry is None:
            raise KeyError(f"{fragment_id!r} has no delivered observation")
        wanted = [str(name) for name in (entry.get("channels") or [])]
        if not wanted:
            wanted = ["tiles", "valid", "view_pos"]
        shard = self.path / "deploy" / entry["shard"]   # index paths are view-relative
        out: dict[str, np.ndarray] = {}
        with tarfile.open(shard, "r") as tar:
            for name in wanted:
                member = tar.extractfile(f"{entry['opaque']}/{name}.npy")
                if member is None:
                    continue
                out[name] = np.load(io.BytesIO(member.read()), allow_pickle=False)
        return out

    def npz_arrays(self, kind: str, fragment_id: str) -> dict[str, np.ndarray]:
        if kind == "geometry":
            return self.inner.read_geometry(fragment_id)
        if kind == "tokens":
            return self.inner.read_tokens(fragment_id)
        raise ValueError(f"unknown npz kind {kind!r}")

    def zarr_arrays(self, fragment_id: str) -> dict[str, np.ndarray]:
        opaque = str((self.deploy_index.get("rows") or {}).get(fragment_id, {}).get("opaque", ""))
        if not opaque:
            opaque = str((self.geometry_index.get("rows") or {}).get(fragment_id, {})
                         .get("opaque", ""))
        if not opaque:
            raise KeyError(f"{fragment_id!r} has no opaque name in the package index")
        group = self.path / "deploy/zarr" / opaque
        if not group.is_dir():
            raise FileNotFoundError(f"no zarr replica for {fragment_id!r} ({group})")
        out: dict[str, np.ndarray] = {}
        for child in sorted(p for p in group.iterdir() if p.is_dir()):
            out[child.name] = read_zarr_array(child)
        return out


def load_relations(package: str | Path) -> pd.DataFrame:
    """The supervised relation table (one row per pair, ``kind``/``valid``/``loss_mask``)."""
    return Package(package).relations


def load_queries(package: str | Path) -> pd.DataFrame:
    """The query roster."""
    return Package(package).queries


def load_labels(package: str | Path, layer: str) -> pd.DataFrame:
    """One label layer (``clean`` / ``physical`` / ``visible`` / ``quality`` / ``correspondence``)."""
    return Package(package).labels(layer)


def load_arrays(package: str | Path, fragment_id: str | None = None, *,
                kind: str = "geometry", source: str = "npz") -> Any:
    """Read packaged arrays.

    ``kind``: ``geometry`` | ``tokens`` | ``obs``.  ``source``: ``npz`` (default), ``tar`` for
    ``obs``, or ``zarr`` for the geometry replica.  With ``fragment_id=None`` every fragment the
    package describes for that kind is read and returned as ``{fragment_id: arrays}``.
    """
    pkg = Package(package)
    if fragment_id is not None:
        return _read_one(pkg, fragment_id, kind, source)
    if kind == "geometry":
        ids = list((pkg.geometry_index.get("rows") or {}).keys())
    elif kind == "tokens":
        ids = list((pkg.token_index.get("rows") or {}).keys())
    else:
        ids = list((pkg.obs_index.get("rows") or {}).keys())
    return {fid: _read_one(pkg, fid, kind, source) for fid in ids}


def _read_one(pkg: Package, fragment_id: str, kind: str, source: str) -> dict[str, np.ndarray]:
    if kind == "obs":
        return pkg.obs_arrays(fragment_id)
    if source == "zarr":
        if kind != "geometry":
            raise ValueError("the zarr replica only covers the geometry shards")
        return pkg.zarr_arrays(fragment_id)
    return pkg.npz_arrays(kind, fragment_id)


# --------------------------------------------------------------------------------------
# zarr v3 reader (the packaged replica had no reader anywhere in synlab/training)
# --------------------------------------------------------------------------------------
def _zarr_metadata(path: Path) -> dict[str, Any]:
    meta = path / "zarr.json"
    if not meta.is_file():
        meta = path / ".zarray"                              # zarr v2 fallback
    if not meta.is_file():
        raise FileNotFoundError(f"{path} carries no zarr metadata")
    return json.loads(meta.read_text(encoding="utf-8"))


def _decode_chunk(raw: bytes, meta: Mapping[str, Any]) -> np.ndarray:
    """Decode one zarr v3 chunk.

    The ``codecs`` list is written in *encode* order (``bytes`` turns the array into a buffer,
    ``zstd`` compresses it), so a reader walks it in reverse: decompress first, then interpret the
    buffer with the declared dtype/endianness.
    """
    payload = raw
    dtype = np.dtype(str(meta.get("data_type", "float32")))
    for codec in reversed(list(meta.get("codecs") or [])):
        name = str(codec.get("name", ""))
        configuration = codec.get("configuration") or {}
        if name == "bytes":
            endian = str(configuration.get("endian", "little"))
            if dtype.itemsize > 1 and endian == "big":
                dtype = dtype.newbyteorder(">")
        elif name == "zstd":
            try:
                from numcodecs import Zstd                       # type: ignore
            except Exception as exc:                             # pragma: no cover
                raise RuntimeError(
                    "chunk is zstd-compressed and no zstd backend is importable "
                    "(install zarr/numcodecs or zstandard)") from exc
            payload = Zstd().decode(np.frombuffer(payload, dtype=np.uint8))
        elif name == "gzip":
            import gzip as _gzip

            payload = _gzip.decompress(payload)
        elif name in ("transpose", "shuffle", "crc32c", "blosc", "blosc2"):
            raise RuntimeError(f"zarr chunk codec {name!r} is not supported by this reader")
        else:
            raise RuntimeError(f"unknown zarr chunk codec {name!r}")
    return np.frombuffer(payload, dtype=dtype)


def read_zarr_array(path: str | Path) -> np.ndarray:
    """Read a zarr v3 array written by ``export._write_zarr`` into a numpy array.

    Uses the ``zarr`` package when it is importable (the reference implementation) and a built-in
    reader otherwise; :func:`zarr_npz_consistency` checks that both agree with the npz shard.
    """
    directory = Path(path)
    if not directory.is_dir():
        raise FileNotFoundError(f"{directory} is not a zarr array directory")
    try:                                                     # reference reader first
        import zarr

        return np.asarray(zarr.open_array(str(directory), mode="r")[:])
    except Exception as exc:                                  # noqa: BLE001 - fall back, report
        fallback_reason = f"{type(exc).__name__}: {exc}"
    meta = _zarr_metadata(directory)
    shape = tuple(int(v) for v in meta["shape"])
    chunk_shape = tuple(int(v) for v in meta["chunk_grid"]["configuration"]["chunk_shape"])
    dtype = np.dtype(str(meta["data_type"]))
    out = np.zeros(shape, dtype=dtype)
    grid = tuple(int(np.ceil(s / c)) if c else 1 for s, c in zip(shape, chunk_shape))
    filled = False
    for index in np.ndindex(*grid):
        key = directory / "c" / "/".join(str(i) for i in index)
        if not key.is_file():
            continue
        values = _decode_chunk(key.read_bytes(), meta)
        expected = tuple(min(c, s - i * c) for s, c, i in zip(shape, chunk_shape, index))
        block = values[: int(np.prod(expected))].reshape(expected)
        slices = tuple(slice(i * c, i * c + size)
                       for i, c, size in zip(index, chunk_shape, expected))
        out[slices] = block
        filled = True
    if not filled:
        raise FileNotFoundError(
            f"{directory}: no chunk file found (fallback reader; zarr said {fallback_reason})")
    return out


def zarr_npz_consistency(package: str | Path, *, fragments: Sequence[str] | None = None
                         ) -> dict[str, Any]:
    """Compare every zarr array with its npz twin (the replica must be a real copy)."""
    pkg = Package(package)
    rows = list((pkg.geometry_index.get("rows") or {}).keys())
    if fragments is not None:
        rows = [f for f in rows if f in set(fragments)]
    report: dict[str, Any] = {"schema": "synlab.zarr_consistency.v1", "fragments": {},
                              "arrays_checked": 0, "arrays_identical": 0, "problems": []}
    for fragment_id in rows:
        try:
            zarr_arrays = pkg.zarr_arrays(fragment_id)
        except Exception as exc:                              # noqa: BLE001 - the failure is data
            report["problems"].append(f"{fragment_id}: zarr unreadable ({type(exc).__name__}: "
                                      f"{exc})")
            continue
        npz_arrays = pkg.npz_arrays("geometry", fragment_id)
        entry: dict[str, Any] = {}
        for name in sorted(zarr_arrays):
            left = np.asarray(zarr_arrays[name])
            right = np.asarray(npz_arrays.get(name)) if name in npz_arrays else None
            report["arrays_checked"] += 1
            if right is None:
                entry[name] = {"identical": False, "reason": "absent from the npz shard"}
                report["problems"].append(f"{fragment_id}/{name}: only in zarr")
                continue
            same = (left.shape == right.shape and left.dtype == right.dtype
                    and left.tobytes() == right.tobytes())
            entry[name] = {"identical": bool(same), "shape": list(left.shape),
                           "dtype": str(left.dtype)}
            report["arrays_identical"] += int(bool(same))
            if not same:
                report["problems"].append(
                    f"{fragment_id}/{name}: zarr {left.shape}/{left.dtype} != npz "
                    f"{right.shape}/{right.dtype}")
        report["fragments"][fragment_id] = entry
    report["ok"] = not report["problems"]
    return report


# --------------------------------------------------------------------------------------
# a real batch (the same code path the trainer uses; numpy only, no torch)
# --------------------------------------------------------------------------------------
def encoder_valid(features: Any) -> np.ndarray:
    """``z_valid`` exactly as ``synlab/training/model.py::encode`` defines it.

    ``valid = (rgb_gate + geo_gate + tok_gate) > 0`` with ``rgb_gate = global_valid.any``,
    ``geo_gate = ((point_valid | normal_valid) & scale_valid).any`` and
    ``tok_gate = token_valid.any``.  Computed here without torch so the supervision table is the
    trainer's own denominator and not a re-definition.  ``features`` is a ``FeatureBundle`` (or any
    object/mapping carrying those five stacked arrays).
    """
    def array(name: str) -> np.ndarray:
        if isinstance(features, Mapping):
            return np.asarray(features[name])
        return np.asarray(getattr(features, name))

    global_valid = array("global_valid").astype(bool)
    token_valid = array("token_valid").astype(bool)
    point_valid = array("point_valid").astype(bool)
    normal_valid = array("normal_valid").astype(bool)
    scale_valid = array("scale_valid").astype(bool).reshape(-1, 1)
    rgb_gate = global_valid.any(axis=tuple(range(1, global_valid.ndim)))
    geo_gate = ((point_valid | normal_valid) & scale_valid).any(axis=1)
    tok_gate = token_valid.any(axis=1)
    return (rgb_gate | geo_gate | tok_gate).astype(bool)


def _label_source(pkg: Package):
    from synlab.training.labels import PackageLabelSource

    return PackageLabelSource.from_package(pkg.inner)


def batch_rows(pkg: Package, fragment_ids: Sequence[str] | None = None) -> list[dict[str, Any]]:
    """One row per query: positives / legal negatives / excluded, taken from the exported table."""
    from synlab.qc.loader_probe import _batch_rows

    ids = list(fragment_ids) if fragment_ids is not None else pkg.fragment_ids()
    relations = pkg.relations.to_dict("records") if not pkg.relations.empty else []
    pool = build_pool(pkg)
    return _batch_rows(relations, ids, pool)


def build_pool(pkg: Package):
    from synlab.qc.loader_probe import ExportedRelationPool, _pool_id

    relations = pkg.relations.to_dict("records") if not pkg.relations.empty else []
    return ExportedRelationPool(relations, pool_id=_pool_id(relations))


def build_batch(package: str | Path, *, fragment_ids: Sequence[str] | None = None,
                token_budget: int = 256, sampler_cfg: Any | None = None) -> dict[str, Any]:
    """Build one real batch from the package and measure its supervision.

    Returns ``{"batch", "bundle", "payloads", "rows", "supervision", "provenance", "shapes"}``.
    """
    from synlab.qc.loader_probe import load_features
    from synlab.training.adapter import FeatureBundle
    from synlab.training.batch import build_training_batch

    pkg = Package(package)
    ids = list(fragment_ids) if fragment_ids is not None else pkg.fragment_ids()
    pool = build_pool(pkg)
    pool.features = load_features(pkg.inner, ids, token_budget=token_budget)
    rows = batch_rows(pkg, ids) if not pkg.relations.empty else []
    bundle = FeatureBundle.from_dict(pool.features, token_budget=token_budget).check_shapes()

    source = _label_source(pkg)
    labels: dict[str, Any] = {"pool_id": getattr(pool, "pool_id", ""),
                              "lineage_cluster": getattr(pool, "lineage_cluster_of", {}) or {}}
    kwargs: dict[str, Any] = {}
    label_report: dict[str, Any] = {}
    quality_target, quality_valid, quality_report = source.quality_target_for(ids)
    kwargs["quality_target"] = quality_target
    kwargs["quality_target_valid"] = quality_valid
    label_report["quality"] = quality_report
    if rows:
        correspondence, corr_report = source.correspondence_for(bundle, rows)
        label_report["correspondence"] = corr_report
        if correspondence:
            # only a real, token-mapped correspondence table may become W
            kwargs["correspondence"] = correspondence

    batch = None
    if rows:
        batch = build_training_batch(bundle, pool=pool, rows=rows, labels=labels,
                                     sampler_cfg=sampler_cfg,
                                     quality_tier=getattr(pool, "quality_tier", None),
                                     meta={"supervision_labels": label_report} or None,
                                     **kwargs)
    # ``z_valid`` comes from the same definition the encoder uses (model.py::encode)
    z_valid = encoder_valid(bundle)
    if batch is not None:
        from synlab.training.supervision import supervision_accounting

        supervision = supervision_accounting(batch, z_valid=z_valid, label_report=label_report)
    else:
        supervision = {"tasks": {}, "pair_mask": None, "tasks_with_supervision": [],
                       "reason": "the package carries no relation row, so no pair batch exists"}
    provenance = {
        "reader": "tools/load_package.py (synlab.qc.loader_probe + synlab.training.batch)",
        "relations_parquet": "research/relations.parquet",
        "queries_parquet": "deploy/queries.parquet",
        "tokens_npz": sorted({str((pkg.token_index.get("rows") or {})[f]["shard"])
                              for f in ids if f in (pkg.token_index.get("rows") or {})}),
        "geometry_npz": sorted({str((pkg.geometry_index.get("rows") or {})[f]["shard"])
                                for f in ids if f in (pkg.geometry_index.get("rows") or {})}),
        "obs_tar": sorted({str((pkg.obs_index.get("rows") or {})[f]["shard"])
                           for f in ids if f in (pkg.obs_index.get("rows") or {})}),
        "fragment_ids": ids,
        "z_valid_sum": int(np.count_nonzero(z_valid)),
        "token_budget": int(token_budget),
    }
    return {"package": pkg, "batch": batch, "bundle": bundle, "payloads": pool.features,
            "rows": rows, "supervision": supervision, "provenance": provenance, "z_valid": z_valid,
            "label_report": label_report}


def iter_batches(package: str | Path, *, batch_size: int = 8, token_budget: int = 256
                 ) -> Iterator[dict[str, Any]]:
    """Yield real batches, chunked over the query rows of the package.

    Each item is ``{"index", "rows", "features", "labels", "supervision", "provenance"}`` where
    ``features`` are numpy arrays (the same tensors ``FeatureBundle`` exposes) and ``labels`` the
    batch tables.  Nothing is fabricated: a chunk with no row still yields an (empty) batch with
    ``supervision.tasks == {}``.
    """
    pkg = Package(package)
    ids = pkg.fragment_ids()
    if not pkg.relations.empty:
        rows = batch_rows(pkg, ids)
    else:
        rows = []
    chunk = max(int(batch_size), 1)
    if not rows:
        built = build_batch(pkg.path, fragment_ids=ids, token_budget=token_budget)
        yield {"index": 0, "rows": [], "features": built["payloads"],
               "labels": {}, "supervision": built["supervision"],
               "provenance": built["provenance"], "batch": built["batch"]}
        return
    for index in range(0, len(rows), chunk):
        window = rows[index:index + chunk]
        wanted: list[str] = []
        for row in window:
            for fid in [row["query"], *row["positives"], *row["negatives"]]:
                if fid not in wanted:
                    wanted.append(fid)
        built = build_batch(pkg.path, fragment_ids=wanted, token_budget=token_budget)
        batch = built["batch"]
        yield {
            "index": index // chunk,
            "rows": window,
            "features": built["payloads"],
            "labels": ({
                "pair_index": np.asarray(batch.pair_index),
                "pair_valid": np.asarray(batch.pair_valid),
                "pos_mask": np.asarray(batch.pos_mask),
                "neg_mask": np.asarray(batch.neg_mask),
                "labels_relation": np.asarray(batch.labels_relation),
                "quality_target": np.asarray(batch.quality_target),
                "corr_weight": np.asarray(batch.corr_weight),
            } if batch is not None else {}),
            "supervision": built["supervision"],
            "provenance": built["provenance"],
            "batch": batch,
        }


def batch_shapes(built: Mapping[str, Any]) -> dict[str, Any]:
    """Shapes + dtype of every tensor of a real mini-batch (features from the stacked bundle)."""
    out: dict[str, Any] = {"features": {}, "labels": {}}
    bundle = built.get("bundle")
    names = ("global_rgb", "global_valid", "pixel_valid", "local_tokens", "token_valid",
             "token_view", "token_modality", "token_source", "tokens_total", "points",
             "point_valid", "normals", "normal_valid", "scale_valid", "quality", "quality_valid",
             "presence", "presence_valid")
    if bundle is not None:
        for name in names:
            if not hasattr(bundle, name):
                continue
            array = np.asarray(getattr(bundle, name))
            out["features"][name] = {"shape": list(array.shape), "dtype": str(array.dtype)}
    else:                                                     # pragma: no cover - defensive
        for name, value in sorted(built["payloads"].items()):
            array = np.asarray(value)
            out["features"][name] = {"shape": list(array.shape), "dtype": str(array.dtype)}
    batch = built.get("batch")
    if batch is not None:
        for name in ("pair_index", "pair_valid", "labels_relation", "pos_mask", "neg_mask",
                     "excluded_mask", "quality_target", "quality_target_valid", "corr_weight",
                     "contradiction", "contradiction_valid", "lineage_cluster"):
            array = np.asarray(getattr(batch, name))
            out["labels"][name] = {"shape": list(array.shape), "dtype": str(array.dtype),
                                   "nonzero": int(np.count_nonzero(array))}
        out["positives"] = int(np.asarray(batch.pos_mask).sum())
        out["negatives"] = int(np.asarray(batch.neg_mask).sum())
        out["effective_queries"] = int(batch.effective_query_count())
    out["fragments"] = len(built["payloads"])
    out["observed_fragments"] = int(sum(1 for p in built["payloads"].values()
                                        if int(np.asarray(p["tokens_total"])) > 0))
    return out


# --------------------------------------------------------------------------------------
# package scan -> data card
# --------------------------------------------------------------------------------------
def _file_family(relative: str) -> str:
    for prefix in ("deploy/obs/shard", "deploy/geometry/shard", "deploy/tokens/shard",
                   "deploy/zarr", "research/roi_views", "research/synthetic_extras",
                   "research/context", "research/degrade", "research/fracture"):
        if relative.startswith(prefix):
            return prefix
    return relative


def _purpose_for(relative: str) -> dict[str, str]:
    return FILE_PURPOSE.get(relative) or FILE_PURPOSE.get(_file_family(relative)) or {
        "purpose": "packaged artifact", "unit": "1", "frame": "-"}


def _file_format(relative: str) -> str:
    suffix = Path(relative).suffix.lower()
    if relative.startswith("deploy/zarr"):
        return "zarr-v3-chunk" if suffix not in (".json",) else "zarr-v3-metadata"
    return {".json": "json", ".parquet": "parquet", ".npz": "npz", ".tar": "tar", ".npy": "npy",
            ".md": "markdown"}.get(suffix, suffix.lstrip(".") or "unknown")


def _table_shape(path: Path) -> dict[str, Any]:
    try:
        frame = pd.read_parquet(path)
    except Exception as exc:                                  # noqa: BLE001
        return {"rows": None, "columns": None, "error": f"{type(exc).__name__}: {exc}"}
    return {"rows": int(frame.shape[0]), "columns": int(frame.shape[1]),
            "column_names": [str(c) for c in frame.columns]}


def _npz_shape(path: Path) -> dict[str, Any]:
    try:
        with np.load(path, allow_pickle=False) as data:
            arrays = {name: list(np.shape(data[name])) for name in data.files}
            dtypes = {name: str(data[name].dtype) for name in data.files}
    except Exception as exc:                                  # noqa: BLE001
        return {"arrays": None, "error": f"{type(exc).__name__}: {exc}"}
    return {"arrays": arrays, "dtypes": dtypes, "n_arrays": len(arrays)}


def _tar_shape(path: Path) -> dict[str, Any]:
    try:
        with tarfile.open(path, "r") as tar:
            members = [(m.name, int(m.size)) for m in tar.getmembers() if m.isfile()]
    except Exception as exc:                                  # noqa: BLE001
        return {"members": None, "error": f"{type(exc).__name__}: {exc}"}
    names = sorted({m.split("/", 1)[-1] for m, _ in members})
    return {"members": len(members), "entities": len({m.split("/", 1)[0] for m, _ in members}),
            "member_names": names}


def _safe_nunique(series: pd.Series) -> int:
    """``nunique`` that also works for object columns holding mappings (``applicability``)."""
    try:
        return int(series.nunique(dropna=True))
    except TypeError:
        seen = set()
        for value in series.dropna().tolist():
            try:
                seen.add(json.dumps(value, sort_keys=True, default=str))
            except TypeError:                                # pragma: no cover - defensive
                seen.add(repr(value))
        return len(seen)


def _column_stats(frame: pd.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {}
    rows = max(int(frame.shape[0]), 1)
    for column in frame.columns:
        series = frame[column]
        semantics = COLUMN_SEMANTICS.get(str(column), {})
        entry: dict[str, Any] = {
            "dtype": str(series.dtype),
            "meaning": semantics.get("meaning", "not documented"),
            "unit": semantics.get("unit", "1"),
            "is_label": bool(semantics.get("label", False)),
            "missing_rate": float(series.isna().sum() / rows),
            "n_unique": _safe_nunique(series),
        }
        numeric = pd.to_numeric(series, errors="coerce")
        if numeric.notna().any():
            entry["min"] = float(numeric.min())
            entry["max"] = float(numeric.max())
            entry["mean"] = float(numeric.mean())
        else:
            values = series.dropna().astype(str)
            if entry["n_unique"] <= 12 and not values.empty:
                entry["value_counts"] = {str(k): int(v) for k, v in
                                         values.value_counts().items()}
            entry["min"] = None
            entry["max"] = None
        out[str(column)] = entry
    return out


def _array_stats(array: np.ndarray) -> dict[str, Any]:
    data = np.asarray(array)
    entry: dict[str, Any] = {"shape": list(data.shape), "dtype": str(data.dtype),
                             "nbytes": int(data.nbytes)}
    if data.size == 0:
        return entry
    if data.dtype == bool:
        entry["true_rate"] = float(data.mean())
    elif np.issubdtype(data.dtype, np.floating):
        finite = np.isfinite(data)
        entry["missing_rate"] = float(1.0 - finite.mean())
        entry["nonzero_rate"] = float(np.count_nonzero(data) / data.size)
        if finite.any():
            entry["min"] = float(data[finite].min())
            entry["max"] = float(data[finite].max())
            entry["mean"] = float(data[finite].mean())
    elif np.issubdtype(data.dtype, np.integer):
        entry["nonzero_rate"] = float(np.count_nonzero(data) / data.size)
        entry["min"] = int(data.min())
        entry["max"] = int(data.max())
        entry["n_unique"] = int(np.unique(data).size)
    return entry


def _token_rank(tokens: np.ndarray) -> dict[str, Any]:
    """Effective rank of a token block: the measurement that exposed defect D1."""
    matrix = np.asarray(tokens, dtype=np.float64)
    if matrix.ndim != 2 or matrix.size == 0:
        return {"shape": list(matrix.shape), "effective_rank": None,
                "reason": "empty token block"}
    n, columns = matrix.shape
    singular = np.linalg.svd(matrix, compute_uv=False)
    first = matrix[:, 0]
    predicted = first[:, None] * (1.0 - 1e-6 * np.arange(columns))[None, :]
    return {
        "shape": [int(n), int(columns)],
        "sv0": float(singular[0]),
        "sv1": float(singular[1]) if singular.size > 1 else 0.0,
        "sv1_over_sv0": float(singular[1] / singular[0]) if singular.size > 1 and singular[0] else 0.0,
        "effective_rank_1e-6": int((singular > singular[0] * 1e-6).sum()),
        "columns_equal_to_scaled_column0": int(np.count_nonzero(
            np.abs(matrix - predicted).max(axis=0) <= 1e-6)),
        "max_abs_error_vs_scaled_broadcast": float(np.abs(matrix - predicted).max()),
        "broadcast_defect_present": bool(np.abs(matrix - predicted).max() <= 1e-5),
    }


def scan_package(package: str | Path, *, hash_files: bool = True,
                 array_fragments: int | None = None, token_fragments: int | None = None
                 ) -> dict[str, Any]:
    """Scan the package bytes and return everything a data card needs (all values measured)."""
    started = time.time()
    pkg = Package(package)
    manifest = pkg.manifest
    root = pkg.path

    # ---- files ---------------------------------------------------------------------
    files: list[dict[str, Any]] = []
    for entry in sorted(manifest.get("files", []), key=lambda e: str(e.get("path"))):
        relative = str(entry["path"])
        path = root / relative
        purpose = _purpose_for(relative)
        record: dict[str, Any] = {
            "path": relative, "format": _file_format(relative),
            "bytes": int(path.stat().st_size) if path.exists() else None,
            "manifest_hash": entry.get("hash"),
            "sha256": (sha256_file(path) if hash_files and path.exists() else None),
            "purpose": purpose["purpose"], "unit": purpose["unit"], "frame": purpose["frame"],
            "view": "deploy" if relative.startswith("deploy/") else
                    ("research" if relative.startswith("research/") else "package"),
        }
        if path.exists() and relative.endswith(".parquet"):
            record.update(_table_shape(path))
        elif path.exists() and relative.endswith(".npz"):
            record.update(_npz_shape(path))
        elif path.exists() and relative.endswith(".tar"):
            record.update(_tar_shape(path))
        files.append(record)
    declared = {str(e["path"]) for e in manifest.get("files", [])}
    on_disk = {str(p.relative_to(root)).replace("\\", "/") for p in root.rglob("*") if p.is_file()}
    extras = sorted(on_disk - declared)
    missing = sorted(declared - on_disk)
    hashes_ok = all(record["sha256"] is None or record["sha256"] == record["manifest_hash"]
                    for record in files)

    # ---- tables --------------------------------------------------------------------
    tables: dict[str, Any] = {}
    for relative in sorted(p for p in declared if p.endswith(".parquet")):
        frame = pd.read_parquet(root / relative)
        tables[relative] = {"rows": int(frame.shape[0]),
                            "columns": _column_stats(frame)}

    # ---- splits --------------------------------------------------------------------
    splits = _split_report(pkg)

    # ---- labels --------------------------------------------------------------------
    labels = _label_report(pkg)

    # ---- arrays --------------------------------------------------------------------
    arrays: dict[str, Any] = {"geometry": {}, "tokens": {}, "obs": {}, "zarr": {}}
    geometry_ids = list((pkg.geometry_index.get("rows") or {}).keys())
    token_ids = list((pkg.token_index.get("rows") or {}).keys())
    obs_ids = list((pkg.obs_index.get("rows") or {}).keys())
    for fragment_id in (geometry_ids[:array_fragments] if array_fragments else geometry_ids):
        entry = (pkg.geometry_index.get("rows") or {})[fragment_id]
        with np.load(root / "deploy" / entry["shard"], allow_pickle=False) as data:
            arrays["geometry"][fragment_id] = {
                name[len(entry["opaque"]) + 2:]: _array_stats(data[name])
                for name in data.files if name.startswith(f"{entry['opaque']}__")}
        arrays["zarr"][fragment_id] = {
            name: _array_stats(values) for name, values in pkg.zarr_arrays(fragment_id).items()}
    for fragment_id in (token_ids[:token_fragments] if token_fragments else token_ids):
        entry = (pkg.token_index.get("rows") or {})[fragment_id]
        with np.load(root / "deploy" / entry["shard"], allow_pickle=False) as data:
            arrays["tokens"][fragment_id] = {
                name[len(entry["opaque"]) + 2:]: _array_stats(data[name])
                for name in data.files if name.startswith(f"{entry['opaque']}__")}
            arrays["tokens"][fragment_id]["tokens"]["effective_rank"] = _token_rank(
                data[f"{entry['opaque']}__tokens"])
    for fragment_id in obs_ids:
        shard = pkg.obs_index["rows"][fragment_id]["shard"]
        with tarfile.open(root / "deploy" / shard, "r") as tar:
            collected = {}
            for name, values in pkg.obs_arrays(fragment_id).items():
                collected[name] = _array_stats(values)
            arrays["obs"][fragment_id] = collected

    return {
        "schema": "synlab.package_scan.v1",
        "package_dir": str(root),
        "seconds": time.time() - started,
        "manifest_schema": manifest.get("schema"),
        "package_schema": manifest.get("package_schema"),
        "package_id": manifest.get("package_id"),
        "release_id": manifest.get("release_id"),
        "release_manifest_hash": manifest.get("release_manifest_hash"),
        "manifest_hash": manifest.get("manifest_hash"),
        "bytes_total": manifest.get("bytes_total"),
        "counts": _jsonable(manifest.get("counts") or {}),
        "counts_total": manifest.get("counts_total"),
        "views": _jsonable(manifest.get("views") or {}),
        "files": files,
        "files_extra": extras,
        "files_missing": missing,
        "hashes_match_manifest": bool(hashes_ok),
        # a sampled scan is declared as sampled: the file list and every hash are always complete,
        # the per-array statistics may be limited to the first N fragments per family.
        "sampling": {
            "hash_all_files": bool(hash_files),
            "array_fragments_limit": (int(array_fragments) if array_fragments else None),
            "array_fragments_measured": {
                "geometry": len(arrays["geometry"]), "tokens": len(arrays["tokens"]),
                "obs": len(arrays["obs"]),
                "fragments_present": {"geometry": len(geometry_ids), "tokens": len(token_ids),
                                      "obs": len(obs_ids)}},
            "note": ("a None limit means every fragment of that family was measured; the column "
                     "statistics are always complete"),
        },
        "tables": tables,
        "splits": splits,
        "labels": labels,
        "arrays": arrays,
        "indexes": {
            "obs": _jsonable(pkg.obs_index),
            "geometry": _jsonable(pkg.geometry_index),
            "tokens": _jsonable(pkg.token_index),
        },
        "governance": {
            "label_layers": pkg.label_layers,
            "release_gates": _jsonable(manifest.get("release_gates") or {}),
            "release_profile": manifest.get("release_profile"),
            "release_scope": manifest.get("release_scope"),
            "reference_closure": _jsonable(manifest.get("reference_closure") or {}),
            "token_cache": _jsonable(manifest.get("token_cache") or {}),
            "separation": {
                "features_carry_answer_fields": (manifest.get("separation") or {}).get(
                    "features_carry_answer_fields"),
                "deploy_truth_files": len((manifest.get("separation") or {}).get(
                    "deploy_truth_files") or []),
                "answer_field_hits": _jsonable(
                    ((manifest.get("separation") or {}).get("answer_field_scan") or {}).get("hits")
                    or []),
                # names the view channel policy declares as acquisition context
                # (evidence_class=capture_context); reported separately from the answer hits so
                # the exemption is visible in the card instead of vanishing from it
                "exempt_capture_context_fields": _jsonable(
                    ((manifest.get("separation") or {}).get("answer_field_scan") or {}).get(
                        "exempt_capture_context_fields") or []),
                "capture_context_hits": _jsonable(
                    ((manifest.get("separation") or {}).get("capture_context_scan") or {}).get(
                        "hits") or []),
                "capture_context_source": _jsonable(
                    ((manifest.get("separation") or {}).get("capture_context_scan") or {}).get(
                        "declaration_source") or {}),
                "statement": (manifest.get("separation") or {}).get("statement"),
            },
        },
    }


def _split_report(pkg: Package) -> dict[str, Any]:
    """Lineage-level split assignment and the leakage checks that must hold.

    An unreadable table is reported as a problem instead of raising: ``--check`` exists to report
    an inconsistent package, and a corrupt parquet is exactly that.
    """
    report: dict[str, Any] = {"by_split": {}, "lineages": {}, "fragments": {},
                              "problems": [], "source": "research/relations.parquet + labels"}
    lineage_split: dict[str, set[str]] = {}
    fragment_split: dict[str, set[str]] = {}

    def _safe(name: str, getter: Any) -> pd.DataFrame:
        try:
            return getter()
        except Exception as exc:                          # noqa: BLE001 - the failure is the fact
            report["problems"].append(f"{name}: unreadable ({type(exc).__name__}: "
                                      f"{str(exc).splitlines()[0][:120]})")
            return pd.DataFrame()

    frames = [("relations", _safe("relations", lambda: pkg.relations))]
    frames += [(layer, _safe(f"labels/{layer}", lambda layer=layer: pkg.labels(layer)))
               for layer in pkg.label_layers]
    for name, frame in frames:
        if frame.empty or "split" not in frame.columns:
            continue
        lineage_column = ("lineage_cluster" if "lineage_cluster" in frame.columns
                          else ("lineage" if "lineage" in frame.columns else None))
        fragment_column = next((c for c in ("fragment_id", "query", "fragment_a")
                                if c in frame.columns), None)
        for _, row in frame.iterrows():
            split = str(row.get("split") or "")
            if not split:
                continue
            report["by_split"].setdefault(split, {"rows": 0, "tables": {}})
            report["by_split"][split]["rows"] += 1
            report["by_split"][split]["tables"][name] = \
                report["by_split"][split]["tables"].get(name, 0) + 1
            if lineage_column:
                lineage = str(row.get(lineage_column) or "")
                if lineage:
                    lineage_split.setdefault(lineage, set()).add(split)
            if fragment_column:
                fragment = str(row.get(fragment_column) or "")
                if fragment:
                    fragment_split.setdefault(fragment, set()).add(split)
    report["lineages"] = {name: sorted(splits) for name, splits in sorted(lineage_split.items())}
    report["fragments"] = {name: sorted(splits) for name, splits in sorted(fragment_split.items())}
    report["by_split"] = {
        split: {"rows": entry["rows"], "tables": entry["tables"],
                "lineages": sum(1 for v in lineage_split.values() if v == {split}),
                "fragments": sum(1 for v in fragment_split.values() if v == {split})}
        for split, entry in sorted(report["by_split"].items())}
    for name, splits in report["lineages"].items():
        if len(splits) > 1:
            report["problems"].append(f"lineage {name} appears in splits {sorted(splits)}")
    for name, splits in report["fragments"].items():
        if len(splits) > 1:
            report["problems"].append(f"fragment {name} appears in splits {sorted(splits)}")
    report["leak_free"] = not report["problems"]
    return report


def _label_report(pkg: Package) -> dict[str, Any]:
    relations = pkg.relations
    report: dict[str, Any] = {"relation_kinds": {}, "eligible_as_negative": 0,
                              "layers": {}, "label_source": {}}
    if not relations.empty:
        report["relation_kinds"] = {str(k): int(v) for k, v in
                                    relations["kind"].value_counts().items()}
        if "eligible_as_negative" in relations.columns:
            report["eligible_as_negative"] = int(
                relations["eligible_as_negative"].astype(bool).sum())
        if "valid" in relations.columns:
            report["valid_rows"] = int(relations["valid"].astype(bool).sum())
        if "loss_mask" in relations.columns:
            report["loss_masked_rows"] = int(relations["loss_mask"].astype(bool).sum())
        if {"kind", "valid", "loss_mask"} <= set(relations.columns):
            legal = relations[(relations["kind"].isin(["R1", "R0"]))
                              & relations["valid"].astype(bool)
                              & relations["loss_mask"].astype(bool)]
            report["legal_negative_rows"] = int(legal.shape[0])
    for layer in pkg.label_layers:
        frame = pkg.labels(layer)
        entry: dict[str, Any] = {"rows": int(frame.shape[0]),
                                 "columns": [str(c) for c in frame.columns]}
        if "kind" in frame.columns:
            entry["kind_counts"] = {str(k): int(v) for k, v in
                                    frame["kind"].value_counts().items()}
        if "reason" in frame.columns and not frame.empty:
            reasons = frame["reason"].dropna().astype(str)
            top = reasons.value_counts().head(6)
            entry["reason_counts"] = {str(k): int(v) for k, v in top.items()}
        if "valid" in frame.columns:
            entry["valid_rows"] = int(frame["valid"].astype(bool).sum())
        if "loss_mask" in frame.columns:
            entry["loss_masked_rows"] = int(frame["loss_mask"].astype(bool).sum())
        if "split" in frame.columns:
            entry["splits"] = {str(k): int(v) for k, v in frame["split"].value_counts().items()}
        report["layers"][layer] = entry
    for entry in (pkg.manifest.get("labels") or []):
        report["label_source"][str(entry.get("layer"))] = {
            "path": entry.get("path"), "rows": entry.get("rows"),
            "assets": list(entry.get("assets") or [])}
    report["supervision_labels"] = _jsonable(pkg.manifest.get("supervision_labels") or {})
    return report


# --------------------------------------------------------------------------------------
# supervision table (five tasks, real n_valid / n_allowed)
# --------------------------------------------------------------------------------------
def supervision_table(built: Mapping[str, Any]) -> dict[str, Any]:
    """Per-task ``n_valid`` / ``n_allowed`` / blockers of a real batch (single source of truth)."""
    supervision = built.get("supervision") or {}
    tasks = supervision.get("tasks") or {}
    reason = str(supervision.get("reason") or "")
    table: dict[str, Any] = {}
    for name in TASKS:
        entry = tasks.get(name)
        if entry is None:
            # no pair batch at all (the fragment subset names no relation row): say that instead
            # of a bare "missing", and point at the package-level counts.
            table[name] = {
                "n_valid": "not_applicable", "n_allowed": "not_applicable",
                "blocked_by": [reason] if reason else [],
                "applicable": False,
                "why": reason or "the batch builder reported nothing for this task",
                "unlock_condition": [
                    "build a batch whose fragments include both endpoints of an exported "
                    "relation row (see --batch-fragments / iter_batches)",
                ],
                "evidence": {"batch_has_rows": bool(built.get("rows"))},
            }
            continue
        structural = entry.get("structural") or {}
        table[name] = {
            "n_valid": int(entry.get("n_valid", 0)),
            "n_allowed": int(entry.get("n_allowed", 0)),
            "blocked_by": list(entry.get("blocked_by") or []),
            "applicable": bool(structural.get("applicable", True)),
            "why": ("supervised" if int(entry.get("n_allowed", 0)) > 0
                    else (structural.get("reason") or
                          (entry.get("blocked_by") or ["unknown"])[0])),
            "unlock_condition": list(structural.get("unlock_condition") or []),
            "evidence": _jsonable(entry.get("evidence") or {}),
        }
    table["_pair_mask"] = _jsonable(supervision.get("pair_mask"))
    table["_z_valid_fragments"] = int(np.count_nonzero(built["z_valid"]))
    table["_tasks_with_supervision"] = list(supervision.get("tasks_with_supervision") or [])
    return table


# --------------------------------------------------------------------------------------
# data card
# --------------------------------------------------------------------------------------
def build_data_card(package: str | Path, *, hash_files: bool = True,
                    sample_fragments: int | None = None,
                    batch_fragments: int | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Scan the package, build a real batch and assemble the data card (returns card + scan)."""
    scan = scan_package(package, hash_files=hash_files, array_fragments=sample_fragments,
                        token_fragments=sample_fragments)
    probe = Package(package)
    batch_ids = probe.fragment_ids()
    sampled_batch = bool(batch_fragments)
    if batch_fragments:
        # A very large package can not be stacked in one process (its per-fragment RGB is hundreds
        # of MB); the card then measures a declared subset instead of failing.  The subset is taken
        # **pair-wise** from the relation table (a pair batch needs both endpoints of at least one
        # row), preferring fragments that carry an observation -- otherwise the card would report
        # "no supervision" for a package that has some, just not among its first N fragments.
        limit = int(batch_fragments)
        observed = set(probe.obs_index.get("rows") or {})
        ordered: list[str] = []

        def add(fragment_id: str) -> None:
            if fragment_id and fragment_id not in ordered:
                ordered.append(fragment_id)

        pairs: list[tuple[str, str]] = []
        if not probe.relations.empty and {"query", "candidate"} <= set(probe.relations.columns):
            pairs = [(str(a), str(b)) for a, b in zip(probe.relations["query"],
                                                     probe.relations["candidate"])]
        # pairs first: a pair batch needs both endpoints of at least one exported relation row;
        # among the pairs, the ones with the most observed endpoints come first.
        pairs.sort(key=lambda pair: -((pair[0] in observed) + (pair[1] in observed)))
        for left, right in pairs:
            if len(ordered) >= limit:
                break
            add(left)
            add(right)
        for fragment_id in batch_ids:
            if len(ordered) >= limit:
                break
            if fragment_id in observed:
                add(fragment_id)
        batch_ids = ordered[:limit]
    built = build_batch(package, fragment_ids=batch_ids)
    pkg = built["package"]
    manifest = pkg.manifest
    identity = {
        "run_id": "missing",
        "run_id_reason": ("the package manifest carries no run_id (schema "
                          "synlab.training_package_manifest.v1); the producing store's runs table "
                          "is the only place it exists"),
        "release_id": manifest.get("release_id"),
        "package_id": manifest.get("package_id"),
        "git_head": git_head(),
        "registry": registry_fingerprint(),
        "exported_at_unix": float((pkg.path / "export_manifest.json").stat().st_mtime),
        "exported_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                         time.gmtime((pkg.path / "export_manifest.json").stat().st_mtime)),
        "spec_hash": "missing",
        "spec_hash_reason": ("no spec is embedded in a training package; the run's spec_hash "
                             "lives in the source store's runs table"),
        "manifest_hash": manifest.get("manifest_hash"),
        "release_manifest_hash": manifest.get("release_manifest_hash"),
        "release_profile": manifest.get("release_profile"),
        "release_scope": manifest.get("release_scope"),
        # which code produced / reads this package: pinned by hash, because "dirty" alone does
        # not say *which* writer wrote the bytes on disk.
        "writer": {
            "module": "synlab/storage/export.py",
            "sha256": (sha256_file(REPO_ROOT / "synlab/storage/export.py")
                       if (REPO_ROOT / "synlab/storage/export.py").is_file() else "missing"),
        },
        "loader": {
            "module": "tools/load_package.py",
            "sha256": sha256_file(Path(__file__)),
            "card_schema": CARD_SCHEMA,
        },
        "card_generated_at_unix": time.time(),
        "card_generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    card: dict[str, Any] = {
        "schema": CARD_SCHEMA,
        "generated_by": "tools/load_package.py (real scan of the package bytes)",
        "identity": identity,
        "package": {
            "path": scan["package_dir"],
            "schema": scan["package_schema"],
            "counts": scan["counts"],
            "bytes_total": scan["bytes_total"],
            "views": scan["views"],
            "files": scan["files"],
            "files_extra": scan["files_extra"],
            "files_missing": scan["files_missing"],
            "hashes_match_manifest": scan["hashes_match_manifest"],
            "card_artifacts": list(CARD_ARTIFACTS),
        },
        "columns": scan["tables"],
        "arrays": scan["arrays"],
        "array_dictionary": {name: entry for name, entry in ARRAY_SEMANTICS.items()},
        "splits": scan["splits"],
        "labels": scan["labels"],
        "tasks": _task_definitions(built, scan),
        "honest_boundaries": _honest_boundaries(pkg, scan, built),
        "governance": scan["governance"],
        "mini_batch": {
            "fragments_requested": len(batch_ids),
            "sampled": sampled_batch,
            "shapes": batch_shapes(built),
            "provenance": built["provenance"],
            "note": ("built with synlab.qc.loader_probe + synlab.training.batch, the same code "
                     "path synlab.training.smoke uses; no torch and no synthetic row"),
        },
    }
    card["package"]["file_count_on_disk"] = len(scan["files"]) + len(scan["files_extra"])
    return card, scan


def _task_definitions(built: Mapping[str, Any], scan: Mapping[str, Any]) -> dict[str, Any]:
    table = supervision_table(built)
    relations = scan["tables"].get("research/relations.parquet", {}).get("columns", {})
    definitions = {
        "view": {
            "inputs": ["deploy/obs/shard_*/<opaque>/tiles.npy (RGB views)",
                       "deploy/obs/shard_*/<opaque>/view_pos.npy"],
            "supervision": "self-supervised across the delivered views of one fragment "
                           "(>=2 valid views anchor a contrastive row)",
            "loss_mask": "global_valid per view; a fragment with fewer than two valid views "
                         "contributes no anchor",
            "why": "the delivered RGB itself; no label file is read",
        },
        "rank": {
            "inputs": ["deploy/tokens/shard_*.npz (<opaque>__tokens)",
                       "deploy/geometry/shard_*.npz (points/normals/*_valid/scale_valid)"],
            "supervision": ["research/relations.parquet kind=R2 & valid -> positive pair",
                            "research/relations.parquet kind in {R1,R0} & valid & loss_mask -> "
                            "legal negative"],
            "loss_mask": "allowed = z_valid[query] & z_valid[candidate] & pair_valid; UNKNOWN "
                         "never enters a loss and is never rewritten into R0",
            "why": "relation table + encodability of both sides",
            "columns_used": ["query", "candidate", "kind", "valid", "loss_mask"],
        },
        "correspondence": {
            "inputs": ["deploy/tokens/shard_*.npz (token space the weights live in)"],
            "supervision": ["research/labels/correspondence.parquet (index_a/index_b/weight/"
                            "residual_mm/ambiguous/sample_valid)"],
            "loss_mask": "corr_weight > 0 anchored through the token mapping, then the same "
                         "`allowed` pair mask",
            "why": "many-to-many surface correspondence of the cut faces",
        },
        "quality": {
            "inputs": ["deploy/obs (delivered observation; observation-side quality estimate)"],
            "supervision": ["research/labels/quality.parquet target_value (label-side "
                            "observability rate per fragment x view)"],
            "loss_mask": "valid per row; a fragment without a measurement stays invalid and is "
                         "*not* a zero target",
            "why": "how much of the fragment's surface a view really shows",
            "target_channel": "observability_visible_rate",
        },
        "contradiction": {
            "inputs": ["deploy tokens/geometry of both sides of a pair"],
            "supervision": ["research/relations.parquet (kind/label_pair_valid) -> the pair "
                            "compatibility class"],
            "loss_mask": "contradiction_valid from the pair labels, then the same `allowed` mask "
                         "(the head is supervised on pair logits, so both sides must encode)",
            "why": "whether two fragments' evidence can belong to one body",
        },
    }
    for name in TASKS:
        definitions[name]["measured"] = table.get(name)
    definitions["_table"] = table
    definitions["_relation_columns_present"] = sorted(relations.keys())
    return definitions


def _honest_boundaries(pkg: Package, scan: Mapping[str, Any],
                       built: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Known defects / unavailable items: current value, impact, unlock condition."""
    boundaries: list[dict[str, Any]] = []
    labels = scan["labels"]
    eligible = int(labels.get("eligible_as_negative", 0))
    relations_empty = not labels.get("relation_kinds")
    boundaries.append({
        "id": "no_legal_negatives",
        "current_value": {"eligible_as_negative": eligible,
                          "relation_kinds": labels.get("relation_kinds", {}),
                          "legal_negative_rows": labels.get("legal_negative_rows", 0)},
        "impact": ("the rank task cannot start: a positive without a legal negative yields no "
                   "gradient (effective_queries = 0)"),
        "status": "not_applicable" if eligible == 0 else "available",
        "unlock_condition": ("export confirmed R1/R0 rows with valid=true and loss_mask=true "
                             "between two fragments that both carry an observation"),
    })
    if relations_empty:
        boundaries.append({
            "id": "no_relation_rows",
            "current_value": {"relations": 0},
            "impact": "no pair-shaped task (rank/contradiction) exists in this package",
            "status": "not_applicable",
            "unlock_condition": "export the release's relation table",
        })

    # D1 tokens
    ranks = [entry.get("tokens", {}).get("effective_rank", {})
             for entry in scan["arrays"]["tokens"].values()]
    ranks = [r for r in ranks if r]
    broadcast = [r for r in ranks if r.get("broadcast_defect_present")]
    boundaries.append({
        "id": "tokens_broadcast_defect",
        "current_value": {
            "fragments_measured": len(ranks),
            "fragments_with_scaled_broadcast": len(broadcast),
            "max_sv1_over_sv0": (max((r["sv1_over_sv0"] for r in ranks), default=None)),
            "min_effective_rank": (min((r["effective_rank_1e-6"] for r in ranks), default=None)),
            "token_dim_declared": (scan["indexes"]["tokens"] or {}).get("token_dim"),
            "encoder_id": (scan["indexes"]["tokens"] or {}).get("encoder_id"),
        },
        "impact": ("a token block whose columns are scaled copies of one scalar carries the "
                   "information of one number per token; any layer that treats it as a 256-dim "
                   "feature is reading a placeholder"),
        "status": "defect_present" if broadcast else "fixed_in_this_package",
        "unlock_condition": ("re-export with the fixed writer "
                             "(synlab/storage/export.py::_token_arrays, per-token sub-grid means) "
                             "or use token_input"),
    })

    # D2 view_pos
    view_pos = [entry.get("view_pos", {}) for entry in scan["arrays"]["obs"].values()]
    zero_arrays = [v for v in view_pos if v and v.get("nonzero_rate") == 0.0]
    # the writer's index flag pools every delivered view; what a consumer needs to know is
    # whether the value varies *inside* one fragment (a turntable rig keeps the slide fixed).
    per_fragment = []
    for fragment_id, entry in scan["arrays"]["obs"].items():
        stats = entry.get("view_pos") or {}
        low, high = stats.get("min"), stats.get("max")
        per_fragment.append({
            "fragment": fragment_id,
            "views": (stats.get("shape") or [None])[0],
            "min": low, "max": high,
            "varies_within_fragment": (low is not None and high is not None and high != low),
        })
    boundaries.append({
        "id": "view_pos_all_zero",
        "current_value": {"delivered_views": sum(int(v.get("shape", [0])[0]) for v in view_pos
                                                 if v.get("shape")),
                          "arrays_all_zero": len(zero_arrays),
                          "sources": sorted({str((scan["indexes"]["obs"].get("rows") or {})
                                                 .get(fid, {}).get("view_pos_source"))
                                             for fid in scan["arrays"]["obs"]}),
                          "per_fragment": per_fragment,
                          "index_block": (scan["indexes"]["obs"] or {}).get("view_pos")},
        "impact": ("the declared camera-slip channel carries no information when it is all zero, "
                   "so a model can not condition on the viewpoint from it; when it is real but "
                   "constant inside a fragment (turntable rig: the camera stays on the slide "
                   "axis) it is honest but still not a view identifier -- use frame_id for that"),
        "status": "defect_present" if zero_arrays else "fixed_in_this_package",
        "unlock_condition": ("re-export with the fixed writer (view_pos from the delivered T_WC) "
                             "or delete the channel from the observation index; a *varying* "
                             "viewpoint channel needs either a slide-moving rig or a new channel "
                             "in synlab/schemas/view_channels.json"),
    })

    # D3 frame_id
    frame_ids = [entry.get("frame_id", {}) for entry in scan["arrays"]["geometry"].values()]
    mismatched = [f for f in frame_ids
                  if f.get("n_unique") is not None and f.get("n_unique") > 0
                  and f.get("min") is not None and f.get("min") < 0]
    boundaries.append({
        "id": "frame_id_row_counter",
        "current_value": {
            "fragments_measured": len(frame_ids),
            "index_sources": sorted({str(entry.get("frame_id_source"))
                                     for entry in (scan["indexes"]["geometry"].get("rows")
                                                   or {}).values()}),
            "index_block": (scan["indexes"]["geometry"] or {}).get("frame_id"),
            "unmatched_fragments": len(mismatched),
        },
        "impact": ("frame_id == arange(n) % n_views is a function of the row index: it carries "
                   "no viewpoint information and misleads any per-view pooling"),
        "status": ("fixed_in_this_package"
                   if (scan["indexes"]["geometry"] or {}).get("frame_id") else "defect_present"),
        "unlock_condition": ("re-export with the fixed writer (frame_id from K/T_WC/depth_z) or "
                             "drop the array from the geometry index"),
    })

    # delivery-side gaps that the scan can see
    obs = scan["arrays"]["obs"]
    valid_rates = [entry["valid"]["true_rate"] for entry in obs.values()
                   if entry.get("valid", {}).get("true_rate") is not None]
    boundaries.append({
        "id": "deployment_mask_sparse",
        "current_value": {"per_fragment_true_rate": valid_rates,
                          "min": min(valid_rates) if valid_rates else None,
                          "max": max(valid_rates) if valid_rates else None},
        "impact": ("the deployment mask is very sparse and uneven across views, so a view may "
                   "contribute almost no pixels; per-pixel losses are dominated by the mask"),
        "status": "measured",
        "unlock_condition": ("raise the delivered foreground fraction (or deliver the mask "
                             "contract the deployment profile really has)"),
    })
    unknown_columns = []
    for path, table in scan["tables"].items():
        for name, entry in table["columns"].items():
            if entry["meaning"] == "not documented":
                unknown_columns.append(f"{path}:{name}")
    boundaries.append({
        "id": "undocumented_columns",
        "current_value": {"columns_without_semantics": sorted(unknown_columns)},
        "impact": "a consumer can not tell unit/meaning for those columns without the source",
        "status": "measured" if unknown_columns else "complete",
        "unlock_condition": "add the column to tools/load_package.COLUMN_SEMANTICS",
    })
    channels = (scan["indexes"]["obs"] or {}).get("channel_names")
    if channels:
        core = {"tiles", "valid", "view_pos"}
        boundaries.append({
            "id": "deploy_view_channels",
            "current_value": {"channels": channels,
                              "beyond_core": sorted(set(channels) - core)},
            "impact": ("channels beyond tiles/valid/view_pos are policy-granted inputs; each one "
                       "carries its own evidence_class/caveat in deploy/obs/index.json"),
            "status": "measured",
            "unlock_condition": ("change synlab/schemas/view_channels.json (the policy is data; "
                                 "the manifest records its path and hash)"),
        })

    # the writer's own separation scan: an answer-side field name inside the deployment view is a
    # real finding, reported here as measured (this loader does not re-run the scan, it reads the
    # manifest's measurement of the bytes that were written).
    separation = scan["governance"].get("separation") or {}
    answer_hits = list(separation.get("answer_field_hits") or [])
    if separation.get("features_carry_answer_fields") or answer_hits:
        boundaries.append({
            "id": "deploy_view_answer_field_hit",
            "current_value": {"features_carry_answer_fields": separation.get(
                "features_carry_answer_fields"),
                "hits": answer_hits,
                "deploy_contains_truth": (scan["views"].get("deploy") or {}).get(
                    "contains_truth")},
            "impact": ("a field whose name is in roles.FORBIDDEN_FEATURE_FIELDS appears inside the "
                       "deployment view; whoever ships deploy/ alone ships that field"),
            "status": "defect_present",
            "unlock_condition": ("remove the field from the deployment view, or record it as an "
                                 "explicitly permitted acquisition-context field with its own "
                                 "evidence_class in the policy document"),
        })
    if not built["rows"]:
        boundaries.append({
            "id": "no_query_rows",
            "current_value": {"rows": 0},
            "impact": "no batch can be sampled: the package has no query row to rank",
            "status": "not_applicable",
            "unlock_condition": "export a query roster (deploy/queries.parquet) with real queries",
        })
    return boundaries


# --------------------------------------------------------------------------------------
# README rendering + verification
# --------------------------------------------------------------------------------------
def _fmt_bytes(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "missing"
    for unit in ("B", "KiB", "MiB", "GiB"):
        if number < 1024 or unit == "GiB":
            return f"{number:,.1f} {unit}" if unit != "B" else f"{int(number)} B"
        number /= 1024
    return f"{number}"                                                       # pragma: no cover


def render_readme(card: Mapping[str, Any]) -> str:
    identity = card["identity"]
    package = card["package"]
    tasks = card["tasks"]
    lines: list[str] = []
    lines.append(f"# Training package: {identity.get('release_id')}")
    lines.append("")
    lines.append("> Generated by `tools/load_package.py --write-card` from a real scan of this "
                 "directory.  Every number below is measured; anything unknown is written as "
                 "`missing` / `not_applicable` with the condition that would unlock it.")
    lines.append("")
    lines.append("## Identity")
    lines.append("")
    lines.append("| field | value |")
    lines.append("|---|---|")
    lines.append(f"| package_id | `{identity.get('package_id')}` |")
    lines.append(f"| release_id | `{identity.get('release_id')}` |")
    lines.append(f"| run_id | `{identity.get('run_id')}` |")
    lines.append(f"| git HEAD | `{(identity.get('git_head') or {}).get('head')}` "
                 f"(dirty: `{(identity.get('git_head') or {}).get('dirty')}`) |")
    lines.append(f"| REGISTRY.fingerprint() | `{(identity.get('registry') or {}).get('fingerprint')}` |")
    lines.append(f"| spec_hash | `{identity.get('spec_hash')}` |")
    lines.append(f"| exported at | {identity.get('exported_at_utc')} |")
    lines.append(f"| manifest_hash | `{identity.get('manifest_hash')}` |")
    lines.append(f"| release_manifest_hash | `{identity.get('release_manifest_hash')}` |")
    lines.append(f"| files / bytes | {package.get('file_count_on_disk')} / "
                 f"{_fmt_bytes(package.get('bytes_total'))} |")
    lines.append(f"| hashes match manifest | `{package.get('hashes_match_manifest')}` |")
    lines.append("")
    lines.append("## Files")
    lines.append("")
    lines.append("| path | format | rows/shape | bytes | sha256 | purpose | unit / frame |")
    lines.append("|---|---|---|---|---|---|---|")
    for entry in package["files"]:
        shape = entry.get("rows") if entry.get("rows") is not None else entry.get("n_arrays")
        if shape is None and entry.get("members") is not None:
            shape = f"{entry['members']} members"
        if shape is None and entry.get("shape") is None:
            arrays = entry.get("arrays")
            shape = (f"{len(arrays)} arrays" if isinstance(arrays, dict) else None)
        lines.append(f"| `{entry['path']}` | {entry['format']} | {shape if shape is not None else '—'} "
                     f"| {entry.get('bytes')} | `{(entry.get('sha256') or '—')[:22]}` "
                     f"| {entry['purpose']} | {entry['unit']} / {entry['frame']} |")
    if package.get("files_extra"):
        lines.append("")
        lines.append(f"Files present but not declared by the manifest: "
                     f"`{', '.join(package['files_extra'])}`")
    lines.append("")
    lines.append("## Supervised tasks")
    lines.append("")
    lines.append("| task | inputs | supervision | loss_mask | n_valid | n_allowed | why |")
    lines.append("|---|---|---|---|---|---|---|")
    for name in TASKS:
        entry = tasks[name]
        measured = entry.get("measured") or {}
        lines.append(f"| {name} | {', '.join(entry['inputs'])} | "
                     f"{'; '.join(entry['supervision']) if isinstance(entry['supervision'], list) else entry['supervision']} "
                     f"| {entry['loss_mask']} | {measured.get('n_valid')} "
                     f"| {measured.get('n_allowed')} | {measured.get('why')} |")
    lines.append("")
    lines.append("## Splits (lineage level)")
    lines.append("")
    lines.append("| split | rows | lineages | fragments |")
    lines.append("|---|---|---|---|")
    for split, entry in (card["splits"].get("by_split") or {}).items():
        lines.append(f"| {split} | {entry['rows']} | {entry['lineages']} | {entry['fragments']} |")
    lines.append("")
    lines.append(f"Leak-free: `{card['splits'].get('leak_free')}`"
                 + (f" — problems: {card['splits'].get('problems')}"
                    if card["splits"].get("problems") else ""))
    lines.append("")
    lines.append("## Labels")
    lines.append("")
    lines.append(f"Relation kinds: `{card['labels'].get('relation_kinds')}`; "
                 f"eligible_as_negative: **{card['labels'].get('eligible_as_negative')}**")
    lines.append("")
    lines.append("| layer | rows | kinds | valid | loss-masked | source assets |")
    lines.append("|---|---|---|---|---|---|")
    for layer, entry in (card["labels"].get("layers") or {}).items():
        source = card["labels"]["label_source"].get(layer, {})
        lines.append(f"| {layer} | {entry['rows']} | `{entry.get('kind_counts', {})}` "
                     f"| {entry.get('valid_rows')} | {entry.get('loss_masked_rows')} "
                     f"| {len(source.get('assets') or [])} |")
    lines.append("")
    lines.append("## Honest boundaries")
    lines.append("")
    lines.append("| id | status | current value | impact | unlock condition |")
    lines.append("|---|---|---|---|---|")
    for entry in card["honest_boundaries"]:
        lines.append(f"| {entry['id']} | {entry['status']} | "
                     f"`{json.dumps(entry['current_value'], ensure_ascii=False)[:220]}` "
                     f"| {entry['impact']} | {entry['unlock_condition']} |")
    lines.append("")
    lines.append("## How to load it")
    lines.append("")
    lines.append("```powershell")
    lines.append("& .venv\\Scripts\\python.exe tools\\load_package.py --package "
                 f"\"{package['path']}\"")
    lines.append("& .venv\\Scripts\\python.exe tools\\load_package.py --package "
                 f"\"{package['path']}\" --check")
    lines.append("& .venv\\Scripts\\python.exe examples\\quickstart.py --package "
                 f"\"{package['path']}\"")
    lines.append("```")
    lines.append("")
    lines.append("```python")
    lines.append("from tools.load_package import load_relations, load_arrays, iter_batches")
    lines.append(f"relations = load_relations(r\"{package['path']}\")")
    lines.append(f"geometry = load_arrays(r\"{package['path']}\", kind=\"geometry\")")
    lines.append(f"for batch in iter_batches(r\"{package['path']}\", batch_size=2):")
    lines.append("    print(batch['index'], batch['provenance']['fragment_ids'])")
    lines.append("```")
    lines.append("")
    lines.append("The full machine-readable card is `dataset_card.json` next to this file.")
    lines.append("")
    return "\n".join(lines)


def check_package(package: str | Path) -> dict[str, Any]:
    """Independent verification of a package (used by ``--check``; exit 0 or 3).

    Checks: (1) file set vs manifest, (2) sha256 of every declared file, (3) the card's column
    dictionary vs the real parquet columns, (4) lineage/fragment split leakage.
    """
    pkg = Package(package)
    root = pkg.path
    manifest = pkg.manifest
    problems: list[str] = []
    checks: dict[str, Any] = {}

    declared = {str(entry["path"]): str(entry["hash"]) for entry in manifest.get("files", [])}
    on_disk = {str(p.relative_to(root)).replace("\\", "/") for p in root.rglob("*") if p.is_file()}
    missing = sorted(set(declared) - on_disk)
    extras = sorted(on_disk - set(declared))
    unexpected = [name for name in extras if name not in CARD_ARTIFACTS + ALWAYS_EXTRA]
    checks["file_set"] = {"declared": len(declared), "on_disk": len(on_disk),
                          "missing": missing, "extra": extras, "unexpected_extra": unexpected,
                          "ok": not missing and not unexpected}
    if missing:
        problems.append(f"{len(missing)} declared file(s) missing, e.g. {missing[:3]}")
    if unexpected:
        problems.append(f"undeclared file(s) present: {unexpected[:5]}")

    mismatched: list[str] = []
    for relative, expected in sorted(declared.items()):
        path = root / relative
        if not path.is_file():
            continue
        actual = hash_file(path)
        if actual != expected:
            mismatched.append(f"{relative}: {actual} != {expected}")
    checks["sha256"] = {"checked": len(declared) - len(missing), "mismatched": mismatched,
                        "ok": not mismatched}
    if mismatched:
        problems.append(f"{len(mismatched)} file hash mismatch(es): {mismatched[:3]}")

    card_path = root / CARD_NAME
    if card_path.is_file():
        card = json.loads(card_path.read_text(encoding="utf-8"))
        column_problems: list[str] = []
        for relative, table in (card.get("columns") or {}).items():
            path = root / relative
            if not path.is_file():
                column_problems.append(f"{relative}: declared in the card but absent")
                continue
            actual_columns: list[str] = []
            try:
                frame = pd.read_parquet(path)
                actual_columns = [str(c) for c in frame.columns]
                actual_rows = int(frame.shape[0])
            except Exception as exc:                    # noqa: BLE001 - unreadable *is* a problem
                column_problems.append(f"{relative}: unreadable ({type(exc).__name__}: "
                                       f"{str(exc).splitlines()[0][:120]})")
                continue
            declared_columns = [str(c) for c in (table.get("columns") or {}).keys()]
            if sorted(actual_columns) != sorted(declared_columns):
                column_problems.append(
                    f"{relative}: card {sorted(declared_columns)} != actual {sorted(actual_columns)}")
            rows = table.get("rows")
            if rows is not None and int(rows) != actual_rows:
                column_problems.append(f"{relative}: card rows {rows} != actual {actual_rows}")
        checks["column_dictionary"] = {"tables": len(card.get("columns") or {}),
                                       "problems": column_problems, "ok": not column_problems}
        if column_problems:
            problems.append(f"column dictionary mismatch: {column_problems[:3]}")
        card_files = {entry["path"] for entry in (card.get("package") or {}).get("files", [])}
        if card_files - set(declared):
            problems.append("the card lists files the manifest does not declare")
    else:
        checks["column_dictionary"] = {"ok": False, "problems": [f"{CARD_NAME} absent"],
                                       "note": "run --write-card to generate it"}
        problems.append(f"{CARD_NAME} is absent: no column dictionary to verify against")

    splits = _split_report(pkg)
    checks["splits"] = {"leak_free": splits["leak_free"], "problems": splits["problems"],
                        "by_split": splits["by_split"], "ok": bool(splits["leak_free"])}
    if splits["problems"]:
        problems.extend(splits["problems"][:5])

    verdict = {
        "schema": "synlab.package_check.v1",
        "package": str(root),
        "checks": checks,
        "problems": problems,
        "ok": not problems,
        "exit_code": EXIT_OK if not problems else EXIT_INCONSISTENT,
    }
    return verdict


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------
def _print_summary(card: Mapping[str, Any], built: Mapping[str, Any], scan: Mapping[str, Any]
                   ) -> None:
    identity = card["identity"]
    package = card["package"]
    print(f"package      : {package['path']}")
    print(f"release_id   : {identity.get('release_id')}   package_id: {identity.get('package_id')}")
    print(f"git HEAD     : {(identity.get('git_head') or {}).get('head')} "
          f"(dirty={((identity.get('git_head') or {}).get('dirty'))})")
    print(f"REGISTRY.fp  : {(identity.get('registry') or {}).get('fingerprint')}")
    print(f"run_id       : {identity.get('run_id')}   spec_hash: {identity.get('spec_hash')}")
    print(f"files/bytes  : {package['file_count_on_disk']} files, "
          f"{_fmt_bytes(package['bytes_total'])}, hashes_match_manifest="
          f"{package['hashes_match_manifest']}")
    print(f"counts       : {json.dumps(scan['counts'], ensure_ascii=False)}")
    print(f"relations    : {json.dumps(card['labels'].get('relation_kinds'), ensure_ascii=False)}"
          f"  eligible_as_negative={card['labels'].get('eligible_as_negative')}")
    print(f"label layers : {', '.join((card['labels'].get('layers') or {}).keys()) or '(none)'}")
    print(f"splits       : leak_free={card['splits'].get('leak_free')} "
          f"{json.dumps({k: {'rows': v['rows'], 'lineages': v['lineages']} for k, v in (card['splits'].get('by_split') or {}).items()}, ensure_ascii=False)}")
    print()
    print("per-task supervision (real batch, trainer's own masks):")
    print(f"  {'task':<15}{'n_valid':>9}{'n_allowed':>11}  why")
    for name in TASKS:
        entry = (card["tasks"][name].get("measured") or {})
        print(f"  {name:<15}{str(entry.get('n_valid')):>9}{str(entry.get('n_allowed')):>11}  "
              f"{entry.get('why')}")
    print()
    print("mini-batch (real, built from this package):")
    shapes = card["mini_batch"]["shapes"]
    for name in ("global_rgb", "pixel_valid", "local_tokens", "token_view", "points", "normals",
                 "scale_valid"):
        entry = shapes["features"].get(name)
        if entry:
            print(f"  feature {name:<14} {str(entry['shape']):<22} {entry['dtype']}")
    for name in ("pair_index", "pair_valid", "pos_mask", "neg_mask", "labels_relation",
                 "quality_target", "corr_weight", "contradiction"):
        entry = shapes["labels"].get(name)
        if entry:
            print(f"  label   {name:<14} {str(entry['shape']):<22} {entry['dtype']}")
    print(f"  fragments={shapes['fragments']} observed={shapes['observed_fragments']} "
          f"positives={shapes.get('positives')} negatives={shapes.get('negatives')} "
          f"effective_queries={shapes.get('effective_queries')}")
    provenance = card["mini_batch"]["provenance"]
    print(f"  source  : relations={provenance['relations_parquet']} "
          f"queries={provenance['queries_parquet']} tokens={provenance['tokens_npz']} "
          f"geometry={provenance['geometry_npz']} obs={provenance['obs_tar']}")
    print(f"  fragment_ids: {provenance['fragment_ids']}")
    print()
    print("honest boundaries:")
    for entry in card["honest_boundaries"]:
        print(f"  - {entry['id']:<28} {entry['status']:<22} "
              f"{json.dumps(entry['current_value'], ensure_ascii=False)[:150]}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--package", required=True, help="training package directory")
    parser.add_argument("--check", action="store_true",
                        help="verify the package independently; exit 0 (ok) or 3 (inconsistent)")
    parser.add_argument("--write-card", action="store_true",
                        help="(re)generate dataset_card.json and README.md from a real scan")
    parser.add_argument("--json", default=None, help="write the card (or check verdict) to a file")
    parser.add_argument("--token-budget", type=int, default=256)
    parser.add_argument("--batch-size", type=int, default=4,
                        help="queries per batch when iterating (see --iterate)")
    parser.add_argument("--iterate", action="store_true",
                        help="walk the package in batches and print each batch's supervision")
    parser.add_argument("--no-hash", action="store_true",
                        help="skip sha256 of every file while scanning (faster, weaker card)")
    parser.add_argument("--sample-fragments", type=int, default=None,
                        help="scan only the first N fragments per array family")
    parser.add_argument("--batch-fragments", type=int, default=None,
                        help="build the card's mini-batch from the first N fragments only"
                             " (needed for packages too large to stack at once)")
    args = parser.parse_args(argv)

    try:
        root = resolve_package(args.package)
    except FileNotFoundError as exc:
        print(f"usage error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    if args.check:
        verdict = check_package(root)
        for name, entry in verdict["checks"].items():
            print(f"[{'PASS' if entry.get('ok') else 'FAIL'}] {name}: "
                  f"{json.dumps({k: v for k, v in entry.items() if k != 'ok'}, ensure_ascii=False, default=str)[:400]}")
        print(json.dumps({"ok": verdict["ok"], "problems": verdict["problems"]},
                         ensure_ascii=False, indent=2))
        print(f"exit {verdict['exit_code']} "
              f"({'consistent' if verdict['ok'] else 'inconsistent'})")
        if args.json:
            Path(args.json).write_text(json.dumps(verdict, indent=2, ensure_ascii=False,
                                                  default=str), encoding="utf-8")
        return int(verdict["exit_code"])

    card, scan = build_data_card(root, hash_files=not args.no_hash,
                                 sample_fragments=args.sample_fragments,
                                 batch_fragments=args.batch_fragments)
    built = build_batch(root, token_budget=args.token_budget)
    _print_summary(card, built, scan)

    if args.iterate:
        print()
        print("batches:")
        for item in iter_batches(root, batch_size=args.batch_size, token_budget=args.token_budget):
            tasks = {name: (item["supervision"]["tasks"].get(name) or {}).get("n_allowed")
                     for name in TASKS} if item["supervision"].get("tasks") else {}
            print(f"  batch {item['index']}: rows={len(item['rows'])} "
                  f"fragments={item['provenance']['fragment_ids']} n_allowed={tasks}")

    if args.write_card:
        card_path = root / CARD_NAME
        card_path.write_text(json.dumps(_jsonable(card), indent=2, ensure_ascii=False),
                             encoding="utf-8")
        (root / README_NAME).write_text(render_readme(_jsonable(card)), encoding="utf-8")
        print()
        print(f"wrote {card_path}")
        print(f"wrote {root / README_NAME}")

    if args.json:
        Path(args.json).write_text(json.dumps(_jsonable(card), indent=2, ensure_ascii=False),
                                   encoding="utf-8")
        print(f"wrote {args.json}")

    ok = bool(scan["hashes_match_manifest"]) and not scan["files_missing"]
    if not ok:
        print("package failed its own manifest hash check", file=sys.stderr)
        return EXIT_INCONSISTENT
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
