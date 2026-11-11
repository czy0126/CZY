from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'hardware/dcx_main/g1'))
import route_driver_eco as R
import route_lr_signal_stubs as S


def line(a=(0,0),b=(2,0),net='VCC',layer=1,width=.2):
    return dict(a=a,b=b,net=net,layer=layer,width=width)


@pytest.mark.parametrize('actual',[line(net='PGND'),line(layer=2),line(width=.15),line(a=(0,.02),b=(2,.02))])
def test_wrong_net_layer_width_or_offset_cannot_cover(actual):
    assert not R._covered(line(),[actual],allow_wider=True)[0]


def test_longer_same_net_line_can_cover_with_explicit_width_policy():
    actual=line((-1,0),(3,0),width=.3)
    assert not R._covered(line(),[actual])[0]
    assert R._covered(line(),[actual],allow_wider=True)[0]


def test_interval_union_and_real_gap_diagnostics():
    assert R._covered(line(),[line((0,0),(1,0)),line((1,0),(2,0))])[0]
    for pieces in ([line((0,0),(.9,0)),line((1,0),(2,0))],[line((0,0),(1.9,0))]):
        ok,why=R._covered(line(),pieces)
        assert not ok and why
    # At a tighter coordinate tolerance even a 1um gap must fail.
    assert not R._covered(line(),[line((0,0),(1,0)),line((1.001,0),(2,0))],tol=.0001)[0]


def test_unrelated_copper_is_ignored_not_used_as_proof_or_veto():
    assert R._covered(line(),[line(net='PGND'),line()])[0]
    assert not R._covered(line(b=(0,0)),[line()])[0]


def test_saved_c103_c104_coverage_has_wider_existing_copper():
    # Optional local native receipt: CI without this candidate still runs all
    # adversarial geometry tests above. The real saved file is not regenerated.
    if not S.READBACK_OUT.exists():pytest.skip('candidate receipt not supplied')
    seg=next(s for s in R.segments(S.copper()) if s['net']=='VCC12' and s['a'][1]>64)
    actual=R.lines_from_readback(S.READBACK_OUT)
    assert not R._covered(seg,actual)[0]
    assert R._covered(seg,actual,allow_wider=True)[0]
