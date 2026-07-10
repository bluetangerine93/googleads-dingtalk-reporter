from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from .config import load_settings
from .dingtalk import send_markdown
from .estimator import estimate_loans, save_daily_snapshot
from .fx import get_monthly_rate
from .google_ads import GoogleAdsReporter, Metrics


def money(value: float | Decimal) -> str:
    amount = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"${amount:,}"


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


def signed_pct(current: float, previous: float) -> str:
    return f"({pct_change(current, previous)})"


def window_label(max_hour: int) -> str:
    if max_hour < 0:
        return "暂无完整小时"
    return f"00:00-{max_hour:02d}:59 IST"


def daily_report(dry_run: bool = False, report_date: str | None = None) -> None:
    settings = load_settings()
    tz = ZoneInfo(settings.report_timezone)
    now = datetime.now(tz)
    today = now.date()
    target_day = datetime.fromisoformat(report_date).date() if report_date else today - timedelta(days=1)
    previous_day = target_day - timedelta(days=1)
    rate = get_monthly_rate(settings, today)
    reporter = GoogleAdsReporter(settings)

    current = reporter.metrics_for_day(target_day)
    previous = reporter.metrics_for_day(previous_day)
    estimated_loans, estimate_note = estimate_loans(reporter, settings, target_day, current, today)
    estimated_loans = max(current.loans, round(estimated_loans))
    save_daily_snapshot(target_day, today, current)

    current_cost = convert_cost(current.cost_inr, rate)
    previous_cost = convert_cost(previous.cost_inr, rate)
    current_reg_cpa = cpa(current_cost, current.registers)
    previous_reg_cpa = cpa(previous_cost, previous.registers)
    estimated_loan_cpa = cpa(current_cost, estimated_loans)
    previous_loan_cpa = cpa(previous_cost, previous.loans)

    title = f"{settings.dingtalk_keyword} {settings.report_brand} 日报 {target_day}"
    text = "\n".join(
        [
            f"📣 {settings.report_brand} 日报 推送日期：{today} 统计日期：{target_day}（昨日）",
            "",
            f"【Google】💰 昨日花费：{money(current_cost)} {signed_pct(float(current_cost), float(previous_cost))}",
            f"昨日注册：{number(current.registers)} {signed_pct(current.registers, previous.registers)} 📈  昨日 CPA：{money(current_reg_cpa)} {signed_pct(float(current_reg_cpa), float(previous_reg_cpa))}",
            "",
            f"💵 放款数：{number(current.loans)} 已回传 / {number(estimated_loans)} 预估",
            f"放款成本：{money(estimated_loan_cpa)} 预估 {signed_pct(float(estimated_loan_cpa), float(previous_loan_cpa))}",
            "",
            f"📝 放款预估：{estimate_note}",
            f"汇率：1 INR = {rate} USD",
        ]
    )
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

    current = reporter.metrics_until_hour(today, hour)
    previous = reporter.metrics_until_hour(yesterday, hour)
    current_cost = convert_cost(current.cost_inr, rate)
    previous_cost = convert_cost(previous.cost_inr, rate)
    current_cpa = cpa(current_cost, current.registers)
    previous_cpa = cpa(previous_cost, previous.registers)

    title = f"{settings.dingtalk_keyword} {settings.report_brand} 实时数据 {now:%H:%M}"
    text = "\n".join(
        [
            f"📣 {settings.report_brand} 实时数据 印度时间：{now:%H:%M} 统计窗口：",
            window_label(hour),
            "",
            f"【Google】💰 今日花费：{money(current_cost)} {signed_pct(float(current_cost), float(previous_cost))} 📝",
            f"今日注册：{number(current.registers)} {signed_pct(current.registers, previous.registers)} 📈 今日 CPA：{money(current_cpa)}",
            signed_pct(float(current_cpa), float(previous_cpa)),
            "",
            f"💰 昨日花费：{money(previous_cost)} 📝 昨日注册：{number(previous.registers)} 📈",
            f"昨日 CPA：{money(previous_cpa)}",
        ]
    )
    send_markdown(settings, title, text, dry_run=dry_run)


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    daily = subparsers.add_parser("daily")
    daily.add_argument("--date", help="Report date in YYYY-MM-DD, defaults to yesterday in report timezone")
    daily.add_argument("--dry-run", action="store_true")
    hourly = subparsers.add_parser("hourly")
    hourly.add_argument("--dry-run", action="store_true")
    conversions = subparsers.add_parser("conversions")
    conversions.add_argument("--date", help="Date in YYYY-MM-DD, defaults to yesterday in report timezone")
    args = parser.parse_args()
    if args.command == "daily":
        daily_report(dry_run=args.dry_run, report_date=args.date)
    elif args.command == "hourly":
        hourly_report(dry_run=args.dry_run)
    elif args.command == "conversions":
        settings = load_settings()
        tz = ZoneInfo(settings.report_timezone)
        day = datetime.fromisoformat(args.date).date() if args.date else datetime.now(tz).date() - timedelta(days=1)
        reporter = GoogleAdsReporter(settings)
        print(f"Conversion breakdown for {day}:")
        for name, selected, all_value in reporter.conversion_breakdown(day):
            print(f"{selected:,.2f}\tall={all_value:,.2f}\t{name}")


if __name__ == "__main__":
    main()
