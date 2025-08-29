"""
Simple colored logging system for the Twitch Color Changer bot
"""

import logging
import os
import sys

from .colors import bcolors


class ColoredFormatter(logging.Formatter):
    """Simple formatter that outputs colored logs"""
    
    def format(self, record: logging.LogRecord) -> str:
        return self._format_colored(record)
    
    def _format_colored(self, record: logging.LogRecord) -> str:
        """Format log record with colors"""
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
    """Simple logging system with colored output"""
    
    def __init__(self, name: str = "twitch_colorchanger"):
        self.logger = logging.getLogger(name)
        
        # Clear any existing handlers
        self.logger.handlers.clear()
        
        # Set log level based on DEBUG flag
        debug_enabled = os.environ.get('DEBUG', 'false').lower() in ('true', '1', 'yes')
        if debug_enabled:
            self.logger.setLevel(logging.DEBUG)
        else:
            self.logger.setLevel(logging.INFO)
        
        # Setup console handler with colored formatter
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(ColoredFormatter())
        self.logger.addHandler(console_handler)
    
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
        """Internal method to log with context"""
        extra = {}
        
        # Extract known context fields
        if 'user' in kwargs:
            extra['user'] = kwargs.pop('user')
        if 'channel' in kwargs:
            extra['channel'] = kwargs.pop('channel')
        
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
