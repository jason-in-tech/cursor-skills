# Slack Prepare: Draft, Review, Send

Structured workflow for preparing Slack messages through a draft → review → send cycle.
Use when the user wants to announce results, share updates, or send messages to channels
or individuals, and wants to review the content before sending.

## Workflow

### Step 1: Draft

Create a markdown file with the message content. Store it in a predictable location
near the relevant project output:

```
<project_dir>/output/<topic>_slack_<target>.md
```

The file should contain:
- **Header block**: Target channel/user, status (DRAFT/REVIEWED/SENT), date
- **Message body**: Formatted for Slack (see formatting rules below)
- **Placeholders**: Use `<PLACEHOLDER — description>` for values not yet available

### Step 2: Review

When the user says "review" or "looks good":
1. Read the current draft
2. Fill in any remaining placeholders with actual data
3. Present the final message to the user for approval
4. Update status from DRAFT to REVIEWED

### Step 3: Send

When the user approves, send via the appropriate Slack MCP tool:

**Send to yourself for final review** (recommended first):
```
CallMcpTool:
  server: user-slack-all-company  (or user-slack-ss for side-server)
  toolName: slack_send_message_draft
  arguments:
    channel_id: <your_DM_channel_id>
    message: <formatted_message>
```

**Send to a channel**:
```
CallMcpTool:
  server: user-slack-all-company
  toolName: slack_send_message
  arguments:
    channel_id: <channel_id>
    message: <formatted_message>
```

**To find channel IDs**:
```
CallMcpTool:
  server: user-slack-all-company
  toolName: slack_search_channels
  arguments:
    query: <channel_name>
```

**To find user IDs (for DMs)**:
```
CallMcpTool:
  server: user-slack-all-company
  toolName: slack_search_users
  arguments:
    query: <user_name>
```

## Slack Formatting Rules

Slack uses mrkdwn (not standard Markdown). Key differences:

| Element | Markdown | Slack mrkdwn |
|---|---|---|
| Bold | `**text**` | `*text*` |
| Italic | `*text*` | `_text_` |
| Code | `` `code` `` | `` `code` `` (same) |
| Link | `[text](url)` | `<url\|text>` |
| Bullet | `- item` | `• item` (use bullet char) |
| Sub-bullet | `  - item` | `    ◦ item` |
| Header | `# text` | Not supported (use *bold*) |
| Mention user | N/A | `<@USER_ID>` |
| Mention channel | N/A | `<#CHANNEL_ID>` |

### Converting MD draft to Slack format

When sending, convert the markdown draft to Slack mrkdwn:
1. Replace `**text**` with `*text*`
2. Replace `[text](url)` with `<url\|text>`
3. Replace `- ` bullets with `• `
4. Replace `  - ` sub-bullets with `    ◦ `
5. Remove markdown headers (`#`, `##`), use `*bold*` instead
6. Keep `` `code` `` as-is
7. Replace user names with `<@USER_ID>` (look up via slack_search_users)

## Draft File Format

```markdown
# Slack Message: <topic>

**Target**: #channel-name (CHANNEL_ID) or @user-name
**Status**: DRAFT | REVIEWED | SENT
**Date**: YYYY-MM-DD

---

<message content in Slack mrkdwn format>
```

## Self-Review Checklist

Before sending to user for review:
- [ ] All placeholders filled with actual data
- [ ] Numbers are accurate and sourced (BQ queries, run results)
- [ ] Links are valid (Roboflow, Confluence, GitHub)
- [ ] Tone matches the team's communication style
- [ ] CC list includes relevant stakeholders
- [ ] File attachments noted (screenshots, plots) if needed

## Example: Dataset Announcement

See reference: `https://all-gm.slack.com/archives/C08L1PQBAMT/p1764630546832069`
(DCV-1 Dataset-V2.0 announcement by Yi Hao)

Key elements of a dataset announcement:
1. Bold title line
2. One-sentence summary of what's new
3. Bullet list of changes/updates with PR links
4. Dataset ID and Roboflow run links
5. Stats table: total sequences, train/val/test split
6. Yield analysis with percentages
7. Known limitations
8. Next steps
9. CC list of relevant people
