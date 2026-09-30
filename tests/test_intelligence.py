from __future__ import annotations

from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from report_collector.intelligence import build_daily_intelligence
from report_collector.main import _dedupe_reports
from report_collector.models import DailyDigest, Report
from report_collector.storage import publish_digest


def report(**overrides):
    return {
        "source": "mirae_asset_official", "report_id": "mirae-1",
        "broker": "미래에셋증권", "published_date": "2026-09-30",
        "title": "삼성전자 (005930/매수)", "category": "company",
        "category_label": "종목분석", "subject": None, "ticker": None,
        "detail_url": "https://securities.miraeasset.com/bbs/board/message/view.do?messageId=1",
        "pdf_url": "https://securities.miraeasset.com/bbs/download/1.pdf?attachmentId=1",
        "content_sources": ["html"], "has_pdf_text": False, "summary_engine": "rule",
        "excerpt": "HBM 수요가 증가할 것으로 전망한다.", **overrides,
    }


def payload(*reports, **overrides):
    return {"date": "2026-09-30", "requested_date": "2026-09-30",
            "generated_at": "2026-09-30T15:30:00+09:00", "reports": list(reports),
            "stats": {}, **overrides}


class DailyIntelligenceTests(unittest.TestCase):
    def test_pdf_link_is_not_extraction_or_assistant_reading(self):
        feed = build_daily_intelligence(payload(report()))
        status = feed["reports"][0]["content_status"]
        self.assertTrue(status["pdf_link_available"])
        self.assertFalse(status["pdf_text_extracted"])
        self.assertFalse(status["fulltext_read"])
        self.assertEqual(status["level"], "html_excerpt")
        self.assertEqual(feed["counts"]["pdf_links"], 1)
        self.assertEqual(feed["counts"]["pdf_text_extracted"], 0)
        self.assertEqual(feed["reports"][0]["provenance"]["link_verification"], "not_checked")
        self.assertEqual(status["extraction_error"], "not_recorded")

    def test_title_only_does_not_republish_title_as_body(self):
        row = build_daily_intelligence(payload(report(content_sources=[], excerpt="title")))["reports"][0]
        self.assertEqual(row["content_status"]["level"], "title_only")
        self.assertEqual(row["report_claims"], {"excerpt": "", "status": "unavailable"})
        self.assertEqual(row["read_priority"]["action"], "selective_pdf_read")

    def test_pdf_extraction_remains_partial_and_no_new_extraction_runs(self):
        row = build_daily_intelligence(payload(report(content_sources=["pdf"], has_pdf_text=True)))["reports"][0]
        self.assertEqual(row["content_status"]["level"], "pdf_excerpt")
        self.assertTrue(row["content_status"]["pdf_text_extracted"])
        self.assertFalse(row["content_status"]["fulltext_read"])

    def test_corrects_title_topics_but_preserves_upstream_labels(self):
        for title, upstream, expected in (
            ("Fixed Income Monthly", "industry", "fixed_income"),
            ("중국 주식전략: 시장 점검", "company", "strategy"),
            ("삼성E&A (028050/매수)", "industry", "company"),
            ("방산/첨단항공우주 (비중확대/신규)", "market", "industry"),
            ("소프트웨어:산업 동향", "company", "industry"),
        ):
            with self.subTest(title=title):
                row = build_daily_intelligence(payload(report(title=title, category=upstream)))["reports"][0]
                self.assertEqual(row["upstream_category"], upstream)
                self.assertEqual(row["classification"]["category"], expected)
                self.assertEqual(row["classification"]["method"], "deterministic_rules")
                self.assertEqual(row["classification"]["reasons"][0]["field"], "title")
                self.assertNotEqual(row["classification"]["confidence"], "verified")

    def test_company_title_candidate_does_not_adopt_translator_as_company(self):
        row = build_daily_intelligence(payload(report(
            title="카니발(CCL USA):F3Q 실적", subject="스티펠", ticker=None)))["reports"][0]
        self.assertEqual(row["upstream_subject"], "스티펠")
        self.assertEqual(row["company"], {"name": "카니발", "ticker": None, "status": "title_candidate"})

    def test_keywords_are_not_numeric_revisions_and_conflicts_are_visible(self):
        row = build_daily_intelligence(payload(report(
            estimate_signal_types=["earnings_estimate_up", "earnings_estimate_down"],
            change_types=["earnings_estimate_up"], estimate_revisions=[])))["reports"][0]
        self.assertEqual(row["signals"]["numeric_revision_status"], "none")
        self.assertEqual(row["signals"]["numeric_revisions"], [])
        self.assertTrue(row["signals"]["conflicting_keyword_directions"])
        self.assertNotIn("numeric_comparison_available_for_review", [x["code"] for x in row["read_priority"]["reasons"]])

    def test_numeric_comparison_is_labelled_unverified_and_requires_numbers(self):
        row = build_daily_intelligence(payload(report(estimate_revisions=[
            {"metric": "eps", "previous_value": 100, "current_value": 120, "period": "2027", "unit": "원"},
            {"metric": "eps", "previous_value": 100, "current_value": None},
            {"metric": "eps", "previous_value": 100, "current_value": float("nan")},
        ])))["reports"][0]
        self.assertEqual(len(row["signals"]["numeric_revisions"]), 1)
        self.assertEqual(row["signals"]["numeric_revisions"][0]["evidence_status"], "collector_numeric_comparison_unverified")

    def test_private_fields_settings_memos_and_exception_messages_are_excluded(self):
        secret = "PRIVATE_DIARY_PORTFOLIO_TOKEN"
        p = payload(report(body=secret, pdf_text=secret, investment_memo={"thesis": [secret]},
                           priority_keyword_matches=[secret], summary=secret),
                    priority_filters={"subjects": [secret]}, diary=secret,
                    stats={"collector_health": [{"source": "mirae_asset_official", "status": "failed",
                                                  "report_count": 0, "message": secret}]})
        before = deepcopy(p)
        feed = build_daily_intelligence(p)
        self.assertNotIn(secret, json.dumps(feed))
        self.assertEqual(feed["collector_health"][0]["error_code"], "collector_failed")
        self.assertEqual(p, before)

    def test_llm_excerpt_is_not_labelled_report_claim(self):
        row = build_daily_intelligence(payload(report(summary_engine="openai", excerpt="assistant interpretation")))["reports"][0]
        self.assertEqual(row["report_claims"]["status"], "unavailable")
        self.assertEqual(row["report_claims"]["excerpt"], "")

    def test_unsafe_urls_and_unknown_sources_do_not_escape(self):
        feed = build_daily_intelligence(payload(
            report(pdf_url="https://securities.miraeasset.com@localhost/private.pdf",
                   detail_url="https://securities.miraeasset.com/bbs?token=SECRET"),
            report(source="private_diary", report_id="private", excerpt="private")))
        self.assertEqual(feed["counts"]["excluded_reports"], 1)
        self.assertEqual(feed["counts"]["reports"], 1)
        row = feed["reports"][0]
        self.assertIsNone(row["pdf_url"])
        self.assertIsNone(row["detail_url"])
        self.assertIn("pdf_url_rejected", row["errors"])
        self.assertEqual(feed["shortlist"], [])
        self.assertNotIn("SECRET", json.dumps(feed))

    def test_canonical_ids_and_cross_source_groups_prevent_duplicate_reading_slots(self):
        first = report()
        second = report(source="naver_research", report_id="naver-1",
                        detail_url="https://finance.naver.com/research/company_read.naver?nid=1",
                        pdf_url="https://stock.pstatic.net/stock-research/company/1.pdf")
        feed = build_daily_intelligence(payload(first, second, deepcopy(first)))
        self.assertEqual(feed["counts"]["reports"], 2)
        self.assertEqual(feed["counts"]["duplicate_groups"], 1)
        self.assertEqual(len(feed["shortlist"]), 1)
        self.assertEqual(feed, build_daily_intelligence(payload(second, first)))

    def test_shortlist_is_bounded_and_diversifies_issuers_before_filling(self):
        rows = [report(report_id=f"r-{i}", title=f"Report {i}", broker=f"Issuer {i // 3}") for i in range(9)]
        feed = build_daily_intelligence(payload(*rows))
        shortlisted = [r for r in feed["reports"] if r["canonical_id"] in feed["shortlist"]]
        counts = Counter(r["broker"] for r in shortlisted)
        self.assertEqual(len(shortlisted), 5)
        self.assertLessEqual(max(counts.values()), 2)
        self.assertEqual(build_daily_intelligence(payload(*rows), shortlist_limit=0)["shortlist"], [])

    def test_merged_pdf_retains_original_collector_link_provenance(self):
        pdf = "https://stock.pstatic.net/stock-research/company/1.pdf"
        r = report(pdf_url=pdf, source_records=[
            {"source": "mirae_asset_official", "report_id": "mirae-1", "pdf_url": None},
            {"source": "naver_research", "report_id": "n1", "pdf_url": pdf},
        ])
        row = build_daily_intelligence(payload(r))["reports"][0]
        self.assertEqual(row["pdf_url"], pdf)
        self.assertEqual(row["provenance"]["source_records"][1]["pdf_url"], pdf)
        self.assertNotIn("pdf_url_rejected", row["errors"])

    def test_fallback_empty_and_malformed_dates_are_explicit(self):
        feed = build_daily_intelligence(payload(report(), requested_date="2026-10-01"))
        self.assertEqual(feed["freshness"], {"status": "fallback", "effective_age_days": 1})
        self.assertEqual(build_daily_intelligence(payload())["freshness"]["status"], "no_reports")
        self.assertEqual(build_daily_intelligence(payload(report(), date="unknown"))["freshness"]["status"], "unknown")

    def test_merge_preserves_both_collector_references_without_raw_content(self):
        first = Report(**{k: v for k, v in report().items() if k not in ("has_pdf_text", "content_sources")})
        second = Report(source="naver_research", report_id="n1", broker=first.broker,
                        category=first.category, category_label=first.category_label, title=first.title,
                        published_date=first.published_date, detail_url="https://finance.naver.com/research/company_read.naver?nid=1")
        deduped = _dedupe_reports([first, second])
        self.assertEqual(len(deduped), 1)
        first.source_records[0]["body"] = "PRIVATE"
        public = first.to_public_dict()
        self.assertNotIn("PRIVATE", json.dumps(public))
        row = build_daily_intelligence(payload(public))["reports"][0]
        self.assertEqual(len(row["provenance"]["source_records"]), 2)
        self.assertTrue(row["provenance"]["source_records_complete"])

    def test_publisher_adds_sidecars_preserving_legacy_outputs_and_historic_archive(self):
        r = Report(**{k: v for k, v in report().items() if k not in ("has_pdf_text", "content_sources")}, body="HBM")
        digest = DailyDigest(date="2026-09-30", requested_date="2026-09-30",
                             generated_at="2026-09-30T15:30:00+09:00", collection_note="",
                             dashboard_url=None, editorial_note="", keywords=[], priority_filters={},
                             stats={"total_reports": 1}, change_summary={}, rankings={}, changes=[], must_read=[r], reports=[r])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive, docs = root / "archive", root / "docs"
            historic = archive / "2026-09-29" / "digest.json"
            historic.parent.mkdir(parents=True)
            historic.write_text('{"date":"2026-09-29","reports":[]}', encoding="utf8")
            original = historic.read_bytes()
            with patch("report_collector.storage._sync_selection_performance", return_value={}), patch("report_collector.storage._sync_subject_payloads"):
                publish_digest(digest, archive_root=archive, docs_root=docs, markdown_content="legacy summary")
            archive_payload = json.loads((archive / digest.date / "digest.json").read_text(encoding="utf8"))
            for relative in ("data/latest.json", f"data/days/{digest.date}.json"):
                self.assertEqual(json.loads((docs / relative).read_text(encoding="utf8")), archive_payload)
            self.assertEqual(archive_payload, digest.to_public_dict())
            sidecar = json.loads((docs / "data/intelligence/latest.json").read_text(encoding="utf8"))
            self.assertEqual(sidecar, build_daily_intelligence(archive_payload))
            self.assertEqual(sidecar, json.loads((docs / f"data/intelligence/days/{digest.date}.json").read_text(encoding="utf8")))
            self.assertEqual(historic.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
