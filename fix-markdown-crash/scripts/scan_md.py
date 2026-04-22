#!/usr/bin/env python3
"""Scan markdown files for patterns that crash Cursor's markdown parser.

Usage:
    python scan_md.py FILE_OR_DIR [--fix]

Accepts a single .md file or a directory (scans all *.md files recursively).
Without --fix: prints problematic lines with context.
With --fix: rewrites files with common auto-fixes applied.
"""
import re
import sys
from pathlib import Path
from typing import List, Tuple

REWORD_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"<br\s*/?>", re.IGNORECASE), " -- "),
    (re.compile(r"<!--.*?-->", re.DOTALL), ""),
    (re.compile(r"<(https?://[^|>]+)\|([^>]+)>"), r"[\2](\1)"),
    (re.compile(r"<@\w+>"), "someone"),
    (re.compile(r"\s*>=\s*"), " at least "),
    (re.compile(r"\s*<=\s*"), " at most "),
    (re.compile(r"<\s*(\d[\d.]*)"), r"under \1"),
    (re.compile(r">\s*~?\s*(\d[\d.]*)"), r"above \1"),
]

BARE_ANGLE_RE = re.compile(r"<(?!/?\s*(?:code|pre)\b)[^`]|(?<![`])[^`]>")


def _in_code_span(line: str, pos: int) -> bool:
    """Return True if position is inside a backtick code span."""
    ticks = 0
    i = 0
    while i < pos:
        if line[i] == "`":
            run = 0
            while i < pos and line[i] == "`":
                run += 1
                i += 1
            ticks += 1
        else:
            i += 1
    return ticks % 2 == 1


def _in_fenced_block(lines: List[str], line_idx: int) -> bool:
    """Return True if line_idx is inside a fenced code block."""
    fence_count = 0
    for i in range(line_idx):
        stripped = lines[i].lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            fence_count += 1
    return fence_count % 2 == 1


def _is_blockquote(line: str, pos: int) -> bool:
    """Return True if > at pos is a markdown blockquote marker."""
    return line[:pos].strip() == "" and pos < len(line) and line[pos] == ">"


def _is_arrow(line: str, pos: int) -> bool:
    """Return True if < or > at pos is part of a text arrow (-> or --> or <-)."""
    ch = line[pos]
    if ch == ">":
        if pos >= 1 and line[pos - 1] == "-":
            return True
        if pos >= 2 and line[pos - 2 : pos] == "--":
            return True
    if ch == "<":
        if pos + 1 < len(line) and line[pos + 1] == "-":
            return True
    return False


def scan(filepath: str) -> List[Tuple[int, str, str]]:
    """Return list of (line_number, line_content, reason) for problematic lines."""
    path = Path(filepath)
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    issues: List[Tuple[int, str, str]] = []

    for idx, line in enumerate(lines):
        if _in_fenced_block(lines, idx):
            continue

        for m in re.finditer(r"[<>]", line):
            pos = m.start()
            ch = m.group()
            if _in_code_span(line, pos):
                continue
            if _is_blockquote(line, pos):
                continue
            if _is_arrow(line, pos):
                continue
            context = line[max(0, pos - 15) : pos + 16].strip()
            issues.append((idx + 1, line.strip(), f"bare '{ch}' at col {pos + 1}: ...{context}..."))

    return issues


def fix(filepath: str) -> int:
    """Apply auto-fixes and return count of changes made."""
    path = Path(filepath)
    text = path.read_text(encoding="utf-8")
    original = text
    for pattern, replacement in REWORD_PATTERNS:
        text = pattern.sub(replacement, text)
    if text != original:
        path.write_text(text, encoding="utf-8")
    changes = sum(1 for a, b in zip(original, text) if a != b)
    return changes


def _collect_files(target: str) -> List[Path]:
    p = Path(target)
    if p.is_dir():
        return sorted(p.rglob("*.md"))
    return [p]


def main() -> None:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} FILE_OR_DIR [--fix]")
        sys.exit(1)

    target = sys.argv[1]
    do_fix = "--fix" in sys.argv
    files = _collect_files(target)

    if not files:
        print(f"No .md files found in {target}.")
        sys.exit(0)

    total_issues = 0
    files_with_issues = 0

    for fpath in files:
        fp = str(fpath)
        if do_fix:
            changes = fix(fp)
            if changes:
                print(f"Auto-fixed {fpath.name} ({changes} char changes)")

        issues = scan(fp)
        if issues:
            files_with_issues += 1
            total_issues += len(issues)
            print(f"\n=== {fpath.name} === ({len(issues)} issue(s))\n")
            for lineno, content, reason in issues:
                print(f"  L{lineno}: {reason}")
                print(f"         {content[:120]}")
                print()

    if total_issues:
        print(f"TOTAL: {total_issues} issue(s) in {files_with_issues} file(s) out of {len(files)} scanned.")
        sys.exit(1 if not do_fix else 0)
    else:
        print(f"All clean: {len(files)} file(s) scanned, no crash patterns found.")
        sys.exit(0)


if __name__ == "__main__":
    main()
