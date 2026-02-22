#!/usr/bin/env python3
"""
Session Data Extractor for Flux Improve

Extracts raw session data from OpenCode database for LLM analysis.
The intelligent analysis (frustration detection, pattern recognition)
is done by the agent running /flux:improve, not this script.
"""

import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

OPENCODE_DB = Path.home() / ".local/share/opencode/opencode.db"


def get_sessions(directory: str, limit: int = 20) -> list[dict]:
    """Get recent sessions for a project directory."""
    if not OPENCODE_DB.exists():
        return []

    conn = sqlite3.connect(OPENCODE_DB)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT 
            s.id,
            s.title,
            s.summary_additions,
            s.summary_deletions,
            s.summary_files,
            s.time_created,
            s.time_updated,
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


def get_conversation_sample(directory: str, limit: int = 100) -> list[dict]:
    """
    Extract recent user prompts with context for LLM analysis.
    Returns chronological conversation snippets.
    """
    if not OPENCODE_DB.exists():
        return []

    conn = sqlite3.connect(OPENCODE_DB)
    cursor = conn.cursor()

    # Get user messages with their session context
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
        # Skip system injections and very long context dumps
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
    # Return in chronological order (oldest first)
    return list(reversed(messages))


def get_error_retry_patterns(directory: str) -> list[dict]:
    """
    Find potential error/retry cycles by looking for:
    - Multiple user messages in quick succession
    - Messages containing error indicators
    """
    if not OPENCODE_DB.exists():
        return []

    conn = sqlite3.connect(OPENCODE_DB)
    cursor = conn.cursor()

    # Find user messages that might indicate frustration/retry
    cursor.execute(
        """
        SELECT 
            s.title as session_title,
            json_extract(p.data, '$.text') as text,
            datetime(m.time_created/1000, 'unixepoch', 'localtime') as timestamp,
            m.time_created as ts_raw
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
                OR lower(json_extract(p.data, '$.text')) LIKE '%doesn%t work%'
                OR lower(json_extract(p.data, '$.text')) LIKE '%broken%'
                OR lower(json_extract(p.data, '$.text')) LIKE '%wrong%'
                OR lower(json_extract(p.data, '$.text')) LIKE '%rip%'
                OR lower(json_extract(p.data, '$.text')) LIKE '%nani%'
                OR lower(json_extract(p.data, '$.text')) LIKE '%what?%'
                OR lower(json_extract(p.data, '$.text')) LIKE '%huh%'
                OR lower(json_extract(p.data, '$.text')) LIKE '%confused%'
                OR lower(json_extract(p.data, '$.text')) LIKE '%i thought%'
                OR lower(json_extract(p.data, '$.text')) LIKE '%already%'
                OR lower(json_extract(p.data, '$.text')) LIKE '%didn%t you%'
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


def get_tool_usage(directory: str) -> dict:
    """Get tool usage statistics from assistant messages."""
    if not OPENCODE_DB.exists():
        return {}

    conn = sqlite3.connect(OPENCODE_DB)
    cursor = conn.cursor()

    # Count tool uses
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

    tools = {}
    for row in cursor.fetchall():
        if row[0]:
            tools[row[0]] = row[1]

    conn.close()
    return tools


def extract_all(directory: str) -> dict:
    """Extract all session data for LLM analysis."""
    sessions = get_sessions(directory)
    conversation = get_conversation_sample(directory, limit=80)
    friction_signals = get_error_retry_patterns(directory)
    tool_usage = get_tool_usage(directory)

    # Basic stats
    total_messages = sum(s["messages"] for s in sessions)
    total_additions = sum(s["additions"] for s in sessions)
    total_deletions = sum(s["deletions"] for s in sessions)
    total_files = sum(s["files"] for s in sessions)

    return {
        "directory": directory,
        "extracted_at": datetime.now().isoformat(),
        "stats": {
            "sessions": len(sessions),
            "total_messages": total_messages,
            "total_additions": total_additions,
            "total_deletions": total_deletions,
            "files_modified": total_files,
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
        # Summary format for quick view
        print(f"Sessions: {data['stats']['sessions']}")
        print(f"Messages: {data['stats']['total_messages']}")
        print(f"Friction signals: {len(data['friction_signals'])}")
        print(f"Tools used: {len(data['tool_usage'])}")
