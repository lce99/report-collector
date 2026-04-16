from __future__ import annotations

from io import BytesIO
from urllib.request import Request, urlopen
import re

from pypdf import PdfReader


def _normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def extract_pdf_text(
    pdf_url: str,
    *,
    user_agent: str,
    timeout_seconds: int,
    page_limit: int,
    char_limit: int,
    referer: str | None = None,
) -> str:
    request = Request(
        pdf_url,
        headers={
            "User-Agent": user_agent,
            **({"Referer": referer} if referer else {}),
        },
    )
    with urlopen(request, timeout=timeout_seconds) as response:
        payload = response.read()

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
        text = _normalize_space(text)
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
