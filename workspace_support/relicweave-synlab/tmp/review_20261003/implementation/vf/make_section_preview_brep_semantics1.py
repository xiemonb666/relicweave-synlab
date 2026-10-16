from __future__ import annotations

import argparse
import io
import zipfile
from pathlib import Path

import cadquery as cq
import numpy as np
from vesselforge.geometry import VesselSpec, mesh_shape, section_shape

parser = argparse.ArgumentParser()
parser.add_argument('--asset', type=Path, required=True)
parser.add_argument('--out', type=Path, required=True)
args = parser.parse_args()
shape = cq.importers.importStep(str(args.asset / 'geometry' / 'solid.step')).val()
section = section_shape(shape)
vertices, faces, source_ids = mesh_shape(section, VesselSpec())
args.out.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(args.out, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
    for name, array in sorted({'vertices_mm': vertices, 'faces': faces, 'face_source_brep_index': source_ids}.items()):
        buffer = io.BytesIO()
        np.save(buffer, array, allow_pickle=False)
        info = zipfile.ZipInfo(f'{name}.npy', date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, buffer.getvalue(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=6)
print(f'valid={section.isValid()} solids={len(section.Solids())} volume_mm3={section.Volume():.9f} vertices={len(vertices)} triangles={len(faces)}')
