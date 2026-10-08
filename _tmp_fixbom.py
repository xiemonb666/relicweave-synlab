import io, ast
from pathlib import Path
p = Path(r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\tools\next_experiment_export.py")
raw = p.read_bytes()
print("first bytes:", raw[:4])
text = raw.decode("utf-8-sig")
ast.parse(text)
p.write_text(text, encoding="utf-8", newline="\n")
print("rewritten without BOM, syntax OK, bytes:", p.stat().st_size)
