"""Native Ansys Maxwell 3D geometry artifact identity and fabrication guards.

The .aedt was created by installed Ansys Electronics Desktop 2025 R2 on
Windows, not produced by the offline CI. CI only verifies its source identity,
the native file's bytes, and that no solver or OEM B-H signoff is implied.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
META = ROOT / "hardware/dcx_main/maxwell/ELP38_Lr_2turn_0920uH_NATIVE_CONCEPT_NOT_FOR_FAB.evidence.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_aedt_native_geometry_is_real_and_bound_to_concept_source():
    e = json.loads(META.read_text(encoding="utf-8"))
    cad = ROOT / e["cad_project"]
    contract = ROOT / e["concept_source"]
    script = ROOT / e["native_script"]
    assert cad.is_file() and cad.suffix == ".aedt"
    assert cad.stat().st_size >= 20000
    assert e["cad_project_sha256"] == sha(cad)
    assert e["cad_project_bytes"] == cad.stat().st_size
    assert e["concept_source_sha256"] == sha(contract)
    assert e["native_script_sha256"] == sha(script)
    spec = json.loads(contract.read_text(encoding="utf-8"))
    candidates = [c for c in spec["cases"] if c["id"] == "ELP38_Lr_2turn_0920uH"]
    assert len(candidates) == 1
    case = candidates[0]
    assert case["turns"] == 2
    assert case["gap_mm"] == 1.031
    assert case["target_inductance_uH"] == .92
    assert case["type"] == "LR_ELP38"
    assert e["geometry_solids"] == [
        "I38_FERRITE_PROXY", "E_BACK", "LR_OUTER_1", "LR_OUTER_2"
    ]


def test_native_concept_is_not_fem_or_fabrication_approval():
    e = json.loads(META.read_text(encoding="utf-8"))
    assert e["status"] == "ACTUAL_AEDT_NATIVE_GEOMETRY_SAVED_NO_SOLVER_NOT_FOR_FAB"
    assert e["magnetic_material"] == "AEDT_STOCK_FERRITE_PLACEHOLDER_NOT_N97_100C"
    for name in (
        "physical_winding_connected", "validated_terminal_dot",
        "actual_oem_geometry", "fem_solver_executed", "mesh_converged",
        "l_vs_i_verified", "iron_and_copper_loss_verified",
        "fabrication_approved", "real_windings_and_24_plus_2_pads_approved",
    ):
        assert e[name] is False, name
