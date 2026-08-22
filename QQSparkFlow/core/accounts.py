"""QQ account management backed by usersData.json.

Each account points at one NapCat container (onebot.http_url / onebot.ws_url)
and carries the friend list (targets) that should receive the daily message.
"""

from __future__ import annotations

import uuid

from core.onebot import OneBotClient
from utils.config import get_userData, normalize_unique_id, save_userData


def new_account_ref() -> str:
    return f"acc-{uuid.uuid4().hex}"


def default_onebot_config(service: str = "napcat-1", access_token: str = "") -> dict:
    return {
        "service": service,
        "http_url": f"http://{service}:3000",
        "ws_url": f"ws://{service}:3001",
        "access_token": access_token,
    }


def list_accounts(enabled_only: bool = False) -> list[dict]:
    accounts = get_userData(force_reload=True)
    if enabled_only:
        return [account for account in accounts if account.get("enabled", True)]
    return accounts


def find_account(accounts, unique_id: str):
    normalized = normalize_unique_id(unique_id)
    for account in accounts:
        if normalize_unique_id(account.get("unique_id")) == normalized or account.get("account_ref") == unique_id:
            return account
    return None


def add_account(username: str, service: str = "napcat-1", access_token: str = "",
                targets=None, enabled: bool = True, onebot: dict | None = None) -> dict:
    accounts = get_userData(force_reload=True)
    account = {
        "account_ref": new_account_ref(),
        "unique_id": "",
        "username": str(username or "").strip() or f"账号{len(accounts) + 1}",
        "enabled": bool(enabled),
        "onebot": dict(onebot) if onebot else default_onebot_config(service, access_token),
        "targets": [normalize_target(target) for target in (targets or [])],
        "message_history": {},
        "online": False,
        "last_error": "",
    }
    accounts.append(account)
    save_userData(accounts)
    return account


def normalize_target(target) -> dict:
    if isinstance(target, dict):
        return {
            "user_id": str(target.get("user_id") or "").strip(),
            "remark": str(target.get("remark") or "").strip(),
        }
    return {"user_id": str(target).strip(), "remark": ""}


def update_account(unique_id: str, **changes) -> dict | None:
    accounts = get_userData(force_reload=True)
    for index, account in enumerate(accounts):
        if normalize_unique_id(account.get("unique_id")) == normalize_unique_id(unique_id) or account.get("account_ref") == unique_id:
            account = dict(account)
            for key, value in changes.items():
                if key == "targets":
                    account[key] = [normalize_target(target) for target in value]
                else:
                    account[key] = value
            accounts[index] = account
            save_userData(accounts)
            return account
    return None


def delete_account(unique_id: str) -> bool:
    accounts = get_userData(force_reload=True)
    normalized = normalize_unique_id(unique_id)
    remaining = [
        account
        for account in accounts
        if normalize_unique_id(account.get("unique_id")) != normalized and account.get("account_ref") != unique_id
    ]
    removed = len(accounts) != len(remaining)
    if removed:
        save_userData(remaining)
    return removed


def toggle_account_enabled(unique_id: str) -> dict | None:
    accounts = get_userData(force_reload=True)
    for index, account in enumerate(accounts):
        if normalize_unique_id(account.get("unique_id")) == normalize_unique_id(unique_id) or account.get("account_ref") == unique_id:
            account = dict(account)
            account["enabled"] = not bool(account.get("enabled", True))
            accounts[index] = account
            save_userData(accounts)
            return account
    return None


def account_online_status(account: dict) -> dict:
    return {
        "online": bool(account.get("online")),
        "last_error": str(account.get("last_error") or ""),
        "unique_id": str(account.get("unique_id") or ""),
    }


def onebot_client_for(account: dict, timeout: float = 15.0) -> OneBotClient:
    onebot = dict(account.get("onebot") or {})
    return OneBotClient(
        onebot.get("http_url") or f"http://{onebot.get('service') or 'napcat-1'}:3000",
        access_token=str(onebot.get("access_token") or ""),
        timeout=timeout,
    )


def persist_account(account: dict) -> dict:
    accounts = get_userData(force_reload=True)
    key = account.get("account_ref")
    for index, existing in enumerate(accounts):
        if existing.get("account_ref") == key or (
            account.get("unique_id") and normalize_unique_id(existing.get("unique_id")) == normalize_unique_id(account.get("unique_id"))
        ):
            accounts[index] = account
            save_userData(accounts)
            return account
    accounts.append(account)
    save_userData(accounts)
    return account


async def refresh_account_identity(account: dict) -> dict:
    """Call get_login_info and backfill uin/nickname/online state."""
    client = onebot_client_for(account)
    try:
        info = await client.get_login_info()
    except Exception as exc:  # OneBotConnectionError / OneBotAPIError
        account["online"] = False
        account["last_error"] = str(exc)
        persist_account(account)
        return account
    finally:
        await client.close()

    account["unique_id"] = str(info.get("user_id") or account.get("unique_id") or "")
    if info.get("nickname"):
        account["username"] = str(info["nickname"])
    account["online"] = True
    account["last_error"] = ""
    persist_account(account)
    return account


async def validate_targets(account: dict) -> dict:
    """Fetch the friend list and flag configured targets that are no longer friends."""
    client = onebot_client_for(account)
    try:
        friends = await client.get_friend_list()
    except Exception:
        friends = None
    finally:
        await client.close()

    friend_ids = {str(item.get("user_id")) for item in (friends or [])}
    targets = list(account.get("targets") or [])
    for target in targets:
        target["isFriend"] = str(target.get("user_id")) in friend_ids
    account["targets"] = targets
    persist_account(account)
    return {
        "friendIds": sorted(friend_ids),
        "targets": targets,
        "unavailable": friends is None,
    }


def interactive_add_account(console=None) -> dict:
    """Prompt for a new account from the command line."""
    from rich.prompt import Prompt

    def ask(label, default=""):
        if console is None:
            return input(f"{label}: ").strip() or default
        return (console.input(f"[bold]{label}[/bold]: ").strip() or default)

    username = ask("账号显示名（例如：主号）", f"账号{len(list_accounts()) + 1}")
    service = ask("NapCat 服务名", "napcat-1")
    access_token = ask("OneBot Access Token（留空使用 .env 中值）", "")
    raw_targets = ask("好友 QQ 号（逗号分隔，可留空稍后在网页填写）", "")
    targets = [item.strip() for item in raw_targets.split(",") if item.strip()]
    return add_account(username, service=service, access_token=access_token, targets=targets)
