"""Thin asynchronous Twitch Helix API client used by bots.

Currently wraps only the endpoints required by the color changer bot.
If new endpoints are needed, prefer adding focused methods instead of
sprinkling raw request logic across modules.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import aiohttp


class TwitchAPI:
    """Asynchronous client for Twitch Helix API endpoints.

    Provides methods to interact with Twitch API for user validation, user ID resolution, and raw requests.

    Attributes:
        BASE_URL (str): The base URL for Twitch Helix API.
    """

    BASE_URL = "https://api.twitch.tv/helix"

    def __init__(self, session: aiohttp.ClientSession):
        """Initialize the TwitchAPI client.

        Args:
            session (aiohttp.ClientSession): The aiohttp session to use for requests.

        Raises:
            ValueError: If session is not provided.
        """
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
        """Perform a raw HTTP request to the Twitch Helix API.

        Args:
            method (str): HTTP method (e.g., 'GET', 'POST').
            endpoint (str): API endpoint path (without base URL).
            access_token (str): OAuth access token for authorization.
            client_id (str): Twitch application client ID.
            params (dict[str, Any] | None): Query parameters for the request.
            json_body (dict[str, Any] | None): JSON body for the request.

        Returns:
            tuple[dict[str, Any], int, dict[str, str]]: A tuple containing the JSON response data, HTTP status code, and response headers.
        """
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
    async def validate_token(self, access_token: str) -> dict[str, Any] | None:
        """Validate an OAuth access token using Twitch's validation endpoint.

        Args:
            access_token (str): The OAuth access token to validate.

        Returns:
            dict[str, Any] | None: Token validation payload if valid, None otherwise.
        """
        url = "https://id.twitch.tv/oauth2/validate"
        headers = {"Authorization": f"OAuth {access_token}"}
        try:
            async with self._session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    return await resp.json()
                return None
        except Exception:  # noqa: BLE001
            return None

    async def get_users_by_login(
        self, *, access_token: str, client_id: str, logins: list[str]
    ) -> dict[str, str]:
        """Resolve Twitch login names to user IDs.

        Args:
            access_token (str): OAuth access token.
            client_id (str): Twitch application client ID.
            logins (list[str]): List of login names to resolve.

        Returns:
            dict[str, str]: Mapping of lowercase login names to user IDs. Unknown logins are omitted.
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
        """Remove duplicates from a list of login names, preserving order and case-insensitively.

        Args:
            logins (list[str]): List of login names.

        Returns:
            list[str]: Deduplicated list of lowercase login names.
        """
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
        """Split a sequence into chunks of specified size.

        Args:
            seq (list[str]): The sequence to chunk.
            size (int): Maximum size of each chunk.

        Yields:
            Iterable[list[str]]: Chunks of the sequence.
        """
        for i in range(0, len(seq), size):
            yield seq[i : i + size]

    @staticmethod
    def _auth_headers(access_token: str, client_id: str) -> dict[str, str]:
        """Generate authorization headers for Twitch API requests.

        Args:
            access_token (str): OAuth access token.
            client_id (str): Twitch application client ID.

        Returns:
            dict[str, str]: Dictionary of HTTP headers.
        """
        return {
            "Authorization": f"Bearer {access_token}",
            "Client-Id": client_id,
            "Content-Type": "application/json",
        }

    @staticmethod
    async def _safe_rows(resp: aiohttp.ClientResponse) -> list[dict[str, Any]]:
        """Safely extract data rows from an aiohttp response.

        Args:
            resp (aiohttp.ClientResponse): The response object.

        Returns:
            list[dict[str, Any]]: List of data dictionaries, or empty list on error.
        """
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
