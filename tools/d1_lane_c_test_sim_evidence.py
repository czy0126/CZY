"""Simulation readback cannot become a hardware release report."""
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parent))
import d1_lane_c_sim_evidence as e

def test_original_raw_log_and_deck_have_consistent_hashes():
    r=e.build()
    assert r["raw_bytes"] > 1000
    assert r["archive_bytes"] < r["raw_bytes"]
    assert r["passive_gate_fall_to_threshold_s"] > 100e-6
    assert r["illustrative_powered_sink_fall_to_threshold_s"] < 100e-9
    assert r["g0_approved"] is False and r["g1_approved"] is False
    assert r["is_vendor_worst_case"] is False

def test_missing_simulation_completion_is_rejected():
    with pytest.raises(ValueError, match="complete log"):
        e.load(e.DECK.read_text("utf-8"),"truncated",b"Title: x\nNo. Variables: 2",b"stub")

def test_mutated_measurement_is_rejected():
    t=e.LOG.read_text("utf-8").replace("0.000148910339781","0.000001")
    archive=e.ARCHIVE.read_bytes()
    import gzip
    with pytest.raises(ValueError, match="RC formula"):
        e.load(e.DECK.read_text("utf-8"),t,gzip.decompress(archive),archive)
