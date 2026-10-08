import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"C:\Users\xiemo\Desktop\ShardForge")
COORD = ROOT / "tmp" / "review_20261005" / "backup_coordinator"
OLD_SCOPE_PATH = COORD / "approved_execution_scope_v3_111_20261005.json"
OLD_EXEC_PATH = COORD / "git_execution_receipt_v3_111_20261005_continuation.json"
OUT_PATH = COORD / "next_incremental_backup_plan_20261005_v1.json"
BRANCH = "backup/forge-work-20261003"
MAX_FILES = 60
MAX_BYTES = 10 * 1024 * 1024


def sha_file(path: Path):
    h = hashlib.sha256()
    n = 0
    with path.open("rb") as f:
        while True:
            b = f.read(1024 * 1024)
            if not b:
                break
            h.update(b)
            n += len(b)
    return n, h.hexdigest()


def git(repo: Path, args):
    argv = ["git", "-c", "core.autocrlf=false", *args]
    p = subprocess.run(argv, cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    return {
        "argv": argv,
        "returncode": p.returncode,
        "stdout": p.stdout.decode("utf-8", "replace").strip(),
        "stderr": p.stderr.decode("utf-8", "replace").strip(),
    }


def cat_blob(repo: Path, oid: str):
    p = subprocess.Popen(["git", "-c", "core.autocrlf=false", "cat-file", "blob", oid], cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    h = hashlib.sha256()
    n = 0
    while True:
        b = p.stdout.read(1024 * 1024)
        if not b:
            break
        h.update(b)
        n += len(b)
    err = p.stderr.read().decode("utf-8", "replace").strip()
    rc = p.wait()
    return {"returncode": rc, "bytes": n, "sha256": h.hexdigest(), "stderr": err}


def repo_preflight(name):
    repo = ROOT / name
    branch = git(repo, ["branch", "--show-current"])
    head = git(repo, ["rev-parse", "HEAD"])
    origin = git(repo, ["remote", "get-url", "origin"])
    remote = git(repo, ["ls-remote", "origin", f"refs/heads/{BRANCH}"])
    tracked_diff = git(repo, ["diff", "--quiet"])
    index_diff = git(repo, ["diff", "--cached", "--quiet"])
    tracked_status = git(repo, ["status", "--porcelain=v1", "--untracked-files=no"])
    if any(x["returncode"] != 0 for x in (branch, head, origin, remote, tracked_diff, index_diff, tracked_status)):
        raise RuntimeError(f"read-only git preflight command failed for {name}")
    remote_oid = remote["stdout"].split()[0] if remote["stdout"] else None
    expected_head = {"pgfrag": "f21f15837eab1e012a0007422cd819d8f3171a18", "vesselforge": "c65624062fc0dbdaaceed9b1ea92335b92976682"}[name]
    if branch["stdout"] != BRANCH or head["stdout"] != expected_head or remote_oid != expected_head:
        raise RuntimeError(f"branch/head/remote moved for {name}: {branch['stdout']} {head['stdout']} {remote_oid}")
    return {
        "branch": branch["stdout"],
        "head": head["stdout"],
        "origin": origin["stdout"],
        "remote_head": remote_oid,
        "tracked_worktree_clean": tracked_diff["returncode"] == 0,
        "index_clean": index_diff["returncode"] == 0,
        "tracked_status": tracked_status["stdout"],
        "read_only_commands_succeeded": True,
    }


def file_row(group, repo_name, rel_source, rel_dest, operation, role, note=None):
    repo = ROOT / repo_name
    source = repo / Path(rel_source.replace("/", os.sep))
    if not source.is_file():
        raise FileNotFoundError(source)
    n1, h1 = sha_file(source)
    n2, h2 = sha_file(source)
    if (n1, h1) != (n2, h2):
        raise RuntimeError(f"source changed while hashing: {source}")
    dest = repo / Path(rel_dest.replace("/", os.sep))
    if operation == "stage_existing":
        if source.resolve() != dest.resolve():
            raise RuntimeError(f"stage_existing target must equal source: {source} -> {dest}")
    else:
        if dest.exists():
            raise RuntimeError(f"copy destination already exists; no overwrite allowed: {dest}")
    return {
        "group": group,
        "repo": repo_name,
        "operation": operation,
        "source_path": str(source),
        "source_repo_path": rel_source,
        "destination_repo_path": rel_dest,
        "role": role,
        "bytes": n1,
        "sha256": h1,
        "destination_preexists": dest.exists(),
        "note": note,
    }


def tracked_state(repo_name, relpath):
    repo = ROOT / repo_name
    ls = git(repo, ["ls-files", "--error-unmatch", "--", relpath])
    ignored = git(repo, ["check-ignore", "--no-index", "-v", "--", relpath])
    ignore_info = {
        "ignored": ignored["returncode"] == 0,
        "rule": ignored["stdout"] if ignored["returncode"] == 0 else None,
        "returncode": ignored["returncode"],
    }
    if ls["returncode"] != 0:
        return {"tracked_at_head": False, "head_blob": None, "head_blob_matches_candidate": False, "ignore_check": ignore_info}
    oid = git(repo, ["rev-parse", f"HEAD:{relpath}"])
    if oid["returncode"] != 0:
        return {"tracked_at_head": True, "head_blob": None, "head_blob_matches_candidate": False, "ignore_check": ignore_info}
    blob = cat_blob(repo, oid["stdout"].strip())
    return {"tracked_at_head": True, "head_blob": {"oid": oid["stdout"].strip(), **blob}, "ignore_check": ignore_info}


def load_json(rel):
    return json.loads((ROOT / Path(rel.replace("/", os.sep))).read_text(encoding="utf-8"))


def main():
    old_scope_bytes, old_scope_sha = sha_file(OLD_SCOPE_PATH)
    old_scope = json.loads(OLD_SCOPE_PATH.read_text(encoding="utf-8"))
    old_execution = json.loads(OLD_EXEC_PATH.read_text(encoding="utf-8"))
    preflight = {name: repo_preflight(name) for name in ("pgfrag", "vesselforge")}
    groups = []
    candidates = []
    omitted_redundant = []

    # 1. EFGM-MLS adapter source, pre-run review/freeze, and actual bounded run.
    efgm_root = "tmp/review_20261005/efgm_mls_patch_20261005"
    efgm_run = efgm_root + "/runs/run_20261005_efgm_mls_patch_01"
    efgm_sources = [
        "experiments/efgm_mls_patch_20261005/fixed_case.json",
        "experiments/efgm_mls_patch_20261005/mls_elastic_adapter.py",
        "experiments/efgm_mls_patch_20261005/operator_diagnostic.py",
        "experiments/efgm_mls_patch_20261005/README.md",
    ]
    efgm_file_map = []
    for p in efgm_sources:
        efgm_file_map.append(file_row("efgm_mls_patch", "pgfrag", p, p, "stage_existing", "owned source/case/README"))
    efgm_files = [
        (efgm_root + "/SOURCE_REVIEW.md", "review/SOURCE_REVIEW.md", "pre-run source review; historical scope record"),
        (efgm_root + "/source_freeze.json", "freeze/source_freeze.json", "source freeze manifest"),
        (efgm_root + "/source_freeze.sha256", "freeze/source_freeze.sha256", "source freeze manifest hash"),
        (efgm_run + "/operator_diagnostic.json", "run_20261005_efgm_mls_patch_01/operator_diagnostic.json", "primary actual diagnostic output"),
        (efgm_run + "/run_record.json", "run_20261005_efgm_mls_patch_01/run_record.json", "bounded execution record with pre/post source pins"),
        (efgm_run + "/stderr.txt", "run_20261005_efgm_mls_patch_01/stderr.txt", "actual run stderr log (empty)"),
    ]
    for src, dest, note in efgm_files:
        efgm_file_map.append(file_row("efgm_mls_patch", "pgfrag", src, "docs/evidence/20261005/efgm_mls_patch_20261005/" + dest, "copy_then_stage", "curated evidence", note))
    efgm_freeze = load_json("pgfrag/" + efgm_root + "/source_freeze.json")
    efgm_freeze_hashfile = (ROOT / "pgfrag" / Path(efgm_root.replace("/", os.sep)) / "source_freeze.sha256").read_text(encoding="utf-8").strip().split()[0]
    if hashlib.sha256((ROOT / "pgfrag" / Path(efgm_root.replace("/", os.sep)) / "source_freeze.json").read_bytes()).hexdigest() != efgm_freeze_hashfile:
        raise RuntimeError("EFGM source_freeze.sha256 does not match manifest")
    efgm_by_rel = {e["path"].removeprefix("pgfrag/"): e for e in efgm_freeze["files"]}
    for row in efgm_file_map[:4]:
        pin = efgm_by_rel.get(row["source_repo_path"])
        if not pin or (pin["bytes"], pin["sha256"]) != (row["bytes"], row["sha256"]):
            raise RuntimeError(f"EFGM frozen owned-source mismatch: {row['source_repo_path']}")
    efgm_run_record = load_json("pgfrag/" + efgm_run + "/run_record.json")
    stdout_path = ROOT / "pgfrag" / Path((efgm_run + "/stdout.txt").replace("/", os.sep))
    embedded_stdout = efgm_run_record.get("stdout_text", "").encode("utf-8")
    actual_stdout = stdout_path.read_bytes()
    if actual_stdout == embedded_stdout:
        omitted_redundant.append({
            "repo": "pgfrag",
            "source_path": str(stdout_path),
            "bytes": len(actual_stdout),
            "sha256": hashlib.sha256(actual_stdout).hexdigest(),
            "reason": "exact stdout payload is already embedded in the included run_record.json; omitted as redundant per root scope",
        })
    else:
        efgm_file_map.append(file_row("efgm_mls_patch", "pgfrag", efgm_run + "/stdout.txt", "docs/evidence/20261005/efgm_mls_patch_20261005/run_20261005_efgm_mls_patch_01/stdout.txt", "copy_then_stage", "actual run stdout", "Not byte-identical to run_record.stdout_text; retained as a distinct log."))
    efgm_checks = {
        "source_freeze_status": efgm_freeze.get("status"),
        "source_freeze_is_pre_run_snapshot": True,
        "source_freeze_status_context": "Freeze/review retain their pre-run awaiting-root-review wording; the later run_record records the subsequent bounded root-authorized invocation and matching pre/post pins.",
        "source_freeze_manifest_sha256_matches_sidecar": True,
        "run_record_return_code": efgm_run_record.get("real_return_code"),
        "run_record_source_freeze_sha256_matches": efgm_run_record.get("source_freeze_manifest_sha256") == efgm_freeze_hashfile,
        "run_record_pre_post_pins_match": all(p.get("matches_approved_pin") and p.get("unchanged_during_run") for p in efgm_run_record.get("post_run_pins", [])),
        "primary_output_status": load_json("pgfrag/" + efgm_run + "/operator_diagnostic.json").get("status"),
        "limited_interpretation": "one uncracked MLS-to-elastic operator diagnostic; no solver/load/crack/fracture or EFGM stability claim",
    }
    if efgm_checks["run_record_return_code"] != 0 or not efgm_checks["run_record_source_freeze_sha256_matches"] or not efgm_checks["run_record_pre_post_pins_match"]:
        raise RuntimeError("EFGM actual run/freeze evidence validation failed")
    groups.append({"id": "efgm_mls_patch", "repo": "pgfrag", "entries": efgm_file_map, "validation": efgm_checks})
    candidates.extend(efgm_file_map)

    # 2. VF native wall-probe v2, scoped to finite rays and sections.
    wall_root = "tmp/review_20261005/native_cad_wall_probe_20261005"
    wall_files = [
        ("normal_wall_probe.v2.py", "source/normal_wall_probe.v2.py", "frozen v2 adapter source"),
        ("run_normal_wall_probe.v2.ps1", "source/run_normal_wall_probe.v2.ps1", "frozen v2 bounded runner"),
        ("FREEZE.v2.json", "freeze/FREEZE.v2.json", "v2 source freeze"),
        ("normal_wall_probe_data.json", "run/normal_wall_probe_data.json", "actual numeric probe data"),
        ("normal_wall_probe_render_status.json", "run/normal_wall_probe_render_status.json", "separate render status"),
        ("parent_execution_receipt.json", "run/parent_execution_receipt.json", "parent execution receipt"),
        ("normal_wall_probe_rays_3d.png", "images/normal_wall_probe_rays_3d.png", "actual 3D ray visualization"),
        ("normal_wall_probe_section_y0.png", "images/normal_wall_probe_section_y0.png", "actual y=0 section visualization"),
    ]
    wall_rows = [file_row("native_cad_wall_probe_v2", "vesselforge", wall_root + "/" + src, "docs/evidence/20261005/native_cad_wall_probe_v2_20261005/" + dest, "copy_then_stage", "curated evidence/source", note) for src, dest, note in wall_files]
    wall_freeze = load_json("vesselforge/" + wall_root + "/FREEZE.v2.json")
    wall_data = load_json("vesselforge/" + wall_root + "/normal_wall_probe_data.json")
    wall_manifest = load_json("vesselforge/" + wall_root + "/normal_wall_probe_run_manifest.json")
    wall_render = load_json("vesselforge/" + wall_root + "/normal_wall_probe_render_status.json")
    wall_pin_checks = {
        "freeze_state": wall_freeze.get("state"),
        "freeze_is_pre_run_snapshot": True,
        "freeze_state_context": "FREEZE.v2 is the retained pre-run source snapshot; actual execution/render outcomes are separately evidenced by primary data, parent receipt, and render status.",
        "source_sha256_matches_v2_freeze": sha_file(ROOT / "vesselforge" / Path((wall_root + "/normal_wall_probe.v2.py").replace("/", os.sep)))[1] == wall_freeze.get("hashes", {}).get("adapter_sha256"),
        "runner_sha256_matches_v2_freeze": sha_file(ROOT / "vesselforge" / Path((wall_root + "/run_normal_wall_probe.v2.ps1").replace("/", os.sep)))[1] == wall_freeze.get("hashes", {}).get("runner_sha256"),
        "data_status": wall_data.get("status"),
        "global_wall_status": wall_data.get("global_wall_status"),
        "run_manifest_status": wall_manifest.get("status"),
        "render_status": wall_render.get("status"),
        "png_hashes_match_render_receipt": True,
    }
    for key, filename, pin_key in (("rays", "normal_wall_probe_rays_3d.png", "rays_png_sha256"), ("section", "normal_wall_probe_section_y0.png", "section_png_sha256")):
        actual = sha_file(ROOT / "vesselforge" / Path((wall_root + "/" + filename).replace("/", os.sep)))[1]
        if actual != wall_render.get(pin_key):
            wall_pin_checks["png_hashes_match_render_receipt"] = False
    if not wall_pin_checks["source_sha256_matches_v2_freeze"] or not wall_pin_checks["runner_sha256_matches_v2_freeze"] or not wall_pin_checks["png_hashes_match_render_receipt"] or wall_pin_checks["render_status"] != "SUCCESS":
        raise RuntimeError("wall-probe v2 source/render pins failed")
    wall_pin_checks["limited_interpretation"] = "finite normal-ray probes and one section only; global wall status remains UNKNOWN_FINITE_PROBES_ONLY"
    if wall_manifest.get("worker_data") != wall_data:
        raise RuntimeError("wall-probe run manifest no longer duplicates the primary data; review whether it should be included")
    wall_manifest_path = ROOT / "vesselforge" / Path((wall_root + "/normal_wall_probe_run_manifest.json").replace("/", os.sep))
    wall_manifest_n, wall_manifest_h = sha_file(wall_manifest_path)
    omitted_redundant.append({
        "repo": "vesselforge",
        "source_path": str(wall_manifest_path),
        "bytes": wall_manifest_n,
        "sha256": wall_manifest_h,
        "reason": "worker_data is exactly identical to the included normal_wall_probe_data.json; actual run hashes/status are retained in parent_execution_receipt.json and render_status.json",
    })
    groups.append({"id": "native_cad_wall_probe_v2", "repo": "vesselforge", "entries": wall_rows, "validation": wall_pin_checks})
    candidates.extend(wall_rows)

    # 3. Independent native-free run03 audit outputs; do not include the large native binaries or runtime.
    run03_root = "tmp/review_20261005/free_fracture_pilot_independent_review/run03"
    run03_files = [
        ("RUN03_FREEZE.json", "run/RUN03_FREEZE.json", "authorized audit freeze and 84 source pins"),
        ("RUN03_STATIC_PREFLIGHT.json", "run/RUN03_STATIC_PREFLIGHT.json", "static preflight record"),
        ("RUN03_EXECUTION_RECORD.json", "run/RUN03_EXECUTION_RECORD.json", "actual run03 integrity and arithmetic record"),
        ("post_execution_snapshot.json", "run/post_execution_snapshot.json", "post-run source/result pin snapshot"),
        ("pilot_input_hash_inventory.json", "run/pilot_input_hash_inventory.json", "input/output inventory; hashes and sizes only"),
        ("bounded_runner_receipt.json", "run/bounded_runner_receipt.json", "bounded audit runner receipt"),
        ("audit_output/pilot_independent_review.json", "audit/pilot_independent_review.json", "actual independent audit JSON"),
        ("audit_output/PILOT_REVIEW_REPORT.md", "audit/PILOT_REVIEW_REPORT.md", "human-readable audit report"),
        ("audit_output/pilot_timeline_graph_energy.png", "images/pilot_timeline_graph_energy.png", "actual audit visualization"),
        ("audit_output/pilot_geometry_damage_first_breaks.png", "images/pilot_geometry_damage_first_breaks.png", "actual audit visualization"),
    ]
    run03_rows = [file_row("free_fracture_independent_run03", "pgfrag", run03_root + "/" + src, "docs/evidence/20261005/free_fracture_pilot_independent_run03/" + dest, "copy_then_stage", "curated native-free audit evidence", note) for src, dest, note in run03_files]
    run03_freeze = load_json("pgfrag/" + run03_root + "/RUN03_FREEZE.json")
    run03_record = load_json("pgfrag/" + run03_root + "/RUN03_EXECUTION_RECORD.json")
    run03_audit = load_json("pgfrag/" + run03_root + "/audit_output/pilot_independent_review.json")
    run03_validation = {
        "freeze_source_pins": run03_freeze.get("pre_execution", {}).get("source_pin_count"),
        "freeze_source_pins_match": run03_freeze.get("pre_execution", {}).get("all_84_source_pins_match"),
        "runner_status": run03_record.get("runner", {}).get("status"),
        "native_arithmetic_validation": run03_record.get("native_arithmetic_validation"),
        "all_result_file_pins_match": run03_record.get("input_and_output_integrity", {}).get("output_files", {}).get("all_match"),
        "audit_status": run03_audit.get("status"),
        "receipt_size_recorded_bytes": run03_record.get("receipt_size_check", {}).get("recorded_bytes"),
        "receipt_size_observed_bytes": run03_record.get("receipt_size_check", {}).get("observed_bytes"),
        "receipt_size_discrepancy_bytes": run03_record.get("receipt_size_check", {}).get("observed_minus_recorded_bytes"),
        "limitations": "all 6,810 events are right-grip separation, not internal physical fracture; receipt-size discrepancy is retained; native solver not rerun",
    }
    if run03_validation["freeze_source_pins_match"] is not True or run03_validation["runner_status"] != "COMPLETED" or run03_validation["audit_status"] != "AUDITED_WITH_RECEIPT_SIZE_DISCREPANCY":
        raise RuntimeError("run03 audit receipts do not show the expected bounded completed state")
    groups.append({"id": "free_fracture_independent_run03", "repo": "pgfrag", "entries": run03_rows, "validation": run03_validation})
    candidates.extend(run03_rows)

    # 4. Independent ROI oracle math and render-only correction. Raw retained stage and runtime are intentionally omitted.
    roi_root = "tmp/review_20261005/forge_volume_ingress_independent_review"
    roi_run = roi_root + "/audit_retry_hashcase_plotcompat_20261005"
    roi_render = roi_run + "/render_only_revised_colorbar_20261005"
    roi_files = [
        (roi_root + "/analytic_roi_reference.py", "sources/analytic_roi_reference.py", "independent analytic ROI reference source"),
        (roi_root + "/ANALYTIC_METHOD.md", "sources/ANALYTIC_METHOD.md", "analytic reference method"),
        (roi_root + "/pilot_actual_audit.py", "sources/pilot_actual_audit.py", "independent actual-output audit source"),
        (roi_root + "/PILOT_AUDIT_INPUT_FREEZE.json", "freeze/PILOT_AUDIT_INPUT_FREEZE.json", "actual audit input freeze"),
        (roi_root + "/FINAL_SOURCE_REVIEW.md", "review/FINAL_SOURCE_REVIEW.md", "source review and residual limits"),
        (roi_root + "/FINAL_SOURCE_REVIEW.json", "review/FINAL_SOURCE_REVIEW.json", "machine-readable source review"),
        (roi_root + "/FINAL_EXECUTION_ARTIFACT_HASHES.json", "execution/FINAL_EXECUTION_ARTIFACT_HASHES.json", "final execution artifact pins"),
        (roi_root + "/READONLY_AUDIT_EXECUTION_RECEIPT_renderreport_retry.json", "execution/READONLY_AUDIT_EXECUTION_RECEIPT_renderreport_retry.json", "actual independent audit execution receipt"),
        (roi_root + "/READONLY_AUDIT_STDOUT_renderreport_retry.txt", "execution/READONLY_AUDIT_STDOUT_renderreport_retry.txt", "actual audit stdout"),
        (roi_root + "/READONLY_AUDIT_STDERR_renderreport_retry.txt", "execution/READONLY_AUDIT_STDERR_renderreport_retry.txt", "actual audit stderr"),
        (roi_run + "/PILOT_ACTUAL_AUDIT.json", "audit/PILOT_ACTUAL_AUDIT.json", "actual 96-cell independent numeric audit JSON"),
        (roi_run + "/PILOT_CELL_AUDIT.csv", "audit/PILOT_CELL_AUDIT.csv", "actual per-cell geometry/mass audit CSV"),
        (roi_run + "/PILOT_POINT_AUDIT.csv", "audit/PILOT_POINT_AUDIT.csv", "actual point delivery audit CSV"),
        (roi_root + "/render_only_grid_colorbar_fix.py", "render_only/render_only_grid_colorbar_fix.py", "render-only plotting source; no geometry recomputation"),
        (roi_render + "/PILOT_CELL_VOLUME_MASS_DELTA_render_only.png", "render_only/PILOT_CELL_VOLUME_MASS_DELTA_render_only.png", "new render-only cell volume/mass figure"),
        (roi_render + "/PILOT_XY_CELL_MAP_grid_colorbar.png", "render_only/PILOT_XY_CELL_MAP_grid_colorbar.png", "new render-only XY map"),
        (roi_render + "/RENDER_ONLY_EXECUTION_RECEIPT.json", "render_only/RENDER_ONLY_EXECUTION_RECEIPT.json", "render-only execution/hash receipt"),
        (roi_render + "/RENDER_ONLY_RECEIPT.json", "render_only/RENDER_ONLY_RECEIPT.json", "render result receipt"),
        (roi_render + "/RENDER_ONLY_STDOUT.txt", "render_only/RENDER_ONLY_STDOUT.txt", "render-only stdout"),
        (roi_render + "/RENDER_ONLY_STDERR.txt", "render_only/RENDER_ONLY_STDERR.txt", "render-only stderr"),
    ]
    roi_rows = [file_row("forge_volume_ingress_independent_audit", "pgfrag", src, "docs/evidence/20261005/forge_volume_ingress_independent_audit_20261005/" + dest, "copy_then_stage", "curated independent audit/render evidence", note) for src, dest, note in roi_files]
    roi_actual = load_json("pgfrag/" + roi_run + "/PILOT_ACTUAL_AUDIT.json")
    roi_review = load_json("pgfrag/" + roi_root + "/FINAL_SOURCE_REVIEW.json")
    roi_hash_record = load_json("pgfrag/" + roi_root + "/FINAL_EXECUTION_ARTIFACT_HASHES.json")
    roi_render_receipt = load_json("pgfrag/" + roi_render + "/RENDER_ONLY_RECEIPT.json")
    roi_exec_receipt = load_json("pgfrag/" + roi_run + "/render_only_revised_colorbar_20261005/RENDER_ONLY_EXECUTION_RECEIPT.json")
    roi_validation = {
        "source_review_status": roi_review.get("status"),
        "audit_status": roi_actual.get("status"),
        "all_local_checks_pass": roi_actual.get("all_checks_pass"),
        "candidate_promotion_status": roi_actual.get("finalization_and_promotion", {}).get("final_status"),
        "render_only_status": roi_render_receipt.get("status"),
        "render_execution_status": roi_exec_receipt.get("status"),
        "render_geometry_recomputed": roi_render_receipt.get("geometry_recomputed"),
        "render_inputs_match_pins": roi_exec_receipt.get("script_and_three_inputs_unchanged"),
        "render_only_pngs_match_receipt": True,
        "limitation": "local 96-cell geometry diagnostic only; report finalization blocked and candidate not promoted; no whole-mother coverage or physical calibration claim",
    }
    for filename in ("PILOT_CELL_VOLUME_MASS_DELTA_render_only.png", "PILOT_XY_CELL_MAP_grid_colorbar.png"):
        row = next(r for r in roi_rows if r["source_path"].endswith(filename))
        actual_sha = row["sha256"]
        expected_sha = roi_render_receipt.get("outputs", {}).get(filename, {}).get("sha256")
        if not expected_sha or expected_sha != actual_sha:
            roi_validation["render_only_pngs_match_receipt"] = False
    if not roi_validation["render_only_pngs_match_receipt"]:
        raise RuntimeError("ROI rendered PNG hash does not match render receipt")
    roi_validation["final_hash_record_schema"] = roi_hash_record.get("schema")
    groups.append({"id": "forge_volume_ingress_independent_audit", "repo": "pgfrag", "entries": roi_rows, "validation": roi_validation})
    candidates.extend(roi_rows)

    # Omit duplicate entries already accepted in the previous 111-file scope or already present unchanged at HEAD.
    old_map = {}
    for entry in old_scope["approved_exact_entries"]:
        old_map[(entry["repo"], entry["destination_repo_path"])] = (entry["expected_bytes"], entry["expected_sha256"])
    planned = []
    already = []
    errors = []
    for row in candidates:
        key = (row["repo"], row["destination_repo_path"])
        if key in old_map:
            if old_map[key] == (row["bytes"], row["sha256"]):
                already.append({**row, "status": "already_in_previous_111_batch_unchanged"})
                continue
            errors.append(f"destination overlaps previous approved scope with a different hash: {key}")
            continue
        state = tracked_state(row["repo"], row["destination_repo_path"])
        if state.get("tracked_at_head"):
            blob = state.get("head_blob") or {}
            if blob.get("returncode") == 0 and (blob.get("bytes"), blob.get("sha256")) == (row["bytes"], row["sha256"]):
                already.append({**row, "status": "already_present_unchanged_at_head", "head_blob": blob})
                continue
            if row["operation"] != "stage_existing":
                errors.append(f"copy destination already tracked with different bytes: {key}")
                continue
        planned.append({**row, "head_state": state})
    if errors:
        raise RuntimeError("plan validation errors: " + "; ".join(errors))
    unique_dest = {(e["repo"], e["destination_repo_path"]) for e in planned}
    if len(unique_dest) != len(planned):
        raise RuntimeError("duplicate plan destinations")
    total_bytes = sum(e["bytes"] for e in planned)
    if len(planned) > MAX_FILES or total_bytes > MAX_BYTES:
        raise RuntimeError(f"incremental plan cap exceeded: files={len(planned)} bytes={total_bytes}")

    # Verify destination prefixes resolve inside their intended repository, without creating directories.
    for e in planned:
        repo = ROOT / e["repo"]
        dest = (repo / Path(e["destination_repo_path"].replace("/", os.sep))).resolve()
        if repo.resolve() not in dest.parents:
            raise RuntimeError(f"destination escapes repo: {dest}")

    receipt = {
        "schema": "backup_coordinator.incremental_curated_plan.v1",
        "status": "PREPARED_SOURCE_HASH_ROSTER_ROOT_REVIEW_REQUIRED_NO_GIT_WRITES",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "plan_only": True,
        "no_copy_stage_commit_push": True,
        "baseline_after_previous_backup": {
            "plan_path": str(OLD_SCOPE_PATH),
            "scope_file_bytes": old_scope_bytes,
            "scope_sha256": old_scope_sha,
            "previous_execution_receipt_sha256": hashlib.sha256(OLD_EXEC_PATH.read_bytes()).hexdigest(),
            "repos": preflight,
        },
        "limits": {"max_new_files": MAX_FILES, "max_new_bytes": MAX_BYTES, "actual_new_files": len(planned), "actual_new_bytes": total_bytes},
        "counts_by_repo": {name: sum(1 for e in planned if e["repo"] == name) for name in ("pgfrag", "vesselforge")},
        "counts_by_group": {g["id"]: sum(1 for e in planned if e["group"] == g["id"]) for g in groups},
        "groups": groups,
        "exact_new_entries": planned,
        "omitted_already_present": already,
        "omitted_redundant": omitted_redundant,
        "explicit_scope_exclusions": [
            "raw/native binary result bundles, runtime/depot/venv/cache, large duplicated data, original DOCX, third-party copyrighted excerpts, credentials/secrets",
            "nativefree run03 raw producer binaries/result tree; only the independent audit artifacts are proposed",
            "ROI retained stage and unrelated historical retry artifacts; only the final actual audit outputs and render-only receipts are proposed",
            "additional mode-III and two-cap packages deferred to a later batch",
        ],
        "group_interpretation": {
            "efgm_mls_patch": "single bounded uncracked MLS-to-elastic operator diagnostic; no solver, load, crack, fracture, or EFGM stability claim",
            "native_cad_wall_probe_v2": "finite ray/section probes only; global wall status unknown",
            "free_fracture_independent_run03": "native-free independent numeric review; retains 53-byte receipt-size discrepancy; 6,810 events are right-grip separation, not physical fracture",
            "forge_volume_ingress_independent_audit": "local 96-cell geometry diagnostic; report finalization blocked, candidate not promoted, no whole-mother coverage or physical calibration claim",
        },
        "execution_constraints_for_future_root_review": [
            "Do not copy or stage until root approves the exact generated plan SHA.",
            "At execution, recheck every source SHA/byte count and destination absence; stop on any mismatch.",
            "Use exact path staging only and skip paths already identical at HEAD.",
            "Keep commit scopes per repository and retain all historical failure receipts.",
        ],
    }
    data = (json.dumps(receipt, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    OUT_PATH.write_bytes(data)
    print(json.dumps({
        "status": receipt["status"],
        "path": str(OUT_PATH),
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "new_files": len(planned),
        "new_bytes": total_bytes,
        "counts_by_repo": receipt["counts_by_repo"],
        "counts_by_group": receipt["counts_by_group"],
        "already_present_unchanged": len(already),
        "redundant_omissions": omitted_redundant,
        "errors": errors,
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
