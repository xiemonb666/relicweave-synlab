import hashlib
import json
import re
from pathlib import Path


root = Path(__file__).resolve().parent
manifest = root / "path_migration.toml"
old_root = Path(r"C:\Users\xiemo\Desktop\ShardForge\SynLab\tmp\review_20261004\implementation\native_contact_minimal")
old_text = manifest.read_text(encoding="utf-8")


def find_field(block, name):
    match = re.search(rf"(?m)^{re.escape(name)} = \"([0-9a-f]+)\"$", block)
    return match.group(1) if match else None


old_records = {}
for block in re.findall(r"(?ms)^\[\[cases\]\]\r?\n(.*?)(?=^\[\[cases\]\]|\Z)", old_text):
    name_match = re.search(r'(?m)^name = "([^"]+)"$', block)
    if not name_match:
        continue
    name = name_match.group(1)
    old_records[name] = {
        "summary_before": find_field(block, "summary_sha256_before_path_annotation"),
        "summary_after": find_field(block, "summary_sha256_after_path_annotation"),
        "execution_before": find_field(block, "execution_sha256_before_toml_normalization") or find_field(block, "execution_sha256"),
    }


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ts(value):
    return json.dumps(str(value), ensure_ascii=False)


lines = [
    'schema = "native_contact_minimal.path_migration.v1"',
    f"source_path = {ts(old_root)}",
    f"destination_path = {ts(root)}",
    'reason = "Moved the actual run outputs from the mistaken SynLab alias directory into the relicweave-synlab review repository."',
    'move_action = "PowerShell Move-Item; destination was verified absent before the move"',
    "execution_toml_rewritten = true",
    "original_execution_argv_preserved = true",
    "execution_argv_exit_runtime_unchanged = true",
    'execution_toml_rewrite_reason = "Corrected the PowerShell boolean casing to valid TOML false and added current archived log paths."',
    "summary_toml_annotated_with_original_and_current_artifact_paths = true",
    "",
]

for name in ("preflight", "contact_baseline", "contact_halfdt", "nocontact_control"):
    case_dir = root / name
    old_dir = old_root / name
    lines.extend(
        [
            "[[cases]]",
            f"name = {ts(name)}",
            f"original_runtime_output_path = {ts(old_dir)}",
            f"current_archive_path = {ts(case_dir)}",
            f"summary_sha256_before_path_annotation = {ts(old_records[name]['summary_before'])}",
            f"summary_sha256_after_path_annotation = {ts(sha(case_dir / 'summary.toml'))}",
            f"execution_sha256_before_toml_normalization = {ts(old_records[name]['execution_before'])}",
            f"execution_sha256_after_toml_normalization = {ts(sha(case_dir / 'execution.toml'))}",
            f"points_sha256 = {ts(sha(case_dir / 'points.csv'))}",
            "",
        ]
    )

manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"Rewrote valid TOML path migration manifest: {manifest}")
