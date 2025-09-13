"""ColorChanger mixin for TwitchColorBot - handles color change logic and API calls."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from ..api.twitch import TwitchAPI
from ..color import ColorChangeService
from ..color.models import ColorRequestResult, ColorRequestStatus
from ..config.async_persistence import queue_user_update
from ..errors.handling import handle_retryable_error

CHAT_COLOR_ENDPOINT = "chat/color"


class ColorChanger:
    """Mixin class for handling color change logic and API calls."""

    # Expected attributes from consumer class
    username: str
    config_file: str | None
    user_id: str | None
    api: TwitchAPI
    access_token: str
    client_id: str
    colors_changed: int
    _color_service: ColorChangeService | None
    last_color: str | None

    """Mixin class for handling color change logic and API calls."""

    def _init_color_cache(self) -> None:
        """Initialize the color cache for optimization."""
        self._cache_lock = asyncio.Lock()
        self._current_color_cache: dict[str, dict[str, Any]] = {}
        self._successful_color_cache: dict[str, set[str]] = {}
        self._cache_ttl = 30.0  # 30 seconds for current color cache

    async def on_persistent_prime_detection(self) -> None:
        """Persist that this user should not use random hex colors.

        Sets is_prime_or_turbo to False in the user's config and writes via
        debounced queue. This method is invoked by ColorChangeService when
        repeated hex rejections indicate lack of Turbo/Prime privileges.
        """
        if not self.config_file:
            return
        user_config = self._build_user_config()  # type: ignore
        user_config["is_prime_or_turbo"] = False
        try:
            await queue_user_update(user_config, self.config_file)
        except Exception as e:
            logging.warning(f"Persist detection error: {str(e)}")

    async def _prime_color_state(self) -> None:
        """Initialize last_color with the user's current chat color.

        Fetches the current color from Twitch API and sets it as the last known color.
        """
        current_color = await self._get_current_color()
        if current_color:
            self.last_color = current_color
            logging.info(
                f"🎨 Initialized with current color {current_color} user={self.username}"
            )

    async def _ensure_user_id(self) -> bool:
        """Ensure user_id is available, fetching from API if needed.

        Returns:
            True if user_id is available or successfully retrieved, False otherwise.
        """
        if self.user_id:
            return True
        user_info = await self._get_user_info()
        if user_info and "id" in user_info:
            self.user_id = user_info["id"]
            logging.debug(f"🆔 Retrieved user_id {self.user_id} user={self.username}")
            return True
        logging.error(f"❌ Failed to retrieve user_id user={self.username}")
        return False

    async def _get_user_info(self) -> dict[str, Any] | None:
        """Fetch user information from Twitch API.

        Returns:
            User info dict or None if failed.
        """
        return await self._get_user_info_impl()

    async def _make_user_info_request(self) -> tuple[dict[str, Any] | None, int]:
        """Make the actual API request for user info.

        Returns:
            Tuple of (response data, status code).
        """
        data, status_code, _ = await self.api.request(
            "GET",
            "users",
            access_token=self.access_token,
            client_id=self.client_id,
        )
        return data, status_code

    def _calculate_retry_delay(self, attempt: int) -> float:
        """Calculate exponential backoff delay for retries.

        Args:
            attempt: Current attempt number (0-based).

        Returns:
            Delay in seconds, capped at 60.
        """
        return min(1 * (2**attempt), 60)

    async def _get_user_info_impl(self) -> dict[str, Any] | None:
        """Implementation of user info fetching with retries.

        Handles API errors and retries with exponential backoff.

        Returns:
            User info dict or None if all attempts failed.
        """

        async def operation(attempt):
            data, status_code = await self._make_user_info_request()
            result = self._process_user_info_response(data, status_code, attempt)
            should_retry = (
                result is None
                and attempt < 5
                and (status_code == 429 or status_code >= 500)
            )
            return result, should_retry

        try:
            return await handle_retryable_error(
                operation, "User info fetch", max_attempts=6
            )
        except Exception:
            return None

    def _process_user_info_response(
        self, data: dict[str, Any] | None, status_code: int, attempt: int
    ) -> dict[str, Any] | None:
        """Process the response from user info API request.

        Args:
            data: Response data dict.
            status_code: HTTP status code.
            attempt: Current attempt number.

        Returns:
            User info dict or None for retry/error.
        """
        if (
            status_code == 200
            and data
            and isinstance(data.get("data"), list)
            and data["data"]
        ):
            first = data["data"][0]
            if isinstance(first, dict):
                return first
            return None
        if status_code == 401:
            return None
        if attempt < 5 and (status_code == 429 or status_code >= 500):
            return None  # indicate retry
        logging.error(
            f"❌ Failed to get user info status={status_code} user={self.username}"
        )
        return None

    async def _get_current_color(self) -> str | None:
        """Fetch the user's current chat color from Twitch API.

        Returns:
            Color string or None if failed.
        """
        return await self._get_current_color_impl()

    async def _get_current_color_impl(self) -> str | None:
        """Implementation of current color fetching with retries.

        Handles API errors and retries with exponential backoff.
        Uses cache to avoid recent fetches.

        Returns:
            Color string or None if all attempts failed.
        """
        # Check cache first
        async with self._cache_lock:
            if self.user_id in self._current_color_cache:
                cached = self._current_color_cache[self.user_id]
                if time.time() - cached["timestamp"] < self._cache_ttl:
                    logging.debug(
                        f"Using cached current color: {cached['color']} user={self.username}"
                    )
                    return cached["color"]

        async def operation(attempt):
            data, status_code = await self._make_color_request()
            result = self._process_color_response(data, status_code, attempt)
            should_retry = (
                result is None
                and attempt < 5
                and (status_code == 429 or status_code >= 500)
            )
            return result, should_retry

        try:
            color = await handle_retryable_error(
                operation, "Current color fetch", max_attempts=6
            )
            # Cache the result if successful
            if color and self.user_id:
                async with self._cache_lock:
                    self._current_color_cache[self.user_id] = {
                        "color": color,
                        "timestamp": time.time(),
                    }
            return color
        except Exception:
            return None

    async def _make_color_request(self) -> tuple[dict[str, Any] | None, int]:
        """Make the actual API request for current color.

        Returns:
            Tuple of (response data, status code).
        """
        params = {"user_id": self.user_id}
        data, status_code, _ = await self.api.request(
            "GET",
            CHAT_COLOR_ENDPOINT,
            access_token=self.access_token,
            client_id=self.client_id,
            params=params,
        )
        return data, status_code

    def _process_color_response(
        self, data: dict[str, Any] | None, status_code: int, attempt: int
    ) -> str | None:
        """Process the response from color API request.

        Args:
            data: Response data dict.
            status_code: HTTP status code.
            attempt: Current attempt number.

        Returns:
            Color string or None for retry/error.
        """
        if status_code == 200 and data and data.get("data"):
            first = data["data"][0]
            if isinstance(first, dict):
                color = first.get("color")
                if isinstance(color, str):
                    logging.info(f"🎨 Current color is {color} user={self.username}")
                    return color
        if status_code == 401:
            return None
        if attempt < 5 and (status_code == 429 or status_code >= 500):
            return None  # indicate retry
        logging.info(f"⚠️ No current color set user={self.username}")
        return None

    # --- Color change low-level request (expected by ColorChangeService) ---
    async def _perform_color_request(
        self, params: dict[str, str], *, action: str
    ) -> ColorRequestResult:  # noqa: D401
        """Issue a raw color change (PUT chat/color) returning structured result.

        This restores the method expected by ColorChangeService._issue_request.
        It encapsulates: status classification, logging
        of certain error diagnostics, and payload capture for later snippets.
        Uses cache to skip API calls for known successful colors.
        """
        color = params.get("color")
        if color and self.user_id:
            async with self._cache_lock:
                if (
                    self.user_id in self._successful_color_cache
                    and color in self._successful_color_cache[self.user_id]
                ):
                    logging.debug(
                        f"Using cached successful color change: {color} user={self.username}"
                    )
                    return ColorRequestResult(
                        ColorRequestStatus.SUCCESS, http_status=204
                    )

        logging.debug(f"Performing color request action={action} user={self.username}")

        async def operation(attempt):
            data, status_code, _ = await self.api.request(
                "PUT",
                CHAT_COLOR_ENDPOINT,
                access_token=self.access_token,
                client_id=self.client_id,
                params=params,
            )
            self._last_color_change_payload = data if isinstance(data, dict) else None

            result = self._handle_color_response(status_code, attempt)
            if result is not None:
                return result, False
            else:
                return ColorRequestResult(
                    ColorRequestStatus.INTERNAL_ERROR, error="Retry needed"
                ), True

        try:
            result = await handle_retryable_error(
                operation, f"Color change {action}", max_attempts=6
            )
            # Cache successful color changes
            if result.status == ColorRequestStatus.SUCCESS and color and self.user_id:
                async with self._cache_lock:
                    if self.user_id not in self._successful_color_cache:
                        self._successful_color_cache[self.user_id] = set()
                    self._successful_color_cache[self.user_id].add(color)
                    # Also update current color cache since we just set it
                    self._current_color_cache[self.user_id] = {
                        "color": color,
                        "timestamp": time.time(),
                    }
            return result
        except Exception:
            return ColorRequestResult(
                ColorRequestStatus.INTERNAL_ERROR, error="Max retries exceeded"
            )

    def _handle_color_response(
        self, status_code: int, attempt: int
    ) -> ColorRequestResult | None:
        """Handle HTTP response for color change request.

        Args:
            status_code: HTTP status code.
            attempt: Current attempt number.

        Returns:
            ColorRequestResult or None for retry.
        """
        if status_code in (200, 204):
            return ColorRequestResult(
                ColorRequestStatus.SUCCESS, http_status=status_code
            )
        elif status_code == 401:
            return ColorRequestResult(
                ColorRequestStatus.UNAUTHORIZED, http_status=status_code
            )
        elif status_code == 429 and attempt < 5:
            return None  # retry
        elif status_code == 429:
            return ColorRequestResult(
                ColorRequestStatus.RATE_LIMIT, http_status=status_code
            )
        elif status_code >= 500 and attempt < 5:
            return None  # retry
        elif status_code >= 500:
            return ColorRequestResult(
                ColorRequestStatus.HTTP_ERROR,
                http_status=status_code,
                error=self._extract_color_error_snippet(),
            )
        return ColorRequestResult(
            ColorRequestStatus.HTTP_ERROR,
            http_status=status_code,
            error=self._extract_color_error_snippet(),
        )

    def _handle_color_exception(
        self, e: Exception, attempt: int
    ) -> ColorRequestResult | None:
        """Handle exceptions during color change request.

        Args:
            e: The exception that occurred.
            attempt: Current attempt number.

        Returns:
            ColorRequestResult or None for retry.
        """
        if attempt < 5:
            return None  # retry
        if isinstance(e, TimeoutError):
            return ColorRequestResult(ColorRequestStatus.TIMEOUT, error=str(e))
        return ColorRequestResult(ColorRequestStatus.INTERNAL_ERROR, error=str(e))

    def increment_colors_changed(self) -> None:
        """Increment the counter for successful color changes."""
        self.colors_changed += 1

    async def _change_color(self, hex_color: str | None = None) -> bool:
        """Change the user's chat color.

        Args:
            hex_color: Specific color to set, or None for random.

        Returns:
            True if color change was successful.
        """
        # Local import only when needed to avoid circular dependency at import time
        if self._color_service is None:
            from ..color import ColorChangeService  # local import

            self._color_service = ColorChangeService(self)
        return await self._color_service.change_color(hex_color)

    def _extract_color_error_snippet(self) -> str | None:
        """Extract error message from last color change response.

        Returns:
            Error message string or None if not available.
        """
        try:  # pragma: no cover - defensive
            payload: dict[str, Any] | None = self._last_color_change_payload
            if payload is None:
                return None
            if isinstance(payload, dict):
                message = payload.get("message") or payload.get("error")
                base = message if message else payload
                return str(base)[:200]
        except Exception:  # noqa: BLE001
            return None
