"""50V runner does not silently rewrite results or mistake logs for safety."""
from pathlib import Path
import pytest
import shutil
import subprocess
ROOT=Path(__file__).resolve().parent.parent
FILE=ROOT/"tools/run_d1_50v_matched_cases.ps1"

def test_all_50v_pairs_and_no_fab_claims():
    s=FILE.read_text(encoding="utf-8")
    for role in ("A_CONTROL","A_CANDIDATE","B_CONTROL","B_CANDIDATE"):
        assert '"'+role+'"' in s
    for suffix in ("prot_a_oc1v_thrmute_control.cir","prot_a_oc1v.cir",
                   "prot_b_fast10u_1p8v_thrmute_control.cir","prot_b_fast10u_1p8v.cir"):
        assert suffix in s
        assert (ROOT/"sim/v3"/("sr_tank_dual_v33_ss_hotfault_50v_120a_cshunt_srprobe_"+suffix)).exists()
    assert "& $LTspice -b -ascii $Stage" in s
    assert "from ascii_raw_window import last_time" in s
    assert 'pre_fault_1mV_paired_verified=$false' in s
    assert "fabrication_approved=$false" in s
    assert "Refuse overwrite" in s

@pytest.mark.skipif(shutil.which("pwsh") is None,reason="PowerShell not available")
def test_dry_run_powershell_parses_without_ltspice():
    r=subprocess.run(["pwsh","-NoLogo","-NonInteractive","-File",str(FILE)],capture_output=True,
                     text=True,cwd=ROOT,timeout=30)
    assert r.returncode==0,(r.stdout,r.stderr)
    assert r.stdout.count("DRY_RUN")==4
    assert "NO NEW RAW" in r.stdout


def test_sweep_selector_requires_identical_cshunt_for_control_and_candidate():
    s=FILE.read_text(encoding='utf-8')
    assert 'ValidateSet("published","shunt_2f","shunt_5f","shunt_10f")' in s
    assert '$RequiredShunt = switch($Variant)' in s
    assert 'if(!$Txt.Contains(".options plotwinsize=0 method=gear cshunt="+$RequiredShunt))' in s
