"""Unified CLI (`eced-watch`) for Türkiye-wide e-ÇED polling, PDF digesting, and static site/map/RSS builds."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from .digest import ensure_digest_for_filing
from .fetcher import (
    _quick_row_signature,
    fetch_announcements,
    merge_filings,
)
from .gis import enrich_digests_gis, load_gis_cache
from .llm import DEFAULT_EK1_MODEL, DEFAULT_EK2_MODEL, resolve_api_key
from .site import build_site


def parse_provinces(raw: list[str] | None) -> list[tuple[str, str]]:
    if not raw:
        return []
    out: list[tuple[str, str]] = []
    for item in raw:
        code, label = item.split(":", 1)
        out.append((code.strip(), label.strip()))
    return out


def select_digest_candidates(
    filings: list[dict[str, Any]],
    digests_dir: Path,
    max_new: int,
) -> list[dict[str, Any]]:
    """Refresh existing digests and prioritize new Ek-1 + active-clock + newest filings."""
    existing_ids = (
        {p.name.replace("_analysis.json", "") for p in digests_dir.glob("*_analysis.json")}
        if digests_dir.exists()
        else set()
    )

    already: list[dict[str, Any]] = []
    fresh: list[tuple[tuple[int, int, int, str], dict[str, Any]]] = []
    seen_ids: set[str] = set()

    for f in filings:
        docs = f.get("documents") or []
        if not docs or not docs[0].get("pdf_urls"):
            continue
        fid = docs[0].get("filing_id")
        if not fid or fid in seen_ids:
            continue
        seen_ids.add(fid)

        if fid in existing_ids:
            already.append(f)
            continue

        clocks = f.get("statutory_clocks") or []
        hard_days = [
            c["days_remaining"]
            for c in clocks
            if c.get("code") in ("iyuk_20a", "aski_10d")
            and c.get("days_remaining") is not None
            and c["days_remaining"] >= 0
        ]
        meeting_days = [
            c["days_remaining"]
            for c in clocks
            if c.get("code") in ("hkt", "idk")
            and c.get("days_remaining") is not None
            and c["days_remaining"] >= 0
        ]

        if hard_days:
            urgency_tier = 3
            neg_days_left = -min(hard_days)
        elif meeting_days:
            urgency_tier = 2
            neg_days_left = -min(meeting_days)
        elif any(c.get("code") in ("hkt", "idk", "process_open") for c in clocks):
            urgency_tier = 1
            neg_days_left = -999
        else:
            urgency_tier = 0
            neg_days_left = -9999

        is_ek1 = 1 if f.get("project_type") == "Ek-1" else 0
        ann = f.get("announcement_date") or "0000-00-00"
        fresh.append(((urgency_tier, is_ek1, neg_days_left, ann), f))

    fresh.sort(key=lambda x: x[0], reverse=True)
    return already + [f for _, f in fresh[:max_new]]


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="eced-watch",
        description="Türkiye e-ÇED İzleme Platformu — artımlı tarama, PDF ön özet ve statik site/harita üreticisi",
    )
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Project root directory")
    parser.add_argument("--days", type=int, default=7, help="Lookback window in days (default: 7 nationwide)")
    parser.add_argument(
        "--provinces",
        nargs="+",
        help="Optional province filter as CODE:LABEL (omit for all 81 provinces / Türkiye geneli)",
    )
    parser.add_argument(
        "--max-records",
        type=int,
        default=None,
        help="Optional cap on records fetched per query",
    )
    parser.add_argument(
        "--max-digests",
        type=int,
        default=5,
        help="Max new PDFs to download and digest per run",
    )
    parser.add_argument("--workers", type=int, default=4, help="Parallel workers for PDF parsing & Gemini synthesis (default: 4)")
    parser.add_argument("--skip-fetch", action="store_true", help="Rebuild site/digests from existing data/filings.json")
    parser.add_argument("--check-revisions", action="store_true", help="Re-check document pages on already-cached rows to detect silent PDF/metadata edits")
    parser.add_argument("--skip-digests", action="store_true", help="Skip downloading/digesting new PDFs")
    parser.add_argument("--skip-llm", action="store_true", help="Disable Gemini API synthesis even if GEMINI_API_KEY is set")
    parser.add_argument("--re-synthesize", action="store_true", help="Re-run Gemini synthesis even on already-synthesized digests")
    parser.add_argument(
        "--gemini-model",
        default=None,
        help=f"Override Gemini model ID (default: Ek-1 -> {DEFAULT_EK1_MODEL}, Ek-2 -> {DEFAULT_EK2_MODEL})",
    )
    parser.add_argument("--drop-pdfs", action="store_true", help="Delete downloaded PDFs after digesting")
    parser.add_argument("--enrich-gis", action="store_true", help="Query OpenStreetMap/Overpass (3 km) for exact-coord filings not yet in data/gis_cache.json")
    parser.add_argument("--max-gis", type=int, default=15, help="Max new Overpass GIS queries per run when --enrich-gis is enabled (default: 15)")
    parser.add_argument(
        "--site-url",
        default="https://yanekyuk.github.io/eced-watchdog/",
        help="Public GitHub Pages base URL for RSS feed links",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    cert_path = root / "certs" / "ssl2buy-emea-ov.pem"
    data_dir = root / "data"
    filings_path = data_dir / "filings.json"
    digests_dir = data_dir / "digests"
    pdfs_dir = data_dir / "pdfs"
    docs_dir = root / "docs"

    existing: list[dict[str, Any]] = []
    if filings_path.exists():
        loaded = json.loads(filings_path.read_text(encoding="utf-8"))
        existing = loaded.get("filings", [])

    new_count = 0
    if not args.skip_fetch:
        existing_by_sig = {_quick_row_signature(f): f for f in existing}
        provinces = parse_provinces(args.provinces)
        incoming: list[dict[str, Any]] = []
        if provinces:
            for code, label in provinces:
                incoming.extend(
                    fetch_announcements(
                        province_code=code,
                        province_label=label,
                        days=args.days,
                        cert_path=cert_path,
                        existing_by_sig=existing_by_sig,
                        max_records=args.max_records,
                        check_revisions=args.check_revisions,
                    )
                )
            scope_meta = [f"{c}:{l}" for c, l in provinces]
        else:
            incoming = fetch_announcements(
                days=args.days,
                cert_path=cert_path,
                existing_by_sig=existing_by_sig,
                max_records=args.max_records,
                check_revisions=args.check_revisions,
            )
            scope_meta = ["ALL:TÜRKİYE"]

        filings, new_count = merge_filings(existing, incoming)
        data_dir.mkdir(parents=True, exist_ok=True)
        filings_path.write_text(
            json.dumps(
                {
                    "updated_at": datetime.now().isoformat(timespec="seconds"),
                    "scope": scope_meta,
                    "count": len(filings),
                    "filings": filings,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"Merged registry: {len(filings)} total filings ({new_count} new) -> {filings_path}")
    else:
        filings, _ = merge_filings(existing, [])
        print(f"Loaded {len(filings)} existing filings (fetch skipped)")

    if not args.skip_digests:
        gemini_key = None if args.skip_llm else resolve_api_key(root)
        if not args.skip_llm and not gemini_key:
            print("Gemini synthesis skipped (set GEMINI_API_KEY in environment or .env to enable)")
        candidates = select_digest_candidates(filings, digests_dir, args.max_digests)
        digested_new = 0
        synthesized_new = 0
        print_lock = threading.Lock()

        def run_one(f: dict[str, Any]) -> tuple[dict[str, Any], str, dict[str, Any] | None, Exception | None]:
            fid = f["documents"][0]["filing_id"]
            try:
                res = ensure_digest_for_filing(
                    f,
                    digests_dir=digests_dir,
                    pdfs_dir=pdfs_dir,
                    cert_path=cert_path,
                    keep_pdf=not args.drop_pdfs,
                    gemini_api_key=gemini_key,
                    gemini_model=args.gemini_model,
                    re_synthesize=args.re_synthesize,
                )
                return f, fid, res, None
            except Exception as exc:
                return f, fid, None, exc

        workers = max(1, min(args.workers, len(candidates) or 1))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for fut in as_completed([pool.submit(run_one, f) for f in candidates]):
                f, fid, res, exc = fut.result()
                with print_lock:
                    if exc is not None:
                        print(f"  WARN: failed to digest #{fid}: {exc}")
                        continue
                    if res and res.get("pdf_revised_now"):
                        diff_s = (res.get("latest_pdf_diff") or {}).get("summary_tr", "")
                        print(f"  REVISED PDF #{fid} ({f['province']}/{f['district']}): {diff_s}")
                    elif res and not res["cached"]:
                        digested_new += 1
                        geo = res["analysis"].get("geo") or {}
                        print(
                            f"  Digested NEW #{fid} ({f['province']}/{f['district']}): "
                            f"{res['analysis']['page_count']}p "
                            f"({res['pdf_info']['bytes'] / 1024 / 1024:.1f} MB, geo={geo.get('precision')})"
                        )
                    if res and res.get("synthesized_now"):
                        synthesized_new += 1
                        llm_m = res["llm_synthesis"]["model"]
                        n_flags = len(res["llm_synthesis"]["result"].get("red_flags") or [])
                        print(f"  Synthesized #{fid} via {llm_m} ({n_flags} findings)")
        print(f"Digests ready ({digested_new} newly extracted, {synthesized_new} newly synthesized)")

    gis_cache_path = data_dir / "gis_cache.json"
    if args.enrich_gis:
        gis_cache, gis_new, gis_fail = enrich_digests_gis(
            digests_dir,
            gis_cache_path,
            max_new=args.max_gis,
        )
        print(f"GIS 3 km verification: {len(gis_cache)} cached ({gis_new} newly queried, {gis_fail} failed)")
    else:
        gis_cache = load_gis_cache(gis_cache_path)

    stats = build_site(
        filings,
        digests_dir=digests_dir,
        docs_dir=docs_dir,
        site_url=args.site_url,
        revisions_out=data_dir / "revisions.json",
        gis_cache=gis_cache,
    )
    print(
        f"Built site: {stats['total']} filings ({stats['provinces']} provinces, "
        f"{stats['active']} active, {stats['digests_rendered']} digests, "
        f"{stats['exact_geo']} exact-coord, {stats['audit_alerts']} revision/lifecycle alerts, "
        f"{stats['gis_verified']} GIS-verified) -> {stats['index_path']}"
    )


if __name__ == "__main__":
    main()
