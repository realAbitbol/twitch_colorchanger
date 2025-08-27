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
        
    async def start_all_bots(self):
        """Start all bots for configured users"""
        print_log(f"\n🚀 Starting {len(self.users_config)} bot(s)...", bcolors.HEADER)
        
        for i, user_config in enumerate(self.users_config, 1):
            try:
                bot = self.create_bot(user_config, i)
                if bot:
                    self.bots.append(bot)
                    
            except Exception as e:
                print_log(f"❌ Failed to create bot for user {user_config['username']}: {e}", bcolors.FAIL)
                continue
        
        if not self.bots:
            print_log("❌ No bots could be started!", bcolors.FAIL)
            return False
        
        # Start all bot tasks
        print_log(f"\n🎯 Launching {len(self.bots)} bot task(s)...", bcolors.OKGREEN)
        
        for bot in self.bots:
            task = asyncio.create_task(bot.start())
            self.tasks.append(task)
        
        # Give a small delay to let bots initialize
        await asyncio.sleep(1)
        
        self.running = True
        print_log("✅ All bots started successfully!", bcolors.OKGREEN)
        return True
    
    def create_bot(self, user_config: Dict[str, Any], user_num: int) -> TwitchColorBot:
        """Create a single bot instance"""
        username = user_config['username']
        print_log(f"👤 Creating bot for user {user_num}: {username}", bcolors.OKCYAN)
        
        # Get token from config (no oauth prefix manipulation needed)
        token = user_config['access_token']
        # Ensure oauth prefix for twitchio Bot constructor
        if not token.startswith('oauth:'):
            token = f"oauth:{token}"
        
        try:
            bot = TwitchColorBot(
                token=token,
                refresh_token=user_config.get('refresh_token', ''),
                client_id=user_config.get('client_id', ''),
                client_secret=user_config.get('client_secret', ''),
                nick=username,
                channels=user_config['channels'],
                use_random_colors=user_config.get('use_random_colors', True),
                config_file=self.config_file
            )
            
            print_log(f"✅ Bot created for {username}", bcolors.OKGREEN)
            return bot
            
        except Exception as e:
            print_log(f"❌ Failed to create bot for {username}: {e}", bcolors.FAIL)
            raise
    
    async def wait_for_completion(self):
        """Wait for all bot tasks to complete"""
        if not self.tasks:
            return
        
        try:
            # Wait for all tasks to complete
            await asyncio.gather(*self.tasks, return_exceptions=True)
            
        except Exception as e:
            print_log(f"❌ Error in bot tasks: {e}", bcolors.FAIL)
        
        finally:
            self.running = False
    
    async def stop_all_bots(self):
        """Stop all running bots"""
        if not self.running:
            return
        
        print_log("\n🛑 Stopping all bots...", bcolors.WARNING)
        
        # Cancel all tasks
        for task in self.tasks:
            if not task.done():
                task.cancel()
        
        # Close all bots
        for bot in self.bots:
            try:
                await bot.close()
            except Exception as e:
                print_log(f"⚠️ Error closing bot: {e}", bcolors.WARNING)
        
        # Wait for tasks to finish cancellation
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        
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
        def signal_handler(signum, frame):
            print_log(f"\n🔔 Received signal {signum}, initiating graceful shutdown...", bcolors.WARNING)
            asyncio.create_task(self.stop_all_bots())
        
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
        success = await manager.start_all_bots()
        if not success:
            return
        
        print_log("\n🎮 Bots are running! Press Ctrl+C to stop.", bcolors.HEADER)
        print_log("💬 Start chatting in your channels to see color changes!", bcolors.OKBLUE)
        
        # Keep running until interrupted
        try:
            await manager.wait_for_completion()
        except KeyboardInterrupt:
            print_log("\n⌨️ Keyboard interrupt received", bcolors.WARNING)
        
    except Exception as e:
        print_log(f"❌ Fatal error: {e}", bcolors.FAIL)
        
    finally:
        # Ensure cleanup
        await manager.stop_all_bots()
        
        # Print final statistics
        manager.print_statistics()
        
        print_log("\n👋 Goodbye!", bcolors.OKBLUE)
