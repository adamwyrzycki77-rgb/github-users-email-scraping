# GitHub Texas Users Email Scraper

This project scrapes GitHub users located in Texas and collects their email addresses.

## How to Import to Google Sheets

## Quick Import to Google Sheets

### Option 1: Copy-Paste (Easiest)

1. Open this CSV in a text editor or Excel
2. Select all rows (Ctrl+A or Cmd+A)
3. Copy (Ctrl+C or Cmd+C)
4. Open Google Sheets → Paste into cell A1

### Option 2: File Import

1. Go to [Google Sheets](https://sheets.google.com) → Blank spreadsheet
2. Go to **File → Import → Upload**
3. Upload `texas_github_users.csv`
4. Choose "Replace data in selected cells"

### Option 3: Direct Link (Auto-updates from GitHub)

In cell A1 of a new Google Sheet, paste:
```
=IMPORTCSV("https://github.com/adamwyrzycki77-rgb/github-users-email-scraping/raw/texas-github-email-scraper/texas_github_users.csv")
```

**Note:** This creates a live connection that auto-updates when the GitHub file changes.

## Data Collected

| Column | Description |
|--------|-------------|
| name | User's full name from GitHub profile |
| email | Valid email address (no noreply@github.com) |
| github_url | Link to GitHub profile |

**Current Records:** 774 Texas users with valid email addresses

## How the Scraper Works

1. **Search Users by Location:**
   - Uses GitHub Search API with `location:TX` and `location:Texas`
   - Searches by creation date to avoid the 1000 result limit

2. **Email Collection:**
   - First tries to get public email from profile
   - If no public email, searches commit metadata from their repositories
   - Skips forked repositories
   - Filters out `noreply@github.com` addresses

3. **Date Ranges:**
   - First search: `created:<2009-01-01` (users before 2009)
   - Then monthly ranges: `created:YYYY-MM-01..YYYY-MM-31`

## Continuing the Scraping

To continue scraping more users (up to 2022-12-31):

```bash
python3 scraper_continue.py
```

The script will:
- Resume from where it left off
- Search monthly periods sequentially
- Save progress incrementally to `texas_github_users.csv`

## Scripts Included

| Script | Description |
|--------|-------------|
| `github_email_scraper.py` | Original full-featured scraper |
| `scraper_fast.py` | Optimized for speed |
| `scraper_continue.py` | Continuation script for extended scraping |
| `scraper_v2.py` | Alternative version |

## Requirements

- Python 3.x
- `requests` library: `pip install requests`
- GitHub API token (set as `GITHUB_TOKEN` environment variable)

## API Rate Limits

- GitHub Search API: 30 requests/minute (authenticated)
- Core API: 5000 requests/hour

The scraper includes rate limiting to avoid hitting limits.