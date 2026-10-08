import ast
from pathlib import Path
p = Path(r"C:\Users\xiemo\Desktop\ShardForge\relicweave-synlab\tools\next_experiment_export.py")
text = p.read_text(encoding="utf-8")
# thread the profile through explicitly instead of a module global
text = text.replace("def step_freeze(store: AssetStore, *, ledger_path: Path, out_dir: Path,\n"
                    "                evidence_root: str | None) -> dict[str, Any]:",
                    "def step_freeze(store: AssetStore, *, ledger_path: Path, out_dir: Path,\n"
                    "                evidence_root: str | None, profile: str = PROFILE) -> dict[str, Any]:")
text = text.replace('            result = step_freeze(store, ledger_path=Path(args.ledger), out_dir=out_dir,\n'
                    '                                 evidence_root=args.evidence)',
                    '            result = step_freeze(store, ledger_path=Path(args.ledger), out_dir=out_dir,\n'
                    '                                 evidence_root=args.evidence, profile=profile)')
text = text.replace("    args = parser.parse_args(argv)\n    global PROFILE\n    PROFILE = str(args.profile).upper()\n",
                    "    args = parser.parse_args(argv)\n    profile = str(args.profile).upper()\n")
# inside step_freeze, the local name `profile` now shadows nothing: rename the gate-derived one
text = text.replace("    gates, _gate_assets, profile = gates_mod.evaluate_gates(\n"
                    "        store, run_ids[0], evidence_dirs=evidence_dirs)",
                    "    gates, _gate_assets, run_profile = gates_mod.evaluate_gates(\n"
                    "        store, run_ids[0], evidence_dirs=evidence_dirs)")
text = text.replace('json.dumps({"profile": profile, "gates": gates, "evidence": evidence},',
                    'json.dumps({"profile": run_profile, "gates": gates, "evidence": evidence},')
text = text.replace('blocked = {\n            "schema": "synlab.release_freeze_blocked.v1", "frozen": False,\n'
                    '            "release_id_attempted": release_id, "profile": PROFILE,\n'
                    '            "required_gates": PROFILE_GATES[PROFILE],',
                    'blocked = {\n            "schema": "synlab.release_freeze_blocked.v1", "frozen": False,\n'
                    '            "release_id_attempted": release_id, "profile": profile,\n'
                    '            "required_gates": PROFILE_GATES[profile],')
text = text.replace('record = manager.freeze(release_id=release_id, profile=PROFILE, scope="SYNTHETIC",',
                    'record = manager.freeze(release_id=release_id, profile=profile, scope="SYNTHETIC",')
text = text.replace('        return {"status": "FAILED", "frozen": False, "release_id_attempted": release_id,\n'
                    '                "profile": PROFILE, "gates": gates, "coverage": coverage,',
                    '        return {"status": "FAILED", "frozen": False, "release_id_attempted": release_id,\n'
                    '                "profile": profile, "gates": gates, "coverage": coverage,')
ast.parse(text)
p.write_text(text, encoding="utf-8", newline="\n")
leftover = [l for l in text.splitlines() if "PROFILE" in l]
print("remaining PROFILE lines:")
for l in leftover:
    print("   ", l.strip())
