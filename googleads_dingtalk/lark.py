from __future__ import annotations

import json
import urllib.request
from typing import Any


def _post_payload(webhook: str, payload: dict[str, Any], dry_run: bool) -> None:
    if dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    request = urllib.request.Request(
        webhook,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        result = json.loads(response.read().decode("utf-8"))
    if result.get("code") != 0:
        raise RuntimeError(f"Lark send failed: {result}")


def send_text(webhook: str, keyword: str, text: str, dry_run: bool = False) -> None:
    if keyword and keyword not in text:
        text = f"{keyword}\n\n{text}"
    payload = {
        "msg_type": "text",
        "content": {
            "text": text,
        },
    }
    _post_payload(webhook, payload, dry_run)


def send_interactive_card(
    webhook: str,
    keyword: str,
    card: dict[str, Any],
    dry_run: bool = False,
) -> None:
    title = card.get("header", {}).get("title", {})
    if keyword and keyword not in title.get("content", ""):
        title["content"] = f"{keyword} | {title.get('content', '')}".strip()
        card.setdefault("header", {})["title"] = title
    payload = {
        "msg_type": "interactive",
        "card": card,
    }
    _post_payload(webhook, payload, dry_run)
