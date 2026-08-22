import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from core.onebot import OneBotAPIError, OneBotClient, OneBotConnectionError


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload


class FakeAsyncClient:
    def __init__(self, *args, **kwargs):
        self.post = AsyncMock(return_value=FakeResponse({"retcode": 0, "status": "ok", "data": {"user_id": 10001, "nickname": "me"}}))
        self.aclose = AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None


def run(coro):
    return asyncio.run(coro)


class OneBotClientTests(unittest.TestCase):
    def test_send_private_msg_returns_message_id(self):
        client = OneBotClient("http://napcat-1:3000")
        with patch("core.onebot.httpx.AsyncClient", FakeAsyncClient):
            client._client = FakeAsyncClient()
            client._client.post.return_value = FakeResponse({"retcode": 0, "status": "ok", "data": {"message_id": 12345}})
            message_id = run(client.send_private_msg(10001, "hello"))
        self.assertEqual(12345, message_id)

    def test_nonzero_retcode_raises_api_error(self):
        client = OneBotClient("http://napcat-1:3000")
        client._client = FakeAsyncClient()
        client._client.post.return_value = FakeResponse({"retcode": 1403, "status": "failed", "wording": "message too frequent"})
        with self.assertRaises(OneBotAPIError) as ctx:
            run(client.send_private_msg(10001, "hello"))
        self.assertEqual(1403, ctx.exception.retcode)

    def test_token_is_injected_as_bearer_header(self):
        client = OneBotClient("http://napcat-1:3000", access_token="secret-token")
        client._client = FakeAsyncClient()
        run(client.get_login_info())
        headers = client._client.post.call_args.kwargs["headers"]
        self.assertEqual("Bearer secret-token", headers["Authorization"])

    def test_empty_token_omits_authorization_header(self):
        client = OneBotClient("http://napcat-1:3000", access_token="")
        client._client = FakeAsyncClient()
        run(client.get_login_info())
        headers = client._client.post.call_args.kwargs["headers"]
        self.assertNotIn("Authorization", headers)

    def test_timeout_maps_to_connection_error(self):
        client = OneBotClient("http://napcat-1:3000")
        client._client = FakeAsyncClient()
        client._client.post.side_effect = httpx.TimeoutException("timed out")
        with self.assertRaises(OneBotConnectionError):
            run(client.get_login_info())

    def test_http_error_maps_to_connection_error(self):
        client = OneBotClient("http://napcat-1:3000")
        client._client = FakeAsyncClient()
        client._client.post.side_effect = httpx.ConnectError("refused")
        with self.assertRaises(OneBotConnectionError):
            run(client.get_login_info())


if __name__ == "__main__":
    unittest.main()
