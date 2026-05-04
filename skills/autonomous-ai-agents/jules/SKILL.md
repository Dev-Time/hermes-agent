---
name: jules
description: "Delegate coding to Google Jules asynchronous agent (features, refactors, bug fixes)."
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [Coding-Agent, Jules, Google, Async, Background-Tasks]
    related_skills: [claude-code, codex, hermes-agent]
---

# Jules

Delegate coding tasks to [Jules](https://jules.google.com/), Google's asynchronous coding agent. Jules works on tasks in the background — bug fixes, refactors, dependency updates, documentation — and submits changes to a GitHub branch when complete.

## When to Use

- Large-scale refactoring (project-wide symbol renames, module restructuring)
- Adding missing unit tests across the entire project
- Dependency version upgrades
- Code readability improvements across multiple files
- Tasks you want to run in the background without blocking your terminal

**Don't use for:** small single-file edits, quick fixes you can do yourself in one turn.

## Prerequisites

- A [Jules account](https://jules.google.com/)
- GitHub repository connected to your Jules account
- Jules CLI installed: `npm install -g @google/jules`
- Must run inside a git repository with a GitHub remote

## Installation
```bash
npm install -g @google/jules
jules login --no-launch-browser
# Visit the URL, paste the authorization code
```

If `jules login` fails with an authentication error about GitHub connection, go to https://jules.google.com to configure your GitHub connection.

## Durable Auth Configuration

Jules stores auth at `~/.jules/cache/oauth_creds.json`. In the Hermes Docker environment, `/root/.jules` is bind-mounted to the persistent volume — auth survives container restarts automatically.

If credentials expire (401 error), re-authenticate:
```bash
jules login --no-launch-browser
```

Or restore from a saved `oauth_creds.json` file:
```bash
mkdir -p ~/.jules/cache
chmod 700 ~/.jules/cache
# Place oauth_creds.json in ~/.jules/cache/
```

## Workflow 1: Creating a New Task

### 1. Identify the Repository

```bash
git config --get remote.origin.url
```

Parse the output to extract `username/repo_name` (e.g., from `https://github.com/username/repo_name.git`). If this fails, ask the user for the repo in `username/repo_name` format.

### 2. Start the Jules Session

```bash
jules remote new --repo <username/repo_name> --session "<task description>"
```

Example:

```bash
jules remote new --repo wyatth/my-project --session "Add missing unit tests for all API endpoints"
```

### 3. Report to User

Share the console link from the output so the user can track progress at https://jules.google.com.

## Workflow 2: Checking Existing Tasks

### 1. List Sessions

```bash
jules remote list --session
```

### 2. Find the Target Session

- **Latest task:** pick the session with the most recent `lastActive` timestamp
- **By description:** match the user's query against session descriptions
- Store the session ID once found

### 3. Handle by Status

**Status: "awaiting user feedback"**
Direct the user to the Jules console: `https://jules.google.com/session/<session_id>`

**Status: "Completed"**
Apply the diff (see Workflow 3).

## Workflow 3: Applying Completed Diffs

### 1. Pull the Diff

```bash
mkdir -p .jules
jules remote pull --session <session_id> > .jules/diff.patch
```

### 2. Verify the Diff Applies

Examine the first 500 lines of `.jules/diff.patch`. If the file paths don't match the current directory, the changes are for a different project — tell the user and provide the console URL, then clean up:

```bash
rm -rf .jules
```

### 3. Apply Changes

Ask the user: apply locally or publish to a new branch?

#### Option A: Apply Locally

```bash
patch -p1 < .jules/diff.patch
git status          # verify changes
rm -rf .jules
```

#### Option B: Publish to a New Branch

```bash
# Ask for branch name, or generate one from the changes
git checkout -b <branch_name>
git apply --index .jules/diff.patch
git add .
git status          # verify changes
git rm --cached -r .jules   # don't commit the .jules dir
git commit -m "Apply Jules changes for session <session_id>"
git push -u origin <branch_name>
rm -rf .jules
```

Provide the URL for the newly created branch.

## Auto-Detection Triggers

If the user's request (without explicitly mentioning Jules) matches any of these, suggest using Jules:

- "Add missing unit tests for the entire project"
- "Improve code readability across multiple files"
- "Upgrade dependency versions"
- "Perform a large-scale refactoring" (e.g., renaming a symbol project-wide)
- "Analyze the dependency tree for optimization"

Prompt: *"This looks like a great fit for Jules! Would you like to offload this to Jules so it runs in the background?"*

If the user explicitly asks for Jules, skip the confirmation.

## Common Pitfalls

1. **`jules: command not found`** — Install with `npm install -g @google/jules`
2. **401 authentication error despite being logged in** — The GitHub connection may need reconfiguration at https://jules.google.com
3. **Diff paths don't match** — The completed task may target a different directory layout. Point the user to the console URL for manual review.
4. **Committing `.jules/` directory** — Always `git rm --cached -r .jules` before committing, and `rm -rf .jules` after.
5. **Not inside a git repo** — Jules requires a Git repository with a GitHub remote.

## Verification Checklist

- [ ] Jules CLI installed (`which jules`)
- [ ] Authenticated (`jules login` succeeds)
- [ ] Inside a git repo with a GitHub remote (`git config --get remote.origin.url`)
- [ ] Task created successfully (`jules remote new` returns a session ID)
- [ ] Console link shared with user
- [ ] `.jules/` directory cleaned up after applying diffs
- [ ] No `.jules/` artifacts committed to the repo
