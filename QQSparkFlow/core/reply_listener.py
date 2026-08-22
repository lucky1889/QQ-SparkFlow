"""Listen to OneBot v11 forward WebSocket events and mark replies.

The scheduler container runs `python main.py --listen` alongside cron_runner.
Each enabled account gets one long-lived WS connection. When a private message
arrives from a configured target, we mark that target repliedToday=True.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime

import websockets

from core.send_state import mark_replied_today
from utils.config import get_userData
from utils.logger import setup_logger


logger = setup_logger(level=logging.DEBUG)

MAX_BACKOFF_SECONDS = 60


def backoff_seconds(attempt: int) -> int:
    """Exponential backoff 1,2,4,... capped at 60 seconds."""
    return min(MAX_BACKOFF_SECONDS, 2 ** max(0, int(attempt)))


def event_matches_account(account: dict, event: dict) -> bool:
    if not isinstance(event, dict):
        return False
    if event.get("post_type") != "message":
        return False
    if event.get("message_type") != "private":
        return False

    sender = event.get("sender") or {}
    sender_id = str(sender.get("user_id") or event.get("user_id") or "")
    target_ids = {str(target.get("user_id")) for target in (account.get("targets") or []) if target.get("user_id") is not None}
    if sender_id not in target_ids:
        return False

    account_uin = str(account.get("unique_id") or "")
    self_id = str(event.get("self_id") or "")
    if account_uin and self_id and self_id != account_uin:
        return False
    return True


def handle_event(account: dict, event: dict, now=None) -> bool:
    """Return True when the event matched a target and was persisted."""
    if not event_matches_account(account, event):
        return False
    sender = event.get("sender") or {}
    user_id = sender.get("user_id") or event.get("user_id")
    if user_id is None:
        return False
    if now is None:
        now = datetime.now().astimezone()
    return mark_replied_today(account, user_id, now)


async def _listen_account(account: dict) -> None:
    onebot = dict(account.get("onebot") or {})
    ws_url = onebot.get("ws_url") or f"ws://{onebot.get('service') or 'napcat-1'}:3001"
    access_token = str(onebot.get("access_token") or "")
    account_name = str(account.get("username") or account.get("unique_id") or "unknown")
    attempt = 0

    headers = {}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"

    while True:
        try:
            logger.info("reply listener connecting %s -> %s", account_name, ws_url)
            async with websockets.connect(
                ws_url,
                additional_headers=headers,
                ping_interval=20,
                ping_timeout=20,
                max_size=2 ** 23,
            ) as ws:
                attempt = 0
                async for raw in ws:
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if handle_event(account, event):
                        logger.info("marked reply from target on account=%s", account_name)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            delay = backoff_seconds(attempt)
            logger.warning("reply listener account=%s disconnected: %s; reconnect in %ss", account_name, exc, delay)
            attempt += 1
            await asyncio.sleep(delay)


async def start_reply_listener(account_refs=None) -> None:
    accounts = [account for account in get_userData(force_reload=True) if account.get("enabled", True)]
    if account_refs is not None:
        accounts = [account for account in accounts if account.get("account_ref") in set(account_refs)]

    if not accounts:
        logger.warning("reply listener: no enabled accounts to listen on")
        return

    listeners = [asyncio.create_task(_listen_account(account)) for account in accounts]
    logger.info("reply listener started for %s account(s)", len(listeners))
    try:
        await asyncio.gather(*listeners)
    except asyncio.CancelledError:
        for listener in listeners:
            listener.cancel()
        await asyncio.gather(*listeners, return_exceptions=True)
        raise

