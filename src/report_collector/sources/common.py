from __future__ import annotations

from datetime import date, timedelta
from urllib.request import Request, urlopen
import re

from bs4 import BeautifulSoup

from report_collector.config import Settings


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


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


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
