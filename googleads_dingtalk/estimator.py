from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from .config import ROOT, Settings
from .google_ads import GoogleAdsReporter, Metrics


SNAPSHOTS = ROOT / "data" / "daily_snapshots.json"


@dataclass(frozen=True)
class LoanEstimate:
    observed_loans: float
    estimated_loans: float
    completion_rate: float
    sample_count: int
    basis: str


def _read_snapshots() -> dict:
    if not SNAPSHOTS.exists():
        return {}
    return json.loads(SNAPSHOTS.read_text(encoding="utf-8"))


def save_daily_snapshot(report_day: date, observed_at: date, metrics, source: str = "google") -> None:
    data = _read_snapshots()
    day_key = report_day.isoformat()
    payload = {
        "cost_inr": _metric_value(metrics, "cost_inr", "spend_inr"),
        "registers": _metric_value(metrics, "registers"),
        "loans": _metric_value(metrics, "loans", "purchases"),
    }
    if source == "google":
        data.setdefault(day_key, {})
        data[day_key][observed_at.isoformat()] = payload
    data.setdefault("_sources", {}).setdefault(source, {}).setdefault(day_key, {})
    data["_sources"][source][day_key][observed_at.isoformat()] = payload
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


def estimate_delayed_loans(source: str, report_day: date, observed_loans: float, observed_at: date) -> LoanEstimate:
    if observed_loans <= 0:
        return LoanEstimate(
            observed_loans=observed_loans,
            estimated_loans=observed_loans,
            completion_rate=1.0,
            sample_count=0,
            basis="当前无已回传放款",
        )
    age_days = max((observed_at - report_day).days, 0)
    rates = _completion_rates(source, report_day, observed_at)
    if len(rates) < 3:
        return LoanEstimate(
            observed_loans=observed_loans,
            estimated_loans=observed_loans,
            completion_rate=1.0,
            sample_count=len(rates),
            basis=f"历史 T+{age_days} 样本不足，使用当前已回传值",
        )
    completion_rate = min(max(statistics.median(rates), 0.01), 1.0)
    return LoanEstimate(
        observed_loans=observed_loans,
        estimated_loans=observed_loans / completion_rate,
        completion_rate=completion_rate,
        sample_count=len(rates),
        basis=f"基于历史 T+{age_days} 回传完成率",
    )


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


def _completion_rates(source: str, report_day: date, observed_at: date) -> list[float]:
    age_days = max((observed_at - report_day).days, 0)
    source_data = _source_snapshots(source)
    rates: list[float] = []
    for day_key, snapshots in source_data.items():
        historical_day = date.fromisoformat(day_key)
        if historical_day >= report_day:
            continue
        early_day = historical_day + timedelta(days=age_days)
        early = snapshots.get(early_day.isoformat())
        if not early:
            continue
        later_snapshots = [
            (date.fromisoformat(snapshot_day), snapshot)
            for snapshot_day, snapshot in snapshots.items()
            if date.fromisoformat(snapshot_day) > early_day
        ]
        if not later_snapshots:
            continue
        _final_day, final = sorted(later_snapshots, key=lambda item: item[0])[-1]
        early_loans = float(early.get("loans", 0))
        final_loans = float(final.get("loans", 0))
        if early_loans > 0 and final_loans >= early_loans:
            rates.append(early_loans / final_loans)
    return rates


def _source_snapshots(source: str) -> dict:
    data = _read_snapshots()
    source_data = dict(data.get("_sources", {}).get(source, {}))
    if source == "google":
        for day_key, snapshots in data.items():
            if day_key.startswith("_") or not isinstance(snapshots, dict):
                continue
            source_data.setdefault(day_key, snapshots)
    return source_data


def _metric_value(metrics, *names: str) -> float:
    for name in names:
        if hasattr(metrics, name):
            return float(getattr(metrics, name) or 0)
    return 0.0
