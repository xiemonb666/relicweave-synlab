import re
from pathlib import Path
s=Path('docs/handover/20261007/HANDOVER.md').read_text(encoding='utf-8-sig')
hs=re.findall(r'(?<![0-9a-fA-F])[0-9a-fA-F]{64}(?![0-9a-fA-F])',s)
for h in hs:
 if '246630' in h: print('found',h,len(h))
q='2466306decc0af17d47c71d8e66b110aa77255f8f9279b94180a86ee7029886d'
print('expected length',len(q),'present',q in s)
for m in re.finditer('246630',s): print(s[m.start():m.start()+80])
