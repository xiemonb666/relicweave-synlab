from pathlib import Path
hits=[]
for p in Path("data").rglob("*"):
    if p.name.startswith("rel_nexp_1790919836"):
        hits.append(str(p))
for h in hits: print(h)
