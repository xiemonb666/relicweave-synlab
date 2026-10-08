from __future__ import annotations

import io
import zipfile
from pathlib import Path

import cadquery as cq
import numpy as np

from vesselforge.geometry import VesselSpec, mesh_shape, section_shape

ASSET = Path(r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\tmp\review_20261003\implementation\vf\artifacts\four_bands_canonical3")
OUT = Path(r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\tmp\review_20261003\implementation\vf\artifacts\preview_canonical3")
OUT.mkdir(parents=True, exist_ok=True)
shape = cq.importers.importStep(str(ASSET / "geometry" / "solid.step")).val()
section = section_shape(shape)
vertices, faces, source_ids = mesh_shape(section, VesselSpec())
arrays = {"vertices_mm": vertices, "faces": faces, "face_source_brep_index": source_ids}
with zipfile.ZipFile(OUT / "section_halfspace.npz", "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
    for name, array in arrays.items():
        buffer = io.BytesIO()
        np.save(buffer, array, allow_pickle=False)
        info = zipfile.ZipInfo(f"{name}.npy", date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, buffer.getvalue())
print(f"valid={section.isValid()} solids={len(section.Solids())} volume_mm3={section.Volume():.9f} vertices={len(vertices)} triangles={len(faces)}")
