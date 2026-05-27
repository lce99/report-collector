from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any
import re

if TYPE_CHECKING:
    from report_collector.models import Report


PROFIT_LABELS = {
    "OP": ("operating_profit", "영업이익"),
    "영업이익": ("operating_profit", "영업이익"),
    "순이익": ("net_profit", "순이익"),
    "지배순이익": ("net_profit", "지배순이익"),
    "지배주주순이익": ("net_profit", "지배주주순이익"),
    "EPS": ("eps", "EPS"),
}

ESTIMATE_SIGNAL_LABELS = {
    "earnings_estimate_up": "이익 추정 상향/증가",
    "earnings_estimate_down": "이익 추정 하향/감소",
    "margin_estimate_up": "마진율 추정 상승/개선",
    "margin_estimate_down": "마진율 추정 하락/악화",
}

PERIOD_RE = (
    r"(?:(?:[12]\d{3}|[’']?\d{2})\s*(?:년|F|E)?|"
    r"[1-4]Q\s*(?:\d{2,4})?|[1-4]분기)?"
)
NUMBER_RE = r"[+-]?\d+(?:,\d{3})*(?:\.\d+)?"

PROFIT_METRIC_RE = re.compile(
    rf"(?P<period>{PERIOD_RE})\s*"
    r"(?P<label>지배주주순이익|지배순이익|영업이익|순이익|EPS|OP)"
    r"(?:은|는|이|가|을|를|:|의|으로)?\s*"
    r"(?:약|전망|추정|예상|기록|컨센서스|시장 기대치|당사 추정치)?\s*"
    rf"(?P<value>{NUMBER_RE})\s*(?P<unit>조원|억원|십억원|원)",
    re.IGNORECASE,
)

MARGIN_METRIC_RE = re.compile(
    rf"(?P<label>OPM|영업이익률|영업마진|마진율|순이익률)"
    r"(?:은|는|이|가|:|의)?\s*"
    rf"(?P<value>{NUMBER_RE})\s*%",
    re.IGNORECASE,
)

CHANGE_POINT_RE = re.compile(rf"(?P<value>{NUMBER_RE})\s*%?p", re.IGNORECASE)

SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。！？])\s+|[\r\n]+")
EARNINGS_TERMS_RE = re.compile(r"(영업이익|순이익|지배이익|EPS|실적|이익|추정치|전망치|컨센서스)")
MARGIN_TERMS_RE = re.compile(r"(마진|수익성|영업이익률|OPM|스프레드)")
UP_TERMS_RE = re.compile(r"(상향|증가|개선|상회|확대|높아|높였|올려|회복|턴어라운드|흑자전환|흑전)")
DOWN_TERMS_RE = re.compile(r"(하향|감소|악화|하회|부진|축소|낮아|낮췄|적자전환|적전)")


def _normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _trim_text(value: str, limit: int = 160) -> str:
    cleaned = _normalize_space(value)
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def _numeric(value: str) -> float | None:
    try:
        return float(value.replace(",", ""))
    except (TypeError, ValueError):
        return None


def _value_to_100m(value: float, unit: str) -> float | None:
    if unit == "조원":
        return value * 10000
    if unit == "십억원":
        return value * 10
    if unit == "억원":
        return value
    return None


def _sentence_for_match(text: str, start: int, end: int) -> str:
    left = max(text.rfind(".", 0, start), text.rfind("\n", 0, start), text.rfind("。", 0, start))
    right_candidates = [
        index for index in (text.find(".", end), text.find("\n", end), text.find("。", end)) if index >= 0
    ]
    right = min(right_candidates) if right_candidates else min(len(text), end + 140)
    return text[left + 1 : right + 1]


def _iter_sentences(text: str) -> Iterable[str]:
    for raw in SENTENCE_SPLIT_RE.split(text):
        sentence = _normalize_space(raw)
        if sentence:
            yield sentence


def _metric_key(metric: dict[str, Any]) -> tuple[Any, ...]:
    return (
        metric.get("metric"),
        metric.get("period"),
        metric.get("value"),
        metric.get("unit"),
    )


def extract_estimate_metrics(text: str, *, limit: int = 12) -> list[dict[str, Any]]:
    cleaned = _normalize_space(text)
    if not cleaned:
        return []

    metrics: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    earnings_limit = max(1, limit - 4)
    earnings_count = 0

    for match in PROFIT_METRIC_RE.finditer(cleaned):
        if earnings_count >= earnings_limit:
            break
        label_raw = match.group("label").upper() if match.group("label").upper() == "OP" else match.group("label")
        metric_name, display_label = PROFIT_LABELS.get(label_raw, (label_raw.lower(), label_raw))
        value = _numeric(match.group("value"))
        if value is None:
            continue

        unit = match.group("unit")
        metric: dict[str, Any] = {
            "metric": metric_name,
            "metric_group": "earnings",
            "label": display_label,
            "period": _normalize_space(match.group("period") or "") or None,
            "value": value,
            "unit": unit,
            "source_excerpt": _trim_text(_sentence_for_match(cleaned, match.start(), match.end())),
        }
        value_100m = _value_to_100m(value, unit)
        if value_100m is not None:
            metric["value_krw_100m"] = round(value_100m, 2)
        if unit == "원":
            metric["value_won"] = round(value, 2)

        key = _metric_key(metric)
        if key in seen:
            continue
        seen.add(key)
        metrics.append(metric)
        earnings_count += 1

    for match in MARGIN_METRIC_RE.finditer(cleaned):
        value = _numeric(match.group("value"))
        if value is None:
            continue
        tail = cleaned[match.end() : match.end() + 24]
        change_match = CHANGE_POINT_RE.search(tail)
        metric = {
            "metric": "operating_margin",
            "metric_group": "margin",
            "label": match.group("label").upper() if match.group("label").upper() == "OPM" else match.group("label"),
            "period": None,
            "value": value,
            "unit": "%",
            "value_pct": round(value, 2),
            "source_excerpt": _trim_text(_sentence_for_match(cleaned, match.start(), match.end())),
        }
        if change_match:
            change_value = _numeric(change_match.group("value"))
            if change_value is not None:
                metric["change_pctp"] = round(change_value, 2)

        key = _metric_key(metric)
        if key in seen:
            continue
        seen.add(key)
        metrics.append(metric)
        if len(metrics) >= limit:
            return metrics

    return metrics


def extract_estimate_signal_types(text: str) -> list[str]:
    signal_types: list[str] = []
    for sentence in _iter_sentences(text):
        has_earnings = bool(EARNINGS_TERMS_RE.search(sentence))
        has_margin = bool(MARGIN_TERMS_RE.search(sentence))
        has_up = bool(UP_TERMS_RE.search(sentence))
        has_down = bool(DOWN_TERMS_RE.search(sentence))

        if has_earnings and has_up:
            signal_types.append("earnings_estimate_up")
        if has_earnings and has_down:
            signal_types.append("earnings_estimate_down")
        if has_margin and has_up:
            signal_types.append("margin_estimate_up")
        if has_margin and has_down:
            signal_types.append("margin_estimate_down")

    return list(dict.fromkeys(signal_types))


def estimate_reasons_for_types(signal_types: Iterable[str]) -> list[str]:
    return [
        ESTIMATE_SIGNAL_LABELS[signal_type]
        for signal_type in dict.fromkeys(signal_types)
        if signal_type in ESTIMATE_SIGNAL_LABELS
    ]


def annotate_report_estimates(report: Report) -> None:
    text = " ".join(
        part
        for part in (
            report.title,
            report.subject,
            report.summary,
            report.excerpt,
            report.source_text,
        )
        if part
    )
    report.estimate_metrics = extract_estimate_metrics(text)
    report.estimate_signal_types = extract_estimate_signal_types(text)
    report.estimate_reasons = estimate_reasons_for_types(report.estimate_signal_types)
