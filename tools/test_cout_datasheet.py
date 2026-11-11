"""The Cout part data must point at the archived manufacturer documents.

`cout_bank.py` used to carry a vendor-page summary and say so.  The selected
part now has a part-specific YAGEO spec sheet and a KEMET T2078 series excerpt
in ``references/datasheets``.  These tests keep the numbers and the archive
from drifting apart: remove or edit a document and the sizing must fail instead
of silently keeping unverified literals.
"""
from __future__ import annotations

import hashlib
import json

import pytest

from cout_bank import CANDIDATES, DATASHEET_TEXT, REPO, SERIES_TEXT, TEXT_ENCODING, spec_facts

PROVENANCE = REPO / "references/datasheets/a720v477m2r5ape003.provenance.json"
BRIEF_TEXT = REPO / "references/datasheets/yageo_pb_a720_a798_revA.txt"


def test_every_archived_document_hashes_to_its_provenance_record():
    record = json.loads(PROVENANCE.read_text(encoding="utf-8"))
    assert record["part"] == "A720V477M2R5APE003"
    paths = []
    for document in record["documents"]:
        for kind in ("pdf", "text"):
            if kind not in document:
                continue
            path = REPO / document[kind]
            assert path.is_file(), path
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            assert digest == document[f"{kind}_sha256"], path
            paths.append(path)
    assert DATASHEET_TEXT in paths
    assert SERIES_TEXT in paths
    assert BRIEF_TEXT in paths


def test_spec_sheet_values_are_the_ones_the_bank_must_use():
    facts = spec_facts()
    assert facts["case"] == "V/7343-21"
    assert facts["c_f"] == pytest.approx(470e-6, rel=1e-12)
    assert facts["v_rated"] == pytest.approx(2.5, rel=1e-12)
    assert facts["esr_ohm"] == pytest.approx(3e-3, rel=1e-12)
    assert facts["irms_a"] == pytest.approx(11.69, rel=1e-12)
    assert facts["height_max_mm"] == pytest.approx(2.1, rel=1e-12)
    assert facts["length_mm"] == pytest.approx(7.3, rel=1e-12)
    assert facts["width_mm"] == pytest.approx(4.3, rel=1e-12)
    assert facts["lead_pitch_mm"] == pytest.approx(2.4, rel=1e-12)
    assert facts["leakage_ua"] == pytest.approx(70.5, rel=1e-12)
    assert facts["df_pct"] == pytest.approx(6.0, rel=1e-12)
    assert facts["life_h"] == 2000
    assert facts["rated_temp_c"] == 105


def test_the_series_row_keeps_the_ripple_at_100_khz_and_a_20_c_rise():
    facts = spec_facts()
    assert facts["ripple_frequency_khz"] == 100
    assert facts["ripple_delta_t_c"] == 20
    series = SERIES_TEXT.read_text(encoding=TEXT_ENCODING)
    assert ("2.5 470 V/7343-21 A720V477M2R5APE003 70.5 6 3 11,690 3 105"
            in series)


def test_the_selected_candidate_carries_the_datasheet_values_and_source():
    part = next(p for p in CANDIDATES if p["mpn"] == "KEMET A720V477M2R5APE003")
    facts = spec_facts()
    assert part["verified"] is True
    assert part["c_f"] == facts["c_f"]
    assert part["v_rated"] == facts["v_rated"]
    assert part["esr_ohm"] == facts["esr_ohm"]
    assert part["irms_a"] == facts["irms_a"]
    assert part["height_mm"] == facts["height_max_mm"]
    assert part["case"] == facts["case"]
    assert "yageogroup.com/download/specsheet/A720V477M2R5APE003" in part["source"]


def test_the_alternates_are_still_marked_unverified():
    for part in CANDIDATES:
        if part["mpn"] == "KEMET A720V477M2R5APE003":
            continue
        assert part["verified"] is False, part["mpn"]
        assert part["source"].startswith("network search summary"), part["mpn"]


def test_the_product_brief_records_no_voltage_derating_for_a720():
    brief = BRIEF_TEXT.read_text(encoding=TEXT_ENCODING)
    assert "No voltage derating" in brief


def test_a_truncated_or_empty_spec_sheet_is_refused(tmp_path):
    empty = tmp_path / "empty.txt"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="Capacitance"):
        spec_facts(empty)
    partial = tmp_path / "partial.txt"
    partial.write_text("Capacitance 470 uF\nVoltage DC 2.5 VDC\n", encoding="utf-8")
    with pytest.raises(ValueError, match="ESR"):
        spec_facts(partial)
