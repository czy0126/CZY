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
    assert source.count('(pin power_out line (at 30.04 9 180)') == 1
    assert source.count('(pin passive line (at 30.04 3 180)') == 1
    assert source.count('(pin power_out line (at 30.04 3 180)') == 0
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
