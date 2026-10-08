"""Recipe serialisation and hashing (plan 9.1: frozen recipe + resource hash + version).

A :class:`~synlab.schemas.runtime.PatternRecipe` is stored as canonical JSON (``params``
and ``meta`` are already JSON-safe by construction) plus the palette.  ``recipe_hash`` is
a content hash over everything except the stored hash itself, so replay can verify that
the frozen coefficients, the raster payloads, the region, the warp and the height policy
are exactly the ones that were audited.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ..canonical import array_hash, hash_json
from ..errors import ErrorCode, SynLabError
from ..schemas.runtime import PatternChannels, PatternRecipe

MODULE_VERSION = "1.0"
CHANNELS = ("albedo", "roughness", "height_mm", "pattern_region")


def recipe_payload(recipe: PatternRecipe) -> dict[str, Any]:
    meta = {k: v for k, v in (recipe.meta or {}).items() if k != "recipe_hash"}
    return {
        "family_id": recipe.family_id,
        "seed_ref": recipe.seed_ref,
        "params": recipe.params,
        "palette": [list(map(float, colour)) for colour in recipe.palette],
        "channels": list(recipe.channels),
        "version": recipe.version,
        "resource_hash": recipe.resource_hash,
        "meta": meta,
    }


def recipe_hash(recipe: PatternRecipe) -> str:
    return hash_json(recipe_payload(recipe))


def recipe_to_dict(recipe: PatternRecipe) -> dict[str, Any]:
    payload = recipe_payload(recipe)
    payload["recipe_hash"] = str((recipe.meta or {}).get("recipe_hash", recipe_hash(recipe)))
    return payload


def recipe_from_dict(payload: dict[str, Any]) -> PatternRecipe:
    if "family_id" not in payload:
        raise SynLabError(ErrorCode.SCHEMA_INVALID, "recipe payload lacks family_id",
                          stage="patterns.serialize.recipe_from_dict")
    meta = dict(payload.get("meta") or {})
    if payload.get("recipe_hash"):
        meta["recipe_hash"] = str(payload["recipe_hash"])
    return PatternRecipe(
        family_id=str(payload["family_id"]),
        seed_ref=str(payload.get("seed_ref", "")),
        params=dict(payload.get("params") or {}),
        palette=[tuple(float(c) for c in colour) for colour in payload.get("palette", [])],
        channels=tuple(payload.get("channels", CHANNELS)),
        version=str(payload.get("version", MODULE_VERSION)),
        resource_hash=str(payload.get("resource_hash", "")),
        meta=meta,
    )


def channels_payload(channels: PatternChannels) -> dict[str, np.ndarray]:
    return {
        "albedo": np.asarray(channels.albedo, dtype=np.float32),
        "roughness": np.asarray(channels.roughness, dtype=np.float32),
        "height_mm": np.asarray(channels.height_mm, dtype=np.float32),
        "pattern_region": np.asarray(channels.pattern_region, dtype=np.uint8),
    }


def channels_from_arrays(arrays: dict[str, np.ndarray], meta: dict[str, Any] | None = None
                         ) -> PatternChannels:
    missing = [key for key in ("albedo", "roughness", "height_mm", "pattern_region")
               if key not in arrays]
    if missing:
        raise SynLabError(ErrorCode.ASSET_HASH_MISMATCH,
                          f"pattern channel arrays missing {missing}",
                          stage="patterns.serialize.channels_from_arrays")
    return PatternChannels(
        albedo=np.asarray(arrays["albedo"], dtype=np.float32),
        roughness=np.asarray(arrays["roughness"], dtype=np.float32),
        height_mm=np.asarray(arrays["height_mm"], dtype=np.float32),
        pattern_region=np.asarray(arrays["pattern_region"], dtype=np.uint8),
        meta=dict(meta or {}),
    )


def resource_hash(entries: list[dict[str, Any]] | None, params: dict[str, Any]) -> str:
    """Hash of frozen external resources plus the frozen coefficient payload.

    ``entries`` lists real files that were read (font, SVG) with their SHA-256; when the
    family has no external resource the coefficient payload alone is hashed and the fact
    is recorded, instead of inventing a placeholder resource.
    """
    clean_entries = []
    for entry in entries or []:
        clean_entries.append({k: v for k, v in entry.items() if k != "path"})
    return hash_json({
        "resources": clean_entries,
        "resource_kinds": sorted({str(e.get("kind", "")) for e in clean_entries}),
        "coefficients": params,
    })


def geometry_hash(vertices: np.ndarray, faces: np.ndarray) -> str:
    return hash_json({"vertices": array_hash(np.asarray(vertices, dtype=np.float64)),
                      "faces": array_hash(np.asarray(faces, dtype=np.int64))})
