# Phistory

[中文](README_zh.md)

Phistory tracks how system prompts change across popular coding-agent CLIs like Claude Code, Codex, DeepSeek Harness, Antigravity, Grok Build, MiniMax Code, Kimi Code, MiMo Code, OpenClaw, Hermes, Kimi CLI, opencode, Pi, and Oh My Pi.

Open the web viewer to compare prompt snapshots across versions and see how agent design changes through prompts, tools, policies, and runtime instructions.

**Start here:** [phistory.cc](https://phistory.cc/)

> Checks for new releases hourly. Archive last updated: **2026-09-26 08:04 UTC**.

![Phistory prompt diff viewer](docs/screenshot.png)

## Why Use It

- Follow how Anthropic, OpenAI, and other agent builders iterate on system prompts over time.
- See when new tools, permission checks, model defaults, and user-confirmation rules are added.
- Compare how different CLIs structure agent behavior, tool use, and developer-facing constraints.
- Cite stable prompt snapshots in posts, research notes, audits, or debugging reports.

## How It Works

For each supported release, Phistory installs the exact CLI package and runs each configured snapshot through [`claude-tap`](https://github.com/WEIFENG2333/claude-tap), captures the prompt-bearing HTTP request without calling the real model provider, and stores the result under `captures/<agent>/<version>/variants/<variant>/` with `prompt.md`, `trace.jsonl`, and `meta.json`. Capture configurations use a `default` snapshot as their baseline; selected models or modes are stored as additional variants.

For recent Claude Code releases, Phistory also extracts static prompt-like strings from the installed package and stores them under `captures/<agent>/<version>/static/`. The candidate archive keeps the raw extraction input so matching rules can be improved later without reinstalling every historical package.

GitHub Actions checks automatically tracked CLI releases every hour and commits new snapshots when they appear.

## Local Development

Use the hosted viewer at [phistory.cc](https://phistory.cc/). These commands are for local development, capture reproduction, historical backfills, and regenerating generated files.

```bash
# Install the locked development environment.
uv sync --all-groups

# Capture the latest release and every configured snapshot for each CLI.
uv run phistory capture --latest --agents claude-code,codex,dsh,antigravity,grok,minimax-code,kimi-code,mimo,openclaw,hermes,kimi,opencode,pi,omp

# Capture only selected Codex snapshots.
uv run phistory capture --latest --agents codex --variants default,gpt-5.5,gpt-5.6

# Capture a historical version range for one agent.
uv run phistory backfill claude-code --from 2.1.113 --to latest

# Rebuild static prompt files for the latest 10 captured Claude Code versions.
uv run phistory extract-static claude-code --latest-captured 10

# Regenerate README.md, README_zh.md, docs/captures.md, and captures/index.json.
uv run phistory render-index

# Regenerate the static web viewer at index.html.
uv run phistory render-site
```

## Supported Agents

- Claude Code (`@anthropic-ai/claude-code`)
- Codex CLI (`@openai/codex`)
- DeepSeek Harness (`@deepseek-ai/dsh`)
- Antigravity CLI (`google-antigravity/antigravity-cli`)
- Grok Build (`@xai-official/grok`)
- MiniMax Code desktop app ([official download](https://agent.minimax.io/download))
- Kimi Code (`@moonshot-ai/kimi-code`)
- MiMo Code (`@mimo-ai/cli`)
- OpenClaw (`openclaw`)
- Hermes Agent (`hermes-agent`)
- Kimi CLI (`MoonshotAI/kimi-cli`)
- opencode (`opencode-ai`)
- Pi (`@earendil-works/pi-coding-agent`)
- Oh My Pi (`@oh-my-pi/pi-coding-agent`)

## Capture Status

Last capture update: 2026-09-26 08:04 UTC

| Agent | Latest | Versions | Snapshots | Last Captured |
| --- | --- | ---: | ---: | --- |
| Claude Code | [2.1.283 - 2026-09-25](captures/claude-code/2.1.283/variants/default/prompt.md) | 413 | 413 | 2026-09-26 07:58 UTC |
| Codex CLI | [0.157.1 - 2026-09-26](captures/codex/0.157.1/variants/default/prompt.md) | 86 | 116 | 2026-09-26 07:58 UTC |
| DeepSeek Harness | [0.1.5-rc.3 - 2026-09-22](captures/dsh/0.1.5-rc.3/variants/headless/prompt.md) | 12 | 43 | 2026-09-24 07:48 UTC |
| Antigravity CLI | [1.2.11 - 2026-09-25](captures/antigravity/1.2.11/variants/default/prompt.md) | 49 | 49 | 2026-09-25 08:14 UTC |
| Grok Build | [1.0.41 - 2026-09-22](captures/grok/1.0.41/variants/default/prompt.md) | 137 | 137 | 2026-09-23 08:02 UTC |
| MiniMax Code | [3.0.73 - 2026-09-18](captures/minimax-code/3.0.73/variants/default/prompt.md) | 37 | 37 | 2026-09-19 07:37 UTC |
| Kimi Code | [2.1.1 - 2026-09-24](captures/kimi-code/2.1.1/variants/default/prompt.md) | 74 | 74 | 2026-09-24 07:53 UTC |
| Qwen Code | [0.24.6 - 2026-09-26](captures/qwen-code/0.24.6/variants/default/prompt.md) | 133 | 133 | 2026-09-26 08:04 UTC |
| MiMo Code | [0.1.15 - 2026-09-22](captures/mimo/0.1.15/variants/default/prompt.md) | 15 | 15 | 2026-09-23 08:02 UTC |
| OpenClaw | [2026.9.6 - 2026-09-23](captures/openclaw/2026.9.6/variants/default/prompt.md) | 76 | 76 | 2026-09-24 07:54 UTC |
| Hermes Agent | [v2026.9.24 - 2026-09-24](captures/hermes/v2026.9.24/variants/default/prompt.md) | 33 | 33 | 2026-09-25 08:15 UTC |
| Kimi CLI | [1.51.0 - 2026-09-21](captures/kimi/1.51.0/variants/default/prompt.md) | 23 | 23 | 2026-09-22 07:57 UTC |
| opencode | [1.18.32 - 2026-09-21](captures/opencode/1.18.32/variants/default/prompt.md) | 111 | 111 | 2026-09-22 07:58 UTC |
| Pi | [0.87.1 - 2026-09-22](captures/pi/0.87.1/variants/default/prompt.md) | 49 | 49 | 2026-09-23 08:02 UTC |
| Oh My Pi | [18.3.2 - 2026-09-26](captures/omp/18.3.2/variants/default/prompt.md) | 92 | 92 | 2026-09-26 08:04 UTC |

## Project Trend

![Phistory star history](https://api.star-history.com/svg?repos=WEIFENG2333/phistory&type=Date)
