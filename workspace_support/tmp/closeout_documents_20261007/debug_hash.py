import re,hashlib
from pathlib import Path
s=Path('docs/handover/20261007/HANDOVER.md').read_text(encoding='utf-8-sig')
a=hashlib.sha256(Path('vesselforge/experiments/global_wall_distance_certificate_20261007/global_wall_distance_certificate.py').read_bytes()).hexdigest()
b=[x for x in re.findall(r'(?<![0-9a-fA-F])[0-9a-fA-F]{64}(?![0-9a-fA-F])',s) if x.startswith('246630')][0]
print(repr(a),repr(b)); print(a[17:27],b[17:27],[(i,a[i],b[i]) for i in range(64) if a[i]!=b[i]])
