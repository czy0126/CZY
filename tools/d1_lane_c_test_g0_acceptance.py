"""Issue #133 G0 acceptance cannot be spoofed by reports or fabricated PASS."""
from __future__ import annotations
import hashlib
import json
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parent))
import d1_lane_c_g0_acceptance as g

def test_current_g0_release_is_hard_blocked():
    r = g.build()
    assert r["native_bench_netlist_pins_checked"] == 565
    assert r["native_bench_erc_violations"] == 0
    assert r["native_bench_not_production_isolated"] is True
    assert r["independent_dual_bias_candidate_erc_violations"] == 0
    assert r["independent_dual_bias_candidate_pins_checked"] == 28
    assert r["independent_dual_bias_candidate_secondary_ground_separate"] is True
    assert r["dual_bias_candidate_is_not_integrated_or_fab_ready"] is True
    v4=r["latest_native_mainboard_G0_V4"]
    assert v4["pcb_footprints"]==157
    assert v4["independent_ref_pin_net_parity"]==433
    assert v4["pcb_unconnected"]==v4["pcb_drc_violations"]==v4["schematic_erc_violations"]==0
    assert v4["secondary_return_pads_reassigned"]==129
    assert v4["actual_bias_regulation_and_uvlo_not_integrated"] is True
    assert v4["g0_remains_blocked"] is True
    v5=r["latest_native_mainboard_G0_V5"]
    assert v5["pcb_footprints"]==161
    assert v5["independent_schematic_pins"]==441
    assert v5["native_drc"]==v5["native_erc"]==v5["native_unconnected"]==0
    assert v5["effective_REG_c_and_SR_noise_not_signed"] is True
    bias=r["new_dual_Traco_48v_12v_bias_carrier_CAD"]
    assert bias["modules_30w_each"]==2
    assert bias["native_pcb_parts"]==13 and bias["native_schematic_pins"]==34
    assert bias["native_erc"]==bias["native_pcb_drc"]==bias["native_pcb_unconnected"]==0
    assert bias["physically_assembled_and_verified"] is False
    assert bias["g0_still_blocked"] is True
    v6=r["new_V6_dual_rail_UVLO_real_KiCad_bias_carrier"]
    assert v6["native_pcb_devices"]==30
    assert v6["independently_exported_pin_parity"]==80
    assert v6["native_drc"]==v6["native_open"]==v6["native_erc"]==0
    assert v6["secondary_to_primary_status_opto_isolated"] is True
    assert v6["UVLO_status_closes_actual_primary_power_contactor_or_RUN"] is False
    assert v6["main_G0_still_blocked"] is True
    v7=r["new_V7_external_NC_ESTOP_and_manual_rearm_CAD_NOT_CONNECTED"]
    assert v7["native_pcb_footprints"]==27
    assert v7["source_authored_pin_parity"]==81
    assert v7["native_pcb_drc"]==v7["native_schematic_erc"]==0
    assert v7["native_pcb_unconnected"]>0
    assert v7["true_series_NC_stop_48V_coil_copper_present"] is True
    assert v7["actual_signal_copper_all_routed"] is False
    assert v7["G0_04_physical_approved"] is False
    assert v7["G0_continues_BLOCKED"] is True
    assert r["baseline_unconnected"] > 0
    assert r["required_scope_captures"] == 60
    assert len(r["obligations"]) == 9
    assert all(v["status"] == "PENDING" for v in r["obligations"])
    assert r["independent_hardware_signoff"] == "NOT_OBTAINED"
    assert r["energization_allowed"] is False
    assert r["gate_0_approved"] is False
    assert r["fabrication_approved"] is False

def test_every_gate_and_fault_has_a_unique_raw_capture_request():
    modes = g.build()["fault_modes"]
    rows = list(__import__("csv").DictReader(__import__("io").StringIO(g.capture_csv(tuple(modes)))))
    assert len(rows) == 60
    assert len({(x["gate"], x["fault_mode"]) for x in rows}) == 60
    assert {x["vgs_negative_probe"] for x in rows if x["gate"] == "GH1"} == {"SW"}
    assert {x["vgs_negative_probe"] for x in rows if x["gate"] == "GL1"} == {"PGND"}
    assert {x["vgs_negative_probe"] for x in rows if x["gate"].startswith("GA")} == {"SR_SOURCE_RETURN"}
    assert all(x["raw_scope_artifact"] == "PENDING" for x in rows)

def test_fake_green_or_unknown_witness_is_rejected():
    with pytest.raises(ValueError, match="invalid witness state"):
        g.build({"items": {"G0-01": {"result": "PASS"}}})
    with pytest.raises(ValueError, match="unknown G0"):
        g.build({"items": {"G0-XX": {"result": "PASS"}}})

@pytest.mark.parametrize("bad", [
    {"result": "PASS"}, {"result": "SUBMITTED_FOR_REVIEW"},
    {"result": "SUBMITTED_FOR_REVIEW", "operator": "x", "reviewer": "x",
     "board_serial": "a", "date": "2026-11-15", "test_procedure": "p",
     "measurement_summary": "m", "artifacts": []},
])
def test_unsubstantiated_witness_is_rejected(bad, tmp_path):
    with pytest.raises(ValueError):
        g.validate_witness("G0-01", bad, tmp_path)

def test_hash_bound_real_file_is_only_submitted_never_physically_approved(tmp_path):
    f = tmp_path / "physical_scope_trace.csv"
    f.write_text("unverified trace\n", encoding="utf-8")
    entry = dict(result="SUBMITTED_FOR_REVIEW", board_serial="BENCH-UNKNOWN",
                 operator="submitter", reviewer="reviewer",
                 date="2026-11-15", test_procedure="TESTONLY",
                 measurement_summary="not physical proof",
                 artifacts=[{"path": f.name, "sha256": hashlib.sha256(f.read_bytes()).hexdigest()}])
    result = g.build({"items": {"G0-01": entry}}, evidence_root=tmp_path)
    assert result["obligations"][0]["status"] == "SUBMITTED_UNVERIFIED_HARDWARE"
    assert result["energization_allowed"] is False
    assert result["gate_0_approved"] is False
    assert result["all_evidence_submitted_for_independent_review"] is False
    entry["artifacts"][0]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="checksum mismatch"):
        g.build({"items": {"G0-01": entry}}, evidence_root=tmp_path)

@pytest.mark.parametrize("name", ["../escaping.txt", "/absolute/path"])
def test_path_escape_is_rejected(name, tmp_path):
    with pytest.raises(ValueError):
        g.safe_file(name, tmp_path)

def test_template_is_explicitly_not_a_release_document():
    tmpl = g.template()
    assert tmpl["never_use_as_hardware_permit"] is True
    assert len(tmpl["items"]) == 9
    assert all(x["result"] == "PENDING" for x in tmpl["items"].values())
