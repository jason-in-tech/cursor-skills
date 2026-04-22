"""Generate a color-coded heatmap PNG from a GFM pipe-table.

Input table shape:
  - First column  -> row labels (kept as strings)
  - First row     -> column labels (kept as strings)
  - Remaining cells -> floats (bold/italic/code markers and `,`/`%` stripped)

The color palette is fixed (red #FF9696 -> white -> green #96FF96) so that
every heatmap in a report is visually consistent.

Typical usage:
  cat > /tmp/tbl.md <<EOF
  | Range | B0 | B1 | B2 |
  | --- | --- | --- | --- |
  | [0, 25) | 0.952 | 0.969 | 0.897 |
  EOF
  python scripts/make_heatmap.py --md-file /tmp/tbl.md --output /tmp/h.png \\
      --normalize row --direction higher-is-better
"""
import argparse
import re
import sys
import textwrap

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap


# ---------------------------------------------------------------------------
# Markdown pipe-table parser
# ---------------------------------------------------------------------------

_SEP_RE = re.compile(
    r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$"
)


def _split_row(row: str) -> list[str]:
    row = row.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|"):
        row = row[:-1]
    return [c.strip() for c in row.split("|")]


def _to_float(cell: str) -> float:
    s = cell
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    s = re.sub(r"\*(.+?)\*", r"\1", s)
    s = re.sub(r"`(.+?)`", r"\1", s)
    s = s.replace(",", "").replace("%", "").strip()
    try:
        return float(s)
    except ValueError:
        return float("nan")


def parse_md_table(text: str):
    """Parse the first pipe-table in `text`.

    Returns (col_labels, row_labels, values_ndarray).
    """
    lines = [l.rstrip() for l in text.splitlines() if "|" in l]
    sep_idx = None
    for i, l in enumerate(lines):
        if _SEP_RE.match(l):
            sep_idx = i
            break
    if sep_idx is None:
        raise ValueError(
            "No markdown-table separator line (|---|---|...|) found. "
            "The --md-file should contain ONLY the table lines."
        )
    header_cells = _split_row(lines[sep_idx - 1])
    data_rows = [_split_row(l) for l in lines[sep_idx + 1:]]

    col_labels = header_cells[1:]
    row_labels = [r[0] for r in data_rows]
    values = np.array(
        [[_to_float(c) for c in r[1:]] for r in data_rows],
        dtype=float,
    )
    return col_labels, row_labels, values


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def _norm_slice(slice_: np.ndarray, direction: str, center=None) -> np.ndarray:
    if center is not None:
        centered = slice_ - center
        abs_max = float(np.nanmax(np.abs(centered)))
        if not np.isfinite(abs_max) or abs_max == 0:
            return np.full_like(slice_, 0.5)
        u = 0.5 + 0.5 * centered / abs_max
        u = np.clip(u, 0.0, 1.0)
        return u if direction == "higher-is-better" else (1.0 - u)
    vmin, vmax = np.nanmin(slice_), np.nanmax(slice_)
    if vmax == vmin:
        return np.full_like(slice_, 0.5)
    u = (slice_ - vmin) / (vmax - vmin)
    return u if direction == "higher-is-better" else (1 - u)


def normalize(values: np.ndarray, mode: str, direction: str, center=None) -> np.ndarray:
    t = np.zeros_like(values, dtype=float)
    if mode == "row":
        for i in range(values.shape[0]):
            t[i] = _norm_slice(values[i], direction, center)
    elif mode == "column":
        for j in range(values.shape[1]):
            t[:, j] = _norm_slice(values[:, j], direction, center)
    else:
        t = _norm_slice(values, direction, center)
    return t


# ---------------------------------------------------------------------------
# Plot
# ---------------------------------------------------------------------------

def render(
    col_labels,
    row_labels,
    values,
    output,
    normalize_mode="row",
    direction="higher-is-better",
    headers_position="top",
    annotate_best_worst=True,
    value_fmt="{:.3f}",
    y_label=None,
    title=None,
    figsize=None,
    col_wrap=12,
    row_wrap=0,
    center_value=None,
):
    if col_wrap and col_wrap > 0:
        col_labels = [
            textwrap.fill(lbl, width=col_wrap, break_long_words=False)
            for lbl in col_labels
        ]
    if row_wrap and row_wrap > 0:
        row_labels = [
            textwrap.fill(lbl, width=row_wrap, break_long_words=False)
            for lbl in row_labels
        ]
    t = normalize(values, normalize_mode, direction, center_value)
    cmap = LinearSegmentedColormap.from_list(
        "rwg", ["#F25C5C", "#FFFFFF", "#4FCB5C"]
    )
    n_rows, n_cols = values.shape
    if figsize is None:
        figsize = (max(6.0, 1.6 * n_cols + 2.0), max(2.0, 0.9 * n_rows + 1.4))

    fig, ax = plt.subplots(figsize=figsize)
    ax.imshow(t, cmap=cmap, aspect="auto", vmin=0, vmax=1)

    for i in range(n_rows):
        row = values[i]
        rmax, rmin = np.nanmax(row), np.nanmin(row)
        best_val, worst_val = (rmax, rmin) if direction == "higher-is-better" else (rmin, rmax)
        for j in range(n_cols):
            v = values[i, j]
            is_best = (v == best_val) if normalize_mode == "row" else False
            is_worst = (v == worst_val) if normalize_mode == "row" else False
            weight = "bold" if is_best else "normal"
            ax.text(j, i, value_fmt.format(v), ha="center", va="center",
                    fontsize=15.5, fontweight=weight, color="black")
            if annotate_best_worst and normalize_mode == "row":
                if is_best:
                    ax.text(j, i + 0.34, "↑ best", ha="center", va="center",
                            fontsize=9.5, color="#1B5E20", fontstyle="italic")
                elif is_worst:
                    ax.text(j, i + 0.34, "↓ worst", ha="center", va="center",
                            fontsize=9.5, color="#B71C1C", fontstyle="italic")

    ax.set_xticks(range(n_cols))
    ax.set_xticklabels(col_labels, fontsize=13.5)
    ax.set_yticks(range(n_rows))
    ax.set_yticklabels(row_labels, fontsize=16.5, fontfamily="monospace")

    if headers_position == "top":
        ax.xaxis.set_ticks_position("top")
        ax.xaxis.set_label_position("top")

    ax.set_xticks(np.arange(-0.5, n_cols), minor=True)
    ax.set_yticks(np.arange(-0.5, n_rows), minor=True)
    ax.grid(which="minor", color="#999999", linestyle="-", linewidth=0.5)
    ax.tick_params(which="minor", length=0)
    ax.tick_params(which="major", length=0)
    for spine in ax.spines.values():
        spine.set_edgecolor("#888888")

    if y_label:
        ax.set_ylabel(y_label, fontsize=12.5)
    if title:
        ax.set_title(title, fontsize=12, pad=10)

    plt.tight_layout()
    plt.savefig(output, dpi=170, bbox_inches="tight", facecolor="white")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description=__doc__)
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--md-file", help="Path to a file containing ONLY the markdown table lines.")
    src.add_argument("--md-stdin", action="store_true",
                     help="Read the markdown table from stdin.")

    p.add_argument("--output", required=True, help="Output PNG path.")
    p.add_argument("--normalize", choices=["row", "column", "global"], default="row",
                   help="Color-scale normalization axis. Default: row.")
    p.add_argument("--direction",
                   choices=["higher-is-better", "lower-is-better"],
                   default="higher-is-better",
                   help="higher-is-better (AP, recall, F1) vs lower-is-better (MAE, RMSE, loss).")
    p.add_argument("--headers-position", choices=["top", "bottom"], default="top")
    p.add_argument("--no-annotate", dest="annotate", action="store_false", default=True,
                   help="Disable the '↑ best' / '↓ worst' subscripts.")
    p.add_argument("--value-fmt", default="{:.3f}",
                   help="Python format string for cell values. Default {:.3f}.")
    p.add_argument("--y-label", default=None, help="Y-axis label (optional).")
    p.add_argument("--title", default=None, help="Plot title (optional).")
    p.add_argument("--figsize", default=None, help="W,H inches, e.g. 13,3.3 (optional).")
    p.add_argument("--col-wrap", type=int, default=12,
                   help="Wrap column labels wider than N chars at spaces. 0 = no wrap. Default 12.")
    p.add_argument("--row-wrap", type=int, default=0,
                   help="Wrap row labels wider than N chars at spaces. 0 = no wrap. Default 0.")
    p.add_argument("--center-value", type=float, default=None,
                   help="Center the color scale on this value (0 = white, symmetric). "
                        "Use with signed-delta tables. Disables --direction sign flip.")
    args = p.parse_args()

    text = sys.stdin.read() if args.md_stdin else open(args.md_file).read()
    col_labels, row_labels, values = parse_md_table(text)

    figsize = None
    if args.figsize:
        figsize = tuple(float(x) for x in args.figsize.split(","))

    render(
        col_labels=col_labels,
        row_labels=row_labels,
        values=values,
        output=args.output,
        normalize_mode=args.normalize,
        direction=args.direction,
        headers_position=args.headers_position,
        annotate_best_worst=args.annotate,
        value_fmt=args.value_fmt,
        y_label=args.y_label,
        title=args.title,
        figsize=figsize,
        col_wrap=args.col_wrap,
        row_wrap=args.row_wrap,
        center_value=args.center_value,
    )
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
