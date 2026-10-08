"""Label-side supervision of an exported training package (read, never invented).

The exporter writes the supervision it really measured into the **research** view
(``research/labels/<layer>.parquet``); this module is the training-side reader.  It exists
because :meth:`synlab.training.trainer.Trainer.build_batch` used to call
:func:`synlab.training.batch.build_training_batch` **without** ``correspondence=`` /
``quality_target=`` / ``quality_target_valid=``, so a package that carried the labels still
produced a batch with every one of those tensors at zero.  That made "the label was never
produced" indistinguishable from "the label never reached the batch".

Rules kept here (plan 30.12):

* a fragment (or view) with **no** measurement gets ``valid=False`` and is never turned into a
  zero-valued target: the value slot may be ``0.0`` but the validity mask is what the loss reads;
* ``UNKNOWN``-style bookkeeping (an unmeasured view) never becomes supervision;
* nothing is derived from a truth channel: the reader only re-shapes what the package stores.

Two labels are read today:

``quality``
    per (fragment, view) label-side observability of the delivered observation.  The D task's
    single target channel is the mean over measured views of the reported ``target_value``
    (``observability_visible_rate`` by default), aggregated per fragment because the
    observation-only quality head is one channel wide.
``correspondence``
    real many-to-many surface correspondence between the two sides of a cut face.  A sample can
    only become a correspondence *loss* row if both fragments carry token evidence **and** the
    sample can be located in token space; the second half needs the camera channels the
    deployment view deliberately does not carry, so this module reports the blocker instead of
    fabricating a weight matrix (see :meth:`PackageLabelSource.correspondence_for`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from ..errors import ErrorCode, SynLabError

#: label layers this reader knows how to consume
QUALITY_LAYER = "quality"
CORRESPONDENCE_LAYER = "correspondence"
#: target channel of the D task when the package does not name one
DEFAULT_QUALITY_CHANNEL = "observability_visible_rate"


def _mean_or_none(values: Sequence[float]) -> float | None:
    vals = [float(v) for v in values if v is not None and np.isfinite(float(v))]
    return float(np.mean(vals)) if vals else None


@dataclass
class PackageLabelSource:
    """Real label-side supervision read out of one exported package."""

    #: fragment id -> {"target", "valid", "views", "asset_id", "channel", "spread"}
    quality: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: (fragment_a, fragment_b) -> {"samples", "valid_samples", "weight_sum", "asset_id", ...}
    correspondence: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    quality_channel: str = DEFAULT_QUALITY_CHANNEL
    package_dir: str = ""
    quality_provenance: dict[str, Any] = field(default_factory=dict)
    correspondence_provenance: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------ construction
    @classmethod
    def from_package(cls, package: Any) -> "PackageLabelSource":
        """Read ``package.labels('quality')`` / ``package.labels('correspondence')``."""
        return cls.from_tables(quality=package.labels(QUALITY_LAYER),
                               correspondence=package.labels(CORRESPONDENCE_LAYER),
                               provenance=(package.manifest.get("supervision_labels") or {}),
                               package_dir=str(getattr(package, "root", "")))

    @classmethod
    def from_dir(cls, package_dir: str | Path) -> "PackageLabelSource":
        from ..storage.export import TrainingPackage

        return cls.from_package(TrainingPackage(package_dir))

    @classmethod
    def from_tables(cls, *, quality: Sequence[Mapping[str, Any]] = (),
                    correspondence: Sequence[Mapping[str, Any]] = (),
                    provenance: Mapping[str, Any] | None = None,
                    package_dir: str = "") -> "PackageLabelSource":
        prov = dict(provenance or {})
        channel = str((prov.get(QUALITY_LAYER) or {}).get("target_channel")
                      or DEFAULT_QUALITY_CHANNEL)
        by_fragment: dict[str, list[dict[str, Any]]] = {}
        for row in quality:
            fragment_id = str(row.get("fragment_id") or "")
            if not fragment_id:
                continue
            by_fragment.setdefault(fragment_id, []).append(dict(row))
        quality_out: dict[str, dict[str, Any]] = {}
        for fragment_id, rows in sorted(by_fragment.items()):
            values = [r.get("target_value") for r in rows if bool(r.get("valid", False))]
            values = [float(v) for v in values if v is not None]
            quality_out[fragment_id] = {
                "target": _mean_or_none(values),
                "valid": bool(values),
                "views": int(sum(1 for r in rows if bool(r.get("valid", False)))),
                "views_reported": len(rows),
                "values": values,
                "asset_id": str(rows[0].get("asset_id", "")),
                "channel": str(rows[0].get("target_channel") or channel),
                "source_kind": str(rows[0].get("source_kind", "")),
                "unit": str(rows[0].get("target_unit", "")),
            }
        corr: dict[tuple[str, str], dict[str, Any]] = {}
        for row in correspondence:
            a = str(row.get("fragment_a") or "")
            b = str(row.get("fragment_b") or "")
            key = (a, b) if a <= b else (b, a)
            entry = corr.setdefault(key, {"samples": 0, "valid_samples": 0, "weight_sum": 0.0,
                                          "ambiguous_samples": 0, "asset_id": str(
                                              row.get("asset_id", "")),
                                          "relation_kind": str(row.get("relation_kind", "")),
                                          "lineage": str(row.get("lineage", ""))})
            entry["samples"] += 1
            entry["valid_samples"] += int(bool(row.get("valid", False)))
            entry["ambiguous_samples"] += int(bool(row.get("ambiguous", False)))
            entry["weight_sum"] += float(row.get("weight") or 0.0)
        for entry in corr.values():
            entry["weight_sum"] = float(entry["weight_sum"])
        return cls(quality=quality_out, correspondence=corr, quality_channel=channel,
                   package_dir=package_dir,
                   quality_provenance=dict(prov.get(QUALITY_LAYER) or {}),
                   correspondence_provenance=dict(prov.get(CORRESPONDENCE_LAYER) or {}))

    # ------------------------------------------------------------------ quality
    def quality_target_for(self, fragment_ids: Sequence[str]) -> tuple[np.ndarray, np.ndarray,
                                                                      dict[str, Any]]:
        """``([F,1,1] target, [F,1,1] valid, report)`` for the given fragment order.

        A fragment with no measurement gets ``valid=False``; its value stays ``0.0`` and is
        documented as *not* supervision (plan 30.12: a missing label is never a zero label).
        """
        f = len(fragment_ids)
        target = np.zeros((f, 1, 1), dtype=np.float32)
        valid = np.zeros((f, 1, 1), dtype=bool)
        per_fragment: dict[str, Any] = {}
        for i, fid in enumerate(fragment_ids):
            entry = self.quality.get(str(fid))
            if entry and entry["valid"] and entry["target"] is not None:
                target[i, 0, 0] = float(entry["target"])
                valid[i, 0, 0] = True
            per_fragment[str(fid)] = {
                "valid": bool(valid[i, 0, 0]),
                "target": (float(target[i, 0, 0]) if valid[i, 0, 0] else None),
                "views": int(entry["views"]) if entry else 0,
                "reason": None if (entry and entry["valid"]) else "no_label_side_measurement",
            }
        report = {
            "layer": QUALITY_LAYER,
            "channel": self.quality_channel,
            "n_valid": int(valid.sum()),
            "n_fragments": f,
            "n_measured_fragments_in_package": int(sum(1 for e in self.quality.values()
                                                       if e["valid"])),
            "missing_is_not_a_zero_label": True,
            "per_fragment": per_fragment,
            "source_kind": next((e["source_kind"] for e in self.quality.values()
                                 if e["source_kind"]), ""),
        }
        return target, valid, report

    # ------------------------------------------------------------------ correspondence
    def correspondence_for(self, features: Any, rows: Sequence[Mapping[str, Any]]
                           ) -> tuple[None, dict[str, Any]]:
        """Return ``(mapping, report)``; ``mapping`` is ``None`` while the labels cannot be
        located in token space.

        A correspondence sample is a pair of **surface** points on the two fragments.  The loss
        consumes ``W[q, c, i, j]`` over *token* indices, so a sample only becomes supervision if
        (a) both fragments carry token evidence and (b) the sample can be projected into the
        delivered views -- and the projection channels (``K``/``T_WC``/``id_map``/``depth_z``) are
        forbidden in the deployment view by design.  The report states which of the two failed;
        it never guesses a weight matrix.
        """
        token_counts = {str(fid): int(np.count_nonzero(features.token_valid[i]))
                        for i, fid in enumerate(features.fragment_ids)}
        wanted: set[tuple[str, str]] = set()
        for row in rows:
            entries = [str(x) for x in row.get("positives", [])] + \
                      [str(x) for x in row.get("negatives", [])]
            query = str(row.get("query", ""))
            for candidate in entries:
                wanted.add((query, candidate) if query <= candidate else (candidate, query))
        labelled = sorted(wanted & set(self.correspondence))
        samples_in_batch = int(sum(self.correspondence[p]["samples"] for p in labelled))
        both_observed = [pair for pair in labelled
                         if token_counts.get(pair[0], 0) > 0 and token_counts.get(pair[1], 0) > 0]
        one_side = [pair for pair in labelled
                    if (token_counts.get(pair[0], 0) > 0) != (token_counts.get(pair[1], 0) > 0)]
        report = {
            "layer": CORRESPONDENCE_LAYER,
            "n_label_samples_in_package": int(sum(e["samples"] for e in
                                                  self.correspondence.values())),
            "n_pairs_with_labels": len(self.correspondence),
            "pairs_in_batch_with_labels": len(labelled),
            "n_label_samples_in_batch": samples_in_batch,
            "pairs_with_both_sides_observable": len(both_observed),
            "pairs_with_one_side_observable": len(one_side),
            "token_mapped_rows": 0,
            "token_mapping_available": False,
            "reference_geometry_mm": {
                "n_points": int(features.points.shape[1]),
                "observed_fragments": sorted(fid for fid, n in token_counts.items() if n > 0),
                "unobserved_fragments": sorted(fid for fid, n in token_counts.items() if n == 0),
            },
            "blocked_by": [],
            "unlock_condition": [],
        }
        if not self.correspondence:
            report["blocked_by"].append("no_correspondence_label_in_package")
            report["unlock_condition"].append(
                "export the release's corr_* truth arrays into research/labels/correspondence")
        if one_side:
            report["blocked_by"].append("one_side_of_every_labelled_pair_has_no_token_evidence")
            report["unlock_condition"].append(
                "observe both fragments of at least one R2 pair (the exported package currently "
                "renders exactly one side per cut event)")
        if not both_observed and not one_side and labelled:
            report["blocked_by"].append("no_labelled_pair_inside_the_batch")
        report["blocked_by"].append(
            "surface_sample_to_token_mapping_is_not_derivable_from_the_package")
        report["unlock_condition"].append(
            "export a token-mapped correspondence table (project the corr_* samples with the "
            "camera channels in the truth/observe layer, which the deployment view must not carry)")
        return None, report

    # ------------------------------------------------------------------ diagnostics
    def report(self) -> dict[str, Any]:
        return {
            "package_dir": self.package_dir,
            "quality": {
                "channel": self.quality_channel,
                "fragments_with_measurement": int(sum(1 for e in self.quality.values()
                                                      if e["valid"])),
                "fragments_reported": len(self.quality),
                "provenance": self.quality_provenance,
            },
            "correspondence": {
                "pairs_with_labels": len(self.correspondence),
                "samples": int(sum(e["samples"] for e in self.correspondence.values())),
                "valid_samples": int(sum(e["valid_samples"] for e in self.correspondence.values())),
                "weight_sum": float(sum(e["weight_sum"] for e in self.correspondence.values())),
                "provenance": self.correspondence_provenance,
            },
        }


def assert_label_source_available(source: PackageLabelSource | None) -> None:
    """A caller that claims to train on labels must have a label source."""
    if source is None:
        raise SynLabError(ErrorCode.INPUT_UNAVAILABLE,
                          "no label source configured; the batch would carry no supervision",
                          stage="training.labels.assert_label_source_available")


__all__ = [
    "QUALITY_LAYER", "CORRESPONDENCE_LAYER", "DEFAULT_QUALITY_CHANNEL", "PackageLabelSource",
    "assert_label_source_available",
]
