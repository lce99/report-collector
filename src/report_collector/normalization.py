from __future__ import annotations

from typing import TYPE_CHECKING
import re

if TYPE_CHECKING:
    from report_collector.models import Report


OPINION_ALIASES = {
    "buy": "buy",
    "매수": "buy",
    "strongbuy": "strong_buy",
    "강력매수": "strong_buy",
    "hold": "hold",
    "neutral": "hold",
    "중립": "hold",
    "marketperform": "hold",
    "marketperformer": "hold",
    "tradingbuy": "trading_buy",
    "reduce": "sell",
    "underperform": "sell",
    "sell": "sell",
    "매도": "sell",
    "outperform": "outperform",
}

OPINION_RANKS = {
    "strong_buy": 5,
    "buy": 4,
    "outperform": 4,
    "trading_buy": 3,
    "hold": 2,
    "sell": 1,
}


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def normalize_subject_name(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = normalize_space(value)
    return cleaned or None


def normalize_subject_key(value: str | None) -> str | None:
    cleaned = normalize_subject_name(value)
    if not cleaned:
        return None
    slug = re.sub(r"[^0-9a-z가-힣]+", "-", cleaned.lower()).strip("-")
    return slug or None


def parse_target_price_value(value: str | None) -> int | None:
    if not value:
        return None

    cleaned = normalize_space(value).lower().replace(",", "")
    match = re.search(r"\d+(?:\.\d+)?", cleaned)
    if not match:
        return None

    amount = float(match.group(0))
    if "만원" in cleaned:
        amount *= 10000
    elif "천원" in cleaned:
        amount *= 1000

    return int(round(amount))


def normalize_opinion_value(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = normalize_space(value).lower()
    token = re.sub(r"[\s/_-]+", "", cleaned)
    return OPINION_ALIASES.get(token, token or None)


def opinion_rank(value: str | None) -> int | None:
    normalized = normalize_opinion_value(value)
    if not normalized:
        return None
    return OPINION_RANKS.get(normalized)


def opinion_change_direction(
    current_value: str | None,
    previous_value: str | None,
) -> str | None:
    current_rank = opinion_rank(current_value)
    previous_rank = opinion_rank(previous_value)
    if current_rank is None or previous_rank is None or current_rank == previous_rank:
        return None
    return "up" if current_rank > previous_rank else "down"


def annotate_report_normalized_fields(report: Report) -> None:
    report.subject = normalize_subject_name(report.subject)
    report.subject_key = normalize_subject_key(report.subject)
    report.target_price_value = parse_target_price_value(report.target_price)
    report.opinion_normalized = normalize_opinion_value(report.opinion)
