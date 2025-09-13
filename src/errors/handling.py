from __future__ import annotations

import logging


def log_error(message: str, error: Exception) -> None:
    logging.error(f"Error: {message} - {str(error)}")
