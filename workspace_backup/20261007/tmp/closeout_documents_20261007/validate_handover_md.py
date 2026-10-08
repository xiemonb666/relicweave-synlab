from pathlib import Path
import re,sys
p=Path('docs/handover/20261007/HANDOVER.md'); s=p.read_text(encoding='utf-8'); lines=s.splitlines(); errors=[]; open_fence=None
for i,line in enumerate(lines,1):
 if line.startswith('~~~'):
  if open_fence is None: open_fence=(i,len(line)-len(line.lstrip('~')))
  elif len(line.strip())>=open_fence[1] and not line.strip()[open_fence[1]:].strip(): open_fence=None
if open_fence: errors.append(f'unclosed fence: {open_fence}')
in_table=False; columns=None
for i,line in enumerate(lines,1):
 if line.startswith('|') and line.rstrip().endswith('|'):
  cells=len(line.strip().strip('|').split('|'))
  if not in_table: in_table=True; columns=cells
  elif cells!=columns: errors.append(f'table cell count {cells} != {columns} at line {i}')
 else: in_table=False; columns=None
print('bytes',p.stat().st_size,'lines',len(lines),'64-char hashes',len(re.findall(r'(?<![0-9a-fA-F])[0-9a-fA-F]{64}(?![0-9a-fA-F])',s)),'errors',errors)
if errors: sys.exit(1)
