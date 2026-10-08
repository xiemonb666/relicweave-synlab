import sys; sys.path.insert(0,'.')
from synlab.training.model import encoder_valid, DualTowerModel
print("encoder_valid ok:", callable(encoder_valid))
import inspect
print(inspect.signature(DualTowerModel.__init__))
from synlab.storage.export import TrainingPackage
print("relations() ok:", callable(TrainingPackage("data/a12_exports/a12_extras/training_package").relations))
