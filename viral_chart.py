#!/usr/bin/env python3
"""
Viral ranking chart: Top repos by first-day stars in GitHub history.
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np
from pathlib import Path

ASSETS_DIR = Path(__file__).parent / "assets"
ASSETS_DIR.mkdir(exist_ok=True)

# Data from our analysis (first 24h from first star)
DATA = [
    ("nanochat (Karpathy)", 11736, 17101, "#8B5CF6"),
    ("OpenManus", 9716, 14143, "#3B82F6"),
    ("career-ops (santifer)", 7207, 13381, "#FF4500"),
    ("DeepSeek-R1", 5352, 9100, "#06B6D4"),
    ("Linux (Torvalds)", 3784, 3801, "#F59E0B"),
    ("ChatGPT Plugin (OpenAI)", 3575, 5675, "#10B981"),
    ("996.ICU", 3125, 40000, "#EC4899"),
    ("gstack (Garry Tan)", 2313, 5743, "#A855F7"),
    ("oh-my-zsh", 2290, 2295, "#64748B"),
    ("free-prog-books", 2240, 2785, "#64748B"),
    ("autoresearch (Karpathy)", 1385, 7848, "#64748B"),
    ("llama.cpp", 1167, 2545, "#64748B"),
    ("stable-diffusion", 1146, 1517, "#64748B"),
]

# Cap 48h display so 996.ICU doesn't distort the chart
MAX_48H_DISPLAY = 18000


def plot_viral_ranking():
    fig, ax = plt.subplots(figsize=(18, 11))
    fig.patch.set_facecolor("#0D1117")
    ax.set_facecolor("#0D1117")

    names = [d[0] for d in DATA]
    stars_24h = [d[1] for d in DATA]
    stars_48h = [min(d[2], MAX_48H_DISPLAY) for d in DATA]
    stars_48h_real = [d[2] for d in DATA]
    colors = [d[3] for d in DATA]

    y_pos = np.arange(len(DATA))
    bar_height = 0.55

    # 48h bars (behind, capped)
    bars_48 = ax.barh(y_pos, stars_48h, height=bar_height,
                       color=[c + "22" for c in colors],
                       edgecolor=[c + "44" for c in colors], linewidth=0.8)

    # 24h bars (in front)
    bars_24 = ax.barh(y_pos, stars_24h, height=bar_height,
                       color=colors, alpha=0.9)

    # Highlight career-ops with glow effect
    highlight_idx = 2
    bars_24[highlight_idx].set_edgecolor("#FF4500")
    bars_24[highlight_idx].set_linewidth(2.5)

    # Labels
    for i, (s24, s48r) in enumerate(zip(stars_24h, stars_48h_real)):
        is_hl = i == highlight_idx
        # 24h count inside or next to bar
        ax.text(s24 + 200, i, f"{s24:,}",
                va="center", ha="left",
                color="#FFFFFF" if is_hl else "#C9D1D9",
                fontsize=12 if is_hl else 10,
                fontweight="bold")
        # 48h count further right
        if s48r > s24 * 1.3:
            display_48 = min(s48r, MAX_48H_DISPLAY)
            suffix = "+" if s48r > MAX_48H_DISPLAY else ""
            ax.text(display_48 + 200, i, f"{s48r:,} in 48h",
                    va="center", ha="left", color="#6B7280", fontsize=9)

    # Left side: rank + name as single clean label
    ax.set_yticks(y_pos)
    labels = []
    for i, name in enumerate(names):
        rank = f"#{i+1}"
        labels.append(f"{rank}  {name}")
    ax.set_yticklabels(labels, fontsize=11, fontfamily="monospace")
    # Color each label
    for i, label in enumerate(ax.get_yticklabels()):
        if i == highlight_idx:
            label.set_color("#FF4500")
            label.set_fontweight("bold")
        else:
            label.set_color("#C9D1D9")
    ax.invert_yaxis()

    # Axes styling
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["bottom"].set_color("#30363D")
    ax.spines["left"].set_visible(False)
    ax.tick_params(axis="x", colors="#8B949E", labelsize=10)
    ax.tick_params(axis="y", left=False, pad=10)
    ax.xaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f"{int(x):,}"))
    ax.set_xlim(0, MAX_48H_DISPLAY + 3000)

    ax.set_xlabel("GitHub Stars", color="#8B949E", fontsize=12)

    # Title
    ax.set_title("Most Viral First-Day Repos in GitHub History",
                 color="#C9D1D9", fontsize=22, fontweight="bold", pad=25, loc="left")
    ax.text(0.0, 1.015, "Stars in first 24h (solid) vs 48h (faded)  |  Measured from first star, not repo creation",
            transform=ax.transAxes, ha="left", color="#6B7280", fontsize=10)

    # Callout for career-ops — arrow from label to bar endpoint
    ax.annotate(
        "#3 all-time",
        xy=(stars_24h[highlight_idx], highlight_idx),
        xytext=(12500, highlight_idx + 2.2),
        fontsize=14, fontweight="bold", color="#FF4500",
        arrowprops=dict(arrowstyle="-|>", color="#FF4500", lw=2,
                        connectionstyle="arc3,rad=0.3"),
        bbox=dict(boxstyle="round,pad=0.4", facecolor="#FF450018",
                  edgecolor="#FF4500", linewidth=1.5),
    )

    # Legend
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor="#C9D1D9", alpha=0.9, label="First 24h"),
        Patch(facecolor="#C9D1D9", alpha=0.2, edgecolor="#C9D1D944", label="First 48h"),
    ]
    ax.legend(handles=legend_elements, loc="lower right", fontsize=10,
              facecolor="#161B22", edgecolor="#30363D", labelcolor="#C9D1D9")

    fig.tight_layout(pad=2.5)
    out = ASSETS_DIR / "viral_ranking.png"
    fig.savefig(out, dpi=300, facecolor="#0D1117", bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


def plot_first_week_race():
    """Show cumulative stars over first 7 days for top repos."""
    import json
    from datetime import datetime, timedelta

    cache_dir = Path(__file__).parent / "cache"

    # Repos we have full cache for + the verified ones
    # Use cached data where available
    repo_configs = {
        "career-ops": {"color": "#FF4500", "lw": 4},
        "DeepSeek-V3": {"color": "#06B6D4", "lw": 2},
        "AutoGPT": {"color": "#10B981", "lw": 2},
        "ollama": {"color": "#8B5CF6", "lw": 2},
        "open-webui": {"color": "#3B82F6", "lw": 2},
        "browser-use": {"color": "#F59E0B", "lw": 2},
        "screenshot-to-code": {"color": "#EC4899", "lw": 2},
        "Flowise": {"color": "#A855F7", "lw": 1.5},
    }

    fig, ax = plt.subplots(figsize=(16, 9))
    fig.patch.set_facecolor("#0D1117")
    ax.set_facecolor("#0D1117")

    for fname in sorted(cache_dir.glob("*.json")):
        with open(fname) as f:
            timestamps = json.load(f)
        if not timestamps:
            continue

        repo_short = fname.stem.split("_")[-1]
        if repo_short not in repo_configs:
            continue

        cfg = repo_configs[repo_short]
        dates = sorted([datetime.fromisoformat(t.replace("Z", "+00:00")) for t in timestamps])
        first = dates[0]

        # Build hourly cumulative for first 14 days
        hours = []
        counts = []
        for h in range(0, 14 * 24 + 1):
            cutoff = first + timedelta(hours=h)
            count = sum(1 for d in dates if d <= cutoff)
            hours.append(h / 24)  # Convert to days
            counts.append(count)

        is_hl = repo_short == "career-ops"
        ax.plot(hours, counts, color=cfg["color"], linewidth=cfg["lw"],
                alpha=1.0 if is_hl else 0.6, zorder=10 if is_hl else 5,
                label=f"{repo_short} ({max(counts):,})")

        # Endpoint annotation for career-ops
        if is_hl:
            ax.annotate(f" {max(counts):,}", xy=(hours[-1], max(counts)),
                        color=cfg["color"], fontsize=12, fontweight="bold", va="center")

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["bottom"].set_color("#30363D")
    ax.spines["left"].set_color("#30363D")
    ax.tick_params(colors="#8B949E", labelsize=11)
    ax.yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f"{int(x):,}"))

    ax.set_xlabel("Days since first star", color="#C9D1D9", fontsize=13)
    ax.set_ylabel("Cumulative Stars", color="#C9D1D9", fontsize=13)
    ax.set_title("First 14 Days: Growth Race of the Most Viral Repos",
                 color="#C9D1D9", fontsize=18, fontweight="bold", pad=15)
    ax.legend(loc="upper left", fontsize=10, facecolor="#161B22", edgecolor="#30363D", labelcolor="#C9D1D9")

    fig.tight_layout(pad=2)
    out = ASSETS_DIR / "viral_first_week_race.png"
    fig.savefig(out, dpi=300, facecolor="#0D1117", bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


if __name__ == "__main__":
    plot_viral_ranking()
    plot_first_week_race()
