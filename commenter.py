import openai
import requests
import json
from datetime import datetime, timedelta
import time
import logging
import os

# GitHub API configuration
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
if not GITHUB_TOKEN:
    raise ValueError("GITHUB_TOKEN environment variable is required")

# Days threshold configuration (default: 2 years = 730 days)
raw_days = os.getenv("DAYS_THRESHOLD", "").strip()
DAYS_THRESHOLD = int(raw_days) if raw_days else 730

REPO_OWNER = os.getenv("REPO_OWNER", "dotnet")
REPO_NAME = os.getenv("REPO_NAME", "TorchSharp")
GITHUB_API_BASE = "https://api.github.com"

# Hidden marker to identify bot comments for the closer script
BOT_COMMENT_MARKER = "<!-- issue-commenter-bot -->"

# GitHub Copilot Enterprise configuration
openai.api_key = GITHUB_TOKEN
openai.api_base = "https://models.github.ai/inference"
openai.api_type = "open_ai"

model = "openai/gpt-4o-mini"

def setup_logging():
    """Set up logging with timestamped log file."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_filename = f"torchsharp_issue_comments_{timestamp}.log"
    
    # Create logs directory if it doesn't exist
    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    log_filepath = os.path.join(log_dir, log_filename)
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(message)s',
        handlers=[
            logging.FileHandler(log_filepath),
            logging.StreamHandler()  # Also log to console
        ]
    )
    
    return log_filepath

def get_old_issues(days_threshold=DAYS_THRESHOLD):
    """Fetch issues that haven't been updated in more than the specified number of days."""
    cutoff_date = datetime.utcnow() - timedelta(days=days_threshold)
    cutoff_str = cutoff_date.strftime("%Y-%m-%dT%H:%M:%SZ")
    
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

    url = f"{GITHUB_API_BASE}/repos/{REPO_OWNER}/{REPO_NAME}/issues"
    params = {
        "state": "open",
        "sort": "updated",
        "direction": "asc",
        "per_page": 100
    }
    
    old_issues = []
    page = 1
    
    while True:
        params["page"] = page
        response = requests.get(url, headers=headers, params=params)
        
        if response.status_code != 200:
            logging.error(f"Error fetching issues: {response.status_code}")
            break
            
        issues = response.json()
        if not issues:
            break
            
        for issue in issues:
            if "pull_request" in issue:
                continue
                
            updated_at = datetime.strptime(issue["updated_at"], "%Y-%m-%dT%H:%M:%SZ")
            if updated_at < cutoff_date:
                old_issues.append(issue)
            else:
                return old_issues
                
        page += 1
        time.sleep(1)  # Rate limiting - wait between requests
        
    return old_issues

def get_issue_comments(issue_number):
    """Fetch comments for a specific issue."""
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    url = f"{GITHUB_API_BASE}/repos/{REPO_OWNER}/{REPO_NAME}/issues/{issue_number}/comments"
    response = requests.get(url, headers=headers)
    
    if response.status_code == 200:
        return response.json()
    return []

def get_issue_metadata(issue):
    """Extract labels and linked PR references from an issue."""
    labels = [label["name"] for label in issue.get("labels", [])]

    # Check for linked PRs via timeline API
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    url = f"{GITHUB_API_BASE}/repos/{REPO_OWNER}/{REPO_NAME}/issues/{issue['number']}/timeline"
    response = requests.get(url, headers=headers)

    linked_prs = []
    if response.status_code == 200:
        for event in response.json():
            if event.get("event") == "cross-referenced":
                source_issue = event.get("source", {}).get("issue", {})
                if "pull_request" in source_issue:
                    pr_title = source_issue.get("title", "")
                    pr_number = source_issue.get("number", "")
                    linked_prs.append(f"#{pr_number} ({pr_title})")

    return labels, linked_prs

def generate_personalized_comment(issue_title, issue_body, comments, issue_creator, labels, linked_prs):
    """Generate a personalized comment using GitHub Copilot Enterprise."""
    
    # Prepare context from ALL issue comments
    comments_text = ""
    if comments:
        comments_text = "\n".join(
            [f"Comment by @{c['user']['login']}: {c['body'][:300]}" for c in comments]
        )
    
    labels_text = ", ".join(labels) if labels else "None"
    prs_text = ", ".join(linked_prs) if linked_prs else "None"
    
    prompt = f"""
You are a maintainer of the {REPO_NAME} repository. You need to write a friendly, personalized comment for an old issue that hasn't been updated in over 2 years.

Issue Title: {issue_title}
Issue Description: {issue_body[:500] if issue_body else "No description provided."}
Labels: {labels_text}
Linked Pull Requests: {prs_text}
Discussion History:
{comments_text if comments_text else "No comments yet."}
Issue Creator: @{issue_creator}

Write a polite, professional comment that:
1. Starts by tagging the issue creator (@{issue_creator})
2. Acknowledges the issue and thanks the user for reporting it
3. References specific details from the issue title, description, or discussion history
4. If there are linked PRs, mention them and ask if they addressed the issue
5. If there are labels, acknowledge the categorization
6. Asks if the issue is still relevant or if it has been resolved
7. Mentions that {REPO_NAME} has evolved significantly
8. Asks for updated information if the issue is still valid
9. Keep it concise (under 150 words)

Write only the comment text, no additional formatting or explanations.
"""
    try:
        response = openai.ChatCompletion.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=200
        )
        
        return response.choices[0].message.content.strip()
        
    except Exception as e:
        logging.error(f"Error generating comment: {e}")
        return None

def post_comment_to_issue(issue_number, comment_text, max_retries=3):
    """Post a comment to a GitHub issue with retry logic."""
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json"
    }
    
    url = f"{GITHUB_API_BASE}/repos/{REPO_OWNER}/{REPO_NAME}/issues/{issue_number}/comments"
    # Prepend hidden marker so the closer script can identify bot comments
    marked_comment = f"{BOT_COMMENT_MARKER}\n{comment_text}"
    data = {"body": marked_comment}
    
    for attempt in range(max_retries):
        response = requests.post(url, headers=headers, json=data)
        
        if response.status_code == 201:
            if attempt > 0:
                logging.info(f"Issue #{issue_number}: Comment posted successfully after {attempt + 1} attempts")
            else:
                logging.info(f"Issue #{issue_number}: Comment posted successfully")
            return True
        elif response.status_code == 403 and "rate limit" in response.text.lower():
            wait_time = 60 * (attempt + 1)  # Exponential backoff
            logging.warning(f"Issue #{issue_number}: Rate limit reached on attempt {attempt + 1}. Waiting {wait_time} seconds...")
            time.sleep(wait_time)
        else:
            logging.error(f"Issue #{issue_number}: Failed to post comment on attempt {attempt + 1}. Status: {response.status_code}")
            if attempt < max_retries - 1:
                time.sleep(5)  # Wait 5 seconds before retry
    
    logging.error(f"Issue #{issue_number}: Failed to post comment after {max_retries} attempts")
    return False

def main():
    # Set up logging
    log_filepath = setup_logging()
    logging.info(f"TorchSharp Issue Comments Script Started - Log file: {log_filepath}")
    logging.info(f"Using days threshold: {DAYS_THRESHOLD} days")
    
    logging.info("Fetching old issues from TorchSharp repository...")
    old_issues = get_old_issues()
    
    logging.info(f"Found {len(old_issues)} issues that haven't been updated in over {DAYS_THRESHOLD} days")
    
    if not old_issues:
        logging.info("No old issues found!")
        return
    
    # Process all old issues (remove limit for production)
    processed_count = 0
    
    for issue in old_issues:
        issue_number = issue["number"]
        issue_title = issue["title"]
        issue_body = issue["body"] or ""
        issue_creator = issue["user"]["login"]
        
        logging.info(f"Processing issue #{issue_number}: {issue_title[:50]}...")
        
        # Get issue comments and metadata
        comments = get_issue_comments(issue_number)
        
        # Skip if we already left a bot comment on this issue
        if any(BOT_COMMENT_MARKER in c["body"] for c in comments):
            logging.info(f"Issue #{issue_number}: Already has bot comment, skipping")
            continue
        
        labels, linked_prs = get_issue_metadata(issue)
        
        # Generate personalized comment
        comment_text = generate_personalized_comment(issue_title, issue_body, comments, issue_creator, labels, linked_prs)
        
        if comment_text:
            logging.info(f"Issue #{issue_number}: Generated comment preview: {comment_text[:100]}...")
            success = post_comment_to_issue(issue_number, comment_text)
            if success:
                processed_count += 1
                time.sleep(2)
            else:
                logging.error(f"Issue #{issue_number}: Failed to process comment")
        else:
            logging.error(f"Issue #{issue_number}: Failed to generate comment")
        
        time.sleep(1)  # Rate limiting between issues
    
    logging.info(f"Script completed. Successfully processed {processed_count} issues")
    logging.info(f"Log file saved: {log_filepath}")

if __name__ == "__main__":
    main()