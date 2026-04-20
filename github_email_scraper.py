#!/usr/bin/env python3
"""
GitHub User Email Scraper for Texas Users

This script scrapes GitHub users in Texas and extracts their email addresses:
1. Search users by location (Texas/TX) and creation date
2. For each user, try to get public email
3. If no public email, search commit metadata from their repos
4. Skip noreply emails and validate addresses
5. Output to CSV for Google Sheets
"""

import os
import re
import csv
import time
import json
import base64
from datetime import datetime, timedelta
from typing import Optional, List, Dict
import requests

# GitHub API configuration
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
if not GITHUB_TOKEN:
    raise ValueError("GITHUB_TOKEN environment variable is required")

HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json",
    "User-Agent": "GitHub-Email-Scraper"
}

API_BASE = "https://api.github.com"

# Output file
OUTPUT_FILE = "texas_github_users.csv"

# Configuration - can use TX or Texas as location
LOCATIONS = ["TX", "Texas"]

# Email regex pattern for validation
EMAIL_PATTERN = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')

# noreply email pattern to skip
NOREPLY_PATTERN = re.compile(r'noreply@github\.com', re.IGNORECASE)


def search_users_by_location_and_created(location: str, created_filter: str, page: int = 1, per_page: int = 100) -> List[Dict]:
    """Search GitHub users by location and creation date filter.
    
    created_filter examples:
        - "2008-01-01..2008-01-31" (specific month)
        - "<2009-01-01" (before a date)
    """
    query = f"location:{location} created:{created_filter}"
    url = f"{API_BASE}/search/users"
    params = {
        "q": query,
        "page": page,
        "per_page": per_page,
        "sort": "created",
        "order": "asc"
    }
    
    response = requests.get(url, headers=HEADERS, params=params)
    response.raise_for_status()
    data = response.json()
    
    return data.get("items", [])


def get_user_details(username: str) -> Optional[Dict]:
    """Get detailed user information."""
    url = f"{API_BASE}/users/{username}"
    response = requests.get(url, headers=HEADERS)
    
    if response.status_code == 200:
        return response.json()
    return None


def get_user_public_email(username: str) -> Optional[str]:
    """Get user's public email address."""
    user = get_user_details(username)
    if user and user.get("email"):
        email = user["email"]
        if is_valid_email(email) and not is_noreply_email(email):
            return email
    return None


def get_user_repositories(username: str, max_repos: int = 100) -> List[Dict]:
    """Get user's public repositories."""
    url = f"{API_BASE}/users/{username}/repos"
    params = {
        "type": "owner",  # Only user's own repos, not forks
        "sort": "updated",
        "per_page": min(100, max_repos),
        "direction": "desc"
    }
    
    response = requests.get(url, headers=HEADERS, params=params)
    if response.status_code != 200:
        return []
    
    repos = response.json()
    # Filter out forked repositories
    repos = [r for r in repos if not r.get("fork", False)]
    return repos[:max_repos]


def get_commit_emails_from_repo(owner: str, repo: str, max_commits: int = 100) -> List[str]:
    """Get email addresses from commit metadata in a repository."""
    emails = set()
    
    url = f"{API_BASE}/repos/{owner}/{repo}/commits"
    params = {
        "per_page": min(100, max_commits)
    }
    
    try:
        response = requests.get(url, headers=HEADERS, params=params)
        if response.status_code != 200:
            return list(emails)
        
        commits = response.json()
        
        for commit in commits:
            commit_sha = commit.get("sha")
            if commit_sha:
                commit_url = f"{API_BASE}/repos/{owner}/{repo}/commits/{commit_sha}"
                commit_response = requests.get(commit_url, headers=HEADERS)
                
                if commit_response.status_code == 200:
                    commit_data = commit_response.json()
                    author = commit_data.get("author", {})
                    if author and author.get("email"):
                        email = author["email"]
                        if is_valid_email(email) and not is_noreply_email(email):
                            emails.add(email)
                    
                    # Also check commit info
                    commit_info = commit_data.get("commit", {})
                    if commit_info:
                        author_info = commit_info.get("author", {})
                        if author_info and author_info.get("email"):
                            email = author_info["email"]
                            if is_valid_email(email) and not is_noreply_email(email):
                                emails.add(email)
        
        # Limit to reasonable number
        return list(emails)[:10]
        
    except Exception as e:
        print(f"  Error getting commits from {owner}/{repo}: {e}")
        return list(emails)


def is_valid_email(email: str) -> bool:
    """Validate email format."""
    if not email:
        return False
    return bool(EMAIL_PATTERN.match(email))


def is_noreply_email(email: str) -> bool:
    """Check if email is a noreply address."""
    if not email:
        return False
    return bool(NOREPLY_PATTERN.search(email))


def generate_date_ranges(start_date: str, end_date: str) -> List[str]:
    """Generate monthly date ranges for searching."""
    ranges = []
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    
    current = start
    while current <= end:
        next_month = current + timedelta(days=32)
        next_month = next_month.replace(day=1)
        
        if next_month > end:
            next_month = end + timedelta(days=1)
        
        # Format: created:YYYY-MM-DD..YYYY-MM-DD
        range_str = f"{current.strftime('%Y-%m-%d')}..{(next_month - timedelta(days=1)).strftime('%Y-%m-%d')}"
        ranges.append(range_str)
        
        current = next_month
    
    return ranges


def scrape_user_email(username: str) -> Optional[str]:
    """Scrape email from a user's profile or repositories."""
    # First try to get public email
    public_email = get_user_public_email(username)
    if public_email:
        return public_email
    
    # If no public email, search through repositories
    repos = get_user_repositories(username, max_repos=20)
    
    for repo in repos:
        owner = repo.get("owner", {}).get("login")
        repo_name = repo.get("name")
        
        if not owner or not repo_name:
            continue
        
        emails = get_commit_emails_from_repo(owner, repo_name, max_commits=50)
        
        if emails:
            return emails[0]
    
    return None


def process_users_batch(users: List[Dict], processed_usernames: set) -> List[Dict]:
    """Process a batch of users and collect their information."""
    results = []
    
    for user in users:
        username = user.get("login")
        
        if username in processed_usernames:
            continue
        
        print(f"Processing user: {username}")
        
        try:
            # Get public email first
            email = get_user_public_email(username)
            
            # If no public email, try from commits
            if not email:
                email = scrape_user_email(username)
            
            if email:
                user_details = get_user_details(username)
                name = user_details.get("name", username) if user_details else username
                github_url = user_details.get("html_url", f"https://github.com/{username}") if user_details else f"https://github.com/{username}"
                
                results.append({
                    "name": name,
                    "email": email,
                    "github_url": github_url
                })
                print(f"  Found email: {email}")
            
            processed_usernames.add(username)
            
            # Rate limiting
            time.sleep(0.5)
            
        except Exception as e:
            print(f"  Error processing {username}: {e}")
            processed_usernames.add(username)
            continue
    
    return results


def save_to_csv(data: List[Dict], filename: str):
    """Save data to CSV file."""
    if not data:
        print("No data to save")
        return
    
    fieldnames = ["name", "email", "github_url"]
    
    with open(filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(data)
    
    print(f"Saved {len(data)} records to {filename}")


def append_to_csv(data: List[Dict], filename: str):
    """Append data to CSV file."""
    if not data:
        return
    
    fieldnames = ["name", "email", "github_url"]
    file_exists = os.path.exists(filename)
    
    with open(filename, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerows(data)


def get_total_user_count(location: str, created_date: str) -> int:
    """Get total count of users matching search criteria."""
    query = f"location:{location} created:{created_date}"
    url = f"{API_BASE}/search/users"
    params = {
        "q": query,
        "per_page": 1
    }
    
    response = requests.get(url, headers=HEADERS, params=params)
    response.raise_for_status()
    data = response.json()
    
    return data.get("total_count", 0)


def main():
    """Main function to scrape GitHub users in Texas."""
    print("GitHub Email Scraper for Texas Users")
    print("=" * 50)
    
    # Configuration
    end_date = "2022-12-31"
    start_date = "2008-01-01"  # GitHub launched in 2008
    
    print(f"Location: Texas and TX")
    print(f"Date range: {start_date} to {end_date}")
    print()
    
    # Track processed users
    processed_usernames = set()
    all_results = []
    
    # First: search users created before 2009-01-01 (should be less than 1K)
    print("\n=== Phase 1: Users created before 2009-01-01 ===")
    for location in LOCATIONS:
        print(f"\n--- Searching {location} users created before 2009-01-01 ---")
        try:
            users = search_users_by_location_and_created(location, "<2009-01-01")
            print(f"  Found {len(users)} users")
            
            if users:
                results = process_users_batch(users, processed_usernames)
                all_results.extend(results)
                print(f"  Found {len(results)} emails")
        except Exception as e:
            print(f"  Error: {e}")
    
    # Second: search monthly from 2009-01-01 to 2022-12-31
    print("\n=== Phase 2: Users created by month (2009-01 to 2022-12) ===")
    current = datetime(2009, 1, 1)
    end = datetime(2022, 12, 31)
    month_count = 0
    total_months = (2022 - 2009) * 12 + 12  # ~168 months
    
    while current <= end:
        # Calculate end of this month
        next_month = current + timedelta(days=32)
        next_month = next_month.replace(day=1)
        
        if next_month > end:
            next_month = end + timedelta(days=1)
        
        month_str = current.strftime("%Y-%m")
        date_filter = f"{current.strftime('%Y-%m-%d')}..{(next_month - timedelta(days=1)).strftime('%Y-%m-%d')}"
        
        month_count += 1
        
        for location in LOCATIONS:
            try:
                print(f"\n  [{month_count}/{total_months}] {location} - {month_str}")
                users = search_users_by_location_and_created(location, date_filter)
                
                if users:
                    print(f"    Found {len(users)} users")
                    
                    # Process users - limit to avoid going over 1K per query
                    if len(users) >= 1000:
                        print(f"    WARNING: More than 1000 users, processing first 100")
                        users = users[:100]
                    
                    results = process_users_batch(users, processed_usernames)
                    all_results.extend(results)
                    
                    if results:
                        append_to_csv(results, OUTPUT_FILE)
                        print(f"    Found {len(results)} emails")
                else:
                    print(f"    No users found")
                
                time.sleep(0.5)  # Rate limiting
                
            except Exception as e:
                print(f"    Error: {e}")
                continue
        
        current = next_month
    
    # Final save with all results
    print(f"\n=== Final Results ===")
    print(f"Total unique users processed: {len(processed_usernames)}")
    print(f"Total valid emails found: {len(all_results)}")
    
    save_to_csv(all_results, OUTPUT_FILE)
    
    print(f"\nScraping complete! Results saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()