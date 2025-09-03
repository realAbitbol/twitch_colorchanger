"""Token provisioning helpers (moved from token_provisioner.py)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

import aiohttp

from constants import TOKEN_REFRESH_SAFETY_BUFFER_SECONDS
from logs.logger import logger
from utils import format_duration

from .device_flow import DeviceCodeFlow


class TokenProvisioner:
    def __init__(self, session: aiohttp.ClientSession):
        self.session = session

    async def provision(
        self,
        username: str,
        client_id: str,
        client_secret: str,
        access_token: str | None,
        refresh_token: str | None,
        expiry: datetime | None,
    ) -> tuple[str | None, str | None, datetime | None]:
        if access_token and refresh_token:
            return access_token, refresh_token, expiry
        return await self._interactive_authorize(username, client_id, client_secret)

    async def _interactive_authorize(
        self, username: str, client_id: str, client_secret: str
    ) -> tuple[str | None, str | None, datetime | None]:
        flow = DeviceCodeFlow(client_id, client_secret)
        try:
            device_data = await flow.request_device_code()
            if not device_data:
                return None, None, None
            code = device_data["user_code"]
            verify_url = device_data["verification_uri"]
            expires_in = device_data["expires_in"]
            logger.log_event(
                "token",
                "device_code_obtained",
                user=username,
                expires_in=expires_in,
                human=f"Visit {verify_url} and enter code {code}",
            )
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
                safe = max(lifetime - TOKEN_REFRESH_SAFETY_BUFFER_SECONDS, 0)
                expiry = datetime.now() + timedelta(seconds=safe)
            logger.log_event(
                "token",
                "device_authorized",
                user=username,
                expires_in=lifetime,
                human=f"Authorized (token lifetime {format_duration(lifetime)})",
            )
            return access, refresh, expiry
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.log_event(
                "token", "device_authorize_error", level=logging.ERROR, error=str(e)
            )
            return None, None, None
