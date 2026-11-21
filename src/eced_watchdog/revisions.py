"""Revision, lifecycle timeline, 2009/7 Circular, and cross-filing diff tracking for e-ÇED filings."""

from __future__ import annotations

import hashlib
import math
import re
from collections import defaultdict
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

# Turkish legal/procedural cues pointing to post-annulment or circular-2009/7 re-submissions
CIRCULAR_2009_7_RE = re.compile(
    r"(?:2009\s*/\s*7|genelge\s*kapsamında\s*yeniden|mahkeme\s*kararı\s*(?:gereğince|sonrası|doğrultusunda)|"
    r"yargı\s*kararı\s*(?:gereğince|sonrası)|iptal\s*kararı\s*sonrası|revize\s*çed|yeniden\s*hazırlanan\s*çed)",
    re.I,
)

CAPACITY_EXPANSION_RE = re.compile(
    r"(?:kapasite\s*artış|ilave\s*ünite|alan\s*genişlet|tevsii|revizyon)",
    re.I,
)

LICENSE_ID_RE = re.compile(
    r"(?:ER\s*[:.]?\s*(\d{5,9})|(\d{4,7})\s*(?:sayılı|nolu|no\.?lu)?\s*ruhsat|ruhsat\s*(?:no|numaralı)\s*[:.]?\s*(\d{4,8}))",
    re.I,
)

STOP_TOKENS = {
    "ve",
    "ile",
    "icin",
    "için",
    "projesi",
    "proje",
    "tesisi",
    "tesisi",
    "tesisleri",
    "faaliyeti",
    "kapasite",
    "artisi",
    "artışı",
    "artisi",
    "ilave",
    "alan",
    "sanayi",
    "ticaret",
    "anonim",
    "limited",
    "sirketi",
    "şirketi",
    "as",
    "aş",
    "ltd",
    "sti",
    "şti",
    "san",
    "tic",
    "ins",
    "inş",
    "enerji",
    "uretim",
    "üretim",
    "santrali",
    "ocagi",
    "ocağı",
    "il",
    "ili",
    "ilcesi",
    "ilçesi",
    "mahallesi",
    "koyu",
    "köyü",
    "mevkii",
    "mevki",
    "parsel",
    "ada",
}

OWNER_CORP_NOISE_RE = re.compile(
    r"\b(?:anonim|limited|şirketi|sirketi|sanayi|ticaret|san|tic|ltd|şti|sti|a\.?ş\.?|a\.?s\.?|"
    r"inşaat|insaat|inş|ins|mühendislik|muhendislik|müh|muh|taahhüt|taahhut|taah|ithalat|ihracat|"
    r"ith|ihr|pazarlama|paz|turizm|tur|yatırım|yatirim|enerji|madencilik|maden|mad|tarım|tarim)\b",
    re.I,
)

TR_CHECK_LABELS = {
    "mentions_field_survey": "Saha / arazi çalışması",
    "mentions_literature_only_cue": "Literatür taraması",
    "mentions_seasonal_sampling": "Mevsimsel örnekleme",
    "mentions_cumulative_impact": "Kümülatif etki",
    "mentions_olive_law_3573": "3573 / zeytinlik",
    "mentions_groundwater_or_aquifer": "Yeraltı suyu / akifer",
    "mentions_iucn_or_endemic": "Endemik / IUCN / Bern",
    "mentions_capacity_or_splitting": "Kapasite artışı / eşik değer",
    "mentions_circular_2009_7_or_revision": "2009/7 / yargı sonrası revizyon",
    "mentions_agency_opinions": "Kurum görüşleri (DSİ / İl Tarım / OGM / MAPEG)",
    "mentions_seismic_or_geotech": "Deprem / fay hattı / jeoteknik stabilite",
}


def normalize_tr(text: str) -> str:
    s = (text or "").replace("İ", "i").replace("I", "ı").lower()
    tr_map = str.maketrans("çğıöşü", "cgiosu")
    s = s.translate(tr_map)
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def normalize_owner(owner: str) -> str:
    base = normalize_tr(OWNER_CORP_NOISE_RE.sub(" ", owner or ""))
    tokens = [t for t in base.split() if len(t) >= 2]
    return " ".join(tokens[:6])


def meaningful_tokens(text: str) -> set[str]:
    return {
        t
        for t in normalize_tr(text).split()
        if len(t) >= 3 and t not in STOP_TOKENS and not t.isdigit()
    }


def extract_license_ids(text: str) -> set[str]:
    out: set[str] = set()
    for m in LICENSE_ID_RE.finditer(text or ""):
        for g in m.groups():
            if g:
                out.add(g)
    return out


def parse_pdf_url_meta(url: str) -> dict[str, str | None]:
    """Parse tempAd, orjinalAd, and yuklemeTarihi from an e-ÇED dosyaGoster.htm URL."""
    if not url:
        return {"temp_ad": None, "original_name": None, "upload_date": None}
    qs = parse_qs(urlparse(url).query)
    return {
        "temp_ad": (qs.get("tempAd") or [None])[0],
        "original_name": (qs.get("orjinalAd") or [None])[0],
        "upload_date": (qs.get("yuklemeTarihi") or [None])[0],
    }


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return round(2 * r * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a))), 1)


def _extract_year(date_str: str | None) -> int | None:
    if not date_str:
        return None
    m = re.search(r"\b(20\d{2}|19\d{2})\b", date_str)
    return int(m.group(1)) if m else None


def make_pdf_snapshot(
    filing: dict[str, Any],
    doc_meta: dict[str, Any],
    pdf_info: dict[str, Any],
    analysis: dict[str, Any],
    *,
    version: int = 1,
    observed_at: str | None = None,
) -> dict[str, Any]:
    """Create a compact, immutable snapshot of one PDF version for courtroom-grade diffing."""
    pdf_url = pdf_info.get("source_url") or (
        doc_meta["pdf_urls"][0]["url"] if doc_meta.get("pdf_urls") else ""
    )
    url_meta = parse_pdf_url_meta(pdf_url)
    geo = analysis.get("geo") or {}
    signal_counts = {
        k: int(v.get("page_count", 0))
        for k, v in (analysis.get("signals") or {}).items()
    }
    return {
        "version": version,
        "observed_at": observed_at or datetime.now().isoformat(timespec="seconds"),
        "decision_type": filing.get("decision_type"),
        "announcement_date": filing.get("announcement_date"),
        "announcement_date_tr": filing.get("announcement_date_tr"),
        "submitted_at": doc_meta.get("submitted_at"),
        "consulting_firm": doc_meta.get("consulting_firm"),
        "source_url": pdf_url,
        "pdf_temp_ad": url_meta["temp_ad"],
        "pdf_original_name": url_meta["original_name"],
        "pdf_upload_date": url_meta["upload_date"],
        "sha256": pdf_info.get("sha256"),
        "bytes": pdf_info.get("bytes"),
        "page_count": analysis.get("page_count"),
        "text_pages": analysis.get("text_pages"),
        "scanned_or_blank_pages": analysis.get("scanned_or_blank_pages"),
        "audit_checks": dict(analysis.get("audit_checks") or {}),
        "signal_page_counts": signal_counts,
        "geo_precision": geo.get("precision"),
        "geo_lat": geo.get("lat"),
        "geo_lon": geo.get("lon"),
        "geo_point_count": geo.get("point_count", 0),
        "detail_text_sha256": hashlib.sha256(
            (filing.get("detail_text") or "").encode("utf-8")
        ).hexdigest()[:16],
    }


def has_pdf_changed(saved: dict[str, Any], incoming_url: str) -> bool:
    """Detect whether the portal now serves a different PDF file than the cached digest."""
    if not incoming_url:
        return False
    prev_url = (saved.get("pdf_info") or {}).get("source_url")
    if not prev_url:
        prev_docs = (saved.get("filing") or {}).get("documents") or []
        if prev_docs and prev_docs[0].get("pdf_urls"):
            prev_url = prev_docs[0]["pdf_urls"][0].get("url")
    if not prev_url or prev_url == incoming_url:
        return False
    prev_m = parse_pdf_url_meta(prev_url)
    curr_m = parse_pdf_url_meta(incoming_url)
    if prev_m["temp_ad"] and curr_m["temp_ad"]:
        if prev_m["temp_ad"] != curr_m["temp_ad"]:
            return True
    if prev_m["upload_date"] and curr_m["upload_date"]:
        if prev_m["upload_date"] != curr_m["upload_date"]:
            return True
    if prev_m["original_name"] and curr_m["original_name"]:
        if prev_m["original_name"] != curr_m["original_name"]:
            return True
    return prev_url != incoming_url


def compute_pdf_revision_diff(
    prev: dict[str, Any],
    curr: dict[str, Any],
) -> dict[str, Any]:
    """Compare two immutable PDF snapshots and highlight substantive technical/legal changes."""
    sha_changed = bool(prev.get("sha256") and curr.get("sha256") and prev["sha256"] != curr["sha256"])
    page_delta = (curr.get("page_count") or 0) - (prev.get("page_count") or 0)
    bytes_delta = (curr.get("bytes") or 0) - (prev.get("bytes") or 0)

    prev_checks = prev.get("audit_checks") or {}
    curr_checks = curr.get("audit_checks") or {}
    check_changes: list[dict[str, Any]] = []
    for k in sorted(set(prev_checks) | set(curr_checks)):
        if k not in prev_checks or k not in curr_checks:
            continue
        if bool(prev_checks[k]) != bool(curr_checks[k]):
            check_changes.append(
                {
                    "key": k,
                    "label": TR_CHECK_LABELS.get(k, k),
                    "from": bool(prev_checks[k]),
                    "to": bool(curr_checks[k]),
                    "direction": "added" if curr_checks[k] else "removed",
                }
            )

    prev_sigs = prev.get("signal_page_counts") or {}
    curr_sigs = curr.get("signal_page_counts") or {}
    signal_deltas: dict[str, int] = {}
    for k in sorted(set(prev_sigs) | set(curr_sigs)):
        delta = int(curr_sigs.get(k, 0)) - int(prev_sigs.get(k, 0))
        if delta != 0:
            signal_deltas[k] = delta

    coord_shift_m: float | None = None
    if (
        prev.get("geo_precision") == "exact_pdf"
        and curr.get("geo_precision") == "exact_pdf"
        and prev.get("geo_lat") is not None
        and curr.get("geo_lat") is not None
    ):
        dist = haversine_meters(
            float(prev["geo_lat"]),
            float(prev["geo_lon"]),
            float(curr["geo_lat"]),
            float(curr["geo_lon"]),
        )
        if dist >= 5.0:
            coord_shift_m = dist

    firm_changed = bool(
        prev.get("consulting_firm")
        and curr.get("consulting_firm")
        and prev["consulting_firm"].strip() != curr["consulting_firm"].strip()
    )

    parts: list[str] = []
    if sha_changed:
        parts.append("PDF dosya özeti (SHA-256) değişti")
    if page_delta != 0:
        sign = "+" if page_delta > 0 else ""
        parts.append(f"sayfa sayısı {sign}{page_delta} ({prev.get('page_count')}→{curr.get('page_count')})")
    if check_changes:
        removed = [c["label"] for c in check_changes if c["direction"] == "removed"]
        added = [c["label"] for c in check_changes if c["direction"] == "added"]
        if removed:
            parts.append(f"çıkarılan ifadeler: {', '.join(removed)}")
        if added:
            parts.append(f"eklenen ifadeler: {', '.join(added)}")
    if coord_shift_m is not None:
        parts.append(f"koordinat merkezi {coord_shift_m:.0f} m kaydı")
    if firm_changed:
        parts.append("danışman firma değişti")
    if not parts:
        parts.append("belge üstverisi veya yükleme bağlantısı güncellendi")

    return {
        "from_version": prev.get("version", 1),
        "to_version": curr.get("version", 2),
        "sha256_changed": sha_changed,
        "from_sha256": (prev.get("sha256") or "")[:16],
        "to_sha256": (curr.get("sha256") or "")[:16],
        "from_upload_date": prev.get("pdf_upload_date") or prev.get("submitted_at"),
        "to_upload_date": curr.get("pdf_upload_date") or curr.get("submitted_at"),
        "from_stage": prev.get("decision_type"),
        "to_stage": curr.get("decision_type"),
        "page_delta": page_delta,
        "bytes_delta": bytes_delta,
        "consulting_firm_changed": firm_changed,
        "from_firm": prev.get("consulting_firm"),
        "to_firm": curr.get("consulting_firm"),
        "audit_check_changes": check_changes,
        "signal_page_deltas": signal_deltas,
        "coordinate_shift_m": coord_shift_m,
        "summary_tr": "; ".join(parts),
    }


def _primary_fid(filing: dict[str, Any]) -> str:
    docs = filing.get("documents") or []
    return str(docs[0].get("filing_id") or "") if docs else ""


def _primary_pdf_meta(filing: dict[str, Any]) -> dict[str, str | None]:
    docs = filing.get("documents") or []
    if docs and docs[0].get("pdf_urls"):
        return parse_pdf_url_meta(docs[0]["pdf_urls"][0].get("url", ""))
    return {"temp_ad": None, "original_name": None, "upload_date": None}


def build_revision_index(
    filings: list[dict[str, Any]],
    digests_map: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build deterministic revision, lifecycle timeline, 2009/7, and cross-filing relation index."""
    digests_map = digests_map or {}

    # 1. Group all announcements by filing_id to form chronological stage timelines
    by_fid_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for f in filings:
        fid = _primary_fid(f)
        if fid:
            by_fid_rows[fid].append(f)

    timelines_by_fid: dict[str, list[dict[str, Any]]] = {}
    for fid, rows in by_fid_rows.items():
        ordered = sorted(
            rows,
            key=lambda x: (
                x.get("announcement_date") or "0000-00-00",
                x.get("decision_type") or "",
            ),
        )
        timelines_by_fid[fid] = [
            {
                "filing_key": r.get("filing_key"),
                "announcement_date": r.get("announcement_date"),
                "announcement_date_tr": r.get("announcement_date_tr"),
                "decision_type": r.get("decision_type"),
                "project_type": r.get("project_type"),
                "submitted_at": (r.get("documents") or [{}])[0].get("submitted_at"),
                "pdf_upload_date": _primary_pdf_meta(r).get("upload_date"),
            }
            for r in ordered
        ]

    # 2. Deduplicate unique filings by filing_id (latest announcement per fid) for cross-filing comparison
    latest_by_fid: dict[str, dict[str, Any]] = {}
    for fid, rows in by_fid_rows.items():
        latest_by_fid[fid] = max(rows, key=lambda x: x.get("announcement_date") or "0000-00-00")

    # Detect related filings across DIFFERENT filing_ids (potential 2009/7 re-filing, post-cancel re-submission, or project splitting)
    related_by_fid: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen_pairs: set[tuple[str, str]] = set()

    # Precompute comparison keys per unique fid
    meta_by_fid: dict[str, dict[str, Any]] = {}
    by_dist: dict[tuple[str, str], list[str]] = defaultdict(list)
    by_license: dict[str, list[str]] = defaultdict(list)

    for fid, f in latest_by_fid.items():
        prov = normalize_tr(f.get("province", ""))
        dist = normalize_tr(f.get("district", ""))
        owner_norm = normalize_owner(f.get("project_owner", ""))
        tokens = meaningful_tokens(f.get("project_name", ""))
        licenses = extract_license_ids(f"{f.get('project_name', '')} {f.get('detail_text', '')}")
        meta_by_fid[fid] = {
            "prov": prov,
            "dist": dist,
            "owner_norm": owner_norm,
            "tokens": tokens,
            "licenses": licenses,
        }
        if prov and dist:
            by_dist[(prov, dist)].append(fid)
        for lic in licenses:
            by_license[lic].append(fid)

    def link_pair(fid_a: str, fid_b: str, reason: str, detail: str) -> None:
        pair = (min(fid_a, fid_b), max(fid_a, fid_b))
        if pair in seen_pairs or fid_a == fid_b:
            return
        seen_pairs.add(pair)
        fa, fb = latest_by_fid[fid_a], latest_by_fid[fid_b]
        related_by_fid[fid_a].append(
            {
                "filing_id": fid_b,
                "reason": reason,
                "detail": detail,
                "project_name": fb.get("project_name"),
                "project_owner": fb.get("project_owner"),
                "decision_type": fb.get("decision_type"),
                "announcement_date_tr": fb.get("announcement_date_tr"),
                "has_digest": fid_b in digests_map,
            }
        )
        related_by_fid[fid_b].append(
            {
                "filing_id": fid_a,
                "reason": reason,
                "detail": detail,
                "project_name": fa.get("project_name"),
                "project_owner": fa.get("project_owner"),
                "decision_type": fa.get("decision_type"),
                "announcement_date_tr": fa.get("announcement_date_tr"),
                "has_digest": fid_a in digests_map,
            }
        )

    # Match 2a: identical mining/quarry license number across different filing IDs
    for lic, fids in by_license.items():
        if len(fids) < 2:
            continue
        for i in range(len(fids)):
            for j in range(i + 1, len(fids)):
                link_pair(fids[i], fids[j], "same_license", f"Aynı ruhsat/ER numarası ({lic})")

    # Match 2b: same province + district -> same owner OR high project-name token overlap
    for (_prov, _dist), fids in by_dist.items():
        if len(fids) < 2:
            continue
        for i in range(len(fids)):
            for j in range(i + 1, len(fids)):
                a, b = fids[i], fids[j]
                ma, mb = meta_by_fid[a], meta_by_fid[b]
                same_owner = bool(ma["owner_norm"] and len(ma["owner_norm"]) >= 5 and ma["owner_norm"] == mb["owner_norm"])
                ta, tb = ma["tokens"], mb["tokens"]
                jaccard = (len(ta & tb) / len(ta | tb)) if (ta and tb) else 0.0
                if same_owner:
                    reason = "same_owner_district"
                    det = (
                        "Aynı ilçe ve proje sahibi (olası proje parçalama veya yeniden başvuru)"
                        if jaccard >= 0.35
                        else "Aynı ilçe ve proje sahibi (kümülatif etki takibi)"
                    )
                    link_pair(a, b, reason, det)
                elif len(ta) >= 3 and len(tb) >= 3 and jaccard >= 0.65:
                    link_pair(
                        a,
                        b,
                        "similar_project_district",
                        f"Aynı ilçede yüksek proje adı benzerliği (%{int(jaccard * 100)})",
                    )

    # Match 2c: exact PDF coordinate proximity (<= 2 km) — catches corporate handovers & re-branded returns
    geo_fids: list[tuple[str, float, float]] = []
    for fid in latest_by_fid:
        geo = ((digests_map.get(fid) or {}).get("analysis") or {}).get("geo") or {}
        if geo.get("precision") == "exact_pdf" and geo.get("lat") is not None and geo.get("lon") is not None:
            geo_fids.append((fid, float(geo["lat"]), float(geo["lon"])))

    for i in range(len(geo_fids)):
        fid_a, lat_a, lon_a = geo_fids[i]
        for j in range(i + 1, len(geo_fids)):
            fid_b, lat_b, lon_b = geo_fids[j]
            # Fast bounding-box pre-filter (~2.5 km) before Haversine
            if abs(lat_a - lat_b) > 0.025 or abs(lon_a - lon_b) > 0.03:
                continue
            dist_m = haversine_meters(lat_a, lon_a, lat_b, lon_b)
            if dist_m <= 2000.0:
                link_pair(
                    fid_a,
                    fid_b,
                    "coordinate_proximity",
                    f"Aynı saha / yakın koordinat ({int(round(dist_m))} m — olası el değiştirme, kümülatif yük veya proje parçalama)",
                )

    # 3. Compute per-filing_id and per-filing_key intelligence
    by_filing_id: dict[str, dict[str, Any]] = {}
    by_filing_key: dict[str, dict[str, Any]] = {}

    summary = {
        "pdf_revisions": 0,
        "circular_2009_7": 0,
        "multi_stage_filings": 0,
        "related_filings": 0,
        "legacy_resurfaced": 0,
        "portal_text_changes": 0,
        "capacity_expansions": 0,
        "audit_alerts_total": 0,
    }

    # Build per-fid summary first
    for fid, rows in by_fid_rows.items():
        saved = digests_map.get(fid) or {}
        rev_hist = list(saved.get("revision_history") or [])
        if not rev_hist and saved.get("pdf_info") and saved.get("analysis"):
            # Synthesize baseline v1 snapshot for existing digests
            s_filing = saved.get("filing") or latest_by_fid[fid]
            s_doc = (s_filing.get("documents") or [{}])[0]
            rev_hist = [
                make_pdf_snapshot(
                    s_filing,
                    s_doc,
                    saved["pdf_info"],
                    saved["analysis"],
                    version=1,
                    observed_at=s_filing.get("first_seen_at") or s_filing.get("announcement_date"),
                )
            ]

        latest_pdf_diff = (
            compute_pdf_revision_diff(rev_hist[-2], rev_hist[-1])
            if len(rev_hist) >= 2
            else None
        )

        # Check all rows for this fid for 2009/7 cues, portal change logs, legacy gap, capacity expansion
        combined_text = " ".join(
            f"{r.get('project_name', '')} {r.get('detail_text', '')}" for r in rows
        )
        analysis_checks = (saved.get("analysis") or {}).get("audit_checks") or {}
        is_2009_7 = bool(
            CIRCULAR_2009_7_RE.search(combined_text)
            or analysis_checks.get("mentions_circular_2009_7_or_revision")
        )
        is_capacity = bool(CAPACITY_EXPANSION_RE.search(combined_text))

        portal_changes: list[dict[str, Any]] = []
        for r in rows:
            for ch in r.get("change_log") or []:
                portal_changes.append(ch)

        timeline = timelines_by_fid.get(fid, [])
        is_multi_stage = len(timeline) >= 2
        related = related_by_fid.get(fid, [])

        # Detect resurfaced legacy filing (submitted_at / upload year >= 1 year older than announcement, or very old ID)
        latest_row = latest_by_fid[fid]
        ann_year = _extract_year(latest_row.get("announcement_date"))
        sub_year = _extract_year((latest_row.get("documents") or [{}])[0].get("submitted_at"))
        legacy_gap_years: int | None = None
        if ann_year and sub_year and (ann_year - sub_year) >= 1:
            legacy_gap_years = ann_year - sub_year
        elif fid.isdigit() and int(fid) < 48000 and ann_year and ann_year >= 2026:
            legacy_gap_years = max(1, ann_year - (sub_year or ann_year - 2))

        flags: list[str] = []
        if len(rev_hist) >= 2:
            flags.append("pdf_changed")
        if is_2009_7:
            flags.append("circular_2009_7")
        if portal_changes:
            flags.append("portal_text_changed")
        if is_multi_stage:
            flags.append("multi_stage")
        if related:
            flags.append("related_filing")
        if legacy_gap_years is not None:
            flags.append("legacy_resurfaced")
        if is_capacity:
            flags.append("capacity_expansion")

        has_audit_alert = any(
            fl in flags
            for fl in (
                "pdf_changed",
                "circular_2009_7",
                "portal_text_changed",
                "multi_stage",
                "related_filing",
                "legacy_resurfaced",
            )
        )

        if "pdf_changed" in flags:
            summary["pdf_revisions"] += 1
        if "circular_2009_7" in flags:
            summary["circular_2009_7"] += 1
        if "portal_text_changed" in flags:
            summary["portal_text_changes"] += 1
        if "multi_stage" in flags:
            summary["multi_stage_filings"] += 1
        if "related_filing" in flags:
            summary["related_filings"] += 1
        if "legacy_resurfaced" in flags:
            summary["legacy_resurfaced"] += 1
        if "capacity_expansion" in flags:
            summary["capacity_expansions"] += 1
        if has_audit_alert:
            summary["audit_alerts_total"] += 1

        fid_entry = {
            "filing_id": fid,
            "flags": flags,
            "has_audit_alert": has_audit_alert,
            "revision_count": len(rev_hist),
            "revision_history": rev_hist,
            "latest_pdf_diff": latest_pdf_diff,
            "timeline": timeline,
            "related_filings": related,
            "portal_change_log": portal_changes,
            "legacy_gap_years": legacy_gap_years,
        }
        by_filing_id[fid] = fid_entry
        for r in rows:
            fk = r.get("filing_key")
            if fk:
                by_filing_key[fk] = fid_entry

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "summary": summary,
        "by_filing_id": by_filing_id,
        "by_filing_key": by_filing_key,
    }
