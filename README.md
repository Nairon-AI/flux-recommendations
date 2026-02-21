# Flux Recommendations

Curated database of workflow optimizations for AI-augmented development.

Used by [`/flux:improve`](https://github.com/Nairon-AI/flux) to recommend tools, plugins, and patterns.

## Categories

| Folder | Description |
|--------|-------------|
| `mcps/` | Model Context Protocol servers |
| `plugins/` | Claude Code plugins |
| `skills/` | Standalone skills |
| `cli-tools/` | Command-line tools |
| `applications/` | Desktop/native apps (voice, transcription, etc.) |
| `workflow-patterns/` | Best practices (not tools) |

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
