# Flux Recommendations

**Curated workflow optimizations that make AI agents actually work.**

Used by `/flux:improve` to analyze your sessions, identify friction, and recommend the right tools.

## Compatibility

| Agent | Status | Session Analysis |
|-------|--------|------------------|
| **OpenCode** | Full support | SQLite database |
| **Claude Code** | Full support | JSONL files |
| **Cursor** | Planned | — |
| **Codex** | Planned | — |

Works with both global (`~/.config/opencode/`) and local (`.opencode/`, `.claude/`) configurations.

## The Problem

Process failures, not model failures:

- **Repeating the same debugging cycle** — trying the same broken approach 5 times before pivoting
- **Losing context mid-session** — agent forgets what was decided, you re-explain
- **Drip-feeding requirements** — "also add X" after implementation, causing rework
- **Missing obvious tools** — not using MCPs/skills that would save hours

`/flux:improve` analyzes your actual sessions, finds these patterns, and recommends specific fixes from this database.

## Categories

| Folder | Subfolders | Description |
|--------|------------|-------------|
| `mcps/` | `design/`, `search/`, `productivity/`, `dev/` | Model Context Protocol servers |
| `cli-tools/` | `linting/`, `git/`, `terminal/`, `tasks/` | Command-line tools |
| `applications/` | `individual/`, `collaboration/` | Desktop/native apps |
| `skills/` | *(flat)* | Standalone skills |
| `plugins/` | *(empty)* | Claude Code plugins |
| `workflow-patterns/` | `git/`, `testing/`, `ai/` | Best practices (not tools) |

### Structure

```
mcps/
├── design/       # excalidraw, figma, pencil
├── search/       # exa, context7
├── productivity/ # linear, supermemory
└── dev/          # github

cli-tools/
├── linting/      # oxlint, biome
├── git/          # lefthook
├── terminal/     # jq, fzf
└── tasks/        # beads

applications/
├── individual/    # wispr-flow, raycast, dia (personal productivity)
└── collaboration/ # granola (team/stakeholder communication)

skills/           # stagehand-e2e, remotion, repoprompt

workflow-patterns/
├── git/          # pre-commit-hooks, atomic-commits
├── testing/      # test-first-debugging
└── ai/           # agents-md-structure, context-management
```

## Adding Recommendations

> **Note:** Only the Nairon core team can add recommendations to prevent low-quality submissions.

### Via Slack (Internal)

Core team members drop URLs into the private `#flux-inbox` channel. That's it.

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
│ #flux-inbox │     │ (extracts URLs)     │     │ (analyzes)      │
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
| **Slack `#flux-inbox`** | Drop zone for URLs - just paste and go |
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
- **Duplicate check**: Against existing recommendations + flux plugin built-ins

---

## How `/flux:improve` Works

```
Step 1: Extract session data
✓ Found 20 sessions in /Users/you/project
✓ Extracted 2,500 messages
✓ Identified 15 friction signals

Step 2: Analyze friction points
| # | Friction | Evidence |
|---|----------|----------|
| 1 | API retry loop | "bruh" "again" "still failing" (6 attempts) |
| 2 | Task confusion | "i thought we completed this?" |

Step 3: Search recommendations database
✓ Loaded 27 recommendations from ~/.flux/recommendations/
  ├── 6 MCPs (context7, exa, figma...)
  ├── 6 CLI tools (beads, jq, fzf...)
  └── 7 Workflow patterns (test-first-debugging...)

Step 4: Match friction → recommendations
| Your Friction | Matched Tool | Why |
|---------------|--------------|-----|
| API retry loop | test-first-debugging | Write failing test first |
| Task confusion | beads | Git-backed tracker AI can't forget |

Step 5: Interactive apply
→ Select which improvements to apply
→ Agent implements: AGENTS.md rules, tool installs, hooks
```

## Community

Join the most AI-native developer community on the planet. No hype. No AI slop. Just practical discussions on becoming the strongest developers alive.

[discord.gg/nairon](https://discord.gg/nairon) *(coming soon)*

## License

MIT
