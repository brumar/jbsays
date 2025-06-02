# Telegram Project Manager Bot Setup Guide

## Quick Start

### 1. Install Dependencies
```bash
pip install python-telegram-bot watchdog
```

### 2. Create Your Telegram Bot
1. Open Telegram and search for **@BotFather**
2. Send `/newbot` and follow the prompts
3. Choose a name (e.g., "JBSays Project Manager")
4. Choose a username (must end in 'bot', e.g., "jbsays_pm_bot")
5. Copy the **bot token** you receive

### 3. Configure the Bot
Create a security config file `telegram_bot_config.json`:
```json
{
  "allowed_user_ids": [YOUR_TELEGRAM_USER_ID]
}
```

### 4. Run the Bot
```bash
python telegram_pm_2.py
```

The bot will create config at `~/.telegram_inbox_bot/pm_config.json` on first run.

### 5. Get Your User ID and Initialize
1. Start a chat with your bot in Telegram
2. Send `/start` 
3. The bot will save your chat ID and start inbox monitoring

## Features

### Commands
- `/start` - Initialize bot and start inbox monitoring
- `/pm` - Open project management menu
- `/status` - Show bot and monitoring status
- `/restart_inbox` - Force restart inbox monitoring

### Project Management

**Main Menu (`/pm`):**
- Shows all projects with status indicators:
  - 🟢 Running
  - ⏸️ Paused
  - 🔴 Stopped
  - ✅ Completed
  - ⚫ Not Started
- Batch operations for multiple projects

**Project Actions:**
- ▶️ Start/Resume - Start or resume a project
- ⏸️ Pause - Pause a running project
- 🛑 Stop - Stop a project
- 📊 Status - View detailed status
- 📜 Logs - View container logs
- ❓ Ask - Run a single-iteration query

### Inbox Integration

1. **Monitoring**: Watches `inbox/to_human/` in each project
2. **Notifications**: Sends message when new files appear
3. **Quick Actions**: 
   - 💬 Reply - Send to project inbox
   - 📊 Status - Check project status
   - ⚡ Actions - Open project menu
4. **Responses**: Saved to `inbox/from_human/`

### Message Routing

**Direct Messages:**
- Send any text to the bot
- Choose project and action:
  - 📥 Inbox - Save to project's inbox
  - ❓ Ask - Run as temporary container

**AI → You:**
- AI writes to `project/inbox/to_human/message.md`
- Bot sends Telegram notification with project context
- Quick action buttons for response

**You → AI:**
- Reply via bot commands or quick buttons
- Messages saved to `project/inbox/from_human/telegram_pm_[timestamp].md`
- AI processes on next iteration

### File Organization

**Outgoing messages** (AI to Human):
```
project/
└── inbox/
    └── to_human/
        ├── critical_decision_20250123.md
        └── infrastructure_proposal.md.processed
```

**Incoming responses** (Human to AI):
```
project/
└── inbox/
    └── from_human/
        ├── telegram_20250123_143022.md
        └── response_to_critical_decision.md
```

### Configuration

The bot stores configuration in `~/.telegram_inbox_bot/config.json`:
```json
{
  "bot_token": "YOUR_BOT_TOKEN",
  "chat_id": "YOUR_CHAT_ID",
  "projects": {
    "myproject": {
      "path": "/home/user/myproject",
      "enabled": true
    }
  }
}
```

### Tips

1. **Security**: Whitelist user IDs in `telegram_bot_config.json`
2. **Performance**: Bot uses thread pool for Docker operations
3. **Monitoring**: Multiple projects monitored concurrently
4. **Questions**: Fire-and-forget mode for quick queries
5. **Navigation**: Persistent quick action buttons

## Troubleshooting

**Bot not responding:**
- Check bot token is correct
- Ensure you've started the chat with `/start`
- Check Python dependencies are installed

**Files not detected:**
- Verify project path is correct
- Check `inbox/to_human/` directory exists
- Ensure files have `.md` extension

**Can't reply:**
- Use the Reply button or reply to bot messages
- Direct messages are saved as new instructions
