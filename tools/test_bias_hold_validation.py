import hashlib
import json
import pytest
import bias_hold_validation as b


def test_internal_reg_budget_is_separate_from_external_bias():
    data=b.budget()
    assert data['gate_current_per_controller_a']==pytest.approx(.03330292)
    assert not data['within_30ma_characterized_load']
    assert data['target_max_charge_per_fet_nc']==pytest.approx(59.8145748)
    assert data['low_qg_candidate']['qg_max_nc'] is None
    assert data['low_qg_candidate']['engineering_double_typ_gate_current_a'] < .024
    assert any(row['controllers_on_branch']==4 for row in data['rows'])


def test_energy_bound_covers_all_passive_load_voltages():
    e=b.energy_budget()
    for vout in (0,.1,3.63,7.875,11,15.75):
        assert vout*(15.75-vout)/21.78 <= e['series_transfer_max_w']+1e-12
    assert e['conditional_total_j']==pytest.approx(.00241699119)
    assert not e['continuous_backfeed_has_finite_bound']


def test_measured_timestamps_are_times_not_threshold_values():
    data=json.loads((b.OUT/'report.json').read_text())
    assert not data['hardware_qualified'] and not data['thermal_qualified']
    assert all(data['checks'].values())
    for name,args in b.CASES.items():
        run=data['cases'][name]
        assert .02<run['measures']['gate_off_at']<.021
        assert .02<run['measures']['reg_off_at']<.02005
        assert (b.OUT/f'{name}.cir').read_text()==b.deck(**args)
        assert run['deck_sha256']==b.digest(b.OUT/f'{name}.cir')
        text=(b.OUT/f'{name}.log').read_text(encoding='utf-8',errors='replace')
        assert run['measures']==b.parse_log(text)
        assert run['measures']['q41_energy']>=0


def test_deck_hash_is_canonical_lf_not_checkout_bytes():
    # CI checks out with core.autocrlf=false (LF) while this Windows tree holds
    # CRLF, so the stored hash must be over the canonical LF text (text_identity),
    # not the checkout bytes.  Logs stay unhashed for identity: LTspice writes
    # mixed CRLF/LF, so their evidence is the parsed measurements checked above.
    data=json.loads((b.OUT/'report.json').read_text())
    for name in b.CASES:
        canonical=(b.OUT/f'{name}.cir').read_bytes().replace(b'\r\n',b'\n')
        expected=hashlib.sha256(canonical).hexdigest()
        assert data['cases'][name]['deck_sha256']==expected,name


def test_model_draws_regulator_current_from_vdd_and_body_diode_faces_source():
    deck=b.deck()
    assert 'BREG VDD_SR REG I=' in deck
    assert 'DBODY PASS_OUT VDD_IN BODY' in deck
    assert 'Cgd BC_GATE PASS_OUT' in deck
    assert 'CREG REG 0 2.3u' in deck
