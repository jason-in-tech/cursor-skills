---
name: table-heatmap
description: >-
  Generate a color-coded heatmap PNG from a markdown pipe-table so that any
  markdown renderer (including ones that strip inline HTML) shows per-row or
  per-column performance comparisons visually. Use when the user wants to
  colorize a markdown table, highlight best/worst values across branches or
  variants, visualize performance comparisons, or when inline HTML styling
  (`<td style>`, `<span style>`) renders as raw code in their viewer.
---

# Table Heatmap Generator

Generate a red → white → green heatmap PNG from a GFM pipe-table. Paste the PNG
into a markdown report above the original text table. The text table stays in
the document for search / diff / copy-paste; the PNG carries the color signal.

Script: `scripts/make_heatmap.py` (bundled).

## When to use

- The user asks to colorize, color-code, or heatmap a markdown table.
- Numeric table comparing variants / branches / runs where the reader should
  spot best/worst at a glance.
- Renderer does not support inline HTML (`<td style="...">` shows as raw text).
- Multiple tables in one report that should share a consistent visual style.

## Workflow

1. **Extract** the target table into a temp file. Include only the `|...|`
   lines (header row, `|---|` separator, and data rows). Drop all surrounding
   prose. Bold markers like `**0.976**` are OK; units (`m`, `rad`, `%`, `ms`)
   must be stripped or the cell becomes NaN.

2. **Decide two parameters:**

   | Parameter | Options | Choose by |
   |---|---|---|
   | `--normalize` | `row`, `column`, `global` | `row` (default) when each row is a metric slice and columns are variants being compared. `column` when columns are different metrics. `global` for a single-metric grid. |
   | `--direction` | `higher-is-better`, `lower-is-better` | `higher`: AP, recall, F1, pass-rate. `lower`: MAE, RMSE, loss, latency, error. |

3. **Run the script:**

   ```bash
   python ~/.cursor/skills/table-heatmap/scripts/make_heatmap.py \
       --md-file /tmp/tbl.md \
       --output  /path/to/report/folder/report_X_heatmap.png \
       --normalize row \
       --direction higher-is-better \
       --y-label "Forward range bin"
   ```

   Output path convention: drop the PNG into the same folder that already
   hosts the report's other images (alongside `report_*.png` files).

4. **Insert the image reference ABOVE the existing markdown table:**

   ```markdown
   ![Per-row heatmap: green = best branch in that row, red = worst. <one-line finding>.](report_X_heatmap.png)

   | Original | Plain | Markdown | Table |
   | --- | --- | --- | --- |
   | ... | ... | ... | ... |
   ```

   Do **not** delete the text table. The image is visual; the text is
   authoritative / diffable / searchable / machine-readable.

## Key CLI flags

| Flag | Default | Notes |
|---|---|---|
| `--md-file PATH` / `--md-stdin` | — | Exactly one is required. |
| `--output PATH` | — | Required. Use `.png`. |
| `--normalize {row,column,global}` | `row` | See step 2. |
| `--direction {higher-is-better,lower-is-better}` | `higher-is-better` | See step 2. |
| `--headers-position {top,bottom}` | `top` | Column labels above the grid. |
| `--value-fmt STR` | `{:.3f}` | Python format, e.g. `{:.1%}`, `{:.0f}`, `{:.4f}`. |
| `--y-label STR` | none | Short axis label. `\n` for line break. |
| `--title STR` | none | Usually leave empty; caption the image via the markdown alt text instead. |
| `--figsize W,H` | auto | Override if labels collide (15+ cols → bump width). |
| `--col-wrap N` | `12` | Wrap column labels wider than N chars at spaces. `0` disables. |
| `--row-wrap N` | `0` | Wrap row labels wider than N chars at spaces. `0` disables. |
| `--center-value N` | off | Center the color scale on N (symmetric, `0 = white`). Use with **signed-delta** tables (e.g. `+5%` / `-3%`). Values farther from N become more saturated. Best paired with `--normalize global` for a consistent scale across the whole grid. |
| `--no-annotate` | off | Disables `↑ best` / `↓ worst` subscripts. |

## Common pitfalls

- **Table file contains surrounding prose.** Parser requires only the
  `|...|` lines of one table. Strip everything else into the temp file.
- **Mixed directions in one table.** One row AP (higher-better), another row
  latency (lower-better) cannot share one heatmap. Split into two tables and
  call the script twice.
- **Non-numeric cells.** Units or text in value cells → NaN → white cell.
  Strip units before passing.
- **Very small value ranges.** If all cells in a row are within 0.001 the
  heatmap is visually uninformative. That's diagnostic: note it in the
  surrounding prose instead of adding color.
- **Signed deltas (e.g. "B2 vs B0 Δ%").** Default `row`/`column`/`global`
  normalization is min-max, so an all-positive grid with `vmin = +0.4%` would
  paint the smallest positive cell **red**. Pass `--normalize global
  --center-value 0` to anchor white at 0; positives become green, negatives
  become red, color intensity scales with `|value| / max(|value|)`.

## Example (the one that shipped)

Source table (Main CAR AP by Range, 7 branches × 3 ranges):

```
| Range | B0 Baseline | B1 A110+NV frozen | B2 A110+NV unfrozen | B3 FE+NV frozen | B4 FE+autolabel frozen | B5 A110+autolabel frozen | B6 A110+autolabel unfrozen |
| --- | --- | --- | --- | --- | --- | --- | --- |
| [0, 25) | 0.952 | 0.969 | 0.897 | 0.975 | **0.976** | 0.956 | 0.967 |
| [25, 50) | 0.869 | 0.867 | **0.890** | 0.863 | 0.877 | 0.847 | 0.838 |
| [50, 100) | 0.521 | 0.518 | **0.548** | 0.493 | 0.533 | 0.469 | 0.464 |
```

Invocation:

```bash
python ~/.cursor/skills/table-heatmap/scripts/make_heatmap.py \
    --md-file /tmp/main_ap.md \
    --output  cruise/mlp/.../notebooks/output/report_main_ap_heatmap.png \
    --normalize row \
    --direction higher-is-better \
    --y-label "Forward range bin\n(bin_x × |y|<10m)"
```

Insert:

```markdown
![Main CAR AP heatmap. Per-row normalized: green = best branch, red = worst. B4 best at [0, 25), B2 at [25, 50) and [50, 100).](report_main_ap_heatmap.png)

| Range | B0 Baseline | ... |
...
```

## Style contract (do not change per-invocation)

The script's palette (`#FF9696` / `#FFFFFF` / `#96FF96`) and cell/font sizing
are fixed so every heatmap in a report matches. If a report needs a different
palette, edit the script rather than adding per-call flags, so consistency is
preserved.
