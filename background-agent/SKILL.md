---
name: background-agent
description: Launch a Cursor CLI agent in tmux that runs autonomously after Cursor IDE disconnects. Use when the user says background agent, run in background, keep running, detached agent, run overnight, tmux agent, autonomous task, or wants work to continue after disconnect.
---

# Background Agent (Cursor CLI in tmux)

Runs a `cursor-agent -p` (print mode) session inside tmux so it survives Cursor IDE disconnect. The agent has full tool access: read/edit files, run shell commands.

## Prerequisites

1. **cursor-agent installed**: `which cursor-agent` (install: `curl https://cursor.com/install -fsSL | bash`)
2. **Authenticated**: `~/.config/cursor/auth.json` must have a valid `accessToken`. Test: `echo "ping" | cursor-agent -p`
3. **tmux session**: An existing tmux session (the `keep-awake` skill creates one called `overnight`)

## Critical Constraint

The Cursor CLI uses the Ink TUI framework which checks `process.stdout.isTTY`. **Any stdout redirect (`> file`, `| tee`, `2>&1 > log`) suppresses all output.** The only way to capture output is:

- Let stdout go to the tmux PTY (visible in the pane)
- Use `tmux pipe-pane` to tap the PTY master into a log file
- Use `tmux capture-pane -p -S -10000` to dump scrollback after completion

## Launch Procedure

### Step 1: Write the prompt to a file

```bash
cat > /tmp/agent_prompt.txt << 'EOF'
<the full task prompt here, including file paths, context, and explicit instructions>
EOF
```

**Prompt best practices:**
- Include full file paths the agent should read for context
- Be explicit about what to do and what NOT to do
- Specify where to write results/progress
- Include repo-specific instructions (e.g., `--config=no-tty` for bazel, `make fix` for lint)

### Step 2: Launch in tmux

```bash
TMUX_SESSION=overnight  # or create one: tmux new-session -d -s agents
WINDOW_NAME=my-task

tmux new-window -t "$TMUX_SESSION" -n "$WINDOW_NAME" \
  'bash -c "cat /tmp/agent_prompt.txt | cursor-agent -p; echo; echo EXIT_CODE=\$?; exec bash"'
```

The trailing `exec bash` keeps the window open after the agent finishes so you can read the output.

### Step 3: Enable log capture (optional)

```bash
tmux pipe-pane -t "$TMUX_SESSION:$WINDOW_NAME" "cat >> ~/agent_${WINDOW_NAME}.log"
```

This taps the PTY and writes to the log file alongside the pane output.

### Step 4: Monitor progress

From a Cursor session or SSH:

```bash
# Live pane content (last 500 lines)
tmux capture-pane -t overnight:my-task -p -S -500

# Check if agent process is still running
ps aux | grep 'cursor-agent.*-p' | grep -v grep

# Read log file (if pipe-pane was set up)
tail -100 ~/agent_my-task.log
```

## After Reconnect

When you reconnect to Cursor or SSH into the Cruise Shell:

```bash
# List tmux windows
tmux list-windows -t overnight

# Capture full output from a completed agent
tmux capture-pane -t overnight:my-task -p -S -10000 > ~/agent_output.txt

# Or attach interactively
tmux attach -t overnight
```

## Limitations

- **Single turn**: `-p` mode processes one prompt and exits. It does not loop or accept follow-up input.
- **No output redirect**: Cannot pipe/redirect stdout. Use `tmux pipe-pane` instead.
- **Auth expiry**: Long-running sessions may hit token expiry. The agent does not auto-refresh.
- **No cancel**: Once started, the agent runs to completion. Kill with `pkill -f 'cursor-agent.*-p'` or kill the specific PID.
- **Scrollback limit**: tmux default is 2000 lines. Increase with `tmux set-option -g history-limit 50000` before launching.

## Example: Full Workflow

```bash
# 1. Increase scrollback
tmux set-option -g history-limit 50000

# 2. Write prompt
cat > /tmp/agent_prompt.txt << 'EOF'
Read cruise/mlp/.../session_state.md and continue the work.
Focus on step 3: create the backbone-frozen config.
Do NOT push or commit. Write progress to the session state file.
EOF

# 3. Launch
tmux new-window -t overnight -n nvidia-train \
  'bash -c "cat /tmp/agent_prompt.txt | cursor-agent -p; echo; echo EXIT_CODE=\$?; exec bash"'

# 4. Log capture
tmux pipe-pane -t overnight:nvidia-train "cat >> ~/agent_nvidia-train.log"

# 5. Check later
tmux capture-pane -t overnight:nvidia-train -p -S -10000
```
