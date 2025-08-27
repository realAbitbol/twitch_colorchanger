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
    
    async def get_session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session with connection pooling"""
        async with self._lock:
            now = time.time()
            
            # Periodic cleanup
            if now - self._last_cleanup > self._cleanup_interval:
                await self._cleanup_session()
                self._last_cleanup = now
            
            if self._should_create_new_session(now):
                await self._create_new_session()
            
            return self._session
    
    def _should_create_new_session(self, now: float) -> bool:
        """Determine if a new session should be created"""
        if self._session is None:
            return True
        
        if self._session.closed:
            logger.debug("Session is closed, creating new session")
            return True
        
        # Check session age
        if self._session_created_at and (now - self._session_created_at) > self._session_lifetime:
            logger.debug("Session expired, creating new session")
            return True
        
        return False
    
    async def _create_new_session(self):
        """Create a new HTTP session with optimized settings"""
        # Close existing session if any
        if self._session and not self._session.closed:
            await self._session.close()
        
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
        
        # Create session without timeout configuration to avoid context manager issues
        self._session = aiohttp.ClientSession(
            connector=connector,
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
            # Use asyncio.wait_for for timeout handling to avoid aiohttp timeout context issues
            response = await asyncio.wait_for(
                session.request(method, url, **kwargs),
                timeout=self.config.timeout_total
            )
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
        """Get connection pool statistics"""
        stats = {
            'request_count': self._request_count,
            'session_age': time.time() - self._session_created_at if self._session_created_at else 0,
            'session_active': self._session is not None and not self._session.closed
        }
        
        if self._session and hasattr(self._session.connector, '_conns'):
            stats['active_connections'] = len(self._session.connector._conns)
        
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
                    status_code=response.status,
                    category=ErrorCategory.API,
                    severity=ErrorSeverity.HIGH
                )
            
            try:
                json_data = await response.json()
                return json_data, response.status
            except Exception as e:
                raise APIError(
                    f"Failed to parse JSON response: {e}",
                    status_code=response.status,
                    category=ErrorCategory.API,
                    severity=ErrorSeverity.MEDIUM
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
                    category=ErrorCategory.API,
                    severity=ErrorSeverity.HIGH
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
    """Close the global HTTP client and cleanup resources"""
    global _global_http_client
    if _global_http_client:
        await _global_http_client.close()
        _global_http_client = None
        logger.info("Closed global HTTP client")
        logger.info("HTTP resources cleaned up")
