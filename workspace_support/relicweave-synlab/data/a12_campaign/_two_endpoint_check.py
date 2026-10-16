"""Two-endpoint observation check + why a lineage with a label_bundle is still "failed".

Requirement under test (task brief, item 2): pick an *accepted* lineage at random and confirm that
**both ends of its R2 pairs have their own observation asset**, with the asset ids and view counts.

The store is the only source: for each lineage we read
* every ``label_bundle`` asset and its ``qa_status`` (the driver's accept proxy),
* every ``obs_result`` asset, its ``meta.obs_semantics``, ``meta.observation_facts`` and the number
  of views it actually carries,
* the ``clean_truth`` asset, whose payload lists the relations and their kind, so the R2 pairs and
  their endpoint fragment ids are read from the artefact rather than assumed.

Read-only.  Writes one JSON answer next to the campaign logs.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from synlab.storage.store import AssetStore  # noqa: E402

ROOT = REPO / "data" / "a12_campaign" / "store"
OUT = REPO / "data" / "a12_campaign" / "two_endpoint_check.json"
SEED = 20261002


def views_of(record) -> int:
    views = (record.meta or {}).get("views")
    if isinstance(views, list):
        return len(views)
    try:
        payload = json.loads(record.files.get("payload", "") or "{}")
    except Exception:
        payload = {}
    if isinstance(payload, dict) and isinstance(payload.get("views"), list):
        return len(payload["views"])
    return 0


def obs_semantics_of(record) -> str:
    """``_stamp_obs_semantics`` writes into ``obs.meta``, which ``observation_meta`` nests."""
    meta = record.meta or {}
    for candidate in (meta.get("obs_semantics"), (meta.get("meta") or {}).get("obs_semantics")):
        if candidate:
            return str(candidate)
    return "None"


def observation_facts_of(record):
    meta = record.meta or {}
    return meta.get("observation_facts") or (meta.get("meta") or {}).get("observation_facts")


def main() -> int:
    store = AssetStore(ROOT)
    records = list(store.list_assets(limit=1000000))

    by_lineage: dict[str, list] = {}
    for rec in records:
        if rec.lineage_id:
            by_lineage.setdefault(rec.lineage_id, []).append(rec)

    accepted = sorted(lid for lid, recs in by_lineage.items()
                      if any(r.role == "label_bundle" and r.qa_status == "QA_PASS" for r in recs))
    rng = random.Random(SEED)
    sample = rng.choice(accepted) if accepted else None

    answer: dict[str, object] = {
        "store": str(ROOT.relative_to(REPO)).replace("\\", "/"),
        "assets_total": len(records),
        "lineages_with_assets": sorted(by_lineage),
        "lineages_with_qa_pass_label_bundle": accepted,
        "sampled_lineage": sample,
        "random_seed": SEED,
    }
    per_lineage: dict[str, object] = {}

    for lid, recs in sorted(by_lineage.items()):
        roles: dict[str, int] = {}
        for r in recs:
            roles[r.role] = roles.get(r.role, 0) + 1
        obs = [r for r in recs if r.role == "obs_result"]
        labels = [r for r in recs if r.role == "label_bundle"]
        truths = [r for r in recs if r.role == "clean_truth"]

        r2_pairs: list[dict[str, object]] = []
        relation_kinds: dict[str, int] = {}
        for truth in truths:
            # relations live in meta["relations"] (a list of edge rows) or, when meta elides
            # them, in the "relations" blob -- read through load_truth so the artefact decides.
            try:
                from synlab.truth.api import load_truth

                obj = load_truth(store, truth.asset_id)
                rows = (getattr(obj, "meta", {}) or {}).get("relations")
                if rows is None:
                    rows = getattr(obj, "relations", None)
            except Exception:  # noqa: BLE001 - fall back to the raw metadata rows
                rows = (truth.meta or {}).get("relations")
            if isinstance(rows, dict):
                rows = list(rows.values())
            for rel in rows or []:
                if not isinstance(rel, dict):
                    continue
                kind = str(rel.get("kind"))
                relation_kinds[kind] = relation_kinds.get(kind, 0) + 1
                if kind != "R2":
                    continue
                a = str(rel.get("a") or rel.get("a_id") or "")
                b = str(rel.get("b") or rel.get("b_id") or "")
                obs_for = {}
                for end in (a, b):
                    hit = [r for r in obs
                           if str((r.meta or {}).get("fragment_id", "")) == end]
                    obs_for[end] = {
                        "observation_assets": [r.asset_id for r in hit],
                        "views": [views_of(r) for r in hit],
                        "obs_semantics": sorted({obs_semantics_of(r) for r in hit}),
                        "observation_facts": [observation_facts_of(r) for r in hit],
                    }
                r2_pairs.append({"a": a, "b": b, "ends": obs_for,
                                 "both_ends_observed": all(
                                     v["observation_assets"] for v in obs_for.values())})

        per_lineage[lid] = {
            "assets": len(recs),
            "roles": roles,
            "label_bundles": [{"asset_id": r.asset_id, "qa_status": r.qa_status,
                               "split": r.split} for r in labels],
            "observations": [{"asset_id": r.asset_id,
                              "fragment_id": str((r.meta or {}).get("fragment_id", "")),
                              "obs_semantics": obs_semantics_of(r),
                              "observation_facts": observation_facts_of(r),
                              "views": views_of(r),
                              "qa_status": r.qa_status} for r in obs],
            "r2_pairs": r2_pairs,
            "relation_kinds": relation_kinds,
        }

    answer["per_lineage"] = per_lineage
    if sample:
        s = per_lineage[sample]
        answer["sampled_detail"] = {
            "lineage_id": sample,
            "label_bundles": s["label_bundles"],
            "n_observation_assets": len(s["observations"]),
            "observation_view_counts": [o["views"] for o in s["observations"]],
            "obs_semantics_values": sorted({o["obs_semantics"] for o in s["observations"]}),
            "n_r2_pairs": len(s["r2_pairs"]),
            "r2_both_ends_observed": [p.get("both_ends_observed") for p in s["r2_pairs"]],
            "r2_pair_detail": s["r2_pairs"],
        }

    OUT.write_text(json.dumps(answer, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in answer.items() if k != "per_lineage"},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
