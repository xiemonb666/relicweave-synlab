import json
from pathlib import Path

path=Path(r'C:\Users\xiemo\Desktop\ShardForge\pgfrag\tmp\review_20261007\mixed93_opening_control_20261007\run01\result.json')
data=json.loads(path.read_text(encoding='utf-8'))
trajectory=data.get('trajectory')
if not isinstance(trajectory,list):
    raise SystemExit(f'Unexpected trajectory type: {type(trajectory).__name__}; top-level keys={sorted(data)}')
print('trajectory_states',len(trajectory))
print('step_6_keys',sorted(trajectory[6]) if len(trajectory)>6 else None)
for item in trajectory:
    fields={k:v for k,v in item.items() if 'damage' in k.lower() or k in {'step_index','all_points_fully_damaged'}}
    print(fields)
