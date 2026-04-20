#!/usr/bin/env python3
"""Continuation script - continues scraping from where left off."""

import os
import re
import csv
import time
import requests

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}

OUTPUT_FILE = "texas_github_users.csv"
EMAIL_PATTERN = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
NOREPLY_PATTERN = re.compile(r'noreply@github\.com', re.IGNORECASE)

REQUEST_DELAY = 0.3


def is_valid_email(email):
    return email and bool(EMAIL_PATTERN.match(email)) and not NOREPLY_PATTERN.search(email)


def search_users(query, page=1, per_page=100):
    url = "https://api.github.com/search/users"
    params = {"q": query, "page": page, "per_page": per_page, "sort": "created", "order": "asc"}
    r = requests.get(url, headers=HEADERS, params=params)
    r.raise_for_status()
    data = r.json()
    return data.get("items", []), data.get("total_count", 0)


def get_user(username):
    r = requests.get(f"https://api.github.com/users/{username}", headers=HEADERS)
    if r.status_code == 200:
        return r.json()
    return None


def get_user_repos(username, max_repos=5):
    r = requests.get(f"https://api.github.com/users/{username}/repos", 
                   headers=HEADERS, params={"type": "owner", "per_page": max_repos})
    if r.status_code != 200:
        return []
    return [repo for repo in r.json() if not repo.get("fork")][:max_repos]


def get_commit_emails(owner, repo, max_commits=20):
    emails = set()
    try:
        r = requests.get(f"https://api.github.com/repos/{owner}/{repo}/commits",
                         headers=HEADERS, params={"per_page": min(100, max_commits)})
        if r.status_code != 200:
            return []
        
        commits = r.json()
        for commit in commits[:5]:
            sha = commit.get("sha")
            if sha:
                cr = requests.get(f"https://api.github.com/repos/{owner}/{repo}/commits/{sha}",
                                 headers=HEADERS)
                if cr.status_code == 200:
                    c = cr.json()
                    author = c.get("author", {})
                    if author and author.get("email"):
                        email = author["email"]
                        if is_valid_email(email):
                            emails.add(email)
                    ci = c.get("commit", {}).get("author", {})
                    if ci and ci.get("email"):
                        email = ci["email"]
                        if is_valid_email(email):
                            emails.add(email)
                    if emails:
                        break
        return list(emails)[:3]
    except:
        return []


def find_email(username):
    user = get_user(username)
    if not user:
        return None
    
    email = user.get("email")
    if is_valid_email(email):
        return email
    
    repos = get_user_repos(username)
    for repo in repos:
        owner = repo.get("owner", {}).get("login")
        repo_name = repo.get("name")
        if owner and repo_name:
            emails = get_commit_emails(owner, repo_name)
            if emails:
                return emails[0]
    
    return None


def save_row(data):
    file_exists = os.path.exists(OUTPUT_FILE)
    with open(OUTPUT_FILE, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["name", "email", "github_url"])
        if not file_exists:
            writer.writeheader()
        writer.writerow(data)


def load_processed():
    processed = set()
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                url = row.get("github_url", "")
                if url:
                    processed.add(url.split("/")[-1])
    return processed


def clean_noreply():
    """Remove noreply emails from CSV."""
    rows = []
    with open(OUTPUT_FILE, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            email = row.get("email", "")
            if not NOREPLY_PATTERN.search(email):
                rows.append(row)
    
    with open(OUTPUT_FILE, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["name", "email", "github_url"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"Cleaned. {len(rows)} rows remaining.")


from datetime import datetime, timedelta


def run_scraper(location, created_filter, processed):
    """Run scraper for a given location and date filter."""
    page = 1
    
    while True:
        users, total = search_users(f"location:{location} created:{created_filter}", page=page)
        
        if not users:
            break
        
        print(f"  Page {page}: {len(users)} users", flush=True)
        
        for user in users:
            username = user.get("login")
            
            if username in processed:
                continue
            
            try:
                email = find_email(username)
                
                if email:
                    user_data = get_user(username)
                    name = user_data.get("name", username) if user_data else username
                    url = user_data.get("html_url", f"https://github.com/{username}") if user_data else f"https://github.com/{username}"
                    
                    data = {"name": name, "email": email, "github_url": url}
                    save_row(data)
                    processed.add(username)
                    print(f"    {username}: {email}", flush=True)
                else:
                    processed.add(username)
                    print(f"    {username}: no email", flush=True)
                
                time.sleep(REQUEST_DELAY)
                
            except Exception as e:
                print(f"    Error: {e}", flush=True)
                processed.add(username)
                continue
        
        if len(users) < 100 or page * 100 >= 1000:
            break
        
        page += 1
        time.sleep(REQUEST_DELAY)


def main():
    print("GitHub Texas Email Scraper - Continuation")
    print("=" * 50)
    
    # Load processed
    processed = load_processed()
    print(f"Already processed: {len(processed)} users")
    
    locations = ["TX", "Texas"]
    
    # Phase 1: Remaining users before 2009
    print("\n=== Phase 1: Users created <2009-01-01 (remaining) ===")
    for loc in locations:
        print(f"\n{loc}:", flush=True)
        run_scraper(loc, "<2009-01-01", processed)
        time.sleep(REQUEST_DELAY)
    
    # Phase 2: Monthly searches
    print("\n=== Phase 2: Monthly (2009-01 to 2022-12) ===")
    
    current = datetime(2009, 1, 1)
    end = datetime(2022, 12, 31)
    month_num = 0
    total_months = (2022 - 2009) * 12 + 12
    
    while current <= end:
        next_month = current + timedelta(days=32)
        next_month = next_month.replace(day=1)
        if next_month > end:
            next_month = end + timedelta(days=1)
        
        month_str = current.strftime("%Y-%m")
        date_filter = f"{current.strftime('%Y-%m-%d')}..{(next_month - timedelta(days=1)).strftime('%Y-%m-%d')}"
        
        month_num += 1
        print(f"\n--- Month {month_num}/{total_months}: {month_str} ---", flush=True)
        
        for loc in locations:
            print(f"\n{loc} {month_str}:", flush=True)
            try:
                run_scraper(loc, date_filter, processed)
            except Exception as e:
                print(f"Error: {e}", flush=True)
            time.sleep(REQUEST_DELAY)
        
        current = next_month
        
        # Check if we have enough results
        clean_noreply()
        
        # Stop at 50 months for demo (can continue later)
        if month_num >= 50:
            print("Stopping at 50 months (demo limit)")
            break
    
    # Final cleanup
    clean_noreply()
    
    # Count results
    with open(OUTPUT_FILE, "r") as f:
        count = sum(1 for _ in f) - 1
    
    print(f"\n=== Done! {count} total emails found ===")
    print(f"Results saved to: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()