# Get Transcript Directory

Return the agent transcript path for the current session.

## How It Works

Cursor stores agent transcripts at:

```
~/.cursor/projects/<project-slug>/agent-transcripts/<session-uuid>/<session-uuid>.jsonl
```

Where `<project-slug>` is the workspace path with `/` replaced by `-` and leading `-` stripped.

## Steps

1. The project slug is provided in the system prompt's `agent_transcripts` section. It contains the path to the `agent-transcripts` folder. Read it directly from the system prompt -- do NOT try to compute it.

2. The current session UUID is the parent directory name of the transcript JSONL mentioned in the `[Previous conversation summary]` section (field: `Transcript location`). If there is no summary, the session UUID appears in the `agent_transcripts` section as the citation format `(<uuid excluding .jsonl>)`.

3. Return both:
   - **Transcript directory**: `~/.cursor/projects/<project-slug>/agent-transcripts/<uuid>/`
   - **Transcript file**: `~/.cursor/projects/<project-slug>/agent-transcripts/<uuid>/<uuid>.jsonl`

## When There Is No Prior Summary

If this is a brand-new session with no `[Previous conversation summary]`, the transcript folder is the one from the `agent_transcripts` section in the system prompt. List the folder to find the most recently modified `.jsonl` file -- that is the current session.

## Output Format

```
Transcript directory: <path>
Transcript file: <path>.jsonl
```
