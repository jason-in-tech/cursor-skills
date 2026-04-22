# Automated Cruise Auth Refresh

Fully automates `authcli refresh` including the Google → Okta → Microsoft SSO → Duo
browser flow. Requires user interaction only for Microsoft MFA number matching.

## Prerequisites

1. **Secret file** at `~/.cruise-google-creds` (mode 600), JSON format:
   ```json
   {
     "email": "user@gm.com",
     "password": "<okta_password>",
     "ms_password": "<microsoft_ad_password>",
     "gcp_email": "user@getcruise.com"
   }
   ```
   | Field | Used for | Required |
   |-------|----------|----------|
   | `email` | Okta login (cruise.okta.com) | Yes |
   | `password` | Okta password | Yes |
   | `ms_password` | Microsoft Azure AD password (login.microsoftonline.com). Falls back to `password` if absent. | Recommended |
   | `gcp_email` | Google account for GCP re-auth (accounts.google.com). Falls back to `email` if absent. | Recommended |

   If this file does not exist, tell the user to create it and STOP.

2. **Playwright + xvfb** installed:
   ```bash
   cd ~/.cursor/scripts && npm install playwright
   npx playwright install-deps chromium
   sudo apt-get install -y xvfb   # for headed mode on headless VMs
   ```
   Playwright is installed in `~/.cursor/scripts/node_modules/`.
   Google blocks headless Chrome; `xvfb` lets us run headed mode on a headless VM.

3. **Scripts** at `~/.cursor/scripts/`:
   - `cruise-auth-refresh.exp` — expect script that drives `authcli refresh`
   - `cruise-auth-browser.mjs` — Playwright script that completes the SSO flow

## When to Trigger

- `gcloud auth application-default print-access-token` returns "Reauthentication" or error
- `authcli status` shows any credential as non-VALID
- Any command fails with `401`, `credentials`, `Permission denied`, `RefreshError`,
  `Reauthentication`, `access token`, or `insufficient authentication scopes`
- Google Drive/Docs API returns `403 insufficient scopes` (use `gcloud-adc` mode)

**Other skills/workflows should call this skill** whenever they detect auth-related errors
rather than asking the user to re-auth manually. See "Cross-Referencing from Other Skills"
at the bottom.

## Auth Flow Architecture

There are two distinct flows depending on what `authcli refresh` needs:

### GCP re-auth flow (most common after hours of inactivity)

```
authcli refresh -no-launch-browser -re-auth gcp
  → prints Google OAuth URL (accounts.google.com)

Browser automation (xvfb + Playwright):
  1. Navigate to Google OAuth URL
  2. Fill GCP email (gcp_email) → Next
  3. Google redirects to Okta SAML (cruise.okta.com)
  4. Okta auto-submits or fills email → redirects to Microsoft SSO
  5. Fill Microsoft password (ms_password) on login.microsoftonline.com
  6. Handle "Stay signed in?" → Yes
  7. ★ Microsoft MFA: display 2-digit number for user to enter in Authenticator
  8. Okta redirects to Duo Security (duosecurity.com)
  9. Auto-click "Skip for now" on Duo Desktop check
  10. Duo auto-approves (no user action if device is remembered)
  11. Google consent: auto-click "Continue" (may need 2 clicks)
  12. Extract auth code from sdk.cloud.google.com/authcode.html

Expect script reads code and feeds it to authcli stdin.
```

### App re-auth flow (Okta SSO)

```
authcli refresh -no-launch-browser [-re-auth all]
  → prints Okta OAuth URL (cruise.okta.com)

Browser automation:
  1-6. Same Okta → Microsoft → MFA → Duo flow as above
  7. Redirected to iop.robot.car/cli_callback?code=...
  8. Extract code from callback URL
```

### What requires user interaction

| Step | Automated? | User action needed |
|------|------------|-------------------|
| Google email/password | Yes | None |
| Okta email | Yes | None |
| Microsoft password | Yes | None |
| Microsoft MFA (number matching) | Partially | **Enter displayed number in Authenticator app** |
| Duo Security | Yes (Skip + auto-approve) | None |
| Google consent | Yes | None |

**Microsoft MFA is the only step requiring user action.** The script displays the 2-digit
number in the terminal output. The operator (human or AI agent) must read this number and
tell the user to enter it in their Microsoft Authenticator app.

## Flow

### Step 0: Check if refresh is actually needed

```bash
authcli status 2>&1
```

If ALL rows show `VALID`, auth is fine. Skip the rest.

### Step 1: Read credentials from secret file

```bash
cat ~/.cruise-google-creds
```

Parse the JSON. Store in memory for later.

### Step 2: Start expect script in background

```bash
~/.cursor/scripts/cruise-auth-refresh.exp
```

Run in a **background terminal** (`block_until_ms: 0`). The expect script will:
- Spawn `authcli refresh -no-launch-browser`
- Auto-answer "y" to prompts
- Write the OAuth URL to `/tmp/cruise-auth-url.txt`
- Wait up to 960 seconds for the code at `/tmp/cruise-auth-code.txt`

To force re-authentication (even when tokens are valid):
```bash
~/.cursor/scripts/cruise-auth-refresh.exp gcp        # GCP only
~/.cursor/scripts/cruise-auth-refresh.exp all         # all tokens
~/.cursor/scripts/cruise-auth-refresh.exp gcloud-adc  # GCP ADC with Drive/Docs/Sheets scopes
```

The `gcloud-adc` mode runs `gcloud auth application-default login` with Drive, Docs,
Sheets, and Cloud Platform scopes. Use this when publishing Google Docs or accessing
Drive API. The browser flow is identical to GCP re-auth.

### Step 3: Poll for the OAuth URL

Check `/tmp/cruise-auth-status.txt` every 5 seconds:
- `STARTED` → still initializing
- `URL_CAPTURED` → URL is ready at `/tmp/cruise-auth-url.txt`
- `WAITING_FOR_CODE` → URL captured AND verification code prompt reached
- `SUCCESS` → auth refreshed silently (no browser needed). Done!
- `FAILED:*` → authcli failed. Check the terminal output.

If `SUCCESS` appears without `URL_CAPTURED`, skip browser steps.

### Step 4: Run Playwright browser automation via xvfb

**IMPORTANT**: Must use `xvfb-run` for headed mode. Google blocks headless Chrome.

```bash
cd ~/.cursor/scripts && \
  XVFB=1 xvfb-run --auto-servernum --server-args="-screen 0 1280x1024x24" \
  node cruise-auth-browser.mjs 2>&1
```

Run in a **background terminal** (`block_until_ms: 0`) so you can monitor output.

The script will:
1. Read credentials from `~/.cruise-google-creds`
2. Read the OAuth URL from `/tmp/cruise-auth-url.txt`
3. Navigate through Google → Okta → Microsoft → MFA → Duo → consent
4. Write screenshots to `/tmp/cruise-auth-*.png` at each step
5. Extract the authorization code and write to `/tmp/cruise-auth-code.txt`

Exit codes:
- 0: Success, code written
- 1: General error
- 2: Account locked or wrong password
- 3: MFA/Duo timeout (user didn't approve in 900s)
- 4: Timeout waiting for final redirect

### Step 4a: Handle Microsoft MFA

When the script reaches Microsoft MFA, it prints the number to the terminal:

```
========================================
  MFA NUMBER: 78
  Enter this in Microsoft Authenticator
========================================
```

**You MUST monitor the browser terminal output** for this number and immediately tell
the user to enter it in their Microsoft Authenticator app. The MFA times out after 900s (15 minutes).

To find the number:
1. Read the browser terminal output file
2. Look for `MFA NUMBER:` in the output
3. Also check the screenshot at `/tmp/cruise-auth-05-mfa-page.png`

After the user approves MFA, the script automatically handles Duo and Google consent.

### Step 5: Wait for expect script to complete

Poll `/tmp/cruise-auth-status.txt`:
- `CODE_SENT` → expect sent the code to authcli
- `SUCCESS` → done! Auth refreshed.
- `FAILED:*` → something went wrong after code submission

### Step 6: Verify

```bash
authcli status 2>&1
gcloud auth application-default print-access-token 2>&1 | head -1
```

Both should show valid credentials.

### Fallback: Manual completion

If browser automation fails (account lockout, repeated MFA timeout, CAPTCHA):

1. Read `/tmp/cruise-auth-url.txt` and print the OAuth URL for the user
2. Tell the user: "Please open this URL in your browser and complete sign-in.
   Then paste the verification code here."
3. When the user provides the code, write it to `/tmp/cruise-auth-code.txt`
4. The expect script will pick it up and feed it to authcli
5. Verify with `authcli status`

## SSO Flow Details

The SSO flow goes through multiple identity providers:

1. **Google** (`accounts.google.com`): GCP OAuth, accepts `gcp_email`. For managed accounts,
   redirects to SAML/Okta.
2. **Okta** (`cruise.okta.com`): Cruise's IdP, accepts `email`. Auto-redirects to Microsoft.
3. **Microsoft Azure AD** (`login.microsoftonline.com`): GM's corporate SSO, accepts
   `ms_password`. The Okta email maps to an internal GM account
   (e.g., `user@gm.com` → `xxxxx@nam.corp.gm.com`).
4. **Microsoft MFA**: Number matching via Microsoft Authenticator app. Required on
   unrecognized devices (Linux VMs). Not required on enrolled devices (e.g., your MacBook).
5. **Duo Security** (`duosecurity.com`): Cruise's second factor. "Skip for now" bypasses
   the Desktop check; auto-approves if device was previously remembered.
6. **Google Consent** (`accounts.google.com/signin/oauth/id`): May require clicking
   "Continue" once or twice. Grants Google Cloud SDK access.
7. **Callback**: `iop.robot.car/cli_callback?code=...` (Okta flow) or
   `sdk.cloud.google.com/authcode.html` (Google flow). Code is extracted from URL/page.

## Why MFA is required every time on Linux VMs

Microsoft's **Conditional Access Policies** trigger MFA based on device enrollment.
Your MacBook is enrolled as a trusted device (via Company Portal / Intune), so MFA is
skipped there. A Linux VM is not enrolled and cannot be — Microsoft requires MFA
**every single time** on unmanaged devices. The persistent browser profile
(`~/.cruise-browser-profile`) caches cookies/sessions for Okta and Duo (reducing their
prompts), but **cannot bypass Microsoft MFA**. Plan for MFA on every auth refresh.

## Cleanup / Reset

To clear all state and start fresh:
```bash
rm -rf ~/.cruise-browser-profile
rm -f /tmp/cruise-auth-url.txt /tmp/cruise-auth-code.txt /tmp/cruise-auth-status.txt /tmp/cruise-auth-*.png
```

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `~/.cruise-google-creds` missing | First-time setup | Tell user to create it |
| Playwright not installed | Missing npm package | `cd ~/.cursor/scripts && npm install playwright` |
| `libatk-1.0.so.0: cannot open` | Missing system deps | `npx playwright install-deps chromium` |
| `xvfb-run: not found` | Missing xvfb | `sudo apt-get install -y xvfb` |
| Google "Couldn't sign you in" | Headless browser detected | Must use `xvfb-run` for headed mode |
| Google "Couldn't find your Google Account" | Wrong email for GCP | Set `gcp_email` in creds file |
| Account temporarily locked | Wrong Microsoft password | Wait 15-30 min; update `ms_password` in creds |
| MFA timeout | User didn't enter number in time | Retry; tell user the number immediately |
| Duo "Skip for now" not clicked | Timing issue (page loads after check) | Fixed: script retries in wait loop |
| Google consent "Continue" not clicked | Multiple consent pages | Fixed: polling loop clicks Continue |
| `Execution context was destroyed` | Navigation race during rapid redirects | Fixed: caught and recovered |
| Script exits with code 3 | MFA or Duo timeout (900s) | Retry; ensure user has Authenticator ready |

## Autonomy

- Steps 0-6: fully autonomous except for MFA number relay
- MFA step: **read the number from terminal output, tell the user immediately**
- Duo: fully automatic (no user action)
- Google consent: fully automatic
- Fallback: tell user what happened and ask for the verification code
- NEVER ask the user to run `authcli refresh` themselves -- always use the expect script

## Cross-Referencing from Other Skills

Any skill or workflow that runs cloud commands (BQ queries, `bazel run` with cloud targets,
`gcloud` commands, Roboflow submissions) should check for auth errors and invoke this skill.

To reference this skill from another SKILL.md, add to your pre-flight section:

```markdown
## Pre-flight: Authentication

Before running cloud commands, check auth:

```bash
gcloud auth application-default print-access-token 2>&1 | head -1
```

**If expired**: Follow the `cruise-auth-refresh` skill (`~/.cursor/skills/cruise-auth-refresh/SKILL.md`).
This automates the full SSO flow. Only requires user interaction for Microsoft MFA number matching.
```

Skills that already reference this:
- `nvidia-featurization` (Section 0: Pre-flight Authentication)
- `trino-lakehouse` (Pre-flight: Authentication + Gotchas)
- `write-technical-report` (Pre-flight: Authentication)