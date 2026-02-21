#!/usr/bin/env python3
"""
Process any URL from Slack inbox, analyze with Claude, and create a GitHub issue.

Supports:
- Tweet URLs (twitter.com, x.com) → Twitter API
- YouTube URLs → Transcript API (full transcript analysis)
- GitHub URLs → Exa AI
- Any other URL → Exa AI

Usage:
    URL=... python scripts/slack-inbox.py
"""

import glob
import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request

try:
    from youtube_transcript_api import YouTubeTranscriptApi

    YOUTUBE_TRANSCRIPT_AVAILABLE = True
except ImportError:
    YOUTUBE_TRANSCRIPT_AVAILABLE = False

TWITTER_API_BASE = "https://api.twitterapi.io"
ANTHROPIC_API_BASE = "https://api.anthropic.com/v1/messages"
EXA_API_BASE = "https://api.exa.ai/contents"

# Type prefixes for issue titles
TYPE_PREFIXES = {
    "tweet": "Tweet",
    "video": "Video",
    "tool": "Tool",
    "mcp": "MCP",
    "plugin": "Plugin",
    "skill": "Skill",
    "pattern": "Pattern",
    "article": "Article",
    "repo": "Repo",
}

ANALYSIS_PROMPT = """Analyze this content for Flux (AI-augmented dev workflow system).

IMPORTANT: First check if this tool/technique/pattern already exists in:
1. Existing recommendations (provided below)
2. The Flux plugin codebase (already built-in)

Return ONLY valid JSON:
{{
  "type": "tweet" | "video" | "tool" | "mcp" | "plugin" | "skill" | "pattern" | "article" | "repo",
  "title": "5-8 word title (without type prefix)",
  "tldr": "1 sentence summary",
  "verdict": "Yes" | "No" | "Maybe" | "Duplicate",
  "stars": 1-5,
  "stars_reason": "brief reason",
  "category": "category/path/",
  "sdlc_phases": ["phase1", "phase2"],
  "what": "2-3 sentences explaining the tool/technique",
  "integration": "1-2 sentences on how to integrate",
  "duplicate_of": null | "path/to/existing.yaml or 'flux-plugin'",
  "duplicate_reason": null | "explanation of overlap"
}}

Type guide:
- tweet: Social media discussion/tip
- video: YouTube video, tutorial, demo
- tool: CLI tool, standalone utility
- mcp: Model Context Protocol server
- plugin: Editor extension (VSCode, Neovim, etc.)
- skill: Reusable prompt/workflow for AI assistants
- pattern: Workflow pattern, best practice, methodology
- article: Blog post, documentation, guide
- repo: GitHub repository, library, framework

If duplicate_of is set, verdict MUST be "Duplicate".

Categories: mcps/, cli-tools/, plugins/, skills/, applications/, workflow-patterns/
SDLC phases: Planning, Implementation, Testing, Code Review, CI/CD, Debugging

---

EXISTING RECOMMENDATIONS:
{existing_recommendations}

---

FLUX PLUGIN BUILT-IN FEATURES:
{flux_plugin_context}

---

{content_section}
"""


def detect_url_type(url):
    """Detect URL type for routing to appropriate fetcher."""
    url_lower = url.lower()
    if "twitter.com" in url_lower or "x.com" in url_lower:
        if "/status/" in url_lower:
            return "tweet"
    if "youtube.com" in url_lower or "youtu.be" in url_lower:
        return "youtube"
    if "github.com" in url_lower:
        return "github"
    return "other"


def load_existing_recommendations(recommendations_path):
    """Load all existing recommendation YAML files as context."""
    recommendations = []
    yaml_files = glob.glob(f"{recommendations_path}/**/*.yaml", recursive=True)
    yaml_files += glob.glob(f"{recommendations_path}/**/*.yml", recursive=True)

    for filepath in yaml_files:
        if "schema" in filepath.lower() or "accounts" in filepath.lower():
            continue
        try:
            with open(filepath, "r") as f:
                content = f.read()
                name_match = re.search(r"name:\s*(.+)", content)
                desc_match = re.search(r"description:\s*(.+)", content)
                rel_path = os.path.relpath(filepath, recommendations_path)
                name = name_match.group(1).strip() if name_match else rel_path
                desc = desc_match.group(1).strip() if desc_match else ""
                recommendations.append(f"- {rel_path}: {name} - {desc[:100]}")
        except Exception:
            continue

    return "\n".join(recommendations) if recommendations else "(none yet)"


def load_flux_plugin_context(flux_path):
    """Load key files from flux plugin to understand built-in features."""
    context_parts = []

    # Key command files
    key_files = [
        "README.md",
        "commands/flux/improve.md",
        "commands/flux/plan.md",
        "commands/flux/work.md",
        "hooks/hooks.json",
    ]

    for filename in key_files:
        filepath = os.path.join(flux_path, filename)
        if os.path.exists(filepath):
            try:
                with open(filepath, "r") as f:
                    content = f.read()
                    if len(content) > 2000:
                        content = content[:2000] + "\n... (truncated)"
                    context_parts.append(f"### {filename}\n{content}")
            except Exception:
                continue

    # Scan agents folder for capabilities
    agents_path = os.path.join(flux_path, "agents")
    if os.path.isdir(agents_path):
        agent_summaries = ["### Built-in Agents (sub-agents that run automatically)"]
        for agent_file in sorted(glob.glob(f"{agents_path}/*.md")):
            try:
                with open(agent_file, "r") as f:
                    content = f.read()
                    name_match = re.search(r"name:\s*(.+)", content)
                    desc_match = re.search(r"description:\s*(.+)", content)
                    name = (
                        name_match.group(1).strip()
                        if name_match
                        else os.path.basename(agent_file)
                    )
                    desc = desc_match.group(1).strip() if desc_match else ""
                    agent_summaries.append(f"- **{name}**: {desc}")
            except Exception:
                continue
        if len(agent_summaries) > 1:
            context_parts.append("\n".join(agent_summaries))

    # Scan commands folder for all available commands
    commands_path = os.path.join(flux_path, "commands/flux")
    if os.path.isdir(commands_path):
        cmd_summaries = ["### Available Commands"]
        for cmd_file in sorted(glob.glob(f"{commands_path}/*.md")):
            try:
                with open(cmd_file, "r") as f:
                    content = f.read()
                    name_match = re.search(r"name:\s*(.+)", content)
                    desc_match = re.search(r"description:\s*(.+)", content)
                    name = (
                        name_match.group(1).strip()
                        if name_match
                        else os.path.basename(cmd_file)
                    )
                    desc = desc_match.group(1).strip() if desc_match else ""
                    cmd_summaries.append(f"- **{name}**: {desc}")
            except Exception:
                continue
        if len(cmd_summaries) > 1:
            context_parts.append("\n".join(cmd_summaries))

    return (
        "\n\n".join(context_parts) if context_parts else "(flux plugin not available)"
    )


# --- Twitter fetching ---


def extract_tweet_id(url):
    for pattern in [r"twitter\.com/\w+/status/(\d+)", r"x\.com/\w+/status/(\d+)"]:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def fetch_tweet(tweet_id, api_key):
    url = f"{TWITTER_API_BASE}/twitter/tweets?tweet_ids={tweet_id}"
    req = urllib.request.Request(url)
    req.add_header("X-API-Key", api_key)
    req.add_header("User-Agent", "FluxInbox/1.0")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
            tweets = data.get("tweets", [])
            return tweets[0] if tweets else None
    except Exception as e:
        print(f"Error fetching tweet: {e}")
        return None


def fetch_tweet_content(url, api_key):
    """Fetch tweet and return structured content."""
    tweet_id = extract_tweet_id(url)
    if not tweet_id:
        return None

    tweet = fetch_tweet(tweet_id, api_key)
    if not tweet:
        return None

    text = tweet.get("text", "")
    author = tweet.get("author", {}).get("userName", "unknown")
    author_name = tweet.get("author", {}).get("name", "Unknown")
    likes = tweet.get("likeCount", 0)
    retweets = tweet.get("retweetCount", 0)

    # Check for parent tweet (reply)
    parent_id = tweet.get("inReplyToId") or tweet.get("in_reply_to_status_id")
    parent_context = ""
    parent_text = ""
    parent_author = ""
    if parent_id:
        parent = fetch_tweet(parent_id, api_key)
        if parent:
            parent_text = parent.get("text", "")
            parent_author = parent.get("author", {}).get("userName", "unknown")
            parent_context = f"[Replying to @{parent_author}]:\n{parent_text}\n\n"
            print(f"Fetched parent tweet from @{parent_author}")

    # Build display format
    if parent_context:
        display = f"**@{parent_author}:**\n> {parent_text}\n\n**↳ @{author} replied:**\n> {text}"
    else:
        display = f"> {text}"

    return {
        "type": "tweet",
        "text": f"{parent_context}[Tweet by @{author}]:\n{text}",
        "author": author,
        "author_name": author_name,
        "likes": likes,
        "retweets": retweets,
        "display": display,
        "meta": f"@{author} · {likes} ❤️",
    }


# --- Exa fetching ---


def fetch_with_exa(url, api_key):
    """Fetch URL content using Exa AI."""
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
    }

    data = json.dumps(
        {
            "urls": [url],
            "text": True,
            "summary": True,
        }
    ).encode()

    req = urllib.request.Request(
        EXA_API_BASE, data=data, headers=headers, method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode())
            results = result.get("results", [])
            if results:
                r = results[0]
                return {
                    "type": "exa",
                    "title": r.get("title", ""),
                    "text": r.get("text", "")[:5000],  # Limit content size
                    "summary": r.get("summary", ""),
                    "author": r.get("author", ""),
                    "url": url,
                }
            return None
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        print(f"Exa API error: {e.code} - {error_body}")
        return None
    except Exception as e:
        print(f"Error calling Exa: {e}")
        return None


def extract_youtube_video_id(url):
    """Extract video ID from various YouTube URL formats."""
    patterns = [
        r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([a-zA-Z0-9_-]{11})",
        r"youtube\.com/shorts/([a-zA-Z0-9_-]{11})",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def fetch_youtube_content(url, exa_api_key=None):
    """Fetch YouTube video content - tries transcript, falls back to Exa."""
    video_id = extract_youtube_video_id(url)
    if not video_id:
        print(f"Could not extract video ID from {url}")
        return None

    # Get video metadata via oembed (no API key needed)
    title = "YouTube Video"
    author = ""
    try:
        oembed_url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
        req = urllib.request.Request(oembed_url)
        req.add_header("User-Agent", "FluxInbox/1.0")
        with urllib.request.urlopen(req, timeout=10) as resp:
            metadata = json.loads(resp.read().decode())
            title = metadata.get("title", "Unknown Video")
            author = metadata.get("author_name", "")
    except Exception as e:
        print(f"Could not fetch video metadata: {e}")

    # Try multiple transcript sources
    transcript_text = ""

    # Method 1: Supadata API (if key available)
    supadata_key = os.environ.get("SUPADATA_API_KEY")
    if not transcript_text and supadata_key:
        try:
            supadata_url = (
                f"https://api.supadata.ai/v1/youtube/transcript?videoId={video_id}"
            )
            req = urllib.request.Request(supadata_url)
            req.add_header("x-api-key", supadata_key)
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode())
                if result.get("content"):
                    transcript_text = result["content"]
                    print(
                        f"Fetched transcript via Supadata: {len(transcript_text)} chars"
                    )
        except Exception as e:
            print(f"Supadata API failed: {e}")

    # Fallback to local library if hosted API fails
    if not transcript_text and YOUTUBE_TRANSCRIPT_AVAILABLE:
        try:
            ytt_api = YouTubeTranscriptApi()
            transcript_list = ytt_api.fetch(video_id)
            transcript_text = " ".join([entry["text"] for entry in transcript_list])
            print(f"Fetched transcript via local lib: {len(transcript_text)} chars")
        except Exception as e:
            print(f"Local transcript lib failed: {e}")

    # If no transcript, use Exa to get video description/summary
    exa_content = ""
    if not transcript_text and exa_api_key:
        print("Using Exa for video content...")
        exa_result = fetch_with_exa(url, exa_api_key)
        if exa_result:
            exa_content = exa_result.get("text", "") or exa_result.get("summary", "")
            print(f"Got Exa content: {len(exa_content)} chars")

    # Build final content
    if transcript_text:
        # Truncate transcript if too long
        if len(transcript_text) > 8000:
            transcript_text = transcript_text[:8000] + "\n... (truncated)"
        content_text = (
            f"Title: {title}\nChannel: {author}\n\nTranscript:\n{transcript_text}"
        )
        preview = transcript_text[:300].replace("\n", " ") + "..."
    elif exa_content:
        content_text = f"Title: {title}\nChannel: {author}\n\nVideo Description/Summary:\n{exa_content[:4000]}"
        preview = exa_content[:300].replace("\n", " ") + "..."
    else:
        content_text = f"Title: {title}\nChannel: {author}\n\n(No transcript or description available)"
        preview = "(No content available)"

    display = f"**{title}**\n\nBy: {author}\n\n> {preview}"

    return {
        "type": "youtube",
        "text": content_text,
        "title": title,
        "author": author,
        "has_transcript": bool(transcript_text),
        "display": display,
        "meta": f"📺 {author}",
    }


def fetch_exa_content(url, api_key, url_type):
    """Fetch content via Exa and return structured content."""
    exa_result = fetch_with_exa(url, api_key)
    if not exa_result:
        return None

    title = exa_result.get("title", "Unknown")
    summary = exa_result.get("summary", "")
    text = exa_result.get("text", "")
    author = exa_result.get("author", "")

    # Build content section for Claude
    content_text = f"Title: {title}\n"
    if author:
        content_text += f"Author: {author}\n"
    if summary:
        content_text += f"Summary: {summary}\n"
    content_text += f"\nContent:\n{text[:4000]}"

    # Display format varies by type
    if url_type == "github":
        meta = f"🔗 {title}"
        display = f"**{title}**\n\n{summary or text[:500]}"
    else:
        meta = f"🔗 {title}"
        display = f"**{title}**\n\n{summary or text[:500]}"

    return {
        "type": url_type,
        "text": content_text,
        "title": title,
        "summary": summary,
        "author": author,
        "display": display,
        "meta": meta,
    }


# --- Claude analysis ---


def analyze_with_claude(prompt, api_key):
    """Call Claude API to analyze content."""
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }

    data = json.dumps(
        {
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 1500,
            "messages": [{"role": "user", "content": prompt}],
        }
    ).encode()

    req = urllib.request.Request(ANTHROPIC_API_BASE, data=data, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode())
            return result.get("content", [{}])[0].get("text", "Analysis failed")
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        print(f"Claude API error: {e.code} - {error_body}")
        return f"Analysis failed: {e.code}"
    except Exception as e:
        print(f"Error calling Claude: {e}")
        return f"Analysis failed: {e}"


def parse_analysis(analysis_raw, fallback_text):
    """Parse Claude's JSON response."""
    try:
        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", analysis_raw)
        if json_match:
            analysis_raw = json_match.group(1)
        return json.loads(analysis_raw)
    except json.JSONDecodeError:
        print(f"Failed to parse Claude response as JSON: {analysis_raw[:200]}")
        return {
            "type": "article",
            "title": fallback_text[:40] + "...",
            "tldr": "Analysis failed - see raw response",
            "verdict": "Maybe",
            "stars": 3,
            "stars_reason": "Could not analyze",
            "category": "unknown/",
            "sdlc_phases": [],
            "what": analysis_raw[:500],
            "integration": "",
            "duplicate_of": None,
            "duplicate_reason": None,
        }


def create_issue_body(url, content, analysis):
    """Create the GitHub issue body."""
    # Build stars display
    stars = analysis.get("stars", 3)
    stars_display = "⭐" * stars + "☆" * (5 - stars)

    # Verdict emoji
    verdict = analysis.get("verdict", "Maybe")
    verdict_emoji = {"Yes": "✅", "No": "❌", "Maybe": "🤔", "Duplicate": "🔄"}.get(
        verdict, "🤔"
    )

    # SDLC phases
    phases = analysis.get("sdlc_phases", [])
    phases_display = " · ".join(phases) if phases else "—"

    # Duplicate section
    duplicate_of = analysis.get("duplicate_of")
    duplicate_reason = analysis.get("duplicate_reason")
    if duplicate_of:
        duplicate_section = f"""
> **🔄 Already exists:** `{duplicate_of}`
> 
> {duplicate_reason or "This appears to already be covered."}

"""
    else:
        duplicate_section = ""

    # Content display
    content_display = content.get("display", "")
    meta = content.get("meta", "")

    return f"""[→ View Source]({url}) · {meta}

{content_display}

---

## {verdict_emoji} Verdict: {verdict}

{analysis.get("tldr", "")}
{duplicate_section}
| | |
|:--|:--|
| **Relevance** | {stars_display} — {analysis.get("stars_reason", "")} |
| **Category** | `{analysis.get("category", "unknown/")}` |
| **SDLC** | {phases_display} |

---

<details>
<summary><strong>📋 Details</strong></summary>

### What is this?
{analysis.get("what", "")}

### Integration
{analysis.get("integration", "")}

</details>

---
<sub>via Slack inbox</sub>
"""


def main():
    # Get inputs
    url = os.environ.get("URL") or os.environ.get("TWEET_URL")  # Backward compat
    twitter_api_key = os.environ.get("TWITTER_API_KEY")
    anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY")
    exa_api_key = os.environ.get("EXA_API_KEY")
    recommendations_path = os.environ.get("RECOMMENDATIONS_PATH", ".")
    flux_plugin_path = os.environ.get("FLUX_PLUGIN_PATH", "")

    if not url:
        print("Error: URL not set")
        exit(1)
    if not anthropic_api_key:
        print("Error: ANTHROPIC_API_KEY not set")
        exit(1)

    # Detect URL type
    url_type = detect_url_type(url)
    print(f"Detected URL type: {url_type}")

    # Load existing context for deduplication
    print("Loading existing recommendations...")
    existing_recs = load_existing_recommendations(recommendations_path)
    rec_count = existing_recs.count("\n") + 1 if existing_recs != "(none yet)" else 0
    print(f"Found {rec_count} recommendations")

    print("Loading flux plugin context...")
    flux_context = (
        load_flux_plugin_context(flux_plugin_path)
        if flux_plugin_path
        else "(not available)"
    )

    # Fetch content based on URL type
    content = None
    if url_type == "tweet":
        if not twitter_api_key:
            print("Error: TWITTER_API_KEY required for tweets")
            exit(1)
        print("Fetching tweet...")
        content = fetch_tweet_content(url, twitter_api_key)
    elif url_type == "youtube":
        print("Fetching YouTube content...")
        content = fetch_youtube_content(url, exa_api_key)
    else:
        if not exa_api_key:
            print("Error: EXA_API_KEY required for non-tweet URLs")
            exit(1)
        print(f"Fetching content via Exa...")
        content = fetch_exa_content(url, exa_api_key, url_type)

    if not content:
        print("Could not fetch content from URL")
        exit(1)

    # Build content section for prompt
    if url_type == "tweet":
        content_section = f"""Tweet by @{content.get("author", "unknown")} ({content.get("author_name", "")}) · {content.get("likes", 0)} likes, {content.get("retweets", 0)} RTs:
{content.get("text", "")}"""
    else:
        content_section = f"""URL: {url}
Type: {url_type}

{content.get("text", "")}"""

    # Analyze with Claude
    prompt = ANALYSIS_PROMPT.format(
        existing_recommendations=existing_recs,
        flux_plugin_context=flux_context,
        content_section=content_section,
    )

    print("Analyzing with Claude...")
    analysis_raw = analyze_with_claude(prompt, anthropic_api_key)
    analysis = parse_analysis(analysis_raw, content.get("text", "")[:40])

    # Build title with type prefix
    content_type = analysis.get("type", "article")
    prefix = TYPE_PREFIXES.get(content_type, "Link")
    title = f"{prefix}: {analysis.get('title', 'Unknown')}"

    # Create issue body
    body = create_issue_body(url, content, analysis)

    # Write body to file
    with open("/tmp/issue.md", "w") as f:
        f.write(body)

    # Create issue
    labels = ["inbox", content_type]
    duplicate_of = analysis.get("duplicate_of")
    if duplicate_of:
        labels.append("duplicate")

    cmd = ["gh", "issue", "create", "--title", title, "--body-file", "/tmp/issue.md"]
    for label in labels:
        cmd.extend(["--label", label])

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"Error creating issue: {result.stderr}")
        exit(1)

    print(f"Created issue: {result.stdout.strip()}")


if __name__ == "__main__":
    main()
