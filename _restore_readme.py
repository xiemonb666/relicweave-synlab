import sys, json
sys.path.insert(0, ".")
from pathlib import Path
from synlab.storage.export_full import render_readme
pkg = Path(r"data\a12_exports\full")
manifest = json.loads((pkg/"manifest.json").read_text(encoding="utf-8"))
index = json.loads((pkg/"ablation_index.json").read_text(encoding="utf-8"))
text = render_readme(manifest, index)
(pkg/"README.md").write_text(text, encoding="utf-8")
print("restored README.md bytes:", len(text.encode("utf-8")))
print("first line:", text.splitlines()[0])
