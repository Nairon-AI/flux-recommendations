#!/usr/bin/env python3
"""
Session Analysis for Flux Improve

Analyzes OpenCode sessions for the current project directory to identify
workflow patterns, gaps, and improvement opportunities.
"""

import json
import os
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

# OpenCode database location
OPENCODE_DB = Path.home() / ".local/share/opencode/opencode.db"
RECOMMENDATIONS_DIR = Path.home() / ".flux/recommendations"


def get_project_sessions(directory: str, limit: int = 50) -> list[dict]:
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

    sessions = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return sessions


def get_session_messages(session_id: str, limit: int = 100) -> list[dict]:
    """Get messages from a session."""
    if not OPENCODE_DB.exists():
        return []

    conn = sqlite3.connect(OPENCODE_DB)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT data FROM message 
        WHERE session_id = ? 
        ORDER BY time_created DESC 
        LIMIT ?
        """,
        (session_id, limit),
    )

    messages = []
    for (data,) in cursor.fetchall():
        try:
            messages.append(json.loads(data))
        except json.JSONDecodeError:
            continue

    conn.close()
    return messages


def analyze_tool_usage(sessions: list[dict]) -> dict:
    """Analyze which tools are being used across sessions."""
    tool_counts = Counter()
    agent_counts = Counter()
    model_counts = Counter()

    for session in sessions[:10]:  # Sample recent sessions
        messages = get_session_messages(session["id"], limit=50)
        for msg in messages:
            if "agent" in msg:
                agent_counts[msg["agent"]] += 1
            if "modelID" in msg:
                model_counts[msg["modelID"]] += 1
            # Check for tool usage in content
            if "content" in msg and isinstance(msg["content"], list):
                for block in msg["content"]:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        tool_counts[block.get("name", "unknown")] += 1

    return {
        "tools": dict(tool_counts.most_common(20)),
        "agents": dict(agent_counts.most_common(10)),
        "models": dict(model_counts.most_common(5)),
    }


def analyze_session_patterns(sessions: list[dict]) -> dict:
    """Analyze session patterns to identify workflow characteristics."""
    if not sessions:
        return {"error": "No sessions found"}

    # Session topics (from titles)
    topics = Counter()
    for s in sessions:
        title = s.get("title", "").lower()
        # Extract key themes
        if "bug" in title or "fix" in title:
            topics["debugging"] += 1
        if "test" in title:
            topics["testing"] += 1
        if "refactor" in title:
            topics["refactoring"] += 1
        if "feature" in title or "add" in title or "implement" in title:
            topics["feature_development"] += 1
        if "explore" in title or "research" in title:
            topics["exploration"] += 1
        if "review" in title or "pr" in title:
            topics["code_review"] += 1
        if "doc" in title:
            topics["documentation"] += 1
        if "setup" in title or "config" in title or "install" in title:
            topics["setup"] += 1
        if "subagent" in title:
            topics["delegation"] += 1

    # Code changes
    total_additions = sum(s.get("summary_additions", 0) for s in sessions)
    total_deletions = sum(s.get("summary_deletions", 0) for s in sessions)
    total_files = sum(s.get("summary_files", 0) for s in sessions)
    total_messages = sum(s.get("message_count", 0) for s in sessions)

    # Session length patterns
    long_sessions = sum(1 for s in sessions if s.get("message_count", 0) > 100)
    short_sessions = sum(1 for s in sessions if s.get("message_count", 0) < 10)

    return {
        "total_sessions": len(sessions),
        "topics": dict(topics.most_common(10)),
        "code_changes": {
            "additions": total_additions,
            "deletions": total_deletions,
            "files_modified": total_files,
        },
        "conversation_stats": {
            "total_messages": total_messages,
            "avg_messages_per_session": total_messages // len(sessions)
            if sessions
            else 0,
            "long_sessions": long_sessions,
            "short_sessions": short_sessions,
        },
    }


def identify_workflow_gaps(patterns: dict, tool_usage: dict) -> list[dict]:
    """Identify workflow gaps based on session analysis."""
    gaps = []
    topics = patterns.get("topics", {})
    tools = tool_usage.get("tools", {})

    # Gap: Heavy debugging but no test-first approach
    if topics.get("debugging", 0) > 3 and topics.get("testing", 0) < 2:
        gaps.append(
            {
                "gap": "Debugging without tests",
                "evidence": f"{topics.get('debugging', 0)} debug sessions vs {topics.get('testing', 0)} testing sessions",
                "recommendation": "test-first-debugging",
                "impact": "high",
            }
        )

    # Gap: Long sessions suggest context loss
    if patterns.get("conversation_stats", {}).get("long_sessions", 0) > 2:
        gaps.append(
            {
                "gap": "Long sessions causing context loss",
                "evidence": f"{patterns['conversation_stats']['long_sessions']} sessions with 100+ messages",
                "recommendation": "context-management",
                "impact": "high",
            }
        )

    # Gap: Not using delegation
    if topics.get("delegation", 0) < 2 and patterns.get("total_sessions", 0) > 10:
        gaps.append(
            {
                "gap": "Underusing agent delegation",
                "evidence": f"Only {topics.get('delegation', 0)} delegated tasks across {patterns['total_sessions']} sessions",
                "recommendation": "beads",
                "impact": "medium",
            }
        )

    # Gap: Low code output relative to messages
    code_stats = patterns.get("code_changes", {})
    conv_stats = patterns.get("conversation_stats", {})
    if (
        conv_stats.get("total_messages", 0) > 500
        and code_stats.get("files_modified", 0) < 10
    ):
        gaps.append(
            {
                "gap": "High conversation, low code output",
                "evidence": f"{conv_stats['total_messages']} messages but only {code_stats['files_modified']} files modified",
                "recommendation": "atomic-commits",
                "impact": "medium",
            }
        )

    # Gap: Not using MCP tools efficiently
    mcp_tools = ["context7", "exa", "linear", "supermemory"]
    used_mcps = [t for t in tools.keys() if any(m in t.lower() for m in mcp_tools)]
    if len(used_mcps) < 2:
        gaps.append(
            {
                "gap": "Underutilizing MCP integrations",
                "evidence": f"Only using {len(used_mcps)} MCP tools",
                "recommendation": "context7",
                "impact": "medium",
            }
        )

    return gaps


def load_recommendation(name: str) -> dict | None:
    """Load a recommendation by name."""
    for yaml_file in RECOMMENDATIONS_DIR.rglob("*.yaml"):
        if yaml_file.name == "schema.yaml":
            continue
        try:
            import yaml

            with open(yaml_file) as f:
                rec = yaml.safe_load(f)
                if rec and rec.get("name") == name:
                    return rec
        except Exception:
            continue
    return None


def generate_report(directory: str) -> dict:
    """Generate a full session analysis report."""
    sessions = get_project_sessions(directory)

    if not sessions:
        return {
            "status": "no_data",
            "message": f"No sessions found for {directory}",
            "sessions_analyzed": 0,
        }

    patterns = analyze_session_patterns(sessions)
    tool_usage = analyze_tool_usage(sessions)
    gaps = identify_workflow_gaps(patterns, tool_usage)

    # Enrich gaps with recommendation details
    for gap in gaps:
        rec = load_recommendation(gap["recommendation"])
        if rec:
            gap["recommendation_details"] = {
                "name": rec.get("name"),
                "tagline": rec.get("tagline"),
                "install_command": rec.get("install", {}).get("command"),
            }

    return {
        "status": "success",
        "directory": directory,
        "sessions_analyzed": len(sessions),
        "patterns": patterns,
        "tool_usage": tool_usage,
        "workflow_gaps": gaps,
        "generated_at": datetime.now().isoformat(),
    }


def format_report(report: dict) -> str:
    """Format the report as markdown."""
    if report.get("status") == "no_data":
        return f"No session data found for this project.\n\n{report.get('message', '')}"

    lines = []
    lines.append("## Session Analysis\n")
    lines.append(f"**Sessions analyzed:** {report['sessions_analyzed']}")
    lines.append(f"**Directory:** `{report['directory']}`\n")

    # Patterns
    patterns = report.get("patterns", {})
    if patterns.get("topics"):
        lines.append("### Session Topics")
        for topic, count in patterns["topics"].items():
            lines.append(f"- {topic.replace('_', ' ').title()}: {count} sessions")
        lines.append("")

    # Code stats
    code = patterns.get("code_changes", {})
    conv = patterns.get("conversation_stats", {})
    lines.append("### Activity Stats")
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Total messages | {conv.get('total_messages', 0)} |")
    lines.append(f"| Avg per session | {conv.get('avg_messages_per_session', 0)} |")
    lines.append(f"| Lines added | {code.get('additions', 0)} |")
    lines.append(f"| Lines deleted | {code.get('deletions', 0)} |")
    lines.append(f"| Files modified | {code.get('files_modified', 0)} |")
    lines.append("")

    # Workflow gaps
    gaps = report.get("workflow_gaps", [])
    if gaps:
        lines.append("### Workflow Gaps Detected\n")
        for gap in gaps:
            impact_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(
                gap["impact"], "⚪"
            )
            lines.append(f"#### {impact_emoji} {gap['gap']}")
            lines.append(f"**Evidence:** {gap['evidence']}\n")

            rec = gap.get("recommendation_details", {})
            if rec:
                lines.append(
                    f"**Recommendation:** `{rec.get('name')}` - {rec.get('tagline', '')}"
                )
                if rec.get("install_command"):
                    lines.append(f"```bash\n{rec['install_command'].strip()}\n```")
            lines.append("")
    else:
        lines.append("### ✅ No workflow gaps detected\n")
        lines.append("Your sessions look well-structured!")

    return "\n".join(lines)


if __name__ == "__main__":
    directory = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    output_format = sys.argv[2] if len(sys.argv) > 2 else "markdown"

    report = generate_report(directory)

    if output_format == "json":
        print(json.dumps(report, indent=2))
    else:
        print(format_report(report))
