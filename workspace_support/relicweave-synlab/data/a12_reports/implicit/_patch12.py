import pathlib
p = pathlib.Path("synlab/fracture/implicit/assembler.py")
s = p.read_text(encoding="utf-8")
s = s.replace("""__all__ = ["assemble_implicit_event", "sheet_distance"]""",
"""__all__ = ["assemble_implicit_event", "sheet_distance"]


def _trace(message: str) -> None:
    \"\"\"Stage trace for the assembler: an implicit event is a heavy run, so it says where it is.\"\"\"
    import os

    if str(os.environ.get("SYNLAB_IMPLICIT_TRACE", "")).strip() not in ("", "0", "false"):
        print(f"[assemble] {message}", flush=True)""")
s = s.replace("""    minus = boolean_intersection([source_mother, source_cutter], label="M_minus")
    plus = boolean_difference([source_mother, source_cutter], label="M_plus")""",
"""    _trace(f"sources tagged: mother {source_mother.n_faces} faces, "
           f"cutter {source_cutter.n_faces} faces")
    minus = boolean_intersection([source_mother, source_cutter], label="M_minus")
    _trace(f"intersection done: {minus.n_faces} faces")
    plus = boolean_difference([source_mother, source_cutter], label="M_plus")
    _trace(f"difference done: {plus.n_faces} faces")""")
s = s.replace("""        classifications[name] = classification
    timings["classify_seconds"] = time.time() - stage""",
"""        classifications[name] = classification
        _trace(f"classified {name}: {classification['_faces'].shape[0]} faces, "
               f"interface vertices {int(np.sum(classification['vertex_origin'] == ORIGIN_INTERFACE))}")
    timings["classify_seconds"] = time.time() - stage""")
s = s.replace("""    timings["fragments_seconds"] = time.time() - stage""",
"""    timings["fragments_seconds"] = time.time() - stage
    _trace(f"fragments built: {[f.fragment_id for f in fragments]}")""")
s = s.replace("""    timings["interfaces_seconds"] = time.time() - stage
    _write_interface_ids(fragments, patches)""",
"""    timings["interfaces_seconds"] = time.time() - stage
    _trace(f"interfaces paired: {len(patches)} patches")
    _write_interface_ids(fragments, patches)""")
p.write_text(s, encoding="utf-8")
print("trace added")
