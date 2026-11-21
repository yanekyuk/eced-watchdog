"""Polite pure-HTTP/1.1 JSF/PrimeFaces fetcher for Turkey's public e-ÇED registry (nationwide or per-province)."""

from __future__ import annotations

import hashlib
import re
import ssl
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import certifi
import httpx
from bs4 import BeautifulSoup

BASE_URL = "https://eced-duyuru.csb.gov.tr/eced-prod/duyurular.xhtml"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
AJAX_HEADERS = {
    "Faces-Request": "partial/ajax",
    "X-Requested-With": "XMLHttpRequest",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
}


def build_ssl_context(cert_path: Path | None) -> ssl.SSLContext:
    ctx = ssl.create_default_context(cafile=certifi.where())
    if cert_path and cert_path.exists():
        ctx.load_verify_locations(str(cert_path))
    return ctx


def normalize_tr_upper(text: str) -> str:
    return text.replace("i", "İ").replace("ı", "I").upper().strip()


def _extract_meeting_date(detail_text: str, ann_date: date) -> date | None:
    """Extract an upcoming HKT / İDK meeting date from official announcement text."""
    if not detail_text:
        return None
    # Match DD/MM/YYYY or DD.MM.YYYY
    candidates: list[date] = []
    for m in re.finditer(r"\b(\d{2})[./](\d{2})[./](\d{4})\b", detail_text):
        day_s, mon_s, yr_s = m.group(1), m.group(2), m.group(3)
        try:
            d = date(int(yr_s), int(mon_s), int(day_s))
        except ValueError:
            continue
        # Ignore regulation publication dates (e.g., 29.07.2022) or distant historical dates
        if ann_date <= d <= ann_date + timedelta(days=180):
            candidates.append(d)
    if not candidates:
        return None
    # Prefer the earliest date on/after announcement date (the scheduled meeting date)
    return min(candidates)


def compute_deadlines(
    decision_type: str,
    date_str: str,
    today: date,
    detail_text: str = "",
) -> dict[str, Any]:
    """Compute legally accurate statutory clocks under ÇED Regulation (31907 RG + 2025/2026) & İYUK m. 20/A."""
    try:
        ann_date = datetime.strptime(date_str, "%d.%m.%Y").date()
    except ValueError:
        return {"announcement_date": None, "statutory_clocks": []}

    clocks: list[dict[str, Any]] = []
    dt_lower = decision_type.lower()

    # 1. Final administrative decisions: 30-day hard İYUK m. 20/A annulment clock (İYUK m. 11 does not toll)
    if "gerekli değil" in dt_lower or "çed olumlu" in dt_lower or "çed olumsuz" in dt_lower:
        cutoff = ann_date + timedelta(days=30)
        clocks.append(
            {
                "code": "iyuk_20a",
                "kind": "İYUK Madde 20/A iptal davası süresi (30 takvim günü; İYUK 11 süreyi durdurmaz)",
                "deadline": cutoff.isoformat(),
                "days_remaining": (cutoff - today).days,
            }
        )
    # 2. Final Ek-1 ÇED Report (Madde 14): 10-calendar-day public review / comment window
    elif "nihai" in dt_lower or "görüş" in dt_lower:
        cutoff = ann_date + timedelta(days=10)
        clocks.append(
            {
                "code": "aski_10d",
                "kind": "ÇED Yönetmeliği Madde 14 kapsamındaki 10 takvim günlük nihai askı ve görüş süresi",
                "deadline": cutoff.isoformat(),
                "days_remaining": (cutoff - today).days,
            }
        )
    # 3. HKT (Madde 9): extract exact meeting date from announcement text when available
    elif "hkt" in dt_lower or "halkın katılım" in dt_lower:
        m_date = _extract_meeting_date(detail_text, ann_date)
        clocks.append(
            {
                "code": "hkt",
                "kind": "Halkın Katılımı Toplantısı (HKT — ÇED Yönetmeliği m. 9)",
                "deadline": m_date.isoformat() if m_date else None,
                "days_remaining": (m_date - today).days if m_date else None,
            }
        )
    # 4. İDK (Madde 11-12): extract exact commission review date from announcement text when available
    elif "idk" in dt_lower or "İdk" in decision_type:
        m_date = _extract_meeting_date(detail_text, ann_date)
        clocks.append(
            {
                "code": "idk",
                "kind": "İnceleme Değerlendirme Komisyonu (İDK — ÇED Yönetmeliği m. 11–12)",
                "deadline": m_date.isoformat() if m_date else None,
                "days_remaining": (m_date - today).days if m_date else None,
            }
        )
    # 5. Process initiation (Madde 8 / Madde 16): early-warning open review stage (no 10-day expiration)
    elif "başlayan" in dt_lower:
        clocks.append(
            {
                "code": "process_open",
                "kind": "Karar öncesi inceleme süreci (ÇED Yönetmeliği m. 8/16; süreç boyunca yazılı görüş verilebilir)",
                "deadline": None,
                "days_remaining": None,
            }
        )

    return {
        "announcement_date": ann_date.isoformat(),
        "statutory_clocks": clocks,
    }


def make_filing_key(row: dict[str, Any]) -> str:
    docs = row.get("documents") or []
    filing_id = docs[0].get("filing_id") if docs else None
    if filing_id:
        return f"{filing_id}:{row.get('announcement_date_tr', '')}:{row.get('decision_type', '')}"
    raw = "|".join(
        [
            row.get("province", ""),
            row.get("district", ""),
            row.get("announcement_date_tr", ""),
            row.get("decision_type", ""),
            row.get("project_name", ""),
        ]
    )
    return "hash_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _extract_viewstate(xml_text: str) -> str | None:
    m = re.search(
        r'<update id="[^"]*javax\.faces\.ViewState[^"]*"><!\[CDATA\[(.*?)\]\]></update>',
        xml_text,
        re.S,
    )
    return m.group(1) if m else None


def _extract_update_cdata(xml_text: str, update_id: str) -> str | None:
    pattern = r'<update id="' + re.escape(update_id) + r'"><!\[CDATA\[(.*?)\]\]></update>'
    m = re.search(pattern, xml_text, re.S)
    return m.group(1) if m else None


def _parse_table_rows(html_fragment: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html_fragment, "lxml")
    tbody = soup.find("tbody", id="form:duyurTable_data")
    rows_el = (tbody or soup).find_all("tr", attrs={"data-ri": True})

    records: list[dict[str, Any]] = []
    for tr in rows_el:
        ri = int(tr["data-ri"])
        tds = tr.find_all("td")
        if len(tds) < 9:
            continue
        btn = tr.find("button", id=re.compile(r"form:duyurTable:\d+:j_idt67"))
        btn_id = btn["id"] if btn else f"form:duyurTable:{ri}:j_idt67"
        records.append(
            {
                "row_index": ri,
                "button_id": btn_id,
                "province": tds[0].get_text(strip=True),
                "district": tds[1].get_text(strip=True),
                "project_name": tds[2].get_text(" ", strip=True),
                "project_owner": tds[3].get_text(" ", strip=True),
                "sector": tds[4].get_text(strip=True),
                "sub_sector": tds[5].get_text(strip=True),
                "decision_type": tds[6].get_text(strip=True),
                "announcement_date_tr": tds[7].get_text(strip=True),
                "project_type": tds[8].get_text(strip=True),
            }
        )
    return records


def _parse_total_records(xml_or_html: str) -> int | None:
    m = re.search(r"toplam\s+(\d+)", xml_or_html)
    if m:
        return int(m.group(1))
    m2 = re.search(r'"totalRecords":(\d+)', xml_or_html)
    return int(m2.group(1)) if m2 else None


def _resolve_document_page(doc_client: httpx.Client, doc_url: str) -> dict[str, Any]:
    info: dict[str, Any] = {
        "portal_doc_url": doc_url,
        "filing_id": None,
        "consulting_firm": None,
        "submitted_at": None,
        "pdf_urls": [],
    }
    m_id = re.search(r"/(\d+)/?$", doc_url)
    if m_id:
        info["filing_id"] = m_id.group(1)

    try:
        resp = doc_client.get(doc_url)
        if resp.status_code != 200:
            info["doc_fetch_status"] = resp.status_code
            return info
        soup = BeautifulSoup(resp.text, "lxml")
        tr = soup.select_one("table#proje tbody tr")
        if tr:
            tds = tr.find_all("td")
            if len(tds) >= 5:
                info["consulting_firm"] = tds[3].get_text(" ", strip=True)
                info["submitted_at"] = tds[4].get_text(" ", strip=True)
        for a in soup.find_all("a", onclick=True):
            m_open = re.search(r"window\.open\(['\"]([^'\"]+)['\"]", a["onclick"])
            if m_open:
                info["pdf_urls"].append(
                    {
                        "label": a.get_text(" ", strip=True),
                        "url": urljoin(doc_url, m_open.group(1)),
                    }
                )
    except Exception as exc:
        info["doc_fetch_error"] = str(exc)
    return info


def _quick_row_signature(row: dict[str, Any]) -> str:
    return "|".join(
        [
            normalize_tr_upper(row.get("province", "")),
            normalize_tr_upper(row.get("district", "")),
            row.get("announcement_date_tr", "").strip(),
            row.get("decision_type", "").strip(),
            row.get("project_name", "").strip(),
        ]
    )


def fetch_announcements(
    *,
    province_code: str | None = None,
    province_label: str | None = None,
    days: int = 7,
    cert_path: Path | None = None,
    existing_by_sig: dict[str, dict[str, Any]] | None = None,
    delay_sec: float = 0.2,
    max_records: int | None = None,
    check_revisions: bool = False,
) -> list[dict[str, Any]]:
    """Fetch e-ÇED filings nationwide (when province_code is None) or for a single province."""
    ssl_ctx = build_ssl_context(cert_path)
    today = date.today()
    start_date = today - timedelta(days=days)
    start_str = start_date.strftime("%d.%m.%Y")
    end_str = today.strftime("%d.%m.%Y")

    existing_by_sig = existing_by_sig or {}
    scope_name = province_label or "TÜRKİYE GENELİ"

    client = httpx.Client(
        verify=ssl_ctx,
        http2=False,
        headers={"User-Agent": USER_AGENT},
        timeout=30.0,
        follow_redirects=True,
    )
    doc_client = httpx.Client(
        verify=ssl_ctx,
        http2=False,
        headers={"User-Agent": USER_AGENT},
        timeout=25.0,
        follow_redirects=True,
    )

    try:
        r0 = client.get(BASE_URL)
        r0.raise_for_status()
        soup0 = BeautifulSoup(r0.text, "lxml")
        vs_input = soup0.find("input", {"name": "javax.faces.ViewState"})
        if not vs_input:
            raise RuntimeError("Could not locate javax.faces.ViewState on e-ÇED landing page")
        vs = vs_input["value"]

        if province_code and province_label:
            r_sel = client.post(
                BASE_URL,
                headers=AJAX_HEADERS,
                data={
                    "javax.faces.partial.ajax": "true",
                    "javax.faces.source": "form:duyuru-arama-fieldset:j_idt26",
                    "javax.faces.partial.execute": "form:duyuru-arama-fieldset:j_idt26",
                    "javax.faces.partial.render": "form:duyuru-arama-fieldset:duyuru-ilce",
                    "javax.faces.behavior.event": "itemSelect",
                    "javax.faces.partial.event": "itemSelect",
                    "form:duyuru-arama-fieldset:j_idt26_itemSelect": province_code,
                    "form:duyuru-arama-fieldset:j_idt26_input": province_label,
                    "form:duyuru-arama-fieldset:j_idt26_hinput": province_code,
                    "form": "form",
                    "javax.faces.ViewState": vs,
                },
            )
            r_sel.raise_for_status()
            vs = _extract_viewstate(r_sel.text) or vs

        base_form = {
            "form": "form",
            "form:duyuru-arama-fieldset:j_idt20": "",
            "form:duyuru-arama-fieldset:j_idt23_input": start_str,
            "form:duyuru-arama-fieldset:j_idt24_input": end_str,
            "form:duyuru-arama-fieldset:j_idt26_input": province_label or "",
            "form:duyuru-arama-fieldset:j_idt26_hinput": province_code or "",
            "form:duyuru-arama-fieldset:j_idt28_input": "",
            "form:duyuru-arama-fieldset:j_idt28_hinput": "",
            "form:duyuru-arama-fieldset:duyuru-ilce_input": "",
            "form:duyuru-arama-fieldset:duyuru-ilce_hinput": "",
            "form:duyuru-arama-fieldset:alt-sektor_input": "",
            "form:duyuru-arama-fieldset:alt-sektor_hinput": "",
            "form:duyuru-arama-fieldset:j_idt32": "",
            "form:duyuru-arama-fieldset:j_idt34_focus": "",
            "form:duyuru-arama-fieldset:j_idt34_input": "",
            "form:duyuru-arama-fieldset:j_idt39": "",
            "form:duyuru-arama-fieldset:j_idt41_focus": "",
            "form:duyuru-arama-fieldset:j_idt41_input": "",
            "form:duyuru-arama-fieldset_active": "0",
            "form:duyurTable_rppDD": "10",
        }

        r_search = client.post(
            BASE_URL,
            headers=AJAX_HEADERS,
            data={
                **base_form,
                "javax.faces.partial.ajax": "true",
                "javax.faces.source": "form:duyuru-arama-fieldset:j_idt44",
                "javax.faces.partial.execute": "@all",
                "javax.faces.partial.render": "form:duyurTable",
                "form:duyuru-arama-fieldset:j_idt44": "form:duyuru-arama-fieldset:j_idt44",
                "javax.faces.ViewState": vs,
            },
        )
        r_search.raise_for_status()
        vs = _extract_viewstate(r_search.text) or vs

        total_records = _parse_total_records(r_search.text) or 0
        limit = min(total_records, max_records) if max_records else total_records
        table_html = _extract_update_cdata(r_search.text, "form:duyurTable") or r_search.text
        first_page_rows = _parse_table_rows(table_html)
        page_size = len(first_page_rows) or 10

        print(f"[{scope_name}] {start_str}..{end_str}: reported={total_records} (fetching up to {limit})")

        def enrich_row(row: dict[str, Any]) -> dict[str, Any]:
            nonlocal vs
            sig = _quick_row_signature(row)
            cached = existing_by_sig.get(sig)
            if cached and cached.get("detail_text") and cached.get("documents"):
                merged = {**cached, **{k: v for k, v in row.items() if k not in {"row_index", "button_id"}}}
                if check_revisions:
                    refreshed_docs = []
                    for old_doc in cached.get("documents") or []:
                        doc_url = old_doc.get("portal_doc_url")
                        if doc_url and "eced.csb.gov.tr" in doc_url:
                            time.sleep(delay_sec)
                            refreshed = _resolve_document_page(doc_client, doc_url)
                            # Keep cached doc if portal hiccupped
                            if refreshed.get("pdf_urls") or refreshed.get("submitted_at"):
                                refreshed_docs.append(refreshed)
                            else:
                                refreshed_docs.append(old_doc)
                        else:
                            refreshed_docs.append(old_doc)
                    if refreshed_docs:
                        merged["documents"] = refreshed_docs
                merged.update(
                    compute_deadlines(
                        merged["decision_type"],
                        merged["announcement_date_tr"],
                        today,
                        merged.get("detail_text", ""),
                    )
                )
                merged["filing_key"] = make_filing_key(merged)
                return merged

            time.sleep(delay_sec)
            btn_id = row["button_id"]
            r_det = client.post(
                BASE_URL,
                headers=AJAX_HEADERS,
                data={
                    **base_form,
                    "javax.faces.partial.ajax": "true",
                    "javax.faces.source": btn_id,
                    "javax.faces.partial.execute": "@all",
                    "javax.faces.partial.render": "form:duyuru-detay-dialog",
                    btn_id: btn_id,
                    "javax.faces.ViewState": vs,
                },
            )
            r_det.raise_for_status()
            vs = _extract_viewstate(r_det.text) or vs
            dlg_html = _extract_update_cdata(r_det.text, "form:duyuru-detay-dialog") or ""
            dlg_soup = BeautifulSoup(dlg_html, "lxml")

            row["detail_text"] = dlg_soup.get_text(" ", strip=True)
            links = []
            for a in dlg_soup.find_all("a", href=True):
                href = a["href"].strip()
                if href and href != "#":
                    links.append({"text": a.get_text(" ", strip=True), "href": href})
            row["detail_links"] = links

            docs = []
            for lk in links:
                if "eced.csb.gov.tr" in lk["href"]:
                    time.sleep(delay_sec)
                    docs.append(_resolve_document_page(doc_client, lk["href"]))
            row["documents"] = docs
            row.update(
                compute_deadlines(
                    row["decision_type"],
                    row["announcement_date_tr"],
                    today,
                    row.get("detail_text", ""),
                )
            )
            row["filing_key"] = make_filing_key(row)
            row["first_seen_at"] = datetime.now().isoformat(timespec="seconds")
            row.pop("row_index", None)
            row.pop("button_id", None)
            return row

        all_rows: list[dict[str, Any]] = [enrich_row(r) for r in first_page_rows]

        first_offset = page_size
        while limit and len(all_rows) < limit:
            time.sleep(delay_sec)
            r_page = client.post(
                BASE_URL,
                headers=AJAX_HEADERS,
                data={
                    **base_form,
                    "javax.faces.partial.ajax": "true",
                    "javax.faces.source": "form:duyurTable",
                    "javax.faces.partial.execute": "form:duyurTable",
                    "javax.faces.partial.render": "form:duyurTable",
                    "form:duyurTable": "form:duyurTable",
                    "form:duyurTable_pagination": "true",
                    "form:duyurTable_first": str(first_offset),
                    "form:duyurTable_rows": str(page_size),
                    "form:duyurTable_skipChildren": "true",
                    "form:duyurTable_encodeFeature": "true",
                    "javax.faces.ViewState": vs,
                },
            )
            r_page.raise_for_status()
            vs = _extract_viewstate(r_page.text) or vs
            chunk_html = _extract_update_cdata(r_page.text, "form:duyurTable") or r_page.text
            page_rows = _parse_table_rows(chunk_html)
            if not page_rows:
                break
            for r in page_rows:
                if len(all_rows) >= limit:
                    break
                all_rows.append(enrich_row(r))
            first_offset += len(page_rows)
            print(f"  [{scope_name}] {len(all_rows)}/{limit}...")

        return all_rows
    finally:
        client.close()
        doc_client.close()


def merge_filings(
    existing: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Merge incoming filings into canonical store keyed by filing_key; returns (merged, new_count)."""
    today = date.today()
    by_key: dict[str, dict[str, Any]] = {}
    for f in existing:
        k = f.get("filing_key") or make_filing_key(f)
        f["filing_key"] = k
        by_key[k] = f

    new_count = 0
    for f in incoming:
        k = f.get("filing_key") or make_filing_key(f)
        f["filing_key"] = k
        if k not in by_key:
            new_count += 1
            by_key[k] = f
        else:
            prev = by_key[k]
            f["first_seen_at"] = prev.get("first_seen_at", f.get("first_seen_at"))
            change_log = list(prev.get("change_log") or [])

            prev_doc = (prev.get("documents") or [{}])[0]
            curr_doc = (f.get("documents") or [{}])[0]
            prev_urls = [u.get("url", "") for u in (prev_doc.get("pdf_urls") or [])]
            curr_urls = [u.get("url", "") for u in (curr_doc.get("pdf_urls") or [])]
            prev_sub = prev_doc.get("submitted_at")
            curr_sub = curr_doc.get("submitted_at")
            prev_firm = prev_doc.get("consulting_firm")
            curr_firm = curr_doc.get("consulting_firm")
            prev_txt = (prev.get("detail_text") or "").strip()
            curr_txt = (f.get("detail_text") or "").strip()

            changed_fields: list[str] = []
            if prev_urls and curr_urls and prev_urls != curr_urls:
                changed_fields.append("pdf_urls")
            if prev_sub and curr_sub and prev_sub != curr_sub:
                changed_fields.append("submitted_at")
            if prev_firm and curr_firm and prev_firm != curr_firm:
                changed_fields.append("consulting_firm")
            if prev_txt and curr_txt and prev_txt != curr_txt:
                changed_fields.append("detail_text")

            if changed_fields:
                change_log.append(
                    {
                        "detected_at": datetime.now().isoformat(timespec="seconds"),
                        "changed_fields": changed_fields,
                        "prev_submitted_at": prev_sub,
                        "new_submitted_at": curr_sub,
                        "prev_consulting_firm": prev_firm,
                        "new_consulting_firm": curr_firm,
                        "prev_pdf_urls": prev_urls,
                        "new_pdf_urls": curr_urls,
                        "prev_detail_sha256": hashlib.sha256(prev_txt.encode("utf-8")).hexdigest()[:16],
                        "new_detail_sha256": hashlib.sha256(curr_txt.encode("utf-8")).hexdigest()[:16],
                    }
                )

            merged_entry = {**prev, **f}
            if change_log:
                merged_entry["change_log"] = change_log
            by_key[k] = merged_entry

    merged = list(by_key.values())
    for f in merged:
        f.update(
            compute_deadlines(
                f.get("decision_type", ""),
                f.get("announcement_date_tr", ""),
                today,
                f.get("detail_text", ""),
            )
        )

    merged.sort(
        key=lambda x: (
            x.get("announcement_date") or "0000-00-00",
            x.get("filing_key", ""),
        ),
        reverse=True,
    )
    return merged, new_count
