"""Per-account, per-target daily send/reply state helpers.

A send is considered "strong confirmed today" only when OneBot returned
retcode == 0 with a message_id and the send happened today. Reply tracking is
kept on the same per-target entry so the Web UI can show "replied today".
"""

from __future__ import annotations

from datetime import datetime


def parse_sent_at(raw_value, local_tz):
    if not raw_value:
        return None
    raw = str(raw_value).strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=local_tz)
    return parsed.astimezone(local_tz)


def _entry_is_today(entry, now, key):
    entry = dict(entry or {})
    parsed = parse_sent_at(entry.get(key), now.tzinfo)
    return bool(parsed and parsed.date() == now.date())


def history_entry_is_strong_confirmed_today(entry, now):
    entry = dict(entry or {})
    sent_at = parse_sent_at(entry.get("sentAt"), now.tzinfo)
    if not sent_at or sent_at.date() != now.date():
        return False
    if entry.get("status") != "confirmed":
        return False
    return entry.get("message_id") is not None


def history_entry_is_today(entry, now):
    sent_at = parse_sent_at(dict(entry or {}).get("sentAt"), now.tzinfo)
    return bool(sent_at and sent_at.date() == now.date())


def target_is_strong_confirmed_today(account, target_name, now):
    history = dict(account.get("message_history") or {})
    return history_entry_is_strong_confirmed_today(history.get(str(target_name)), now)


def replied_today(account, user_id, now):
    history = dict(account.get("message_history") or {})
    entry = history.get(str(user_id)) or {}
    if not bool(entry.get("repliedToday")):
        return False
    return _entry_is_today(entry, now, "repliedAt") or _entry_is_today(entry, now, "sentAt")


def mark_replied_in_account(account, user_id, now) -> dict:
    account = dict(account or {})
    history = dict(account.get("message_history") or {})
    entry = dict(history.get(str(user_id)) or {})
    entry["repliedToday"] = True
    entry["repliedAt"] = now.isoformat()
    history[str(user_id)] = entry
    account["message_history"] = history
    return account


def _account_key(account) -> str:
    return str(account.get("unique_id") or account.get("account_ref") or "")


def mark_replied_today(account, user_id, now=None) -> bool:
    """Persist repliedToday=True for the matching account in usersData.json."""
    from utils.config import get_userData, save_userData

    if now is None:
        now = datetime.now().astimezone()

    target_key = str(user_id)
    accounts = get_userData(force_reload=True)
    key = _account_key(account)
    for index, acc in enumerate(accounts):
        if _account_key(acc) == key:
            accounts[index] = mark_replied_in_account(acc, target_key, now)
            save_userData(accounts)
            return True
    return False
