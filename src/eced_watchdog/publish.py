"""Interactive all-in-one CLI (`eced-publish`): fetch -> preview missing LLM reports + cost -> generate -> build -> commit & push."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import subprocess
import sys
import threading
import xml.etree.ElementTree as ET
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .cli import parse_provinces
from .digest import ensure_digest_for_filing
from .fetcher import _quick_row_signature, fetch_announcements, merge_filings
from .llm import DEFAULT_EK1_MODEL, DEFAULT_EK2_MODEL, choose_gemini_model, resolve_api_key
from .revisions import has_pdf_changed
from .site import build_site

# Approximate USD per 1M tokens (input, output) as of late 2026
MODEL_PRICING_PER_1M: dict[str, tuple[float, float]] = {
    "gemini-3.1-flash-lite": (0.25, 1.50),
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini-3.8-flash": (0.75, 3.75),
    "gemini-4-hydrogen": (1.50, 7.50),
    "gemini-4-neon": (3.00, 15.00),
    "gemini-4-argon": (2.00, 10.00),
    "gemini-4-carbon": (2.00, 10.00),
}

# Typical token footprint for ~24 excerpted PDF pages + structured JSON output (incl. thinking)
EST_INPUT_TOKENS = 22_000
EST_OUTPUT_TOKENS = 2_200


def estimate_filing_cost(model: str) -> float:
    in_rate, out_rate = MODEL_PRICING_PER_1M.get(model, (1.50, 7.50))
    return (EST_INPUT_TOKENS / 1_000_000) * in_rate + (EST_OUTPUT_TOKENS / 1_000_000) * out_rate


def actual_usage_cost(model: str, usage: dict[str, Any] | None) -> float | None:
    if not usage:
        return None
    in_tok = usage.get("prompt_tokens")
    out_tok = usage.get("output_tokens") or 0
    th_tok = usage.get("thoughts_tokens") or 0
    if in_tok is None:
        return None
    in_rate, out_rate = MODEL_PRICING_PER_1M.get(model, (1.50, 7.50))
    return (in_tok / 1_000_000) * in_rate + ((out_tok + th_tok) / 1_000_000) * out_rate


def _urgency_key(f: dict[str, Any]) -> tuple[int, int, int, str]:
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
    is_ek1 = 1 if f.get("project_type") == "Ek-1" else 0
    ann = f.get("announcement_date") or "0000-00-00"
    if hard_days:
        return (3, -min(hard_days), is_ek1, ann)
    if meeting_days:
        return (2, -min(meeting_days), is_ek1, ann)
    if any(c.get("code") in ("hkt", "idk", "process_open") for c in clocks):
        return (1, -999, is_ek1, ann)
    return (0, -9999, is_ek1, ann)


def _urgency_label(f: dict[str, Any]) -> str:
    clocks = f.get("statutory_clocks") or []
    for c in clocks:
        code = c.get("code")
        dr = c.get("days_remaining")
        if code == "iyuk_20a" and dr is not None:
            return f"İYUK {dr:2d}d" if dr >= 0 else "expired "
        if code == "aski_10d" and dr is not None:
            return f"Askı {dr:2d}d" if dr >= 0 else "expired "
        if code in ("hkt", "idk"):
            tag = "HKT" if code == "hkt" else "İDK"
            return f"{tag}  {dr:2d}d" if (dr is not None and dr >= 0) else f"{tag}  -- "
        if code == "process_open":
            return "m.8/16  "
    return "closed  "


def find_missing_llm(
    filings: list[dict[str, Any]],
    digests_dir: Path,
    explicit_model: str | None,
) -> list[dict[str, Any]]:
    """Return unique PDF filings missing an LLM synthesis, ordered by statutory urgency."""
    candidates: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for f in filings:
        docs = f.get("documents") or []
        if not docs or not docs[0].get("pdf_urls"):
            continue
        fid = docs[0].get("filing_id")
        if not fid or fid in seen_ids:
            continue
        seen_ids.add(fid)

        json_path = digests_dir / f"{fid}_analysis.json"
        has_llm = False
        has_pdf_extract = False
        pdf_changed = False
        if json_path.exists():
            has_pdf_extract = True
            try:
                saved = json.loads(json_path.read_text(encoding="utf-8"))
                incoming_url = docs[0]["pdf_urls"][0]["url"]
                pdf_changed = has_pdf_changed(saved, incoming_url)
                has_llm = bool(saved.get("llm_synthesis") and saved["llm_synthesis"].get("result")) and not pdf_changed
            except Exception:
                has_llm = False

        if not has_llm:
            model = choose_gemini_model(f, explicit_model)
            candidates.append(
                {
                    "filing_id": fid,
                    "filing": f,
                    "has_extract": has_pdf_extract,
                    "pdf_changed": pdf_changed,
                    "model": model,
                    "est_cost": estimate_filing_cost(model),
                }
            )

    candidates.sort(key=lambda item: _urgency_key(item["filing"]), reverse=True)
    return candidates


def summarize_slice_cost(items: list[dict[str, Any]]) -> tuple[float, dict[str, int]]:
    total = sum(x["est_cost"] for x in items)
    by_model: dict[str, int] = {}
    for x in items:
        by_model[x["model"]] = by_model.get(x["model"], 0) + 1
    return total, by_model


def format_model_mix(by_model: dict[str, int]) -> str:
    return ", ".join(f"{cnt}× {m}" for m, cnt in sorted(by_model.items()))


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="eced-publish",
        description="Interactive fetch -> cost-estimated Gemini synthesis -> build -> git commit & push",
    )
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Project root directory")
    parser.add_argument("--days", type=int, default=7, help="Lookback window in days (default: 7)")
    parser.add_argument("--provinces", nargs="+", help="Optional CODE:LABEL province filter (default: all 81)")
    parser.add_argument("--skip-fetch", action="store_true", help="Skip live portal fetch; inspect existing data/filings.json")
    parser.add_argument("--check-revisions", action="store_true", help="Re-check document pages on already-cached rows to detect silent PDF edits")
    parser.add_argument("--keep-pdfs", action="store_true", help="Keep downloaded PDFs in data/pdfs/ instead of deleting after digest")
    parser.add_argument("--workers", type=int, default=4, help="Parallel workers for PDF parsing & Gemini synthesis (default: 4; downloads stay capped at 2)")
    parser.add_argument(
        "--gemini-model",
        default=None,
        help=f"Force one Gemini model (default tiered: Ek-1 -> {DEFAULT_EK1_MODEL}, Ek-2 -> {DEFAULT_EK2_MODEL})",
    )
    parser.add_argument(
        "--site-url",
        default="https://yanekyuk.github.io/eced-watchdog/",
        help="Public GitHub Pages base URL for RSS feed",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    cert_path = root / "certs" / "ssl2buy-emea-ov.pem"
    data_dir = root / "data"
    filings_path = data_dir / "filings.json"
    digests_dir = data_dir / "digests"
    pdfs_dir = data_dir / "pdfs"
    docs_dir = root / "docs"

    # 1. Fetch & merge
    existing: list[dict[str, Any]] = []
    if filings_path.exists():
        existing = json.loads(filings_path.read_text(encoding="utf-8")).get("filings", [])

    if not args.skip_fetch:
        print(f"=== [1/4] Fetching e-ÇED announcements (last {args.days} days) ===")
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
                        check_revisions=args.check_revisions,
                    )
                )
            scope_meta = [f"{c}:{l}" for c, l in provinces]
        else:
            incoming = fetch_announcements(
                days=args.days,
                cert_path=cert_path,
                existing_by_sig=existing_by_sig,
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
        print(f"Registry updated: {len(filings)} total filings ({new_count} new).\n")
    else:
        filings, _ = merge_filings(existing, [])
        print(f"=== [1/4] Fetch skipped — loaded {len(filings)} existing filings ===\n")

    # 2. Detect missing LLM reports & estimate cost
    print("=== [2/4] Detecting filings without LLM reports (sorted by statutory urgency) ===")
    missing = find_missing_llm(filings, digests_dir, args.gemini_model)
    ek1_missing = [m for m in missing if m["filing"].get("project_type") == "Ek-1"]
    already_with_llm = len(
        [
            p
            for p in (digests_dir.glob("*_analysis.json") if digests_dir.exists() else [])
            if json.loads(p.read_text(encoding="utf-8")).get("llm_synthesis")
        ]
    )

    print(f"Already have LLM report : {already_with_llm}")
    print(f"Missing LLM report      : {len(missing)} ({len(ek1_missing)} Ek-1, {len(missing) - len(ek1_missing)} Ek-2)")

    selected: list[dict[str, Any]] = []
    gemini_key = resolve_api_key(root)

    if missing:
        if not gemini_key:
            print("\nWARN: GEMINI_API_KEY not found in environment or .env — skipping LLM generation.")
        else:
            print("\nTop pending filings (most urgent deadlines first):")
            for i, item in enumerate(missing[:15], start=1):
                f = item["filing"]
                print(
                    f"  {i:2d}. #{item['filing_id']} | {_urgency_label(f)} | "
                    f"{f['project_type']:4s} | {f['province'][:11]:11s}/{f['district'][:11]:11s} | "
                    f"{item['model']:21s} (~${item['est_cost']:.3f}) | {f['project_name'][:48]}"
                )
            if len(missing) > 15:
                print(f"  ... and {len(missing) - 15} more pending filings.")

            print("\nEstimated cost options (~22k input + ~2.2k output tokens/report):")
            for label, subset in [
                ("Next 5", missing[:5]),
                ("Next 10", missing[:10]),
                ("Next 25", missing[:25]),
                (f"All Ek-1 ({len(ek1_missing)})", ek1_missing),
                (f"All pending ({len(missing)})", missing),
            ]:
                if not subset:
                    continue
                c_usd, mix = summarize_slice_cost(subset)
                print(f"  - {label:18s}: ~${c_usd:6.2f}  ({format_model_mix(mix)})")

            while True:
                try:
                    raw = input(
                        f"\nHow many LLM reports to generate? [0..{len(missing)}, 'ek1', 'all', or Enter=0]: "
                    ).strip().lower()
                except EOFError:
                    raw = "0"
                if raw in ("", "0", "n", "no"):
                    selected = []
                    break
                if raw == "all":
                    selected = list(missing)
                    break
                if raw == "ek1":
                    selected = list(ek1_missing)
                    break
                if raw.isdigit():
                    n = int(raw)
                    if 0 <= n <= len(missing):
                        selected = missing[:n]
                        break
                print(f"Please enter a number 0..{len(missing)}, 'ek1', or 'all'.")

            if selected:
                est_usd, mix = summarize_slice_cost(selected)
                print(f"\nSelected {len(selected)} filings ({format_model_mix(mix)}) — estimated total: ~${est_usd:.2f}")
                try:
                    confirm = input("Proceed with download & Gemini generation? [Y/n]: ").strip().lower()
                except EOFError:
                    confirm = "n"
                if confirm not in ("", "y", "yes", "e", "evet"):
                    print("Cancelled LLM generation.")
                    selected = []

    # 3. Generate selected reports in parallel + rebuild site
    workers = max(1, min(args.workers, len(selected) or 1))
    print(f"\n=== [3/4] Generating digests ({workers} parallel workers, max 2 concurrent downloads) & rebuilding site ===")
    total_actual_usd = 0.0
    total_prompt_tok = 0
    total_out_tok = 0
    generated_ok = 0
    print_lock = threading.Lock()
    done_counter = 0

    def process_one(item: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None, Exception | None]:
        f = item["filing"]
        fid = item["filing_id"]
        with print_lock:
            print(f"  [start] #{fid} ({f['province']}/{f['district']}, {f['project_type']}, {item['model']})...")
        try:
            res = ensure_digest_for_filing(
                f,
                digests_dir=digests_dir,
                pdfs_dir=pdfs_dir,
                cert_path=cert_path,
                keep_pdf=args.keep_pdfs,
                gemini_api_key=gemini_key,
                gemini_model=item["model"],
            )
            return item, res, None
        except Exception as exc:
            return item, None, exc

    if selected:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(process_one, item) for item in selected]
            for fut in as_completed(futures):
                done_counter += 1
                item, res, exc = fut.result()
                f = item["filing"]
                fid = item["filing_id"]
                with print_lock:
                    if exc is not None:
                        print(f"  [{done_counter}/{len(selected)}] WARN #{fid}: {exc}")
                    elif res and res.get("llm_synthesis"):
                        generated_ok += 1
                        llm_s = res["llm_synthesis"]
                        u = llm_s.get("usage") or {}
                        cost = actual_usage_cost(llm_s["model"], u)
                        if cost is not None:
                            total_actual_usd += cost
                        total_prompt_tok += u.get("prompt_tokens") or 0
                        total_out_tok += (u.get("output_tokens") or 0) + (u.get("thoughts_tokens") or 0)
                        geo_p = (res["analysis"].get("geo") or {}).get("precision", "?")
                        n_flags = len(llm_s["result"].get("red_flags") or [])
                        cost_str = f"${cost:.4f}" if cost is not None else f"~${item['est_cost']:.3f}"
                        print(
                            f"  [{done_counter}/{len(selected)}] OK #{fid} ({f['province']}/{f['district']}): "
                            f"{res['analysis']['page_count']}p, geo={geo_p}, "
                            f"{llm_s['model']} -> {n_flags} findings ({cost_str})"
                        )

    # Refresh countdowns on already-digested markdown files without calling LLM
    if digests_dir.exists():
        existing_ids = {p.name.replace("_analysis.json", "") for p in digests_dir.glob("*_analysis.json")}
        refreshed: set[str] = set()
        for f in filings:
            docs = f.get("documents") or []
            fid = docs[0].get("filing_id") if docs else None
            if fid and fid in existing_ids and fid not in refreshed:
                refreshed.add(fid)
                try:
                    ensure_digest_for_filing(
                        f,
                        digests_dir=digests_dir,
                        pdfs_dir=pdfs_dir,
                        cert_path=cert_path,
                        keep_pdf=args.keep_pdfs,
                        gemini_api_key=None,
                    )
                except Exception:
                    pass

    stats = build_site(
        filings,
        digests_dir=digests_dir,
        docs_dir=docs_dir,
        site_url=args.site_url,
        revisions_out=data_dir / "revisions.json",
    )
    # Validate RSS XML before offering to commit/push
    rss_tree = ET.parse(docs_dir / "feed.xml")
    rss_items = len(rss_tree.findall("./channel/item"))

    print(
        f"\nBuilt site: {stats['total']} filings ({stats['provinces']} provinces, "
        f"{stats['active']} active, {stats['digests_rendered']} digests, "
        f"{stats['exact_geo']} exact-coord, {stats['audit_alerts']} revision/lifecycle alerts, {rss_items} RSS items)."
    )
    if generated_ok:
        print(
            f"Generated {generated_ok}/{len(selected)} LLM reports "
            f"(tokens: {total_prompt_tok:,} in / {total_out_tok:,} out+think; est. actual cost: ${total_actual_usd:.4f})."
        )

    # 4. Git commit & push
    print("\n=== [4/4] Git commit & push ===")
    st = subprocess.run(
        ["git", "status", "--short", "data/", "docs/"],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    )
    changed_lines = [ln for ln in st.stdout.splitlines() if ln.strip()]
    if not changed_lines:
        print("No changes in data/ or docs/ to commit.")
        return

    print(f"Pending changes ({len(changed_lines)} files):")
    for ln in changed_lines[:20]:
        print(f"  {ln}")
    if len(changed_lines) > 20:
        print(f"  ... and {len(changed_lines) - 20} more files.")

    default_msg = (
        f"chore(watch): {date.today().isoformat()} update "
        f"({stats['total']} filings, {stats['digests_rendered']} digests)"
    )
    try:
        ans = input(f"\nCommit and push to origin/main with message:\n  \"{default_msg}\"\nProceed? [Y/n]: ").strip().lower()
    except EOFError:
        ans = "n"

    if ans not in ("", "y", "yes", "e", "evet"):
        print("Skipped git commit & push. Changes remain on disk.")
        return

    subprocess.run(["git", "add", "data/", "docs/"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-m", default_msg], cwd=root, check=True)
    subprocess.run(["git", "push"], cwd=root, check=True)
    print(f"\nPublished! Live site will update shortly at: {args.site_url}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
