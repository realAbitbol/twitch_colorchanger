"""
HTTP connection pooling and session management for the Twitch Color Changer bot
"""

import asyncio
import aiohttp
import time
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass
from contextlib import asynccontextmanager

from .logger import logger
from .error_handling import NetworkError, APIError, ErrorCategory, ErrorSeverity

# Constants
APPLICATION_JSON = 'application/json'


@dataclass
class SessionConfig:
    """Configuration for HTTP sessions"""
    timeout_total: int = 30
    timeout_connect: int = 10
    timeout_sock_read: int = 10
    max_connections: int = 100
    max_connections_per_host: int = 10
    keepalive_timeout: int = 30
    enable_cleanup_closed: bool = True
    headers: Optional[Dict[str, str]] = None


class ConnectionPool:
    """HTTP connection pool manager"""
    
    def __init__(self, config: Optional[SessionConfig] = None):
        self.config = config or SessionConfig()
        self._session: Optional[aiohttp.ClientSession] = None
        self._session_created_at: Optional[float] = None
        self._lock = asyncio.Lock()
        self._session_lifetime = 3600  # 1 hour
        self._request_count = 0
        self._cleanup_interval = 300  # 5 minutes
        self._last_cleanup = time.time()
        self._loop = None  # Track which event loop the session belongs to
    
    async def get_session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session with connection pooling"""
        async with self._lock:
            now = time.time()
            current_loop = asyncio.get_running_loop()
            
            # Periodic cleanup
            if now - self._last_cleanup > self._cleanup_interval:
                await self._cleanup_session()
                self._last_cleanup = now
            
            # Check if we need a new session (including loop change)
            if self._should_create_new_session(now, current_loop):
                await self._create_new_session()
                self._loop = current_loop
            
            return self._session
    
    def _should_create_new_session(self, now: float, current_loop) -> bool:
        """Determine if a new session should be created"""
        if self._session is None:
            return True
        
        if self._session.closed:
            logger.debug("Session is closed, creating new session")
            return True
        
        # Check if the event loop has changed
        if self._loop is not None and self._loop != current_loop:
            logger.debug("Event loop changed, creating new session")
            return True
        
        # Check session age
        if self._session_created_at and (now - self._session_created_at) > self._session_lifetime:
            logger.debug("Session expired, creating new session")
            return True
        
        return False
    
    def _force_close_cross_loop_session(self):
        """Force close session from different event loop to prevent memory leaks"""
        try:
            if hasattr(self._session, '_connector') and self._session._connector:
                connector = self._session._connector
                # Force close all connections
                connector._close()
                # Clear connection pools
                if hasattr(connector, '_conns'):
                    connector._conns.clear()
            # Mark session as closed to prevent further use
            self._session._closed = True
        except Exception as e:
            logger.debug(f"Error during force cleanup: {e}")

    async def _close_same_loop_session(self):
        """Safely close session in same event loop"""
        try:
            await self._session.close()
        except Exception as e:
            logger.debug(f"Error closing old session: {e}")

    async def _create_new_session(self):
        """Create a new HTTP session with optimized settings"""
        # Close existing session if any - improved cleanup for memory leak prevention
        if self._session and not self._session.closed:
            try:
                current_loop = asyncio.get_running_loop()
                if self._loop is None or self._loop == current_loop:
                    # Same loop - safe to await close
                    await self._close_same_loop_session()
                else:
                    # Different loop - force cleanup to prevent memory leaks
                    logger.debug("Force-closing session from different event loop")
                    self._force_close_cross_loop_session()
            except Exception as e:
                logger.debug(f"Unexpected error during session cleanup: {e}")
            finally:
                # Always clear the session reference to prevent memory leaks
                self._session = None
        
        # Configure connector for connection pooling (no session-level timeout)
        connector = aiohttp.TCPConnector(
            limit=self.config.max_connections,
            limit_per_host=self.config.max_connections_per_host,
            keepalive_timeout=self.config.keepalive_timeout,
            enable_cleanup_closed=self.config.enable_cleanup_closed,
            # Enable connection reuse
            force_close=False,
            # Enable DNS caching
            use_dns_cache=True
        )
        
        # Create session with explicit None timeout to disable aiohttp's timeout system
        self._session = aiohttp.ClientSession(
            connector=connector,
            timeout=aiohttp.ClientTimeout(total=None),  # Disable all timeouts
            headers=self.config.headers or {}
        )
        
        self._session_created_at = time.time()
        self._request_count = 0
        
        logger.debug("Created new HTTP session with connection pooling")
    
    async def _cleanup_session(self):
        """Perform periodic session cleanup"""
        if self._session and hasattr(self._session.connector, 'close_idle_connections'):
            # Close idle connections to free resources
            await self._session.connector.close_idle_connections()
            logger.debug("Cleaned up idle connections")
    
    async def request(self, method: str, url: str, **kwargs) -> aiohttp.ClientResponse:
        """Make HTTP request with connection pooling and error handling"""
        session = await self.get_session()
        self._request_count += 1
        
        start_time = time.time()
        try:
            # Direct request without asyncio.wait_for to avoid timeout context manager issues
            response = await session.request(method, url, **kwargs)
            response_time = time.time() - start_time
            
            logger.debug(f"HTTP {method} {url} -> {response.status} ({response_time:.3f}s)",
                        api_endpoint=url, response_time=response_time, status_code=response.status)
            
            return response
        except asyncio.TimeoutError as e:
            response_time = time.time() - start_time
            logger.warning(f"HTTP {method} {url} timed out after {response_time:.3f}s",
                          api_endpoint=url, response_time=response_time)
            raise NetworkError(f"Request to {url} timed out", status_code=None)
        except aiohttp.ClientError as e:
            response_time = time.time() - start_time
            logger.error(f"HTTP {method} {url} failed: {e} ({response_time:.3f}s)",
                        api_endpoint=url, response_time=response_time)
            raise NetworkError(f"HTTP request failed: {e}", status_code=None)
        except Exception as e:
            response_time = time.time() - start_time
            logger.error(f"HTTP {method} {url} unexpected error: {e} ({response_time:.3f}s)",
                        api_endpoint=url, response_time=response_time)
            raise NetworkError(f"Unexpected error: {e}", status_code=None)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get connection pool statistics including memory leak indicators"""
        stats = {
            'session_created': self._session is not None,
            'session_closed': self._session.closed if self._session else None,
            'loop_id': id(self._loop) if self._loop else None,
            'current_loop_id': id(asyncio.get_running_loop()) if asyncio._get_running_loop() else None,
            'request_count': getattr(self, '_request_count', 0),
            'session_age': time.time() - self._session_created_at if self._session_created_at else 0,
            'session_active': self._session is not None and not self._session.closed
        }
        
        # Add connector statistics if available
        if self._session and hasattr(self._session, '_connector'):
            connector = self._session._connector
            stats.update({
                'connector_closed': connector.closed if hasattr(connector, 'closed') else None,
                'active_connections': len(connector._conns) if hasattr(connector, '_conns') else 0,
                'connection_limit': connector.limit if hasattr(connector, 'limit') else None,
            })
        
        return stats
    
    async def close(self):
        """Close the connection pool and cleanup resources"""
        if self._session and not self._session.closed:
            await self._session.close()
            logger.debug("Closed HTTP session")


class HTTPClient:
    """HTTP client with connection pooling and Twitch API integration"""
    
    def __init__(self, session_config: Optional[SessionConfig] = None):
        # Setup default headers for Twitch API
        default_headers = {
            'Accept': APPLICATION_JSON,
            'User-Agent': 'TwitchColorChanger/1.0'
        }
        
        if session_config:
            if session_config.headers:
                default_headers.update(session_config.headers)
            session_config.headers = default_headers
        else:
            session_config = SessionConfig(headers=default_headers)
        
        self.pool = ConnectionPool(session_config)
    
    async def close(self):
        """Close the HTTP client and cleanup resources"""
        await self.pool.close()
    
    @asynccontextmanager
    async def request(self, method: str, url: str, **kwargs):
        """Context manager for HTTP requests with automatic response handling"""
        response = None
        try:
            response = await self.pool.request(method, url, **kwargs)
            yield response
        finally:
            if response:
                response.close()
    
    async def get_json(self, url: str, headers: Optional[Dict[str, str]] = None, **kwargs) -> Tuple[Dict[str, Any], int]:
        """
        Make GET request and return JSON response
        
        Returns:
            Tuple of (json_data, status_code)
        """
        async with self.request('GET', url, headers=headers, **kwargs) as response:
            if response.status >= 400:
                error_text = await response.text()
                raise APIError(
                    f"API request failed: {response.status} {error_text}",
                    status_code=response.status
                )
            
            try:
                json_data = await response.json()
                return json_data, response.status
            except Exception as e:
                raise APIError(
                    f"Failed to parse JSON response: {e}",
                    status_code=response.status
                )
    
    async def twitch_api_request(self, method: str, endpoint: str, access_token: str, 
                               client_id: str, **kwargs) -> Tuple[Optional[Dict[str, Any]], int, Dict[str, str]]:
        """
        Make authenticated request to Twitch API
        
        Returns:
            Tuple of (json_data, status_code, headers)
        """
        url = f"https://api.twitch.tv/helix/{endpoint}"
        
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Client-Id': client_id,
            'Content-Type': APPLICATION_JSON
        }
        
        # Add any additional headers
        if 'headers' in kwargs:
            headers.update(kwargs['headers'])
            del kwargs['headers']
        
        async with self.request(method, url, headers=headers, **kwargs) as response:
            response_headers = dict(response.headers)
            
            if response.status >= 400:
                error_text = await response.text()
                raise APIError(
                    f"Twitch API request failed: {response.status} {error_text}",
                    status_code=response.status,
                    endpoint=endpoint
                )
            
            # Handle different response types
            json_data = None
            if response.content_length and response.content_length > 0:
                try:
                    json_data = await response.json()
                except Exception:
                    # Some endpoints return empty body or non-JSON
                    pass
            
            return json_data, response.status, response_headers
    
    def get_stats(self) -> Dict[str, Any]:
        """Get HTTP client statistics"""
        return self.pool.get_stats()


# Global HTTP client instance
_global_http_client: Optional[HTTPClient] = None


def get_http_client() -> HTTPClient:
    """Get or create the global HTTP client instance"""
    global _global_http_client
    if _global_http_client is None:
        _global_http_client = HTTPClient()
        logger.info("Created global HTTP client with connection pooling")
    return _global_http_client


async def close_http_client():
    """Close the global HTTP client and ensure all resources are cleaned up"""
    global _global_http_client
    if _global_http_client is not None:
        try:
            logger.debug("Closing global HTTP client")
            await _global_http_client.close()
        except Exception as e:
            logger.debug(f"Error closing global HTTP client: {e}")
        finally:
            # Always clear the global reference to prevent memory leaks
            _global_http_client = None
            logger.debug("Global HTTP client reference cleared")


async def cleanup_http_resources():
    """Legacy function for backward compatibility"""
    await close_http_client()
