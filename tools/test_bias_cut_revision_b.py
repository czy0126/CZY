"""Electrical regressions and evidence identity for the candidate, not approval."""
import json
import bias_cut_revision_b as b


def test_series_blocking_has_no_output_to_gate_bypass():
    ps={p.ref:p for p in b.parts()}
    assert 'Q51' not in ps and 'Q55' not in ps
    assert ps['D50'].nets=={'1':'VDD_SR','2':'D_ANODE'}
    assert ps['R59'].nets=={'1':'PASS_OUT','2':'D_ANODE'}
    assert ps['Q50'].nets=={'1':'BC_GATE','2':'VDD_IN','3':'PASS_OUT'}
    assert all('VDD_SR' not in p.nets.values() for p in b.parts() if 'BC_GATE' in p.nets.values())


def test_evidence_matches_generated_decks_and_cannot_approve_hardware():
    report=json.loads((b.OUT/'report.json').read_text(encoding='utf-8'))
    assert not report['hardware_qualified']
    assert not report['fabrication_approved']
    assert not report['full_control_simulated']
    assert set(report['cases'])==set(b.CASES)
    for name,kwargs in b.CASES.items():
        deck=b.OUT/f'{name}.cir'
        assert deck.read_text(encoding='utf-8')==b.deck(**kwargs)
        assert report['cases'][name]['deck_sha256']==b.digest(deck)
        assert report['cases'][name]['log_sha256']==b.digest(b.OUT/f'{name}.log')
    assert all(report['checks'].values())


def test_resistor_current_and_hold_bounds_do_not_use_maximum_diode_drop():
    report=json.loads((b.OUT/'report.json').read_text(encoding='utf-8'))
    bounds=report['analytic_bounds']
    assert .723 < bounds['inrush_a'] < .724
    assert bounds['r57_24v_w'] < .27
    assert bounds['single_pair_10v_gate_budget_a'] > .03
