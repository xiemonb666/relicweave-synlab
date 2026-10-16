"""Post-freeze verification: manifest integrity, reference closure, package inventory.

Usage: python verify_release.py <store_root> <release_id>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from synlab.storage.release import ReleaseManager  # noqa: E402
from synlab.storage.store import AssetStore  # noqa: E402

store = AssetStore(ROOT / sys.argv[1] if not Path(sys.argv[1]).is_absolute() else sys.argv[1])
release_id = sys.argv[2]
manager = ReleaseManager(store)
manifest = manager.load(release_id)          # re-hashes the manifest: raises if modified
closure = manager.verify_closure([a["asset_id"] for a in manifest["assets"]])
roles: dict[str, int] = {}
for asset in manifest["assets"]:
    roles[asset["role"]] = roles.get(asset["role"], 0) + 1
print("release:", manifest["release_id"], "profile:", manifest["profile"],
      "scope:", manifest["scope"])
print("manifest_hash:", manifest["manifest_hash"])
print("assets:", len(manifest["assets"]), "gates_required:", manifest["required_gates"])
print("scope_completed:", manifest["scope_completed"])
print("scope_pending:", manifest["scope_pending"])
print("closure_ok:", closure["ok"], "assets_checked:", closure["assets"],
      "files_checked:", closure["files_checked"], "problems:", closure["problems"][:5])
print("assets_by_role:", json.dumps(dict(sorted(roles.items()))))
print("qa_pass_in_manifest:", sum(1 for a in manifest["assets"] if a["qa_status"] == "QA_PASS"),
      "of", len(manifest["assets"]))

package = ROOT / "data" / "a12_exports" / "closed_loop" / "training_package"
payload = json.loads((package / "export_manifest.json").read_text(encoding="utf-8"))
print("\npackage:", package)
print("  release_id:", payload.get("release_id"), "manifest_hash:", payload.get("manifest_hash"))
print("  counts:", json.dumps(payload.get("counts"), sort_keys=True))
print("  views:", json.dumps(payload.get("views"), sort_keys=True))
print("  separation:", json.dumps(payload.get("separation"), sort_keys=True))
files = payload.get("files") or []
print("  files:", len(files), "bytes_total:", payload.get("bytes_total"))
for entry in sorted(files, key=lambda f: f["path"]):
    print(f"    {entry['path']:<44} {entry.get('bytes'):>9}  {entry.get('view')}")
