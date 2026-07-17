from __future__ import annotations

import json
import statistics
from datetime import date, timedelta
from pathlib import Path

from .config import ROOT, Settings
from .google_ads import GoogleAdsReporter, Metrics


SNAPSHOTS = ROOT / "data" / "adjust_daily_snapshots.json"


def _read_snapshots() -> dict:
    if not SNAPSHOTS.exists():
        return {}
    return json.loads(SNAPSHOTS.read_text(encoding="utf-8"))


def save_daily_snapshot(report_day: date, observed_at: date, metrics: Metrics) -> None:
    data = _read_snapshots()
    day_key = report_day.isoformat()
    data.setdefault(day_key, {})
    data[day_key][observed_at.isoformat()] = {
        "cost_inr": metrics.cost_inr,
        "registers": metrics.registers,
        "loans": metrics.loans,
    }
    SNAPSHOTS.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOTS.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def update_cohort_snapshots(reporter: GoogleAdsReporter, settings: Settings, observed_at: date) -> None:
    start = observed_at - timedelta(days=settings.loan_cohort_track_days)
    end = observed_at - timedelta(days=1)
    if start > end:
        return
    data = _read_snapshots()
    for report_day, metrics in reporter.metrics_by_day(start, end).items():
        day_key = report_day.isoformat()
        data.setdefault(day_key, {})
        data[day_key][observed_at.isoformat()] = {
            "cost_inr": getattr(metrics, "cost_inr", 0),
            "registers": metrics.registers,
            "loans": metrics.loans,
        }
    SNAPSHOTS.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOTS.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def estimate_loans(
    reporter: GoogleAdsReporter,
    settings: Settings,
    report_day: date,
    observed_metrics: Metrics,
    observed_at: date,
) -> tuple[float, str]:
    factor_estimate = _estimate_from_snapshot_factor(settings, report_day, observed_metrics.loans, observed_at)
    if factor_estimate is not None:
        return factor_estimate

    return observed_metrics.loans, "自有 Adjust cohort 样本不足，使用当前已回传值"


def _estimate_from_conversion_lag_curve(
    reporter: GoogleAdsReporter,
    settings: Settings,
    report_day: date,
    observed_metrics: Metrics,
    observed_at: date,
) -> tuple[float, str] | None:
    if observed_metrics.loans <= 0:
        return None
    end = report_day - timedelta(days=settings.loan_estimate_exclude_recent_days)
    start = end - timedelta(days=settings.loan_estimate_lookback_days - 1)
    if start > end:
        return None
    lag_rows = reporter.conversion_lag_breakdown(
        settings.loan_conversion_name,
        settings.loan_conversion_metric,
        start,
        end,
    )
    total_mature_loans = sum(lag_rows.values())
    if total_mature_loans <= 0:
        return None
    age_days = max((observed_at - report_day).days, 1)
    completed_loans = sum(
        value
        for bucket, value in lag_rows.items()
        if _lag_bucket_upper_day(bucket) <= age_days
    )
    completion_rate = completed_loans / total_mature_loans
    if completion_rate <= 0:
        return None
    estimated = observed_metrics.loans / completion_rate
    note = (
        f"基于近{settings.loan_estimate_lookback_days}天成熟 cohort "
        f"D+{age_days} 回传完成率 {completion_rate:.2%}"
    )
    return max(observed_metrics.loans, estimated), note


def _lag_bucket_upper_day(bucket: str) -> int:
    upper_days = {
        "LESS_THAN_ONE_DAY": 1,
        "ONE_TO_TWO_DAYS": 2,
        "TWO_TO_THREE_DAYS": 3,
        "THREE_TO_FOUR_DAYS": 4,
        "FOUR_TO_FIVE_DAYS": 5,
        "FIVE_TO_SIX_DAYS": 6,
        "SIX_TO_SEVEN_DAYS": 7,
        "SEVEN_TO_EIGHT_DAYS": 8,
        "EIGHT_TO_NINE_DAYS": 9,
        "NINE_TO_TEN_DAYS": 10,
        "TEN_TO_ELEVEN_DAYS": 11,
        "ELEVEN_TO_TWELVE_DAYS": 12,
        "TWELVE_TO_THIRTEEN_DAYS": 13,
        "THIRTEEN_TO_FOURTEEN_DAYS": 14,
        "FOURTEEN_TO_TWENTY_ONE_DAYS": 21,
        "TWENTY_ONE_TO_THIRTY_DAYS": 30,
        "THIRTY_TO_FORTY_FIVE_DAYS": 45,
        "FORTY_FIVE_TO_SIXTY_DAYS": 60,
        "SIXTY_TO_NINETY_DAYS": 90,
    }
    return upper_days.get(bucket, 999)


def _estimate_from_snapshot_factor(
    settings: Settings,
    report_day: date,
    observed_loans: float,
    observed_at: date,
) -> tuple[float, str] | None:
    if observed_loans <= 0:
        return None
    data = _read_snapshots()
    age_days = (observed_at - report_day).days
    factors: list[float] = []
    for day_key, snapshots in data.items():
        historical_day = date.fromisoformat(day_key)
        early_day = historical_day + timedelta(days=age_days)
        early = snapshots.get(early_day.isoformat())
        if not early:
            continue
        current_snapshots = sorted(snapshots.items())
        if not current_snapshots:
            continue
        final_observed_at = date.fromisoformat(current_snapshots[-1][0])
        if (final_observed_at - historical_day).days < settings.loan_estimate_exclude_recent_days:
            continue
        final = current_snapshots[-1][1]
        early_loans = float(early.get("loans", 0))
        final_loans = float(final.get("loans", 0))
        if early_loans > 0 and final_loans >= early_loans:
            factors.append(final_loans / early_loans)
    if len(factors) < 3:
        return None
    median_factor = statistics.median(factors)
    completion_rate = 1 / median_factor
    note = f"基于自有 cohort D+{age_days} 回传完成率 {completion_rate:.2%}（{len(factors)}天样本）"
    return observed_loans * median_factor, note
