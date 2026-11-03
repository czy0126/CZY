"""Generated D1 RFQ sheets are complete and still unverified."""
import csv
import io
import d1_reference_kit as kit


def test_supplier_seed_matches_all_61_current_placeholders():
    result = list(csv.DictReader(io.StringIO(kit.supplier_seed())))
    assert len(result) == 61
    assert len({x["ref"] for x in result}) == 61
    assert all(x["status"] == x["verified_mpn"] == "PENDING" for x in result)


def test_magnetic_seed_contains_24_real_pin_requests():
    result = list(csv.DictReader(io.StringIO(kit.magnetic_seed())))
    assert len(result) == 24
    assert {x["ref"] for x in result} == {"CT", "T1", "T2", "T3", "T4"}
    assert all(x["supplier_terminal"] == "PENDING" for x in result)


def test_committed_seed_is_current():
    assert kit.SUPPLIER.read_text(encoding="utf-8") == kit.supplier_seed()
    assert kit.MAGNETICS.read_text(encoding="utf-8") == kit.magnetic_seed()
