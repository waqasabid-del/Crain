"""Report the comment-to-code ratio per file against the budget in md/17 §8.1.

Python is measured with `tokenize`, not by matching quotes line by line. The
previous JavaScript version treated the *closing* delimiter of a module-level
constant like ``SAMPLE = \"\"\"\\`` as an opener and counted the rest of the file
as prose — `pipeline/live_check.py` reported 70% and is actually 13%, and two
people changed code to satisfy that number before anyone checked the tool.

A docstring counts as documentation; a string assigned to a name is data.
Only `tokenize` can tell them apart reliably.
"""

from __future__ import annotations

import io
import re
import sys
import token as token_types
import tokenize
from pathlib import Path

#: Logic explains itself through code, so a comment there is an exception.
LOGIC_BUDGET = 15

#: Declaration modules — enums, schemas, ORM models, design tokens — are field
#: lists whose meaning is not recoverable from `String(32)` or `OWNER = "owner"`.
#: Documenting each field is the job, so they get a wider budget.
DECLARATION_BUDGET = 35

DECLARATION = re.compile(r"(models?|schemas?|domain|tokens|envelope|contract|types)[/\\.]", re.I)

#: Below this, a module docstring alone can exceed any percentage. Measured and
#: reported, never failed.
SMALL_FILE_LINES = 60

ROOTS = ("apps/api/src", "apps/web/src", "packages")
SKIP = {"node_modules", "__pycache__", "dist", ".next", "generated", ".venv"}


def budget_for(path: Path) -> int:
    return DECLARATION_BUDGET if DECLARATION.search(str(path)) else LOGIC_BUDGET


def python_ratio(source: str) -> tuple[int, int]:
    """Comment lines and total non-blank lines, by tokenising."""
    total = sum(1 for line in source.splitlines() if line.strip())
    documented = 0

    tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    for index, tok in enumerate(tokens):
        if tok.type == token_types.COMMENT:
            documented += 1
            continue
        if tok.type != token_types.STRING:
            continue
        # A docstring stands alone as an expression statement; a string bound to
        # a name is data. The preceding significant token tells them apart.
        previous = next(
            (
                candidate
                for candidate in reversed(tokens[:index])
                if candidate.type not in {token_types.NEWLINE, token_types.NL, token_types.INDENT}
            ),
            None,
        )
        if previous is None or previous.type in {token_types.INDENT, token_types.DEDENT}:
            documented += tok.string.count("\n") + 1

    return documented, total


def typescript_ratio(source: str) -> tuple[int, int]:
    lines = [line for line in source.splitlines() if line.strip()]
    documented = 0
    in_block = False

    for line in lines:
        text = line.strip()
        if in_block:
            documented += 1
            if "*/" in text:
                in_block = False
        elif text.startswith("//"):
            documented += 1
        elif text.startswith("/*") or text.startswith("{/*"):
            documented += 1
            in_block = "*/" not in text

    return documented, len(lines)


def measure(path: Path) -> tuple[int, int, int] | None:
    source = path.read_text(encoding="utf-8")
    try:
        documented, total = (
            python_ratio(source) if path.suffix == ".py" else typescript_ratio(source)
        )
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return None
    if total == 0:
        return None
    return documented, total, round(documented * 100 / total)


def main() -> int:
    files = [
        path
        for root in ROOTS
        for path in Path(root).rglob("*")
        if path.suffix in {".py", ".ts", ".tsx"}
        and not any(part in SKIP for part in path.parts)
        and ".test." not in path.name
    ]

    rows = []
    for path in sorted(files):
        result = measure(path)
        if result is None:
            continue
        documented, total, pct = result
        rows.append((pct, documented, total, path))

    over = [row for row in rows if row[0] > budget_for(row[3]) and row[2] >= SMALL_FILE_LINES]
    for pct, documented, total, path in sorted(over, reverse=True):
        print(f"{pct:3d}%  (budget {budget_for(path):2d}%)  {documented:4d}/{total:<5d} {path}")

    median = sorted(row[0] for row in rows)[len(rows) // 2] if rows else 0
    small = sum(1 for row in rows if row[2] < SMALL_FILE_LINES)
    print(
        f"\n{len(over)} of {len(rows)} files over budget. Median {median}%. "
        f"{small} files under {SMALL_FILE_LINES} lines are measured but not failed."
    )
    return 1 if over else 0


if __name__ == "__main__":
    sys.exit(main())
