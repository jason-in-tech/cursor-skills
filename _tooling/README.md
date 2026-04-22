# _tooling

Backup of the scripts that sync `~/.cursor/skills/` between this Mac and the
cruise VM (`/home/yike.li/.cursor/skills/`). The sync runs hourly via a macOS
LaunchAgent.

## Files

- `cursor-sync` — the shell script that does bidirectional rsync. Install to
  `~/.local/bin/cursor-sync` and make executable.
- `com.cursor.sync.plist` — the LaunchAgent that invokes `cursor-sync pull`
  every 3600 seconds. Install to `~/Library/LaunchAgents/` and load with
  `launchctl load ~/Library/LaunchAgents/com.cursor.sync.plist`.

## History

Before 2026-04-21 the script used `rsync -avz --delete` one-way from cruise
to local, which silently deleted any skill created locally but not present on
cruise. Known casualties:

- `meeting-summarizer` (recreated multiple times, deleted every hour)
- `meeting-research` (same)
- `wechat-chat-analysis` (never made it to GitHub backup; lost)

Current script uses `rsync -az --update` in BOTH directions and no `--delete`.
Intentional removals go through `cursor-sync delete <name>`.

## Reinstall after a fresh checkout

```bash
install -m 0755 _tooling/cursor-sync ~/.local/bin/cursor-sync
cp _tooling/com.cursor.sync.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.cursor.sync.plist
```
