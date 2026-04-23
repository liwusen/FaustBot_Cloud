import secrets
import urllib.parse
from typing import Optional

import requests


def generate_state() -> str:
    return secrets.token_urlsafe(16)


def build_authorize_url(client_id: str, callback_url: str, scopes: list[str], state: Optional[str] = None) -> str:
    state = state or generate_state()
    params = {
        "client_id": client_id,
        "redirect_uri": callback_url,
        "scope": " ".join(scopes),
        "state": state,
        "allow_signup": "false",
    }
    return "https://github.com/login/oauth/authorize?" + urllib.parse.urlencode(params), state


def exchange_code_for_token(code: str, client_id: str, client_secret: str, callback_url: str, github_api_base: str = "https://api.github.com") -> Optional[str]:
    url = "https://github.com/login/oauth/access_token"
    headers = {"Accept": "application/json"}
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": callback_url,
    }
    resp = requests.post(url, data=data, headers=headers, timeout=10)
    resp.raise_for_status()
    body = resp.json()
    return body.get("access_token")


def get_github_user(access_token: str, github_api_base: str = "https://api.github.com") -> dict:
    url = f"{github_api_base.rstrip('/')}/user"
    headers = {"Authorization": f"token {access_token}", "Accept": "application/json"}
    resp = requests.get(url, headers=headers, timeout=10)
    resp.raise_for_status()
    return resp.json()
