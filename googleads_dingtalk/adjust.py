from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date

from .config import Settings


BASE_URL = "https://automate.adjust.com/reports-service"


@dataclass
class AdjustMetrics:
    registers: float = 0.0
    loans: float = 0.0


class AdjustReporter:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._register_metric: str | None = settings.adjust_register_metric or None
        self._loan_metric: str | None = settings.adjust_loan_metric or None

    @property
    def enabled(self) -> bool:
        return bool(self.settings.adjust_api_token)

    def metrics_for_day(self, day: date, channel: str = "google") -> AdjustMetrics:
        return self._metrics(day, day, channel)

    def events(self, search: str) -> list[dict]:
        params = {
            "events__contains": search,
            "tokens_mapping": "true",
        }
        if self.settings.adjust_app_tokens:
            params["app_token__in"] = ",".join(self.settings.adjust_app_tokens)
        rows = self._get_json("/events", params)
        return rows if isinstance(rows, list) else []

    def metrics_until_hour(self, day: date, max_hour: int, channel: str = "google") -> AdjustMetrics:
        if max_hour < 0:
            return AdjustMetrics()
        metrics = self._metric_names()
        totals = {metric: 0.0 for metric in metrics}
        for params in self._report_param_sets(day, day, dimensions="hour", metrics=metrics, channel=channel):
            rows = self._get_json("/report", params).get("rows", [])
            for row in rows:
                if _row_hour(row) <= max_hour:
                    for metric in metrics:
                        totals[metric] += _float(row.get(metric))
        return AdjustMetrics(registers=totals[metrics[0]], loans=totals[metrics[1]])

    def metrics_by_day(self, start: date, end: date, channel: str = "google") -> dict[date, AdjustMetrics]:
        register_metric, loan_metric = self._metric_names()
        metrics: dict[date, AdjustMetrics] = {}
        for params in self._report_param_sets(start, end, dimensions="day", metrics=(register_metric, loan_metric), channel=channel):
            rows = self._get_json("/report", params).get("rows", [])
            for row in rows:
                day_value = row.get("day")
                if not day_value:
                    continue
                report_day = date.fromisoformat(str(day_value).split("T", 1)[0])
                current = metrics.setdefault(report_day, AdjustMetrics())
                current.registers += _float(row.get(register_metric))
                current.loans += _float(row.get(loan_metric))
        return metrics

    def _metrics(self, start: date, end: date, channel: str) -> AdjustMetrics:
        register_metric, loan_metric = self._metric_names()
        metrics = AdjustMetrics()
        for params in self._report_param_sets(start, end, dimensions="day", metrics=(register_metric, loan_metric), channel=channel):
            totals = self._get_json("/report", params).get("totals", {})
            metrics.registers += _float(totals.get(register_metric))
            metrics.loans += _float(totals.get(loan_metric))
        return metrics

    def _report_param_sets(
        self,
        start: date,
        end: date,
        dimensions: str,
        metrics: tuple[str, ...],
        channel: str,
    ) -> list[dict[str, str]]:
        filters = self._channel_filters(channel)
        if not filters:
            return [self._base_report_params(start, end, dimensions, metrics, "")]
        return [
            self._base_report_params(start, end, dimensions, metrics, filter_value)
            for filter_value in filters
        ]

    def _base_report_params(
        self,
        start: date,
        end: date,
        dimensions: str,
        metrics: tuple[str, ...],
        filter_contains: str,
    ) -> dict[str, str]:
        params = {
            "date_period": f"{start.isoformat()}:{end.isoformat()}",
            "dimensions": dimensions,
            "metrics": ",".join(metrics),
            "utc_offset": "+05:30",
            "format_dates": "false",
            "cohort_maturity": "immature",
            "attribution_source": self.settings.adjust_attribution_source,
        }
        if self.settings.adjust_app_tokens:
            params["app_token__in"] = ",".join(self.settings.adjust_app_tokens)
        if self.settings.adjust_filter_dimension and filter_contains:
            params[f"{self.settings.adjust_filter_dimension}__contains"] = filter_contains
        return params

    def _channel_filters(self, channel: str) -> tuple[str, ...]:
        if channel == "google":
            return self.settings.adjust_google_filter_contains
        if channel == "facebook":
            return self.settings.adjust_facebook_filter_contains
        raise ValueError(f"Unsupported Adjust channel: {channel}")

    def _metric_names(self) -> tuple[str, str]:
        if not self._register_metric:
            self._register_metric = self._find_event_metric(self.settings.adjust_register_event_search)
        if not self._loan_metric:
            self._loan_metric = self._find_event_metric(self.settings.adjust_loan_event_search)
        return self._register_metric, self._loan_metric

    def _find_event_metric(self, search: str) -> str:
        if not search:
            raise ValueError("Adjust event metric is missing. Set ADJUST_REGISTER_METRIC/ADJUST_LOAN_METRIC.")
        rows = self.events(search)
        if not rows:
            raise RuntimeError(f"Adjust event not found for search: {search}")
        exact = [
            row for row in rows
            if search.lower() in str(row.get("id", "")).lower()
            or search.lower() in str(row.get("name", "")).lower()
        ]
        selected = exact[0] if exact else rows[0]
        metric = str(selected.get("id") or "").strip()
        if not metric:
            raise RuntimeError(f"Adjust event response has no metric id for search: {search}")
        return metric

    def _get_json(self, path: str, params: dict[str, str]):
        if not self.settings.adjust_api_token:
            raise ValueError("ADJUST_API_TOKEN is required for reports.")
        url = f"{BASE_URL}{path}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.settings.adjust_api_token}",
            },
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            if response.status == 204:
                return [] if path == "/events" else {"rows": [], "totals": {}}
            payload = response.read().decode("utf-8")
        return json.loads(payload)


def apply_adjust_metrics(metrics, adjust_metrics: AdjustMetrics) -> None:
    metrics.registers = adjust_metrics.registers
    metrics.loans = adjust_metrics.loans


def _float(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _row_hour(row: dict) -> int:
    value = row.get("hour", "")
    if "T" in str(value):
        value = str(value).split("T", 1)[1]
    try:
        return int(str(value).split(":", 1)[0])
    except (TypeError, ValueError):
        return 999
