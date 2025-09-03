"""Token provisioning orchestration (validation, refresh, device flow fetch).

Provides a single entrypoint to ensure a user's tokens are usable. Returns a
structured ProvisionResult describing what happened. Supports a dry_run mode
that performs validation but does not mutate tokens or invoke the device flow.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto
from typing import Any

import aiohttp

from .device_flow import DeviceCodeFlow
from .logger import logger
from .token_client import TokenClient, TokenOutcome


class ProvisionStatus(Enum):
    VALID = auto()  # Token already valid (no changes)
    REFRESHED = auto()  # Token refreshed successfully
    NEW_OBTAINED = auto()  # New tokens acquired via device flow
    MISSING_CREDENTIALS = auto()  # Missing client id/secret
    NEEDS_DEVICE_FLOW = auto()  # Needs device flow (dry-run skip)
    FAILED = auto()  # Attempt failed


@dataclass
class ProvisionResult:
    user: dict[str, Any]
    updated: bool
    status: ProvisionStatus
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "updated": self.updated,
            "status": self.status.name,
            "error": self.error,
            "username": self.user.get("username"),
        }


class TokenProvisioner:
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run

    async def provision(self, user: dict[str, Any]) -> ProvisionResult:
        """Ensure tokens for a single user are valid, refreshing or creating if needed."""
        username = user.get("username", "Unknown")
        client_id = user.get("client_id")
        client_secret = user.get("client_secret")

        logger.log_event(
            "token_provision",
            "start",
            username=username,
            dry_run=self.dry_run,
        )

        if not client_id or not client_secret:
            logger.log_event(
                "token_provision",
                "missing_credentials",
                level=30,
                username=username,
            )
            return ProvisionResult(user, False, ProvisionStatus.MISSING_CREDENTIALS)

        # If access token present attempt validation/refresh
        access_token = user.get("access_token")
        refresh_token = user.get("refresh_token")

        if access_token:
            result = await self._validate_or_refresh(
                user, username, client_id, client_secret, access_token, refresh_token
            )
            if result is not None:
                return result

        # Need device flow (no access token or validation failed path requested new tokens)
        if self.dry_run:
            logger.log_event(
                "token_provision",
                "dry_run_device_flow_needed",
                username=username,
            )
            return ProvisionResult(user, False, ProvisionStatus.NEEDS_DEVICE_FLOW)
        return await self._device_flow_acquire(user, username, client_id, client_secret)

    async def _validate_or_refresh(
        self,
        user: dict[str, Any],
        username: str,
        client_id: str,
        client_secret: str,
        access_token: str,
        refresh_token: str | None,
    ) -> ProvisionResult | None:
        try:
            async with aiohttp.ClientSession() as session:
                client = TokenClient(client_id, client_secret, session)
                outcome_obj = await client.ensure_fresh(
                    username,
                    access_token,
                    refresh_token,
                    None,
                    force_refresh=False,
                )
        except Exception as e:  # noqa: BLE001
            logger.log_event(
                "token_provision",
                "validate_exception",
                level=40,
                username=username,
                error=str(e),
                error_type=type(e).__name__,
            )
            return ProvisionResult(user, False, ProvisionStatus.FAILED, error=str(e))

        if outcome_obj.outcome == TokenOutcome.VALID:
            # Emit remaining lifetime for observability
            if outcome_obj.expiry:
                remaining = int((outcome_obj.expiry - datetime.now()).total_seconds())
                logger.log_event(
                    "token_provision",
                    "valid",
                    username=username,
                    expires_in_seconds=remaining,
                )
            return ProvisionResult(user, False, ProvisionStatus.VALID)
        if outcome_obj.outcome == TokenOutcome.REFRESHED:
            if self.dry_run:
                logger.log_event(
                    "token_provision",
                    "dry_run_refresh_skipped",
                    username=username,
                )
                return ProvisionResult(user, False, ProvisionStatus.REFRESHED)
            if outcome_obj.access_token:
                user["access_token"] = outcome_obj.access_token
            if outcome_obj.refresh_token:
                user["refresh_token"] = outcome_obj.refresh_token
            logger.log_event(
                "token_provision",
                "refreshed",
                username=username,
            )
            return ProvisionResult(user, True, ProvisionStatus.REFRESHED)
        # Any other outcome requires new tokens (return None to trigger device flow)
        logger.log_event(
            "token_provision",
            "needs_device_flow",
            username=username,
        )
        return None

    async def _device_flow_acquire(
        self,
        user: dict[str, Any],
        username: str,
        client_id: str,
        client_secret: str,
    ) -> ProvisionResult:
        logger.log_event(
            "token_provision",
            "device_flow_start",
            username=username,
        )
        device_flow = DeviceCodeFlow(client_id, client_secret)
        try:
            token_result = await device_flow.get_user_tokens(username)
            if not token_result:
                logger.log_event(
                    "token_provision",
                    "device_flow_failed",
                    level=40,
                    username=username,
                )
                return ProvisionResult(user, False, ProvisionStatus.FAILED)
            access, refresh = token_result
            user["access_token"] = access
            user["refresh_token"] = refresh
            logger.log_event(
                "token_provision",
                "device_flow_obtained",
                username=username,
            )
            return ProvisionResult(user, True, ProvisionStatus.NEW_OBTAINED)
        except Exception as e:  # noqa: BLE001
            logger.log_event(
                "token_provision",
                "device_flow_exception",
                level=40,
                username=username,
                error=str(e),
                error_type=type(e).__name__,
            )
            return ProvisionResult(user, False, ProvisionStatus.FAILED, error=str(e))
