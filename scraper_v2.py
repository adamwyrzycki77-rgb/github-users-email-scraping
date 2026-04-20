#!/usr/bin/env python3
"""
GitHub User Email Scraper for Texas Users - Optimized Version

This version:
1. Uses pagination properly to handle large result sets
2. Has better rate limiting
3. Saves progress incrementally
4. Can be resumed if interrupted
"""

import os
import re
import csv
import time
import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Set
import requests

# GitHub API configuration
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
if not GITHUB_TOKEN:
    raise ValueError("GITHUB_TOKEN environment variable is required")

HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json",
    "User-Agent": "GitHub-Email-Scraper-v2"
}

API_BASE = "https://api.github.com"
OUTPUT_FILE = "texas_github_users.csv"

# Email patterns
EMAIL_PATTERN = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
NOREPLY_PATTERN = re.compile(r'noreply@github\.com', re.IGNORECASE)

# Rate limiting
REQUEST_DELAY = 0.5  # seconds between requests


def search_users(query: str, page: int = 1, per_page: int = 100) -> tuple[List[Dict], int]:
    """Search GitHub users and return results with total count."""
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
    
    return data.get("items", []), data.get("total_count", 0)


def get_user(username: str) -> Optional[Dict]:
    """Get detailed user information."""
    url = f"{API_BASE}/users/{username}"
    response = requests.get(url, headers=HEADERS)
    
    if response.status_code == 200:
        return response.json()
    return None


def get_user_repos(username: str, max_repos: int = 50) -> List[Dict]:
    """Get user's own repositories (not forks)."""
    url = f"{API_BASE}/users/{username}/repos"
    params = {
        "type": "owner",
        "sort": "updated",
        "per_page": min(100, max_repos),
        "direction": "desc"
    }
    
    response = requests.get(url, headers=HEADERS, params=params)
    if response.status_code != 200:
        return []
    
    repos = response.json()
    # Filter out forked repositories
    return [r for r in repos if not r.get("fork", False)][:max_repos]


def get_commits_with_email(owner: str, repo: str, max_commits: int = 50) -> List[str]:
    """Get unique emails from commits."""
    emails: Set[str] = set()
    
    url = f"{API_BASE}/repos/{owner}/{repo}/commits"
    params = {"per_page": min(100, max_commits)}
    
    try:
        response = requests.get(url, headers=HEADERS, params=params)
        if response.status_code != 200:
            return []
        
        commits = response.json()
        
        for commit in commits:
            sha = commit.get("sha")
            if sha:
                # Get full commit details
                commit_url = f"{API_BASE}/repos/{owner}/{repo}/commits/{sha}"
                cr = requests.get(commit_url, headers=HEADERS)
                if cr.status_code == 200:
                    cd = cr.json()
                    # Check author
                    author = cd.get("author", {})
                    if author and author.get("email"):
                        email = author["email"]
                        if is_valid_email(email) and not is_noreply(email):
                            emails.add(email)
                    # Also check commit info
                    ci = cd.get("commit", {})
                    if ci:
                        auth = ci.get("author", {})
                        if auth and auth.get("email"):
                            email = auth["email"]
                            if is_valid_email(email) and not is_noreply(email):
                                emails.add(email)
                    
                    if len(emails) >= 5:  # Enough emails found
                        break
        
        return list(emails)[:5]
        
    except Exception as e:
        print(f"    Error getting commits: {e}")
        return []


def is_valid_email(email: str) -> bool:
    return bool(email) and bool(EMAIL_PATTERN.match(email))


def is_noreply(email: str) -> bool:
    return bool(email) and bool(NOREPLY_PATTERN.search(email))


def find_user_email(username: str) -> Optional[str]:
    """Find user's email from profile or commits."""
    user = get_user(username)
    if not user:
        return None
    
    # 1. Try public email on profile
    email = user.get("email")
    if email and is_valid_email(email) and not is_noreply(email):
        return email
    
    # 2. Search through repositories for commit emails
    repos = get_user_repos(username, max_repos=10)
    
    for repo in repos:
        owner_login = repo.get("owner", {}).get("login")
        repo_name = repo.get("name")
        
        if not owner_login or not repo_name:
            continue
        
        emails = get_commits_with_email(owner_login, repo_name, max_commits=30)
        
        if emails:
            return emails[0]
    
    return None


def process_batch(users: List[Dict], processed: Set[str]) -> List[Dict]:
    """Process a batch of users."""
    results = []
    
    for user in users:
        username = user.get("login")
        
        if not username or username in processed:
            continue
        
        print(f"  Processing: {username}")
        
        try:
            email = find_user_email(username)
            
            if email:
                user_data = get_user(username)
                name = user_data.get("name", username) if user_data else username
                github_url = user_data.get("html_url", f"https://github.com/{username}") if user_data else f"https://github.com/{username}"
                
                results.append({
                    "name": name,
                    "email": email,
                    "github_url": github_url
                })
                print(f"    Found: {email}")
            
            processed.add(username)
            time.sleep(REQUEST_DELAY)
            
        except Exception as e:
            print(f"    Error: {e}")
            processed.add(username)
            continue
    
    return results


def save_results(data: List[Dict], filename: str, append: bool = False):
    """Save results to CSV."""
    if not data:
        return
    
    fieldnames = ["name", "email", "github_url"]
    
    mode = 'a' if append else 'w'
    file_exists = os.path.exists(filename) and os.path.getsize(filename) > 0
    
    with open(filename, mode, newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists or not append:
            writer.writeheader()
        writer.writerows(data)


def count_users_in_period(location: str, created_filter: str) -> int:
    """Count users in a period."""
    query = f"location:{location} created:{created_filter}"
    try:
        _, total = search_users(query, page=1, per_page=1)
        return total
    except:
        return 0


def main():
    """Main function."""
    print("GitHub Email Scraper for Texas Users (v2)")
    print("=" * 50)
    
    locations = ["TX", "Texas"]
    processed_usernames: Set[str] = set()
    all_results: List[Dict] = []
    
    # Try to load existing progress
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Extract username from URL
                url = row.get('github_url', '')
                if url:
                    username = url.split('/')[-1]
                    processed_usernames.add(username)
        print(f"Loaded {len(processed_usernames)} previously processed users")
    
    # Phase 1: Users before 2009-01-01 (< 1K by design)
    print("\n=== Phase 1: Users before 2009-01-01 ===")
    for location in locations:
        print(f"\nSearching {location} users created <2009-01-01")
        count = count_users_in_period(location, "<2009-01-01")
        print(f"  Total users: {count}")
        
        if count > 0:
            users, _ = search_users(f"location:{location} created:<2009-01-01")
            results = process_batch(users, processed_usernames)
            all_results.extend(results)
            save_results(results, OUTPUT_FILE, append=True)
            print(f"  Found {len(results)} emails")
        
        time.sleep(REQUEST_DELAY)
    
    # Phase 2: Monthly from 2009-01 to 2022-12
    print("\n=== Phase 2: Monthly searches (2009-01 to 2022-12) ===")
    current = datetime(2009, 1, 1)
    end = datetime(2022, 12, 31)
    month_num = 0
    total_months = (2022 - 2009) * 12 + 12
    
    while current <= end:
        # Calculate end of month
        next_month = current + timedelta(days=32)
        next_month = next_month.replace(day=1)
        
        if next_month > end:
            next_month = end + timedelta(days=1)
        
        month_str = current.strftime("%Y-%m")
        filter_str = f"{current.strftime('%Y-%m-%d')}..{(next_month - timedelta(days=1)).strftime('%Y-%m-%d')}"
        
        month_num += 1
        
        for location in locations:
            print(f"\n[{month_num}/{total_months}] {location} - {month_str}")
            
            try:
                count = count_users_in_period(location, filter_str)
                print(f"  Total: {count} users")
                
                if count == 0:
                    continue
                
                # Paginate if needed (max 1000 per query)
                max_pages = min(10, (count // 100) + 2)
                
                for page in range(1, max_pages + 1):
                    users, _ = search_users(f"location:{location} created:{filter_str}", page=page)
                    
                    if not users:
                        break
                    
                    print(f"  Page {page}: {len(users)} users")
                    
                    results = process_batch(users, processed_usernames)
                    all_results.extend(results)
                    
                    if results:
                        save_results(results, OUTPUT_FILE, append=True)
                        print(f"  Found {len(results)} emails")
                    
                    time.sleep(REQUEST_DELAY)
                    
                    if len(users) < 100:  # Last page
                        break
            
            except Exception as e:
                print(f"  Error: {e}")
                continue
        
        current = next_month
    
    # Final summary
    print(f"\n=== Summary ===")
    print(f"Total users processed: {len(processed_usernames)}")
    print(f"Total emails found: {len(all_results)}")
    print(f"Results saved to: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()