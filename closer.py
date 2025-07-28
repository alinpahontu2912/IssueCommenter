import openai
import requests
import json
from datetime import datetime, timedelta
import time
import logging
import os
import re
import glob

# GitHub API configuration
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
if not GITHUB_TOKEN:
    raise ValueError("GITHUB_TOKEN environment variable is required")

# Days threshold for checking if issue should be closed after comment (default: 30 days)
CLOSE_THRESHOLD_DAYS = int(os.getenv("CLOSE_THRESHOLD_DAYS", "30"))

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
    log_filename = f"torchsharp_issue_closer_{timestamp}.log"
    
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

def get_latest_commenter_log():
    """Find the most recent commenter log file."""
    log_dir = "logs"
    if not os.path.exists(log_dir):
        return None
    
    # Look for torchsharp_issue_comments_*.log files
    pattern = os.path.join(log_dir, "torchsharp_issue_comments_*.log")
    log_files = glob.glob(pattern)
    
    if not log_files:
        return None
    
    # Sort by modification time and get the latest
    latest_log = max(log_files, key=os.path.getmtime)
    return latest_log

def parse_commented_issues_from_log(log_file_path):
    """Parse the log file to extract successfully commented issue numbers and their comment dates."""
    commented_issues = {}
    
    try:
        with open(log_file_path, 'r', encoding='utf-8') as f:
            for line in f:
                # Look for successful comment posts
                if "Comment posted successfully" in line:
                    # Extract issue number from lines like: "Issue #123: Comment posted successfully"
                    match = re.search(r'Issue #(\d+): Comment posted successfully', line)
                    if match:
                        issue_number = int(match.group(1))
                        # Extract timestamp from the beginning of the log line
                        timestamp_match = re.match(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})', line)
                        if timestamp_match:
                            timestamp_str = timestamp_match.group(1)
                            # Parse the timestamp (adjust format as needed)
                            try:
                                comment_date = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S,%f")
                                commented_issues[issue_number] = comment_date
                            except ValueError:
                                # If timestamp parsing fails, use current time as fallback
                                commented_issues[issue_number] = datetime.now()
    except Exception as e:
        logging.error(f"Error parsing log file {log_file_path}: {e}")
    
    return commented_issues

def get_issue_details(issue_number):
    """Fetch details for a specific issue."""
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    url = f"{GITHUB_API_BASE}/repos/{REPO_OWNER}/{REPO_NAME}/issues/{issue_number}"
    response = requests.get(url, headers=headers)
    
    if response.status_code == 200:
        return response.json()
    return None

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

def check_if_issue_updated_after_comment(issue_number, comment_date):
    """Check if the issue has been updated after our comment."""
    issue = get_issue_details(issue_number)
    if not issue:
        return False, None
    
    # Check if issue is already closed
    if issue["state"] == "closed":
        logging.info(f"Issue #{issue_number}: Already closed")
        return False, issue
    
    # Check issue update time
    issue_updated_at = datetime.strptime(issue["updated_at"], "%Y-%m-%dT%H:%M:%SZ")
    
    # Get comments to check for any new activity
    comments = get_issue_comments(issue_number)
    
    # Check if there are any comments after our comment
    new_activity = False
    for comment in comments:
        comment_created_at = datetime.strptime(comment["created_at"], "%Y-%m-%dT%H:%M:%SZ")
        if comment_created_at > comment_date:
            new_activity = True
            break
    
    # Also check if the issue itself was updated after our comment
    if issue_updated_at > comment_date:
        new_activity = True
    
    return new_activity, issue

def generate_personalized_close_comment(issue_title, issue_body, issue_creator, days_since_comment):
    """Generate a personalized closing comment using GitHub Copilot Enterprise."""
    
    prompt = f"""
        You are a maintainer of the TorchSharp repository. You need to write a friendly, professional comment before closing an old issue that hasn't received any response after you asked for updates {days_since_comment} days ago.

        Issue Title: {issue_title}
        Issue Description: {issue_body[:300]}...
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

def close_issue(issue_number, close_comment):
    """Close an issue with a comment (currently commented out for safety)."""
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json"
    }
    
    # First post the closing comment
    comment_url = f"{GITHUB_API_BASE}/repos/{REPO_OWNER}/{REPO_NAME}/issues/{issue_number}/comments"
    comment_data = {"body": close_comment}
    
    logging.info(f"Issue #{issue_number}: WOULD POST CLOSING COMMENT: {close_comment[:100]}...")
    
    # Commented out for safety - uncomment when ready to actually close issues
    # comment_response = requests.post(comment_url, headers=headers, json=comment_data)
    # if comment_response.status_code != 201:
    #     logging.error(f"Issue #{issue_number}: Failed to post closing comment")
    #     return False
    
    # Then close the issue
    close_url = f"{GITHUB_API_BASE}/repos/{REPO_OWNER}/{REPO_NAME}/issues/{issue_number}"
    close_data = {"state": "closed"}
    
    logging.info(f"Issue #{issue_number}: WOULD CLOSE ISSUE")
    
    # Commented out for safety - uncomment when ready to actually close issues
    # close_response = requests.patch(close_url, headers=headers, json=close_data)
    # if close_response.status_code == 200:
    #     logging.info(f"Issue #{issue_number}: Issue closed successfully")
    #     return True
    # else:
    #     logging.error(f"Issue #{issue_number}: Failed to close issue")
    #     return False
    
    return True  # Return True for simulation

def main():
    # Set up logging
    log_filepath = setup_logging()
    logging.info(f"TorchSharp Issue Closer Script Started - Log file: {log_filepath}")
    logging.info(f"Using close threshold: {CLOSE_THRESHOLD_DAYS} days")
    
    # Find the latest commenter log file
    latest_log = get_latest_commenter_log()
    if not latest_log:
        logging.error("No commenter log file found. Please run the commenter script first.")
        return
    
    logging.info(f"Using log file: {latest_log}")
    
    # Parse commented issues from the log
    commented_issues = parse_commented_issues_from_log(latest_log)
    
    if not commented_issues:
        logging.info("No successfully commented issues found in the log file.")
        return
    
    logging.info(f"Found {len(commented_issues)} previously commented issues")
    
    close_threshold_date = datetime.now() - timedelta(days=CLOSE_THRESHOLD_DAYS)
    issues_to_close = []
    
    for issue_number, comment_date in commented_issues.items():
        # Only consider issues that were commented on more than CLOSE_THRESHOLD_DAYS ago
        if comment_date > close_threshold_date:
            logging.info(f"Issue #{issue_number}: Too recent (commented {(datetime.now() - comment_date).days} days ago)")
            continue
        
        logging.info(f"Checking issue #{issue_number} (commented {(datetime.now() - comment_date).days} days ago)...")
        
        # Check if there has been any activity since our comment
        has_new_activity, issue = check_if_issue_updated_after_comment(issue_number, comment_date)
        
        if issue is None:
            logging.error(f"Issue #{issue_number}: Could not fetch issue details")
            continue
        
        if has_new_activity:
            logging.info(f"Issue #{issue_number}: Has new activity since our comment, skipping")
            continue
        
        # This issue should be closed
        days_since_comment = (datetime.now() - comment_date).days
        issues_to_close.append((issue_number, issue, days_since_comment))
    
    logging.info(f"Found {len(issues_to_close)} issues that should be closed")
    
    if not issues_to_close:
        logging.info("No issues need to be closed at this time.")
        return
    
    # Process issues to close
    closed_count = 0
    
    for issue_number, issue, days_since_comment in issues_to_close:
        issue_title = issue["title"]
        issue_body = issue["body"] or ""
        issue_creator = issue["user"]["login"]
        
        logging.info(f"Processing issue #{issue_number}: {issue_title[:50]}...")
        
        # Generate personalized closing comment
        close_comment = generate_personalized_close_comment(
            issue_title, issue_body, issue_creator, days_since_comment
        )
        
        if close_comment:
            success = close_issue(issue_number, close_comment)
            if success:
                closed_count += 1
                time.sleep(2)  # Rate limiting
            else:
                logging.error(f"Issue #{issue_number}: Failed to close issue")
        else:
            logging.error(f"Issue #{issue_number}: Failed to generate closing comment")
        
        time.sleep(1)  # Rate limiting between issues
    
    logging.info(f"Script completed. Successfully processed {closed_count} issues for closing")
    logging.info(f"Log file saved: {log_filepath}")

if __name__ == "__main__":
    main()
