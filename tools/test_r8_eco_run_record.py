"""Lock the R8 ECO real-run record (2026-11-06) to the story it tells.

The record is a measurement of one real run against copies of the native board.
It is not a generator output, so nothing regenerates it -- which means nothing
would notice if a number in it drifted.  These tests assert the properties that
made the run meaningful:

  * the native file never moved (all mutation landed on copies),
  * phase 1 verified the pin map and *could not* save (the document was poisoned
    by the five injected footprints), and left its copy byte-identical,
  * phase 2 applied the exclusion in a clean session, gated on the phase-1
    attestation, and the saved copy grew,
  * the exclusion survives a reopen and is idempotent,
  * exporting from the saved copy itself (the delivered file, not the session
    that wrote it) shows exactly one excluded part, renumbered R8 -> R6, with
    the same pins, and R7 untouched.

Anything about fabrication approval is checked as absent on purpose.
"""
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / "hardware/dcx_main/gen/r8_eco_run_2026-11-06.json"
ECO = ROOT / "hardware/dcx_main/gen/eco_r8_bom_pcb_inhibit.js"

FINGERPRINT = re.compile(r"^fnv1a32:[0-9a-f]{8}:n\d+$")


@pytest.fixture(scope="module")
def record() -> dict:
    return json.loads(RECORD.read_text(encoding="utf-8"))


def test_the_native_project_never_moved(record):
    real = record["real_project"]
    assert real["unchanged"] is True
    assert real["before"] == real["after"]
    assert real["before"]["size"] > 0 and len(real["before"]["sha256"]) == 64


def test_phase_one_verified_the_pins_without_saving(record):
    phase = record["phase_1_verify"]
    assert phase["status"] == "PIN_MAP_VERIFIED_NO_SAVE"
    assert phase["applied"] is False
    assert phase["copy_unchanged"] is True
    assert phase["copy_before"] == phase["copy_after"]
    assert phase["attestation"]["parts"] == phase["netlist_components"] == 83
    assert FINGERPRINT.match(phase["attestation"]["inventory_fingerprint"])
    pins = phase["attestation"]["pins"]
    assert pins["pullup"]["pads"] == phase["expected_pads"] == {"1": "VCC12", "2": "RUN"}
    assert pins["R7"] == {"1": "RUN", "2": "PGND"}
    assert pins["U2.6"] == "RUN"


def test_phase_two_applied_exactly_the_two_assembly_flags(record):
    phase = record["phase_2_apply"]
    assert phase["status"] == "R8_ASSEMBLY_EXCLUSION_SAVED_NOT_VERIFIED"
    assert phase["applied"] is True
    assert phase["before"] == {"addIntoBom": True, "addIntoPcb": True}
    assert phase["after"] == {"addIntoBom": False, "addIntoPcb": False}
    assert phase["size_growth_bytes"] == (phase["copy_after"]["size"]
                                          - phase["copy_before"]["size"]) > 0
    assert phase["copy_before"]["sha256"] != phase["copy_after"]["sha256"]


def test_the_apply_was_gated_on_the_other_sessions_attestation(record):
    first, second = record["phase_1_verify"], record["phase_2_apply"]
    assert second["attestation_fingerprint"] == first["attestation"]["inventory_fingerprint"]
    assert second["pins_verified_in_a_different_session"] is True
    # The clean session cannot re-run the export, so it cannot re-verify here.
    assert second["pins_reverifiable_here"] is False


def test_the_exclusion_survives_a_reopen_and_is_idempotent(record):
    phase = record["phase_3_reopen"]
    assert phase["status"] == "ALREADY_DNP"
    assert phase["applied"] is False
    assert phase["before"] == {"addIntoBom": False, "addIntoPcb": False}
    assert phase["primitive_id_stable"] is True
    assert phase["primitive_id"] == record["phase_2_apply"]["primitive_id"]


def test_the_delivered_file_shows_one_exclusion_with_the_same_pins(record):
    back = record["readback_export"]
    applied = record["phase_2_apply"]["copy_after"]
    assert back["copy"]["sha256"] == applied["sha256"]
    assert back["copy"]["size"] == applied["size"]
    assert back["components"] == 83
    assert back["excluded_count"] == 1
    row = back["excluded_row"]
    assert row["bom"] == "no" and row["pcb"] == "no"
    # Excluding a part renames it during the export; the pins stay put.  Do not
    # read the R8 -> R6 rename as a second defect.
    assert back["renumbered_from"] == "R8"
    assert row["designator"] == back["renumbered_to"] == "R6"
    assert back["pins_unchanged_by_renumbering"] is True
    assert row["pads"] == record["phase_1_verify"]["expected_pads"]
    neighbour = back["neighbour_untouched"]
    assert neighbour["designator"] == "R7"
    assert (neighbour["bom"], neighbour["pcb"]) == ("yes", "yes")


def test_nothing_in_the_record_claims_an_approval(record):
    text = json.dumps(record)
    assert "fabrication_approved" not in text
    assert "hardware_built" not in text
    for key in ("phase_1_verify", "phase_2_apply"):
        assert record[key]["release"] == "NOT_FOR_FAB"


def test_the_eco_source_still_says_what_the_record_says(record):
    source = ECO.read_text(encoding="utf-8")
    for status in (record["phase_1_verify"]["status"],
                   record["phase_2_apply"]["status"],
                   record["phase_3_reopen"]["status"]):
        assert status in source, f"{status} is no longer produced by the ECO"
    # The phase is a declared flag, not an inference from the export: an injected
    # session also shows footprints on CT/T1-T4, so "the export worked" does not
    # prove "this session was injected".
    for flag in ("CZY_APPLY_R8_DNP", "CZY_R8_VERIFY_ONLY", "CZY_R8_PIN_MAP_VERIFIED"):
        assert "globalThis." + flag in source
    # The body is wrapped: a bare `let` would leak into the render's global scope
    # and collide with the next invoke in the same session.
    assert "return await (async () => {" in source
    assert record["phase_2_apply"]["session"]["stored_uuid"] in source
