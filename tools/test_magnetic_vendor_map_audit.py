"""Vendor reply regressions: synthetic pad names never count as physical evidence."""
from __future__ import annotations

import copy
import csv
import hashlib
import json

import pytest

import magnetic_vendor_map_audit as m


def synthetic_complete_rows():
    rows = m.blank_rows()
    counts = {}
    for row in rows:
        ref = row["ref"]
        counts[ref] = counts.get(ref, 0) + 1
        pos = counts[ref]
        row.update({
            "supplier_terminal": f"FAKE_PAD_{pos}",
            "supplier_dot": (
                ("DOT" if row["logical_pin"] in ("PRI_A", "SEC_A") else "NON_DOT")
                if ref == "CT" else
                ("CTAP_SPLICE" if row["logical_pin"] == "CTAP"
                 else row["model_polarity"])),
            "pad_xy_mm": f"{pos * 2},0",
            "mechanical_footprint_ref": "FAKE_TEST_FOOTPRINT",
            "manufacturer_drawing": "FAKE_TEST_MANUFACTURER_DRAWING",
            "drawing_rev": "FAKE_TEST_REV",
            "drawing_sha256": "a" * 64,
            "measured_phase": "MATCH",
            "phase_test_record": "FAKE_TEST_NOT_A_PHYSICAL_MEASUREMENT",
            "phase_test_sha256": "b" * 64,
            "reviewer": "FAKE_TEST_ONLY",
            "status": "SUPPLIER_PROPOSED",
        })
    return rows


def test_legacy_terminal_sheet_is_full_24_rows_and_center_tap_net_fixed():
    legacy=m.ROOT / "docs/D1_EXECUTION_KIT/templates/magnetic_terminal_map.csv"
    with legacy.open(encoding="utf-8",newline="") as f:
        rows=list(csv.DictReader(f))
    frozen=m.contract_entries()
    assert len(rows)==len(frozen)==24
    assert set((r["ref"],r["logical_pin"]) for r in rows)==set(frozen)
    for row in rows:
        key=(row["ref"],row["logical_pin"])
        assert row["logical_net"]==frozen[key]["golden_net"]
        assert row["physical_terminal_number"]=="PENDING"
        assert row["dot_or_non_dot"]=="PENDING"
    assert next(r for r in rows if r["ref"]=="T1" and r["logical_pin"]=="CTAP")["logical_net"]=="VOUT"


def test_template_covers_exactly_24_logical_pins_without_physical_claim():
    response = m.DEFAULT_TEMPLATE
    saved = m.load_rows(response)
    assert saved == m.blank_rows()
    assert len(saved) == 24
    assert {r["ref"] for r in saved} == {"CT", "T1", "T2", "T3", "T4"}
    assert m.evaluate(saved)["status"] == "INCOMPLETE_VENDOR_PACKET"
    assert not m.evaluate(saved)["physical_pad_map_verified"]


def test_synthetic_complete_packet_only_means_human_review_not_signoff():
    result = m.evaluate(synthetic_complete_rows())
    assert result["status"] == "REVIEW_PACKAGE_COMPLETE_NOT_APPROVED"
    assert result["rows_with_all_response_fields"] == 24
    assert result["submitted_unique_terminal_count"] == 24
    assert not result["ct_relative_phase_independently_proven"]
    assert not result["supplier_document_authenticity_verified"]
    assert not result["physical_pad_map_verified"]
    assert not result["native_cad_replaced_with_real_footprints"]
    assert not result["fabrication_approved"]
    assert result["human_review_mandatory"]


def test_wrong_or_duplicate_physical_pad_rejected():
    rows = synthetic_complete_rows()
    rows[1]["supplier_terminal"] = rows[0]["supplier_terminal"]
    result = m.evaluate(rows)
    assert result["status"] == "CONTRACT_REJECTED"
    assert any("duplicated physical pad" in p for p in result["errors"])
    rows = synthetic_complete_rows()
    rows[0]["supplier_terminal"] = "PRI_A"
    result = m.evaluate(rows)
    assert any("logical pin label is NOT a vendor" in p for p in result["errors"])


def test_duplicate_logical_pin_or_missing_row_rejected():
    rows = synthetic_complete_rows()
    rows.append(copy.deepcopy(rows[0]))
    assert m.evaluate(rows)["status"] == "CONTRACT_REJECTED"
    assert any("duplicate logical pin" in e for e in m.evaluate(rows)["errors"])
    rows = synthetic_complete_rows()[1:]
    assert m.evaluate(rows)["status"] == "CONTRACT_REJECTED"
    assert any("missing logical terminal" in e for e in m.evaluate(rows)["errors"])


def test_golden_net_and_frozen_center_tap_dot_never_silently_change():
    rows = synthetic_complete_rows()
    rows[5]["golden_net"] = "WRONG_NET"
    assert any("frozen golden_net" in e for e in m.evaluate(rows)["errors"])
    rows = synthetic_complete_rows()
    ctap = next(row for row in rows if row["ref"] == "T1" and row["logical_pin"] == "CTAP")
    ctap["supplier_dot"] = "DOT"
    assert any("CTAP requires splice" in e for e in m.evaluate(rows)["errors"])
    rows = synthetic_complete_rows()
    t1sa = next(row for row in rows if row["ref"] == "T1" and row["logical_pin"] == "SEC_A")
    t1sa["supplier_dot"] = "DOT"
    assert any("supplier DOT conflicts" in e for e in m.evaluate(rows)["errors"])


def test_ct_dot_pair_cannot_have_both_dots_or_no_dots():
    rows = synthetic_complete_rows()
    for row in rows:
        if row["ref"] == "CT" and row["logical_pin"] == "PRI_B":
            row["supplier_dot"] = "DOT"
    assert any("CT primary" in e for e in m.evaluate(rows)["errors"])
    rows = synthetic_complete_rows()
    for row in rows:
        if row["ref"] == "CT" and row["logical_pin"] == "SEC_A":
            row["supplier_dot"] = "NON_DOT"
    assert any("CT secondary" in e for e in m.evaluate(rows)["errors"])


def test_pad_coordinates_duplicate_and_nonfinite_rejected():
    rows = synthetic_complete_rows()
    rows[1]["pad_xy_mm"] = rows[0]["pad_xy_mm"]
    assert any("share the same physical xy" in e for e in m.evaluate(rows)["errors"])
    rows = synthetic_complete_rows()
    rows[0]["pad_xy_mm"] = "NaN,4"
    assert any("must be finite" in e for e in m.evaluate(rows)["errors"])


def test_placeholder_footprint_and_phase_mismatch_are_not_completeness():
    rows = synthetic_complete_rows()
    contract = m.contract_entries()
    rows[0]["mechanical_footprint_ref"] = contract[("CT","PRI_A")]["placeholder_footprint"]
    assert any("placeholder footprint" in e for e in m.evaluate(rows)["errors"])
    rows = synthetic_complete_rows()
    rows[0]["measured_phase"] = "MISMATCH"
    assert any("phase is not MATCH" in e for e in m.evaluate(rows)["errors"])


def test_missing_evidence_or_malformed_sha_cannot_pass():
    rows = synthetic_complete_rows()
    rows[0]["phase_test_record"] = "PENDING"
    assert m.evaluate(rows)["status"] == "INCOMPLETE_VENDOR_PACKET"
    rows = synthetic_complete_rows()
    rows[0]["drawing_sha256"] = "notasha"
    assert any("drawing_sha256" in e for e in m.evaluate(rows)["errors"])


def test_provided_template_never_overwritten(tmp_path):
    out = tmp_path / "response.csv"
    m.write_template(out)
    assert m.load_rows(out) == m.blank_rows()
    with pytest.raises(FileExistsError):
        m.write_template(out)


def test_invalid_schema_and_legacy_nine_row_response_not_accepted(tmp_path):
    invalid = tmp_path / "old.csv"
    invalid.write_text("ref,logical_pin\nCT,PRI_A\n", encoding="utf-8")
    with pytest.raises(ValueError,match="unexpected response columns"):
        m.load_rows(invalid)


@pytest.mark.parametrize("field,value", [
    ("mechanical_footprint_ref", "OTHER_TEST_FOOTPRINT"),
    ("manufacturer_drawing", "OTHER_TEST_DRAWING"),
    ("drawing_rev", "OTHER_TEST_REV"),
    ("drawing_sha256", "c" * 64),
    ("phase_test_record", "OTHER_TEST_PHASE_RECORD"),
    ("phase_test_sha256", "d" * 64),
])
def test_terminals_of_one_part_must_cite_one_identity(field, value):
    rows = synthetic_complete_rows()
    assert rows[0]["ref"] == rows[1]["ref"] == "CT"
    rows[1][field] = value
    result = m.evaluate(rows)
    assert result["status"] == "CONTRACT_REJECTED"
    assert any(f"CT: terminals disagree on {field}" in p for p in result["errors"])


def test_sha256_case_only_difference_is_not_an_identity_conflict():
    rows = synthetic_complete_rows()
    rows[1]["drawing_sha256"] = rows[1]["drawing_sha256"].upper()
    result = m.evaluate(rows)
    assert result["status"] == "REVIEW_PACKAGE_COMPLETE_NOT_APPROVED"
    assert not any("terminals disagree" in p for p in result["errors"])


def test_a_duplicated_contract_terminal_is_refused_instead_of_collapsing():
    pin = {"logical_pin": "PRI_A", "golden_net": "PRI_A", "polarity": "DOT"}
    contract = {"symbols": [{"ref": "T1", "placeholder_footprint": "F",
                             "pins": [pin, dict(pin)]}]}
    with pytest.raises(ValueError, match="duplicate logical terminal"):
        m.contract_entries(contract)


def test_the_report_names_the_contract_bytes_it_was_judged_against():
    fingerprint = m.contract_fingerprint()
    assert fingerprint["sha256"] == hashlib.sha256(m.CONTRACT.read_bytes()).hexdigest()
    assert fingerprint["logical_terminal_count"] == 24
    assert fingerprint["symbols"] == 5
    assert fingerprint["path"].endswith("magnetics_symbol_contract.json")


def test_editing_the_contract_changes_the_fingerprint(tmp_path):
    contract = json.loads(m.CONTRACT.read_text(encoding="utf-8"))
    contract["symbols"][0]["pins"][0]["golden_net"] = "EDITED_FOR_TEST"
    edited = tmp_path / "contract.json"
    edited.write_text(json.dumps(contract), encoding="utf-8")
    assert m.contract_fingerprint(edited)["sha256"] != m.contract_fingerprint()["sha256"]


def test_main_writes_both_the_input_and_contract_hashes(tmp_path):
    response = tmp_path / "reply.csv"
    with response.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=m.FIELDS)
        writer.writeheader()
        writer.writerows(synthetic_complete_rows())
    out = tmp_path / "audit.json"
    assert m.main(["--input", str(response), "--output", str(out)]) == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["input_sha256"] == hashlib.sha256(response.read_bytes()).hexdigest()
    assert doc["contract"]["sha256"] == hashlib.sha256(m.CONTRACT.read_bytes()).hexdigest()


def test_a_contract_that_drifted_from_its_sources_is_refused():
    # contract_entries() treats the JSON as frozen truth, so an edited golden
    # net would otherwise make a wrong vendor map look model-correct.
    drifted = json.loads(m.CONTRACT.read_text(encoding="utf-8"))
    drifted["symbols"][0]["pins"][0]["golden_net"] = "EDITED_FOR_TEST"
    with pytest.raises(ValueError, match="no longer matches"):
        m.verify_contract_sources(drifted)


def test_filling_in_physical_pads_is_not_contract_drift():
    contract = copy.deepcopy(m.cad_contract.build())
    for symbol in contract["symbols"]:
        symbol["physical_pad_map_verified"] = True
        symbol["native_symbol_present"] = True
        for pin in symbol["pins"]:
            pin["physical_pad"] = "PAD_FROM_VENDOR"
    assert m.verify_contract_sources(contract) is None


def test_main_rejects_a_drifted_contract_as_invalid_packet(tmp_path, monkeypatch):
    drifted = json.loads(m.CONTRACT.read_text(encoding="utf-8"))
    drifted["symbols"][0]["pins"][0]["golden_net"] = "EDITED_FOR_TEST"
    bad = tmp_path / "contract.json"
    bad.write_text(json.dumps(drifted), encoding="utf-8")
    monkeypatch.setattr(m, "CONTRACT", bad)
    response = tmp_path / "reply.csv"
    with response.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=m.FIELDS)
        writer.writeheader()
        writer.writerows(synthetic_complete_rows())
    out = tmp_path / "audit.json"
    assert m.main(["--input", str(response), "--output", str(out)]) == 2
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["status"] == "INVALID_PACKET"
    assert any("no longer matches" in error for error in doc["errors"])
    assert doc["contract"]["sha256"] == hashlib.sha256(bad.read_bytes()).hexdigest()


def test_main_records_the_sources_the_contract_was_rebuilt_from(tmp_path):
    response = tmp_path / "reply.csv"
    with response.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=m.FIELDS)
        writer.writeheader()
        writer.writerows(synthetic_complete_rows())
    out = tmp_path / "audit.json"
    assert m.main(["--input", str(response), "--output", str(out)]) == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    paths = {item["path"]: item["sha256"] for item in doc["contract_sources"]}
    assert paths["design/v3/pcb/board_netlist.csv"]
    assert paths["design/v3/magnetics/winding_polarity.json"]
    assert all(len(value) == 64 for value in paths.values())
