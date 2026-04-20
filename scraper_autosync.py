#!/usr/bin/env python3
"""
Google Sheets Auto-Sync Scraper

This scraper saves each new lead to Google Sheets immediately as it's found.
Requires: pip install google-api-python-client google-auth-oauthlib

Setup:
1. Go to Google Cloud Console → APIs → Enable Sheets API
2. Create Service Account → Download JSON key
3. Share your Google Sheet with the service account email
4. Set GOOGLE_APPLICATION_CREDENTIALS environment variable
"""

import os
import re
import csv
import time
import requests
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Set

# GitHub API configuration
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
if not GITHUB_TOKEN:
    raise ValueError("GITHUB_TOKEN environment variable is required")

HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}

# Email patterns
EMAIL_PATTERN = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
NOREPLY_PATTERN = re.compile(r'noreply@github\.com', re.IGNORECASE)

REQUEST_DELAY = 0.3
OUTPUT_FILE = "texas_github_users.csv"

# Google Sheets configuration
SPREADSHEET_ID = os.environ.get("GOOGLE_SHEET_ID")  # Your Google Sheet ID
RANGE = "Sheet1!A:C"  # Columns A, B, C (name, email, github_url)


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


def get_commit_emails(owner, repo):
    emails = set()
    try:
        r = requests.get(f"https://api.github.com/repos/{owner}/{repo}/commits",
                         headers=HEADERS, params={"per_page": 10})
        if r.status_code != 200:
            return []
        
        commits = r.json()
        for commit in commits[:3]:
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
        return list(emails)[:1]
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


def save_to_csv(data):
    """Save to local CSV file."""
    file_exists = os.path.exists(OUTPUT_FILE)
    with open(OUTPUT_FILE, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["name", "email", "github_url"])
        if not file_exists:
            writer.writeheader()
        writer.writerow(data)


def save_to_google_sheet(data):
    """Save to Google Sheets (requires setup)."""
    try:
        from googleapiclient.discovery import build
        from google.oauth2 import service_account
        
        # Check for credentials
        creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        if not creds_path or not os.path.exists(creds_path):
            print(f"  [CSV only] {data['email']}")
            return
        
        # Build service
        creds = service_account.Credentials.from_service_account_file(
            creds_path, 
            scopes=['https://www.googleapis.com/auth/spreadsheets']
        )
        service = build('sheets', 'v4', credentials=creds)
        
        # Append row
        values = [[data["name"], data["email"], data["github_url"]]]
        body = {'values': values}
        
        result = service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=RANGE,
            valueInputOption='USER_ENTERED',
            body=body
        ).execute()
        
        print(f"  [Google Sheet] {data['email']}")
        
    except ImportError:
        print(f"  [CSV only] {data['email']} (google-api-python-client not installed)")
    except Exception as e:
        print(f"  [CSV only] {data['email']} (Error: {e})")


def load_processed():
    """Load already processed usernames."""
    processed = set()
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                url = row.get("github_url", "")
                if url:
                    processed.add(url.split("/")[-1])
    return processed


def run_scraper(location, created_filter, processed):
    """Run scraper for a given search."""
    page = 1
    
    while True:
        users, total = search_users(f"location:{location} created:{created_filter}", page=page)
        
        if not users:
            break
        
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
                    
                    # Save to both CSV and Google Sheets
                    save_to_csv(data)
                    save_to_google_sheet(data)
                
                processed.add(username)
                time.sleep(REQUEST_DELAY)
                
            except Exception as e:
                print(f"  Error: {e}")
                processed.add(username)
                continue
        
        if len(users) < 100 or page * 100 >= 1000:
            break
        
        page += 1
        time.sleep(REQUEST_DELAY)


def main():
    print("GitHub Texas Email Scraper - Auto-Sync Version")
    print("=" * 50)
    
    # Check Google Sheets setup
    if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        print("Google Sheets: Enabled")
    else:
        print("Google Sheets: Not configured (CSV only)")
        print("Set GOOGLE_APPLICATION_CREDENTIALS to enable")
    
    print()
    
    processed = load_processed()
    print(f"Already processed: {len(processed)} users")
    
    locations = ["TX", "Texas"]
    
    # Phase 1: Before 2009
    print("\n=== Users created <2009-01-01 ===")
    for loc in locations:
        print(f"\n{loc}:")
        run_scraper(loc, "<2009-01-01", processed)
        time.sleep(REQUEST_DELAY)
    
    # Phase 2: Monthly
    print("\n=== Monthly (2009-01 to 2022-12) ===")
    
    current = datetime(2009, 1, 1)
    end = datetime(2022, 12, 31)
    month_num = 0
    
    while current <= end:
        next_month = current + timedelta(days=32)
        next_month = next_month.replace(day=1)
        if next_month > end:
            next_month = end + timedelta(days=1)
        
        month_str = current.strftime("%Y-%m")
        date_filter = f"{current.strftime('%Y-%m-%d')}..{(next_month - timedelta(days=1)).strftime('%Y-%m-%d')}"
        
        month_num += 1
        
        for loc in locations:
            print(f"\n[{month_num}] {loc} {month_str}")
            try:
                run_scraper(loc, date_filter, processed)
            except Exception as e:
                print(f"Error: {e}")
            time.sleep(REQUEST_DELAY)
        
        current = next_month
        
        # Stop at 50 months for demo
        if month_num >= 50:
            print("Stopping at 50 months")
            break
    
    print(f"\nDone! Results in {OUTPUT_FILE}")


if __name__ == "__main__":
    main()