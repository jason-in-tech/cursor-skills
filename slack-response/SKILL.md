---
name: slack-response
description: >-
  Unified Slack assistant. Monitor mode: poll every 10 minutes for messages
  pending your response across DMs, group chats, and channel @mentions,
  classify by intent, and draft replies. Thread mode: read a Slack thread or
  channel from a URL or name, summarize, and help draft a response. Can view
  Slack file attachments (images, screenshots) via browser automation. Use when
  the user says "check DMs", "check slack", "monitor slack", "pending messages",
  "slack inbox", pastes a Slack URL, asks "what's happening in #channel",
  "catch me up", or wants help replying to a Slack conversation.
---

# Slack Response

Two modes depending on user input:

- **Monitor** — poll for pending messages, classify, draft replies (triggered by "check DMs", "monitor slack", "slack inbox", etc.)
- **Thread/Channel** — read a specific thread or channel, summarize, help draft a reply (triggered by a Slack URL, channel name, or "catch me up on #channel")

## MCP Servers

| Domain | MCP server |
|--------|------------|
| gm-sns.slack.com | `user-slack-ss` |
| all-gm.slack.com | `user-slack-all-company` |

Default: `user-slack-ss`. For Thread/Channel mode, pick server by URL domain.

## Mode Detection

| User input | Mode |
|------------|------|
| Slack URL (contains `archives/`) | Thread/Channel |
| Channel/group name ("what's happening in #team-x") | Thread/Channel |
| "catch me up", "what did I miss" with a channel reference | Thread/Channel |
| "check DMs", "slack inbox", "pending messages", "monitor slack" | Monitor |
| "any new messages", "what needs my attention" | Monitor |

---

# Monitor Mode

Poll for messages awaiting response. Runs a **10-minute polling loop** until user says "stop".

## M1: Time Window

First poll: last 24 hours (or user-specified). Subsequent polls: last 10 minutes.

```bash
date -d '24 hours ago' +%s   # first poll
date -d '10 minutes ago' +%s  # subsequent polls
```

## M2: Search

Run **three parallel searches** via `slack_search_public_and_private`:

| Search | `channel_types` |
|--------|----------------|
| DMs | `im` |
| Group DMs | `mpim` |
| Channel @mentions | `public_channel,private_channel` |

All three use: `query: "to:me"`, `sort: "timestamp"`, `sort_dir: "desc"`, `after: $OLDEST_TS`, `limit: 20`, `include_context: false`.

## M3: Check Reply Status

For each result, determine if the user already replied **or reacted**.

A conversation is considered **acknowledged** (skip) if the user has done ANY of:
- Sent a text message after the other person's last message
- Added an emoji reaction (e.g. 👍, ✅, 🎉, any reacji) to the other person's last message

Use `response_format: "detailed"` when reading channels in this step — the detailed format includes emoji reactions on messages. Look for the user's display name or user_id in reaction lists.

**DMs**: `slack_read_channel` with sender's user_id as channel_id, limit 5.
- Last message from them AND no reply or reaction from user → pending.
- User sent a message after theirs, OR user reacted to their last message → skip.

**Group DMs**: `slack_read_channel` with channel_id, limit 10.
- User sent a message after the one tagging them, OR user reacted to it → skip. Otherwise → pending.

**Channel @mentions**: `slack_read_thread` if in a thread, else `slack_read_channel`.
- User replied after the mention, OR user reacted to it → skip. Otherwise → pending.

Dedup: same person across searches → keep most recent only.

## M4: Summarize Pending Items

For each pending conversation from M3, fetch context and summarize:

**DMs / Group DMs**: use the messages already fetched in M3 (limit 5-10). If the conversation is long or has threads, fetch more with `slack_read_thread`.

**Channel @mentions**: use `slack_read_thread` to get the full thread context.

For each pending item, produce a **detailed context block**:
- **Topic**: what the conversation is about (one sentence)
- **Key participants**: who's involved
- **Full context**: quote or closely paraphrase the key messages so the user can understand the conversation without opening Slack. Include timestamps and who said what. For short conversations (< 5 messages), include all messages. For longer ones, include the most recent 5-8 messages plus any earlier messages that are critical for understanding.
- **Current state**: what's been decided, what's open, any blockers
- **What they need from you**: the specific question, request, or action item

Summaries should be **thorough enough that the user can draft a reply without leaving the terminal**. Don't compress away useful detail — err on the side of including too much context rather than too little.

**Attachments**: If pending messages have `Files:` in the output, view relevant ones using the **Viewing Attachments** workflow (A1-A5) and include a description of the image content in the context block. This is especially important when the attachment IS the message (e.g., a screenshot of an error with minimal text).

## M5: Classify Intent

### URGENT

- Deadline language: "by EOD", "ASAP", "urgent", "today", "blocking"
- 2+ unreplied messages from same person
- Escalation: "following up", "bumping", "ping", "circling back"

### NEEDS RESPONSE

- Questions: "?", "thoughts?", "WDYT", "what do you think"
- Requests: "can you", "please", "could you"
- Review: "PTAL", "please review", "take a look"
- Decisions: "should we", "which option"
- Blocked: "waiting on you", "need your input"

### FYI ONLY

- Acknowledgments: "thanks", "got it", "sounds good", "LGTM"
- Announcements with no question
- Bot/automated messages

When ambiguous, default to NEEDS RESPONSE.

## M6: Present

Use this layout. Adapt sections based on what's present (omit empty categories).

```
# Slack Inbox
_[N] conversations · [N] need reply · [Day, Month DD, HH:MM AM/PM]_

---

### 🔴 Urgent

**1. [Person]** · [DM / #channel / Group DM] · [time ago]

**Context:**
> [Quoted/paraphrased messages with timestamps and authors, enough to understand the full conversation]

**State:** [what's decided / open / blocking]
**Ask:** [what they need from you]

**Suggested reply:**
```
[reply text, ready to copy/paste]
```

---

### 💬 Needs Response

**2. [Person]** · [DM / #channel / Group DM] · [time ago]

**Context:**
> [Quoted/paraphrased messages with timestamps and authors]

**Ask:** [what they need from you]

**Suggested reply:**
```
[reply text, ready to copy/paste]
```

---

### 📋 FYI

| Who | Where | Note |
|-----|-------|------|
| [Person] | [DM / #channel] | [brief note] |

---

`edit 1: [text]` · `dismiss 1` · `skip` · `stop`
```

**Section rules:**
- Urgent: full context block with quoted messages, state, and ask. Always include suggested reply in a code block for easy copy/paste.
- Needs Response: full context block with quoted messages and ask. Always include suggested reply in a code block.
- FYI: table row, one line each. No reply needed.
- Omit any section that has zero items (don't show empty headers).
- Numbering is sequential across Urgent + Needs Response (FYI items are unnumbered).
- All suggested replies go in fenced code blocks (```) so the user can copy/paste directly to Slack.
- **Carried-over items**: For items that persisted from a previous poll, append `(pending X min)` or `(pending X hrs)` to the time-ago field. Re-display the full context block and suggested reply each cycle — don't abbreviate on repeat appearances. Items pending 1+ hours auto-escalate: NEEDS RESPONSE → URGENT.

## M7: Poll Loop

The poll loop starts **automatically** after the first presentation (M6). Do NOT wait for user action before entering the loop.

### Keeping the loop alive (foreground blocking sleep)

To avoid requiring user intervention between polls, run the sleep as a **foreground blocking command** with `block_until_ms` set higher than the sleep duration. This keeps the assistant's turn alive so it can auto-continue when the sleep completes.

```
Shell(command="sleep 600", block_until_ms=630000)
```

This blocks for ~10 minutes, then the assistant regains control and runs the next poll cycle — no user input needed.

### Persistent Pending List

Maintain an in-memory list of **pending conversations** across poll cycles. Each entry is `(channel_id, last_message_ts, person, classification)`.

A conversation is removed from the pending list ONLY when:
- The user **replies** in Slack (detected via M3 reply-status check)
- The user **reacts** to the message in Slack (detected via M3 reaction check)
- The user says **`dismiss N`** to explicitly remove item N from the list

Conversations that remain unanswered **carry forward** and are re-displayed every poll cycle until resolved. This ensures nothing slips through the cracks.

### Loop steps

1. Present first results (M6)
2. Run `sleep 600` as a **foreground** call with `block_until_ms: 630000`
3. When sleep completes:
   a. Search for **new messages** with `date -d '10 minutes ago' +%s` as the time window (M2)
   b. **Re-check reply status** (M3) for ALL items on the persistent pending list — the user may have replied in Slack since the last poll
   c. Remove any items from the pending list that are now acknowledged (replied or reacted)
   d. Add any new pending items discovered in step (a)
4. Present **all currently-pending items** (carried-over + new). Mark carried-over items with how long they've been pending (e.g., "pending 30 min", "pending 2 hrs").
5. Loop back to step 2

Print on each cycle: `--- Poll [N] at [HH:MM] — checking for new messages... ---`

If nothing pending (list empty and no new items): `Nothing pending — next check in 10 minutes.`

**State tracking**: maintain the persistent pending list as described above. Also track `(channel_id, message_ts)` tuples already surfaced to detect new activity on known conversations.

**Stop**: user says "stop", "pause", or "done monitoring".

**User input mid-loop**: When the user sends a message during the poll loop (e.g., "edit 1: [text]", a follow-up question, or any other input that is NOT "stop"/"pause"/"done monitoring"), handle the request immediately, then **resume the polling loop** by starting a new `sleep 600` cycle. Do NOT wait for the user to re-trigger monitoring — the loop continues automatically after every user interaction.

**Note**: M4 (Summarize) adds MCP calls per pending item. To keep polls fast, batch `slack_read_thread` / `slack_read_channel` calls in parallel where possible.

---

# Thread/Channel Mode

Read a specific Slack thread or channel, summarize, and help draft a reply.

## T1: Parse Input

### From a Slack URL

Extract from `archives/<channel_id>/p<timestamp>`:
- `channel_id`: the segment after `archives/`
- `message_ts`: convert `p1771353881877769` → `1771353881.877769` (insert dot 6 digits from end)

Pick MCP server by domain:
- `gm-sns.slack.com` → `user-slack-ss`
- `all-gm.slack.com` → `user-slack-all-company`

### From a channel/group name (no URL)

```
slack_search_channels(query="<name>", channel_types="public_channel,private_channel")
```

Try both MCP servers if unsure which workspace.

## T2: Determine Focus

**Thread-focused** (reply to, understand, respond, "what are they asking"):
```
slack_read_thread(channel_id, message_ts)
```

**Channel-focused** (catch up, "what did I miss", "summarize channel"):
```
slack_read_channel(channel_id, limit=50)
```

If ambiguous: thread-focused when URL points to a message with replies; channel-focused when phrasing mentions "channel" or "group chat".

Use `response_format: "concise"` for long content, then `"detailed"` selectively.

## T3: Summarize + Suggest Reply

**Thread**:
- Topic (one sentence)
- Key participants
- **Full message log**: quote or closely paraphrase each message with author and timestamp. For short threads (< 10 messages), include all. For longer ones, include the first message, any critical context messages, and the most recent 5-8 messages.
- **Attachments**: If any messages have `Files:` in the output, view them using the **Viewing Attachments** workflow (A1-A5) and describe what they show inline with the message log.
- Current state: decided, open, being asked
- What needs a response from the user
- **Suggested reply** in a fenced code block for copy/paste

**Channel**:
- Recent topics (grouped by conversation, not chronological)
- Key threads with significant discussion — include quoted excerpts, not just one-line summaries
- **Attachments**: View images/screenshots that appear relevant to the conversation context. Skip decorative files (emoji GIFs, memes) unless they're the point of the message.
- Action items / open questions for the user
- For each item needing a response: **Suggested reply** in a fenced code block
- Offer: "Want me to read any of these threads in full?"

Always provide a suggested reply in a code block for anything that looks like it needs a response. If the user confirms the draft ("looks good", "draft it", etc.), attach it as a Slack draft per **Shared: Actions → Creating Drafts**. Otherwise the user copy/pastes manually.

---

# Shared: Viewing Attachments

When a Slack message contains files/images (indicated by `Files:` in `slack_read_thread` / `slack_read_channel` output), use this procedure to view them. This requires the `user-playwright` MCP server.

## A1: Find the File ID

Search for the file using `slack_search_public_and_private` (not `slack_search_public`) to cover private channels and DMs:

```
slack_search_public_and_private(
  query="from:<@USER_ID> in:<#CHANNEL_ID> type:images",
  content_types="files",
  sort="timestamp",
  sort_dir="desc",
  limit=5
)
```

The result includes the file ID (e.g., `F0AQ97YL95E`) in the permalink URL: `.../files/USER_ID/FILE_ID/filename.png`

**Fallback**: If `type:images` returns nothing, retry without the type filter. For non-image files (PDFs, docs), the same flow works but the screenshot may show a download page instead of rendered content.

## A2: Establish Authenticated Slack Session

Navigate to `app.slack.com` to establish an authenticated session. The browser inherits SSO cookies so no manual login is needed.

```
browser_navigate(url="https://app.slack.com")
browser_wait_for(time=5)
browser_snapshot()
```

**Verify success**: The snapshot should show Slack UI elements (sidebar, channels, messages). If the page title contains "Sign in" or the snapshot shows SSO/login buttons, SSO cookies have expired. Fall back to telling the user: "Slack browser session expired — open app.slack.com in a browser first, then retry."

**Session reuse**: Once established, the session persists across calls in the same conversation. Skip A2 on subsequent files — but see A4 domain warning.

## A3: Extract API Token

Extract the `xoxc-` token from the Slack web client's localStorage:

```
browser_evaluate(function="() => {
  const val = localStorage.getItem('localConfig_v2');
  const match = val && val.match(/xoxc-[a-zA-Z0-9._-]+/);
  return match ? match[0] : null;
}")
```

**Cache the token** for the rest of the conversation. Only re-extract if a subsequent API call returns `invalid_auth`.

## A4: Get Private File URL

**CRITICAL**: The `fetch('/api/files.info')` call uses a **relative URL**. The browser MUST be on `app.slack.com` when this runs. If you previously navigated to `files.slack.com` (e.g., to view an earlier image in A5), navigate back first:

```
browser_navigate(url="https://app.slack.com")
browser_wait_for(time=3)
```

Then call the Slack `files.info` API:

```
browser_evaluate(function="async () => {
  const resp = await fetch('/api/files.info', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: 'token=TOKEN&file=FILE_ID',
    credentials: 'include'
  });
  const data = await resp.json();
  return {
    ok: data.ok,
    url_private: data.file?.url_private,
    thumb_720: data.file?.thumb_720,
    thumb_480: data.file?.thumb_480,
    mimetype: data.file?.mimetype,
    filetype: data.file?.filetype,
    name: data.file?.name,
    error: data.error
  };
}")
```

Replace `TOKEN` with the cached token and `FILE_ID` with the file ID from A1.

If the response returns `{ok: false, error: "invalid_auth"}`, re-extract the token (A3) and retry.

## A5: View the Image

Navigate to `url_private` (the full-resolution image) and take a screenshot:

```
browser_navigate(url="<url_private from A4>")
browser_take_screenshot(type="png")
```

The browser's cookies authenticate the request to `files.slack.com`. The screenshot renders the image visually so you can describe its contents to the user.

For thumbnails (faster load), use `thumb_720` or `thumb_480` instead of `url_private`.

## A6: Describe to User

After viewing the screenshot, describe the image contents in your summary. Include:
- What the image shows (UI screenshot, error message, chart, diagram, etc.)
- Any text visible in the image
- How it relates to the message context

## When to View vs Skip

**Always view** (the attachment IS the message or is critical context):
- Screenshots of errors, UIs, dashboards, terminals
- Charts, graphs, diagrams
- Code screenshots
- Messages where `Files:` is present but the text is minimal/cryptic (the image explains the message)

**Skip** (not worth the browser round-trip):
- Emoji GIFs, memes, stickers (unless that's clearly the point the user is asking about)
- Profile pictures, avatars
- Files you can identify by name as irrelevant (e.g., `giphy.gif`)
- Messages where the text already fully explains the context and the file is supplementary

When in doubt, view it. A few extra seconds is better than missing context.

## Attachment Quick Reference

| Step | Tool | Purpose |
|------|------|---------|
| A1 | `slack_search_public_and_private` | Find file ID |
| A2 | `browser_navigate` | Establish auth session (once) |
| A3 | `browser_evaluate` | Extract API token (once) |
| A4 | `browser_evaluate` | Get private file URL (must be on `app.slack.com`) |
| A5 | `browser_navigate` + `browser_take_screenshot` | View the image |

Steps A2-A3 only run once per conversation. For multiple files, repeat A4 + A5 per file (navigate back to `app.slack.com` before each A4 call).

---

# Shared: Reply Guidelines

Suggested replies must sound like a real person typed them quickly on Slack — not like AI-generated text.

- **Casual but capitalized.** Use standard sentence capitalization (capitalize the first word of each sentence). Contractions preferred ("I'll" not "I will"), fragments fine. Do NOT use all-lowercase style.
- Match the conversation's language and tone. If the other person writes in Chinese, reply in Chinese. If they're casual, be casual. If they're formal in a channel, be slightly more polished.
- Keep to 1-3 sentences for Slack. No walls of text.
- Bullet points for multiple items. Bold the label of each bullet when there's a clear category (e.g. `**Obstacles** (...): ...`) — this is the one place bold IS welcome because it scans fast.
- Outside of bullet labels: NO italic formatting, NO bold, NO markdown. Plain text only — Slack renders markdown differently and it looks unnatural.
- Use single dash `-` instead of double dash `--` or em dash `—`. Example: "really helpful - thank you" not "really helpful -- thank you".
- Don't start with "Hey [Name]!" every time. Vary openers or skip greetings entirely when the conversation is already flowing.
- Don't over-explain things participants already know.
- For technical questions needing investigation: "let me check and get back to you"
- For review requests: acknowledge + give ETA
- For urgent items: acknowledge urgency
- Include relevant links/data the user mentioned
- When in doubt, shorter is better. Real people don't write paragraphs in Slack DMs.

## Warm / polite tone ("礼貌热情")

When the user asks for a warm, polite, or enthusiastic tone, follow Yike's house style:

- **Open with a short warm acknowledgement**, not a preview of the answer. Good: "Thanks for reaching out!", "Thanks for the ping!", "Great to hear from you!". Bad: "Great question - short answer is: partially yes..." (the meta-preview feels AI-y).
- **Skip the "short answer is X" framing entirely.** Just say what's available and what's not. The reader infers the verdict from the content.
- **Be specific but not detailed.** State *where* something lives (e.g. "already ingested in the Lakehouse", "on the shared GCS bucket") so the reader can immediately act, but don't explain *how* it got there.
- **Push nuance into a linked thread instead of the reply body.** Format: `... (arriving in the upcoming weeks, <url|thread>)`. This keeps the reply short while making the detail one click away.
- **Cut hedging phrases.** Replace "Realistic ETA is a few weeks on their end + we can featurize shortly after, so roughly May" with "arriving in the upcoming weeks". One timeframe is enough.
- **End with a concrete offer, not a question.** Good: "Happy to get you access now so you can start prototyping, and I'll loop you in as soon as X lands." Bad: "Want to chat briefly to align?" (questions push work back onto the other person; offers pull it toward you).
- **One warm touchpoint is enough.** Don't stack "Thanks for reaching out!" + "Great question!" + "Happy to help!" — pick one opener, one closer, keep the middle factual.

# Shared: Actions

Suggested replies are presented in fenced code blocks so the user can review. **Do NOT auto-send or auto-draft** — only create a draft in Slack after the user explicitly confirms.

| Command | Action |
|---------|--------|
| "edit N: [text]" | Replace suggestion text and show updated version in a code block |
| "draft N" / "draft it" / "looks good" / "ok send" / "go ahead" / 挂上 / 挂到slack | Confirm the reply — call `slack_send_message_draft` to attach the draft in Slack (see **Creating Drafts** below). Do **not** call `slack_send_message` (don't send outright). |
| "dismiss N" | Remove item N from the persistent pending list without replying. It will not resurface in future polls. |
| "skip" | In Monitor: continue to next poll. In Thread: done. |
| "stop" | End polling loop (Monitor only) |

When a confirmation command is ambiguous (no number) and there is exactly **one** pending item in the current context (Thread mode, or Monitor mode with a single pending item), apply it to that item. Otherwise ask which item.

## Creating Drafts

After the user confirms a suggested reply, attach it as a Slack draft using `slack_send_message_draft`. This saves the draft in the user's Slack "Drafts & Sent" attached to the right channel/thread, so they just review and hit send.

### Parameters

| Arg | Value |
|-----|-------|
| `channel_id` | The channel of the original message (from M1/T1). For DMs, use the other person's user_id. |
| `thread_ts` | **Set this** when replying inside a thread (threaded @mention, threaded DM reply, or any reply to a specific message). Use the ts of the thread's root message, NOT the latest reply. Omit only when composing a brand-new top-level channel message. |
| `message` | The confirmed reply body. Convert the plain-text suggested reply into the draft API's **standard markdown** (`**bold**`, `*italic*`, `` `code` ``). Use `<URL\|label>` for links (angle-bracket form works in both APIs and renders cleanly). |

### Formatting notes (draft API vs send API)

`slack_send_message_draft` uses standard markdown (`**bold**`, `*italic*`). `slack_send_message` uses Slack-native markup (`*bold*`, `_italic_`). When converting a suggested reply (plain text, no markdown per Reply Guidelines) into a draft, only add emphasis if the original intent clearly warranted it — most replies stay as plain text.

Always use `<URL|label>` for links. Bare URLs get merged with adjacent text in Slack rendering.

### After drafting

1. Report the draft was created. Include the `channel_link` returned by the tool so the user can jump straight to it.
2. Remove the item from the persistent pending list (same effect as "dismiss"). The user's next Slack action resolves it.
3. In Monitor mode, resume the poll loop.

### Errors

- `draft_already_exists`: a draft is already attached to that channel. Tell the user to delete/send the existing draft in Slack first, then re-confirm.
- `mcp_externally_shared_channel_restricted`: Slack Connect channel — drafts aren't supported. Fall back to presenting the reply in a code block and telling the user to paste manually.
- `channel_not_found`: verify the channel_id; for DMs make sure it's the user_id, not a channel_id.

# Edge Cases

- **Inbox zero**: "Nothing pending — next check in 10 minutes."
- **Rate limits**: Space out MCP calls with 2s delays.
- **Long threads**: `response_format: "concise"` first, `"detailed"` on demand.
- **Both workspaces**: If user says "check everything", repeat searches against `user-slack-all-company`.
- **Mid-loop user input**: Handle the request (edit, question, etc.), then immediately resume the poll loop with a new `sleep 600` cycle. Never drop back to idle.
