from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from report_collector.config import Settings  # noqa: E402
from report_collector.telegram_bot import process_command_updates  # noqa: E402


def _parse_args() -> ArgumentParser:
    parser = ArgumentParser(description="Reply to Telegram report bot commands.")
    parser.add_argument("--docs-root", default="docs")
    parser.add_argument("--state-path", default="")
    parser.add_argument("--timeout", type=int, default=0)
    return parser


def main() -> int:
    args = _parse_args().parse_args()
    settings = Settings.from_env()
    if not settings.telegram_bot_token:
        print("TELEGRAM_BOT_TOKEN is not configured.")
        return 1

    processed = process_command_updates(
        settings.telegram_bot_token,
        docs_root=args.docs_root,
        allowed_chat_id=settings.telegram_chat_id,
        state_path=args.state_path or None,
        timeout=args.timeout,
    )
    print(f"processed {processed} command(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
