from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from google.ads.googleads.client import GoogleAdsClient

from .config import Settings


@dataclass
class Metrics:
    cost_inr: float = 0.0
    registers: float = 0.0
    loans: float = 0.0


class GoogleAdsReporter:
    def __init__(self, settings: Settings):
        config = {
            "developer_token": settings.developer_token,
            "client_id": settings.client_id,
            "client_secret": settings.client_secret,
            "refresh_token": settings.refresh_token,
            "use_proto_plus": True,
        }
        if settings.login_customer_id:
            config["login_customer_id"] = settings.login_customer_id
        self.client = GoogleAdsClient.load_from_dict(config)
        self.settings = settings

    def _search(self, customer_id: str, query: str):
        service = self.client.get_service("GoogleAdsService")
        return service.search(customer_id=customer_id, query=query)

    def _sum_cost(self, start: date, end: date, max_hour: int | None = None) -> float:
        total_micros = 0
        for customer_id in self.settings.customer_ids:
            if max_hour is None:
                query = f"""
                    SELECT metrics.cost_micros
                    FROM customer
                    WHERE segments.date BETWEEN '{start}' AND '{end}'
                """
            else:
                query = f"""
                    SELECT metrics.cost_micros, segments.hour
                    FROM customer
                    WHERE segments.date = '{start}'
                      AND segments.hour <= {max_hour}
                """
            for row in self._search(customer_id, query):
                total_micros += row.metrics.cost_micros
        return total_micros / 1_000_000

    def _sum_conversion(self, action_name: str, metric_name: str, start: date, end: date, max_hour: int | None = None) -> float:
        metric = f"metrics.{metric_name}"
        total = 0.0
        escaped_name = action_name.replace("\\", "\\\\").replace("'", "\\'")
        for customer_id in self.settings.customer_ids:
            if max_hour is None:
                query = f"""
                    SELECT {metric}, segments.conversion_action_name
                    FROM customer
                    WHERE segments.date BETWEEN '{start}' AND '{end}'
                      AND segments.conversion_action_name = '{escaped_name}'
                """
            else:
                query = f"""
                    SELECT {metric}, segments.conversion_action_name, segments.hour
                    FROM customer
                    WHERE segments.date = '{start}'
                      AND segments.hour <= {max_hour}
                      AND segments.conversion_action_name = '{escaped_name}'
                """
            for row in self._search(customer_id, query):
                value = row.metrics.conversions if metric_name == "conversions" else row.metrics.all_conversions
                total += float(value)
        return total

    def metrics_for_day(self, day: date) -> Metrics:
        return Metrics(
            cost_inr=self._sum_cost(day, day),
            registers=self._sum_conversion(self.settings.register_conversion_name, self.settings.register_conversion_metric, day, day),
            loans=self._sum_conversion(self.settings.loan_conversion_name, self.settings.loan_conversion_metric, day, day),
        )

    def metrics_for_period(self, start: date, end: date) -> Metrics:
        return Metrics(
            cost_inr=self._sum_cost(start, end),
            registers=self._sum_conversion(self.settings.register_conversion_name, self.settings.register_conversion_metric, start, end),
            loans=self._sum_conversion(self.settings.loan_conversion_name, self.settings.loan_conversion_metric, start, end),
        )

    def metrics_until_hour(self, day: date, hour: int) -> Metrics:
        return Metrics(
            cost_inr=self._sum_cost(day, day, max_hour=hour),
            registers=self._sum_conversion(self.settings.register_conversion_name, self.settings.register_conversion_metric, day, day, max_hour=hour),
            loans=0.0,
        )

    def conversion_breakdown(self, day: date) -> list[tuple[str, float, float]]:
        rows: dict[str, tuple[float, float]] = {}
        metric = f"metrics.{self.settings.conversion_metric}"
        for customer_id in self.settings.customer_ids:
            query = f"""
                SELECT {metric}, metrics.all_conversions, segments.conversion_action_name
                FROM customer
                WHERE segments.date = '{day}'
                  AND segments.conversion_action_name IS NOT NULL
            """
            for row in self._search(customer_id, query):
                name = row.segments.conversion_action_name
                selected_value = row.metrics.conversions if self.settings.conversion_metric == "conversions" else row.metrics.all_conversions
                existing_selected, existing_all = rows.get(name, (0.0, 0.0))
                rows[name] = (
                    existing_selected + float(selected_value),
                    existing_all + float(row.metrics.all_conversions),
                )
        return sorted(
            [(name, selected, all_value) for name, (selected, all_value) in rows.items()],
            key=lambda item: item[1],
            reverse=True,
        )

    def conversion_lag_breakdown(self, action_name: str, metric_name: str, start: date, end: date) -> dict[str, float]:
        metric = f"metrics.{metric_name}"
        rows: dict[str, float] = {}
        escaped_name = action_name.replace("\\", "\\\\").replace("'", "\\'")
        for customer_id in self.settings.customer_ids:
            query = f"""
                SELECT {metric}, segments.conversion_action_name, segments.conversion_lag_bucket
                FROM customer
                WHERE segments.date BETWEEN '{start}' AND '{end}'
                  AND segments.conversion_action_name = '{escaped_name}'
            """
            for row in self._search(customer_id, query):
                bucket = row.segments.conversion_lag_bucket.name
                value = row.metrics.conversions if metric_name == "conversions" else row.metrics.all_conversions
                rows[bucket] = rows.get(bucket, 0.0) + float(value)
        return rows
