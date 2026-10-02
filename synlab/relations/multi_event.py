"""Mutually exclusive multi-event library: the source of R1 / R0 / TINY_CONTACT negatives.

Why this module exists
----------------------
``synlab.pipeline`` plans exactly **one** fracture event per lineage
(``pipeline.py`` builds ``LineagePlan(event_ids=[f"{lineage_id}_E01"])`` and consumes only
``event_ids[0]``), and ``synlab.truth.finalize_clean_truth`` classifies the pairs of a single
``FractureResult``.  Consequently a real store can only ever contain ``R2`` (plus the
within-event fallbacks) and a loader built on it reports ``negatives = 0`` -- the measured
state of ``data/a12/reports/loader_probe.json``.

This module produces the missing source honestly: **several independent fracture events on the
same physical mother** (plan 11.1 "同一互斥事件库").  Every event is a real
``synlab.fracture.fracture_event`` call with its own event id, its own derived seed and its own
cut surface; the relation verdict of every pair is then read off the measured truth of the
events, never declared:

===========================  ===========================================================
pair                          verdict (plan 11.1 / 30.5)
===========================  ===========================================================
same event, shared patch      the **real** ``finalize_clean_truth`` verdict of that event
                              (``R2`` / ``TINY_CONTACT`` / ``UNKNOWN``) with its measured
                              pair common-fracture area
same event, no patch          ``R1`` (real reason ``no_direct_fracture_surface``)
same mother, different event  ``R1`` -- the events are mutually exclusive, so neither piece
                              can carry a shared fracture surface; the exclusion is *verified*
                              (:func:`verify_event_exclusion`): no interface patch connects the
                              two events and no two events of a mother use the same cut plane
different mother              ``R0`` (physically unrelated bodies)
unconfirmed source            ``UNKNOWN`` with ``loss_mask=False`` (never a negative)
===========================  ===========================================================

Every emitted row carries an ``evidence`` block (mother, both event ids, the deciding basis
and, where a surface exists, its measured area), so a negative can always be traced back to the
event and lineage that produced it.

One deliberate flag choice
--------------------------
``synlab.truth`` sets ``valid=False`` on an *R1* edge because R1 means "no measured fracture
surface backs this pair".  For the **cross-event** R1 rows written here, ``valid`` and
``loss_mask`` record something different and narrower -- that the non-adjacency statement is
*confirmed* by the mutually exclusive event construction -- because that is exactly the flag the
exporter and loader read to decide negative eligibility
(``storage.export``: ``eligible_as_negative = kind in {R1,R0} and valid and loss_mask``).  Both
facts stay visible: cross-event R1 rows carry ``measured_surface=False`` and
``decidability="mutually_exclusive_event"``, and the truth layer's own within-event R1 rows keep
``valid=False`` unchanged.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from ..canonical import hash_json
from ..errors import ErrorCode, SynLabError
from ..seeds import make_rng, seed_ref
from ..schemas.runtime import (
    RELATION_R0,
    RELATION_R1,
    RELATION_R2,
    RELATION_TINY,
    RELATION_UNKNOWN,
)
from ..storage.store import QA_PASS, AssetStore

MULTI_EVENT_VERSION = "relations.multi_event.v1"

#: Roles of the events of one mother.  ``primary``/``secondary``/``extra`` get an rng-chosen cut
#: plane drawn from their own base azimuth; ``grey_zone`` gets an explicitly dialled plane whose
#: real interface area is meant to land in the frozen numerical grey zone (``TINY_CONTACT``)
#: instead of above the R2 threshold.
ROLE_PRIMARY = "primary"
ROLE_SECONDARY = "secondary"
#: The third (and every further) mutually exclusive event of a mother.  It is a **plain** cut on
#: its own base azimuth -- not a grey-zone dial.  Measured reason (``data/a12/reports/
#: relation_negatives_summary.json``, grey_zone ledger): dialling a plane into the grey band
#: cost 16 attempts of which 15 were refused by the conservation audit (20-83 s each) and the one
#: that succeeded produced fragments with **no** tagged new-fracture faces, so ``_event_plane``
#: could not measure its cut plane at all.  A third event is needed for the legal-negative route
#: ("a second event of the same mother" is what makes a non-adjacency claim decidable), and it
#: must be cheap *and* measurable; the grey zone is an optional extra, requested explicitly
#: through ``grey_zone_mothers``.
ROLE_EXTRA = "extra"
ROLE_GREY_ZONE = "grey_zone"
#: An event whose fracture really ran but whose clean truth was deliberately **not** computed.
#: Its fragments exist as real bodies while their relation evidence is missing, which is exactly
#: ``UNKNOWN`` in plan 11.1 ("关系或来源无法确认", ``loss_mask=False``) -- it is never an R0.
ROLE_UNRESOLVED = "unresolved"
EVENT_ROLES: tuple[str, ...] = (ROLE_PRIMARY, ROLE_SECONDARY, ROLE_EXTRA)

#: Splits that the pool builder treats as a distractor-only lineage (``gallery.DISTRACTOR_SPLITS``).
SPLIT_DISTRACTOR = "gallery_distractor"

#: Base cut azimuth (rad) per event role.  A **measured** necessity, not decoration:
#: ``synlab.fracture.api._default_basis`` derives its plane from the *body* (a hash of the
#: mother's vertices/faces, ``del rng``) whenever the spec carries no explicit plane, so three
#: events of one mother planned only with different event ids produced the **byte-identical**
#: fragment mesh sets (measured: mother ``LIN0000_V01_M01_PAT01`` events E01/E02/EU all yielded
#: meshes ``22f8746a...`` and ``ed9d25f6...``, and ``verify_event_exclusion`` reported
#: ``distinct_plane`` with ``normal_alignment=1.0``, ``offset_gap_mm=0.0``).  They were therefore
#: one fracture repeated, not mutually exclusive alternatives, and the exclusion check correctly
#: withdrew every cross-event R1 label to UNKNOWN.
#: Each role gets its own base azimuth; the per-event seed adds a small jitter and each retry
#: rotates further, so the events of one mother cut along different planes by construction while
#: staying fully reproducible from ``(master_seed, lineage_id, event_id)``.
#: The four base azimuths are deliberately **not** 0 and pi apart in pairs: the check compares
#: ``abs(dot(normal_a, normal_b))``, so two planes at opposite azimuths would count as the same
#: plane whenever their offsets coincide.  0 / 60 / 120 / 270 degrees keep every pair at
#: ``|dot| <= 0.5`` in the ideal case.
ROLE_BASE_AZIMUTH: dict[str, float] = {
    ROLE_PRIMARY: 0.0, ROLE_SECONDARY: np.pi / 3.0, ROLE_UNRESOLVED: 2.0 * np.pi / 3.0,
    ROLE_EXTRA: 1.5 * np.pi,
}
#: Azimuth step between the retries of one event, and the jitter band around a base azimuth.
PLANE_RETRY_STEP_RAD = np.pi / 5.0
PLANE_JITTER_RAD = 0.15
PLANE_TILT_RAD = 0.25

#: Two cut planes count as "the same fracture surface" when their normals agree and their
#: offsets coincide within these tolerances (mm / dimensionless).
PLANE_NORMAL_TOL = 1.0e-6
PLANE_OFFSET_TOL_MM = 1.0e-3


# --------------------------------------------------------------------------------------
# planning
# --------------------------------------------------------------------------------------
@dataclass
class MotherPlan:
    """One physical mother (a real vessel + material + parameters) and its event library."""

    lineage_id: str
    split: str
    vessel_id: str
    material_id: str
    pattern_id: str
    layer_combo_id: str | None
    params: dict[str, Any]
    mother_index: int
    distractor: bool = False

    @property
    def mother_id(self) -> str:
        return self.lineage_id

    def as_dict(self) -> dict[str, Any]:
        return {"lineage_id": self.lineage_id, "split": self.split, "vessel_id": self.vessel_id,
                "material_id": self.material_id, "pattern_id": self.pattern_id,
                "layer_combo_id": self.layer_combo_id, "params": dict(self.params),
                "mother_index": int(self.mother_index), "distractor": bool(self.distractor)}


@dataclass
class EventPlan:
    """One fracture event of one mother: its own id, its own seed, its own cut plane."""

    event_id: str
    mother_index: int
    lineage_id: str
    role: str
    seed_ref: str
    plane_point: list[float] | None = None
    plane_normal: list[float] | None = None
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"event_id": self.event_id, "mother_index": int(self.mother_index),
                "lineage_id": self.lineage_id, "role": self.role, "seed_ref": self.seed_ref,
                "plane_point": self.plane_point, "plane_normal": self.plane_normal,
                "note": self.note}


@dataclass
class LibraryPlan:
    """A frozen, reproducible event library: mothers x (>= 3 mutually exclusive events)."""

    master_seed: int
    mothers: list[MotherPlan] = field(default_factory=list)
    events: list[EventPlan] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def events_per_mother(self) -> int:
        """Labelled events per mother (the unresolved-source events are not counted)."""
        return max((sum(1 for e in self.events
                        if e.mother_index == m.mother_index and e.role != ROLE_UNRESOLVED)
                    for m in self.mothers), default=0)

    @property
    def events_total(self) -> int:
        return len(self.events)

    def events_of(self, mother_index: int) -> list[EventPlan]:
        return [e for e in self.events if e.mother_index == int(mother_index)]

    def as_dict(self) -> dict[str, Any]:
        return {"schema": "synlab.relations.event_library_plan.v1",
                "version": MULTI_EVENT_VERSION,
                "master_seed": int(self.master_seed),
                "mothers": [m.as_dict() for m in self.mothers],
                "events": [e.as_dict() for e in self.events],
                "events_per_mother": self.events_per_mother,
                "events_total": self.events_total,
                "independent_mothers": len(self.mothers),
                "notes": list(self.notes)}


def plan_event_library(mothers: Sequence[Mapping[str, Any]], *,
                       n_events: int = 3, master_seed: int = 20261001,
                       grey_zone_mothers: Iterable[int] = (),
                       distractor_indices: Iterable[int] = (),
                       unresolved_mothers: Iterable[int] = ()) -> LibraryPlan:
    """Freeze the event library: >= 3 independent events per mother, each with its own seed.

    ``mothers`` entries are the ``{lineage_id, split, vessel_id, material_id, pattern_id,
    layer_combo_id, params, mother_index}`` mappings of an executed run plan
    (``data/a12/reports/run_spec_run_*.json`` -> ``plan``), so the parameters are known-good.

    The **last** event of a mother listed in ``grey_zone_mothers`` is planned with role
    ``grey_zone``; its plane is dialled at run time so that the *measured* interface area lands
    in the frozen grey zone.  Nothing here invents an area.  Every other event (the third and
    beyond) is a **plain** ``extra`` cut on its own base azimuth -- see ``ROLE_EXTRA`` for the
    measured reason the third event must not default to a grey-zone dial.
    """
    if int(n_events) < 3:
        raise SynLabError(ErrorCode.SCHEMA_INVALID,
                          "an event library needs >= 3 mutually exclusive events per mother "
                          "(plan 11.1: R1 requires a second event of the same mother)",
                          stage="relations.multi_event.plan_event_library",
                          measurements={"n_events": int(n_events)})
    grey = {int(i) for i in grey_zone_mothers}
    distractors = {int(i) for i in distractor_indices}
    unresolved = {int(i) for i in unresolved_mothers}
    plan = LibraryPlan(master_seed=int(master_seed))
    for entry in mothers:
        index = int(entry.get("mother_index", len(plan.mothers)))
        distractor = index in distractors
        split = SPLIT_DISTRACTOR if distractor else str(entry.get("split", "dev"))
        mother = MotherPlan(
            lineage_id=str(entry["lineage_id"]), split=split,
            vessel_id=str(entry["vessel_id"]), material_id=str(entry["material_id"]),
            pattern_id=str(entry.get("pattern_id", "")),
            layer_combo_id=(None if entry.get("layer_combo_id") in (None, "")
                            else str(entry["layer_combo_id"])),
            params=dict(entry.get("params") or {}), mother_index=index, distractor=distractor)
        plan.mothers.append(mother)
        for order in range(int(n_events)):
            role = ROLE_GREY_ZONE if (order == int(n_events) - 1 and index in grey) else (
                EVENT_ROLES[min(order, len(EVENT_ROLES) - 1)])
            event_id = f"{mother.lineage_id}_E{order + 1:02d}"
            plan.events.append(EventPlan(
                event_id=event_id, mother_index=index, lineage_id=mother.lineage_id, role=role,
                seed_ref=seed_ref(plan.master_seed, mother.lineage_id, "cut", event_id),
                note=("plane dialled into the frozen grey zone"
                      if role == ROLE_GREY_ZONE else "cut plane drawn from the event seed")))
        if index in unresolved:
            event_id = f"{mother.lineage_id}_EU"
            plan.events.append(EventPlan(
                event_id=event_id, mother_index=index, lineage_id=mother.lineage_id,
                role=ROLE_UNRESOLVED,
                seed_ref=seed_ref(plan.master_seed, mother.lineage_id, "cut", event_id),
                note="fracture runs for real, clean truth deliberately not computed: the "
                     "relation evidence of these fragments is missing, so every pair that "
                     "mentions one of them is UNKNOWN (plan 11.1), never R0"))
    plan.notes.append("events of one mother are mutually exclusive alternatives of the same "
                      "physical body; they are not fragments of one another")
    plan.notes.append("every event id is distinct and every event draws its own cut sub-stream "
                      "make_rng(master_seed, lineage_id, 'cut', event_id)")
    if unresolved:
        plan.notes.append("mothers listed in unresolved_mothers carry one extra event whose "
                          "clean truth is deliberately not computed; every pair that mentions "
                          "one of its fragments is UNKNOWN with loss_mask=False (plan 11.1) and "
                          "must never be used as a negative")
    return plan


# --------------------------------------------------------------------------------------
# running (real fracture + real clean truth)
# --------------------------------------------------------------------------------------
def _section_area_mm2(mesh: Any, normal: np.ndarray, origin: np.ndarray) -> float:
    """Measured cross-section area of ``mesh`` by the plane (normal, origin), in mm^2."""
    import trimesh

    section = trimesh.intersections.mesh_plane(
        mesh, plane_normal=np.asarray(normal, dtype=np.float64),
        plane_origin=np.asarray(origin, dtype=np.float64))
    if section is None or len(section) == 0:
        return 0.0
    path = trimesh.load_path(np.asarray(section, dtype=np.float64))
    try:
        planar, _tf = path.to_planar()
        return float(sum(poly.area for poly in planar.polygons_full))
    except Exception:  # noqa: BLE001 - fall back to the segment-length bound, recorded by caller
        return float(np.sum(np.linalg.norm(np.diff(section, axis=1), axis=2)))


def dial_grey_zone_plane(mother: Any, *, target_area_mm2: float, direction: Sequence[float],
                         search_steps: int = 28) -> dict[str, Any]:
    """Dial a cut plane whose **measured** cross-section area matches ``target_area_mm2``.

    The plane is found by bisecting the offset along ``direction`` while measuring the real
    cross-section of the mother mesh (``trimesh.intersections.mesh_plane``).  Only the *plane*
    is chosen here; the relation verdict still comes from the fracture's own measured interface
    area, so a mis-dialed plane degrades into a wrong *role*, never into a fabricated area.
    """
    mesh = mother.mesh
    points = np.asarray(mesh.vertices, dtype=np.float64)
    normal = np.asarray(direction, dtype=np.float64).reshape(3)
    normal = normal / max(float(np.linalg.norm(normal)), 1e-12)
    centre = points.mean(axis=0)
    projections = (points - centre) @ normal
    low = float(np.min(projections)) + 1e-6
    high = float(np.max(projections)) - 1e-6
    history: list[dict[str, Any]] = []

    def area_at(offset: float) -> float:
        return _section_area_mm2(mesh, normal, centre + normal * float(offset))

    best_offset, best_area = high, 0.0
    for _ in range(int(search_steps)):
        middle = 0.5 * (low + high)
        area = area_at(middle)
        history.append({"offset_mm": middle, "section_area_mm2": area})
        if abs(area - float(target_area_mm2)) < abs(best_area - float(target_area_mm2)):
            best_offset, best_area = middle, area
        if area > float(target_area_mm2):
            high = middle          # too much material on the cap side -> cut deeper
        else:
            low = middle
        if abs(area - float(target_area_mm2)) <= max(1e-9, 0.02 * float(target_area_mm2)):
            best_offset, best_area = middle, area
            break
    return {"plane_point": (centre + normal * best_offset).tolist(),
            "plane_normal": normal.tolist(), "target_area_mm2": float(target_area_mm2),
            "measured_section_area_mm2": float(best_area), "search_steps": len(history),
            "search_history": history}


def run_event_library(plan: LibraryPlan, *, fracture_config: Any,
                      work_dir: str | Path | None = None,
                      mesh_dir: str | Path | None = None,
                      only_mothers: Sequence[int] | None = None,
                      micro_events: bool = True) -> dict[str, Any]:
    """Run every planned event for real; returns the measured library (JSON-serialisable).

    ``work_dir`` makes the run resumable: each mother's result is written to
    ``<work_dir>/mother_<index>.json`` and reused on the next call, so a long library can be
    built in several bounded steps (the host kills long heavy processes).  ``mesh_dir`` stores
    every produced fragment mesh as ``<mesh_dir>/mesh_<fragment_id>.npz`` so the real geometry
    can be committed later without re-running the fracture.
    """
    from ..fracture.api import audit_fracture, fracture_event
    from ..fracture.spec import BACKEND_PLANE, FractureSpec
    from ..mothers.api import create_mother
    from ..truth.api import finalize_clean_truth

    directory = Path(work_dir) if work_dir is not None else None
    if directory is not None:
        directory.mkdir(parents=True, exist_ok=True)
    meshes = Path(mesh_dir) if mesh_dir is not None else None
    if meshes is not None:
        meshes.mkdir(parents=True, exist_ok=True)
    wanted = ({int(i) for i in only_mothers} if only_mothers is not None
              else {m.mother_index for m in plan.mothers})
    library: dict[str, Any] = {
        "schema": "synlab.relations.event_library.v1", "version": MULTI_EVENT_VERSION,
        "master_seed": int(plan.master_seed), "plan": plan.as_dict(), "mothers": [], "ok": False,
    }
    for mother_plan in plan.mothers:
        if mother_plan.mother_index not in wanted:
            continue
        cache = (directory / f"mother_{mother_plan.mother_index:04d}.json") if directory else None
        if cache is not None and cache.exists():
            library["mothers"].append(json.loads(cache.read_text(encoding="utf-8")))
            continue
        record = _run_one_mother(mother_plan, plan, fracture_config=fracture_config,
                                 create_mother=create_mother, fracture_event=fracture_event,
                                 audit_fracture=audit_fracture, finalize_clean_truth=finalize_clean_truth,
                                 fracture_spec_cls=FractureSpec, plane_backend=BACKEND_PLANE,
                                 micro_events=micro_events, mesh_dir=meshes)
        if cache is not None:
            cache.write_text(json.dumps(record, ensure_ascii=False, indent=2, default=str),
                             encoding="utf-8")
        library["mothers"].append(record)
    library["ok"] = bool(library["mothers"]) and all(m["ok"] for m in library["mothers"])
    library["exclusion"] = verify_event_exclusion(library)
    library["ok"] = bool(library["ok"] and library["exclusion"]["ok"])
    return library


def _run_one_mother(mother_plan: MotherPlan, plan: LibraryPlan, *, fracture_config: Any,
                    create_mother: Any, fracture_event: Any, audit_fracture: Any,
                    finalize_clean_truth: Any, fracture_spec_cls: Any,
                    plane_backend: str, micro_events: bool,
                    mesh_dir: Path | None = None) -> dict[str, Any]:
    from ..fracture.spec import R2_AREA_ABS_MM2, R2_AREA_REL, TINY_AREA_ABS_MM2, TINY_AREA_REL
    from ..fracture.spec import TINY_VOLUME_MM3

    record: dict[str, Any] = {"mother": mother_plan.as_dict(), "events": [], "ok": False}
    started = time.perf_counter()
    rng_shape = make_rng(plan.master_seed, mother_plan.lineage_id, "shape")
    mother = create_mother(mother_plan.vessel_id, mother_plan.material_id, mother_plan.params,
                           rng_shape, mother_id=mother_plan.mother_id)
    mother_area = float(getattr(mother, "area_mm2", 0.0) or 0.0)
    area_threshold = max(R2_AREA_ABS_MM2, R2_AREA_REL * mother_area)
    tiny_threshold = max(TINY_AREA_ABS_MM2, TINY_AREA_REL * mother_area)
    record["mother"].update({
        "vertices": int(len(mother.mesh.vertices)), "faces": int(len(mother.mesh.faces)),
        "area_mm2": mother_area, "volume_mm3": float(getattr(mother, "volume_mm3", 0.0) or 0.0),
        "r2_area_threshold_mm2": float(area_threshold),
        "tiny_area_threshold_mm2": float(tiny_threshold),
        "mother_seconds": time.perf_counter() - started})

    for event_plan in plan.events_of(mother_plan.mother_index):
        item: dict[str, Any] = {"plan": event_plan.as_dict(), "ok": False, "attempts": []}
        record["events"].append(item)
        t0 = time.perf_counter()
        for attempt_index, (spec, attempt_meta) in enumerate(_event_candidates(
                event_plan, fracture_config, fracture_spec_cls, plane_backend, mother=mother,
                area_threshold=area_threshold, tiny_threshold=tiny_threshold,
                master_seed=plan.master_seed)):
            attempt: dict[str, Any] = {"attempt": attempt_index, **attempt_meta}
            item["attempts"].append(attempt)
            try:
                rng = make_rng(plan.master_seed, mother_plan.lineage_id, "cut",
                               event_plan.event_id, attempt_index)
                event_id = (event_plan.event_id if attempt_index == 0
                            else f"{event_plan.event_id}_a{attempt_index}")
                fracture = fracture_event(mother, spec, rng, event_id=event_id)
                audit = audit_fracture(fracture, mother)
                clean = (None if event_plan.role == ROLE_UNRESOLVED
                         else finalize_clean_truth(mother, fracture))
            except Exception as exc:  # noqa: BLE001 - a failed attempt is a recorded outcome
                attempt.update({"ok": False, "error": f"{type(exc).__name__}: {exc}",
                                "error_code": str(getattr(getattr(exc, "code", None), "value", "")),
                                "seconds": time.perf_counter() - t0})
                item["last_error"] = attempt["error"]
                continue
            if mesh_dir is not None:
                _persist_meshes(mesh_dir, fracture)
            measured = _event_measurements(mother, fracture, clean, audit,
                                           _renamed_event(event_plan, event_id),
                                           r2_threshold=area_threshold,
                                           tiny_threshold=tiny_threshold,
                                           tiny_volume_mm3=TINY_VOLUME_MM3)
            measured["fracture_spec"] = {
                "backend": str(spec.backend),
                "plane_point": None if spec.plane_point is None
                else np.asarray(spec.plane_point, dtype=float).tolist(),
                "plane_normal": None if spec.plane_normal is None
                else np.asarray(spec.plane_normal, dtype=float).tolist(),
                "plane_source": spec.meta.get("plane_source", "seed")}
            measured["grey_zone_dial"] = spec.meta.get("grey_zone_dial")
            measured["event_id"] = event_id
            measured["plan"] = {**event_plan.as_dict(), "event_id": event_id,
                                "role": event_plan.role}
            measured["attempts"] = list(item["attempts"])
            satisfied, why = _role_satisfied(measured, tallow=tiny_threshold,
                                             r2_threshold=area_threshold)
            measured["role_satisfied"] = satisfied
            measured["role_check"] = why
            measured["seconds"] = time.perf_counter() - t0
            measured["ok"] = True
            attempt.update({"ok": True, "seconds": measured["seconds"],
                            "fragment_ids": measured["fragment_ids"],
                            "relation_histogram": measured["relation_histogram"],
                            "role_satisfied": satisfied, "role_check": why})
            item.clear()
            item.update(measured)
            break
        if not item.get("ok"):
            item["seconds"] = time.perf_counter() - t0
    usable = [e for e in record["events"] if e["ok"]]
    record["ok"] = len(usable) >= 3 and len({e["event_id"] for e in usable}) == len(usable)
    record["events_ok"] = len(usable)
    record["seconds"] = time.perf_counter() - started
    return record


def _persist_meshes(mesh_dir: Path, fracture: Any) -> None:
    """Store every fragment mesh of one event as a compressed npz (real geometry, kept)."""
    for fragment in getattr(fracture, "fragments", []):
        mesh = getattr(fragment, "mesh", None)
        if mesh is None:
            continue
        path = Path(mesh_dir) / f"mesh_{fragment.fragment_id}.npz"
        if path.exists():
            continue
        np.savez_compressed(path,
                            vertices=np.asarray(mesh.vertices, dtype=np.float64),
                            faces=np.asarray(mesh.faces, dtype=np.int64),
                            origin_kind=np.asarray(fragment.face_origin_kind, dtype=np.uint8),
                            source_triangle=np.asarray(fragment.face_source_tri, dtype=np.int32),
                            interface_id=np.asarray(fragment.face_interface_id, dtype=np.int32),
                            side=np.asarray(fragment.face_side, dtype=np.int8))


def _renamed_event(event_plan: EventPlan, event_id: str) -> EventPlan:
    if event_id == event_plan.event_id:
        return event_plan
    return EventPlan(event_id=event_id, mother_index=event_plan.mother_index,
                     lineage_id=event_plan.lineage_id, role=event_plan.role,
                     seed_ref=event_plan.seed_ref, plane_point=event_plan.plane_point,
                     plane_normal=event_plan.plane_normal, note=event_plan.note)


def _role_satisfied(measured: Mapping[str, Any], *, tallow: float,
                    r2_threshold: float) -> tuple[bool, str]:
    """Did the event play the role the plan asked for?  Decided on measured numbers only."""
    role = str(measured.get("plan", {}).get("role", ""))
    if role == ROLE_UNRESOLVED:
        return (measured.get("truth_status") == "NOT_COMPUTED",
                "fracture ran, clean truth deliberately not computed -> UNKNOWN evidence")
    areas = [float(r["area_mm2"]) for r in measured.get("relations", [])
             if str(r["kind"]) in (RELATION_R2, RELATION_TINY)]
    kinds = {str(r["kind"]) for r in measured.get("relations", [])}
    if role == ROLE_GREY_ZONE:
        if RELATION_TINY in kinds:
            return True, f"TINY_CONTACT measured, area={max(areas, default=0.0):.6g} mm^2"
        if RELATION_R2 in kinds:
            return False, (f"grey-zone plane still produced R2 "
                           f"(area={max(areas, default=0.0):.6g} >= {r2_threshold:.6g} mm^2)")
        return False, f"no R2/TINY pair was produced (kinds={sorted(kinds)})"
    if RELATION_R2 in kinds:
        return True, f"R2 measured, area={max(areas, default=0.0):.6g} mm^2"
    return False, (f"no R2 pair was produced (kinds={sorted(kinds)}, "
                   f"tiny threshold={tallow:.6g} mm^2)")


def _event_candidates(event_plan: EventPlan, fracture_config: Any, fracture_spec_cls: Any,
                      plane_backend: str, *, mother: Any, area_threshold: float,
                      tiny_threshold: float, master_seed: int,
                      max_attempts: int = 5) -> list[tuple[Any, dict[str, Any]]]:
    """Candidate specs for one event: an event-seeded plane, several dialled planes for the grey zone.

    A **non-grey** event gets an explicit plane derived from its own event id and role
    (``ROLE_BASE_AZIMUTH`` + seeded jitter + a rotation per retry), because the frozen default
    basis of ``fracture.api`` is body-determined: without an explicit plane every event of one
    mother is the same cut (measured, see ``ROLE_BASE_AZIMUTH``).  Retries rotate the plane
    further, so a refused event is retried on genuinely different geometry and every attempt is
    recorded.

    A **grey-zone** plane has to be *dialled*: the frozen area band
    ``[max(1e-3, 1e-6 A_mother), max(0.1, 1e-4 A_mother))`` is wide but a real boolean can still
    refuse an extremely oblique sliver cut (``FRACTURE_CONSERVATION_FAIL``), so several
    directions/areas inside the band are tried in a deterministic order and every attempt is
    recorded -- including the ones that failed.

    The targets are ordered from the **least oblique** cut that is still inside the band
    (``0.95 * band_high``, just below the R2 threshold) downwards: a plane whose cross-section is
    a sliver grazing the rim is what the conservation audit refuses, and the measured probe in
    ``data/a12/reports/_neg_greyzone_probe.json`` shows the refusal is worst for the smallest
    targets.  No threshold is touched: the band and the audit stay exactly as frozen.
    """
    if event_plan.role != ROLE_GREY_ZONE:
        points = np.asarray(mother.mesh.vertices, dtype=np.float64)
        centre = points.mean(axis=0)
        out_plain: list[tuple[Any, dict[str, Any]]] = []
        base = float(ROLE_BASE_AZIMUTH.get(event_plan.role, 0.0))
        for index in range(int(max_attempts)):
            rng = make_rng(master_seed, event_plan.lineage_id, "cut_plane", event_plan.event_id,
                           index)
            azimuth = (base + index * float(PLANE_RETRY_STEP_RAD)
                       + float(rng.uniform(-PLANE_JITTER_RAD, PLANE_JITTER_RAD)))
            tilt = float(rng.uniform(-PLANE_TILT_RAD, PLANE_TILT_RAD))
            normal = np.array([np.cos(azimuth), np.sin(azimuth), tilt])
            normal = normal / max(float(np.linalg.norm(normal)), 1e-12)
            out_plain.append((fracture_spec_cls(
                backend=plane_backend,
                error_budget_mm=float(getattr(fracture_config, "shared_surface_max_error_mm",
                                              0.01)),
                target_rms_mm=float(np.mean(getattr(fracture_config, "rough_amplitude_mm",
                                                    (0.02, 0.3)))),
                plane_point=centre, plane_normal=normal,
                meta={"plane_source": "event_seeded", "event_role": event_plan.role,
                      "plane_azimuth_rad": azimuth, "plane_tilt": tilt}),
                {"kind": "event_seeded_plane", "attempt_index": index,
                 "plane_azimuth_rad": azimuth, "plane_tilt": tilt}))
        return out_plain
    band_low, band_high = float(tiny_threshold), float(area_threshold)
    targets = [0.95 * band_high, 0.80 * band_high, 0.60 * band_high, 0.40 * band_high,
               float(np.sqrt(band_low * band_high))]
    out: list[tuple[Any, dict[str, Any]]] = []
    for index in range(int(max_attempts)):
        rng = make_rng(master_seed, event_plan.event_id, "grey_zone", index)
        azimuth = float(rng.uniform(0.0, 2.0 * np.pi))
        # a mostly horizontal normal like the frozen seed basis: it splits the body through its
        # axis, which keeps the boolean well conditioned; the tilt is what the seed varies.
        tilt = float(rng.uniform(-0.2, 0.2))
        direction = np.array([np.cos(azimuth), np.sin(azimuth), tilt])
        target = targets[index % len(targets)]
        dial = dial_grey_zone_plane(mother, target_area_mm2=target, direction=direction)
        spec = fracture_spec_cls(
            backend=plane_backend,
            error_budget_mm=float(getattr(fracture_config, "shared_surface_max_error_mm", 0.01)),
            target_rms_mm=float(np.mean(getattr(fracture_config, "rough_amplitude_mm",
                                                (0.02, 0.3)))),
            plane_point=np.asarray(dial["plane_point"], dtype=np.float64),
            plane_normal=np.asarray(dial["plane_normal"], dtype=np.float64),
            meta={"plane_source": "grey_zone_dial", "event_role": event_plan.role,
                  "grey_zone_dial": {k: v for k, v in dial.items() if k != "search_history"},
                  "grey_zone_target_area_mm2": target,
                  "r2_area_threshold_mm2": band_high, "tiny_area_threshold_mm2": band_low})
        out.append((spec, {"kind": "grey_zone_dial", "target_area_mm2": target,
                           "direction": direction.tolist(),
                           "dialed_section_area_mm2": dial["measured_section_area_mm2"],
                           "dial_search_steps": dial["search_steps"]}))
    return out


def _interface_face_plane(fragment: Any) -> dict[str, Any]:
    """Measure the cut plane of one fragment **from its own mesh**, not from the truth layer.

    Faces tagged ``face_interface_id >= 0`` are the new fracture faces of that fragment; their
    area-weighted mean normal and the area-weighted mean of ``n . centroid`` define the plane
    the event cut along.  This works for every event, including one whose clean truth was not
    computed, so the mutual-exclusion check never depends on the layer it is checking.
    """
    mesh = getattr(fragment, "mesh", None)
    ids = np.asarray(getattr(fragment, "face_interface_id", np.zeros(0)), dtype=np.int64)
    if mesh is None or ids.size == 0:
        return {"interface_face_count": 0, "interface_face_area_mm2": 0.0,
                "interface_plane": None}
    faces = np.asarray(mesh.faces, dtype=np.int64)
    if faces.shape[0] != ids.size:
        return {"interface_face_count": 0, "interface_face_area_mm2": 0.0,
                "interface_plane": None}
    selected = np.nonzero(ids >= 0)[0]
    if selected.size == 0:
        return {"interface_face_count": 0, "interface_face_area_mm2": 0.0,
                "interface_plane": None}
    triangles = np.asarray(mesh.triangles, dtype=np.float64)[selected]
    normals = np.asarray(mesh.face_normals, dtype=np.float64)[selected]
    areas = np.asarray(mesh.area_faces, dtype=np.float64)[selected]
    total = float(areas.sum())
    if total <= 0.0:
        return {"interface_face_count": int(selected.size), "interface_face_area_mm2": 0.0,
                "interface_plane": None}
    weighted_normal = (normals * areas[:, None]).sum(axis=0)
    magnitude = float(np.linalg.norm(weighted_normal))
    if magnitude <= 1e-12:
        return {"interface_face_count": int(selected.size), "interface_face_area_mm2": total,
                "interface_plane": None}
    normal = weighted_normal / magnitude
    centroids = triangles.mean(axis=1)
    offset = float((centroids @ normal * areas).sum() / total)
    spread = np.degrees(np.arccos(np.clip(np.abs(normals @ normal), -1.0, 1.0)))
    return {"interface_face_count": int(selected.size), "interface_face_area_mm2": total,
            "interface_plane": {"plane_normal": normal.tolist(), "offset_mm": offset,
                                "normal_spread_max_deg": float(np.max(spread)),
                                "source": "measured_from_fragment_interface_faces"}}


def _event_plane(event: Mapping[str, Any]) -> dict[str, Any] | None:
    """The cut plane of an event, measured from its fragments (truth-independent).

    The fragment-level ``interface_plane`` (area-weighted normals of the faces the fragment
    itself tags as new fracture faces) is authoritative here: it exists even for an event whose
    clean truth was not computed, so the exclusion check never depends on the layer it checks.
    The truth-derived ``plane`` is only a fallback.
    """
    best: dict[str, Any] | None = None
    for fragment in event.get("fragments", []):
        plane = fragment.get("interface_plane")
        if plane is None:
            continue
        if best is None or float(fragment.get("interface_face_area_mm2", 0.0)) > float(
                best.get("interface_face_area_mm2", 0.0)):
            best = {**plane, "fragment_id": fragment.get("fragment_id"),
                    "interface_face_area_mm2": float(
                        fragment.get("interface_face_area_mm2", 0.0))}
    if best is not None:
        return best
    fallback = event.get("plane")
    return None if fallback is None else dict(fallback)


def _event_measurements(mother: Any, fracture: Any, clean: Any, audit: Mapping[str, Any],
                        event_plan: EventPlan, *, r2_threshold: float, tiny_threshold: float,
                        tiny_volume_mm3: float) -> dict[str, Any]:
    """The measured facts of one event: fragments, interfaces, verdicts, cut plane."""
    from ..fracture.booleans import mesh_hash

    fragments = list(getattr(fracture, "fragments", []))
    fragment_rows = []
    for fragment in fragments:
        mesh = getattr(fragment, "mesh", None)
        row = {
            "fragment_id": str(getattr(fragment, "fragment_id", "")),
            "volume_mm3": float(getattr(fragment, "volume_mm3", 0.0) or 0.0),
            "area_mm2": float(getattr(fragment, "area_mm2", 0.0) or 0.0),
            "is_tiny": bool(float(getattr(fragment, "volume_mm3", 0.0) or 0.0)
                            < float(tiny_volume_mm3)),
            "vertices": int(len(np.asarray(mesh.vertices))) if mesh is not None else 0,
            "faces": int(len(np.asarray(mesh.faces))) if mesh is not None else 0,
            "mesh_hash": (mesh_hash(mesh) if mesh is not None else ""),
        }
        row.update(_interface_face_plane(fragment))
        fragment_rows.append(row)
    patches = []
    normals: list[np.ndarray] = []
    points: list[np.ndarray] = []
    for patch in ([] if clean is None else getattr(clean, "interfaces", [])):
        normal_a = np.asarray(getattr(patch, "normals_a", np.zeros((0, 3))), dtype=np.float64)
        point_a = np.asarray(getattr(patch, "sample_points_a", np.zeros((0, 3))), dtype=np.float64)
        mean_normal = (normal_a.mean(axis=0) if normal_a.size else np.zeros(3))
        mean_point = (point_a.mean(axis=0) if point_a.size else np.zeros(3))
        if normal_a.size:
            normals.append(mean_normal / max(float(np.linalg.norm(mean_normal)), 1e-12))
            points.append(mean_point)
        evidence = (getattr(clean, "meta", {}) or {}).get("patch_evidence", {}).get(
            int(getattr(patch, "interface_id", -1)), {}) if clean is not None else {}
        patches.append({
            "interface_id": int(getattr(patch, "interface_id", -1)),
            "fragment_a": str(getattr(patch, "fragment_a", "")),
            "fragment_b": str(getattr(patch, "fragment_b", "")),
            "area_mm2": float(getattr(patch, "area_mm2", 0.0) or 0.0),
            "common_clip_area_mm2": float((getattr(patch, "meta", {}) or {}).get(
                "common_clip_area_mm2", 0.0) or 0.0),
            "pair_common_clip_area_mm2": (None if (getattr(patch, "meta", {}) or {}).get(
                "pair_common_clip_area_mm2") is None else float(
                (getattr(patch, "meta", {}) or {})["pair_common_clip_area_mm2"])),
            "gap_p95_mm": float(getattr(patch, "gap_p95_mm", 0.0) or 0.0),
            "normal_angle_p95_deg": float(getattr(patch, "normal_angle_p95_deg", 0.0) or 0.0),
            "ambiguous_area_ratio": float(getattr(patch, "ambiguous_area_ratio", 0.0) or 0.0),
            "patch_kind": str(evidence.get("kind", "")),
            "patch_reason": str(evidence.get("reason", "")),
        })
    plane = None
    if normals:
        stacked = np.stack(normals)
        mean_normal = stacked.mean(axis=0)
        magnitude = float(np.linalg.norm(mean_normal))
        if magnitude > 1e-9:
            mean_normal = mean_normal / magnitude
            mean_point = np.stack(points).mean(axis=0)
            plane = {"plane_normal": mean_normal.tolist(), "plane_point": mean_point.tolist(),
                     "offset_mm": float(np.dot(mean_normal, mean_point)),
                     "normal_spread_max_deg": float(np.degrees(np.max(
                         np.arccos(np.clip(np.abs(stacked @ mean_normal), -1.0, 1.0))))),
                     "source": "measured_from_interface_patches"}
    relations = []
    for (a, b), edge in ({} if clean is None else clean.relations).items():
        relations.append({"a": str(a), "b": str(b), "kind": str(edge.kind),
                          "area_mm2": float(edge.area_mm2), "valid": bool(edge.valid),
                          "loss_mask": bool(edge.loss_mask),
                          "interface_id": (None if edge.interface_id is None
                                           else int(edge.interface_id)),
                          "reason": str(edge.reason)})
    kinds: dict[str, int] = {}
    for row in relations:
        kinds[row["kind"]] = kinds.get(row["kind"], 0) + 1
    return {
        "truth_status": ("NOT_COMPUTED" if clean is None else "COMPUTED"),
        "fragment_ids": [row["fragment_id"] for row in fragment_rows],
        "fragments": fragment_rows,
        "interface_ids": sorted({row["interface_id"] for row in patches}),
        "interfaces": patches,
        "plane": plane,
        "relations": relations,
        "relation_histogram": kinds,
        "clean_qa": ({k: v for k, v in (getattr(clean, "qa", {}) or {}).items()
                      if isinstance(v, (int, float, bool, str))} if clean is not None else {}),
        "clean_meta": ({k: v for k, v in (getattr(clean, "meta", {}) or {}).items()
                        if k in ("mother_area_mm2", "r2_area_threshold_mm2",
                                 "tiny_area_threshold_mm2", "r2_area_threshold_rule")}
                       if clean is not None else {}),
        "fracture_audit": {k: v for k, v in dict(audit).items()
                           if isinstance(v, (int, float, bool, str))},
        "fracture_audit_ok": bool(audit.get("ok", audit.get("passed", True))),
        "r2_area_threshold_mm2": float(r2_threshold),
        "tiny_area_threshold_mm2": float(tiny_threshold),
        "event_id": event_plan.event_id,
    }


# --------------------------------------------------------------------------------------
# exclusion verification (the "no shared real fracture surface" claim)
# --------------------------------------------------------------------------------------
def verify_event_exclusion(library: Mapping[str, Any]) -> dict[str, Any]:
    """Verify the mutually-exclusive claim for every pair of events of the same mother.

    Three independent checks, all measured on the produced events:

    ``no_shared_patch``   no interface patch of any event connects a fragment of event *i* with
                          a fragment of event *j* (a shared real fracture surface would have to
                          appear as such a patch);
    ``distinct_plane``    the measured cut planes of two events are not the same plane (normals
                          anti/parallel within ``PLANE_NORMAL_TOL`` **and** offsets within
                          ``PLANE_OFFSET_TOL_MM``) -- if they were, the two events would cut
                          along one and the same fracture surface;
    ``distinct_mesh``     two events never produce the byte-identical fragment mesh set.
    """
    problems: list[dict[str, Any]] = []
    pairs_checked = 0
    mothers = list(library.get("mothers") or [])
    for mother in mothers:
        events = [e for e in mother.get("events", []) if e.get("ok")]
        owner: dict[str, str] = {}
        for event in events:
            for fragment_id in event.get("fragment_ids", []):
                owner[str(fragment_id)] = str(event["event_id"])
        for i, first in enumerate(events):
            for second in events[i + 1:]:
                pairs_checked += 1
                a, b = str(first["event_id"]), str(second["event_id"])
                left = {str(f) for f in first.get("fragment_ids", [])}
                right = {str(f) for f in second.get("fragment_ids", [])}
                for event in events:
                    for patch in event.get("interfaces", []):
                        ends = {str(patch.get("fragment_a", "")), str(patch.get("fragment_b", ""))}
                        if ends & left and ends & right:
                            problems.append({"check": "no_shared_patch", "events": [a, b],
                                             "interface_id": patch.get("interface_id"),
                                             "fragments": sorted(ends)})
                plane_a, plane_b = _event_plane(first), _event_plane(second)
                if plane_a is None or plane_b is None:
                    problems.append({"check": "plane_unmeasured", "events": [a, b]})
                    continue
                normal_a = np.asarray(plane_a["plane_normal"], dtype=np.float64)
                normal_b = np.asarray(plane_b["plane_normal"], dtype=np.float64)
                alignment = abs(float(np.dot(normal_a, normal_b)))
                offset_gap = abs(float(plane_a["offset_mm"]) - float(plane_b["offset_mm"]))
                if alignment >= 1.0 - PLANE_NORMAL_TOL and offset_gap <= PLANE_OFFSET_TOL_MM:
                    problems.append({"check": "distinct_plane", "events": [a, b],
                                     "normal_alignment": alignment,
                                     "offset_gap_mm": offset_gap})
                hashes_a = {str(f["mesh_hash"]) for f in first.get("fragments", [])}
                hashes_b = {str(f["mesh_hash"]) for f in second.get("fragments", [])}
                if hashes_a and hashes_a == hashes_b:
                    problems.append({"check": "distinct_mesh", "events": [a, b],
                                     "mesh_hash": sorted(hashes_a)[:2]})
    return {"ok": not problems, "problems": problems, "event_pairs_checked": pairs_checked,
            "mothers": len(mothers),
            "checks": ["no_shared_patch", "distinct_plane", "distinct_mesh"],
            "tolerances": {"plane_normal_tol": PLANE_NORMAL_TOL,
                           "plane_offset_tol_mm": PLANE_OFFSET_TOL_MM}}


# --------------------------------------------------------------------------------------
# labelling: the library-level relation table
# --------------------------------------------------------------------------------------
def classify_library(library: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Every unordered fragment pair of the library with its traceable verdict (plan 11.1).

    The order of the decision is fixed and each row records which branch decided it:

    ``surface``   both fragments belong to one event and that event's measured clean truth has
                  an edge for the pair -> the **measured** kind and area are copied verbatim;
    ``within``    both fragments belong to one event, no edge exists -> ``R1`` with the truth's
                  own reason (``no_direct_fracture_surface``);
    ``cross``     same mother, different (verified mutually exclusive) events -> ``R1``;
    ``mother``    different physical mothers -> ``R0``.
    """
    fragments: dict[str, dict[str, Any]] = {}
    for mother in library.get("mothers") or []:
        mother_row = mother["mother"]
        for event in mother.get("events", []):
            if not event.get("ok"):
                continue
            for fragment in event.get("fragments", []):
                fragments[str(fragment["fragment_id"])] = {
                    "fragment_id": str(fragment["fragment_id"]),
                    "mother_id": str(mother_row["lineage_id"]),
                    "lineage_id": str(mother_row["lineage_id"]),
                    "event_id": str(event["event_id"]),
                    "split": str(mother_row["split"]),
                    "volume_mm3": float(fragment.get("volume_mm3", 0.0)),
                    "is_tiny": bool(fragment.get("is_tiny", False)),
                    "event_role": str(event["plan"]["role"]),
                    "truth_status": str(event.get("truth_status", "COMPUTED")),
                }
    measured: dict[tuple[str, str], dict[str, Any]] = {}
    event_ids: dict[str, str] = {}
    for mother in library.get("mothers") or []:
        for event in mother.get("events", []):
            if not event.get("ok"):
                continue
            event_ids[str(event["event_id"])] = str(mother["mother"]["lineage_id"])
            for row in event.get("relations", []):
                key = (str(row["a"]), str(row["b"]))
                measured[(key[0], key[1]) if key[0] <= key[1] else (key[1], key[0])] = {
                    **row, "event_id": str(event["event_id"])}
    out: list[dict[str, Any]] = []
    identifiers = sorted(fragments)
    for i, first in enumerate(identifiers):
        for second in identifiers[i + 1:]:
            a, b = fragments[first], fragments[second]
            base = {"a": first, "b": second, "mother_a": a["mother_id"],
                    "mother_b": b["mother_id"], "event_a": a["event_id"],
                    "event_b": b["event_id"], "lineage_a": a["lineage_id"],
                    "lineage_b": b["lineage_id"], "split_a": a["split"], "split_b": b["split"]}
            unresolved = [f for f in (a, b) if f.get("truth_status") != "COMPUTED"]
            if unresolved:
                out.append({**base, "kind": RELATION_UNKNOWN, "area_mm2": 0.0, "valid": False,
                            "loss_mask": False, "interface_id": None,
                            "reason": "truth_not_computed_for_source_event",
                            "decidability": "insufficient_evidence", "measured_surface": False,
                            "evidence": {"basis": "clean_truth_not_computed",
                                         "fragments": [f["fragment_id"] for f in unresolved],
                                         "events": [f["event_id"] for f in unresolved]}})
                continue
            if a["mother_id"] != b["mother_id"]:
                out.append({**base, "kind": RELATION_R0, "area_mm2": 0.0, "valid": True,
                            "loss_mask": True, "interface_id": None,
                            "reason": "different_physical_mother",
                            "decidability": "mother", "measured_surface": False,
                            "evidence": {"basis": "different_physical_mother",
                                         "mothers": [a["mother_id"], b["mother_id"]]}})
                continue
            if a["event_id"] == b["event_id"]:
                edge = measured.get((first, second))
                if edge is not None:
                    out.append({**base, "kind": edge["kind"], "area_mm2": edge["area_mm2"],
                                "valid": edge["valid"], "loss_mask": edge["loss_mask"],
                                "interface_id": edge.get("interface_id"),
                                "reason": edge.get("reason", ""), "decidability": "surface",
                                "measured_surface": edge["kind"] in (RELATION_R2, RELATION_TINY),
                                "evidence": {"basis": "same_event_measured_interface",
                                             "event_id": a["event_id"],
                                             "interface_id": edge.get("interface_id"),
                                             "area_mm2": edge["area_mm2"]}})
                else:
                    out.append({**base, "kind": RELATION_R1, "area_mm2": 0.0, "valid": False,
                                "loss_mask": False, "interface_id": None,
                                "reason": "no_direct_fracture_surface (same event)",
                                "decidability": "within_event", "measured_surface": False,
                                "evidence": {"basis": "same_event_no_shared_patch",
                                             "event_id": a["event_id"]}})
                continue
            # same mother, different events: legal only when **this pair of events** is verified
            # to be mutually exclusive.
            #
            # The decision is per pair, not per library.  It used to read the library-global
            # ``exclusion.ok`` flag, which is a coarse proxy: one unverifiable event anywhere
            # (measured: a grey-zone event whose fragments carried no tagged new-fracture faces,
            # so ``_event_plane`` returned ``None`` and the check reported ``plane_unmeasured``)
            # withdrew *every* cross-event R1 row of *every* mother -- measured 24 rows became
            # ``mutually_exclusive_library_not_verified`` and the whole library produced
            # ``r1_cross_event = 0`` (``data/a12/reports/relation_negatives_summary.json``).
            # Reading the three checks for the pair itself is **stricter**, not looser: a pair is
            # R1 only when ``no_shared_patch`` and ``distinct_plane`` and ``distinct_mesh`` were
            # all actually evaluated for it and none of them failed.  A library with no exclusion
            # block at all, or a pair that appears in ``problems`` for any reason (including
            # ``plane_unmeasured``), still yields UNKNOWN with ``loss_mask=False``.
            exclusion = dict(library.get("exclusion") or {})
            checks_run = {str(c) for c in (exclusion.get("checks") or [])}
            verified_library = {"no_shared_patch", "distinct_plane", "distinct_mesh"} <= checks_run
            shared = [p for p in (exclusion.get("problems") or [])
                      if set(p.get("events", [])) == {a["event_id"], b["event_id"]}]
            pair_evidence = {
                "basis": "mutually_exclusive_event",
                "mother": a["mother_id"],
                "events": [a["event_id"], b["event_id"]],
                "shared_patch": None,
                "exclusion_checks_run": sorted(checks_run),
                "exclusion_problems_for_this_pair": shared[:4],
                "library_exclusion_ok": bool(exclusion.get("ok", False)),
            }
            if not verified_library or shared:
                out.append({**base, "kind": RELATION_UNKNOWN, "area_mm2": 0.0, "valid": False,
                            "loss_mask": False, "interface_id": None,
                            "reason": "mutually_exclusive_library_not_verified",
                            "decidability": "unverified", "measured_surface": False,
                            "evidence": {**pair_evidence, "basis": "exclusion_check_failed",
                                         "problems": shared[:4]}})
                continue
            out.append({**base, "kind": RELATION_R1, "area_mm2": 0.0, "valid": True,
                        "loss_mask": True, "interface_id": None,
                        "reason": "mutually_exclusive_event_no_shared_surface",
                        "decidability": "mutually_exclusive_event", "measured_surface": False,
                        "evidence": pair_evidence})
    return out


def relation_histogram(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {RELATION_R2: 0, RELATION_R1: 0, RELATION_R0: 0,
                           RELATION_TINY: 0, RELATION_UNKNOWN: 0}
    for row in rows:
        key = str(row.get("kind", RELATION_UNKNOWN))
        out[key] = out.get(key, 0) + 1
    return out


def library_fragments(library: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """``{fragment_id: {mother_id, event_id, lineage_id, split, ...}}`` for the whole library."""
    out: dict[str, dict[str, Any]] = {}
    for mother in library.get("mothers") or []:
        row = mother["mother"]
        for event in mother.get("events", []):
            if not event.get("ok"):
                continue
            for fragment in event.get("fragments", []):
                out[str(fragment["fragment_id"])] = {
                    "fragment_id": str(fragment["fragment_id"]),
                    "mother_id": str(row["lineage_id"]), "lineage_id": str(row["lineage_id"]),
                    "event_id": str(event["event_id"]), "split": str(row["split"]),
                    "vessel_id": str(row["vessel_id"]), "material_id": str(row["material_id"]),
                    "pattern_id": str(row.get("pattern_id", "")),
                    "volume_mm3": float(fragment.get("volume_mm3", 0.0)),
                    "is_tiny": bool(fragment.get("is_tiny", False)),
                    "event_role": str(event["plan"]["role"]),
                    "truth_status": str(event.get("truth_status", "COMPUTED")),
                    "event_seed_ref": str(event["plan"]["seed_ref"]),
                }
    return out


def library_hash(library: Mapping[str, Any]) -> str:
    """Content hash of the measured library (its plan + every measured event fact)."""
    payload = {
        "plan": library.get("plan"),
        "mothers": [{"mother": m.get("mother"),
                     "events": [{"plan": e.get("plan"), "fragment_ids": e.get("fragment_ids"),
                                 "interfaces": e.get("interfaces"),
                                 "relations": e.get("relations"),
                                 "plane": e.get("plane"), "ok": e.get("ok")}
                                for e in m.get("events", [])]}
                    for m in library.get("mothers") or []],
    }
    return hash_json(payload)


__all__ = [
    "MULTI_EVENT_VERSION", "EVENT_ROLES", "ROLE_PRIMARY", "ROLE_SECONDARY", "ROLE_EXTRA",
    "ROLE_GREY_ZONE",
    "SPLIT_DISTRACTOR", "PLANE_NORMAL_TOL", "PLANE_OFFSET_TOL_MM",
    "MotherPlan", "EventPlan", "LibraryPlan", "plan_event_library", "run_event_library",
    "dial_grey_zone_plane", "verify_event_exclusion", "classify_library",
    "relation_histogram", "library_fragments", "library_hash",
]
