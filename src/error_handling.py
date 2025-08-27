"""
Enhanced error handling system for the Twitch Color Changer bot
"""

import asyncio
import traceback
import sys
from typing import Optional, Callable, Any, Dict, Type
from functools import wraps
from dataclasses import dataclass
from enum import Enum

from .logger import logger


class ErrorSeverity(Enum):
    """Error severity levels"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ErrorCategory(Enum):
    """Error categories for better classification"""
    NETWORK = "network"
    AUTH = "authentication"
    API = "api"
    CONFIG = "configuration"
    IRC = "irc"
    SYSTEM = "system"
    USER_INPUT = "user_input"
    RATE_LIMIT = "rate_limit"


@dataclass
class ErrorContext:
    """Enhanced error context information"""
    category: ErrorCategory
    severity: ErrorSeverity
    user: Optional[str] = None
    channel: Optional[str] = None
    api_endpoint: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    additional_info: Optional[Dict[str, Any]] = None


class BotError(Exception):
    """Base exception class for bot errors"""
    
    def __init__(self, message: str, context: Optional[ErrorContext] = None):
        super().__init__(message)
        self.context = context or ErrorContext(
            category=ErrorCategory.SYSTEM,
            severity=ErrorSeverity.MEDIUM
        )


class NetworkError(BotError):
    """Network-related errors"""
    
    def __init__(self, message: str, status_code: Optional[int] = None, user: Optional[str] = None):
        context = ErrorContext(
            category=ErrorCategory.NETWORK,
            severity=ErrorSeverity.MEDIUM,
            user=user,
            additional_info={'status_code': status_code} if status_code else None
        )
        super().__init__(message, context)


class AuthenticationError(BotError):
    """Authentication and authorization errors"""
    
    def __init__(self, message: str, user: Optional[str] = None):
        context = ErrorContext(
            category=ErrorCategory.AUTH,
            severity=ErrorSeverity.HIGH,
            user=user
        )
        super().__init__(message, context)


class APIError(BotError):
    """Twitch API specific errors"""
    
    def __init__(self, message: str, status_code: Optional[int] = None, 
                 endpoint: Optional[str] = None, user: Optional[str] = None):
        severity = ErrorSeverity.HIGH if status_code and status_code >= 500 else ErrorSeverity.MEDIUM
        context = ErrorContext(
            category=ErrorCategory.API,
            severity=severity,
            user=user,
            api_endpoint=endpoint,
            additional_info={'status_code': status_code} if status_code else None
        )
        super().__init__(message, context)


class RateLimitError(BotError):
    """Rate limit specific errors"""
    
    def __init__(self, message: str, reset_time: Optional[float] = None, user: Optional[str] = None):
        context = ErrorContext(
            category=ErrorCategory.RATE_LIMIT,
            severity=ErrorSeverity.MEDIUM,
            user=user,
            additional_info={'reset_time': reset_time} if reset_time else None
        )
        super().__init__(message, context)


class ConfigurationError(BotError):
    """Configuration-related errors"""
    
    def __init__(self, message: str, field: Optional[str] = None):
        context = ErrorContext(
            category=ErrorCategory.CONFIG,
            severity=ErrorSeverity.HIGH,
            additional_info={'field': field} if field else None
        )
        super().__init__(message, context)


class IRCError(BotError):
    """IRC connection and communication errors"""
    
    def __init__(self, message: str, channel: Optional[str] = None, user: Optional[str] = None):
        context = ErrorContext(
            category=ErrorCategory.IRC,
            severity=ErrorSeverity.MEDIUM,
            user=user,
            channel=channel
        )
        super().__init__(message, context)


class ErrorHandler:
    """Centralized error handling system"""
    
    def __init__(self):
        self.error_counts = {}
        self.retry_handlers = {}
        self.error_callbacks = {}
    
    def register_retry_handler(self, error_type: Type[Exception], 
                             handler: Callable[[Exception, ErrorContext], bool]):
        """Register a retry handler for specific error types"""
        self.retry_handlers[error_type] = handler
    
    def register_error_callback(self, category: ErrorCategory, 
                              callback: Callable[[Exception, ErrorContext], None]):
        """Register a callback for specific error categories"""
        self.error_callbacks[category] = callback
    
    def handle_error(self, error: Exception, context: Optional[ErrorContext] = None) -> bool:
        """
        Handle an error with appropriate logging and recovery
        
        Returns:
            bool: True if operation should be retried, False otherwise
        """
        # Ensure we have context
        if isinstance(error, BotError) and error.context:
            ctx = error.context
        elif context:
            ctx = context
        else:
            ctx = ErrorContext(
                category=ErrorCategory.SYSTEM,
                severity=ErrorSeverity.MEDIUM
            )
        
        # Log the error with context
        self._log_error(error, ctx)
        
        # Track error counts
        self._track_error(error, ctx)
        
        # Call registered callbacks
        self._call_error_callbacks(error, ctx)
        
        # Check if we should retry
        return self._should_retry(error, ctx)
    
    def _log_error(self, error: Exception, context: ErrorContext):
        """Log error with appropriate level and context"""
        error_msg = str(error)
        
        # Prepare logging context
        log_context = {
            'category': context.category.value,
            'severity': context.severity.value,
        }
        
        if context.user:
            log_context['user'] = context.user
        if context.channel:
            log_context['channel'] = context.channel
        if context.api_endpoint:
            log_context['api_endpoint'] = context.api_endpoint
        if context.retry_count > 0:
            log_context['retry_count'] = context.retry_count
        if context.additional_info:
            log_context.update(context.additional_info)
        
        # Choose log level based on severity
        if context.severity == ErrorSeverity.CRITICAL:
            logger.critical(error_msg, exc_info=True, **log_context)
        elif context.severity == ErrorSeverity.HIGH:
            logger.error(error_msg, exc_info=True, **log_context)
        elif context.severity == ErrorSeverity.MEDIUM:
            logger.warning(error_msg, **log_context)
        else:
            logger.info(error_msg, **log_context)
    
    def _track_error(self, error: Exception, context: ErrorContext):
        """Track error frequency for monitoring"""
        error_key = f"{context.category.value}:{type(error).__name__}"
        if context.user:
            error_key += f":{context.user}"
        
        self.error_counts[error_key] = self.error_counts.get(error_key, 0) + 1
        
        # Log warning for frequently occurring errors
        if self.error_counts[error_key] % 5 == 0:
            logger.warning(f"Error {error_key} has occurred {self.error_counts[error_key]} times")
    
    def _call_error_callbacks(self, error: Exception, context: ErrorContext):
        """Call registered error callbacks"""
        callback = self.error_callbacks.get(context.category)
        if callback:
            try:
                callback(error, context)
            except Exception as e:
                logger.error(f"Error in error callback: {e}", exc_info=True)
    
    def _should_retry(self, error: Exception, context: ErrorContext) -> bool:
        """Determine if operation should be retried"""
        # Check if we've exceeded max retries
        if context.retry_count >= context.max_retries:
            logger.warning(f"Max retries ({context.max_retries}) exceeded for {type(error).__name__}")
            return False
        
        # Check registered retry handlers
        for error_type, handler in self.retry_handlers.items():
            if isinstance(error, error_type):
                try:
                    return handler(error, context)
                except Exception as e:
                    logger.error(f"Error in retry handler: {e}", exc_info=True)
                    return False
        
        # Default retry logic based on error type and category
        return self._default_retry_logic(error, context)
    
    def _default_retry_logic(self, error: Exception, context: ErrorContext) -> bool:
        """Default retry logic for common error scenarios"""
        # Network errors: retry for temporary issues
        if context.category == ErrorCategory.NETWORK:
            if context.additional_info and context.additional_info.get('status_code'):
                status_code = context.additional_info['status_code']
                # Retry on server errors but not client errors
                return 500 <= status_code < 600
            return True  # Retry network errors without status codes
        
        # Rate limit errors: always retry after waiting
        if context.category == ErrorCategory.RATE_LIMIT:
            return True
        
        # Authentication errors: don't retry invalid tokens
        if context.category == ErrorCategory.AUTH:
            return False
        
        # API errors: retry on server errors
        if context.category == ErrorCategory.API:
            if context.additional_info and context.additional_info.get('status_code'):
                status_code = context.additional_info['status_code']
                return 500 <= status_code < 600
            return False
        
        # IRC errors: retry connection issues
        if context.category == ErrorCategory.IRC:
            return True
        
        # Configuration errors: don't retry
        if context.category == ErrorCategory.CONFIG:
            return False
        
        # Default: don't retry unknown errors
        return False
    
    def get_error_stats(self) -> Dict[str, int]:
        """Get error statistics for monitoring"""
        return self.error_counts.copy()
    
    def reset_error_stats(self):
        """Reset error statistics"""
        self.error_counts.clear()


# Global error handler instance
error_handler = ErrorHandler()


def with_error_handling(category: ErrorCategory = ErrorCategory.SYSTEM,
                       severity: ErrorSeverity = ErrorSeverity.MEDIUM,
                       max_retries: int = 3,
                       user: Optional[str] = None,
                       channel: Optional[str] = None):
    """
    Decorator for automatic error handling and retries
    
    Args:
        category: Error category
        severity: Error severity level
        max_retries: Maximum number of retry attempts
        user: User context for logging
        channel: Channel context for logging
    """
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            return await _retry_with_error_handling(
                func, args, kwargs, category, severity, max_retries, user, channel, is_async=True
            )
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            return _retry_with_error_handling(
                func, args, kwargs, category, severity, max_retries, user, channel, is_async=False
            )
        
        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    
    return decorator


async def _retry_with_error_handling(func, args, kwargs, category, severity, max_retries, user, channel, is_async=True):
    """Internal function to handle retries for both async and sync functions"""
    retry_count = 0
    last_error = None
    
    while retry_count <= max_retries:
        try:
            if is_async:
                return await func(*args, **kwargs)
            else:
                return func(*args, **kwargs)
        except Exception as e:
            last_error = e
            
            # Create error context
            context = _create_error_context(e, category, severity, user, channel, retry_count, max_retries)
            
            # Handle the error and check if we should retry
            if not _should_continue_retry(e, context):
                break
            
            retry_count += 1
            
            # Wait before retrying
            if retry_count <= max_retries:
                await _wait_before_retry(retry_count, is_async)
    
    # If we get here, all retries were exhausted
    if last_error:
        raise last_error


def _should_continue_retry(error, context):
    """Determine if we should continue retrying"""
    should_retry = error_handler.handle_error(error, context)
    return should_retry


def _wait_before_retry_sync(wait_time):
    """Synchronous wait function to avoid async lint warnings"""
    import time
    time.sleep(wait_time)


async def _wait_before_retry(retry_count, is_async):
    """Wait before retrying with exponential backoff"""
    wait_time = min(2 ** retry_count, 30)  # Cap at 30 seconds
    logger.info(f"Retrying in {wait_time} seconds... (attempt {retry_count + 1})")
    
    if is_async:
        await asyncio.sleep(wait_time)
    else:
        _wait_before_retry_sync(wait_time)


def _create_error_context(error, category, severity, user, channel, retry_count, max_retries):
    """Create appropriate error context for an exception"""
    context = ErrorContext(
        category=category,
        severity=severity,
        user=user,
        channel=channel,
        retry_count=retry_count,
        max_retries=max_retries
    )
    
    # If it's already a BotError, update the context
    if isinstance(error, BotError) and error.context:
        error.context.retry_count = retry_count
        error.context.max_retries = max_retries
        context = error.context
    
    return context


def setup_error_handlers():
    """Setup default error handlers and callbacks"""
    
    def network_retry_handler(error: Exception, context: ErrorContext) -> bool:
        """Custom retry logic for network errors"""
        if isinstance(error, (asyncio.TimeoutError, ConnectionError)):
            return True
        return error_handler._default_retry_logic(error, context)
    
    def auth_error_callback(error: Exception, context: ErrorContext):
        """Handle authentication errors"""
        if isinstance(error, AuthenticationError):
            logger.error(f"Authentication failed for user {context.user}. Check tokens and scopes.")
    
    def rate_limit_callback(error: Exception, context: ErrorContext):
        """Handle rate limit errors"""
        if isinstance(error, RateLimitError):
            reset_time = context.additional_info.get('reset_time') if context.additional_info else None
            if reset_time:
                logger.warning(f"Rate limited. Will reset at {reset_time}")
    
    # Register handlers
    error_handler.register_retry_handler(NetworkError, network_retry_handler)
    error_handler.register_error_callback(ErrorCategory.AUTH, auth_error_callback)
    error_handler.register_error_callback(ErrorCategory.RATE_LIMIT, rate_limit_callback)


def handle_critical_error(error: Exception, context: Optional[str] = None):
    """Handle critical errors that should shut down the application"""
    logger.critical(f"Critical error occurred: {error}", exc_info=True)
    if context:
        logger.critical(f"Context: {context}")
    
    # Attempt graceful shutdown
    logger.info("Attempting graceful shutdown...")
    sys.exit(1)
