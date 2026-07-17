from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from .adjust import AdjustReporter, apply_adjust_metrics
from .config import load_settings
from .dingtalk import send_markdown
from .estimator import estimate_loans, update_cohort_snapshots
from .facebook_ads import FacebookMetrics, FacebookAdsReporter, total_reports
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
    current: FacebookMetrics,
    previous: FacebookMetrics,
    rate: Decimal,
) -> list[str]:
    if current.spend_inr <= 0 and current.registers <= 0 and current.loans <= 0:
        return []
    return ["", *_fb_daily_block("【Facebook】 两账户合计", current, previous, rate)]


def _fb_daily_block(title: str, current: FacebookMetrics, previous: FacebookMetrics, rate: Decimal) -> list[str]:
    current_spend_usd = convert_inr_decimal(current.spend_inr, rate)
    previous_spend_usd = convert_inr_decimal(previous.spend_inr, rate)
    current_cpa_usd = convert_inr_decimal(current.cpa_inr, rate)
    previous_cpa_usd = convert_inr_decimal(previous.cpa_inr, rate)
    current_cps_usd = convert_inr_decimal(current.cps_inr, rate)
    previous_cps_usd = convert_inr_decimal(previous.cps_inr, rate)
    label = title if title.startswith("【") else f"{title}："
    return [
        f"{label} 💰 昨日花费：{money(current_spend_usd)} {signed_pct(float(current_spend_usd), float(previous_spend_usd))} 📝 昨日注册：{number(current.registers)} {signed_pct(current.registers, previous.registers)} 📈 昨日 CPA：{money(current_cpa_usd)} {signed_pct(float(current_cpa_usd), float(previous_cpa_usd))}",
        f"💵 昨日放款：{number(current.loans)} {signed_pct(current.loans, previous.loans)}  放款成本：{money(current_cps_usd)} {signed_pct(float(current_cps_usd), float(previous_cps_usd))}",
        f"参考 INR：{inr_money(current.spend_inr)}",
    ]


def fb_hourly_lines(
    current: FacebookMetrics,
    previous: FacebookMetrics,
    rate: Decimal,
) -> list[str]:
    if current.spend_inr <= 0 and current.registers <= 0 and current.loans <= 0:
        return []
    return ["", *_fb_hourly_total_block("【Facebook】 两账户合计", current, previous, rate)]


def _fb_hourly_total_block(title: str, current: FacebookMetrics, previous: FacebookMetrics, rate: Decimal) -> list[str]:
    current_spend_usd = convert_inr_decimal(current.spend_inr, rate)
    previous_spend_usd = convert_inr_decimal(previous.spend_inr, rate)
    current_cpa_usd = convert_inr_decimal(current.cpa_inr, rate)
    previous_cpa_usd = convert_inr_decimal(previous.cpa_inr, rate)
    current_cps_usd = convert_inr_decimal(current.cps_inr, rate)
    previous_cps_usd = convert_inr_decimal(previous.cps_inr, rate)
    label = title if title.startswith("【") else f"{title}："
    return [
        f"{label} 💰 今日花费：{money(current_spend_usd)} {signed_pct(float(current_spend_usd), float(previous_spend_usd))} 📝 今日注册：{number(current.registers)} {signed_pct(current.registers, previous.registers)} 📈 今日 CPA：{money(current_cpa_usd)} {signed_pct(float(current_cpa_usd), float(previous_cpa_usd))}",
        f"💵 今日放款：{number(current.loans)} {signed_pct(current.loans, previous.loans)}  放款成本：{money(current_cps_usd)} {signed_pct(float(current_cps_usd), float(previous_cps_usd))}",
        f"昨日参考：花费 {money(previous_spend_usd)} / 注册 {number(previous.registers)} / 放款 {number(previous.loans)} / CPA {money(previous_cpa_usd)} / CPS {money(previous_cps_usd)}",
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
    adjust_reporter = AdjustReporter(settings)
    if not adjust_reporter.enabled:
        raise ValueError("ADJUST_API_TOKEN is required for daily/hourly reports.")
    fb_reporter = FacebookAdsReporter(settings)
    update_cohort_snapshots(adjust_reporter, settings, today)

    current = reporter.metrics_for_day(target_day)
    previous = reporter.metrics_for_day(previous_day)
    apply_adjust_metrics(current, adjust_reporter.metrics_for_day(target_day, channel="google"))
    apply_adjust_metrics(previous, adjust_reporter.metrics_for_day(previous_day, channel="google"))
    estimated_loans, estimate_note = estimate_loans(reporter, settings, target_day, current, today)
    estimated_loans = max(current.loans, round(estimated_loans))
    previous_estimated_loans, _ = estimate_loans(reporter, settings, previous_day, previous, today)
    previous_estimated_loans = max(previous.loans, round(previous_estimated_loans))

    current_cost = convert_cost(current.cost_inr, rate)
    previous_cost = convert_cost(previous.cost_inr, rate)
    current_reg_cpa = cpa(current_cost, current.registers)
    previous_reg_cpa = cpa(previous_cost, previous.registers)
    actual_loan_cpa = cpa(current_cost, current.loans)
    estimated_loan_cpa = cpa(current_cost, estimated_loans)
    previous_estimated_loan_cpa = cpa(previous_cost, previous_estimated_loans)
    fb_current = total_reports(fb_reporter.daily_reports(target_day)) if fb_reporter.enabled else FacebookMetrics()
    fb_previous = total_reports(fb_reporter.daily_reports(previous_day)) if fb_reporter.enabled else FacebookMetrics()
    fb_current_adjust = adjust_reporter.metrics_for_day(target_day, channel="facebook")
    fb_previous_adjust = adjust_reporter.metrics_for_day(previous_day, channel="facebook")
    fb_current.registers = fb_current_adjust.registers
    fb_current.loans = fb_current_adjust.loans
    fb_previous.registers = fb_previous_adjust.registers
    fb_previous.loans = fb_previous_adjust.loans

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
    adjust_reporter = AdjustReporter(settings)
    if not adjust_reporter.enabled:
        raise ValueError("ADJUST_API_TOKEN is required for daily/hourly reports.")
    fb_reporter = FacebookAdsReporter(settings)

    current = reporter.metrics_until_hour(today, hour)
    previous = reporter.metrics_until_hour(yesterday, hour)
    apply_adjust_metrics(current, adjust_reporter.metrics_until_hour(today, hour, channel="google"))
    apply_adjust_metrics(previous, adjust_reporter.metrics_until_hour(yesterday, hour, channel="google"))
    current_cost = convert_cost(current.cost_inr, rate)
    previous_cost = convert_cost(previous.cost_inr, rate)
    current_cpa = cpa(current_cost, current.registers)
    previous_cpa = cpa(previous_cost, previous.registers)
    fb_current = total_reports(fb_reporter.hourly_reports(today, hour)) if fb_reporter.enabled else FacebookMetrics()
    fb_previous = total_reports(fb_reporter.hourly_reports(yesterday, hour)) if fb_reporter.enabled else FacebookMetrics()
    fb_current_adjust = adjust_reporter.metrics_until_hour(today, hour, channel="facebook")
    fb_previous_adjust = adjust_reporter.metrics_until_hour(yesterday, hour, channel="facebook")
    fb_current.registers = fb_current_adjust.registers
    fb_current.loans = fb_current_adjust.loans
    fb_previous.registers = fb_previous_adjust.registers
    fb_previous.loans = fb_previous_adjust.loans

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
    conversions = subparsers.add_parser("conversions")
    conversions.add_argument("--date", help="Date in YYYY-MM-DD, defaults to yesterday in report timezone")
    lag = subparsers.add_parser("loan-lag")
    lag.add_argument("--start", required=True, help="Start date in YYYY-MM-DD")
    lag.add_argument("--end", required=True, help="End date in YYYY-MM-DD")
    adjust_events = subparsers.add_parser("adjust-events")
    adjust_events.add_argument("--search", default="", help="Search Adjust events by name or key")
    args = parser.parse_args()
    if args.command == "daily":
        daily_report(dry_run=args.dry_run, report_date=args.date)
    elif args.command == "hourly":
        hourly_report(dry_run=args.dry_run)
    elif args.command == "policy":
        run_policy_monitor(dry_run=args.dry_run)
    elif args.command == "conversions":
        settings = load_settings()
        tz = ZoneInfo(settings.report_timezone)
        day = datetime.fromisoformat(args.date).date() if args.date else datetime.now(tz).date() - timedelta(days=1)
        reporter = GoogleAdsReporter(settings)
        print(f"Conversion breakdown for {day}:")
        for name, selected, all_value in reporter.conversion_breakdown(day):
            print(f"{selected:,.2f}\tall={all_value:,.2f}\t{name}")
    elif args.command == "loan-lag":
        settings = load_settings()
        reporter = GoogleAdsReporter(settings)
        start = datetime.fromisoformat(args.start).date()
        end = datetime.fromisoformat(args.end).date()
        rows = reporter.conversion_lag_breakdown(settings.loan_conversion_name, settings.loan_conversion_metric, start, end)
        total = sum(rows.values())
        print(f"Loan lag breakdown for {start} to {end}, total={total:,.2f}:")
        for bucket, value in sorted(rows.items()):
            pct = value / total if total else 0
            print(f"{bucket}\t{value:,.2f}\t{pct:.2%}")
    elif args.command == "adjust-events":
        settings = load_settings()
        reporter = AdjustReporter(settings)
        for event in reporter.events(args.search):
            print(f"{event.get('id', '')}\t{event.get('name', '')}\t{','.join(event.get('tokens', []) or [])}")


if __name__ == "__main__":
    main()
