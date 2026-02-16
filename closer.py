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

# Days threshold for checking if issue should be closed after comment (default: 14 days)
CLOSE_THRESHOLD_DAYS = int(os.getenv("CLOSE_THRESHOLD_DAYS", "14"))

REPO_OWNER = os.getenv("REPO_OWNER", "dotnet")
REPO_NAME = os.getenv("REPO_NAME", "TorchSharp")
GITHUB_API_BASE = "https://api.github.com"

BOT_COMMENT_MARKER = "<!-- issue-commenter-bot -->"

# GitHub Copilot Enterprise configuration
openai.api_key = GITHUB_TOKEN
openai.api_base = "https://models.github.ai/inference"
openai.api_type = "open_ai"

model = "openai/gpt-4o-mini"

def setup_logging():
    """Set up logging with timestamped log file."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_filename = f"torchsharp_issue_closer_{timestamp}.log"
    
    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    log_filepath = os.path.join(log_dir, log_filename)
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(message)s',
        handlers=[
            logging.FileHandler(log_filepath),
            logging.StreamHandler()
        ]
    )
    
    return log_filepath

def get_authenticated_username():
    """Get the username of the authenticated user."""
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    response = requests.get(f"{GITHUB_API_BASE}/user", headers=headers)
    if response.status_code == 200:
        return response.json()["login"]
    logging.error(f"Failed to get authenticated user: {response.status_code}")
    return None

def find_issues_with_bot_comments(username):
    """Search for open issues where the authenticated user left a bot-marked comment."""
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    # Search for open issues where the user has commented
    search_url = f"{GITHUB_API_BASE}/search/issues"
    query = f"repo:{REPO_OWNER}/{REPO_NAME} is:issue is:open commenter:{username}"
    params = {"q": query, "per_page": 100, "sort": "updated", "order": "asc"}
    
    results = []
    page = 1
    
    while True:
        params["page"] = page
        response = requests.get(search_url, headers=headers, params=params)
        
        if response.status_code != 200:
            logging.error(f"Search API error: {response.status_code} - {response.text}")
            break
        
        data = response.json()
        items = data.get("items", [])
        if not items:
            break
        
        for issue in items:
            issue_number = issue["number"]
            # Fetch comments and find the most recent bot-marked comment
            comments_url = f"{GITHUB_API_BASE}/repos/{REPO_OWNER}/{REPO_NAME}/issues/{issue_number}/comments"
            comments_response = requests.get(comments_url, headers=headers)
            
            if comments_response.status_code != 200:
                continue
            
            comments = comments_response.json()
            bot_comment = None
            for comment in reversed(comments):
                if comment["user"]["login"] == username and BOT_COMMENT_MARKER in comment["body"]:
                    bot_comment = comment
                    break
            
            if bot_comment:
                results.append((issue_number, issue, bot_comment, comments))
            
            time.sleep(0.5)
        
        page += 1
        if page > 10:
            break
        time.sleep(1)
    
    return results

def has_new_activity_after_comment(bot_comment, all_comments, issue):
    """Check if there are any comments or issue updates after the bot comment."""
    bot_comment_date = datetime.strptime(bot_comment["created_at"], "%Y-%m-%dT%H:%M:%SZ")
    
    # Check for new comments after the bot comment
    for comment in all_comments:
        if comment["id"] == bot_comment["id"]:
            continue
        comment_date = datetime.strptime(comment["created_at"], "%Y-%m-%dT%H:%M:%SZ")
        if comment_date > bot_comment_date:
            return True
    
    return False

def generate_personalized_close_comment(issue_title, issue_body, issue_creator, days_since_comment):
    """Generate a personalized closing comment using GitHub Copilot Enterprise."""
    
    prompt = f"""
You are a maintainer of the {REPO_NAME} repository. You need to write a friendly, professional comment before closing an old issue that hasn't received any response after you asked for updates {days_since_comment} days ago.

Issue Title: {issue_title}
Issue Description: {issue_body[:300] if issue_body else "No description provided."}
Issue Creator: @{issue_creator}
Days since our status request: {days_since_comment}

Write a polite, professional comment that:
1. Starts by tagging the issue creator (@{issue_creator})
2. References that you asked for an update {days_since_comment} days ago
3. Mentions that since there's been no response, you're assuming the issue is resolved or no longer relevant
4. Thanks them for their original contribution
5. Mentions they can always reopen if the issue persists
6. Keep it concise (under 120 words)

Write only the comment text, no additional formatting or explanations.
"""
    
    try:
        response = openai.ChatCompletion.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=150
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logging.error(f"Error generating close comment: {e}")
        return None

def close_issue(issue_number, close_comment, max_retries=3):
    """Close an issue with a personalized comment."""
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json"
    }
    
    # Post the closing comment
    comment_url = f"{GITHUB_API_BASE}/repos/{REPO_OWNER}/{REPO_NAME}/issues/{issue_number}/comments"
    comment_data = {"body": close_comment}
    
    for attempt in range(max_retries):
        comment_response = requests.post(comment_url, headers=headers, json=comment_data)
        if comment_response.status_code == 201:
            logging.info(f"Issue #{issue_number}: Posted closing comment")
            break
        elif comment_response.status_code == 403 and "rate limit" in comment_response.text.lower():
            wait_time = 60 * (attempt + 1)
            logging.warning(f"Issue #{issue_number}: Rate limit on attempt {attempt + 1}. Waiting {wait_time}s...")
            time.sleep(wait_time)
        else:
            logging.error(f"Issue #{issue_number}: Failed to post closing comment. Status: {comment_response.status_code}")
            if attempt < max_retries - 1:
                time.sleep(5)
    else:
        logging.error(f"Issue #{issue_number}: Failed to post closing comment after {max_retries} attempts")
        return False
    
    # Close the issue
    close_url = f"{GITHUB_API_BASE}/repos/{REPO_OWNER}/{REPO_NAME}/issues/{issue_number}"
    close_data = {"state": "closed", "state_reason": "not_planned"}
    
    close_response = requests.patch(close_url, headers=headers, json=close_data)
    if close_response.status_code == 200:
        logging.info(f"Issue #{issue_number}: Issue closed successfully")
        return True
    else:
        logging.error(f"Issue #{issue_number}: Failed to close issue. Status: {close_response.status_code}")
        return False

def main():
    log_filepath = setup_logging()
    logging.info(f"TorchSharp Issue Closer Script Started - Log file: {log_filepath}")
    logging.info(f"Repository: {REPO_OWNER}/{REPO_NAME}")
    logging.info(f"Close threshold: {CLOSE_THRESHOLD_DAYS} days")
    
    # Get authenticated username
    username = get_authenticated_username()
    if not username:
        logging.error("Could not determine authenticated user. Exiting.")
        return
    logging.info(f"Authenticated as: {username}")
    
    # Find issues with bot comments via GitHub API
    logging.info("Searching for issues with bot comments...")
    issues_with_bot_comments = find_issues_with_bot_comments(username)
    
    if not issues_with_bot_comments:
        logging.info("No issues with bot comments found.")
        return
    
    logging.info(f"Found {len(issues_with_bot_comments)} issues with bot comments")
    
    close_threshold_date = datetime.utcnow() - timedelta(days=CLOSE_THRESHOLD_DAYS)
    issues_to_close = []
    
    for issue_number, issue, bot_comment, all_comments in issues_with_bot_comments:
        comment_date = datetime.strptime(bot_comment["created_at"], "%Y-%m-%dT%H:%M:%SZ")
        days_ago = (datetime.utcnow() - comment_date).days
        
        if comment_date > close_threshold_date:
            logging.info(f"Issue #{issue_number}: Too recent (commented {days_ago} days ago)")
            continue
        
        logging.info(f"Checking issue #{issue_number} (commented {days_ago} days ago)...")
        
        if has_new_activity_after_comment(bot_comment, all_comments, issue):
            logging.info(f"Issue #{issue_number}: Has new activity since bot comment, skipping")
            continue
        
        issues_to_close.append((issue_number, issue, days_ago))
    
    logging.info(f"Found {len(issues_to_close)} issues to close")
    
    if not issues_to_close:
        logging.info("No issues need to be closed at this time.")
        return
    
    closed_count = 0
    
    for issue_number, issue, days_since_comment in issues_to_close:
        issue_title = issue["title"]
        issue_body = issue.get("body") or ""
        issue_creator = issue["user"]["login"]
        
        logging.info(f"Closing issue #{issue_number}: {issue_title[:50]}...")
        
        close_comment = generate_personalized_close_comment(
            issue_title, issue_body, issue_creator, days_since_comment
        )
        
        if close_comment:
            success = close_issue(issue_number, close_comment)
            if success:
                closed_count += 1
                time.sleep(2)
            else:
                logging.error(f"Issue #{issue_number}: Failed to close")
        else:
            logging.error(f"Issue #{issue_number}: Failed to generate closing comment")
        
        time.sleep(1)
    
    logging.info(f"Script completed. Successfully closed {closed_count} issues")
    logging.info(f"Log file saved: {log_filepath}")

if __name__ == "__main__":
    main()
