"""Vendor packets must preserve unknowns and never fake approval."""
from __future__ import annotations

import csv
import export_d1_vendor_packets as p


def test_vendor_packet_is_reproducible_and_fail_closed():
    mag, bom = p.rows()
    assert len(mag) == 24
    assert len(bom) == 61
    assert {x["ref"] for x in mag} == {"CT", "T1", "T2", "T3", "T4"}
    assert all(x["supplier_physical_pad"] == "" and x["decision"] == "PENDING"
               and x["terminal_footprint_verified"] == "NO" for x in mag)
    assert all(x["proposed_mpn"] == "" and x["decision"] == "PENDING"
               and x["electrical_stress_accepted"] == "NO" for x in bom)


def test_checked_in_packet_rows_and_priority_are_current():
    assert p.MAG_OUT.read_text(encoding="utf-8") == p.serialize(p.MAG_FIELDS, p.rows()[0])
    assert p.BOM_OUT.read_text(encoding="utf-8") == p.serialize(p.BOM_FIELDS, p.rows()[1])
    with p.BOM_OUT.open(encoding="utf-8", newline="") as fp:
        rows = list(csv.DictReader(fp))
    assert len(rows) == 61
    assert rows[0]["priority"] == "P0"
    assert any(row["ref"] == "Cr" for row in rows)
    assert not any(row["pad_map_reviewed"] != "NO" for row in rows)
