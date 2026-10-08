from pathlib import Path
import hashlib
p=Path('docs/handover/20261007/HANDOVER.md')
s=p.read_text(encoding='utf-8-sig')
rel=Path('vesselforge/experiments/global_wall_distance_certificate_20261007/global_wall_distance_certificate.py')
actual=hashlib.sha256(rel.read_bytes()).hexdigest()
wrong='2466306decc0af17d47c71e8d66b110aa77255f8f9279b94180a86ee7029886d'
assert wrong in s and actual not in s
p.write_text(s.replace(wrong,actual),encoding='utf-8')
print('replaced with file-derived SHA',actual)
