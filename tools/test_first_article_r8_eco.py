"""Rehearse the native EasyEDA R8 assembly-inhibit ECO with mocked EDA APIs.

Tests the ACTUAL JavaScript callback. It cannot certify an EasyEDA project that
has not been opened, edited and independently exported on the real GUI.

**The ECO is two-phase by necessity, not by taste.**  This build makes the pin
guard and the save mutually exclusive in one session:

  * ``getNetlistFile`` returns undefined while any placed part has an empty
    footprint, and this project has five (CT, T1-T4);
  * injecting those five footprints in memory unblocks the export but poisons
    the document, so every later ``save()`` returns false.

Measured both ways on a copy of the real project on 2026-11-06.  So:

  phase 1 (VERIFY)   -- injected session: export, check pins, return
                        ``PIN_MAP_VERIFIED_NO_SAVE`` + ``attestation``, never
                        mutate (saving there is impossible anyway).
  phase 2 (APPLY)    -- clean session: the export is blocked, so require the
                        attestation and check it against *this* session's live
                        inventory before modifying and saving.

The tests below lock both halves, including the two ways the phases can be
confused: mutating in a session that can export, and applying without an
attestation that belongs to this board.

The netlist side is mocked from ``gen/netlist_export_capture_2026-11-06.json``,
a trimmed capture of a live export, rather than from a hand-written shape.  The
first version of this file invented ``{components: {R8: …}, nets: {RUN: {}}}``
and thereby hid two defects in the ECO that the real export exposed:

  * the real export has **no** top-level ``nets`` map (connectivity lives in
    ``components[*].pinInfoMap[pin].net``), so ``!netlist.nets`` refused every
    real export;
  * excluding a part **renumbers it during the export** (R8 -> R6, same pins),
    so a second run that filtered the netlist on ``Designator === 'R8'``
    reported "pin map drift" for its own previous edit.  The mock flips the
    live designator when the export happens, which is what the measurement
    showed, so a regression that re-looks-up by designator after exporting
    fails here instead of on the bench.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ECO = ROOT / "hardware/dcx_main/gen/eco_r8_bom_pcb_inhibit.js"
NATIVE_EXPORT = ROOT / "hardware/dcx_main/gen/netlist_export_raw.json"
CAPTURE = ROOT / "hardware/dcx_main/gen/netlist_export_capture_2026-11-06.json"

PROJECT_NAME = "dcx_main_board"
# What native_inventory_raw.json actually saw, opened by --path.
SESSION_UUID = "0054c1e0f493b9ebf3517da33827a1985e43c2e9a23f621e11cf5b82f136a085"
STORED_UUID = "14837d107b6a52feb21f43869dd7378616b33db49e6c75ae2ea6bc0a53989e46"
# The three components the ECO reads, by the exporter-assigned Unique ID.
R8_UID, R7_UID, U2_UID = "gge67", "gge66", "gge62"
BLANKS = ["CT", "T1", "T2", "T3", "T4"]

pytestmark = pytest.mark.skipif(shutil.which("node") is None,
                                reason="Node.js not present for native ECO mock")


def _capture() -> dict:
    return json.loads(CAPTURE.read_text(encoding="utf-8"))


def _netlist(excluded: bool = False, drift: str | None = None,
             flags: tuple[str, str] = ("yes", "yes")) -> dict:
    """The captured export, optionally as it looks after R8 was excluded.

    ``drift`` corrupts one known pin so the guard has something to catch;
    ``flags`` is what the export prints for the EN pull-up's BOM / PCB columns.
    """
    net = _capture()
    if excluded:
        # Measured: the excluded part is renumbered to R6 in the export.
        net["components"][R8_UID]["props"]["Designator"] = "R6"
    net["components"][R8_UID]["props"]["Add into BOM"] = flags[0]
    net["components"][R8_UID]["props"]["Convert to PCB"] = flags[1]
    if drift == "pullup":
        net["components"][R8_UID]["pinInfoMap"]["2"]["net"] = "PGND"
    elif drift == "neighbour":
        net["components"][R7_UID]["pinInfoMap"]["2"]["net"] = "VCC12"
    elif drift == "u2":
        net["components"][U2_UID]["pinInfoMap"]["6"]["net"] = "PGND"
    return net


def _mock_js(mode: str, name: str = PROJECT_NAME, uuid: str = SESSION_UUID,
             netlist: dict | None = None, netlist_available: bool | None = None,
             bom: bool = True, pcb: bool = True, injected: bool = False,
             footprints: bool = False, verify_only: bool = False,
             attest: dict | None = None) -> str:
    """Build the Node harness around the real ECO source.

    ``injected`` reproduces the ``--netlist-ready`` session: the five magnetic
    parts carry footprints (so the export works) but the document can no longer
    be saved.  ``footprints`` is the world after the vendor drawings arrive: the
    parts have real footprints *and* the document saves normally.  From the live
    objects the two are indistinguishable -- which is exactly why the ECO takes
    its phase from a flag instead of guessing.  ``attest`` is passed in exactly
    as an operator would pass it on the command line.
    """
    code = ECO.read_text(encoding="utf-8")
    net = json.dumps(netlist if netlist is not None else _netlist(), ensure_ascii=True)
    attest_literal = "null" if attest is None else json.dumps(attest, ensure_ascii=True)
    has_footprints = injected or footprints
    if netlist_available is None:
        # Measured: getNetlistFile refuses exactly while some part is blank.
        netlist_available = has_footprints
    return f"""
// The real operator prefix sets these on globalThis: a top-level const in one
// invoke persists in the render's global scope and collides with the next one.
globalThis.CZY_APPLY_R8_DNP = {str(mode == 'apply').lower()};
globalThis.CZY_R8_VERIFY_ONLY = {str(verify_only).lower()};
globalThis.CZY_R8_PIN_MAP_VERIFIED = {attest_literal};
const state = {{bom:{str(bom).lower()}, pcb:{str(pcb).lower()}, modify:0, save:0,
                getAll:0, get:[], exported:false}};
const comp = {{
 getState_Designator:()=> state.exported ? 'R6' : 'R8',
 getState_PrimitiveId:()=> 'R8-uuid',
 getState_AddIntoBom:()=> state.bom,
 getState_AddIntoPcb:()=> state.pcb,
 getState_Footprint:()=> ({{uuid:'54d0eff80ecd1bb3'}})
}};
const blank = {json.dumps(BLANKS)}.map((ref, i) => ({{
 getState_Designator:()=> ref,
 getState_PrimitiveId:()=> 'blank-'+ref,
 getState_Footprint:()=> ({{uuid: {'true' if has_footprints else 'false'} ? 'fp-'+i : ''}})
}}));
const NET_TEXT = {json.dumps(net)};
global.eda = {{
 dmt_Project: {{getCurrentProjectInfo:async()=>({{friendlyName:'{name}',uuid:'{uuid}',data:[{{
 schematic:{{page:[{{uuid:'one-schematic'}}]}}
 }}]}})}},
 dmt_EditorControl: {{openDocument:async()=>true}},
 sch_ManufactureData: {{getNetlistFile:async()=>{{
   if ({str(not netlist_available).lower()}) return undefined;
   state.exported = true;
   return {{text:async()=>NET_TEXT}};
 }}}},
 sch_PrimitiveComponent: {{
 getAll:async()=>{{state.getAll++; return [comp, ...blank];}},
 get:async(id)=>{{state.get.push(id); return comp;}},
 modify:async(id,values)=>{{state.modify++;state.bom=values.addIntoBom;
                            state.pcb=values.addIntoPcb;return comp;}}
 }},
 // An injected document cannot be saved; that is measurement 5 itself.
 sch_Document: {{save:async()=>{{state.save++;return {str(not injected).lower()};}}}}
}};
(async()=> {{
{code}
}})().then(result=>process.stdout.write(JSON.stringify({{result, state}})))
    .catch(error=>{{process.stderr.write(String(error));process.exit(2);}});
"""


def _run(tmp_path: Path, mode: str = "dry", **kwargs) -> dict:
    script = tmp_path / "test_r8_eco.js"
    script.write_text(_mock_js(mode, **kwargs), encoding="utf-8")
    process = subprocess.run(["node", str(script)], text=True, capture_output=True,
                             timeout=20, check=False)
    assert process.returncode == 0, process.stderr
    return json.loads(process.stdout)


def _verify(tmp_path: Path, **kwargs) -> dict:
    """Phase 1 against an injected session -- the only place pins can be read."""
    return _run(tmp_path, mode="dry", verify_only=True, injected=True, **kwargs)


# --------------------------------------------------------------------------
# The real shapes. These read committed files, not this test's own mock.
# --------------------------------------------------------------------------

def test_evolving_native_pin_map_is_exactly_the_known_stopline():
    data = json.loads(NATIVE_EXPORT.read_text(encoding="utf-8"))["value"]["refs"]
    assert data["U2"]["6"] == "RUN"
    assert data["R7"] == {"1": "RUN", "2": "PGND"}
    assert data["R8"] == {"1": "VCC12", "2": "RUN"}


def test_the_real_export_has_no_top_level_nets_map():
    """The defect the old mock hid: requiring `nets` refused every real export."""
    capture = _capture()
    assert "nets" not in capture
    assert capture["provenance"]["captured_top_level_keys"] == [
        "version", "projectId", "components", "designRule", "differentialPair",
        "netClass", "equalLengthNetGroup", "differentialPairGroups"]
    assert capture["provenance"]["captured_components"] == 83
    for component in capture["components"].values():
        assert "pinInfoMap" in component and "props" in component
        # connectivity is on the pin, not in a separate map
        assert all("net" in pin for pin in component["pinInfoMap"].values())


def test_the_en_pullup_is_the_only_vcc12_to_run_two_pin_part():
    """Why pin-signature identification is unambiguous in the real data."""
    capture = _capture()
    matches = []
    for uid, component in capture["components"].items():
        pads = {p: pin["net"] for p, pin in component["pinInfoMap"].items()}
        if len(pads) == 2 and pads.get("1") == "VCC12" and pads.get("2") == "RUN":
            matches.append((uid, component["props"]["Designator"]))
    assert matches == [(R8_UID, "R8")]
    # U2 has the same two nets but on eleven pins, and pin 2 is unconnected --
    # a pin-count-insensitive test would have matched it too.
    u2 = capture["components"][U2_UID]["pinInfoMap"]
    assert len(u2) == 11 and u2["2"]["net"] == ""


def test_the_inventory_uuid_is_not_the_uuid_the_eprj2_stores():
    """The premise of the gate change, asserted rather than remembered."""
    inventory = json.loads(
        (ROOT / "hardware/dcx_main/gen/native_inventory_raw.json").read_text(encoding="utf-8"))
    value = inventory["value"]
    assert value["opened_by"] == "path"
    assert value["project_name"] == PROJECT_NAME
    assert value["project_uuid"] != value["stored_project_uuid"]


# --------------------------------------------------------------------------
# Phase 1: verify in an injected session, never mutate.
# --------------------------------------------------------------------------

def test_an_injected_session_verifies_the_pins_and_says_it_cannot_save(tmp_path: Path):
    """The core of the two-phase contract.

    The session that can export is the session that must not be edited, so the
    only correct output here is a report -- with the fresh pin map and a
    fingerprint an APPLY run can be held to.
    """
    outcome = _verify(tmp_path)
    result = outcome["result"]
    assert result["status"] == "PIN_MAP_VERIFIED_NO_SAVE"
    assert result["applied"] is False
    assert outcome["state"]["modify"] == 0
    assert outcome["state"]["save"] == 0
    assert result["attestation"]["pins"]["pullup"]["pads"] == {"1": "VCC12", "2": "RUN"}
    assert result["attestation"]["r8_designator"] == "R8"
    assert result["attestation"]["parts"] == 1 + len(BLANKS)
    assert result["attestation"]["inventory_fingerprint"].startswith("fnv1a32:")
    assert "CZY_R8_PIN_MAP_VERIFIED" in result["next"]


def test_apply_in_a_poisoned_session_fails_closed_at_the_save(tmp_path: Path):
    """Even with the opt-in flag and a valid attestation, an injected session
    cannot persist anything: ``save()`` returns false by construction.  The run
    must report that refusal rather than an applied edit that never happened."""
    verified = _verify(tmp_path)["result"]["attestation"]
    outcome = _run(tmp_path, mode="apply", injected=True, attest=verified)
    result = outcome["result"]
    assert result["status"] == "REFUSED"
    assert "save failed" in result["reason"]
    assert "CZY_R8_VERIFY_ONLY" in result["hint"]
    assert result["applied"] is False
    assert outcome["state"]["save"] == 1


def test_a_drifted_en_pullup_pin_map_fails_before_any_mutation(tmp_path: Path):
    outcome = _verify(tmp_path, netlist=_netlist(drift="pullup"))
    assert outcome["result"]["status"] == "REFUSED"
    assert "VCC12/RUN two-pin part, found 0" in outcome["result"]["reason"]
    assert outcome["state"]["modify"] == 0
    assert outcome["state"]["save"] == 0


def test_a_drifted_neighbour_pin_map_fails_before_any_mutation(tmp_path: Path):
    """R7 and U2 keep their designators, so they are still checked by name."""
    for drift, pin in (("neighbour", "R7.2"), ("u2", "U2.6")):
        outcome = _verify(tmp_path, netlist=_netlist(drift=drift))
        assert outcome["result"]["status"] == "REFUSED"
        assert outcome["result"]["reason"].startswith("Pre-ECO native pin map drift:")
        assert pin in outcome["result"]["reason"]
        assert outcome["state"]["modify"] == 0
        assert outcome["state"]["save"] == 0


def test_live_state_and_the_export_disagreeing_is_not_guessed(tmp_path: Path):
    """Live says populated, the export says excluded: refuse rather than pick one.

    This is also the renumbering guard: an exported R6 while live still reads
    R8 means a save is pending or the schematic moved -- never a pin drift.
    """
    for netlist in (_netlist(flags=("no", "no")), _netlist(excluded=True, flags=("no", "no"))):
        outcome = _verify(tmp_path, netlist=netlist)
        assert outcome["result"]["status"] == "REFUSED"
        assert "disagree" in outcome["result"]["reason"]
        assert outcome["result"]["netlist_addIntoBom"] == "no"
        assert outcome["state"]["modify"] == 0
        assert outcome["state"]["save"] == 0


# --------------------------------------------------------------------------
# Phase 2: apply in a clean session, gated on the attestation.
# --------------------------------------------------------------------------

def test_a_clean_session_cannot_verify_so_it_refuses_and_names_the_blockers(tmp_path: Path):
    """getNetlistFile returns undefined while any placed part has no footprint.

    A bare "cannot export" told the operator nothing; the five magnetic parts
    are enumerable live, so the refusal must list them and the two-phase remedy.
    """
    outcome = _run(tmp_path)
    result = outcome["result"]
    assert result["status"] == "REFUSED"
    assert result["blocking_parts"] == BLANKS
    assert result["blocking_parts_count"] == 5
    assert "getNetlistFile() returns undefined" in result["why"]
    assert "--netlist-ready" in result["remedy"]
    assert "CZY_R8_PIN_MAP_VERIFIED" in result["remedy"]
    assert outcome["state"]["modify"] == 0
    assert outcome["state"]["save"] == 0


def test_applying_without_an_attestation_is_refused(tmp_path: Path):
    outcome = _run(tmp_path, mode="apply")
    result = outcome["result"]
    assert result["status"] == "REFUSED"
    assert "no pin-map attestation" in result["reason"]
    assert outcome["state"]["modify"] == 0
    assert outcome["state"]["save"] == 0


def test_an_attestation_from_a_different_inventory_is_refused(tmp_path: Path):
    """The fingerprint binds the attestation to a part count and numbering.

    Without it, an attestation carried over from another board (or from this
    board before a rescope) would authorise the edit with pins nobody checked.
    """
    verified = _verify(tmp_path)["result"]["attestation"]
    for field, value, needle in (
        ("parts", verified["parts"] + 1, "different live inventory"),
        ("inventory_fingerprint", "fnv1a32:deadbeef:n9", "different live inventory"),
        ("r8_designator", "R9", "different designator"),
    ):
        tampered = dict(verified, **{field: value})
        outcome = _run(tmp_path, mode="apply", attest=tampered)
        assert outcome["result"]["status"] == "REFUSED"
        assert needle in outcome["result"]["reason"], (field, outcome["result"]["reason"])
        assert outcome["state"]["modify"] == 0
        assert outcome["state"]["save"] == 0


def test_a_verified_attestation_authorises_the_apply_and_says_where_pins_were_read(tmp_path: Path):
    """The end-to-end contract: verify in one session, apply in the next.

    The result must not claim the pins are verified *here* -- they were read in
    a different session, and the document being edited cannot export.
    """
    verified = _verify(tmp_path)["result"]["attestation"]
    outcome = _run(tmp_path, mode="apply", attest=verified)
    result = outcome["result"]
    assert result["status"] == "R8_ASSEMBLY_EXCLUSION_SAVED_NOT_VERIFIED"
    assert result["applied"] is True
    assert result["pins_verified_in_a_different_session"] is True
    assert result["pins_reverifiable_here"] is False
    assert result["pin_map_evidence"] == verified["pins"]
    assert result["attestation_fingerprint"] == verified["inventory_fingerprint"]
    assert outcome["state"]["modify"] == 1
    assert outcome["state"]["save"] == 1
    assert outcome["state"]["bom"] is False
    assert outcome["state"]["pcb"] is False
    assert result["release"] == "NOT_FOR_FAB"


# --------------------------------------------------------------------------
# Idempotency: a second run must not need the export at all.
# --------------------------------------------------------------------------

def test_an_already_excluded_part_is_reported_without_exporting(tmp_path: Path):
    """Idempotency is decided from the live flags, before the export.

    Deciding it from the export would make the no-op case unreachable on the
    real file, because the clean session cannot export.
    """
    for mode in ("dry", "apply"):
        outcome = _run(tmp_path, mode=mode, bom=False, pcb=False)
        result = outcome["result"]
        assert result["status"] == "ALREADY_DNP"
        assert result["applied"] is False
        assert outcome["state"]["exported"] is False
        assert outcome["state"]["modify"] == 0
        assert outcome["state"]["save"] == 0
        assert result["blocking_parts"] == BLANKS


# --------------------------------------------------------------------------
# The world after the vendor drawings arrive: one session does both.
# --------------------------------------------------------------------------

def test_when_no_part_is_blank_one_session_verifies_and_applies(tmp_path: Path):
    """Once T1-T4/CT have real footprints the two phases collapse into one.

    The code path must already be correct, or the day the drawings land the ECO
    will still refuse for a reason that no longer exists.
    """
    outcome = _run(tmp_path, mode="apply", footprints=True)
    result = outcome["result"]
    assert result["status"] == "R8_ASSEMBLY_EXCLUSION_SAVED_NOT_VERIFIED"
    assert result["pins_reverifiable_here"] is True
    assert result["pins_verified_in_a_different_session"] is False
    assert outcome["state"]["modify"] == 1
    assert outcome["state"]["save"] == 1


def test_a_dry_run_in_that_world_still_cannot_mutate(tmp_path: Path):
    outcome = _run(tmp_path, mode="dry", footprints=True)
    assert outcome["result"]["status"] == "DRY_RUN_SAFE"
    assert outcome["state"]["modify"] == 0
    assert outcome["state"]["save"] == 0
    assert outcome["result"]["proposed"] == {"addIntoBom": False, "addIntoPcb": False}


# --------------------------------------------------------------------------
# Identity routes.
# --------------------------------------------------------------------------

def test_a_fresh_session_uuid_is_the_same_project(tmp_path: Path):
    """Opening the same file again is not a different project.

    This is the case the old stored-uuid gate refused: same board, new session.
    """
    outcome = _run(tmp_path, mode="apply", uuid="f" * 64, footprints=True)
    assert outcome["result"]["status"] == "R8_ASSEMBLY_EXCLUSION_SAVED_NOT_VERIFIED"
    assert outcome["result"]["project"]["identified_by"] == "path_name"
    assert outcome["state"]["modify"] == 1


def test_a_library_opened_project_is_accepted_by_its_stored_uuid(tmp_path: Path):
    """Opened from the library the name differs, but the uuid is the stored one.

    Refusing here would block the other legitimate route, which is why the gate
    is a disjunction rather than a name-only check.
    """
    outcome = _run(tmp_path, mode="apply", name="DCX Main Board", uuid=STORED_UUID,
                   footprints=True)
    assert outcome["result"]["status"] == "R8_ASSEMBLY_EXCLUSION_SAVED_NOT_VERIFIED"
    assert outcome["result"]["project"]["identified_by"] == "studio_uuid"


def test_a_project_with_neither_identity_is_refused_before_any_mutation(tmp_path: Path):
    outcome = _run(tmp_path, mode="apply", name="some_other_board")
    assert outcome["result"]["status"] == "REFUSED"
    assert outcome["result"]["expected_path_opened_name"] == PROJECT_NAME
    assert outcome["result"]["actual_name"] == "some_other_board"
    assert outcome["result"]["project"]["identified_by"] is None
    # the hint must explain why a renamed rehearsal copy is refused
    assert "FILE STEM" in outcome["result"]["hint"]
    assert outcome["state"]["modify"] == 0
    assert outcome["state"]["save"] == 0


# --------------------------------------------------------------------------
# Addressed by primitive id, and the wording that keeps the scope honest.
# --------------------------------------------------------------------------

def test_the_part_is_addressed_by_primitive_id_not_by_designator(tmp_path: Path):
    """The export renames the live part; the ECO must not look it up again.

    Any re-lookup by designator after the export would find zero parts, so a
    green apply here is evidence of the capture-before-export ordering.
    """
    verified = _verify(tmp_path)
    assert verified["state"]["exported"] is True  # the export did rename it
    outcome = _run(tmp_path, mode="apply", attest=verified["result"]["attestation"])
    assert outcome["result"]["primitiveId"] == "R8-uuid"
    assert outcome["state"]["getAll"] == 1
    assert outcome["state"]["get"] == ["R8-uuid"]
    assert outcome["state"]["modify"] == 1


def test_explicit_opt_in_excludes_only_r8_assembly_and_does_not_approve_fab(tmp_path: Path):
    outcome = _run(tmp_path, mode="apply", footprints=True)
    assert outcome["state"]["bom"] is False
    assert outcome["state"]["pcb"] is False
    assert outcome["result"]["release"] == "NOT_FOR_FAB"
    # The old wording claimed R8 leaves the electrical netlist. It does not:
    # the schematic keeps the wire, only the assembly columns change.
    warning = outcome["result"]["warning"]
    assert "stays wired on the schematic" in warning
    assert "netlist" not in warning.split("stays wired on the schematic")[0].lower()
