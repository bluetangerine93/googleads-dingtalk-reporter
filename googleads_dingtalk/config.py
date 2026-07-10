from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_dotenv(path: Path = ROOT / ".env") -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def env_int(name: str, default: int) -> int:
    value = env(name)
    return int(value) if value else default


@dataclass(frozen=True)
class Settings:
    developer_token: str
    client_id: str
    client_secret: str
    refresh_token: str
    login_customer_id: str
    customer_ids: tuple[str, ...]
    conversion_metric: str
    register_conversion_metric: str
    loan_conversion_metric: str
    register_conversion_name: str
    loan_conversion_name: str
    dingtalk_webhook: str
    dingtalk_keyword: str
    dingtalk_secret: str
    policy_dingtalk_webhook: str
    policy_dingtalk_keyword: str
    policy_dingtalk_secret: str
    report_timezone: str
    account_currency: str
    target_currency: str
    inr_usd_rate: str
    report_brand: str
    loan_estimate_lookback_days: int
    loan_estimate_exclude_recent_days: int


def load_settings() -> Settings:
    load_dotenv()
    customer_ids = tuple(
        item.replace("-", "").strip()
        for item in env("GOOGLE_ADS_CUSTOMER_IDS").split(",")
        if item.strip()
    )
    conversion_metric = env("GOOGLE_ADS_CONVERSION_METRIC", "conversions")
    if conversion_metric not in {"conversions", "all_conversions"}:
        raise ValueError("GOOGLE_ADS_CONVERSION_METRIC must be conversions or all_conversions")
    register_conversion_metric = env("REGISTER_CONVERSION_METRIC", conversion_metric)
    loan_conversion_metric = env("LOAN_CONVERSION_METRIC", conversion_metric)
    for name, value in {
        "REGISTER_CONVERSION_METRIC": register_conversion_metric,
        "LOAN_CONVERSION_METRIC": loan_conversion_metric,
    }.items():
        if value not in {"conversions", "all_conversions"}:
            raise ValueError(f"{name} must be conversions or all_conversions")
    settings = Settings(
        developer_token=env("GOOGLE_ADS_DEVELOPER_TOKEN"),
        client_id=env("GOOGLE_ADS_CLIENT_ID"),
        client_secret=env("GOOGLE_ADS_CLIENT_SECRET"),
        refresh_token=env("GOOGLE_ADS_REFRESH_TOKEN"),
        login_customer_id=env("GOOGLE_ADS_LOGIN_CUSTOMER_ID").replace("-", ""),
        customer_ids=customer_ids,
        conversion_metric=conversion_metric,
        register_conversion_metric=register_conversion_metric,
        loan_conversion_metric=loan_conversion_metric,
        register_conversion_name=env("REGISTER_CONVERSION_NAME"),
        loan_conversion_name=env("LOAN_CONVERSION_NAME"),
        dingtalk_webhook=env("DINGTALK_WEBHOOK"),
        dingtalk_keyword=env("DINGTALK_KEYWORD", "推送"),
        dingtalk_secret=env("DINGTALK_SECRET"),
        policy_dingtalk_webhook=env("POLICY_DINGTALK_WEBHOOK", env("DINGTALK_WEBHOOK")),
        policy_dingtalk_keyword=env("POLICY_DINGTALK_KEYWORD", "拒审"),
        policy_dingtalk_secret=env("POLICY_DINGTALK_SECRET"),
        report_timezone=env("REPORT_TIMEZONE", "Asia/Kolkata"),
        account_currency=env("ACCOUNT_CURRENCY", "INR"),
        target_currency=env("TARGET_CURRENCY", "USD"),
        inr_usd_rate=env("INR_USD_RATE"),
        report_brand=env("REPORT_BRAND", "PocketMitra"),
        loan_estimate_lookback_days=env_int("LOAN_ESTIMATE_LOOKBACK_DAYS", 28),
        loan_estimate_exclude_recent_days=env_int("LOAN_ESTIMATE_EXCLUDE_RECENT_DAYS", 7),
    )
    missing = [
        name
        for name, value in {
            "GOOGLE_ADS_DEVELOPER_TOKEN": settings.developer_token,
            "GOOGLE_ADS_CLIENT_ID": settings.client_id,
            "GOOGLE_ADS_CLIENT_SECRET": settings.client_secret,
            "GOOGLE_ADS_REFRESH_TOKEN": settings.refresh_token,
            "GOOGLE_ADS_CUSTOMER_IDS": ",".join(settings.customer_ids),
            "REGISTER_CONVERSION_NAME": settings.register_conversion_name,
            "LOAN_CONVERSION_NAME": settings.loan_conversion_name,
            "DINGTALK_WEBHOOK": settings.dingtalk_webhook,
        }.items()
        if not value
    ]
    if missing:
        raise ValueError(f"Missing required config: {', '.join(missing)}")
    return settings
