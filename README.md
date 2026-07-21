# Google Ads DingTalk Reporter

This project sends Google Ads account reports to a DingTalk robot.

## Reports

- Daily report: runs at 10:00 Asia/Shanghai, which is 07:30 Asia/Kolkata.
- Hourly reports: run at 12:00, 15:00, 18:00, and 21:00 Asia/Kolkata, which are 14:30, 17:30, 20:30, and 23:30 Asia/Shanghai.
- Costs are read from Google Ads and Facebook ad accounts in INR and converted to USD with one cached monthly rate.
- Google Ads and Facebook conversion/event counts are read from Adjust KPI Service by channel. Ad account conversion/action counts are not used in reports.
- Daily loan count uses the current returned Adjust loan event count plus an estimate. Once the script has accumulated enough daily snapshots, it uses historical D+1 completion factors. Before that, it uses the current returned value.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Test

```bash
python3 -m googleads_dingtalk daily --dry-run
python3 -m googleads_dingtalk hourly --dry-run
```

Remove `--dry-run` to send to DingTalk.

## Regenerate Google Ads refresh token

If Google returns `invalid_grant`, generate a new token:

```bash
source .venv/bin/activate
python scripts/generate_refresh_token.py
```

Authorize with a Google account that has access to the MCC or ad account, then replace `GOOGLE_ADS_REFRESH_TOKEN` in `.env`.

## Install launchd jobs

```bash
mkdir -p ~/Library/LaunchAgents
cp launchd/com.jasmine.googleads.daily.plist ~/Library/LaunchAgents/
cp launchd/com.jasmine.googleads.hourly.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.jasmine.googleads.daily.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.jasmine.googleads.hourly.plist
```

## Run once manually

```bash
scripts/run_report.sh daily
scripts/run_report.sh hourly
```

## GitHub Actions

The report workflow in `.github/workflows/googleads-dingtalk.yml` and the policy monitor workflow in `.github/workflows/googleads-policy-monitor.yml` run in GitHub Actions, so the Mac does not need to stay online. Scheduled runs are triggered by cron-job.org through GitHub's `repository_dispatch` API.

Add these repository secrets in GitHub:

```text
GOOGLE_ADS_DEVELOPER_TOKEN
GOOGLE_ADS_CLIENT_ID
GOOGLE_ADS_CLIENT_SECRET
GOOGLE_ADS_REFRESH_TOKEN
GOOGLE_ADS_LOGIN_CUSTOMER_ID
GOOGLE_ADS_CUSTOMER_IDS
FB_TOKEN
ADJUST_API_TOKEN
DINGTALK_WEBHOOK
POLICY_DINGTALK_WEBHOOK
POLICY_DINGTALK_SECRET
DINGTALK_SECRET
INR_USD_RATE
```

For the current direct-account setup, `GOOGLE_ADS_LOGIN_CUSTOMER_ID` can be left empty and `GOOGLE_ADS_CUSTOMER_IDS` should be `5309400878`.

Report times:

- Daily: `10:00 Asia/Shanghai`.
- Hourly: `12:00`, `15:00`, `18:00`, `21:00 Asia/Kolkata`, equal to `14:30`, `17:30`, `20:30`, `23:30 Asia/Shanghai`.
- Policy monitor: every 30 minutes if configured in cron-job.org.

You can also run it manually from the Actions tab with `workflow_dispatch`.

Adjust KPI settings:

```text
ADJUST_APP_TOKEN=y23vaaza5vcw
ADJUST_REGISTER_EVENT_TOKEN=elfwqi
ADJUST_LOAN_EVENT_TOKEN=yogqjh
ADJUST_GROUPING=partner_name
ADJUST_UTC_OFFSET=+05:30
ADJUST_ATTRIBUTION_SOURCE=first
ADJUST_GOOGLE_CHANNELS=Google Ads
ADJUST_FACEBOOK_CHANNELS=Facebook
ADJUST_FACEBOOK_ACCOUNT_PATTERNS=PocketMitra-02:pocketmitra_02,PocketMitra-04:pocketmitra_04
```

## External cron trigger

Use an external scheduler such as cron-job.org to call GitHub's `repository_dispatch` API.

Endpoint:

```text
POST https://api.github.com/repos/bluetangerine93/googleads-dingtalk-reporter/dispatches
```

Required headers:

```text
Accept: application/vnd.github+json
Authorization: Bearer YOUR_GITHUB_TOKEN
X-GitHub-Api-Version: 2022-11-28
Content-Type: application/json
```

Hourly report body:

```json
{"event_type":"googleads_report","client_payload":{"report_type":"hourly","dry_run":"false"}}
```

Daily report body:

```json
{"event_type":"googleads_report","client_payload":{"report_type":"daily","dry_run":"false"}}
```

Policy monitor body:

```json
{"event_type":"googleads_policy_monitor","client_payload":{"dry_run":"false"}}
```
