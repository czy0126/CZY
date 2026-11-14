"""Lane C actual remote raw/log readback; no simulation-to-hardware shortcut."""
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parent))
import d1_lane_c_uvlo_evidence as u

def test_uvlo_native_source_and_raw_integrity():
    r=u.build()
    assert r["raw_bytes"]>10_000
    assert r["raw_gzip_bytes"]<r["raw_bytes"]
    assert 100e-6<r["uvlo_trip_model_time_s"]<120e-6
    assert r["gate_threshold_model_time_s"]>r["uvlo_trip_model_time_s"]
    assert r["driver_hold_voltage_200us"]>8
    assert r["g0_approved"] is False and r["energization_allowed"] is False
    assert r["bench_primary_secondary_bias_isolated"] is False
    assert r["real_48v_12v_converter_specified"] is False

def test_incomplete_log_measurement_is_rejected():
    assert "Total elapsed time:" in u.LOG.read_text("utf-8")
    with pytest.raises(ValueError,match="missing HOLD"):
        u.scalar("truncated","hold_at_130u")

def test_generator_has_real_kicad_circuit_with_unpopulated_hs_detector():
    p,_,_=u.hw.expected_text()
    x={r.ref:r for r in p}
    assert x["R74"].dnp and x["D17"].dnp
    assert x["U18"].nets["5"]=="SW"
    assert x["R20"].nets["1"]=="V12P_F"
    assert x["R22"].nets["1"]=="V12S_F"
