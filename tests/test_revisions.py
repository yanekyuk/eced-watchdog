"""Unit tests for revision tracking, 2009/7 Circular diffing, and portal change logs."""

from __future__ import annotations

import unittest

from eced_watchdog.fetcher import merge_filings
from eced_watchdog.revisions import (
    build_revision_index,
    compute_pdf_revision_diff,
    has_pdf_changed,
    make_pdf_snapshot,
    parse_pdf_url_meta,
)


class TestRevisions(unittest.TestCase):
    def test_parse_pdf_url_meta(self) -> None:
        url = (
            "http://eced.csb.gov.tr/jsp/dosya/dosyaGoster.htm?"
            "tempAd=sign111.pdf&orjinalAd=CEDRAPORU.pdf&yuklemeTarihi=2026-11-17"
        )
        m = parse_pdf_url_meta(url)
        self.assertEqual(m["temp_ad"], "sign111.pdf")
        self.assertEqual(m["original_name"], "CEDRAPORU.pdf")
        self.assertEqual(m["upload_date"], "2026-11-17")

    def test_has_pdf_changed_detects_new_upload(self) -> None:
        saved = {
            "pdf_info": {
                "source_url": "http://eced.csb.gov.tr/jsp/dosya/dosyaGoster.htm?tempAd=signA.pdf&yuklemeTarihi=2026-11-01"
            }
        }
        same_url = "http://eced.csb.gov.tr/jsp/dosya/dosyaGoster.htm?tempAd=signA.pdf&yuklemeTarihi=2026-11-01"
        new_url = "http://eced.csb.gov.tr/jsp/dosya/dosyaGoster.htm?tempAd=signB.pdf&yuklemeTarihi=2026-11-20"
        self.assertFalse(has_pdf_changed(saved, same_url))
        self.assertTrue(has_pdf_changed(saved, new_url))

    def test_compute_pdf_revision_diff(self) -> None:
        filing = {
            "decision_type": "ÇED Olumlu",
            "announcement_date": "2026-11-01",
            "announcement_date_tr": "01.11.2026",
            "detail_text": "İlk duyuru",
        }
        doc1 = {
            "submitted_at": "01/11/2026 10:00:00",
            "consulting_firm": "Firma A Ltd.",
            "pdf_urls": [{"url": "http://eced.csb.gov.tr/jsp/dosya/dosyaGoster.htm?tempAd=v1.pdf&yuklemeTarihi=2026-11-01"}],
        }
        doc2 = {
            "submitted_at": "20/11/2026 14:00:00",
            "consulting_firm": "Firma B A.Ş.",
            "pdf_urls": [{"url": "http://eced.csb.gov.tr/jsp/dosya/dosyaGoster.htm?tempAd=v2.pdf&yuklemeTarihi=2026-11-20"}],
        }
        s1 = make_pdf_snapshot(
            filing,
            doc1,
            {"sha256": "a" * 64, "bytes": 10_000_000, "source_url": doc1["pdf_urls"][0]["url"]},
            {
                "page_count": 300,
                "text_pages": 280,
                "scanned_or_blank_pages": 20,
                "audit_checks": {
                    "mentions_olive_law_3573": True,
                    "mentions_seasonal_sampling": False,
                },
                "signals": {"protected_land_and_olive": {"page_count": 10}},
                "geo": {"precision": "exact_pdf", "lat": 38.5000, "lon": 27.0000, "point_count": 4},
            },
            version=1,
        )
        s2 = make_pdf_snapshot(
            filing,
            doc2,
            {"sha256": "b" * 64, "bytes": 12_000_000, "source_url": doc2["pdf_urls"][0]["url"]},
            {
                "page_count": 325,
                "text_pages": 305,
                "scanned_or_blank_pages": 20,
                "audit_checks": {
                    "mentions_olive_law_3573": False,
                    "mentions_seasonal_sampling": True,
                },
                "signals": {"protected_land_and_olive": {"page_count": 2}},
                "geo": {"precision": "exact_pdf", "lat": 38.5050, "lon": 27.0000, "point_count": 4},
            },
            version=2,
        )
        diff = compute_pdf_revision_diff(s1, s2)
        self.assertTrue(diff["sha256_changed"])
        self.assertEqual(diff["page_delta"], 25)
        self.assertTrue(diff["consulting_firm_changed"])
        self.assertIsNotNone(diff["coordinate_shift_m"])
        self.assertGreater(diff["coordinate_shift_m"], 500)
        removed = [c["key"] for c in diff["audit_check_changes"] if c["direction"] == "removed"]
        added = [c["key"] for c in diff["audit_check_changes"] if c["direction"] == "added"]
        self.assertEqual(removed, ["mentions_olive_law_3573"])
        self.assertEqual(added, ["mentions_seasonal_sampling"])
        self.assertEqual(diff["signal_page_deltas"]["protected_land_and_olive"], -8)

    def test_merge_filings_records_change_log(self) -> None:
        base = {
            "filing_key": "99999:10.11.2026:ÇED Olumlu",
            "province": "İZMİR",
            "district": "ALİAĞA",
            "project_name": "Test Tesisi",
            "project_owner": "Örnek A.Ş.",
            "decision_type": "ÇED Olumlu",
            "announcement_date_tr": "10.11.2026",
            "detail_text": "İlk resmi duyuru metni.",
            "documents": [
                {
                    "filing_id": "99999",
                    "submitted_at": "01/11/2026 09:00:00",
                    "consulting_firm": "Danışman A",
                    "pdf_urls": [{"label": "Dosya", "url": "http://eced.csb.gov.tr/jsp/dosya/dosyaGoster.htm?tempAd=old.pdf"}],
                }
            ],
        }
        updated = {
            **base,
            "detail_text": "2009/7 sayılı genelge kapsamında yenilenen duyuru metni.",
            "documents": [
                {
                    "filing_id": "99999",
                    "submitted_at": "18/11/2026 11:00:00",
                    "consulting_firm": "Danışman A",
                    "pdf_urls": [{"label": "Dosya", "url": "http://eced.csb.gov.tr/jsp/dosya/dosyaGoster.htm?tempAd=new.pdf"}],
                }
            ],
        }
        merged, new_cnt = merge_filings([base], [updated])
        self.assertEqual(new_cnt, 0)
        self.assertEqual(len(merged), 1)
        cl = merged[0].get("change_log") or []
        self.assertEqual(len(cl), 1)
        self.assertIn("pdf_urls", cl[0]["changed_fields"])
        self.assertIn("submitted_at", cl[0]["changed_fields"])
        self.assertIn("detail_text", cl[0]["changed_fields"])

    def test_build_revision_index_flags(self) -> None:
        filings = [
            {
                "filing_key": "10001:01.11.2026:ÇED Süreci Başlayan",
                "province": "İZMİR",
                "district": "KARABURUN",
                "project_name": "Kuzey Rüzgar Enerji Santrali (ER:3478799)",
                "project_owner": "Rüzgar Gücü A.Ş.",
                "decision_type": "ÇED Süreci Başlayan",
                "announcement_date": "2026-11-01",
                "announcement_date_tr": "01.11.2026",
                "detail_text": "Süreç başladı.",
                "documents": [{"filing_id": "10001", "submitted_at": "20/10/2026 10:00:00", "pdf_urls": []}],
            },
            {
                "filing_key": "10001:15.11.2026:ÇED Olumlu",
                "province": "İZMİR",
                "district": "KARABURUN",
                "project_name": "Kuzey Rüzgar Enerji Santrali (ER:3478799)",
                "project_owner": "Rüzgar Gücü A.Ş.",
                "decision_type": "ÇED Olumlu",
                "announcement_date": "2026-11-15",
                "announcement_date_tr": "15.11.2026",
                "detail_text": "2009/7 sayılı genelge kapsamında revize edilen rapor onaylandı.",
                "documents": [{"filing_id": "10001", "submitted_at": "12/11/2026 10:00:00", "pdf_urls": []}],
            },
            {
                "filing_key": "10002:18.11.2026:ÇED Süreci Başlayan",
                "province": "İZMİR",
                "district": "KARABURUN",
                "project_name": "Kuzey Rüzgar Enerji Santrali İlave Türbin (ER:3478799)",
                "project_owner": "Rüzgar Gücü A.Ş.",
                "decision_type": "ÇED Süreci Başlayan",
                "announcement_date": "2026-11-18",
                "announcement_date_tr": "18.11.2026",
                "detail_text": "İlave türbin başvurusu.",
                "documents": [{"filing_id": "10002", "submitted_at": "15/11/2026 10:00:00", "pdf_urls": []}],
            },
        ]
        idx = build_revision_index(filings, {})
        e1 = idx["by_filing_id"]["10001"]
        self.assertIn("multi_stage", e1["flags"])
        self.assertIn("circular_2009_7", e1["flags"])
        self.assertIn("related_filing", e1["flags"])
        self.assertEqual(len(e1["timeline"]), 2)
        self.assertEqual(e1["related_filings"][0]["filing_id"], "10002")

    def test_coordinate_proximity_links_asset_handover(self) -> None:
        filings = [
            {
                "filing_key": "20001:01.11.2026:İptal/İade",
                "province": "ÇANAKKALE",
                "district": "MERKEZ",
                "project_name": "Eski Şirket Altın Projesi",
                "project_owner": "Alamos Eski A.Ş.",
                "decision_type": "İptal/İade",
                "announcement_date": "2026-11-01",
                "announcement_date_tr": "01.11.2026",
                "detail_text": "İptal edildi.",
                "documents": [{"filing_id": "20001", "submitted_at": "01/11/2026", "pdf_urls": []}],
            },
            {
                "filing_key": "20002:18.11.2026:ÇED Süreci Başlayan",
                "province": "ÇANAKKALE",
                "district": "MERKEZ",
                "project_name": "Yeni Marka Cevher Zenginleştirme",
                "project_owner": "Yeni Holding Madencilik A.Ş.",
                "decision_type": "ÇED Süreci Başlayan",
                "announcement_date": "2026-11-18",
                "announcement_date_tr": "18.11.2026",
                "detail_text": "Yeni başvuru.",
                "documents": [{"filing_id": "20002", "submitted_at": "18/11/2026", "pdf_urls": []}],
            },
        ]
        digests_map = {
            "20001": {"analysis": {"geo": {"precision": "exact_pdf", "lat": 40.0000, "lon": 26.6000}}},
            "20002": {"analysis": {"geo": {"precision": "exact_pdf", "lat": 40.0040, "lon": 26.6010}}},
        }
        idx = build_revision_index(filings, digests_map)
        rel = idx["by_filing_id"]["20002"]["related_filings"]
        self.assertEqual(len(rel), 1)
        self.assertEqual(rel[0]["filing_id"], "20001")
        self.assertEqual(rel[0]["reason"], "coordinate_proximity")


if __name__ == "__main__":
    unittest.main()
