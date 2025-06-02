#!/usr/bin/env python3
"""
Telegram Inbox Bot - Monitors inbox/to_human/ and sends notifications
Receives responses and writes them to inbox/from_human/
"""

import os
import time
import asyncio
from pathlib import Path
from datetime import datetime
import logging
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from telegram import Bot
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.ext import Updater
import json

# Configuration
TELEGRAM_BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"  # Get from @BotFather
TELEGRAM_CHAT_ID = "YOUR_CHAT_ID_HERE"     # Get from @userinfobot or /start message

# Paths
INBOX_TO_HUMAN = Path("inbox/to_human")
INBOX_FROM_HUMAN = Path("inbox/from_human")
LOGS_DIR = Path("logs/telegram_bot")

# Ensure directories exist
INBOX_TO_HUMAN.mkdir(parents=True, exist_ok=True)
INBOX_FROM_HUMAN.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Global bot instance
bot = None

class MessageLogger:
    """Handles logging of all messages to structured log files"""
    
    def __init__(self):
        self.current_log_file = None
        self.ensure_log_file()
    
    def ensure_log_file(self):
        """Create or get today's log file"""
        today = datetime.now().strftime('%Y-%m-%d')
        self.current_log_file = LOGS_DIR / f"messages_{today}.jsonl"
    
    def log_message(self, message_data):
        """Log a message to the current log file"""
        try:
            # Ensure we're using today's log file
            self.ensure_log_file()
            
            # Add timestamp if not present
            if 'timestamp' not in message_data:
                message_data['timestamp'] = datetime.now().isoformat()
            
            # Write to log file
            with open(self.current_log_file, 'a') as f:
                f.write(json.dumps(message_data) + '\n')
            
            logger.info(f"Logged message: {message_data.get('type', 'unknown')} - {message_data.get('filename', 'N/A')}")
        except Exception as e:
            logger.error(f"Error logging message: {e}")
    
    def log_outgoing_telegram(self, filename, content, chat_id):
        """Log messages sent to Telegram"""
        self.log_message({
            'type': 'telegram_outgoing',
            'direction': 'bot_to_human',
            'filename': filename,
            'content': content,
            'chat_id': str(chat_id),
            'platform': 'telegram'
        })
    
    def log_incoming_telegram(self, message_type, content, response_to=None):
        """Log messages received from Telegram"""
        self.log_message({
            'type': 'telegram_incoming',
            'direction': 'human_to_bot',
            'message_type': message_type,
            'content': content,
            'response_to': response_to,
            'platform': 'telegram'
        })
    
    def log_file_created(self, filepath, content, source='telegram'):
        """Log files created in inbox directories"""
        self.log_message({
            'type': 'file_created',
            'filepath': str(filepath),
            'filename': filepath.name,
            'content': content,
            'source': source,
            'directory': str(filepath.parent)
        })
    
    def log_file_detected(self, filepath, content):
        """Log files detected in to_human directory"""
        self.log_message({
            'type': 'file_detected',
            'filepath': str(filepath),
            'filename': filepath.name,
            'content': content,
            'directory': str(filepath.parent)
        })

# Initialize message logger
message_logger = MessageLogger()

class InboxWatcher(FileSystemEventHandler):
    """Watches for new files in inbox/to_human/"""
    
    def __init__(self, bot_instance):
        self.bot = bot_instance
        self.processed_files = set()
    
    def on_created(self, event):
        if event.is_directory:
            return
        
        file_path = Path(event.src_path)
        if file_path.suffix == '.md' and file_path.name not in self.processed_files:
            self.process_new_message(file_path)
    
    def on_modified(self, event):
        if event.is_directory:
            return
        
        file_path = Path(event.src_path)
        if file_path.suffix == '.md' and file_path.name not in self.processed_files:
            self.process_new_message(file_path)
    
    def process_new_message(self, file_path):
        """Read and send the message via Telegram"""
        try:
            with open(file_path, 'r') as f:
                content = f.read()
            
            # Log file detection
            message_logger.log_file_detected(file_path, content)
            
            # Mark as processed
            self.processed_files.add(file_path.name)
            
            # Format message
            message = f"📥 **New AI Message**\n\n"
            message += f"**File:** `{file_path.name}`\n"
            message += f"**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            message += f"**Content:**\n{content}\n\n"
            message += f"Reply to this message to respond."
            
            # Send via Telegram
            asyncio.run(self.send_telegram_message(message, file_path.name, content))
            
        except Exception as e:
            logger.error(f"Error processing {file_path}: {e}")
    
    async def send_telegram_message(self, message, filename, original_content):
        """Send message to Telegram"""
        try:
            await self.bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=message,
                parse_mode='Markdown'
            )
            # Log outgoing telegram message
            message_logger.log_outgoing_telegram(filename, original_content, TELEGRAM_CHAT_ID)
            logger.info(f"Sent notification for {filename}")
        except Exception as e:
            logger.error(f"Error sending Telegram message: {e}")

async def start_command(update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        f"Bot started! Your chat ID is: {chat_id}\n"
        f"Add this to the script configuration.\n\n"
        f"I'll notify you of messages in inbox/to_human/"
    )

async def handle_message(update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming messages as responses"""
    try:
        user_message = update.message.text
        
        # Check if this is a reply to a bot message
        if update.message.reply_to_message and update.message.reply_to_message.from_user.is_bot:
            # Extract filename from the original message
            original_text = update.message.reply_to_message.text
            filename_line = [line for line in original_text.split('\n') if line.startswith('**File:**')]
            
            if filename_line:
                # Extract filename
                filename = filename_line[0].split('`')[1]
                base_name = filename.replace('.md', '')
                
                # Log incoming response
                message_logger.log_incoming_telegram('response', user_message, response_to=filename)
                
                # Create response file
                response_filename = f"{base_name}_response_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
                response_path = INBOX_FROM_HUMAN / response_filename
                
                # Build file content
                file_content = f"# Response to: {filename}\n\n"
                file_content += f"**From:** Telegram\n"
                file_content += f"**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                file_content += f"---\n\n"
                file_content += user_message
                
                # Write response
                with open(response_path, 'w') as f:
                    f.write(file_content)
                
                # Log file creation
                message_logger.log_file_created(response_path, file_content, source='telegram_response')
                
                await update.message.reply_text(
                    f"✅ Response saved to:\n`{response_filename}`"
                )
                logger.info(f"Saved response to {response_path}")
            else:
                await update.message.reply_text(
                    "⚠️ Please reply to a bot message to respond to an AI message."
                )
        else:
            # Regular message - save as general instruction
            # Log incoming instruction
            message_logger.log_incoming_telegram('instruction', user_message)
            
            instruction_filename = f"instruction_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
            instruction_path = INBOX_FROM_HUMAN / instruction_filename
            
            # Build file content
            file_content = f"# Direct Instruction\n\n"
            file_content += f"**From:** Telegram\n"
            file_content += f"**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            file_content += f"---\n\n"
            file_content += user_message
            
            with open(instruction_path, 'w') as f:
                f.write(file_content)
            
            # Log file creation
            message_logger.log_file_created(instruction_path, file_content, source='telegram_instruction')
            
            await update.message.reply_text(
                f"📝 Instruction saved to:\n`{instruction_filename}`"
            )
            logger.info(f"Saved instruction to {instruction_path}")
            
    except Exception as e:
        logger.error(f"Error handling message: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def list_pending(update, context: ContextTypes.DEFAULT_TYPE):
    """List all pending messages in inbox/to_human/"""
    try:
        pending_files = list(INBOX_TO_HUMAN.glob("*.md"))
        if not pending_files:
            await update.message.reply_text("📭 No pending messages")
            return
        
        message = "📋 **Pending Messages:**\n\n"
        for file in pending_files:
            if not file.name.endswith('.processed'):
                message += f"• `{file.name}`\n"
        
        await update.message.reply_text(message, parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def show_logs(update, context: ContextTypes.DEFAULT_TYPE):
    """Show recent log entries"""
    try:
        # Get today's log file
        today = datetime.now().strftime('%Y-%m-%d')
        log_file = LOGS_DIR / f"messages_{today}.jsonl"
        
        if not log_file.exists():
            await update.message.reply_text("📄 No logs for today yet")
            return
        
        # Read last 10 entries
        with open(log_file, 'r') as f:
            lines = f.readlines()
        
        recent_logs = lines[-10:] if len(lines) > 10 else lines
        
        message = f"📊 **Recent Log Entries ({len(recent_logs)} latest):**\n\n"
        
        for line in recent_logs:
            try:
                entry = json.loads(line)
                timestamp = entry.get('timestamp', 'N/A')[:19]  # Just date and time
                log_type = entry.get('type', 'unknown')
                direction = entry.get('direction', '')
                filename = entry.get('filename', 'N/A')
                
                if log_type == 'telegram_outgoing':
                    message += f"📤 [{timestamp}] Sent: {filename}\n"
                elif log_type == 'telegram_incoming':
                    msg_type = entry.get('message_type', 'unknown')
                    message += f"📥 [{timestamp}] Received: {msg_type}\n"
                elif log_type == 'file_created':
                    message += f"💾 [{timestamp}] Created: {filename}\n"
                elif log_type == 'file_detected':
                    message += f"👁️ [{timestamp}] Detected: {filename}\n"
            except:
                continue
        
        message += f"\n📁 Log location: `{log_file.name}`"
        
        await update.message.reply_text(message, parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

def main():
    """Main function"""
    global bot
    
    # Create bot
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    bot = application.bot
    
    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("list", list_pending))
    application.add_handler(CommandHandler("logs", show_logs))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Start file watcher
    event_handler = InboxWatcher(bot)
    observer = Observer()
    observer.schedule(event_handler, str(INBOX_TO_HUMAN), recursive=False)
    observer.start()
    
    logger.info("Bot started. Watching inbox/to_human/ for new messages...")
    logger.info(f"Logging all messages to: {LOGS_DIR}")
    logger.info("Available commands: /start, /list, /logs")
    
    try:
        # Start bot
        application.run_polling()
    except KeyboardInterrupt:
        observer.stop()
    observer.join()

if __name__ == "__main__":
    main()