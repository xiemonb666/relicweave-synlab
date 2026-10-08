import json, numpy as np
from pathlib import Path
STORE = Path(r"data\a12_trainable\store")
print("store exists", STORE.exists())
for sub in sorted(STORE.iterdir()): print("  ", sub.name)
