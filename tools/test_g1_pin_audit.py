import importlib.util
from pathlib import Path

spec=importlib.util.spec_from_file_location('g1audit',Path(__file__).resolve().parents[1]/'hardware/dcx_main/g1/make_g1_report.py')
g=importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)


def test_wrong_and_missing_pins_cannot_report_zero_pass():
    pads=[{'ref':'Q1','PadNumber':'1','Net':'WRONG'}]
    result=g.audit_pad_nets(pads,{'Q1':{'1':'GATE','2':'PGND'}},{'Q1'})
    assert len(result['mismatches'])==1 and len(result['missing_pins'])==1
    assert not result['snapshot_equivalent']


def test_duplicate_thermal_pads_must_have_identical_nets():
    pads=[{'ref':'Q1','PadNumber':'5','Net':n} for n in ('DRAIN','PGND')]
    result=g.audit_pad_nets(pads,{'Q1':{'5':'DRAIN'}},{'Q1'})
    assert result['duplicate_net_conflicts'] and not result['snapshot_equivalent']
    pads[1]['Net']='DRAIN'
    assert g.audit_pad_nets(pads,{'Q1':{'5':'DRAIN'}},{'Q1'})['snapshot_equivalent']


def test_unknown_pin_and_concept_pad_are_distinct():
    pads=[{'ref':None,'PadNumber':'PRI_A','Net':'SW'}, {'ref':'U1','PadNumber':'9','Net':'PGND'}]
    result=g.audit_pad_nets(pads,{'U1':{'1':'PGND'}},{'U1'})
    assert len(result['unknown_pins'])==1 and len(result['missing_pins'])==1
