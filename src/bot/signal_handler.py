"""SignalHandler - handles system signals and shutdown coordination."""

import asyncio
import logging
import signal


class SignalHandler:
    """Handler for system signals and shutdown coordination."""

    def __init__(self) -> None:
        """Initialize the SignalHandler."""
        self.shutdown_initiated = False

    def stop(self) -> None:
        """Initiate shutdown of all bots."""
        self.shutdown_initiated = True
        try:
            asyncio.get_running_loop()
            # Note: This will be handled by the main loop
        except RuntimeError:
            pass

    def setup_signal_handlers(self) -> None:  # pragma: no cover
        """Set up signal handlers for graceful shutdown on SIGINT/SIGTERM."""

        def handler(signum: int, _frame: object | None) -> None:  # noqa: D401
            # Idempotent signal handler: only trigger once
            if self.shutdown_initiated:
                return
            logging.warning(
                f"🛑 Signal received - initiating shutdown (signal={signum})"
            )
            self.shutdown_initiated = True
            # We don't directly stop bots here; main loop will detect flag and perform orderly shutdown

        signal.signal(signal.SIGINT, handler)
        signal.signal(signal.SIGTERM, handler)
