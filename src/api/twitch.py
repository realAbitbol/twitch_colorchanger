"""Thin asynchronous Twitch Helix API client used by bots.

Currently wraps only the endpoints required by the color changer bot.
If new endpoints are needed, prefer adding focused methods instead of
sprinkling raw request logic across modules.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

import aiohttp

from ..errors.handling import handle_api_error
from ..errors.internal import InternalError
from ..utils.circuit_breaker import (
    CircuitBreakerConfig,
    CircuitBreakerOpenException,
    get_circuit_breaker,
)


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

        # Circuit breaker for API requests
        cb_config = CircuitBreakerConfig(
            name="twitch_api",
            failure_threshold=5,
            recovery_timeout=60.0,
            success_threshold=3,
        )
        self.circuit_breaker = get_circuit_breaker("twitch_api", cb_config)

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

        Raises:
            aiohttp.ClientError: If network request fails.
            TimeoutError: If request times out.
            ValueError: If response parsing fails.
            CircuitBreakerOpenException: If circuit breaker is open.
        """
        async def _perform_request() -> tuple[dict[str, Any], int, dict[str, str]]:
            """Internal request logic wrapped by circuit breaker."""
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Client-Id": client_id,
                "Content-Type": "application/json",
            }
            url = f"{self.BASE_URL}/{endpoint}"
            async with self._session.request(
                method, url, headers=headers, params=params, json=json_body
            ) as resp:
                logging.debug(
                    f"Twitch API response: status={resp.status}, content-type={resp.headers.get('content-type', 'none')}, "
                    f"content-length={resp.headers.get('content-length', 'unknown')}, url={url}"
                )

                async def operation():
                    return await resp.json()

                try:
                    if resp.status == 204:
                        # 204 No Content has no body, so don't try to parse JSON
                        data = {}
                    else:
                        data = await handle_api_error(
                            operation, f"Twitch API {method} {endpoint}"
                        )
                except (
                    aiohttp.ClientError,
                    TimeoutError,
                    ConnectionError,
                    ValueError,
                    RuntimeError,
                    InternalError,
                ):
                    data = {}
                return data, resp.status, dict(resp.headers)

        try:
            return await self.circuit_breaker.call(_perform_request)
        except CircuitBreakerOpenException:
            logging.error(f"🚨 Twitch API request blocked by circuit breaker: {method} {endpoint}")
            # Return a failed response tuple when circuit breaker is open
            return {}, 503, {"X-Circuit-Breaker": "OPEN"}

    # ---- High level helpers ----
    async def validate_token(self, access_token: str) -> dict[str, Any] | None:
        """Validate an OAuth access token using Twitch's validation endpoint.

        Args:
            access_token (str): The OAuth access token to validate.

        Returns:
            dict[str, Any] | None: Token validation payload if valid, None otherwise.

        Raises:
            aiohttp.ClientError: If network request fails.
            TimeoutError: If request times out.
            ValueError: If response parsing fails.
        """

        async def operation():
            url = "https://id.twitch.tv/oauth2/validate"
            headers = {"Authorization": f"OAuth {access_token}"}
            async with self._session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    return await resp.json()
                return None

        try:
            return await handle_api_error(operation, "Twitch token validation")
        except (
            aiohttp.ClientError,
            TimeoutError,
            ConnectionError,
            ValueError,
            RuntimeError,
            InternalError,
        ):
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

        Raises:
            aiohttp.ClientError: If network request fails.
            TimeoutError: If request times out.
            ValueError: If response parsing fails.

        Example:
            >>> api = TwitchAPI(session)
            >>> users = await api.get_users_by_login(
            ...     access_token="token",
            ...     client_id="client_id",
            ...     logins=["user1", "user2"]
            ... )
            >>> print(users)
            {'user1': '12345', 'user2': '67890'}
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
                import logging

                logging.debug(
                    f"🔍 Twitch API get_users status={resp.status} logins={part}"
                )
                rows = await self._safe_rows(resp)
                logging.debug(
                    f"📋 Twitch API get_users rows={len(rows)} for logins={part}"
                )
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

    async def _safe_rows(self, resp: aiohttp.ClientResponse) -> list[dict[str, Any]]:
        """Safely extract data rows from an aiohttp response.

        Args:
            resp (aiohttp.ClientResponse): The response object.

        Returns:
            list[dict[str, Any]]: List of data dictionaries, or empty list on error.
        """

        async def operation():
            return await resp.json()

        try:
            data = await handle_api_error(operation, "Twitch API response parsing")
        except (
            aiohttp.ClientError,
            TimeoutError,
            ConnectionError,
            ValueError,
            RuntimeError,
            InternalError,
        ):
            return []
        if resp.status != 200 or not isinstance(data, dict):
            return []
        rows = data.get("data")
        if isinstance(rows, list):
            return [r for r in rows if isinstance(r, dict)]
        return []
