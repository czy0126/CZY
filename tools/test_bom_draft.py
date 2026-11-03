"""Structural checks for design/v3/bom/bom_draft.csv.

The BOM is a draft, but its status labels are what keep it from being mistaken
for a frozen purchase list.  These tests pin the schema and the labels.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOM = ROOT / "design/v3/bom/bom_draft.csv"
DATASHEET = ROOT / "references/datasheets/csd19531q5a.txt"
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


def test_the_primary_fet_max_rds_matches_the_vendored_datasheet():
    """SOURCE-02: the BOM said 6.2 mOhm max; the vendored table says 6.4.

    The number is a purchase/derating input, so it must be traceable to the
    vendored datasheet rather than to a figure eyeballed once.  The datasheet
    text is the same file the BOM cites; if TI ships a new revision the table
    changes and this test fails instead of the BOM drifting silently.
    """
    text = DATASHEET.read_text(encoding="utf-8", errors="ignore")
    table = re.search(r"VGS = 10 V, ID = 16 A\s*\n5\.3\s*\n6\.4\s*\nm", text)
    assert table, "vendored datasheet no longer lists 5.3 typ / 6.4 max at VGS=10 V"
    value = next(r for r in rows() if r["ref"] == "QH QL")["value_or_rating"]
    assert "5.3 mohm typ" in value
    assert "6.4 mohm max" in value
    assert "6.2 mohm" not in value
