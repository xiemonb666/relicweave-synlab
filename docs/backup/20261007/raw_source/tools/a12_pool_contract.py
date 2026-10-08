#!/usr/bin/env python
"""Pool-protocol contract runner: four parallel implementations, one battery, one exit code.

The suite itself lives in :mod:`synlab.qc.pool_contract` (single source of truth).  This driver
only *runs* it on real inputs and writes the raw report:

``--step canonical``
    The canonical context (``synlab.qc.pool_contract.canonical_context()``): one deterministic row
    set, every implementation instantiated from it, the full battery plus the cross-implementation
    agreement check, plus the **failure injection** proof (six single-clause breakages, each of
    which must be caught by its named assertion).

``--step real``
    The same battery on the real exported package's ``research/relations.parquet`` (default:
    ``data/a12_exports/negfix/next_experiment/training_package``) and on a real
    ``relations.gallery.RelationPool`` whose sparse index is loaded from the real asset store
    (``--store``) over the fragments the exported table names.  The agreement block is a
    *measurement* here, not a pass/fail on its own: the exported reader is deliberately
    conservative (a pair absent from the table is ``UNKNOWN``), so the two families cannot know
    the same amount.  What must hold is the safety half -- no implementation may offer a legal
    negative it cannot justify -- and that is what decides the exit code.

Usage::

    python tools/a12_pool_contract.py --step all --out data/a12_reports/pool_contract.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_PACKAGE = "data/a12_exports/negfix/next_experiment/training_package"
DEFAULT_STORE = "data/a12_trainable/store"


# --------------------------------------------------------------------------------------
# contexts
# --------------------------------------------------------------------------------------
def canonical_step() -> dict[str, Any]:
    from synlab.qc.pool_contract import (POOL_PROTOCOL_VERSION, build_implementations,
                                         canonical_context, run_contract_suite,
                                         run_failure_injections)

    started = time.perf_counter()
    ctx = canonical_context()
    pools = build_implementations(ctx)
    suite = run_contract_suite(pools, ctx, agreement=True)
    injections = run_failure_injections(ctx)
    suite["failure_injection"] = injections
    suite["step"] = "canonical"
    suite["wall_seconds"] = time.perf_counter() - started
    suite["exit_ok"] = bool(suite["ok"] and injections["ok"])
    suite["source"] = {"context": ctx.source, "implementations": sorted(pools),
                       "protocol_version": POOL_PROTOCOL_VERSION}
    return suite


def real_context(package_dir: str | Path, *, store_dir: str | Path | None) -> Any:
    """A :class:`~synlab.qc.pool_contract.ProtocolContext` from a real package (+ real store).

    The universe is every fragment the exported table names.  The relation rows are the exported
    rows verbatim.  When a store is given, the same fragments' ``FragmentRecord`` rows (needed by
    ``RelationPool.quality_tier``/``lineage_cluster_of``) are loaded and attached to the gallery
    pool by the caller.
    """
    from synlab.qc.pool_contract import ProtocolContext
    from synlab.storage.export import TrainingPackage

    package = TrainingPackage(package_dir)
    rows = [dict(row) for row in package.relations()]
    endpoints = sorted({str(row.get("query", "")) for row in rows}
                       | {str(row.get("candidate", "")) for row in rows})
    endpoints = [fid for fid in endpoints if fid]
    return ProtocolContext(
        name=f"real::{Path(package_dir).name}",
        lineup=tuple(endpoints),
        rows=tuple(rows),
        source=str(package_dir),
        notes={"package": str(package_dir), "store": str(store_dir or ""),
               "table_rows": len(rows), "fragments": len(endpoints),
               "complete_over_the_universe": False,
               "why_not_complete": ("the exported table is one row per measured pair; a pair the "
                                    "exporter never named is UNKNOWN to this reader and R0 to "
                                    "the gallery -- the agreement block reports that gap")})


def real_step(package_dir: str | Path, *, store_dir: str | Path | None) -> dict[str, Any]:
    from synlab.qc.pool_contract import (POOL_PROTOCOL_VERSION, check_agreement, check_pool,
                                         classify_divergence, eligibility_finding,
                                         exported_pool, gallery_pool, pool_index,
                                         run_failure_injections, training_pool_view)

    started = time.perf_counter()
    ctx = real_context(package_dir, store_dir=store_dir)
    fragments: dict[str, Any] = {}
    store_info: dict[str, Any] = {"used": False}
    if store_dir:
        store_path = Path(store_dir)
        if store_path.exists():
            from synlab.relations.gallery import collect_fragments
            from synlab.storage.store import AssetStore

            store = AssetStore(store_path)
            records = collect_fragments(store, release=None)
            wanted = set(ctx.universe())
            fragments = {fid: rec for fid, rec in records.items() if fid in wanted}
            store_info = {"used": True, "store": str(store_path),
                          "store_fragment_records": len(records),
                          "records_for_this_universe": len(fragments),
                          "universe": len(wanted)}

    pools: dict[str, Any] = {
        "qc.loader_probe.ExportedRelationPool": exported_pool(ctx),
        "training.smoke.TrainingPoolView": training_pool_view(ctx),
        "training.sampler.PoolIndex[exported]": pool_index(ctx, carrier="exported"),
        "relations.gallery.RelationPool": gallery_pool(ctx, fragments=fragments),
        "training.sampler.PoolIndex[gallery]": pool_index(ctx, carrier="gallery"),
    }
    results = {label: check_pool(pool, ctx, label=label) for label, pool in sorted(pools.items())}
    agreement = check_agreement(pools, ctx)
    divergence = classify_divergence(pools, ctx)
    injections = run_failure_injections(ctx, base=pools["relations.gallery.RelationPool"])
    payload: dict[str, Any] = {
        "schema": "synlab.qc.pool_contract.suite.v1",
        "step": "real",
        "protocol_version": POOL_PROTOCOL_VERSION,
        "context": {"name": ctx.name, "source": ctx.source, "universe": len(ctx.universe()),
                    "rows": len(ctx.rows), "notes": dict(ctx.notes),
                    "duplicate_pairs": ctx.duplicate_pairs()},
        "store": store_info,
        "pools": results,
        "safety_ok": all(item["ok"] for item in results.values()),
        "failed_pools": sorted(label for label, item in results.items() if not item["ok"]),
        "agreement": agreement,
        "divergence": divergence,
        "eligibility_finding": eligibility_finding(pools, ctx),
        "failure_injection": injections,
        "implementation_count": len(results),
        "wall_seconds": time.perf_counter() - started,
    }
    payload["ok"] = bool(payload["safety_ok"] and injections["ok"] and divergence["ok"])
    return payload


# --------------------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------------------
def _summary(report: Mapping[str, Any]) -> str:
    lines: list[str] = []
    if report.get("step") == "canonical" or "pools" in report:
        head = f"[{report.get('step', '?')}] protocol {report.get('protocol_version')} " \
               f"context={report.get('context', {}).get('name')} " \
               f"universe={report.get('context', {}).get('universe')} " \
               f"rows={report.get('context', {}).get('rows')}"
        lines.append(head)
        for label, item in sorted((report.get("pools") or {}).items()):
            mark = "PASS" if item["ok"] else "FAIL"
            lines.append(f"  {mark}  {label}  assertions "
                         f"{sum(1 for a in item['assertions'] if a['ok'])}/{len(item['assertions'])}"
                         + (f"  failed={item['failed_assertions']}" if not item["ok"] else ""))
        agree = report.get("agreement") or {}
        if agree:
            lines.append(f"  agreement: {'OK' if agree.get('ok') else 'DIVERGENT'} "
                         f"({agree.get('disagreement_count', 0)} disagreement(s))")
        div = report.get("divergence") or {}
        if div:
            lines.append(f"  divergence: gaps {div.get('conservative_gaps')}, "
                         f"eligibility findings {div.get('eligibility_findings')} "
                         f"({div.get('eligibility_pairs')} pair-direction(s)), "
                         f"kind/mate conflicts {div.get('conflicts')}")
            if div.get("eligibility_findings"):
                lines.append("    FINDING: same kind, different eligibility reading -- see "
                             "divergence.eligibility_examples")
        inj = report.get("failure_injection") or {}
        if inj:
            lines.append(f"  failure injection: caught {inj.get('caught')}/{inj.get('total')}")
            for item in inj.get("injections", []):
                lines.append(f"    {'caught' if item['caught'] else 'MISSED'}  {item['name']}"
                             f" -> {item['expected_assertion']}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--step", default="all", choices=("canonical", "real", "all"))
    parser.add_argument("--package", default=DEFAULT_PACKAGE)
    parser.add_argument("--store", default=DEFAULT_STORE)
    parser.add_argument("--out", default="data/a12_reports/pool_contract.json")
    parser.add_argument("--no-store", action="store_true",
                        help="build the gallery pool without loading real FragmentRecords")
    args = parser.parse_args(argv)

    payload: dict[str, Any] = {"schema": "synlab.a12.pool_contract.run.v1"}
    ok = True
    if args.step in ("canonical", "all"):
        canonical = canonical_step()
        payload["canonical"] = canonical
        ok = bool(ok and canonical["exit_ok"])
    if args.step in ("real", "all"):
        try:
            real = real_step(args.package, store_dir=None if args.no_store else args.store)
        except FileNotFoundError as exc:
            real = {"step": "real", "ok": False, "error": f"{type(exc).__name__}: {exc}"}
        payload["real"] = real
        ok = bool(ok and real.get("ok"))
    payload["ok"] = ok
    payload["status"] = "PASS" if ok else "FAIL"

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True,
                                   default=str), encoding="utf-8")
    for key in ("canonical", "real"):
        if key in payload:
            print(_summary(payload[key]))
    print(f"status={payload['status']} out={out_path}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
