"""README charts from the audit results (October 2026). Regenerate: python docs/make_charts.py

Numbers are copied from the workflow runs linked in the README:
  compatibility  - audit run 37393191985 (13 images x 7 emulated CPU models)
  tecnativa      - tecnativa-fix runs 37425193526 (EPYC 9V45) and 37400226456 (EPYC 7763),
                   median of 5 alternating rounds on the same runner
Style matches the rest of the author's repositories: one light surface, one highlight
colour, grey for everything else, a red rule for the thing being compared against.
"""
import pathlib

import matplotlib
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

SURFACE, INK, INK_2, MUTED = "#fcfcfb", "#0b0b0b", "#52514e", "#898781"
BASELINE, S1, GOOD, CRITICAL = "#c3c2b7", "#2a78d6", "#0ca30c", "#d03b3b"
OUT = pathlib.Path(__file__).parent / "charts"


def style():
    matplotlib.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "text.color": INK, "axes.labelcolor": INK_2, "xtick.color": MUTED, "ytick.color": MUTED,
        "axes.edgecolor": BASELINE, "axes.linewidth": 1.0,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "grid.color": BASELINE, "grid.alpha": 0.45, "grid.linewidth": 0.8,
        "font.size": 11, "axes.titlesize": 13, "axes.titleweight": "bold",
        "axes.titlelocation": "left", "axes.titlepad": 12, "figure.dpi": 120,
    })


def finish(fig, name, subtitle):
    fig.text(0.0, 1.0, subtitle, ha="left", va="bottom", fontsize=10, color=INK_2, transform=fig.transFigure)
    fig.tight_layout()
    OUT.mkdir(exist_ok=True)
    fig.savefig(OUT / name, bbox_inches="tight")
    plt.close(fig)
    print(f"  {OUT / name}")


CPUS = ["Nehalem", "Sandy\nBridge", "Ivy\nBridge", "Haswell", "Cortex\nA53", "Cortex\nA72", "Neoverse\nN1"]
# (image, crash per CPU model, first faulting instruction / where)
ROWS = [
    ("bitnami/postgresql:latest", [1, 1, 1, 1, 1, 1, 0], "vpermt2d (AVX-512) · fabs h (FP16)"),
    ("tecnativa/postgres-autoconf:18-alpine", [1, 1, 1, 0, 1, 1, 1], "shlx, vcvtps2ph · cntd (SVE)"),
    ("timescale/timescaledb-ha (pgvectorscale)", [1, 1, 1, 0, 0, 0, 0], "vinserti128 in foldhash seed"),
    ("pgvector/pgvector:pg17 / pg18", [0] * 7, ""),
    ("cloudnative-pg/postgresql:17-standard", [0] * 7, ""),
    ("supabase/postgres:17.11", [0] * 7, ""),
    ("paradedb/paradedb:0.26.0", [0] * 7, ""),
    ("immich-app/postgres (both tags)", [0] * 7, ""),
    ("tensorchord/vchord-postgres", [0] * 7, ""),
    ("ankane/pgvector (0.5.1)", [0] * 7, ""),
    ("lifeboat/postgresql:18", [0] * 7, ""),
]


def compatibility():
    fig, ax = plt.subplots(figsize=(11.5, 0.46 * len(ROWS) + 2.2))
    ax.grid(False)
    for s in ax.spines.values():
        s.set_visible(False)
    for i, (_, cells, why) in enumerate(ROWS):
        y = len(ROWS) - 1 - i
        for j, bad in enumerate(cells):
            box = FancyBboxPatch((j + 0.08, y + 0.1), 0.84, 0.8, boxstyle="round,pad=0,rounding_size=0.12",
                                 facecolor=CRITICAL if bad else "#e7f1e4", edgecolor="none")
            ax.add_patch(box)
            ax.text(j + 0.5, y + 0.5, "crash" if bad else "runs", ha="center", va="center", fontsize=9,
                    color="white" if bad else "#4a7a44", fontweight="bold" if bad else "normal")
        if why:
            ax.text(len(CPUS) + 0.2, y + 0.5, why, va="center", fontsize=10, color=INK)
    ax.axvline(4, color=MUTED, linewidth=1.2, linestyle=(0, (3, 3)))
    ax.set_xlim(0, len(CPUS) + 3.6)
    ax.set_ylim(0, len(ROWS))
    ax.set_xticks([j + 0.5 for j in range(len(CPUS))], CPUS, rotation=0, fontsize=9.5, color=INK_2)
    ax.xaxis.tick_top()
    ax.tick_params(length=0)
    ax.set_yticks([len(ROWS) - 1 - i + 0.5 for i in range(len(ROWS))], [r[0] for r in ROWS], fontsize=10.5, color=INK_2)
    ax.text(2, -0.55, "amd64", ha="center", va="center", fontsize=10, color=MUTED)
    ax.text(5.5, -0.55, "arm64", ha="center", va="center", fontsize=10, color=MUTED)
    ax.text(len(CPUS) + 0.2, len(ROWS) + 0.05, "first faulting instruction", fontsize=10, color=MUTED, va="bottom")
    ax.set_title("Which PostgreSQL vector images crash on which CPU", pad=34)
    finish(fig, "1_compatibility.png",
           "Real server, emulated CPU model (QEMU 10). Crash = backend killed by SIGILL. Native runs: Bitnami also crashes on real EPYC 7763 servers.")


def tecnativa():
    # raw medians in seconds (ms / 1000) so the ratios match the PR text exactly
    runs = [("AMD EPYC 9V45", 111.313, 11.179, 1.903, 0.507), ("AMD EPYC 7763", 152.328, 18.477, 2.704, 0.714)]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11.5, 3.6))
    for ax, idx, title, unit in [(a1, (1, 2), "HNSW index build, 20,000 × 768", "s"),
                                 (a2, (3, 4), "500 nearest-neighbour queries", "s")]:
        labels, vals, cols = [], [], []
        for name, *v in runs:
            labels += [f"{name}\nmaster", f"{name}\nOPTFLAGS=\"\""]
            vals += [v[idx[0] - 1], v[idx[1] - 1]]
            cols += [BASELINE, S1]
        ys = list(range(len(vals)))[::-1]
        ax.barh(ys, vals, height=0.62, color=cols)
        top = max(vals)
        for y, v, c in zip(ys, vals, cols):
            ax.text(v + top * 0.02, y, f"{v:.1f} {unit}" if v >= 10 else f"{v:.2f} {unit}", va="center",
                    fontsize=10.5, color=INK if c == S1 else INK_2, fontweight="bold" if c == S1 else "normal")
        for k, (name, *v) in enumerate(runs):
            speed = v[idx[0] - 1] / v[idx[1] - 1]
            ax.text(top * 1.32, ys[2 * k] - 0.5, f"{speed:.1f}×", va="center", ha="right", fontsize=13,
                    color=GOOD, fontweight="bold")
        ax.set_yticks(ys, labels, fontsize=9.5, color=INK_2)
        ax.set_xlim(0, top * 1.35)
        ax.set_title(title)
        ax.set_xlabel("seconds (median of 5)")
    finish(fig, "2_tecnativa_speed.png",
           "tecnativa/postgres-autoconf built from its own master, unchanged (grey) vs the one-line fix in PR #42 (blue). Same runner, alternating.")


if __name__ == "__main__":
    style()
    compatibility()
    tecnativa()
