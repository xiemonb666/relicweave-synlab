from __future__ import annotations

import json
import sys
from io import BytesIO
from pathlib import Path

import numpy as np

from synlab.roles import ROLE_OBS_RESULT, SCHEMA_OBS
from synlab.storage.store import AssetStore
from fastapi.testclient import TestClient
from synlab.api import create_app

root = Path(sys.argv[1])
store = AssetStore(root)
record = store.commit_asset(
    role=ROLE_OBS_RESULT,
    schema=SCHEMA_OBS,
    unit="mm",
    frame="S_mm",
    payload={
        "v000.rgb": np.zeros((1, 1, 3), dtype=np.uint8),
        "v000.id_map": np.array([[424242]], dtype=np.int32),
        "v000.surface_tag": np.array([[6]], dtype=np.int16),
        "v000.T_WC": np.full((4, 4), 0.25, dtype=np.float64),
    },
    meta={
        "workspace": "default",
        "fragment_id": "frag_secret_probe",
        "quality_GT": {"occlusion_fraction": 0.875},
    },
    qa_status="QA_PASS",
)
client = TestClient(create_app(root, role="deployment_client"))
try:
    detail = client.get(f"/api/synlab/assets/{record.asset_id}")
    response = client.get(f"/api/synlab/assets/{record.asset_id}/files/obs_result",
                          params={"key": "arrays"})
    archive = np.load(BytesIO(response.content))
    result = {
        "asset_id": record.asset_id,
        "metadata_status": detail.status_code,
        "metadata_visible": {key: detail.json()["asset"]["meta"].get(key)
                              for key in ("fragment_id", "quality_GT", "workspace")},
        "download_status": response.status_code,
        "download_keys": sorted(archive.files),
        "id_map_value": int(archive["v000.id_map"][0, 0]),
        "surface_tag_value": int(archive["v000.surface_tag"][0, 0]),
        "pose_value": float(archive["v000.T_WC"][0, 0]),
        "listed_by_default": any(item["asset_id"] == record.asset_id
                                  for item in client.get("/api/synlab/assets").json()["items"]),
    }
    print(json.dumps(result, sort_keys=True))
finally:
    client.close()


