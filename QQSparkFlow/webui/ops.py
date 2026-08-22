"""Runtime operations and snapshot builders for the Web UI."""

from __future__ import annotations

import errno
import json
import logging
import os
import re
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from core.send_state import history_entry_is_strong_confirmed_today, replied_today
from utils.config import (
    get_app_settings,
    get_config,
    get_userData,
    repo_root,
    save_config,
)
from utils.logger import setup_logger


logger = setup_logger(level=logging.DEBUG)


def running_in_container():
    if Path("/.dockerenv").exists():
        return True
    try:
        return "docker" in Path("/proc/1/cgroup").read_text(encoding="utf-8")
    except OSError:
        return False


def compose_root():
    settings = get_app_settings()
    root = settings.get("compose_root") or str(repo_root().parent)
    return Path(root)


def compose_file_path():
    return compose_root() / "docker-compose.yml"


def cron_file_path():
    if running_in_container() and Path("/host-spool-cron/root").exists():
        return Path("/host-spool-cron/root")
    return compose_root() / "state" / "cron" / "root"


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


def _parse_lock_pid(raw):
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


def task_run_lock_status():
    lock_path = repo_root() / "logs" / "task.run.lock"
    if not lock_path.exists():
        return {"running": False, "stale": False, "ageSeconds": 0, "staleReason": ""}

    try:
        raw = lock_path.read_text(encoding="utf-8", errors="ignore").strip()
    except OSError:
        return {"running": False, "stale": True, "ageSeconds": 0, "staleReason": "unreadable"}

    age_seconds = 0
    try:
        age_seconds = int(time.time() - lock_path.stat().st_mtime)
    except OSError:
        pass

    pid = _parse_lock_pid(raw)
    if pid is None:
        return {"running": False, "stale": True, "ageSeconds": age_seconds, "staleReason": "unreadable_pid"}
    if _pid_is_alive(pid):
        return {"running": True, "stale": False, "ageSeconds": age_seconds, "staleReason": ""}
    return {"running": False, "stale": True, "ageSeconds": age_seconds, "staleReason": "owner_pid_missing"}


def build_task_run_spec():
    return {
        "command": ["python", "main.py", "--doTask"],
        "cwd": str(repo_root()),
        "log_path": str(repo_root() / "logs" / "app.log"),
    }


def _env_shell_prefix(extra_env=None):
    parts = []
    for key, value in (extra_env or {}).items():
        parts.append(f"{key}={value}")
    return " ".join(parts)


def _with_env_prefix(command, extra_env=None):
    prefix = _env_shell_prefix(extra_env)
    if prefix:
        return prefix + " " + command
    return command


def _compose_env_args(extra_env=None):
    return [(key, str(value)) for key, value in (extra_env or {}).items()]


def build_scheduled_task_command(extra_env=None, trigger_label="scheduled send"):
    del trigger_label
    return _with_env_prefix("cd /app && python main.py --doTask >> /app/logs/app.log 2>&1", extra_env)


def build_unsent_fallback_task_command(extra_env=None):
    env = {"SPARKFLOW_MANUAL_RUN": "1", "SPARKFLOW_MANUAL_UNSENT_ONLY": "1", "PYTHONUNBUFFERED": "1"}
    if extra_env:
        env.update(extra_env)
    return build_scheduled_task_command(env, trigger_label="unsent fallback")


def run_command(args, cwd=None, timeout=120, check=False):
    try:
        return subprocess.run(
            args,
            cwd=cwd,
            timeout=timeout,
            check=check,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        logger.debug("optional runtime tool not found: %s", exc)
        return SimpleNamespace(returncode=1, stdout="", stderr=str(exc))
    except subprocess.TimeoutExpired as exc:
        logger.debug("command timed out: %s", exc)
        return SimpleNamespace(returncode=124, stdout="", stderr=str(exc))


def run_background_command(args, log_path, cwd=None, env=None):
    log_file = Path(log_path)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    handle = log_file.open("ab")
    process = subprocess.Popen(
        args,
        cwd=cwd,
        env=env,
        stdout=handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    return process


def get_container_status():
    if not running_in_container():
        return {"state": "local", "containers": []}
    result = run_command(["docker", "ps", "--format", "{{.Names}}"])
    names = [line for line in result.stdout.splitlines() if line.strip()]
    return {"state": "container", "containers": names}


def get_task_container_rows():
    return get_container_status()


def _task_env(*, unsent_only=False, failed_only=False, force_all=False, account_refs=None):
    env = dict(os.environ)
    env["SPARKFLOW_MANUAL_RUN"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    if unsent_only:
        env["SPARKFLOW_MANUAL_UNSENT_ONLY"] = "1"
    if failed_only:
        env["SPARKFLOW_MANUAL_FAILED_ONLY"] = "1"
    if account_refs:
        env["SPARKFLOW_ACCOUNT_REFS"] = ",".join(account_refs)
    if force_all:
        env.pop("SPARKFLOW_MANUAL_UNSENT_ONLY", None)
        env.pop("SPARKFLOW_MANUAL_FAILED_ONLY", None)
    return env


def run_task_now(*, unsent_only=False, failed_only=False, force_all=False, account_refs=None):
    spec = build_task_run_spec()
    env = _task_env(unsent_only=unsent_only, failed_only=failed_only, force_all=force_all, account_refs=account_refs)
    process = run_background_command(spec["command"], spec["log_path"], cwd=spec["cwd"], env=env)
    return {"pid": process.pid, "started": True}


def run_failed_retry_now(*, account_refs=None):
    return run_task_now(failed_only=True, account_refs=account_refs)


def run_unsent_retry_now(*, account_refs=None):
    return run_task_now(unsent_only=True, account_refs=account_refs)


def read_log_tail(lines=200):
    log_path = repo_root() / "logs" / "app.log"
    if not log_path.exists():
        return ""
    text = log_path.read_text(encoding="utf-8", errors="replace")
    return "\n".join(text.splitlines()[-lines:])


def read_crontab():
    path = cron_file_path()
    if not path.exists():
        logger.debug("crontab file not found at %s", path)
        return []
    lines = []
    for raw in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line.split(maxsplit=1)[0]:
            continue
        lines.append(line)
    return lines


def parse_schedule_string(time_string):
    match = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", str(time_string or ""))
    if not match:
        raise ValueError("time must be in HH:MM format")
    hour = int(match.group(1))
    minute = int(match.group(2))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("invalid time")
    return hour, minute


def validate_time_string(time_string):
    try:
        parse_schedule_string(time_string)
        return True
    except ValueError:
        return False


def _cron_line_for(command):
    return f"{command} >> /app/logs/app.log 2>&1"


def _fallback_time(hour, minute):
    total = hour * 60 + minute + 40
    return (total // 60) % 24, total % 60


def build_cron_lines(time_string):
    hour, minute = parse_schedule_string(time_string)
    fallback_hour, fallback_minute = _fallback_time(hour, minute)
    return [
        f"{minute} {hour} * * * cd /app && python main.py --doTask >> /app/logs/app.log 2>&1",
        f"{fallback_minute} {fallback_hour} * * * cd /app && env SPARKFLOW_MANUAL_RUN=1 SPARKFLOW_MANUAL_UNSENT_ONLY=1 PYTHONUNBUFFERED=1 python main.py --doTask >> /app/logs/app.log 2>&1",
    ]


def replace_qq_cron_schedule(crontab_text, time_string):
    new_lines = build_cron_lines(time_string)
    lines = [line.rstrip() for line in str(crontab_text or "").splitlines()]
    kept = [line for line in lines if "--doTask" not in line and not line.strip().startswith("# QQSparkFlow")]
    return "\n".join(["# QQSparkFlow daily send", *new_lines, *kept]).strip() + "\n"


def persist_schedule_config(time_string):
    parse_schedule_string(time_string)
    config = get_config(force_reload=True)
    config["dailySendTime"] = time_string
    save_config(config)
    update_daily_schedule(time_string)
    return current_daily_schedule()


def update_daily_schedule(time_string):
    path = cron_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    path.write_text(replace_qq_cron_schedule(existing, time_string), encoding="utf-8")
    return read_crontab()


def sync_daily_schedule_from_config():
    config = get_config(force_reload=True)
    time_string = str(config.get("dailySendTime") or "10:00")
    if validate_time_string(time_string):
        update_daily_schedule(time_string)
    return current_daily_schedule()


def current_daily_schedule():
    config = get_config(force_reload=True)
    return str(config.get("dailySendTime") or "10:00")


def _schedule_timezone():
    name = str(os.getenv("TZ") or os.getenv("SPARKFLOW_TIMEZONE") or "Asia/Shanghai")
    try:
        return ZoneInfo(name)
    except Exception:
        return timezone(timedelta(hours=8), name="Asia/Shanghai")


def _now():
    return datetime.now(_schedule_timezone())


def get_schedule_snapshot(now=None):
    now = now or _now()
    time_string = current_daily_schedule()
    try:
        hour, minute = parse_schedule_string(time_string)
    except ValueError:
        hour, minute = 10, 0
    next_trigger = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if next_trigger <= now:
        next_trigger += timedelta(days=1)
    return {
        "label": f"每天 {time_string}",
        "nextTriggerAt": next_trigger.isoformat(),
    }


def _account_identity(account):
    return str(account.get("username") or account.get("unique_id") or "unknown")


def _target_snapshot(account, target, now, include_messages=True):
    target_key = str(target.get("user_id"))
    history = dict(account.get("message_history") or {})
    entry = dict(history.get(target_key) or {})
    confirmed = history_entry_is_strong_confirmed_today(entry, now)
    replied = replied_today(account, target_key, now)
    failed = bool(entry.get("status") == "failed")

    item = {
        "user_id": target_key,
        "remark": str(target.get("remark") or ""),
        "status": "confirmed" if confirmed else ("failed" if failed else "pending"),
        "replied_today": replied,
        "isFriend": bool(target.get("isFriend", True)),
    }
    if include_messages:
        item["message"] = str(entry.get("message") or "") if confirmed or failed else ""
        item["message_id"] = entry.get("message_id")
        item["reason"] = str(entry.get("reason") or "") if failed else ""
    return item


def _account_summary(account, now, include_messages=True):
    targets = account.get("targets") or []
    items = [_target_snapshot(account, target, now, include_messages=include_messages) for target in targets]
    confirmed_count = sum(1 for item in items if item["status"] == "confirmed")
    replied_count = sum(1 for item in items if item["replied_today"])
    failed_count = sum(1 for item in items if item["status"] == "failed")
    pending_count = len(items) - confirmed_count - failed_count
    return {
        "unique_id": str(account.get("unique_id") or account.get("account_ref") or ""),
        "account_ref": str(account.get("account_ref") or ""),
        "username": _account_identity(account),
        "online": bool(account.get("online")),
        "last_error": str(account.get("last_error") or ""),
        "enabled": bool(account.get("enabled", True)),
        "onebot_service": str((account.get("onebot") or {}).get("service") or ""),
        "total_targets": len(items),
        "confirmed_count": confirmed_count,
        "replied_count": replied_count,
        "failed_count": failed_count,
        "pending_count": pending_count,
        "targets": items,
    }


def _scope_accounts(account_refs=None):
    accounts = get_userData(force_reload=True)
    if account_refs is not None:
        accounts = [account for account in accounts if account.get("account_ref") in set(account_refs)]
    return accounts


def get_send_console_snapshot(account_refs=None):
    now = _now()
    accounts = [account for account in _scope_accounts(account_refs) if account.get("enabled", True)]
    rows = [_account_summary(account, now, include_messages=True) for account in accounts]
    total_targets = sum(row["total_targets"] for row in rows)
    confirmed = sum(row["confirmed_count"] for row in rows)
    replied = sum(row["replied_count"] for row in rows)
    failed = sum(row["failed_count"] for row in rows)
    pending = sum(row["pending_count"] for row in rows)
    return {
        "now": now.isoformat(),
        "nowDisplay": now.strftime("%Y-%m-%d %H:%M"),
        "summary": {
            "enabled_accounts": len(rows),
            "total_targets": total_targets,
            "today_confirmed_targets": confirmed,
            "today_replied_targets": replied,
            "today_failed_targets": failed,
            "today_pending_targets": pending,
            "today_attention_targets": failed + pending,
        },
        "accounts": rows,
    }


def get_overview_snapshot(account_refs=None):
    send_console = get_send_console_snapshot(account_refs=account_refs)
    accounts = []
    for row in send_console["accounts"]:
        accounts.append(
            {
                "unique_id": row["unique_id"],
                "account_ref": row["account_ref"],
                "username": row["username"],
                "online": row["online"],
                "enabled": row["enabled"],
                "state": "attention" if (row["failed_count"] or row["pending_count"] or not row["online"]) else "ok",
                "total_targets": row["total_targets"],
                "confirmed_count": row["confirmed_count"],
                "replied_count": row["replied_count"],
                "failed_count": row["failed_count"],
                "pending_count": row["pending_count"],
            }
        )
    summary = send_console.get("summary") or {}
    public_summary = {
        key: summary.get(key)
        for key in (
            "enabled_accounts",
            "total_targets",
            "today_confirmed_targets",
            "today_replied_targets",
            "today_failed_targets",
            "today_pending_targets",
            "today_attention_targets",
        )
    }
    schedule = get_schedule_snapshot()
    lock = task_run_lock_status()
    return {
        "summary": public_summary,
        "accounts": accounts,
        "schedule": schedule,
        "taskLock": lock,
    }


def get_ops_snapshot(account_refs=None):
    return {
        "send_console": get_send_console_snapshot(account_refs=account_refs),
        "schedule": get_schedule_snapshot(),
        "taskLock": task_run_lock_status(),
        "containers": get_container_status(),
    }



