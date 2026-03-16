"""Google Drive authentication for multiple accounts."""

import json
import os
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/drive",
]

TOKENS_DIR = Path("tokens")


def authenticate_account(account_config: dict) -> Credentials:
    """Authenticate a single Google Drive account and return credentials.

    Uses stored token if valid, refreshes if expired, or runs OAuth flow.
    """
    name = account_config["name"]
    creds_file = account_config["credentials_file"]
    token_path = TOKENS_DIR / f"{name}_token.json"

    TOKENS_DIR.mkdir(exist_ok=True)

    creds = None

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(creds_file):
                raise FileNotFoundError(
                    f"Credentials file not found for account '{name}': {creds_file}\n"
                    f"Download OAuth client credentials from Google Cloud Console."
                )
            flow = InstalledAppFlow.from_client_secrets_file(creds_file, SCOPES)
            creds = flow.run_local_server(port=0)

        token_path.write_text(creds.to_json())

    return creds


def build_drive_service(creds: Credentials):
    """Build a Google Drive API service from credentials."""
    return build("drive", "v3", credentials=creds)


def authenticate_all(config: dict) -> dict:
    """Authenticate all accounts from config. Returns {name: service} dict."""
    services = {}
    for account in config["accounts"]:
        name = account["name"]
        creds = authenticate_account(account)
        services[name] = {
            "service": build_drive_service(creds),
            "role": account["role"],
            "name": name,
        }
    return services
