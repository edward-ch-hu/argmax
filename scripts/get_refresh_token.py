"""Opens a browser for Google sign-in and saves the refresh token into google-ads.yaml.

Sign in with the Google login that has access to the ad account (directly, or through a manager account). The OAuth
client must be a Desktop app client of the Google Cloud project that has Google Ads API access (Explorer or above):
access levels belong to that project since developer tokens were sunset on 2026-09-09. No developer token needed.

Scopes: Google Ads, plus read-only Google Sheets (only used when crm.source is google_sheets).

Usage: uv run scripts/get_refresh_token.py path/to/client_secret.json
"""
import re
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/adwords", "https://www.googleapis.com/auth/spreadsheets.readonly"]
CONFIG = Path("google-ads.yaml")


def with_token(text, token):
    """google-ads.yaml text with refresh_token set (replaced, or added when the line is missing). Pure."""
    line = f"refresh_token: {token}"
    if re.search(r"^refresh_token:", text, flags=re.MULTILINE):
        return re.sub(r"^refresh_token:.*$", line, text, count=1, flags=re.MULTILINE)
    return text.rstrip("\n") + "\n" + line + "\n"


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    flow = InstalledAppFlow.from_client_secrets_file(sys.argv[1], scopes=SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
    if not CONFIG.exists():
        print("\nNo google-ads.yaml here (cp google-ads.example.yaml google-ads.yaml). Put this line in it:")
        print(f"refresh_token: {creds.refresh_token}")
        return
    CONFIG.write_text(with_token(CONFIG.read_text(), creds.refresh_token))
    print(f"Saved refresh token to {CONFIG}. Next: uv run scripts/check_connection.py (or scripts/accounts.py).")


if __name__ == "__main__":
    main()
