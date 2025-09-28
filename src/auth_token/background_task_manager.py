"""Background task management for token refresh."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

import aiohttp

from ..constants import (
    TOKEN_MANAGER_BACKGROUND_BASE_SLEEP,
    TOKEN_MANAGER_PERIODIC_VALIDATION_INTERVAL,
    TOKEN_REFRESH_THRESHOLD_SECONDS,
)
from ..utils import format_duration
from .client import TokenOutcome
from .types import TokenState, _jitter_rng

if TYPE_CHECKING:
    from .manager import TokenInfo, TokenManager


class BackgroundTaskManager:
    """Manages the background refresh loop and related operations."""

    def __init__(self, manager: TokenManager) -> None:
        self.manager = manager
        self.task: asyncio.Task[Any] | None = None
        self.running = False

    async def start(self) -> None:
        """Start the background refresh loop."""
        if self.running:
            return
        # Defensive: if a previous background task is still lingering, cancel it
        if self.task and not self.task.done():
            logging.debug("Cancelling stale background task before restart")
            try:
                self.task.cancel()
                await self.task
            except asyncio.CancelledError:
                raise
            except (ValueError, TypeError, RuntimeError) as e:
                logging.debug(f"⚠️ Error cancelling stale background task: {str(e)}")
            finally:
                self.task = None
        self.running = True
        self.task = asyncio.create_task(self._background_refresh_loop())
        logging.debug("▶️ Started background token refresh loop")

    async def stop(self) -> None:
        """Stop the background refresh loop."""
        if not self.running:
            return
        self.running = False
        if self.task:
            try:
                self.task.cancel()
                # Don't wait for the task to complete
            except (RuntimeError, OSError, ValueError) as e:
                logging.error(f"Error cancelling background task: {e}")
            finally:
                self.task = None

    async def _background_refresh_loop(self) -> None:
        """Background loop for periodic token validation and refresh.

        Runs continuously while the manager is running, checking all tokens
        and refreshing as needed. Includes drift correction to maintain
        reliable timing for unattended operation.

        Raises:
            RuntimeError: If background processing fails.
            OSError: If system-level errors occur.
            ValueError: If invalid data is encountered.
            aiohttp.ClientError: If network requests fail.
        """
        base = TOKEN_MANAGER_BACKGROUND_BASE_SLEEP
        last_loop = time.time()
        consecutive_drift = 0
        drift_correction_applied = False

        while self.running:
            try:
                now = time.time()
                drift = now - last_loop
                drifted = drift > (base * 3)

                # Enhanced drift detection and correction
                if drifted:
                    consecutive_drift += 1
                    logging.warning(
                        f"⏱️ Token manager loop drift detected drift={int(drift)}s base={base}s consecutive={consecutive_drift}"
                    )

                    # Apply drift correction after multiple consecutive drifts
                    if consecutive_drift >= 3 and not drift_correction_applied:
                        # Reduce sleep time to compensate for drift
                        corrected_sleep = max(base * 0.3, base - (drift * 0.5))
                        logging.info(
                            f"🔧 Applied drift correction: sleep={corrected_sleep:.1f}s (was {base}s) drift={int(drift)}s"
                        )
                        drift_correction_applied = True
                        sleep_duration = corrected_sleep
                    else:
                        sleep_duration = base
                else:
                    # Reset drift tracking on successful timing
                    consecutive_drift = 0
                    drift_correction_applied = False
                    sleep_duration = base

                async with self.manager._tokens_lock:
                    users = list(self.manager.tokens.items())
                users = [(u, info) for u, info in users if u not in self.manager._paused_users]

                # Enhanced proactive refresh with drift compensation
                for username, info in users:
                    try:
                        await self._process_single_background(
                            username, info, force_proactive=drifted, drift_compensation=drift
                        )
                    except Exception as e:
                        logging.error(
                            f"💥 Error processing background refresh for user={username}: {str(e)} type={type(e).__name__}"
                        )
                        # Continue with other users even if one fails
                        continue

                last_loop = now
                # Apply jitter to corrected sleep duration
                jittered_sleep = sleep_duration * _jitter_rng.uniform(0.5, 1.5)

                # Use cancellable sleep to allow immediate shutdown
                try:
                    await asyncio.wait_for(asyncio.sleep(jittered_sleep), timeout=None)
                except asyncio.CancelledError:
                    # Re-raise to allow proper cancellation
                    raise

            except asyncio.CancelledError:
                # Handle cancellation gracefully
                logging.debug("Background token refresh loop cancelled")
                raise
            except (RuntimeError, OSError, ValueError, aiohttp.ClientError) as e:
                logging.error(f"💥 Background token manager loop error: {str(e)}")
                # Reset drift correction on error
                consecutive_drift = 0
                drift_correction_applied = False
                try:
                    await asyncio.wait_for(asyncio.sleep(base * 2), timeout=None)
                except asyncio.CancelledError:
                    raise

    async def _process_single_background(
        self, username: str, info: TokenInfo, *, force_proactive: bool = False, drift_compensation: float = 0.0
    ) -> None:
        """Handle refresh/validation logic for a single user with drift compensation.

        Enhanced with proactive refresh and drift compensation for reliable
        unattended operation.

        Args:
            username: Username associated with the token.
            info: TokenInfo object containing token details.
            force_proactive: Whether to force proactive refresh due to drift.
            drift_compensation: Amount of drift in seconds to compensate for.
        """
        remaining = self.manager.validator.remaining_seconds(info)
        self._log_remaining_detail(username, remaining)

        # Enhanced token health monitoring
        health_status = self.manager.validator.assess_token_health(info, remaining, drift_compensation)
        if health_status == "critical":
            logging.warning(
                f"🚨 Critical token health detected user={username} remaining={remaining}s drift={drift_compensation:.1f}s"
            )
            await self.manager.refresher.ensure_fresh(username, force_refresh=True)
            return
        elif health_status == "degraded":
            logging.info(
                f"⚠️ Degraded token health detected user={username} remaining={remaining}s drift={drift_compensation:.1f}s"
            )

        # Unified unknown-expiry + periodic validation resolution.
        remaining = await self._maybe_periodic_or_unknown_resolution(
            username, info, remaining
        )
        if remaining is None:
            return

        if remaining < 0:
            async with info.refresh_lock:
                info.state = TokenState.EXPIRED
            logging.warning(
                f"⚠️ Unexpected expired state detected user={username} remaining={remaining}"
            )
            await self.manager.refresher.ensure_fresh(username, force_refresh=True)
            return

        # Enhanced proactive refresh with drift compensation
        trigger_threshold = self._calculate_refresh_threshold(force_proactive, drift_compensation)

        if remaining <= trigger_threshold:
            # Enhanced error handling for token refresh operations
            try:
                # Force refresh if we're only triggering due to drift compensation
                if self._should_force_refresh_due_to_drift(force_proactive, drift_compensation, remaining):
                    await self.manager.refresher.ensure_fresh(username, force_refresh=True)
                else:
                    await self.manager.refresher.ensure_fresh(username)
            except Exception as e:
                logging.error(
                    f"💥 Token refresh failed for user={username} remaining={remaining}s threshold={trigger_threshold}s: {str(e)}"
                )
                # Mark token as expired if refresh consistently fails
                async with info.refresh_lock:
                    info.state = TokenState.EXPIRED
                # Fire invalidation hook for failed refresh
                await self.manager.hook_manager.maybe_fire_invalidation_hook(username)

    async def _maybe_periodic_or_unknown_resolution(
        self, username: str, info: TokenInfo, remaining: float | None
    ) -> float | None:
        """Resolve unknown expiry or perform periodic validation.

        Returns (possibly updated) remaining seconds (None if still unknown).
        Always logs both remaining_seconds and remaining_human for periodic events.
        """
        # Unknown expiry path first.
        if info.expiry is None:
            await self._handle_unknown_expiry(username)
            return self.manager.validator.remaining_seconds(info)
        # Periodic validation check.
        try:
            now = time.time()
            if now - info.last_validation < TOKEN_MANAGER_PERIODIC_VALIDATION_INTERVAL:
                return remaining
            outcome = await self.manager.validator.validate(username)
            updated_remaining = self.manager.validator.remaining_seconds(info)
            if outcome == TokenOutcome.VALID:
                if updated_remaining is not None:
                    human_new = format_duration(max(0, int(updated_remaining)))
                    logging.info(
                        f"✅ Periodic remote token validation ok for user {username} ({human_new} remaining)"
                    )
                return updated_remaining
            # Failure -> forced refresh.
            pre_seconds = (
                int(updated_remaining) if updated_remaining is not None else None
            )
            pre_human = (
                format_duration(max(0, pre_seconds))
                if pre_seconds is not None
                else "unknown"
            )
            logging.error(
                f"❌ Periodic remote token validation failed for user {username} ({pre_human} remaining pre-refresh, {pre_seconds}s)"
            )
            ref_outcome = await self.manager.refresher.ensure_fresh(username, force_refresh=True)
            post_remaining = self.manager.validator.remaining_seconds(info)
            post_seconds = int(post_remaining) if post_remaining is not None else None
            post_human = (
                format_duration(max(0, post_seconds))
                if post_seconds is not None
                else "unknown"
            )
            logging.info(
                f"🔄 Forced refresh after failed periodic remote validation for user {username} outcome={ref_outcome.value} ({post_human} remaining, {post_seconds}s)"
            )
            return post_remaining
        except (aiohttp.ClientError, ValueError, RuntimeError) as e:
            logging.warning(
                f"⚠️ Periodic remote token validation error for user {username} type={type(e).__name__} error={str(e)}"
            )
            return self.manager.validator.remaining_seconds(info)

    def _log_remaining_detail(self, username: str, remaining: float | None) -> None:
        """Log detailed remaining token validity time for observability.

        Args:
            username: Username associated with the token.
            remaining: Remaining seconds until expiry, or None if unknown.
        """
        # Emit remaining time every cycle for observability (even when no refresh triggered).
        if remaining is None:
            logging.debug(
                f"❔ Token expiry unknown (will validate / refresh) user={username} remaining_seconds=None"
            )
            return
        int_remaining = int(remaining)
        human = format_duration(int(max(0, int_remaining)))
        if int_remaining <= 900:
            icon = "🚨"
        elif int_remaining <= 3600:
            icon = "⏰"
        elif int_remaining <= 2 * 3600:
            icon = "⌛"
        else:
            icon = "🔐"
        # Expiry timestamp not included in human message (simplified per request).
        # Build a clearer human message: explicitly mention token remaining time (no extra parenthetical details).
        logging.debug(
            f"{icon} Access token validity: {human} remaining user={username} remaining_seconds={int_remaining}"
        )

    async def _handle_unknown_expiry(self, username: str) -> None:
        """Resolve unknown expiry with capped forced refresh attempts (max 3) using exponential backoff."""
        outcome = await self.manager.refresher.ensure_fresh(username, force_refresh=False)
        async with self.manager._tokens_lock:
            info_ref = self.manager.tokens.get(username)
        if not info_ref:
            return
        if info_ref.expiry is None:
            async with self.manager._tokens_lock:
                if info_ref.forced_unknown_attempts < 3:
                    info_ref.forced_unknown_attempts += 1
            delay = TOKEN_MANAGER_BACKGROUND_BASE_SLEEP * (
                2 ** (info_ref.forced_unknown_attempts - 1)
            )
            await asyncio.sleep(delay)
            forced = await self.manager.refresher.ensure_fresh(username, force_refresh=True)
            if forced == TokenOutcome.FAILED:
                logging.warning(
                    f"⚠️ Forced refresh attempt failed resolving unknown expiry user={username} attempt={info_ref.forced_unknown_attempts}"
                )
            else:
                logging.info(
                    f"✅ Forced refresh resolved unknown expiry user={username} attempt={info_ref.forced_unknown_attempts}"
                )
                async with self.manager._tokens_lock:
                    info_ref.forced_unknown_attempts = 0
        else:
            async with self.manager._tokens_lock:
                if info_ref.forced_unknown_attempts:
                    info_ref.forced_unknown_attempts = 0
        async with self.manager._tokens_lock:
            if outcome == TokenOutcome.FAILED and info_ref.expiry is None:
                logging.warning(
                    f"⚠️ Validation failed with unknown expiry user={username}"
                )

    def _calculate_refresh_threshold(self, force_proactive: bool, drift_compensation: float) -> float:
        """Calculate refresh threshold with drift compensation.

        Args:
            force_proactive: Whether proactive refresh is forced due to drift.
            drift_compensation: Amount of drift in seconds to compensate for.

        Returns:
            Calculated refresh threshold in seconds.
        """
        base_threshold = TOKEN_REFRESH_THRESHOLD_SECONDS

        # Apply drift compensation
        if drift_compensation > 0:
            # Reduce threshold by up to 50% of drift to refresh earlier
            drift_reduction = min(drift_compensation * 0.5, base_threshold * 0.3)
            compensated_threshold = base_threshold - drift_reduction
        else:
            compensated_threshold = base_threshold

        # If forcing proactive refresh, use more conservative threshold
        if force_proactive:
            return compensated_threshold * 1.5  # 50% more conservative

        return compensated_threshold

    def _should_force_refresh_due_to_drift(
        self, force_proactive: bool, drift_compensation: float, remaining: float
    ) -> bool:
        """Determine if refresh should be forced due to drift conditions.

        Args:
            force_proactive: Whether proactive refresh is forced.
            drift_compensation: Amount of drift in seconds.
            remaining: Remaining seconds until expiry.

        Returns:
            True if refresh should be forced due to drift.
        """
        if not force_proactive:
            return False

        # Force refresh if drift is significant and we're close to expiry
        base_threshold = TOKEN_REFRESH_THRESHOLD_SECONDS
        return (
            drift_compensation > 60 and  # Significant drift (>1min)
            remaining > base_threshold and  # But not past normal threshold
            remaining <= base_threshold * 2  # And within conservative threshold
        )
