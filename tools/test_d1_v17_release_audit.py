"""Ensure independent DRC geometry cannot falsely approve incomplete power PCB."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import d1_v17_release_audit as R


def test_native_drc_still_has_nine_open_and_missing_magnetics():
    result = R.audit()
    assert result["status"] == "NOT_FOR_FAB"
    assert result["observed"]["rule_violations"] == 0
    assert result["observed"]["unconnected_total"] == 9
    assert result["observed"]["unconnected_by_net"] == {
        "GH": 1, "GH_DRV": 1, "HB": 1, "OC": 1, "SW": 3, "VIN_P": 2
    }
    assert result["observed"]["missing_magnetic_refs"] == [
        "CT", "T1", "T2", "T3", "T4"
    ]
    assert result["observed"]["design_logical_magnetic_terminals"] == 24
    assert result["observed"]["vendor_terminals_signed"] is False
    assert result["evidence_sha256"]["drc_checkout_bytes"] != result["evidence_sha256"]["drc_archived_crlf"]
    assert not result["checks"]["drc_no_ignored_checks"]
    assert result["checks"]["pgnd_and_vout_continuity_recorded"]
    assert not result["can_fabricate"]


def test_all_existing_hash_boundaries_match():
    result = R.audit()
    for name in (
        "pcb_sha_matches_native_build",
        "pcb_sha_matches_pin_parity",
        "drc_sha_matches_pin_parity",
        "drc_source_is_this_pcb",
    ):
        assert result["checks"][name], name


def test_fake_drc_zero_still_rejected_for_unverified_magnetics(tmp_path):
    root = tmp_path / "repo"
    target = root / R.G2
    target.mkdir(parents=True)
    for name in R.FILENAMES.values():
        shutil.copy2(R.ROOT / R.G2 / name, target / name)
    drc_file = target / R.FILENAMES["drc"]
    parity_file = target / R.FILENAMES["parity"]
    drc = json.loads(drc_file.read_text("utf-8"))
    drc["unconnected_items"] = []
    drc_file.write_text(json.dumps(drc), encoding="utf-8")
    parity = json.loads(parity_file.read_text("utf-8"))
    parity["native_V17_drc_sha256"] = R.historical_drc_digest(drc_file)
    parity_file.write_text(json.dumps(parity), encoding="utf-8")
    result = R.audit(root)
    assert result["checks"]["drc_zero_unconnected"]
    assert result["checks"]["drc_zero_rule_violations"]
    assert not result["checks"]["five_physical_magnetics_present"]
    assert not result["checks"]["all_24_magnetics_vendor_pins_and_dot_signed"]
    assert not result["checks"]["full_schematic_pcb_pin_parity"]
    assert not result["can_fabricate"]


def test_sha_mismatch_invalidates_release_facts(tmp_path):
    root = tmp_path / "repo"
    target = root / R.G2
    target.mkdir(parents=True)
    for name in R.FILENAMES.values():
        shutil.copy2(R.ROOT / R.G2 / name, target / name)
    with (target / R.FILENAMES["pcb"]).open("ab") as fh:
        fh.write(b"\\n")
    result = R.audit(root)
    assert not result["checks"]["pcb_sha_matches_native_build"]
    assert not result["checks"]["pcb_sha_matches_pin_parity"]
    assert not result["can_fabricate"]


def test_report_determinism_and_explicit_fail_closed():
    result = R.audit()
    assert R.canonical_json(result) == R.canonical_json(R.audit())
    assert R.main(["--require-release"]) == 2
