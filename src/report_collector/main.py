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
from report_collector.sources.naver_research import NaverResearchCollector
from report_collector.storage import publish_digest
from report_collector.telegram_bot import send_messages


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
    collector: NaverResearchCollector,
    requested_date: date,
    settings: Settings,
) -> tuple[date, list, str]:
    reports = collector.collect(requested_date)
    if reports:
        return requested_date, reports, ""

    if not settings.enable_date_fallback:
        return requested_date, reports, ""

    for days_back in range(1, settings.max_date_fallback_days + 1):
        candidate_date = requested_date - timedelta(days=days_back)
        candidate_reports = collector.collect(candidate_date)
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

    collector = NaverResearchCollector(settings)
    effective_date, reports, collection_note = _collect_with_fallback(
        collector,
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
