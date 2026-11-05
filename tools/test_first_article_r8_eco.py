"""Rehearse the native EasyEDA R8 assembly-inhibit ECO with mocked EDA APIs.

Tests the ACTUAL JavaScript callback: default read-only, strict project and
physical pin map, and explicit opt-in. It cannot certify an EasyEDA project
that has not been opened, edited and independently exported on the real GUI.

Identity accepts two routes, the same pair the sibling scripts use: the uuid
stored inside the .eprj2 (a project opened from the library) or the file stem
(a project opened by path).  The path-opened session reports a *different* uuid
on every open -- ``native_inventory_raw.json`` captured 0054c1e0… while the file
stores 14837d10… -- so a gate that only compared the stored uuid refused every
legitimate path-opened run; the test that changes the session uuid while
keeping the name pins that fix.
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

PROJECT_NAME = "dcx_main_board"
# What native_inventory_raw.json actually saw, opened by --path.
SESSION_UUID = "0054c1e0f493b9ebf3517da33827a1985e43c2e9a23f621e11cf5b82f136a085"

pytestmark = pytest.mark.skipif(shutil.which("node") is None,
                                reason="Node.js not present for native ECO mock")


def _mock_js(mode: str, name: str = PROJECT_NAME, uuid: str = SESSION_UUID,
             r8: str = "correct") -> str:
    code = ECO.read_text(encoding="utf-8")
    net = "VCC12" if r8 == "correct" else "MISMATCHED_NET"
    return f"""
const CZY_APPLY_R8_DNP = {str(mode == 'apply').lower()};
const state = {{bom:true, pcb:true, modify:0, save:0}};
const comp = {{
 getState_Designator:()=> 'R8',
 getState_PrimitiveId:()=> 'R8-uuid',
 getState_AddIntoBom:()=> state.bom,
 getState_AddIntoPcb:()=> state.pcb
}};
const byRef = {{
 R8: {{props:{{Designator:'R8'}},pinInfoMap:{{'1':{{net:'{net}'}},'2':{{net:'RUN'}}}}}},
 R7: {{props:{{Designator:'R7'}},pinInfoMap:{{'1':{{net:'RUN'}},'2':{{net:'PGND'}}}}}},
 U2: {{props:{{Designator:'U2'}},pinInfoMap:{{'6':{{net:'RUN'}}}}}}
}};
global.eda = {{
 dmt_Project: {{getCurrentProjectInfo:async()=>({{friendlyName:'{name}',uuid:'{uuid}',data:[{{
 schematic:{{page:[{{uuid:'one-schematic'}}]}}
 }}]}})}},
 dmt_EditorControl: {{openDocument:async()=>true}},
 sch_ManufactureData: {{getNetlistFile:async()=>({{
 text:async()=>JSON.stringify({{components:byRef,nets:{{RUN:{{}}}}}})
 }})}},
 sch_PrimitiveComponent: {{
 getAll:async()=>[comp],
 get:async()=>comp,
 modify:async(_id,values)=>{{state.modify++;state.bom=values.addIntoBom;
                            state.pcb=values.addIntoPcb;return comp;}}
 }},
 sch_Document: {{save:async()=>{{state.save++;return true;}}}}
}};
(async()=> {{
{code}
}})().then(result=>process.stdout.write(JSON.stringify({{result, state}})))
    .catch(error=>{{process.stderr.write(String(error));process.exit(2);}});
"""


def _run(tmp_path: Path, mode: str = "dry", name: str = PROJECT_NAME,
         uuid: str = SESSION_UUID, r8: str = "correct") -> dict:
    script = tmp_path / "test_r8_eco.js"
    script.write_text(_mock_js(mode, name, uuid, r8), encoding="utf-8")
    process = subprocess.run(["node", str(script)], text=True, capture_output=True,
                             timeout=20, check=False)
    assert process.returncode == 0, process.stderr
    return json.loads(process.stdout)


def test_evolving_native_pin_map_is_exactly_the_known_stopline():
    data = json.loads(NATIVE_EXPORT.read_text(encoding="utf-8"))["value"]["refs"]
    assert data["U2"]["6"] == "RUN"
    assert data["R7"] == {"1": "RUN", "2": "PGND"}
    assert data["R8"] == {"1": "VCC12", "2": "RUN"}


def test_the_inventory_uuid_is_not_the_uuid_the_eprj2_stores():
    """The premise of the gate change, asserted rather than remembered."""
    inventory = json.loads(
        (ROOT / "hardware/dcx_main/gen/native_inventory_raw.json").read_text(encoding="utf-8"))
    value = inventory["value"]
    assert value["opened_by"] == "path"
    assert value["project_name"] == PROJECT_NAME
    assert value["project_uuid"] != value["stored_project_uuid"]


def test_default_invocation_cannot_mutate_native_cad(tmp_path: Path):
    outcome = _run(tmp_path)
    assert outcome["result"]["status"] == "DRY_RUN_SAFE"
    assert not outcome["result"]["applied"]
    assert outcome["state"]["modify"] == 0
    assert outcome["state"]["save"] == 0
    # the run records which project it looked at, both uuids included
    assert outcome["result"]["project"]["name"] == PROJECT_NAME
    assert outcome["result"]["project"]["session_uuid"] == SESSION_UUID
    assert outcome["result"]["project"]["stored_uuid"] not in (
        None, outcome["result"]["project"]["session_uuid"])
    assert outcome["result"]["project"]["identified_by"] == "path_name"


def test_a_fresh_session_uuid_is_the_same_project(tmp_path: Path):
    """Opening the same file again is not a different project.

    This is the case the old stored-uuid gate refused: same board, new session.
    """
    outcome = _run(tmp_path, mode="apply", uuid="f" * 64)
    assert outcome["result"]["status"] == "R8_ASSEMBLY_EXCLUSION_SAVED_NOT_VERIFIED"
    assert outcome["result"]["project"]["identified_by"] == "path_name"
    assert outcome["state"]["modify"] == 1


def test_a_library_opened_project_is_accepted_by_its_stored_uuid(tmp_path: Path):
    """Opened from the library the name differs, but the uuid is the stored one.

    Refusing here would block the other legitimate route, which is why the gate
    is a disjunction rather than a name-only check.
    """
    stored = "14837d107b6a52feb21f43869dd7378616b33db49e6c75ae2ea6bc0a53989e46"
    outcome = _run(tmp_path, mode="apply", name="DCX Main Board", uuid=stored)
    assert outcome["result"]["status"] == "R8_ASSEMBLY_EXCLUSION_SAVED_NOT_VERIFIED"
    assert outcome["result"]["project"]["identified_by"] == "studio_uuid"


def test_a_project_with_neither_identity_is_refused_before_any_mutation(tmp_path: Path):
    outcome = _run(tmp_path, mode="apply", name="some_other_board")
    assert outcome["result"]["status"] == "REFUSED"
    assert outcome["result"]["expected_path_opened_name"] == PROJECT_NAME
    assert outcome["result"]["actual_name"] == "some_other_board"
    assert outcome["result"]["project"]["identified_by"] is None
    assert outcome["state"]["modify"] == 0
    assert outcome["state"]["save"] == 0


def test_native_r8_net_map_mismatch_fails_before_any_mutation(tmp_path: Path):
    outcome = _run(tmp_path, mode="apply", r8="wrong")
    assert outcome["result"]["status"] == "REFUSED"
    assert outcome["state"]["modify"] == 0
    assert outcome["state"]["save"] == 0


def test_explicit_opt_in_excludes_only_r8_assembly_and_does_not_approve_fab(tmp_path: Path):
    outcome = _run(tmp_path, mode="apply")
    assert outcome["result"]["status"] == "R8_ASSEMBLY_EXCLUSION_SAVED_NOT_VERIFIED"
    assert outcome["state"]["modify"] == 1
    assert outcome["state"]["save"] == 1
    assert outcome["state"]["bom"] is False
    assert outcome["state"]["pcb"] is False
    assert outcome["result"]["release"] == "NOT_FOR_FAB"
