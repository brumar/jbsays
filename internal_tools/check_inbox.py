#!/usr/bin/env python3
import os
import argparse
from pathlib import Path
from datetime import datetime

INBOX_PATH = Path("inbox/from_human")
ARCHIVE_PATH = INBOX_PATH / "archive"
PROCESSED_SUFFIX = ".processed"

def get_file_status(file_path: Path):
    """Determines if a file is processed based on its name and location."""
    if file_path.parent == ARCHIVE_PATH and file_path.name.endswith(PROCESSED_SUFFIX):
        return "archived_processed"
    if file_path.name.endswith(PROCESSED_SUFFIX):
        return "processed"
    return "unprocessed"

def main():
    parser = argparse.ArgumentParser(description="Checks the human inbox for messages.")
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Show a summary of all messages, not just new ones.",
    )
    args = parser.parse_args()

    if not INBOX_PATH.exists():
        print(f"Inbox directory '{INBOX_PATH}' does not exist.")
        return

    ARCHIVE_PATH.mkdir(exist_ok=True)

    all_files = sorted(
        [f for f in INBOX_PATH.iterdir() if f.is_file() and f.suffix == '.md'] +
        [f for f in ARCHIVE_PATH.iterdir() if f.is_file() and f.suffix == '.md'],
        key=lambda p: p.stat().st_mtime, reverse=True
    )

    unprocessed_messages = []
    processed_messages = []
    archived_messages = []

    for f_path in all_files:
        status = get_file_status(f_path)
        if status == "unprocessed":
            unprocessed_messages.append(f_path)
        elif status == "processed":
            processed_messages.append(f_path)
        elif status == "archived_processed":
            archived_messages.append(f_path)

    if unprocessed_messages:
        print("CRITICAL: New unprocessed human messages found:")
        for msg_path in unprocessed_messages:
            print(f"  - {msg_path.relative_to(Path.cwd())}")
        print("Process these messages immediately.")
    else:
        print("No new unprocessed human messages found.")

    if args.summary:
        print("\n--- Inbox Summary ---")
        if unprocessed_messages:
            print("\nUnprocessed Messages:")
            for msg_path in unprocessed_messages:
                print(f"  - {msg_path.relative_to(Path.cwd())}")
        
        if processed_messages:
            print("\nProcessed Messages (in inbox, consider archiving):")
            for msg_path in processed_messages:
                 print(f"  - {msg_path.relative_to(Path.cwd())}")
        
        if archived_messages:
            print(f"\nArchived Processed Messages (last {min(5, len(archived_messages))}):")
            for msg_path in archived_messages[:5]:
                print(f"  - {msg_path.relative_to(Path.cwd())}")
        
        if not unprocessed_messages and not processed_messages and not archived_messages:
            print("Inbox is completely empty.")

if __name__ == "__main__":
    main()
