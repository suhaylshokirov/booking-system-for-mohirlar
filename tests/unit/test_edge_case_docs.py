"""docs/edge-cases.md is only worth anything if every test it names exists.

The Definition of Done says each risk handled gets a row with its test. Renaming
or deleting a test silently turns that row into a claim nothing proves, so this
test reads the table and checks the names against the test sources.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TABLE_START = "## Table"


def _table_rows() -> list[str]:
    text = (ROOT / "docs" / "edge-cases.md").read_text()
    table = text[text.index(TABLE_START) :]
    return [line for line in table.splitlines() if re.match(r"\| \d+ \|", line)]


def _defined_tests() -> set[str]:
    names: set[str] = set()
    for source in (ROOT / "tests").rglob("*.py"):
        names.update(re.findall(r"def (test_\w+)", source.read_text()))
    return names


def test_every_edge_case_row_names_a_test_and_all_of_them_exist():
    defined = _defined_tests()
    problems = []
    for row in _table_rows():
        number = row.split("|")[1].strip()
        # `test_name` is one test; `test_prefix_*` stands for a family of them.
        named = re.findall(r"(?<![/\w])(test_\w+)(\*)?", row)  # not a file name
        if not named:
            problems.append(f"row {number}: names no test")
        for name, star in named:
            if star:
                found = any(test.startswith(name) for test in defined)
            else:
                found = name in defined
            if not found:
                problems.append(f"row {number}: {name}{star} does not exist")

    assert not problems, "\n".join(problems)


def test_every_test_file_named_in_the_table_exists():
    missing = []
    for row in _table_rows():
        for path in re.findall(r"`(tests/[\w/]+\.py)", row):
            if not (ROOT / path).exists():
                missing.append(f"{row.split('|')[1].strip()}: {path}")

    assert not missing, "\n".join(missing)


def test_no_row_is_still_marked_planned():
    planned = [row.split("|")[1].strip() for row in _table_rows() if "planned" in row.lower()]

    assert not planned, f"rows still planned: {planned}"
