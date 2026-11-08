"""Native ERC repair invariants for the two physical pin-type conditions.

These checks inspect the exact editable schematic, not simulated or signed
hardware. Only original KiCad 10 ERC can establish zero electrical violations.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
SCH = ROOT / "hardware/sr_bias_efuse_proposal/native/tps26630_sr_bias_concept.kicad_sch"


def test_paralleled_out_contacts_use_one_power_driver_and_one_passive_pin():
    source = SCH.read_text(encoding="utf-8")
    # Actual KiCad 10 symbol-grid coordinates from the OEM-mapped U1 symbol.
    # Check pin types on distinct physical OUT pins, not a stale draft grid.
    assert source.count('(pin power_out line (at 30.48 8.89 180)') == 1
    assert source.count('(pin passive line (at 30.48 2.54 180)') == 1
    assert source.count('(pin power_out line (at 30.48 2.54 180)') == 0
    # Two manufacturer OUT pins still physically appear and share VDD_SR.
    assert '(number "17"' in source and '(number "18"' in source
    assert source.count('(label "VDD_SR" (at 135.04 ') == 2


def test_external_fet_feeds_efuse_in_with_explicit_erc_source_annotation():
    source = SCH.read_text(encoding="utf-8")
    assert '(property "Reference" "#FLG_EFUSE"' in source
    assert '(label "EFUSE_IN" (at 60.96 330.2 0)' in source
    assert '(symbol (lib_id "power:PWR_FLAG") (at 60.96 330.2 0)' in source
    # PWR_FLAG is an ERC declaration, not a short or new hardware device.
    assert '(in_bom no) (on_board no)' in source
    assert source.count('(label "EFUSE_IN"') == 7


def test_power_gate_does_not_authorize_manufacture():
    source = SCH.read_text(encoding="utf-8")
    assert 'NOT_FOR_FAB' in source
    assert '(property "Footprint" ""' in source
    assert 'U1 symbol EP model pin 25 is a conceptual pad alias' in source

def test_custom_project_library_is_not_missing_in_native_erc():
    folder = SCH.parent
    table = (folder / "sym-lib-table").read_text(encoding="utf-8")
    library = (folder / "SR_Bias.kicad_sym").read_text(encoding="utf-8")
    assert '(name "SR_Bias")' in table
    assert "SR_Bias.kicad_sym" in table
    assert library.startswith("(kicad_symbol_lib")
    assert library.count('(symbol "BSS138"') == 1
    assert library.count('(symbol "CSD19537Q3"') == 1
    assert library.count('(symbol "TPS26630_RGE24"') == 1
    assert "NOT_FOR_FAB" in table
