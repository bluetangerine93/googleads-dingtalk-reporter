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


def parse_named_accounts(raw_value: str) -> tuple[tuple[str, str], ...]:
    accounts: list[tuple[str, str]] = []
    for item in raw_value.split(","):
        if not item.strip() or ":" not in item:
            continue
        name, account_id = item.split(":", 1)
        accounts.append((name.strip(), account_id.strip()))
    return tuple(accounts)


def parse_csv(raw_value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in raw_value.split(",") if item.strip())


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
    loan_cohort_track_days: int
    adjust_api_token: str
    adjust_app_tokens: tuple[str, ...]
    adjust_register_metric: str
    adjust_loan_metric: str
    adjust_register_event_search: str
    adjust_loan_event_search: str
    adjust_filter_dimension: str
    adjust_google_filter_contains: tuple[str, ...]
    adjust_facebook_filter_contains: tuple[str, ...]
    adjust_attribution_source: str
    fb_access_token: str
    fb_api_version: str
    fb_daily_accounts: tuple[tuple[str, str], ...]


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
        loan_cohort_track_days=env_int("LOAN_COHORT_TRACK_DAYS", 45),
        adjust_api_token=env("ADJUST_API_TOKEN"),
        adjust_app_tokens=parse_csv(env("ADJUST_APP_TOKENS")),
        adjust_register_metric=env("ADJUST_REGISTER_METRIC"),
        adjust_loan_metric=env("ADJUST_LOAN_METRIC"),
        adjust_register_event_search=env("ADJUST_REGISTER_EVENT_SEARCH", "register_success"),
        adjust_loan_event_search=env("ADJUST_LOAN_EVENT_SEARCH", "first_loan_success"),
        adjust_filter_dimension=env("ADJUST_FILTER_DIMENSION", "network"),
        adjust_google_filter_contains=parse_csv(env("ADJUST_GOOGLE_FILTER_CONTAINS", env("ADJUST_FILTER_CONTAINS", "Google Ads"))),
        adjust_facebook_filter_contains=parse_csv(env("ADJUST_FACEBOOK_FILTER_CONTAINS", "Facebook,Instagram")),
        adjust_attribution_source=env("ADJUST_ATTRIBUTION_SOURCE", "first"),
        fb_access_token=env("FB_ACCESS_TOKEN", env("FB_TOKEN")),
        fb_api_version=env("FB_API_VERSION", "v19.0"),
        fb_daily_accounts=parse_named_accounts(env("FB_DAILY_ACCOUNTS")),
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
