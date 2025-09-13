"""Device Code Flow implementation for automatic token generation"""

import asyncio
import logging
import time
from typing import Any, cast

import aiohttp

from ..utils import format_duration


class DeviceCodeFlow:
    """Handles OAuth Device Authorization Grant flow for automatic token generation"""

    def __init__(self, client_id: str, client_secret: str):
        """Initialize the device code flow handler.

        Args:
            client_id: Twitch application client ID.
            client_secret: Twitch application client secret.
        """
        self.client_id = client_id
        self.client_secret = client_secret
        # Public OAuth endpoint constants (well-known; not secrets or passwords)
        # These are standard Twitch OAuth endpoints, not credentials or secrets.
        self.device_code_url = "https://id.twitch.tv/oauth2/device"
        # Standard public Twitch OAuth token endpoint (well-known; not a secret).
        # Security linters (Bandit/Ruff S105) flag this as a potential hardcoded password/secret,
        # but it's a fixed public endpoint URL, not credentials.
        self.token_url = "https://id.twitch.tv/oauth2/token"  # nosec B105  # noqa: S105
        self.poll_interval = 5  # seconds

    async def request_device_code(self) -> dict[str, Any] | None:
        """Request a device code from Twitch for OAuth flow.

        Returns:
            Device code data on success, None on failure.
        """
        data = {
            "client_id": self.client_id,
            # Include EventSub chat reading scope so subscriptions succeed.
            "scopes": "chat:read user:read:chat user:manage:chat_color",
        }

        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(self.device_code_url, data=data) as response:
                    if response.status == 200:
                        result = cast(dict[str, Any], await response.json())
                        logging.info(
                            f"🔑 Device code retrieved successfully client_id={self.client_id} interval={self.poll_interval}"
                        )
                        return result
                    error_data = cast(dict[str, Any], await response.json())
                    logging.error(
                        f"💥 Failed to obtain device code (status={response.status}) client_id={self.client_id} error_data={str(error_data)}"
                    )
                    return None

            except Exception as e:
                logging.error(
                    f"💥 Exception while requesting device code: {type(e).__name__} {str(e)} client_id={self.client_id}"
                )
                return None

    async def poll_for_tokens(
        self, device_code: str, expires_in: int
    ) -> dict[str, Any] | None:
        """Poll Twitch for token authorization completion.

        Continuously polls until authorization succeeds, fails, or times out.

        Args:
            device_code: Device code from initial request.
            expires_in: Total seconds before device code expires.

        Returns:
            Token data on success, None on failure or timeout.
        """
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "device_code": device_code,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        }

        start_time = time.time()
        poll_count = 0

        async with aiohttp.ClientSession() as session:
            while time.time() - start_time < expires_in:
                poll_count += 1
                elapsed = int(time.time() - start_time)

                try:
                    async with session.post(self.token_url, data=data) as response:
                        result = cast(dict[str, Any], await response.json())

                        if response.status == 200:
                            logging.info(
                                f"Authorized after {format_duration(elapsed)} (polls={poll_count}) client_id={self.client_id}"
                            )
                            return result

                        if response.status == 400:
                            # Handle specific polling errors (pending, slow_down, etc.)
                            error_result = self._handle_polling_error(
                                result, elapsed, poll_count
                            )
                            if error_result is not None:
                                return error_result
                        else:
                            logging.error(
                                f"⚠️ Unexpected device token response: status={response.status} result={str(result)}"
                            )
                            return None

                except Exception as e:
                    logging.error(
                        f"💥 Exception polling for tokens: {type(e).__name__} {str(e)} elapsed={elapsed} polls={poll_count}"
                    )
                    return None

                # Wait before next poll
                await asyncio.sleep(self.poll_interval)

        logging.error(
            f"Timed out after {format_duration(expires_in)} client_id={self.client_id}"
        )
        return None

    def _handle_polling_error(
        self, result: dict[str, Any], elapsed: int, poll_count: int
    ) -> dict[str, Any] | None:
        """Handle specific polling errors from Twitch API.

        Args:
            result: Response JSON from polling request.
            elapsed: Seconds elapsed since polling started.
            poll_count: Number of polls performed.

        Returns:
            None to continue polling, empty dict to stop.
        """
        # Twitch API returns errors in 'message' field, not 'error'
        error = result.get("message", result.get("error", "unknown"))
        error_description = result.get("error_description", "")

        # Log full error details for debugging (only for non-pending errors)
        if error != "authorization_pending":
            logging.debug(f"🧪 Polling error details logged details={str(result)}")

        if error == "authorization_pending":
            # Still waiting for user authorization; continue polling
            if poll_count % 6 == 0:  # Show message every 30 seconds
                logging.info(
                    f"Waiting for authorization {format_duration(elapsed)} elapsed polls={poll_count}"
                )
            return None  # Continue polling

        if error == "slow_down":
            # Server requests slower polling; adjust interval
            self.poll_interval = min(self.poll_interval + 1, 10)
            logging.warning(
                f"Server requested slower polling interval={self.poll_interval}s elapsed={elapsed} polls={poll_count}"
            )
            return None  # Continue polling

        if error == "expired_token":
            logging.error(
                f"Device code expired after {format_duration(elapsed)} polls={poll_count}"
            )
            return {}  # Stop polling

        if error == "access_denied":
            logging.warning(f"User denied access elapsed={elapsed} polls={poll_count}")
            return {}  # Stop polling

        # Unknown error; stop polling
        if error_description:
            logging.error(f"💥 Device flow error: {error} {error_description}")
        else:
            logging.error(f"💥 Unknown device flow error: {error}")
        return {}  # Stop polling

    async def get_user_tokens(self, username: str) -> tuple[str, str] | None:
        """Complete the full device code flow to obtain user tokens.

        Orchestrates the three-step process: request device code, prompt user,
        and poll for authorization completion.

        Args:
            username: Username for logging purposes.

        Returns:
            Tuple of (access_token, refresh_token) on success, None on failure.
        """
        logging.info(
            f"Starting device authorization user={username} poll_interval={self.poll_interval}"
        )
        logging.info(f"Authorization required user={username}")

        # Step 1: Request device code
        device_data = await self.request_device_code()
        if not device_data:
            return None

        device_code = device_data["device_code"]
        user_code = device_data["user_code"]
        verification_uri = device_data["verification_uri"]
        expires_in = device_data["expires_in"]

        # Step 2: Display instructions to user
        logging.info(
            f"Open {verification_uri} and enter code {user_code} (expires in {format_duration(expires_in)}) user={username} expires_minutes={expires_in // 60}"
        )
        logging.info(
            f"Polling every {self.poll_interval}s for authorization user={username} interval={self.poll_interval}"
        )

        # Step 3: Poll for authorization
        token_data = await self.poll_for_tokens(device_code, expires_in)
        if not token_data:
            return None
        access_token = token_data["access_token"]
        refresh_token = token_data.get("refresh_token", "")
        logging.info(f"Tokens obtained user={username}")
        return access_token, refresh_token
