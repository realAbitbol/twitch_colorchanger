"""
Simple IRC client for Twitch - based on working implementation
"""

import socket
import threading
import time
import asyncio
from typing import List, Callable, Optional

from .colors import bcolors
from .utils import print_log


class SimpleTwitchIRC:
    """Simple IRC client for Twitch using raw sockets - based on working version"""
    
    def __init__(self, username: str, token: str, channels: List[str], 
                 on_message: Optional[Callable] = None):
        self.username = username.lower()
        self.token = token if token.startswith('oauth:') else f'oauth:{token}'
        self.channels = [ch.lower().replace('#', '') for ch in channels]
        self.on_message = on_message
        
        # IRC connection
        self.server = 'irc.chat.twitch.tv'
        self.port = 6667
        self.sock = None
        self.running = False
        self.connected = False
        
        # Message tracking
        self.message_count = 0
        self.joined_channels = set()
        
    def connect(self) -> bool:
        """Connect to Twitch IRC"""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(10.0)
            self.sock.connect((self.server, self.port))
            
            # Send authentication
            self.sock.send(f"PASS {self.token}\r\n".encode('utf-8'))
            self.sock.send(f"NICK {self.username}\r\n".encode('utf-8'))
            
            # Request capabilities
            self.sock.send("CAP REQ :twitch.tv/membership\r\n".encode('utf-8'))
            self.sock.send("CAP REQ :twitch.tv/tags\r\n".encode('utf-8'))
            self.sock.send("CAP REQ :twitch.tv/commands\r\n".encode('utf-8'))
            
            self.connected = True
            print_log(f"✅ Connected to Twitch IRC as {self.username}", bcolors.OKGREEN)
            return True
            
        except Exception as e:
            print_log(f"❌ IRC connection failed: {e}", bcolors.FAIL)
            return False
    
    def join_channel(self, channel: str):
        """Join a Twitch channel"""
        channel = channel.lower().replace('#', '')
        if self.sock and self.connected:
            self.sock.send(f"JOIN #{channel}\r\n".encode('utf-8'))
            self.joined_channels.add(channel)
            print_log(f"📺 Joined #{channel}", bcolors.OKBLUE)
    
    def parse_message(self, raw_message: str) -> Optional[dict]:
        """Parse IRC message - based on working implementation"""
        try:
            if raw_message.startswith('@'):
                parts = raw_message.split(' ', 3)
                if len(parts) >= 4:
                    _ = parts[0]  # tags (not used in current implementation)
                    prefix = parts[1]
                    command = parts[2]
                    params = parts[3]
                else:
                    return None
            else:
                parts = raw_message.split(' ', 2)
                if len(parts) >= 3:
                    prefix = parts[0]
                    command = parts[1]
                    params = parts[2]
                    # No tags in this message format
                else:
                    return None
            
            if '!' in prefix:
                sender = prefix.split('!')[0].replace(':', '')
            else:
                sender = prefix.replace(':', '')
            
            if command == 'PRIVMSG':
                channel_msg = params.split(' :', 1)
                if len(channel_msg) >= 2:
                    channel = channel_msg[0].replace('#', '')
                    message = channel_msg[1]
                    
                    return {
                        'sender': sender,
                        'channel': channel,
                        'message': message,
                        'command': command,
                        'raw': raw_message
                    }
            elif command == '366':  # RPL_ENDOFNAMES - successful join
                channel = params.split(' ')[1].replace('#', '')
                print_log(f"✅ Successfully joined #{channel}", bcolors.OKGREEN)
                return None
            
            return None
            
        except Exception as e:
            print_log(f"⚠️ Parse error: {e}", bcolors.WARNING)
            return None
    
    def _handle_ping(self, line: str):
        """Handle PING messages"""
        pong = line.replace('PING', 'PONG')
        self.sock.send(f"{pong}\r\n".encode('utf-8'))
        print_log("🏓 Responded to PING", bcolors.OKCYAN, debug_only=True)
    
    def _handle_privmsg(self, parsed: dict):
        """Handle PRIVMSG messages"""
        self.message_count += 1
        sender = parsed['sender']
        channel = parsed['channel']
        message = parsed['message']
        
        # Log message - only show other users' messages in debug mode
        display_msg = message[:50] + ('...' if len(message) > 50 else '')
        is_own_message = sender.lower() == self.username.lower()
        debug_only = not is_own_message  # Only show other users' messages in debug mode
        color = bcolors.OKCYAN if is_own_message else bcolors.OKBLUE
        print_log(f"💬 #{self.message_count}: {sender} in #{channel}: {display_msg}", color, debug_only=debug_only)
        
        # Call message handler
        if self.on_message:
            self.on_message(sender, channel, message)
    
    def _process_line(self, line: str):
        """Process a single IRC line"""
        if line.startswith('PING'):
            self._handle_ping(line)
            return
        
        # Parse message
        parsed = self.parse_message(line)
        if parsed and parsed.get('command') == 'PRIVMSG':
            self._handle_privmsg(parsed)
    
    def listen(self):
        """Main listening loop"""
        buffer = ""
        
        while self.running and self.connected:
            try:
                data = self.sock.recv(4096).decode('utf-8', errors='ignore')
                if not data:
                    print_log("❌ IRC connection lost", bcolors.FAIL)
                    break
                    
                buffer += data
                
                while '\r\n' in buffer:
                    line, buffer = buffer.split('\r\n', 1)
                    if line:
                        self._process_line(line)
                        
            except socket.timeout:
                continue
            except Exception as e:
                print_log(f"❌ Listen error: {e}", bcolors.FAIL)
                break
    
    def start(self):
        """Start IRC connection"""
        if not self.connect():
            return False
        
        self.running = True
        
        # Join channels
        time.sleep(2)  # Give IRC time to authenticate
        for channel in self.channels:
            self.join_channel(channel)
        
        # Start listening in background thread
        listen_thread = threading.Thread(target=self.listen, daemon=True)
        listen_thread.start()
        
        print_log(f"🔍 IRC monitoring started. Joined {len(self.channels)} channels.", bcolors.OKGREEN)
        return True
    
    def stop(self):
        """Stop IRC connection"""
        self.running = False
        self.connected = False
        if self.sock:
            try:
                self.sock.close()
            except (OSError, socket.error):
                pass
        print_log("📡 IRC connection stopped", bcolors.OKBLUE)
