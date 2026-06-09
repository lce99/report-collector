from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING, Callable
from urllib.request import Request, urlopen
import re

from bs4 import BeautifulSoup

from report_collector.config import Settings
from report_collector.normalization import normalize_space

if TYPE_CHECKING:
    from report_collector.models import Report


CATEGORY_LABELS = {
    "company": "종목분석",
    "industry": "산업분석",
    "economy": "경제분석",
    "invest": "투자정보",
    "market": "시황정보",
    "debenture": "채권분석",
}

COMPANY_HINTS = (
    " not rated",
    " buy",
    " hold",
    " neutral",
    " outperform",
    " underperform",
    " review",
    " preview",
)

INDUSTRY_HINTS = (
    "반도체",
    "배터리",
    "신재생",
    "에너지",
    "ess",
    "조선",
    "철강",
    "정유",
    "유틸리티",
    "은행",
    "보험",
    "자동차",
    "산업",
    "업종",
)

MARKET_HINTS = (
    "한눈에 투데이",
    "마켓",
    "market",
    "snapshot",
    "weekly market review",
    "브리핑",
    "브리프",
    "투자전략",
    "주간 시장",
    "금리",
    "채권",
    "환율",
    "fomc",
    "cpi",
    "매크로",
    "경제",
)


def parse_int(value: str) -> int:
    digits = re.sub(r"[^\d]", "", value)
    return int(digits) if digits else 0


def fetch_html(
    url: str,
    *,
    settings: Settings,
    encoding: str,
    referer: str | None = None,
) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": settings.user_agent,
            **({"Referer": referer} if referer else {}),
        },
    )
    with urlopen(request, timeout=settings.request_timeout_seconds) as response:
        return response.read().decode(encoding, errors="ignore")


def fetch_soup(
    url: str,
    *,
    settings: Settings,
    encoding: str,
    referer: str | None = None,
) -> BeautifulSoup:
    return BeautifulSoup(
        fetch_html(
            url,
            settings=settings,
            encoding=encoding,
            referer=referer,
        ),
        "html.parser",
    )


def split_text_lines(soup: BeautifulSoup) -> list[str]:
    return [
        normalize_space(line)
        for line in soup.get_text("\n").splitlines()
        if normalize_space(line)
    ]


def normalize_report_key(value: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]+", "", value.lower())


def infer_category(
    title: str,
    *,
    subject: str | None = None,
    body: str = "",
) -> str:
    haystack = " ".join(part for part in (subject, title, body) if part)
    lowered = haystack.lower()

    if subject and subject.endswith("기업분석"):
        return "company"
    if subject and subject.endswith("산업분석"):
        return "industry"

    if re.search(r"\([A-Z0-9./ -]{2,}\)", title):
        return "company"
    if ":" in title and any(token in lowered for token in COMPANY_HINTS):
        return "company"
    if any(token in lowered for token in INDUSTRY_HINTS):
        return "industry"
    if any(token in lowered for token in MARKET_HINTS):
        return "market"
    if ":" in title:
        return "company"
    return "invest"


def category_label(category: str) -> str:
    return CATEGORY_LABELS.get(category, "투자정보")


def build_recent_window(target_date: date, days: int = 365) -> tuple[date, date]:
    return target_date - timedelta(days=days), target_date


def collect_pages_for_date(
    target_date: date,
    *,
    page_depth: int,
    parse_page: Callable[[int], list[tuple["Report", date]]],
) -> dict[str, "Report"]:
    """Walk paginated list pages, keeping reports published on target_date.

    Stops when a page has no rows, or when it contains no target-date rows
    and every row is older than the target date.
    """
    reports_by_id: dict[str, "Report"] = {}

    for page in range(1, page_depth + 1):
        rows = parse_page(page)
        if not rows:
            break

        page_has_target_date = False
        page_all_older = True

        for report, row_date in rows:
            if row_date == target_date:
                page_has_target_date = True
                page_all_older = False
                reports_by_id.setdefault(report.report_id, report)
            elif row_date > target_date:
                page_all_older = False

        if not page_has_target_date and page_all_older:
            break

    return reports_by_id
