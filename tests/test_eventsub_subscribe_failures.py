import asyncio

import pytest

from src.chat.eventsub_backend import EventSubChatBackend


class DummyAPI:
    def __init__(self, statuses):
        self.statuses = list(statuses)
    async def request(self, method, endpoint, *, access_token, client_id, json_body, params=None, json=None):  # noqa: D401
        await asyncio.sleep(0)
        status = self.statuses.pop(0)
        data = {"message": "err"} if status != 202 else {"ok": True}
        return data, status, {}

@pytest.mark.asyncio
async def test_two_401s_set_invalid_flag(monkeypatch):
    backend = EventSubChatBackend()
    backend._token = "tok"  # noqa: SLF001
    backend._client_id = "cid"  # noqa: SLF001
    backend._username = "user"  # noqa: SLF001
    backend._user_id = "uid"  # noqa: SLF001
    backend._session_id = "sess"  # noqa: SLF001
    backend._channel_ids = {"chan": "bid"}  # noqa: SLF001
    backend._scopes = {"chat:read"}  # insufficient but not used for 401 path

    dummy = DummyAPI([401, 401])
    monkeypatch.setattr(backend, "_api", dummy)

    await backend._subscribe_channel_chat("chan")  # noqa: SLF001
    assert backend._consecutive_subscribe_401 == 1  # noqa: SLF001
    assert backend._token_invalid_flag is False  # noqa: SLF001
    await backend._subscribe_channel_chat("chan")  # second 401
    assert backend._consecutive_subscribe_401 == 2  # noqa: SLF001
    assert backend._token_invalid_flag is True  # noqa: SLF001

@pytest.mark.asyncio
async def test_403_missing_scopes_logs(monkeypatch):
    backend = EventSubChatBackend()
    backend._token = "tok"  # noqa: SLF001
    backend._client_id = "cid"  # noqa: SLF001
    backend._username = "user"  # noqa: SLF001
    backend._user_id = "uid"  # noqa: SLF001
    backend._session_id = "sess"  # noqa: SLF001
    backend._channel_ids = {"chan": "bid"}  # noqa: SLF001
    backend._scopes = {"chat:read"}  # missing user:read:chat

    dummy = DummyAPI([403])
    monkeypatch.setattr(backend, "_api", dummy)

    await backend._subscribe_channel_chat("chan")  # noqa: SLF001
    # token_invalid_flag should remain False; just logging occurs
    assert backend._token_invalid_flag is False  # noqa: SLF001
