"""Thin asynchronous Twitch Helix API client used by bots.

Currently wraps only the endpoints required by the color changer bot.
If new endpoints are needed, prefer adding focused methods instead of
sprinkling raw request logic across modules.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import aiohttp


class TwitchAPIError(RuntimeError):  # pragma: no cover (simple wrapper)
    pass


class TwitchAPI:
    BASE_URL = "https://api.twitch.tv/helix"

    def __init__(self, session: aiohttp.ClientSession):
        if not session:
            raise ValueError("aiohttp session required")
        self._session = session

    async def request(
        self,
        method: str,
        endpoint: str,
        *,
        access_token: str,
        client_id: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], int, dict[str, str]]:
        """Perform raw Helix request returning (json, status, headers)."""
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Client-Id": client_id,
            "Content-Type": "application/json",
        }
        url = f"{self.BASE_URL}/{endpoint}"
        async with self._session.request(
            method, url, headers=headers, params=params, json=json_body
        ) as resp:
            try:
                data = await resp.json()
            except Exception:  # noqa: BLE001
                data = {}
            return data, resp.status, dict(resp.headers)

    # ---- High level helpers ----
    async def get_user(
        self, *, access_token: str, client_id: str
    ) -> dict[str, Any] | None:
        data, status, _ = await self.request(
            "GET", "users", access_token=access_token, client_id=client_id
        )
        if status == 200 and isinstance(data.get("data"), list) and data["data"]:
            first = data["data"][0]
            if isinstance(first, dict):
                return first
        return None

    async def get_chat_color(
        self, *, access_token: str, client_id: str, user_id: str
    ) -> str | None:
        params = {"user_id": user_id}
        data, status, _ = await self.request(
            "GET",
            "chat/color",
            access_token=access_token,
            client_id=client_id,
            params=params,
        )
        if status == 200 and isinstance(data.get("data"), list) and data["data"]:
            entry = data["data"][0]
            if isinstance(entry, dict):
                color = entry.get("color")
                if isinstance(color, str):
                    return color
        return None

    async def set_chat_color(
        self,
        *,
        access_token: str,
        client_id: str,
        user_id: str,
        color: str,
    ) -> int:
        params = {"user_id": user_id, "color": color}
        _data, status, _headers = await self.request(
            "PUT",
            "chat/color",
            access_token=access_token,
            client_id=client_id,
            params=params,
        )
        return status

    @staticmethod
    def scrub_headers(
        headers: dict[str, str], keys: Iterable[str]
    ) -> dict[str, str]:  # pragma: no cover
        return {k: v for k, v in headers.items() if k in keys}


def get_api(session: aiohttp.ClientSession) -> TwitchAPI:  # pragma: no cover
    return TwitchAPI(session)
