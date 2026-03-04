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
from datetime import datetime

import yaml

try:
    from youtube_transcript_api import YouTubeTranscriptApi

    YOUTUBE_TRANSCRIPT_AVAILABLE = True
except ImportError:
    YOUTUBE_TRANSCRIPT_AVAILABLE = False


def update_slack_reaction(
    channel: str, timestamp: str, add_emoji: str, remove_emoji: str = "eyes"
):
    """Update Slack reactions: remove old emoji, add new emoji."""
    slack_token = os.environ.get("SLACK_BOT_TOKEN")
    if not slack_token or not channel or not timestamp:
        print("Skipping Slack reaction update (missing token/channel/ts)")
        return

    headers = {
        "Authorization": f"Bearer {slack_token}",
        "Content-Type": "application/json",
    }

    # Remove old reaction (eyes)
    try:
        data = json.dumps(
            {"channel": channel, "timestamp": timestamp, "name": remove_emoji}
        ).encode()
        req = urllib.request.Request(
            "https://slack.com/api/reactions.remove", data=data, headers=headers
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"Failed to remove reaction: {e}")

    # Add new reaction
    try:
        data = json.dumps(
            {"channel": channel, "timestamp": timestamp, "name": add_emoji}
        ).encode()
        req = urllib.request.Request(
            "https://slack.com/api/reactions.add", data=data, headers=headers
        )
        urllib.request.urlopen(req, timeout=10)
        print(f"Updated Slack reaction: -{remove_emoji} +{add_emoji}")
    except Exception as e:
        print(f"Failed to add reaction: {e}")


TWITTER_API_BASE = "https://api.twitterapi.io"
ANTHROPIC_API_BASE = "https://api.anthropic.com/v1/messages"
EXA_API_BASE = "https://api.exa.ai/contents"

# Type prefixes for issue titles
TYPE_PREFIXES = {
    "tweet": "Tweet",
    "video": "Video",
    "podcast": "Podcast",
    "tool": "Tool",
    "mcp": "MCP",
    "plugin": "Plugin",
    "skill": "Skill",
    "pattern": "Pattern",
    "article": "Article",
    "repo": "Repo",
}

ANALYSIS_PROMPT = """Analyze this content for Flux (AI-augmented dev workflow system).

Flux philosophy: "Agentic SDLC" - AI agents assist at every phase of software development.
We want to find tools, patterns, and insights that make AI-augmented workflows more effective.

IMPORTANT: First check if this tool/technique/pattern already exists in:
1. Existing recommendations (provided below)
2. The Flux plugin codebase (already built-in)

Return ONLY valid JSON:
{{
  "type": "tweet" | "video" | "podcast" | "tool" | "mcp" | "plugin" | "skill" | "pattern" | "article" | "repo",
  "title": "5-8 word title (without type prefix)",
  "tldr": "1 sentence summary",
  "verdict": "Yes" | "No" | "Maybe" | "Duplicate",
  "stars": 1-5,
  "stars_reason": "brief reason",
  "category": "category/path/",
  "sdlc_phases": ["phase1", "phase2"],
  "what": "2-3 sentences explaining the tool/technique",
  "integration": "Specific steps to integrate with Flux/Claude Code workflows",
  "action_items": ["Concrete action 1", "Concrete action 2", "..."],
  "flux_impact": "How this improves our Agentic SDLC approach (or null if not relevant)",
  "key_takeaways": ["Takeaway 1", "Takeaway 2", "..."] | null,
  "duplicate_of": null | "path/to/existing.yaml or 'flux-plugin'",
  "duplicate_reason": null | "explanation of overlap"
}}

Type guide:
- tweet: Social media discussion/tip
- video: YouTube video, tutorial, demo (short-form, focused content)
- podcast: Long-form discussion, interview, conversation (use key_takeaways!)
- tool: CLI tool, standalone utility
- mcp: Model Context Protocol server
- plugin: Editor extension (VSCode, Neovim, etc.)
- skill: Reusable prompt/workflow for AI assistants
- pattern: Workflow pattern, best practice, methodology
- article: Blog post, documentation, guide
- repo: GitHub repository, library, framework

For videos: Extract mentioned tools, techniques, and workflow tips.
For podcasts: MUST include key_takeaways summarizing the main memorable points.
Focus on actionable items we can implement in Flux.

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
        if "/article/" in url_lower:
            return "twitter_article"
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


def extract_article_id(url):
    """Extract article ID from Twitter/X article URLs."""
    for pattern in [r"twitter\.com/\w+/article/(\d+)", r"x\.com/\w+/article/(\d+)"]:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def fetch_article(article_id, api_key):
    """Fetch article from Twitter API using the /twitter/article endpoint."""
    url = f"{TWITTER_API_BASE}/twitter/article?tweet_id={article_id}"
    req = urllib.request.Request(url)
    req.add_header("X-API-Key", api_key)
    req.add_header("User-Agent", "FluxInbox/1.0")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
            if data.get("status") == "success":
                return data.get("article")
            else:
                print(f"Article API error: {data.get('message', 'unknown')}")
                return None
    except Exception as e:
        print(f"Error fetching article: {e}")
        return None


def fetch_article_content(url, api_key):
    """Fetch Twitter article content using the dedicated article endpoint."""
    article_id = extract_article_id(url)
    if not article_id:
        return None

    # Extract author from URL as fallback
    author_match = re.search(r"(?:twitter|x)\.com/(\w+)/article/", url)
    fallback_author = author_match.group(1) if author_match else "unknown"

    # Fetch via dedicated article endpoint
    article = fetch_article(article_id, api_key)
    if article:
        title = article.get("title", "")
        preview = article.get("preview_text", "")
        author_info = article.get("author", {})
        author = author_info.get("userName", fallback_author)
        author_name = author_info.get("name", author)
        likes = article.get("likeCount", 0)
        views = article.get("viewCount", 0)

        # Extract full content from contents array
        contents = article.get("contents", [])
        full_text = "\n\n".join([c.get("text", "") for c in contents if c.get("text")])

        # Build display text
        display_text = full_text if full_text else preview
        if len(display_text) > 1000:
            display_preview = display_text[:1000] + "..."
        else:
            display_preview = display_text

        return {
            "type": "twitter_article",
            "text": f"[Twitter Article by @{author}]\n\nTitle: {title}\n\n{full_text or preview}",
            "author": author,
            "author_name": author_name,
            "title": title,
            "likes": likes,
            "views": views,
            "retweets": 0,
            "display": f"**{title}**\n\nBy @{author}\n\n> {display_preview}",
            "meta": f"@{author} · {likes} ❤️ · {views} views",
            "has_embedded_content": False,
        }

    # If API fails, return minimal info so Claude can still try to analyze
    return {
        "type": "twitter_article",
        "text": f"[Twitter Article by @{fallback_author}]\n\nArticle ID: {article_id}\nURL: {url}\n\n(Could not fetch article content)",
        "author": fallback_author,
        "author_name": fallback_author,
        "title": "",
        "likes": 0,
        "views": 0,
        "retweets": 0,
        "display": f"**Twitter Article by @{fallback_author}**\n\n[Could not fetch content]",
        "meta": f"@{fallback_author}",
        "has_embedded_content": False,
    }


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


def extract_urls_from_text(text):
    """Extract URLs from text, including t.co shortened links."""
    url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
    urls = re.findall(url_pattern, text)
    # Filter out twitter/x.com URLs (we don't want to recursively fetch tweets)
    return [u for u in urls if "twitter.com" not in u and "x.com" not in u]


def fetch_tweet_content(url, api_key, exa_api_key=None):
    """Fetch tweet and return structured content, expanding embedded URLs."""
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

    # Extract and expand embedded URLs (articles, tools, etc.)
    embedded_content = ""
    embedded_urls = extract_urls_from_text(text)
    if parent_text:
        embedded_urls.extend(extract_urls_from_text(parent_text))

    if embedded_urls and exa_api_key:
        print(
            f"Found {len(embedded_urls)} embedded URL(s) in tweet, fetching content..."
        )
        for embedded_url in embedded_urls[:2]:  # Limit to first 2 URLs
            try:
                exa_result = fetch_with_exa(embedded_url, exa_api_key)
                if exa_result:
                    title = exa_result.get("title", "")
                    content = exa_result.get("text", "")[:3000]  # Limit size
                    summary = exa_result.get("summary", "")
                    embedded_content += f"\n\n---\n**Linked content: {title}**\n"
                    if summary:
                        embedded_content += f"Summary: {summary}\n\n"
                    embedded_content += f"{content}\n"
                    print(
                        f"Expanded URL: {embedded_url[:50]}... ({len(content)} chars)"
                    )
            except Exception as e:
                print(f"Failed to expand URL {embedded_url}: {e}")

    # Build display format
    if parent_context:
        display = f"**@{parent_author}:**\n> {parent_text}\n\n**↳ @{author} replied:**\n> {text}"
    else:
        display = f"> {text}"

    # Combine tweet text with expanded content
    full_text = f"{parent_context}[Tweet by @{author}]:\n{text}"
    if embedded_content:
        full_text += embedded_content

    return {
        "type": "tweet",
        "text": full_text,
        "author": author,
        "author_name": author_name,
        "likes": likes,
        "retweets": retweets,
        "display": display,
        "meta": f"@{author} · {likes} ❤️",
        "has_embedded_content": bool(embedded_content),
    }


# --- Exa fetching ---

EXA_SEARCH_BASE = "https://api.exa.ai/search"


def search_with_exa(query, api_key, num_results=3):
    """Search for context about a tool/topic using Exa AI."""
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
    }

    data = json.dumps(
        {
            "query": query,
            "numResults": num_results,
            "type": "auto",
            "contents": {
                "text": {"maxCharacters": 1500},
                "summary": True,
            },
        }
    ).encode()

    req = urllib.request.Request(
        EXA_SEARCH_BASE, data=data, headers=headers, method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
            results = result.get("results", [])
            if results:
                context = []
                for r in results[:num_results]:
                    title = r.get("title", "")
                    text = r.get("text", "")[:500]
                    url = r.get("url", "")
                    context.append(f"- {title}: {text}... ({url})")
                return "\n".join(context)
            return None
    except Exception as e:
        print(f"Exa search error: {e}")
        return None


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
            supadata_url = f"https://api.supadata.ai/v1/youtube/transcript?videoId={video_id}&text=true"
            req = urllib.request.Request(supadata_url)
            req.add_header("x-api-key", supadata_key)
            req.add_header("User-Agent", "FluxInbox/1.0")
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode())
                # text=true returns {"content": "transcript text"}
                if result.get("content"):
                    transcript_text = result["content"]
                    print(
                        f"Fetched transcript via Supadata: {len(transcript_text)} chars"
                    )
        except urllib.error.HTTPError as e:
            error_body = e.read().decode() if e.fp else ""
            print(f"Supadata API failed: {e.code} - {error_body[:200]}")
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
            "action_items": [],
            "flux_impact": None,
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

    # Action items
    action_items = analysis.get("action_items", [])
    if action_items:
        action_list = "\n".join([f"- [ ] {item}" for item in action_items])
        action_section = f"""
### Action Items
{action_list}
"""
    else:
        action_section = ""

    # Flux impact
    flux_impact = analysis.get("flux_impact")
    if flux_impact:
        flux_section = f"""
### Flux Impact
{flux_impact}
"""
    else:
        flux_section = ""

    # Key takeaways (for podcasts)
    key_takeaways = analysis.get("key_takeaways", [])
    if key_takeaways:
        takeaways_list = "\n".join([f"- {item}" for item in key_takeaways])
        takeaways_section = f"""
### Key Takeaways
{takeaways_list}
"""
    else:
        takeaways_section = ""

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
{action_section}{flux_section}{takeaways_section}
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


def create_recommendation_file(analysis, url, content, recommendations_path):
    """Create a recommendation YAML file from analysis."""
    import yaml
    from datetime import datetime

    content_type = analysis.get("type", "tool")
    category = analysis.get("category", "discoveries/").rstrip("/")

    # Map content type to folder
    type_to_folder = {
        "tool": "cli-tools",
        "mcp": "mcps",
        "plugin": "plugins",
        "skill": "skills",
        "pattern": "workflow-patterns",
        "repo": "applications",
    }

    base_folder = type_to_folder.get(content_type, "discoveries")

    # Extract name from title
    title = analysis.get("title", "unknown-tool")
    name = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40]

    # Build folder path
    if "/" in category:
        folder_path = os.path.join(recommendations_path, category)
    else:
        folder_path = os.path.join(recommendations_path, base_folder)

    os.makedirs(folder_path, exist_ok=True)
    yaml_path = os.path.join(folder_path, f"{name}.yaml")

    # Don't overwrite existing
    if os.path.exists(yaml_path):
        print(f"File already exists: {yaml_path}")
        return None

    # Build recommendation object
    rec = {
        "name": name,
        "category": content_type,
        "tagline": analysis.get("tldr", "")[:80],
        "description": analysis.get("what", ""),
        "use_cases": analysis.get("action_items", []),
        "install": {
            "type": "manual",
            "command": f"# See: {url}",
        },
        "verification": {
            "type": "manual",
        },
        "resources": [
            {"url": url, "type": "homepage"},
        ],
        "tags": [],
        "added_date": datetime.now().strftime("%Y-%m-%d"),
        "source": "slack-inbox",
        "source_url": url,
        "sdlc_phase": analysis.get("sdlc_phases", ["implementation"])[0]
        if analysis.get("sdlc_phases")
        else "implementation",
    }

    # Add flux impact as description suffix
    if analysis.get("flux_impact"):
        rec["description"] += f"\n\n**Flux Impact:** {analysis['flux_impact']}"

    with open(yaml_path, "w") as f:
        yaml.dump(rec, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    print(f"Created recommendation: {yaml_path}")
    return yaml_path


def main():
    # Get inputs
    url = os.environ.get("URL") or os.environ.get("TWEET_URL")  # Backward compat
    twitter_api_key = os.environ.get("TWITTER_API_KEY")
    anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY")
    exa_api_key = os.environ.get("EXA_API_KEY")
    recommendations_path = os.environ.get("RECOMMENDATIONS_PATH", ".")
    flux_plugin_path = os.environ.get("FLUX_PLUGIN_PATH", "")

    # Slack reaction tracking
    slack_channel = os.environ.get("SLACK_CHANNEL", "")
    slack_ts = os.environ.get("SLACK_TS", "")

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
        content = fetch_tweet_content(url, twitter_api_key, exa_api_key)
    elif url_type == "twitter_article":
        if not twitter_api_key:
            print("Error: TWITTER_API_KEY required for Twitter articles")
            exit(1)
        print("Fetching Twitter article...")
        content = fetch_article_content(url, twitter_api_key)
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

    # Verify ambiguous tool mentions with Exa search
    tool_verification = ""
    if url_type == "tweet" and exa_api_key:
        tweet_text = content.get("text", "")
        # Check if tweet is short/vague (just a link or under 150 chars of actual content)
        text_without_urls = re.sub(r"https?://\S+", "", tweet_text).strip()

        # Extract potential tool names (@ mentions that aren't common accounts)
        tool_mentions = re.findall(r"@(\w+)", tweet_text)
        common_accounts = {
            "x",
            "twitter",
            "youtube",
            "github",
            "vercel",
            "anthropic",
            "openai",
        }
        tool_mentions = [t for t in tool_mentions if t.lower() not in common_accounts]

        # If content is vague and mentions potential tools, search for context
        if len(text_without_urls) < 150 and tool_mentions:
            print(f"Tweet seems vague, searching for tool context: {tool_mentions}")
            for tool in tool_mentions[:2]:  # Limit to first 2 mentions
                search_result = search_with_exa(
                    f"{tool} tool software", exa_api_key, num_results=2
                )
                if search_result:
                    tool_verification += (
                        f"\n\n[VERIFIED CONTEXT for @{tool}]:\n{search_result}"
                    )
                    print(f"Found context for @{tool}")

    # Build content section for prompt
    if url_type == "tweet" or url_type == "twitter_article":
        content_section = f"""{"Tweet" if url_type == "tweet" else "Twitter Article"} by @{content.get("author", "unknown")} ({content.get("author_name", "")}) · {content.get("likes", 0)} likes, {content.get("retweets", 0)} RTs:
{content.get("text", "")}"""
        if tool_verification:
            content_section += tool_verification
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

    verdict = analysis.get("verdict", "Maybe")
    stars = analysis.get("stars", 3)

    print(f"Verdict: {verdict} ({stars} stars)")

    # AUTONOMOUS DECISION LOGIC:
    # - "Yes" + 4-5 stars → Create recommendation and commit directly
    # - "Duplicate" → Skip with log
    # - "No" or low stars → Skip with log
    # - "Maybe" → Create issue for human review (rare)

    if verdict == "Duplicate":
        duplicate_of = analysis.get("duplicate_of", "unknown")
        reason = analysis.get("duplicate_reason", "Already exists")
        print(f"SKIP (Duplicate): Already covered by {duplicate_of}")
        print(f"Reason: {reason}")

        # Create a closed issue for tracking
        body = create_issue_body(url, content, analysis)
        with open("/tmp/issue.md", "w") as f:
            f.write(body)

        cmd = [
            "gh",
            "issue",
            "create",
            "--title",
            f"[DUPLICATE] {title}",
            "--body-file",
            "/tmp/issue.md",
            "--label",
            "duplicate,auto-closed",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            issue_url = result.stdout.strip()
            # Close it immediately
            issue_num = issue_url.split("/")[-1]
            subprocess.run(
                [
                    "gh",
                    "issue",
                    "close",
                    issue_num,
                    "--comment",
                    f"Auto-closed: Duplicate of `{duplicate_of}`",
                ]
            )
            print(f"Created and closed duplicate issue: {issue_url}")
        update_slack_reaction(slack_channel, slack_ts, "x", "eyes")
        return

    if verdict == "No" or stars < 3:
        reason = analysis.get("stars_reason", "Not relevant enough")
        print(f"SKIP (Low value): {reason}")
        print("No issue created - not worth adding to Flux recommendations")
        update_slack_reaction(slack_channel, slack_ts, "x", "eyes")
        return

    if verdict == "Yes" and stars >= 4:
        # HIGH CONFIDENCE: Create recommendation directly
        print(f"AUTO-ADD: High confidence recommendation ({stars} stars)")

        yaml_path = create_recommendation_file(
            analysis, url, content, recommendations_path
        )

        if yaml_path:
            # Commit and push with retry logic for race conditions
            rel_path = os.path.relpath(yaml_path, recommendations_path)

            subprocess.run(["git", "config", "user.name", "Flux Inbox"], check=True)
            subprocess.run(
                ["git", "config", "user.email", "flux-inbox@nairon.ai"], check=True
            )
            # Pull latest before committing to reduce conflicts
            subprocess.run(["git", "pull", "--rebase", "origin", "main"], check=True)
            subprocess.run(["git", "add", yaml_path], check=True)

            commit_msg = f"inbox: auto-add {analysis.get('title', 'unknown')}\n\nSource: {url}\nVerdict: {verdict} ({stars} stars)\nReason: {analysis.get('stars_reason', '')}"
            subprocess.run(["git", "commit", "-m", commit_msg], check=True)

            # Push with retry - handle race conditions from concurrent workflows
            max_retries = 3
            for attempt in range(max_retries):
                result = subprocess.run(
                    ["git", "push", "origin", "main"], capture_output=True, text=True
                )
                if result.returncode == 0:
                    break
                if attempt < max_retries - 1:
                    print(
                        f"Push failed (attempt {attempt + 1}), pulling and retrying..."
                    )
                    subprocess.run(
                        ["git", "pull", "--rebase", "origin", "main"], check=True
                    )
                else:
                    print(f"Push failed after {max_retries} attempts: {result.stderr}")
                    raise subprocess.CalledProcessError(result.returncode, "git push")

            print(f"Committed: {rel_path}")
            print("No issue created - recommendation added directly to main")
            update_slack_reaction(slack_channel, slack_ts, "white_check_mark", "eyes")
        else:
            # File already exists or failed to create
            update_slack_reaction(slack_channel, slack_ts, "x", "eyes")
        return

    # MAYBE or moderate confidence: Create issue for human review
    print(f"REVIEW NEEDED: Creating issue for human decision")

    body = create_issue_body(url, content, analysis)
    with open("/tmp/issue.md", "w") as f:
        f.write(body)

    labels = ["inbox", content_type, "needs-review"]

    cmd = ["gh", "issue", "create", "--title", title, "--body-file", "/tmp/issue.md"]
    for label in labels:
        cmd.extend(["--label", label])

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"Error creating issue: {result.stderr}")
        exit(1)

    print(f"Created issue for review: {result.stdout.strip()}")
    # Issue created for review - use thinking emoji to indicate pending human review
    update_slack_reaction(slack_channel, slack_ts, "thinking_face", "eyes")


if __name__ == "__main__":
    main()
