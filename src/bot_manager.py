"""
Bot manager for handling multiple Twitch bots
"""

import asyncio
import os
import signal
from typing import Any

import aiohttp

from .bot import TwitchColorBot
from .colors import BColors
from .config_watcher import create_config_watcher
from .constants import HEALTH_MONITOR_INTERVAL, TASK_WATCHDOG_INTERVAL
from .utils import print_log
from .watcher_globals import set_global_watcher


class BotManager:  # pylint: disable=too-many-instance-attributes
    """Manages multiple Twitch bots"""

    def __init__(self, users_config: list[dict[str, Any]], config_file: str = None):
        self.users_config = users_config
        self.config_file = config_file
        self.bots: list[Any] = []
        self.tasks: list[Any] = []
        self.running = False
        self.shutdown_initiated = False
        self.restart_requested = False
        self.new_config: list[dict[str, Any]] | None = None

        # Shared HTTP session for all bots
        self.http_session: aiohttp.ClientSession | None = None

    async def _start_all_bots(self):
        """Start all bots and return success status"""
        print_log(f"🚀 Starting {len(self.users_config)} bot(s)...", BColors.HEADER)

        # Create shared HTTP session
        print_log("🌐 Creating shared HTTP session...", BColors.OKCYAN)
        self.http_session = aiohttp.ClientSession()

        for user_config in self.users_config:
            try:
                bot = self._create_bot(user_config)
                if bot:
                    self.bots.append(bot)

            except Exception as e:
                print_log(
                    f"❌ Failed to create bot for user {user_config['username']}: {e}",
                    BColors.FAIL,
                )
                continue

        if not self.bots:
            print_log("❌ No bots could be started!", BColors.FAIL)
            return False

        # Start all bot tasks
        print_log(f"🎯 Launching {len(self.bots)} bot task(s)...", BColors.OKGREEN)

        for bot in self.bots:
            task = asyncio.create_task(bot.start())
            self.tasks.append(task)

        # Give a small delay to let bots initialize
        await asyncio.sleep(1)

        self.running = True
        self.shutdown_initiated = False  # Reset shutdown flag for new run

        # Start health monitoring
        self._start_health_monitoring()
        self._start_task_watchdog()

        print_log("✅ All bots started successfully!", BColors.OKGREEN)
        return True

    def _create_bot(self, user_config: dict[str, Any]) -> TwitchColorBot:
        """Create a bot instance from user configuration"""
        username = user_config["username"]
        token = user_config["access_token"]

        if not self.http_session:
            raise ValueError("HTTP session must be created before creating bots")

        try:
            bot = TwitchColorBot(
                token=token,
                refresh_token=user_config.get("refresh_token", ""),
                client_id=user_config.get("client_id", ""),
                client_secret=user_config.get("client_secret", ""),
                nick=username,
                channels=user_config["channels"],
                http_session=self.http_session,  # Required shared HTTP session
                is_prime_or_turbo=user_config.get("is_prime_or_turbo", True),
                config_file=self.config_file,
                user_id=None,  # Will be fetched by the bot itself
            )

            print_log(f"✅ Bot created for {username}", BColors.OKGREEN)
            return bot

        except Exception as e:
            print_log(f"❌ Failed to create bot for {username}: {e}", BColors.FAIL)
            raise

    async def _stop_all_bots(self):
        """Stop all running bots"""
        if not self.running:
            return

        print_log("\n🛑 Stopping all bots...", BColors.WARNING)

        # Cancel all tasks
        self._cancel_all_tasks()

        # Close all bots
        self._close_all_bots()

        # Close shared HTTP session
        if self.http_session:
            print_log("🌐 Closing shared HTTP session...", BColors.OKCYAN)
            await self.http_session.close()
            self.http_session = None

        # Wait for tasks to finish cancellation
        await self._wait_for_task_completion()

        self.running = False
        print_log("✅ All bots stopped", BColors.OKGREEN)

    def _cancel_all_tasks(self):
        """Cancel all running tasks"""
        for i, task in enumerate(self.tasks):
            try:
                if task and not task.done():
                    task.cancel()
                    print_log(f"✅ Cancelled task {i + 1}", BColors.OKGREEN)
            except Exception as e:
                print_log(f"⚠️ Error cancelling task {i + 1}: {e}", BColors.WARNING)

    def _close_all_bots(self):
        """Close all bot connections"""
        for i, bot in enumerate(self.bots):
            try:
                if bot:
                    bot.close()
                    print_log(f"✅ Closed bot {i + 1}", BColors.OKGREEN)
            except Exception as e:
                print_log(f"⚠️ Error closing bot {i + 1}: {e}", BColors.WARNING)

    async def _wait_for_task_completion(self):
        """Wait for all tasks to complete"""
        if self.tasks:
            try:
                await asyncio.gather(*self.tasks, return_exceptions=True)
            except Exception as e:
                print_log(f"⚠️ Error waiting for task completion: {e}", BColors.WARNING)

    def stop(self):
        """Public method to stop the bot manager"""
        self.shutdown_initiated = True
        # Create a task to stop bots (don't await in sync context)
        if hasattr(asyncio, "_get_running_loop"):
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._stop_all_bots())
            except RuntimeError:
                # No running loop, this is fine for testing
                pass

    def request_restart(self, new_users_config: list[dict[str, Any]]):
        """Request a restart with new configuration"""
        print_log("🔄 Config change detected, restarting bots...", BColors.OKCYAN)
        self.new_config = new_users_config
        self.restart_requested = True

    async def _restart_with_new_config(self):
        """Restart bots with new configuration"""
        if not self.new_config:
            return False

        print_log("🔄 Restarting bots with new configuration...", BColors.OKCYAN)

        # Save current statistics before stopping bots
        saved_stats = self._save_statistics()

        # Stop current bots
        await self._stop_all_bots()

        # Clear old state
        self.bots.clear()
        self.tasks.clear()

        # Update configuration
        old_count = len(self.users_config)
        self.users_config = self.new_config
        new_count = len(self.users_config)

        print_log(f"📊 Config updated: {old_count} → {new_count} users", BColors.OKCYAN)

        # Start with new config
        success = await self._start_all_bots()

        # Restore statistics for users that still exist
        if success:
            self._restore_statistics(saved_stats)

        # Reset restart state
        self.restart_requested = False
        self.new_config = None

        return success

    async def _monitor_bot_health(self):
        """Monitor bot health and attempt reconnections if needed"""
        while self.running and not self.shutdown_initiated:
            try:
                await asyncio.sleep(HEALTH_MONITOR_INTERVAL)  # Check every 5 minutes

                if not self.running or self.shutdown_initiated:
                    break

                print_log("🔍 Performing regular bot health check...", BColors.OKCYAN)
                await self._perform_health_check()

            except asyncio.CancelledError:
                print_log("🔍 Health monitoring cancelled", BColors.WARNING)
                raise  # Re-raise CancelledError
            except Exception as e:
                print_log(f"❌ Error during health check: {e}", BColors.FAIL)
                await asyncio.sleep(60)  # Wait a minute before trying again

    async def _perform_health_check(self):
        """Perform the actual health check logic"""
        unhealthy_bots = self._identify_unhealthy_bots()

        if unhealthy_bots:
            await self._reconnect_unhealthy_bots(unhealthy_bots)
        else:
            print_log("✅ All bots are healthy", BColors.OKGREEN)

    async def _monitor_task_health(self):
        """Monitor individual task health and detect hanging tasks"""
        while self.running and not self.shutdown_initiated:
            try:
                await asyncio.sleep(TASK_WATCHDOG_INTERVAL)  # Check every 2 minutes

                if not self.running or self.shutdown_initiated:
                    break

                print_log("🐕 Performing task watchdog check...", BColors.OKCYAN)
                self._check_task_health()

            except asyncio.CancelledError:
                print_log("🐕 Task watchdog cancelled", BColors.WARNING)
                raise  # Re-raise CancelledError
            except Exception as e:
                print_log(f"❌ Error during task watchdog: {e}", BColors.FAIL)
                await asyncio.sleep(30)  # Wait 30 seconds before trying again

    def _check_task_health(self):
        """Check health of individual tasks"""
        dead_tasks = []
        for i, task in enumerate(self.tasks):
            if task.done():
                if task.exception():
                    print_log(
                        f"⚠️ Task {i} died with exception: {task.exception()}",
                        BColors.WARNING,
                    )
                else:
                    print_log(f"ℹ️ Task {i} completed normally", BColors.OKCYAN)
                dead_tasks.append(i)

        # Remove dead tasks from the list (in reverse order to maintain indices)
        for i in reversed(dead_tasks):
            self.tasks.pop(i)
            print_log(f"🗑️ Removed dead task {i}", BColors.WARNING)

        if dead_tasks:
            print_log(f"⚠️ Found {len(dead_tasks)} dead tasks", BColors.WARNING)
        else:
            print_log("✅ All tasks are alive", BColors.OKGREEN)

    def _identify_unhealthy_bots(self):
        """Identify bots that appear unhealthy"""
        unhealthy_bots = []
        for bot in self.bots:
            if bot.irc and not bot.irc.is_healthy():
                unhealthy_bots.append(bot)
                self._log_bot_health_issues(bot)
        return unhealthy_bots

    def _log_bot_health_issues(self, bot):
        """Log health issues for a specific bot"""
        print_log(f"⚠️ Bot {bot.username} appears unhealthy", BColors.WARNING)

        # Get detailed stats for logging
        stats = bot.irc.get_connection_stats()
        print_log(
            f"📊 {bot.username} health stats: "
            f"time_since_activity={stats['time_since_activity']:.1f}s, "
            f"connected={stats['connected']}, "
            f"running={stats['running']}",
            BColors.WARNING,
        )

    async def _reconnect_unhealthy_bots(self, unhealthy_bots):
        """Attempt to reconnect all unhealthy bots"""
        print_log(
            f"🔧 Attempting to reconnect {len(unhealthy_bots)} unhealthy bot(s)...",
            BColors.WARNING,
        )

        for bot in unhealthy_bots:
            success = await self._attempt_bot_reconnection(bot)
            if success:
                print_log(
                    f"✅ Successfully reconnected {bot.username}", BColors.OKGREEN
                )
            else:
                print_log(f"❌ Failed to reconnect {bot.username}", BColors.FAIL)

    async def _attempt_bot_reconnection(self, bot) -> bool:
        """Attempt to reconnect a bot's IRC connection"""
        try:
            if not bot.irc:
                print_log(
                    f"❌ {bot.username}: No IRC connection to reconnect", BColors.FAIL
                )
                return False

            # Force reconnection in the IRC client
            success = await bot.irc.force_reconnect()

            if success:
                # Give it a moment to stabilize
                await asyncio.sleep(2)

                # Verify the connection is actually healthy now
                if bot.irc.is_healthy():
                    return True
                print_log(
                    f"⚠️ {bot.username}: Reconnection succeeded but "
                    "health check still fails",
                    BColors.WARNING,
                )
                return False
            print_log(f"❌ {bot.username}: IRC reconnection failed", BColors.FAIL)
            return False

        except Exception as e:
            print_log(f"❌ Error reconnecting {bot.username}: {e}", BColors.FAIL)
            return False

    def _start_health_monitoring(self):
        """Start the health monitoring task"""
        if self.running:
            health_task = asyncio.create_task(self._monitor_bot_health())
            self.tasks.append(health_task)
            print_log("🔍 Started bot health monitoring", BColors.OKCYAN)
            return health_task
        return None

    def _start_task_watchdog(self):
        """Start the task watchdog monitoring"""
        if self.running:
            watchdog_task = asyncio.create_task(self._monitor_task_health())
            self.tasks.append(watchdog_task)
            print_log("🐕 Started task watchdog monitoring", BColors.OKCYAN)
            return watchdog_task
        return None

    def _save_statistics(self) -> dict[str, dict[str, int]]:
        """Save current bot statistics"""
        stats = {}
        for bot in self.bots:
            stats[bot.username] = {
                "messages_sent": bot.messages_sent,
                "colors_changed": bot.colors_changed,
            }
        print_log(
            f"💾 Saved statistics for {len(stats)} bot(s)",
            BColors.OKCYAN,
            debug_only=True,
        )
        return stats

    def _restore_statistics(self, saved_stats: dict[str, dict[str, int]]):
        """Restore bot statistics after restart"""
        restored_count = 0
        for bot in self.bots:
            if bot.username in saved_stats:
                bot.messages_sent = saved_stats[bot.username]["messages_sent"]
                bot.colors_changed = saved_stats[bot.username]["colors_changed"]
                restored_count += 1

        if restored_count > 0:
            print_log(
                f"🔄 Restored statistics for {restored_count} bot(s)",
                BColors.OKGREEN,
                debug_only=True,
            )

    def print_statistics(self):
        """Print statistics for all bots"""
        if not self.bots:
            return

        print_log("\n" + "=" * 60, BColors.PURPLE)
        print_log("📊 OVERALL STATISTICS", BColors.PURPLE)
        print_log("=" * 60, BColors.PURPLE)

        total_messages = sum(bot.messages_sent for bot in self.bots)
        total_colors = sum(bot.colors_changed for bot in self.bots)

        print_log(f"👥 Total bots: {len(self.bots)}")
        print_log(f"📩 Total messages: {total_messages}")
        print_log(f"🎨 Total color changes: {total_colors}")

        # Individual bot stats
        for bot in self.bots:
            bot.print_statistics()

    def setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown"""

        def signal_handler(signum, _frame):
            print_log(
                f"\n🔔 Received signal {signum}, initiating graceful shutdown...",
                BColors.WARNING,
            )
            self.shutdown_initiated = True
            # Save the task to prevent garbage collection (intentionally not awaited
            # in signal handler)
            _ = asyncio.create_task(self._stop_all_bots())

        # Handle SIGINT (Ctrl+C) and SIGTERM
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)


async def _setup_config_watcher(manager: BotManager, config_file: str = None):
    """Setup config file watcher if available"""
    if not config_file or not os.path.exists(config_file):
        return None

    try:
        # Create restart callback that the watcher will call
        def restart_callback(new_config):
            manager.request_restart(new_config)

        watcher = await create_config_watcher(config_file, restart_callback)

        # Register the watcher globally so config updates can pause it
        set_global_watcher(watcher)

        print_log(f"👀 Config file watcher enabled for: {config_file}", BColors.OKCYAN)
        return watcher

    except ImportError:
        print_log(
            "⚠️ Config file watching not available "
            "(install 'watchdog' package for this feature)",
            BColors.WARNING,
        )
        return None
    except Exception as e:
        print_log(f"⚠️ Failed to start config watcher: {e}", BColors.WARNING)
        return None


async def _run_main_loop(manager: BotManager):
    """Run the main bot loop handling restarts and monitoring"""
    while manager.running:
        await asyncio.sleep(1)

        # Check for shutdown
        if manager.shutdown_initiated:
            print_log("\n🛑 Shutdown initiated, stopping bots...", BColors.WARNING)
            await manager._stop_all_bots()
            break

        # Check for restart requests
        if manager.restart_requested:
            success = await manager._restart_with_new_config()
            if not success:
                print_log(
                    "❌ Failed to restart bots, continuing with previous configuration",
                    BColors.FAIL,
                )
            continue

        # Check if all tasks have completed
        if all(task.done() for task in manager.tasks):
            # All tasks completed unexpectedly - likely an error
            print_log("\n⚠️ All bot tasks have completed unexpectedly", BColors.WARNING)
            print_log(
                "💡 This usually means authentication failed or connection issues",
                BColors.OKCYAN,
            )
            print_log(
                "🔧 Please verify your Twitch API credentials are valid", BColors.OKCYAN
            )
            break


def _cleanup_watcher(watcher):
    """Clean up config watcher and global references"""
    if watcher:
        watcher.stop()

    # Clear global watcher reference
    try:
        set_global_watcher(None)
    except (ImportError, AttributeError):
        pass


async def run_bots(users_config: list[dict[str, Any]], config_file: str = None):
    """Main function to run all bots with config file watching"""
    manager = BotManager(users_config, config_file)

    # Setup signal handlers for graceful shutdown
    manager.setup_signal_handlers()

    # Setup config watcher
    watcher = await _setup_config_watcher(manager, config_file)

    try:
        # Start all bots
        success = await manager._start_all_bots()
        if not success:
            return

        print_log("\n🎮 Bots are running! Press Ctrl+C to stop.", BColors.HEADER)
        print_log(
            "💬 Start chatting in your channels to see color changes!", BColors.OKBLUE
        )
        print_log(
            "⚠️ Note: If bots exit quickly, check your Twitch credentials",
            BColors.WARNING,
        )

        # Run main loop
        await _run_main_loop(manager)

    except KeyboardInterrupt:
        print_log("\n⌨️ Keyboard interrupt received", BColors.WARNING)
    except Exception as e:
        print_log(f"❌ Fatal error: {e}", BColors.FAIL)
    finally:
        # Cleanup
        _cleanup_watcher(watcher)
        await manager._stop_all_bots()
        manager.print_statistics()
        print_log("\n👋 Goodbye!", BColors.OKBLUE)
