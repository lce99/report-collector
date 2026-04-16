from __future__ import annotations

from argparse import ArgumentParser
from datetime import date, datetime
from zoneinfo import ZoneInfo

from report_collector.config import Settings
from report_collector.digest import (
    enrich_and_build_digest,
    now_iso_string,
    render_markdown,
    render_telegram_messages,
)
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


def main() -> int:
    parser = _parse_args()
    args = parser.parse_args()

    settings = Settings.from_env()
    target_date = _resolve_target_date(args.target_date, settings.timezone)

    collector = NaverResearchCollector(settings)
    reports = collector.collect(target_date)

    digest = enrich_and_build_digest(
        reports,
        target_date=target_date.isoformat(),
        generated_at=now_iso_string(settings.timezone),
        settings=settings,
    )
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
        f"[{target_date.isoformat()}] Collected {len(reports)} reports. "
        f"Must-read: {len(digest.must_read)}. "
        f"Generated at {now_iso_string(settings.timezone)}."
    )
    return 0
