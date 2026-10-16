import pathlib
p = pathlib.Path("synlab/fracture/implicit/assembler.py")
s = p.read_text(encoding="utf-8")
s = s.replace("""    _trace(f"sources tagged: mother {source_mother.n_faces} faces, "
           f"cutter {source_cutter.n_faces} faces")""",
"""    _trace(f"sources tagged: mother {len(np.asarray(source_mother.mesh.faces))} faces, "
           f"cutter {len(np.asarray(source_cutter.mesh.faces))} faces")""")
p.write_text(s, encoding="utf-8")
print("fixed")
