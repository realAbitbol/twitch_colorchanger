"""
Token service for unified token validation and refresh logic
"""

from datetime import datetime, timedelta
from enum import Enum

import aiohttp

from .colors import BColors
from .utils import print_log


class TokenStatus(Enum):
    """Status of token validation result"""

    VALID = "valid"
    REFRESHED = "refreshed"
    FAILED = "failed"


class TokenService:
    """Service for managing token validation and refresh"""

    def __init__(
        self, client_id: str, client_secret: str, http_session: aiohttp.ClientSession
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.http_session = http_session

    async def validate_and_refresh(
        self,
        access_token: str,
        refresh_token: str,
        username: str,
        token_expiry: datetime | None = None,
        force_refresh: bool = False,
    ) -> tuple[TokenStatus, str | None, str | None, datetime | None]:
        """
        Validate and refresh token if needed

        Returns:
            (status, new_access_token, new_refresh_token, new_expiry)
        """
        if not force_refresh and self._is_token_still_valid(token_expiry):
            return TokenStatus.VALID, access_token, refresh_token, token_expiry

        # Validate current token first
        if not force_refresh:
            is_valid = await self._validate_token(access_token, username)
            if is_valid:
                # Token is valid, keep the original expiry time
                return TokenStatus.VALID, access_token, refresh_token, token_expiry

        # Token is invalid or refresh is forced, try to refresh
        print_log(f"🔄 {username}: Token needs refresh", BColors.OKCYAN)

        new_access_token, new_refresh_token, expires_in = await self._refresh_token(
            refresh_token, username
        )

        if new_access_token:
            # Calculate expiry time with buffer
            new_expiry = (
                datetime.now() + timedelta(seconds=expires_in - 300)
                if expires_in
                else None
            )
            print_log(f"✅ {username}: Token refreshed successfully", BColors.OKGREEN)
            return (
                TokenStatus.REFRESHED,
                new_access_token,
                new_refresh_token,
                new_expiry,
            )

        print_log(f"❌ {username}: Token refresh failed", BColors.FAIL)
        return TokenStatus.FAILED, None, None, None

    def _is_token_still_valid(self, token_expiry: datetime | None) -> bool:
        """Check if token is still valid and has more than 1 hour remaining"""
        if not token_expiry:
            return False

        now = datetime.now()
        time_until_expiry = (token_expiry - now).total_seconds()

        # Token should be refreshed if it expires in less than 1 hour (3600 seconds)
        return time_until_expiry > 3600

    async def _validate_token(self, access_token: str, username: str) -> bool:
        """Validate token by making a test API call"""
        try:
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Client-Id": self.client_id,
            }

            url = "https://id.twitch.tv/oauth2/validate"

            async with self.http_session.get(url, headers=headers) as response:
                if response.status == 200:
                    return True

                print_log(
                    f"⚠️ {username}: Token validation failed with status "
                    f"{response.status}",
                    BColors.WARNING,
                )
                return False

        except Exception as e:
            print_log(f"❌ {username}: Token validation error: {e}", BColors.FAIL)
            return False

    async def _refresh_token(
        self, refresh_token: str, username: str
    ) -> tuple[str | None, str | None, int | None]:
        """Refresh the access token using refresh token"""
        try:
            data = {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            }

            url = "https://id.twitch.tv/oauth2/token"

            async with self.http_session.post(url, data=data) as response:
                if response.status == 200:
                    response_data = await response.json()
                    new_access_token = response_data.get("access_token")
                    new_refresh_token = response_data.get(
                        "refresh_token", refresh_token
                    )
                    expires_in = response_data.get("expires_in")

                    return new_access_token, new_refresh_token, expires_in

                error_text = await response.text()
                print_log(
                    f"❌ {username}: Token refresh failed: {response.status} - "
                    f"{error_text}",
                    BColors.FAIL,
                )
                return None, None, None

        except Exception as e:
            print_log(f"❌ {username}: Token refresh error: {e}", BColors.FAIL)
            return None, None, None

    def next_check_delay(self, token_expiry: datetime | None) -> float:
        """Calculate the next token check delay in seconds with smart timing"""
        if not token_expiry:
            return 300  # Default 5 minutes if no expiry info

        now = datetime.now()
        time_until_expiry = (token_expiry - now).total_seconds()

        # If token is already expired or expires very soon, check immediately
        if time_until_expiry <= 60:  # Less than 1 minute
            return 10  # Check in 10 seconds

        # Smart adaptive timing based on remaining time:
        if time_until_expiry <= 300:  # Less than 5 minutes
            # Check every minute when close to expiry
            return 60
        elif time_until_expiry <= 900:  # Less than 15 minutes
            # Check every 2 minutes when moderately close
            return 120
        elif time_until_expiry <= 1800:  # Less than 30 minutes
            # Check every 5 minutes
            return 300
        elif time_until_expiry <= 3600:  # Less than 1 hour
            # Check every 10 minutes
            return 600
        else:
            # For tokens with >1 hour remaining, check 15 minutes before expiry
            # but with a maximum interval of 30 minutes
            check_time = token_expiry - timedelta(minutes=15)
            delay = (check_time - now).total_seconds()

            # Ensure reasonable bounds: min 10 minutes, max 30 minutes
            return max(600, min(delay, 1800))
