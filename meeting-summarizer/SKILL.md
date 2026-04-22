---
name: meeting-summarizer
description: One-shot pipeline from meeting audio to a polished transcript plus opinionated summary in a single Markdown file. Use when the user attaches an audio file (mp4/m4a/wav/mp3) and mentions meeting or summary, types /meeting-summarizer, says "summarize this meeting" or "总结这个会议", or points at an existing transcript in ~/Desktop/python_code/meeting_notes/.
---

# Meeting Summarizer

Audio → polished transcript → opinionated summary, in one Markdown file.

Transcription, diarization, polish, and speaker identification run via `mac-meeting-transcriber` (the `mmt` CLI) at `/Users/KZFZ9H/Desktop/python_code/mac-meeting-transcriber`. This skill orchestrates that pipeline and appends the summary. Questions are asked only when the LLM's content-based speaker inference is genuinely uncertain — never up front, "just to be safe".

## When to apply

- User attaches an audio file (mp4, m4a, wav, mp3) and mentions meeting / summary / 总结.
- User types `/meeting-summarizer`.
- User says "summarize this meeting", "总结这个会议", or similar.
- User points at an existing transcript `.md` inside `~/Desktop/python_code/meeting_notes/`.

## Workflow

- [ ] 0. Resolve input (audio vs. existing transcript)
- [ ] 1. Identify "me" (default: Jason)
- [ ] 2. Idempotency check
- [ ] 3. Per-speaker key points
- [ ] 4. Intent analysis
- [ ] 5. Action items table
- [ ] 6. Append + verify

### Step 0 — Resolve input

**Case A: audio file**

1. Resolve the audio path: explicit user path > Cursor attachment > most recently modified audio in `~/Downloads/`.
2. Collect candidate speaker names — `Jason` plus unique names harvested from prior transcripts:
   ```bash
   rg '^- \*\*([^*]+)\*\*$' ~/Desktop/python_code/meeting_notes/*.md \
     -or '$1' --no-filename 2>/dev/null | sort -u
   ```
3. Run `mmt` via the `Shell` tool with `working_directory: "/Users/KZFZ9H/Desktop/python_code/mac-meeting-transcriber"` and `block_until_ms` ≥ 900000 (cold: ~12 min, warm cache-hit: ~3 min):
   ```bash
   uv run mmt "<audio_path>" --speakers "Jason,Leo,Kashish,..." -v
   ```
   Output lands in `$MMT_OUTPUT_DIR` (`~/Desktop/python_code/meeting_notes/<stem>.md`). The final stdout line is the full output path.
4. Scan `-v` logs for `confidence=X.XX` and `mapping: {...}`.
5. If `confidence < 0.75` OR the mapping conflicts with obvious content cues, use `AskQuestion` to disambiguate. Include 1–2 sample utterances per ambiguous speaker. If the user corrects a name, patch the generated `.md`:
   - Update the `## Participants` list.
   - Rewrite every `**[MM:SS] OldName:**` segment prefix.

**Case B: transcript `.md` already referenced** — skip 0.1–0.5 and jump to Step 1.

**Case C: neither referenced** — pick the most recently modified `*.md` in `~/Desktop/python_code/meeting_notes/`. If it already has `## Action Items`, confirm which meeting before proceeding.

### Step 1 — Identify "me"

Default "me" = `Jason` unless Jason is not a participant. Ask only if genuinely ambiguous.

### Step 2 — Idempotency

If the file already contains a summary section (`## Summary`, `## Intents`, `## Action Items`), do NOT overwrite silently — confirm with the user before re-summarizing.

### Step 3 — Per-speaker key points

For each participant, extract 3–6 bullets: what they said, what they pushed for, what they flagged. Preserve their voice — do not rewrite into your own register.

### Step 4 — Intent analysis

Surface 2–5 intents per participant:

| Participant | Intent | Evidence [MM:SS] |

"Intent" = what they actually want, not a literal paraphrase. Every row needs a timestamp and a short verbatim quote.

### Step 5 — Action items

| Owner | Action | Due | Source [MM:SS] |

- `Owner` must be a named participant — never "me", "someone", "TBD".
- Include actions that are explicitly stated or strongly implied ("I'll send it over", "Leo will draft…").
- `Due` only when the transcript states it; otherwise leave blank.

### Step 6 — Append + verify

Append `## Summary`, `## Intents`, `## Action Items` after the existing transcript. Before returning, verify:

- Every participant appears in per-speaker points.
- Every `Owner` in actions is in `## Participants`.
- All `[MM:SS]` citations point at real segments.

## Language rules

- Preserve code-switching verbatim (中英混合 stays mixed). Never translate either direction.
- Quote key phrases inline rather than paraphrasing them.
- Keep Chinese quotes in Chinese, English quotes in English — even within one bullet.

## Style

- Cite every factual claim about the meeting with `[MM:SS]`.
- Separate facts from inference: prefix reading-between-the-lines content with `Likely read:` or similar.
- Prefer tight bullets over prose.

## Anti-patterns

- Do NOT ask "who is SPEAKER_01?" up front if `mmt`'s mapping is already confident.
- Do NOT flatten speaker voice or code-switching into neutral English.
- Do NOT invent action items the transcript doesn't support.
- Do NOT overwrite an existing summary without explicit confirmation.

## Example

User attaches `4.15 Leo.mp4` and types `/meeting-summarizer`.

1. Resolve audio → collect speakers (`Jason,Leo,Kashish,Rohan` harvested from past notes) → run `uv run mmt "4.15 Leo.mp4" --speakers "Jason,Leo,Kashish,Rohan" -v`.
2. `mmt` logs: `confidence=0.92 mapping: {'SPEAKER_00': 'Leo', 'SPEAKER_01': 'Jason'}` → accept silently, no question asked.
3. Transcript saved to `~/Desktop/python_code/meeting_notes/4.15 Leo.md`.
4. Append per-speaker points, intents table, and action items for Jason and Leo.
5. Return the path plus a one-line gist to the user.
