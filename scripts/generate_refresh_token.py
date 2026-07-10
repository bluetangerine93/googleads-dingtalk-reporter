from __future__ import annotations

import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from googleads_dingtalk.config import env, load_dotenv  # noqa: E402


SCOPES = ["https://www.googleapis.com/auth/adwords"]


def main() -> None:
    load_dotenv()
    client_id = env("GOOGLE_ADS_CLIENT_ID")
    client_secret = env("GOOGLE_ADS_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise SystemExit("GOOGLE_ADS_CLIENT_ID and GOOGLE_ADS_CLIENT_SECRET are required in .env")
    flow = InstalledAppFlow.from_client_config(
        {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost"],
            }
        },
        scopes=SCOPES,
    )
    credentials = flow.run_local_server(
        port=0,
        prompt="consent",
        authorization_prompt_message="Open this URL and authorize Google Ads access:\n{url}",
    )
    print("\nNew refresh token:\n")
    print(credentials.refresh_token)
    print("\nPut this value into GOOGLE_ADS_REFRESH_TOKEN in .env")


if __name__ == "__main__":
    main()
