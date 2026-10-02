import json
from pathlib import Path
from synlab.storage.store import AssetStore
from synlab.storage.release import ReleaseManager
root = Path(r"data\a12_exports\closed_loop\store")
st = AssetStore(root)
mgr = ReleaseManager(st)
for p in sorted((root/"releases").iterdir()):
    print(p.name)
    if p.is_dir():
        for f in sorted(p.iterdir())[:4]:
            print("    ", f.name, f.stat().st_size)
