from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from .config import load_settings, require_config
from .lark import send_interactive_card


def run_visa_balance_reminder(period: str = "daily", dry_run: bool = False) -> None:
    settings = load_settings()
    require_config({
        "LARK_BALANCE_WEBHOOK": settings.lark_balance_webhook,
    })
    tz = ZoneInfo("Asia/Shanghai")
    now = datetime.now(tz)
    card = _format_reminder_card(now, period)
    send_interactive_card(
        settings.lark_balance_webhook,
        settings.lark_balance_keyword,
        card,
        dry_run=dry_run,
    )


def _format_reminder_card(now: datetime, period: str) -> dict:
    period_label = {
        "before_work": "Before Work",
        "before_off_work": "Before Off Work",
    }.get(period, "Daily")
    return {
        "config": {
            "wide_screen_mode": True,
        },
        "header": {
            "template": "blue",
            "title": {
                "tag": "plain_text",
                "content": "notification | Visa Auto Pay Check",
            },
        },
        "elements": [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        f"**Time:** {now:%Y-%m-%d %H:%M} CST\n"
                        f"**Reminder:** {period_label}\n"
                        "**Action:** Please check whether the auto pay Visa card has enough available balance."
                    ),
                },
            },
            {
                "tag": "hr",
            },
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": "**Accounts:** PocketMitra-02 / PocketMitra-04",
                },
            },
        ],
    }
