# Flux Recommendations

Curated database of workflow optimizations for AI-augmented development.

Used by [`/flux:improve`](https://github.com/Nairon-AI/flux) to recommend tools, plugins, and patterns.

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

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

Each recommendation is a YAML file following [schema.yaml](schema.yaml).

## How It Works

1. User runs `/flux:improve`
2. Flux analyzes their environment (repo, MCPs, sessions)
3. Fetches recommendations from this repo
4. Claude determines relevance for each recommendation
5. User selects which to install
6. Flux installs and verifies

## Community

Join the most AI-native developer community on the planet. No hype. No AI slop. Just practical discussions on becoming the strongest developers alive.

[discord.gg/nairon](https://discord.gg/nairon) *(coming soon)*

## License

MIT
