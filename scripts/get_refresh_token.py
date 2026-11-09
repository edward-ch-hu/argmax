"""Google sign-in that saves the refresh token into google-ads.yaml. The token is never printed.

Sign in with the Google login that has access to the ad account (directly, or through a manager account). The OAuth
client must be a Desktop app client of the Google Cloud project that has Google Ads API access (Explorer or above):
access levels belong to that project since developer tokens were sunset on 2026-09-09. No developer token needed.

Before you run it: the project's OAuth consent screen must be published ("In production", Google Auth Platform,
Audience). An External app left in "Testing" gets refresh tokens that expire after 7 days, and every routine then
fails with invalid_grant. Google shows "Google hasn't verified this app" on the consent page of a personal app in
production: expected and safe to click through (Advanced, Go to argmax), since you are both the developer and the
only user.

google-ads.yaml is created from google-ads.example.yaml when it is missing; its client_id and client_secret are
filled from the client secret JSON when they are still placeholders. The file is made readable by you only.

Two ways to sign in:
- a browser on this machine (the default): one opens, you accept, done.
- --console, for a machine without a browser (a server, a container, an SSH session; automatic when no browser is
  found): it prints a sign-in URL. Open it in a browser on any device and accept. That browser then lands on an
  http://localhost page that fails to load: that is expected. Copy the full address from its address bar and paste
  it here. The address holds a one-time code (not the token) that this script exchanges at once.

Scopes: Google Ads, plus read-only Google Sheets (only used when crm.source is google_sheets).

Usage: uv run scripts/get_refresh_token.py path/to/client_secret.json [--console]
"""
import os
import re
import sys
import webbrowser
from pathlib import Path
from urllib.parse import parse_qs, urlparse

SCOPES = ["https://www.googleapis.com/auth/adwords", "https://www.googleapis.com/auth/spreadsheets.readonly"]
CONFIG = Path("google-ads.yaml")
EXAMPLE = Path("google-ads.example.yaml")
# The console flow's redirect: Desktop app clients accept any loopback port, and nothing has to listen on it.
CONSOLE_REDIRECT = "http://localhost:8765/"


def with_value(text, key, value):
    """google-ads.yaml text with `key` set to a quoted value (replaced, or added when the line is missing). Pure."""
    line = f'{key}: "{value}"'
    if re.search(rf"^{key}:", text, flags=re.MULTILINE):
        return re.sub(rf"^{key}:.*$", lambda _: line, text, count=1, flags=re.MULTILINE)
    return text.rstrip("\n") + "\n" + line + "\n"


def with_token(text, token):
    return with_value(text, "refresh_token", token)


def credentials_text(text, token, client_id=None, client_secret=None):
    """google-ads.yaml text with the refresh token set, and client_id / client_secret filled in when they are still
    missing or placeholders. Pure."""
    import yaml
    from ads_client import placeholder

    current = (yaml.safe_load(text) or {}) if text.strip() else {}
    for key, value in (("client_id", client_id), ("client_secret", client_secret)):
        if value and placeholder(current.get(key)):
            text = with_value(text, key, value)
    return with_token(text, token)


def code_from(pasted):
    """The authorization code from the address the browser landed on (or the bare code). Raises SystemExit."""
    pasted = pasted.strip()
    if not pasted:
        raise SystemExit("FAIL   nothing pasted: run the script again")
    if "://" not in pasted and "=" not in pasted:
        return pasted
    query = parse_qs(urlparse(pasted).query)
    if "error" in query:
        raise SystemExit(f"FAIL   Google answered: {query['error'][0]} (sign in again and accept)")
    if "code" not in query:
        raise SystemExit("FAIL   no code= in that address: copy the whole address of the page you landed on")
    return query["code"][0]


def has_browser():
    try:
        webbrowser.get()
        return True
    except webbrowser.Error:
        return False


def console_sign_in(flow):
    flow.redirect_uri = CONSOLE_REDIRECT
    url, _ = flow.authorization_url(prompt="consent", access_type="offline")
    print("Open this address in a browser on any device, sign in with the login that opens the ad account, accept:\n")
    print(url)
    print("\nThe browser then shows a page that does not load (http://localhost...). That is expected.")
    flow.fetch_token(code=code_from(input("Paste that page's full address here: ")))
    return flow.credentials


def save(creds):
    created = not CONFIG.exists()
    text = CONFIG.read_text() if not created else (EXAMPLE.read_text() if EXAMPLE.exists() else "")
    CONFIG.write_text(credentials_text(text, creds.refresh_token, creds.client_id, creds.client_secret))
    try:
        os.chmod(CONFIG, 0o600)
    except OSError:
        pass
    print(f"{'Created' if created else 'Updated'} {CONFIG} with the refresh token (not shown; never paste it in chat). "
          "Next: uv run scripts/accounts.py")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        sys.exit(__doc__)
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(args[0], scopes=SCOPES)
    if "--console" in sys.argv or not has_browser():
        if "--console" not in sys.argv:
            print("No browser found on this machine: using the console sign-in.")
        creds = console_sign_in(flow)
    else:
        creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
    if not creds.refresh_token:
        sys.exit("FAIL   Google returned no refresh token: remove argmax's access at "
                 "https://myaccount.google.com/permissions and run this again")
    save(creds)


if __name__ == "__main__":
    main()
