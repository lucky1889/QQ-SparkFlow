"""Daily QQ spark maintenance task.

The old Douyin browser-automation task (113KB) is replaced by a small OneBot
send loop: check login -> build messages -> send one private message per target.
"""

from __future__ import annotations

import asyncio
import errno
import logging
import os
import random
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from core import accounts as accounts_module
from core.msg_builder import build_messages_for_targets
from core.onebot import OneBotClient, OneBotError
from core.send_state import target_is_strong_confirmed_today
from utils.config import get_config, get_userData, save_userData
from utils.logger import setup_logger


logger = setup_logger(level=logging.DEBUG)


def _is_manual_run():
    return os.getenv("SPARKFLOW_MANUAL_RUN") == "1"


def _manual_run_failed_only():
    return _is_manual_run() and os.getenv("SPARKFLOW_MANUAL_FAILED_ONLY") == "1"


def _manual_run_unsent_only():
    return _is_manual_run() and os.getenv("SPARKFLOW_MANUAL_UNSENT_ONLY") == "1"


def _requested_account_refs():
    raw = os.getenv("SPARKFLOW_ACCOUNT_REFS")
    if raw is None:
        return None
    return {item.strip() for item in raw.split(",") if item.strip()}


def _schedule_timezone():
    timezone_name = (
        str(os.getenv("SPARKFLOW_TIMEZONE") or "").strip()
        or str(os.getenv("TZ") or "").strip()
        or "Asia/Shanghai"
    )
    try:
        return ZoneInfo(timezone_name)
    except Exception:
        if timezone_name == "Asia/Shanghai":
            logger.warning("Falling back to fixed UTC+8 because %r is unavailable", timezone_name)
            return timezone(timedelta(hours=8), name="Asia/Shanghai")
        logger.warning("Falling back to system timezone because %r is unavailable", timezone_name)
        return datetime.now().astimezone().tzinfo


def _pid_is_alive(pid):
    if pid is None:
        return False
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as exc:
        if exc.errno == errno.EINVAL:
            return False
        raise
    return True


def _coerce_non_negative_int(value, default):
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return max(0, int(default))


def _normalize_send_strategy(active_config):
    raw = active_config.get("sendStrategy", {}) or {}
    start_min = _coerce_non_negative_int(raw.get("accountStartDelaySecondsMin", 0), 0)
    start_max = _coerce_non_negative_int(raw.get("accountStartDelaySecondsMax", start_min), start_min)
    if start_max < start_min:
        start_max = start_min

    message_min = _coerce_non_negative_int(raw.get("messageIntervalSecondsMin", 0), 0)
    message_max = _coerce_non_negative_int(raw.get("messageIntervalSecondsMax", message_min), message_min)
    if message_max < message_min:
        message_max = message_min

    return {
        "accountStartDelaySecondsMin": start_min,
        "accountStartDelaySecondsMax": start_max,
        "messageIntervalSecondsMin": message_min,
        "messageIntervalSecondsMax": message_max,
    }


def _random_delay_seconds(send_strategy, min_key, max_key):
    return random.randint(send_strategy[min_key], send_strategy[max_key])


async def _sleep_with_log(seconds, reason, account_name):
    if seconds <= 0:
        return
    logger.info("%s for %s by %ss", reason, account_name, seconds)
    await asyncio.sleep(seconds)


def _target_keys(account):
    return [str(target.get("user_id")).strip() for target in (account.get("targets") or []) if str(target.get("user_id") or "").strip()]


def _entry_failed_today(account, target_key, now):
    history = dict(account.get("message_history") or {})
    entry = dict(history.get(target_key) or {})
    from core.send_state import parse_sent_at

    sent_at = parse_sent_at(entry.get("sentAt"), now.tzinfo)
    return bool(entry.get("status") == "failed" and sent_at and sent_at.date() == now.date())


def _select_target_keys(account, now):
    keys = _target_keys(account)
    if _manual_run_failed_only():
        return [key for key in keys if _entry_failed_today(account, key, now)]
    if _manual_run_unsent_only():
        return [key for key in keys if not target_is_strong_confirmed_today(account, key, now)]
    if _is_manual_run():
        # Web UI "run now" forces every configured target.
        return keys
    return [key for key in keys if not target_is_strong_confirmed_today(account, key, now)]


def _record_result(account, target_key, message, now, *, message_id=None, status="confirmed", reason=""):
    history = dict(account.get("message_history") or {})
    entry = dict(history.get(target_key) or {})
    entry.update(
        {
            "sentAt": now.isoformat(),
            "message": message,
            "status": status,
            "message_id": message_id,
        }
    )
    if reason:
        entry["reason"] = reason
    history[target_key] = entry
    account["message_history"] = history
    return account


def _persist_account(account):
    accounts = get_userData(force_reload=True)
    key = account.get("account_ref")
    for index, existing in enumerate(accounts):
        if existing.get("account_ref") == key:
            accounts[index] = account
            save_userData(accounts)
            return
    accounts.append(account)
    save_userData(accounts)


async def _run_account(account, active_config, send_strategy, manual):
    account_name = str(account.get("username") or account.get("unique_id") or "unknown")
    targets = _target_keys(account)
    if not targets:
        logger.info("account=%s has no configured targets, skipping", account_name)
        return

    client = accounts_module.onebot_client_for(account)
    try:
        try:
            info = await client.get_login_info()
        except OneBotError as exc:
            account["online"] = False
            account["last_error"] = str(exc)
            _persist_account(account)
            logger.error("account=%s QQ offline or endpoint unreachable: %s", account_name, exc)
            return

        if info.get("user_id"):
            account["unique_id"] = str(info["user_id"])
        if info.get("nickname"):
            account["username"] = str(info["nickname"])
        account["online"] = True
        account["last_error"] = ""
        _persist_account(account)

        messages = build_messages_for_targets(targets, account.get("message_history"), active_config)
        now = datetime.now(_schedule_timezone())
        selected_keys = _select_target_keys(account, now)
        if not selected_keys:
            logger.info("account=%s all targets already confirmed today", account_name)
            return

        logger.info("account=%s sending to %s target(s)", account_name, len(selected_keys))
        for target_key in selected_keys:
            message = messages.get(target_key) or active_config.get("messageTemplate", "🤩今日火花+1")
            try:
                message_id = await client.send_private_msg(target_key, message)
            except OneBotError as exc:
                account = _record_result(account, target_key, message, now, status="failed", reason=str(exc))
                _persist_account(account)
                logger.error("account=%s target=%s send failed: %s", account_name, target_key, exc)
            else:
                account = _record_result(account, target_key, message, now, message_id=message_id, status="confirmed")
                _persist_account(account)
                logger.info("account=%s target=%s confirmed message_id=%s", account_name, target_key, message_id)

            if not manual:
                await _sleep_with_log(
                    _random_delay_seconds(send_strategy, "messageIntervalSecondsMin", "messageIntervalSecondsMax"),
                    "pausing between messages for",
                    account_name,
                )
    finally:
        await client.close()


async def runTasks():
    active_config = get_config(force_reload=True)
    all_user_data = get_userData(force_reload=True)
    requested_refs = _requested_account_refs()
    if requested_refs is not None:
        all_user_data = [user for user in all_user_data if user.get("account_ref") in requested_refs]

    active_user_data = [user for user in all_user_data if user.get("enabled", True)]
    disabled_user_data = [user for user in all_user_data if not user.get("enabled", True)]

    logger.info("Starting QQ SparkFlow tasks")
    for user in disabled_user_data:
        logger.info("skipping disabled account=%s", user.get("username") or "unknown")
    if not active_user_data:
        logger.warning("No enabled accounts are available for the task run")
        return

    send_strategy = _normalize_send_strategy(active_config)
    manual = _is_manual_run()

    async def _run_all():
        if not manual:
            jitter_minutes = _coerce_non_negative_int(active_config.get("dailySendJitterMinutes", 20), 20)
            if jitter_minutes:
                jitter_seconds = random.randint(0, jitter_minutes * 60)
                await _sleep_with_log(jitter_seconds, "delaying scheduled run (jitter) for", "scheduler")

        for account in active_user_data:
            if not manual:
                await _sleep_with_log(
                    _random_delay_seconds(send_strategy, "accountStartDelaySecondsMin", "accountStartDelaySecondsMax"),
                    "delaying account start for",
                    str(account.get("username") or "unknown"),
                )
            await _run_account(account, active_config, send_strategy, manual)

    try:
        with task_run_lock():
            await _run_all()
    except TaskRunAlreadyInProgress:
        logger.warning("Skipping task run because another task run is already in progress")


class TaskRunAlreadyInProgress(RuntimeError):
    """Raised when a live task process already owns the global run lock."""


@contextmanager
def task_run_lock():
    lock_path = Path("logs/task.run.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    while True:
        try:
            handle = lock_path.open("x", encoding="utf-8")
            break
        except FileExistsError as exc:
            raw_pid = lock_path.read_text(encoding="utf-8", errors="ignore").strip()
            try:
                stale_pid = int(raw_pid)
            except (TypeError, ValueError):
                stale_pid = None

            if stale_pid is None or not _pid_is_alive(stale_pid):
                logger.warning("Removing stale task lock contents=%r", raw_pid)
                try:
                    lock_path.unlink()
                except FileNotFoundError:
                    pass
                continue

            raise TaskRunAlreadyInProgress("another task run is already in progress") from exc

    try:
        handle.write(f"{os.getpid()}\n")
        handle.flush()
        yield
    finally:
        handle.close()
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass

