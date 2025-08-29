"""
Device Code Flow implementation for automatic token generation
"""

import asyncio
import aiohttp
import time
from typing import Dict, Optional, Tuple

from .colors import bcolors
from .utils import print_log


class DeviceCodeFlow:
    """Handles OAuth Device Authorization Grant flow for automatic token generation"""
    
    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.device_code_url = "https://id.twitch.tv/oauth2/device"
        self.token_url = "https://id.twitch.tv/oauth2/token"
        self.poll_interval = 5  # seconds
        
    async def request_device_code(self) -> Optional[Dict]:
        """Request a device code from Twitch"""
        data = {
            "client_id": self.client_id,
            "scopes": "chat:read user:manage:chat_color"
        }
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(self.device_code_url, data=data) as response:
                    if response.status == 200:
                        result = await response.json()
                        print_log("✅ Device code generated successfully", bcolors.OKGREEN)
                        return result
                    else:
                        error_data = await response.json()
                        print_log(f"❌ Failed to get device code: {error_data}", bcolors.FAIL)
                        return None
                        
            except Exception as e:
                print_log(f"❌ Error requesting device code: {e}", bcolors.FAIL)
                return None
    
    async def poll_for_tokens(self, device_code: str, expires_in: int) -> Optional[Dict]:
        """Poll for token authorization completion"""
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "device_code": device_code,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code"
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
                            print_log("✅ Authorization successful! Tokens received.", bcolors.OKGREEN)
                            return result
                            
                        elif response.status == 400:
                            error_result = self._handle_polling_error(result, elapsed, poll_count)
                            if error_result is not None:
                                return error_result
                        else:
                            print_log(f"❌ Unexpected response: {response.status} - {result}", bcolors.FAIL)
                            return None
                            
                except Exception as e:
                    print_log(f"❌ Error during polling: {e}", bcolors.FAIL)
                    return None
                
                # Wait before next poll
                await asyncio.sleep(self.poll_interval)
        
        print_log(f"❌ Device code flow timed out after {expires_in}s", bcolors.FAIL)
        return None
    
    def _handle_polling_error(self, result: Dict, elapsed: int, poll_count: int) -> Optional[Dict]:
        """Handle polling errors and return None to continue, or a value to return"""
        # Twitch API returns errors in 'message' field, not 'error'
        error = result.get("message", result.get("error", "unknown"))
        error_description = result.get("error_description", "")
        
        # Log the full error details for debugging (only for non-pending errors)
        if error != "authorization_pending":
            print_log(f"🔍 Device flow error details: {result}", bcolors.WARNING, debug_only=True)
        
        if error == "authorization_pending":
            # Still waiting for user authorization
            if poll_count % 6 == 0:  # Show message every 30 seconds
                print_log(f"⏳ Still waiting for authorization... ({elapsed}s elapsed)", bcolors.OKCYAN)
            return None  # Continue polling
                
        elif error == "slow_down":
            # Increase polling interval
            self.poll_interval = min(self.poll_interval + 1, 10)
            print_log(f"⚠️ Slowing down polling to {self.poll_interval}s", bcolors.WARNING)
            return None  # Continue polling
            
        elif error == "expired_token":
            print_log(f"❌ Device code expired after {elapsed}s", bcolors.FAIL)
            return {}  # Stop polling
            
        elif error == "access_denied":
            print_log("❌ User denied authorization", bcolors.FAIL)
            return {}  # Stop polling
            
        else:
            if error_description:
                print_log(f"❌ Device flow error: {error} - {error_description}", bcolors.FAIL)
            else:
                print_log(f"❌ Unknown device flow error: {error}", bcolors.FAIL)
            return {}  # Stop polling
    
    async def get_user_tokens(self, username: str) -> Optional[Tuple[str, str]]:
        """
        Complete device code flow to get user tokens
        Returns (access_token, refresh_token) on success, None on failure
        """
        print_log(f"\n🔧 Starting automatic token setup for user: {username}", bcolors.HEADER)
        print_log("📱 You will need to authorize this bot on Twitch", bcolors.OKCYAN)
        
        # Step 1: Request device code
        device_data = await self.request_device_code()
        if not device_data:
            return None
        
        device_code = device_data["device_code"]
        user_code = device_data["user_code"]
        verification_uri = device_data["verification_uri"]
        expires_in = device_data["expires_in"]
        
        # Step 2: Display instructions to user
        print_log("\n" + "="*60, bcolors.PURPLE)
        print_log(f"🎯 AUTHORIZATION REQUIRED FOR: {username.upper()}", bcolors.PURPLE)
        print_log("="*60, bcolors.PURPLE)
        print_log(f"📱 Visit: {verification_uri}", bcolors.OKGREEN)
        print_log(f"🔑 Enter code: {user_code}", bcolors.OKGREEN)
        print_log(f"⏰ Code expires in: {expires_in // 60} minutes", bcolors.WARNING)
        print_log("="*60, bcolors.PURPLE)
        print_log(f"⏳ Waiting for authorization... (checking every {self.poll_interval}s)", bcolors.OKCYAN)
        
        # Step 3: Poll for authorization
        token_data = await self.poll_for_tokens(device_code, expires_in)
        if not token_data:
            return None
        
        access_token = token_data["access_token"]
        refresh_token = token_data.get("refresh_token", "")
        
        print_log(f"🎉 Successfully obtained tokens for {username}!", bcolors.OKGREEN)
        return access_token, refresh_token
