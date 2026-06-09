from __future__ import annotations

from argparse import ArgumentParser
from datetime import date, datetime, timedelta
from time import perf_counter
from zoneinfo import ZoneInfo

from report_collector.config import Settings
from report_collector.digest import (
    enrich_and_build_digest,
    now_iso_string,
    render_markdown,
    render_telegram_messages,
)
from report_collector.llm import enhance_digest_summaries
from report_collector.market_data import NaverDailyPriceProvider
from report_collector.models import Report
from report_collector.sources.korea_investment import KoreaInvestmentCollector
from report_collector.sources.mirae_asset import MiraeAssetCollector
from report_collector.sources.naver_research import NaverResearchCollector
from report_collector.sources.shinhan_investment import ShinhanInvestmentCollector
from report_collector.sources.common import normalize_report_key
from report_collector.storage import publish_digest
from report_collector.telegram_bot import send_messages


COLLECTOR_SPECS = (
    ("naver_research", "네이버 금융 리서치", NaverResearchCollector),
    ("mirae_asset_official", "미래에셋증권 공식", MiraeAssetCollector),
    ("korea_investment_official", "한국투자증권 공식", KoreaInvestmentCollector),
    ("shinhan_investment_official", "신한투자증권 공식", ShinhanInvestmentCollector),
)

SOURCE_RANK = {
    "mirae_asset_official": 4,
    "shinhan_investment_official": 3,
    "korea_investment_official": 2,
    "naver_research": 1,
}

# Fields copied from the duplicate report when the preferred one lacks a value.
MERGE_FILL_FIELDS = (
    "pdf_url",
    "subject",
    "subject_key",
    "ticker",
    "analyst",
    "target_price",
    "target_price_value",
    "opinion",
    "opinion_normalized",
    "body",
    "pdf_text",
)


def _report_dedupe_key(report: Report) -> tuple[str, str]:
    return (
        report.published_date,
        normalize_report_key(report.display_title or report.title),
    )


def _report_preference(report: Report) -> tuple[int, int, int, int]:
    return (
        SOURCE_RANK.get(report.source, 0),
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

    for field in MERGE_FILL_FIELDS:
        preferred_value = getattr(preferred, field)
        fallback_value = getattr(fallback, field)
        if preferred_value in (None, "") and fallback_value not in (None, ""):
            setattr(preferred, field, fallback_value)

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


def _trim_error_message(exc: Exception, limit: int = 180) -> str:
    message = f"{exc.__class__.__name__}: {exc}"
    if len(message) <= limit:
        return message
    return message[: limit - 1].rstrip() + "…"


def _run_collector(
    collector,
    *,
    target_date: date,
    source: str,
    label: str,
) -> tuple[list[Report], dict[str, object]]:
    started_at = perf_counter()
    try:
        reports = list(collector.collect(target_date))
    except Exception as exc:
        elapsed = round(perf_counter() - started_at, 2)
        message = _trim_error_message(exc)
        print(f"[warn] {collector.__class__.__name__} failed: {exc}")
        return [], {
            "source": source,
            "label": label,
            "collector": collector.__class__.__name__,
            "status": "failed",
            "report_count": 0,
            "duration_seconds": elapsed,
            "message": message,
        }

    elapsed = round(perf_counter() - started_at, 2)
    return reports, {
        "source": source,
        "label": label,
        "collector": collector.__class__.__name__,
        "status": "ok" if reports else "empty",
        "report_count": len(reports),
        "duration_seconds": elapsed,
        "message": "" if reports else "정상 종료됐지만 해당 날짜 리포트가 없습니다.",
    }


def _collect_reports(
    target_date: date,
    settings: Settings,
) -> tuple[list[Report], dict[str, object]]:
    reports: list[Report] = []
    collector_health: list[dict[str, object]] = []
    for source, label, collector_class in COLLECTOR_SPECS:
        collector_reports, health = _run_collector(
            collector_class(settings),
            target_date=target_date,
            source=source,
            label=label,
        )
        reports.extend(collector_reports)
        collector_health.append(health)

    deduped_reports = _dedupe_reports(reports)
    return deduped_reports, {
        "date": target_date.isoformat(),
        "raw_report_count": len(reports),
        "deduped_report_count": len(deduped_reports),
        "collectors": collector_health,
    }


def _build_arg_parser() -> ArgumentParser:
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
) -> tuple[date, list[Report], str, list[dict[str, object]]]:
    reports, attempt = _collect_reports(requested_date, settings)
    attempts = [attempt]
    if reports:
        return requested_date, reports, "", attempts

    if not settings.enable_date_fallback:
        return requested_date, reports, "", attempts

    for days_back in range(1, settings.max_date_fallback_days + 1):
        candidate_date = requested_date - timedelta(days=days_back)
        candidate_reports, candidate_attempt = _collect_reports(candidate_date, settings)
        attempts.append(candidate_attempt)
        if candidate_reports:
            return (
                candidate_date,
                candidate_reports,
                (
                    f"{requested_date.isoformat()} 기준 리포트가 없어 "
                    f"{candidate_date.isoformat()} 자료로 대체했습니다."
                ),
                attempts,
            )

    return (
        requested_date,
        reports,
        (
            f"{requested_date.isoformat()} 기준 리포트가 없어 "
            f"최근 {settings.max_date_fallback_days}일 내 자료도 찾지 못했습니다."
        ),
        attempts,
    )


def main() -> int:
    args = _build_arg_parser().parse_args()

    settings = Settings.from_env()
    requested_date = _resolve_target_date(args.target_date, settings.timezone)

    (
        effective_date,
        reports,
        collection_note,
        collection_attempts,
    ) = _collect_with_fallback(requested_date, settings)

    digest = enrich_and_build_digest(
        reports,
        target_date=effective_date.isoformat(),
        requested_date=requested_date.isoformat(),
        generated_at=now_iso_string(settings.timezone),
        collection_note=collection_note,
        collection_attempts=collection_attempts,
        settings=settings,
    )
    enhance_digest_summaries(digest, settings)
    markdown = render_markdown(digest)

    market_data_provider = None
    if settings.market_data_enabled and settings.market_data_source == "naver":
        market_data_provider = NaverDailyPriceProvider(
            user_agent=settings.user_agent,
            timeout_seconds=settings.request_timeout_seconds,
            max_pages=settings.market_data_max_pages,
        )

    publish_digest(
        digest,
        archive_root=settings.archive_root,
        docs_root=settings.docs_root,
        markdown_content=markdown,
        market_data_provider=market_data_provider,
        subject_ticker_map=settings.subject_ticker_map,
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
