# Google Ads DingTalk Reporter

This project sends Google Ads account reports to a DingTalk robot.

## Reports

- Daily report: runs at 10:10 Asia/Kolkata, which is 12:40 on this Mac in Asia/Shanghai.
- Hourly reports: run at 12:00, 15:00, 18:00, and 21:00 Asia/Kolkata, which are 14:30, 17:30, 20:30, and 23:30 Asia/Shanghai.
- Costs are read in INR and converted to USD with one cached monthly rate.
- Daily loan count uses the current returned loan conversion count plus an estimate. Once the script has accumulated enough daily snapshots, it uses historical D+1 completion factors. Before that, it falls back to the mature historical loan/register rate.

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

The workflow in `.github/workflows/googleads-dingtalk.yml` can run the same reports in GitHub Actions, so the Mac does not need to stay online.

Add these repository secrets in GitHub:

```text
GOOGLE_ADS_DEVELOPER_TOKEN
GOOGLE_ADS_CLIENT_ID
GOOGLE_ADS_CLIENT_SECRET
GOOGLE_ADS_REFRESH_TOKEN
GOOGLE_ADS_LOGIN_CUSTOMER_ID
GOOGLE_ADS_CUSTOMER_IDS
DINGTALK_WEBHOOK
DINGTALK_SECRET
INR_USD_RATE
```

For the current direct-account setup, `GOOGLE_ADS_LOGIN_CUSTOMER_ID` can be left empty and `GOOGLE_ADS_CUSTOMER_IDS` should be `5309400878`.

Scheduled times are written in UTC:

- Daily: `04:40 UTC`, equal to `10:10 Asia/Kolkata`.
- Hourly: `06:30`, `09:30`, `12:30`, `15:30 UTC`, equal to `12:00`, `15:00`, `18:00`, `21:00 Asia/Kolkata`.

You can also run it manually from the Actions tab with `workflow_dispatch`.
