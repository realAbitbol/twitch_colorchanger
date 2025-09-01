"""
Standalone token validation module.

This module provides token validation functionality without depending on the bot module,
helping to avoid circular imports between config.py and bot.py.
"""

from typing import Any, Dict, Optional

import httpx

from .logger import BColors, print_log

# Constants
VALIDATE_TOKEN_URL = "https://id.twitch.tv/oauth2/validate"


class TokenValidator:
    """Standalone token validator for Twitch API tokens."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        access_token: str,
        refresh_token: Optional[str] = None,
    ):
        """Initialize token validator."""
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token = access_token
        self.refresh_token = refresh_token
        self._token_expiry_threshold_hours = (
            1  # Only refresh if less than 1 hour remaining
        )

    async def validate_token(self) -> tuple[bool, int]:
        """Validate token via Twitch API. Returns (is_valid, expires_in_seconds)."""
        try:
            validation_data = await self._call_validate_api()
            if validation_data is None:
                return await self._handle_invalid_token()

            expires_in = validation_data.get("expires_in", 0)
            if expires_in < (self._token_expiry_threshold_hours * 3600):
                return await self._handle_expiring_token()

            return True, expires_in

        except Exception as e:
            print_log(
                f"❌ Token validation failed: {e}",
                BColors.FAIL,
                debug_only=True,
            )
            return False, 0

    async def _call_validate_api(self) -> Optional[Dict[str, Any]]:
        """
        Call the Twitch validation API and return the response data
        or None if invalid.
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                VALIDATE_TOKEN_URL,
                headers={"Authorization": f"OAuth {self.access_token}"},
                timeout=10.0,
            )
            if response.status_code == 200:
                return response.json()
            return None

    async def _handle_invalid_token(self) -> tuple[bool, int]:
        """Handle invalid token by attempting refresh."""
        if self.refresh_token:
            refreshed = await self._refresh_token()
            if refreshed:
                return await self._validate_refreshed_token()
        return False, 0

    async def _handle_expiring_token(self) -> tuple[bool, int]:
        """Handle token that expires soon by attempting refresh."""
        if self.refresh_token:
            refreshed = await self._refresh_token()
            if refreshed:
                return await self._validate_refreshed_token()
            return False, 0
        return True, 0  # No refresh token, but current token is still valid

    async def _validate_refreshed_token(self) -> tuple[bool, int]:
        """Validate the token after it has been refreshed."""
        validation_data = await self._call_validate_api()
        if validation_data is not None:
            expires_in = validation_data.get("expires_in", 0)
            return True, expires_in
        return False, 0

    async def _refresh_token(self) -> bool:
        """Refresh access token using refresh token."""
        if not self.refresh_token:
            return False

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://id.twitch.tv/oauth2/token",
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": self.refresh_token,
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    timeout=10.0,
                )

                if response.status_code == 200:
                    data = response.json()
                    self.access_token = data["access_token"]
                    self.refresh_token = data.get("refresh_token", self.refresh_token)
                    print_log(
                        "🔄 Token refreshed successfully",
                        BColors.OKGREEN,
                        debug_only=True,
                    )
                    return True
                print_log(
                    f"❌ Token refresh failed: {response.status_code}",
                    BColors.FAIL,
                    debug_only=True,
                )
                return False

        except Exception as e:
            print_log(
                f"❌ Token refresh error: {e}",
                BColors.FAIL,
                debug_only=True,
            )
            return False

    async def check_and_refresh_token(self, force: bool = False) -> tuple[bool, int]:
        """
        Check token validity and refresh if needed.
        Returns (is_valid, expires_in_seconds).
        """
        if force:
            if self.refresh_token:
                refreshed = await self._refresh_token()
                if refreshed:
                    return await self.validate_token()
                return False, 0
            return await self.validate_token()
        return await self.validate_token()


async def validate_user_tokens(user: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate and refresh user tokens.

    Args:
        user: User configuration dictionary

    Returns:
        Dictionary with validation results
    """
    username = user.get("username", "Unknown")
    access_token = user.get("access_token")
    refresh_token = user.get("refresh_token")
    client_id = user.get("client_id")
    client_secret = user.get("client_secret")

    if not access_token:
        print_log(
            f"🔑 {username}: No access token found", BColors.WARNING, debug_only=True
        )
        return {"valid": False, "user": user, "updated": False}

    if not client_id or not client_secret:
        print_log(
            f"🔑 {username}: Missing client credentials",
            BColors.WARNING,
            debug_only=True,
        )
        return {"valid": False, "user": user, "updated": False}

    try:
        validator = TokenValidator(
            client_id=str(client_id),
            client_secret=str(client_secret),
            access_token=str(access_token),
            refresh_token=str(refresh_token) if refresh_token else None,
        )

        # Validate and potentially refresh token
        token_valid, expires_in = await validator.check_and_refresh_token(force=False)

        if token_valid:
            updated = (
                validator.access_token != access_token
                or validator.refresh_token != refresh_token
            )

            if updated:
                # Update user config with refreshed tokens
                user["access_token"] = validator.access_token
                user["refresh_token"] = validator.refresh_token
                print_log(
                    f"🔄 {username}: Token was refreshed during validation",
                    BColors.OKGREEN,
                    debug_only=True,
                )
            else:
                # Token was valid without refresh, show remaining duration
                hours = expires_in // 3600
                minutes = (expires_in % 3600) // 60
                if hours > 0:
                    duration_str = f"{hours}h {minutes}m"
                else:
                    duration_str = f"{minutes}m"
                print_log(
                    f"✅ {username}: Token is valid (expires in {duration_str})",
                    BColors.OKGREEN,
                )

            return {"valid": True, "user": user, "updated": updated}
        print_log(
            f"❌ {username}: Token validation failed", BColors.FAIL, debug_only=True
        )
        return {"valid": False, "user": user, "updated": False}

    except Exception as e:
        print_log(
            f"❌ {username}: Token validation error: {e}",
            BColors.FAIL,
            debug_only=True,
        )
        return {"valid": False, "user": user, "updated": False}


async def validate_new_tokens(user: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate newly obtained tokens.

    Args:
        user: User configuration dictionary with new tokens

    Returns:
        Dictionary with validation results
    """
    username = user.get("username", "Unknown")

    required_keys = ["client_id", "client_secret", "access_token", "refresh_token"]
    for key in required_keys:
        if key not in user:
            print_log(
                f"❌ New tokens validation error for {username}: Missing {key}",
                BColors.FAIL,
                debug_only=True,
            )
            return {"valid": False, "user": user}

    try:
        validator = TokenValidator(
            client_id=str(user["client_id"]),
            client_secret=str(user["client_secret"]),
            access_token=str(user["access_token"]),
            refresh_token=str(user["refresh_token"]),
        )

        # Validate the new tokens (returns tuple)
        token_valid, _ = await validator.validate_token()

        if token_valid:
            # Update user with any refreshed token information
            user["access_token"] = validator.access_token
            user["refresh_token"] = validator.refresh_token
            print_log(
                f"✅ New tokens for {username} validated successfully",
                BColors.OKGREEN,
                debug_only=True,
            )
            return {"valid": True, "user": user}

        print_log(
            f"⚠️ New tokens for {username} validation failed",
            BColors.WARNING,
            debug_only=True,
        )
        return {"valid": False, "user": user}

    except Exception as e:
        print_log(
            f"❌ New tokens validation error for {username}: {e}",
            BColors.FAIL,
            debug_only=True,
        )
        return {"valid": False, "user": user}
