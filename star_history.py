#!/usr/bin/env python3
"""
Star History + Growth Prediction.
Fetches star history via GitHub API, analyzes growth velocity,
and generates comparative charts with milestone predictions.

Usage:
    python star_history.py owner/repo [--compare owner/repo2 owner/repo3 ...]

Examples:
    python star_history.py facebook/react
    python star_history.py santifer/career-ops --compare ollama/ollama deepseek-ai/DeepSeek-V3
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd
import requests

# --- Config ---
CACHE_DIR = Path(__file__).parent / "cache"
ASSETS_DIR = Path(__file__).parent / "assets"

DEFAULT_COMPARE = [
    "Significant-Gravitas/AutoGPT",
    "ollama/ollama",
    "open-webui/open-webui",
    "deepseek-ai/DeepSeek-V3",
    "browser-use/browser-use",
    "abi/screenshot-to-code",
]

COLOR_PALETTE = [
    "#FF4500",  # highlight (always first = user's repo)
    "#10B981", "#8B5CF6", "#3B82F6", "#06B6D4",
    "#F59E0B", "#EC4899", "#A855F7", "#64748B",
]

MILESTONES = [20_000, 50_000, 100_000]


def get_github_token():
    try:
        result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except Exception:
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            print("ERROR: No GitHub token found. Run 'gh auth login' or set GITHUB_TOKEN.", file=sys.stderr)
            sys.exit(1)
        return token


def fetch_stargazers(repo, token):
    cache_file = CACHE_DIR / f"{repo.replace('/', '_')}.json"
    if cache_file.exists():
        print(f"  [cache] {repo}")
        with open(cache_file) as f:
            return json.load(f)

    print(f"  [fetch] {repo} ", end="", flush=True)
    session = requests.Session()
    session.headers.update({
        "Accept": "application/vnd.github.star+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "star-history-analyzer",
    })

    all_stars = []
    page = 1
    max_pages = 400  # GitHub hard limit

    while page <= max_pages:
        resp = session.get(
            f"https://api.github.com/repos/{repo}/stargazers",
            params={"per_page": 100, "page": page},
            timeout=30,
        )

        if resp.status_code == 403:
            reset = resp.headers.get("X-RateLimit-Reset")
            if reset:
                wait = max(0, int(reset) - int(time.time())) + 2
                print(f"\n  [rate limit] waiting {wait}s...", end="", flush=True)
                time.sleep(wait)
                continue
            time.sleep(10)
            continue

        if resp.status_code == 422:
            # Past page 400 limit
            break

        if resp.status_code != 200:
            print(f"\n  [error] HTTP {resp.status_code} on page {page}")
            break

        data = resp.json()
        if not data:
            break

        for entry in data:
            all_stars.append(entry["starred_at"])

        if page % 50 == 0:
            print(f"{len(all_stars):,}...", end="", flush=True)

        page += 1
        time.sleep(0.05)

    print(f" {len(all_stars):,} stars fetched")

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(cache_file, "w") as f:
        json.dump(all_stars, f)

    return all_stars


def build_cumulative_series(timestamps):
    if not timestamps:
        return pd.Series(dtype=float)
    dates = pd.to_datetime(timestamps).sort_values()
    df = pd.DataFrame({"date": dates})
    df["count"] = 1
    # Use hourly resolution for short-lived repos, daily for longer ones
    span_days = (dates.max() - dates.min()).days
    freq = "h" if span_days < 7 else "D"
    cumul = df.set_index("date").resample(freq)["count"].sum().cumsum()
    return cumul


def compute_growth_rate(series, window_weeks=4):
    weekly = series.resample("W").last().ffill()
    growth = weekly.diff(periods=window_weeks) / window_weeks
    return growth.dropna()


def find_growth_at_star_count(series, target_stars):
    if series.empty or series.max() < target_stars:
        return None, None
    idx = (series - target_stars).abs().idxmin()
    growth = compute_growth_rate(series)
    nearby = growth.loc[:idx].tail(1)
    if nearby.empty:
        return idx, None
    return idx, nearby.iloc[0]


def predict_milestones(series, milestones):
    current_stars = series.iloc[-1]
    current_date = series.index[-1]

    if len(series) < 3:
        # Not enough data for regression, return meta only
        return {"_meta": {
            "slope_per_day": 0, "slope_per_week": 0, "exp_rate": 0,
            "current_stars": current_stars, "current_date": current_date,
        }}

    # Use last 90 days for trend, fallback to all data
    recent = series.tail(90)
    if len(recent) < 3:
        recent = series

    x = (recent.index - recent.index[0]).days.values.astype(float)
    y = recent.values.astype(float)

    # If all data is in the same day, use hourly resolution
    if x.max() == 0:
        x = np.arange(len(recent), dtype=float)
        # Convert to "equivalent days" based on hours
        total_hours = (recent.index[-1] - recent.index[0]).total_seconds() / 3600
        if total_hours > 0:
            x = x * (total_hours / 24 / len(recent))

    results = {}

    # Model 1: Linear
    try:
        coeffs = np.polyfit(x, y, 1)
        slope_per_day = coeffs[0]
    except Exception:
        slope_per_day = 0

    # Model 2: Exponential (log-linear fit)
    try:
        y_pos = y[y > 0]
        x_pos = x[:len(y_pos)]
        log_coeffs = np.polyfit(x_pos, np.log(y_pos), 1)
        exp_rate = log_coeffs[0]
    except Exception:
        exp_rate = 0

    for milestone in milestones:
        if milestone <= current_stars:
            results[milestone] = {"linear": current_date, "exponential": current_date}
            continue

        entry = {}

        # Linear prediction
        if slope_per_day > 0:
            days_needed = (milestone - current_stars) / slope_per_day
            entry["linear"] = current_date + timedelta(days=days_needed)
        else:
            entry["linear"] = None

        # Exponential prediction
        if exp_rate > 0:
            days_needed = (np.log(milestone) - np.log(current_stars)) / exp_rate
            entry["exponential"] = current_date + timedelta(days=days_needed)
        else:
            entry["exponential"] = None

        results[milestone] = entry

    results["_meta"] = {
        "slope_per_day": slope_per_day,
        "slope_per_week": slope_per_day * 7,
        "exp_rate": exp_rate,
        "current_stars": current_stars,
        "current_date": current_date,
    }

    return results


def _style_ax(ax, use_date_axis=True):
    ax.set_facecolor("#0D1117")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["bottom"].set_color("#30363D")
    ax.spines["left"].set_color("#30363D")
    ax.tick_params(colors="#8B949E", labelsize=11)
    if use_date_axis:
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=6))


def plot_all(all_series, predictions, highlight_repo, colors):
    fig, axes = plt.subplots(3, 1, figsize=(14, 22))
    fig.patch.set_facecolor("#0D1117")

    # --- Chart 1: Race Chart (normalized by days since first star) ---
    ax1 = axes[0]
    _style_ax(ax1, use_date_axis=False)

    for repo, series in all_series.items():
        if series.empty or series.max() == 0:
            continue
        is_highlight = repo == highlight_repo
        color = colors.get(repo, "#8B949E")
        short_name = repo.split("/")[-1]

        # Normalize: X = days since first star
        first_date = series.index[0]
        days_since_start = (series.index - first_date).total_seconds() / 86400
        label = f"{short_name} ({int(series.max()):,})"

        ax1.plot(
            days_since_start, series.values,
            color=color,
            linewidth=3.5 if is_highlight else 1.5,
            alpha=1.0 if is_highlight else 0.6,
            label=label,
            zorder=10 if is_highlight else 5,
        )

        # Annotate endpoint
        if is_highlight:
            ax1.annotate(
                f" {int(series.max()):,}",
                xy=(days_since_start[-1], series.values[-1]),
                color=color, fontsize=11, fontweight="bold", va="center",
            )

    ax1.set_xlabel("Days since first star", color="#C9D1D9", fontsize=13)
    ax1.set_ylabel("Total Stars", color="#C9D1D9", fontsize=13)
    ax1.set_title("Growth Race: Stars vs Time (normalized)", color="#C9D1D9", fontsize=16, fontweight="bold", pad=15)
    ax1.legend(loc="upper left", fontsize=9, facecolor="#161B22", edgecolor="#30363D", labelcolor="#C9D1D9")

    # --- Chart 2: Growth Rate comparison (absolute dates) ---
    ax2 = axes[1]
    _style_ax(ax2)

    for repo, series in all_series.items():
        if series.empty or series.max() == 0:
            continue
        # Resample to daily for growth rate calculation
        daily = series.resample("D").last().ffill()
        growth = compute_growth_rate(daily)
        if growth.empty:
            continue
        is_highlight = repo == highlight_repo
        color = colors.get(repo, "#8B949E")
        label = repo.split("/")[-1]
        ax2.plot(
            growth.index, growth.values,
            color=color,
            linewidth=2.5 if is_highlight else 1.2,
            alpha=1.0 if is_highlight else 0.5,
            label=label,
            zorder=10 if is_highlight else 5,
        )

    ax2.set_ylabel("Stars / week (4-week rolling)", color="#C9D1D9", fontsize=13)
    ax2.set_title("Growth Velocity Over Time", color="#C9D1D9", fontsize=16, fontweight="bold", pad=15)
    ax2.legend(loc="upper left", fontsize=9, facecolor="#161B22", edgecolor="#30363D", labelcolor="#C9D1D9")

    # --- Chart 3: Peer Analogy Projection ---
    ax3 = axes[2]
    _style_ax(ax3, use_date_axis=False)

    highlight_series = all_series.get(highlight_repo)
    if highlight_series is not None and not highlight_series.empty:
        color_hl = colors[highlight_repo]
        current_stars = int(highlight_series.max())
        first_date = highlight_series.index[0]
        days_hl = (highlight_series.index - first_date).total_seconds() / 86400

        # Plot career-ops actual
        ax3.plot(days_hl, highlight_series.values, color=color_hl, linewidth=3.5,
                 label=f"{highlight_repo.split('/')[-1]} (actual: {current_stars:,})", zorder=10)

        # For each peer, show what happened AFTER they reached career-ops's current star count
        # Normalize so day 0 = when they hit ~current_stars
        for repo, series in all_series.items():
            if repo == highlight_repo or series.empty or series.max() < current_stars:
                continue
            color = colors.get(repo, "#8B949E")
            name = repo.split("/")[-1]

            # Find when this repo crossed current_stars
            crossed = series[series >= current_stars]
            if crossed.empty:
                continue
            cross_date = crossed.index[0]
            # Get data from that point forward
            after = series[series.index >= cross_date]
            # Shift: day 0 = last day of career-ops data
            career_ops_last_day = days_hl[-1]
            days_after = (after.index - cross_date).total_seconds() / 86400 + career_ops_last_day

            ax3.plot(days_after, after.values, color=color, linewidth=1.8, linestyle="--",
                     alpha=0.7, label=f"If follows {name}'s path")

        # Milestone lines
        for milestone in MILESTONES:
            if milestone > current_stars:
                ax3.axhline(y=milestone, color="#30363D", linestyle=":", alpha=0.5)
                ax3.text(0, milestone + 500, f"  {milestone // 1000}K",
                         color="#8B949E", fontsize=11, va="bottom")

        ax3.set_xlabel("Days since first star", color="#C9D1D9", fontsize=13)
        ax3.set_ylabel("Stars", color="#C9D1D9", fontsize=13)
        hl_name = highlight_repo.split("/")[-1]
        ax3.set_title(f"{hl_name} Projection: What if it follows peer trajectories?",
                       color="#C9D1D9", fontsize=16, fontweight="bold", pad=15)
        ax3.legend(loc="upper left", fontsize=9, facecolor="#161B22", edgecolor="#30363D", labelcolor="#C9D1D9")

    fig.tight_layout(pad=3)
    output_path = ASSETS_DIR / "star_growth_analysis.png"
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=300, facecolor="#0D1117", bbox_inches="tight")
    plt.close(fig)
    print(f"\nChart saved to: {output_path}")


def print_report(all_series, predictions, highlight_repo):
    series = all_series.get(highlight_repo)
    if series is None or series.empty:
        return

    meta = predictions.get("_meta", {})
    current = int(meta.get("current_stars", series.iloc[-1]))
    weekly = meta.get("slope_per_week", 0)

    hl_name = highlight_repo.split("/")[-1]
    print("\n" + "=" * 55)
    print(f"  {hl_name} Growth Analysis")
    print("=" * 55)
    print(f"  Current: {current:,} stars")
    print(f"  Growth rate (recent trend): ~{weekly:.0f} stars/week")
    print()

    print("  Milestone predictions:")
    for milestone in MILESTONES:
        entry = predictions.get(milestone, {})
        lin = entry.get("linear")
        exp = entry.get("exponential")
        lin_str = lin.strftime("%b %Y") if lin else "N/A"
        exp_str = exp.strftime("%b %Y") if exp else "N/A"
        print(f"    {milestone:>7,} stars: {lin_str} (linear) / {exp_str} (exponential)")

    print()
    print(f"  Growth comparison at ~{current // 1000}K stars:")
    target = current
    for repo, s in all_series.items():
        if repo == highlight_repo or s.empty:
            continue
        date_at, rate_at = find_growth_at_star_count(s, target)
        if date_at is not None and rate_at is not None:
            name = repo.split("/")[-1]
            print(f"    {name:20s}: {rate_at:>6.0f} stars/week (when at ~{target // 1000}K, {date_at.strftime('%b %Y')})")

    # Peer analogy projections
    print()
    print("  Peer analogy: time from 13K to milestones:")
    for repo, s in all_series.items():
        if repo == highlight_repo or s.empty or s.max() < target:
            continue
        name = repo.split("/")[-1]
        crossed = s[s >= target]
        if crossed.empty:
            continue
        cross_date = crossed.index[0]
        for milestone in MILESTONES:
            reached = s[s >= milestone]
            if not reached.empty:
                days_to = (reached.index[0] - cross_date).days
                if days_to > 0:
                    print(f"    {name:20s}: 13K -> {milestone//1000}K in {days_to:,} days ({days_to // 30} months)")
            else:
                print(f"    {name:20s}: 13K -> {milestone//1000}K — not yet reached (current: {int(s.max()):,})")

    print("=" * 55)


def main():
    parser = argparse.ArgumentParser(
        description="Star History + Growth Prediction for any GitHub repo",
        epilog="Example: python star_history.py facebook/react --compare ollama/ollama deepseek-ai/DeepSeek-V3",
    )
    parser.add_argument("repo", help="Your repo (owner/name) — highlighted in charts")
    parser.add_argument("--compare", nargs="*", default=None,
                        help="Repos to compare against (default: top viral repos)")
    args = parser.parse_args()

    highlight_repo = args.repo
    compare_repos = args.compare if args.compare else DEFAULT_COMPARE
    all_repos = [highlight_repo] + [r for r in compare_repos if r != highlight_repo]

    # Assign colors dynamically
    colors = {}
    for i, repo in enumerate(all_repos):
        colors[repo] = COLOR_PALETTE[i % len(COLOR_PALETTE)]

    print("Star History + Growth Prediction")
    print("-" * 40)

    token = get_github_token()

    print("\nFetching star history...")
    all_series = {}
    for repo in all_repos:
        timestamps = fetch_stargazers(repo, token)
        all_series[repo] = build_cumulative_series(timestamps)

    print("\nAnalyzing growth...")
    predictions = {}
    if highlight_repo in all_series:
        predictions = predict_milestones(all_series[highlight_repo], MILESTONES)

    print_report(all_series, predictions, highlight_repo)

    print("\nGenerating charts...")
    plot_all(all_series, predictions, highlight_repo, colors)


if __name__ == "__main__":
    main()
