from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from .adjust_kpi import AdjustKpiReporter
from .config import load_settings
from .dingtalk import send_markdown
from .estimator import estimate_loans, save_daily_snapshot
from .facebook_ads import FacebookAccountReport, FacebookMetrics, FacebookAdsReporter, total_reports
from .fx import get_monthly_rate
from .google_ads import GoogleAdsReporter, Metrics
from .policy_monitor import run_policy_monitor


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
    estimated_loans: int,
    previous_estimated_loans: int,
    estimated_loan_cpa: Decimal,
    previous_estimated_loan_cpa: Decimal,
    estimate_note: str,
) -> list[str]:
    return [
        f"【Google】 💰 昨日花费：{money(current_cost)} {signed_pct(float(current_cost), float(previous_cost))} 📝 昨日注册：{number(current.registers)} {signed_pct(current.registers, previous.registers)} 📈 昨日 CPA：{money(current_reg_cpa)} {signed_pct(float(current_reg_cpa), float(previous_reg_cpa))}",
        "",
        f"💵 实际放款：{number(current.loans)}  实际放款成本：{money(actual_loan_cpa)}",
        f"💵 预估放款：{number(estimated_loans)} {signed_pct(estimated_loans, previous_estimated_loans)}  预估放款成本：{money(estimated_loan_cpa)} {signed_pct(float(estimated_loan_cpa), float(previous_estimated_loan_cpa))}",
        "",
        f"📝 放款预估：{estimate_note}",
    ]


def google_hourly_lines(
    current: Metrics,
    previous: Metrics,
    current_cost: Decimal,
    previous_cost: Decimal,
    current_cpa: Decimal,
    previous_cpa: Decimal,
) -> list[str]:
    return [
        f"【Google】 💰 今日花费：{money(current_cost)} {signed_pct(float(current_cost), float(previous_cost))} 📝 今日注册：{number(current.registers)} {signed_pct(current.registers, previous.registers)} 📈 今日 CPA：{money(current_cpa)} {signed_pct(float(current_cpa), float(previous_cpa))}",
        "",
        f"💰 昨日花费：{money(previous_cost)} 📝 昨日注册：{number(previous.registers)} 📈 昨日 CPA：{money(previous_cpa)}",
    ]


def fb_daily_lines(
    current_reports: list[FacebookAccountReport],
    previous_reports: list[FacebookAccountReport],
    rate: Decimal,
) -> list[str]:
    if not current_reports:
        return []
    previous_by_name = {report.name: report for report in previous_reports}
    current_total = total_reports(current_reports)
    previous_total = total_reports(previous_reports)
    lines = ["", *_fb_daily_block("【Facebook】 两账户合计", current_total, previous_total, rate), ""]
    for report in current_reports:
        previous = previous_by_name.get(report.name, FacebookAccountReport(report.name, report.account_id, FacebookMetrics()))
        lines.extend(_fb_daily_block(report.name, report.metrics, previous.metrics, rate))
        lines.append("")
    return lines


def _fb_daily_block(title: str, current: FacebookMetrics, previous: FacebookMetrics, rate: Decimal) -> list[str]:
    current_spend_usd = convert_inr_decimal(current.spend_inr, rate)
    previous_spend_usd = convert_inr_decimal(previous.spend_inr, rate)
    current_cpp_usd = convert_inr_decimal(current.cost_per_purchase_inr, rate)
    previous_cpp_usd = convert_inr_decimal(previous.cost_per_purchase_inr, rate)
    label = title if title.startswith("【") else f"{title}："
    return [
        f"{label} 💰 昨日花费：{money(current_spend_usd)} {signed_pct(float(current_spend_usd), float(previous_spend_usd))} 🛒 昨日购物：{number(current.purchases)} {signed_pct(current.purchases, previous.purchases)} 💳 购物成本：{money(current_cpp_usd)} {signed_pct(float(current_cpp_usd), float(previous_cpp_usd))}",
        f"参考 INR：{inr_money(current.spend_inr)}",
    ]


def fb_hourly_lines(
    current_reports: list[FacebookAccountReport],
    previous_reports: list[FacebookAccountReport],
    rate: Decimal,
) -> list[str]:
    if not current_reports:
        return []
    current_total = total_reports(current_reports)
    previous_total = total_reports(previous_reports)
    lines = ["", *_fb_hourly_total_block("【Facebook】 两账户合计", current_total, previous_total, rate), ""]
    for report in current_reports:
        lines.extend(_fb_hourly_account_block(report.name, report.metrics, rate))
        lines.append("")
    return lines


def _fb_hourly_total_block(title: str, current: FacebookMetrics, previous: FacebookMetrics, rate: Decimal) -> list[str]:
    current_spend_usd = convert_inr_decimal(current.spend_inr, rate)
    previous_spend_usd = convert_inr_decimal(previous.spend_inr, rate)
    current_cpp_usd = convert_inr_decimal(current.cost_per_purchase_inr, rate)
    previous_cpp_usd = convert_inr_decimal(previous.cost_per_purchase_inr, rate)
    label = title if title.startswith("【") else f"{title}："
    return [
        f"{label} 💰 今日花费：{money(current_spend_usd)} {signed_pct(float(current_spend_usd), float(previous_spend_usd))} 🛒 今日购物：{number(current.purchases)} {signed_pct(current.purchases, previous.purchases)} 💳 购物成本：{money(current_cpp_usd)} {signed_pct(float(current_cpp_usd), float(previous_cpp_usd))}",
        f"昨日参考：花费 {money(previous_spend_usd)} / 购物 {number(previous.purchases)} / 成本 {money(previous_cpp_usd)}",
    ]


def _fb_hourly_account_block(title: str, current: FacebookMetrics, rate: Decimal) -> list[str]:
    current_cpp_usd = convert_inr_decimal(current.cost_per_purchase_inr, rate)
    return [
        f"{title}： 🛒 今日购物：{number(current.purchases)} 💳 购物成本：{money(current_cpp_usd)}",
    ]


def daily_report(dry_run: bool = False, report_date: str | None = None) -> None:
    settings = load_settings()
    tz = ZoneInfo(settings.report_timezone)
    now = datetime.now(tz)
    today = now.date()
    target_day = datetime.fromisoformat(report_date).date() if report_date else today - timedelta(days=1)
    previous_day = target_day - timedelta(days=1)
    rate = get_monthly_rate(settings, today)
    reporter = GoogleAdsReporter(settings)
    fb_reporter = FacebookAdsReporter(settings)
    adjust_reporter = AdjustKpiReporter(settings)
    if not adjust_reporter.enabled:
        raise ValueError("ADJUST_USER_TOKEN and ADJUST_APP_TOKEN are required.")

    current = reporter.metrics_for_day(target_day)
    previous = reporter.metrics_for_day(previous_day)
    current_adjust = adjust_reporter.channel_totals(target_day, settings.adjust_google_channels)
    previous_adjust = adjust_reporter.channel_totals(previous_day, settings.adjust_google_channels)
    current.registers = current_adjust.registers
    current.loans = current_adjust.loans
    previous.registers = previous_adjust.registers
    previous.loans = previous_adjust.loans
    estimated_loans, estimate_note = estimate_loans(reporter, settings, target_day, current, today)
    estimated_loans = max(current.loans, round(estimated_loans))
    previous_estimated_loans, _ = estimate_loans(reporter, settings, previous_day, previous, today)
    previous_estimated_loans = max(previous.loans, round(previous_estimated_loans))
    save_daily_snapshot(target_day, today, current)

    current_cost = convert_cost(current.cost_inr, rate)
    previous_cost = convert_cost(previous.cost_inr, rate)
    current_reg_cpa = cpa(current_cost, current.registers)
    previous_reg_cpa = cpa(previous_cost, previous.registers)
    actual_loan_cpa = cpa(current_cost, current.loans)
    estimated_loan_cpa = cpa(current_cost, estimated_loans)
    previous_estimated_loan_cpa = cpa(previous_cost, previous_estimated_loans)
    fb_current = fb_reporter.daily_reports(target_day) if fb_reporter.enabled else []
    fb_previous = fb_reporter.daily_reports(previous_day) if fb_reporter.enabled else []
    _apply_facebook_report_adjust(fb_current, adjust_reporter.facebook_account_totals(target_day))
    _apply_facebook_report_adjust(fb_previous, adjust_reporter.facebook_account_totals(previous_day))

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
            estimated_loans,
            previous_estimated_loans,
            estimated_loan_cpa,
            previous_estimated_loan_cpa,
            estimate_note,
        )
    )
    lines.extend(fb_daily_lines(fb_current, fb_previous, rate))
    lines.append(f"汇率：1 USD = {usd_to_inr(rate)} INR")
    text = "\n".join(lines)
    send_markdown(settings, title, text, dry_run=dry_run)


def hourly_report(dry_run: bool = False) -> None:
    settings = load_settings()
    tz = ZoneInfo(settings.report_timezone)
    now = datetime.now(tz)
    today = now.date()
    yesterday = today - timedelta(days=1)
    hour = max(now.hour - 1, 0)
    rate = get_monthly_rate(settings, today)
    reporter = GoogleAdsReporter(settings)
    fb_reporter = FacebookAdsReporter(settings)
    adjust_reporter = AdjustKpiReporter(settings)
    if not adjust_reporter.enabled:
        raise ValueError("ADJUST_USER_TOKEN and ADJUST_APP_TOKEN are required.")

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
    fb_current = fb_reporter.hourly_reports(today, hour) if fb_reporter.enabled else []
    fb_previous = fb_reporter.hourly_reports(yesterday, hour) if fb_reporter.enabled else []
    _apply_facebook_report_adjust(fb_current, adjust_reporter.facebook_account_totals_until_hour(today, hour))
    _apply_facebook_report_adjust(fb_previous, adjust_reporter.facebook_account_totals_until_hour(yesterday, hour))

    title = f"{settings.dingtalk_keyword} {settings.report_brand} 实时数据 {now:%H:%M}"
    lines = [
        f"📣 {settings.report_brand} 实时数据",
        f"印度时间：{now:%H:%M}  统计窗口：{window_label(hour)}",
        "",
    ]
    lines.extend(google_hourly_lines(current, previous, current_cost, previous_cost, current_cpa, previous_cpa))
    lines.extend(fb_hourly_lines(fb_current, fb_previous, rate))
    text = "\n".join(lines)
    send_markdown(settings, title, text, dry_run=dry_run)


def _apply_facebook_report_adjust(reports: list[FacebookAccountReport], account_metrics: dict[str, object]) -> None:
    for report in reports:
        metrics = account_metrics.get(report.name)
        report.metrics.purchases = metrics.loans if metrics else 0.0


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
