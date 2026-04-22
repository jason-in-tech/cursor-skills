# Write Technical Report

Structure and publish technical experiment or analysis write-ups (markdown first, then Confluence or Slack as needed). Use when the user wants a formal report, status doc, or results summary with clear metrics tables and links.

## Pre-flight: Authentication (two-tier)

Many report workflows touch **Glean** (`user-glean` MCP), **Confluence** (`confluence-publish` / Atlassian MCP), or other Cruise-authenticated tools.

**Tier 1** (try first):

```bash
authcli refresh
```

**Tier 2** (if MCP or cloud calls still fail with 401 / refresh errors): follow `~/.cursor/skills/cruise-auth-refresh/SKILL.md`.

## Workflow

1. **Sources**: Collect facts from code, notebooks, Centra/W&B links, BQ/Trino queries, and internal docs (Glean `search` → `read_document` when applicable).
2. **Outline**: Executive summary → context → method → results (tables, figures) → limitations → next steps.
3. **Draft**: Write in markdown to `~/.cursor/reports/<report_name>.md`. Include full URLs for every external reference (Centra, W&B, Confluence, Google Docs).
4. **Image suggestions**: For every figure/screenshot, insert a blockquote placeholder:
   ```
   > **IMAGE: [description]** - [source location] (e.g. notebook cell, W&B panel, script output).
   ```
   This tells the user exactly what to paste and where to find it. Use square brackets (not `<>`) for placeholders; `<>` in prose triggers the markdown-preview crash (see [Markdown-safe syntax](#markdown-safe-syntax-avoid-bare--and--outside-backticks)).
5. **Co-edit**: Review the markdown file with the user. Iterate until content is final. After each substantive edit pass, run the markdown-crash scanner: `python3 ~/.cursor/skills/fix-markdown-crash/scripts/scan_md.py <path>` should print `All clean`. Reword any reported bare `<` / `>` per the safe-syntax table.
6. **Publish**: Choose target based on image density:
   - **Image-heavy** (eval results, viz, screenshots) → **Google Doc**: use `google-doc-publish` skill (`~/.cursor/skills/google-doc-publish/SKILL.md`). This automates the full flow: markdown → HTML with base64-embedded images → Google Doc with proper tables, headings, internal links, and formatting. No manual image pasting needed.
   - **Image-light** (plans, config summaries, tables) → **Confluence**: agent publishes via `confluence-publish` skill
   - **Slack**: follow team conventions and link the canonical doc

## Fact Discipline

When writing technical reports, separate claims into four buckets and label them accurately in the prose:

1. **Formal definition**: What a spec, requirements doc, or design doc says.
2. **Current production behavior**: What code or deployed pipelines actually do today.
3. **Available data / signals**: What exists in the dataset or artifacts right now.
4. **Proposed approach**: What we recommend building next.

Do not blur these together.

- If the raw signals exist but the filter does not, say the filter is **proposed**, not "available in the dataset."
- If a heuristic is your recommendation, do not present it as the formal definition.
- If a formal definition does not exist, say so explicitly instead of reverse-engineering one from code.
- If production behavior differs from the spec, show both.
- When something is inferred or approximate, say that plainly.

Before finalizing a report, do a sentence-level audit:

- Can this sentence be tied to a source?
- If yes, keep it factual.
- If no, rewrite it as a recommendation, hypothesis, estimate, or open question.

## Natural Writing

Reports should sound like they were written by an engineer for another engineer, not by a template engine.

- Prefer direct prose over generic scaffolding like "Goal / Context / Method" when a simpler structure reads better.
- Keep the opening tight: say what was asked, what data exists, and what the proposed path is.
- Use tables when they genuinely help comparison; do not force every idea into a table.
- Avoid padded transitions, repeated framing, and over-explaining obvious points.
- Replace sweeping claims with precise ones. Example: "the signals are present, but the filter is not implemented yet."
- Favor short, concrete sentences over abstract summary language.
- If a section starts sounding like a pitch deck or generated summary, compress it.
- For priority labels, just write "P0" or "P1" - do not expand to "P0 priority" or "P1 priority." The reader knows what P0 means.

## Academic-paper register

For formal experiment write-ups (results readouts, ablation reports, eval summaries), target the register of a conference or workshop paper. The defaults below take precedence over general "natural writing" guidance when the user asks for an "academic" or "paper-style" tone.

### Tense and voice

- **Present tense, active voice.** "B2 improves AP at `[25, 50)`", not "B2 improved AP" or "AP was improved by B2".
- Use past tense only for one-off events (job submission, data collection) where tense matters: "We collected 189K SC3 frames in V0.14."
- First-person plural is fine ("We evaluate seven recipes"); avoid "I" and avoid meta-narration ("In this section we will discuss").

### Concision

- Target 1-3 sentences per bullet in an Executive Summary / Abstract.
- Every sentence either asserts a fact, states a limitation, or draws a conclusion. Remove sentences that exist only to "frame" or "set up" the next sentence.
- Drop filler phrases: "it is worth noting that", "in order to", "as a matter of fact", "it should be pointed out".
- Prefer the noun over the nominalization: "evaluate" over "perform an evaluation", "filter" over "apply a filtering step".
- Numbers as labels, not narrative: `Ego-lane recall: B2 52.4%, B4 52.7%, baseline 51.7%`, not "B2 achieves 52.4%, which is higher than baseline's 51.7% by 1.4%."

### Precision and hedging

- **Claim before evidence.** Lead each bullet with the finding, then the supporting numbers in the same sentence: `B2 improves CAR AP at [25, 50) (0.890, +2.5%)`. Not "We evaluated CAR AP at [25, 50). The value was 0.890 for B2 (+2.5%). This is an improvement."
- **Hedge explicitly once, then commit.** If a claim is not fully verified, label it once (`Root cause (hypothesis, not fully verified)`) and then state it directly. Do not re-hedge every sentence.
- Use "is", "improves", "does not reproduce" over "appears to", "seems to", "might", unless the hedge is load-bearing.
- Prefer `X ↔ Y dissociates` or `X is specific to Y` over prose chains of "if ... then ... however".

### Non-duplication: Abstract (Executive Summary) vs Conclusions (Key Findings)

Papers distinguish abstract from conclusions. Reports should do the same.

- **Executive Summary = abstract.** Top-line deltas, method one-liner, bottom line. Complete on its own: a reader who stops here knows what happened and what it means.
- **Key Findings = discussion / conclusions.** Only claims that require the full Results to support them, or that add interpretation / causal structure beyond the deltas.
- **Hard rule: every Key Finding must either (a) reference data not in the Exec Summary, (b) make a causal / mechanistic claim the summary cannot fit, or (c) identify a trade-off or dissociation across multiple experimental axes.** If a KF item only restates a summary bullet with slightly more words, delete it.
- Add a one-line disclaimer at the top of Key Findings if helpful: `Claims that add detail beyond the [Executive Summary](#executive-summary) deltas.`
- Preserve anchor-link stability: if an anchor like `[Key Findings #1]` is referenced from the summary, keep that item as #1 after trimming. Validate with the anchor script in the [cross-references section](#body---appendix-cross-references-unidirectional).

### Abstract (Executive Summary) shape

One paragraph of context → bullet list of findings (one per orthogonal axis: primary metric, secondary metrics, causal story, trade-offs) → one-paragraph conclusion stating the bottom line and next action.

- Start the opening paragraph with `We evaluate ...` (not `We evaluated`).
- Number of findings bullets: **4-6**. Fewer than 4 usually means too-coarse grouping; more than 6 usually means you're duplicating results material.
- Each bullet starts with a bolded noun phrase naming the axis (`**Mid/far detection AP:**`, `**Lead vehicle:**`), then a **colon**, then the claim + numbers.
- End with `**Conclusion:**` (or `**Bottom line:**` for informal contexts) in a single paragraph: winner, limitation, next action.

### Bolded label punctuation: colon for topic, period for thesis

Two different patterns, two different terminal punctuation marks. Pick the right one.

- **Topic label + elaboration → colon.** When the bolded text is a *topic marker* (a noun phrase naming what this bullet / paragraph is about) followed by the claim on the same line, use a colon. Colons introduce elaboration; periods create a hard stop that makes the sentence read as two fragments.
  - `**Mid/far detection AP:** B2 improves CAR AP at [25, 50) (0.890, +2.5%) ...`
  - `**Reading:** B2 is more confident on ~100 near-range non-CAR objects ...`
  - `**Conclusion:** B2 is the strongest first-pass candidate ...`
  - `**SC3 Protocol:** B0 and B2 tie at 93.2% pass rate ...`
- **Complete-sentence thesis + supporting evidence → period.** When the bolded text is itself a complete sentence stating a finding (subject + verb + predicate), end it with a period and follow with supporting evidence in a separate sentence.
  - `**The mid/far gain is specific to NVIDIA × unfreezing, not to unfreezing in general.** The autolabel control pair B5 vs B6 dissociates the two axes ...`
  - `**The NVIDIA training stage works.** B2 intermediate outperforms B0 on every metric ...`
- **Block-header period.** A bolded token on its own line that opens a block (`**Findings.**`, `**Finding:**`, `**Takeaway:**`) may use either a period or colon depending on whether content follows on a new line (period is fine for a standalone header line; colon is required when content continues on the same line).
- **Quick test.** Read the bolded text aloud. If it doesn't end as a complete sentence (e.g. `Mid/far detection AP` has no verb), it's a topic label and needs a colon. If it ends as a complete sentence (e.g. `The NVIDIA training stage works`), it takes a period.
- **Audit regex.** Topic-label-period-capitalized bullets are the failure mode: `rg -n --pcre2 '^[-*]\s+\*\*[A-Z][a-z][^*]{2,40}\.\*\*\s+[A-Z]' report.md`. Inspect each hit: if the bolded text is a noun phrase, swap the period for a colon.

### Findings / Reading / Observations blocks (post-table register)

The short paragraph that follows a results table ("**Findings:**", "**Reading:**", "**Observations.**") is the main body's equivalent of an abstract bullet and must obey the same rules:

- **Lead with the claim**, then the supporting number in the same sentence: `B2 improves [25, 50) AP to 0.890 (+2.5% vs 0.869) ...` not `When we looked at [25, 50), we saw that ...`.
- **Present tense, active voice.** Even for reporting a fixed experiment.
- **No em-dashes and no prose ` - ` pauses.** Use colons, semicolons, or periods (see [Punctuation](#punctuation-no-em-dashes-use-colons)).
- **One claim per bullet.** If a bullet strings two claims with "and", split it or demote the second to a sub-bullet.
- **Do not re-describe table values literally.** If the table already shows `B2 = 0.890, B0 = 0.869`, say what that means, not that "B2 is 0.890 and B0 is 0.869."
- **Cross-link, do not restate.** If an earlier finding justifies this one, link to that section rather than repeating the mechanism.

### Audit pass for paper register

Run this after a draft, before sharing:

1. Read the Exec Summary bullets and the Key Findings items side by side. Any item in KF that a reader could derive from one Exec Summary bullet alone → delete or rewrite to add new data.
2. Grep for tense drift: `rg '\b(performed|was|were|had been|did not)\b'` in the Exec Summary. Rewrite to present tense unless referring to a one-off event.
3. Grep for padding: `rg -n 'it is worth noting|in order to|it should be'`. Delete.
4. Grep for em-dashes and prose `-` pauses across the full draft, not just the summary: `rg -n '—' report.md` should return 0 hits; `rg -n --pcre2 '^(?!\s*\||\s*[-+*]).*[a-z]\s-\s[a-zA-Z]' report.md` should also return 0 hits (the guards skip table rows and list items).
5. Check every bullet opens with a noun phrase, not `We` or `The result`. Abstracts announce findings, they do not narrate the authors' process.
6. Count sentences per bullet. More than three → split into two bullets or move the tail to the supporting section.
7. **Run the markdown-crash scanner** to guarantee the preview will render: `python3 ~/.cursor/skills/fix-markdown-crash/scripts/scan_md.py report.md` must print `All clean`. If any bare `<` / `>` is reported outside backticks, reword per the [markdown-safe syntax](#markdown-safe-syntax-avoid-bare--and--outside-backticks) table.

## Image & Figure Workflow

Reports live alongside their images for preview compatibility. Follow this workflow:

1. **Extract images from notebooks**: If the report references an executed notebook, extract key `image/png` outputs into the same directory as the markdown file. Use descriptive names like `report_score_histogram_sample00.png`, `report_bev_threshold_sweep_sample00.png`.
2. **Use bare filenames in markdown**: Reference images as `![descriptive alt text](filename.png)` - bare filenames work best for both Cursor markdown preview and copy-paste to Google Docs.
3. **Add narrative around every figure**: Never drop an image without context. Before each image, explain:
   - What the plot shows (axes, what each element represents)
   - What "sample N" or other indices mean (e.g., "Sample 0 = one driving sequence containing 8-16 frames")
   - What the reader should look for (the key insight or takeaway)
   - Why the result looks the way it does (domain gap, calibration, expected vs. unexpected)
4. **Image alt text should be a mini-caption**: Not just `![plot]()` but `![Sample 0: Existence score histogram across all frames. Red lines = threshold candidates.]()`.
5. **For images you can't generate**, use blockquote placeholders:
   ```
   > **TODO: <description>** - <exact source location> (Confluence page section, W&B panel > Media tab > artifact name, notebook cell N output M).
   ```
6. **HTML fallback**: If the user needs images rendered inline and markdown preview isn't cooperating, generate a self-contained HTML file with Base64-embedded images in the same directory.
7. **Prune aggressively**: Not every notebook output belongs in the report. Select 1-2 representative samples per section, plus aggregate views. Move all extracted images to the output directory but only reference the most informative ones in the markdown.

## Table & Metrics Narrative

Every table and metric in the report should be understandable by a reader who has NOT run the experiment. Follow these rules:

1. **"How to read this table" block**: Before any metrics table, add a short block explaining what each column means in plain language. Don't assume the reader knows what TP, FP, ADE, KCM, DT/GT, IoU, etc. stand for. Example:
   ```
   **How to read this table:**
   - **TP (True Positives)**: Predictions that matched a GT box with BEV IoU >= 0.45.
   - **Precision**: TP / (TP + FP) - what fraction of predictions are correct.
   ```

2. **"Takeaway" after every table**: After the table, add a bolded **Takeaway:** sentence summarizing what the reader should conclude. Not just "precision is 7.61%" but "7.61% means ~1 in 13 predictions is accurate. The bottleneck is box geometry, not detection ability."

3. **Connect tables to each other**: If one table's numbers are misleading without context from another (e.g., low recall explained by the DT/GT ratio table), explicitly say so: "This headline is misleading - the next table shows why."

4. **Explain thresholds and parameters**: When a metric depends on a threshold (`IoU >= 0.45`, `existence score >= 0.3`), state what the threshold is, what it means, and how it affects the number. Readers should understand that changing the threshold changes the results.

5. **Quantify in human terms**: Convert abstract numbers to intuition. "28.4m ADE at 9s" → "≈ 18 mph speed mismatch." "0.85 rad heading error" → "≈ 49 degrees, inflated by the 28% heading flip."

6. **State what "good" looks like**: When reporting a metric, give the reader a reference point. "Sub-1m centroid error is good for a fine-tuned model; 0.84m here is surprisingly accurate for zero-shot."

## Style

- Prefer tables for metric comparisons; keep narrative concise but not telegraphic - explain what the numbers mean, not just what they are.
- State what was run (branch, config name, job IDs) so the report is auditable.
- Call out data caveats (sample size, filters, known pipeline limits).
- Distinguish clearly between **what exists today** and **what we propose to build**.
- Prefer "recommended priority", "proposed filter", or "current production behavior" over ambiguous labels.
- For image placeholders, be specific: name the notebook cell, W&B panel tab, or script that produces the figure so the user can find it quickly.
- Draft files go in the notebook's `output/` directory (e.g., `cruise/.../notebooks/output/<report>.md`) so images and markdown are co-located. Only use `~/.cursor/reports/` for drafts that don't have associated images.

### Punctuation: no em-dashes; use colons

- Do **not** use em-dashes (`—`, U+2014) in prose. They render inconsistently across GitHub, Google Docs, Confluence, and Slack, and add visual noise in dense technical writing.
- Do **not** use `-` or `--` as em-dash substitutes in prose either. Pick the correct structural punctuation instead:
  - **Colon (`:`)** introduces an elaboration, list, or explanation. Example: `B2 wins: mid/far AP gains, best longitudinal, no closed-loop regression.`
  - **Semicolon (`;`)** joins two closely related independent clauses. Example: `Not remediated this cycle; see Root cause section.`
  - **Period (`.`)** when the split improves scanability. Example: `... 96.6% vs 94.9%. This is the same cell where AP drops.`
  - **Parentheses (`(...)`)** for parenthetical qualifiers.
- Exceptions (structural, not prose):
  - Table cells: single `-` (or empty) for "not applicable" cells.
  - Markdown table header separators (`| --- |`) and section rules (`---`) are unaffected.
- Rationale: colons, semicolons, and periods are stable across surfaces and signal structure explicitly. Em-dash-like pauses often mask run-on sentences that should be split.
- Cleanup one-liner for an existing draft. Read through after, mechanical replacement will produce some awkward sentences that need rewriting (split into two, rephrase, drop filler):
  ```python
  import re, pathlib
  p = pathlib.Path("report.md")
  txt = p.read_text()
  txt = re.sub(r'\s*—\s*', ': ', txt)       # em-dash -> colon
  txt = re.sub(r'(?<=\w) -- (?=\w)', ': ', txt)  # " -- " prose pause -> colon
  txt = re.sub(r'  +', ' ', txt)             # collapse double spaces
  p.write_text(txt)
  ```

### Markdown-safe syntax: avoid bare `<` and `>` outside backticks

Cursor's markdown preview crashes with "Assertion Failed: Argument is 'undefined' or 'null'" when the tokenizer sees a bare less-than or greater-than character in prose or table cells and misinterprets it as malformed HTML. Unicode characters do NOT cause crashes. This is a frequent failure mode when writing numeric comparisons (`length < 7m`), HTML line-break tags in table cells, or pasted Slack / HTML fragments. Internalize the rules below so a draft never hits the crash in the first place.

**Forbidden patterns** (use alternatives even on first draft; all raw pattern cells below are shown inside backticks to keep this skill renderable):

| Never write (shown quoted as code) | Write instead | Why |
|---|---|---|
| `L2 < 3m` in prose or a table cell | `L2 within 3m`, or wrap the whole token in a backtick code span | Bare less-than + space + digit is parsed as a malformed HTML tag. |
| `cap > 128` in prose | `cap above 128`, or wrap in a backtick code span | Same as above. |
| `IoU >= 0.45` | `IoU at least 0.45`, or wrap in a backtick code span | The `>=` is still a bare greater-than. |
| `br` HTML tag inside a table cell | Either (a) **repeat the row label** in the next row, or (b) use a blank cell. Do **not** use ` -- ` as the "merged cell" filler (reads as a prose pause; conflicts with the em-dash rule). | Tokenizer flags it as HTML. |
| HTML comments | Delete the comment. | HTML comment. |
| Slack link paste `angle-URL-pipe-label-angle` | `[label](https://url)` | Slack link syntax. |
| Slack mention paste (`angle-@U012ABC-angle`) | The person's name. | Slack mention. |
| `details`, `a`, or any other raw HTML tag | Plain markdown equivalent, or wrap the tag name in a backtick code span if you need to document it literally. | Arbitrary HTML. |

**Safe patterns** (no rewrite needed):

- Less-than / greater-than characters **inside a backtick code span** (for example, a backticked token like `bin_x times |y| < 10m`) or a fenced code block. Inside backticks the tokenizer does not try to parse HTML.
- Blockquote markers at the start of a line (`> note ...`).
- Text arrows in prose (`->`, `-->`, `<-`). These are not parsed as HTML.
- Unicode symbols (`→`, `↔`, `–`). Em-dashes are still disallowed by the [punctuation rule](#punctuation-no-em-dashes-use-colons).

**Rule of thumb.** If you want to write a numeric inequality or any token containing less-than / greater-than, either (a) **reword** to `under` / `above` / `within` / `at least` / `at most`, or (b) **wrap it in a backtick code span** so the preview treats it as code. Backslash escapes, HTML entities, and prose-level tricks in some table contexts have been unreliable. Reword or wrap; do not escape.

**Authoring workflow.** After every substantive write / edit pass on a markdown file, scan it. This is cheap (under 1s for a 1k-line file) and catches crashes before they happen:

```bash
python3 ~/.cursor/skills/fix-markdown-crash/scripts/scan_md.py REPORT_PATH
# or, for a whole directory:
python3 ~/.cursor/skills/fix-markdown-crash/scripts/scan_md.py DIRECTORY/
```

Expected output: `All clean: N file(s) scanned, no crash patterns found.` If the scanner reports issues, reword per the table above. **Do not** rely on the `--fix` flag alone: its replacements are aggressive and edit inside backticks too, which degrades readability in places that were already safe.

If the scanner reports zero issues but the file still crashes, this is a Cursor client-side path cache corruption (rare, triggered by many rapid edits). The only reliable fix from SSH is to rename the file (`mv report.md report_v2.md`). See the `fix-markdown-crash` skill for details.

### Body -> Appendix cross-references (unidirectional)

When content is moved into an appendix to keep the main body readable, link **only from the body to the appendix**. Do not add back-links from the appendix to the body.

1. **Body -> appendix**: Every time the body says "details / tables / run links are in the appendix," make "appendix" (or the specific item) an anchor link, e.g. `details are in the [appendix](#detection-methodology)`.
2. **No appendix -> body back-links**: Do NOT add lines like `*Referenced from [X](#x).*` under appendix subheadings. The appendix is reference material; readers scan it or arrive via a body link. Back-links add visual noise and get stale.
3. GitHub-flavored anchor rules: lowercase the heading, strip punctuation that isn't `\w`, space, or `-`, then replace each space with `-`. Adjacent spaces produce adjacent dashes (e.g. `Recall / Precision / F1` becomes `recall` + two-dash + `precision` + two-dash + `f1` since the two spaces around each `/` collapse into two dashes after stripping).
4. After editing, validate every `](#anchor)` resolves to a real heading. A small script is enough:
   ```python
   import re
   txt = open("report.md").read()
   def slug(h):
       s = re.sub(r'[^\w\s-]', '', h.lower().strip())
       return s.replace(' ', '-')
   anchors = {slug(h) for _, h in re.findall(r'^(#+)\s+(.+)$', txt, re.M)}
   missing = [u for u in set(re.findall(r'\]\(#([^)]+)\)', txt)) if u not in anchors]
   assert not missing, missing
   ```

### Link anchor text: semantic, not citation-number

Anchor text inside `[anchor](url)` must be self-describing. A reader should know what a link points to without hovering or clicking.

1. **Use the concrete name (file, symbol, document, section)**:
   - Good: `[seq3d_obstacles_v2.yaml](https://.../seq3d_obstacles_v2.yaml)`, `[geometry_3d_utils.py](...#L355-L370)`, `[SC3 Unified Taxonomy](...)`.
   - Bad: `[CODE5](...)`, `[CODE3](...)`, `[link](...)`, `[here](...)`. Opaque numeric / placeholder anchors force the reader to hover or click to learn what the link is.
2. **Do not invent a citation-number scheme** (`[CODE1]`, `[REF2]`, `[1]`) unless the report actually has a numbered reference list at the end that the number resolves against. A stray `[CODEx]` without a corresponding list is worse than no citation at all.
3. **Function / line-range links**: prefer the filename plus the line range in the URL; keep the anchor text as the filename (optionally with symbol), e.g. `[geometry_3d_utils.py](.../geometry_3d_utils.py#L355-L370)` or `[geometry_3d_utils.euclidean_distance](.../geometry_3d_utils.py#L355-L370)`. Do not use `[L355-L370](...)`: the line range alone has no semantic content.
4. **Internal anchors follow the same rule**: `[Detection Methodology](#detection-methodology)` and `[Key Findings #1](#key-findings)` are self-describing; `[see above](#x)` and `[section 3.2](#x)` are not.
5. **Audit pass**: before finalizing, grep the report for common opaque patterns and rename them.

   ```bash
   rg -n '\[(CODE|REF|LINK|here|see|above|below|this)\d*\]\(' report.md
   ```

   Each hit should be replaced with a concrete name.

### Concision & implementation-detail discipline

Audit the body for verbosity and for implementation detail that belongs in the appendix:

1. **Duplicated definitions**: If a term is defined in a glossary at the top of a section AND restated inline before a table, keep only the glossary version and remove the inline restatement.
2. **Implementation detail (BQ table names, specific function names, SQL-like joins)**: Move to the appendix methodology block. The body should say what the metric measures, not how it's computed.
3. **Explanatory qualifiers** ("This is expected because...", "The reason is...") that restate an already-stated fact: compress to a single terse sentence or drop entirely.
4. **Preambles that describe the section's purpose to the reader**: keep to 1-2 sentences max.
5. **Audit pass**: before finalizing, read each paragraph and ask "if I delete this sentence, does the reader lose a fact or only lose framing?" If framing-only, delete.

### Relative-% audits and rounding

When auditing relative-% changes in a results table, expect and tolerate small discrepancies between the displayed values and what the reader can compute by hand. Underlying data is often 4-6 decimal places; the table displays 2-3. The relative-% is computed from raw data, not from the rounded display values.

**Rules for the audit:**

1. **Do not "correct" a relative-% that is within 0.5 (absolute) of what the displayed base and final values imply** (e.g., a claimed `+2.5%` when the naive recompute from displayed values gives `+2.2%` is not a bug; the 0.3 gap is display-rounding). This is almost always display-rounding, not a calculation error.
2. **Do flag a relative-% as a real bug if the gap exceeds 0.5, OR if the displayed absolute delta itself cannot be reconciled with the displayed base/final cells** (e.g., displayed B0=0.218, B2=0.219 but table claims abs delta = +0.002: this cannot happen by rounding. The abs delta must be at most 0.0014 + 0.0005 margin ≈ 0.002 only if raw B2 ≥ 0.2195, which would round up to 0.220, contradiction).
3. **Document display precision explicitly** when numbers come from higher-precision raw sources. Add a one-liner under the table: "*Raw values at 4 decimals; displayed at 3. Relative % is from raw.*"
4. **Always relative %, never percentage points (`pp`)**: all reported deltas on percentage-valued metrics (recall, F1, pass rate, AP when displayed as %) must be **relative %**: `(feature - base) / base × 100`. Always cite both absolute values in parentheses so the reader can sanity-check and so it is unambiguous that `+1.8%` means relative, not absolute. Round to 1 decimal.
   - Correct: `recall +1.4% (52.4% vs 51.7%)`, `pass rate 0% (93.2% vs 93.2%)`.
   - Forbidden: `+0.7pp`, `+1.7 percentage points`, bare `+0.7%` without the paired absolute values.
   - Special case: if feature = base exactly, write `0%` or `no change`, never `0 pp`.
   - Do not confuse `pp.` (PDF page citation, always written with a trailing period: `pp. 5, 28`) with the forbidden `pp` suffix; the period and context are what distinguish them. `pp.` is always acceptable; `pp` as a delta unit is not.

**Validation snippet** to run when auditing a % table:

```python
import re
with open("report.md") as f:
    txt = f.read()
# Find all "A to B ... N%" or "A -> B ... N%" patterns and check
for m in re.finditer(r'(\d+\.\d+) (?:to|->) (\d+\.\d+).*?(\+?\-?\d+\.\d+)%', txt):
    a, b, claimed = map(float, m.groups())
    actual = (b - a) / a * 100
    if abs(claimed - actual) > 0.5:
        print(f"MISMATCH: {a} -> {b} claimed {claimed}% but naive={actual:.2f}%")
```

## Example: NVIDIA training results section

When reporting Olympus / NVIDIA experiments, a minimal results skeleton (adapt columns to the actual metrics) is:

```markdown
## NVIDIA Training Results: <Phase> - <Variant>

**Run**: [Centra](<url>) | [W&B](<url>)
**Config**: `<config_name>` | **Checkpoint source**: <source>
**Dataset**: NVIDIA MAP_AND_INTENT (<N> samples)

### Tracking / Detection
| Metric | Zero-shot | Backbone-frozen | Backbone-unfrozen |
|--------|-----------|-----------------|-------------------|
| 3D AP [0-25m] | ... | ... | ... |

### Trajectory
| Metric | Zero-shot | Backbone-frozen | Backbone-unfrozen |
|--------|-----------|-----------------|-------------------|
| ADE 3s | ... | ... | ... |

### Observations
- ...

### Next Steps
- ...
```

## Confluence Size Limits & Slicing

The Atlassian MCP `updateConfluencePage` tool has a practical payload limit (~46KB). For reports with many images (which Confluence stores as ADF media nodes with large `localId` UUIDs), a single page update can exceed this limit.

**Strategy for large Confluence reports:**
- **Parent page**: Keep the parent page as a lightweight index with links, summary tables, and navigation. No inline images.
- **Child pages**: Break image-heavy sections into child pages (e.g., "Detection Results", "Trajectory Results", "Calibration Fix"). Each child page stays under the size limit.
- **Use `contentFormat: markdown`** when creating/updating via MCP - markdown payloads are ~10x smaller than ADF and Confluence converts them automatically.
- **Never overwrite a page that has manually-uploaded images** - the ADF for those images is huge and fragile. Instead, add new content as a child page or coordinate with the user to restore + manually merge.

## Related skills

| Skill | Use when |
|-------|----------|
| `google-doc-publish` | Publishing markdown with images to Google Docs (automated tables, images, formatting) |
| `confluence-publish` | Creating/updating Confluence pages via MCP |
| `fix-markdown-crash` | Diagnosing / fixing Cursor markdown-preview crashes from bare `<` / `>`. Run `scan_md.py <path>` after each substantive edit pass; see the [Markdown-safe syntax](#markdown-safe-syntax-avoid-bare--and--outside-backticks) section for the rules codified into the authoring workflow. |
| `nvidia-training-eval` | End-to-end NVIDIA Olympus training workflow |
| `run-notebook-to-html` | Generating HTML from eval notebooks under Bazel |
| `trino-lakehouse` | Ad-hoc lakehouse SQL via Trino CLI |
| `analyze-olympus-runs` / `analyze-wandb` | Pulling run metadata and W&B metrics |
