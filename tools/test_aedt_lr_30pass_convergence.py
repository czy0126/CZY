"""Check actual AEDT 2025R2 1-A convergence and field-calculator results.

The test establishes that real archived mesh/fields exist and that the
concept trial solved at <=2% last-two-pass energy convergence. It MUST NOT
authorize OEM N97, real Lr, 100A, AC loss or fabrication.
"""
from __future__ import annotations
import hashlib
import json
import math
import re
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
HERE=ROOT/"hardware/dcx_main/maxwell"
STEM="ELP38_Lr_1A_EXTERNAL_LEADS_30PASS_CONVERGED_CONCEPT_NOT_FOR_FAB"
EVIDENCE=HERE/(STEM+".evidence.json")

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def evidence():
    r=json.loads(EVIDENCE.read_text(encoding="utf-8"))
    assert r["schema"]=="D1_MAXWELL_1A_CONCEPT_TRUE_18_PASS_CONVERGED_EVIDENCE_V1"
    return r

def test_actual_native_30pass_archives_retain_exact_bytes():
    r=evidence()
    assert len(r["provenance"])==5
    for item in r["provenance"]:
        file=ROOT/item["path"]
        assert file.is_file(),file
        assert file.stat().st_size==item["bytes"]
        assert sha(file)==item["sha256"],file
    archive=HERE/(STEM+".results.zip")
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        assert len(z.namelist())==46
        assert any(name.endswith("fields.blo") for name in z.namelist())
        assert any(name.endswith(".profile") for name in z.namelist())
    assert not r["manufacturing_approved"]
    assert not r["oem_n97_100c_bh_verified"]
    assert r["model_has_two_artificial_long_current_leads"]

def test_real_convergence_file_has_18_passes_under_two_percent():
    r=evidence()
    c=r["native_convergence"]
    path=HERE/(STEM+".conv")
    data=path.read_text(encoding="utf-8")
    assert "Completed : 18" in data and "Maximum   : 30" in data
    assert "Target    : (2, 2)" in data
    rows=[]
    for line in data.splitlines():
        m=re.match(r"^\s*(\d+)\|\s*(\d+)\|\s*([\deE+.-]+)\|\s*([\deE+.-]+)\|\s*([\deE+.-]+|N/A)\|",line)
        if m:
            rows.append({"pass_no":int(m.group(1)),
                         "tetrahedra":int(m.group(2)),
                         "energy_j":float(m.group(3)),
                         "energy_error_pct":float(m.group(4)),
                         "delta_energy_pct":None if m.group(5)=="N/A" else float(m.group(5))})
    assert len(rows)==18 and c["passes"]==18
    assert rows[-1]==c["last_pass"]
    assert rows[-2:]==c["last_two_passes"]
    assert c["max_passes"]==30
    assert all(x["energy_error_pct"]<2 and x["delta_energy_pct"]<2 for x in rows[-2:])
    assert rows[-1]["tetrahedra"]==35976

def test_native_energy_is_DC_2W_not_AC_peak_4W_and_not_qualified_L():
    r=evidence()
    data=json.loads((HERE/(STEM+".postprocess.json")).read_text(encoding="utf-8"))
    receipt=json.loads((HERE/(STEM+".receipt.json")).read_text(encoding="utf-8"))
    assert receipt["solver_success"] and receipt["mesh_convergence_verified"]
    assert receipt["native_validation_passed"]
    assert math.isclose(data["energy_j"],7.08336788694707e-7,rel_tol=1e-8)
    assert math.isclose(
        data["static_dc_energy_equivalent_inductance_uH"],
        2*data["energy_j"]*1e6,rel_tol=1e-8)
    assert math.isclose(r["static_dc_energy_equivalent_L_uH_unqualified"],
                        data["static_dc_energy_equivalent_inductance_uH"])
    assert not r["operating_point_ac_and_high_bias_sweeps_verified"]
    assert not r["t1_t4_ct_24_pin_dot_footprints_verified"]
    assert not data["actual_Lr_qualified"] and not data["actual_inductance_0p92uh_qualified"]
