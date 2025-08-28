"""
Structured logging system for the Twitch Color Changer bot
"""

import logging
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from .colors import bcolors


class StructuredFormatter(logging.Formatter):
    """Custom formatter that outputs structured JSON logs in production or colored logs in development"""
    
    def __init__(self, use_json: bool = False):
        super().__init__()
        self.use_json = use_json
        self.use_colors = os.environ.get('FORCE_COLOR', 'true').lower() != 'false'
    
    def format(self, record: logging.LogRecord) -> str:
        if self.use_json:
            return self._format_json(record)
        else:
            return self._format_colored(record)
    
    def _format_json(self, record: logging.LogRecord) -> str:
        """Format log record as structured JSON"""
        log_data = {
            'timestamp': datetime.fromtimestamp(record.created).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno
        }
        
        # Add extra fields if present
        if hasattr(record, 'user'):
            log_data['user'] = record.user
        if hasattr(record, 'channel'):
            log_data['channel'] = record.channel
        if hasattr(record, 'api_endpoint'):
            log_data['api_endpoint'] = record.api_endpoint
        if hasattr(record, 'response_time'):
            log_data['response_time'] = record.response_time
        if hasattr(record, 'error_code'):
            log_data['error_code'] = record.error_code
        
        # Add exception info if present
        if record.exc_info:
            log_data['exception'] = self.formatException(record.exc_info)
        
        return json.dumps(log_data)
    
    def _format_colored(self, record: logging.LogRecord) -> str:
        """Format log record with colors for development"""
        if not self.use_colors:
            return f"{record.getMessage()}"
        
        # Color mapping
        colors = {
            'DEBUG': bcolors.OKBLUE,
            'INFO': bcolors.OKGREEN,
            'WARNING': bcolors.WARNING,
            'ERROR': bcolors.FAIL,
            'CRITICAL': bcolors.FAIL + bcolors.BOLD
        }
        
        color = colors.get(record.levelname, '')
        
        # Format message with optional context
        message = record.getMessage()
        context_parts = []
        
        if hasattr(record, 'user'):
            context_parts.append(f"user={record.user}")
        if hasattr(record, 'channel'):
            context_parts.append(f"channel={record.channel}")
        
        if context_parts:
            context = f" [{', '.join(context_parts)}]"
        else:
            context = ""
        
        formatted = f"{color}{message}{context}{bcolors.ENDC}"
        
        # Add exception info if present
        if record.exc_info:
            formatted += f"\n{self.formatException(record.exc_info)}"
        
        return formatted


class BotLogger:
    """Enhanced logging system with structured logging support"""
    
    def __init__(self, name: str = "twitch_colorchanger"):
        self.logger = logging.getLogger(name)
        
        # Clear any existing handlers
        self.logger.handlers.clear()
        
        # Determine if we should use JSON logging (production mode)
        use_json = os.environ.get('LOG_FORMAT', '').lower() == 'json'
        debug_enabled = os.environ.get('DEBUG', 'false').lower() in ('true', '1', 'yes')
        
        # Set log level based on DEBUG flag - default to INFO (not DEBUG)
        if debug_enabled:
            self.logger.setLevel(logging.DEBUG)
        else:
            self.logger.setLevel(logging.INFO)
        
        # Setup console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(StructuredFormatter(use_json=use_json))
        self.logger.addHandler(console_handler)
        
        # Setup file handler if LOG_FILE is specified
        log_file = os.environ.get('LOG_FILE')
        if log_file:
            try:
                log_path = Path(log_file)
                log_path.parent.mkdir(parents=True, exist_ok=True)
                
                file_handler = logging.FileHandler(log_file)
                # Always use JSON for file logging
                file_handler.setFormatter(StructuredFormatter(use_json=True))
                self.logger.addHandler(file_handler)
            except Exception as e:
                self.logger.warning(f"Failed to setup file logging: {e}")
    
    def debug(self, message: str, **kwargs):
        """Log debug message with optional context"""
        self._log(logging.DEBUG, message, **kwargs)
    
    def info(self, message: str, **kwargs):
        """Log info message with optional context"""
        self._log(logging.INFO, message, **kwargs)
    
    def warning(self, message: str, **kwargs):
        """Log warning message with optional context"""
        self._log(logging.WARNING, message, **kwargs)
    
    def error(self, message: str, exc_info: bool = False, **kwargs):
        """Log error message with optional context and exception info"""
        self._log(logging.ERROR, message, exc_info=exc_info, **kwargs)
    
    def critical(self, message: str, exc_info: bool = False, **kwargs):
        """Log critical message with optional context and exception info"""
        self._log(logging.CRITICAL, message, exc_info=exc_info, **kwargs)
    
    def _log(self, level: int, message: str, exc_info: bool = False, **kwargs):
        """Internal method to log with structured context"""
        extra = {}
        
        # Extract known context fields
        if 'user' in kwargs:
            extra['user'] = kwargs.pop('user')
        if 'channel' in kwargs:
            extra['channel'] = kwargs.pop('channel')
        if 'api_endpoint' in kwargs:
            extra['api_endpoint'] = kwargs.pop('api_endpoint')
        if 'response_time' in kwargs:
            extra['response_time'] = kwargs.pop('response_time')
        if 'error_code' in kwargs:
            extra['error_code'] = kwargs.pop('error_code')
        
        # If there are remaining kwargs, add them to the message
        if kwargs:
            context_str = ', '.join(f"{k}={v}" for k, v in kwargs.items())
            message = f"{message} ({context_str})"
        
        self.logger.log(level, message, exc_info=exc_info, extra=extra)
    
# Global logger instance
logger = BotLogger()


# Backward compatibility functions
def print_log(message: str, color: str = "", debug_only: bool = False):
    """Legacy print_log function for backward compatibility"""
    # color parameter kept for backward compatibility but ignored
    if debug_only:
        logger.debug(message)
    else:
        logger.info(message)
