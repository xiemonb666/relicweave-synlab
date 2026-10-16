"""Record local artifact exclusions and keep the shared source archive visible."""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / "docs/handover/20261016/FINAL_STAGING_PLAN.json"
plan = json.loads(PLAN.read_text(encoding="utf-8"))
index = {}
for name in ["LOCAL_ONLY_ARTIFACTS.json", "PROJECT_CODE_CANDIDATES.json"]:
    data = json.loads((ROOT / "docs/handover/20261016/repository_inventory" / name).read_text(encoding="utf-8"))
    for row in data["files"]:
        index[(row["repo"], row["path"])] = row
records = []
for repo in plan["repositories"]:
    omitted = repo["excluded_new_files"]
    for row in omitted:
        original = index.get((repo["repository"], row["path"]), {})
        records.append({"repository": repo["repository"], **row,
                        "inventory_sha256": original.get("sha256"),
                        "inventory_hash_status": original.get("hash_status", "not_in_prior_inventory")})
    if not omitted:
        continue
    ignore = ROOT / repo["repository"] / ".gitignore"
    text = ignore.read_text(encoding="utf-8").rstrip() + "\n"
    marker = "# 2026-10-16 pause delivery: local runtime caches and raw histories"
    assert marker not in text, "Boundary update already applied; do not duplicate"
    lines = ["", marker, "# Retained on disk; see A12 LOCAL_ARTIFACT_DELIVERY_BOUNDARY.json and inventory hashes."]
    if repo["repository"] == "pgfrag":
        lines += ["**/_temp_matplotlib/", "**/.mplconfig/"]
    for row in omitted:
        if row["reason"].startswith("runtime_or_dependency_directory:"):
            continue
        # Root anchored literal path, escaped according to gitignore syntax.
        escaped = row["path"].replace("\\", "/")
        for char in ["[", "]", "*", "?", "!", "#", " "]:
            escaped = escaped.replace(char, "\\" + char)
        lines.append("/" + escaped)
    ignore.write_text(text + "\n".join(lines) + "\n", encoding="utf-8")
ignore = ROOT / "relicweave-synlab/.gitignore"
text = ignore.read_text(encoding="utf-8").rstrip()
marker = "# Reviewed shared source archive; undo recursive data/tmp/third_party ignores here only."
assert marker not in text
ignore.write_text(text + "\n\n" + marker + "\n!workspace_support/\n!workspace_support/**\n", encoding="utf-8")
result = {
    "as_of": "2026-10-16",
    "purpose": "All project code is delivered; large raw histories and external runtime payloads remain local, unchanged.",
    "snapshot": "Final pre-ignore plan, before applying these documented local-only ignore entries.",
    "excluded_file_count": len(records),
    "excluded_bytes": sum(row["size_bytes"] for row in records),
    "hash_coverage_note": "Prior streamed inventory hashes are copied where available; runtime caches without hashes are not project sources. No raw arrays were deleted or regenerated.",
    "entries": records,
    "shared_archive": {"path": "workspace_support/archive_manifest.json", "hash_rule": "Each archived source/evidence file has its own SHA-256 in the archive manifest; recursive ignore patterns are explicitly reversed for this dedicated directory."},
}
dest = ROOT / "relicweave-synlab/docs/handover/20261016/LOCAL_ARTIFACT_DELIVERY_BOUNDARY.json"
dest.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"excluded_files":len(records),"excluded_bytes":result["excluded_bytes"],"with_inventory_sha256":sum(bool(x["inventory_sha256"]) for x in records)}))
