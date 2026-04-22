# Cursor Skills

Personal [Cursor](https://cursor.com/) Agent Skills — persistent AI workflow instructions that the model loads when relevant keywords / file types / intents appear.

Each subdirectory is one skill: `SKILL.md` is mandatory and carries the frontmatter that Cursor uses to decide when to load it. Optional `scripts/` hold companion shell / python helpers.

## Why this repo exists

Skills live at `~/.cursor/skills/<name>/SKILL.md` on disk. This repo is both a backup and the history log of the fix for the "disappearing skills" bug.

**Root cause (confirmed 2026-04-21):** a user-level LaunchAgent (`com.cursor.sync.plist`) ran `rsync -avz --delete` every hour from `cruise:/home/yike.li/.cursor/skills/` to `~/.cursor/skills/`. The `--delete` flag obliterated every skill that existed locally but not on cruise — which is every skill created on the Mac (including `meeting-summarizer`, `meeting-research`, `wechat-chat-analysis`, and even this repo's own `.git` directory).

**Fix (2026-04-21):** `_tooling/cursor-sync` now does `rsync -az --update` in both directions with **no `--delete`**. Intentional removals require the explicit `cursor-sync delete <name>` subcommand. The `_tooling/` folder contains a committed copy of the script + LaunchAgent plist so it's also backed up.

If a skill disappears anyway: `cd ~/.cursor/skills && git restore -- <skill>/`.

## Skills

Brief index — see each `SKILL.md` for the full spec.

- **background-agent** — launch a `cursor-agent` in tmux that survives IDE disconnect
- **compute-detection-ap** — detection Average Precision on internal data
- **confluence-publish** — publish a markdown file as a Confluence page
- **cruise-auth-refresh** — automate `authcli refresh` including Okta / Duo
- **fix-markdown-crash** — diagnose and fix markdown files that crash Cursor
- **get-transcript-dir** — return the agent transcript path for the current session
- **google-doc-publish** — publish markdown as a beautifully formatted Google Doc
- **keep-awake** — keep a Cruise shell session alive up to 24h
- **meeting-research** — query existing meeting transcripts for prep / action-item rollup / fact retrieval
- **meeting-summarizer** — audio → polished transcript → opinionated summary, one shot
- **nvidia-featurization** — NVIDIA featurization pipeline runner
- **nvidia-training-eval** — NVIDIA training-evaluation pipeline runner
- **rebase-to-develop** — rebase current branch onto latest `origin/develop`
- **review-pr** — review a GitHub PR by URL or number
- **run-notebook-to-html** — execute a `.ipynb` and render its HTML
- **sc3-protocol** — end-to-end SC3 protocol eval on Galileo for an Olympus checkpoint
- **select-gpu-quota** — pick best `business_attribution` for a GPU training job
- **slack-prepare** — pre-seed Slack browser automation
- **slack-response** — monitor Slack DMs / channels, draft replies
- **table-heatmap** — render a table as a heatmap
- **trino-lakehouse** — query the Trino lakehouse
- **write-technical-report** — author a technical report from data + narrative

## How Cursor reads this

Cursor's agent runtime scans `~/.cursor/skills/<name>/SKILL.md`, parses the YAML frontmatter (`name`, `description`), and surfaces the skill to the model when its description keywords match the user's turn. The model then reads the body on demand.

Keep descriptions specific — they're the signal Cursor uses to decide relevance.
