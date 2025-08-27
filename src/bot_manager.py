"""
Bot manager for handling multiple Twitch bots
"""

import asyncio
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
                use_random_colors=user_config.get('use_random_colors', True),
                config_file=self.config_file,
                user_id=None  # Will be fetched by the bot itself
            )
            
            print_log(f"✅ Bot created for {username}", bcolors.OKGREEN)
            return bot
            
        except Exception as e:
            print_log(f"❌ Failed to create bot for {username}: {e}", bcolors.FAIL)
            raise
    
    async def _wait_for_completion(self):
        """Wait for all bot tasks to complete or keep running if they fail"""
        if not self.tasks:
            return
        
        try:
            # Wait for all tasks to complete, but handle failures gracefully
            results = await asyncio.gather(*self.tasks, return_exceptions=True)
            
            # Check if any tasks failed due to authentication issues
            failed_tasks = 0
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    print_log(f"⚠️ Bot task {i+1} failed: {result}", bcolors.WARNING)
                    failed_tasks += 1
            
            if failed_tasks > 0:
                print_log(f"⚠️ {failed_tasks}/{len(self.tasks)} bot tasks failed", bcolors.WARNING)
                print_log("💡 This is usually due to invalid/expired Twitch credentials", bcolors.OKCYAN)
                print_log("🔧 Please update your tokens in the configuration", bcolors.OKCYAN)
            
        except Exception as e:
            print_log(f"❌ Error in bot tasks: {e}", bcolors.FAIL)
        
        finally:
            self.running = False
    
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
            # Save the task to prevent garbage collection (intentionally not awaited in signal handler)
            _ = asyncio.create_task(self._stop_all_bots())
        
        # Handle SIGINT (Ctrl+C) and SIGTERM
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)


async def run_bots(users_config: List[Dict[str, Any]], config_file: str = None):
    """Main function to run all bots"""
    manager = BotManager(users_config, config_file)
    
    # Setup signal handlers for graceful shutdown
    manager.setup_signal_handlers()
    
    try:
        # Start all bots
        success = await manager._start_all_bots()
        if not success:
            return
        
        print_log("\n🎮 Bots are running! Press Ctrl+C to stop.", bcolors.HEADER)
        print_log("💬 Start chatting in your channels to see color changes!", bcolors.OKBLUE)
        print_log("⚠️ Note: If bots exit quickly, check your Twitch credentials", bcolors.WARNING)
        
        # Keep running until interrupted
        try:
            # Instead of waiting for completion, keep running until interrupted
            while manager.running:
                await asyncio.sleep(1)
                
                # Check if all tasks have completed (likely due to errors)
                if all(task.done() for task in manager.tasks):
                    print_log("\n⚠️ All bot tasks have completed unexpectedly", bcolors.WARNING)
                    print_log("💡 This usually means authentication failed or connection issues", bcolors.OKCYAN)
                    print_log("🔧 Please verify your Twitch API credentials are valid", bcolors.OKCYAN)
                    break
                    
        except KeyboardInterrupt:
            print_log("\n⌨️ Keyboard interrupt received", bcolors.WARNING)
        
    except Exception as e:
        print_log(f"❌ Fatal error: {e}", bcolors.FAIL)
        
    finally:
        # Ensure cleanup
        await manager._stop_all_bots()
        
        # Print final statistics
        manager.print_statistics()
        
        print_log("\n👋 Goodbye!", bcolors.OKBLUE)
