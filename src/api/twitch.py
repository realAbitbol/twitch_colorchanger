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

    async def validate_token(self, access_token: str) -> dict[str, Any] | None:
        """Validate OAuth token and return payload with scopes.

        Uses Twitch validation endpoint outside Helix base URL.
        Returns dict or None on failure.
        """
        url = "https://id.twitch.tv/oauth2/validate"
        headers = {"Authorization": f"OAuth {access_token}"}
        try:
            async with self._session.get(url, headers=headers) as resp:
                data: dict[str, Any] | None
                try:
                    data = await resp.json()
                except Exception:  # noqa: BLE001
                    data = None
                if resp.status == 200 and isinstance(data, dict):
                    return data
                return None
        except Exception:  # noqa: BLE001
            return None

    async def get_users_by_login(
        self, *, access_token: str, client_id: str, logins: list[str]
    ) -> dict[str, str]:
        """Resolve many login names to user IDs.

        Helix allows up to 100 "login" query params per request. We chunk the input,
        aggregate responses, and return a mapping of login(lowercased) -> user id.
        Missing / unknown logins are simply absent from the result mapping.
        """
        if not logins:
            return {}
        deduped = self._dedupe_logins(logins)
        headers = self._auth_headers(access_token, client_id)
        out: dict[str, str] = {}
        url = f"{self.BASE_URL}/users"
        for part in self._chunk(deduped, 100):
            params_list = [("login", c) for c in part]
            async with self._session.get(
                url, headers=headers, params=params_list
            ) as resp:
                rows = await self._safe_rows(resp)
                for entry in rows:
                    login = entry.get("login")
                    uid = entry.get("id")
                    if isinstance(login, str) and isinstance(uid, str):
                        out[login.lower()] = uid
        return out

    # ---- internal helpers (kept simple to satisfy static checks) ----
    @staticmethod
    def _dedupe_logins(logins: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for raw in logins:
            ll = raw.lower()
            if ll not in seen:
                seen.add(ll)
                out.append(ll)
        return out

    @staticmethod
    def _chunk(seq: list[str], size: int) -> Iterable[list[str]]:
        for i in range(0, len(seq), size):
            yield seq[i : i + size]

    @staticmethod
    def _auth_headers(access_token: str, client_id: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {access_token}",
            "Client-Id": client_id,
            "Content-Type": "application/json",
        }

    @staticmethod
    async def _safe_rows(resp: aiohttp.ClientResponse) -> list[dict[str, Any]]:
        try:
            data = await resp.json()
        except Exception:  # noqa: BLE001
            return []
        if resp.status != 200 or not isinstance(data, dict):
            return []
        rows = data.get("data")
        if isinstance(rows, list):
            return [r for r in rows if isinstance(r, dict)]
        return []

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
