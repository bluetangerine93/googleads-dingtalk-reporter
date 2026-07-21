from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime

from .config import Settings


BASE_URL = "https://automate.adjust.com/reports-service"


@dataclass
class AdjustKpiMetrics:
    installs: float = 0.0
    registers: float = 0.0
    loans: float = 0.0


class AdjustKpiReporter:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._event_metric_cache: dict[str, str] = {}

    @property
    def enabled(self) -> bool:
        return bool(self.settings.adjust_user_token and self.settings.adjust_app_token)

    def daily_channel_metrics(self, day: date) -> dict[str, AdjustKpiMetrics]:
        payload = self._request(day, day, self.settings.adjust_grouping)
        rows = _find_rows(payload)
        metrics: dict[str, AdjustKpiMetrics] = {}
        for row in rows:
            channel = _text(row, self.settings.adjust_grouping)
            if not channel:
                channel = _first_text(row, ("channel", "channels", "network", "networks"))
            if not channel:
                continue
            total = metrics.setdefault(channel, AdjustKpiMetrics())
            row_metrics = self._metrics_from_row(row)
            total.installs += row_metrics.installs
            total.registers += row_metrics.registers
            total.loans += row_metrics.loans
        return metrics

    def daily_campaign_metrics(self, day: date) -> list[tuple[str, str, AdjustKpiMetrics]]:
        payload = self._request(day, day, f"{self.settings.adjust_grouping},campaign")
        rows = _find_rows(payload)
        metrics: list[tuple[str, str, AdjustKpiMetrics]] = []
        for row in rows:
            channel = _text(row, self.settings.adjust_grouping)
            if not channel:
                channel = _first_text(row, ("channel", "channels", "network", "networks"))
            campaign = _first_text(row, ("campaign", "campaigns", "campaign_name", "campaign_names"))
            if not channel or not campaign:
                continue
            metrics.append((
                channel,
                campaign,
                AdjustKpiMetrics(
                    installs=_float(row.get("installs")),
                    registers=_float(row.get(self.register_metric_key)),
                    loans=_float(row.get(self.loan_metric_key)),
                ),
            ))
        return metrics

    def channel_totals(self, day: date, channels: tuple[str, ...], attempts: int = 3) -> AdjustKpiMetrics:
        total = AdjustKpiMetrics()
        for _attempt in range(max(attempts, 1)):
            total = _max_metrics(total, self._channel_totals_once(day, channels))
        return total

    def _channel_totals_once(self, day: date, channels: tuple[str, ...]) -> AdjustKpiMetrics:
        rows = self.daily_channel_metrics(day)
        total = AdjustKpiMetrics()
        normalized_channels = {_normalize(value) for value in channels}
        for channel, metrics in rows.items():
            if _normalize(channel) in normalized_channels:
                total.installs += metrics.installs
                total.registers += metrics.registers
                total.loans += metrics.loans
        return total

    def channel_totals_until_hour(self, day: date, hour: int, channels: tuple[str, ...]) -> AdjustKpiMetrics:
        total = AdjustKpiMetrics()
        normalized_channels = {_normalize(value) for value in channels}
        for row in self._hourly_rows(day, f"hour,{self.settings.adjust_grouping}", hour):
            channel = _text(row, self.settings.adjust_grouping)
            if not channel:
                channel = _first_text(row, ("channel", "channels", "network", "networks"))
            if _normalize(channel) not in normalized_channels:
                continue
            metrics = self._metrics_from_row(row)
            total.installs += metrics.installs
            total.registers += metrics.registers
            total.loans += metrics.loans
        return total

    def facebook_account_totals(self, day: date) -> dict[str, AdjustKpiMetrics]:
        totals = {
            name: AdjustKpiMetrics()
            for name, _pattern in self.settings.adjust_facebook_account_patterns
        }
        channel_set = {_normalize(value) for value in self.settings.adjust_facebook_channels}
        for channel, campaign, metrics in self.daily_campaign_metrics(day):
            if _normalize(channel) not in channel_set:
                continue
            account_name = self._match_facebook_account(campaign)
            if not account_name:
                continue
            total = totals.setdefault(account_name, AdjustKpiMetrics())
            total.installs += metrics.installs
            total.registers += metrics.registers
            total.loans += metrics.loans
        return totals

    def facebook_account_totals_until_hour(self, day: date, hour: int) -> dict[str, AdjustKpiMetrics]:
        totals = {
            name: AdjustKpiMetrics()
            for name, _pattern in self.settings.adjust_facebook_account_patterns
        }
        channel_set = {_normalize(value) for value in self.settings.adjust_facebook_channels}
        grouping = f"hour,{self.settings.adjust_grouping},campaign"
        for row in self._hourly_rows(day, grouping, hour):
            channel = _text(row, self.settings.adjust_grouping)
            if not channel:
                channel = _first_text(row, ("channel", "channels", "network", "networks"))
            if _normalize(channel) not in channel_set:
                continue
            campaign = _first_text(row, ("campaign", "campaigns", "campaign_name", "campaign_names"))
            account_name = self._match_facebook_account(campaign)
            if not account_name:
                continue
            metrics = self._metrics_from_row(row)
            total = totals.setdefault(account_name, AdjustKpiMetrics())
            total.installs += metrics.installs
            total.registers += metrics.registers
            total.loans += metrics.loans
        return totals

    @property
    def register_metric_key(self) -> str:
        return self._event_metric_key(self.settings.adjust_register_event_token)

    @property
    def loan_metric_key(self) -> str:
        return self._event_metric_key(self.settings.adjust_loan_event_token)

    def _match_facebook_account(self, campaign: str) -> str:
        normalized_campaign = _normalize(campaign)
        for name, pattern in self.settings.adjust_facebook_account_patterns:
            if normalized_campaign.startswith(_normalize(pattern)):
                return name
        return ""

    def _request(self, start: date, end: date, grouping: str):
        if not self.enabled:
            raise ValueError("ADJUST_USER_TOKEN and ADJUST_APP_TOKEN are required.")
        _validate_header_value("ADJUST_USER_TOKEN", self.settings.adjust_user_token)
        metrics = ",".join(("installs", self.register_metric_key, self.loan_metric_key))
        params = {
            "app_token__in": self.settings.adjust_app_token,
            "date_period": f"{start.isoformat()}:{end.isoformat()}",
            "dimensions": grouping,
            "metrics": metrics,
            "utc_offset": self.settings.adjust_utc_offset,
            "attribution_source": self.settings.adjust_attribution_source,
            "cohort_maturity": "immature",
            "format_dates": "false",
        }
        url = f"{BASE_URL}/report?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.settings.adjust_user_token}",
            },
        )
        body = self._open_json_request(request, "Adjust Report Service API")
        return json.loads(body)

    def _hourly_rows(self, day: date, grouping: str, hour: int) -> list[dict]:
        payload = self._request(day, day, grouping)
        return [
            row
            for row in _find_rows(payload)
            if _row_hour_in_window(row, day, hour)
        ]

    def _metrics_from_row(self, row: dict) -> AdjustKpiMetrics:
        return AdjustKpiMetrics(
            installs=_float(row.get("installs")),
            registers=_float(row.get(self.register_metric_key)),
            loans=_float(row.get(self.loan_metric_key)),
        )

    def _event_metric_key(self, event_token: str) -> str:
        if event_token in self._event_metric_cache:
            return self._event_metric_cache[event_token]
        event_id = self._event_id(event_token)
        metric_key = event_id if event_id.endswith("_events") else f"{event_id}_events"
        self._event_metric_cache[event_token] = metric_key
        return metric_key

    def _event_id(self, event_token: str) -> str:
        if not self.enabled:
            raise ValueError("ADJUST_USER_TOKEN and ADJUST_APP_TOKEN are required.")
        _validate_header_value("ADJUST_USER_TOKEN", self.settings.adjust_user_token)
        params = {"app_token__in": self.settings.adjust_app_token}
        url = f"{BASE_URL}/events?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.settings.adjust_user_token}",
            },
        )
        body = self._open_json_request(request, "Adjust Report Service events API")

        needle = event_token.strip().casefold()
        for row in _find_rows(json.loads(body)):
            if _event_matches(row, needle):
                event_id = _first_text(row, ("id", "key", "slug", "metric", "name"))
                if event_id:
                    return event_id
        raise RuntimeError(f"Adjust event token not found in Report Service events list: {event_token}")

    def _open_json_request(self, request: urllib.request.Request, label: str) -> str:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    return response.read().decode("utf-8")
            except urllib.error.HTTPError as error:
                body = error.read().decode("utf-8", errors="replace")
                if error.code not in {429, 500, 502, 503, 504}:
                    raise RuntimeError(f"{label} error {error.code}: {body}") from error
                last_error = RuntimeError(f"{label} error {error.code}: {body}")
            except urllib.error.URLError as error:
                last_error = error
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
        raise RuntimeError(f"{label} request failed after retries: {last_error}") from last_error


def _find_rows(payload) -> list[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("rows", "data", "result", "results", "kpis"):
        value = payload.get(key)
        if isinstance(value, list) and all(isinstance(item, dict) for item in value):
            return value
    for value in payload.values():
        rows = _find_rows(value)
        if rows:
            return rows
    return []


def _text(row: dict, key: str) -> str:
    value = row.get(key)
    return str(value).strip() if value is not None else ""


def _first_text(row: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        value = _text(row, key)
        if value:
            return value
    return ""


def _float(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _normalize(value: str) -> str:
    return value.strip().casefold()


def _max_metrics(left: AdjustKpiMetrics, right: AdjustKpiMetrics) -> AdjustKpiMetrics:
    return AdjustKpiMetrics(
        installs=max(left.installs, right.installs),
        registers=max(left.registers, right.registers),
        loans=max(left.loans, right.loans),
    )


def _event_matches(row: dict, needle: str) -> bool:
    for key in ("token", "event_token", "id", "key", "slug", "metric"):
        value = row.get(key)
        if value is not None and str(value).strip().casefold() == needle:
            return True
    tokens = row.get("tokens")
    if isinstance(tokens, list) and any(str(token).strip().casefold() == needle for token in tokens):
        return True
    return needle in json.dumps(row, ensure_ascii=False).casefold()


def _row_hour_in_window(row: dict, day: date, hour: int) -> bool:
    hour_value = _text(row, "hour")
    if not hour_value:
        return False
    try:
        row_time = datetime.fromisoformat(hour_value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return row_time.date() == day and 0 <= row_time.hour <= hour


def _validate_header_value(name: str, value: str) -> None:
    try:
        value.encode("latin-1")
    except UnicodeEncodeError as error:
        raise ValueError(f"{name} contains non-ASCII characters. Use the real Adjust API token, not a placeholder.") from error
