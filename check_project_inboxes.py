#!/usr/bin/env python3
"""
Check inbox files across all projects and notify about new messages.
Uses the Linux desktop notification system (notify-send) for alerts.
"""

import os
import json
import argparse
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set, Tuple
import hashlib
import time


class InboxChecker:
    def __init__(self, projects_file: str = "projects.json", verbose: bool = False):
        self.projects_file = projects_file
        self.verbose = verbose
        self.processed_dir = Path.home() / ".telegram_inbox_bot" / "processed"
        self.processed_dir.mkdir(parents=True, exist_ok=True)
        self.projects = self._load_projects()
        
    def _load_projects(self) -> Dict:
        """Load projects configuration."""
        if not os.path.exists(self.projects_file):
            print(f"Error: {self.projects_file} not found")
            return {}
            
        try:
            with open(self.projects_file, 'r') as f:
                data = json.load(f)
                # Handle both old format (direct projects) and new format (nested)
                if 'projects' in data:
                    return data['projects']
                return data
        except Exception as e:
            print(f"Error loading projects: {e}")
            return {}
    
    def _get_file_hash(self, filepath: Path) -> str:
        """Get hash of file contents."""
        try:
            with open(filepath, 'rb') as f:
                return hashlib.sha256(f.read()).hexdigest()
        except:
            return ""
    
    def _load_processed_files(self, project_name: str) -> Set[str]:
        """Load processed file hashes for a project."""
        processed_file = self.processed_dir / f"{project_name}_processed.json"
        if processed_file.exists():
            try:
                with open(processed_file, 'r') as f:
                    data = json.load(f)
                    return set(data.get('processed_hashes', []))
            except:
                pass
        return set()
    
    def _save_processed_files(self, project_name: str, processed_hashes: Set[str]):
        """Save processed file hashes for a project."""
        processed_file = self.processed_dir / f"{project_name}_processed.json"
        try:
            data = {
                'processed_hashes': list(processed_hashes),
                'last_updated': datetime.now().isoformat()
            }
            with open(processed_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            if self.verbose:
                print(f"  Warning: Could not save processed files for {project_name}: {e}")
    
    def _check_project_inbox(self, project_name: str, project_config: Dict) -> Tuple[List[Path], List[Path]]:
        """Check a single project's inbox for new messages."""
        new_messages = []
        all_messages = []
        
        # Get project path from config
        project_path = project_config.get('path', '')
        if not project_path:
            if self.verbose:
                print(f"  No path configured for {project_name}")
            return [], []
        
        # Try common inbox locations in order of preference
        inbox_locations = [
            'inbox/to_human',
            'inbox',
            'rules/human_inbox', 
            'meta/human_inbox',
            'release/human_inbox'
        ]
        
        inbox_path = None
        for inbox_dir in inbox_locations:
            test_path = Path(project_path) / inbox_dir
            if test_path.exists() and test_path.is_dir():
                inbox_path = test_path
                if self.verbose:
                    print(f"  Found inbox at: {inbox_path}")
                break
        
        if not inbox_path:
            if self.verbose:
                print(f"  No inbox found for {project_name} at {project_path}")
            return [], []
        
        # Get processed files for this project
        processed_hashes = self._load_processed_files(project_name)
        current_hashes = set()
        
        # Check for .md files in inbox
        for file_path in inbox_path.glob("*.md"):
            if file_path.name.endswith('.processed'):
                continue
                
            all_messages.append(file_path)
            
            # Get file hash
            file_hash = self._get_file_hash(file_path)
            if file_hash:
                current_hashes.add(file_hash)
                
                # Check if this is a new message
                if file_hash not in processed_hashes:
                    new_messages.append(file_path)
        
        # Save current state as baseline for next run
        self._save_processed_files(project_name, current_hashes)
        
        return new_messages, all_messages
    
    def check_all_inboxes(self) -> Dict[str, Dict]:
        """Check all project inboxes and return status."""
        results = {}
        total_new = 0
        total_all = 0
        
        print(f"\n{'='*60}")
        print(f"Checking Project Inboxes - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}\n")
        
        for project_name, project_config in self.projects.items():
            if self.verbose:
                print(f"Checking {project_name}...")
                
            new_messages, all_messages = self._check_project_inbox(project_name, project_config)
            
            results[project_name] = {
                'new_messages': new_messages,
                'total_messages': len(all_messages),
                'new_count': len(new_messages)
            }
            
            total_new += len(new_messages)
            total_all += len(all_messages)
            
            # Display results for this project
            if new_messages:
                print(f"🔔 {project_name}: {len(new_messages)} NEW messages")
                if self.verbose:
                    for msg in new_messages:
                        print(f"   - {msg.name}")
            elif all_messages:
                print(f"✓ {project_name}: {len(all_messages)} messages (all read)")
            else:
                if self.verbose:
                    print(f"  {project_name}: No messages")
        
        print(f"\n{'='*60}")
        print(f"Summary: {total_new} new messages, {total_all} total messages")
        print(f"{'='*60}\n")
        
        return results
    
    def send_notification(self, results: Dict[str, Dict]):
        """Send notification using Linux desktop notification system."""
        new_count = sum(r['new_count'] for r in results.values())
        
        if new_count == 0:
            return
        
        # Build notification summary and body
        summary = f"📬 {new_count} new message(s) in project inboxes"
        
        body_parts = []
        projects_with_new = []
        for project_name, data in results.items():
            if data['new_count'] > 0:
                body_parts.append(f"{project_name}: {data['new_count']} new")
                projects_with_new.append(project_name)
        
        body = "\n".join(body_parts[:5])  # Limit to 5 projects
        if len(body_parts) > 5:
            body += f"\n... and {len(body_parts) - 5} more projects"
        
        # Determine which folder to open when clicked
        action_path = None
        if len(projects_with_new) == 1:
            # Single project - open its inbox folder
            project_name = projects_with_new[0]
            project_config = self.projects.get(project_name, {})
            project_path = project_config.get('path', '')
            if project_path:
                # Find the inbox folder for this project
                inbox_locations = [
                    'inbox/to_human',
                    'inbox',
                    'rules/human_inbox', 
                    'meta/human_inbox',
                    'release/human_inbox'
                ]
                for inbox_dir in inbox_locations:
                    test_path = Path(project_path) / inbox_dir
                    if test_path.exists() and test_path.is_dir():
                        action_path = str(test_path)
                        break
        
        # Send desktop notification using notify-send
        try:
            cmd = [
                'notify-send',
                '--urgency=normal',
                '--icon=mail-unread',
            ]
            
            # Add click action if we have a single project
            if action_path:
                cmd.extend(['--action=open=Open Folder'])
            
            cmd.extend([summary, body])
            
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            
            # Handle the action response
            if action_path and result.stdout.strip() == 'open':
                try:
                    subprocess.run(['xdg-open', action_path], check=True)
                    if self.verbose:
                        print(f"✅ Opened folder: {action_path}")
                except subprocess.CalledProcessError:
                    if self.verbose:
                        print(f"⚠️  Could not open folder: {action_path}")
            
            if self.verbose:
                print(f"\n✅ Desktop notification sent")
                print(f"Summary: {summary}")
                print(f"Body: {body}")
                if action_path:
                    print(f"Click action: Open {action_path}")
                
        except subprocess.CalledProcessError as e:
            print(f"\n⚠️  Failed to send desktop notification: {e}")
            print("Make sure notify-send is installed (usually part of libnotify)")
        except FileNotFoundError:
            print("\n⚠️  notify-send not found. Install it with:")
            print("  Ubuntu/Debian: sudo apt-get install libnotify-bin")
            print("  Fedora: sudo dnf install libnotify")
            print("  Arch: sudo pacman -S libnotify")
    
    def monitor_mode(self, interval: int = 60):
        """Continuously monitor inboxes."""
        print(f"Starting monitor mode (checking every {interval} seconds)")
        print("Press Ctrl+C to stop\n")
        
        try:
            while True:
                results = self.check_all_inboxes()
                self.send_notification(results)
                
                # Wait for next check
                print(f"\nNext check in {interval} seconds...")
                time.sleep(interval)
                
        except KeyboardInterrupt:
            print("\n\nMonitoring stopped.")


def main():
    parser = argparse.ArgumentParser(description='Check project inbox files for new messages')
    parser.add_argument('-p', '--projects', default='projects.json',
                        help='Path to projects.json file')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Show detailed output')
    parser.add_argument('-m', '--monitor', action='store_true',
                        help='Monitor mode - continuously check for new messages')
    parser.add_argument('-i', '--interval', type=int, default=60,
                        help='Check interval in seconds for monitor mode (default: 60)')
    parser.add_argument('--notify', action='store_true',
                        help='Send notification if new messages found')
    
    args = parser.parse_args()
    
    checker = InboxChecker(args.projects, args.verbose)
    
    if args.monitor:
        checker.monitor_mode(args.interval)
    else:
        results = checker.check_all_inboxes()
        if args.notify:
            checker.send_notification(results)
        
        # Exit with code 1 if there are new messages (useful for scripts)
        new_count = sum(r['new_count'] for r in results.values())
        exit(1 if new_count > 0 else 0)


if __name__ == "__main__":
    main()
