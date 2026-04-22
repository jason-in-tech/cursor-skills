---
name: fix-markdown-crash
description: >-
  Diagnose and fix markdown files that crash Cursor with "Assertion Failed".
  Use when the user reports a markdown file cannot be opened, says "assertion
  failed", "cannot open md", "markdown crash", "fix md", or "fix markdown".
---

# Fix Markdown Crash

**Related authoring skill.** The prevention rules codified from this skill
live in `write-technical-report`'s
[Markdown-safe syntax](../write-technical-report/SKILL.md) section. That
skill runs the scanner as part of its audit checklist, so new drafts should
not hit these crashes in the first place. Use *this* skill reactively, when
a file is already crashing and needs fixing.

## Quick Diagnosis

Cursor's markdown preview crashes on **bare `<` and `>` characters** in prose
or table cells that the tokenizer misinterprets as malformed HTML. Unicode
characters do NOT cause crashes.

Common crash patterns:
- `L2<3m` or `cap < 128` in a table cell
- Slack links: `<https://url|text>`
- HTML tags: `<br>`, `<a id="x">`, `<details>`
- HTML comments: `<!-- ... -->`

Safe patterns (do NOT crash):
- `<`/`>` inside backtick code spans or fenced code blocks
- Markdown blockquotes (`> text` at the start of a line)
- Text arrows (`->`, `-->`, `<-`) -- these are not parsed as HTML
- Unicode symbols (arrows, dashes, etc.)

## Step 0: ALWAYS scan the whole directory

Do NOT just scan the one file the user mentioned. Sibling `.md` files in the
same directory almost always have the same issues. The scanner accepts a
directory and recursively scans all `*.md` files:

```bash
python3 ~/.cursor/skills/fix-markdown-crash/scripts/scan_md.py DIRECTORY/
```

## Step 1: Scan

To scan a single file:

```bash
python3 ~/.cursor/skills/fix-markdown-crash/scripts/scan_md.py PATH_TO_FILE
```

Reports every bare `<` or `>` outside code spans/fenced blocks with line
numbers and surrounding context.

## Step 2: Fix

Option A -- auto-fix common patterns first, then review remaining:

```bash
python3 ~/.cursor/skills/fix-markdown-crash/scripts/scan_md.py PATH_OR_DIR --fix
```

The auto-fixer handles: `<br>`, HTML comments, Slack links, `<@mentions>`,
and simple `< NUMBER` / `> NUMBER` patterns. Anything it cannot auto-fix is
reported for manual rewording.

Option B -- manual reword using these substitutions:

| Instead of | Write |
|---|---|
| `L2 < 3m` | `L2 within 3m` |
| `> 123 deg` | `123+ deg` or `above 123 deg` |
| `< 16 ticks` | `fewer than 16 ticks` |
| `IoU >= 0.45` | `IoU 0.45+` |
| `<br>` | blank line or ` -- ` |
| `<!-- comment -->` | remove entirely |
| `<url\|text>` | `[text](url)` |
| `<@U012ABC>` | person's name |

Key rule: **reword, do not escape**. Backslash escapes (`\<`), HTML entities
(`&lt;`), and even backtick code spans in some table contexts have been
unreliable. Rewording is the only guaranteed fix.

## Step 3: Verify

After fixing, re-run the scanner on the **directory** to confirm zero issues:

```bash
python3 ~/.cursor/skills/fix-markdown-crash/scripts/scan_md.py DIRECTORY/
```

Expected output: `All clean: N file(s) scanned, no crash patterns found.`

## Step 4: If it still crashes -- client-side path cache corruption

If the scanner reports zero issues but the file still triggers "Assertion
Failed: Argument is 'undefined' or 'null'", the crash is a **Cursor
client-side path cache corruption**, not a content problem.

### How to confirm

Copy the file to a different name and open the copy:

```bash
cp problem_file.md test_copy.md
```

If the copy opens fine in preview but the original still crashes, the cache
is corrupted for that specific file path.

### What does NOT fix it

All of these have been tested and **do not work**:
- `Developer: Reload Window` -- client cache persists across reloads
- Replacing the file with an identical copy (same path = same cache key)
- Deleting server-side History (`~/.cursor-server/data/User/History/`)
- Deleting server-side cursor-commits checkpoints
- Replacing the file's inode (`mv` + `cp` back)

The corrupted state lives in the **Cursor client** (macOS:
`~/Library/Application Support/Cursor/`), which is inaccessible from SSH
remote sessions. The cache is keyed by absolute file path.

### What fixes it

**Rename the file.** This is the only reliable fix from an SSH session:

```bash
mv problem_file.md new_name.md
```

The old path's cache entry will become orphaned and eventually expire.

### Root cause

Observed when a markdown file receives many rapid edits (especially
agent-driven StrReplace operations) across multiple sessions. The
client-side markdown tokenizer state gets corrupted and cached under the
file's absolute path. Subsequent opens hit the corrupted cache before
re-parsing the file content.

### Prevention

For files that will be heavily edited by agents, consider periodic renames
or working in a git repo where `git checkout -- file` can reset client
state.
