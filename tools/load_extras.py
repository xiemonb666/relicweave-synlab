"""``load_extras`` -- inspect and verify a package's ``synthetic_extra/`` view.

The extras view holds the nine *bench-unobtainable* modalities of
``docs/a12/rig_contract.md`` §8.  This loader is the authority for that view: it reads
``synthetic_extra/index.json`` (which was itself produced by a filesystem scan) and never
touches ``deploy/`` or ``research/``.

Usage::

    python tools/load_extras.py --list
    python tools/load_extras.py --modality dense_depth_reliable
    python tools/load_extras.py --check
    python tools/load_extras.py --package data/a12_exports/a12_extras --json --list

Exit codes
----------
``0``  the requested action succeeded and, for ``--check``, every check passed
``3``  ``--check`` found a problem (missing file, hash mismatch, a breached claim ban,
       an extras/deploy channel collision, or an extras artifact inside ``deploy/``)
``2``  the command line itself is unusable (unknown modality id, missing package)

``--check`` deliberately fails when an annotation claims ``rig_obtainable=true`` or
``claim_allowed=true``: the whole point of this view is that those two flags are constants
of the §8 catalogue and cannot be turned on by any run parameter.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from synlab.observe.synthetic_extras import MODALITY_BY_ID, MODALITY_IDS  # noqa: E402
from synlab.storage.export_extras import check_extras, extras_dir  # noqa: E402

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_INCONSISTENT = 3

DEFAULT_PACKAGE = "data/a12_exports/a12_extras"


def _load_index(root: Path) -> dict[str, Any]:
    path = root / "index.json"
    if not path.exists():
        raise SystemExit(f"no extras index at {path}; run the exporter first "
                         f"(synlab.storage.export_extras.export_extras)")
    return json.loads(path.read_text(encoding="utf-8"))


def _human_bytes(value: Any) -> str:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return "-"
    for unit in ("B", "KiB", "MiB", "GiB"):
        if abs(n) < 1024.0 or unit == "GiB":
            return f"{n:.2f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024.0
    return f"{n:.2f} GiB"


def _rows_for(index: dict[str, Any], modality_id: str | None,
              fragment_id: str | None) -> list[dict[str, Any]]:
    rows = list(index.get("rows", {}).values())
    if modality_id:
        rows = [r for r in rows if r.get("modality_id") == modality_id]
    if fragment_id:
        rows = [r for r in rows if r.get("fragment_id") == fragment_id]
    return rows


def action_list(index: dict[str, Any], *, as_json: bool) -> int:
    modalities = index.get("modalities", [])
    if as_json:
        print(json.dumps({"schema": index.get("schema"), "totals": index.get("totals"),
                          "modalities": modalities}, ensure_ascii=False, indent=2))
        return EXIT_OK
    totals = index.get("totals", {})
    print(f"extras index : {index.get('index_source')}")
    print(f"claim ban    : {index.get('claim_ban')}")
    print(f"totals       : {totals.get('instances')} instances / "
          f"{totals.get('modalities')} modalities / "
          f"{_human_bytes(totals.get('file_bytes'))} on disk / "
          f"{_human_bytes(totals.get('array_bytes'))} of arrays")
    print()
    header = (f"{'#':>2}  {'item':<4} {'modality_id':<26} {'n':>3} {'arrays':>6} "
              f"{'bytes':>11}  {'rig_obtainable':<14} {'claim_allowed':<13} unit/frame")
    print(header)
    print("-" * len(header))
    for modality in modalities:
        print(f"{'':>2}  {modality.get('item'):>4} {modality.get('modality_id'):<26} "
              f"{modality.get('instances'):>3} {len(modality.get('arrays') or {}):>6} "
              f"{_human_bytes(modality.get('file_bytes')):>11}  "
              f"{str(modality.get('rig_obtainable')):<14} "
              f"{str(modality.get('claim_allowed')):<13} "
              f"{modality.get('unit')}/{modality.get('frame')}")
    problems = index.get("problems", [])
    if problems:
        print(f"\nscan problems ({len(problems)}):")
        for item in problems[:20]:
            print(f"  - {item}")
    failures = index.get("generation_failures", [])
    if failures:
        print(f"\ngeneration failures ({len(failures)}):")
        for item in failures[:20]:
            print(f"  - {item.get('fragment_id')} {item.get('modality_id')}: "
                  f"{item.get('failure')}")
    isolation = index.get("isolation")
    if isolation:
        print(f"\ndeploy isolation: collisions={isolation.get('deploy_channel_collisions')} "
              f"leaked={isolation.get('extras_files_under_protected_dirs')} "
              f"ok={isolation.get('ok')}")
    return EXIT_OK


def action_modality(index: dict[str, Any], modality_id: str, *, as_json: bool,
                    fragment_id: str | None) -> int:
    if modality_id not in MODALITY_BY_ID:
        print(f"unknown modality id {modality_id!r}; known ids: {', '.join(MODALITY_IDS)}",
              file=sys.stderr)
        return EXIT_USAGE
    rows = _rows_for(index, modality_id, fragment_id)
    catalogue = next((m for m in index.get("modalities", [])
                      if m.get("modality_id") == modality_id), {})
    if as_json:
        print(json.dumps({"modality": catalogue, "rows": rows},
                         ensure_ascii=False, indent=2))
        return EXIT_OK
    print(f"modality_id    : {modality_id}")
    print(f"§8 item        : {catalogue.get('item')}")
    print(f"title          : {catalogue.get('title')}")
    print(f"rig_obtainable : {catalogue.get('rig_obtainable')}")
    print(f"synthetic_only : {catalogue.get('synthetic_only')}")
    print(f"rig_source     : {catalogue.get('rig_source')}")
    print(f"claim_allowed  : {catalogue.get('claim_allowed')}")
    print(f"unit / frame   : {catalogue.get('unit')} / {catalogue.get('frame')}")
    print(f"doc_refs       : {catalogue.get('doc_refs')}")
    print(f"reason         : {catalogue.get('reason')}")
    ablation = catalogue.get("ablation") or {}
    print(f"ablation switch: {ablation.get('field')}   group: {ablation.get('group')}")
    print(f"hypothesis     : {ablation.get('hypothesis')}")
    print(f"instances      : {catalogue.get('instances')}   "
          f"fragments: {catalogue.get('fragments')}")
    if not rows:
        print("\nno instance written for this modality")
        return EXIT_OK
    row = rows[0]
    print(f"\nfirst instance : {row.get('npz')}  ({_human_bytes(row.get('file_bytes'))}, "
          f"sha256 {str(row.get('sha256'))[:16]}...)")
    generator = row.get("generator") or {}
    print(f"seed_path      : {generator.get('seed_path')}")
    print(f"seed_ref       : {generator.get('seed_ref')}")
    print(f"params         : {json.dumps(generator.get('params'), ensure_ascii=False)}")
    print(f"seconds        : {generator.get('seconds')}")
    print("\narrays:")
    for name, meta in sorted((row.get("arrays") or {}).items()):
        print(f"  {name:<28} {str(meta.get('shape')):<22} {meta.get('dtype'):<10} "
              f"{_human_bytes(meta.get('bytes'))}")
    extra_keys = [k for k in sorted(row.get("annotation", {}))
                  if k not in ("shape", "dtype", "bytes", "generator", "ablation",
                               "doc_refs", "reason", "title", "claim_ban")]
    print("\nannotation fields:")
    for key in extra_keys:
        print(f"  {key:<32} {_short(row['annotation'][key])}")
    return EXIT_OK


def _short(value: Any, limit: int = 110) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False,
                                                           default=str)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def action_check(package: Path, *, as_json: bool, allow_missing: bool) -> int:
    report = check_extras(package, require_all_modalities=not allow_missing)
    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        return EXIT_OK if report["ok"] else EXIT_INCONSISTENT
    for check in report["checks"]:
        mark = "PASS" if check["ok"] else "FAIL"
        print(f"[{mark}] {check['check']}: {_short(check['detail'])}")
    problems = report.get("problems", [])
    if problems:
        print(f"\n{len(problems)} problem(s):")
        for item in problems:
            print(f"  - {item}")
        print(f"\nexit {EXIT_INCONSISTENT} (inconsistent)")
        return EXIT_INCONSISTENT
    totals = report.get("totals", {})
    print(f"\nextras view consistent: {totals.get('instances')} instances across "
          f"{totals.get('modalities')} modalities")
    print(f"exit {EXIT_OK} (consistent)")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="load_extras",
        description="inspect/verify the §8 synthetic_extra view of an export package")
    parser.add_argument("--package", default=DEFAULT_PACKAGE,
                        help=f"package directory (default {DEFAULT_PACKAGE})")
    parser.add_argument("--root", default=None,
                        help="override the extras root (default <package>/synthetic_extra)")
    parser.add_argument("--list", action="store_true", help="list the nine modalities")
    parser.add_argument("--modality", default=None, help="detail for one modality id")
    parser.add_argument("--fragment", default=None, help="restrict to one fragment id")
    parser.add_argument("--check", action="store_true",
                        help="verify the extras view; exit 0 pass / 3 fail")
    parser.add_argument("--allow-missing", action="store_true",
                        help="with --check, do not require all nine modalities to be present")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    package = Path(args.package)
    if args.modality and args.modality not in MODALITY_BY_ID:
        print(f"unknown modality id {args.modality!r}; known ids: {', '.join(MODALITY_IDS)}",
              file=sys.stderr)
        return EXIT_USAGE

    status = EXIT_OK
    if args.check:
        status = action_check(package, as_json=args.json, allow_missing=args.allow_missing)
        if status != EXIT_OK or not (args.list or args.modality):
            return status

    root = Path(args.root) if args.root else extras_dir(package)
    index = _load_index(root)
    if args.modality:
        code = action_modality(index, args.modality, as_json=args.json,
                               fragment_id=args.fragment)
        return code if code != EXIT_OK else status
    return action_list(index, as_json=args.json) if status == EXIT_OK else status


if __name__ == "__main__":
    raise SystemExit(main())
