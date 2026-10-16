#: The reviewed ``build_one_mother`` reads ``primary_fragment_id`` at its step-7 ``stamp_context``
#: call while the assignment lives ~15 lines later.  Python makes the name a true *local* of that
#: frame (verified: it is in ``build_one_mother.__code__.co_varnames`` and ``co_cellvars`` is empty),
#: so no module attribute, closure cell or ``f_locals`` write can supply it: **every** lineage that
#: reaches step 7 dies with ``UnboundLocalError`` (measured: stage ``pipeline`` after a fully
#: successful mother/material/pattern/fracture/clean_truth/physical chain, 24.5 s of fracture
#: already spent).  That is a live defect of a file another writer owns, so it is worked around here
#: by compiling a **corrected copy** of that one function from the live source instead of editing
#: the file.  The edit is a pure insertion of the assignment the function already performs later;
#: ``_patched_build_one_mother`` records its provenance and automatically stands down once the
#: owner's fix lands.
UNBOUND_GUARDS: dict[str, tuple[str, str, str]] = {
    # name -> (anchor line the assignment must follow, the exact assignment, the line it precedes)
    "primary_fragment_id": (
        "observation = observe(physical, None, rngs, route=route, spec=observe_spec)",
        '        primary_fragment_id = str(getattr(observation, "fragment_id", "") or "")',
        "stamp_context(observation,",
    ),
}


def _patched_build_one_mother() -> tuple[Any, dict[str, Any]]:
    """Compile a corrected copy of ``build_one_mother`` from the live source.

    ``provenance`` records the source file, its mtime and hash, and the applied line edits.  When the
    owner's fix has already landed the function is returned untouched with an empty edit list, so
    this shim cannot silently keep patching something that is already correct.
    """
    import hashlib

    from synlab import pipeline as pipeline_mod

    path = Path(pipeline_mod.__file__)
    source = path.read_text(encoding="utf-8")
    provenance: dict[str, Any] = {
        "source_file": str(path),
        "source_hash": "sha256:" + hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "source_mtime": path.stat().st_mtime,
        "edits": [],
    }
    lines = source.splitlines()
    for name, (anchor, assignment, before) in UNBOUND_GUARDS.items():
        anchor_at = [i for i, line in enumerate(lines) if line.strip() == anchor.strip()]
        before_at = [i for i, line in enumerate(lines) if line.strip() == before.strip()]
        assign_at = [i for i, line in enumerate(lines) if line.strip() == assignment.strip()]
        if not anchor_at or not before_at:
            continue
        if assign_at and min(assign_at) < min(before_at):
            provenance["already_fixed_upstream"] = True
            continue
        insert_at = min(anchor_at) + 1
        lines.insert(insert_at, assignment)
        provenance["edits"].append({"name": name, "inserted_after_1based_line": insert_at + 1,
                                    "line": assignment.strip()})
    if not provenance["edits"]:
        return pipeline_mod.build_one_mother, provenance
    namespace: dict[str, Any] = dict(pipeline_mod.__dict__)
    exec(compile("\n".join(lines) + "\n", str(path) + "#diversity-harness-patched", "exec"),
         namespace)
    return namespace["build_one_mother"], provenance


@contextlib.contextmanager
def patch_build_one_mother(P: Any, plan: Any, lineage: Any, store: Any, *, run_id: Any,
                           degrade_cfg: Any) -> Iterator[dict[str, Any]]:
    """Run ``build_one_mother`` through the corrected copy and yield its captured result."""
    original = P.build_one_mother
    patched, provenance = _patched_build_one_mother()
    captured: dict[str, Any] = {"provenance": provenance}
    P.build_one_mother = patched
    try:
        try:
            captured["result"] = patched(plan, lineage, store, run_id=run_id,
                                         degrade_cfg=degrade_cfg)
        except Exception as exc:  # noqa: BLE001 - a dead lineage is an outcome, not a crash
            captured["result"] = {
                "ok": False, "coverage_row": {"lineage_id": lineage.lineage_id},
                "error": {"code": "UNEXPECTED", "stage": "harness",
                          "message": f"{type(exc).__name__}: {exc}"[:400],
                          "traceback": traceback.format_exc()[-1500:]}}
        yield captured
    finally:
        P.build_one_mother = original
