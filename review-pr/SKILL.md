---
name: review-pr
description: Review a GitHub pull request by URL or number. Fetches the diff, summarizes what the PR does, and generates recommended review comments with severity and file/line references. Use when the user shares a PR link, asks to review a PR, or wants feedback on someone else's pull request.
---

# Review PR

Analyze a GitHub pull request and produce a structured review with recommended comments.

## Trigger

Any of:
- User pastes a GitHub PR URL (e.g. `https://github.robot.car/cruise/cruise/pull/12345`)
- User says "review this PR" or "look at this PR"
- User provides a PR number and repo context

## Step 1: Fetch PR Context

Extract the PR identifier from the user's input. Use `gh` to gather metadata and the diff in parallel.

```bash
# Metadata (title, author, body, labels, base branch, changed files count)
gh pr view <URL_OR_NUMBER> --json title,author,body,labels,baseRefName,changedFiles,additions,deletions,commits

# Full diff
gh pr diff <URL_OR_NUMBER>

# File list with per-file stats
gh pr diff <URL_OR_NUMBER> --stat
```

For GitHub Enterprise (github.robot.car), set the host if needed:
```bash
GH_HOST=github.robot.car gh pr view ...
```

If the diff is very large (>3000 lines), focus on the most impactful files first. Use `--stat` output to prioritize files by change size, then fetch individual file diffs with:
```bash
gh api repos/{owner}/{repo}/pulls/{number}/files --paginate
```

## Step 2: Understand the PR and Surrounding Context

The reviewer may be unfamiliar with the codebase the PR touches. Before diving into line-level review, build a thorough mental model.

### 2a. Read surrounding code (not just the diff)

For every file in the diff, read the full file (or at least the classes/functions that the diff touches) using the Read tool. This gives you:
- The imports and dependencies the module relies on
- The class hierarchy or module-level constants the diff builds on
- Naming conventions and patterns used in the rest of the file

If the diff references types, functions, or constants defined in other files (e.g. imports from sibling modules), read those too. Follow the dependency chain until you have enough context to understand every symbol in the diff.

### 2b. Build a mental model

1. **Read the PR description** for stated intent, linked issues, and test plan
2. **Scan the file list** to understand scope (which packages/modules are touched)
3. **Identify the type of change**: feature, bugfix, refactor, config change, test-only, etc.
4. **Note the base branch** to understand the merge target

### 2c. Identify the key abstractions

Before writing any review comments, list the key abstractions the PR introduces or modifies:
- New types, enums, dataclasses, or config fields
- New SQL queries or templates
- New functions and their call graph (who calls whom)
- Changes to public API surface (renamed functions, new parameters, removed exports)

## Step 3: Analyze the Diff

Review the diff against these criteria, ordered by importance:

### Correctness
- Logic errors, off-by-one mistakes, race conditions
- Unhandled edge cases (null, empty, boundary values)
- Exception handling gaps (swallowed errors, missing propagation)
- API contract violations or breaking changes

### Design and Architecture
- Does the approach fit the codebase's existing patterns?
- Tight coupling, missing abstractions, or leaky abstractions
- Functions/classes that are too large or do too many things
- Opportunities to reuse existing code instead of duplicating

### Safety and Robustness
- Security concerns (injection, auth bypass, data leakage)
- Resource leaks (unclosed handles, missing cleanup)
- Concurrency issues (shared mutable state, missing locks)
- Error paths that could leave the system in a bad state

### Testing
- Are new code paths covered by tests?
- Are edge cases tested?
- Do existing tests need updates for behavioral changes?
- Are test assertions meaningful (not just "doesn't crash")?

### Readability and Maintainability
- Unclear naming or misleading variable/function names
- Magic numbers or hardcoded values that should be constants
- Missing or misleading docstrings for public APIs
- Overly complex logic that could be simplified

## Step 4: Present the Review

### Background / Context Section

Start with a plain-language explanation of the system and the change, written for someone who has never seen this codebase. Cover:

- **What system does this code belong to?** Explain the pipeline, service, or module in 2-3 sentences. What is its purpose, who uses it, and how does it fit into the larger product?
- **What problem is the PR solving?** Explain the motivation and the gap that existed before this PR.
- **How does the PR solve it?** Walk through the approach at a conceptual level (not line-by-line). Describe the new abstractions, data flow, or behavioral changes. Use concrete terms (function names, config fields, query names) so the reader can map concepts to code.
- **Key design decisions**: Call out non-obvious choices the author made (e.g. algorithm selection, schema design, why a placeholder is used) and explain the tradeoff.

### Summary Section

After the background, give a concise summary:
- **Scope**: which packages/modules are affected
- **Risk assessment**: low / medium / high, with reasoning
- **Backward compatibility**: does existing behavior change? Is the new code behind a flag?

### Recommended Comments

Present each comment in this format:

---

**[Severity] `file/path.py:L42`**

> Quote the relevant code line(s)

**For the reviewer (me):** Explanation of the concern in plain language. When the concern involves a concept or pattern the reviewer may not know, explain it briefly (e.g. what the algorithm does, what the BQ function returns, why the pattern matters).

**Suggested PR comment:**

> *Ready-to-post wording written in second person ("you"), conversational but professional, as if the reviewer is speaking directly to the PR author. Keep it concise (2-5 sentences). Include the "why" (what could go wrong, what's confusing, what alternative exists). For suggestions and nits, include a concrete code snippet or rewording when applicable. For questions, phrase as a genuine question, not a veiled demand.*

---

Severity levels:
- **Critical** -- Must address before merge. Bugs, data loss, security issues, breaking changes.
- **Suggestion** -- Strongly recommended. Design issues, missing tests, unclear code.
- **Nit** -- Optional. Style, naming, minor improvements.
- **Question** -- Not necessarily wrong, but needs clarification from the author.

### Ordering

1. Critical items first
2. Group by file when multiple comments target the same file
3. Nits and questions at the end

### Positive Callouts

If the PR does something notably well (clean abstraction, thorough tests, good documentation), mention it briefly at the end. Reviews that only list problems are demoralizing.

## Step 5: Interactive Follow-up

After presenting the review, offer:
- "Want me to look at any file more closely?"
- "Want me to post these comments on the PR?" (only if asked)

### Posting Comments

If the user asks to post comments, use the GitHub API:

```bash
gh api repos/{owner}/{repo}/pulls/{number}/reviews \
  --method POST \
  --field event=COMMENT \
  --field body="<overall summary>" \
  --field 'comments=[{"path":"file.py","line":42,"body":"comment text"}]'
```

Only post after explicit user approval. Never auto-approve or request-changes without the user saying so.
