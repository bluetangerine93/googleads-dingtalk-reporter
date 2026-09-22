from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from .config import load_settings, require_config
from .facebook_ads import FacebookAdsReporter, FacebookAccountBalance
from .lark import send_interactive_card


ACTIVE_ACCOUNT_STATUS = 1
ACCOUNT_STATUS_LABELS = {
    1: "Active",
    2: "Disabled",
    3: "Unsettled",
    7: "Pending Review",
    9: "In Grace Period",
    100: "Pending Closure",
    101: "Temporarily Unavailable",
    201: "Pending Settlement",
    202: "In Dispute",
}
ACCOUNT_STATUS_DETAILS = {
    3: "Payment error / unsettled balance",
    7: "Account is waiting for Meta review",
    9: "Account is in grace period",
    100: "Account is pending closure",
    101: "Account is temporarily unavailable",
    201: "Account is pending settlement",
    202: "Account has a billing dispute",
}
DISABLE_REASON_LABELS = {
    0: "",
    1: "Ads Integrity Policy",
    2: "Ads IP Review",
    3: "Risk Payment",
    4: "Gray Account Shutting Down",
    5: "Ads AFC Review",
    6: "Business Integrity RAR",
    7: "Permanent Close",
    8: "Unused Reseller Account",
    9: "Unused Account",
}


@dataclass
class BalanceAlert:
    balance: FacebookAccountBalance
    reasons: tuple[str, ...]


def run_fb_balance_monitor(dry_run: bool = False, mode: str = "all") -> None:
    if mode not in {"all", "balance", "status"}:
        raise ValueError(f"Unsupported Facebook balance monitor mode: {mode}")
    settings = load_settings()
    monitor_accounts = settings.fb_status_accounts if mode == "status" else settings.fb_daily_accounts
    require_config({
        "FB_ACCESS_TOKEN": settings.fb_access_token,
        "FB_MONITOR_ACCOUNTS": ",".join(account_id for _name, account_id in monitor_accounts),
        "LARK_BALANCE_WEBHOOK": settings.lark_balance_webhook,
    })
    reporter = FacebookAdsReporter(settings)
    balances = reporter.account_balances(accounts=monitor_accounts)
    threshold = Decimal(str(settings.fb_balance_threshold_inr))
    credit_threshold = settings.fb_credit_alert_threshold_inr
    status_account_ids = {
        account_id.removeprefix("act_")
        for _name, account_id in settings.fb_status_accounts
    }
    alerts = []
    for balance in balances:
        normalized_id = balance.account_id.removeprefix("act_")
        alert_mode = mode
        if mode == "all" and normalized_id not in status_account_ids:
            alert_mode = "balance"
        alert = _balance_alert(balance, threshold, credit_threshold, alert_mode)
        if alert is not None:
            alerts.append(alert)
    if not alerts:
        if dry_run:
            print(f"No Facebook account alerts for mode: {mode}.")
        return

    tz = ZoneInfo(settings.report_timezone)
    now = datetime.now(tz)
    card = _format_balance_alert_card(now, alerts, threshold, credit_threshold, mode)
    send_interactive_card(
        settings.lark_balance_webhook,
        settings.lark_balance_keyword,
        card,
        dry_run=dry_run,
    )


def _balance_alert(
    balance: FacebookAccountBalance,
    threshold: Decimal,
    credit_threshold: Decimal,
    mode: str,
) -> BalanceAlert | None:
    reasons: list[str] = []
    if mode in {"all", "balance"} and balance.currency == "INR" and balance.balance_inr < threshold:
        reasons.append("Balance below threshold")
    if (
        mode in {"all", "status"}
        and balance.currency == "INR"
        and balance.credit_limit_inr > 0
        and balance.available_credit_inr <= credit_threshold
    ):
        reasons.append("Estimated available credit is below threshold")
    if mode in {"all", "status"} and balance.account_status != ACTIVE_ACCOUNT_STATUS:
        status_text = account_status_label(balance.account_status)
        detail_text = account_status_detail(balance)
        reasons.append(f"Account status is {status_text}" + (f" ({detail_text})" if detail_text else ""))
    if not reasons:
        return None
    return BalanceAlert(balance=balance, reasons=tuple(reasons))


def _format_balance_alert_card(
    now: datetime,
    alerts: list[BalanceAlert],
    threshold: Decimal,
    credit_threshold: Decimal,
    mode: str,
) -> dict:
    title = {
        "balance": "PM FB Balance Alert",
        "status": "PM FB Account Status Alert",
    }.get(mode, "PM FB Account Alert")
    summary_lines = [
        f"**Time:** {now:%Y-%m-%d %H:%M} IST",
        f"**Mode:** {mode.title()}",
    ]
    if mode in {"all", "balance"}:
        summary_lines.append(f"**Threshold:** INR {threshold:,.2f}")
    if mode in {"all", "status"}:
        summary_lines.append(f"**Credit alert threshold:** INR {credit_threshold:,.2f}")
    summary_lines.append(f"**Alerts:** {len(alerts)} account(s)")
    elements = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": "\n".join(summary_lines),
            },
        },
        {"tag": "hr"},
    ]
    for alert in alerts:
        balance = alert.balance
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": "\n".join([
                    f"**{_md_escape(_short_account_name(balance.name))}** ({_md_escape(balance.account_id)})",
                    f"**Total credit limit:** **INR {balance.credit_limit_inr:,.2f}**",
                    f"**Payable balance:** **INR {balance.balance_inr:,.2f}**",
                    f"**Estimated remaining credit:** **INR {balance.available_credit_inr:,.2f}**",
                    f"**Balance currency:** {_md_escape(balance.currency or 'N/A')}",
                    f"**Status:** **{_md_escape(account_status_label(balance.account_status))}**",
                    f"Detail: {_md_escape(account_status_detail(balance) or 'N/A')}",
                    f"Payment: {_md_escape(balance.funding_source or 'N/A')}",
                ]),
            },
        })
        if alert is not alerts[-1]:
            elements.append({"tag": "hr"})
    return {
        "config": {
            "wide_screen_mode": True,
        },
        "header": {
            "template": "red",
            "title": {
                "tag": "plain_text",
                "content": f"notification | {title}",
            },
        },
        "elements": elements,
    }


def _md_escape(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace("*", "\\*").replace("_", "\\_").replace("`", "\\`")


def _short_account_name(name: str) -> str:
    return name.replace("PocketMitra", "PM", 1) if name.startswith("PocketMitra") else name


def account_status_label(status: int) -> str:
    return ACCOUNT_STATUS_LABELS.get(status, f"Unknown ({status})")


def account_status_detail(balance: FacebookAccountBalance) -> str:
    if balance.disable_reason:
        return DISABLE_REASON_LABELS.get(balance.disable_reason, f"Disable reason code {balance.disable_reason}")
    return ACCOUNT_STATUS_DETAILS.get(balance.account_status, "")
