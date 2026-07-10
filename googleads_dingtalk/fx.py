from __future__ import annotations

import json
import urllib.request
from datetime import date
from decimal import Decimal
from pathlib import Path

from .config import ROOT, Settings


FX_CACHE = ROOT / "data" / "fx_rates.json"


def _read_cache() -> dict:
    if not FX_CACHE.exists():
        return {}
    return json.loads(FX_CACHE.read_text(encoding="utf-8"))


def _write_cache(cache: dict) -> None:
    FX_CACHE.parent.mkdir(parents=True, exist_ok=True)
    FX_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def get_monthly_rate(settings: Settings, today: date) -> Decimal:
    if settings.account_currency != "INR" or settings.target_currency != "USD":
        raise ValueError("Only INR to USD is configured in this reporter")
    month_key = today.strftime("%Y-%m")
    cache = _read_cache()
    if month_key in cache:
        return Decimal(str(cache[month_key]["rate"]))
    if settings.inr_usd_rate:
        rate = Decimal(settings.inr_usd_rate)
        source = "env"
    else:
        rate, source = _fetch_inr_usd_rate()
    cache[month_key] = {
        "from": settings.account_currency,
        "to": settings.target_currency,
        "rate": str(rate),
        "source": source,
    }
    _write_cache(cache)
    return rate


def _open_json(url: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "googleads-dingtalk-reporter/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _fetch_inr_usd_rate() -> tuple[Decimal, str]:
    errors: list[str] = []
    providers = (
        (
            "open.er-api.com",
            "https://open.er-api.com/v6/latest/INR",
            lambda payload: payload["rates"]["USD"],
        ),
        (
            "frankfurter.app",
            "https://api.frankfurter.app/latest?from=INR&to=USD",
            lambda payload: payload["rates"]["USD"],
        ),
    )
    for source, url, parser in providers:
        try:
            payload = _open_json(url)
            return Decimal(str(parser(payload))), source
        except Exception as exc:  # pragma: no cover - network fallback path
            errors.append(f"{source}: {exc}")
    raise RuntimeError("Unable to fetch INR/USD rate. Set INR_USD_RATE in .env. " + " | ".join(errors))
