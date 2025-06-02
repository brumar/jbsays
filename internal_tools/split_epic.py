#!/usr/bin/env python3
import argparse
import re
from pathlib import Path

EPIC_STORY_DELIMITER = "--- EPICS_AND_STORIES_DELIMITER ---" # Standard delimiter
ALTERNATIVE_DELIMITER = "--- STORIES_START ---" # Alternative seen in logs

def sanitize_filename(title):
    """Sanitizes a title to be a valid filename."""
    # Remove problematic characters
    title = re.sub(r'[^\w\s-]', '', title)
    # Replace whitespace with underscores
    title = re.sub(r'\s+', '_', title)
    return f"{title}.md"

def extract_title(story_content):
    """Extracts title from story content."""
    match = re.search(r'^title:\s*"(.*?)"', story_content, re.MULTILINE)
    if match:
        return match.group(1)
    return None

def main():
    parser = argparse.ArgumentParser(description="Splits an epic file into individual story files.")
    parser.add_argument("epic_file", type=Path, help="Path to the epic markdown file.")
    parser.add_argument("output_dir", type=Path, help="Directory to save the individual story files.")
    args = parser.parse_args()

    if not args.epic_file.exists():
        print(f"Error: Epic file '{args.epic_file}' not found.")
        return

    args.output_dir.mkdir(parents=True, exist_ok=True)

    with open(args.epic_file, 'r', encoding='utf-8') as f:
        content = f.read()

    # Try standard delimiter first, then alternative
    if EPIC_STORY_DELIMITER in content:
        stories_raw = content.split(EPIC_STORY_DELIMITER)
    elif ALTERNATIVE_DELIMITER in content:
         stories_raw = content.split(ALTERNATIVE_DELIMITER)
    else:
        print(f"Error: Could not find a known story delimiter in '{args.epic_file}'.")
        print(f"Expected '{EPIC_STORY_DELIMITER}' or '{ALTERNATIVE_DELIMITER}'.")
        # Fallback: Treat the whole file as one story if no delimiter found,
        # but only if it seems to have a story structure (e.g., contains "title:")
        if "title:" in content:
            print("Attempting to parse as a single story file.")
            stories_raw = [content]
        else:
            print("No story structure found. Exiting.")
            return


    story_count = 0
    for i, story_block in enumerate(stories_raw):
        story_block = story_block.strip()
        if not story_block:
            continue

        # Ensure story block starts with '---' if it's not the first block (which might be an epic overview)
        if not story_block.startswith("---") and i > 0 : # First block might be epic overview
             story_block_with_header = "---\n" + story_block
        elif not story_block.startswith("---") and "title:" in story_block and i == 0: # First block is a story without ---
            story_block_with_header = "---\n" + story_block
        else:
            story_block_with_header = story_block


        # Add missing closing --- if needed
        if story_block_with_header.startswith("---") and story_block_with_header.count("---") % 2 != 0 :
             story_block_with_header += "\n---"


        title = extract_title(story_block_with_header)

        if title:
            # Skip the main epic overview if it's also captured as a story
            if "Epic" in title and "Overview" in title and i == 0 and len(stories_raw) > 1:
                 print(f"Skipping epic overview: {title}")
                 continue

            filename_title = title
            # Check if title already starts with a story number like "00XX_"
            if not re.match(r'^\d{4}_', title):
                # If not, prepend a placeholder or try to find one in the content
                # For simplicity, let's use a generic placeholder or skip numbering for now
                # A more advanced version could try to infer numbering
                pass # Keep original title if no number prefix
            
            output_filename = sanitize_filename(filename_title)
            output_path = args.output_dir / output_filename
            
            # Ensure the content starts and ends with '---' for proper frontmatter
            final_content = story_block_with_header
            if not final_content.startswith("---"):
                final_content = "---\n" + final_content
            if final_content.strip().count("---") % 2 != 0: # Ensure an even number of ---
                if not final_content.strip().endswith("---"):
                     final_content = final_content.strip() + "\n---"


            with open(output_path, 'w', encoding='utf-8') as sf:
                sf.write(final_content.strip() + "\n") # Ensure a newline at the end
            print(f"Created: {output_path}")
            story_count += 1
        elif i > 0: # Don't warn for the first block if it's an epic overview without a title
            print(f"Warning: Could not find title in story block {i+1}. Skipping.")

    print(f"\nSuccessfully split {story_count} stories from '{args.epic_file}' into '{args.output_dir}'.")

if __name__ == "__main__":
    main()
