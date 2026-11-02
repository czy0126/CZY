"""The Windows launch manifest covers 50V probes and true 120A cold/fault."""
from __future__ import annotations
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_windows_batch_is_explicit_opt_in_and_includes_all_missing_cases():
    script = (ROOT / "tools/run_dcx_pending_cases.ps1").read_text(encoding="utf-8")
    for name in ("50V110","50V120","48V120Cold","48V120Fault","48V120HotFault","50V120HotFault"):
        assert f'"{name}"' in script
    for src in (
        "sr_tank_dual_v33_ss_1ms_vin50_i110_cin.cir",
        "sr_tank_dual_v33_ss_1ms_vin50_i120_cin.cir",
        "sr_tank_dual_v33_cold_vin48_i120_target.cir",
        "sr_tank_dual_v33_cold_oc_vin48_i120_target.cir",
        "sr_tank_dual_v33_ss_hotfault_48v_120a.cir",
        "sr_tank_dual_v33_ss_hotfault_50v_120a.cir",
    ):
        assert src in script and (ROOT / "sim/v3" / src).is_file()
    assert "if (!$Execute)" in script
    assert 'Test-Path -LiteralPath $Log' in script
    assert "simulation NOT YET VERIFIED" in script


def test_new_unrun_hotfaults_are_default_and_require_complete_logs():
    txt = (ROOT / "tools/run_dcx_pending_cases.ps1").read_text(encoding="utf-8")
    assert '$Cases = @("48V120HotFault", "50V120HotFault")' in txt
    assert "Total elapsed time" in txt
    assert "hot_ipri_after" in txt.lower()
    assert "hot_ss_before" in txt.lower()
