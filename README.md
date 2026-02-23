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

## Contributing

Anyone can submit a PR! We have an AI slop detector that automatically triages low-quality submissions.

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines. Each recommendation is a YAML file following [schema.yaml](schema.yaml).

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
