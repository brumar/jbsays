import json
import csv
import argparse
import os
from collections import defaultdict, Counter
from pathlib import Path
import re

# --- Configuration ---
HUMAN_LOG_TOOL_ID_LENGTH = 10
HUMAN_LOG_PREVIEW_LINES = 3     # Max lines for multi-line previews
HUMAN_LOG_MAX_CHARS_PER_FIELD = 150 # Max chars for ANY single field displayed in human log
HUMAN_LOG_TOTAL_PREVIEW_CHARS = 250 # Max overall chars for a preview if it's structured (like a dict)
CSV_PREVIEW_CHARS = 70

KNOWN_LARGE_FILES = ["/home/node/workspace/CLAUDE.md"]
COMMON_INBOX_PATHS = ["/home/node/workspace/meta/human_inbox",
                      "/home/node/workspace/rules/human_inbox",
                      "/home/node/workspace/release/human_inbox",
                      "/home/node/workspace/inbox"]

# --- Helper Functions ---
def summarize_content(content_input, max_lines=HUMAN_LOG_PREVIEW_LINES, max_chars=HUMAN_LOG_MAX_CHARS_PER_FIELD, is_csv=False, is_single_field_human=False):
    """Creates a preview of content.
    is_single_field_human: True if this is for a single text field in human log (e.g. assistant says)
    """
    if not isinstance(content_input, str):
        content = str(content_input)
    else:
        content = content_input

    original_char_count = len(content)
    lines = content.splitlines()
    num_lines = len(lines)

    suffix = ""

    if is_csv:
        if original_char_count > max_chars:
            suffix = f"...({original_char_count}c)"
        preview = content[:max_chars] + suffix
        preview = preview.replace("\n", " ").replace("\r", " ")
        return preview.strip()

    # For human-readable log (multi-line or single field)
    if is_single_field_human: # Applying to assistant text or single large tool result string
        if original_char_count > max_chars:
            preview = content[:max_chars]
            suffix = f"...({original_char_count}C)"
            # If truncated, ensure no partial words if possible, and add ellipsis
            if ' ' in preview: # try to cut at last space
                preview = preview.rsplit(' ', 1)[0] 
            preview += "..."
        else:
            preview = content
            suffix = f"({num_lines}L, {original_char_count}C)" if num_lines > 1 or original_char_count > 30 else ""
        return preview.strip() + (f" {suffix}" if suffix and preview != content else "")


    # Default human log summarization (often for structured data previews like tool inputs)
    # This part remains similar to your previous good version for structured previews
    if num_lines > max_lines:
        preview = "\n".join(lines[:max_lines])
        suffix = f"...({num_lines}L, {original_char_count}C)"
    else:
        preview = content
        if original_char_count > HUMAN_LOG_TOTAL_PREVIEW_CHARS : # Check against total preview chars for dicts
             suffix = f"...({original_char_count}C)"
        else:
            suffix = f"({num_lines}L, {original_char_count}C)" if num_lines > 1 or original_char_count > 30 else ""

    if len(preview) > HUMAN_LOG_TOTAL_PREVIEW_CHARS :
        preview = preview[:HUMAN_LOG_TOTAL_PREVIEW_CHARS]
        # If truncated, ensure no partial words if possible, and add ellipsis
        if ' ' in preview: # try to cut at last space
            preview = preview.rsplit(' ', 1)[0]
        preview += "..."


    return preview.strip() + (f" {suffix}" if suffix else "")


def get_short_tool_id(tool_use_id):
    if tool_use_id and isinstance(tool_use_id, str):
        return tool_use_id[:HUMAN_LOG_TOOL_ID_LENGTH]
    return "N/A"

# --- Core Parsing Logic (LogParser class) ---
# Largely the same, but ensure it populates `text_output_full` and raw content fields
# The key change will be in HumanLogGenerator's usage of these.
class LogParser:
    def __init__(self):
        self.parsed_actions = []
        self.session_data_aggregates = {}

    def _get_tool_name_for_result(self, session_id, tool_use_id):
        for action in reversed(self.parsed_actions): # Search within already parsed actions
            if action["session_id"] == session_id and \
               action["action_type"] == "tool_call" and \
               action["tool_use_id"] == tool_use_id:
                return action["tool_name"]
        # Fallback if no matching tool_call found (should be rare with full logs)
        if session_id in self.session_data_aggregates and \
           tool_use_id in self.session_data_aggregates[session_id]["tool_call_details"]:
            return self.session_data_aggregates[session_id]["tool_call_details"][tool_use_id]["name"]
        return "UnknownTool(ResultOnly)"


    def _init_session_aggregates(self, session_id):
        if session_id not in self.session_data_aggregates:
            self.session_data_aggregates[session_id] = {
                "claude_md_reads": 0,
                "inbox_ls_calls": 0,
                "file_read_counts": Counter(),
                "tool_call_inputs": {}, 
                "last_ls_path": None,
                "saw_python_fail": False,
                "saw_pip_fail": False,
                "tool_call_details": {} # session_id -> tool_use_id -> {"name": tool_name, "input": tool_input}
            }

    def parse_entry(self, log_entry, entry_sequence, filepath=""):
        session_id = log_entry.get("session_id")
        if not session_id: return

        self._init_session_aggregates(session_id)
        s_agg = self.session_data_aggregates[session_id]

        entry_type = log_entry.get("type")
        timestamp = log_entry.get("timestamp", None)

        base_action = {
            "session_id": session_id, "entry_sequence": entry_sequence,
            "original_filepath": Path(filepath).name, "timestamp": timestamp,
            "source": entry_type, "assistant_message_id": None, "model": None,
            "action_type": None, "text_output_preview": None, "text_output_full": None,
            "tool_name": None, "tool_use_id": None, "tool_input_raw": None,
            "tool_input_summary": None, "tool_input_human_display": None,
            "tool_result_status": None, "tool_result_raw_content": None,
            "tool_result_preview_csv": None, "tool_result_preview_human": None,
            "input_tokens": 0, "output_tokens": 0,
            "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
            "mcp_server_status_summary": None, "is_inefficient_flag": False,
            "inefficiency_type": None, "inefficiency_detail": None, "raw_entry": log_entry
        }
        
        if entry_type == "system" and log_entry.get("subtype") == "init":
            action = base_action.copy()
            action["action_type"] = "init"
            mcp_servers = log_entry.get("mcp_servers", [])
            status_parts = []
            for server in mcp_servers:
                status_parts.append(f"{server.get('name')}:{server.get('status')}")
                if server.get("status") == "failed":
                    action["is_inefficient_flag"] = True
                    action["inefficiency_type"] = "MCP_SERVER_FAILURE"
                    action["inefficiency_detail"] = f"MCP Server {server.get('name')} failed"
            action["mcp_server_status_summary"] = ";".join(status_parts)
            action["tools_available"] = log_entry.get("tools", [])
            self.parsed_actions.append(action)

        elif entry_type == "assistant":
            message = log_entry.get("message", {})
            usage = message.get("usage", {})
            common_assistant_fields = {
                "assistant_message_id": message.get("id"), "model": message.get("model", "unknown_model"),
                "input_tokens": usage.get("input_tokens", 0), "output_tokens": usage.get("output_tokens", 0),
                "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0),
                "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0),
            }
            if "content" in message:
                for content_item in message["content"]:
                    action = base_action.copy()
                    action.update(common_assistant_fields)
                    if content_item.get("type") == "text":
                        action["action_type"] = "text_output"
                        text = content_item.get("text", "")
                        action["text_output_full"] = text # Store full text for human log
                        action["text_output_preview"] = summarize_content(text, max_lines=1, max_chars=CSV_PREVIEW_CHARS, is_csv=True)
                        self.parsed_actions.append(action)
                    elif content_item.get("type") == "tool_use":
                        action["action_type"] = "tool_call"
                        action["tool_name"] = content_item.get("name")
                        action["tool_use_id"] = content_item.get("id")
                        raw_input = content_item.get("input", {})
                        action["tool_input_raw"] = raw_input
                        
                        s_agg["tool_call_details"][action["tool_use_id"]] = {"name": action["tool_name"], "input": raw_input}


                        if isinstance(raw_input, dict):
                            human_display_dict, csv_summary_dict = {}, {}
                            for k, v_in in raw_input.items():
                                if k == 'content' and isinstance(v_in, str) and len(v_in) > HUMAN_LOG_MAX_CHARS_PER_FIELD * 1.2: # Check if 'content' is large
                                    human_display_dict[k] = f"<Content Preview: {summarize_content(v_in, max_chars=HUMAN_LOG_MAX_CHARS_PER_FIELD, is_single_field_human=True)}>"
                                    csv_summary_dict[k] = f"<Content Preview: {summarize_content(v_in, max_chars=CSV_PREVIEW_CHARS, is_csv=True)}>"
                                    if not action["is_inefficient_flag"]: # Don't overwrite existing inefficiency
                                        action["is_inefficient_flag"] = True
                                        action["inefficiency_type"] = "LARGE_TOOL_INPUT"
                                        action["inefficiency_detail"] = f"Tool {action['tool_name']} called with large 'content' field ({len(v_in)} chars)."
                                else: # For other fields or smaller content
                                    human_display_dict[k] = str(v_in) # Keep as string for human log to decide summarization
                                    csv_summary_dict[k] = summarize_content(str(v_in), max_chars=CSV_PREVIEW_CHARS, is_csv=True)
                            action["tool_input_human_display"] = json.dumps(human_display_dict) # Will be parsed and summarized by HumanLogGenerator
                            action["tool_input_summary"] = json.dumps(csv_summary_dict)
                        else: # Input is not a dict
                            action["tool_input_human_display"] = str(raw_input) # Keep as string
                            action["tool_input_summary"] = summarize_content(str(raw_input), max_chars=CSV_PREVIEW_CHARS, is_csv=True)

                        # Specific tool inefficiency checks
                        if action["tool_name"] == "Read":
                            file_path = raw_input.get("file_path", "")
                            s_agg["file_read_counts"][file_path] += 1
                            if file_path in KNOWN_LARGE_FILES and "limit" not in raw_input and not action["is_inefficient_flag"]:
                                action["is_inefficient_flag"], action["inefficiency_type"], action["inefficiency_detail"] = True, "READ_LARGE_FILE_NO_LIMIT", f"Read tool called on known large file '{file_path}' without limit."
                            if s_agg["file_read_counts"][file_path] > 1 and not action["is_inefficient_flag"]:
                                action["is_inefficient_flag"], action["inefficiency_type"], action["inefficiency_detail"] = True, "REPEATED_FILE_READ", f"File '{file_path}' read {s_agg['file_read_counts'][file_path]} times this session."
                            if file_path == "/home/node/workspace/CLAUDE.md":
                                s_agg["claude_md_reads"] += 1
                                if s_agg["claude_md_reads"] > 1 and not action["is_inefficient_flag"]:
                                    action["is_inefficient_flag"], action["inefficiency_type"], action["inefficiency_detail"] = True, "REPEATED_CLAUDE_MD_READ", f"CLAUDE.md read {s_agg['claude_md_reads']} times this session."
                        elif action["tool_name"] == "LS":
                            ls_path = raw_input.get("path", "")
                            if ls_path in COMMON_INBOX_PATHS:
                                s_agg["inbox_ls_calls"] +=1
                                if s_agg["inbox_ls_calls"] > 3 and not action["is_inefficient_flag"]:
                                    action["is_inefficient_flag"], action["inefficiency_type"], action["inefficiency_detail"] = True, "REPEATED_INBOX_LS", f"Inbox LS calls: {s_agg['inbox_ls_calls']} times this session."
                            if ls_path in ["/home/node/workspace", "/home/node/workspace/release/content", "/home/node/workspace/release"] and \
                               s_agg["last_ls_path"] == ls_path and not action["is_inefficient_flag"]:
                                action["is_inefficient_flag"], action["inefficiency_type"], action["inefficiency_detail"] = True, "REPEATED_BROAD_LS", f"Repeated LS on broad path: {ls_path}"
                            s_agg["last_ls_path"] = ls_path
                        elif action["tool_name"] == "Bash":
                            command = raw_input.get("command", "")
                            if "find " in command and " -exec " in command and not command.strip().endswith("\\;"):
                                if not action["is_inefficient_flag"]: action["is_inefficient_flag"], action["inefficiency_type"], action["inefficiency_detail"] = True, "SUSPICIOUS_FIND_EXEC", "find -exec command may be missing trailing \\;."
                            if command.strip().startswith("python "): s_agg["saw_python_fail"] = True
                        self.parsed_actions.append(action)

        elif entry_type == "user":
            message = log_entry.get("message", {})
            if "content" in message:
                for content_item in message["content"]:
                    if content_item.get("type") == "tool_result":
                        action = base_action.copy()
                        action["action_type"] = "tool_result"
                        action["tool_use_id"] = content_item.get("tool_use_id")
                        action["tool_name"] = self._get_tool_name_for_result(session_id, action["tool_use_id"])
                        
                        original_tool_input = s_agg["tool_call_details"].get(action["tool_use_id"], {}).get("input",{})

                        result_content_list = content_item.get("content", "")
                        actual_text_content = "" # This will be the string form of the content
                        
                        # More robust extraction of actual_text_content
                        if isinstance(result_content_list, list) and result_content_list:
                            first_item = result_content_list[0]
                            if isinstance(first_item, dict):
                                actual_text_content = str(first_item.get("content", json.dumps(result_content_list))) # Prioritize "content" key
                            else: # list of non-dicts (e.g. strings)
                                actual_text_content = "\n".join(map(str,result_content_list))
                        elif isinstance(result_content_list, str):
                             actual_text_content = result_content_list
                        else: # Fallback for other types
                            actual_text_content = str(result_content_list)
                        
                        action["tool_result_raw_content"] = actual_text_content # Store full raw content string
                        action["tool_result_status"] = "SUCCESS"
                        preview_human, preview_csv = "", ""
                        ineff_detail_suffix = ""

                        if "<system-reminder>Warning: the file exists but the contents are empty.</system-reminder>" in actual_text_content:
                            action["is_inefficient_flag"], action["inefficiency_type"] = True, "EMPTY_FILE_READ"
                            action["tool_result_status"], preview_human, preview_csv = "EMPTY_FILE", "File empty.", "File empty."
                            ineff_detail_suffix = f"Tool {action['tool_name']} read an empty file: {original_tool_input.get('file_path', '')}"
                        elif "There are more than 40000 characters" in actual_text_content:
                            action["is_inefficient_flag"], action["inefficiency_type"] = True, "LARGE_OUTPUT"
                            action["tool_result_status"], preview_human, preview_csv = "LARGE_OUTPUT", "Large output (>40k chars).", "Large output (>40k)."
                            ineff_detail_suffix = f"Tool {action['tool_name']} on path '{original_tool_input.get('path', '')}' returned >40k chars."
                        elif re.search(r"(?i)\b(Error|Failed|Traceback|Exception|No such file|not found)\b", actual_text_content, re.IGNORECASE) or \
                             (isinstance(result_content_list, list) and result_content_list and result_content_list[0].get("is_error")): # Check for "is_error" in the first item if it's a list of dicts
                            action["is_inefficient_flag"], action["inefficiency_type"] = True, "TOOL_ERROR"
                            action["tool_result_status"] = "ERROR"
                            preview_human = summarize_content(actual_text_content, max_lines=1, max_chars=HUMAN_LOG_MAX_CHARS_PER_FIELD, is_single_field_human=True)
                            preview_csv = summarize_content(actual_text_content, max_lines=1, max_chars=CSV_PREVIEW_CHARS, is_csv=True)
                            ineff_detail_suffix = f"Tool {action['tool_name']} error: {preview_csv}"
                            if action["tool_name"] == "Task": action["inefficiency_type"] = "TASK_TOOL_ERROR"
                            if s_agg["saw_python_fail"] and "command not found: python" in actual_text_content:
                                action["inefficiency_type"], ineff_detail_suffix = "PYTHON_COMMAND_FAIL", "'python' command failed, 'python3' might be needed."
                            s_agg["saw_python_fail"] = False
                            if "No module named pip" in actual_text_content:
                                action["inefficiency_type"], ineff_detail_suffix = "PIP_MODULE_FAIL", "'python -m pip' failed. Pip might not be installed correctly."
                        else:
                            preview_human = summarize_content(actual_text_content, is_single_field_human=True) # Summarize for single field display
                            preview_csv = summarize_content(actual_text_content, max_chars=CSV_PREVIEW_CHARS, is_csv=True)
                        
                        action["tool_result_preview_human"] = preview_human
                        action["tool_result_preview_csv"] = preview_csv
                        if ineff_detail_suffix: action["inefficiency_detail"] = ineff_detail_suffix
                        self.parsed_actions.append(action)

    def get_parsed_actions(self):
        return self.parsed_actions

    def reset(self):
        self.parsed_actions = []
        self.session_data_aggregates = {}

# --- CSV Output Generator (unchanged) ---
class CsvGenerator:
    FIELDNAMES = [
        "session_id", "entry_sequence", "original_filepath", "timestamp", "source",
        "assistant_message_id", "model", "action_type",
        "text_output_preview", "tool_name", "tool_use_id",
        "tool_input_summary", "tool_result_status", "tool_result_preview_csv",
        "input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens",
        "mcp_server_status_summary", "is_inefficient_flag", "inefficiency_type", "inefficiency_detail"
    ]
    def __init__(self, filepath):
        self.filepath = filepath
        self.file = open(self.filepath, 'w', newline='', encoding='utf-8')
        self.writer = csv.DictWriter(self.file, fieldnames=self.FIELDNAMES, extrasaction='ignore')
        self.writer.writeheader()
    def write_action(self, action_data):
        self.writer.writerow(action_data)
    def close(self):
        if self.file: self.file.close()

# --- Human-Readable Log Generator (UPDATED) ---
class HumanLogGenerator:
    def __init__(self, filepath=None):
        self.filepath = filepath
        if self.filepath:
            self.file = open(self.filepath, 'w', encoding='utf-8')
        else:
            self.file = None 
        self.current_session_id = None
        self.last_assistant_message_id = None
        self.last_model = None

    def _write(self, line):
        if self.file:
            self.file.write(line + "\n")
        else:
            print(line)

    def _summarize_for_human_log(self, data_str):
        """Dedicated summarizer for human log fields to ensure compactness."""
        return summarize_content(data_str, max_chars=HUMAN_LOG_MAX_CHARS_PER_FIELD, is_single_field_human=True)

    def write_action(self, action_data):
        session_id = action_data["session_id"]
        if session_id != self.current_session_id:
            if self.current_session_id is not None: self._write("-" * 70)
            self._write(f"SESSION: {session_id} (From: {action_data['original_filepath']})")
            self._write("-" * 70)
            self.current_session_id = session_id
            self.last_assistant_message_id = None # Reset for new session
            self.last_model = None

        source = action_data["source"]
        action_type = action_data["action_type"]
        
        ineff_str = ""
        if action_data["is_inefficient_flag"]:
            detail_preview = summarize_content(action_data.get("inefficiency_detail", ""), max_chars=50, is_csv=True) # Short for inline
            ineff_str = f" ❗{action_data['inefficiency_type']}"
            if detail_preview and detail_preview != "N/A":
                 ineff_str += f" ({detail_preview})"


        if action_type == "init":
            tools_avail_count = len(action_data.get("tools_available", []))
            self._write(f"[SYSTEM] Init. Tools: {tools_avail_count}. MCP: {action_data.get('mcp_server_status_summary','N/A')}{ineff_str}")
            self._write("-" * 70)

        elif source == "assistant":
            if action_data["assistant_message_id"] != self.last_assistant_message_id:
                if self.last_assistant_message_id is not None: self._write("-" * 70)
                model_info = f"(Model: {action_data['model']})" if action_data['model'] != self.last_model else ""
                token_info = f"Tokens: In:{action_data['input_tokens']} Out:{action_data['output_tokens']} CacheC:{action_data['cache_creation_input_tokens']} CacheR:{action_data['cache_read_input_tokens']}"
                self._write(f"🤖 ASSISTANT {model_info} | {token_info}")
                self.last_assistant_message_id = action_data["assistant_message_id"]
                self.last_model = action_data['model']
            
            indent = "   "
            if action_type == "text_output":
                # Use the dedicated summarizer for assistant's speech
                display_text = self._summarize_for_human_log(action_data['text_output_full'])
                self._write(f"{indent}🗣️ \"{display_text}\"")
            elif action_type == "tool_call":
                tool_id_short = get_short_tool_id(action_data['tool_use_id'])
                self._write(f"{indent}🛠️ Calls **{action_data['tool_name']}** (ID: {tool_id_short}){ineff_str}")
                
                # Summarize tool input for human log
                tool_input_display_str = action_data['tool_input_human_display']
                # If it's a JSON string (likely from dict conversion), parse and summarize each value if too long
                try:
                    parsed_input = json.loads(tool_input_display_str)
                    if isinstance(parsed_input, dict):
                        summarized_dict_input = {}
                        for k, v in parsed_input.items():
                            summarized_dict_input[k] = self._summarize_for_human_log(str(v))
                        tool_input_display_str_final = json.dumps(summarized_dict_input)
                    else: # was not a dict string, summarize as is
                        tool_input_display_str_final = self._summarize_for_human_log(tool_input_display_str)
                except json.JSONDecodeError: # Not a JSON string, summarize as is
                    tool_input_display_str_final = self._summarize_for_human_log(tool_input_display_str)
                
                self._write(f"{indent}    ➡️ Input: {tool_input_display_str_final}")


        elif action_type == "tool_result":
            tool_id_short = get_short_tool_id(action_data['tool_use_id'])
            # Use the dedicated summarizer for tool result text
            display_result = self._summarize_for_human_log(action_data['tool_result_preview_human'])
            self._write(f"   💡 Result (for **{action_data['tool_name']}** ID: {tool_id_short}): {display_result}{ineff_str}")

    def close(self):
        if self.file:
            self.file.close()


# --- Summary Report Generator (largely unchanged, uses updated inefficiency fields) ---
def generate_summary_report(parsed_actions):
    sessions_data_for_summary = {}
    for pa in parsed_actions:
        session_id = pa["session_id"]
        if session_id not in sessions_data_for_summary:
            sessions_data_for_summary[session_id] = {
                "session_id": session_id, "original_filepath": pa["original_filepath"],
                "tools_available": [], "mcp_server_status": [], "tokens": defaultdict(int),
                "model_usage": defaultdict(lambda: defaultdict(int)),
                "assistant_turns_count": 0, "tool_calls_summary": defaultdict(int),
                "tool_sequences_count": 0, 
                "detected_inefficiencies": [], 
                "assistant_message_ids_seen": set()
            }
        s_data = sessions_data_for_summary[session_id]
        if pa["is_inefficient_flag"]:
            s_data["detected_inefficiencies"].append({
                "type": pa["inefficiency_type"],
                "detail": pa.get("inefficiency_detail", "N/A"),
                "tool_name": pa.get("tool_name") 
            })
        if pa["action_type"] == "init":
            s_data["tools_available"] = pa.get("tools_available", [])
            if pa.get("mcp_server_status_summary"): s_data["mcp_server_status"] = pa["mcp_server_status_summary"].split(';')
        if pa["source"] == "assistant":
            if pa["assistant_message_id"] not in s_data["assistant_message_ids_seen"]:
                s_data["assistant_turns_count"] += 1
                s_data["assistant_message_ids_seen"].add(pa["assistant_message_id"])
            s_data["tokens"]["input"] += pa["input_tokens"]; s_data["tokens"]["output"] += pa["output_tokens"]
            s_data["tokens"]["cache_creation_input"] += pa["cache_creation_input_tokens"]; s_data["tokens"]["cache_read_input"] += pa["cache_read_input_tokens"]
            model = pa["model"]
            s_data["model_usage"][model]["input_tokens"] += pa["input_tokens"]; s_data["model_usage"][model]["output_tokens"] += pa["output_tokens"]
            s_data["model_usage"][model]["cache_creation_input_tokens"] += pa["cache_creation_input_tokens"]; s_data["model_usage"][model]["cache_read_input_tokens"] += pa["cache_read_input_tokens"]
            if pa["action_type"] == "tool_call": s_data["tool_calls_summary"][pa["tool_name"]] += 1
        if pa["action_type"] == "tool_result": s_data["tool_sequences_count"] += 1
    
    for session_id, data in sessions_data_for_summary.items():
        print(f"\n--- Session Summary Report: {session_id} (From: {data['original_filepath']}) ---")
        print(f"  Assistant Turns: {data['assistant_turns_count']}")
        print(f"  Tool Use Sequences: {data['tool_sequences_count']}")
        print("\n  Token Consumption:"); [print(f"    Total {k.replace('_', ' ').title()}: {v}") for k,v in data['tokens'].items()]
        if data['assistant_turns_count'] > 0:
            print(f"    Avg Input Tokens per Assistant Turn: {data['tokens']['input'] / data['assistant_turns_count']:.2f}")
            print(f"    Avg Output Tokens per Assistant Turn: {data['tokens']['output'] / data['assistant_turns_count']:.2f}")
        print("\n  Model Usage:"); [[print(f"    Model: {model}"), [print(f"      {k.replace('_', ' ').title()}: {v}") for k,v in usage.items()]] for model, usage in data['model_usage'].items()]
        print("\n  Tools Available:"); print(f"    {', '.join(data.get('tools_available', ['Not captured']))}")
        print("\n  Tool Calls Frequency:"); [print(f"    {tool}: {count}") for tool, count in sorted(data['tool_calls_summary'].items())] if data['tool_calls_summary'] else print("    No tools called.")
        print("\n  MCP Server Status:"); [print(f"    {status}") for status in data.get('mcp_server_status',["N/A"])]
        print("\n  Detected Inefficiencies/Errors:")
        if data['detected_inefficiencies']:
            for ineff in data['detected_inefficiencies']:
                tool_info = f", Tool: {ineff['tool_name']}" if ineff.get('tool_name') else ""
                print(f"    - Type: {ineff['type']}{tool_info}\n      Detail: {summarize_content(ineff['detail'], max_chars=100, is_single_field_human=True)}") # Summarize detail here too
        else: print("    None explicitly detected by this script for this session.")
    
    print("\n--- Overall Summary (Across All Processed Logs) ---")
    all_inefficiencies = Counter()
    total_actions = len(parsed_actions)
    inefficient_actions = sum(1 for pa in parsed_actions if pa["is_inefficient_flag"])
    print(f"Total Actions Parsed: {total_actions}")
    print(f"Actions Flagged as Inefficient/Error: {inefficient_actions} ({ (inefficient_actions/total_actions*100) if total_actions else 0 :.1f}%)")
    for data in sessions_data_for_summary.values():
        for ineff in data['detected_inefficiencies']: all_inefficiencies[ineff['type']] += 1
    print("\n  Overall Inefficiency Counts:")
    if all_inefficiencies: [print(f"    {ineff_type}: {count}") for ineff_type, count in all_inefficiencies.most_common()]
    else: print("    No inefficiencies detected across all sessions.")

# --- Main Orchestration (unchanged) ---
def main():
    parser = argparse.ArgumentParser(description="Audit AI agent efficiency from JSON log files in a folder.")
    parser.add_argument("logfolder", help="Path to the folder containing log files (one JSON per line).")
    parser.add_argument("--csv_output", help="Path to save the CSV output file.", default="audit_report.csv")
    parser.add_argument("--human_log_output", help="Path to save the human-readable log file (optional, prints to console if not specified).")
    parser.add_argument("--summary_report", action="store_true", help="Print a summary report to the console.")
    parser.add_argument("--log_extensions", default=".jsonl,.log,.txt", help="Comma-separated list of log file extensions to process.")
    args = parser.parse_args()

    if not os.path.isdir(args.logfolder):
        print(f"Error: Log folder not found at {args.logfolder}")
        return

    log_parser = LogParser()
    extensions_to_process = tuple(args.log_extensions.split(','))
    
    log_files = sorted([Path(args.logfolder) / f for f in os.listdir(args.logfolder) if f.endswith(extensions_to_process)])
    if not log_files:
        print(f"No log files with extensions {extensions_to_process} found in {args.logfolder}")
        return

    print(f"Processing {len(log_files)} log file(s)...")
    processed_files_count = 0
    for log_file_path in log_files:
        print(f"  Processing: {log_file_path.name}")
        try:
            with open(log_file_path, 'r', encoding='utf-8') as f:
                for line_number, line in enumerate(f, 1):
                    try:
                        if not line.strip(): continue
                        log_entry = json.loads(line)
                        log_parser.parse_entry(log_entry, line_number, filepath=str(log_file_path))
                    except json.JSONDecodeError: print(f"    Warning: Could not decode JSON on line {line_number} in {log_file_path.name}. Skipping.")
                    except Exception as e: print(f"    Warning: Error processing line {line_number} in {log_file_path.name}: {e}. Skipping.")
            processed_files_count +=1
        except Exception as e: print(f"  Error reading file {log_file_path.name}: {e}")
    
    print(f"Completed processing {processed_files_count} file(s).")
    all_parsed_actions = log_parser.get_parsed_actions()

    if not all_parsed_actions:
        print("No actions parsed from log files.")
        return

    if args.csv_output:
        print(f"\nGenerating CSV report to {args.csv_output}...")
        csv_gen = CsvGenerator(args.csv_output)
        for action in all_parsed_actions: csv_gen.write_action(action)
        csv_gen.close()
        print("CSV report generated.")

    print(f"\nGenerating human-readable log...")
    human_log_gen = HumanLogGenerator(args.human_log_output)
    for action in all_parsed_actions: human_log_gen.write_action(action)
    human_log_gen.close()
    if args.human_log_output: print(f"Human-readable log saved to {args.human_log_output}.")
    else: print("Human-readable log printed to console.")
        
    if args.summary_report:
        print("\nGenerating summary report...")
        generate_summary_report(all_parsed_actions) 
        print("Summary report generated.")

    print("\nAudit complete.")

if __name__ == "__main__":
    main()
