from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from google.ads.googleads.client import GoogleAdsClient

from .config import Settings
from .policy_types import PolicyIssue


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

    def policy_issues(self) -> list[PolicyIssue]:
        issues: list[PolicyIssue] = []
        for customer_id in self.settings.customer_ids:
            issues.extend(self._ad_policy_issues(customer_id))
            issues.extend(self._ad_group_policy_issues(customer_id))
        return issues

    def _ad_policy_issues(self, customer_id: str) -> list[PolicyIssue]:
        query = """
            SELECT
              customer.descriptive_name,
              campaign.name,
              ad_group.name,
              ad_group_ad.ad.id,
              ad_group_ad.ad.name,
              ad_group_ad.ad.type,
              ad_group_ad.policy_summary.approval_status,
              ad_group_ad.policy_summary.review_status,
              ad_group_ad.policy_summary.policy_topic_entries
            FROM ad_group_ad
            WHERE ad_group_ad.policy_summary.approval_status IN ('DISAPPROVED', 'AREA_OF_INTEREST_ONLY', 'APPROVED_LIMITED')
        """
        issues: list[PolicyIssue] = []
        for row in self._search(customer_id, query):
            topics = tuple(
                entry.topic
                for entry in row.ad_group_ad.policy_summary.policy_topic_entries
                if entry.topic
            )
            issues.append(
                PolicyIssue(
                    customer_id=_format_customer_id(customer_id),
                    customer_name=row.customer.descriptive_name or customer_id,
                    issue_type="广告",
                    approval_status=row.ad_group_ad.policy_summary.approval_status.name,
                    review_status=row.ad_group_ad.policy_summary.review_status.name,
                    campaign_name=row.campaign.name,
                    ad_group_name=row.ad_group.name,
                    item_name=row.ad_group_ad.ad.name or row.ad_group_ad.ad.type_.name,
                    item_id=str(row.ad_group_ad.ad.id),
                    policy_topics=topics,
                )
            )
        return issues

    def _ad_group_policy_issues(self, customer_id: str) -> list[PolicyIssue]:
        query = """
            SELECT
              customer.descriptive_name,
              campaign.name,
              ad_group.id,
              ad_group.name,
              ad_group.status,
              ad_group.primary_status,
              ad_group.primary_status_reasons
            FROM ad_group
            WHERE ad_group.primary_status IN ('NOT_ELIGIBLE', 'LIMITED')
        """
        issues: list[PolicyIssue] = []
        for row in self._search(customer_id, query):
            reasons = tuple(reason.name for reason in row.ad_group.primary_status_reasons)
            policy_reasons = tuple(reason for reason in reasons if _is_policy_ad_group_reason(reason))
            if not policy_reasons:
                continue
            issues.append(
                PolicyIssue(
                    customer_id=_format_customer_id(customer_id),
                    customer_name=row.customer.descriptive_name or customer_id,
                    issue_type="广告组",
                    approval_status=row.ad_group.primary_status.name,
                    review_status=row.ad_group.status.name,
                    campaign_name=row.campaign.name,
                    ad_group_name=row.ad_group.name,
                    item_name=row.ad_group.name,
                    item_id=str(row.ad_group.id),
                    policy_topics=policy_reasons,
                )
            )
        return issues


def _format_customer_id(customer_id: str) -> str:
    digits = customer_id.replace("-", "")
    if len(digits) == 10:
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    return customer_id


def _is_policy_ad_group_reason(reason: str) -> bool:
    return "POLICY" in reason or "DISAPPROVED" in reason
