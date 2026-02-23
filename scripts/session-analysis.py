#!/usr/bin/env python3
"""
Session Data Extractor for Flux Improve

Extracts raw session data from AI coding agents for LLM analysis.
Supports:
- OpenCode (SQLite database)
- Claude Code (JSONL files)

The intelligent analysis (frustration detection, pattern recognition)
is done by the agent running /nbench:improve, not this script.
"""

import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# Session storage locations
OPENCODE_DB = Path.home() / ".local/share/opencode/opencode.db"
CLAUDE_CODE_DIR = Path.home() / ".claude/projects"


def detect_agent() -> str:
    """Detect which agent's session data is available."""
    if OPENCODE_DB.exists():
        return "opencode"
    if CLAUDE_CODE_DIR.exists():
        return "claude-code"
    return "unknown"


def get_claude_code_project_path(directory: str) -> Path | None:
    """Get Claude Code project folder for a directory."""
    encoded = directory.replace("/", "-").lstrip("-")
    project_dir = CLAUDE_CODE_DIR / f"-{encoded}"
    if project_dir.exists():
        return project_dir
    project_dir = CLAUDE_CODE_DIR / encoded
    if project_dir.exists():
        return project_dir
    return None


# ============== OpenCode Functions ==============


def get_opencode_sessions(directory: str, limit: int = 20) -> list[dict]:
    if not OPENCODE_DB.exists():
        return []

    conn = sqlite3.connect(OPENCODE_DB)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT 
            s.id, s.title, s.summary_additions, s.summary_deletions,
            s.summary_files, s.time_created, s.time_updated,
            (SELECT COUNT(*) FROM message m WHERE m.session_id = s.id) as message_count
        FROM session s
        WHERE s.directory = ?
        ORDER BY s.time_created DESC
        LIMIT ?
        """,
        (directory, limit),
    )

    sessions = []
    for row in cursor.fetchall():
        sessions.append(
            {
                "id": row["id"],
                "title": row["title"],
                "additions": row["summary_additions"],
                "deletions": row["summary_deletions"],
                "files": row["summary_files"],
                "messages": row["message_count"],
                "created": datetime.fromtimestamp(
                    row["time_created"] / 1000
                ).isoformat(),
            }
        )

    conn.close()
    return sessions


def get_opencode_conversation_sample(directory: str, limit: int = 100) -> list[dict]:
    if not OPENCODE_DB.exists():
        return []

    conn = sqlite3.connect(OPENCODE_DB)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT 
            s.title as session_title,
            json_extract(m.data, '$.role') as role,
            json_extract(p.data, '$.text') as text,
            datetime(m.time_created/1000, 'unixepoch', 'localtime') as timestamp
        FROM part p
        JOIN message m ON p.message_id = m.id
        JOIN session s ON m.session_id = s.id
        WHERE s.directory = ?
            AND json_extract(p.data, '$.type') = 'text'
            AND json_extract(p.data, '$.text') IS NOT NULL
            AND length(json_extract(p.data, '$.text')) > 10
            AND length(json_extract(p.data, '$.text')) < 2000
        ORDER BY m.time_created DESC
        LIMIT ?
        """,
        (directory, limit),
    )

    messages = []
    for row in cursor.fetchall():
        text = row[2]
        if text and not text.startswith("<beads-") and not text.startswith("[MEMORY"):
            messages.append(
                {
                    "session": row[0],
                    "role": row[1],
                    "text": text[:500] + "..." if len(text) > 500 else text,
                    "time": row[3],
                }
            )

    conn.close()
    return list(reversed(messages))


def get_opencode_friction_signals(directory: str) -> list[dict]:
    if not OPENCODE_DB.exists():
        return []

    conn = sqlite3.connect(OPENCODE_DB)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT 
            s.title as session_title,
            json_extract(p.data, '$.text') as text,
            datetime(m.time_created/1000, 'unixepoch', 'localtime') as timestamp
        FROM part p
        JOIN message m ON p.message_id = m.id
        JOIN session s ON m.session_id = s.id
        WHERE s.directory = ?
            AND json_extract(m.data, '$.role') = 'user'
            AND json_extract(p.data, '$.type') = 'text'
            AND (
                lower(json_extract(p.data, '$.text')) LIKE '%again%'
                OR lower(json_extract(p.data, '$.text')) LIKE '%still%'
                OR lower(json_extract(p.data, '$.text')) LIKE '%bruh%'
                OR lower(json_extract(p.data, '$.text')) LIKE '%why%'
                OR lower(json_extract(p.data, '$.text')) LIKE '%fail%'
                OR lower(json_extract(p.data, '$.text')) LIKE '%error%'
                OR lower(json_extract(p.data, '$.text')) LIKE '%not work%'
                OR lower(json_extract(p.data, '$.text')) LIKE '%broken%'
                OR lower(json_extract(p.data, '$.text')) LIKE '%wrong%'
                OR lower(json_extract(p.data, '$.text')) LIKE '%rip%'
                OR lower(json_extract(p.data, '$.text')) LIKE '%nani%'
                OR lower(json_extract(p.data, '$.text')) LIKE '%confused%'
                OR lower(json_extract(p.data, '$.text')) LIKE '%i thought%'
                OR lower(json_extract(p.data, '$.text')) LIKE '%already%'
                OR lower(json_extract(p.data, '$.text')) LIKE '%try again%'
            )
        ORDER BY m.time_created DESC
        LIMIT 30
        """,
        (directory,),
    )

    patterns = []
    for row in cursor.fetchall():
        text = row[1]
        if text and len(text) > 5:
            patterns.append(
                {
                    "session": row[0],
                    "prompt": text[:300] + "..." if len(text) > 300 else text,
                    "time": row[2],
                }
            )

    conn.close()
    return patterns


def get_opencode_tool_usage(directory: str) -> dict:
    if not OPENCODE_DB.exists():
        return {}

    conn = sqlite3.connect(OPENCODE_DB)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT 
            json_extract(p.data, '$.name') as tool_name,
            COUNT(*) as count
        FROM part p
        JOIN message m ON p.message_id = m.id
        JOIN session s ON m.session_id = s.id
        WHERE s.directory = ?
            AND json_extract(m.data, '$.role') = 'assistant'
            AND json_extract(p.data, '$.type') = 'tool_use'
            AND json_extract(p.data, '$.name') IS NOT NULL
        GROUP BY tool_name
        ORDER BY count DESC
        LIMIT 20
        """,
        (directory,),
    )

    tools = {row[0]: row[1] for row in cursor.fetchall() if row[0]}
    conn.close()
    return tools


# ============== Claude Code Functions ==============


def get_claude_code_sessions(directory: str, limit: int = 20) -> list[dict]:
    project_dir = get_claude_code_project_path(directory)
    if not project_dir:
        return []

    sessions_index = project_dir / "sessions-index.json"
    if not sessions_index.exists():
        return []

    with open(sessions_index) as f:
        index = json.load(f)

    sessions = []
    for entry in index.get("entries", [])[:limit]:
        first_prompt = entry.get("firstPrompt", "")
        sessions.append(
            {
                "id": entry.get("sessionId", ""),
                "title": first_prompt[:100] + "..."
                if len(first_prompt) > 100
                else first_prompt,
                "additions": 0,
                "deletions": 0,
                "files": 0,
                "messages": entry.get("messageCount", 0),
                "created": entry.get("created", ""),
            }
        )

    return sessions


def get_claude_code_conversation_sample(directory: str, limit: int = 100) -> list[dict]:
    project_dir = get_claude_code_project_path(directory)
    if not project_dir:
        return []

    messages = []
    for jsonl_file in sorted(
        project_dir.glob("*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True
    )[:5]:
        try:
            with open(jsonl_file) as f:
                for line in f:
                    try:
                        msg = json.loads(line)
                        role = msg.get("type", "")
                        text = ""

                        if role == "human":
                            for block in msg.get("message", {}).get("content", []):
                                if (
                                    isinstance(block, dict)
                                    and block.get("type") == "text"
                                ):
                                    text = block.get("text", "")
                                    break
                                elif isinstance(block, str):
                                    text = block
                                    break

                        if text and 10 < len(text) < 2000:
                            if not text.startswith("<beads-") and not text.startswith(
                                "[MEMORY"
                            ):
                                messages.append(
                                    {
                                        "session": jsonl_file.stem[:8],
                                        "role": "user"
                                        if role == "human"
                                        else "assistant",
                                        "text": text[:500] + "..."
                                        if len(text) > 500
                                        else text,
                                        "time": msg.get("timestamp", ""),
                                    }
                                )
                    except json.JSONDecodeError:
                        continue
        except Exception:
            continue

    return messages[:limit]


def get_claude_code_friction_signals(directory: str) -> list[dict]:
    conversation = get_claude_code_conversation_sample(directory, limit=200)

    friction_keywords = [
        "again",
        "still",
        "bruh",
        "why",
        "fail",
        "error",
        "not work",
        "broken",
        "wrong",
        "rip",
        "nani",
        "confused",
        "i thought",
        "already",
        "try again",
    ]

    signals = []
    for msg in conversation:
        if msg["role"] == "user":
            text_lower = msg["text"].lower()
            if any(kw in text_lower for kw in friction_keywords):
                signals.append(
                    {
                        "session": msg["session"],
                        "prompt": msg["text"],
                        "time": msg["time"],
                    }
                )

    return signals[:30]


def get_claude_code_tool_usage(directory: str) -> dict:
    project_dir = get_claude_code_project_path(directory)
    if not project_dir:
        return {}

    tools = {}
    for jsonl_file in project_dir.glob("*.jsonl"):
        try:
            with open(jsonl_file) as f:
                for line in f:
                    try:
                        msg = json.loads(line)
                        if msg.get("type") == "assistant":
                            for block in msg.get("message", {}).get("content", []):
                                if (
                                    isinstance(block, dict)
                                    and block.get("type") == "tool_use"
                                ):
                                    tool_name = block.get("name", "unknown")
                                    tools[tool_name] = tools.get(tool_name, 0) + 1
                    except json.JSONDecodeError:
                        continue
        except Exception:
            continue

    return dict(sorted(tools.items(), key=lambda x: x[1], reverse=True)[:20])


# ============== Main ==============


def extract_all(directory: str) -> dict:
    agent = detect_agent()

    if agent == "opencode":
        sessions = get_opencode_sessions(directory)
        conversation = get_opencode_conversation_sample(directory, limit=80)
        friction_signals = get_opencode_friction_signals(directory)
        tool_usage = get_opencode_tool_usage(directory)
    elif agent == "claude-code":
        sessions = get_claude_code_sessions(directory)
        conversation = get_claude_code_conversation_sample(directory, limit=80)
        friction_signals = get_claude_code_friction_signals(directory)
        tool_usage = get_claude_code_tool_usage(directory)
    else:
        return {
            "status": "no_agent",
            "message": "No supported agent session data found (OpenCode or Claude Code)",
            "directory": directory,
        }

    if not sessions:
        return {
            "status": "no_sessions",
            "message": f"No sessions found for {directory}",
            "agent": agent,
            "directory": directory,
        }

    total_messages = sum(s["messages"] for s in sessions)

    return {
        "status": "success",
        "agent": agent,
        "directory": directory,
        "extracted_at": datetime.now().isoformat(),
        "stats": {
            "sessions": len(sessions),
            "total_messages": total_messages,
            "total_additions": sum(s["additions"] for s in sessions),
            "total_deletions": sum(s["deletions"] for s in sessions),
            "files_modified": sum(s["files"] for s in sessions),
            "avg_messages_per_session": total_messages // len(sessions)
            if sessions
            else 0,
        },
        "sessions": sessions,
        "conversation_sample": conversation,
        "friction_signals": friction_signals,
        "tool_usage": tool_usage,
    }


if __name__ == "__main__":
    directory = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    output_format = sys.argv[2] if len(sys.argv) > 2 else "json"

    data = extract_all(directory)

    if output_format == "json":
        print(json.dumps(data, indent=2))
    else:
        print(f"Agent: {data.get('agent', 'unknown')}")
        print(f"Sessions: {data.get('stats', {}).get('sessions', 0)}")
        print(f"Messages: {data.get('stats', {}).get('total_messages', 0)}")
        print(f"Friction signals: {len(data.get('friction_signals', []))}")
        print(f"Tools used: {len(data.get('tool_usage', {}))}")
