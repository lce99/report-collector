from __future__ import annotations

from argparse import ArgumentParser
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from report_collector.config import Settings
from report_collector.digest import (
    enrich_and_build_digest,
    now_iso_string,
    render_markdown,
    render_telegram_messages,
)
from report_collector.llm import enhance_digest_summaries
from report_collector.models import Report
from report_collector.sources.korea_investment import KoreaInvestmentCollector
from report_collector.sources.mirae_asset import MiraeAssetCollector
from report_collector.sources.naver_research import NaverResearchCollector
from report_collector.sources.common import normalize_report_key
from report_collector.storage import publish_digest
from report_collector.telegram_bot import send_messages


def _report_dedupe_key(report: Report) -> tuple[str, str]:
    return (
        report.published_date,
        normalize_report_key(report.display_title or report.title),
    )


def _report_preference(report: Report) -> tuple[int, int, int, int]:
    source_rank = {
        "mirae_asset_official": 3,
        "korea_investment_official": 2,
        "naver_research": 1,
    }.get(report.source, 0)
    return (
        source_rank,
        1 if report.pdf_url else 0,
        len(report.source_text),
        len(report.detail_url),
    )


def _merge_duplicate_reports(current: Report, candidate: Report) -> Report:
    preferred = current
    fallback = candidate
    if _report_preference(candidate) > _report_preference(current):
        preferred = candidate
        fallback = current

    preferred.views = max(preferred.views, fallback.views)

    if not preferred.pdf_url and fallback.pdf_url:
        preferred.pdf_url = fallback.pdf_url
    if not preferred.subject and fallback.subject:
        preferred.subject = fallback.subject
    if not preferred.subject_key and fallback.subject_key:
        preferred.subject_key = fallback.subject_key
    if not preferred.analyst and fallback.analyst:
        preferred.analyst = fallback.analyst
    if not preferred.target_price and fallback.target_price:
        preferred.target_price = fallback.target_price
    if preferred.target_price_value is None and fallback.target_price_value is not None:
        preferred.target_price_value = fallback.target_price_value
    if not preferred.opinion and fallback.opinion:
        preferred.opinion = fallback.opinion
    if not preferred.opinion_normalized and fallback.opinion_normalized:
        preferred.opinion_normalized = fallback.opinion_normalized
    if not preferred.body and fallback.body:
        preferred.body = fallback.body
    if not preferred.pdf_text and fallback.pdf_text:
        preferred.pdf_text = fallback.pdf_text

    return preferred


def _dedupe_reports(reports: list[Report]) -> list[Report]:
    selected: dict[tuple[str, str], Report] = {}
    for report in reports:
        key = _report_dedupe_key(report)
        current = selected.get(key)
        if current is None:
            selected[key] = report
            continue
        selected[key] = _merge_duplicate_reports(current, report)
    return list(selected.values())


def _collect_reports(target_date: date, settings: Settings) -> list[Report]:
    collectors = [
        NaverResearchCollector(settings),
        MiraeAssetCollector(settings),
        KoreaInvestmentCollector(settings),
    ]
    reports: list[Report] = []
    for collector in collectors:
        try:
            reports.extend(collector.collect(target_date))
        except Exception as exc:
            print(f"[warn] {collector.__class__.__name__} failed: {exc}")
            continue
    return _dedupe_reports(reports)


def _parse_args() -> ArgumentParser:
    parser = ArgumentParser(
        description="Collect Korean broker research reports and build a daily digest.",
    )
    parser.add_argument(
        "--date",
        dest="target_date",
        help="Target date in YYYY-MM-DD. Defaults to today in the configured timezone.",
    )
    parser.add_argument(
        "--skip-telegram",
        action="store_true",
        help="Build archive/site outputs without sending Telegram messages.",
    )
    return parser


def _resolve_target_date(value: str | None, timezone_name: str) -> date:
    if value:
        return date.fromisoformat(value)
    return datetime.now(ZoneInfo(timezone_name)).date()


def _collect_with_fallback(
    requested_date: date,
    settings: Settings,
) -> tuple[date, list, str]:
    reports = _collect_reports(requested_date, settings)
    if reports:
        return requested_date, reports, ""

    if not settings.enable_date_fallback:
        return requested_date, reports, ""

    for days_back in range(1, settings.max_date_fallback_days + 1):
        candidate_date = requested_date - timedelta(days=days_back)
        candidate_reports = _collect_reports(candidate_date, settings)
        if candidate_reports:
            return (
                candidate_date,
                candidate_reports,
                (
                    f"{requested_date.isoformat()} 기준 리포트가 없어 "
                    f"{candidate_date.isoformat()} 자료로 대체했습니다."
                ),
            )

    return (
        requested_date,
        reports,
        (
            f"{requested_date.isoformat()} 기준 리포트가 없어 "
            f"최근 {settings.max_date_fallback_days}일 내 자료도 찾지 못했습니다."
        ),
    )


def main() -> int:
    parser = _parse_args()
    args = parser.parse_args()

    settings = Settings.from_env()
    requested_date = _resolve_target_date(args.target_date, settings.timezone)

    effective_date, reports, collection_note = _collect_with_fallback(
        requested_date,
        settings,
    )

    digest = enrich_and_build_digest(
        reports,
        target_date=effective_date.isoformat(),
        requested_date=requested_date.isoformat(),
        generated_at=now_iso_string(settings.timezone),
        collection_note=collection_note,
        settings=settings,
    )
    enhance_digest_summaries(digest, settings)
    markdown = render_markdown(digest)

    publish_digest(
        digest,
        archive_root=settings.archive_root,
        docs_root=settings.docs_root,
        markdown_content=markdown,
    )

    if settings.telegram_enabled and not args.skip_telegram:
        messages = render_telegram_messages(digest)
        send_messages(
            settings.telegram_bot_token or "",
            settings.telegram_chat_id or "",
            messages,
        )

    print(
        f"[requested={requested_date.isoformat()} effective={effective_date.isoformat()}] "
        f"Collected {len(reports)} reports. "
        f"Must-read: {len(digest.must_read)}. "
        f"Generated at {now_iso_string(settings.timezone)}."
    )
    return 0
