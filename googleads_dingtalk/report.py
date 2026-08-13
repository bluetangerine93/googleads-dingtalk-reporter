from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from .adjust_kpi import AdjustKpiMetrics, AdjustKpiReporter
from .balance_monitor import run_fb_balance_monitor
from .config import load_settings, require_config
from .dingtalk import send_markdown
from .estimator import LoanEstimate, estimate_delayed_loans, save_daily_snapshot
from .facebook_ads import FacebookAccountReport, FacebookMetrics, FacebookAdsReporter, total_reports
from .fx import get_monthly_rate
from .google_ads import GoogleAdsReporter, Metrics
from .policy_monitor import run_policy_monitor
from .visa_reminder import run_visa_balance_reminder


DATA_SCOPE_NOTE = "数据口径：花费取自广告账户；注册/放款取自 Adjust，归因来源为 {attribution_source}"


def money(value: float | Decimal) -> str:
    amount = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"${amount:,}"


def inr_money(value: float | Decimal) -> str:
    amount = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"INR {amount:,}"


def number(value: float) -> str:
    if abs(value - round(value)) < 0.0001:
        return f"{int(round(value)):,}"
    return f"{value:,.2f}"


def pct_change(current: float, previous: float) -> str:
    if previous == 0:
        return "N/A" if current == 0 else "+∞"
    change = (current - previous) / previous
    return f"{change:+.1%}"


def cpa(cost_usd: Decimal, conversions: float) -> Decimal:
    if conversions <= 0:
        return Decimal("0")
    return cost_usd / Decimal(str(conversions))


def convert_cost(cost_inr: float, rate: Decimal) -> Decimal:
    return Decimal(str(cost_inr)) * rate


def convert_inr_decimal(cost_inr: Decimal, rate: Decimal) -> Decimal:
    return cost_inr * rate


def usd_to_inr(rate: Decimal) -> Decimal:
    if rate <= 0:
        return Decimal("0")
    return (Decimal("1") / rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def signed_pct(current: float, previous: float) -> str:
    return f"({pct_change(current, previous)})"


def ratio_pct(numerator: float, denominator: float) -> str:
    if denominator <= 0:
        return "0.0%"
    return f"{numerator / denominator:.1%}"


def window_label(max_hour: int) -> str:
    if max_hour < 0:
        return "暂无完整小时"
    return f"00:00-{max_hour:02d}:59 IST"


def trend_icon(current: float | Decimal, previous: float | Decimal, lower_is_better: bool = False) -> str:
    if Decimal(str(previous)) == 0:
        return ""
    current_value = Decimal(str(current))
    previous_value = Decimal(str(previous))
    improved = current_value <= previous_value if lower_is_better else current_value >= previous_value
    return "✅" if improved else "⚠️"


def google_daily_lines(
    current: Metrics,
    previous: Metrics,
    current_cost: Decimal,
    previous_cost: Decimal,
    current_reg_cpa: Decimal,
    previous_reg_cpa: Decimal,
    actual_loan_cpa: Decimal,
    previous_loan_cpa: Decimal,
) -> list[str]:
    return [
        "【Google】",
        f"💰 花费：{money(current_cost)} {signed_pct(float(current_cost), float(previous_cost))}｜📝 注册：{number(current.registers)} {signed_pct(current.registers, previous.registers)}｜📈 CPA：{money(current_reg_cpa)} {signed_pct(float(current_reg_cpa), float(previous_reg_cpa))}",
        f"💵 放款：{number(current.loans)} {signed_pct(current.loans, previous.loans)}｜💳 CPS：{money(actual_loan_cpa)} {signed_pct(float(actual_loan_cpa), float(previous_loan_cpa))}",
    ]


def google_hourly_lines(
    current: Metrics,
    previous: Metrics,
    current_cost: Decimal,
    previous_cost: Decimal,
    current_cpa: Decimal,
    previous_cpa: Decimal,
    current_loan_cpa: Decimal,
    previous_loan_cpa: Decimal,
) -> list[str]:
    return [
        "【Google】",
        f"💰 花费：{money(current_cost)} {signed_pct(float(current_cost), float(previous_cost))}｜📝 注册：{number(current.registers)} {signed_pct(current.registers, previous.registers)}｜📈 CPA：{money(current_cpa)} {signed_pct(float(current_cpa), float(previous_cpa))}",
        f"💵 放款：{number(current.loans)} {signed_pct(current.loans, previous.loans)}｜💳 CPS：{money(current_loan_cpa)} {signed_pct(float(current_loan_cpa), float(previous_loan_cpa))}",
    ]


def fb_daily_lines(
    current_reports: list[FacebookAccountReport],
    previous_reports: list[FacebookAccountReport],
    rate: Decimal,
    current_total: FacebookMetrics | None = None,
    previous_total: FacebookMetrics | None = None,
    current_other_loans: float = 0.0,
    previous_other_loans: float = 0.0,
    current_estimates: dict[str, LoanEstimate] | None = None,
    previous_estimates: dict[str, LoanEstimate] | None = None,
) -> list[str]:
    if not current_reports:
        return []
    previous_by_name = {report.name: report for report in previous_reports}
    current_total = current_total or total_reports(current_reports)
    previous_total = previous_total or total_reports(previous_reports)
    current_estimates = current_estimates or {}
    previous_estimates = previous_estimates or {}
    lines = [
        "",
        *_fb_daily_block(
            "【Facebook】 总计",
            current_total,
            previous_total,
            rate,
            current_estimates.get("total"),
            previous_estimates.get("total"),
            show_estimate_basis=True,
        ),
        "",
    ]
    for report in current_reports:
        previous = previous_by_name.get(report.name, FacebookAccountReport(report.name, report.account_id, FacebookMetrics()))
        lines.extend(
            _fb_daily_block(
                report.name,
                report.metrics,
                previous.metrics,
                rate,
                current_estimates.get(report.name),
                previous_estimates.get(report.name),
            )
        )
        lines.append("")
    if current_other_loans > 0 or previous_other_loans > 0:
        current_other_estimate = current_estimates.get("other")
        previous_other_estimate = previous_estimates.get("other")
        if current_other_estimate and previous_other_estimate:
            lines.append(
                f"其他账户/归因：💵 已回传购物 {number(current_other_loans)}｜"
                f"预估购物 {number(current_other_estimate.estimated_loans)} "
                f"{signed_pct(current_other_estimate.estimated_loans, previous_other_estimate.estimated_loans)}"
            )
        else:
            lines.append(f"其他账户/归因：💵 购物 {number(current_other_loans)} {signed_pct(current_other_loans, previous_other_loans)}")
        lines.append("")
    return lines


def _fb_daily_block(
    title: str,
    current: FacebookMetrics,
    previous: FacebookMetrics,
    rate: Decimal,
    current_estimate: LoanEstimate | None = None,
    previous_estimate: LoanEstimate | None = None,
    show_estimate_basis: bool = False,
) -> list[str]:
    current_spend_usd = convert_inr_decimal(current.spend_inr, rate)
    previous_spend_usd = convert_inr_decimal(previous.spend_inr, rate)
    current_cpa_usd = convert_inr_decimal(current.cost_per_register_inr, rate)
    previous_cpa_usd = convert_inr_decimal(previous.cost_per_register_inr, rate)
    current_cpp_usd = convert_inr_decimal(current.cost_per_purchase_inr, rate)
    previous_cpp_usd = convert_inr_decimal(previous.cost_per_purchase_inr, rate)
    label = title if title.startswith("【") else f"{title}："
    lines = [
        label,
        f"💰 花费：{money(current_spend_usd)} {signed_pct(float(current_spend_usd), float(previous_spend_usd))}｜📝 注册：{number(current.registers)} {signed_pct(current.registers, previous.registers)}｜📈 CPA：{money(current_cpa_usd)} {signed_pct(float(current_cpa_usd), float(previous_cpa_usd))}",
    ]
    if current_estimate and previous_estimate:
        current_estimated_cpp = cpa(current_spend_usd, current_estimate.estimated_loans)
        previous_estimated_cpp = cpa(previous_spend_usd, previous_estimate.estimated_loans)
        lines.append(
            f"💵 已回传购物：{number(current.purchases)}｜"
            f"预估购物：{number(current_estimate.estimated_loans)} {signed_pct(current_estimate.estimated_loans, previous_estimate.estimated_loans)}｜"
            f"💳 实际CPS：{money(current_cpp_usd)} {signed_pct(float(current_cpp_usd), float(previous_cpp_usd))}｜"
            f"预估CPS：{money(current_estimated_cpp)} {signed_pct(float(current_estimated_cpp), float(previous_estimated_cpp))}"
        )
        if show_estimate_basis:
            if current_estimate.sample_count >= 3:
                lines.append(
                    f"预估依据：{current_estimate.basis} "
                    f"{current_estimate.completion_rate:.1%}，样本 {current_estimate.sample_count}"
                )
            else:
                lines.append(f"预估依据：历史样本不足，暂用已回传值（样本 {current_estimate.sample_count}/3）")
    else:
        lines.append(
            f"💵 购物：{number(current.purchases)} {signed_pct(current.purchases, previous.purchases)}｜"
            f"💳 CPS：{money(current_cpp_usd)} {signed_pct(float(current_cpp_usd), float(previous_cpp_usd))}"
        )
    return lines


def fb_hourly_lines(
    current_reports: list[FacebookAccountReport],
    previous_reports: list[FacebookAccountReport],
    rate: Decimal,
    current_total: FacebookMetrics | None = None,
    previous_total: FacebookMetrics | None = None,
    current_other_loans: float = 0.0,
    previous_other_loans: float = 0.0,
) -> list[str]:
    if not current_reports:
        return []
    current_total = current_total or total_reports(current_reports)
    previous_total = previous_total or total_reports(previous_reports)
    lines = ["", *_fb_hourly_total_block("【Facebook】", current_total, previous_total, rate), ""]
    for report in current_reports:
        previous = next((item for item in previous_reports if item.name == report.name), None)
        lines.extend(_fb_hourly_account_block(report.name, report.metrics, previous.metrics if previous else FacebookMetrics(), rate))
        lines.append("")
    if current_other_loans > 0 or previous_other_loans > 0:
        lines.append(f"其他账户/归因：💵 购物 {number(current_other_loans)}")
        lines.append("")
    return lines


def _fb_hourly_total_block(title: str, current: FacebookMetrics, previous: FacebookMetrics, rate: Decimal) -> list[str]:
    current_spend_usd = convert_inr_decimal(current.spend_inr, rate)
    previous_spend_usd = convert_inr_decimal(previous.spend_inr, rate)
    current_cpa_usd = convert_inr_decimal(current.cost_per_register_inr, rate)
    previous_cpa_usd = convert_inr_decimal(previous.cost_per_register_inr, rate)
    current_cpp_usd = convert_inr_decimal(current.cost_per_purchase_inr, rate)
    previous_cpp_usd = convert_inr_decimal(previous.cost_per_purchase_inr, rate)
    return [
        title,
        f"💰 花费：{money(current_spend_usd)} {signed_pct(float(current_spend_usd), float(previous_spend_usd))}｜📝 注册：{number(current.registers)} {signed_pct(current.registers, previous.registers)}｜📈 CPA：{money(current_cpa_usd)} {signed_pct(float(current_cpa_usd), float(previous_cpa_usd))}",
        f"💵 购物：{number(current.purchases)} {signed_pct(current.purchases, previous.purchases)}｜💳 CPS：{money(current_cpp_usd)} {signed_pct(float(current_cpp_usd), float(previous_cpp_usd))}｜✅ 通过率：{ratio_pct(current.approvals, current.applies)}",
    ]


def _fb_hourly_account_block(title: str, current: FacebookMetrics, previous: FacebookMetrics, rate: Decimal) -> list[str]:
    current_spend_usd = convert_inr_decimal(current.spend_inr, rate)
    previous_spend_usd = convert_inr_decimal(previous.spend_inr, rate)
    current_cpa_usd = convert_inr_decimal(current.cost_per_register_inr, rate)
    previous_cpa_usd = convert_inr_decimal(previous.cost_per_register_inr, rate)
    current_cpp_usd = convert_inr_decimal(current.cost_per_purchase_inr, rate)
    previous_cpp_usd = convert_inr_decimal(previous.cost_per_purchase_inr, rate)
    return [
        f"{title}：",
        f"💰 花费：{money(current_spend_usd)} {signed_pct(float(current_spend_usd), float(previous_spend_usd))}｜📝 注册：{number(current.registers)} {signed_pct(current.registers, previous.registers)}｜📈 CPA：{money(current_cpa_usd)} {signed_pct(float(current_cpa_usd), float(previous_cpa_usd))}",
        f"💵 购物：{number(current.purchases)} {signed_pct(current.purchases, previous.purchases)}｜💳 CPS：{money(current_cpp_usd)} {signed_pct(float(current_cpp_usd), float(previous_cpp_usd))}｜✅ 通过率：{ratio_pct(current.approvals, current.applies)}",
    ]


def daily_report(dry_run: bool = False, report_date: str | None = None) -> None:
    settings = load_settings()
    _require_google_ads_config(settings)
    require_config({
        "DINGTALK_WEBHOOK": settings.dingtalk_webhook,
        "ADJUST_USER_TOKEN": settings.adjust_user_token,
        "ADJUST_APP_TOKEN": settings.adjust_app_token,
    })
    tz = ZoneInfo(settings.report_timezone)
    now = datetime.now(tz)
    today = now.date()
    target_day = datetime.fromisoformat(report_date).date() if report_date else today - timedelta(days=1)
    previous_day = target_day - timedelta(days=1)
    rate = get_monthly_rate(settings, today)
    reporter = GoogleAdsReporter(settings)
    fb_reporter = FacebookAdsReporter(settings)
    adjust_reporter = AdjustKpiReporter(settings)
    current = reporter.metrics_for_day(target_day)
    previous = reporter.metrics_for_day(previous_day)
    current_adjust = adjust_reporter.channel_totals(target_day, settings.adjust_google_channels)
    previous_adjust = adjust_reporter.channel_totals(previous_day, settings.adjust_google_channels)
    current.registers = current_adjust.registers
    current.loans = current_adjust.loans
    previous.registers = previous_adjust.registers
    previous.loans = previous_adjust.loans
    save_daily_snapshot(target_day, today, current)

    current_cost = convert_cost(current.cost_inr, rate)
    previous_cost = convert_cost(previous.cost_inr, rate)
    current_reg_cpa = cpa(current_cost, current.registers)
    previous_reg_cpa = cpa(previous_cost, previous.registers)
    actual_loan_cpa = cpa(current_cost, current.loans)
    previous_loan_cpa = cpa(previous_cost, previous.loans)
    fb_current = fb_reporter.daily_reports(target_day) if fb_reporter.enabled else []
    fb_previous = fb_reporter.daily_reports(previous_day) if fb_reporter.enabled else []
    fb_history_start = target_day - timedelta(days=max(settings.loan_estimate_lookback_days, 1) - 1)
    fb_adjust_history = adjust_reporter.channel_totals_by_day(fb_history_start, target_day, settings.adjust_facebook_channels)
    fb_account_history = adjust_reporter.facebook_account_totals_by_day(fb_history_start, target_day)
    fb_current_adjust_total = fb_adjust_history.get(target_day, AdjustKpiMetrics())
    fb_previous_adjust_total = fb_adjust_history.get(previous_day, AdjustKpiMetrics())
    fb_current_adjust_accounts = _facebook_account_metrics_for_day(fb_account_history, target_day, settings)
    fb_previous_adjust_accounts = _facebook_account_metrics_for_day(fb_account_history, previous_day, settings)
    _apply_facebook_report_adjust(fb_current, fb_current_adjust_accounts)
    _apply_facebook_report_adjust(fb_previous, fb_previous_adjust_accounts)
    fb_current_total = _facebook_total_with_adjust(fb_current, fb_current_adjust_total)
    fb_previous_total = _facebook_total_with_adjust(fb_previous, fb_previous_adjust_total)
    fb_current_other_loans = _other_facebook_loans(fb_current_adjust_total, fb_current_adjust_accounts)
    fb_previous_other_loans = _other_facebook_loans(fb_previous_adjust_total, fb_previous_adjust_accounts)
    _save_facebook_history_snapshots(fb_adjust_history, fb_account_history, today, settings)
    fb_current_estimates = _facebook_estimates(target_day, today, fb_current_total, fb_current, fb_current_other_loans)
    fb_previous_estimates = _facebook_estimates(previous_day, today, fb_previous_total, fb_previous, fb_previous_other_loans)

    title = f"{settings.dingtalk_keyword} {settings.report_brand} 日报 {target_day}"
    lines = [
        f"📣 {settings.report_brand} 日报",
        f"推送日期：{today}  统计日期：{target_day}（昨日）",
        "",
    ]
    lines.extend(
        google_daily_lines(
            current,
            previous,
            current_cost,
            previous_cost,
            current_reg_cpa,
            previous_reg_cpa,
            actual_loan_cpa,
            previous_loan_cpa,
        )
    )
    lines.extend(
        fb_daily_lines(
            fb_current,
            fb_previous,
            rate,
            current_total=fb_current_total,
            previous_total=fb_previous_total,
            current_other_loans=fb_current_other_loans,
            previous_other_loans=fb_previous_other_loans,
            current_estimates=fb_current_estimates,
            previous_estimates=fb_previous_estimates,
        )
    )
    lines.append(f"汇率：1 USD = {usd_to_inr(rate)} INR")
    lines.append(DATA_SCOPE_NOTE.format(attribution_source=settings.adjust_attribution_source))
    text = "\n".join(lines)
    send_markdown(settings, title, text, dry_run=dry_run)


def hourly_report(dry_run: bool = False) -> None:
    settings = load_settings()
    _require_google_ads_config(settings)
    require_config({
        "DINGTALK_WEBHOOK": settings.dingtalk_webhook,
        "ADJUST_USER_TOKEN": settings.adjust_user_token,
        "ADJUST_APP_TOKEN": settings.adjust_app_token,
    })
    tz = ZoneInfo(settings.report_timezone)
    now = datetime.now(tz)
    today = now.date()
    yesterday = today - timedelta(days=1)
    hour = max(now.hour - 1, 0)
    rate = get_monthly_rate(settings, today)
    reporter = GoogleAdsReporter(settings)
    fb_reporter = FacebookAdsReporter(settings)
    adjust_reporter = AdjustKpiReporter(settings)
    current = reporter.metrics_until_hour(today, hour)
    previous = reporter.metrics_until_hour(yesterday, hour)
    current_adjust = adjust_reporter.channel_totals_until_hour(today, hour, settings.adjust_google_channels)
    previous_adjust = adjust_reporter.channel_totals_until_hour(yesterday, hour, settings.adjust_google_channels)
    current.registers = current_adjust.registers
    current.loans = current_adjust.loans
    previous.registers = previous_adjust.registers
    previous.loans = previous_adjust.loans
    current_cost = convert_cost(current.cost_inr, rate)
    previous_cost = convert_cost(previous.cost_inr, rate)
    current_cpa = cpa(current_cost, current.registers)
    previous_cpa = cpa(previous_cost, previous.registers)
    current_loan_cpa = cpa(current_cost, current.loans)
    previous_loan_cpa = cpa(previous_cost, previous.loans)
    fb_current = fb_reporter.hourly_reports(today, hour) if fb_reporter.enabled else []
    fb_previous = fb_reporter.hourly_reports(yesterday, hour) if fb_reporter.enabled else []
    fb_current_adjust_total = adjust_reporter.channel_totals_until_hour(today, hour, settings.adjust_facebook_channels)
    fb_previous_adjust_total = adjust_reporter.channel_totals_until_hour(yesterday, hour, settings.adjust_facebook_channels)
    fb_current_adjust_accounts = adjust_reporter.facebook_account_totals_until_hour(today, hour)
    fb_previous_adjust_accounts = adjust_reporter.facebook_account_totals_until_hour(yesterday, hour)
    _apply_facebook_report_adjust(fb_current, fb_current_adjust_accounts)
    _apply_facebook_report_adjust(fb_previous, fb_previous_adjust_accounts)

    title = f"{settings.dingtalk_keyword} {settings.report_brand} 实时数据 {now:%H:%M}"
    lines = [
        f"📣 {settings.report_brand} 实时数据",
        f"印度时间：{now:%H:%M}  统计窗口：{window_label(hour)}",
        "",
    ]
    lines.extend(
        google_hourly_lines(
            current,
            previous,
            current_cost,
            previous_cost,
            current_cpa,
            previous_cpa,
            current_loan_cpa,
            previous_loan_cpa,
        )
    )
    lines.extend(
        fb_hourly_lines(
            fb_current,
            fb_previous,
            rate,
            current_total=_facebook_total_with_adjust(fb_current, fb_current_adjust_total),
            previous_total=_facebook_total_with_adjust(fb_previous, fb_previous_adjust_total),
            current_other_loans=_other_facebook_loans(fb_current_adjust_total, fb_current_adjust_accounts),
            previous_other_loans=_other_facebook_loans(fb_previous_adjust_total, fb_previous_adjust_accounts),
        )
    )
    lines.append(f"汇率：1 USD = {usd_to_inr(rate)} INR")
    lines.append(DATA_SCOPE_NOTE.format(attribution_source=settings.adjust_attribution_source))
    text = "\n".join(lines)
    send_markdown(settings, title, text, dry_run=dry_run)


def _apply_facebook_report_adjust(reports: list[FacebookAccountReport], account_metrics: dict[str, object]) -> None:
    for report in reports:
        metrics = account_metrics.get(report.name)
        report.metrics.registers = metrics.registers if metrics else 0.0
        report.metrics.purchases = metrics.loans if metrics else 0.0
        report.metrics.applies = metrics.applies if metrics else 0.0
        report.metrics.approvals = metrics.approvals if metrics else 0.0


def _facebook_total_with_adjust(
    reports: list[FacebookAccountReport],
    adjust_total: AdjustKpiMetrics,
) -> FacebookMetrics:
    total = total_reports(reports)
    total.registers = adjust_total.registers
    total.purchases = adjust_total.loans
    total.applies = adjust_total.applies
    total.approvals = adjust_total.approvals
    return total


def _other_facebook_loans(total: AdjustKpiMetrics, account_metrics: dict[str, AdjustKpiMetrics]) -> float:
    account_loans = sum(metrics.loans for metrics in account_metrics.values())
    return max(total.loans - account_loans, 0.0)


def _facebook_account_metrics_for_day(
    history: dict[object, dict[str, AdjustKpiMetrics]],
    day,
    settings,
) -> dict[str, AdjustKpiMetrics]:
    totals = {
        name: AdjustKpiMetrics()
        for name, _pattern in settings.adjust_facebook_account_patterns
    }
    totals.update(history.get(day, {}))
    return totals


def _save_facebook_history_snapshots(
    total_history: dict[object, AdjustKpiMetrics],
    account_history: dict[object, dict[str, AdjustKpiMetrics]],
    observed_at,
    settings,
) -> None:
    for report_day, total in total_history.items():
        accounts = _facebook_account_metrics_for_day(account_history, report_day, settings)
        other_loans = _other_facebook_loans(total, accounts)
        save_daily_snapshot(report_day, observed_at, _metrics_from_adjust(total), source="facebook:total")
        for name, metrics in accounts.items():
            save_daily_snapshot(report_day, observed_at, _metrics_from_adjust(metrics), source=f"facebook:{name}")
        save_daily_snapshot(
            report_day,
            observed_at,
            FacebookMetrics(registers=max(total.registers - sum(item.registers for item in accounts.values()), 0.0), purchases=other_loans),
            source="facebook:other",
        )


def _facebook_estimates(
    report_day,
    observed_at,
    total: FacebookMetrics,
    reports: list[FacebookAccountReport],
    other_loans: float,
) -> dict[str, LoanEstimate]:
    estimates = {
        "total": estimate_delayed_loans("facebook:total", report_day, total.purchases, observed_at),
        "other": estimate_delayed_loans("facebook:other", report_day, other_loans, observed_at),
    }
    for report in reports:
        estimates[report.name] = estimate_delayed_loans(
            f"facebook:{report.name}",
            report_day,
            report.metrics.purchases,
            observed_at,
        )
    return estimates


def _metrics_from_adjust(metrics: AdjustKpiMetrics) -> FacebookMetrics:
    return FacebookMetrics(
        registers=metrics.registers,
        purchases=metrics.loans,
        applies=metrics.applies,
        approvals=metrics.approvals,
    )


def _require_google_ads_config(settings) -> None:
    require_config({
        "GOOGLE_ADS_DEVELOPER_TOKEN": settings.developer_token,
        "GOOGLE_ADS_CLIENT_ID": settings.client_id,
        "GOOGLE_ADS_CLIENT_SECRET": settings.client_secret,
        "GOOGLE_ADS_REFRESH_TOKEN": settings.refresh_token,
        "GOOGLE_ADS_CUSTOMER_IDS": ",".join(settings.customer_ids),
    })


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    daily = subparsers.add_parser("daily")
    daily.add_argument("--date", help="Report date in YYYY-MM-DD, defaults to yesterday in report timezone")
    daily.add_argument("--dry-run", action="store_true")
    hourly = subparsers.add_parser("hourly")
    hourly.add_argument("--dry-run", action="store_true")
    policy = subparsers.add_parser("policy")
    policy.add_argument("--dry-run", action="store_true")
    fb_balance = subparsers.add_parser("fb-balance")
    fb_balance.add_argument("--dry-run", action="store_true")
    fb_balance.add_argument("--mode", choices=("all", "balance", "status"), default="all")
    visa_reminder = subparsers.add_parser("visa-reminder")
    visa_reminder.add_argument("--dry-run", action="store_true")
    visa_reminder.add_argument("--period", choices=("daily", "before_work", "before_off_work"), default="daily")
    adjust_channels = subparsers.add_parser("adjust-channels")
    adjust_channels.add_argument("--date", help="Date in YYYY-MM-DD, defaults to yesterday in report timezone")
    adjust_campaigns = subparsers.add_parser("adjust-campaigns")
    adjust_campaigns.add_argument("--date", help="Date in YYYY-MM-DD, defaults to yesterday in report timezone")
    args = parser.parse_args()
    if args.command == "daily":
        daily_report(dry_run=args.dry_run, report_date=args.date)
    elif args.command == "hourly":
        hourly_report(dry_run=args.dry_run)
    elif args.command == "policy":
        run_policy_monitor(dry_run=args.dry_run)
    elif args.command == "fb-balance":
        run_fb_balance_monitor(dry_run=args.dry_run, mode=args.mode)
    elif args.command == "visa-reminder":
        run_visa_balance_reminder(period=args.period, dry_run=args.dry_run)
    elif args.command == "adjust-channels":
        settings = load_settings()
        tz = ZoneInfo(settings.report_timezone)
        day = datetime.fromisoformat(args.date).date() if args.date else datetime.now(tz).date() - timedelta(days=1)
        reporter = AdjustKpiReporter(settings)
        print(f"Adjust KPI channels for {day}:")
        for channel, metrics in sorted(reporter.daily_channel_metrics(day).items()):
            print(
                f"{channel}\tinstalls={number(metrics.installs)}"
                f"\tregisters={number(metrics.registers)}\tloans={number(metrics.loans)}"
            )
    elif args.command == "adjust-campaigns":
        settings = load_settings()
        tz = ZoneInfo(settings.report_timezone)
        day = datetime.fromisoformat(args.date).date() if args.date else datetime.now(tz).date() - timedelta(days=1)
        reporter = AdjustKpiReporter(settings)
        print(f"Adjust Facebook campaigns for {day}:")
        for channel, campaign, metrics in reporter.daily_campaign_metrics(day):
            if channel not in settings.adjust_facebook_channels:
                continue
            matched = ""
            for name, pattern in settings.adjust_facebook_account_patterns:
                if campaign.casefold().startswith(pattern.casefold()):
                    matched = name
                    break
            print(
                f"{matched or 'UNMATCHED'}\t{campaign}\tinstalls={number(metrics.installs)}"
                f"\tregisters={number(metrics.registers)}\tloans={number(metrics.loans)}"
            )


if __name__ == "__main__":
    main()
