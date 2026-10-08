"""Asset-store round trip for pattern recipes and channels (plan 6.3, interfaces §2).

The recipe is committed under ``ROLE_PATTERN_RECIPE`` with its canonical JSON; optional
channel arrays are committed as a separate ``ROLE_PATTERN_CHANNELS`` asset that records
the recipe asset id it was evaluated from, so a channel payload can never be mistaken
for an independent recipe.
"""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np

from ..errors import ErrorCode, SynLabError
from ..roles import (FRAME_WORLD, ROLE_PATTERN_CHANNELS, ROLE_PATTERN_RECIPE, SCHEMA_PATTERN,
                     UNIT_MM)
from ..schemas.runtime import PatternChannels, PatternRecipe
from ..storage.store import QA_PASS, QA_PENDING, AssetRecord, AssetStore
from .serialize import (CHANNELS, channels_from_arrays, channels_payload, recipe_from_dict,
                        recipe_hash, recipe_to_dict)


def commit_pattern(store: AssetStore, recipe: PatternRecipe, channels: PatternChannels | None = None,
                   *, lineage_id: str | None = None, split: str | None = None,
                   ancestry: Sequence[str] = (), mother_id: str | None = None,
                   qa: dict[str, Any] | None = None, qa_status: str = QA_PENDING,
                   channels_key: str = "pattern_channels") -> AssetRecord:
    """Commit the frozen recipe (and optionally its evaluated channels)."""
    if not isinstance(store, AssetStore):
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"commit_pattern expects an AssetStore, got {type(store)!r}",
                          stage="patterns.commit.commit_pattern")
    if not isinstance(recipe, PatternRecipe):
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"commit_pattern expects a PatternRecipe, got {type(recipe)!r}",
                          stage="patterns.commit.commit_pattern")
    payload = recipe_to_dict(recipe)
    meta: dict[str, Any] = {
        "recipe": payload,
        "recipe_hash": payload.get("recipe_hash", recipe_hash(recipe)),
        "family_id": recipe.family_id,
        "module_version": recipe.version,
        "resource_hash": recipe.resource_hash,
        "mother_id": mother_id,
        "channels_declared": list(recipe.channels),
        "units": UNIT_MM,
    }
    if channels is None:
        record = store.commit_asset(
            role=ROLE_PATTERN_RECIPE, schema=SCHEMA_PATTERN, unit=UNIT_MM, frame=FRAME_WORLD,
            payload=meta, meta={"family_id": recipe.family_id},
            qa=dict(qa or {}), qa_status=qa_status, ancestry=list(ancestry),
            lineage_id=lineage_id, split=split,
            interpretation_extra={"family_id": recipe.family_id,
                                 "recipe_hash": meta["recipe_hash"]})
        return record

    arrays = channels_payload(channels)
    channels_meta = {
        "recipe_ref": None,
        "recipe_hash": meta["recipe_hash"],
        "family_id": recipe.family_id,
        "mother_id": mother_id,
        "channels": list(CHANNELS),
        "channel_meta": dict(channels.meta or {}),
        "shape": [int(v.shape[0]) for v in arrays.values()],
        "units": {"albedo": "linear rgb", "roughness": "1", "height_mm": "mm",
                  "pattern_region": "mask"},
    }
    channels_record = store.commit_asset(
        role=ROLE_PATTERN_CHANNELS, schema=SCHEMA_PATTERN, unit=UNIT_MM, frame=FRAME_WORLD,
        payload=dict(arrays), meta=channels_meta, qa=dict(qa or {}), qa_status=qa_status,
        ancestry=list(ancestry), lineage_id=lineage_id, split=split,
        interpretation_extra={"family_id": recipe.family_id, "recipe_hash": meta["recipe_hash"],
                             "role": channels_key})
    meta["channels_asset"] = channels_record.asset_id
    record = store.commit_asset(
        role=ROLE_PATTERN_RECIPE, schema=SCHEMA_PATTERN, unit=UNIT_MM, frame=FRAME_WORLD,
        payload=meta, meta={"family_id": recipe.family_id,
                            "channels_asset": channels_record.asset_id},
        qa=dict(qa or {}), qa_status=qa_status, ancestry=list(ancestry) + [channels_record.asset_id],
        lineage_id=lineage_id, split=split,
        interpretation_extra={"family_id": recipe.family_id, "recipe_hash": meta["recipe_hash"]})
    return record


def load_pattern(store: AssetStore, asset_id: str) -> PatternRecipe:
    """Load a frozen recipe back from the store (hash verified against the payload)."""
    record = store.get_asset(asset_id)
    if record.role != ROLE_PATTERN_RECIPE:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"asset {asset_id} has role {record.role!r}, expected "
                          f"{ROLE_PATTERN_RECIPE!r}", stage="patterns.commit.load_pattern")
    payload = (record.meta or {}).get("recipe")
    if not isinstance(payload, dict):
        raise SynLabError(ErrorCode.ASSET_HASH_MISMATCH,
                          f"asset {asset_id} carries no recipe payload",
                          stage="patterns.commit.load_pattern")
    recipe = recipe_from_dict(payload)
    stored = str(payload.get("recipe_hash") or "")
    actual = recipe_hash(recipe)
    if stored and stored != actual:
        raise SynLabError(ErrorCode.ASSET_HASH_MISMATCH,
                          f"asset {asset_id} recipe hash mismatch: stored {stored}, recomputed {actual}",
                          stage="patterns.commit.load_pattern")
    return recipe


def load_pattern_channels(store: AssetStore, asset_id: str) -> PatternChannels:
    """Load a committed pattern channel payload."""
    record = store.get_asset(asset_id)
    if record.role != ROLE_PATTERN_CHANNELS:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          f"asset {asset_id} has role {record.role!r}, expected "
                          f"{ROLE_PATTERN_CHANNELS!r}",
                          stage="patterns.commit.load_pattern_channels")
    arrays = store.load_arrays(asset_id)
    return channels_from_arrays(arrays, meta=dict(record.meta.get("channel_meta") or {}))


__all__ = ["commit_pattern", "load_pattern", "load_pattern_channels", "QA_PASS", "QA_PENDING"]
