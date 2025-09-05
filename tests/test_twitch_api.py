from __future__ import annotations

import asyncio
from typing import Any

import pytest

from src.api.twitch import TwitchAPI


class _Resp:
    def __init__(self, status: int, payload: dict[str, Any] | list[Any] | None, headers: dict[str, str] | None = None):
        self.status = status
        self._payload = payload
        self.headers = headers or {}

    async def json(self) -> Any:  # noqa: D401
        await asyncio.sleep(0)
        return self._payload


class _Session:
    def __init__(self):
        self.requests: list[tuple[str, str, dict[str, Any]]] = []
        self._queue: list[_Resp] = []

    def queue(self, resp: _Resp) -> None:
        self._queue.append(resp)

    def request(self, method: str, url: str, headers=None, params=None, json=None):  # noqa: A002
        self.requests.append((method, url, {"headers": headers, "params": params, "json": json}))
        resp = self._queue.pop(0)

        class _CM:
            async def __aenter__(self_inner):  # noqa: ANN001
                return resp

            async def __aexit__(self_inner, exc_type, exc, tb):  # noqa: ANN001
                return False

        return _CM()

    def get(self, url: str, headers=None, params=None):  # noqa: D401
        return self.request("GET", url, headers=headers, params=params)


def test_twitch_api_request_headers() -> None:
    session = _Session()
    session.queue(_Resp(200, {}))
    api = TwitchAPI(session)  # type: ignore[arg-type]
    data, status, _ = asyncio.run(api.request("GET", "users", access_token="AT", client_id="CID"))
    if status != 200 or data != {}:
        raise AssertionError("Unexpected response from mocked request")
    method, url, meta = session.requests[0]
    if method != "GET" or not url.endswith("/users"):
        raise AssertionError("URL or method mismatch")
    h = meta["headers"]
    if h["Authorization"] != "Bearer AT" or h["Client-Id"] != "CID":
        raise AssertionError("Auth headers not set correctly")


def test_get_users_by_login_dedup_and_chunk(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session()
    api = TwitchAPI(session)  # type: ignore[arg-type]

    # Prepare multiple chunk responses (simulate 3 chunked requests)
    # Build payload with 'data' list of dicts
    def make_payload(logins):
        return {"data": [{"login": l, "id": f"id_{l}"} for l in logins]}

    # Queue: expect 3 chunks (250 total -> 100 + 100 + 50)
    session.queue(_Resp(200, make_payload([f"user{i}" for i in range(100)])))
    session.queue(_Resp(200, make_payload([f"user{i}" for i in range(100, 200)])))
    session.queue(_Resp(200, make_payload([f"user{i}" for i in range(200, 250)])))

    big_list = [f"User{i}" for i in range(250)] + ["user0", "USER1"]  # duplicates to test dedupe
    mapping = asyncio.run(api.get_users_by_login(access_token="AT", client_id="CID", logins=big_list))
    # Ensure deduped: size should be 250
    if len(mapping) != 250:
        raise AssertionError(f"Expected 250 unique mappings, got {len(mapping)}")
    # Spot check a value
    if mapping.get("user5") != "id_user5":
        raise AssertionError("Missing expected user mapping")
    # Verify number of requests performed
    if len(session.requests) != 3:
        raise AssertionError("Expected 3 chunked requests for 250 users")


def test_validate_token_success_and_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session()
    api = TwitchAPI(session)  # type: ignore[arg-type]

    # Success path
    session.queue(_Resp(200, {"client_id": "cid", "scopes": ["a"]}))
    # Failure path (non-200)
    session.queue(_Resp(401, {"status": 401}))

    result_ok = asyncio.run(api.validate_token("AT"))
    if not result_ok or result_ok.get("client_id") != "cid":
        raise AssertionError("Expected successful validation data")
    result_fail = asyncio.run(api.validate_token("AT"))
    if result_fail is not None:
        raise AssertionError("Expected None on failed validation")
