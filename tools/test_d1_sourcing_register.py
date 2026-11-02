"""Pre-fab supplier registers are reproducible and cannot certify unknown pads."""
from __future__ import annotations
import json
import d1_sourcing_register as reg


def test_61_real_placeholder_references_are_covered():
    parts, _ = reg.build()
    assert parts["total_placeholder_refs"] == 61
    assert len({x["ref"] for x in parts["items"]}) == 61
    assert all(x["verified_mpn"] is None and not x["eda_footprint_verified"]
               for x in parts["items"])


def test_every_magnetic_pin_has_vendor_fillable_physical_pad_and_dot():
    _, query = reg.build()
    assert {x["ref"] for x in query["devices"]} == {"CT","T1","T2","T3","T4"}
    assert sum(len(x["pins"]) for x in query["devices"]) == 24
    for item in query["devices"]:
        assert not item["accepted_by_engineer"]
        for term in item["pins"]:
            assert term["vendor_physical_terminal_id"] is None
            assert term["required_circuit_net"] and term["dot_convention_expected"]


def test_checked_in_supplier_requests_are_current():
    parts, query = reg.build()
    assert json.loads(reg.REG.read_text(encoding="utf-8")) == parts
    assert json.loads(reg.VENDOR.read_text(encoding="utf-8")) == query
