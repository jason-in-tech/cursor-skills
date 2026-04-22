#!/usr/bin/env python3
"""Markdown -> Google Doc (final) - precise formatting, single empty row spacing."""

import re, os, base64, sys
import google.auth
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload

SCOPES = ["https://www.googleapis.com/auth/documents", "https://www.googleapis.com/auth/drive"]
IMG_WIDTH_PX = 620
N = '<span style="font-weight:normal">'
NC = '</span>'


def get_services():
    creds, _ = google.auth.default(scopes=SCOPES)
    creds.refresh(Request())
    return build("drive", "v3", credentials=creds), build("docs", "v1", credentials=creds), creds


_internal_links = []  # collected during HTML generation for post-upload linking
_table_col_pcts = []  # per-table list of column width percentages
_inline_img_dir = [None]  # one-element list so inline() can see the active image dir
_code_spans = []  # unique inline-code literals; post-upload restyles to Roboto Mono
INLINE_IMG_THUMB_PX = 180  # width used for images embedded inside inline contexts (table cells, etc.)
CODE_FONT_FAMILY = "Roboto Mono"
CODE_BG_COLOR = {"color": {"rgbColor": {"red": 0.945, "green": 0.953, "blue": 0.957}}}  # #F1F3F4

def _link_handler(m):
    """Handle markdown links: keep external, strip local files, preserve internal anchors.

    Inline style forces Google Docs HTML importer to use standard Docs hyperlink
    blue (#1155CC) instead of the default browser blue (#0000EE). The latter is
    how Docs renders bare <a> tags; to match hand-authored links the color must
    be explicit.
    """
    text, url = m.group(1), m.group(2)
    link_style = 'color:#1155CC;text-decoration:underline'
    if url.startswith("#"):
        _internal_links.append({"text": text, "anchor": url[1:]})
        return f'<a href="{url}" style="{link_style}">{text}</a>'
    if url.startswith("http"):
        return f'<a href="{url}" style="{link_style}">{text}</a>'
    return text


def _inline_img_handler(m):
    """Handle markdown images inside inline text (e.g. table cells). Returns <img> with base64 src.

    When the image file is missing or no img_dir is active, falls back to the alt text.
    The title attribute (group 3), if present, is used only for the `title=`
    HTML attr — inline images in table cells don't render a caption.
    """
    alt, fn = m.group(1), m.group(2)
    title = m.group(3) if m.lastindex and m.lastindex >= 3 else None
    img_dir = _inline_img_dir[0]
    if img_dir and not fn.startswith("http"):
        uri = img_b64(img_dir, fn)
        if uri:
            title_attr = f' title="{title}"' if title else ""
            return (
                f'<img src="{uri}" width="{INLINE_IMG_THUMB_PX}" '
                f'alt="{alt}"{title_attr}>'
            )
    return alt


def inline(text):
    """Markdown inline -> HTML with strict bold scoping.

    Order matters. Inline-code is masked FIRST so the link regex cannot
    greedy-match across a `\`[0, 25)\`` snippet into a later
    `[text](#anchor)` and swallow everything in between.
    """
    # 1. Images (handle before link regex so `![alt](fn)` is not matched as link).
    #    Title string may contain `)` (e.g. `"[0, 25)"`); close on `"` first.
    text = re.sub(
        r'!\[([^\]]*)\]\(\s*([^)\s]+?)\s*(?:"([^"]*)"\s*)?\)',
        _inline_img_handler,
        text,
    )

    # 2. Mask inline code so its `[` / `]` / `(` / `)` cannot confuse link regex.
    # Also record each literal for post-upload monospace restyling (unique set).
    code_tokens = []
    def _mask_code(m):
        literal = m.group(1)
        code_tokens.append(literal)
        if literal not in _code_spans:
            _code_spans.append(literal)
        return f'\x00CODE{len(code_tokens) - 1}\x00'
    text = re.sub(r'`([^`]+)`', _mask_code, text)

    # 3. Bold-link and link (safe now that code spans are out of the way).
    text = re.sub(r'\*\*\[([^\]]+)\]\(([^)]+)\)\*\*',
                  lambda m: f'<span style="font-weight:bold">{_link_handler(m)}</span>', text)
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', _link_handler, text)

    # 4. Bold and italics.
    text = re.sub(r'\*\*([^*]+)\*\*', r'<span style="font-weight:bold">\1</span>', text)
    text = re.sub(r'\*([^*]+)\*', r'<i>\1</i>', text)

    # 5. Restore code spans as <code>.
    def _unmask_code(m):
        return f'<code>{code_tokens[int(m.group(1))]}</code>'
    text = re.sub(r'\x00CODE(\d+)\x00', _unmask_code, text)

    # Belt-and-suspenders: if any sentinel slipped through (e.g. because an
    # upstream regex consumed one of the surrounding \x00), strip it so the
    # final doc never shows `\x00CODE0\x00` / the U+FFFD renderings of it.
    if '\x00CODE' in text or '\x00' in text:
        text = re.sub(r'\x00CODE(\d+)\x00?', lambda m: f'<code>{code_tokens[int(m.group(1))]}</code>' if int(m.group(1)) < len(code_tokens) else '', text)
        text = text.replace('\x00', '')

    if 'font-weight:bold' in text:
        text = f'{N}{text}{NC}'
    return text


def img_b64(img_dir, fn):
    fp = os.path.join(img_dir, fn)
    if not os.path.exists(fp):
        return None
    with open(fp, "rb") as f:
        return f"data:image/png;base64,{base64.b64encode(f.read()).decode()}"


def _derive_caption(title_cap, alt):
    """Choose the caption shown under an image.

    Rules:
    1. If the markdown image syntax provided `"caption"` (the title attribute),
       use it verbatim. Author has explicit control.
    2. Otherwise fall back to alt truncated at the first sentence boundary
       (`.`, `!`, `?`) so long accessibility alts don't become wall-of-text
       captions. Alt itself is preserved on the `<img>` tag for a11y.
    3. If neither is set, no caption is emitted.

    Keep the alt short if you want the fallback to be useful. Use the title
    form `![alt](src "caption")` for the cleanest author control.
    """
    if title_cap and title_cap.strip():
        return title_cap.strip()
    if not alt:
        return ""
    text = alt.strip()
    # First sentence boundary (., !, ?) followed by whitespace or end-of-string.
    m = re.search(r"[.!?](?:\s|$)", text)
    if m:
        return text[: m.end()].strip()
    return text


def _collect_headings(lines):
    """Pre-scan markdown lines for headings to build a TOC (H2-H6)."""
    headings = []
    for line in lines:
        m = re.match(r'^(#{2,6})\s+(.*)', line)
        if m:
            lvl = len(m.group(1))
            text = re.sub(r'\*\*([^*]+)\*\*', r'\1', m.group(2))
            text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
            text = re.sub(r'`([^`]+)`', r'\1', text)
            slug = re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')
            headings.append((lvl, text, slug))
    return headings


def md_to_html(md_text, img_dir, title=None, author=None, author_email=None, date=None, branch=None, status="Draft"):
    _internal_links.clear()
    _inline_img_dir[0] = img_dir
    lines = md_text.split("\n")
    lines = [l.replace(" -- ", " - ") for l in lines]

    toc_headings = _collect_headings(lines)

    related_docs_lines = []
    related_docs_indices = set()
    for idx, l in enumerate(lines):
        if re.match(r'^\*\*Related [Dd]ocuments?:?\*\*', l.strip()):
            related_docs_lines.append(l)
            related_docs_indices.add(idx)
            for k in range(idx + 1, len(lines)):
                if not lines[k].strip() or re.match(r'^(#{1,6}\s|\*\*)', lines[k]):
                    break
                related_docs_lines.append(lines[k])
                related_docs_indices.add(k)
            break

    h = []
    i = 0

    h.append("""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
body { font-family: Arial, sans-serif; font-size: 11pt; color: #202124; line-height: 1.15; }
h1 { font-size: 20pt; font-weight: 400; margin: 0; line-height: 1.15; }
h2 { font-size: 16pt; font-weight: 400; margin: 0; line-height: 1.15; }
h3 { font-size: 14pt; font-weight: 400; color: #434343; margin: 0; line-height: 1.15; }
h4 { font-size: 12pt; font-weight: 400; color: #434343; margin: 0; line-height: 1.15; }
p { margin: 0; line-height: 1.15; font-weight: normal; }
table { border-collapse: collapse; width: 100%; margin: 0; line-height: 1.15; }
th { background: #1a3764; color: #fff; font-weight: bold; font-size: 11pt; padding: 6px 10px; border: 1px solid #142d52; text-align: left; }
td { font-size: 11pt; padding: 4px 10px; border: 1px solid #dadce0; font-weight: normal; }
tr:nth-child(even) td { background: #f8f9fa; }
code { background: #f1f3f4; padding: 1px 4px; border-radius: 3px; font-family: 'Roboto Mono', monospace; font-size: 9.5pt; color: #37474f; }
blockquote { border-left: 3px solid #dadce0; margin: 0; padding: 4px 14px; color: #5f6368; }
ul, ol { margin: 0; padding-left: 28px; line-height: 1.15; }
li { margin: 0; font-weight: normal; }
img { max-width: 100%; height: auto; }
.caption { font-size: 9pt; color: #80868b; font-style: italic; margin: 0; text-align: center; }
.meta { font-size: 11pt; color: #5f6368; margin: 0; line-height: 1.15; }
.summary td { font-weight: bold; background: #e8f0fe !important; }
a { color: #1155CC; text-decoration: underline; }
</style></head><body>
""")

    BR = '<p><br></p>\n'
    last_was_br = False

    def emit_br():
        nonlocal last_was_br
        if not last_was_br:
            h.append(BR)
            last_was_br = True

    def emit(html):
        nonlocal last_was_br
        h.append(html)
        last_was_br = False

    while i < len(lines):
        if i in related_docs_indices:
            i += 1
            continue
        line = lines[i]
        if not line.strip():
            i += 1
            continue

        # ── Title (first H1) ──
        hm = re.match(r'^#\s+(.*)', line)
        if hm and i < 5:
            emit(f'<h1>{inline(hm.group(1))}</h1>\n')
            i += 1
            # Skip blank lines, --- separator, AND any legacy meta lines the
            # author wrote into the markdown. We always regenerate the metadata
            # block below from publish() kwargs, so consuming these prevents
            # them from being rendered a second time later as a normal paragraph.
            # Supported legacy forms (case-insensitive, bold optional):
            #     **Author:** Name            |  Author: Name
            #     **Last Updated:** 2026-...  |  Last Updated: 2026-...
            #     **Date:** 2026-...          |  Date: 2026-...
            #     **Branch:** foo/bar         |  Branch: foo/bar
            #     **Status:** Draft           |  Status: Draft
            meta_re = re.compile(
                r'^\s*(?:\*\*)?\s*(author|last updated|date|branch|status)\s*:?\s*(?:\*\*)?\s*.*$',
                re.IGNORECASE,
            )
            while i < len(lines):
                ml = lines[i].strip()
                if not ml:
                    i += 1
                    continue
                if ml.startswith("---"):
                    i += 1
                    continue
                if meta_re.match(ml):
                    i += 1
                    continue
                break
            # Emit structured meta block - placeholder for author (replaced with chip post-upload)
            if author:
                emit(f'<p>Author: {author}</p>\n')
            if date:
                emit(f'<p>Last Updated: {date}</p>\n')
            if branch:
                emit(f'<p>Branch: {branch}</p>\n')
            if status:
                emit(f'<p>Status: {status}</p>\n')
            if related_docs_lines:
                emit_br()
                for rdl in related_docs_lines:
                    emit(f'<p>{inline(rdl)}</p>\n')
            emit_br()
            if toc_headings:
                emit('<p><span style="font-weight:bold">Table of Contents</span></p>\n')
                for lvl, text, slug in toc_headings:
                    indent = 14 * (lvl - 2)
                    _internal_links.append({"text": text, "anchor": slug})
                    emit(f'<p style="margin-left:{indent}px"><a href="#{slug}">{text}</a></p>\n')
                emit_br()
            continue

        # ── Headings (H1-H6; Google Docs only has 6 named heading styles) ──
        hm = re.match(r'^(#{1,6})\s+(.*)', line)
        if hm:
            lvl = len(hm.group(1))
            heading_text = hm.group(2)
            slug = re.sub(r'[^a-z0-9]+', '-', heading_text.lower()).strip('-')
            emit_br()
            emit(f'<h{lvl} id="{slug}"><a name="{slug}"></a>{inline(heading_text)}</h{lvl}>\n')
            emit_br()
            i += 1
            continue

        # ── HR -> skip ──
        if re.match(r'^---+\s*$', line):
            i += 1
            continue

        # ── Image ──
        # Two supported forms:
        #   ![alt](src)                -> caption derived from alt (first-sentence fallback)
        #   ![alt](src "caption")      -> title attribute becomes caption; alt kept for a11y
        #
        # Important: a title may contain ')' (e.g. a range like `[0, 25)`). The
        # regex therefore anchors title closure on `"` and the outer `)` must
        # come *after* the full `"..."` title (if present). Whitespace around
        # src and between src/title/close-paren is tolerated.
        img_m = re.match(
            r'^!\[([^\]]*)\]\(\s*([^)\s]+?)\s*(?:"([^"]*)"\s*)?\)\s*$',
            line,
        )
        if img_m:
            alt, fn, title_cap = img_m.group(1), img_m.group(2), img_m.group(3)
            uri = img_b64(img_dir, fn)
            if uri:
                emit_br()
                emit(f'<p style="text-align:center"><img src="{uri}" width="{IMG_WIDTH_PX}" alt="{alt}"></p>\n')
                caption = _derive_caption(title_cap, alt)
                if caption:
                    emit(f'<p class="caption">{inline(caption)}</p>\n')
                emit_br()
            i += 1
            continue

        # ── Table ──
        if "|" in line and i + 1 < len(lines) and re.match(r'^\|[\s|:\-]+\|', lines[i + 1]):
            rows = []
            while i < len(lines) and "|" in lines[i]:
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                rows.append(cells)
                i += 1
            if len(rows) >= 2:
                rows.pop(1)

            emit_br()
            num_cols = len(rows[0])
            max_lens = [0] * num_cols
            for row in rows:
                for ci, cell in enumerate(row):
                    if ci < num_cols:
                        plain = re.sub(r'\*\*|`|\[([^\]]*)\]\([^)]*\)', r'\1', cell)
                        max_lens[ci] = max(max_lens[ci], len(plain))
            COL_CAP = 80
            MIN_LABEL_CHARS = 30
            capped = [max(min(ml, COL_CAP), MIN_LABEL_CHARS) for ml in max_lens]
            total = sum(capped) or 1
            pcts = [max(20, int(100 * c / total)) for c in capped]
            pct_total = sum(pcts)
            pcts = [int(p * 100 / pct_total) for p in pcts]
            _table_col_pcts.append(pcts)
            emit('<table>\n<colgroup>')
            for p in pcts:
                emit(f'<col style="width:{p}%">')
            emit('</colgroup>\n<tr>')
            for cell in rows[0]:
                emit(f'<th>{inline(cell)}</th>')
            emit('</tr>\n')
            for row in rows[1:]:
                first = row[0].strip().lower().replace("*", "")
                is_sum = first in ("agg", "overall", "total")
                cls = ' class="summary"' if is_sum else ''
                emit(f'<tr{cls}>')
                for cell in row:
                    style = '' if is_sum else ' style="font-weight:normal"'
                    emit(f'<td{style}>{inline(cell)}</td>')
                emit('</tr>\n')
            emit('</table>\n')
            emit_br()
            continue

        # ── Blockquote ──
        if line.startswith("> "):
            q = []
            while i < len(lines) and lines[i].startswith("> "):
                q.append(lines[i][2:])
                i += 1
            emit(f'<blockquote>{inline("<br>".join(q))}</blockquote>\n')
            emit_br()
            continue

        # ── Numbered list (no empty row before, only after) ──
        if re.match(r'^\d+\.\s', line):
            emit('<ol>\n')
            while i < len(lines) and re.match(r'^\d+\.\s', lines[i]):
                txt = re.sub(r'^\d+\.\s+', '', lines[i])
                i += 1
                while i < len(lines) and lines[i].startswith("  ") and not re.match(r'^(\d+\.|-)\s', lines[i]):
                    txt += " " + lines[i].strip()
                    i += 1
                emit(f'  <li>{inline(txt)}</li>\n')
            emit('</ol>\n')
            emit_br()
            continue

        # ── Bullet list (no empty row before, only after) ──
        if re.match(r'^[-*]\s', line):
            emit('<ul>\n')
            while i < len(lines) and re.match(r'^[-*]\s', lines[i]):
                txt = re.sub(r'^[-*]\s+', '', lines[i])
                i += 1
                while i < len(lines) and lines[i].startswith("  ") and not re.match(r'^[-*]\s', lines[i]):
                    txt += " " + lines[i].strip()
                    i += 1
                emit(f'  <li>{inline(txt)}</li>\n')
            emit('</ul>\n')
            emit_br()
            continue

        # ── Paragraph ──
        para = [line]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(r'^(#{1,6}\s|---|\||!\[|[-*]\s|\d+\.\s|>)', lines[i]):
            para.append(lines[i])
            i += 1
        emit(f'<p>{inline(" ".join(para))}</p>\n')
        # Skip BR if next non-empty line is a list (no gap before lists)
        j = i
        while j < len(lines) and not lines[j].strip():
            j += 1
        next_is_list = j < len(lines) and re.match(r'^([-*]\s|\d+\.\s)', lines[j])
        if not next_is_list:
            emit_br()

    h.append('</body></html>')
    return "".join(h)


def publish(md_path, title=None, author=None, author_email=None, date=None, branch=None, status="Draft",
            share_domains=None, delete_old_id=None, update_doc_id=None, style_inline_code=False):
    global _table_col_pcts, _internal_links, _code_spans
    _table_col_pcts = []
    _internal_links = []
    _code_spans = []
    img_dir = os.path.dirname(os.path.abspath(md_path))
    with open(md_path) as f:
        md_text = f.read()

    drive, docs_svc, creds = get_services()

    if delete_old_id and not update_doc_id:
        try:
            drive.files().delete(fileId=delete_old_id).execute()
            print(f"Deleted old doc: {delete_old_id}")
        except:
            pass

    print("Converting markdown to HTML...")
    html = md_to_html(md_text, img_dir, title=title, author=author, author_email=author_email, date=date, branch=branch, status=status)
    size_mb = len(html.encode()) / (1024 * 1024)
    print(f"HTML: {size_mb:.1f} MB")

    doc_title = title or os.path.splitext(os.path.basename(md_path))[0]
    media = MediaInMemoryUpload(html.encode(), mimetype="text/html", resumable=True)

    if update_doc_id:
        print(f"Updating existing doc {update_doc_id} in place...")
        uploaded = drive.files().update(
            fileId=update_doc_id,
            body={"name": doc_title, "mimeType": "application/vnd.google-apps.document"},
            media_body=media, media_mime_type="text/html",
            fields="id,webViewLink",
        ).execute()
    else:
        print(f"Uploading as '{doc_title}'...")
        uploaded = drive.files().create(
            body={"name": doc_title, "mimeType": "application/vnd.google-apps.document"},
            media_body=media, fields="id,webViewLink",
        ).execute()
    doc_id = uploaded["id"]
    url = uploaded.get("webViewLink", f"https://docs.google.com/document/d/{doc_id}/edit")
    print(f"Uploaded: {url}")

    # Post-upload: set line spacing 1.15 + zero paragraph spacing on ALL paragraphs
    # including those inside table cells
    doc = docs_svc.documents().get(documentId=doc_id).execute()
    body = doc.get("body", {}).get("content", [])
    reqs = []
    spacing_style = {
        "lineSpacing": 115,
        "spaceAbove": {"magnitude": 0, "unit": "PT"},
        "spaceBelow": {"magnitude": 0, "unit": "PT"},
    }
    spacing_fields = "lineSpacing,spaceAbove,spaceBelow"

    def add_para_spacing(paragraph):
        elems = paragraph.get("elements", [])
        start = elems[0].get("startIndex", 0) if elems else 0
        end = elems[-1].get("endIndex", 0) if elems else 0
        if start < end:
            reqs.append({"updateParagraphStyle": {
                "range": {"startIndex": start, "endIndex": end},
                "paragraphStyle": spacing_style,
                "fields": spacing_fields,
            }})

    for elem in body:
        if "paragraph" in elem:
            add_para_spacing(elem["paragraph"])
        elif "table" in elem:
            for row in elem["table"].get("tableRows", []):
                for cell in row.get("tableCells", []):
                    for cc in cell.get("content", []):
                        if "paragraph" in cc:
                            add_para_spacing(cc["paragraph"])
    # Set pageless mode
    reqs.append({"updateDocumentStyle": {
        "documentStyle": {"documentFormat": {"documentMode": "PAGELESS"}},
        "fields": "documentFormat",
    }})

    # Compute table width. In pageless mode, tables can be wider than the text
    # content area, so we use page width minus minimal margins (~0.5in each side).
    doc_style = doc.get("documentStyle", {})
    page_w = doc_style.get("pageSize", {}).get("width", {}).get("magnitude", 612)
    margin_l = doc_style.get("marginLeft", {}).get("magnitude", 72)
    margin_r = doc_style.get("marginRight", {}).get("magnitude", 72)
    text_width = page_w - margin_l - margin_r
    table_width_pt = max(text_width + 72, 540)
    print(f"Table width: {table_width_pt:.0f}pt (text area={text_width:.0f}pt, page={page_w:.0f}pt)")

    table_idx = 0
    for elem in body:
        if "table" in elem:
            if table_idx < len(_table_col_pcts):
                pcts = _table_col_pcts[table_idx]
                start_loc = {"index": elem["startIndex"]}
                for ci, pct in enumerate(pcts):
                    w_pt = round(table_width_pt * pct / 100)
                    reqs.append({"updateTableColumnProperties": {
                        "tableStartLocation": start_loc,
                        "columnIndices": [ci],
                        "tableColumnProperties": {
                            "widthType": "FIXED_WIDTH",
                            "width": {"magnitude": w_pt, "unit": "PT"},
                        },
                        "fields": "widthType,width",
                    }})
            table_idx += 1

    for b in range(0, len(reqs), 100):
        docs_svc.documents().batchUpdate(documentId=doc_id, body={"requests": reqs[b:b+100]}).execute()
    print(f"Applied spacing to {len(reqs)-1-table_idx} paragraphs + {table_idx} table(s) column widths + pageless mode")

    # Remove consecutive empty rows (cleanup pass)
    for attempt in range(3):
        doc = docs_svc.documents().get(documentId=doc_id).execute()
        body = doc.get("body", {}).get("content", [])
        prev_empty = False
        deleted = 0
        for elem in reversed(body):
            if "paragraph" not in elem:
                prev_empty = False
                continue
            elements = elem["paragraph"].get("elements", [])
            text = "".join(e.get("textRun", {}).get("content", "") for e in elements).strip()
            is_empty = text in ("", "\u00a0", "\n")
            if is_empty and prev_empty:
                start = elements[0].get("startIndex", 0)
                end = elements[-1].get("endIndex", 0)
                if start > 0 and end > start:
                    try:
                        docs_svc.documents().batchUpdate(documentId=doc_id, body={"requests": [
                            {"deleteContentRange": {"range": {"startIndex": start, "endIndex": end}}}
                        ]}).execute()
                        deleted += 1
                    except:
                        pass
            prev_empty = is_empty
        if deleted == 0:
            break
        print(f"Cleanup pass {attempt+1}: removed {deleted} duplicate empty rows")

    # Fix internal anchor links via bookmarks
    if _internal_links:
        doc = docs_svc.documents().get(documentId=doc_id).execute()
        body = doc.get("body", {}).get("content", [])

        # Build heading slug -> startIndex map
        heading_positions = {}
        for elem in body:
            if "paragraph" not in elem:
                continue
            ps = elem["paragraph"].get("paragraphStyle", {})
            if "HEADING" in ps.get("namedStyleType", ""):
                text = "".join(e.get("textRun", {}).get("content", "") for e in elem["paragraph"]["elements"]).strip()
                slug = re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')
                start = elem["paragraph"]["elements"][0].get("startIndex", 0)
                heading_positions[slug] = start

        # Create bookmarks at target headings
        unique_anchors = list(set(il["anchor"] for il in _internal_links if il["anchor"] in heading_positions))
        bookmark_map = {}
        for anchor in unique_anchors:
            pos = heading_positions[anchor]
            try:
                result = docs_svc.documents().batchUpdate(documentId=doc_id, body={"requests": [
                    {"createBookmark": {"location": {"index": pos}}}
                ]}).execute()
                bm_id = result["replies"][0]["createBookmark"]["bookmarkId"]
                bookmark_map[anchor] = bm_id
            except Exception:
                pass

        if bookmark_map:
            # Re-read doc for fresh indices after bookmark creation
            doc = docs_svc.documents().get(documentId=doc_id).execute()
            body = doc.get("body", {}).get("content", [])

            # Find the link text in the body and apply bookmark links
            link_reqs = []
            for il in _internal_links:
                bm_id = bookmark_map.get(il["anchor"])
                if not bm_id:
                    continue
                # Search for the exact text
                for elem in body:
                    if "paragraph" not in elem:
                        continue
                    for e in elem["paragraph"].get("elements", []):
                        tr = e.get("textRun", {})
                        content = tr.get("content", "")
                        if il["text"] in content:
                            offset = content.index(il["text"])
                            start = e["startIndex"] + offset
                            end = start + len(il["text"])
                            link_reqs.append({"updateTextStyle": {
                                "range": {"startIndex": start, "endIndex": end},
                                "textStyle": {"link": {"bookmarkId": bm_id}},
                                "fields": "link",
                            }})
                            break

            if link_reqs:
                docs_svc.documents().batchUpdate(documentId=doc_id, body={"requests": link_reqs}).execute()
                print(f"Created {len(bookmark_map)} bookmarks, linked {len(link_reqs)} internal references")

    # Post-upload: restyle inline code ranges to Roboto Mono + gray background.
    # HTML import does not preserve <code> styling; we walk the document, find
    # each previously-masked literal in the text, and batch updateTextStyle.
    if style_inline_code and _code_spans:
        doc = docs_svc.documents().get(documentId=doc_id).execute()
        body = doc.get("body", {}).get("content", [])
        code_reqs = []
        # Sort longer spans first so e.g. `[0, 25)` is applied before `[0` partial.
        spans_sorted = sorted(set(_code_spans), key=len, reverse=True)

        def scan_paragraph_for_code(paragraph):
            for e in paragraph.get("elements", []):
                tr = e.get("textRun", {})
                content = tr.get("content", "")
                if not content:
                    continue
                start_idx = e.get("startIndex", 0)
                # Skip ranges that are already links (e.g., anchor links) -
                # restyling link text would override the link color in some
                # renderers. But Docs keeps link + font as independent fields,
                # so this is actually safe. We apply regardless.
                for span in spans_sorted:
                    offset = 0
                    while True:
                        pos = content.find(span, offset)
                        if pos < 0:
                            break
                        code_reqs.append({"updateTextStyle": {
                            "range": {
                                "startIndex": start_idx + pos,
                                "endIndex": start_idx + pos + len(span),
                            },
                            "textStyle": {
                                "weightedFontFamily": {"fontFamily": CODE_FONT_FAMILY},
                                "backgroundColor": CODE_BG_COLOR,
                            },
                            "fields": "weightedFontFamily,backgroundColor",
                        }})
                        offset = pos + len(span)

        for elem in body:
            if "paragraph" in elem:
                scan_paragraph_for_code(elem["paragraph"])
            elif "table" in elem:
                for row in elem["table"].get("tableRows", []):
                    for cell in row.get("tableCells", []):
                        for cc in cell.get("content", []):
                            if "paragraph" in cc:
                                scan_paragraph_for_code(cc["paragraph"])

        # Dedupe identical requests (same range + same style).
        seen = set()
        deduped = []
        for r in code_reqs:
            rng = r["updateTextStyle"]["range"]
            key = (rng["startIndex"], rng["endIndex"])
            if key in seen:
                continue
            seen.add(key)
            deduped.append(r)

        # Pace through in 100-request batches to avoid quota 429s.
        applied = 0
        for b in range(0, len(deduped), 100):
            batch = deduped[b:b + 100]
            try:
                docs_svc.documents().batchUpdate(
                    documentId=doc_id, body={"requests": batch}
                ).execute()
                applied += len(batch)
            except Exception as exc:
                # On quota error, sleep and retry once; then give up on this batch.
                msg = str(exc)
                if "429" in msg or "Quota" in msg:
                    import time as _t
                    _t.sleep(65)
                    try:
                        docs_svc.documents().batchUpdate(
                            documentId=doc_id, body={"requests": batch}
                        ).execute()
                        applied += len(batch)
                    except Exception as exc2:
                        print(f"Code-style batch {b}: {exc2}")
                else:
                    print(f"Code-style batch {b}: {exc}")
        print(f"Monospace-styled {applied} inline-code ranges ({len(spans_sorted)} unique literals)")

    # Post-upload: force all hyperlinks to standard Google Docs blue (#1155CC).
    # The HTML importer applies an older browser blue (#0000EE rendered as "pure
    # blue") to <a> tags regardless of CSS / inline style hints. We walk the
    # entire document, collect every textRun whose textStyle.link is set, and
    # re-style it with foregroundColor=#1155CC + underline, matching the color
    # Docs uses for hand-inserted hyperlinks.
    link_color_reqs = []

    def scan_para_for_links(paragraph):
        for e in paragraph.get("elements", []):
            tr = e.get("textRun", {})
            ts = tr.get("textStyle", {}) or {}
            if not ts.get("link"):
                continue
            start = e.get("startIndex")
            end = e.get("endIndex")
            if start is None or end is None or end <= start:
                continue
            link_color_reqs.append({"updateTextStyle": {
                "range": {"startIndex": start, "endIndex": end},
                "textStyle": {
                    "foregroundColor": {"color": {"rgbColor": {
                        "red": 0.06666667, "green": 0.33333334, "blue": 0.8,
                    }}},
                    "underline": True,
                },
                "fields": "foregroundColor,underline",
            }})

    doc_final = docs_svc.documents().get(documentId=doc_id).execute()
    body_final = doc_final.get("body", {}).get("content", [])
    for elem in body_final:
        if "paragraph" in elem:
            scan_para_for_links(elem["paragraph"])
        elif "table" in elem:
            for row in elem["table"].get("tableRows", []):
                for cell in row.get("tableCells", []):
                    for cc in cell.get("content", []):
                        if "paragraph" in cc:
                            scan_para_for_links(cc["paragraph"])

    applied = 0
    for b in range(0, len(link_color_reqs), 100):
        batch = link_color_reqs[b:b + 100]
        try:
            docs_svc.documents().batchUpdate(
                documentId=doc_id, body={"requests": batch}
            ).execute()
            applied += len(batch)
        except Exception as exc:
            msg = str(exc)
            if "429" in msg or "Quota" in msg:
                import time as _t
                _t.sleep(65)
                try:
                    docs_svc.documents().batchUpdate(
                        documentId=doc_id, body={"requests": batch}
                    ).execute()
                    applied += len(batch)
                except Exception as exc2:
                    print(f"Link-color batch {b}: {exc2}")
            else:
                print(f"Link-color batch {b}: {exc}")
    if applied:
        print(f"Recolored {applied} hyperlinks to standard Docs blue (#1155CC)")

    # Insert person chip for author (replace plain text name with @mention)
    if author and author_email:
        doc = docs_svc.documents().get(documentId=doc_id).execute()
        body = doc.get("body", {}).get("content", [])
        for elem in body[:15]:
            if "paragraph" not in elem:
                continue
            elements = elem["paragraph"].get("elements", [])
            full = "".join(e.get("textRun", {}).get("content", "") for e in elements)
            if full.strip().startswith("Author:") and author in full:
                # Find the author name text run and its indices
                for e in elements:
                    tr = e.get("textRun", {})
                    if author in tr.get("content", ""):
                        name_start = e["startIndex"] + tr["content"].index(author)
                        name_end = name_start + len(author)
                        # Delete the name text, insert person chip
                        docs_svc.documents().batchUpdate(documentId=doc_id, body={"requests": [
                            {"deleteContentRange": {"range": {"startIndex": name_start, "endIndex": name_end}}},
                            {"insertPerson": {"location": {"index": name_start}, "personProperties": {"email": author_email}}},
                        ]}).execute()
                        print(f"Inserted @mention chip for {author_email}")
                        break
                break

    # Share with domains
    if share_domains:
        for domain in share_domains:
            try:
                drive.permissions().create(
                    fileId=doc_id, body={"type": "domain", "role": "writer", "domain": domain},
                ).execute()
                print(f"Shared with {domain} (editor)")
            except Exception as e:
                print(f"Share {domain}: {e}")

    # Verify
    doc = docs_svc.documents().get(documentId=doc_id).execute()
    imgs = len(doc.get("inlineObjects", {}))
    tbls = sum(1 for e in doc.get("body", {}).get("content", []) if "table" in e)
    headings = sum(1 for e in doc.get("body", {}).get("content", [])
                   if "paragraph" in e and "HEADING" in e["paragraph"].get("paragraphStyle", {}).get("namedStyleType", ""))

    print(f"\nImages: {imgs} | Tables: {tbls} | Headings: {headings}")
    print(f"URL: {url}")
    return doc_id, url


if __name__ == "__main__":
    IMG_DIR = "/home/yike.li/workspaces/cruise/src/github.robot.car/cruise/cruise/cruise/mlp/robotorch/project/trajectory_ranking/scene_encoder/notebooks/output"
    MD_PATH = os.path.join(IMG_DIR, "nvidia_zero_shot_results_gdoc.md")

    publish(
        md_path=MD_PATH,
        title="Structured Perception - NVIDIA Zero-Shot Inference Results",
        author="Jason Li",
        author_email="yike.li@getcruise.com",
        date="2026-03-27",
        branch="jl/nvidia-msl-label-conversion",
        status="Draft",
        share_domains=["getcruise.com"],
    )
