from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader

from report_collector.http import fetch_bytes
from report_collector.normalization import normalize_space


def extract_pdf_text(
    pdf_url: str,
    *,
    user_agent: str,
    timeout_seconds: int,
    page_limit: int,
    char_limit: int,
    referer: str | None = None,
) -> str:
    payload = fetch_bytes(
        pdf_url,
        user_agent=user_agent,
        timeout_seconds=timeout_seconds,
        referer=referer,
    )

    reader = PdfReader(BytesIO(payload))
    chunks: list[str] = []
    total_chars = 0

    for page_index, page in enumerate(reader.pages):
        if page_index >= max(1, page_limit):
            break
        try:
            text = page.extract_text() or ""
        except Exception:
            continue
        text = normalize_space(text)
        if not text:
            continue

        remaining = char_limit - total_chars
        if remaining <= 0:
            break

        snippet = text[:remaining].strip()
        if not snippet:
            continue

        chunks.append(snippet)
        total_chars += len(snippet)

        if total_chars >= char_limit:
            break

    return "\n".join(chunks).strip()
