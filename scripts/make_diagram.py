"""The architecture diagram.

Drawn at explicit coordinates rather than by a layout engine, because the
failure mode of every auto-laid-out diagram is boxes sitting on top of each
other. The script refuses to write the file if any two rectangles overlap — the
band captions included, which is how the first version quietly hid four of its
own labels — or if any box's text is taller than the box holding it.

The figure is sized so one data unit is one inch, which makes the text-fits
check honest: a line of N-point type is N/72 inches tall, and nothing here
guesses.
"""
from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

W, H = 20.0, 14.8                      # inches; xlim/ylim match, so 1 unit = 1"

INK, MUTED, LINE, PAPER, BAND = "#12232e", "#5a6b78", "#b7c3cc", "#ffffff", "#f2f5f7"
AGENT, AGENT_ED = "#e8f1f8", "#3d7ea6"
TOOL,  TOOL_ED  = "#eef3ee", "#5f8a63"
DATA,  DATA_ED  = "#fdf3e7", "#c98b3a"
SAFE,  SAFE_ED  = "#fdecec", "#c0504d"

COLS = [(0.90, 5.30), (6.90, 5.30), (12.90, 6.20)]     # (x, width) per column
CENT = [x + w / 2 for x, w in COLS]

PAD = 0.30                             # breathing room inside every box
placed: list[tuple[float, float, float, float, str]] = []


def _claim(x, y, w, h, name):
    for bx, by, bw, bh, other in placed:
        if x < bx + bw and bx < x + w and y < by + bh and by < y + h:
            raise SystemExit(f"OVERLAP: {name!r} collides with {other!r}")
    placed.append((x, y, w, h, name))


def band(ax, y, h, caption):
    """A grey band, with its caption in space no box is allowed to occupy."""
    ax.add_patch(FancyBboxPatch((0.45, y), W - 0.90, h,
                                boxstyle="round,pad=0,rounding_size=0.10",
                                fc=BAND, ec="none", zorder=0))
    # zorder above the arrows, on a band-coloured plate: the connectors run
    # through this strip, and a caption with a line drawn across it is a
    # caption nobody reads.
    ax.text(0.80, y + h - 0.18, caption.upper(), fontsize=10.5, color=MUTED,
            fontweight="bold", va="top", ha="left", zorder=6,
            bbox=dict(facecolor=BAND, edgecolor="none", pad=3.0))
    _claim(0.80, y + h - 0.60, W - 1.60, 0.42, f"caption “{caption[:26]}”")


def box(ax, col, y, h, title, body, fc, ec, t_size=14.5, b_size=10.8):
    """One rounded box with its text block centred vertically inside it."""
    x, w = COLS[col] if isinstance(col, int) else col
    label = title.replace("\n", " ")[:44]
    _claim(x, y, w, h, label)

    titles = title.split("\n")
    t_lh, b_lh = t_size / 72 * 1.35, b_size / 72 * 2.0
    gap = 0.16 if body else 0.0
    content = len(titles) * t_lh + gap + len(body) * b_lh
    if content > h - PAD:
        raise SystemExit(
            f"TEXT OVERFLOWS {label!r}: needs {content + PAD:.2f}in, box is {h:.2f}in")

    ax.add_patch(FancyBboxPatch((x, y), w, h,
                                boxstyle="round,pad=0,rounding_size=0.13",
                                fc=fc, ec=ec, lw=1.7, zorder=2))

    ty = y + h / 2 + content / 2
    for line in titles:
        ax.text(x + w / 2, ty, line, fontsize=t_size, color=INK,
                fontweight="bold", ha="center", va="top", zorder=3)
        ty -= t_lh
    ty -= gap
    for line in body:
        ax.text(x + w / 2, ty, line.lstrip("* "), fontsize=b_size,
                color=INK if line.startswith("*") else MUTED, ha="center",
                va="top", zorder=3,
                fontweight="bold" if line.startswith("*") else "normal")
        ty -= b_lh


def arrow(ax, x, y0, y1, colour=LINE, dashed=False, style="-|>"):
    ax.add_patch(FancyArrowPatch((x, y0), (x, y1), arrowstyle=style,
                                 mutation_scale=17, color=colour, lw=1.9,
                                 zorder=1, linestyle="--" if dashed else "-",
                                 shrinkA=2, shrinkB=2))


fig, ax = plt.subplots(figsize=(W, H))
ax.set_xlim(0, W); ax.set_ylim(0, H); ax.axis("off")
fig.patch.set_facecolor(PAPER)

ax.text(0.80, H - 0.45, "VitaCabinet", fontsize=31, fontweight="bold",
        color=INK, va="top")
ax.text(0.80, H - 1.20,
        "Three agents on the Strands Agents SDK. The one that writes to a person holds no tools.",
        fontsize=13.5, color=MUTED, va="top")
ax.plot([0.80, W - 0.80], [H - 1.55, H - 1.55], color=LINE, lw=1.2)

# ------------------------------------------------------------------ input
band(ax, 11.20, 1.85, "what goes in")
box(ax, 0, 11.30, 1.05, "Photos of the drawer",
    ["one image per box, text read off the label"], PAPER, LINE, 13.5, 10.5)
box(ax, 1, 11.30, 1.05, "A schedule",
    ["the recall check nobody remembers to run"], PAPER, LINE, 13.5, 10.5)
box(ax, 2, 11.30, 1.05, "Pharmacy · clinician · the person",
    ["each list carries its own source and date"], PAPER, LINE, 13.5, 10.5)

# ----------------------------------------------------------------- agents
band(ax, 7.55, 3.35, "agents  ·  strands agents sdk  ·  amazon bedrock, eu-north-1")
box(ax, 0, 7.70, 2.50, "Identifier",
    ["reads the drawer",
     "*may answer “I could not read this”",
     "a guess becomes a false alarm downstream"], AGENT, AGENT_ED)
box(ax, 1, 7.70, 2.50, "Watchman",
    ["runs on the schedule, not on a request",
     "*recalls arrive when they arrive",
     "reports batches, never a medicine"], AGENT, AGENT_ED)
box(ax, 2, 7.70, 2.50, "Scribe",
    ["turns one finding into one question",
     "*holds no tools — see below",
     "never meets a user, so cannot be argued with"], SAFE, SAFE_ED)

for x in CENT:
    arrow(ax, x, 11.28, 10.22)

# ------------------------------------------------------------------ tools
band(ax, 4.80, 2.45, "the tools each agent is given")
box(ax, 0, 4.90, 1.65, "identify_medicine\nfind_duplicate_medicines",
    ["identity and duplicates — clerical"], TOOL, TOOL_ED, 12.5, 10.5)
box(ax, 1, 4.90, 1.65, "check_for_recalls",
    ["a safety lookup — kept apart"], TOOL, TOOL_ED, 12.5, 10.5)
box(ax, 2, 4.90, 1.65, "SCRIBE_TOOLS = []",
    ["*the safety boundary is a capability,",
     "*not a paragraph in a prompt"], SAFE, SAFE_ED, 13.5, 11.0)

for x in CENT[:2]:
    arrow(ax, x, 7.68, 6.57)
arrow(ax, CENT[2], 7.68, 6.57, colour=SAFE_ED, dashed=True)

# ------------------------------------------------------------------- data
band(ax, 2.25, 2.25, "outside authorities  ·  public, checkable, not invented here")
box(ax, 0, 2.35, 1.45, "RxNorm / RxNav  (NIH)",
    ["drug identity and ingredients"], DATA, DATA_ED, 13.0, 10.5)
box(ax, 1, 2.35, 1.45, "openFDA enforcement  (FDA)",
    ["live recalls, and the affected lots"], DATA, DATA_ED, 13.0, 10.5)
box(ax, 2, 2.35, 1.45, "nothing to look up",
    ["it is told what was found, and writes"], PAPER, SAFE_ED, 13.0, 10.5)

for x in CENT[:2]:
    arrow(ax, x, 4.88, 3.82, style="<|-|>")

# ---------------------------------------------------------------- cabinet
box(ax, (0.90, 18.20), 0.30, 1.60,
    "The Cabinet  —  every fact carries its source and its age",
    ["pharmacy record 180 days   ·   clinician 120   ·   the person 90   ·   a box in the drawer 60   ·   inferred 30",
     "*whatever decays below half becomes the queue the Scribe writes questions from"],
    PAPER, INK, 14.0, 11.0)

for x in CENT[:2]:
    arrow(ax, x, 2.33, 1.92)
arrow(ax, CENT[2], 4.88, 1.92, colour=SAFE_ED, dashed=True)

fig.savefig("docs/img/architecture.png", dpi=100, facecolor=PAPER,
            bbox_inches="tight", pad_inches=0.25)
print(f"wrote docs/img/architecture.png — {len(placed)} rectangles, "
      f"0 overlaps, 0 text overflows")
