# GitHub Copilot Issue Commenter Workflow

This repository contains a GitHub Actions workflow that uses GitHub Copilot to automatically respond to stale issues every two weeks. The goal is to maintain a clean and relevant backlog by prompting users for updates on inactive issues, while keeping the responses professional and personal.

## Features

- Automated Copilot Responses: Uses GitHub Copilot to generate AI-powered responses asking users if the issue is still relevant.
- Scheduled Workflow: Runs every two weeks, on Mondays, to avoid spamming users and provide a consistent check-in cycle, in lign with the internal policy of closing inactive items for more than two weeks.
- Logs and Transparency: Saves log files for each run to:
  - Review generated responses.
  - Identify any issues or errors during execution.
- Secure by Design:
  - Uses GitHub Secrets to securely store authentication tokens and Copilot keys.
- Stale Issue Detection: Only responds to issues that are considered stale, avoiding unnecessary interactions with active threads.
- Prompt Engineering: Carefully designed prompts guide Copilot to generate replies that are:
  - Professional in tone.
  - Respectful and personal.

## Work in Progress

- Auto-Closure Logic: A planned feature will:
  - Parse the existing log files.
  - Automatically close issues that were commented on but received no reply within two weeks.

## Setup

1. Fork or clone this repository.
2. Set the required GitHub Secrets:
   - `GITHUB_TOKEN`: GitHub Actions token with access to comment on issues.
   - `COPILOT_API_KEY` (if using a custom Copilot integration).
3. Review or modify the workflow schedule in `.github/workflows/copilot-issue-responder.yml`.
4. Push to the default branch – the workflow will start running on the next scheduled Monday.

## Logs

Each run generates a timestamped log file uploaded as an artifact. These logs can be used to:

- Audit AI-generated messages.
- Diagnose errors or missing responses.
- Power future automation (e.g., issue auto-closure).

## Example Messages

> "Thank you for reporting this issue regarding support for non-Tensor types in ScriptModule. We appreciate your contribution and the detailed examples you provided. Since this issue hasn't been updated in over two years, we wanted to check in to see if it is still relevant or if you've found a resolution in the meantime. TorchSharp has evolved significantly since your original post, and we'd love to hear if your needs have changed or if you still require these additional types. Any updated information you can provide would be greatly appreciated!"
> "Thank you for reporting this issue regarding GradScaler and mixed-precision training! We appreciate your input on the need for gradient scaling, especially as we look forward to supporting fp8 with Hopper/40XX GPUs in the future.
Since this issue hasn't been updated in over two years, we wanted to check in to see if it's still relevant or if there have been any developments on your end. TorchSharp has evolved significantly during this time, and we'd love to hear if you still encounter challenges related to this topic.
If the issue persists, any updated information you can provide would be greatly appreciated!"

## What I Learned

- Prompt engineering for professional, on-topic AI responses.
- Integration of GitHub Copilot into GitHub Actions workflows.
- Managing and using GitHub Secrets securely.
- Building reliable, scheduled automation with logging and extensibility.
