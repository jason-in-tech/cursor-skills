---
name: rebase-to-develop
description: Rebase the current branch (and optionally its parent stack) onto the latest origin/develop. Use when the user asks to rebase, update their branch, pull latest develop, or sync with develop.
---

# Rebase to Latest Develop

Rebase the current working branch onto the latest `origin/develop`, preserving any uncommitted local changes. Supports Graphite stacked branches — when the current branch has a parent that is not `develop`, rebase the parent chain first.

## Prerequisites

- Must NOT be on the `develop` branch itself. If so, abort and tell the user.
- **If the rebase is being triggered to resolve a Roboflow stale-branch error**:
  STOP and ask the user first. Rebasing is NOT the only option — env var bypass
  (`CRUISE_BYPASS_BAD_COMMITS` + `STALE_CODE_REASON`) avoids rebasing entirely
  and preserves code parity for experiment comparisons. See the
  `verify-before-claiming` rule for the full decision framework.

## Workflow

Run these steps in order. Stop and resolve if any step fails.

### 1. Identify the current branch and stack

```bash
git branch --show-current
```

Abort if the branch is `develop`.

Check if the branch is part of a Graphite stack:

```bash
gt log short 2>/dev/null
```

If Graphite is available and the branch has a parent that is not `develop`, note the parent branch name. The parent must be rebased first (step 4a) before the current branch (step 4b).

### 2. Fetch latest develop

```bash
git fetch origin develop
```

### 3. Stash uncommitted changes

```bash
git stash
```

Note whether the output says `No local changes to save` (nothing was stashed) or `Saved working directory…` (changes were stashed). Track this so you know whether to pop later.

### 4. Rebase

#### 4a. Rebase parent branch (if stacked)

If the current branch has a Graphite parent that is not `develop`:

```bash
git checkout <parent-branch>
git rebase origin/develop
```

Resolve any conflicts (see "If conflicts arise" below). Then push the parent:

```bash
git push --force-with-lease origin <parent-branch>
```

Then switch back:

```bash
git checkout <current-branch>
git rebase <parent-branch>
```

For deeper stacks (grandparent, etc.), work bottom-up: rebase each branch onto its freshly-rebased parent, push, then move up the stack.

#### 4b. Rebase current branch (no parent, or after parent is done)

```bash
git rebase origin/develop
```

#### If conflicts arise

1. List conflicted files with `git diff --name-only --diff-filter=U`.
2. Search for conflict markers (`<<<<<<<`, `=======`, `>>>>>>>`) in each conflicted file.
3. Read the conflict region with surrounding context, resolve the markers, and write the resolved content.
4. Stage resolved files with `git add`.
5. Continue the rebase:

```bash
GIT_EDITOR=true git rebase --continue
```

6. Repeat until the rebase completes.

If conflicts are too complex to resolve automatically, abort and tell the user:

```bash
git rebase --abort
```

#### If untracked files block the rebase

Git will error with `untracked working tree files would be overwritten by merge` when a commit being replayed creates files that already exist as untracked on disk.

1. Move the listed files to a temp directory:

```bash
mkdir -p /tmp/rebase-untracked
mv <file1> <file2> ... /tmp/rebase-untracked/
```

2. Continue the rebase with `git rebase --continue`.
3. After the rebase completes, restore the files:

```bash
mv /tmp/rebase-untracked/* <original-locations>
rmdir /tmp/rebase-untracked
```

### 5. Restore stashed changes

Only if changes were stashed in step 3:

```bash
git stash pop
```

If the pop produces merge conflicts, resolve them the same way as step 4.

### 6. Push

```bash
git push --force-with-lease origin <branch>
```

Replace `<branch>` with the branch name from step 1.

If the pre-push lint hook fails on **pre-existing** issues (not introduced by the rebase), use `--no-verify`:

```bash
git push --no-verify --force-with-lease origin <branch>
```

Only use `--no-verify` when the lint errors clearly predate the rebase. If the rebase introduced new issues, fix them first.

### 7. Verify

Confirm the rebase landed correctly:

```bash
git merge-base --is-ancestor origin/develop <branch> && echo "includes latest develop"
```

For stacked branches, also verify the parent relationship:

```bash
git merge-base --is-ancestor <parent-branch> <current-branch> && echo "current is on top of parent"
```

## Summary

After completion, report:
- Whether the rebase was clean or conflicts were resolved.
- Whether stashed changes were restored.
- The push result for each branch.
- For stacks: the parent-child relationship is intact.
