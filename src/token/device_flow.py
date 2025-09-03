"""Device Code Flow implementation for automatic token generation"""

import asyncio
import logging
import time

import aiohttp

from logs.logger import logger
from utils import format_duration


class DeviceCodeFlow:
    """Handles OAuth Device Authorization Grant flow for automatic token generation"""

    def __init__(self, client_id: str, client_secret: str):
        """Initialize device flow state."""
        self.client_id = client_id
        self.client_secret = client_secret
        # Public OAuth endpoint constants (well-known; not secrets or passwords)
        # These are standard Twitch OAuth endpoints, not credentials or secrets.
        self.device_code_url = "https://id.twitch.tv/oauth2/device"
        # Standard public Twitch OAuth token endpoint (not a secret or credential)
        self.token_url = "https://id.twitch.tv/oauth2/token"  # noqa: S105  # nosec B105
        self.poll_interval = 5  # seconds

    async def request_device_code(self) -> dict | None:
        """Request a device code from Twitch"""
        data = {
            "client_id": self.client_id,
            "scopes": "chat:read user:manage:chat_color",
        }

        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(self.device_code_url, data=data) as response:
                    if response.status == 200:
                        result = await response.json()
                        logger.log_event(
                            "device_flow",
                            "code_success",
                            level=logging.INFO,
                            client_id=self.client_id,
                            interval=self.poll_interval,
                        )
                        return result
                    error_data = await response.json()
                    logger.log_event(
                        "device_flow",
                        "code_error",
                        level=logging.ERROR,
                        client_id=self.client_id,
                        error_data=str(error_data),
                        status=response.status,
                    )
                    return None

            except Exception as e:
                logger.log_event(
                    "device_flow",
                    "code_exception",
                    level=logging.ERROR,
                    client_id=self.client_id,
                    error=str(e),
                    error_type=type(e).__name__,
                )
                return None

    async def poll_for_tokens(self, device_code: str, expires_in: int) -> dict | None:
        """Poll for token authorization completion"""
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
                        result = await response.json()

                        if response.status == 200:
                            logger.log_event(
                                "device_flow",
                                "authorization_success",
                                level=logging.INFO,
                                client_id=self.client_id,
                                elapsed=elapsed,
                                polls=poll_count,
                                human=f"Authorized after {format_duration(elapsed)} (polls={poll_count})",
                            )
                            return result

                        if response.status == 400:
                            error_result = self._handle_polling_error(
                                result, elapsed, poll_count
                            )
                            if error_result is not None:
                                return error_result
                        else:
                            logger.log_event(
                                "device_flow",
                                "unexpected_response",
                                level=logging.ERROR,
                                status=response.status,
                                result=str(result),
                            )
                            return None

                except Exception as e:
                    logger.log_event(
                        "device_flow",
                        "poll_exception",
                        level=logging.ERROR,
                        error=str(e),
                        error_type=type(e).__name__,
                        elapsed=elapsed,
                        polls=poll_count,
                    )
                    return None

                # Wait before next poll
                await asyncio.sleep(self.poll_interval)

        logger.log_event(
            "device_flow",
            "timeout",
            level=logging.ERROR,
            client_id=self.client_id,
            expires_in=expires_in,
            human=f"Timed out after {format_duration(expires_in)}",
        )
        return None

    def _handle_polling_error(
        self, result: dict, elapsed: int, poll_count: int
    ) -> dict | None:
        """Handle polling errors and return None to continue, or a value to return"""
        # Twitch API returns errors in 'message' field, not 'error'
        error = result.get("message", result.get("error", "unknown"))
        error_description = result.get("error_description", "")

        # Log the full error details for debugging (only for non-pending errors)
        if error != "authorization_pending":
            logger.log_event(
                "device_flow",
                "poll_error_details",
                level=logging.DEBUG,
                details=str(result),
            )

        if error == "authorization_pending":
            # Still waiting for user authorization
            if poll_count % 6 == 0:  # Show message every 30 seconds
                logger.log_event(
                    "device_flow",
                    "waiting_authorization",
                    level=logging.INFO,
                    elapsed=elapsed,
                    polls=poll_count,
                    human=f"Waiting for authorization {format_duration(elapsed)} elapsed",
                )
            return None  # Continue polling

        if error == "slow_down":
            # Increase polling interval
            self.poll_interval = min(self.poll_interval + 1, 10)
            logger.log_event(
                "device_flow",
                "slow_down",
                level=logging.WARNING,
                new_interval=self.poll_interval,
                elapsed=elapsed,
                polls=poll_count,
                human=f"Server requested slower polling interval={self.poll_interval}s",
            )
            return None  # Continue polling

        if error == "expired_token":
            logger.log_event(
                "device_flow",
                "expired_token",
                level=logging.ERROR,
                elapsed=elapsed,
                polls=poll_count,
                human=f"Device code expired after {format_duration(elapsed)}",
            )
            return {}  # Stop polling

        if error == "access_denied":
            logger.log_event(
                "device_flow",
                "access_denied",
                level=logging.WARNING,
                elapsed=elapsed,
                polls=poll_count,
                human="User denied access",
            )
            return {}  # Stop polling

        # Unknown error
        if error_description:
            logger.log_event(
                "device_flow",
                "error",
                level=logging.ERROR,
                error=error,
                description=error_description,
            )
        else:
            logger.log_event(
                "device_flow",
                "unknown_error",
                level=logging.ERROR,
                error=error,
            )
        return {}  # Stop polling

    async def get_user_tokens(self, username: str) -> tuple[str, str] | None:
        """
        Complete device code flow to get user tokens
        Returns (access_token, refresh_token) on success, None on failure
        """
        logger.log_event(
            "device_flow",
            "start",
            user=username,
            poll_interval=self.poll_interval,
            human="Starting device authorization",
        )
        logger.log_event(
            "device_flow",
            "authorization_required",
            user=username,
            human="Authorization required",
        )

        # Step 1: Request device code
        device_data = await self.request_device_code()
        if not device_data:
            return None

        device_code = device_data["device_code"]
        user_code = device_data["user_code"]
        verification_uri = device_data["verification_uri"]
        expires_in = device_data["expires_in"]

        # Step 2: Display instructions to user
        logger.log_event(
            "device_flow",
            "display_instructions",
            user=username,
            verification_uri=verification_uri,
            code=user_code,
            expires_minutes=expires_in // 60,
            human=f"Open {verification_uri} and enter code {user_code} (expires in {format_duration(expires_in)})",
        )
        logger.log_event(
            "device_flow",
            "waiting",
            user=username,
            interval=self.poll_interval,
            human=f"Polling every {self.poll_interval}s for authorization",
        )

        # Step 3: Poll for authorization
        token_data = await self.poll_for_tokens(device_code, expires_in)
        if not token_data:
            return None
        access_token = token_data["access_token"]
        refresh_token = token_data.get("refresh_token", "")
        logger.log_event(
            "device_flow", "tokens_obtained", user=username, human="Tokens obtained"
        )
        return access_token, refresh_token


# Backward compatibility alias (old code imported DeviceFlow)
DeviceFlow = DeviceCodeFlow
