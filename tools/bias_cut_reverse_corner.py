"""Reproducible hypothetical threshold-mismatch counterexample, not vendor corners."""
import json
from pathlib import Path
import make_bias_cut_eco as eco

OUT = eco.OUT
DECK = OUT / 'bias_cut_reverse_mismatch.cir'

def deck():
    return eco.reverse_deck().replace(
        '* Bias-cut ECO reverse-blocking check:', '* HYPOTHETICAL threshold mismatch; not device qualification:').replace(
        'VREV VREV_SRC 0 18', 'VREV VREV_SRC 0 16').replace(
        '.model SVP SW(Ron=0.05 Roff=1Meg Vt=1.5 Vh=0.3)',
        '.model SVP SW(Ron=0.05 Roff=1Meg Vt=2.5 Vh=0.3)').replace(
        '.model SWPM SW(Ron=0.05 Roff=1Meg Vt=1.5 Vh=0.3)',
        '.model SWPM SW(Ron=0.05 Roff=1Meg Vt=0.6 Vh=0.3)')

if __name__ == '__main__':
    import sys
    if '--record' not in sys.argv:
        DECK.write_text(deck(),encoding='utf-8')
    else:
        log=DECK.with_suffix('.log')
        assert DECK.read_text(encoding='utf-8') == deck()
        assert log.stat().st_mtime_ns >= DECK.stat().st_mtime_ns
        text=log.read_text(encoding='utf-8',errors='replace')
        values=eco.parse_meas(text)
        result={'evidence_level':'HYPOTHETICAL_BEHAVIOURAL_COUNTEREXAMPLE',
                'device_corner_qualified':False,'hardware_qualified':False,
                'conditions':{'input_v':15,'backfeed_source_v':16,
                              'pass_switch_vt':.6,'follower_vt':2.5,'hysteresis':.3},
                'deck_sha256':eco.sha256(deck()),'log_sha256':eco.sha256(text),
                'measures':values,'passes_100ua_screen':abs(values['i_vdd_in_min']) <= 100e-6}
        DECK.with_suffix('.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(result,indent=2))
