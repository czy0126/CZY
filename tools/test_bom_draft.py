"""Structural checks for design/v3/bom/bom_draft.csv.

The BOM is a draft, but its status labels are what keep it from being mistaken
for a frozen purchase list.  These tests pin the schema and the labels.
"""

from __future__ import annotations

import csv
from pathlib import Path

BOM = Path(__file__).resolve().parent.parent / "design/v3/bom/bom_draft.csv"
COLUMNS = ["group", "ref", "qty", "item", "mpn", "package", "value_or_rating", "basis", "status", "source"]
STATUSES = {"VERIFIED", "VALUE FROZEN", "TO SELECT", "TO BUILD"}


def rows() -> list[dict[str, str]]:
    with BOM.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def test_schema_and_status_vocabulary():
    data = rows()
    assert data, "BOM is empty"
    assert list(data[0]) == COLUMNS
    assert {row["status"] for row in data} <= STATUSES


def test_every_row_has_a_source_or_is_marked_open():
    for row in rows():
        assert row["source"].strip(), row["ref"]
        assert row["qty"].isdigit(), row["ref"]


def test_verified_rows_cite_a_file_that_exists():
    root = BOM.parent.parent.parent.parent
    for row in rows():
        if row["status"] == "VERIFIED":
            assert (root / row["source"]).exists(), row["source"]


def test_unselected_parts_do_not_carry_a_fake_mpn():
    for row in rows():
        if row["status"] == "TO SELECT":
            assert row["mpn"] == "TO SELECT", row["ref"]
