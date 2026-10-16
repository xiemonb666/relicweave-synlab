import re
from pathlib import Path
s=Path('docs/handover/20261007/HANDOVER.md').read_text(encoding='utf-8')
for m in re.finditer(r'!?\[[^\]]+\]\([^)]+\)',s): print(m.group(0))
