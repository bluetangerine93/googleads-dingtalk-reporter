from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import ROOT, Settings, load_settings, require_config
from .dingtalk import send_markdown_to
from .google_ads import GoogleAdsReporter
from .policy_types import PolicyIssue


STATE_FILE = ROOT / "data" / "policy_alert_state.json"


def _read_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    return json.loads(STATE_FILE.read_text(encoding="utf-8"))


def _write_state(fingerprints: set[str]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps({"fingerprints": sorted(fingerprints)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _format_issue(issue: PolicyIssue) -> str:
    policy_reason = "；".join(issue.policy_topics) if issue.policy_topics else "未返回具体 policy topic"
    return (
        f"产品：PocketMitra 账号：{issue.customer_name}\n"
        f"({issue.customer_id}) 类型：{issue.issue_type} | {issue.approval_status} | {issue.review_status}\n"
        f"Campaign：{issue.campaign_name}\n"
        f"广告组：{issue.ad_group_name}\n"
        f"名称：{issue.item_name}\n"
        f"原因：\n{policy_reason}"
    )


def run_policy_monitor(dry_run: bool = False) -> None:
    settings = load_settings()
    require_config({
        "GOOGLE_ADS_DEVELOPER_TOKEN": settings.developer_token,
        "GOOGLE_ADS_CLIENT_ID": settings.client_id,
        "GOOGLE_ADS_CLIENT_SECRET": settings.client_secret,
        "GOOGLE_ADS_REFRESH_TOKEN": settings.refresh_token,
        "GOOGLE_ADS_CUSTOMER_IDS": ",".join(settings.customer_ids),
        "POLICY_DINGTALK_WEBHOOK": settings.policy_dingtalk_webhook,
    })
    reporter = GoogleAdsReporter(settings)
    tz = ZoneInfo(settings.report_timezone)
    now = datetime.now(tz)
    issues = reporter.policy_issues()
    current_fingerprints = {issue.fingerprint for issue in issues}
    state = _read_state()
    previous_fingerprints = set(state.get("fingerprints", []))
    changed_issues = [issue for issue in issues if issue.fingerprint not in previous_fingerprints]
    if not dry_run:
        _write_state(current_fingerprints)

    if not changed_issues:
        if dry_run:
            print("No new or changed policy issues.")
        return

    title = f"Google Ads拒审提醒 | {now:%Y-%m-%d %H:%M}"
    header = f"Google Ads拒审提醒 | {now:%Y-%m-%d %H:%M}\n\n发现 {len(changed_issues)} 条新增/变化的问题"
    blocks = []
    for issue in changed_issues[:10]:
        blocks.append(_format_issue(issue))
    if len(changed_issues) > 10:
        blocks.append(f"还有 {len(changed_issues) - 10} 条未展示，请到 Google Ads 后台查看。")
    text = header + "\n\n" + "\n\n".join(blocks)
    send_markdown_to(
        settings.policy_dingtalk_webhook,
        settings.policy_dingtalk_secret,
        settings.policy_dingtalk_keyword,
        title,
        text,
        dry_run=dry_run,
    )
