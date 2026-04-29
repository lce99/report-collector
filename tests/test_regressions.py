from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from report_collector.config import _parse_bool, _parse_int
from report_collector.digest import _iter_previous_reports
from report_collector.main import _merge_duplicate_reports
from report_collector.models import Report
from report_collector.storage import _build_index


class ConfigParsingTests(unittest.TestCase):
    def test_invalid_env_values_fall_back_to_defaults(self) -> None:
        self.assertEqual(_parse_int("not-a-number", 7), 7)
        self.assertEqual(_parse_int("", 7), 7)
        self.assertTrue(_parse_bool("true", False))
        self.assertFalse(_parse_bool("false", True))
        self.assertTrue(_parse_bool("unknown", True))


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
        self.assertEqual(merged.analyst, naver.analyst)
        self.assertEqual(merged.target_price, naver.target_price)
        self.assertEqual(merged.opinion, naver.opinion)


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
