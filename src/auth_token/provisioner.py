"""Token provisioning helpers (moved from token_provisioner.py)."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

import aiohttp

from ..constants import TOKEN_REFRESH_SAFETY_BUFFER_SECONDS
from ..utils import format_duration
from .device_flow import DeviceCodeFlow


class TokenProvisioner:
    """Handles token provisioning for users.

    Provides methods to provision tokens, either from existing ones or
    through interactive device flow authorization.
    """

    def __init__(self, session: aiohttp.ClientSession):
        """Initialize the token provisioner.

        Args:
            session: HTTP session for API requests.
        """
        self.session = session

    async def provision(
        self,
        client_id: str,
        client_secret: str,
        access_token: str | None,
        refresh_token: str | None,
        expiry: datetime | None,
    ) -> tuple[str | None, str | None, datetime | None]:
        """Provision tokens for a user.

        If tokens are provided, returns them; otherwise initiates interactive authorization.

        Args:
            client_id: Twitch client ID.
            client_secret: Twitch client secret.
            access_token: Existing access token.
            refresh_token: Existing refresh token.
            expiry: Existing expiry datetime.

        Returns:
            Tuple of (access_token, refresh_token, expiry).
        """
        if access_token and refresh_token:
            return access_token, refresh_token, expiry
        return await self._interactive_authorize(client_id, client_secret)

    async def _interactive_authorize(
        self, client_id: str, client_secret: str
    ) -> tuple[str | None, str | None, datetime | None]:
        """Perform interactive device flow authorization.

        Args:
            client_id: Twitch client ID.
            client_secret: Twitch client secret.

        Returns:
            Tuple of (access_token, refresh_token, expiry) on success, None otherwise.
        """
        flow = DeviceCodeFlow(client_id, client_secret)
        try:
            device_data = await flow.request_device_code()
            if not device_data:
                return None, None, None
            code = device_data["user_code"]
            verify_url = device_data["verification_uri"]
            expires_in = device_data["expires_in"]
            logging.info(f"Visit {verify_url} and enter code {code}")
            token_data = await flow.poll_for_tokens(
                device_data["device_code"], expires_in
            )
            if not token_data:
                return None, None, None
            access = token_data.get("access_token")
            refresh = token_data.get("refresh_token")
            lifetime = token_data.get("expires_in")
            expiry = None
            if lifetime:
                # Apply safety buffer to expiry
                safe = max(lifetime - TOKEN_REFRESH_SAFETY_BUFFER_SECONDS, 0)
                expiry = datetime.now(UTC) + timedelta(seconds=safe)
            logging.info(f"Authorized (token lifetime {format_duration(lifetime)})")
            return access, refresh, expiry
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            logging.error(f"💥 Device authorization error: {str(e)}")
            return None, None, None
