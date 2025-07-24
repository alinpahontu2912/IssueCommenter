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
DAYS_THRESHOLD = int(os.getenv("DAYS_THRESHOLD", "730"))

REPO_OWNER = "dotnet"
REPO_NAME = "TorchSharp"
GITHUB_API_BASE = "https://api.github.com"

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
    cutoff_date = datetime.now() - timedelta(days=days_threshold)
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

def generate_personalized_comment(issue_title, issue_body, comments, issue_creator):
    """Generate a personalized comment using GitHub Copilot Enterprise."""
    
    # Prepare context from issue and comments
    comments_text = ""
    if comments:
        recent_comments = comments[-3:]  # Last 3 comments for context
        comments_text = "\n".join([f"Comment: {comment['body'][:200]}..." for comment in recent_comments])
    
    prompt = f"""
You are a maintainer of the TorchSharp repository. You need to write a friendly, personalized comment for an old issue that hasn't been updated in over 2 years.

Issue Title: {issue_title}
Issue Description: {issue_body}
Recent Comments: {comments_text}
Issue Creator: @{issue_creator}

Write a polite, professional comment that:
1. Starts by tagging the issue creator (@{issue_creator})
2. Acknowledges the issue and thanks the user for reporting it
3. References specific details from the issue title or description
4. Asks if the issue is still relevant or if it has been resolved
5. Mentions that TorchSharp has evolved significantly
6. Asks for updated information if the issue is still valid
7. Keep it concise (under 150 words)

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
    data = {"body": comment_text}
    
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
        
        # Get issue comments
        comments = get_issue_comments(issue_number)
        
        # Generate personalized comment
        comment_text = generate_personalized_comment(issue_title, issue_body, comments, issue_creator)
        
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