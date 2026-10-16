import pathlib
p = pathlib.Path("synlab/fracture/implicit/backend.py")
s = p.read_text(encoding="utf-8")
s = s.replace('''    from .. import event as event_mod
    from .. import morphology as morphology_mod''', '''    from .. import morphology as morphology_mod
    from .assembler import assemble_implicit_event''')
s = s.replace('''    result = event_mod.run_shared_cut(
        mother, cutter, event_id=event_id, backend=BACKEND_IMPLICIT,
        extra_meta={''', '''    result = assemble_implicit_event(
        mother, cutter, event_id=event_id, backend=BACKEND_IMPLICIT,
        extra_meta={''')
p.write_text(s, encoding="utf-8")
print("event path switched to the analytic assembler")
