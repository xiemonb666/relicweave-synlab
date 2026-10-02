"""One口径 for the U rail: contract vs profiles vs the positions the packages really carry (S10).

Three numbers used to disagree:

* ``configs/a12/capture_contract.json`` — ``mechanics.u_axis_near_far`` says the scan bench gets a
  *basic manual optical-axis rail, about 150 mm, 100–200 mm reserved* (source ``t052``), i.e.
  ``travel_mm_nominal = 150``.  ``synlab/degrade/specs.py`` carries the same number as
  ``u_rail_travel_mm = 150.0`` and is a **hard gate** that refuses a view outside it.
* ``configs/a12/camera_profiles.json`` — ``max_travel_mm`` was ``120.0`` on every profile.  That is
  the *span of the three nominal lock positions* (0 / 60 / 120 mm), not a travel bound, so a
  measured position of 127.12 mm read as over-travel.
* the exported packages — ``deploy/obs/*.tar`` really carry ``view_pos.npy``, read from the
  delivered pose ``T_WC[0, 3]``.

This driver states all three, names the口径 that wins (the contract, which is the rig's own
specification) and prints **both** readings of the measured positions so neither is hidden:

``span``
    ``max - min`` over the observed positions: what a *travel* reading measures.
``absolute``
    ``max(|position|)``: what an *absolute coordinate* reading measures.

Exit code 0 when the declared limits are consistent with the contract **and** every measured
position is inside them under the travel reading; 3 otherwise.

    python tools/a12_u_travel_check.py [--package <pkg> ...] [--json out.json]
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import tarfile
from pathlib import Path
from typing import Any, Sequence

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

EXIT_OK = 0
EXIT_INCONSISTENT = 3
EXIT_USAGE = 2

CONTRACT_PATH = REPO_ROOT / "configs" / "a12" / "capture_contract.json"
PROFILES_PATH = REPO_ROOT / "configs" / "a12" / "camera_profiles.json"

#: packages shipped by this repository that carry real ``view_pos`` arrays
DEFAULT_PACKAGES = (
    "data/a12_exports/trainable/next_experiment/training_package",
    "data/a12_exports/negfix/next_experiment/training_package",
)


def contract_travel() -> dict[str, Any]:
    """The scan bench's declared U-rail travel (the authoritative口径)."""
    payload = json.loads(CONTRACT_PATH.read_text(encoding="utf-8-sig"))
    block = ((payload.get("mechanics") or {}).get("u_axis_near_far") or {})
    return {
        "source": "configs/a12/capture_contract.json#mechanics.u_axis_near_far",
        "spec": block.get("spec"),
        "doc_ref": block.get("source"),
        "travel_mm_nominal": block.get("travel_mm_nominal"),
        "travel_mm_reserved_range": block.get("travel_mm_reserved_range"),
    }


def profile_travel() -> dict[str, Any]:
    """What the profile document declares, per profile."""
    payload = json.loads(PROFILES_PATH.read_text(encoding="utf-8-sig"))
    limits = payload.get("travel_limits") or {}
    return {
        "source": "configs/a12/camera_profiles.json",
        "declared_nominal": limits.get("u_rail_travel_mm_nominal"),
        "declared_reserved_range": limits.get("u_rail_travel_mm_reserved_range"),
        "profiles": [
            {"profile_id": row.get("profile_id"), "tier": row.get("tier"),
             "u_position_mm": row.get("u_position_mm"),
             "max_travel_mm": row.get("max_travel_mm")}
            for row in (payload.get("profiles") or [])
        ],
    }


def enforced_tier_travel() -> dict[str, Any]:
    """The limits ``transform_profile_u`` really refuses against (the code, not a document)."""
    from synlab.cameras.profiles import _TIER_SPECS

    rows = []
    for spec in _TIER_SPECS:
        low, high = (float(spec.u_travel_mm[0]), float(spec.u_travel_mm[1]))
        rows.append({"tier": spec.tier, "profile_id": spec.profile_id,
                     "u_nominal_mm": float(spec.u_position_mm),
                     "travel_mm": [low, high], "span_mm": high - low,
                     "step_mm": float(spec.u_step_mm)})
    union = [min(row["travel_mm"][0] for row in rows), max(row["travel_mm"][1] for row in rows)]
    return {"source": "synlab/cameras/profiles.py::_TIER_SPECS (enforced by "
                      "transform_profile_u)", "tiers": rows,
            "union_travel_mm": union, "union_span_mm": union[1] - union[0]}


def measure_package(package: str | Path, *, store_root: str | Path | None = None
                    ) -> dict[str, Any]:
    """Every ``view_pos`` value the package really carries, per obs shard."""
    root = Path(package)
    index_path = root / "deploy" / "obs" / "index.json"
    if not index_path.is_file():
        return {"package": str(root), "available": False,
                "reason": f"no {index_path.relative_to(root)} (not a training package)"}
    index = json.loads(index_path.read_text(encoding="utf-8"))
    per_shard: dict[str, list[tuple[str, str]]] = {}
    for fragment_id, row in (index.get("rows") or {}).items():
        per_shard.setdefault(str(row["shard"]), []).append((fragment_id, str(row["opaque"])))
    shards: list[dict[str, Any]] = []
    values: list[float] = []
    for shard, members in sorted(per_shard.items()):
        path = root / "deploy" / shard
        if not path.is_file():
            shards.append({"shard": shard, "available": False})
            continue
        collected: list[float] = []
        with tarfile.open(path) as tar:
            for _fragment_id, opaque in members:
                try:
                    handle = tar.extractfile(f"{opaque}/view_pos.npy")
                except KeyError:
                    continue
                if handle is None:
                    continue
                collected.extend(np.asarray(np.load(io.BytesIO(handle.read())),
                                            dtype=np.float64).reshape(-1).tolist())
        finite = [v for v in collected if np.isfinite(v)]
        values.extend(finite)
        shards.append({
            "shard": shard, "available": True, "views": len(collected),
            "finite": len(finite),
            "absmax_mm": (max(abs(v) for v in finite) if finite else None),
            "min_mm": (min(finite) if finite else None),
            "max_mm": (max(finite) if finite else None),
        })
    array = np.asarray(values, dtype=np.float64)
    if array.size == 0:
        return {"package": str(root), "available": False, "reason": "no finite view_pos",
                "shards": shards}
    span = float(array.max() - array.min())
    absmax = float(np.abs(array).max())
    # Is this a *travel* number at all?  A real slide move keeps the working distance fixed and
    # changes only the optical-axis coordinate.  A number that swings while the profile's working
    # distance is constant is frame geometry (the X/Y of a rotated camera centre), not travel.
    frame_geometry = _frame_geometry_evidence(store_root)
    return {
        "package": str(root),
        "available": True,
        "views": int(array.size),
        "min_mm": float(array.min()),
        "max_mm": float(array.max()),
        "absmax_mm": absmax,
        "span_mm": span,
        "mean_mm": float(array.mean()),
        # the two readings of the same bytes; both are printed so neither is hidden
        "travel_reading_span_mm": span,
        "absolute_reading_absmax_mm": absmax,
        "frame_geometry_evidence": frame_geometry,
        "reads_as_travel": not frame_geometry["is_frame_geometry"],
        "shards": shards,
    }


def _frame_geometry_evidence(store_root: str | Path | None) -> dict[str, Any]:
    """Does ``view_pos := T_WC[0,3]`` behave like a slide coordinate or like frame geometry?

    The test needs no extra data: for one observation whose metadata names a single profile (so a
    single declared working distance) the delivered poses are read, and the spread of the camera
    centre components is compared with the spread of the working distance the profile declares.
    A slide move leaves ``working_distance_mm`` fixed and moves the camera along the optical axis;
    the numbers below are what the shipped packages really contain.
    """
    from synlab.storage.store import AssetStore

    if not store_root:
        return {"is_frame_geometry": False,
                "reason": "no --store given; component evidence unavailable"}
    probe = Path(store_root)
    if not probe.is_dir():
        return {"is_frame_geometry": False,
                "reason": f"store {probe} not present; component evidence unavailable"}
    store = AssetStore(probe)
    observation = store.list_assets(role="obs_result", limit=1)
    if not observation:
        return {"is_frame_geometry": False, "reason": "no obs_result asset in the store"}
    record = observation[0]
    meta = dict(record.meta or {})
    views = list(meta.get("views") or [])
    declared_wd = {float(view.get("working_distance_mm") or 0.0) for view in views}
    keys = [f"v{index_:03d}.T_WC" for index_ in range(len(views))]
    arrays = store.load_arrays(record.asset_id, keys=keys) if keys else {}
    centres = [np.asarray(arrays[key], dtype=np.float64)[:3, 3] for key in keys if key in arrays]
    if not centres:
        return {"is_frame_geometry": False, "reason": "the asset carries no T_WC"}
    centre = np.vstack(centres)
    spread = [float(centre[:, axis].max() - centre[:, axis].min()) for axis in range(3)]
    return {
        "fragment": meta.get("fragment_id"),
        "declared_working_distance_mm": sorted(declared_wd),
        "camera_centre_x_spread_mm": spread[0],
        "camera_centre_y_spread_mm": spread[1],
        "camera_centre_z_spread_mm": spread[2],
        "is_frame_geometry": bool(
            len(declared_wd) == 1 and max(spread[0], spread[1]) > spread[2]),
        "reason": ("the camera centre moves in X/Y while the declared working distance is a single "
                   "value: T_WC[0,3] is the scan-frame X of a rotated camera, not the slide "
                   "coordinate the channel claims to carry"),
    }


def check(packages: Sequence[str | Path], *, store_root: str | Path | None = None
          ) -> dict[str, Any]:
    contract = contract_travel()
    profiles = profile_travel()
    enforced = enforced_tier_travel()
    measured = [measure_package(package, store_root=store_root) for package in packages]

    nominal = contract.get("travel_mm_nominal")
    problems: list[str] = []
    if nominal is None:
        problems.append("the capture contract declares no travel_mm_nominal")
    if profiles.get("declared_nominal") != nominal:
        problems.append(
            f"camera_profiles.json declares nominal travel "
            f"{profiles.get('declared_nominal')} but the contract says {nominal}")
    for row in profiles["profiles"]:
        limit = row.get("max_travel_mm")
        if limit is not None and nominal is not None and float(limit) < float(nominal):
            problems.append(
                f"profile {row['profile_id']} declares max_travel_mm={limit} < the contract's "
                f"nominal {nominal}")
        position = row.get("u_position_mm")
        if position is not None and limit is not None and abs(float(position)) > float(limit):
            problems.append(
                f"profile {row['profile_id']} nominal position {position} is outside its own "
                f"max_travel_mm={limit}")
    for row in measured:
        if not row.get("available"):
            continue
        # the travel reading: how far the slide moved across the batch.  It is only a travel
        # statement when the channel really carries a slide coordinate; when the component
        # evidence says it carries frame geometry, the finding is recorded separately instead of
        # being booked as over-travel (which would blame the rig for a channel-definition defect).
        if not row.get("reads_as_travel"):
            continue
        if nominal is not None and row["travel_reading_span_mm"] > float(nominal) + 1e-9:
            problems.append(
                f"{row['package']}: the observed positions span "
                f"{row['travel_reading_span_mm']:.2f} mm, beyond the declared nominal travel "
                f"{nominal} mm")
    return {
        "contract": contract,
        "profiles": profiles,
        "enforced_tier_travel": enforced,
        "measured": measured,
        "problems": problems,
        "over_travel_verdict": [
            {"package": row["package"],
             "span_mm": row["travel_reading_span_mm"],
             "nominal_mm": nominal,
             "reads_as_travel": row["reads_as_travel"],
             "verdict": ("the exported view_pos does NOT carry a slide coordinate; the span is "
                         "frame geometry, so it is not evidence of over-travel"
                         if not row["reads_as_travel"] else
                         "a real slide-coordinate span beyond the declared nominal travel"),
             "evidence": row.get("frame_geometry_evidence")}
            for row in measured if row.get("available")],
        "exit_code": EXIT_OK if not problems else EXIT_INCONSISTENT,
        "reading_note": (
            "``span`` is the travel reading (max-min over the delivered positions); ``absmax`` is "
            "the absolute-coordinate reading (max |position|).  The rail spec is a travel, so "
            "``span`` is the number to compare against travel_mm_nominal -- but only if the "
            "channel really carries a slide coordinate.  ``frame_geometry_evidence`` measures "
            "that: a channel whose value moves in X/Y while the profile's working distance is "
            "constant is the camera centre of a rotated frame, not a slide read-out."),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", action="append", default=None,
                        help="training package to measure (repeatable; defaults to the shipped "
                             "ones that exist)")
    parser.add_argument("--json", default=None)
    parser.add_argument("--store", default=None,
                        help="asset store holding the release's obs_result assets; needed for the "
                             "frame-geometry evidence (default: data/a12_trainable/store)")
    args = parser.parse_args(argv)

    packages = args.package if args.package else [
        path for path in DEFAULT_PACKAGES if (REPO_ROOT / path).is_dir()]
    if not packages:
        print("no package to measure", file=sys.stderr)
        return EXIT_USAGE
    store_root = args.store
    if store_root is None:
        candidate = REPO_ROOT / "data" / "a12_trainable" / "store"
        store_root = candidate if candidate.is_dir() else None
    report = check(packages, store_root=store_root)
    contract = report["contract"]
    print(f"contract      : nominal {contract['travel_mm_nominal']} mm, reserved "
          f"{contract['travel_mm_reserved_range']} ({contract['doc_ref']})")
    print(f"profiles      : declared nominal {report['profiles']['declared_nominal']} mm; "
          f"max_travel_mm={sorted({r['max_travel_mm'] for r in report['profiles']['profiles']})}")
    enforced = report["enforced_tier_travel"]
    print(f"enforced tiers: union travel {enforced['union_travel_mm']} "
          f"(span {enforced['union_span_mm']} mm)")
    for row in measured_rows(report):
        print(f"measured      : {row['package']}")
        print(f"                views {row['views']}, signed range "
              f"[{row['min_mm']:.2f}, {row['max_mm']:.2f}] mm")
        print(f"                travel reading   span   = {row['travel_reading_span_mm']:.2f} mm")
        print(f"                absolute reading absmax = {row['absolute_reading_absmax_mm']:.2f} mm")
        evidence = row.get("frame_geometry_evidence") or {}
        print(f"                reads as a slide coordinate: {row['reads_as_travel']}")
        if evidence.get("reason"):
            print(f"                frame-geometry evidence: {evidence['reason']}")
            spread = (evidence.get("camera_centre_x_spread_mm"),
                      evidence.get("camera_centre_y_spread_mm"),
                      evidence.get("camera_centre_z_spread_mm"))
            if all(value is not None for value in spread):
                print("                  declared working distance "
                      f"{evidence.get('declared_working_distance_mm')} mm; camera-centre spread "
                      f"x={spread[0]:.2f} y={spread[1]:.2f} z={spread[2]:.2f} mm")
    for verdict in report["over_travel_verdict"]:
        print(f"over-travel   : {verdict['package']}")
        print(f"                span {verdict['span_mm']:.2f} mm vs nominal {verdict['nominal_mm']} mm"
              f" -> {verdict['verdict']}")
    if report["problems"]:
        print("PROBLEMS:")
        for problem in report["problems"]:
            print(f"  - {problem}")
    else:
        not_travel = [row["package"] for row in measured_rows(report)
                      if not row.get("reads_as_travel")]
        if not_travel:
            print("OK: the declared limits agree with the contract, and no measured span is a "
                  "travel statement")
            print(f"    ({len(not_travel)} package(s) carry a view_pos that is frame geometry, "
                  f"not a slide coordinate -- reported per package above)")
        else:
            print("OK: the declared limits agree with the contract and every measured span is "
                  "inside it")
    if args.json:
        Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=2,
                                              sort_keys=True), encoding="utf-8")
        print(f"wrote {args.json}")
    return int(report["exit_code"])


def measured_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in report["measured"] if row.get("available")]


if __name__ == "__main__":
    raise SystemExit(main())
