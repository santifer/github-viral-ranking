#!/usr/bin/env python3
"""
Find the most viral first-day repos in GitHub history.
Checks the top repos + known viral repos and ranks by stars in first 24h.
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

CACHE_DIR = Path(__file__).parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)


def get_github_token():
    try:
        result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except Exception:
        return os.environ.get("GITHUB_TOKEN", "")


def get_repo_info(session, repo):
    """Get creation date and total stars."""
    resp = session.get(f"https://api.github.com/repos/{repo}", timeout=15)
    if resp.status_code == 403:
        wait_for_rate_limit(resp)
        resp = session.get(f"https://api.github.com/repos/{repo}", timeout=15)
    if resp.status_code != 200:
        return None, None
    data = resp.json()
    return data.get("created_at"), data.get("stargazers_count", 0)


def wait_for_rate_limit(resp):
    reset = resp.headers.get("X-RateLimit-Reset")
    if reset:
        wait = max(0, int(reset) - int(time.time())) + 2
        print(f"  [rate limit] waiting {wait}s...", flush=True)
        time.sleep(wait)
    else:
        time.sleep(30)


def count_first_day_stars(session, repo, created_at_str):
    """Count stars received in the first 24 hours after creation."""
    # Check full cache first
    cache_file = CACHE_DIR / f"{repo.replace('/', '_')}.json"
    if cache_file.exists():
        with open(cache_file) as f:
            timestamps = json.load(f)
        if timestamps:
            created = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
            cutoff_24h = created + timedelta(hours=24)
            cutoff_48h = created + timedelta(hours=48)
            count_24h = sum(1 for t in timestamps
                           if datetime.fromisoformat(t.replace("Z", "+00:00")) <= cutoff_24h)
            count_48h = sum(1 for t in timestamps
                           if datetime.fromisoformat(t.replace("Z", "+00:00")) <= cutoff_48h)
            return count_24h, count_48h

    # Fetch stargazers page by page until past 24h
    created = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
    cutoff_24h = created + timedelta(hours=24)
    cutoff_48h = created + timedelta(hours=48)

    all_timestamps = []
    page = 1
    past_48h = False

    while page <= 400 and not past_48h:
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
            ts = entry["starred_at"]
            star_date = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            all_timestamps.append(ts)
            if star_date > cutoff_48h:
                past_48h = True
                break

        page += 1
        time.sleep(0.05)

    count_24h = sum(1 for t in all_timestamps
                    if datetime.fromisoformat(t.replace("Z", "+00:00")) <= cutoff_24h)
    count_48h = sum(1 for t in all_timestamps
                    if datetime.fromisoformat(t.replace("Z", "+00:00")) <= cutoff_48h)
    return count_24h, count_48h


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Find where your repo ranks among the most viral in GitHub history",
        epilog="Example: python viral_ranking.py santifer/career-ops",
    )
    parser.add_argument("repo", nargs="?", default=None,
                        help="Your repo (owner/name) — highlighted in results")
    args = parser.parse_args()

    highlight = args.repo

    token = get_github_token()
    session = requests.Session()
    session.headers.update({
        "Authorization": f"Bearer {token}",
        "User-Agent": "viral-ranking-analyzer",
        "Accept": "application/vnd.github+json",
    })

    # Build candidate list: top repos + known viral repos
    print("Building candidate list...", flush=True)

    candidates = set()
    if highlight:
        candidates.add(highlight)

    # Top repos by stars (multiple searches to get broad coverage)
    searches = [
        "stars:>50000",
        "stars:>20000 created:>2023-01-01",
        "stars:>10000 created:>2024-01-01",
        "stars:>5000 created:>2025-01-01",
    ]

    for query in searches:
        resp = session.get(
            "https://api.github.com/search/repositories",
            params={"q": query, "sort": "stars", "per_page": 30},
            timeout=15,
        )
        if resp.status_code == 403:
            wait_for_rate_limit(resp)
            resp = session.get(
                "https://api.github.com/search/repositories",
                params={"q": query, "sort": "stars", "per_page": 30},
                timeout=15,
            )
        if resp.status_code == 200:
            for item in resp.json().get("items", []):
                candidates.add(item["full_name"])
        time.sleep(2)  # search API rate limit

    # Load repos from viral_tracker database
    db_path = Path(__file__).parent / "data" / "viral_repos.json"
    if db_path.exists():
        with open(db_path) as f:
            db = json.load(f)
        db_repos = set(db.get("repos", {}).keys())
        candidates.update(db_repos)
        print(f"  Loaded {len(db_repos)} repos from tracker database")

    # Add known historically viral repos
    known_viral = [
        "Significant-Gravitas/AutoGPT",
        "ollama/ollama",
        "open-webui/open-webui",
        "deepseek-ai/DeepSeek-V3",
        "deepseek-ai/DeepSeek-R1",
        "browser-use/browser-use",
        "abi/screenshot-to-code",
        "karpathy/nanoGPT",
        "karpathy/nanochat",
        "FoundationAgents/OpenManus",
        "AUTOMATIC1111/stable-diffusion-webui",
        "f/prompts.chat",
        "FlowiseAI/Flowise",
        "langchain-ai/langchain",
        "ggerganov/llama.cpp",
        "openai/chatgpt-retrieval-plugin",
        "CompVis/stable-diffusion",
        "langgenius/dify",
        "All-Hands-AI/OpenHands",
        "kamranahmedse/developer-roadmap",
        "codecrafters-io/build-your-own-x",
        "996icu/996.ICU",
        "ohmyzsh/ohmyzsh",
        "EbookFoundation/free-programming-books",
        "torvalds/linux",
    ]
    candidates.update(known_viral)

    print(f"Analyzing {len(candidates)} repos...\n", flush=True)

    results = []
    for i, repo in enumerate(sorted(candidates)):
        print(f"  [{i+1}/{len(candidates)}] {repo}...", end=" ", flush=True)

        created_at, total_stars = get_repo_info(session, repo)
        if not created_at:
            print("skip (not found)")
            continue

        stars_24h, stars_48h = count_first_day_stars(session, repo, created_at)
        print(f"{stars_24h:,} in 24h, {stars_48h:,} in 48h")

        results.append({
            "repo": repo,
            "stars_24h": stars_24h,
            "stars_48h": stars_48h,
            "total_stars": total_stars,
            "created_at": created_at,
        })
        time.sleep(0.1)

    # Sort and display
    results.sort(key=lambda x: x["stars_24h"], reverse=True)

    print("\n")
    print("=" * 80)
    print("  RANKING HISTORICO: Repos mas virales en sus primeras 24 horas")
    print("  (Muestra: top repos + repos virales conocidos)")
    print("=" * 80)
    print(f"{'Rank':>4}  {'Repo':<42} {'24h':>8} {'48h':>8} {'Total':>10}")
    print("-" * 80)

    for i, r in enumerate(results[:50], 1):
        name = r["repo"]
        short = name if len(name) <= 40 else name[:37] + "..."
        marker = "  <<<" if highlight and highlight in name else ""
        print(f"{i:>4}. {short:<42} {r['stars_24h']:>8,} {r['stars_48h']:>8,} {r['total_stars']:>10,}{marker}")

    print("=" * 80)

    # Find user's repo position
    if highlight:
        for i, r in enumerate(results, 1):
            if highlight in r["repo"]:
                hl_name = highlight.split("/")[-1]
                print(f"\n  {hl_name}: #{i} de {len(results)} repos analizados")
                print(f"  {r['stars_24h']:,} stars en 24h | {r['stars_48h']:,} en 48h | {r['total_stars']:,} total")
                break


if __name__ == "__main__":
    main()
