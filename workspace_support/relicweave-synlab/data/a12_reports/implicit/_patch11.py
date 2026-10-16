import pathlib
p = pathlib.Path("data/a12_reports/implicit/_stage_probe.py")
s = p.read_text(encoding="utf-8")
s = s.replace("""        from synlab.fracture.api import audit_fracture
        from synlab.fracture.event import run_shared_cut

        stage = time.time()
        try:
            result = run_shared_cut(mother, cutter, event_id="stage_probe",
                                    backend="implicit_sheet_cut")""",
"""        from synlab.fracture.api import audit_fracture
        from synlab.fracture.implicit.assembler import assemble_implicit_event

        stage = time.time()
        try:
            result = assemble_implicit_event(mother, cutter, event_id="stage_probe",
                                            backend="implicit_sheet_cut")""")
p.write_text(s, encoding="utf-8")
print("ok")
