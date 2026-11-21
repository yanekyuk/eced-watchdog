# Türkiye e-ÇED İzleme Platformu

Open-source, low-maintenance watcher, interactive **81-province** Türkiye map, statutory deadline monitor, **PDF revision & Circular 2009/7 diff tracker**, and page-cited ecological pre-digest pipeline for Turkey's public Environmental Impact Assessment (*ÇED*) portal (`https://eced-duyuru.csb.gov.tr/eced-prod/duyurular.xhtml`).

> **Scope:** Polls **all 81 provinces of Türkiye** by default (zero regional lock-in). You can optionally filter to specific provinces via `--provinces CODE:LABEL`.

---

## Why Revision & 2009/7 Diff Tracking Exists

In Turkey's EIA practice, outright Ministry rejections (*ÇED Olumsuz*) are vanishingly rare, and even after an administrative court annuls a *ÇED Olumlu* decision, projects routinely return under **Circular 2009/7 (*2009/7 Sayılı Genelge*)** with patched sections—or re-enter under a new filing ID or split capacity thresholds (*proje parçalama*).

`eced-watchdog` turns silent edits and re-submissions into verifiable, courtroom-ready evidence:

1. **Cryptographic PDF Snapshots (`v1`, `v2`, …):** Every digested PDF is fingerprinted with **SHA-256**, file size, upload timestamp (`yuklemeTarihi` / `tempAd`), page count, extracted UTM/WGS84 coordinates, and deterministic audit checks.
2. **Automatic `v1 → v2` Revision Diffs:** When the portal serves a new PDF URL or file hash for a tracked filing ID, the previous snapshot is archived in `revision_history` (never overwritten) and `compute_pdf_revision_diff()` records exact page deltas, consulting-firm switches, coordinate shifts (in meters), and deleted/added legal-ecological terms (e.g., `3573 / zeytinlik: VAR → YOK`), passing the diff into Gemini re-synthesis as well.
3. **Portal Metadata Change Log:** Re-checking existing rows (`--check-revisions`) records any silent edits to announcement text, upload timestamps, consulting firm, or PDF links in `change_log`.
4. **Cross-Filing Lifecycle & Relation Graph (`data/revisions.json`):** Links multi-stage announcements for the same `filing_id` into chronological timelines, flags `2009/7` / post-annulment cues, surfaces reactivated legacy filing IDs, and links different `filing_id`s in the same district sharing the same owner, mining license (`ER:`/`ruhsat`), or high project-name similarity.

---

## End-to-End Architecture & Data Flow

```text
eced-duyuru.csb.gov.tr (JSF / PrimeFaces Portal — All 81 Provinces)
   │  [1] fetcher.py — Pure HTTP/1.1 + ViewState poller (Turkish IP, strict TLS, change_log)
   ▼
data/filings.json (Canonical registry + İYUK m. 20/A 30d, m. 14 10d askı, HKT/İDK clocks)
   │  [2] digest.py + geo.py — PyMuPDF page-cited scan + UTM/ED50/WGS84 coordinate extraction
   │  [3] revisions.py — Immutable SHA-256 snapshots, v1->v2 diffs, 2009/7 & lifecycle graph
   │  [4] llm.py — Optional tiered Gemini API synthesis aligned to Danıştay's 7 annulment grounds
   ▼
data/digests/<id>_analysis.json + <id>_digest.md + data/revisions.json
   │  [5] site.py — Clean Turkish web UI (light/dark, print-ready digests), Leaflet map, rehber.html, RSS 2.0
   ▼
docs/ (index.html, rehber.html, feed.xml, digests/*.html + *.md)
   │  [6] git push -> .github/workflows/deploy-pages.yml (XML/HTML check + GitHub Pages deploy)
   ▼
Live Public Website & RSS 2.0 Feed
```

---

## Sorting, Filtering & Prioritization

Both the **public dashboard** (`docs/index.html`) and the **automated digest queue** prioritize **statutory urgency** so strict court deadlines never get buried under routine filings:

1. **Active hard statutory clocks (ascending by days remaining):** Filings with `0`, `1`, `2`, … days left on their 30-day **İYUK Madde 20/A** lawsuit clock or 10-day **Madde 14** *askı* window appear first.
2. **Scheduled upcoming HKT / İDK meetings** (parsed directly from official text).
3. **Open pre-decision review notices** (*ÇED Süreci Başlayan*, m. 8/16).
4. **Expired or cancelled/returned records** (*İptal/İade*) at the bottom.

On the website, users can combine full-text search, an 81-province dropdown (with counts), a legal-stage filter (`İYUK 20/A`, `Madde 14 Askı`, `HKT/İDK`, `Karar Öncesi`, `İptal/İade`), a **Revizyon / Süreç / İlişkili** filter pill, a synced Leaflet map, and light/dark themes. Every digest page (`docs/digests/<id>.html`) includes a **Belge Bütünlüğü, Revizyon ve Süreç Geçmişi** panel, one-click question copying, and clean print-to-PDF styling.

---

## Step-by-Step: Local Setup & Publishing

### 1. Install Dependencies

Requires Python 3.12+ and [`uv`](https://docs.astral.sh/uv/):

```bash
uv sync
```

### 2. Configure the Gemini API Key (Optional LLM Layer)

Without an API key, `eced-watch` runs 100% deterministically (PyMuPDF page-cited extraction, statutory clocks, coordinate extraction, SHA-256 revision diffs, maps, and RSS).

To enable **schema-constrained Gemini synthesis** aligned to Danıştay's 7 annulment grounds (plus `v1 → v2` revision audits), create a gitignored `.env` file:

```bash
cat > .env <<'EOF'
GEMINI_API_KEY=your_gemini_api_key_here
# Optional: override automatic Ek-1 / Ek-2 tiering
# GEMINI_MODEL=gemini-4-hydrogen
EOF
chmod 600 .env
```

- **Ek-1** (full ÇED reports) → `gemini-4-hydrogen`
- **Ek-2** (PTD files) → `gemini-3.5-flash-lite`
- Cached in `data/digests/<id>_analysis.json` so unchanged filings are never re-billed unless `--re-synthesize` is passed or a **new PDF revision** is detected on the portal.

### 3. Run the Pipeline

#### Interactive All-in-One Publish Flow (`eced-publish`)
```bash
# Fetch all 81 provinces, check cost estimates for pending/revised PDFs, generate, build & push
uv run eced-publish

# Also re-verify document pages of already-cached filings for silent PDF swaps
uv run eced-publish --check-revisions

# Rebuild/synthesize from existing data/filings.json without live portal polling
uv run eced-publish --skip-fetch
```

#### Scriptable / Headless CLI (`eced-watch`)
```bash
# Standard nationwide run (last 7 days across all 81 provinces, up to 5 new PDFs)
uv run eced-watch --days 7 --max-digests 5 --drop-pdfs

# Nationwide run + active silent-revision check on existing rows
uv run eced-watch --days 14 --check-revisions --max-digests 10 --drop-pdfs

# Rebuild static site, revision index, maps & RSS offline from data/
uv run eced-watch --skip-fetch --skip-digests

# Deterministic-only run (no Gemini API calls)
uv run eced-watch --days 7 --max-digests 5 --skip-llm

# Optional: poll specific provinces only (Turkish plate codes)
uv run eced-watch --provinces 35:İZMİR 45:MANİSA 34:İSTANBUL --days 14
```

### 4. Run Unit Tests

```bash
uv run python -m unittest discover -s tests -v
```

---

## Daily Automated Scheduling (Turkish IP Requirement)

`eced-duyuru.csb.gov.tr` drops TCP connections from foreign datacenter IP ranges (such as GitHub Actions' US runners), so portal polling runs from a **Turkish IP** (a local Linux machine or Turkish VPS), while GitHub Actions deploys `docs/` on every push:

```bash
chmod +x scripts/install-systemd-timer.sh
./scripts/install-systemd-timer.sh

systemctl --user list-timers
journalctl --user -u eced-watchdog.service -n 50 --no-pager
```

---

## CLI Options Reference

| Flag | Default | Purpose |
|---|---|---|
| `--days N` | `7` | Lookback window in days |
| `--provinces CODE:LABEL ...` | *(all 81)* | Optional province restriction (omit for nationwide Türkiye) |
| `--check-revisions` | `false` | Re-check portal document pages on already-cached rows to detect silent PDF/metadata edits |
| `--max-digests N` | `5` | Max newly downloaded & synthesized PDFs per run |
| `--workers N` | `4` | Parallel workers for PDF parsing & Gemini synthesis (portal downloads stay capped at 2 concurrent) |
| `--drop-pdfs` | `false` | Delete raw PDFs after extraction/synthesis |
| `--skip-fetch` | `false` | Skip portal polling; use existing `data/filings.json` |
| `--skip-digests` | `false` | Skip PDF extraction & LLM synthesis; rebuild `docs/` and `data/revisions.json` only |
| `--skip-llm` | `false` | Run deterministic PyMuPDF extraction without Gemini |
| `--re-synthesize` | `false` | Force fresh Gemini synthesis on already-digested PDFs |
| `--gemini-model ID` | *tiered* | Override default `Ek-1` / `Ek-2` model selection |
| `--site-url URL` | GitHub Pages URL | Base URL written into `docs/feed.xml` |

> **Disclaimer:** Informational transparency aid generated from official public Ministry announcements. Under Article 20/A of Turkey's Administrative Procedure Law (İYUK), annulment lawsuits against ÇED decisions carry a 30-day statutory clock that is **not** tolled by İYUK Article 11 administrative applications. Always verify deadlines and legal standing with qualified counsel.
