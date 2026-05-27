from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from report_collector.config import Settings, _parse_bool, _parse_int, _parse_mapping
from report_collector.digest import (
    _build_stats,
    _iter_previous_reports,
    _score_report,
    _select_must_read,
    render_telegram_messages,
)
from report_collector.estimates import extract_estimate_metrics, extract_estimate_signal_types
from report_collector.llm import _apply_summary
from report_collector.main import _merge_duplicate_reports, _run_collector
from report_collector.market_data import NaverDailyPriceProvider, parse_naver_daily_price_html
from report_collector.models import DailyDigest, Report
from report_collector.sources.naver_research import CATEGORY_CONFIGS, NaverResearchCollector
from report_collector.sources.shinhan_investment import ShinhanBoardConfig, _parse_item
from report_collector.storage import (
    _build_index,
    _build_subject_chart_payload,
    _sync_selection_performance,
)
from report_collector.telegram_bot import process_command_updates, render_command_response


class ConfigParsingTests(unittest.TestCase):
    def test_invalid_env_values_fall_back_to_defaults(self) -> None:
        self.assertEqual(_parse_int("not-a-number", 7), 7)
        self.assertEqual(_parse_int("", 7), 7)
        self.assertTrue(_parse_bool("true", False))
        self.assertFalse(_parse_bool("false", True))
        self.assertTrue(_parse_bool("unknown", True))
        self.assertEqual(
            _parse_mapping("삼성전자=005930,NAVER=035420"),
            {"삼성전자": "005930", "NAVER": "035420"},
        )

    def test_openai_summary_requires_explicit_enable_flag(self) -> None:
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=True):
            self.assertFalse(Settings.from_env().openai_summary_enabled)

        with patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "sk-test", "OPENAI_SUMMARY_ENABLED": "true"},
            clear=True,
        ):
            self.assertTrue(Settings.from_env().openai_summary_enabled)


class ReportLinkTests(unittest.TestCase):
    def test_primary_url_prefers_pdf_when_available(self) -> None:
        report = Report(
            source="naver_research",
            category="company",
            category_label="Company",
            report_id="r1",
            title="Earnings review",
            broker="Fake증권",
            published_date="2026-04-20",
            detail_url="https://finance.naver.com/research/company_read.naver?nid=1",
            pdf_url="https://stock.pstatic.net/stock-research/company/report.pdf",
        )

        payload = report.to_public_dict()

        self.assertEqual(report.primary_url, report.pdf_url)
        self.assertEqual(payload["primary_url"], report.pdf_url)
        self.assertEqual(payload["primary_url_label"], "PDF")
        self.assertEqual(payload["link_health"]["status"], "pdf_preferred")

    def test_primary_url_falls_back_to_detail_page(self) -> None:
        report = Report(
            source="korea_investment_official",
            category="company",
            category_label="Company",
            report_id="r2",
            title="Earnings review",
            broker="Fake증권",
            published_date="2026-04-20",
            detail_url="https://example.com/detail",
        )

        self.assertEqual(report.primary_url, report.detail_url)
        self.assertEqual(report.to_public_dict()["primary_url_label"], "상세")
        self.assertEqual(report.to_public_dict()["link_health"]["status"], "detail_only")


class MarketDataTests(unittest.TestCase):
    def test_naver_price_provider_calculates_close_to_close_return(self) -> None:
        html = """
        <table class="type2">
          <tr><td>2026.04.28</td><td>110,000</td><td></td><td></td><td></td><td></td><td>200</td></tr>
          <tr><td>2026.04.20</td><td>100,000</td><td></td><td></td><td></td><td></td><td>100</td></tr>
        </table>
        """
        points = parse_naver_daily_price_html(html)
        self.assertEqual([point.date.isoformat() for point in points], ["2026-04-28", "2026-04-20"])

        provider = NaverDailyPriceProvider(
            user_agent="test",
            timeout_seconds=1,
            fetch_html=lambda url: html,
        )
        result = provider.calculate_return("005930", date(2026, 4, 20), date(2026, 4, 28))

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["ticker"], "005930")
        self.assertEqual(result["price_return_pct"], 10.0)
        self.assertEqual(result["volume_change_pct"], 100.0)


class NaverResearchCollectorTests(unittest.TestCase):
    def test_parse_list_row_keeps_subject_ticker(self) -> None:
        html = """
        <table><tr>
          <td><a href="/item/main.naver?code=005930">삼성전자</a></td>
          <td><a href="/research/company_read.naver?nid=1&page=1">Earnings review</a></td>
          <td>Fake증권</td>
          <td><a href="/stock-research/company/report.pdf">PDF</a></td>
          <td>26.04.20</td>
          <td>1,234</td>
        </tr></table>
        """
        soup = BeautifulSoup(html, "html.parser")
        row = soup.find("tr")
        assert row is not None
        collector = NaverResearchCollector(
            SimpleNamespace(base_url="https://finance.naver.com/research/")
        )

        report = collector._parse_list_row(row.find_all("td"), CATEGORY_CONFIGS["company"])

        self.assertIsNotNone(report)
        assert report is not None
        self.assertEqual(report.subject, "삼성전자")
        self.assertEqual(report.ticker, "005930")


class DedupeMergeTests(unittest.TestCase):
    def test_official_report_keeps_priority_and_backfills_naver_metadata(self) -> None:
        official = Report(
            source="mirae_asset_official",
            category="company",
            category_label="Company",
            report_id="official-1",
            title="Earnings review",
            broker="Mirae",
            published_date="2026-04-20",
            detail_url="https://example.com/official",
        )
        naver = Report(
            source="naver_research",
            category="company",
            category_label="Company",
            report_id="naver-1",
            title="Earnings review",
            broker="Mirae",
            published_date="2026-04-20",
            detail_url="https://example.com/naver",
            pdf_url="https://example.com/report.pdf",
            subject="ExampleCo",
            ticker="005930",
            views=1250,
            analyst="Analyst",
            target_price="10,000",
            opinion="Buy",
            body="Naver detail body",
        )

        merged = _merge_duplicate_reports(official, naver)

        self.assertIs(merged, official)
        self.assertEqual(merged.views, 1250)
        self.assertEqual(merged.pdf_url, naver.pdf_url)
        self.assertEqual(merged.subject, naver.subject)
        self.assertEqual(merged.ticker, naver.ticker)
        self.assertEqual(merged.analyst, naver.analyst)
        self.assertEqual(merged.target_price, naver.target_price)
        self.assertEqual(merged.opinion, naver.opinion)


class CollectorHealthTests(unittest.TestCase):
    def test_successful_collector_reports_health_metadata(self) -> None:
        class FakeCollector:
            def collect(self, target_date):
                return [
                    Report(
                        source="fake_source",
                        category="company",
                        category_label="Company",
                        report_id="fake-1",
                        title="Earnings review",
                        broker="Fake",
                        published_date=target_date.isoformat(),
                        detail_url="https://example.com/report",
                    )
                ]

        reports, health = _run_collector(
            FakeCollector(),
            target_date=date(2026, 4, 20),
            source="fake_source",
            label="Fake Source",
        )

        self.assertEqual(len(reports), 1)
        self.assertEqual(health["status"], "ok")
        self.assertEqual(health["report_count"], 1)
        self.assertEqual(health["source"], "fake_source")
        self.assertEqual(health["label"], "Fake Source")
        self.assertIn("duration_seconds", health)

    def test_failed_collector_reports_failure_without_raising(self) -> None:
        class FailingCollector:
            def collect(self, target_date):
                raise RuntimeError("source unavailable")

        with redirect_stdout(StringIO()):
            reports, health = _run_collector(
                FailingCollector(),
                target_date=date(2026, 4, 20),
                source="fake_source",
                label="Fake Source",
            )

        self.assertEqual(reports, [])
        self.assertEqual(health["status"], "failed")
        self.assertEqual(health["report_count"], 0)
        self.assertIn("RuntimeError", str(health["message"]))

    def test_digest_stats_include_active_collector_health(self) -> None:
        attempts = [
            {
                "date": "2026-04-20",
                "raw_report_count": 2,
                "deduped_report_count": 2,
                "collectors": [
                    {
                        "source": "naver_research",
                        "label": "Naver",
                        "status": "ok",
                        "report_count": 2,
                        "duration_seconds": 0.5,
                    },
                    {
                        "source": "official",
                        "label": "Official",
                        "status": "empty",
                        "report_count": 0,
                        "duration_seconds": 0.1,
                    },
                ],
            }
        ]

        stats = _build_stats([], [], {"changed_reports": 0}, attempts)

        self.assertEqual(stats["collector_health_summary"]["ok_sources"], 1)
        self.assertEqual(stats["collector_health_summary"]["empty_sources"], 1)
        self.assertEqual(stats["collector_health_summary"]["failed_sources"], 0)
        self.assertEqual(len(stats["collector_health"]), 2)
        self.assertEqual(stats["collector_health_attempts"], attempts)
        self.assertEqual(stats["collector_alerts"], [])

    def test_digest_stats_alert_on_failed_collector(self) -> None:
        attempts = [
            {
                "date": "2026-04-20",
                "raw_report_count": 0,
                "deduped_report_count": 0,
                "collectors": [
                    {
                        "source": "fake_source",
                        "label": "Fake Source",
                        "status": "failed",
                        "report_count": 0,
                        "duration_seconds": 0.1,
                        "message": "RuntimeError: source unavailable",
                    }
                ],
            }
        ]

        stats = _build_stats([], [], {"changed_reports": 0}, attempts)

        self.assertEqual(stats["collector_alert_summary"]["total_alerts"], 1)
        self.assertEqual(stats["collector_alerts"][0]["type"], "collector_failed")
        self.assertEqual(stats["collector_alerts"][0]["severity"], "critical")

    def test_digest_stats_alert_on_source_volume_drop_against_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive_root = Path(tmp)
            for day, count in (("2026-04-18", 12), ("2026-04-19", 10)):
                day_dir = archive_root / day
                day_dir.mkdir()
                (day_dir / "digest.json").write_text(
                    json.dumps(
                        {
                            "date": day,
                            "stats": {
                                "total_reports": 100,
                                "collector_health": [
                                    {
                                        "source": "fake_source",
                                        "label": "Fake Source",
                                        "status": "ok",
                                        "report_count": count,
                                    }
                                ],
                                "collector_health_summary": {
                                    "deduped_report_count": 100,
                                },
                            },
                            "reports": [],
                        }
                    ),
                    encoding="utf-8",
                )

            attempts = [
                {
                    "date": "2026-04-20",
                    "raw_report_count": 100,
                    "deduped_report_count": 100,
                    "collectors": [
                        {
                            "source": "fake_source",
                            "label": "Fake Source",
                            "status": "ok",
                            "report_count": 2,
                        }
                    ],
                }
            ]

            stats = _build_stats(
                [],
                [],
                {"changed_reports": 0},
                attempts,
                archive_root=archive_root,
                current_date="2026-04-20",
            )

        self.assertEqual(stats["collector_alert_summary"]["volume_drop_alerts"], 1)
        self.assertEqual(stats["collector_alerts"][0]["type"], "collector_volume_drop")
        self.assertEqual(stats["collector_alerts"][0]["current_count"], 2)
        self.assertEqual(stats["collector_alerts"][0]["average_count"], 11.0)


class ShinhanInvestmentCollectorTests(unittest.TestCase):
    def test_parse_item_builds_official_report_with_pdf_and_body_metadata(self) -> None:
        report = _parse_item(
            {
                "fn": "935861",
                "f0": "2026.05.04",
                "f1": "산일전기; AI 데이터센터 밸류체인으로 합류",
                "f2": "산일전기",
                "f3": "https://bbs2.shinhansec.com/board/message/file.pdf.do?attachmentId=351220",
                "f4": "최승환",
                "f5": "444",
                "f6": "매수",
                "f7": (
                    "신한생각: 특수변압기 전방 확대<br>"
                    "Valuation &amp; Risk: 목표주가 180,000원에서 370,000원으로 상향"
                ),
                "f10": (
                    "https://bbs2.shinhansec.com/siw/board/message/view.file.pop.do"
                    "?boardName=gicompanyanalyst&messageId=935861"
                ),
            },
            ShinhanBoardConfig("gicompanyanalyst", "company"),
        )

        self.assertEqual(report.source, "shinhan_investment_official")
        self.assertEqual(report.category, "company")
        self.assertEqual(report.broker, "신한투자증권")
        self.assertEqual(report.published_date, "2026-05-04")
        self.assertEqual(report.report_id, "shinhan-gicompanyanalyst-935861")
        self.assertEqual(report.views, 444)
        self.assertEqual(report.analyst, "최승환")
        self.assertEqual(report.opinion, "매수")
        self.assertEqual(report.target_price, "370,000원")
        self.assertIsNone(report.subject)
        self.assertIn("Valuation & Risk", report.body)
        self.assertTrue(report.pdf_url and report.pdf_url.endswith("351220"))


class MustReadSelectionTests(unittest.TestCase):
    def _report(
        self,
        report_id: str,
        *,
        broker: str,
        subject: str,
        category: str = "company",
        score: float = 10.0,
    ) -> Report:
        report = Report(
            source="fake_source",
            category=category,
            category_label=category.title(),
            report_id=report_id,
            title=f"{subject} update",
            broker=broker,
            published_date="2026-04-20",
            detail_url=f"https://example.com/{report_id}",
            subject=subject,
            subject_key=subject.lower(),
        )
        report.score = score
        return report

    def test_must_read_prefers_diverse_subjects_before_backfill(self) -> None:
        reports = [
            self._report("a1", broker="Broker A", subject="Alpha", score=12),
            self._report("a2", broker="Broker A", subject="Alpha", score=11),
            self._report("b1", broker="Broker A", subject="Beta", score=10),
            self._report("c1", broker="Broker B", subject="Gamma", score=9),
        ]

        selected = _select_must_read(reports, 3)

        self.assertEqual([report.report_id for report in selected], ["a1", "b1", "c1"])

    def test_must_read_keeps_change_signal_near_top(self) -> None:
        normal = self._report("normal", broker="Broker A", subject="Alpha", score=15)
        changed = self._report("changed", broker="Broker B", subject="Beta", score=8)
        changed.change_reasons = ["목표가 상향"]

        selected = _select_must_read(
            [normal, changed],
            2,
            changed_reports=[changed],
        )

        self.assertIs(selected[0], changed)

    def test_must_read_relaxed_backfill_still_caps_subject_and_broker_skew(self) -> None:
        reports = [
            self._report("a1", broker="Broker A", subject="Alpha", score=20),
            self._report("a2", broker="Broker A", subject="Alpha", score=19),
            self._report("a3", broker="Broker A", subject="Alpha", score=18),
            self._report("b1", broker="Broker A", subject="Beta", score=17),
            self._report("c1", broker="Broker B", subject="Gamma", score=16),
            self._report("d1", broker="Broker C", subject="Delta", score=15),
        ]

        selected = _select_must_read(
            reports,
            4,
            broker_soft_limit=1,
            broker_hard_limit=2,
            identity_hard_limit=2,
        )

        self.assertEqual(len(selected), 4)
        self.assertLessEqual(sum(1 for report in selected if report.broker == "Broker A"), 2)
        self.assertLessEqual(sum(1 for report in selected if report.subject == "Alpha"), 2)


class ScoringTests(unittest.TestCase):
    def test_score_rewards_official_source_and_change_signals(self) -> None:
        settings = SimpleNamespace(broker_priority=("Fake증권",))
        base = Report(
            source="naver_research",
            category="company",
            category_label="Company",
            report_id="base",
            title="Earnings review",
            broker="Other",
            published_date="2026-04-20",
            detail_url="https://example.com/base",
        )
        changed = Report(
            source="shinhan_investment_official",
            category="company",
            category_label="Company",
            report_id="changed",
            title="Earnings review",
            broker="Fake증권",
            published_date="2026-04-20",
            detail_url="https://example.com/changed",
            target_price="100,000원",
            opinion="매수",
            analyst="Analyst",
            pdf_text="본문" * 600,
        )
        changed.target_price_change = "up"
        changed.target_price_change_pct = 18.0
        changed.opinion_changed = True
        changed.opinion_change_direction = "up"
        changed.coverage_initiated = True

        base_score, _ = _score_report(base, settings)  # type: ignore[arg-type]
        changed_score, reasons = _score_report(changed, settings)  # type: ignore[arg-type]

        self.assertGreater(changed_score, base_score + 5.0)
        self.assertIn("공식 소스", reasons)
        self.assertTrue(any("목표가" in reason and "상향" in reason for reason in reasons))
        self.assertTrue(changed.score_breakdown)
        self.assertIn("목표가 상향", {item["label"] for item in changed.score_breakdown})


class EstimateExtractionTests(unittest.TestCase):
    def test_extracts_profit_margin_metrics_and_signals(self) -> None:
        text = (
            "1Q26 영업이익은 294억원(+52%QoQ)으로 컨센서스를 상회할 전망입니다. "
            "이익 전망치를 상향하고 OPM 5.5%(+1.2%p)로 마진 개선이 예상됩니다."
        )

        metrics = extract_estimate_metrics(text)
        signals = extract_estimate_signal_types(text)

        profit = next(item for item in metrics if item["metric"] == "operating_profit")
        margin = next(item for item in metrics if item["metric"] == "operating_margin")
        self.assertEqual(profit["value_krw_100m"], 294)
        self.assertEqual(margin["value_pct"], 5.5)
        self.assertEqual(margin["change_pctp"], 1.2)
        self.assertIn("earnings_estimate_up", signals)
        self.assertIn("margin_estimate_up", signals)


class SubjectHistoryTests(unittest.TestCase):
    def test_subject_chart_payload_tracks_targets_opinions_and_recent_timeline(self) -> None:
        timeline = [
            {
                "published_date": "2026-04-10",
                "broker": "A증권",
                "title": "old",
                "target_price_value": 90000,
                "opinion_normalized": "buy",
            },
            {
                "published_date": "2026-04-25",
                "broker": "A증권",
                "title": "raise",
                "target_price_value": 100000,
                "opinion_normalized": "buy",
                "estimate_metrics": [
                    {
                        "metric": "operating_profit",
                        "metric_group": "earnings",
                        "label": "영업이익",
                        "value": 294,
                        "unit": "억원",
                        "value_krw_100m": 294,
                    }
                ],
                "score": 8,
            },
            {
                "published_date": "2026-05-01",
                "broker": "B증권",
                "title": "hold",
                "target_price_value": 95000,
                "opinion_normalized": "hold",
                "estimate_metrics": [
                    {
                        "metric": "operating_margin",
                        "metric_group": "margin",
                        "label": "OPM",
                        "value": 5.5,
                        "unit": "%",
                        "value_pct": 5.5,
                    }
                ],
                "score": 7,
            },
        ]

        payload = _build_subject_chart_payload(
            timeline,
            [timeline[1], timeline[2]],
            "2026-05-01",
        )

        self.assertEqual(
            [item["target_price_value"] for item in payload["target_price_history"]],
            [90000, 100000, 95000],
        )
        self.assertEqual(
            payload["opinion_distribution"],
            [{"label": "buy", "count": 1}, {"label": "hold", "count": 1}],
        )
        self.assertEqual(
            [item["title"] for item in payload["broker_timeline"]],
            ["raise", "hold"],
        )
        self.assertEqual(
            [item["metric"] for item in payload["estimate_metric_history"]],
            ["operating_profit", "operating_margin"],
        )

    def test_selection_performance_ledger_adds_pending_horizons_without_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            docs_data_root = Path(tmp) / "docs" / "data"
            archive_root = Path(tmp) / "storage" / "archive"
            digest_payload = {
                "date": "2026-04-20",
                "generated_at": "2026-04-20T18:00:00+09:00",
                "must_read": [
                    {
                        "report_id": "r1",
                        "display_title": "삼성전자 - Earnings review",
                        "subject": "삼성전자",
                        "subject_key": "samsung",
                        "broker": "Fake증권",
                        "category": "company",
                        "category_label": "Company",
                        "score": 9.5,
                        "score_reasons": ["목표가 상향"],
                        "detail_url": "https://example.com/r1",
                    }
                ],
            }

            first = _sync_selection_performance(
                docs_data_root,
                digest_payload,
                archive_root=archive_root,
            )
            second = _sync_selection_performance(
                docs_data_root,
                digest_payload,
                archive_root=archive_root,
            )

        self.assertEqual(first["summary"]["tracked_selections"], 1)
        self.assertEqual(second["summary"]["tracked_selections"], 1)
        selection = second["selections"][0]
        self.assertEqual(set(selection["horizons"]), {"1d", "7d", "30d"})
        self.assertEqual(selection["horizons"]["7d"]["due_date"], "2026-04-27")
        self.assertEqual(selection["horizons"]["7d"]["status"], "pending")

    def test_selection_performance_completes_due_horizons_from_archive(self) -> None:
        class FakeMarketDataProvider:
            source_name = "fake_market_data"

            def calculate_return(self, ticker: str, selected_date: date, due_date: date):
                self.last_request = (ticker, selected_date, due_date)
                return {
                    "ticker": ticker,
                    "price_source": self.source_name,
                    "entry_price_date": selected_date.isoformat(),
                    "entry_close": 100000,
                    "exit_price_date": due_date.isoformat(),
                    "exit_close": 112000,
                    "price_return_pct": 12.0,
                    "entry_volume": 100,
                    "exit_volume": 150,
                    "volume_change_pct": 50.0,
                }

        with tempfile.TemporaryDirectory() as tmp:
            docs_data_root = Path(tmp) / "docs" / "data"
            archive_root = Path(tmp) / "storage" / "archive"
            market_provider = FakeMarketDataProvider()
            selected_payload = {
                "date": "2026-04-20",
                "generated_at": "2026-04-20T18:00:00+09:00",
                "must_read": [
                    {
                        "report_id": "r1",
                        "display_title": "삼성전자 - Earnings review",
                        "subject": "삼성전자",
                        "subject_key": "samsung",
                        "broker": "Fake증권",
                        "category": "company",
                        "category_label": "Company",
                        "score": 9.5,
                        "score_reasons": ["목표가 상향"],
                        "detail_url": "https://example.com/r1",
                        "target_price_value": 100000,
                    }
                ],
            }
            _sync_selection_performance(
                docs_data_root,
                selected_payload,
                archive_root=archive_root,
            )
            follow_up_dir = archive_root / "2026-04-21"
            follow_up_dir.mkdir(parents=True)
            (follow_up_dir / "digest.json").write_text(
                json.dumps(
                    {
                        "date": "2026-04-21",
                        "reports": [
                            {
                                "report_id": "r2",
                                "display_title": "삼성전자 - Follow up",
                                "subject": "삼성전자",
                                "subject_key": "samsung",
                                "broker": "Other증권",
                                "published_date": "2026-04-21",
                                "score": 8.1,
                                "target_price": "110,000원",
                                "target_price_value": 110000,
                                "opinion": "매수",
                                "has_change_signal": True,
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = _sync_selection_performance(
                docs_data_root,
                {"date": "2026-04-28", "generated_at": "2026-04-28T18:00:00+09:00", "must_read": []},
                archive_root=archive_root,
                market_data_provider=market_provider,
                subject_ticker_map={"samsung": "005930"},
            )

        selection = result["selections"][0]
        self.assertEqual(selection["horizons"]["1d"]["status"], "completed")
        self.assertEqual(selection["horizons"]["1d"]["follow_up_report_count"], 1)
        self.assertEqual(selection["horizons"]["1d"]["follow_up_change_count"], 1)
        self.assertEqual(selection["horizons"]["1d"]["target_price_delta_pct"], 10.0)
        self.assertEqual(selection["ticker"], "005930")
        self.assertEqual(selection["horizons"]["1d"]["price_return_pct"], 12.0)
        self.assertEqual(selection["horizons"]["1d"]["volume_change_pct"], 50.0)
        self.assertEqual(result["summary"]["priced_by_horizon"]["1d"], 1)
        self.assertEqual(result["summary"]["average_price_return_by_horizon"]["1d"], 12.0)
        self.assertEqual(selection["horizons"]["30d"]["status"], "pending")


class TelegramRenderingTests(unittest.TestCase):
    def test_telegram_health_block_only_lists_problem_sources(self) -> None:
        digest = DailyDigest(
            date="2026-04-20",
            requested_date="2026-04-20",
            generated_at="2026-04-20T18:00:00+09:00",
            collection_note="",
            dashboard_url=None,
            editorial_note="오늘의 요약입니다.",
            keywords=[],
            priority_filters={
                "enabled": False,
                "subjects": [],
                "keywords": [],
                "priority_only": False,
                "matched_reports": 0,
                "matched_must_read": 0,
            },
            stats={
                "total_reports": 1,
                "pdf_text_reports": 0,
                "llm_summary_reports": 0,
                "collector_health_summary": {
                    "available": True,
                    "ok_sources": 1,
                    "empty_sources": 0,
                    "failed_sources": 1,
                },
                "collector_alert_summary": {"available": False},
                "collector_alerts": [],
                "collector_health": [
                    {
                        "source": "ok_source",
                        "label": "Good Source",
                        "status": "ok",
                        "report_count": 10,
                        "duration_seconds": 0.1,
                    },
                    {
                        "source": "bad_source",
                        "label": "Bad Source",
                        "status": "failed",
                        "report_count": 0,
                        "duration_seconds": 0.2,
                        "message": "failed",
                    },
                ],
            },
            change_summary={},
            rankings={},
            changes=[],
            must_read=[],
            reports=[],
        )

        rendered = "\n".join(render_telegram_messages(digest))

        self.assertIn("Bad Source", rendered)
        self.assertNotIn("Good Source: 정상", rendered)

    def test_telegram_includes_structured_investment_memo(self) -> None:
        report = Report(
            source="fake_source",
            category="company",
            category_label="Company",
            report_id="memo-1",
            title="Earnings review",
            broker="Fake",
            published_date="2026-04-20",
            detail_url="https://example.com/report",
            pdf_url="https://example.com/report.pdf",
            summary="실적이 개선됐습니다.",
        )
        report.score = 9.2
        report.investment_memo = {
            "stance": "positive",
            "thesis": ["수익성 개선"],
            "catalysts": ["신제품 출시"],
            "risks": ["원가 상승"],
            "numbers": ["목표가 10,000원"],
            "action": "실적 추정 상향 여부를 확인",
            "confidence": "medium",
        }
        digest = DailyDigest(
            date="2026-04-20",
            requested_date="2026-04-20",
            generated_at="2026-04-20T18:00:00+09:00",
            collection_note="",
            dashboard_url=None,
            editorial_note="오늘의 요약입니다.",
            keywords=[],
            priority_filters={
                "enabled": False,
                "subjects": [],
                "keywords": [],
                "priority_only": False,
                "matched_reports": 0,
                "matched_must_read": 0,
            },
            stats={
                "total_reports": 1,
                "pdf_text_reports": 0,
                "llm_summary_reports": 1,
                "llm_investment_memo_reports": 1,
                "collector_health_summary": {"available": False},
                "collector_alert_summary": {"available": False},
                "collector_alerts": [],
                "collector_health": [],
            },
            change_summary={},
            rankings={},
            changes=[],
            must_read=[report],
            reports=[report],
        )

        rendered = "\n".join(render_telegram_messages(digest))

        self.assertIn("LLM 투자 메모 1건", rendered)
        self.assertIn("투자 메모", rendered)
        self.assertIn("실적 추정 상향 여부를 확인", rendered)
        self.assertIn("https://example.com/report.pdf", rendered)
        self.assertNotIn('<a href="https://example.com/report">', rendered)

    def test_command_renderer_returns_subject_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            docs_root = Path(tmp) / "docs"
            data_root = docs_root / "data"
            subjects_root = data_root / "subjects"
            subjects_root.mkdir(parents=True)
            (data_root / "latest.json").write_text(
                json.dumps(
                    {
                        "date": "2026-04-20",
                        "editorial_note": "오늘의 요약입니다.",
                        "must_read": [
                            {
                                "display_title": "삼성전자 - Earnings review",
                                "broker": "Fake증권",
                                "score": 9.2,
                                "detail_url": "https://example.com/r1",
                                "pdf_url": "https://example.com/r1.pdf",
                            }
                        ],
                        "changes": [],
                        "reports": [],
                        "stats": {"collector_health": []},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (subjects_root / "index.json").write_text(
                json.dumps(
                    {
                        "subjects": [
                            {"subject_key": "samsung", "subject_name": "삼성전자"}
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (subjects_root / "samsung.json").write_text(
                json.dumps(
                    {
                        "subject_name": "삼성전자",
                        "latest_report_date": "2026-04-20",
                        "report_count": 3,
                        "active_broker_count": 2,
                        "target_summary": {"avg": 90000, "high": 100000, "low": 80000},
                        "broker_timeline": [
                            {
                                "date": "2026-04-20",
                                "broker": "Fake증권",
                                "title": "목표가 상향",
                            }
                        ],
                        "latest_by_broker": [
                            {
                                "display_title": "삼성전자 - Earnings review",
                                "broker": "Fake증권",
                                "score": 9.2,
                                "detail_url": "https://example.com/r1",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            today = render_command_response("/today", docs_root)
            subject = render_command_response("/subject 삼성전자", docs_root)

        self.assertIn("데일리 리포트", today)
        self.assertIn("https://example.com/r1.pdf", today)
        self.assertNotIn('<a href="https://example.com/r1">', today)
        self.assertIn("삼성전자", subject)
        self.assertIn("최근 2주", subject)

    def test_command_polling_omits_offset_until_state_exists(self) -> None:
        calls: list[dict[str, object]] = []

        def fake_get(bot_token: str, method: str, params: dict[str, object]) -> dict:
            calls.append(params)
            return {"result": []}

        with tempfile.TemporaryDirectory() as tmp:
            with patch("report_collector.telegram_bot._telegram_api_get", fake_get):
                processed = process_command_updates("token", docs_root=Path(tmp) / "docs")

        self.assertEqual(processed, 0)
        self.assertNotIn("offset", calls[0])


class LlmInvestmentMemoTests(unittest.TestCase):
    def test_apply_summary_stores_structured_investment_memo(self) -> None:
        report = Report(
            source="fake_source",
            category="company",
            category_label="Company",
            report_id="memo-1",
            title="Earnings review",
            broker="Fake",
            published_date="2026-04-20",
            detail_url="https://example.com/report",
        )

        applied = _apply_summary(
            report,
            {
                "summary": "실적 개선이 핵심입니다.",
                "excerpt": "수익성 개선 리포트",
                "investment_memo": {
                    "stance": "positive",
                    "thesis": ["마진 개선"],
                    "catalysts": ["신규 수주"],
                    "risks": ["원가 상승"],
                    "numbers": ["목표가 10,000원"],
                    "action": "다음 실적 발표에서 마진 지속성을 확인",
                    "confidence": "medium",
                },
            },
        )

        self.assertTrue(applied)
        self.assertEqual(report.summary_engine, "openai")
        self.assertEqual(report.investment_memo["stance"], "positive")
        self.assertEqual(report.investment_memo["thesis"], ["마진 개선"])
        self.assertEqual(
            report.to_public_dict()["investment_memo"]["action"],
            "다음 실적 발표에서 마진 지속성을 확인",
        )


class ArchiveRobustnessTests(unittest.TestCase):
    def test_index_and_history_skip_malformed_digest_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive_root = Path(tmp)
            good_day = archive_root / "2026-04-20"
            bad_day = archive_root / "2026-04-19"
            good_day.mkdir()
            bad_day.mkdir()
            (bad_day / "digest.json").write_text("{not-json", encoding="utf-8")
            (good_day / "digest.json").write_text(
                json.dumps(
                    {
                        "date": "2026-04-20",
                        "generated_at": "2026-04-20T18:00:00+09:00",
                        "stats": {"total_reports": 1},
                        "keywords": ["test"],
                        "must_read": [{"display_title": "Example report"}],
                        "reports": [{"broker": "Mirae", "subject": "ExampleCo"}],
                    }
                ),
                encoding="utf-8",
            )

            index = _build_index(archive_root)
            previous_reports = _iter_previous_reports(archive_root, "2026-04-21")

        self.assertEqual(index["days"][0]["date"], "2026-04-20")
        self.assertEqual(index["days"][0]["top_titles"], ["Example report"])
        self.assertEqual(previous_reports, [{"broker": "Mirae", "subject": "ExampleCo"}])


if __name__ == "__main__":
    unittest.main()
