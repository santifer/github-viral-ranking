#!/usr/bin/env python3
"""
Viral Repo Tracker — Automated discovery of fast-growing GitHub repos.

Searches for recently created repos with high star counts, fetches their
first-day stargazer timestamps, and saves to a persistent database.

Run daily via cron to build a comprehensive dataset of viral repos over time.

Usage:
    python viral_tracker.py                  # Scan last 30 days
    python viral_tracker.py --days 7         # Scan last 7 days
    python viral_tracker.py --min-stars 500  # Lower threshold
    python viral_tracker.py --show           # Just show the database
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

DB_PATH = Path(__file__).parent / "data" / "viral_repos.json"
CACHE_DIR = Path(__file__).parent / "cache"


def get_github_token():
    try:
        result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except Exception:
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            print("ERROR: No GitHub token. Run 'gh auth login' or set GITHUB_TOKEN.", file=sys.stderr)
            sys.exit(1)
        return token


def load_db():
    if DB_PATH.exists():
        with open(DB_PATH) as f:
            return json.load(f)
    return {"repos": {}, "last_scan": None}


def save_db(db):
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db["last_scan"] = datetime.now(timezone.utc).isoformat()
    with open(DB_PATH, "w") as f:
        json.dump(db, f, indent=2, default=str)


def wait_for_rate_limit(resp):
    reset = resp.headers.get("X-RateLimit-Reset")
    if reset:
        wait = max(0, int(reset) - int(time.time())) + 2
        print(f"    [rate limit] waiting {wait}s...", flush=True)
        time.sleep(wait)
    else:
        time.sleep(30)


def search_candidates(session, days_back, min_stars):
    """Search GitHub for recently created repos with high star counts."""
    since = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d")
    candidates = []

    # Multiple queries to catch different ranges
    queries = [
        f"created:>{since} stars:>{min_stars}",
    ]
    if min_stars <= 5000:
        queries.append(f"created:>{since} stars:>5000")

    seen = set()
    for query in queries:
        for page in range(1, 4):  # up to 3 pages per query
            resp = session.get(
                "https://api.github.com/search/repositories",
                params={"q": query, "sort": "stars", "order": "desc",
                        "per_page": 100, "page": page},
                timeout=15,
            )
            if resp.status_code == 403:
                wait_for_rate_limit(resp)
                continue
            if resp.status_code != 200:
                break
            items = resp.json().get("items", [])
            if not items:
                break
            for item in items:
                name = item["full_name"]
                if name not in seen:
                    seen.add(name)
                    candidates.append({
                        "full_name": name,
                        "stars": item["stargazers_count"],
                        "created_at": item["created_at"],
                    })
            time.sleep(2)  # search API rate limit

    return candidates


def fetch_first_day_stats(session, repo, created_at_str):
    """Fetch stargazer timestamps and calculate first-day metrics."""
    created = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
    cutoffs = {
        "1h": created + timedelta(hours=1),
        "6h": created + timedelta(hours=6),
        "12h": created + timedelta(hours=12),
        "24h": created + timedelta(hours=24),
        "48h": created + timedelta(hours=48),
        "72h": created + timedelta(hours=72),
        "7d": created + timedelta(days=7),
    }

    all_timestamps = []
    page = 1
    first_star = None
    past_7d = False

    while page <= 400 and not past_7d:
        resp = session.get(
            f"https://api.github.com/repos/{repo}/stargazers",
            params={"per_page": 100, "page": page},
            headers={"Accept": "application/vnd.github.star+json"},
            timeout=15,
        )
        if resp.status_code == 403:
            wait_for_rate_limit(resp)
            continue
        if resp.status_code == 422 or resp.status_code != 200:
            break

        data = resp.json()
        if not data:
            break

        for entry in data:
            ts_str = entry["starred_at"]
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            all_timestamps.append(ts_str)
            if first_star is None:
                first_star = ts
            if ts > cutoffs["7d"]:
                past_7d = True
                break

        page += 1
        time.sleep(0.05)

    # Calculate counts at each cutoff (from first star, not creation)
    if not all_timestamps or not first_star:
        return None

    from_first = {
        "1h": first_star + timedelta(hours=1),
        "6h": first_star + timedelta(hours=6),
        "12h": first_star + timedelta(hours=12),
        "24h": first_star + timedelta(hours=24),
        "48h": first_star + timedelta(hours=48),
        "72h": first_star + timedelta(hours=72),
        "7d": first_star + timedelta(days=7),
    }

    parsed = [datetime.fromisoformat(t.replace("Z", "+00:00")) for t in all_timestamps]

    stats = {
        "first_star": first_star.isoformat(),
        "created_at": created_at_str,
    }
    for label, cutoff in from_first.items():
        stats[f"stars_{label}"] = sum(1 for t in parsed if t <= cutoff)

    return stats


def show_db(db):
    """Display the database sorted by first-24h stars."""
    repos = db.get("repos", {})
    if not repos:
        print("Database is empty. Run without --show to start scanning.")
        return

    entries = []
    for name, data in repos.items():
        entries.append((data.get("stars_24h", 0), data.get("stars_48h", 0),
                        data.get("total_stars", 0), data.get("first_star", ""), name))

    entries.sort(reverse=True)

    print(f"\n{'=' * 90}")
    print(f"  Viral Repos Database — {len(entries)} repos tracked")
    print(f"  Last scan: {db.get('last_scan', 'never')}")
    print(f"{'=' * 90}")
    print(f"{'#':>4}  {'Repo':<40} {'24h':>7} {'48h':>7} {'7d':>7} {'Total':>8}  First star")
    print(f"{'-' * 90}")

    for i, (s24, s48, total, first, name) in enumerate(entries[:50], 1):
        short = name if len(name) <= 38 else name[:35] + "..."
        first_short = first[:10] if first else "?"
        print(f"{i:>4}. {short:<40} {s24:>7,} {s48:>7,} {0:>7} {total:>8,}  {first_short}")

    print(f"{'=' * 90}")


def main():
    parser = argparse.ArgumentParser(
        description="Track the most viral repos on GitHub automatically",
    )
    parser.add_argument("--days", type=int, default=30,
                        help="How far back to search (default: 30)")
    parser.add_argument("--min-stars", type=int, default=1000,
                        help="Minimum stars to consider (default: 1000)")
    parser.add_argument("--show", action="store_true",
                        help="Just show the current database")
    parser.add_argument("--force", action="store_true",
                        help="Re-analyze repos already in database")
    args = parser.parse_args()

    db = load_db()

    if args.show:
        show_db(db)
        return

    token = get_github_token()
    session = requests.Session()
    session.headers.update({
        "Authorization": f"Bearer {token}",
        "User-Agent": "viral-tracker",
        "Accept": "application/vnd.github+json",
    })

    # Search for candidates
    print(f"Searching for repos created in last {args.days} days with >{args.min_stars} stars...", flush=True)
    candidates = search_candidates(session, args.days, args.min_stars)
    print(f"Found {len(candidates)} candidates\n")

    # Filter out already-tracked repos (unless --force)
    new_count = 0
    skip_count = 0
    for cand in candidates:
        name = cand["full_name"]
        if name in db["repos"] and not args.force:
            skip_count += 1
            continue

        print(f"  [{new_count + skip_count + 1}/{len(candidates)}] {name}...", end=" ", flush=True)

        stats = fetch_first_day_stats(session, name, cand["created_at"])
        if stats:
            db["repos"][name] = {
                **stats,
                "total_stars": cand["stars"],
                "tracked_at": datetime.now(timezone.utc).isoformat(),
            }
            s24 = stats.get("stars_24h", 0)
            s48 = stats.get("stars_48h", 0)
            print(f"{s24:,} in 24h, {s48:,} in 48h")
            new_count += 1
        else:
            print("skip (no stargazer data)")

        time.sleep(0.1)

    if skip_count:
        print(f"\n  Skipped {skip_count} already-tracked repos (use --force to re-analyze)")

    save_db(db)
    print(f"\nDatabase updated: {len(db['repos'])} total repos tracked")
    print(f"Saved to: {DB_PATH}")

    # Show top 10
    show_db(db)


if __name__ == "__main__":
    main()
