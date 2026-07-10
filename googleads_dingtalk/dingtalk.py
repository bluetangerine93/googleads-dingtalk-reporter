from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import urllib.parse
import urllib.request

from .config import Settings


def _signed_webhook(webhook: str, secret: str) -> str:
    timestamp = str(round(time.time() * 1000))
    string_to_sign = f"{timestamp}\n{secret}".encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), string_to_sign, digestmod=hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(digest))
    sep = "&" if "?" in webhook else "?"
    return f"{webhook}{sep}timestamp={timestamp}&sign={sign}"


def send_markdown(settings: Settings, title: str, text: str, dry_run: bool = False) -> None:
    send_markdown_to(
        settings.dingtalk_webhook,
        settings.dingtalk_secret,
        settings.dingtalk_keyword,
        title,
        text,
        dry_run=dry_run,
    )


def send_markdown_to(webhook: str, secret: str, keyword: str, title: str, text: str, dry_run: bool = False) -> None:
    if keyword and keyword not in title and keyword not in text:
        text = f"{keyword}\n\n{text}"
    payload = {
        "msgtype": "markdown",
        "markdown": {
            "title": title,
            "text": text,
        },
    }
    if dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    webhook = _signed_webhook(webhook, secret) if secret else webhook
    request = urllib.request.Request(
        webhook,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        result = json.loads(response.read().decode("utf-8"))
    if result.get("errcode") != 0:
        raise RuntimeError(f"DingTalk send failed: {result}")
