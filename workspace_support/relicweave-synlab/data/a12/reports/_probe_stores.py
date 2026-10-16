"""Read-only survey of every store on disk: roles, qa counts, semantics markers.

Writes JSON to stdout-redirect target. Opens sqlite with mode=ro so nothing is written.
"""
from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def find_stores() -> list[Path]:
    out = []
    for db in sorted(ROOT.glob("data/**/*.sqlite")):
        if db.parent.name.startswith("_"):
            continue
        out.append(db)
    return out


def survey(db: Path) -> dict:
    info: dict = {"db": str(db.relative_to(ROOT)).replace("\\", "/"), "root": str(db.parent.relative_to(ROOT)).replace("\\", "/")}
    try:
        conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
    except Exception as exc:  # noqa: BLE001
        info["error"] = f"open: {exc}"
        return info
    try:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        info["tables"] = tables
        if "assets" not in tables:
            return info
        info["asset_count"] = conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
        info["role_counts"] = dict(Counter(r[0] for r in conn.execute("SELECT role FROM assets")))
        info["qa_counts"] = dict(Counter(r[0] for r in conn.execute("SELECT qa_status FROM assets")))
        if "runs" in tables:
            info["run_count"] = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        if "releases" in tables:
            info["release_count"] = conn.execute("SELECT COUNT(*) FROM releases").fetchone()[0]
            info["releases"] = [dict(r) for r in conn.execute("SELECT release_id, scope, profile, meta_json FROM releases")]
        # semantics marker histogram: per role
        hist: dict[str, Counter] = {}
        for role, meta_json in conn.execute("SELECT role, meta_json FROM assets"):
            try:
                meta = json.loads(meta_json or "{}")
            except Exception:  # noqa: BLE001
                hist.setdefault(role, Counter())["<unparsable>"] += 1
                continue
            inner = meta.get("meta") if isinstance(meta.get("meta"), dict) else {}
            ds = meta.get("data_semantics") or inner.get("data_semantics") or {}
            key = (
                f"mask={ds.get('mask_semantics')}|dmg={ds.get('damage_semantics')}"
                if ds else
                f"dmg={meta.get('damage_semantics')}" if meta.get("damage_semantics") else
                "none"
            )
            hist.setdefault(role, Counter())[key] += 1
        info["semantics_by_role"] = {k: dict(v) for k, v in sorted(hist.items())}
    finally:
        conn.close()
    return info


def main() -> None:
    result = [survey(db) for db in find_stores()]
    text = json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True)
    out = Path(__file__).with_name("_probe_stores.json")
    out.write_text(text, encoding="utf-8")
    print(f"wrote {out} ({len(text)} chars)")


if __name__ == "__main__":
    main()
