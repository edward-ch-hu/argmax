"""Opens a browser for Google sign-in and saves the refresh token into google-ads.yaml.

Scopes: Google Ads, plus read-only Google Sheets (only used when crm.source is google_sheets).

Usage: uv run scripts/get_refresh_token.py path/to/client_secret.json
"""
import re
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/adwords", "https://www.googleapis.com/auth/spreadsheets.readonly"]
CONFIG = Path("google-ads.yaml")


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    flow = InstalledAppFlow.from_client_secrets_file(sys.argv[1], scopes=SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
    if not CONFIG.exists():
        print(f"\nrefresh_token: {creds.refresh_token}")
        return
    text = re.sub(r"^refresh_token:.*$", f"refresh_token: {creds.refresh_token}", CONFIG.read_text(), flags=re.MULTILINE)
    CONFIG.write_text(text)
    print(f"Saved refresh token to {CONFIG}.")


if __name__ == "__main__":
    main()
