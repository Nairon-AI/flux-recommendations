# Flux Recommendations

Curated database of workflow optimizations for AI-augmented development.

Used by [`/flux:improve`](https://github.com/Nairon-AI/flux) to recommend tools, plugins, and patterns.

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

## Contributing

Anyone can submit a PR! We have an AI slop detector that automatically triages low-quality submissions.

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines. Each recommendation is a YAML file following [schema.yaml](schema.yaml).

---

## How It Works

1. User runs `/flux:improve`
2. Flux analyzes their environment (repo, MCPs, sessions)
3. Fetches recommendations from this repo
4. Claude determines relevance for each recommendation
5. User selects which to install
6. Flux installs and verifies

## N-bench Radar (Fully Autonomous)

This repo continuously improves itself. The **N-bench Radar** runs daily via GitHub Actions and requires **zero human input**:

1. **Monitors** high-signal X/Twitter accounts (AI developers, tool makers, thought leaders)
2. **Validates** tweets against existing recommendations → adds social proof mentions
3. **Evaluates** unmatched tweets with AI → determines if they're about valuable NEW tools
4. **Auto-creates** recommendation YAMLs for genuinely useful discoveries
5. **Discards** low-value tweets (general chat, opinions, low engagement)
6. **Auto-commits** directly to main

**Criteria for new tool discovery:**
- 50+ likes (engagement signal)
- Specific tool/MCP/CLI/plugin/skill/pattern (not vague advice)
- Relevant to AI-assisted development
- Actionable (has install method, homepage, etc.)

The radar ingests useful data from high-intent signals on X, so the recommendation database grows smarter every day without manual curation.

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
