"""Synthetic P0-C matrix regression: NEVER actual lab/physical protection evidence."""
from __future__ import annotations
import copy
import csv
import hashlib
import json
from pathlib import Path

import pytest

import d0_p0_fault_matrix as m
import d0_gate_capture_audit as auditor
import d0_scope_sync_align as align
from test_d0_evidence_chain import Case

REV="BENCH_FIXTURE_UNITTEST_REV1" # synthetic fixture, not genuine physical provenance

def sample_case(root:Path,mode:str)->dict:
    folder=root/mode
    folder.mkdir()
    case=Case(folder)
    caseid="UNITTEST_FAULT_"+mode
    # Six synthetic fixtures must have SIX distinct captures, not one reused
    # scope file with six different mode labels. Perturb a pre-trip gate level
    # per fixture, without changing the switching/overlap/timing assertions.
    scope=folder/"scope_a.csv"
    with scope.open(newline="",encoding="utf-8") as handle:
        rows=list(csv.reader(handle))
    for row in rows[1:]:
        if float(row[2])>4.0:
            row[2]=str(5.0+0.05*m.MODES.index(mode))
    with scope.open("w",newline="",encoding="utf-8") as handle:
        csv.writer(handle).writerows(rows)
    man=json.loads(case.manifest.read_text(encoding="utf-8"))
    man["case_id"]=caseid
    case.manifest.write_text(json.dumps(man),encoding="utf-8")
    assert align.run(case.manifest,case.csv,case.alignment_path) in (0,1)
    case.config["case_id"]=caseid
    # Rebind original auditor to one common, synthetically attributed revision.
    case.config["hardware_revision"]=REV
    case.config["instrument_id"]="UNITTEST_SCOPE_A"
    case.config_path.write_text(json.dumps(case.config),encoding="utf-8")
    case.audit_path.write_text(
        json.dumps(auditor.run(case.csv,case.config_path)),encoding="utf-8")
    witness=folder/"witness.json"
    event=folder/"scope_a.csv"
    witness.write_text(json.dumps({
        "mode":mode,"hardware_revision":REV,
        "stimulus_applied_physically":True,
        "stimulus_instrument_id":"UNITTEST_SCOPE_A",
        "observer":"UNITTEST_ENGINEER",
        "observed_at":"2026-11-12T00:00:00+08:00",
        "raw_event_trace_path":event.name,
        "raw_event_trace_sha256":hashlib.sha256(event.read_bytes()).hexdigest(),
        "power_stage_energy_limited":True,
        "voltage_current_soa_reviewed_before_test":True,
    }),encoding="utf-8")
    return {
        "mode":mode, "case_id":caseid,
        "manifest":str(case.manifest.relative_to(root)),
        "alignment":str(case.alignment_path.relative_to(root)),
        "csv":str(case.csv.relative_to(root)),
        "config":str(case.config_path.relative_to(root)),
        "audit":str(case.audit_path.relative_to(root)),
        "witness_record":str(witness.relative_to(root)),
    }

def fixture(tmp_path:Path):
    rows=[sample_case(tmp_path,mode) for mode in m.MODES]
    path=tmp_path/"matrix.json"
    data={"schema_version":1,"hardware_revision":REV,"cases":rows}
    path.write_text(json.dumps(data),encoding="utf-8")
    return path,data

def test_repository_physical_test_manifest_template_cannot_claim_real_protection():
    template=m.Path(__file__).resolve().parents[1]/"hardware/dcx_main/protection_p0_fault_matrix_TEMPLATE.json"
    evidence=m.build(template)
    assert evidence["matrix_complete"] is False
    assert evidence["fabrication_approved"] is False
    assert evidence["physical_gate_protection_approved"] is False
    assert set(evidence["cases"])==set(m.MODES)


def test_missing_matrix_and_missing_scenarios_never_pass(tmp_path):
    result=m.build(tmp_path/"absent.json")
    assert result["matrix_complete"] is False
    path=tmp_path/"matrix.json"
    path.write_text(json.dumps({"schema_version":1,
        "hardware_revision":"REV1","cases":[]}),encoding="utf-8")
    r=m.build(path)
    assert r["missing_modes"]==sorted(m.MODES)
    assert not r["fabrication_approved"]

def test_six_independent_reproduced_capture_chains_are_not_physical_certification(tmp_path):
    manifest,_=fixture(tmp_path)
    result=m.build(manifest)
    assert result["status"]=="SIX_CAPTURE_CHAINS_CONSISTENT_NEEDS_PHYSICAL_REVIEW"
    assert result["matrix_complete"]
    assert len(result["cases"])==6 and not result["errors"]
    assert all(x["status"].startswith("CAPTURE_CHAIN_VERIFIED")
               for x in result["cases"].values())
    assert all(len(x["evidence_sha256"])==8
               for x in result["cases"].values())
    assert result["fabrication_approved"] is False
    assert result["physical_gate_protection_approved"] is False
    assert result["all_ten_gate_hardware_proven"] is False
    assert result["origin_authenticated_by_software"] is False

def test_missing_hardware_case_is_not_replaced_by_one_healthy_trip(tmp_path):
    manifest,d=fixture(tmp_path)
    d["cases"]=d["cases"][:-1]
    manifest.write_text(json.dumps(d),encoding="utf-8")
    r=m.build(manifest)
    assert not r["matrix_complete"]
    assert "HELD_HIGH_ACK_FAULT_RECOVERY" in r["missing_modes"]

def test_duplicate_witness_and_provenance_tampering_fail_closed(tmp_path):
    path,data=fixture(tmp_path)
    data["cases"][1]["witness_record"]=data["cases"][0]["witness_record"]
    path.write_text(json.dumps(data),encoding="utf-8")
    r=m.build(path)
    assert not r["matrix_complete"]
    assert any("witness" in " ".join(x["errors"]).lower() for x in r["cases"].values())

def test_witness_with_stale_raw_trace_or_no_power_limit_is_rejected(tmp_path):
    path,d=fixture(tmp_path)
    raw=tmp_path/d["cases"][0]["witness_record"]
    w=json.loads(raw.read_text(encoding="utf-8"))
    w["power_stage_energy_limited"]=False
    w["raw_event_trace_sha256"]="0"*64
    raw.write_text(json.dumps(w),encoding="utf-8")
    r=m.build(path)
    assert not r["matrix_complete"]
    assert any("trace SHA256" in x for x in r["cases"][m.MODES[0]]["errors"])
    assert any("energy" in x for x in r["cases"][m.MODES[0]]["errors"])

def test_bad_rev_and_duplicate_fault_scenarios_never_pass(tmp_path):
    path,d=fixture(tmp_path)
    d["cases"].append(copy.deepcopy(d["cases"][0]))
    path.write_text(json.dumps(d),encoding="utf-8")
    r=m.build(path)
    assert not r["matrix_complete"]
    assert any("duplicate" in e for e in r["errors"])
    d["cases"].pop()
    d["hardware_revision"]="SYNTHETIC_WRONG_REV"
    path.write_text(json.dumps(d),encoding="utf-8")
    assert not m.build(path)["matrix_complete"]

def test_absolute_or_parent_relative_paths_refused(tmp_path):
    path,d=fixture(tmp_path)
    for bad in ("../etc/passwd","C:/system/private.csv"):
        edited=copy.deepcopy(d)
        edited["cases"][0]["csv"]=bad
        path.write_text(json.dumps(edited),encoding="utf-8")
        assert not m.build(path)["matrix_complete"]

def test_unauthenticated_capture_does_not_count_as_bench_proof(tmp_path):
    path,d=fixture(tmp_path)
    row=d["cases"][0]
    manifest=tmp_path/row["manifest"]
    raw=json.loads(manifest.read_text(encoding="utf-8"))
    raw["sync"]["basis_review_status"]="PENDING"
    manifest.write_text(json.dumps(raw),encoding="utf-8")
    assert not m.build(path)["matrix_complete"]
