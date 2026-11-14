#!/usr/bin/env python3
"""
Documentation and Markdown Link Integrity Validator.
Checks that all required repository documents exist and all relative markdown links resolve.
Part of the Bortle Cero CI pipeline (NASA Space Apps Challenge 2026).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REQUIRED_DOCS = [
    "README.md",
    "AGENTS.md",
    "DESIGN.md",
    "docs/AI-USAGE.md",
    "docs/SOURCES.md",
    "docs/GUIA-EQUIPO-INGESTA.md",
]


def check_required_docs(repo_root: Path) -> list[str]:
    errors: list[str] = []
    for doc in REQUIRED_DOCS:
        p = repo_root / doc
        if not p.is_file():
            errors.append(f"Missing required document: {doc}")
        elif p.stat().st_size == 0:
            errors.append(f"Required document is empty: {doc}")
    return errors


def check_markdown_links(repo_root: Path) -> list[str]:
    errors: list[str] = []
    link_pattern = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
    md_files = sorted(
        list(repo_root.glob("*.md")) + list(repo_root.glob("docs/*.md"))
    )

    for md in md_files:
        content = md.read_text(encoding="utf-8")
        for match in link_pattern.finditer(content):
            href = match.group(2).strip()
            # Ignore absolute URLs, mailto, local fragment-only anchors,
            # and special conversation URIs
            if href.startswith(
                ("http://", "https://", "mailto:", "#", "conversation://", "file://")
            ):
                continue
            path_part = href.split("#")[0]
            if not path_part:
                continue
            target = (md.parent / path_part).resolve()
            if not target.exists():
                errors.append(f"Broken relative link in {md.name}: '{href}' -> {target}")

    return errors


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    errors: list[str] = []

    print(f"Validating repository documentation in: {repo_root}")
    req_errors = check_required_docs(repo_root)
    if req_errors:
        errors.extend(req_errors)

    link_errors = check_markdown_links(repo_root)
    if link_errors:
        errors.extend(link_errors)

    if errors:
        print(f"\n[FAIL] Found {len(errors)} documentation issue(s):", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print("[SUCCESS] All required documentation files and relative markdown links are valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
