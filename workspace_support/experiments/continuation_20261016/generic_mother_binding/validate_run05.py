"""Read-only, hash-anchored binding demonstration for the frozen VF run05 mesh."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "pgfrag" / "src"))

from pgfrag.mother_binding import build_mother_binding, write_mother_binding  # noqa: E402


TRUSTED_AUDIT_SHA256 = "ab8e8a0c691a0fa4d31d65e5922ca82900e2bcef4eb7dbba3ef8dd3344e1e7cc"
ASSET = (ROOT / "vesselforge/experiments/continuation_20261015/reference_forms/outputs"
         / "daily_aberdeen_108x53_v6_final")
WITNESS_RUN = ROOT / "vesselforge/experiments/continuation_20261015/named_step/daily_witness_probe_20261016_v15"
PARTITION_RUN = ROOT / "vesselforge/experiments/continuation_20261016/reference_v6_tetra/run05"
OUTPUT = Path(__file__).resolve().parent / "run05_binding"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    partition = PARTITION_RUN / "partition_output"
    audit = PARTITION_RUN / "audit_receipt.json"
    binding = build_mother_binding(
        source_asset_dir=ASSET,
        partition_result_path=partition / "result.json",
        audit_receipt_path=audit,
        trusted_audit_receipt_sha256=TRUSTED_AUDIT_SHA256,
        canonical_step_path=WITNESS_RUN / "daily_native_named.step",
        canonical_step_input_key="daily_native_named.step",
        native_face_identity_path=WITNESS_RUN / "native_face_identity.json",
        witness_manifest_path=WITNESS_RUN / "witness_manifest.json",
        v15_receipt_path=WITNESS_RUN / "receipt.json",
        label_import_receipt_path=WITNESS_RUN / "label_import_receipt.json",
        witness_directory=WITNESS_RUN / "native_face_witnesses",
    )
    receipt = write_mother_binding(binding, OUTPUT)
    exp_receipt = {
        "schema": "pgfrag.generic_mother_binding_run_receipt.v1",
        "status": "READ_ONLY_BINDING_VALIDATED",
        "binding_id": binding.binding_id,
        "binding_receipt_sha256": sha(OUTPUT / "binding_receipt.json"),
        "arrays_sha256": sha(OUTPUT / "binding_arrays.npz"),
        "trusted_audit_receipt_sha256": TRUSTED_AUDIT_SHA256,
        "counts": receipt["counts"],
        "qualification": receipt["qualification"],
        "solver_run": False,
        "fracture_created": False,
        "observations_created": False,
        "training_eligible": False,
        "output_bytes": sum(path.stat().st_size for path in OUTPUT.iterdir() if path.is_file()),
    }
    exp_path = OUTPUT / "experiment_receipt.json"
    if exp_path.exists():
        raise FileExistsError(exp_path)
    exp_path.write_text(json.dumps(exp_receipt, indent=2, sort_keys=True,
                                   allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(exp_receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
