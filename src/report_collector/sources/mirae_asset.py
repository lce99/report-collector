from __future__ import annotations

from datetime import date
from urllib.parse import urlencode
from urllib.parse import urljoin
import re

from bs4 import Tag

from report_collector.config import Settings
from report_collector.models import Report
from report_collector.sources.common import (
    build_recent_window,
    category_label,
    fetch_soup,
    infer_category,
    normalize_space,
    split_text_lines,
)


BASE_URL = "https://securities.miraeasset.com"
LIST_URL = BASE_URL + "/bbs/board/message/list.do"
DETAIL_URL = BASE_URL + "/bbs/board/message/view.do"
CATEGORY_ID = "1521"
BROKER_NAME = "미래에셋증권"
DETAIL_END_MARKERS = {
    "다음글",
    "이전글",
    "본 내용은 투자 판단의 참고 사항이며, 투자판단의 최종 책임은 본 게시물을 열람하시는 이용자에게 있습니다.",
}


def _parse_list_date(value: str) -> date:
    return date.fromisoformat(normalize_space(value))


def _build_list_url(target_date: date, page: int) -> str:
    start_date, end_date = build_recent_window(target_date)
    params = {
        "categoryId": CATEGORY_ID,
        "searchType": "2",
        "searchStartYear": f"{start_date.year:04d}",
        "searchStartMonth": f"{start_date.month:02d}",
        "searchStartDay": f"{start_date.day:02d}",
        "searchEndYear": f"{end_date.year:04d}",
        "searchEndMonth": f"{end_date.month:02d}",
        "searchEndDay": f"{end_date.day:02d}",
        "listType": "1",
        "startId": "zzzzz~",
        "startPage": "1",
        "curPage": str(page),
        "direction": "1",
    }
    return LIST_URL + "?" + urlencode(params)


def _split_title(anchor: Tag) -> tuple[str | None, str]:
    parts = [normalize_space(part) for part in anchor.stripped_strings if normalize_space(part)]
    if not parts:
        return None, ""
    if len(parts) == 1:
        return None, parts[0]
    return parts[0], " ".join(parts[1:])


def _extract_detail_info(onclick_text: str) -> tuple[str, str] | None:
    match = re.search(r"view\('([^']+)','([^']+)'\)", onclick_text)
    if not match:
        return None
    return match.group(1), match.group(2)


def _extract_pdf_url(cell: Tag) -> str | None:
    anchor = cell.find("a", href=True)
    if not anchor:
        return None
    href = anchor["href"]
    match = re.search(r"downConfirm\('([^']+)'", href)
    if not match:
        return None
    return match.group(1)


class MiraeAssetCollector:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def collect(self, target_date: date) -> list[Report]:
        reports_by_id: dict[str, Report] = {}

        for page in range(1, self.settings.page_depth + 1):
            rows = self._parse_list_page(_build_list_url(target_date, page))
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

        for report in reports_by_id.values():
            self._hydrate_detail(report)

        return sorted(
            reports_by_id.values(),
            key=lambda item: (item.category, item.published_date, item.display_title),
        )

    def _parse_list_page(self, url: str) -> list[tuple[Report, date]]:
        soup = fetch_soup(url, settings=self.settings, encoding="cp949")
        rows = soup.select("table.bbs_linetype2 tbody tr")
        parsed: list[tuple[Report, date]] = []

        for row in rows:
            columns = row.find_all("td")
            if len(columns) < 4:
                continue

            row_date = _parse_list_date(columns[0].get_text(" ", strip=True))
            title_anchor = columns[1].find("a", id=re.compile(r"^bbsTitle"))
            if not title_anchor:
                continue

            detail_info = _extract_detail_info(title_anchor.get("href", ""))
            if not detail_info:
                continue
            message_id, message_number = detail_info

            subject, title = _split_title(title_anchor)
            detail_url = (
                f"{DETAIL_URL}?messageId={message_id}"
                f"&messageNumber={message_number}&categoryId={CATEGORY_ID}"
            )
            body = ""
            category = infer_category(title, subject=subject, body=body)

            parsed.append(
                (
                    Report(
                        source="mirae_asset_official",
                        category=category,
                        category_label=category_label(category),
                        report_id=f"mirae-{message_id}",
                        title=title,
                        broker=BROKER_NAME,
                        published_date=row_date.isoformat(),
                        detail_url=detail_url,
                        pdf_url=_extract_pdf_url(columns[2]),
                        subject=subject,
                        analyst=normalize_space(columns[3].get_text(" ", strip=True)) or None,
                    ),
                    row_date,
                )
            )

        return parsed

    def _hydrate_detail(self, report: Report) -> None:
        try:
            soup = fetch_soup(
                report.detail_url,
                settings=self.settings,
                encoding="cp949",
                referer=LIST_URL,
            )
        except Exception:
            return

        lines = split_text_lines(soup)
        try:
            title_index = lines.index("전체 글읽기") + 1
            author_index = lines.index("작성자")
            date_index = lines.index("작성일")
        except ValueError:
            return

        if title_index < len(lines):
            detail_title = lines[title_index]
            if detail_title:
                report.title = detail_title
                report.subject = None

        if author_index + 1 < len(lines):
            report.analyst = lines[author_index + 1]

        if date_index + 1 < len(lines):
            try:
                report.published_date = date.fromisoformat(lines[date_index + 1]).isoformat()
            except ValueError:
                pass

        body_start = date_index + 2
        body_end = len(lines)
        for index in range(body_start, len(lines)):
            if lines[index] in DETAIL_END_MARKERS:
                body_end = index
                break

        body_lines = [
            line
            for line in lines[body_start:body_end]
            if line not in {"작성자", "작성일"}
        ]
        report.body = "\n".join(body_lines).strip()

        category = infer_category(
            report.title,
            subject=report.subject,
            body=report.body,
        )
        report.category = category
        report.category_label = category_label(category)
