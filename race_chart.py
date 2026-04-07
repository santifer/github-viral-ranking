#!/usr/bin/env python3
"""
Temporal Race Chart: shows how repos rank at each time cutoff (1h → 7d).
Highlights a target repo and projects its trajectory with confidence bands.

Usage:
    python race_chart.py santifer/career-ops
    python race_chart.py santifer/career-ops --current-stars 16100
"""

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np

DB_PATH = Path(__file__).parent / "data" / "viral_repos.json"
ASSETS_DIR = Path(__file__).parent / "assets"
ASSETS_DIR.mkdir(exist_ok=True)

TIME_POINTS = ["1h", "6h", "12h", "24h", "48h", "72h", "7d"]
TIME_HOURS = [1, 6, 12, 24, 48, 72, 168]
# For projection beyond available data
PROJ_HOURS = [24 * d for d in range(4, 31)]  # day 4 to day 30

COLOR_HIGHLIGHT = "#FF4500"
COLOR_TOP = ["#8B5CF6", "#3B82F6", "#06B6D4", "#10B981", "#F59E0B",
             "#EC4899", "#A855F7", "#64748B", "#84CC16", "#FB923C"]


def load_db():
    with open(DB_PATH) as f:
        return json.load(f)


def get_top_repos(db, n=10):
    """Get top N repos by max stars at any time point."""
    repos = []
    for name, data in db["repos"].items():
        max_stars = max(data.get(f"stars_{tp}", 0) for tp in TIME_POINTS)
        if max_stars > 0:
            repos.append((max_stars, name, data))
    repos.sort(reverse=True)
    return repos[:n]


def project_growth(time_series_hours, star_counts, proj_hours):
    """
    Project growth using log-linear regression on available data.
    Returns projected values and confidence bands.
    """
    # Filter valid data points (non-zero, non-plateaued at API limit)
    valid = [(h, s) for h, s in zip(time_series_hours, star_counts)
             if s > 0 and s < 40000]

    if len(valid) < 2:
        return None, None, None

    x = np.array([v[0] for v in valid])
    y = np.array([v[1] for v in valid])

    # Log-linear fit: log(stars) = a*log(hours) + b  (power law)
    try:
        log_x = np.log(x)
        log_y = np.log(y)
        coeffs = np.polyfit(log_x, log_y, 1)
        a, b = coeffs

        proj_x = np.array(proj_hours)
        proj_y = np.exp(b) * proj_x ** a

        # Residuals for confidence band
        residuals = log_y - (a * log_x + b)
        std = np.std(residuals) if len(residuals) > 2 else 0.3

        proj_upper = np.exp(b + std) * proj_x ** a
        proj_lower = np.exp(b - std) * proj_x ** a

        return proj_y, proj_lower, proj_upper
    except Exception:
        return None, None, None


def plot_race(highlight_repo, current_stars=None):
    db = load_db()
    top = get_top_repos(db, n=12)

    # Ensure highlight repo is included
    highlight_data = db["repos"].get(highlight_repo)
    if not highlight_data:
        print(f"ERROR: {highlight_repo} not found in database")
        return

    # Remove highlight from top list if present, we'll add it separately
    top = [(s, n, d) for s, n, d in top if n != highlight_repo][:9]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(22, 11),
                                     gridspec_kw={"width_ratios": [3, 2]})
    fig.patch.set_facecolor("#0D1117")
    for ax in [ax1, ax2]:
        ax.set_facecolor("#0D1117")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["bottom"].set_color("#30363D")
        ax.spines["left"].set_color("#30363D")
        ax.tick_params(colors="#8B949E", labelsize=10)

    # --- LEFT: Race chart (cumulative stars at each time point) ---
    # Only plot time points the repo has actually lived through
    from datetime import datetime, timezone
    first_star_dt = datetime.fromisoformat(highlight_data["first_star"])
    repo_age_hours = (datetime.now(timezone.utc) - first_star_dt).total_seconds() / 3600

    hl_hours_real = []
    hl_stars_real = []
    for h, tp in zip(TIME_HOURS, TIME_POINTS):
        s = highlight_data.get(f"stars_{tp}", 0)
        if s > 0 and h <= repo_age_hours:
            hl_hours_real.append(h)
            hl_stars_real.append(s)

    # Add current point at actual elapsed time if provided
    if current_stars and hl_stars_real:
        if current_stars > hl_stars_real[-1]:
            hl_hours_real.append(repo_age_hours)
            hl_stars_real.append(current_stars)

    hl_name = highlight_repo.split("/")[-1]
    ax1.plot(hl_hours_real, hl_stars_real, color=COLOR_HIGHLIGHT, linewidth=4,
             marker="o", markersize=10, zorder=20, label=hl_name)

    # Project highlight repo forward with dotted line
    if len(hl_hours_real) >= 2:
        future_hours = [h for h in TIME_HOURS if h > hl_hours_real[-1]]
        if future_hours:
            proj, lower, upper = project_growth(hl_hours_real, hl_stars_real, future_hours)
            if proj is not None:
                ax1.plot(future_hours, proj, color=COLOR_HIGHLIGHT, linewidth=2,
                         linestyle=":", marker="o", markersize=6, alpha=0.4, zorder=15)
                ax1.fill_between(future_hours, lower, upper,
                                 color=COLOR_HIGHLIGHT, alpha=0.07)

    # Annotate each real point for highlight
    for h, s in zip(hl_hours_real, hl_stars_real):
        ax1.annotate(f"{s:,}", xy=(h, s), xytext=(0, 12),
                     textcoords="offset points", ha="center",
                     color=COLOR_HIGHLIGHT, fontsize=9, fontweight="bold")

    # Top repos
    for idx, (_, name, data) in enumerate(top):
        stars = [data.get(f"stars_{tp}", 0) for tp in TIME_POINTS]
        short = name.split("/")[-1]
        if len(short) > 20:
            short = short[:17] + "..."
        color = COLOR_TOP[idx % len(COLOR_TOP)]
        ax1.plot(TIME_HOURS, stars, color=color, linewidth=1.5,
                 marker="s", markersize=4, alpha=0.6, label=short)

    ax1.set_xlabel("Hours since first star", color="#C9D1D9", fontsize=13)
    ax1.set_ylabel("Cumulative Stars", color="#C9D1D9", fontsize=13)
    ax1.set_title("Viral Race: Stars at Each Time Cutoff",
                  color="#C9D1D9", fontsize=16, fontweight="bold", pad=15)
    # Linear scale — no log compression
    ax1.set_xticks(TIME_HOURS)
    ax1.set_xticklabels(TIME_POINTS)
    ax1.yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f"{int(x):,}"))
    ax1.legend(loc="upper left", fontsize=9, facecolor="#161B22",
               edgecolor="#30363D", labelcolor="#C9D1D9", ncol=2)

    # --- RIGHT: Projection for highlight repo ---
    # Get actual data points (use the filtered real data)
    actual_hours = list(hl_hours_real)
    actual_stars = list(hl_stars_real)

    # Plot actual
    ax2.plot(actual_hours, actual_stars, color=COLOR_HIGHLIGHT, linewidth=3.5,
             marker="o", markersize=10, zorder=10, label="Actual")

    # Project
    all_proj_hours = [h for h in PROJ_HOURS if h > max(actual_hours)]
    if all_proj_hours:
        proj, lower, upper = project_growth(actual_hours, actual_stars, all_proj_hours)
        if proj is not None:
            proj_days = [h / 24 for h in all_proj_hours]
            actual_days = [h / 24 for h in actual_hours]

            # Re-plot actual in days
            ax2.clear()
            ax2.set_facecolor("#0D1117")
            ax2.spines["top"].set_visible(False)
            ax2.spines["right"].set_visible(False)
            ax2.spines["bottom"].set_color("#30363D")
            ax2.spines["left"].set_color("#30363D")
            ax2.tick_params(colors="#8B949E", labelsize=10)

            ax2.plot(actual_days, actual_stars, color=COLOR_HIGHLIGHT, linewidth=3.5,
                     marker="o", markersize=10, zorder=10, label="Actual")

            # Projection line
            ax2.plot(proj_days, proj, color=COLOR_HIGHLIGHT, linewidth=2,
                     linestyle="--", alpha=0.7, label="Power-law projection")

            # Confidence band
            ax2.fill_between(proj_days, lower, upper,
                             color=COLOR_HIGHLIGHT, alpha=0.1)

            # Milestone lines
            for milestone in [20000, 50000, 100000]:
                ax2.axhline(y=milestone, color="#30363D", linestyle=":", alpha=0.4)
                ax2.text(0.5, milestone * 1.03, f"{milestone // 1000}K",
                         color="#6B7280", fontsize=10)

                # Find when projection crosses milestone
                crossings = [d for d, p in zip(proj_days, proj) if p >= milestone]
                if crossings:
                    day = crossings[0]
                    ax2.plot(day, milestone, marker="*", color="#F59E0B",
                             markersize=15, zorder=15)
                    ax2.annotate(f"Day {day:.0f}", xy=(day, milestone),
                                xytext=(10, 10), textcoords="offset points",
                                color="#F59E0B", fontsize=10, fontweight="bold")

            # Annotate current
            ax2.annotate(f" {actual_stars[-1]:,}\n (now)",
                         xy=(actual_days[-1], actual_stars[-1]),
                         xytext=(10, -5), textcoords="offset points",
                         color=COLOR_HIGHLIGHT, fontsize=11, fontweight="bold")

    ax2.set_xlabel("Days since first star", color="#C9D1D9", fontsize=13)
    ax2.set_ylabel("Cumulative Stars", color="#C9D1D9", fontsize=13)
    ax2.set_title(f"{hl_name}: Growth Projection (power-law)",
                  color="#C9D1D9", fontsize=16, fontweight="bold", pad=15)
    ax2.yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f"{int(x):,}"))
    ax2.legend(loc="upper left", fontsize=10, facecolor="#161B22",
               edgecolor="#30363D", labelcolor="#C9D1D9")

    fig.suptitle(f"How does {hl_name} compare to the most viral repos?",
                 color="#C9D1D9", fontsize=20, fontweight="bold", y=1.02)

    fig.tight_layout(pad=3)
    out = ASSETS_DIR / "race_chart.png"
    fig.savefig(out, dpi=300, facecolor="#0D1117", bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")

    # Print ranking — only for time points with real data
    print(f"\n{'=' * 70}")
    print(f"  {hl_name} ranking at each time cutoff")
    print(f"{'=' * 70}")
    for tp, h in zip(TIME_POINTS, TIME_HOURS):
        if h > repo_age_hours:
            print(f"  {tp:>4}: (not yet reached)")
            continue
        hl_val = highlight_data.get(f"stars_{tp}", 0)
        if hl_val == 0:
            continue
        higher = sum(1 for _, d in db["repos"].items()
                     if d.get(f"stars_{tp}", 0) > hl_val)
        rank = higher + 1
        print(f"  {tp:>4}: {hl_val:>7,} stars — #{rank} of {len(db['repos'])}")
    # Show current if provided
    if current_stars:
        print(f"  now: {current_stars:>7,} stars ({repo_age_hours:.0f}h elapsed)")
    print(f"{'=' * 70}")


def main():
    parser = argparse.ArgumentParser(description="Temporal race chart with projection")
    parser.add_argument("repo", help="Your repo (owner/name)")
    parser.add_argument("--current-stars", type=int, default=None,
                        help="Override with current star count (if newer than cached)")
    args = parser.parse_args()

    plot_race(args.repo, args.current_stars)


if __name__ == "__main__":
    main()
