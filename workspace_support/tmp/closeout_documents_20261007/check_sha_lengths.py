import re
from pathlib import Path
p=Path('docs/handover/20261007/HANDOVER.md')
s=p.read_text(encoding='utf-8-sig')
for m in re.finditer(r'(?<![0-9a-fA-F])[0-9a-fA-F]{48,70}(?![0-9a-fA-F])',s):
 t=m.group(0)
 if len(t)!=64: print(len(t),t)
