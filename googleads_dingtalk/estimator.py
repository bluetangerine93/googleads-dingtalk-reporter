from __future__ import annotations

import json
import statistics
from datetime import date, timedelta
from pathlib import Path

from .config import ROOT, Settings
from .google_ads import GoogleAdsReporter, Metrics


SNAPSHOTS = ROOT / "data" / "daily_snapshots.json"


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


def estimate_loans(
    reporter: GoogleAdsReporter,
    settings: Settings,
    report_day: date,
    observed_metrics: Metrics,
    observed_at: date,
) -> tuple[float, str]:
    factor_estimate = _estimate_from_snapshot_factor(report_day, observed_metrics.loans, observed_at)
    if factor_estimate is not None:
        return factor_estimate, "基于历史 D+1 回传完成率"

    return observed_metrics.loans, "Adjust cohort 样本不足，使用当前已回传值"


def _estimate_from_snapshot_factor(report_day: date, observed_loans: float, observed_at: date) -> float | None:
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
        final = current_snapshots[-1][1]
        early_loans = float(early.get("loans", 0))
        final_loans = float(final.get("loans", 0))
        if early_loans > 0 and final_loans >= early_loans:
            factors.append(final_loans / early_loans)
    if len(factors) < 3:
        return None
    return observed_loans * statistics.median(factors)
