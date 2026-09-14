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
from .policy_types import PolicyIssue


@dataclass
class FacebookMetrics:
    spend_inr: Decimal = Decimal("0")
    registers: float = 0.0
    purchases: float = 0.0
    applies: float = 0.0
    approvals: float = 0.0

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


@dataclass
class FacebookAccountBalance:
    name: str
    account_id: str
    facebook_name: str
    balance_inr: Decimal
    currency: str
    account_status: int
    disable_reason: int
    funding_source: str


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

    def account_balances(
        self,
        accounts: tuple[tuple[str, str], ...] | None = None,
    ) -> list[FacebookAccountBalance]:
        monitor_accounts = accounts if accounts is not None else self.settings.fb_daily_accounts
        return [
            self._account_balance(name, account_id)
            for name, account_id in monitor_accounts
        ]

    def policy_issues(self) -> list[PolicyIssue]:
        issues: list[PolicyIssue] = []
        for name, account_id in self.settings.fb_daily_accounts:
            issues.extend(self._ad_policy_issues(name, account_id))
            issues.extend(self._adset_policy_issues(name, account_id))
        return issues

    def _account_balance(self, name: str, account_id: str) -> FacebookAccountBalance:
        normalized_account_id = account_id if account_id.startswith("act_") else f"act_{account_id}"
        params = {
            "access_token": self.settings.fb_access_token,
            "fields": "id,name,account_id,account_status,balance,currency,disable_reason,funding_source_details",
        }
        url = f"https://graph.facebook.com/{self.settings.fb_api_version}/{normalized_account_id}?{urllib.parse.urlencode(params)}"
        payload = _open_json_request(urllib.request.Request(url, headers={"Accept": "application/json"}))
        return FacebookAccountBalance(
            name=name,
            account_id=payload.get("account_id", account_id.replace("act_", "")),
            facebook_name=payload.get("name", name),
            balance_inr=_minor_units_to_currency(payload.get("balance")),
            currency=payload.get("currency", ""),
            account_status=int(payload.get("account_status") or 0),
            disable_reason=int(payload.get("disable_reason") or 0),
            funding_source=(payload.get("funding_source_details") or {}).get("display_string", ""),
        )

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

    def _ad_policy_issues(self, name: str, account_id: str) -> list[PolicyIssue]:
        rows = self._objects(
            account_id,
            "ads",
            fields="id,name,effective_status,configured_status,status,ad_review_feedback,issues_info,campaign{name},adset{name}",
            extra_params={"effective_status": json.dumps(["DISAPPROVED", "WITH_ISSUES"])},
        )
        issues: list[PolicyIssue] = []
        for row in rows:
            reasons = _policy_reasons(row)
            issues.append(
                PolicyIssue(
                    customer_id=_format_account_id(account_id),
                    customer_name=name,
                    issue_type="Facebook广告",
                    approval_status=str(row.get("effective_status") or "UNKNOWN"),
                    review_status=str(row.get("status") or row.get("configured_status") or "UNKNOWN"),
                    campaign_name=(row.get("campaign") or {}).get("name", ""),
                    ad_group_name=(row.get("adset") or {}).get("name", ""),
                    item_name=row.get("name") or row.get("id", ""),
                    item_id=str(row.get("id", "")),
                    policy_topics=tuple(reasons) or ("未返回具体审核原因",),
                )
            )
        return issues

    def _adset_policy_issues(self, name: str, account_id: str) -> list[PolicyIssue]:
        rows = self._objects(
            account_id,
            "adsets",
            fields="id,name,effective_status,configured_status,status,issues_info,campaign{name}",
            extra_params={"effective_status": json.dumps(["WITH_ISSUES"])},
        )
        issues: list[PolicyIssue] = []
        for row in rows:
            reasons = _policy_reasons(row)
            issues.append(
                PolicyIssue(
                    customer_id=_format_account_id(account_id),
                    customer_name=name,
                    issue_type="Facebook广告组",
                    approval_status=str(row.get("effective_status") or "UNKNOWN"),
                    review_status=str(row.get("status") or row.get("configured_status") or "UNKNOWN"),
                    campaign_name=(row.get("campaign") or {}).get("name", ""),
                    ad_group_name=row.get("name") or row.get("id", ""),
                    item_name=row.get("name") or row.get("id", ""),
                    item_id=str(row.get("id", "")),
                    policy_topics=tuple(reasons) or ("未返回具体审核原因",),
                )
            )
        return issues

    def _objects(self, account_id: str, edge: str, fields: str, extra_params: dict[str, str] | None = None) -> list[dict]:
        normalized_account_id = account_id if account_id.startswith("act_") else f"act_{account_id}"
        params = {
            "access_token": self.settings.fb_access_token,
            "fields": fields,
            "limit": "500",
        }
        if extra_params:
            params.update(extra_params)
        url = f"https://graph.facebook.com/{self.settings.fb_api_version}/{normalized_account_id}/{edge}?{urllib.parse.urlencode(params)}"
        rows: list[dict] = []
        while url:
            payload = _open_json_request(urllib.request.Request(url, headers={"Accept": "application/json"}))
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


def _minor_units_to_currency(value) -> Decimal:
    return (Decimal(str(value or "0")) / Decimal("100")).quantize(Decimal("0.01"))


def _open_json_request(request: urllib.request.Request) -> dict:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            if error.code not in {429, 500, 502, 503, 504}:
                raise RuntimeError(f"Facebook API error {error.code}: {body}") from error
            last_error = RuntimeError(f"Facebook API error {error.code}: {body}")
        except (TimeoutError, urllib.error.URLError) as error:
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


def _format_account_id(account_id: str) -> str:
    return account_id.replace("act_", "")


def _policy_reasons(row: dict) -> list[str]:
    reasons: list[str] = []
    _collect_policy_text(row.get("ad_review_feedback"), reasons)
    _collect_policy_text(row.get("issues_info"), reasons)
    return _dedupe(reasons)


def _collect_policy_text(value, reasons: list[str]) -> None:
    if value is None:
        return
    if isinstance(value, str):
        text = value.strip()
        if text:
            reasons.append(text)
        return
    if isinstance(value, dict):
        preferred_keys = ("error_summary", "error_message", "message", "summary", "title", "description", "policy", "policy_name")
        for key in preferred_keys:
            if key in value:
                _collect_policy_text(value[key], reasons)
        if any(key in value for key in preferred_keys):
            return
        for key, item in value.items():
            if key in {"blame_field_specs", "debug_info", "error_code", "level", "object_type", "severity"}:
                continue
            _collect_policy_text(item, reasons)
        return
    if isinstance(value, list):
        for item in value:
            _collect_policy_text(item, reasons)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
