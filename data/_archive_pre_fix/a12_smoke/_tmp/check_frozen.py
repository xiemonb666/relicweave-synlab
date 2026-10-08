
import sys
from pathlib import Path
frozen = Path(r'C:/Users/xiemo/Desktop/ShardForge/relicweave-synlab/data/a12_smoke/_tmp/frozen_tree')
sys.path.insert(0, str(frozen))
import synlab, synlab.pipeline
print('synlab from:', synlab.__file__)
print('pipeline from:', synlab.pipeline.__file__)
