---
name: keep-awake
description: Keep a Cruise Shell session alive for up to 24 hours. Automates Slack keep-alive via Playwright, runs caffeinate on Mac via reverse SSH, verifies VPN and SSH health. First run requires one Mac Terminal command; all subsequent runs are fully automatic. Use when the user says "keep awake", "keep alive", "prepare overnight", "going to bed", "leaving cursor running", or wants to run agents unattended for hours.
---

# Keep Awake (24-Hour Session)

Automated preparation for unattended Cursor sessions on Cruise Shells.
First invocation requires a single Mac Terminal command (one-time setup + tunnel).
All subsequent invocations on any VM are fully automatic -- zero manual steps.

## Failure modes addressed

| # | Failure Mode | Cause | Automated Fix |
|---|-------------|-------|---------------|
| 1 | Cruise Shell deleted | "Are you still there?" idle timeout | Playwright triggers Keep Alive via Slack Block Kit |
| 2 | VPN disconnects | Mac sleeps, Cisco VPN `DisconnectOnSuspend` fires | Reverse SSH runs `caffeinate` on Mac |
| 3 | SSH tunnel dies | VPN drop or network interruption | caffeinate + SSH keepalive + Cisco AutoReconnect |
| 4 | Auth tokens expire | Token TTL shorter than session | `authcli refresh` before starting |

## Parallelization guide

Steps 0 and 1a must run first (environment detection + status request). After that:

- **Step 1b-1e** (Playwright Keep Alive) and **Step 2a** (reverse SSH test) can start in parallel.
- If Step 2a needs user action (Mac command), start the **background watcher** (Step 2a-alt)
  immediately and proceed with Steps 3-5 while waiting. The watcher will auto-complete
  caffeinate the instant the tunnel appears.
- **Steps 3, 4, 5** (VPN, tmux, auth) are all independent and can run in parallel.
  Steps 3 (VPN) requires Mac SSH, so if tunnel isn't up yet, defer it until watcher succeeds.

Maximize parallelism to complete the skill faster.

## Step 0: Environment detection

Verify we're on a Cruise Shell, check for reverse tunnel, and identify the Mac.

```bash
echo "CRUISE_SHELLS=$CRUISE_SHELLS"
echo "=== Reverse tunnel check ==="
nc -z -w 1 localhost 2222 2>/dev/null && echo "Reverse tunnel: ACTIVE (port 2222)" || echo "Reverse tunnel: NOT AVAILABLE"
echo "=== Direct SSH check ==="
MAC_IP=$(echo $SSH_CONNECTION | awk '{print $1}')
echo "Mac IP: $MAC_IP"
nc -z -w 3 $MAC_IP 22 2>/dev/null && echo "Direct SSH: REACHABLE" || echo "Direct SSH: UNREACHABLE"
```

If `CRUISE_SHELLS` is empty, this is not a Cruise Shell -- skip Step 1.

**Mac connectivity priority**:
1. **Reverse tunnel** (port 2222 on localhost) -- preferred, works regardless of VPN routing
2. **Direct SSH** to Mac IP -- fallback, only works if GCP can route to VPN client subnet
3. **Manual tunnel from Mac** -- user runs `ssh -N -f -R 2222:localhost:22` from Mac Terminal

**NEVER skip Step 2.** If both automated paths fail, use the `ssh -N -f -R` fallback
in Step 2a to create the tunnel from the Mac side. Start the background watcher
(Step 2a-alt) in parallel so caffeinate starts automatically the instant the tunnel
appears.

## Step 1: Cruise Shell Keep Alive (Playwright)

There is no CLI or text command for Keep Alive. It must be triggered through the Slack
Block Kit interactive dropdown via Playwright's React fiber injection.

### 1a. Request fresh status and check if already active

```
CallMcpTool: user-slack-ss / slack_send_message
  channel_id: "D096E8N8PC5"
  message: "status"
```

Wait 3 seconds, then read the response:

```
CallMcpTool: user-slack-ss / slack_read_channel
  channel_id: "D096E8N8PC5"
  limit: 5
```

Confirm machine shows `Status: RUNNING`. Note the machine name (e.g. `cs-0uz7bqlr-...`).

**Check if Keep Alive is already active**: Look at the `Keep Alive:` field in the bot
response. If it shows a date 2+ days in the future, Keep Alive is already at or near
the maximum (3 days is the max). In that case, **skip Steps 1b-1e entirely** and report
the existing expiry date. There is no benefit to re-triggering when it's already maxed.

### 1b. Ensure Chrome is installed and navigate to Slack DM

**Pre-flight: Chrome installation check.** Playwright requires a Chrome binary. On fresh
Cruise Shells it may not be installed. Check and install before navigating:

```bash
if [ -f /opt/google/chrome/chrome ]; then
  echo "Chrome: installed ($(google-chrome --version 2>/dev/null || echo 'unknown version'))"
else
  echo "Chrome: NOT FOUND -- installing..."
  npx playwright install chrome 2>&1 | tail -3
fi
```

If Chrome is not installed, `npx playwright install chrome` takes ~60-90 seconds. Use
`block_until_ms: 120000` to avoid premature backgrounding.

**Pre-flight: Clear stale browser locks.** If a prior Playwright session crashed or was
interrupted, the Chrome profile may be locked. Clean up before navigating:

```bash
pkill -f "chrome.*playwright" 2>/dev/null
rm -f /home/yike.li/.cache/ms-playwright/mcp-chrome-*/SingletonLock 2>/dev/null
echo "Browser locks cleared"
```

**Navigate:**

```
CallMcpTool: user-playwright / browser_navigate
  url: "https://app.slack.com/client/E078AUGKMDE/D096E8N8PC5"
```

Wait **8 seconds** (Slack is slow to render Block Kit messages). Take a snapshot:

```
CallMcpTool: user-playwright / browser_snapshot
```

Verify the snapshot contains a `combobox` element (the Keep Alive dropdown). If you see
`Loading history...` but no combobox, wait 5 more seconds and snapshot again.

### 1c. Find the correct combobox and open the dropdown

**CRITICAL: Multiple comboboxes exist.** The DM history contains many status messages,
each with its own Keep Alive combobox. `document.querySelector('[role="combobox"]')`
returns the FIRST one in DOM order (oldest message), which is almost always wrong.

**Step 1: Identify the correct combobox from the snapshot.**

Search the snapshot output (from Step 1b) for the machine name noted in Step 1a. The
snapshot structure looks like:

```
- 'listitem "Cruise Shells: Your machines: *cs-XXXXX-...-NNNNNN* ..."':
    ...
    - combobox "None" [ref=eNNNN]
    ...
    - generic [ref=eNNNN]: "Keep Alive:"
```

Find the `listitem` whose label contains the current machine name. Inside that listitem,
note the `combobox` ref. The combobox value will be `"None"` (not yet active) or a date
string (already active -- check if it's 2+ days in the future before proceeding).

If there are multiple listitem entries for the same machine (from repeated `status`
commands), use the **last one** (most recent status message, closest to the bottom of
the snapshot).

**Step 2: Click the combobox using its snapshot ref.**

```
CallMcpTool: user-playwright / browser_click
  element: "Keep Alive combobox for <machine-name>"
  ref: "<combobox ref from snapshot>"
```

Take a snapshot. If `listbox` with `option` elements is visible, proceed to 1d.

**Fallback chain** (if `browser_click` doesn't open the dropdown):

**Fallback 1: React fiber onClick**

```
CallMcpTool: user-playwright / browser_evaluate
  function: |
    () => {
      const comboboxes = document.querySelectorAll('[role="combobox"]');
      const target = comboboxes[comboboxes.length - 1];  // last = most recent status message
      if (!target) return 'no combobox found';
      const propsKey = Object.keys(target).find(k => k.startsWith('__reactProps$'));
      if (propsKey && target[propsKey].onClick) {
        target[propsKey].onClick({
          preventDefault: () => {}, stopPropagation: () => {},
          nativeEvent: new MouseEvent('click', { bubbles: true }),
          target: target, currentTarget: target, type: 'click'
        });
      }
      target.focus();
      return 'last combobox opened via React onClick';
    }
```

Take a snapshot. If `listbox` with `option` elements is visible, proceed to 1d.

**Fallback 2: React fiber onFocus + onMouseDown**

Some Slack versions wire the dropdown to `onFocus` or `onMouseDown` instead of `onClick`:

```
CallMcpTool: user-playwright / browser_evaluate
  function: |
    () => {
      const comboboxes = document.querySelectorAll('[role="combobox"]');
      const target = comboboxes[comboboxes.length - 1];
      if (!target) return 'no combobox';
      const propsKey = Object.keys(target).find(k => k.startsWith('__reactProps$'));
      if (!propsKey) return 'no React props found';
      const props = target[propsKey];
      const synth = {
        preventDefault: () => {}, stopPropagation: () => {},
        nativeEvent: new MouseEvent('mousedown', { bubbles: true }),
        target: target, currentTarget: target, type: 'mousedown'
      };
      if (props.onMouseDown) props.onMouseDown(synth);
      if (props.onFocus) props.onFocus({ ...synth, type: 'focus' });
      if (props.onClick) props.onClick({ ...synth, type: 'click' });
      target.focus();
      return { handlers: Object.keys(props).filter(k => k.startsWith('on')) };
    }
```

Take a snapshot. If `listbox` visible, proceed to 1d.

**Fallback 3: Keyboard navigation (MOST RELIABLE as of Apr 2026)**

Click the combobox ref first (using `browser_click`), then press ArrowDown to open:

```
CallMcpTool: user-playwright / browser_press_key
  key: "ArrowDown"
```

Take a snapshot. This click-then-ArrowDown approach has been the most reliable method
for opening the Slack Block Kit dropdown.

**If all approaches fail**: The combobox text already shows the current Keep Alive
expiry date. If it shows any future date, Keep Alive is already active. Report the
date and move on. Only escalate to the user if the date is in the past or missing.

### 1d. Select longest Keep Alive duration

```
CallMcpTool: user-playwright / browser_evaluate
  function: |
    () => {
      const options = document.querySelectorAll('[role="option"]');
      if (!options.length) return 'no options - dropdown may not be open';
      const target = options[options.length - 1];  // last = longest duration
      const propsKey = Object.keys(target).find(k => k.startsWith('__reactProps$'));
      if (!propsKey || !target[propsKey].onClick) return 'no React onClick on option';
      target[propsKey].onClick({
        preventDefault: () => {}, stopPropagation: () => {},
        nativeEvent: new MouseEvent('click', { bubbles: true }),
        target: target, currentTarget: target, type: 'click'
      });
      return { triggered: true, option: target.textContent };
    }
```

This dispatches to Slack's `blocks.actions` internal API, which forwards the
interaction to the Cruise Shells bot.

### 1e. Verify bot confirmation

Wait 10 seconds. Read the DM:

```
CallMcpTool: user-slack-ss / slack_read_channel
  channel_id: "D096E8N8PC5"
  limit: 5
```

**Expected bot messages** (all three must appear):
1. "Received request to keep machine ... alive, processing..."
2. "Marking your machine ... to be kept alive."
3. "Keep Alive request for machine ... has completed."

If missing, retry from Step 1c. If the dropdown option refs changed, take a fresh
snapshot to get new refs.

## Step 2: Run caffeinate on Mac (Reverse SSH)

The VPN is Cisco Secure Client with `DisconnectOnSuspend` policy. If the Mac sleeps,
VPN drops immediately and does NOT auto-reconnect until wake. `caffeinate` prevents
sleep entirely.

### One-time Mac setup

The Mac needs Remote Login enabled and a one-time config command. **Check if already
done** by looking for the marker file:

```bash
test -f ~/.keep-awake-setup-done && echo "SETUP_DONE" || echo "SETUP_NEEDED"
```

If `SETUP_DONE`, skip to Step 2a.

If `SETUP_NEEDED`, the user must run this **single command** in Mac Terminal. It is
fully idempotent (safe to run multiple times), handles authorized_keys, SSH config,
and caffeinate in one shot:

```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh && (grep -q 'AAAAC3NzaC1lZDI1NTE5AAAAIPDSohnQQkeFkl0ItZBRyA9hmBMPyZ11GzsYIOafWRAT' ~/.ssh/authorized_keys 2>/dev/null || echo 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPDSohnQQkeFkl0ItZBRyA9hmBMPyZ11GzsYIOafWRAT yike.li@getcruise.com' >> ~/.ssh/authorized_keys) && chmod 600 ~/.ssh/authorized_keys && (grep -q 'RemoteForward 2222' ~/.ssh/config 2>/dev/null || printf '\nHost cs-*\n    RemoteForward 2222 localhost:22\n' >> ~/.ssh/config) && echo "Done! Setup complete."
```

This command does three things:
1. Authorizes the Cruise Shell's SSH key (same key across all VMs via persistent home disk)
2. Adds `RemoteForward 2222 localhost:22` for all `Host cs-*` connections
3. Is permanent -- never needs to be re-run unless the Mac is wiped

The `Host cs-*` wildcard matches ALL Cruise Shell hostnames, so it works across VM
recreates. The SSH key is tied to `~/.ssh/id_ed25519` on the persistent home disk,
so it also survives VM recreates.

**Remote Login**: The Mac must have Remote Login enabled (System Settings > General >
Sharing > Remote Login). GM corporate Macs typically have this on by default.

### 2a. Detect Mac connectivity and establish tunnel

Try reverse tunnel first, then direct SSH, then create tunnel from Mac.

```bash
MAC_USER="KZFZ9H"
if nc -z -w 1 localhost 2222 2>/dev/null; then
  echo "Using reverse tunnel (localhost:2222)"
  MAC_SSH="ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no -p 2222 ${MAC_USER}@localhost"
elif nc -z -w 5 $(echo $SSH_CONNECTION | awk '{print $1}') 22 2>/dev/null; then
  MAC_IP=$(echo $SSH_CONNECTION | awk '{print $1}')
  echo "Using direct SSH to $MAC_IP"
  MAC_SSH="ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 -o BatchMode=yes -i ~/.ssh/id_ed25519 ${MAC_USER}@${MAC_IP}"
else
  echo "BOTH_PATHS_BLOCKED"
fi
```

**If reverse tunnel works**: proceed directly to Step 2b. This is the happy path.

**If direct SSH works but reverse tunnel didn't**: auto-fix the Mac's SSH config:

```bash
$MAC_SSH 'grep -q "RemoteForward 2222" ~/.ssh/config 2>/dev/null && echo "Reverse tunnel config: already present" || {
  printf "\nHost cs-*\n    RemoteForward 2222 localhost:22\n" >> ~/.ssh/config
  echo "Reverse tunnel config: ADDED"
}'
```

Then proceed to Step 2b.

**If BOTH paths are blocked** (GCP cannot route to VPN client IPs -- known limitation):

Check if the one-time Mac setup was previously completed:

```bash
test -f ~/.keep-awake-setup-done && echo "SETUP_DONE" || echo "SETUP_NEEDED"
```

**If `SETUP_DONE`**: The Mac has the SSH config and authorized_keys, but the current
Cursor SSH connection was established before `RemoteForward` was added to the config
(or this is a session where GCP routing blocks direct SSH). The fix is to create the
reverse tunnel manually from the Mac **without reconnecting Cursor**:

```bash
ssh -N -f -R 2222:localhost:22 -o StrictHostKeyChecking=no yike.li@CRUISE_SHELL_IP
```

Give the user this exact command with the Cruise Shell's IP filled in (from the Cruise
Shells bot status message or `hostname -I`). This creates a background SSH tunnel from
the Mac to the Cruise Shell with the reverse forward on port 2222. Flags: `-N` = no
remote command, `-f` = background after auth. The user's Cursor session is untouched.

After the user runs it, verify the tunnel:

```bash
nc -z -w 1 localhost 2222 && echo "Tunnel ACTIVE" || echo "Tunnel NOT YET ACTIVE"
```

Then proceed to Step 2b.

**If `SETUP_NEEDED`**: The one-time setup hasn't been done. Give the user the combined
setup + tunnel command for Mac Terminal:

```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh && (grep -q 'AAAAC3NzaC1lZDI1NTE5AAAAIPDSohnQQkeFkl0ItZBRyA9hmBMPyZ11GzsYIOafWRAT' ~/.ssh/authorized_keys 2>/dev/null || echo 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPDSohnQQkeFkl0ItZBRyA9hmBMPyZ11GzsYIOafWRAT yike.li@getcruise.com' >> ~/.ssh/authorized_keys) && chmod 600 ~/.ssh/authorized_keys && (grep -q 'RemoteForward 2222' ~/.ssh/config 2>/dev/null || printf '\nHost cs-*\n    RemoteForward 2222 localhost:22\n' >> ~/.ssh/config) && ssh -N -f -R 2222:localhost:22 -o StrictHostKeyChecking=no yike.li@CRUISE_SHELL_IP && echo "Done!"
```

Fill in CRUISE_SHELL_IP. This does the one-time setup AND creates the tunnel in one
command. No Cursor reconnect needed.

After the user runs it, verify the tunnel, then proceed to Step 2b.

**CRITICAL: Do NOT tell the user to "reconnect Cursor" or "reload window".** The
`ssh -N -f -R` command creates the tunnel immediately without disrupting anything.
Telling the user to reconnect is a passive 3.25 move.

### 2a-alt. Background watcher (start in parallel with user action)

While waiting for the user to run the Mac command (if needed), start a background
watcher that will detect the tunnel the instant it becomes available:

```bash
cat > /tmp/keep_awake_watcher.sh << 'SCRIPT'
#!/bin/bash
MAC_USER="KZFZ9H"
LOG="/tmp/keep_awake_watcher.log"
log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $1" >> "$LOG"; }
log "=== Keep Awake Watcher started ==="
while true; do
    if nc -z -w 1 localhost 2222 2>/dev/null; then
        MAC_SSH="ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no -p 2222 ${MAC_USER}@localhost"
        log "Reverse tunnel ACTIVE! Starting caffeinate..."
        RESULT=$($MAC_SSH 'kill $(pgrep caffeinate) 2>/dev/null; sleep 0.5; nohup caffeinate -dimsu -t 86400 </dev/null >/dev/null 2>&1 & echo "PID=$!"; sleep 0.5; pgrep -l caffeinate' 2>&1)
        if echo "$RESULT" | grep -q caffeinate; then
            log "caffeinate STARTED: $RESULT"
            echo "SUCCESS" > /tmp/keep_awake_watcher_status.txt
            exit 0
        fi
        log "caffeinate failed: $RESULT"
    fi
    MAC_IP=$(echo $SSH_CONNECTION | awk '{print $1}')
    if nc -z -w 3 $MAC_IP 22 2>/dev/null; then
        MAC_SSH="ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o BatchMode=yes -i ~/.ssh/id_ed25519 ${MAC_USER}@${MAC_IP}"
        log "Direct SSH reachable! Fixing config + starting caffeinate..."
        $MAC_SSH 'grep -q "RemoteForward 2222" ~/.ssh/config 2>/dev/null || printf "\nHost cs-*\n    RemoteForward 2222 localhost:22\n" >> ~/.ssh/config' 2>&1
        RESULT=$($MAC_SSH 'kill $(pgrep caffeinate) 2>/dev/null; sleep 0.5; nohup caffeinate -dimsu -t 86400 </dev/null >/dev/null 2>&1 & echo "PID=$!"; sleep 0.5; pgrep -l caffeinate' 2>&1)
        if echo "$RESULT" | grep -q caffeinate; then
            log "caffeinate STARTED via direct SSH: $RESULT"
            echo "SUCCESS" > /tmp/keep_awake_watcher_status.txt
            exit 0
        fi
    fi
    sleep 30
done
SCRIPT
chmod +x /tmp/keep_awake_watcher.sh
nohup bash /tmp/keep_awake_watcher.sh > /dev/null 2>&1 &
echo "Watcher PID: $!"
```

The watcher checks every 30 seconds and auto-starts caffeinate the moment either path
becomes available. It exits after success. Check status via:
```bash
cat /tmp/keep_awake_watcher.log
cat /tmp/keep_awake_watcher_status.txt 2>/dev/null
```

### 2b. Mark setup complete and start caffeinate

After ANY successful SSH to the Mac (reverse tunnel or direct), mark the one-time setup
as done so future invocations skip the setup prompt:

```bash
touch ~/.keep-awake-setup-done
```

Kill existing caffeinate and start fresh with 24-hour timer:

Always kill and restart. An existing caffeinate may have been started with an older/shorter
timer that could expire mid-session.

```bash
MAC_USER="KZFZ9H"
if nc -z -w 1 localhost 2222 2>/dev/null; then
  MAC_SSH="ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no -p 2222 ${MAC_USER}@localhost"
else
  MAC_IP=$(echo $SSH_CONNECTION | awk '{print $1}')
  MAC_SSH="ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 -i ~/.ssh/id_ed25519 ${MAC_USER}@${MAC_IP}"
fi
$MAC_SSH 'kill $(pgrep caffeinate) 2>/dev/null; sleep 0.5; nohup caffeinate -dimsu -t 86400 </dev/null >/dev/null 2>&1 & echo "caffeinate PID: $!"; sleep 0.5; pgrep -l caffeinate'
```

Flags: `-d` display, `-i` idle, `-m` disk, `-s` system, `-u` user activity.
Duration: 86400s = 24 hours.

### 2c. Verify Mac power and sleep state

```bash
MAC_USER="KZFZ9H"
if nc -z -w 1 localhost 2222 2>/dev/null; then
  MAC_SSH="ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no -p 2222 ${MAC_USER}@localhost"
else
  MAC_IP=$(echo $SSH_CONNECTION | awk '{print $1}')
  MAC_SSH="ssh -o ConnectTimeout=5 -i ~/.ssh/id_ed25519 ${MAC_USER}@${MAC_IP}"
fi
$MAC_SSH '
  echo "=== Power ===" && pmset -g ps | head -2
  echo "=== Sleep prevention ===" && pmset -g | grep "sleep "
'
```

**Required**: Output must show `AC Power` (not battery) and `sleep prevented by caffeinate`.
If on battery, warn the user to plug in.

## Step 3: Verify VPN health

(Can run in parallel with Steps 4 and 5)

```bash
MAC_USER="KZFZ9H"
if nc -z -w 1 localhost 2222 2>/dev/null; then
  MAC_SSH="ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no -p 2222 ${MAC_USER}@localhost"
else
  MAC_IP=$(echo $SSH_CONNECTION | awk '{print $1}')
  MAC_SSH="ssh -o ConnectTimeout=5 -i ~/.ssh/id_ed25519 ${MAC_USER}@${MAC_IP}"
fi
$MAC_SSH '
  echo "=== VPN process uptime ===" && ps -eo pid,lstart,etime,comm | grep vpnagentd | grep -v grep
  echo "=== AutoReconnect config ===" && grep -A1 "AutoReconnect" /opt/cisco/secureclient/vpn/profile/GM-Cruise.xml 2>/dev/null
'
```

The VPN is Cisco Secure Client (not GlobalProtect). Key config:
- `AutoReconnect: true` -- recovers from brief network interruptions
- `DisconnectOnSuspend` -- disconnects on Mac sleep (neutralized by caffeinate)
- No client-side session timeout -- server-side timeout is long (proven 2+ day uptime)

## Step 4: Set up tmux (optional)

(Can run in parallel with Steps 3 and 5)

For terminal processes that should survive a brief SSH reconnect:

```bash
tmux has-session -t overnight 2>/dev/null \
  && echo "tmux session 'overnight' already exists" \
  || tmux new-session -d -s overnight
```

Note: Cursor agent state CANNOT be recovered after SSH disconnect. tmux only preserves
terminal processes, not the Cursor agent conversation.

## Step 5: Verify auth credentials

(Can run in parallel with Steps 3 and 4)

```bash
TOKEN=$(gcloud auth application-default print-access-token 2>&1 | head -1)
if [[ "$TOKEN" == ya29.* ]]; then echo "gcloud: OK"; else echo "gcloud: EXPIRED"; fi

echo "---"
authcli status 2>&1 | head -30 || true
```

Note: pipe `authcli status` through `|| true` to avoid SIGPIPE exit code 141 from `head`.

If Cruise User Credentials or gcloud are expired, follow the `cruise-auth-refresh` skill.
If only non-critical app tokens are expired, note them but don't block on them.

## Summary checklist

Report to the user after all steps complete:

- [ ] **Keep Alive**: Active (report expiry date -- max is 3 days)
- [ ] **Reverse tunnel**: Active on port 2222 (or watcher running if pending)
- [ ] **caffeinate**: Running on Mac via reverse SSH (PID confirmed, 24-hour timer)
- [ ] **Mac power**: On AC power, sleep prevented
- [ ] **VPN health**: Cisco Secure Client up, AutoReconnect enabled
- [ ] **tmux**: Session created (optional)
- [ ] **Auth**: gcloud and Cruise User Credentials valid (note any expired app tokens)
- [ ] **Setup marker**: `~/.keep-awake-setup-done` exists (future runs skip setup prompt)

## Troubleshooting

### Chrome not installed (Playwright fails immediately)

Error: `Chromium distribution 'chrome' is not found at /opt/google/chrome/chrome`

Run `npx playwright install chrome`. This downloads and installs Chrome (~60-90s). Use
`block_until_ms: 120000` to prevent premature backgrounding. Step 1b now includes this
check automatically.

### Browser locked ("Browser is already in use")

Error: `Browser is already in use for .../mcp-chrome-..., use --isolated`

A prior Playwright session crashed or was interrupted. Fix:

```bash
pkill -f "chrome.*playwright" 2>/dev/null
rm -f /home/yike.li/.cache/ms-playwright/mcp-chrome-*/SingletonLock 2>/dev/null
```

Then retry `browser_navigate`. Step 1b now includes this cleanup automatically.

### Keep Alive Playwright fails

1. **Already at max**: The combobox text shows a date 2-3 days in the future. The dropdown
   won't open because Keep Alive is already at the maximum. This is fine -- skip it.
2. **No combobox found**: The status message may not have loaded. Send `status` to the bot
   DM again via Slack MCP, wait 5s, then re-navigate Playwright.
3. **Multiple comboboxes**: The DM history contains many status messages, each with its
   own Keep Alive combobox. DO NOT use `document.querySelector('[role="combobox"]')` --
   it returns the first (oldest) one. Instead, find the correct combobox ref from the
   Playwright snapshot by searching for the machine name inside `listitem` labels.
4. **Dropdown opens but option click has no effect**: If the React fiber key suffix
   changed (page reload), take a fresh snapshot and re-query `__reactProps$`.
5. **None of the fallback approaches open the dropdown**: If the combobox shows any future
   date, Keep Alive is active. Report the date and move on. Only escalate if the date is
   in the past or missing entirely.

### Reverse tunnel not available (port 2222 closed)

1. **SSH config missing + direct SSH works**: Auto-fix it (see Step 2a). Do NOT tell
   the user to run the command manually.
2. **SSH config missing + direct SSH blocked**: Have the user run the combined setup +
   tunnel command from Step 2a. This does the one-time config AND creates the tunnel
   in a single paste. No Cursor reconnect needed.
3. **Config present but tunnel not active**: The current Cursor SSH session was
   established before `RemoteForward` was in the config. Have the user create the
   tunnel directly: `ssh -N -f -R 2222:localhost:22 -o StrictHostKeyChecking=no yike.li@CRUISE_SHELL_IP`.
   Do NOT tell the user to reconnect Cursor -- that's disruptive and unnecessary.
4. **Cursor reconnected but tunnel didn't start**: Verify the config was written
   correctly by SSHing to the Mac and running `grep RemoteForward ~/.ssh/config`.
5. **Port 2222 already in use on Cruise Shell**: Another process is using the port.
   Change to a different port (e.g., 2223) in both the SSH config and the skill commands.

### Direct SSH to Mac fails (fallback path)

1. **Connection timed out**: GCP Cruise Shells cannot route to VPN client IPs (10.249.x.x,
   10.252.x.x). This is a known network limitation since ~March 2026. **Do NOT give up.**
   Fall back to the `ssh -N -f -R` approach: have the user create the tunnel from their
   Mac (see Step 2a). Start the background watcher (Step 2a-alt) in parallel.
2. **Permission denied**: The Cruise Shell's pubkey isn't in Mac's `~/.ssh/authorized_keys`.
   Give the user the one-time setup command from Step 2 (it includes authorized_keys +
   SSH config + tunnel creation in a single paste).
3. **Connection refused**: Mac doesn't have Remote Login enabled.
   Tell user: System Settings > General > Sharing > Remote Login > ON.
4. **Wrong username**: GM corporate Macs use a short ID (e.g. `KZFZ9H`), not the Cruise
   Shell username. Detect by trying common patterns or asking the user for `whoami` output.

### Both paths blocked -- decision tree

When BOTH reverse tunnel and direct SSH fail, follow this decision tree:

```
Is ~/.keep-awake-setup-done present?
├── YES: One-time setup was done before.
│   Give user SHORT command (just the tunnel, ~30 chars):
│   ssh -N -f -R 2222:localhost:22 -o StrictHostKeyChecking=no yike.li@<IP>
│   Start background watcher in parallel.
│
└── NO: First time ever.
    Give user FULL command (setup + tunnel, single paste):
    mkdir -p ~/.ssh && chmod 700 ~/.ssh && ... && ssh -N -f -R ...
    Start background watcher in parallel.
```

**NEVER say "skip caffeinate" or "will self-heal next session."** Always provide the
user with an actionable command and start the background watcher.

### caffeinate dies mid-session

If caffeinate terminates (e.g., another process kills it), the Mac can sleep and VPN drops.
To guard against this, you can start caffeinate with `while true` loop:

```bash
MAC_USER="KZFZ9H"
if nc -z -w 1 localhost 2222 2>/dev/null; then
  MAC_SSH="ssh -o ConnectTimeout=5 -p 2222 ${MAC_USER}@localhost"
else
  MAC_IP=$(echo $SSH_CONNECTION | awk '{print $1}')
  MAC_SSH="ssh -o ConnectTimeout=5 -i ~/.ssh/id_ed25519 ${MAC_USER}@${MAC_IP}"
fi
$MAC_SSH 'nohup bash -c "while true; do caffeinate -dimsu -t 3600; done" </dev/null >/dev/null 2>&1 &'
```

This restarts caffeinate every hour indefinitely.
