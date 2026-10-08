import pathlib
p = pathlib.Path("data/a12_reports/implicit/_boolean_probe.py")
s = p.read_text(encoding="utf-8")
s = s.replace('''    (OUT / "boolean_probe.json").write_text''', '''    if "resolve" in steps:
        from synlab.fracture.event import _cut_both_sides
        from synlab.truth.source_resolver import SourceResolver

        t0 = time.time()
        minus, plus = _cut_both_sides(source_mother, source_cutter)
        print(f"[cut_both] {time.time() - t0:.1f}s minus={minus.n_faces} plus={plus.n_faces}",
              flush=True)
        t0 = time.time()
        resolver = SourceResolver([source_mother, source_cutter], tolerance_mm=1.0e-4)
        for name, side in (("M_minus", minus), ("M_plus", plus)):
            classification = resolver.classify(side, container=cutter.mesh,
                                               container_tolerance_mm=1.0e-4)
            print(f"[resolve:{name}] {time.time() - t0:.1f}s keys={sorted(classification)[:8]}",
                  flush=True)
    if "full" in steps:
        from synlab.fracture.event import run_shared_cut

        t0 = time.time()
        result = run_shared_cut(mother, cutter, event_id="bool_probe",
                                backend="implicit_sheet_cut")
        print(f"[full] {time.time() - t0:.1f}s fragments={len(result.fragments)} "
              f"interfaces={len(result.interfaces)} "
              f"volumes={[round(float(f.volume_mm3), 3) for f in result.fragments]}", flush=True)
    (OUT / "boolean_probe.json").write_text''')
p.write_text(s, encoding="utf-8")
print("ok")
