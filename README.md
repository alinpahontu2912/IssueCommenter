# GitHub Copilot Issue Commenter Workflow

This repository contains a GitHub Actions workflow that uses GitHub Copilot to automatically manage stale issues. It comments on old issues asking if they're still relevant, then closes them if no reply is received within 14 days.

## How It Works

1. **Every Monday**, two jobs run in parallel:
   - **Commenter** (`commenter.py`): Finds open issues not updated in 730+ days, generates an AI-personalized comment asking the author for an update. Each comment includes a hidden HTML marker (`<!-- issue-commenter-bot -->`) for tracking.
   - **Closer** (`closer.py`): Searches the GitHub API for issues with bot-marked comments. If 14+ days have passed with no reply, it posts a closing comment and closes the issue.

2. **Manual dispatch** is also supported with a mode selector (`comment`, `close`, or `both`).

## Features

- **AI-Powered Comments**: Uses GitHub Models (GPT-4o-mini) to generate personalized, context-aware comments referencing issue details, labels, linked PRs, and full discussion history.
- **Stateless Design**: The closer queries the GitHub API directly — no log files or state needed between runs.
- **Duplicate Prevention**: The commenter skips issues that already have a bot comment.
- **Configurable**: Repo, staleness threshold, and close threshold are all configurable via environment variables.
- **Secure**: Uses GitHub Secrets for authentication tokens.

## Setup

1. Fork or clone this repository.
2. Set the required GitHub Secret:
   - `AI_TOKEN`: GitHub token with issues write access and GitHub Models access.
3. Optionally configure environment variables in the workflow:
   - `REPO_OWNER` / `REPO_NAME`: Target repository (defaults to `dotnet/TorchSharp`)
   - `DAYS_THRESHOLD`: Days of inactivity before commenting (default: 730)
   - `CLOSE_THRESHOLD_DAYS`: Days to wait for reply before closing (default: 14)
4. Push to the default branch — the workflow runs every Monday.

## Logs

Each run generates timestamped log files uploaded as GitHub Actions artifacts (retained for 30 days).
