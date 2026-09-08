"""Meta test: no em dashes anywhere in the tracked source or docs.

House rule from PLAN.md section 12. Scoped through git ls-files, which honours .gitignore,
so gitignored files (PLAN.md, .prompts/) are never read by the test suite.
Untracked but not ignored files are included too, so a new file is checked
before it is committed rather than after.
"""

import subprocess
from pathlib import Path

import pytest

# Written as an escape so that this file does not itself contain the character.
EM_DASH = "\u2014"

REPO_ROOT = Path(__file__).resolve().parent.parent

SCANNED_PREFIXES = ("src/", "tests/", "examples/")


def tracked_files():
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=REPO_ROOT,
            capture_output=True,
            check=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        pytest.skip(f"git ls-files unavailable: {exc}")

    return [name for name in result.stdout.split("\0") if name]


def scanned_files():
    """Every tracked file under src/ or tests/, plus every tracked Markdown file."""
    selected = []
    for name in tracked_files():
        if name.startswith(SCANNED_PREFIXES) or name.endswith(".md"):
            path = REPO_ROOT / name
            if path.is_file():
                selected.append(name)
    return selected


def test_scan_covers_the_expected_files():
    """Guard against the scan silently matching nothing and passing for free."""
    names = scanned_files()
    assert "README.md" in names
    assert any(name.startswith("src/runprobe/") for name in names)
    assert any(name.startswith("tests/") for name in names)
    assert any(name.startswith("examples/") for name in names)


def test_no_em_dashes_in_tracked_source_and_docs():
    offenders = []
    for name in scanned_files():
        text = (REPO_ROOT / name).read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if EM_DASH in line:
                offenders.append(f"{name}:{lineno}: {line.strip()}")

    assert not offenders, "em dash found (house rule, use commas or colons):\n" + "\n".join(
        offenders
    )
