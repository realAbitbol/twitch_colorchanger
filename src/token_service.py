"""
Token service for unified token validation and refresh logic
"""

import json
import time
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, Tuple

import aiohttp

from .logger import logger
from .utils import print_log
from .colors import BColors


class TokenStatus(Enum):
    """Status of token validation result"""
    VALID = "valid"
    REFRESHED = "refreshed"
    FAILED = "failed"


class TokenService:
    """Service for managing token validation and refresh"""

    def __init__(self, client_id: str, client_secret: str, http_session: aiohttp.ClientSession):
        self.client_id = client_id
        self.client_secret = client_secret
        self.http_session = http_session

    async def validate_and_refresh(
        self, 
        access_token: str, 
        refresh_token: str, 
        username: str,
        token_expiry: Optional[datetime] = None,
        force_refresh: bool = False
    ) -> Tuple[TokenStatus, Optional[str], Optional[str], Optional[datetime]]:
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
                # Token is valid, calculate next expiry check
                new_expiry = datetime.now() + timedelta(minutes=30)
                return TokenStatus.VALID, access_token, refresh_token, new_expiry

        # Token is invalid or refresh is forced, try to refresh
        print_log(f"🔄 {username}: Token needs refresh", BColors.OKCYAN)
        
        new_access_token, new_refresh_token, expires_in = await self._refresh_token(
            refresh_token, username
        )
        
        if new_access_token:
            # Calculate expiry time with buffer
            new_expiry = datetime.now() + timedelta(seconds=expires_in - 300) if expires_in else None
            print_log(f"✅ {username}: Token refreshed successfully", BColors.OKGREEN)
            return TokenStatus.REFRESHED, new_access_token, new_refresh_token, new_expiry
        else:
            print_log(f"❌ {username}: Token refresh failed", BColors.FAIL)
            return TokenStatus.FAILED, None, None, None

    def _is_token_still_valid(self, token_expiry: Optional[datetime]) -> bool:
        """Check if token is still valid based on expiry time"""
        if not token_expiry:
            return False
        return datetime.now() < token_expiry

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
                else:
                    print_log(
                        f"⚠️ {username}: Token validation failed with status {response.status}",
                        BColors.WARNING
                    )
                    return False
                    
        except Exception as e:
            print_log(f"❌ {username}: Token validation error: {e}", BColors.FAIL)
            return False

    async def _refresh_token(
        self, refresh_token: str, username: str
    ) -> Tuple[Optional[str], Optional[str], Optional[int]]:
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
                    new_refresh_token = response_data.get("refresh_token", refresh_token)
                    expires_in = response_data.get("expires_in")
                    
                    return new_access_token, new_refresh_token, expires_in
                else:
                    error_text = await response.text()
                    print_log(
                        f"❌ {username}: Token refresh failed: {response.status} - {error_text}",
                        BColors.FAIL
                    )
                    return None, None, None
                    
        except Exception as e:
            print_log(f"❌ {username}: Token refresh error: {e}", BColors.FAIL)
            return None, None, None

    def next_check_delay(self, token_expiry: Optional[datetime]) -> float:
        """Calculate the next token check delay in seconds"""
        if not token_expiry:
            return 300  # Default 5 minutes if no expiry info
            
        # Check again 5 minutes before expiry
        check_time = token_expiry - timedelta(minutes=5)
        delay = (check_time - datetime.now()).total_seconds()
        
        # Ensure minimum 1 minute delay and maximum 1 hour
        return max(60, min(delay, 3600))
