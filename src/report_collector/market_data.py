from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import re

from bs4 import BeautifulSoup


@dataclass(frozen=True, slots=True)
class PricePoint:
    date: date
    close: float
    volume: int | None = None


def normalize_ticker(value: object) -> str | None:
    match = re.search(r"(?<!\d)(\d{6})(?!\d)", str(value or ""))
    if not match:
        return None
    return match.group(1)


def parse_naver_daily_price_html(html: str) -> list[PricePoint]:
    soup = BeautifulSoup(html, "html.parser")
    points: list[PricePoint] = []

    for row in soup.select("table.type2 tr"):
        cells = [cell.get_text(" ", strip=True) for cell in row.find_all("td")]
        if len(cells) < 6:
            continue
        try:
            point_date = date.fromisoformat(cells[0].replace(".", "-"))
            close = _parse_number(cells[1])
        except ValueError:
            continue
        if close is None:
            continue
        points.append(
            PricePoint(
                date=point_date,
                close=float(close),
                volume=_parse_number(cells[-1]),
            )
        )

    return points


class NaverDailyPriceProvider:
    source_name = "naver_daily_price"

    def __init__(
        self,
        *,
        user_agent: str,
        timeout_seconds: int,
        max_pages: int = 8,
        fetch_html: Callable[[str], str] | None = None,
    ) -> None:
        self.user_agent = user_agent
        self.timeout_seconds = timeout_seconds
        self.max_pages = max(1, max_pages)
        self._fetch_html = fetch_html

    def calculate_return(
        self,
        ticker: str,
        selected_date: date,
        due_date: date,
    ) -> dict[str, object] | None:
        normalized_ticker = normalize_ticker(ticker)
        if not normalized_ticker:
            return None

        prices = self.fetch_prices(
            normalized_ticker,
            start=selected_date - timedelta(days=7),
            end=due_date,
        )
        entry = _latest_on_or_before(prices, selected_date)
        exit_ = _latest_on_or_before(prices, due_date)
        if entry is None or exit_ is None or entry.close <= 0:
            return None

        payload: dict[str, object] = {
            "ticker": normalized_ticker,
            "price_source": self.source_name,
            "entry_price_date": entry.date.isoformat(),
            "entry_close": entry.close,
            "exit_price_date": exit_.date.isoformat(),
            "exit_close": exit_.close,
            "price_return_pct": round(((exit_.close - entry.close) / entry.close) * 100, 2),
        }
        if entry.volume and exit_.volume is not None:
            payload["entry_volume"] = entry.volume
            payload["exit_volume"] = exit_.volume
            payload["volume_change_pct"] = round(
                ((exit_.volume - entry.volume) / entry.volume) * 100,
                2,
            )
        return payload

    def fetch_prices(
        self,
        ticker: str,
        *,
        start: date,
        end: date,
    ) -> list[PricePoint]:
        normalized_ticker = normalize_ticker(ticker)
        if not normalized_ticker:
            return []

        points_by_date: dict[date, PricePoint] = {}
        for page in range(1, self.max_pages + 1):
            points = parse_naver_daily_price_html(self._fetch_price_page(normalized_ticker, page))
            if not points:
                break
            for point in points:
                if start <= point.date <= end:
                    points_by_date[point.date] = point
            if min(point.date for point in points) < start:
                break

        return [points_by_date[key] for key in sorted(points_by_date)]

    def _fetch_price_page(self, ticker: str, page: int) -> str:
        url = "https://finance.naver.com/item/sise_day.naver?" + urlencode(
            {"code": ticker, "page": page}
        )
        if self._fetch_html:
            return self._fetch_html(url)
        request = Request(url, headers={"User-Agent": self.user_agent})
        with urlopen(request, timeout=self.timeout_seconds) as response:
            return response.read().decode("euc-kr", errors="ignore")


def _parse_number(value: str) -> int | None:
    digits = re.sub(r"[^\d]", "", value)
    if not digits:
        return None
    return int(digits)


def _latest_on_or_before(points: list[PricePoint], target: date) -> PricePoint | None:
    candidates = [point for point in points if point.date <= target]
    if not candidates:
        return None
    return max(candidates, key=lambda point: point.date)
