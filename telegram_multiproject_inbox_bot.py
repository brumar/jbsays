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
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# Configuration file paths
CONFIG_FILE = Path.home() / ".telegram_inbox_bot" / "config.json"
SECURITY_CONFIG_FILE = Path(__file__).parent / "telegram_bot_config.json"

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
    
    def __init__(self, bot_instance, config):
        self.bot = bot_instance
        self.config = config
        self.processed_files = {}  # {project_name: set(filenames)}
    
    def on_created(self, event):
        if not event.is_directory and event.src_path.endswith('.md'):
            self.process_event(event)
    
    def on_modified(self, event):
        if not event.is_directory and event.src_path.endswith('.md'):
            self.process_event(event)
    
    def process_event(self, event):
        """Process file events and determine which project they belong to"""
        file_path = Path(event.src_path)
        
        # Find which project this file belongs to
        for project_name, project_info in self.config.projects.items():
            if not project_info['enabled']:
                continue
                
            project_inbox = Path(project_info['path']) / "inbox" / "to_human"
            if str(project_inbox) in str(file_path):
                if project_name not in self.processed_files:
                    self.processed_files[project_name] = set()
                
                if file_path.name not in self.processed_files[project_name]:
                    self.process_new_message(file_path, project_name)
                break
    
    def process_new_message(self, file_path, project_name):
        """Read and send the message via Telegram"""
        try:
            with open(file_path, 'r') as f:
                content = f.read()
            
            # Mark as processed
            self.processed_files[project_name].add(file_path.name)
            
            # Format message with project context
            message = f"📥 **New Message from Project: {project_name}**\n\n"
            message += f"**File:** `{file_path.name}`\n"
            message += f"**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            message += f"**Content:**\n{content[:3000]}"  # Telegram message limit
            if len(content) > 3000:
                message += f"\n\n... (truncated, {len(content)} total chars)"
            
            # Create inline keyboard for quick actions
            keyboard = [
                [
                    InlineKeyboardButton("📝 Reply", callback_data=f"reply:{project_name}:{file_path.name}"),
                    InlineKeyboardButton("✅ Mark Read", callback_data=f"read:{project_name}:{file_path.name}")
                ],
                [
                    InlineKeyboardButton("📂 Open Project", callback_data=f"project:{project_name}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Send via Telegram
            asyncio.run(self.send_telegram_message(message, reply_markup))
            
        except Exception as e:
            logger.error(f"Error processing {file_path}: {e}")
    
    async def send_telegram_message(self, message, reply_markup=None):
        """Send message to Telegram"""
        try:
            await self.bot.send_message(
                chat_id=self.config.chat_id,
                text=message,
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.error(f"Error sending Telegram message: {e}")

# Global variables
config = None
watchers = {}
observers = {}

@require_auth
async def start_command(update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    chat_id = update.effective_chat.id
    
    # Save chat ID if not already saved
    if not config.chat_id:
        config.chat_id = str(chat_id)
        config.save()
    
    message = f"🤖 Multi-Project Inbox Bot Started!\n\n"
    message += f"**Your Chat ID:** `{chat_id}`\n\n"
    message += "**Commands:**\n"
    message += "/add <name> <path> - Add a project\n"
    message += "/remove <name> - Remove a project\n"
    message += "/list - List all projects\n"
    message += "/toggle <name> - Enable/disable project\n"
    message += "/status - Show bot status\n"
    message += "/config - Show configuration"
    
    await update.message.reply_text(message, parse_mode='Markdown')

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
    
    message = "📋 **Monitored Projects:**\n\n"
    for name, info in config.projects.items():
        status = "🟢" if info['enabled'] else "🔴"
        message += f"{status} **{name}**\n"
        message += f"   Path: `{info['path']}`\n\n"
    
    await update.message.reply_text(message, parse_mode='Markdown')

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
async def handle_message(update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming messages as responses"""
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
    
    if action == 'reply':
        project_name = data[1]
        filename = data[2]
        context.user_data['reply_to'] = {'project': project_name, 'file': filename}
        await query.message.reply_text(
            f"💬 Reply to '{filename}' in project '{project_name}':\n"
            f"(Send your message and I'll save it as a response)"
        )
    
    elif action == 'read':
        project_name = data[1]
        filename = data[2]
        # Mark the original file as processed
        project_path = Path(config.projects[project_name]['path'])
        original_file = project_path / "inbox" / "to_human" / filename
        if original_file.exists():
            processed_file = original_file.with_suffix('.md.processed')
            original_file.rename(processed_file)
            await query.message.edit_text(
                query.message.text + "\n\n✅ Marked as read",
                parse_mode='Markdown'
            )
    
    elif action == 'send':
        project_name = data[1]
        message_text = context.user_data.get('last_message', '')
        
        if message_text:
            # Save to project's inbox/from_human/
            project_path = Path(config.projects[project_name]['path'])
            inbox_from = project_path / "inbox" / "from_human"
            inbox_from.mkdir(parents=True, exist_ok=True)
            
            filename = f"telegram_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
            
            # Check if this is a reply
            reply_info = context.user_data.get('reply_to')
            if reply_info and reply_info['project'] == project_name:
                content = f"# Response to: {reply_info['file']}\n\n"
                content += f"**From:** Telegram\n"
                content += f"**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                content += f"---\n\n"
                content += message_text
                context.user_data['reply_to'] = None
            else:
                content = f"# Direct Message\n\n"
                content += f"**From:** Telegram\n"
                content += f"**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                content += f"---\n\n"
                content += message_text
            
            file_path = inbox_from / filename
            with open(file_path, 'w') as f:
                f.write(content)
            
            await query.message.edit_text(
                f"✅ Message sent to project '{project_name}':\n`{filename}`"
            )

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
    global config, watchers
    
    # Load configuration
    config = Config()
    
    # Check if bot token is configured
    if not config.bot_token:
        print("❌ No bot token configured!")
        setup_bot_token()
    
    # Create bot
    application = Application.builder().token(config.bot_token).build()
    bot = application.bot
    
    # Create main watcher
    watchers['main'] = MultiProjectInboxWatcher(bot, config)
    
    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("add", add_project))
    application.add_handler(CommandHandler("remove", remove_project))
    application.add_handler(CommandHandler("list", list_projects))
    application.add_handler(CommandHandler("toggle", toggle_project))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Start monitoring all enabled projects
    for project_name in config.projects:
        start_monitoring_project(project_name)
    
    logger.info("Bot started. Monitoring projects...")
    
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