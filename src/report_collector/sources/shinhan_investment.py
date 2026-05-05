from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from html import unescape
import json
import re
from urllib.parse import urlencode
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from report_collector.config import Settings
from report_collector.models import Report
from report_collector.sources.common import (
    category_label,
    fetch_html,
    normalize_space,
    parse_int,
)


BBS_BASE_URL = "https://bbs2.shinhansec.com"
BBS_LIST_URL = BBS_BASE_URL + "/bbs/list/{board}"
BROKER_NAME = "신한투자증권"


@dataclass(frozen=True, slots=True)
class ShinhanBoardConfig:
    board: str
    category: str


BOARD_CONFIGS = (
    ShinhanBoardConfig("gicompanyanalyst", "company"),
    ShinhanBoardConfig("giindustry", "industry"),
    ShinhanBoardConfig("gicomment", "market"),
    ShinhanBoardConfig("gieconomy", "economy"),
)


def _clean_optional_value(value: object) -> str | None:
    text = normalize_space(str(value or ""))
    if not text or text == "-":
        return None
    return text


def _absolute_url(value: object) -> str | None:
    text = _clean_optional_value(value)
    if not text:
        return None
    return urljoin(BBS_BASE_URL, text)


def _parse_shinhan_date(value: object) -> date:
    text = _clean_optional_value(value) or ""
    return date.fromisoformat(text.replace(".", "-"))


def _clean_body_text(value: object) -> str:
    raw = unescape(str(value or "")).replace("\xa0", " ")
    if not raw:
        return ""

    soup = BeautifulSoup(raw, "html.parser")
    return "\n".join(
        line
        for line in (
            normalize_space(unescape(part))
            for part in soup.get_text("\n").splitlines()
        )
        if line
    )


def _extract_target_price(body: str) -> str | None:
    for line in body.splitlines():
        if "목표주가" not in line:
            continue
        prices = re.findall(r"\d[\d,]*(?:\.\d+)?\s*(?:만원|천원|원)", line)
        if prices:
            return normalize_space(prices[-1]).replace(" ", "")
    return None


def _build_list_url(
    board: str,
    *,
    page: int,
    start_page: int,
    start_id: str | None,
) -> str:
    params = {
        "curPage": str(page),
        "startPage": str(start_page),
    }
    if start_id:
        params["startId"] = start_id
    return BBS_LIST_URL.format(board=board) + "?" + urlencode(params)


def _parse_item(item: dict[str, object], config: ShinhanBoardConfig) -> Report:
    message_id = _clean_optional_value(item.get("fn"))
    if not message_id:
        raise ValueError("missing Shinhan report id")

    title = _clean_optional_value(item.get("f1"))
    if not title:
        raise ValueError(f"missing Shinhan report title: {message_id}")

    published_date = _parse_shinhan_date(item.get("f0")).isoformat()
    body = _clean_body_text(item.get("f7"))
    subject = _clean_optional_value(item.get("f2"))
    if subject and subject in title:
        subject = None

    report = Report(
        source="shinhan_investment_official",
        category=config.category,
        category_label=category_label(config.category),
        report_id=f"shinhan-{config.board}-{message_id}",
        title=title,
        broker=BROKER_NAME,
        published_date=published_date,
        detail_url=(
            _absolute_url(item.get("f10"))
            or _absolute_url(item.get("f3"))
            or BBS_LIST_URL.format(board=config.board)
        ),
        pdf_url=_absolute_url(item.get("f3")),
        subject=subject,
        views=parse_int(_clean_optional_value(item.get("f5")) or ""),
        analyst=_clean_optional_value(item.get("f4")),
        target_price=_extract_target_price(body),
        opinion=_clean_optional_value(item.get("f6")),
        body=body,
    )
    return report


class ShinhanInvestmentCollector:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def collect(self, target_date: date) -> list[Report]:
        reports_by_id: dict[str, Report] = {}
        enabled_categories = set(self.settings.categories)

        for config in BOARD_CONFIGS:
            if config.category not in enabled_categories:
                continue
            for report, row_date in self._iter_board_reports(config, target_date):
                if row_date == target_date:
                    reports_by_id.setdefault(report.report_id, report)

        return sorted(
            reports_by_id.values(),
            key=lambda item: (item.category, item.published_date, item.display_title),
        )

    def _iter_board_reports(
        self,
        config: ShinhanBoardConfig,
        target_date: date,
    ) -> list[tuple[Report, date]]:
        parsed: list[tuple[Report, date]] = []
        start_page = 1
        start_id: str | None = None

        for page in range(1, self.settings.page_depth + 1):
            payload = self._fetch_payload(
                config.board,
                page=page,
                start_page=start_page,
                start_id=start_id,
            )
            items = payload.get("list", [])
            if not isinstance(items, list) or not items:
                break

            page_has_target_date = False
            page_all_older = True

            for item in items:
                if not isinstance(item, dict):
                    continue
                try:
                    report = _parse_item(item, config)
                    row_date = date.fromisoformat(report.published_date)
                except (TypeError, ValueError):
                    continue

                parsed.append((report, row_date))
                if row_date == target_date:
                    page_has_target_date = True
                    page_all_older = False
                elif row_date > target_date:
                    page_all_older = False

            if not page_has_target_date and page_all_older:
                break

            next_start_id = self._next_start_id(payload)
            if not next_start_id:
                break
            start_id = next_start_id

        return parsed

    def _fetch_payload(
        self,
        board: str,
        *,
        page: int,
        start_page: int,
        start_id: str | None,
    ) -> dict[str, object]:
        url = _build_list_url(
            board,
            page=page,
            start_page=start_page,
            start_id=start_id,
        )
        raw = fetch_html(url, settings=self.settings, encoding="utf-8")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError(f"unexpected Shinhan payload for {board}")
        return payload

    def _next_start_id(self, payload: dict[str, object]) -> str | None:
        page_info = payload.get("pageInfo")
        if not isinstance(page_info, dict):
            return None

        pages = page_info.get("pages")
        if not isinstance(pages, list) or len(pages) < 2:
            return None

        return _clean_optional_value(pages[-1])
