"""OneBot v11 HTTP client used to drive NapCatQQ.

NapCat exposes the OneBot v11 HTTP API on a per-account port (default 3000).
This module keeps every upstream call in one place so protocol changes only
need to be adapted here.
"""

from __future__ import annotations

import httpx


class OneBotError(Exception):
    """Base error for OneBot client failures."""


class OneBotConnectionError(OneBotError):
    """Raised when the OneBot endpoint cannot be reached or returns HTTP errors."""


class OneBotAPIError(OneBotError):
    """Raised when OneBot returns retcode != 0."""

    def __init__(self, retcode, wording="", status=""):
        self.retcode = retcode
        self.wording = wording or ""
        self.status = status or ""
        detail = self.wording or self.status or "unknown error"
        super().__init__(f"OneBot API error retcode={retcode}: {detail}")


def _coerce_user_id(user_id) -> int:
    try:
        return int(user_id)
    except (TypeError, ValueError):
        raise OneBotAPIError(-1, wording=f"invalid user_id: {user_id!r}") from None


class OneBotClient:
    def __init__(self, http_url: str, access_token: str = "", timeout: float = 15.0):
        self.http_url = str(http_url or "").rstrip("/")
        self.access_token = str(access_token or "")
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        return headers

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self.http_url, timeout=self.timeout)
        return self._client

    async def close(self):
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    async def _call(self, action: str, params: dict | None = None) -> dict:
        client = self._get_client()
        try:
            response = await client.post(
                f"/{action}",
                json=params or {},
                headers=self._headers(),
            )
        except httpx.TimeoutException as exc:
            raise OneBotConnectionError(f"timeout calling {action}") from exc
        except httpx.HTTPError as exc:
            raise OneBotConnectionError(f"connection error calling {action}: {exc}") from exc

        try:
            payload = response.json()
        except ValueError:
            raise OneBotConnectionError(f"non-JSON response calling {action}: HTTP {response.status_code}") from None

        if response.status_code != 200:
            raise OneBotConnectionError(f"HTTP {response.status_code} calling {action}")

        payload = payload if isinstance(payload, dict) else {}
        retcode = payload.get("retcode", 0)
        if retcode not in (0, None):
            raise OneBotAPIError(
                retcode,
                wording=str(payload.get("wording") or ""),
                status=str(payload.get("status") or ""),
            )
        return payload

    async def get_login_info(self) -> dict:
        payload = await self._call("get_login_info")
        data = payload.get("data") or {}
        if not isinstance(data, dict):
            raise OneBotConnectionError("get_login_info returned malformed data")
        user_id = data.get("user_id")
        if user_id is None:
            raise OneBotConnectionError("get_login_info response missing user_id (QQ may be offline)")
        return {
            "user_id": str(user_id),
            "nickname": str(data.get("nickname") or ""),
        }

    async def get_friend_list(self) -> list[dict]:
        payload = await self._call("get_friend_list")
        data = payload.get("data") or []
        if not isinstance(data, list):
            return []
        friends = []
        for item in data:
            if not isinstance(item, dict):
                continue
            friends.append(
                {
                    "user_id": str(item.get("user_id") or ""),
                    "nickname": str(item.get("nickname") or ""),
                    "remark": str(item.get("remark") or ""),
                }
            )
        return friends

    async def send_private_msg(self, user_id, message: str) -> int:
        target_id = _coerce_user_id(user_id)
        payload = await self._call(
            "send_private_msg",
            {"user_id": target_id, "message": str(message)},
        )
        data = payload.get("data") or {}
        message_id = data.get("message_id")
        if message_id is None:
            raise OneBotAPIError(0, wording="send_private_msg returned no message_id", status=payload.get("status") or "")
        return int(message_id)
