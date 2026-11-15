"""G0 nine physical witness evidence readiness: only provenance, no fabricated pass."""
from __future__ import annotations
import csv,hashlib,io,json,sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parent))
import d1_g0_physical_readiness as ready
import d1_lane_c_g0_acceptance as g0

def matrix(faults=None):
    return g0.capture_csv(tuple(faults or g0.build()["fault_modes"]))

def write_matrix(path,rows):
    with path.open("w",encoding="utf-8",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=g0.CAPTURE_COLUMNS,lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

def rows():
    return list(csv.DictReader(io.StringIO(matrix())))

def test_live_nine_are_unapproved_and_no_raw_scope_files():
    result=ready.build()
    assert result["status"]=="PHYSICAL_SIGNOFF_NOT_OBTAINED_DO_NOT_POWER"
    assert result["physical_signed_approved"]==0
    assert result["physical_signoff_obligations_total"]==9
    assert len(result["physical_obligations"])==9
    assert all(x["status"]=="PENDING" and not x["claimed_or_signed_physical_PASS"]
               for x in result["physical_obligations"])
    assert all(x["requires_human_and_actual_hardware"] for x in result["physical_obligations"])
    assert result["capture_matrix"]["required"]==60
    assert result["capture_matrix"]["missing_raw"]==60
    assert result["capture_matrix"]["raw_present_unverified"]==0
    assert result["G0_approved"] is False and result["energization_allowed"] is False

def test_native_CAD_zero_is_not_witness_G0_01_or_09():
    data=ready.build()
    main=data["V5_mainboard_CAD"];bias=data["V6_bias_CAD"]
    assert main["footprints"]==161 and main["pin_parity"]==441
    assert bias["footprints"]==30 and bias["pin_parity"]==80
    assert main["erc"]==main["drc"]==main["opens"]==0
    assert bias["erc"]==bias["drc"]==bias["opens"]==0
    assert len(data["unreviewed_power_mainboard_drc_categories"])==5
    assert {i["status"] for i in data["physical_obligations"]}=={"PENDING"}

def test_fake_pass_or_bad_reference_is_impossible(tmp_path):
    arr=rows()
    arr[0]["vgs_negative_probe"]="PGND" # GA1 references SR source, not PGND!
    path=tmp_path/"invalid_reference.csv"
    write_matrix(path,arr)
    with pytest.raises(ValueError,match="VGS source-reference"):
        ready.captures(path,tmp_path,g0.build()["fault_modes"],g0.build()["gate_channels"])
    arr=rows()
    arr[4]["fault_mode"]=arr[0]["fault_mode"]
    arr[4]["gate"]=arr[0]["gate"]
    write_matrix(path,arr)
    with pytest.raises(ValueError,match="invalid/duplicate"):
        ready.captures(path,tmp_path,g0.build()["fault_modes"],g0.build()["gate_channels"])

def test_raw_file_present_is_provenance_only_never_physical_pass(tmp_path):
    arr=rows()
    raw=tmp_path/"original_scope.wfm"
    raw.write_bytes(b"\x01\x02real-file-origin-not-verified-test-data\x04")
    arr[0]["raw_scope_artifact"]=raw.name
    arr[0]["sample_interval_s"]="1e-8"
    arr[0]["measured_off_time_s"]="0.000011"
    arr[0]["review_status"]="SUBMITTED_FOR_REVIEW"
    f=tmp_path/"scope.csv"
    write_matrix(f,arr)
    out=ready.captures(f,tmp_path,g0.build()["fault_modes"],g0.build()["gate_channels"])
    assert out["raw_present_unverified"]==1
    assert out["missing_raw"]==59 and out["rejected"]==0
    assert out["physical_waveform_approval"]=="NOT_OBTAINED"
    assert out["original_raw_files"][0]["sha256"]==hashlib.sha256(raw.read_bytes()).hexdigest()

def test_missing_or_unsafe_raw_scope_file_cannot_count(tmp_path):
    a=rows()
    a[0]["raw_scope_artifact"]="../../fake.wfm"
    a[0]["sample_interval_s"]="1e-8"
    a[0]["measured_off_time_s"]="0.1"
    a[0]["review_status"]="SUBMITTED_FOR_REVIEW"
    f=tmp_path/"scope.csv";write_matrix(f,a)
    x=ready.captures(f,tmp_path,g0.build()["fault_modes"],g0.build()["gate_channels"])
    assert x["raw_present_unverified"]==0 and x["rejected"]==1
    a[0]["raw_scope_artifact"]="fake.wfm"
    (tmp_path/"fake.wfm").write_bytes(b"content is not real measured data")
    a[0]["review_status"]="PASS"
    write_matrix(f,a)
    x=ready.captures(f,tmp_path,g0.build()["fault_modes"],g0.build()["gate_channels"])
    assert x["rejected"]==1 and x["raw_present_unverified"]==0

def test_generated_readiness_report_exact_and_stale_not_passed():
    assert ready.AUDIT.read_text("utf-8")==ready.encode(ready.build())
    q=json.loads(ready.AUDIT.read_text("utf-8"))
    assert len(q["physical_obligations"])==9
    assert q["fabrication_approved"] is False
