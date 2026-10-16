"""为浏览器端 3D 视口验证准备一个**真实**的最小数据根。

为什么需要它：`display_lod` 的 handler 读 `ctx.spec["asset_id"]`（顶层键），而 `POST /jobs`
只会把校验过的 generation spec 放进 `spec.spec`，并把固定的一组键写进 job spec ——
因此**当前 HTTP API 没有创建 display_lod 任务的路径**（已记入 docs/a12/api_ui.md 差异表）。
本脚本走与 `tests/a12/api/conftest.py` 相同的真实路径：`AssetStore.commit_asset` +
`Scheduler.create_job` + 真实 worker 子进程，产出真实 GLB，用于验证前端 GLTFLoader 路线。

用法::

    python tests/a12/api_ui/_seed_demo.py --store-root <dir>
    python -m synlab.api.worker --store-root <dir> --once --json --quiet
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

CUBE_EDGE_MM = 100.0


def cube_arrays(edge_mm: float = CUBE_EDGE_MM) -> dict[str, np.ndarray]:
    """与 API 测试 fixture 相同的真实 100 mm 立方体（mm / Z-up，原点居中）。"""
    half = edge_mm / 2.0
    vertices = np.array([
        [-half, -half, -half], [+half, -half, -half], [+half, +half, -half], [-half, +half, -half],
        [-half, -half, +half], [+half, -half, +half], [+half, +half, +half], [-half, +half, +half],
    ], dtype=np.float64)
    faces = np.array([
        [0, 2, 1], [0, 3, 2],
        [4, 5, 6], [4, 6, 7],
        [0, 1, 5], [0, 5, 4],
        [1, 2, 6], [1, 6, 5],
        [2, 3, 7], [2, 7, 6],
        [3, 0, 4], [3, 4, 7],
    ], dtype=np.int64)
    return {"mesh.vertices": vertices, "mesh.faces": faces}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store-root", required=True)
    parser.add_argument("--workspace", default="default")
    parser.add_argument("--edge-mm", type=float, default=CUBE_EDGE_MM)
    args = parser.parse_args()

    from synlab.api.integrity import record_integrity
    from synlab.api.tables import ensure_api_schema
    from synlab.jobs.scheduler import Scheduler
    from synlab.roles import ROLE_MOTHER_MESH, SCHEMA_MOTHER
    from synlab.storage.store import AssetStore

    root = Path(args.store_root)
    root.mkdir(parents=True, exist_ok=True)
    store = AssetStore(root)
    ensure_api_schema(store)
    scheduler = Scheduler(store)

    record = store.commit_asset(
        role=ROLE_MOTHER_MESH,
        schema=SCHEMA_MOTHER,
        unit="mm",
        frame="W_mm",
        payload=cube_arrays(args.edge_mm),
        qa={"watertight": True, "edge_mm": args.edge_mm, "source": "ui_verification_cube"},
        qa_status="QA_PASS",
        meta={"vessel_id": "V01", "material_id": "M01", "workspace": args.workspace,
              "note": "UI 三维视口验证用的真实立方体（非 mock 几何）"},
        lineage_id="lin_ui_cube",
    )
    record_integrity(store, record.asset_id, source="producer")

    run_id = f"run_ui_display_{int(time.time())}"
    store.create_run(run_id, "display_lod", "SYNTHETIC", None,
                     meta={"workspace": args.workspace, "stage": "display_lod", "role": "researcher"})
    job_id = f"job_ui_display_{int(time.time())}"
    scheduler.create_job(
        job_id=job_id,
        run_id=run_id,
        stage="display_lod",
        spec={"workspace": args.workspace, "asset_id": record.asset_id,
              "node_id": "n0_display_lod", "chain": 0, "input_refs": [record.asset_id],
              "spec_hash": None, "role": "researcher", "planned_jobs": 1},
        inputs=[record.asset_id],
    )

    print(json.dumps({
        "store_root": str(root),
        "authority_asset_id": record.asset_id,
        "run_id": run_id,
        "job_id": job_id,
        "edge_mm": args.edge_mm,
        "authority_role": record.role,
        "next": "python -m synlab.api.worker --store-root <store-root> --once --json --quiet",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
