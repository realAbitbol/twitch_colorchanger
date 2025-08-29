"""
Bot manager for handling multiple Twitch bots
"""

import asyncio
import os
import signal
from typing import List, Dict, Any

from .bot import TwitchColorBot
from .colors import bcolors
from .utils import print_log


class BotManager:
    """Manages multiple Twitch bots"""
    
    def __init__(self, users_config: List[Dict[str, Any]], config_file: str = None):
        self.users_config = users_config
        self.config_file = config_file
        self.bots = []
        self.tasks = []
        self.running = False
        self.shutdown_initiated = False
        self.restart_requested = False
        self.new_config = None
        
    async def _start_all_bots(self):
        """Start all bots and return success status"""
        print_log(f"🚀 Starting {len(self.users_config)} bot(s)...", bcolors.HEADER)
        
        for i, user_config in enumerate(self.users_config, 1):
            try:
                bot = self._create_bot(user_config)
                if bot:
                    self.bots.append(bot)
                    
            except Exception as e:
                print_log(f"❌ Failed to create bot for user {user_config['username']}: {e}", bcolors.FAIL)
                continue
        
        if not self.bots:
            print_log("❌ No bots could be started!", bcolors.FAIL)
            return False
        
        # Start all bot tasks
        print_log(f"🎯 Launching {len(self.bots)} bot task(s)...", bcolors.OKGREEN)
        
        for bot in self.bots:
            task = asyncio.create_task(bot.start())
            self.tasks.append(task)
        
        # Give a small delay to let bots initialize
        await asyncio.sleep(1)
        
        self.running = True
        self.shutdown_initiated = False  # Reset shutdown flag for new run
        print_log("✅ All bots started successfully!", bcolors.OKGREEN)
        return True
    
    def _create_bot(self, user_config: Dict[str, Any]) -> TwitchColorBot:
        """Create a bot instance from user configuration"""
        username = user_config['username']
        token = user_config['access_token']
        
        try:
            bot = TwitchColorBot(
                token=token,
                refresh_token=user_config.get('refresh_token', ''),
                client_id=user_config.get('client_id', ''),
                client_secret=user_config.get('client_secret', ''),
                nick=username,
                channels=user_config['channels'],
                is_prime_or_turbo=user_config.get('is_prime_or_turbo', True),
                config_file=self.config_file,
                user_id=None  # Will be fetched by the bot itself
            )
            
            print_log(f"✅ Bot created for {username}", bcolors.OKGREEN)
            return bot
            
        except Exception as e:
            print_log(f"❌ Failed to create bot for {username}: {e}", bcolors.FAIL)
            raise
    
    async def _stop_all_bots(self):
        """Stop all running bots"""
        if not self.running:
            return
        
        print_log("\n🛑 Stopping all bots...", bcolors.WARNING)
        
        # Cancel all tasks
        for i, task in enumerate(self.tasks):
            try:
                if task and not task.done():
                    task.cancel()
                    print_log(f"✅ Cancelled task {i+1}", bcolors.OKGREEN)
            except Exception as e:
                print_log(f"⚠️ Error cancelling task {i+1}: {e}", bcolors.WARNING)
        
        # Close all bots
        for i, bot in enumerate(self.bots):
            try:
                if bot:
                    bot.close()
                    print_log(f"✅ Closed bot {i+1}", bcolors.OKGREEN)
            except Exception as e:
                print_log(f"⚠️ Error closing bot {i+1}: {e}", bcolors.WARNING)
        
        # Wait for tasks to finish cancellation
        if self.tasks:
            try:
                await asyncio.gather(*self.tasks, return_exceptions=True)
            except Exception as e:
                print_log(f"⚠️ Error waiting for task completion: {e}", bcolors.WARNING)
        
        self.running = False
        print_log("✅ All bots stopped", bcolors.OKGREEN)
    
    def request_restart(self, new_users_config: List[Dict[str, Any]]):
        """Request a restart with new configuration"""
        print_log("🔄 Config change detected, restarting bots...", bcolors.OKCYAN)
        self.new_config = new_users_config
        self.restart_requested = True
        
    async def _restart_with_new_config(self):
        """Restart bots with new configuration"""
        if not self.new_config:
            return False
            
        print_log("🔄 Restarting bots with new configuration...", bcolors.OKCYAN)
        
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
        
        print_log(f"📊 Config updated: {old_count} → {new_count} users", bcolors.OKCYAN)
        
        # Start with new config
        success = await self._start_all_bots()
        
        # Restore statistics for users that still exist
        if success:
            self._restore_statistics(saved_stats)
        
        # Reset restart state
        self.restart_requested = False
        self.new_config = None
        
        return success
    
    def _save_statistics(self) -> Dict[str, Dict[str, int]]:
        """Save current bot statistics"""
        stats = {}
        for bot in self.bots:
            stats[bot.username] = {
                'messages_sent': bot.messages_sent,
                'colors_changed': bot.colors_changed
            }
        print_log(f"💾 Saved statistics for {len(stats)} bot(s)", bcolors.OKCYAN, debug_only=True)
        return stats
    
    def _restore_statistics(self, saved_stats: Dict[str, Dict[str, int]]):
        """Restore bot statistics after restart"""
        restored_count = 0
        for bot in self.bots:
            if bot.username in saved_stats:
                bot.messages_sent = saved_stats[bot.username]['messages_sent']
                bot.colors_changed = saved_stats[bot.username]['colors_changed']
                restored_count += 1
        
        if restored_count > 0:
            print_log(f"🔄 Restored statistics for {restored_count} bot(s)", bcolors.OKGREEN, debug_only=True)
    
    def print_statistics(self):
        """Print statistics for all bots"""
        if not self.bots:
            return
        
        print_log("\n" + "="*60, bcolors.PURPLE)
        print_log("📊 OVERALL STATISTICS", bcolors.PURPLE)
        print_log("="*60, bcolors.PURPLE)
        
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
            print_log(f"\n🔔 Received signal {signum}, initiating graceful shutdown...", bcolors.WARNING)
            self.shutdown_initiated = True
            # Save the task to prevent garbage collection (intentionally not awaited in signal handler)
            _ = asyncio.create_task(self._stop_all_bots())
        
        # Handle SIGINT (Ctrl+C) and SIGTERM
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)


async def _setup_config_watcher(config_file: str, manager: BotManager):
    """Setup config file watcher if available"""
    if not config_file or not os.path.exists(config_file):
        return None
        
    try:
        from .config_watcher import create_config_watcher
        from .watcher_globals import set_global_watcher
        
        # Create restart callback that the watcher will call
        def restart_callback(new_config):
            manager.request_restart(new_config)
        
        watcher = await create_config_watcher(config_file, restart_callback)
        
        # Register the watcher globally so config updates can pause it
        set_global_watcher(watcher)
        
        print_log(f"👀 Config file watcher enabled for: {config_file}", bcolors.OKCYAN)
        return watcher
        
    except ImportError:
        print_log("⚠️ Config file watching not available (install 'watchdog' package for this feature)", bcolors.WARNING)
        return None
    except Exception as e:
        print_log(f"⚠️ Failed to start config watcher: {e}", bcolors.WARNING)
        return None


async def _run_main_loop(manager: BotManager):
    """Run the main bot loop handling restarts and monitoring"""
    while manager.running:
        await asyncio.sleep(1)
        
        # Check for restart requests
        if manager.restart_requested:
            success = await manager._restart_with_new_config()
            if not success:
                print_log("❌ Failed to restart bots, continuing with previous configuration", bcolors.FAIL)
            continue
        
        # Check if all tasks have completed
        if all(task.done() for task in manager.tasks):
            if manager.shutdown_initiated:
                # Normal shutdown - tasks completed as expected
                print_log("\n✅ All bot tasks completed during shutdown", bcolors.OKGREEN)
            else:
                # Unexpected completion - likely an error
                print_log("\n⚠️ All bot tasks have completed unexpectedly", bcolors.WARNING)
                print_log("💡 This usually means authentication failed or connection issues", bcolors.OKCYAN)
                print_log("🔧 Please verify your Twitch API credentials are valid", bcolors.OKCYAN)
            break


def _cleanup_watcher(watcher):
    """Clean up config watcher and global references"""
    if watcher:
        watcher.stop()
        
    # Clear global watcher reference
    try:
        from .watcher_globals import set_global_watcher
        set_global_watcher(None)
    except ImportError:
        pass


async def run_bots(users_config: List[Dict[str, Any]], config_file: str = None):
    """Main function to run all bots with config file watching"""
    manager = BotManager(users_config, config_file)
    
    # Setup signal handlers for graceful shutdown
    manager.setup_signal_handlers()
    
    # Setup config watcher
    watcher = await _setup_config_watcher(config_file, manager)
    
    try:
        # Start all bots
        success = await manager._start_all_bots()
        if not success:
            return
        
        print_log("\n🎮 Bots are running! Press Ctrl+C to stop.", bcolors.HEADER)
        print_log("💬 Start chatting in your channels to see color changes!", bcolors.OKBLUE)
        print_log("⚠️ Note: If bots exit quickly, check your Twitch credentials", bcolors.WARNING)
        
        # Run main loop
        await _run_main_loop(manager)
                    
    except KeyboardInterrupt:
        print_log("\n⌨️ Keyboard interrupt received", bcolors.WARNING)
    except Exception as e:
        print_log(f"❌ Fatal error: {e}", bcolors.FAIL)
    finally:
        # Cleanup
        _cleanup_watcher(watcher)
        await manager._stop_all_bots()
        manager.print_statistics()
        print_log("\n👋 Goodbye!", bcolors.OKBLUE)
