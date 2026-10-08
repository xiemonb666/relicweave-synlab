"""Scratch: insert the teammate group ids into the extras catalogue."""
from __future__ import annotations

import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8")

path = pathlib.Path("synlab/observe/synthetic_extras.py")
text = path.read_text(encoding="utf-8")
mapping = {
    "extra::photometric_normals": "G-EXTRA-NORMAL-PS",
    "extra::polarizer_angle_sequence": "G-EXTRA-POLAR-SWEEP",
    "extra::sub_millimetre_scale_claim": "G-EXTRA-SCALE-0P1",
    "extra::hard_sync_stereo": "G-EXTRA-STEREO",
    "extra::dense_depth_reliable": "G-EXTRA-DENSE-DEPTH",
    "extra::continuous_rotation": "G-EXTRA-CONT-ROT",
    "extra::auto_flip_second_set": "G-EXTRA-AUTO-FLIP",
    "extra::excavation_context_ref": "G-EXTRA-CONTEXT-REF",
    "extra::synthetic_calibration": "G-EXTRA-CALIB",
}
patched = 0
for group, teammate in mapping.items():
    old = f'ablation_group="{group}",\n'
    new = f'ablation_group="{group}",\n        teammate_group_id="{teammate}",\n'
    if old not in text:
        print("MISS", group)
        continue
    text = text.replace(old, new, 1)
    patched += 1
path.write_text(text, encoding="utf-8")
print("patched", patched)
