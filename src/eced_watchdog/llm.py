"""Optional Gemini API structured-output synthesis layer over deterministic PDF page extracts."""

from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import pymupdf as fitz
from pydantic import BaseModel, Field

DEFAULT_EK1_MODEL = "gemini-4-hydrogen"
DEFAULT_EK2_MODEL = "gemini-3.5-flash-lite"
DEFAULT_GEMINI_MODEL = DEFAULT_EK1_MODEL


def choose_gemini_model(filing: dict[str, Any], explicit_model: str | None = None) -> str:
    """Use explicit/env model if set; otherwise route Ek-1 to Gemini 4 Hydrogen and Ek-2 to 3.5 Flash-Lite."""
    if explicit_model:
        return explicit_model
    env_model = os.environ.get("GEMINI_MODEL")
    if env_model:
        return env_model
    if (filing.get("project_type") or "").strip().lower() == "ek-1":
        return DEFAULT_EK1_MODEL
    return DEFAULT_EK2_MODEL


class CitedFact(BaseModel):
    label: str = Field(description="Short parameter label, e.g. 'Footprint / Length', 'Water Use', 'Nearest Settlement'.")
    value: str = Field(description="Exact stated number/claim from the report, with units.")
    page: int = Field(description="Exact 1-based PDF page number from the supplied excerpts.")


class BaselineAssessment(BaseModel):
    field_survey_status: Literal[
        "field_survey_documented",
        "literature_only",
        "mixed_or_unclear",
        "not_found",
    ] = Field(description="Whether actual field surveys were conducted vs. literature-only species/habitat lists.")
    seasonal_sampling_status: Literal[
        "completed_pre_project",
        "promised_post_approval_only",
        "not_found",
        "unclear",
    ] = Field(
        description=(
            "Distinguish strictly between multi-season baseline sampling ALREADY completed before filing "
            "vs. seasonal monitoring merely PROMISED after approval."
        )
    )
    cumulative_impact_status: Literal[
        "quantitatively_assessed",
        "superficial_or_boilerplate",
        "omitted_or_not_found",
    ] = Field(description="Quality of cumulative regional impact evaluation.")
    olive_and_protected_status: str = Field(
        description="Concise factual summary of olive groves (Law 3573), forests, wetlands, ÖÇK/SİT status with [s. N]."
    )
    explanation: str = Field(
        description="2-4 concise, neutral scientific sentences explaining the baseline findings with [s. N] page citations."
    )


DanistayCategory = Literal[
    "zeytinlik_3573",
    "proje_parcalama",
    "kumulatif_etki",
    "flora_fauna_mevsimsel",
    "su_hidrojeoloji",
    "tarim_orman_korunan_alan",
    "izleme_olcum_celiskisi",
]


class AuditRedFlag(BaseModel):
    category: DanistayCategory = Field(
        description=(
            "Danıştay ÇED iptal içtihatlarına karşılık gelen hukuki/teknik kategori: "
            "zeytinlik_3573 (3573 m.20 3 km yasağı), proje_parcalama (eşik değer dolanılması / Ek-2 parçalama), "
            "kumulatif_etki (birikimli bölgesel etki eksikliği), flora_fauna_mevsimsel (tek mevsim/literatür/endemik/göç), "
            "su_hidrojeoloji (akifer/başlangıç analizi/can suyu/atıksu), tarim_orman_korunan_alan (5403/orman/ÖÇK/SİT/kurum görüşü), "
            "izleme_olcum_celiskisi (ölçüm hatası/iç çelişki/bilirkişi denetim noktası)."
        )
    )
    severity: Literal["high", "medium", "low"] = Field(
        description=(
            "high = doğrudan Danıştay iptal emsali taşıyan ağır mevzuat/metodoloji ihlali; "
            "medium = keşif ve bilirkişi incelemesinde doğrulanması gereken somut teknik eksik; "
            "low = ikincil idari veya biçimsel eksiklik."
        )
    )
    title: str = Field(description="Kısa, somut ve hukuki/bilimsel açıdan net başlık (Türkçe).")
    detail: str = Field(description="Yalnızca verilen sayfalara dayanan, nesnel ve eksiksiz Türkçe açıklama.")
    pages: list[int] = Field(description="Bu bulguyu destekleyen 1 tabanlı PDF sayfa numaraları.")


class RecordQuestion(BaseModel):
    question_tr: str = Field(
        description="HKT tutanağına, askı görüş dilekçesine veya keşif/bilirkişi talebine doğrudan eklenebilecek net Türkçe teknik soru."
    )
    pages: list[int] = Field(description="İlgili 1 tabanlı PDF sayfa numaraları.")


class EcologicalSynthesis(BaseModel):
    executive_summary_tr: str = Field(
        description="3-5 cümlelik akıcı, resmi ve nesnel Türkçe özet: projenin kapsamı, konumu, ölçeği ve temel çevresel riskleri."
    )
    executive_summary_en: str = Field(
        description="3-5 sentence neutral English summary: what is proposed, exact location/scale, and primary environmental stakes."
    )
    key_facts: list[CitedFact] = Field(
        description="Doğrudan rapordan çıkarılmış, sayfa numaralı en fazla 10 somut sayısal veri."
    )
    baseline_assessment: BaselineAssessment
    red_flags: list[AuditRedFlag] = Field(
        description=(
            "Danıştay ÇED iptal ölçütlerine göre sınıflandırılmış en fazla 6 somut bilimsel/hukuki bulgu. "
            "Önemsiz biçimsel detayları 'high' olarak işaretlemeyiniz."
        )
    )
    recommended_bilirkisi_disciplines: list[str] = Field(
        description=(
            "İdari yargıda mahallinde keşif ve bilirkişi heyeti talep edilmesi halinde heyette bulunması gereken "
            "temel akademik uzmanlık alanları (ör. 'Çevre Mühendisi', 'Hidrojeoloji Mühendisi', 'Biyolog', "
            "'Ziraat Mühendisi', 'Orman Mühendisi', 'Maden Mühendisi', 'Şehir ve Bölge Plancısı')."
        )
    )
    hkt_and_petition_questions: list[RecordQuestion] = Field(
        description="HKT tutanağı, Madde 14 görüş dilekçesi veya İYUK 20/A davasında bilirkişi incelemesi için 3-5 somut Türkçe teknik soru."
    )
    data_limitations: str = Field(
        description="İncelenemeyen bölümler (taranmış ekler, alıntı dışı kalan sayfalar) hakkında kısa Türkçe not."
    )


def load_env_file(env_path: Path) -> None:
    """Load KEY=VALUE pairs from a local .env file without overriding existing env vars."""
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def resolve_api_key(root: Path | None = None) -> str | None:
    if root:
        load_env_file(root / ".env")
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")


def select_high_signal_pages(
    pdf_path: Path,
    analysis: dict[str, Any],
    *,
    max_pages: int = 26,
    max_chars: int = 75_000,
) -> tuple[list[int], str]:
    """Select the highest-signal body pages from the PDF for focused, page-cited synthesis."""
    doc = fitz.open(pdf_path)
    n_pages = len(doc)
    chosen: list[int] = []

    def add_page(pno: int) -> None:
        if 1 <= pno <= n_pages and pno not in chosen and len(chosen) < max_pages:
            chosen.append(pno)

    # 1. Cover / project card (pages 1-2)
    for p in (1, 2):
        add_page(p)

    # 2. Key detected section starts + immediate following page
    priority_heading_terms = (
        "teknik olmayan",
        "bölüm ii",
        "flora",
        "kümülatif",
        "çevresel ve sosyal",
        "bölüm i:",
    )
    for pno, title in analysis.get("headings") or []:
        t_low = title.lower()
        if any(term in t_low for term in priority_heading_terms):
            add_page(pno)
            add_page(pno + 1)

    # 3. Top pages from each deterministic signal bucket
    for bucket in (
        "protected_land_and_olive",
        "water_and_discharge",
        "ecology_and_baseline",
        "pollutants_and_hazards",
        "coordinates_and_footprint",
        "cost_and_capacity",
    ):
        sig = (analysis.get("signals") or {}).get(bucket) or {}
        for pno in (sig.get("pages") or [])[:4]:
            add_page(pno)

    # 4. Backfill early body pages (e.g. non-technical summary pages 6..15)
    for p in range(6, min(16, n_pages + 1)):
        add_page(p)

    chosen.sort()

    parts: list[str] = []
    used_pages: list[int] = []
    total_chars = 0
    for pno in chosen:
        txt = (doc[pno - 1].get_text("text") or "").strip()
        if len(txt) < 40:
            continue
        if len(txt) > 4500:
            txt = txt[:4500] + "\n[...page truncated...]"
        chunk = f"=== PDF PAGE [s. {pno}] ===\n{txt}\n"
        if total_chars + len(chunk) > max_chars and used_pages:
            break
        parts.append(chunk)
        used_pages.append(pno)
        total_chars += len(chunk)

    doc.close()
    return used_pages, "\n".join(parts)


def synthesize_with_gemini(
    filing: dict[str, Any],
    analysis: dict[str, Any],
    pdf_path: Path,
    *,
    api_key: str,
    model: str | None = None,
    revision_diff: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run strict schema-constrained Gemini synthesis over selected PDF pages (with optional v1->v2 diff context)."""
    from google import genai
    from google.genai import types

    chosen_model = choose_gemini_model(filing, model)
    used_pages, excerpt_blob = select_high_signal_pages(pdf_path, analysis)

    system_instruction = (
        "You are an independent environmental scientist and Turkish administrative-law EIA (ÇED) auditor reviewing "
        "an official Turkish ÇED / PTD filing for public-interest transparency and court-grade technical review.\n"
        "Strict epistemic & legal grounding rules:\n"
        "1. Rely ONLY on the provided PDF page excerpts and filing metadata. Never invent figures, species, distances, or claims.\n"
        "2. Every fact, finding, and question MUST cite exact 1-based PDF page numbers from the === PDF PAGE [s. N] === markers.\n"
        "3. Apply Danıştay (Turkish Council of State) ÇED annulment criteria strictly:\n"
        "   - 'high' severity ONLY for established annulment grounds: 3573 Olive Law 3 km violations (mitigation promises cannot bypass it), "
        "project splitting / capacity-threshold evasion (proje parçalama), absent cumulative regional impact assessment, "
        "single-season/literature-only flora-fauna inventories in sensitive ecosystems, missing mandatory pre-project baseline water/soil chemistry "
        "or agency consents (DSİ, İl Tarım/5403, OGM), or outright impossible monitoring methods (e.g. visual noise monitoring).\n"
        "   - 'medium' severity for concrete technical gaps requiring on-site keşif & bilirkişi verification.\n"
        "   - 'low' severity for secondary procedural or administrative omissions.\n"
        "4. Explicitly distinguish completed pre-project baseline field/seasonal surveys from future post-approval monitoring commitments.\n"
        "5. Recommend the exact university expert disciplines (bilirkişi heyeti — always include 'Şehir ve Bölge Plancısı' when land-use/plan compliance is implicated) needed for an on-site court inspection.\n"
        "6. If a REVISION DIFF (v1 -> v2) or 2009/7 Circular re-submission context is provided, explicitly examine whether the revised PDF genuinely resolved prior scientific/legal gaps or merely patched wording / removed sensitive terms.\n"
        "7. Write all fields except executive_summary_en in fluent, complete, formal Turkish sentences (zero fragments, zero partisan commentary)."
    )

    revision_blob = ""
    if revision_diff:
        revision_blob = (
            f"\nREVISION DIFF DETECTED (v{revision_diff.get('from_version')} -> v{revision_diff.get('to_version')}):\n"
            f"- Summary: {revision_diff.get('summary_tr')}\n"
            f"- Page delta: {revision_diff.get('page_delta')}\n"
            f"- Upload dates: {revision_diff.get('from_upload_date')} -> {revision_diff.get('to_upload_date')}\n"
            f"- Audit check changes: {revision_diff.get('audit_check_changes')}\n"
            f"- Coordinate shift (m): {revision_diff.get('coordinate_shift_m')}\n"
        )

    user_prompt = (
        f"FILING METADATA:\n"
        f"- Province / District: {filing.get('province')} / {filing.get('district')}\n"
        f"- Project: {filing.get('project_name')}\n"
        f"- Owner: {filing.get('project_owner')}\n"
        f"- Sector: {filing.get('sector')} / {filing.get('sub_sector')}\n"
        f"- Stage / Annex: {filing.get('decision_type')} / {filing.get('project_type')}\n"
        f"- Announcement Date: {filing.get('announcement_date_tr')}\n"
        f"- Total PDF Pages: {analysis.get('page_count')} "
        f"(extractable text: {analysis.get('text_pages')}, scanned/image-only: {analysis.get('scanned_or_blank_pages')})\n"
        f"- Pages Included Below: {used_pages}\n"
        f"{revision_blob}\n"
        f"OFFICIAL ANNOUNCEMENT:\n{filing.get('detail_text', '')}\n\n"
        f"EXCERPTED PDF PAGES:\n{excerpt_blob}"
    )

    client = genai.Client(api_key=api_key)
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=0.1,
        response_mime_type="application/json",
        response_schema=EcologicalSynthesis,
    )

    last_err: Exception | None = None
    response = None
    for attempt, backoff in enumerate((4, 10, 20), start=1):
        try:
            response = client.models.generate_content(
                model=chosen_model,
                contents=user_prompt,
                config=config,
            )
            break
        except Exception as exc:
            last_err = exc
            msg = str(exc)
            if any(code in msg for code in ("503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED")) and attempt < 3:
                time.sleep(backoff)
                continue
            raise
    if response is None:
        raise last_err or RuntimeError("Gemini synthesis returned no response")

    parsed = EcologicalSynthesis.model_validate_json(response.text)
    usage = getattr(response, "usage_metadata", None)
    usage_dict = None
    if usage is not None:
        usage_dict = {
            "prompt_tokens": getattr(usage, "prompt_token_count", None),
            "output_tokens": getattr(usage, "candidates_token_count", None),
            "thoughts_tokens": getattr(usage, "thoughts_token_count", None),
            "total_tokens": getattr(usage, "total_token_count", None),
        }
    return {
        "model": chosen_model,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "pages_sent": used_pages,
        "usage": usage_dict,
        "result": parsed.model_dump(),
    }
