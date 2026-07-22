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


def parse_named_patterns(raw_value: str) -> tuple[tuple[str, str], ...]:
    patterns: list[tuple[str, str]] = []
    for item in raw_value.split(","):
        if not item.strip() or ":" not in item:
            continue
        name, pattern = item.split(":", 1)
        patterns.append((name.strip(), pattern.strip()))
    return tuple(patterns)


@dataclass(frozen=True)
class Settings:
    developer_token: str
    client_id: str
    client_secret: str
    refresh_token: str
    login_customer_id: str
    customer_ids: tuple[str, ...]
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
    adjust_user_token: str
    adjust_app_token: str
    adjust_register_event_token: str
    adjust_loan_event_token: str
    adjust_grouping: str
    adjust_utc_offset: str
    adjust_attribution_source: str
    adjust_google_channels: tuple[str, ...]
    adjust_facebook_channels: tuple[str, ...]
    adjust_facebook_account_patterns: tuple[tuple[str, str], ...]
    fb_access_token: str
    fb_api_version: str
    fb_daily_accounts: tuple[tuple[str, str], ...]
    fb_balance_threshold_inr: int
    lark_balance_webhook: str
    lark_balance_keyword: str


def load_settings() -> Settings:
    load_dotenv()
    customer_ids = tuple(
        item.replace("-", "").strip()
        for item in env("GOOGLE_ADS_CUSTOMER_IDS").split(",")
        if item.strip()
    )
    settings = Settings(
        developer_token=env("GOOGLE_ADS_DEVELOPER_TOKEN"),
        client_id=env("GOOGLE_ADS_CLIENT_ID"),
        client_secret=env("GOOGLE_ADS_CLIENT_SECRET"),
        refresh_token=env("GOOGLE_ADS_REFRESH_TOKEN"),
        login_customer_id=env("GOOGLE_ADS_LOGIN_CUSTOMER_ID").replace("-", ""),
        customer_ids=customer_ids,
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
        adjust_user_token=env("ADJUST_USER_TOKEN", env("ADJUST_API_TOKEN")),
        adjust_app_token=env("ADJUST_APP_TOKEN", "y23vaaza5vcw"),
        adjust_register_event_token=env("ADJUST_REGISTER_EVENT_TOKEN", "elfwqi"),
        adjust_loan_event_token=env("ADJUST_LOAN_EVENT_TOKEN", "yogqjh"),
        adjust_grouping=env("ADJUST_GROUPING", "partner_name"),
        adjust_utc_offset=env("ADJUST_UTC_OFFSET", "+05:30"),
        adjust_attribution_source=env("ADJUST_ATTRIBUTION_SOURCE", "first"),
        adjust_google_channels=parse_csv(env("ADJUST_GOOGLE_CHANNELS", "Google Ads")),
        adjust_facebook_channels=parse_csv(env("ADJUST_FACEBOOK_CHANNELS", "Facebook")),
        adjust_facebook_account_patterns=parse_named_patterns(
            env("ADJUST_FACEBOOK_ACCOUNT_PATTERNS", "PocketMitra-02:pocketmitra_02,PocketMitra-04:pocketmitra_04")
        ),
        fb_access_token=env("FB_ACCESS_TOKEN", env("FB_TOKEN")),
        fb_api_version=env("FB_API_VERSION", "v19.0"),
        fb_daily_accounts=parse_named_accounts(env("FB_DAILY_ACCOUNTS")),
        fb_balance_threshold_inr=env_int("FB_BALANCE_THRESHOLD_INR", 20000),
        lark_balance_webhook=env("LARK_BALANCE_WEBHOOK"),
        lark_balance_keyword=env("LARK_BALANCE_KEYWORD", "notification"),
    )
    return settings


def require_config(values: dict[str, str]) -> None:
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise ValueError(f"Missing required config: {', '.join(missing)}")
