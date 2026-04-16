from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


DEFAULT_BROKER_PRIORITY = (
    "메리츠증권",
    "삼성증권",
    "신한투자증권",
    "한국투자증권",
    "키움증권",
    "대신증권",
    "하나증권",
    "NH투자증권",
    "KB증권",
    "미래에셋증권",
    "유안타증권",
    "교보증권",
    "SK증권",
    "유진투자증권",
    "IBK투자증권",
    "iM증권",
    "다올투자증권",
    "DS투자증권",
    "한화투자증권",
)

DEFAULT_CATEGORIES = (
    "company",
    "industry",
    "economy",
    "invest",
    "market",
    "debenture",
)


def _parse_csv(value: str | None, default: tuple[str, ...]) -> tuple[str, ...]:
    if not value:
        return default
    parts = tuple(item.strip() for item in value.split(",") if item.strip())
    return parts or default


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _normalize_site_url(value: str | None) -> str | None:
    if not value:
        return None
    return value.rstrip("/") + "/"


def _default_site_url() -> str | None:
    explicit = _normalize_site_url(os.getenv("SITE_URL"))
    if explicit:
        return explicit

    repository = os.getenv("GITHUB_REPOSITORY")
    if not repository or "/" not in repository:
        return None

    owner, name = repository.split("/", 1)
    return f"https://{owner}.github.io/{name}/"


@dataclass(slots=True)
class Settings:
    base_url: str
    timezone: str
    user_agent: str
    archive_root: Path
    docs_root: Path
    request_timeout_seconds: int
    page_depth: int
    must_read_limit: int
    preview_char_limit: int
    summary_sentence_count: int
    ranking_limit: int
    enable_date_fallback: bool
    max_date_fallback_days: int
    categories: tuple[str, ...]
    broker_priority: tuple[str, ...]
    priority_subjects: tuple[str, ...]
    priority_keywords: tuple[str, ...]
    priority_only: bool
    telegram_bot_token: str | None
    telegram_chat_id: str | None
    send_telegram: bool
    site_url: str | None
    site_title: str

    @property
    def telegram_enabled(self) -> bool:
        return bool(
            self.send_telegram
            and self.telegram_bot_token
            and self.telegram_chat_id
        )

    @property
    def priority_filter_enabled(self) -> bool:
        return bool(self.priority_subjects or self.priority_keywords)

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            base_url=os.getenv(
                "REPORT_SOURCE_BASE_URL",
                "https://finance.naver.com/research/",
            ),
            timezone=os.getenv("REPORT_TIMEZONE", "Asia/Seoul"),
            user_agent=os.getenv(
                "REPORT_USER_AGENT",
                (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/135.0.0.0 Safari/537.36"
                ),
            ),
            archive_root=Path(os.getenv("ARCHIVE_ROOT", "storage/archive")),
            docs_root=Path(os.getenv("DOCS_ROOT", "docs")),
            request_timeout_seconds=int(os.getenv("REQUEST_TIMEOUT_SECONDS", "20")),
            page_depth=int(os.getenv("REPORT_PAGE_DEPTH", "4")),
            must_read_limit=int(os.getenv("MUST_READ_LIMIT", "12")),
            preview_char_limit=int(os.getenv("PREVIEW_CHAR_LIMIT", "240")),
            summary_sentence_count=int(os.getenv("SUMMARY_SENTENCE_COUNT", "3")),
            ranking_limit=int(os.getenv("RANKING_LIMIT", "5")),
            enable_date_fallback=_parse_bool(
                os.getenv("ENABLE_DATE_FALLBACK"),
                True,
            ),
            max_date_fallback_days=int(os.getenv("MAX_DATE_FALLBACK_DAYS", "3")),
            categories=_parse_csv(
                os.getenv("REPORT_CATEGORIES"),
                DEFAULT_CATEGORIES,
            ),
            broker_priority=_parse_csv(
                os.getenv("BROKER_PRIORITY"),
                DEFAULT_BROKER_PRIORITY,
            ),
            priority_subjects=_parse_csv(
                os.getenv("PRIORITY_SUBJECTS"),
                (),
            ),
            priority_keywords=_parse_csv(
                os.getenv("PRIORITY_KEYWORDS"),
                (),
            ),
            priority_only=_parse_bool(os.getenv("PRIORITY_ONLY"), False),
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID"),
            send_telegram=_parse_bool(os.getenv("SEND_TELEGRAM"), True),
            site_url=_default_site_url(),
            site_title=os.getenv("SITE_TITLE", "증권사 리포트 데일리"),
        )
