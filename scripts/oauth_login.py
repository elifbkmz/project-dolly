#!/usr/bin/env python3
"""
One-time OAuth2 login flow.

Opens a browser for Google sign-in, then saves a refresh token
so future comment creation uses your real Google account.

Run: python3 scripts/oauth_login.py
"""

import json
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
]

CLIENT_SECRET = Path(__file__).parent.parent / "credentials" / "oauth_client.json"
TOKEN_PATH = Path(__file__).parent.parent / "credentials" / "oauth_token.json"


def main():
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET), SCOPES)
    creds = flow.run_local_server(port=0)

    token_data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes),
    }
    TOKEN_PATH.write_text(json.dumps(token_data, indent=2))
    print(f"Saved token to {TOKEN_PATH}")
    print("You can now create comments as your Google account.")


if __name__ == "__main__":
    main()
