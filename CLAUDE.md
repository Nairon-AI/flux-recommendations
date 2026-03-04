# Claude Code Context

Project-specific context for Claude Code when working in this repository.

## External APIs

### Twitter API (twitterapi.io)

When working with Twitter/X API integration in this repo, always reference the official documentation:

- **Base URL**: `https://api.twitterapi.io`
- **Docs**: https://docs.twitterapi.io/api-reference/endpoint/get_article

Key endpoints used:
- `GET /twitter/tweets?tweet_ids=` - Fetch tweets by ID
- `GET /twitter/article?tweet_id=` - Fetch X articles (long-form posts)

The article endpoint returns:
- `article.title` - Article title
- `article.preview_text` - Preview/summary text
- `article.contents[]` - Array of content blocks with `text` field
- `article.author` - Author info (userName, name, etc.)
- `article.likeCount`, `article.viewCount` - Engagement metrics

Authentication: `X-API-Key` header

## Repository Structure

- `scripts/slack-inbox.py` - Processes URLs from Slack, uses Twitter API for tweets/articles
- `scripts/monitor.py` - N-bench Radar, monitors Twitter accounts for new tools
- `.github/workflows/slack-inbox.yml` - Workflow triggered by Slack links
- `.github/workflows/nbench-radar.yml` - Daily Twitter monitoring workflow
