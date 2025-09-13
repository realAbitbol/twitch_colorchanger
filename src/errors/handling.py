from __future__ import annotations

import logging


def log_error(message: str, error: Exception) -> None:
    """Logs an error message with the associated exception details.

    This function formats and logs an error message along with the string
    representation of the exception using the logging module's error level.

    Args:
        message: A descriptive message about the error context.
        error: The exception instance to be logged.

    Returns:
        None

    Raises:
        No exceptions are raised by this function.
    """
    logging.error(f"Error: {message} - {str(error)}")
