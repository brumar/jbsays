#!/usr/bin/env python3
"""
Multi-Project Telegram Inbox Bot
Monitors multiple project inbox/to_human/ directories and sends notifications
Receives responses and writes them to the appropriate inbox/from_human/
"""

import os
import json
import time
import asyncio
from pathlib import Path
from datetime import datetime
import logging
import hashlib
from queue import Queue
from threading import Thread, Lock
from typing import Dict, List, Tuple, Optional
from concurrent.futures import ThreadPoolExecutor
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
import subprocess

# Configuration file paths
CONFIG_FILE = Path.home() / ".telegram_inbox_bot" / "config.json"
PROCESSED_FILES_DIR = Path.home() / ".telegram_inbox_bot" / "processed"
RETRY_QUEUE_FILE = Path.home() / ".telegram_inbox_bot" / "retry_queue.json"
SECURITY_CONFIG_FILE = Path(__file__).parent / "telegram_bot_config.json"
PROJECT_MANAGER_SCRIPT = Path(__file__).parent / "project_manager.sh"
PROJECTS_JSON_FILE = Path(__file__).parent / "projects.json"

# Load security configuration
def load_security_config():
    """Load security configuration with user whitelist"""
    try:
        if SECURITY_CONFIG_FILE.exists():
            with open(SECURITY_CONFIG_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Error loading security config: {e}")
    return {"allowed_user_ids": []}

# Security configuration
SECURITY_CONFIG = load_security_config()
ALLOWED_USER_IDS = SECURITY_CONFIG.get("allowed_user_ids", [])

# Predefined messages configuration
PREDEFINED_MESSAGES = {
    "check_inbox": "Please ask me a lot more for decisions and share more your roadblocks. Check your inbox every minute for 5 minutes without working on something else.",
    "work_independently": "You can now work more independently. Resume your normal workflow.",
    "status": "Please provide a status update on the current task.",
    "explain": "Can you explain the current implementation in more detail?",
    "continue": "Please continue with the task.",
    "test": "Please run the tests and report the results.",
    "fix": "Please fix any errors or issues you've encountered.",
    "optimize": "Can you optimize this code for better performance?",
    "document": "Please add documentation for this code.",
    "review": "Please review the current implementation and suggest improvements.",
    "debug": "Please help debug this issue.",
    "refactor": "Can you refactor this code to be cleaner?",
    "implement": "Please implement this feature.",
    "custom": "[CUSTOM MESSAGE]"
}

# Authentication decorator
def require_auth(func):
    """Decorator to require authentication for commands"""
    async def wrapper(update, context):
        user_id = update.effective_user.id
        if user_id not in ALLOWED_USER_IDS:
            await update.message.reply_text("⛔ Unauthorized access. This bot is private.")
            logger.warning(f"Unauthorized access attempt from user ID: {user_id}")
            return
        return await func(update, context)
    return wrapper

# Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class ProcessedFilesTracker:
    """Persistent tracking of processed files"""
    
    def __init__(self):
        self.processed_dir = PROCESSED_FILES_DIR
        self.processed_dir.mkdir(parents=True, exist_ok=True)
        self.lock = Lock()
    
    def _get_file_hash(self, file_path):
        """Get hash of file content for tracking"""
        try:
            with open(file_path, 'rb') as f:
                content = f.read()
            return hashlib.md5(content).hexdigest()
        except:
            return None
    
    def _get_processed_file_path(self, project_name):
        """Get path to processed files list for project"""
        return self.processed_dir / f"{project_name}_processed.json"
    
    def load_processed_files(self, project_name):
        """Load processed files for a project"""
        processed_file = self._get_processed_file_path(project_name)
        if processed_file.exists():
            try:
                with open(processed_file, 'r') as f:
                    return json.load(f)
            except:
                return {}
        return {}
    
    def save_processed_files(self, project_name, processed_files):
        """Save processed files for a project"""
        processed_file = self._get_processed_file_path(project_name)
        with self.lock:
            with open(processed_file, 'w') as f:
                json.dump(processed_files, f, indent=2)
    
    def is_file_processed(self, project_name, file_path):
        """Check if file has been processed"""
        processed_files = self.load_processed_files(project_name)
        file_key = f"{file_path.name}_{file_path.stat().st_mtime}"
        file_hash = self._get_file_hash(file_path)
        
        if file_key in processed_files:
            stored_hash = processed_files[file_key].get('hash')
            return stored_hash == file_hash
        return False
    
    def mark_file_processed(self, project_name, file_path):
        """Mark file as processed"""
        processed_files = self.load_processed_files(project_name)
        file_key = f"{file_path.name}_{file_path.stat().st_mtime}"
        file_hash = self._get_file_hash(file_path)
        
        processed_files[file_key] = {
            'hash': file_hash,
            'processed_at': datetime.now().isoformat(),
            'file_size': file_path.stat().st_size
        }
        
        self.save_processed_files(project_name, processed_files)

class RetryQueue:
    """Queue for retrying failed Telegram sends"""
    
    def __init__(self):
        self.queue_file = RETRY_QUEUE_FILE
        self.queue = Queue()
        self.lock = Lock()
        self.load_queue()
    
    def load_queue(self):
        """Load retry queue from disk"""
        if self.queue_file.exists():
            try:
                with open(self.queue_file, 'r') as f:
                    items = json.load(f)
                for item in items:
                    self.queue.put(item)
            except:
                pass
    
    def save_queue(self):
        """Save retry queue to disk"""
        items = []
        temp_queue = Queue()
        
        while not self.queue.empty():
            item = self.queue.get()
            items.append(item)
            temp_queue.put(item)
        
        # Restore queue
        while not temp_queue.empty():
            self.queue.put(temp_queue.get())
        
        with self.lock:
            with open(self.queue_file, 'w') as f:
                json.dump(items, f, indent=2)
    
    def add_retry(self, message_data):
        """Add message to retry queue"""
        # Remove non-serializable objects
        clean_data = message_data.copy()
        clean_data.pop('reply_markup', None)  # Remove InlineKeyboardMarkup
        
        retry_item = {
            'message_data': clean_data,
            'retry_count': clean_data.get('retry_count', 0) + 1,
            'added_at': datetime.now().isoformat()
        }
        self.queue.put(retry_item)
        self.save_queue()
    
    def get_retry(self):
        """Get next item from retry queue"""
        if not self.queue.empty():
            item = self.queue.get()
            self.save_queue()
            return item
        return None

class Config:
    """Handle configuration for multiple projects"""
    
    def __init__(self):
        self.config_dir = CONFIG_FILE.parent
        self.config_dir.mkdir(exist_ok=True)
        self.load()
    
    def load(self):
        """Load configuration from file"""
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, 'r') as f:
                data = json.load(f)
                self.bot_token = data.get('bot_token', '')
                self.chat_id = data.get('chat_id', '')
                self.projects = data.get('projects', {})
        else:
            self.bot_token = ''
            self.chat_id = ''
            self.projects = {}
            self.save()
    
    def save(self):
        """Save configuration to file"""
        data = {
            'bot_token': self.bot_token,
            'chat_id': self.chat_id,
            'projects': self.projects
        }
        with open(CONFIG_FILE, 'w') as f:
            json.dump(data, f, indent=2)
    
    def add_project(self, name, path):
        """Add a project to monitor"""
        self.projects[name] = {
            'path': str(Path(path).resolve()),
            'enabled': True,
            'last_check': None
        }
        self.save()
    
    def remove_project(self, name):
        """Remove a project"""
        if name in self.projects:
            del self.projects[name]
            self.save()
    
    def toggle_project(self, name):
        """Enable/disable a project"""
        if name in self.projects:
            self.projects[name]['enabled'] = not self.projects[name]['enabled']
            self.save()

class MultiProjectInboxWatcher(FileSystemEventHandler):
    """Watches for new files in multiple project inbox/to_human/ directories"""
    
    def __init__(self, bot_instance, config, processed_tracker, retry_queue):
        self.bot = bot_instance
        self.config = config
        self.processed_tracker = processed_tracker
        self.retry_queue = retry_queue
        self.application = None  # Will be set by main
        self.processing_files = set()  # Track files currently being processed
        self.processing_lock = Lock()
    
    def on_created(self, event):
        if not event.is_directory and event.src_path.endswith('.md'):
            self.process_event(event)
    
    def on_modified(self, event):
        # Skip modified events to prevent duplicates
        # on_created is sufficient for new files
        pass
    
    def process_event(self, event):
        """Process file events and determine which project they belong to"""
        file_path = Path(event.src_path)
        
        # Check if file is already being processed
        with self.processing_lock:
            file_key = str(file_path)
            if file_key in self.processing_files:
                logger.debug(f"File already being processed: {file_path}")
                return
            self.processing_files.add(file_key)
        
        try:
            # Find which project this file belongs to
            for project_name, project_info in self.config.projects.items():
                if not project_info['enabled']:
                    continue
                    
                project_inbox = Path(project_info['path']) / "inbox" / "to_human"
                if str(project_inbox) in str(file_path):
                    # Check if already processed using persistent tracker
                    if not self.processed_tracker.is_file_processed(project_name, file_path):
                        self.process_new_message(file_path, project_name)
                    break
        finally:
            # Remove from processing set
            with self.processing_lock:
                self.processing_files.discard(file_key)
    
    def process_new_message(self, file_path, project_name):
        """Read and send the message via Telegram"""
        logger.info(f"Processing new file: {file_path}")
        try:
            with open(file_path, 'r') as f:
                content = f.read()
            
            # Format message with project context - NO TRUNCATION
            message = f"📥 New Message from Project: {project_name}\n\n"
            message += f"File: {file_path.name}\n"
            message += f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            message += f"Size: {len(content)} characters\n\n"
            message += f"--- CONTENT ---\n{content}"
            
            # Create inline keyboard for quick actions
            # Ensure callback_data is within 64 byte limit
            # Use shortened versions if needed
            reply_data = f"r:{project_name[:20]}:{file_path.name[:20]}"
            project_data = f"p:{project_name[:40]}"
            
            # Ensure data is within limits
            if len(reply_data.encode('utf-8')) > 64:
                reply_data = f"r:{project_name[:10]}:{file_path.name[:10]}"
            if len(project_data.encode('utf-8')) > 64:
                project_data = f"p:{project_name[:30]}"
            
            keyboard = [
                [
                    InlineKeyboardButton("📝 Reply", callback_data=reply_data),
                    InlineKeyboardButton("📂 Open Project", callback_data=project_data)
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Prepare message data for sending
            message_data = {
                'message': message,
                'reply_markup': reply_markup,
                'chat_id': self.config.chat_id,
                'project_name': project_name,
                'file_path': str(file_path),
                'file_name': file_path.name,
                'retry_count': 0
            }
            
            # Use application's event loop to handle async operations from sync context
            if self.application and hasattr(self.application, 'loop') and self.application.loop and not self.application.loop.is_closed():
                try:
                    # Schedule the coroutine in the application's event loop
                    future = asyncio.run_coroutine_threadsafe(
                        self.send_telegram_message_safe(message_data),
                        self.application.loop
                    )
                    # Wait a bit to ensure it's scheduled
                    future.result(timeout=1.0)
                except Exception as e:
                    logger.error(f"Error scheduling message send: {e}")
                    # Add to retry queue as fallback
                    self.retry_queue.add_retry(message_data)
            else:
                # Log error if no event loop available
                logger.error(f"No valid event loop available to send message for {file_path}")
                # Add to retry queue as fallback
                self.retry_queue.add_retry(message_data)
            
        except Exception as e:
            logger.error(f"Error processing file {file_path}: {e}")
    
    async def send_telegram_message_safe(self, message_data):
        """Send message to Telegram with retry mechanism"""
        try:
            # Split message if it's too long for Telegram (4096 char limit)
            message = message_data['message']
            chat_id = message_data['chat_id']
            
            # Recreate reply_markup if it's missing (from retry queue)
            reply_markup = message_data.get('reply_markup')
            if not reply_markup and 'file_name' in message_data:
                project_name = message_data['project_name']
                file_name = message_data['file_name']
                keyboard = [
                    [
                        InlineKeyboardButton("📝 Reply", callback_data=f"reply:{project_name}:{file_name}"),
                        InlineKeyboardButton("📂 Open Project", callback_data=f"project:{project_name}")
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
            
            if len(message) <= 4096:
                # Send as single message
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode=None,  # Disable parsing to avoid errors
                    reply_markup=reply_markup
                )
            else:
                # Split into multiple messages
                parts = self.split_message(message)
                for i, part in enumerate(parts):
                    # Only add keyboard to last message
                    markup = reply_markup if i == len(parts) - 1 else None
                    await self.bot.send_message(
                        chat_id=chat_id,
                        text=part,
                        parse_mode=None,  # Disable parsing to avoid errors
                        reply_markup=markup
                    )
                    # Add delay between messages to avoid flood control
                    if i < len(parts) - 1:
                        await asyncio.sleep(0.5)
            
            # Mark as processed on successful send
            project_name = message_data['project_name']
            file_path = Path(message_data['file_path'])
            self.processed_tracker.mark_file_processed(project_name, file_path)
            
            logger.info(f"Successfully sent message for {file_path.name}")
            
        except Exception as e:
            logger.error(f"Error sending Telegram message: {e}")
            
            # Handle flood control specifically
            if "flood control" in str(e).lower():
                # Extract retry time if possible
                import re
                match = re.search(r'retry in (\d+) seconds', str(e).lower())
                if match:
                    wait_time = int(match.group(1))
                    logger.info(f"Flood control: waiting {wait_time} seconds before retry")
                    await asyncio.sleep(wait_time)
            
            # Add to retry queue if not too many retries
            retry_count = message_data.get('retry_count', 0)
            if retry_count < 3:
                self.retry_queue.add_retry(message_data)
                logger.info(f"Added message to retry queue (attempt {retry_count + 1})")
    
    def split_message(self, message):
        """Split long message into Telegram-compatible chunks"""
        max_length = 4096
        if len(message) <= max_length:
            return [message]
        
        parts = []
        lines = message.split('\n')
        current_part = ""
        
        for line in lines:
            if len(current_part) + len(line) + 1 <= max_length:
                current_part += line + '\n'
            else:
                if current_part:
                    parts.append(current_part.rstrip())
                    current_part = line + '\n'
                else:
                    # Line itself is too long, split it
                    while len(line) > max_length:
                        parts.append(line[:max_length])
                        line = line[max_length:]
                    current_part = line + '\n'
        
        if current_part:
            parts.append(current_part.rstrip())
        
        return parts
    
    def scan_existing_files(self):
        """Scan existing files on startup to catch any missed messages"""
        logger.info("Scanning existing files for unprocessed messages...")
        
        # Use asyncio to add delays between messages
        async def scan_with_delay():
            message_count = 0
            current_time = time.time()
            max_age_seconds = 3 * 60 * 60  # 3 hours in seconds
            
            for project_name, project_info in self.config.projects.items():
                if not project_info['enabled']:
                    continue
                
                project_inbox = Path(project_info['path']) / "inbox" / "to_human"
                if not project_inbox.exists():
                    continue
                
                for file_path in project_inbox.glob("*.md"):
                    # Check if file is less than 3 hours old
                    file_age_seconds = current_time - file_path.stat().st_mtime
                    
                    if file_age_seconds > max_age_seconds:
                        continue  # Skip files older than 3 hours
                    
                    if not self.processed_tracker.is_file_processed(project_name, file_path):
                        logger.info(f"Found fresh unprocessed file (age: {file_age_seconds/60:.1f} minutes): {file_path}")
                        self.process_new_message(file_path, project_name)
                        message_count += 1
                        # Add delay every 3 messages to avoid flood control
                        if message_count % 3 == 0:
                            await asyncio.sleep(1)
            
            if message_count > 0:
                logger.info(f"Processed {message_count} fresh unprocessed files")
            else:
                logger.info("No fresh unprocessed files found (younger than 3 hours)")
        
        # Run the scan asynchronously with proper event loop handling
        if self.application and self.application.loop:
            # Schedule in the application's event loop
            asyncio.run_coroutine_threadsafe(scan_with_delay(), self.application.loop)
        else:
            # This method should only be called after application is initialized
            logger.warning("scan_existing_files called before application is ready")

class ProjectLauncher:
    """Handle non-blocking container launches using threads"""
    
    def __init__(self, bot, chat_id):
        self.bot = bot
        self.chat_id = chat_id
        self.script_path = PROJECT_MANAGER_SCRIPT
        self.projects_json = PROJECTS_JSON_FILE
        self.active_launches = {}  # Track active launch tasks
        self.executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="container-launcher")
        self.loop = None
        
    def set_event_loop(self, loop):
        """Set the event loop for async operations"""
        self.loop = loop
    
    def _run_command_sync(self, cmd: List[str], timeout: int = 30) -> Tuple[bool, str]:
        """Run command synchronously in thread"""
        try:
            logger.info(f"Running command in thread: {' '.join(cmd)}")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            success = result.returncode == 0
            output = result.stdout if success else result.stderr
            return success, output
        except subprocess.TimeoutExpired:
            return False, f"Command timed out after {timeout} seconds"
        except Exception as e:
            return False, str(e)
    
    def _check_container_sync(self, container_name: str) -> bool:
        """Check if container is running synchronously"""
        try:
            result = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Running}}", container_name],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.returncode == 0 and result.stdout.strip() == "true"
        except:
            return False
    
    async def start_project_nonblocking(self, project_name: str, overrides: List[str] = None) -> Tuple[bool, str]:
        """Start a project without blocking the bot"""
        cmd = [str(self.script_path), "start", project_name]
        if overrides:
            cmd.extend(overrides)
        
        # Mark as launching
        self.active_launches[project_name] = {
            'started_at': datetime.now(),
            'status': 'launching'
        }
        
        # Run in thread pool to avoid blocking
        if self.loop:
            self.loop.call_soon_threadsafe(
                asyncio.create_task,
                self._launch_in_thread(project_name, cmd)
            )
        
        return True, f"🚀 Starting project '{project_name}' in background..."
    
    async def _launch_in_thread(self, project_name: str, cmd: List[str]):
        """Launch container in background thread"""
        try:
            # Run the command in thread pool
            success, output = await self.loop.run_in_executor(
                self.executor,
                self._run_command_sync,
                cmd,
                30  # timeout
            )
            
            if success:
                # Check if container is actually running
                container_name = await self.loop.run_in_executor(
                    self.executor,
                    self._get_container_name_sync,
                    project_name
                )
                
                if container_name:
                    is_running = await self.loop.run_in_executor(
                        self.executor,
                        self._check_container_sync,
                        container_name
                    )
                    
                    if is_running:
                        self.active_launches[project_name]['status'] = 'started'
                        await self._send_notification(
                            f"✅ Project '{project_name}' started successfully!"
                        )
                    else:
                        # Wait a bit and check again
                        await asyncio.sleep(2)
                        is_running = await self.loop.run_in_executor(
                            self.executor,
                            self._check_container_sync,
                            container_name
                        )
                        
                        if is_running:
                            self.active_launches[project_name]['status'] = 'started'
                            await self._send_notification(
                                f"✅ Project '{project_name}' started successfully!"
                            )
                        else:
                            self.active_launches[project_name]['status'] = 'failed'
                            await self._send_notification(
                                f"⚠️ Project '{project_name}' script completed but container not running"
                            )
                else:
                    self.active_launches[project_name]['status'] = 'failed'
                    await self._send_notification(
                        f"⚠️ Project '{project_name}': No container configured"
                    )
            else:
                self.active_launches[project_name]['status'] = 'failed'
                await self._send_notification(
                    f"❌ Failed to start '{project_name}':\n{output[:200]}"
                )
        
        except Exception as e:
            logger.error(f"Error in _launch_in_thread for {project_name}: {e}")
            self.active_launches[project_name]['status'] = 'failed'
            await self._send_notification(
                f"❌ Error launching '{project_name}': {str(e)}"
            )
        
        finally:
            # Clean up after some time
            await asyncio.sleep(60)
            if project_name in self.active_launches:
                del self.active_launches[project_name]
    
    def _get_container_name_sync(self, project_name: str) -> Optional[str]:
        """Get container name from projects.json synchronously"""
        try:
            with open(self.projects_json, 'r') as f:
                data = json.load(f)
            return data.get('projects', {}).get(project_name, {}).get('container_name')
        except Exception as e:
            logger.error(f"Error reading projects.json: {e}")
            return None
    
    async def _get_container_name(self, project_name: str) -> Optional[str]:
        """Get container name asynchronously"""
        return await self.loop.run_in_executor(
            self.executor,
            self._get_container_name_sync,
            project_name
        )
    
    async def _is_container_running(self, container_name: str) -> bool:
        """Check if container is running asynchronously"""
        return await self.loop.run_in_executor(
            self.executor,
            self._check_container_sync,
            container_name
        )
    
    async def _send_notification(self, message: str, parse_mode=None):
        """Send notification to Telegram chat"""
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode=parse_mode
            )
        except Exception as e:
            logger.error(f"Error sending notification: {e}")
    
    async def stop_project(self, project_name: str) -> Tuple[bool, str]:
        """Stop a project container using thread pool"""
        cmd = [str(self.script_path), "stop", project_name]
        
        try:
            success, output = await self.loop.run_in_executor(
                self.executor,
                self._run_command_sync,
                cmd,
                10  # timeout
            )
            
            if success:
                return True, f"🛑 Project '{project_name}' stopped"
            else:
                return False, f"Failed to stop: {output}"
                
        except Exception as e:
            logger.error(f"Error stopping project: {e}")
            return False, str(e)
    
    def get_active_launches(self) -> Dict[str, Dict]:
        """Get currently active launches"""
        return self.active_launches.copy()

# Global variables
config = None
watchers = {}
observers = {}
processed_tracker = None
retry_queue = None
project_launcher = None

@require_auth
async def start_command(update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    chat_id = update.effective_chat.id
    
    # Save chat ID if not already saved
    if not config.chat_id:
        config.chat_id = str(chat_id)
        config.save()
    
    message = f"🤖 Multi-Project Inbox Bot Started!\n\n"
    message += f"Your Chat ID: {chat_id}\n\n"
    message += "Commands:\n"
    message += "/add <name> <path> - Add a project\n"
    message += "/remove <name> - Remove a project\n"
    message += "/list - List all projects\n"
    message += "/toggle <name> - Enable/disable project\n"
    message += "/short - Send predefined message to AI\n"
    message += "/status - Show bot status\n"
    message += "/config - Show configuration\n\n"
    message += "💡 Containers auto-start when you send messages!"
    
    await update.message.reply_text(message)

@require_auth
async def add_project(update, context: ContextTypes.DEFAULT_TYPE):
    """Add a new project to monitor"""
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /add <project_name> <project_path>")
        return
    
    project_name = context.args[0]
    project_path = ' '.join(context.args[1:])
    
    # Validate path
    path = Path(project_path).resolve()
    if not path.exists():
        await update.message.reply_text(f"❌ Path does not exist: {project_path}")
        return
    
    inbox_path = path / "inbox" / "to_human"
    inbox_path.mkdir(parents=True, exist_ok=True)
    
    # Add to config
    config.add_project(project_name, str(path))
    
    # Start monitoring
    start_monitoring_project(project_name)
    
    await update.message.reply_text(
        f"✅ Added project '{project_name}' at:\n`{path}`\n\n"
        f"Monitoring: `{inbox_path}`"
    )

@require_auth
async def remove_project(update, context: ContextTypes.DEFAULT_TYPE):
    """Remove a project"""
    if not context.args:
        await update.message.reply_text("Usage: /remove <project_name>")
        return
    
    project_name = context.args[0]
    
    if project_name not in config.projects:
        await update.message.reply_text(f"❌ Project '{project_name}' not found")
        return
    
    # Stop monitoring
    stop_monitoring_project(project_name)
    
    # Remove from config
    config.remove_project(project_name)
    
    await update.message.reply_text(f"✅ Removed project '{project_name}'")

@require_auth
async def list_projects(update, context: ContextTypes.DEFAULT_TYPE):
    """List all monitored projects"""
    if not config.projects:
        await update.message.reply_text("📭 No projects configured")
        return
    
    message = "📋 Monitored Projects:\n\n"
    for name, info in config.projects.items():
        status = "🟢" if info['enabled'] else "🔴"
        message += f"{status} {name}\n"
        message += f"   Path: {info['path']}\n\n"
    
    await update.message.reply_text(message)

@require_auth
async def toggle_project(update, context: ContextTypes.DEFAULT_TYPE):
    """Enable/disable a project"""
    if not context.args:
        await update.message.reply_text("Usage: /toggle <project_name>")
        return
    
    project_name = context.args[0]
    
    if project_name not in config.projects:
        await update.message.reply_text(f"❌ Project '{project_name}' not found")
        return
    
    config.toggle_project(project_name)
    
    if config.projects[project_name]['enabled']:
        start_monitoring_project(project_name)
        await update.message.reply_text(f"🟢 Enabled project '{project_name}'")
    else:
        stop_monitoring_project(project_name)
        await update.message.reply_text(f"🔴 Disabled project '{project_name}'")


@require_auth
async def status_command(update, context: ContextTypes.DEFAULT_TYPE):
    """Show bot and container status"""
    message = "🤖 Bot Status\n\n"
    
    # Bot info
    message += f"📋 Projects monitored: {len(config.projects)}\n"
    enabled_count = sum(1 for p in config.projects.values() if p['enabled'])
    message += f"✅ Enabled projects: {enabled_count}\n\n"
    
    # Container status if launcher is available
    if project_launcher and config.projects:
        message += "🐳 Container Status:\n\n"
        
        for project_name in config.projects:
            container_name = await project_launcher._get_container_name(project_name)
            if container_name:
                is_running = await project_launcher._is_container_running(container_name)
                status_emoji = "🟢" if is_running else "🔴"
                message += f"{status_emoji} {project_name}: {'Running' if is_running else 'Stopped'}\n"
            else:
                message += f"❓ {project_name}: No container configured\n"
        
        # Active launches
        active_launches = project_launcher.get_active_launches()
        if active_launches:
            message += f"\n🚀 Active launches: {len(active_launches)}\n"
            for name in active_launches:
                message += f"  - {name}\n"
    
    await update.message.reply_text(message)

@require_auth
async def short_command(update, context: ContextTypes.DEFAULT_TYPE):
    """Send a predefined message to a project"""
    if not config.projects:
        await update.message.reply_text("❌ No projects configured. Use /add to add a project.")
        return
    
    # Store command context
    context.user_data['predefined_mode'] = True
    
    # Create project selection keyboard
    keyboard = []
    for project_name in config.projects:
        keyboard.append([InlineKeyboardButton(
            f"📁 {project_name}", 
            callback_data=f"predefined_project:{project_name}"
        )])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "📋 Select the project to send a predefined message to:",
        reply_markup=reply_markup
    )

@require_auth
async def handle_message(update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming messages as responses"""
    # Check if we're expecting a reply to a specific message
    if context.user_data.get('reply_to'):
        reply_info = context.user_data['reply_to']
        project_name = reply_info['project']
        filename = reply_info['file']
        message_text = update.message.text
        
        # Check if project still exists
        if project_name not in config.projects:
            await update.message.reply_text(f"❌ Project '{project_name}' no longer exists")
            context.user_data['reply_to'] = None
            return
        
        # Use the common function with auto-launch
        await send_user_message_to_project(
            update.message,
            project_name,
            message_text,
            is_reply=True,
            reply_to_file=filename
        )
        
        # Clear the reply state
        context.user_data['reply_to'] = None
        return
    
    # Check if we're expecting a custom predefined message
    if context.user_data.get('pending_custom_project'):
        project_name = context.user_data['pending_custom_project']
        message_text = update.message.text
        await send_message_to_project(update.message, project_name, message_text)
        context.user_data['pending_custom_project'] = None
        context.user_data['predefined_mode'] = False
        return
    
    # Store the message in context for the callback handler
    context.user_data['last_message'] = update.message.text
    
    # Ask which project to send to
    if config.projects:
        keyboard = []
        for project_name in config.projects:
            keyboard.append([InlineKeyboardButton(
                project_name, 
                callback_data=f"send:{project_name}"
            )])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "Which project should receive this message?",
            reply_markup=reply_markup
        )
    else:
        await update.message.reply_text("❌ No projects configured. Use /add to add a project.")

@require_auth
async def button_callback(update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline keyboard callbacks"""
    query = update.callback_query
    await query.answer()
    
    data = query.data.split(':')
    action = data[0]
    
    # Handle shortened callback data
    if action == 'r':  # reply
        project_name = data[1] if len(data) > 1 else ''
        filename = data[2] if len(data) > 2 else ''
        context.user_data['reply_to'] = {'project': project_name, 'file': filename}
        await query.message.reply_text(
            f"💬 Reply to '{filename}' in project '{project_name}':\n"
            f"(Send your message and I'll save it as a response)"
        )
    
    elif action == 'p':  # project
        project_name = data[1] if len(data) > 1 else ''
        if project_name in config.projects:
            project_info = config.projects[project_name]
            await query.message.reply_text(
                f"📂 Project: {project_name}\n"
                f"📍 Path: {project_info['path']}\n"
                f"🔵 Status: {'Enabled' if project_info['enabled'] else 'Disabled'}"
            )
        else:
            await query.message.reply_text(f"❌ Unknown project: {project_name}")
    
    elif action == 'reply':  # Legacy format
        project_name = data[1]
        filename = data[2]
        context.user_data['reply_to'] = {'project': project_name, 'file': filename}
        await query.message.reply_text(
            f"💬 Reply to '{filename}' in project '{project_name}':\n"
            f"(Send your message and I'll save it as a response)"
        )
    
    elif action == 'predefined_project':
        project_name = data[1]
        context.user_data['selected_project'] = project_name
        
        # Show predefined messages
        keyboard = []
        for key, message in PREDEFINED_MESSAGES.items():
            if key == 'custom':
                display_text = "✏️ Custom Message"
            elif key == 'check_inbox':
                display_text = "🔔 Ask for decisions (check inbox frequently)"
            elif key == 'work_independently':
                display_text = "🚀 Work independently"
            else:
                # Use simpler display for common commands
                display_text = key.replace('_', ' ').title()
            
            keyboard.append([InlineKeyboardButton(
                display_text,
                callback_data=f"predefined_msg:{key}"
            )])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(
            f"📝 Select a predefined message for project '{project_name}':",
            reply_markup=reply_markup
        )
    
    elif action == 'predefined_msg':
        msg_key = data[1]
        project_name = context.user_data.get('selected_project')
        
        if not project_name:
            await query.message.edit_text("❌ Error: No project selected")
            return
        
        if msg_key == 'custom':
            context.user_data['pending_custom_project'] = project_name
            await query.message.edit_text(
                f"✏️ Send your custom message for project '{project_name}':\n"
                f"(Type your message and send it)"
            )
        else:
            # Send the predefined message
            message_text = PREDEFINED_MESSAGES.get(msg_key, "")
            await send_message_to_project(query.message, project_name, message_text)
            context.user_data['predefined_mode'] = False
            context.user_data['selected_project'] = None
    
    elif action == 'send':
        project_name = data[1]
        message_text = context.user_data.get('last_message', '')
        
        if message_text:
            # Check if this is a reply
            reply_info = context.user_data.get('reply_to')
            is_reply = reply_info and reply_info['project'] == project_name
            reply_to_file = reply_info['file'] if is_reply else None
            
            # Use the common function to send message with auto-launch
            await send_user_message_to_project(
                query.message, 
                project_name, 
                message_text,
                is_reply=is_reply,
                reply_to_file=reply_to_file
            )
            
            if is_reply:
                context.user_data['reply_to'] = None

async def send_user_message_to_project(message, project_name, text, is_reply=False, reply_to_file=None, auto_launch=True):
    """Send a user message to a project with optional auto-launch"""
    try:
        # Check if we should auto-launch the container
        if auto_launch and project_launcher:
            container_name = await project_launcher._get_container_name(project_name)
            if container_name:
                is_running = await project_launcher._is_container_running(container_name)
                if not is_running:
                    # Container not running, start it
                    await message.reply_text(f"🔄 Container for '{project_name}' is not running. Starting it...")
                    success, launch_msg = await project_launcher.start_project_nonblocking(project_name)
                    if not success:
                        await message.reply_text(f"⚠️ Failed to start container: {launch_msg}")
                        await message.reply_text("📝 Message will still be saved to inbox.")
        
        project_path = Path(config.projects[project_name]['path'])
        inbox_from = project_path / "inbox" / "from_human"
        inbox_from.mkdir(parents=True, exist_ok=True)
        
        filename = f"telegram_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        
        # Build content based on message type
        if is_reply and reply_to_file:
            content = f"# Response to: {reply_to_file}\n\n"
        else:
            content = f"# Direct Message\n\n"
        
        content += f"**From:** Telegram\n"
        content += f"**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        content += f"---\n\n"
        content += text
        
        file_path = inbox_from / filename
        with open(file_path, 'w') as f:
            f.write(content)
        
        # Update the message differently based on type
        if hasattr(message, 'edit_text'):
            await message.edit_text(
                f"✅ Message sent to project '{project_name}':\n`{filename}`"
            )
        else:
            await message.reply_text(
                f"✅ Message sent to project '{project_name}':\n`{filename}`"
            )
    except Exception as e:
        await message.reply_text(f"❌ Error sending message: {str(e)}")

async def send_message_to_project(message, project_name, text, auto_launch=True):
    """Helper function to send a message to a project's inbox/from_human/"""
    try:
        # Check if we should auto-launch the container
        if auto_launch and project_launcher:
            container_name = await project_launcher._get_container_name(project_name)
            if container_name:
                is_running = await project_launcher._is_container_running(container_name)
                if not is_running:
                    # Container not running, start it
                    await message.reply_text(f"🔄 Container for '{project_name}' is not running. Starting it...")
                    success, launch_msg = await project_launcher.start_project_nonblocking(project_name)
                    if not success:
                        await message.reply_text(f"⚠️ Failed to start container: {launch_msg}")
                        await message.reply_text("📝 Message will still be saved to inbox.")
        
        project_path = Path(config.projects[project_name]['path'])
        inbox_from = project_path / "inbox" / "from_human"
        inbox_from.mkdir(parents=True, exist_ok=True)
        
        filename = f"telegram_predefined_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        
        content = f"# Predefined Message\n\n"
        content += f"**From:** Telegram (Predefined)\n"
        content += f"**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        content += f"---\n\n"
        content += text
        
        file_path = inbox_from / filename
        with open(file_path, 'w') as f:
            f.write(content)
        
        await message.reply_text(
            f"✅ Predefined message sent to project '{project_name}':\n"
            f"📄 {filename}\n\n"
            f"Message: {text[:100]}{'...' if len(text) > 100 else ''}"
        )
    except Exception as e:
        await message.reply_text(f"❌ Error sending message: {str(e)}")

def start_monitoring_project(project_name):
    """Start monitoring a specific project"""
    if project_name in observers:
        return  # Already monitoring
    
    project_info = config.projects[project_name]
    if not project_info['enabled']:
        return
    
    inbox_path = Path(project_info['path']) / "inbox" / "to_human"
    if not inbox_path.exists():
        inbox_path.mkdir(parents=True, exist_ok=True)
    
    observer = Observer()
    observer.schedule(watchers['main'], str(inbox_path), recursive=False)
    observer.start()
    observers[project_name] = observer
    
    logger.info(f"Started monitoring project '{project_name}' at {inbox_path}")

def stop_monitoring_project(project_name):
    """Stop monitoring a specific project"""
    if project_name in observers:
        observers[project_name].stop()
        observers[project_name].join()
        del observers[project_name]
        logger.info(f"Stopped monitoring project '{project_name}'")

async def retry_worker():
    """Background worker to process retry queue"""
    while True:
        try:
            retry_item = retry_queue.get_retry()
            if retry_item:
                message_data = retry_item['message_data']
                retry_count = retry_item['retry_count']
                
                if retry_count <= 3:
                    logger.info(f"Retrying message send (attempt {retry_count})")
                    message_data['retry_count'] = retry_count
                    
                    # Get the watcher to retry sending
                    if 'main' in watchers:
                        await watchers['main'].send_telegram_message_safe(message_data)
                else:
                    logger.error(f"Max retries exceeded for message: {message_data.get('file_path')}")
            
            await asyncio.sleep(30)  # Check retry queue every 30 seconds
        except Exception as e:
            logger.error(f"Error in retry worker: {e}")
            await asyncio.sleep(60)

def setup_bot_token(token=None):
    """Interactive setup for bot token"""
    if token:
        config.bot_token = token
    else:
        print("\n🤖 Telegram Bot Setup")
        print("1. Open Telegram and search for @BotFather")
        print("2. Send /newbot and follow the instructions")
        print("3. Copy the bot token you receive")
        config.bot_token = input("\nEnter your bot token: ").strip()
    
    config.save()
    print("✅ Bot token saved!")

def main():
    """Main function"""
    global config, watchers, processed_tracker, retry_queue, project_launcher
    
    # Load configuration
    config = Config()
    
    # Check if bot token is configured
    if not config.bot_token:
        print("❌ No bot token configured!")
        setup_bot_token()
    
    # Initialize persistent components
    processed_tracker = ProcessedFilesTracker()
    retry_queue = RetryQueue()
    
    # Create bot
    application = Application.builder().token(config.bot_token).build()
    bot = application.bot
    
    # Initialize project launcher
    project_launcher = ProjectLauncher(bot, config.chat_id)
    
    # Create main watcher
    watchers['main'] = MultiProjectInboxWatcher(bot, config, processed_tracker, retry_queue)
    watchers['main'].application = application
    
    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("add", add_project))
    application.add_handler(CommandHandler("remove", remove_project))
    application.add_handler(CommandHandler("list", list_projects))
    application.add_handler(CommandHandler("toggle", toggle_project))
    application.add_handler(CommandHandler("short", short_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Define post_init callback
    async def post_init(application):
        # Ensure the application has the event loop reference
        if not hasattr(application, 'loop') or application.loop is None:
            application.loop = asyncio.get_running_loop()
        
        # Set event loop in project launcher
        if project_launcher:
            project_launcher.set_event_loop(application.loop)
        
        # Start retry worker
        application.create_task(retry_worker())
        
        # Scan for existing unprocessed files on startup
        watchers['main'].scan_existing_files()
        
        # Start monitoring all enabled projects
        for project_name in config.projects:
            start_monitoring_project(project_name)
        
        logger.info("Bot started. Monitoring projects...")
        logger.info(f"Processed files tracked in: {PROCESSED_FILES_DIR}")
        logger.info(f"Retry queue file: {RETRY_QUEUE_FILE}")
        logger.info("Container auto-launch enabled for messaging")
    
    # Set post_init callback
    application.post_init = post_init
    
    try:
        # Start bot
        application.run_polling()
    except KeyboardInterrupt:
        # Stop all observers
        for observer in observers.values():
            observer.stop()
        for observer in observers.values():
            observer.join()

if __name__ == "__main__":
    main()
