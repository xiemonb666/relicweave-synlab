from pathlib import Path
import hashlib
root=Path(r'C:\Users\xiemo\Desktop\ShardForge')
files={
'front_source':'pgfrag/experiments/mixed93_moving_front_reanalysis_20261007/mixed93_moving_front_reanalysis.py',
'front_capture_receipt':'pgfrag/tmp/review_20261007/mixed93_moving_front_reanalysis_20261007/capture_once01/capture_receipt.json',
'front_citation_source':'pgfrag/experiments/mixed93_moving_front_reanalysis_20261007/mixed93_moving_front_reanalysis.py',
'object_pins':'pgfrag/tmp/review_20261007/mixed93_mechanics_objectivity_20261007/source_pins.json',
'a12_degrade':'relicweave-synlab/data/a12/reports/precision_probe_07_degrade_audit.json',
'a12_error':'relicweave-synlab/data/a12/reports/precision_probe_09_degrade_error.json',
'a12_pattern':'relicweave-synlab/data/a12/reports/pattern_audit.json',
'a12_status':'relicweave-synlab/docs/a12/status.md',
'a12_patterns':'relicweave-synlab/docs/a12/patterns.md',
}
for k,r in files.items():
 p=root/r
 if not p.exists(): print(f'MISSING\t{k}\t{r}'); continue
 h=hashlib.sha256(p.read_bytes()).hexdigest()
 print(f'{k}\t{h}\t{p.stat().st_size}\t{r}')
