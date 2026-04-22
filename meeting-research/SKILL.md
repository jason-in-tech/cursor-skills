---
name: meeting-research
description: Consume existing meeting transcripts to prep for upcoming meetings, roll up action items across meetings, or answer specific factual questions. Use when the user says "what did X say about Y", "prep me for my meeting with Z", "还有啥 action 没推完", "上周 ... 聊啥了", or similar queries against the ~/Desktop/python_code/meeting_notes/ corpus. Chat-only output by default.
---

# Meeting Research

Knowledge-base skill over the user's meeting transcript corpus at `~/Desktop/python_code/meeting_notes/*.md`. Answers questions, preps for upcoming meetings, and tracks action items across meetings. Does NOT create new transcripts — for that, use `meeting-summarizer`.

## When to apply

Three patterns:

1. **Prep for upcoming meeting** — "I have a 1:1 with Leo at 3pm, prep me."
2. **Action-item rollup / follow-through** — "What's still open from my chats with Kashish?", "那个 SC3 protocol 的 action 推完了没？"
3. **Fact retrieval** — "What did Rohan say about the simulation pipeline last week?"

## Workflow

- [ ] 1. Parse prompt for intent / who / when / topic
- [ ] 2. Resolve relative time expressions
- [ ] 3. Locate candidate files
- [ ] 4. Disambiguate (only if > 5 candidates)
- [ ] 5. Read selected files in full
- [ ] 6. Intent-specific analysis
- [ ] 7. Reply in chat with citations

### Step 1–2 — Parse + resolve time

Extract from the prompt:

- **Intent**: prep / action-rollup / fact-retrieval (sometimes mixed).
- **Who**: participant name(s).
- **When**: absolute or relative time window.
- **Topic**: keywords, project names, entities.

Resolve relative time expressions against today's local date (the value in the `user_info` block, not training-data date):

| Chinese / English | Window |
|---|---|
| 上周 / last week | previous Mon–Sun |
| 这周 / this week | current Mon–Sun |
| 最近 / recently | last 14 days |
| 上次 / last time | most recent matching file |
| 上个月 / last month | previous calendar month |

### Step 3 — Locate candidate files

Search strategies (run in this order, intersect where useful):

1. **Filename match**: `ls ~/Desktop/python_code/meeting_notes/ | rg -i '<keyword>'`.
2. **Participant match**: `rg -l '^- \*\*<Name>\*\*$' ~/Desktop/python_code/meeting_notes/*.md`.
3. **Topic match**: `rg -l -i '<keyword>' ~/Desktop/python_code/meeting_notes/*.md`.
4. **Time filter**: intersect with files whose filename date prefix (e.g. `4.15`, `2026-04-10`) or `stat -f %Sm` mtime falls in the resolved window.

### Step 4 — Disambiguate

If > 5 candidate files remain after filtering, use `AskQuestion` to let the user pick. If ≤ 5, proceed with all of them.

### Step 5 — Read

Read each selected file in full — meeting transcripts are typically < 2000 lines and fit comfortably. Do NOT skim; you need full participant attribution and accurate timestamps for citation.

### Step 6 — Intent-specific analysis

#### 6a. Prep for upcoming meeting

Produce the shortest useful briefing:

- **Standing**: where did you leave off? (most recent file with this person)
- **Open threads**: decisions pending, questions unanswered, commitments made.
- **Their likely positions**: what they've pushed for historically.
- **Your open questions**: things you flagged but didn't resolve.
- **Risks / traps**: points where you've disagreed or previously talked past each other.

#### 6b. Action-item rollup

For each relevant action item from the target meeting(s):

1. Pull the original row: `Owner`, `Action`, `Due`, `Source [MM:SS]`.
2. Scan later meetings (mtime > source date) for status cues, using a small keyword set derived from the action:
   - **Done** — "finished X", "X is merged/deployed", explicit close.
   - **Deferred** — "pushed to next week", "we agreed to wait".
   - **Blocked** — "blocked on Y", "waiting for Z".
   - **No mention** — genuinely silent in later meetings.
3. Report as a status table with per-row citations.

#### 6c. Fact retrieval

Quote the relevant line(s) verbatim with `[MM:SS]` and file citation. Add 1–2 lines of surrounding context only if omitting them would change meaning. Do NOT paraphrase the quote away.

### Step 7 — Reply

Chat-only output by default. Save to file ONLY if the user explicitly asks ("save this", "write it out", "落盘"). When saving, write to `~/Desktop/python_code/meeting_notes/research/<YYYY-MM-DD>-<short-topic>.md`.

## Style

- Cite every factual claim: `[file.md MM:SS]`.
- Separate facts from inference: prefix inference with `Likely read:` or "Reading between the lines:".
- Prefer tight tables / bullets over prose walls.
- Preserve code-switching in quotes verbatim.
- If the corpus genuinely has nothing relevant, say so explicitly — do not pad with adjacent-but-irrelevant content.

## Anti-patterns

- Do NOT fabricate citations or invent meeting content.
- Do NOT flatten quotes into paraphrase.
- Do NOT save to disk unless explicitly asked.
- Do NOT read only file summaries — status cues often live in mid-transcript dialogue.

## Example

User: "上周 Kashish 聊的那个 SC3 evaluation protocol，他那边 action 还有啥没推完？"

1. **Parse**: intent = action-rollup, who = Kashish, when = 上周, topic = SC3 evaluation protocol.
2. **Resolve time**: last Mon–Sun window.
3. **Locate**: `rg -l 'Kashish' ~/Desktop/python_code/meeting_notes/*.md`, filter by filename date / mtime in window → `4.10 Kashish SC3.md`.
4. **Read** the file in full.
5. For each action in `## Action Items` with Owner = Kashish: scan all `meeting_notes/*.md` with mtime > 4.10 for status cues on matching topic keywords.
6. **Reply**:

   > **Kashish's open actions from 4.10 (`4.10 Kashish SC3.md`)**
   >
   > | Action | Status | Evidence |
   > |---|---|---|
   > | Share SC3 score breakdown script | **Done** | `4.13 Kashish.md` [07:22] "pushed the script last night" |
   > | Draft eval protocol doc | **No mention** | — |
   > | Check sim pipeline flake rate | **Blocked** | `4.12 team sync.md` [14:03] "blocked on Rohan's commit" |
   >
   > (Save to `meeting_notes/research/`? Default: no.)
