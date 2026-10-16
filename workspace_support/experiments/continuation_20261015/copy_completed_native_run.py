"""Read back only completed, immutable native output with all payload hashes."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024**2), b""):
            digest.update(block)
    return digest.hexdigest()


def verify(root, receipt):
    for name, row in receipt["files"].items():
        path = (root/name).resolve(strict=True)
        path.relative_to(root.resolve())
        if path.stat().st_size != row["bytes"] or sha(path) != row["sha256"]:
            raise ValueError(f"source/result hash mismatch: {name}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--src", type=Path, required=True)
    p.add_argument("--dest", type=Path, required=True)
    a = p.parse_args()
    if a.dest.exists():
        raise FileExistsError(a.dest)
    receipt_path = a.src/"receipt.json"
    before = sha(receipt_path)
    receipt = json.loads(receipt_path.read_text())
    if receipt["status"] != "NATIVE_RUN_COMPLETE_DIAGNOSTIC":
        raise ValueError("native output is not complete")
    verify(a.src, receipt)
    shutil.copytree(a.src, a.dest)
    verify(a.dest, receipt)
    if sha(receipt_path) != before or sha(a.dest/"receipt.json") != before:
        raise ValueError("completed source changed during copy")
    report = {"status": "COMPLETED_RUN_READBACK_ALL_HASHES_PASS", "source": str(a.src),
              "destination": str(a.dest), "receipt_sha256": before, "verified_payload_count": len(receipt["files"]),
              "verified_bytes": sum(row["bytes"] for row in receipt["files"].values())}
    a.dest.with_name(a.dest.name+"_readback_receipt.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
