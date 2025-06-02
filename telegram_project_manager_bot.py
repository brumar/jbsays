#!/usr/bin/env python3
"""
Telegram Project Manager Bot
Integrates with project_manager.sh to control and monitor JBSays containers
"""

import os
import json
import time
import asyncio
import subprocess
import re
import signal
import sys
from pathlib import Path
from datetime import datetime, timedelta
import logging
import hashlib
from collections import defaultdict
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass
from queue import Queue
from threading import Thread, Lock
from concurrent.futures import ThreadPoolExecutor
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.constants import ParseMode

# Configuration
SCRIPT_DIR = Path(__file__).parent
CONFIG_FILE = Path.home() / ".telegram_inbox_bot" / "pm_config.json"
PROCESSED_FILES_DIR = Path.home() / ".telegram_inbox_bot" / "processed"
RETRY_QUEUE_FILE = Path.home() / ".telegram_inbox_bot" / "retry_queue.json"
RECENT_QUESTIONS_FILE = Path.home() / ".telegram_inbox_bot" / "recent_questions.json"
SECURITY_CONFIG_FILE = SCRIPT_DIR / "telegram_bot_config.json"
PROJECT_MANAGER_SCRIPT = SCRIPT_DIR / "project_manager.sh"
PROJECTS_JSON = SCRIPT_DIR / "projects.json"

# Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

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

SECURITY_CONFIG = load_security_config()
ALLOWED_USER_IDS = SECURITY_CONFIG.get("allowed_user_ids", [])

# Simple auth check function
async def check_auth(update: Update) -> bool:
    """Check if user is authorized"""
    # Handle both Message and CallbackQuery updates
    if hasattr(update, 'message') and update.message:
        user_id = update.message.from_user.id
        reply_func = update.message.reply_text
    elif hasattr(update, 'callback_query') and update.callback_query:
        user_id = update.callback_query.from_user.id
        reply_func = update.callback_query.message.reply_text
    else:
        return False
    
    if user_id not in ALLOWED_USER_IDS:
        await reply_func("⛔ Unauthorized access. This bot is private.")
        logger.warning(f"Unauthorized access attempt from user ID: {user_id}")
        return False
    return True

@dataclass
class ProjectStatus:
    """Container status information"""
    name: str
    container_name: str
    state: str  # running, paused, stopped, not_started, exited
    progress: float = 0.0  # percentage
    current_iteration: int = 0
    total_iterations: int = 0
    cpu_percent: float = 0.0
    memory_mb: float = 0.0
    uptime: str = ""
    last_activity: str = ""
    exit_code: Optional[int] = None

class ProjectManager:
    """Interface to project_manager.sh and Docker using thread pool"""
    
    def __init__(self, script_path: Path, projects_json_path: Path):
        self.script_path = script_path
        self.projects_json_path = projects_json_path
        self.projects_data = self.load_projects_json()
        self.executor = ThreadPoolExecutor(max_workers=5, thread_name_prefix="project-manager")
        self.loop = None
    
    def set_event_loop(self, loop):
        """Set the event loop for async operations"""
        self.loop = loop
        
    def load_projects_json(self) -> Dict:
        """Load projects configuration"""
        try:
            with open(self.projects_json_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading projects.json: {e}")
            return {"projects": {}}
    
    def _get_container_info_sync(self, container_name: str) -> Dict[str, Any]:
        """Get detailed container information synchronously in thread"""
        try:
            # Check if container exists
            result = subprocess.run(
                ["docker", "inspect", container_name],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode != 0:
                return {"exists": False}
            
            info = json.loads(result.stdout)[0]
            state = info["State"]
            
            # Get container stats if running
            stats = {}
            if state["Running"]:
                stats_result = subprocess.run(
                    ["docker", "stats", container_name, "--no-stream", "--format", "{{json .}}"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if stats_result.returncode == 0 and stats_result.stdout.strip():
                    stats = json.loads(stats_result.stdout.strip())
            
            return {
                "exists": True,
                "running": state["Running"],
                "paused": state["Paused"],
                "status": state["Status"],
                "started_at": state["StartedAt"],
                "finished_at": state["FinishedAt"],
                "exit_code": state["ExitCode"],
                "cpu_percent": self._parse_cpu(stats.get("CPUPerc", "0%")),
                "memory": self._parse_memory(stats.get("MemUsage", "0MiB / 0MiB"))
            }
            
        except Exception as e:
            logger.error(f"Error getting container info for {container_name}: {e}")
            return {"exists": False}
    
    async def get_container_info(self, container_name: str) -> Dict[str, Any]:
        """Get detailed container information asynchronously"""
        if self.loop:
            return await self.loop.run_in_executor(
                self.executor,
                self._get_container_info_sync,
                container_name
            )
        else:
            # Fallback to sync if no loop available
            return self._get_container_info_sync(container_name)
    
    def _parse_cpu(self, cpu_str: str) -> float:
        """Parse CPU percentage from docker stats"""
        try:
            return float(cpu_str.rstrip('%'))
        except:
            return 0.0
    
    def _parse_memory(self, mem_str: str) -> float:
        """Parse memory usage from docker stats"""
        try:
            # Format: "100MiB / 1GiB"
            used = mem_str.split('/')[0].strip()
            value = float(re.search(r'[\d.]+', used).group())
            if 'GiB' in used:
                value *= 1024
            return value
        except:
            return 0.0
    
    async def get_project_status(self, project_name: str) -> ProjectStatus:
        """Get comprehensive project status asynchronously"""
        project_info = self.projects_data["projects"].get(project_name, {})
        container_name = project_info.get("container_name", "")
        
        if not container_name:
            return ProjectStatus(
                name=project_name,
                container_name="",
                state="not_configured"
            )
        
        container_info = await self.get_container_info(container_name)
        
        # Determine state
        if not container_info["exists"]:
            state = "not_started"
        elif container_info["paused"]:
            state = "paused"
        elif container_info["running"]:
            state = "running"
        elif container_info.get("exit_code", 1) == 0:
            state = "completed"
        else:
            state = "stopped"
        
        # Get iteration progress from logs if running
        progress = 0.0
        current_iteration = 0
        total_iterations = int(project_info.get("args", []).count("--iterations") and 
                             self._get_arg_value(project_info.get("args", []), "--iterations") or 40)
        
        if state in ["running", "paused", "completed"]:
            progress_info = await self.get_iteration_progress(container_name)
            if progress_info:
                current_iteration = progress_info[0]
                total_iterations = progress_info[1]
                progress = (current_iteration / total_iterations * 100) if total_iterations > 0 else 0
        
        # Calculate uptime
        uptime = ""
        if container_info.get("started_at"):
            started = datetime.fromisoformat(container_info["started_at"].replace('Z', '+00:00'))
            if state == "running":
                uptime = self._format_duration(datetime.now(started.tzinfo) - started)
            elif container_info.get("finished_at"):
                finished = datetime.fromisoformat(container_info["finished_at"].replace('Z', '+00:00'))
                uptime = self._format_duration(finished - started)
        
        return ProjectStatus(
            name=project_name,
            container_name=container_name,
            state=state,
            progress=progress,
            current_iteration=current_iteration,
            total_iterations=total_iterations,
            cpu_percent=container_info.get("cpu_percent", 0.0),
            memory_mb=container_info.get("memory", 0.0),
            uptime=uptime,
            last_activity=await self.get_last_activity(container_name),
            exit_code=container_info.get("exit_code")
        )
    
    def _get_arg_value(self, args: List[str], flag: str) -> Optional[str]:
        """Extract value for a specific flag from args list"""
        try:
            idx = args.index(flag)
            if idx + 1 < len(args):
                return args[idx + 1]
        except (ValueError, IndexError):
            pass
        return None
    
    def _get_iteration_progress_sync(self, container_name: str) -> Optional[Tuple[int, int]]:
        """Extract iteration progress from container logs synchronously"""
        try:
            result = subprocess.run(
                ["docker", "logs", "--tail", "100", container_name],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                # Look for iteration patterns
                matches = re.findall(r'Iteration (\d+)/(\d+)', result.stdout + result.stderr)
                if matches:
                    # Get the last match
                    current, total = map(int, matches[-1])
                    return (current, total)
        except Exception as e:
            logger.error(f"Error getting iteration progress: {e}")
        
        return None
    
    async def get_iteration_progress(self, container_name: str) -> Optional[Tuple[int, int]]:
        """Extract iteration progress from container logs asynchronously"""
        if self.loop:
            return await self.loop.run_in_executor(
                self.executor,
                self._get_iteration_progress_sync,
                container_name
            )
        else:
            return self._get_iteration_progress_sync(container_name)
    
    def _get_last_activity_sync(self, container_name: str) -> str:
        """Get time since last container log entry synchronously"""
        try:
            result = subprocess.run(
                ["docker", "logs", "--tail", "1", "--timestamps", container_name],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0 and result.stdout:
                # Extract timestamp from log
                match = re.match(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})', result.stdout)
                if match:
                    log_time = datetime.fromisoformat(match.group(1))
                    ago = datetime.now() - log_time.replace(tzinfo=None)
                    return self._format_duration(ago) + " ago"
        except Exception as e:
            logger.error(f"Error getting last activity: {e}")
        
        return "unknown"
    
    async def get_last_activity(self, container_name: str) -> str:
        """Get time since last container log entry asynchronously"""
        if self.loop:
            return await self.loop.run_in_executor(
                self.executor,
                self._get_last_activity_sync,
                container_name
            )
        else:
            return self._get_last_activity_sync(container_name)
    
    def _format_duration(self, duration: timedelta) -> str:
        """Format duration in human-readable form"""
        total_seconds = int(duration.total_seconds())
        
        if total_seconds < 60:
            return f"{total_seconds}s"
        elif total_seconds < 3600:
            return f"{total_seconds // 60}m {total_seconds % 60}s"
        elif total_seconds < 86400:
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            return f"{hours}h {minutes}m"
        else:
            days = total_seconds // 86400
            hours = (total_seconds % 86400) // 3600
            return f"{days}d {hours}h"
    
    def _execute_command_sync(self, args: List[str], timeout: int = 30) -> Tuple[bool, str]:
        """Execute command synchronously in thread"""
        try:
            logger.info(f"Executing command in thread: {' '.join(args)}")
            result = subprocess.run(
                args,
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
            logger.error(f"Error executing command: {e}")
            return False, str(e)
    
    async def execute_command(self, args: List[str]) -> Tuple[bool, str]:
        """Execute project manager command using thread pool"""
        if self.loop:
            return await self.loop.run_in_executor(
                self.executor,
                self._execute_command_sync,
                args,
                30  # timeout
            )
        else:
            return self._execute_command_sync(args)
    
    async def start_project(self, project_name: str, overrides: List[str] = None) -> Tuple[bool, str]:
        """Start a project"""
        cmd = [str(self.script_path), "start", project_name]
        if overrides:
            cmd.extend(overrides)
        
        return await self.execute_command(cmd)
    
    async def pause_project(self, project_name: str) -> Tuple[bool, str]:
        """Pause a project"""
        return await self.execute_command([str(self.script_path), "pause", project_name])
    
    async def resume_project(self, project_name: str) -> Tuple[bool, str]:
        """Resume a project"""
        return await self.execute_command([str(self.script_path), "resume", project_name])
    
    async def stop_project(self, project_name: str) -> Tuple[bool, str]:
        """Stop a project"""
        return await self.execute_command([str(self.script_path), "stop", project_name])
    
    def _get_logs_sync(self, container_name: str, tail: int = 50) -> str:
        """Get container logs synchronously"""
        try:
            result = subprocess.run(
                ["docker", "logs", "--tail", str(tail), container_name],
                capture_output=True,
                text=True,
                timeout=10
            )
            return result.stdout + result.stderr
            
        except Exception as e:
            logger.error(f"Error getting logs: {e}")
            return f"Error getting logs: {str(e)}"
    
    async def get_logs(self, container_name: str, tail: int = 50) -> str:
        """Get container logs asynchronously"""
        if self.loop:
            return await self.loop.run_in_executor(
                self.executor,
                self._get_logs_sync,
                container_name,
                tail
            )
        else:
            return self._get_logs_sync(container_name, tail)

class RecentQuestions:
    """Manage recent questions for each project"""
    
    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.questions = self.load()
        self.lock = Lock()
    
    def load(self) -> Dict[str, List[Dict]]:
        """Load recent questions from file"""
        if self.file_path.exists():
            try:
                with open(self.file_path, 'r') as f:
                    return json.load(f)
            except:
                pass
        return defaultdict(list)
    
    def save(self):
        """Save recent questions to file"""
        with self.lock:
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.file_path, 'w') as f:
                json.dump(dict(self.questions), f, indent=2)
    
    def add_question(self, project: str, question: str):
        """Add a question to recent history"""
        with self.lock:
            self.questions[project].insert(0, {
                "question": question,
                "timestamp": datetime.now().isoformat()
            })
            # Keep only last 10 questions per project
            self.questions[project] = self.questions[project][:10]
            self.save()
    
    def get_recent(self, project: str, limit: int = 3) -> List[str]:
        """Get recent questions for a project"""
        return [q["question"] for q in self.questions.get(project, [])[:limit]]

class ProcessedFilesTracker:
    """Track processed files from inbox monitoring"""
    
    def __init__(self):
        self.processed_dir = PROCESSED_FILES_DIR
        self.processed_dir.mkdir(parents=True, exist_ok=True)
        self.lock = Lock()
    
    def _get_file_hash(self, file_path: Path) -> Optional[str]:
        """Get hash of file content for tracking"""
        try:
            with open(file_path, 'rb') as f:
                content = f.read()
            return hashlib.md5(content).hexdigest()
        except:
            return None
    
    def _get_processed_file_path(self, project_name: str) -> Path:
        """Get path to processed files list for project"""
        return self.processed_dir / f"{project_name}_processed.json"
    
    def load_processed_files(self, project_name: str) -> Dict:
        """Load processed files for a project"""
        processed_file = self._get_processed_file_path(project_name)
        if processed_file.exists():
            try:
                with open(processed_file, 'r') as f:
                    return json.load(f)
            except:
                return {}
        return {}
    
    def save_processed_files(self, project_name: str, processed_files: Dict):
        """Save processed files for a project"""
        processed_file = self._get_processed_file_path(project_name)
        with self.lock:
            with open(processed_file, 'w') as f:
                json.dump(processed_files, f, indent=2)
    
    def is_file_processed(self, project_name: str, file_path: Path) -> bool:
        """Check if file has been processed"""
        processed_files = self.load_processed_files(project_name)
        file_key = f"{file_path.name}_{file_path.stat().st_mtime}"
        file_hash = self._get_file_hash(file_path)
        
        if file_key in processed_files:
            stored_hash = processed_files[file_key].get('hash')
            return stored_hash == file_hash
        return False
    
    def mark_file_processed(self, project_name: str, file_path: Path):
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

class InboxWatcher(FileSystemEventHandler):
    """Watch for new files in project inbox directories"""
    
    def __init__(self, bot, chat_id, project_manager, processed_tracker, loop=None):
        self.bot = bot
        self.chat_id = chat_id
        self.project_manager = project_manager
        self.processed_tracker = processed_tracker
        self.processing_files = set()
        self.processing_lock = Lock()
        self.loop = loop or asyncio.get_event_loop()
    
    def on_created(self, event):
        if not event.is_directory and event.src_path.endswith('.md'):
            # Run the async processing in a new thread
            file_path = Path(event.src_path)
            Thread(target=self._process_file_thread, args=(file_path,)).start()
    
    def _process_file_thread(self, file_path: Path):
        """Process file in a separate thread"""
        try:
            # Create a new event loop for this thread
            asyncio.run(self.process_new_file(file_path))
        except Exception as e:
            logger.error(f"Error processing file {file_path}: {e}")
    
    async def process_new_file(self, file_path: Path):
        """Process new inbox file"""
        logger.info(f"Processing new file: {file_path}")
        
        # Check if already processing
        with self.processing_lock:
            if str(file_path) in self.processing_files:
                logger.debug(f"File already being processed: {file_path}")
                return
            self.processing_files.add(str(file_path))
        
        try:
            # Find project
            project_name = None
            for name, info in self.project_manager.projects_data["projects"].items():
                project_path = Path(info.get("path", ""))
                if project_path in file_path.parents:
                    project_name = name
                    break
            
            if not project_name:
                return
            
            # Check if already processed
            if self.processed_tracker.is_file_processed(project_name, file_path):
                return
            
            # Read and send message
            with open(file_path, 'r') as f:
                content = f.read()
            
            # Format message
            message = f"📥 New message from {project_name}\n\n"
            message += f"File: {file_path.name}\n"
            message += f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            message += f"--- CONTENT ---\n{content}"
            
            # Create inline keyboard with quick actions
            keyboard = [
                [
                    InlineKeyboardButton("💬 Reply", callback_data=f"quick_inbox:{project_name}"),
                    InlineKeyboardButton("📊 Status", callback_data=f"action:status:{project_name}")
                ],
                [
                    InlineKeyboardButton("⚡ Actions", callback_data=f"pm:project:{project_name}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Send to Telegram with buttons
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message[:4096],  # Telegram limit
                parse_mode=None,
                reply_markup=reply_markup
            )
            
            # Mark as processed
            self.processed_tracker.mark_file_processed(project_name, file_path)
            
        except Exception as e:
            logger.error(f"Error processing file {file_path}: {e}")
        finally:
            with self.processing_lock:
                self.processing_files.discard(str(file_path))

class ProjectManagerBot:
    """Main bot class"""
    
    def __init__(self):
        self.config = self.load_config()
        self.project_manager = ProjectManager(PROJECT_MANAGER_SCRIPT, PROJECTS_JSON)
        self.recent_questions = RecentQuestions(RECENT_QUESTIONS_FILE)
        self.processed_tracker = ProcessedFilesTracker()
        self.observers = {}
        self.message_history = defaultdict(lambda: datetime.min)
        self.last_project = None
        self.application = None  # Will be set later
        self.running = True
    
    def load_config(self) -> Dict:
        """Load bot configuration"""
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        else:
            config = {
                'bot_token': '',
                'chat_id': ''
            }
            self.save_config(config)
            return config
    
    def save_config(self, config: Dict):
        """Save bot configuration"""
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
    
    async def get_projects_with_status(self) -> List[Tuple[str, ProjectStatus]]:
        """Get all projects with their status, smartly ordered"""
        projects = []
        
        for project_name in self.project_manager.projects_data["projects"]:
            status = await self.project_manager.get_project_status(project_name)
            projects.append((project_name, status))
        
        # Smart ordering
        def sort_key(item):
            name, status = item
            state_priority = {
                'running': 0,
                'paused': 1,
                'stopped': 2,
                'completed': 3,
                'not_started': 4
            }
            
            priority = state_priority.get(status.state, 5)
            
            # For running projects, prioritize by CPU usage
            if status.state == 'running':
                priority -= status.cpu_percent / 1000
            
            # Consider last message time
            last_msg = self.message_history.get(name, datetime.min)
            if last_msg != datetime.min:
                hours_ago = (datetime.now() - last_msg).total_seconds() / 3600
                priority += hours_ago / 100
            
            return priority
        
        return sorted(projects, key=sort_key)
    
    def format_project_button(self, name: str, status: ProjectStatus) -> str:
        """Format project button text with emoji and status"""
        emoji = {
            'running': '🟢',
            'paused': '⏸️',
            'stopped': '🔴',
            'completed': '✅',
            'not_started': '⚫'
        }.get(status.state, '❓')
        
        text = f"{emoji} {name}"
        
        if status.state == 'running' and status.total_iterations > 0:
            text += f" ({status.current_iteration}/{status.total_iterations})"
        elif status.state == 'paused':
            text += " (paused)"
        elif status.state == 'completed':
            text += " ✓"
            
        return text
    
    def get_available_actions(self, status: ProjectStatus) -> List[Tuple[str, str]]:
        """Get available actions based on project state"""
        actions = {
            'running': [
                ('⏸️ Pause', 'pause'),
                ('❓ Ask', 'ask'),
                ('📊 Status', 'status'),
                ('🛑 Stop', 'stop')
            ],
            'paused': [
                ('⏭️ Resume', 'resume'),
                ('❓ Ask', 'ask'),
                ('📊 Status', 'status'),
                ('🛑 Stop', 'stop')
            ],
            'stopped': [
                ('▶️ Start', 'start'),
                ('❓ Ask', 'ask'),
                ('📊 Status', 'status')
            ],
            'completed': [
                ('🔄 Restart', 'start'),
                ('❓ Ask', 'ask'),
                ('📊 Status', 'status')
            ],
            'not_started': [
                ('▶️ Start', 'start'),
                ('❓ Ask', 'ask')
            ]
        }
        
        return actions.get(status.state, [])
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        if not await check_auth(update):
            return
        chat_id = update.effective_chat.id
        
        # Save chat ID
        self.config['chat_id'] = str(chat_id)
        self.save_config(self.config)
        
        # Start inbox monitoring if not already started
        if self.application and not self.observers:
            self.start_inbox_monitoring(self.application)
        
        message = "🤖 Project Manager Bot\n\n"
        message += "Commands:\n"
        message += "/pm - Manage projects\n"
        message += "/status - Show bot status\n"
        message += "/help - Show help\n\n"
        message += "Send any text message to route it to a project."
        
        await update.message.reply_text(message)
    
    async def pm_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /pm command - main entry point"""
        if not await check_auth(update):
            return
        projects = await self.get_projects_with_status()
        
        if not projects:
            await update.message.reply_text("❌ No projects configured in projects.json")
            return
        
        keyboard = []
        for name, status in projects:
            button_text = self.format_project_button(name, status)
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"pm:project:{name}")])
        
        # Add batch actions if multiple projects
        if len(projects) > 1:
            keyboard.append([
                InlineKeyboardButton("▶️ Start All", callback_data="pm:batch:start_all"),
                InlineKeyboardButton("⏸️ Pause All", callback_data="pm:batch:pause_all"),
                InlineKeyboardButton("🛑 Stop All", callback_data="pm:batch:stop_all")
            ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("🎯 Select a project:", reply_markup=reply_markup)
        
        # Clear any previous state
        context.user_data.clear()
        context.user_data['flow'] = 'pm'
    
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command - show bot status"""
        if not await check_auth(update):
            return
        
        status_text = "🤖 Bot Status\n\n"
        status_text += f"Chat ID: {self.config.get('chat_id', 'Not set')}\n"
        status_text += f"Active observers: {len(self.observers)}\n\n"
        
        if self.observers:
            status_text += "📥 Monitoring inboxes:\n"
            for project_name, observer in self.observers.items():
                status_text += f"- {project_name}: {'Active' if observer.is_alive() else 'Stopped'}\n"
        else:
            status_text += "⚠️ No inbox monitoring active\n"
            status_text += "\nUse /restart_inbox to start monitoring\n"
            
        await update.message.reply_text(status_text)
    
    async def restart_inbox_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /restart_inbox command - restart inbox monitoring"""
        if not await check_auth(update):
            return
        
        # Stop existing observers
        if self.observers:
            await update.message.reply_text("Stopping existing monitors...")
            for observer in self.observers.values():
                observer.stop()
                observer.join()
            self.observers.clear()
        
        # Restart monitoring
        if self.application:
            self.start_inbox_monitoring(self.application)
            await update.message.reply_text("✅ Inbox monitoring restarted")
        else:
            await update.message.reply_text("❌ Application not initialized")
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle text messages"""
        if not await check_auth(update):
            return
        message_text = update.message.text
        
        # Check if we're expecting input
        if context.user_data.get('expecting') == 'question':
            # Handle ask question flow
            project = context.user_data.get('ask_project')
            if project:
                await self.handle_ask_question(update, context, project, message_text)
                return
        elif context.user_data.get('expecting') == 'inbox_message':
            # Handle inbox message flow
            project = context.user_data.get('inbox_project')
            if project:
                await self.send_to_inbox(update, context, project, message_text)
                return
        
        # Regular message routing
        await self.route_message(update, context, message_text)
    
    async def route_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE, message_text: str):
        """Route message to project with simplified workflow"""
        projects = await self.get_projects_with_status()
        
        if not projects:
            await update.message.reply_text("❌ No projects available")
            return
        
        # Store message in context
        context.user_data['pending_message'] = message_text
        
        keyboard = []
        
        # Show all projects with inbox/ask buttons
        for name, status in projects:
            emoji = {
                'running': '🟢',
                'paused': '⏸️',
                'stopped': '🔴',
                'completed': '✅',
                'not_started': '⚫'
            }.get(status.state, '❓')
            
            # Create two buttons per project - Inbox and Ask
            row = [
                InlineKeyboardButton(f"{emoji} {name} 📥", callback_data=f"direct_inbox:{name}"),
                InlineKeyboardButton(f"{emoji} {name} ❓", callback_data=f"direct_ask:{name}")
            ]
            keyboard.append(row)
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"📮 Your message:\n\"{message_text[:100]}{'...' if len(message_text) > 100 else ''}\"\n\n"
            f"Select action:\n📥 = Send to inbox\n❓ = Ask as question",
            reply_markup=reply_markup
        )
    
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle button callbacks"""
        query = update.callback_query
        
        try:
            # Check auth for callbacks
            user_id = query.from_user.id
            if user_id not in ALLOWED_USER_IDS:
                try:
                    await query.answer("⛔ Unauthorized access")
                except Exception:
                    pass
                return
                
            # Try to answer the callback query
            try:
                await query.answer()
            except Exception as e:
                # If we can't answer (query too old, etc.), just log and continue
                logger.debug(f"Could not answer callback query: {e}")
        except Exception as e:
            logger.error(f"Error in callback auth check: {e}")
            return
        
        data = query.data
        
        # No-op for separators
        if data == "noop":
            return
        
        # Parse callback data
        parts = data.split(':')
        
        try:
            if parts[0] == 'pm':
                await self.handle_pm_callback(query, context, parts[1:])
            elif parts[0] == 'send':
                await self.handle_send_callback(query, context, parts[1])
            elif parts[0] == 'action':
                await self.handle_action_callback(query, context, parts[1], parts[2])
            elif parts[0] == 'quick_inbox':
                # Quick inbox access
                project = parts[1]
                self.last_project = project
                await self.action_inbox(query, context, project)
            elif parts[0] == 'direct_inbox':
                # Direct inbox from message routing
                project = parts[1]
                await self.handle_direct_inbox(query, context, project)
            elif parts[0] == 'direct_ask':
                # Direct ask from message routing
                project = parts[1]
                await self.handle_direct_ask(query, context, project)
        except Exception as e:
            logger.error(f"Error handling callback {data}: {e}")
            try:
                await query.message.reply_text(f"❌ Error: {str(e)}")
            except:
                pass
    
    async def handle_pm_callback(self, query, context: ContextTypes.DEFAULT_TYPE, parts: List[str]):
        """Handle project manager callbacks"""
        if parts[0] == 'project':
            # Project selected
            project_name = parts[1]
            self.last_project = project_name  # Track last project
            context.user_data['selected_project'] = project_name
            
            # Get status and show actions
            status = await self.project_manager.get_project_status(project_name)
            context.user_data['project_status'] = status
            
            actions = self.get_available_actions(status)
            keyboard = []
            
            for action_text, action_id in actions:
                keyboard.append([InlineKeyboardButton(
                    action_text,
                    callback_data=f"action:{action_id}:{project_name}"
                )])
            
            # Add back button
            keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="pm:back")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Format status message
            status_text = f"📁 Project: {project_name}\n"
            status_text += f"📊 Status: {status.state}\n"
            
            if status.state == 'running':
                status_text += f"📈 Progress: {status.current_iteration}/{status.total_iterations} iterations\n"
                status_text += f"💻 CPU: {status.cpu_percent:.1f}%\n"
                status_text += f"🧠 Memory: {status.memory_mb:.0f}MB\n"
                status_text += f"⏱️ Uptime: {status.uptime}\n"
            
            await query.message.edit_text(status_text, reply_markup=reply_markup)
            
        elif parts[0] == 'batch':
            # Batch operations
            operation = parts[1]
            await self.handle_batch_operation(query, operation)
            
        elif parts[0] == 'back':
            # Go back to project list - recreate the project list
            projects = await self.get_projects_with_status()
            
            if not projects:
                await query.message.edit_text("❌ No projects configured in projects.json")
                return
            
            keyboard = []
            for name, status in projects:
                button_text = self.format_project_button(name, status)
                keyboard.append([InlineKeyboardButton(button_text, callback_data=f"pm:project:{name}")])
            
            # Add batch actions if multiple projects
            if len(projects) > 1:
                keyboard.append([
                    InlineKeyboardButton("▶️ Start All", callback_data="pm:batch:start_all"),
                    InlineKeyboardButton("⏸️ Pause All", callback_data="pm:batch:pause_all"),
                    InlineKeyboardButton("🛑 Stop All", callback_data="pm:batch:stop_all")
                ])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.edit_text("🎯 Select a project:", reply_markup=reply_markup)
    
    async def handle_action_callback(self, query, context: ContextTypes.DEFAULT_TYPE, action: str, project: str):
        """Handle action selection"""
        handlers = {
            'start': self.action_start,
            'pause': self.action_pause,
            'resume': self.action_resume,
            'stop': self.action_stop,
            'status': self.action_status,
            'ask': self.action_ask
        }
        
        handler = handlers.get(action)
        if handler:
            await handler(query, context, project)
    
    async def action_start(self, query, context: ContextTypes.DEFAULT_TYPE, project: str):
        """Start project action"""
        try:
            await query.message.edit_text(f"🚀 Starting {project}...")
            
            # Run start_project in background to avoid blocking
            asyncio.create_task(self._start_project_async(query.message, project))
            
        except Exception as e:
            logger.error(f"Error in start action: {e}")
            await query.message.edit_text(
                f"❌ Error starting {project}: {str(e)}",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ Back", callback_data="pm:back")
                ]])
            )
    
    async def action_pause(self, query, context: ContextTypes.DEFAULT_TYPE, project: str):
        """Pause project action"""
        try:
            await query.message.edit_text(f"⏸️ Pausing {project}...")
            success, output = await self.project_manager.pause_project(project)
            
            if success:
                message = f"✅ Successfully paused {project}"
            else:
                message = f"❌ Failed to pause {project}\n\nError: {output}"
            
            # Update message with back button
            await query.message.edit_text(
                message,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ Back to project", callback_data=f"pm:project:{project}")
                ]])
            )
        except Exception as e:
            logger.error(f"Error in pause action: {e}")
            await query.message.edit_text(
                f"❌ Error pausing {project}: {str(e)}",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ Back", callback_data="pm:back")
                ]])
            )
    
    async def action_resume(self, query, context: ContextTypes.DEFAULT_TYPE, project: str):
        """Resume project action"""
        try:
            await query.message.edit_text(f"▶️ Resuming {project}...")
            success, output = await self.project_manager.resume_project(project)
            
            if success:
                message = f"✅ Successfully resumed {project}"
            else:
                message = f"❌ Failed to resume {project}\n\nError: {output}"
            
            # Update message with back button
            await query.message.edit_text(
                message,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ Back to project", callback_data=f"pm:project:{project}")
                ]])
            )
        except Exception as e:
            logger.error(f"Error in resume action: {e}")
            await query.message.edit_text(
                f"❌ Error resuming {project}: {str(e)}",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ Back", callback_data="pm:back")
                ]])
            )
    
    async def action_stop(self, query, context: ContextTypes.DEFAULT_TYPE, project: str):
        """Stop project action"""
        try:
            await query.message.edit_text(f"🛑 Stopping {project}...")
            success, output = await self.project_manager.stop_project(project)
            
            if success:
                message = f"✅ Successfully stopped {project}"
            else:
                message = f"❌ Failed to stop {project}\n\nError: {output}"
            
            # Update message with back button
            await query.message.edit_text(
                message,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ Back to projects", callback_data="pm:back")
                ]])
            )
        except Exception as e:
            logger.error(f"Error in stop action: {e}")
            await query.message.edit_text(
                f"❌ Error stopping {project}: {str(e)}",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ Back", callback_data="pm:back")
                ]])
            )
    
    async def action_status(self, query, context: ContextTypes.DEFAULT_TYPE, project: str):
        """Show detailed status"""
        status = await self.project_manager.get_project_status(project)
        
        text = f"📊 Detailed Status for {project}\n\n"
        text += f"🔹 Container: {status.container_name}\n"
        text += f"🔹 State: {status.state}\n"
        
        if status.total_iterations > 0:
            text += f"🔹 Progress: {status.current_iteration}/{status.total_iterations} "
            text += f"({status.progress:.1f}%)\n"
        
        if status.state in ['running', 'paused']:
            text += f"🔹 CPU: {status.cpu_percent:.1f}%\n"
            text += f"🔹 Memory: {status.memory_mb:.0f}MB\n"
            text += f"🔹 Uptime: {status.uptime}\n"
            text += f"🔹 Last activity: {status.last_activity}\n"
        
        if status.exit_code is not None and status.state == 'stopped':
            text += f"🔹 Exit code: {status.exit_code}\n"
        
        # Add action buttons
        keyboard = []
        
        if status.state == 'running':
            keyboard.append([
                InlineKeyboardButton("📜 View Logs", callback_data=f"logs:{project}"),
                InlineKeyboardButton("🔄 Refresh", callback_data=f"action:status:{project}")
            ])
        
        keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data=f"pm:project:{project}")])
        
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        
        # Update last project and add persistent buttons for status view
        self.last_project = project
        await self.add_persistent_buttons(query.message, project)
    
    async def action_ask(self, query, context: ContextTypes.DEFAULT_TYPE, project: str):
        """Ask question action"""
        context.user_data['ask_project'] = project
        context.user_data['expecting'] = 'question'
        
        # Get recent questions
        recent = self.recent_questions.get_recent(project)
        
        text = f"❓ Type your question for {project}:\n"
        text += "(This will run in a temporary container with 1 iteration)\n\n"
        
        if recent:
            text += "Recent questions:\n"
            for i, q in enumerate(recent, 1):
                text += f"{i}. {q[:60]}...\n" if len(q) > 60 else f"{i}. {q}\n"
        
        try:
            await query.message.edit_text(text)
        except Exception as e:
            logger.error(f"Error editing message in action_ask: {e}")
            # If we can't edit the message, send a new one to the chat
            try:
                # Get the chat from the query and send a new message
                chat_id = query.message.chat_id
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=text
                )
            except Exception as e2:
                logger.error(f"Error sending new message in action_ask: {e2}")
    
    async def handle_ask_question(self, update: Update, context: ContextTypes.DEFAULT_TYPE, project: str, question: str):
        """Handle the actual question for ask flow"""
        # Clear expecting state
        context.user_data['expecting'] = None
        
        # Save question to history
        self.recent_questions.add_question(project, question)
        self.last_project = project  # Track for persistent buttons
        
        # Generate temp container name
        temp_name = f"temp_{int(time.time())}"
        
        # Prepare overrides
        overrides = [
            "--iterations", "1",
            "--prompt-append", question,
            "--container-name", temp_name
        ]
        
        await update.message.reply_text(
            f"🤖 Running your question in temporary container '{temp_name}'...\n"
            f"Project: {project}\n"
            f"Question: {question[:100]}..."
        )
        
        # Start the temporary container in a background task to avoid blocking
        asyncio.create_task(self._start_and_monitor_container(update.message, project, temp_name, overrides))
    
    async def _start_project_async(self, message, project: str):
        """Start project asynchronously - runs in background task"""
        try:
            success, output = await self.project_manager.start_project(project)
            
            if success:
                await message.edit_text(
                    f"✅ Started {project}\n\n{output}",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("📊 View Status", callback_data=f"action:status:{project}"),
                        InlineKeyboardButton("⬅️ Back", callback_data="pm:back")
                    ]])
                )
            else:
                await message.edit_text(
                    f"❌ Failed to start {project}\n\n{output}",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("⬅️ Back", callback_data="pm:back")
                    ]])
                )
        except Exception as e:
            logger.error(f"Error in _start_project_async: {e}")
            try:
                await message.edit_text(
                    f"❌ Error starting {project}: {str(e)}",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("⬅️ Back", callback_data="pm:back")
                    ]])
                )
            except:
                pass
    
    async def _start_and_monitor_container_from_query(self, message, project: str, temp_name: str, overrides: List[str]):
        """Start container and monitor it from query message - runs in background task"""
        try:
            # Start the temporary container
            success, output = await self.project_manager.start_project(project, overrides)
            
            if success:
                # Send a new message about the container starting
                new_message = await message.reply_text(
                    f"✅ Temporary container started!\n"
                    f"Container: {temp_name}\n"
                    f"Monitoring for completion..."
                )
                
                # Monitor container
                await self.monitor_temp_container(new_message, temp_name)
            else:
                await message.reply_text(
                    f"❌ Failed to start temporary container\n{output}"
                )
                # Add persistent buttons even on failure
                await self.add_persistent_buttons(message, project)
        except Exception as e:
            logger.error(f"Error in _start_and_monitor_container_from_query: {e}")
            try:
                await message.reply_text(f"❌ Error processing question: {str(e)}")
            except:
                pass
    
    async def _start_and_monitor_container(self, message, project: str, temp_name: str, overrides: List[str]):
        """Start container and monitor it - runs in background task"""
        try:
            # Start the temporary container
            success, output = await self.project_manager.start_project(project, overrides)
            
            if success:
                await message.reply_text(
                    f"✅ Temporary container started!\n"
                    f"Container: {temp_name}\n"
                    f"Monitoring for completion..."
                )
                
                # Monitor container
                await self.monitor_temp_container(message, temp_name)
            else:
                await message.reply_text(
                    f"❌ Failed to start temporary container\n{output}"
                )
                # Add persistent buttons even on failure
                await self.add_persistent_buttons(message, project)
        except Exception as e:
            logger.error(f"Error in _start_and_monitor_container: {e}")
            try:
                await message.reply_text(f"❌ Error processing question: {str(e)}")
            except:
                pass
    
    async def monitor_temp_container(self, message, container_name: str, max_wait: int = 300):
        """Monitor temporary container until completion"""
        chat_id = message.chat_id
        bot = message.get_bot()
        
        try:
            start_time = time.time()
            last_update = time.time()
            
            while time.time() - start_time < max_wait:
                # Check if bot is still running
                if not self.running:
                    logger.info(f"Bot shutting down, stopping monitor for {container_name}")
                    break
                    
                # Get container info
                info = await self.project_manager.get_container_info(container_name)
                
                if not info["exists"] or not info["running"]:
                    # Container stopped
                    logs = await self.project_manager.get_logs(container_name, tail=100)
                    
                    # Extract response
                    response = self.extract_response_from_logs(logs)
                    
                    try:
                        if response:
                            await bot.send_message(
                                chat_id=chat_id,
                                text=f"✅ Response received:\n\n{response[:4000]}"
                            )
                        else:
                            await bot.send_message(
                                chat_id=chat_id,
                                text=f"⚠️ Container completed but no clear response found.\n"
                                     f"Last logs:\n```\n{logs[-1000:]}\n```",
                                parse_mode=ParseMode.MARKDOWN
                            )
                    except Exception as e:
                        logger.error(f"Error sending completion message: {e}")
                    
                    # Clean up container
                    await self.project_manager.execute_command(["docker", "rm", container_name])
                    
                    # Add persistent buttons after ask completion
                    try:
                        await self.add_persistent_buttons_by_id(bot, chat_id, self.last_project)
                    except Exception as e:
                        logger.error(f"Error adding persistent buttons: {e}")
                    break
                
                # Send periodic updates
                if time.time() - last_update > 30:
                    progress = await self.project_manager.get_iteration_progress(container_name)
                    if progress:
                        try:
                            await bot.send_message(
                                chat_id=chat_id,
                                text=f"⏳ Still processing... ({progress[0]}/{progress[1]} iterations)"
                            )
                        except Exception as e:
                            logger.error(f"Error sending progress update: {e}")
                    last_update = time.time()
                
                await asyncio.sleep(5)
            else:
                # Timeout
                try:
                    await bot.send_message(
                        chat_id=chat_id,
                        text=f"⏱️ Timeout reached. Stopping container {container_name}"
                    )
                except Exception as e:
                    logger.error(f"Error sending timeout message: {e}")
                    
                await self.project_manager.execute_command(["docker", "stop", container_name])
                await self.project_manager.execute_command(["docker", "rm", container_name])
                
                # Add persistent buttons even on timeout
                try:
                    await self.add_persistent_buttons_by_id(bot, chat_id, self.last_project)
                except Exception as e:
                    logger.error(f"Error adding persistent buttons on timeout: {e}")
                
        except Exception as e:
            logger.error(f"Error monitoring container {container_name}: {e}")
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text=f"❌ Error monitoring container: {str(e)}\n"
                         f"Container: {container_name}"
                )
            except Exception as send_error:
                logger.error(f"Error sending error message: {send_error}")
            finally:
                # Try to clean up
                await self.project_manager.execute_command(["docker", "rm", "-f", container_name])
    
    def extract_response_from_logs(self, logs: str) -> Optional[str]:
        """Extract AI response from container logs"""
        # Look for patterns that indicate AI response
        # This is a simple implementation - adjust based on your log format
        
        lines = logs.split('\n')
        response_lines = []
        in_response = False
        
        for line in lines:
            # Look for response markers (adjust these patterns)
            if 'RESPONSE:' in line or 'Answer:' in line:
                in_response = True
                continue
            elif in_response and ('---' in line or 'END' in line):
                break
            elif in_response:
                response_lines.append(line)
        
        if response_lines:
            return '\n'.join(response_lines).strip()
        
        # Fallback: return last significant portion
        significant_lines = [l for l in lines if l.strip() and not l.startswith('[')]
        if significant_lines:
            return '\n'.join(significant_lines[-20:])
        
        return None
    
    async def handle_send_callback(self, query, context: ContextTypes.DEFAULT_TYPE, project: str):
        """Handle sending message to project"""
        message_text = context.user_data.get('pending_message', '')
        
        if not message_text:
            await query.message.edit_text("❌ No message to send")
            return
        
        # Get project path
        project_info = self.project_manager.projects_data["projects"].get(project)
        if not project_info:
            await query.message.edit_text(f"❌ Project {project} not found")
            return
        
        project_path = Path(project_info.get("path", ""))
        inbox_from = project_path / "inbox" / "from_human"
        inbox_from.mkdir(parents=True, exist_ok=True)
        
        # Create message file
        filename = f"telegram_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        
        content = f"# Message from Telegram\n\n"
        content += f"**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        content += f"---\n\n"
        content += message_text
        
        file_path = inbox_from / filename
        with open(file_path, 'w') as f:
            f.write(content)
        
        # Update message history
        self.message_history[project] = datetime.now()
        
        await query.message.edit_text(
            f"✅ Message sent to {project}\n"
            f"📄 File: {filename}"
        )
        
        # Clear pending message
        context.user_data['pending_message'] = None
        
        # Update last project
        self.last_project = project
        
        # Add persistent buttons
        await self.add_persistent_buttons(query.message, project)
    
    async def handle_batch_operation(self, query, operation: str):
        """Handle batch operations"""
        await query.message.edit_text(f"⏳ Processing batch operation: {operation}...")
        
        # Run batch operation in background to avoid blocking
        asyncio.create_task(self._run_batch_operation_async(query.message, operation))
    
    async def _run_batch_operation_async(self, message, operation: str):
        """Run batch operation asynchronously - runs in background task"""
        try:
            results = []
            
            if operation == 'start_all':
                for project in self.project_manager.projects_data["projects"]:
                    status = await self.project_manager.get_project_status(project)
                    if status.state == 'not_started':
                        success, _ = await self.project_manager.start_project(project)
                        results.append(f"{'✅' if success else '❌'} {project}")
            
            elif operation == 'pause_all':
                for project in self.project_manager.projects_data["projects"]:
                    status = await self.project_manager.get_project_status(project)
                    if status.state == 'running':
                        success, _ = await self.project_manager.pause_project(project)
                        results.append(f"{'✅' if success else '❌'} {project}")
            
            elif operation == 'stop_all':
                for project in self.project_manager.projects_data["projects"]:
                    status = await self.project_manager.get_project_status(project)
                    if status.state in ['running', 'paused']:
                        success, _ = await self.project_manager.stop_project(project)
                        results.append(f"{'✅' if success else '❌'} {project}")
            
            result_text = f"Batch operation '{operation}' completed:\n\n"
            result_text += '\n'.join(results) if results else "No projects affected"
            
            await message.edit_text(
                result_text,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ Back", callback_data="pm:back")
                ]])
            )
            
            # Add persistent buttons after batch operations
            await self.add_persistent_buttons(message)
            
        except Exception as e:
            logger.error(f"Error in _run_batch_operation_async: {e}")
            try:
                await message.edit_text(
                    f"❌ Error in batch operation: {str(e)}",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("⬅️ Back", callback_data="pm:back")
                    ]])
                )
            except:
                pass
    
    def start_inbox_monitoring(self, application):
        """Start monitoring inbox directories"""
        if not self.config.get('chat_id'):
            logger.warning("No chat_id configured, skipping inbox monitoring")
            return
            
        # Get the current event loop
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.get_event_loop()
            
        for project_name, project_info in self.project_manager.projects_data["projects"].items():
            project_path = Path(project_info.get("path", ""))
            inbox_path = project_path / "inbox" / "to_human"
            
            if inbox_path.exists():
                observer = Observer()
                watcher = InboxWatcher(
                    application.bot,
                    self.config['chat_id'],
                    self.project_manager,
                    self.processed_tracker,
                    loop=loop
                )
                observer.schedule(watcher, str(inbox_path), recursive=False)
                observer.start()
                self.observers[project_name] = observer
                logger.info(f"Started monitoring {project_name} inbox at {inbox_path}")
            else:
                logger.info(f"Inbox path does not exist for {project_name}: {inbox_path}")
    
    async def add_persistent_buttons(self, message, current_project=None):
        """Add persistent action buttons after operations"""
        keyboard = []
        
        # If we have a last project, add quick access buttons
        if self.last_project:
            keyboard.append([
                InlineKeyboardButton(f"📥 Inbox {self.last_project}", callback_data=f"quick_inbox:{self.last_project}"),
                InlineKeyboardButton(f"⚡ Actions {self.last_project}", callback_data=f"pm:project:{self.last_project}")
            ])
        
        # Always add general actions button
        keyboard.append([
            InlineKeyboardButton("🎯 All Actions", callback_data="pm:back")
        ])
        
        if keyboard:
            reply_markup = InlineKeyboardMarkup(keyboard)
            await message.reply_text(
                "Quick actions:",
                reply_markup=reply_markup
            )
    
    async def add_persistent_buttons_by_id(self, bot, chat_id, current_project=None):
        """Add persistent action buttons using bot and chat_id directly"""
        keyboard = []
        
        # If we have a last project, add quick access buttons
        if self.last_project:
            keyboard.append([
                InlineKeyboardButton(f"📥 Inbox {self.last_project}", callback_data=f"quick_inbox:{self.last_project}"),
                InlineKeyboardButton(f"⚡ Actions {self.last_project}", callback_data=f"pm:project:{self.last_project}")
            ])
        
        # Always add general actions button
        keyboard.append([
            InlineKeyboardButton("🎯 All Actions", callback_data="pm:back")
        ])
        
        if keyboard:
            reply_markup = InlineKeyboardMarkup(keyboard)
            await bot.send_message(
                chat_id=chat_id,
                text="Quick actions:",
                reply_markup=reply_markup
            )
    
    async def action_inbox(self, query, context: ContextTypes.DEFAULT_TYPE, project: str):
        """Handle inbox action - send message to project"""
        context.user_data['inbox_project'] = project
        context.user_data['expecting'] = 'inbox_message'
        
        await query.message.edit_text(
            f"📝 Type your message for {project}:\n"
            f"(This will be saved to the project's inbox/from_human/)"
        )
    
    async def send_to_inbox(self, update: Update, context: ContextTypes.DEFAULT_TYPE, project: str, message_text: str):
        """Send message to project inbox"""
        # Clear expecting state
        context.user_data['expecting'] = None
        self.last_project = project
        
        # Get project path
        project_info = self.project_manager.projects_data["projects"].get(project)
        if not project_info:
            await update.message.reply_text(f"❌ Project {project} not found")
            return
        
        project_path = Path(project_info.get("path", ""))
        inbox_from = project_path / "inbox" / "from_human"
        inbox_from.mkdir(parents=True, exist_ok=True)
        
        # Create message file
        filename = f"telegram_pm_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        
        content = f"# Message from Telegram PM Bot\n\n"
        content += f"**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        content += f"---\n\n"
        content += message_text
        
        file_path = inbox_from / filename
        with open(file_path, 'w') as f:
            f.write(content)
        
        await update.message.reply_text(
            f"✅ Message sent to {project}\n"
            f"📄 File: {filename}"
        )
        
        # Add persistent buttons
        await self.add_persistent_buttons(update.message, project)
    
    async def handle_direct_inbox(self, query, context: ContextTypes.DEFAULT_TYPE, project: str):
        """Handle direct inbox action from message routing"""
        message_text = context.user_data.get('pending_message', '')
        
        if not message_text:
            await query.message.edit_text("❌ No message to send")
            return
        
        # Update message history
        self.message_history[project] = datetime.now()
        self.last_project = project
        
        # Get project path
        project_info = self.project_manager.projects_data["projects"].get(project)
        if not project_info:
            await query.message.edit_text(f"❌ Project {project} not found")
            return
        
        project_path = Path(project_info.get("path", ""))
        inbox_from = project_path / "inbox" / "from_human"
        inbox_from.mkdir(parents=True, exist_ok=True)
        
        # Create message file
        filename = f"telegram_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        
        content = f"# Message from Telegram\n\n"
        content += f"**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        content += f"---\n\n"
        content += message_text
        
        file_path = inbox_from / filename
        with open(file_path, 'w') as f:
            f.write(content)
        
        await query.message.edit_text(
            f"✅ Message sent to {project} inbox\n"
            f"📄 File: {filename}"
        )
        
        # Clear pending message
        context.user_data['pending_message'] = None
        
        # Add persistent buttons
        await self.add_persistent_buttons(query.message, project)
    
    async def handle_direct_ask(self, query, context: ContextTypes.DEFAULT_TYPE, project: str):
        """Handle direct ask action from message routing"""
        question = context.user_data.get('pending_message', '')
        
        if not question:
            await query.message.edit_text("❌ No question to ask")
            return
        
        # Save question to history
        self.recent_questions.add_question(project, question)
        self.last_project = project
        
        # Generate temp container name
        temp_name = f"temp_{int(time.time())}"
        
        # Prepare overrides
        overrides = [
            "--iterations", "1",
            "--prompt-append", question,
            "--container-name", temp_name
        ]
        
        await query.message.edit_text(
            f"🤖 Running your question in temporary container '{temp_name}'...\n"
            f"Project: {project}\n"
            f"Question: {question[:100]}..."
        )
        
        # Clear pending message
        context.user_data['pending_message'] = None
        
        # Start and monitor container in background task to avoid blocking
        asyncio.create_task(self._start_and_monitor_container_from_query(query.message, project, temp_name, overrides))
    
    def cleanup(self):
        """Clean up resources"""
        self.running = False
        # Stop all observers
        for observer in self.observers.values():
            try:
                observer.stop()
                observer.join(timeout=2)
            except Exception as e:
                logger.error(f"Error stopping observer: {e}")
        self.observers.clear()
        logger.info("Cleanup completed")

async def setup_application(application: Application):
    """Setup application on startup"""
    bot_instance = application.bot_data.get('bot_instance')
    if bot_instance:
        # Set event loop for async operations
        loop = asyncio.get_running_loop()
        bot_instance.project_manager.set_event_loop(loop)
        
        if bot_instance.config.get('chat_id'):
            bot_instance.start_inbox_monitoring(application)

def main():
    """Main function"""
    # Create bot instance
    bot_instance = ProjectManagerBot()
    
    # Check if bot token is configured
    if not bot_instance.config.get('bot_token'):
        print("❌ No bot token configured!")
        print("Please add your bot token to:", CONFIG_FILE)
        print("Format: {\"bot_token\": \"YOUR_TOKEN\", \"chat_id\": \"\"}")
        return
    
    # Create application
    application = Application.builder().token(bot_instance.config['bot_token']).build()
    
    # Store bot instance in application and vice versa
    application.bot_data['bot_instance'] = bot_instance
    bot_instance.application = application
    
    # Add handlers
    application.add_handler(CommandHandler("start", bot_instance.start_command))
    application.add_handler(CommandHandler("pm", bot_instance.pm_command))
    application.add_handler(CommandHandler("status", bot_instance.status_command))
    application.add_handler(CommandHandler("restart_inbox", bot_instance.restart_inbox_command))
    application.add_handler(CallbackQueryHandler(bot_instance.handle_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot_instance.handle_message))
    
    # Setup post init
    application.post_init = setup_application
    
    # Signal handler
    def signal_handler(signum, frame):
        print("\n🛑 Shutting down gracefully...")
        bot_instance.cleanup()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Run bot with proper signal handling
    print("🤖 Starting Project Manager Bot...")
    print("Press Ctrl+C to stop")
    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user")
        bot_instance.cleanup()
    except Exception as e:
        logger.error(f"Bot crashed: {e}")
        bot_instance.cleanup()
        raise
    finally:
        bot_instance.cleanup()

if __name__ == "__main__":
    main()
