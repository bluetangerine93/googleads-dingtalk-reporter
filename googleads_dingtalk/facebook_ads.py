from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .config import Settings


@dataclass
class FacebookMetrics:
    spend_inr: Decimal = Decimal("0")
    registers: float = 0.0
    purchases: float = 0.0

    @property
    def cost_per_register_inr(self) -> Decimal:
        if self.registers <= 0:
            return Decimal("0")
        return self.spend_inr / Decimal(str(self.registers))

    @property
    def cost_per_purchase_inr(self) -> Decimal:
        if self.purchases <= 0:
            return Decimal("0")
        return self.spend_inr / Decimal(str(self.purchases))


@dataclass
class FacebookAccountReport:
    name: str
    account_id: str
    metrics: FacebookMetrics


class FacebookAdsReporter:
    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def enabled(self) -> bool:
        return bool(self.settings.fb_access_token and self.settings.fb_daily_accounts)

    def daily_reports(self, day: date) -> list[FacebookAccountReport]:
        return [
            FacebookAccountReport(name, account_id, self._metrics_for_day(account_id, day))
            for name, account_id in self.settings.fb_daily_accounts
        ]

    def hourly_reports(self, day: date, max_hour: int) -> list[FacebookAccountReport]:
        return [
            FacebookAccountReport(name, account_id, self._metrics_until_hour(account_id, day, max_hour))
            for name, account_id in self.settings.fb_daily_accounts
        ]

    def _metrics_for_day(self, account_id: str, day: date) -> FacebookMetrics:
        rows = self._insights(account_id, day, day)
        return _sum_rows(rows)

    def _metrics_until_hour(self, account_id: str, day: date, max_hour: int) -> FacebookMetrics:
        rows = self._insights(
            account_id,
            day,
            day,
            extra_params={"breakdowns": "hourly_stats_aggregated_by_advertiser_time_zone"},
        )
        selected_rows = [row for row in rows if _row_hour(row) <= max_hour]
        return _sum_rows(selected_rows)

    def _insights(self, account_id: str, start: date, end: date, extra_params: dict[str, str] | None = None) -> list[dict]:
        normalized_account_id = account_id if account_id.startswith("act_") else f"act_{account_id}"
        params = {
            "access_token": self.settings.fb_access_token,
            "fields": "spend",
            "level": "account",
            "time_range": json.dumps({"since": start.isoformat(), "until": end.isoformat()}),
            "limit": "500",
        }
        if extra_params:
            params.update(extra_params)
        url = f"https://graph.facebook.com/{self.settings.fb_api_version}/{normalized_account_id}/insights?{urllib.parse.urlencode(params)}"
        rows: list[dict] = []
        while url:
            request = urllib.request.Request(url, headers={"Accept": "application/json"})
            payload = _open_json_request(request)
            if "error" in payload:
                raise RuntimeError(f"Facebook API error for {normalized_account_id}: {payload['error']}")
            rows.extend(payload.get("data", []))
            url = payload.get("paging", {}).get("next", "")
        return rows


def total_reports(reports: list[FacebookAccountReport]) -> FacebookMetrics:
    total = FacebookMetrics()
    for report in reports:
        total.spend_inr += report.metrics.spend_inr
        total.registers += report.metrics.registers
        total.purchases += report.metrics.purchases
    return total


def _sum_rows(rows: list[dict]) -> FacebookMetrics:
    metrics = FacebookMetrics()
    for row in rows:
        metrics.spend_inr += Decimal(str(row.get("spend", "0") or "0"))
    return metrics


def _open_json_request(request: urllib.request.Request) -> dict:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            if error.code not in {429, 500, 502, 503, 504}:
                raise RuntimeError(f"Facebook API error {error.code}: {body}") from error
            last_error = RuntimeError(f"Facebook API error {error.code}: {body}")
        except urllib.error.URLError as error:
            last_error = error
        if attempt < 2:
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Facebook API request failed after retries: {last_error}") from last_error


def _row_hour(row: dict) -> int:
    value = row.get("hourly_stats_aggregated_by_advertiser_time_zone", "")
    try:
        return int(str(value).split(":", 1)[0])
    except (TypeError, ValueError):
        return 999
