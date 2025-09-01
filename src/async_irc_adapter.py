"""
Async IRC adapter - Sync-compatible interface for the async IRC client
"""

import asyncio
import threading
import time
from typing import Optional, Callable

from .async_irc import AsyncTwitchIRC
from .colors import BColors
from .constants import (
    ASYNC_IRC_CONNECT_TIMEOUT,
    ASYNC_IRC_JOIN_TIMEOUT,
    ASYNC_IRC_RECONNECT_TIMEOUT,
)
from .utils import print_log


class AsyncIRCAdapter:
    """
    Adapter that wraps AsyncTwitchIRC to provide a synchronous interface
    while using async operations internally for improved responsiveness
    """

    def __init__(self):
        self.async_irc = AsyncTwitchIRC()
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.thread: Optional[threading.Thread] = None
        self.running = False
        
        # Forward properties
        self.username = None
        self.token = None
        self.channels = []
        self.connected = False
        self.joined_channels = set()
        self.confirmed_channels = set()
        
        # Health monitoring properties  
        self.last_server_activity = 0
        self.last_ping_from_server = 0
        self.server_activity_timeout = 300
        self.expected_ping_interval = 600
        
        # Exponential backoff properties
        self.consecutive_failures = 0
        self.last_reconnect_attempt = 0

    def connect(self, token: str, username: str, channel: str) -> bool:
        """Connect to Twitch IRC - synchronous interface to async implementation"""
        if self.running:
            self.disconnect()
        
        # Start the async event loop in a separate thread
        self._start_async_loop()
        
        # Run async connect and wait for result
        try:
            if not self.loop:
                raise RuntimeError("Event loop not started")
                
            future = asyncio.run_coroutine_threadsafe(
                self.async_irc.connect(token, username, channel),
                self.loop
            )
            success = future.result(timeout=ASYNC_IRC_CONNECT_TIMEOUT)
            
            if success:
                # Sync properties
                self._sync_properties()
                self.running = True
                
                # Start the async listening loop
                asyncio.run_coroutine_threadsafe(
                    self.async_irc.listen(),
                    self.loop
                )
                
            return success
            
        except asyncio.TimeoutError:
            print_log(f"❌ Adapter connect timeout after {ASYNC_IRC_CONNECT_TIMEOUT}s", BColors.FAIL)
            return False
        except Exception as e:
            print_log(f"❌ Adapter connect error: {type(e).__name__}: {e}", BColors.FAIL)
            import traceback
            print_log(f"❌ Full traceback: {traceback.format_exc()}", BColors.FAIL)
            return False

    def _start_async_loop(self):
        """Start the asyncio event loop in a separate thread"""
        if self.thread and self.thread.is_alive():
            return
            
        def run_loop():
            try:
                self.loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self.loop)
                print_log("🔄 Started async event loop", BColors.OKCYAN)
                self.loop.run_forever()
            except Exception as e:
                print_log(f"❌ Event loop error: {e}", BColors.FAIL)
            finally:
                try:
                    self.loop.close()
                except Exception as e:
                    print_log(f"❌ Event loop close error: {e}", BColors.FAIL)
                self.loop = None
        
        self.thread = threading.Thread(target=run_loop, daemon=True, name="AsyncIRC-EventLoop")
        self.thread.start()
        
        # Wait for loop to be ready with better error handling
        timeout = 5.0
        start_time = time.time()
        while self.loop is None and time.time() - start_time < timeout:
            time.sleep(0.01)
            
        if self.loop is None:
            raise RuntimeError("Failed to start async event loop within 5 seconds")
            
        # Additional check that the loop is actually running
        if self.loop.is_closed():
            raise RuntimeError("Event loop started but is already closed")
            
        print_log("✅ Async event loop ready", BColors.OKGREEN)

    def _sync_properties(self):
        """Sync properties from async IRC to adapter"""
        self.username = self.async_irc.username
        self.token = self.async_irc.token
        self.channels = self.async_irc.channels.copy()
        self.connected = self.async_irc.connected
        self.joined_channels = self.async_irc.joined_channels.copy()
        self.confirmed_channels = self.async_irc.confirmed_channels.copy()
        
        # Health monitoring
        self.last_server_activity = self.async_irc.last_server_activity
        self.last_ping_from_server = self.async_irc.last_ping_from_server
        
        # Backoff tracking
        self.consecutive_failures = self.async_irc.consecutive_failures
        self.last_reconnect_attempt = self.async_irc.last_reconnect_attempt

    def join_channel(self, channel: str) -> bool:
        """Join a channel - synchronous interface"""
        if not self.loop:
            return False
            
        try:
            future = asyncio.run_coroutine_threadsafe(
                self.async_irc.join_channel(channel),
                self.loop
            )
            success = future.result(timeout=ASYNC_IRC_JOIN_TIMEOUT)
            
            if success:
                self._sync_properties()
                
            return success
            
        except Exception as e:
            print_log(f"❌ Join channel error: {e}", BColors.FAIL)
            return False

    def disconnect(self):
        """Disconnect from IRC"""
        if self.loop:
            try:
                # Stop the async IRC
                future = asyncio.run_coroutine_threadsafe(
                    self.async_irc.disconnect(),
                    self.loop
                )
                future.result(timeout=5.0)
            except Exception as e:
                print_log(f"❌ Disconnect error: {e}", BColors.FAIL)
            
            # Stop the event loop
            try:
                self.loop.call_soon_threadsafe(self.loop.stop)
            except Exception:
                pass
                
        # Wait for thread to finish
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)
            
        # Reset state
        self.running = False
        self.connected = False
        self.loop = None
        self.thread = None
        
        # Clear collections
        self.joined_channels.clear()
        self.confirmed_channels.clear()
        self.channels.clear()
        
        print_log("📡 Async IRC adapter disconnected", BColors.WARNING)

    def force_reconnect(self) -> bool:
        """Force reconnection - synchronous interface"""
        if not self.loop:
            return False
            
        try:
            future = asyncio.run_coroutine_threadsafe(
                self.async_irc.force_reconnect(),
                self.loop
            )
            success = future.result(timeout=ASYNC_IRC_RECONNECT_TIMEOUT)
            
            if success:
                self._sync_properties()
                
            return success
            
        except Exception as e:
            print_log(f"❌ Force reconnect error: {e}", BColors.FAIL)
            return False

    def set_message_handler(self, handler: Callable[[str, str, str], None]):
        """Set message handler callback"""
        self.async_irc.set_message_handler(handler)

    def set_color_change_handler(self, handler: Callable[[str, str, str], None]):
        """Set color change handler callback"""
        self.async_irc.set_color_change_handler(handler)

    def is_healthy(self) -> bool:
        """Check if the IRC connection is healthy"""
        if not self.connected:
            return False
            
        self._sync_properties()
        
        current_time = time.time()
        
        # Check for recent server activity
        if current_time - self.last_server_activity > self.server_activity_timeout:
            return False
            
        # Check ping timeout (if we've received pings)
        if (self.last_ping_from_server > 0 and 
            current_time - self.last_ping_from_server > self.expected_ping_interval * 1.5):
            return False
            
        return True

    def get_status(self) -> dict:
        """Get detailed status information"""
        self._sync_properties()
        
        current_time = time.time()
        
        return {
            "connected": self.connected,
            "running": self.running,
            "username": self.username,
            "channels": len(self.channels),
            "confirmed_channels": len(self.confirmed_channels),
            "last_activity_ago": current_time - self.last_server_activity,
            "last_ping_ago": current_time - self.last_ping_from_server if self.last_ping_from_server > 0 else None,
            "consecutive_failures": self.consecutive_failures,
            "adapter_type": "async",
            "loop_running": self.loop is not None and not self.loop.is_closed() if self.loop else False,
        }
        
    def _calculate_backoff_delay(self) -> float:
        """Calculate exponential backoff delay - delegate to async IRC"""
        return self.async_irc._calculate_backoff_delay()

    def listen(self):
        """
        Compatibility method for listen() - for async adapter, listening is already started
        This method is a no-op since the async listening loop is started in connect()
        """
        if not self.connected:
            print_log("❌ Cannot listen: not connected", BColors.FAIL)
            return
            
        print_log("ℹ️ Async IRC adapter: listen() called - already listening asynchronously", BColors.OKCYAN, debug_only=True)
        
        # Keep the calling thread alive while connected
        # This maintains compatibility with sync code that expects listen() to block
        try:
            while self.connected and self.running:
                time.sleep(1.0)
        except KeyboardInterrupt:
            print_log("🛑 Listen interrupted", BColors.WARNING)

    def get_connection_stats(self) -> dict:
        """Get connection health statistics"""
        self._sync_properties()
        
        current_time = time.time()
        return {
            "connected": self.connected,
            "running": self.running,
            "last_server_activity": self.last_server_activity,
            "time_since_activity": current_time - self.last_server_activity,
            "last_ping_from_server": self.last_ping_from_server,
            "time_since_server_ping": (
                current_time - self.last_ping_from_server
                if self.last_ping_from_server > 0
                else 0
            ),
            "consecutive_failures": self.consecutive_failures,
            "adapter_type": "async",
            "loop_running": self.loop is not None and not self.loop.is_closed() if self.loop else False,
        }
        
    # Compatibility properties for existing code
    @property
    def sock(self):
        """Compatibility property - returns None since we use async streams"""
        return None
