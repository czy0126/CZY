"""Source-locked real native Maxwell CAD and nonconverged FEM evidence.

This test protects provenance and the explicit NOT_FOR_FAB conclusions.
It does not assert or fabricate any valid inductance/temperature/current data.
"""
import hashlib
import json
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"hardware/dcx_main/maxwell"
EVIDENCE=BASE/"ELP38_Lr_1A_connected_spiral_fem_nonconverged.evidence.json"
SPIRAL=BASE/"ELP38_Lr_CONNECTED_2TURN_SPIRAL_GEOMETRY_ONLY_NOT_FOR_FAB.evidence.json"

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def original_windows_contract_sha(path):
    """Match the actual CRLF input bytes used by native AEDT on Windows.

    Git normalizes this original concept contract to LF on CI. Converting
    back to original CRLF is an identity check, not a fabricated result.
    """
    data=path.read_bytes().replace(b"\r\n",b"\n")
    return hashlib.sha256(data.replace(b"\n",b"\r\n")).hexdigest()

def test_actual_native_spiral_is_one_connected_conductor_and_source_bound():
    e=json.loads(SPIRAL.read_text(encoding="utf-8"))
    cad=ROOT/e["project_file"]
    assert cad.is_file() and cad.stat().st_size>100000
    assert sha(cad)==e["project_sha256"]
    assert e["project_bytes"]==cad.stat().st_size
    assert original_windows_contract_sha(ROOT/e["source_contract"])==e["source_contract_sha256"]
    # Original native CAD generator was recorded as Git-normalized LF text.
    # On Windows, core.autocrlf may have converted it to CRLF.
    script=ROOT/e["native_generation_script"]
    assert hashlib.sha256(script.read_bytes().replace(b"\r\n",b"\n")).hexdigest()==e["native_generation_script_sha256"]
    assert e["solids"]==["I38_FERRITE_PROXY","E_BACK","LR_SERIES_2TURN_COPPER"]
    assert e["conductor_one_piece_connected_geometry"] is True
    assert e["physical_terminal_assigned_and_validated"] is False
    assert e["oem_material_n97_100c_verified"] is False
    assert e["fem_solved"] is False
    assert e["fabrication_approved"] is False

def test_both_real_maxwell_runs_have_native_field_archives_but_neither_converged():
    e=json.loads(EVIDENCE.read_text(encoding="utf-8"))
    assert e["status"]=="REAL_NATIVE_FIELD_SOLVER_EXECUTED_BUT_ADAPTIVE_NOT_CONVERGED"
    assert len(e["cases"])==2
    assert e["two_long_external_leads_unmanufacturable"] is True
    assert e["only_1A_solves_not_operating_100A"] is True
    assert e["mesh_convergence_qualified"] is False
    assert e["fabrication_approved"] is False
    for d in e["cases"]:
        for key, h in (
            ("source_aedt","source_sha256"),
            ("native_fields_zip","native_fields_zip_sha256"),
            ("receipt","receipt_sha256")
        ):
            a=ROOT/d[key]
            assert a.is_file()
            assert sha(a)==d[h],key
        raw=json.loads((ROOT/d["receipt"]).read_text(encoding="utf-8"))
        assert d["solver_returned"] is True
        assert d["mesh_converged"] is False
        assert any("Adaptive Passes did not converge" in m
                   for m in raw["solver_messages"])
        with zipfile.ZipFile(ROOT/d["native_fields_zip"]) as z:
            assert len(z.namelist())==d["fields_count"]
            assert any(name.endswith(".profile") for name in z.namelist())
            assert any(name.endswith("fields.blo") for name in z.namelist())
