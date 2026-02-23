# N-bench Recommendations

Curated database of workflow optimizations for AI-augmented development.

Used by [`/nbench:improve`](https://github.com/Nairon-AI/n-bench) to recommend tools, plugins, and patterns.

## Categories

| Folder | Subfolders | Description |
|--------|------------|-------------|
| `mcps/` | `design/`, `search/`, `productivity/`, `dev/`, `browser/` | Model Context Protocol servers |
| `cli-tools/` | `linting/`, `git/`, `terminal/`, `tasks/`, `agent-workflow/`, `communication/`, `frontend/`, `security/`, `testing/`, `review/`, `system/` | Command-line tools |
| `applications/` | `individual/`, `collaboration/`, `developer/`, `frameworks/` | Desktop/native apps and app-building stacks |
| `skills/` | `frontend/`, `research/`, `backend/`, `codebase-mapping/`, `marketplaces/`, `marketing/`, `writing/`, `meta-learning/`, `security/`, `specification/` | Standalone skills |
| `plugins/` | *(empty)* | Claude Code plugins |
| `workflow-patterns/` | `git/`, `testing/`, `ai/`, `review/` | Best practices (not tools) |
| `models/` | *(flat)* | Model guidance and model hubs |
| `model-evaluations/` | *(flat)* | 3-day model capability reports from X/Twitter signals |

## Adding Recommendations

Anyone can submit a PR! We have an AI slop detector that automatically triages low-quality submissions.

### Via Slack (Internal)

Core team members drop URLs into the private `#nbench-inbox` channel. That's it.

**Supported URLs:**
- Tweets/X posts → discussions, tips, tool mentions
- YouTube videos → tutorials, demos, walkthroughs  
- GitHub repos → tools, MCPs, libraries
- Blog posts, docs, product pages → anything useful

The system automatically:
1. Fetches and analyzes the content
2. Checks for duplicates against existing recommendations
3. Creates a GitHub Issue with structured analysis
4. Labels by type (tweet, video, tool, mcp, plugin, etc.)

### Manual

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

Each recommendation is a YAML file following [schema.yaml](schema.yaml).

---

## Architecture

```
┌─────────────┐     ┌─────────────────────┐     ┌─────────────────┐
│   Slack     │────▶│ Cloudflare Worker   │────▶│ GitHub Action   │
│ #nbench-inbox│     │ (extracts URLs)     │     │ (analyzes)      │
└─────────────┘     └─────────────────────┘     └─────────────────┘
                                                        │
                    ┌───────────────────────────────────┘
                    ▼
            ┌───────────────┐     ┌─────────────┐
            │  Twitter API  │     │   Exa AI    │
            │  (tweets)     │     │ (everything │
            └───────────────┘     │    else)    │
                    │             └─────────────┘
                    └───────┬───────────┘
                            ▼
                    ┌───────────────┐
                    │    Claude     │
                    │  (analysis)   │
                    └───────────────┘
                            │
                            ▼
                    ┌───────────────┐
                    │ GitHub Issue  │
                    │ (for review)  │
                    └───────────────┘
```

### Components

| Component | Purpose |
|-----------|---------|
| **Slack `#nbench-inbox`** | Drop zone for URLs - just paste and go |
| **Cloudflare Worker** | Receives Slack events, extracts URLs, triggers GitHub |
| **GitHub Action** | Orchestrates fetching and analysis |
| **Twitter API** | Fetches tweet content + thread context |
| **Exa AI** | Fetches and summarizes any other URL |
| **Claude** | Analyzes relevance, categorizes, checks for duplicates |

### Issue Format

Issues are created with:
- **Type prefix**: `Tweet:`, `Video:`, `Tool:`, `MCP:`, `Plugin:`, etc.
- **Verdict**: ✅ Yes / ❌ No / 🤔 Maybe / 🔄 Duplicate
- **Metadata**: Relevance stars, category, SDLC phases
- **Duplicate check**: Against existing recommendations + N-bench plugin built-ins

---

## How It Works

1. User runs `/nbench:improve`
2. N-bench analyzes their environment (repo, MCPs, sessions)
3. Fetches recommendations from this repo
4. Claude determines relevance for each recommendation
5. User selects which to install
6. N-bench installs and verifies

## Model Evaluation Radar

`scripts/model-eval-radar.py` monitors AI lab release announcements and runs a 3-day collection window:

1. Detects release tweets from labs (`@AnthropicAI`, `@OpenAI`, `@GoogleAI`, etc.)
2. Collects monitored-account and high-engagement discovery tweets for each model
3. Generates structured reports in `model-evaluations/`

Run manually:

```bash
TWITTER_API_KEY=... python3 scripts/model-eval-radar.py
```

Or use `.github/workflows/model-eval-radar.yml` for daily automation.

## Community

Join the most AI-native developer community on the planet. No hype. No AI slop. Just practical discussions on becoming the strongest developers alive.

AI-slop pull requests are automatically triaged and closed.

[discord.gg/CEQMd6fmXk](https://discord.gg/CEQMd6fmXk)

## License

MIT
