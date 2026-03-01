# Contributing to Flux Recommendations

Thanks for helping improve AI development workflows!

Anyone can submit a PR. We have an AI slop detector that automatically triages low-quality submissions.

## What We're Looking For

- **Tweets/X posts** → discussions, tips, tool mentions
- **YouTube videos** → tutorials, demos, walkthroughs
- **GitHub repos** → tools, MCPs, libraries
- **Blog posts, docs, product pages** → anything useful

## Adding a New Recommendation

1. Fork this repo
2. Create a YAML file in the appropriate category folder
3. Follow the [schema.yaml](schema.yaml) format
4. Submit a PR

PRs are automatically analyzed for duplicates and relevance.

## YAML Template

```yaml
name: tool-name
category: mcp  # mcp, plugin, skill, cli-tool, vscode-extension, workflow-pattern
tagline: "One-line description"

description: |
  Full description of what this tool does.
  Can be multiple lines with markdown.

use_cases:
  - When to use this
  - Another use case

prerequisites:
  - Node.js 18+
  - npm or pnpm

install:
  type: mcp  # mcp, plugin, skill, npm, brew, manual
  command: |
    npm install -g tool-name
  config_snippet: |
    {
      "key": "value"
    }

verification:
  type: command_exists  # mcp_connect, command_exists, config_exists, manual
  test_command: "tool-name --version"
  success_indicator: "Should output version number"

related_tools:
  - other-tool

resources:
  - url: https://example.com
    type: homepage
  - url: https://github.com/org/repo
    type: github

added_date: 2025-02-21
source: community
source_url: null

ratings:
  usefulness: 4
  setup_difficulty: 2

tags:
  - relevant
  - tags
```

## Guidelines

- **Test before submitting**: Make sure the install commands work
- **Be specific**: Include exact commands, not vague instructions
- **Add verification**: How do we know it installed correctly?
- **Rate honestly**: usefulness 1-5, difficulty 1-5 (1=easy)

## Questions?

Open an issue or reach out to [@nairon_ai](https://x.com/nairon_ai)
