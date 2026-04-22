---
name: google-doc-publish
description: >-
  Publish a markdown file as a beautifully formatted Google Doc with inline images,
  proper tables, and professional styling. Use when the user asks to publish, upload,
  or convert a markdown file to Google Docs, or says "publish to gdoc", "create google doc",
  or "upload report".
---

# Google Doc Publish

Converts a local markdown file to a well-formatted Google Doc via HTML upload with
base64-embedded images (no public URLs needed), then applies post-upload formatting
via the Docs API.

## Prerequisites

- ADC credentials with Drive + Docs scopes (check: `gcloud auth application-default print-access-token | head -c4` should print `ya29`):
  ```
  gcloud auth application-default login \
    --scopes="openid,https://www.googleapis.com/auth/userinfo.email,https://www.googleapis.com/auth/cloud-platform,https://www.googleapis.com/auth/documents,https://www.googleapis.com/auth/drive,https://www.googleapis.com/auth/spreadsheets"
  ```
- Python packages: `google-auth`, `google-auth-httplib2`, `google-api-python-client`
  (install: `/usr/bin/python3 -m pip install --user google-auth google-auth-httplib2 google-api-python-client`)

If ADC is expired or missing Drive/Docs scopes (`ResumableUploadError: 403 insufficient scopes`),
run the automated auth refresh:
```bash
~/.cursor/scripts/cruise-auth-refresh.exp gcloud-adc
# Then in parallel:
cd ~/.cursor/scripts && XVFB=1 xvfb-run --auto-servernum --server-args="-screen 0 1280x1024x24" node cruise-auth-browser.mjs
```
This automates the full SSO flow. Only requires user interaction for Microsoft MFA.
See `cruise-auth-refresh` skill for details.

## Usage

```python
from md_to_gdoc import publish

publish(
    md_path="path/to/report.md",
    title="My Report Title",
    author="Name",
    author_email="user@getcruise.com",
    date="2026-03-27",
    branch="branch-name",
    status="Draft",
    share_domains=["getcruise.com"],
    delete_old_id="optional_old_doc_id",     # one-shot report: create new; delete old
    update_doc_id="optional_existing_doc_id", # living doc: update in place; preserves URL
    style_inline_code=False,                 # (opt-in) post-style <code> as Roboto Mono + gray bg
)
```

Script location: `~/.cursor/skills/google-doc-publish/scripts/md_to_gdoc.py`

### Default pattern: update in place (living docs)

**Any doc that will be updated more than once should be updated in place.** Trackers, status
pages, weekly reports, rolling summaries — all fall in this bucket. A stable URL is the
whole point: people bookmark it, link it in Slack, paste it in Jira. Creating a new doc on
every edit breaks every one of those references.

When the user asks to "update", "add to", "refresh", "modify" an existing Google Doc, use
`update_doc_id`. This calls `drive.files().update()` which replaces the content while
preserving the `documentId` (= same URL).

- `update_doc_id`: **default for any doc that already exists**. Keeps the URL.
- `delete_old_id`: only for one-shot reports that were mis-published and the old draft
  should be nuked. URL changes.
- If both are set, `update_doc_id` wins and `delete_old_id` is ignored.

### Tracking doc IDs across sessions

For living docs, save the `doc_id` as a sidecar `.gdoc.json` next to the markdown file on
first publish, then read it back on every subsequent publish. This means the agent can
update the doc in place in a new session without the user re-supplying the ID.

```python
import json, os
from md_to_gdoc import publish

md_path = "path/to/tracker.md"
sidecar = md_path + ".gdoc.json"

update_id = None
if os.path.exists(sidecar):
    with open(sidecar) as f:
        update_id = json.load(f).get("doc_id")

doc_id, url = publish(
    md_path=md_path,
    title="My Living Tracker",
    # ...,
    update_doc_id=update_id,
)

with open(sidecar, "w") as f:
    json.dump({"doc_id": doc_id, "url": url}, f)
```

If the sidecar is missing / deleted and the user mentions they already have a published
doc, ask them for the URL or grep the chat transcript for a `docs.google.com/document/d/<ID>`
link before creating a new one. **Do not create a fresh doc when one already exists.**

## Formatting Rules

### Bold - Strict Scoping

- Use `<span style="font-weight:bold">` instead of `<b>` tags
- When ANY bold span exists in a paragraph, wrap the ENTIRE paragraph in
  `<span style="font-weight:normal">...` to prevent Google's converter from
  bleeding bold to the whole paragraph
- Only bold where the source markdown explicitly has `**...**`
- Table data cells: explicit `style="font-weight:normal"`

### Spacing

- Line spacing: 1.15x (via Docs API `lineSpacing: 115`)
- Paragraph spacing: zero (`spaceAbove=0, spaceBelow=0`)
- Single empty `<p><br></p>` between paragraphs (NOT `&nbsp;` which leaves a visible space)
- Use `last_was_br` flag to prevent consecutive empty lines
- Post-upload cleanup pass to remove any remaining double empty rows
- Empty line before/after: tables, images
- Empty line before AND after headings (blank row between heading and content)
- NO empty line before bullet/numbered lists (peek ahead to suppress BR)
- Zero spacing in table cells too (apply to paragraphs inside `tableRows > tableCells`)

### Headings - H1 through H6

- Use `<h1>`-`<h6>` HTML tags (converts to proper Google Doc heading styles).
- Google Docs has exactly 6 named heading styles (HEADING_1..HEADING_6); do NOT
  try to support `#######` (H7+) — they would render as plain paragraphs.
- The script's heading regex in `_collect_headings` and in the main loop MUST accept
  `#{1,6}` (not `#{1,4}`). Capping at H4 silently drops H5/H6 and leaves literal
  `#####` in the rendered doc. Also applies to the paragraph-continuation guard
  regex that prevents paragraphs from swallowing the next heading.
- Add `id="slug"` and `<a name="slug"></a>` to each heading tag for internal linking.
  This triggers Google's converter to assign `headingId` values.
- H3/H4/H5/H6: color `#434343`
- Do NOT use `<p>` with font-size (won't create real heading styles).

### Tables

- Header: `background:#1a3764; color:#fff; font-weight:bold; font-size:11pt`
- Data cells: `font-weight:normal; font-size:11pt` (same as body text)
- Table width: `width: 100%` in HTML. Post-upload, tables are sized to text area + 72pt
  (wider than body text) to use the extra horizontal space in pageless mode.
- Column widths: auto-computed proportional to max content length per column (capped at
  80 chars, floored at 30 chars). Applied via both HTML `<colgroup>` and Docs API
  `updateTableColumnProperties` with `FIXED_WIDTH`. Minimum 20% per column.
- Summary rows (Agg/Overall/Total): bold with `background:#e8f0fe`
- Alternating even rows: `background:#f8f9fa`
- Borders: `1px solid #dadce0` (data), `1px solid #3d73c4` (header)

### Images and Captions

Two supported markdown syntaxes:

```markdown
![long accessibility alt text](image.png)
![long accessibility alt text](image.png "Short caption shown below image.")
```

- **Preferred: `![alt](src "caption")`**. The `"caption"` (title attribute) becomes the
  visible caption under the image. Alt text is kept verbatim on the `<img>` tag for
  accessibility. Keep captions to **1 sentence, 1-2 lines max**; any longer repeats
  information that belongs in body prose.
- **Fallback: `![alt](src)`**. When no title is provided, the script truncates `alt`
  at the first sentence boundary (`.`, `!`, `?`) and uses that as the caption. The full
  alt is still preserved on `<img>`. This lets legacy markdown with verbose alts
  automatically produce a compact caption without a source edit.
- Base64-embedded: `data:image/png;base64,...` in `<img>` tags; width 620px; centered.
- Caption style: centered, italic, 9pt, color `#80868b`.
- Image paths are resolved relative to the markdown file's directory.

Images inside markdown table cells use inline-image syntax (`![...](...)` inside a
`|` row) and render as small thumbnails (180px). Alt text is kept on the `<img>`, but
no caption is rendered because the caption model only applies to top-level block images.

### Title Processing

- The first `# Heading` becomes the document title (`<h1>`).
- Only blank lines and `---` separators after the H1 are consumed. Any content
  paragraph (e.g., a "Goal:" line) is preserved and emitted after the metadata/TOC block.
- Order in the output: Title → Metadata → Related Documents → TOC → Body content.

### Metadata Block

Separate lines below title, all in default body color:
```
Author: name
Last Updated: date
Branch: branch
Status: Draft
```
Labels and values are all normal weight. Default body text color (#202124).
Author name is a real @mention chip via `insertPerson` API (not a mailto link).
Date chips are not supported by the API; use plain text.

**Always generated from `publish()` kwargs**, never from markdown source. The
title-processing loop consumes any legacy `**Author:**` / `**Last Updated:**` /
`**Date:**` / `**Branch:**` / `**Status:**` lines the author may have written
into the md file (with or without the `**...**` bold wrapper), so those never
get rendered a second time as plain paragraphs further down the body. Put
these values in `publish(author=..., date=..., branch=..., status=...)` and
leave them out of the md.

**Email gotcha**: `insertPerson` rejects emails that contain non-ASCII characters
with `HttpError 400: The email is invalid.` If a hard-coded or copy-pasted email
fails this check, reconstruct the string from known-safe parts (`"user" + "@" +
"getcruise.com"`) or validate with `email.encode("ascii")` before the API call.
Zero-width Unicode chars in copied strings are the usual culprit.

### Related Documents (auto-hoisted)

- If the markdown body contains a `**Related documents:**` (or `**Related Documents:**`)
  section, it is automatically extracted from the body and placed between the metadata
  block and the Table of Contents.
- The section includes the bold label line and all continuation lines until the next
  empty line or another bold/heading section.
- Links in the related docs are rendered as clickable hyperlinks.

### Table of Contents

- Auto-generated from all H2-H6 headings.
- Placed immediately after the metadata block.
- Bold "Table of Contents" label followed by one entry per heading.
- Level indent: 14px × (level − 2). H2 flush left, H3 +14px, H4 +28px, etc.
- Each entry is an internal anchor link (`<a href="#slug">`) that is wired to a
  bookmark post-upload.
- **Page numbers**: Not supported. The Docs API has no `insertTableOfContents`
  request, and pageless mode (our default) has no page concept. For paged mode
  with page numbers, manually insert a native TOC via the UI after upload.

### Text

- Replace `" -- "` with `" - "` throughout.
- Skip markdown `---` HR delimiters (sections separated by headings only).
- Internal links (`#section-slug`): `<a href="#slug">` in HTML + heading `id`/`name`
  attrs → Google maps these to `headingId` links. Post-upload, the script also creates
  explicit bookmarks at target headings and rewrites the anchors to `bookmarkId` links
  for stability.
- Local file links (`.py`, `.html`, `.ipynb`, relative paths): strip link, keep display text.
- Font: Arial 11pt, color #202124.

### Inline Code (monospace restyling — opt-in)

Markdown backtick spans (`` `code` ``) are rendered in two steps:

1. **HTML phase**: wrapped in `<code>` tags. Google Docs HTML import preserves the
   text but **strips font styling from `<code>`** — imported runs use the default
   body font. The gray background from CSS is also dropped.
2. **Post-upload phase (`style_inline_code=True`, OPT-IN, default off)**: after the
   doc exists, the script walks every paragraph, locates each unique inline-code
   literal by substring match, and applies `weightedFontFamily: "Roboto Mono"` +
   a light gray `backgroundColor` (`#F1F3F4`) to those ranges.

**Why off by default**: substring matching over-applies the style in practice.
Code literals like `[0, 25)`, `Car`, `A110`, `CAR` appear hundreds of times in
report prose, not all of them meant as `<code>`. Styling all occurrences makes
the doc look speckled and inconsistent with surrounding Arial body text. Turn
on only when the report is dominated by identifiers (configs, file paths,
API names) where monospace genuinely aids readability.

Pitfall #1 — **link-regex greedy match across code spans**. The link regex
`\[([^\]]+)\]\(([^)]+)\)` would otherwise greedy-match across a snippet like
`` `[25, 50)` … [Heading](#anchor) `` and swallow the code literal into the link
text. The `inline()` function therefore masks inline-code spans with
`\x00CODE{n}\x00` sentinels **before** running the link regex, then restores them
after. Do not reorder these steps.

Pitfall #2 — **sentinel leakage into markdown source**. If you ever cat an HTML
render and paste it back into a markdown file, the raw `\x00CODE{n}\x00` bytes
become U+FFFD replacement characters in the md and get re-imported as literal
`CODE0` / `CODE1` text in the next publish. The `inline()` function contains a
belt-and-suspenders scrub that replaces any stray `\x00CODE{n}\x00?` with the
corresponding code literal and strips lone `\x00` bytes, but the real fix is to
**never paste HTML output back into markdown**.

### Post-Upload (Docs API)

Applied via `batchUpdate` after HTML upload, in this order:

1. `lineSpacing: 115` on all paragraphs (body AND table cells).
2. `spaceAbove: 0, spaceBelow: 0` on all paragraphs.
3. `updateTableColumnProperties` with `FIXED_WIDTH` per column, proportional to content.
4. `documentFormat.documentMode: PAGELESS`.
5. Cleanup pass: delete consecutive empty rows (up to 3 iterations).
6. Internal-link wiring: create bookmarks at target headings, then apply
   `textStyle.link.bookmarkId` to each anchor-link text range.
7. Inline-code monospace restyle (if `style_inline_code=True`).
8. Author @mention chip: `deleteContentRange` over plain-text name, then `insertPerson`.
9. Domain share: `drive.permissions().create(type="domain", role="writer")`.

### Quota pacing

`batchUpdate` has a per-minute write-request quota. Complex docs can hit
`HttpError 429: Quota exceeded` during steps 6-8, especially the bookmark
creation loop (one call per heading). The script:

- Batches style/spacing requests in chunks of 100.
- Falls back to `time.sleep(65)` + one retry on 429 in the monospace loop.
- If you still hit 429 anywhere, re-run the script with `update_doc_id=<id>`;
  idempotent post-upload steps (bookmarks, styling) will re-apply cleanly to
  the existing doc.

### Sharing

- `drive.permissions().create(type="domain", role="writer", domain="getcruise.com")`.
- Share within Cruise only (not external / gm.com).

## Authoring Conventions (what to write in the markdown)

- **Captions: one sentence.** Put analysis / figure interpretation in the body
  paragraph around the figure, not in the caption. Use the `![alt](src "caption")`
  title form whenever you want explicit control over the caption.
- **Alt text is for a11y.** It can be long (it's not rendered visibly) but should
  describe the figure content, not interpret it.
- **Inline code for identifiers only.** Config names, file paths, math snippets
  — things where monospace conveys meaning. Don't backtick prose.
- **Internal links resolve by slug.** Headings like `## Root cause: labeling-spec
  divergence` become `#root-cause-labeling-spec-divergence`. Match the exact
  lower-cased, hyphenated slug; any mismatch is silently dropped by the
  bookmark-wiring step.
- **H1 is reserved.** Only use `#` for the document title (first line). Use `##`
  as the top body section.

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Bold bleeds to entire paragraph | Wrap in `<span style="font-weight:normal">` |
| Images missing | Re-auth ADC with Drive+Docs scopes |
| `insertInlineImage` fails | Use HTML upload with base64 instead |
| Headings not in outline | Use `<h1>`-`<h6>` tags, not `<p>` with font-size |
| H5/H6 rendered as literal `#####` text | Heading regex capped; must be `#{1,6}` |
| Double empty rows | `last_was_br` flag + post-upload cleanup pass |
| Table cells bold | Add `style="font-weight:normal"` to `<td>` |
| Table cell padding | Zero `spaceAbove/Below` on paragraphs inside table cells |
| Empty rows show space | Use `<p><br></p>` not `<p>&nbsp;</p>` |
| Pageless not set | Use `documentFormat.documentMode: PAGELESS` via API |
| Org blocks public sharing | Use `type=domain` with `getcruise.com` |
| Internal link renders as plain text | `inline()` must mask inline-code before link regex |
| Literal `CODE0` / U+FFFD in rendered doc | Sentinel leaked into md source; see pitfall #2 |
| `insertPerson: The email is invalid` | Non-ASCII chars in email; rebuild from ASCII parts |
| Inline code shows in default font | Set `style_inline_code=True` (opt-in; over-applies — see Inline Code section) |
| Metadata block (Author/Date/…) duplicated in body | Legacy `**Author:**` lines in md are now consumed by the title loop; remove them from md source for older scripts |
| `HttpError 429: Quota exceeded` | Sleep 65s + retry; or re-run with `update_doc_id` |
| Caption too verbose | Use `![alt](src "short caption")` form; script truncates at first `.` otherwise |

## Post-Publish Audit (recommended)

After publishing, especially for one-shot reports, verify the live doc against the
markdown source. Common checks:

1. Count internal links in md (`\[[^\]]+\]\(#`) vs anchor links in doc — every
   one should resolve to a `headingId` or `bookmarkId`.
2. Count external links in md (`\]\(https?://`) vs URL links in doc — should match.
3. Scan doc text for literal `**`, `[`, `#` prefixes at line start, `CODE{n}`, or
   U+FFFD — there should be none.
4. Count images in md vs `inlineObjects` in doc — should match.
5. Count tables in md (`^|`) vs `table` elements — should match.
6. Count headings in md (`^#{1,6} `) vs paragraphs with `HEADING_*` style — should match.
7. Verify author chip exists (walk first ~15 paragraphs, look for a `person` element).
8. Verify sharing permissions via `drive.permissions().list`.

A sample audit script is the right tool when the doc is user-facing and long.
