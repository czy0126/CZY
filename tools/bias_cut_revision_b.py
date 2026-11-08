"""Revision B candidate: reuse latch drawing, replace the defective power path.

Does not overwrite revision A evidence or claim device/hardware qualification.
Run without flags to generate schematic and stress decks; --record checks logs.
"""
from pathlib import Path
from dataclasses import replace
import argparse
import csv
import hashlib
import ltspice_windows_evidence as input_hash
import json
import subprocess
import make_bias_cut_eco as base

OUT = base.ROOT / 'pcb/bias_cut_revision_b'
SOURCES = {
    'pmos': 'https://www.diodes.com/datasheet/download/DMP3098L.pdf',
    'diode': 'https://www.vishay.com/docs/88586/es1.pdf',
    'resistor': 'https://www.vishay.com/docs/20043/crcwhpe3.pdf',
}


def parts():
    changes = {
        'Q50': dict(value='DMP3098L-7', nets={'1':'BC_GATE','2':'VDD_IN','3':'PASS_OUT'},
                    mpn='DMP3098L-7', mpn_source=SOURCES['pmos'],
                    note='Candidate; single pass PMOS; pin 1 G, 2 S, 3 D; SOA pending'),
        'D50': dict(lib='Device:D', value='ES1D-E3/61T',
                    footprint='Diode_SMD:D_SMA', nets={'1':'VDD_SR','2':'D_ANODE'},
                    rating='200V 1A', mpn='ES1D-E3/61T', mpn_source=SOURCES['diode'],
                    note='Series reverse blocking; pin 1 cathode; hot leakage is not zero'),
        'R50': dict(value='10k', note='Default-off pull-up; selected PMOS gate charge still needs validation'),
        'R57': dict(value='2.2k', rating='0.75W at 70C subject to PCB thermal conditions',
                    mpn='CRCW12062K20FKEAHP', mpn_source=SOURCES['resistor'],
                    note='Slow hold discharge only. Q41/REG fast crowbar remains mandatory'),
        'R58': dict(note='Passive bleed when independent 5V is absent; nominal tau 1.11s'),
        'R62': dict(rating='0.75W conditional', mpn='CRCW12061K00FKEAHP',
                    mpn_source=SOURCES['resistor'], note='Bench-only dummy load; remove on integration'),
    }
    ps = [replace(p, **changes.get(p.ref, {})) for p in base.parts() if p.ref not in ('Q51','Q55')]
    ps.append(base.Part('R59','Device:R','22R',base.R1206,125,60,
                       {'1':'PASS_OUT','2':'D_ANODE'},'0.75W conditional; pulse qualification OPEN',
                       'Startup limiter, 1%; verify pulse curve and real gate transition',
                       mpn='CRCW120622R0FKEAHP',mpn_source=SOURCES['resistor']))
    return [base.snap(p) for p in ps]


def deck(vin=15, load=1000, reverse=0, enabled=True):
    # Deliberately a power-path screening model. No fake vendor MOS model.
    control = 'PULSE(0 5 1m 10n 10n 19m 1)' if enabled else '0'
    injection = f'VREV VDD_SR 0 {reverse}\n' if reverse else ''
    return f'''Revision B POWER PATH SCREEN ONLY - not a controller/device model
VIN VDD_IN 0 {vin}
VEN EN 0 {control}
S50 VDD_IN PASS_OUT EN 0 PASS
DBODY PASS_OUT VDD_IN BODY
R59 PASS_OUT D_ANODE 22
D50 D_ANODE VDD_SR RECT
R57 VDD_SR DIS 2200
S54 DIS 0 EN 0 DISCHARGE
R58 VDD_SR 0 100k
R62 VDD_SR 0 {load}
C54 VDD_SR 0 11.1u
{injection}.model PASS SW(Ron=0.07 Roff=1e10 Vt=2.5)
.model DISCHARGE SW(Ron=0.05 Roff=1e10 Vt=2.5)
* Negative control makes discharge on while pass is off.
* Implement this with swapped control terminals below via generation.
.model BODY D(Is=1n Rs=0.1)
* Generic diode; VF/IR bounds are checked analytically, not extracted here.
.model RECT D(Is=1n N=1.5 Rs=0.05 Cjo=10p BV=200)
.tran 0 100m 0 2u uic
.options plotwinsize=0
.meas tran input_peak MIN I(VIN)
.meas tran reverse_peak MAX I(VIN) FROM 5m TO 19m
.meas tran enabled_v AVG V(VDD_SR) FROM 18m TO 19m
.meas tran discharge_power MAX (V(VDD_SR,DIS)*V(VDD_SR,DIS)/2200) FROM 25m TO 95m
.meas tran residual_v FIND V(VDD_SR) AT=95m
.meas tran limiter_energy INTEG (V(PASS_OUT,D_ANODE)*V(PASS_OUT,D_ANODE)/22) FROM 1m TO 5m
.end
'''.replace('S54 DIS 0 EN 0 DISCHARGE','BNEG NEG 0 V=5-V(EN)\nS54 DIS 0 NEG 0 DISCHARGE')


CASES = {
    'startup': dict(),
    'no_dummy_load': dict(load=1e12),
    'low_input_30ma_equivalent': dict(vin=14.25,load=430),
    'low_input_35ma_equivalent': dict(vin=14.25,load=360),
    'low_input_50ma_equivalent': dict(vin=14.25,load=240),
    'reverse18_off': dict(reverse=18,enabled=False),
    'reverse24_off': dict(reverse=24,enabled=False),
    'reverse24_on': dict(reverse=24),
    'reverse24_input_dead': dict(vin=0,reverse=24,enabled=False),
    'reverse24_input_dead_enable_high': dict(vin=0,reverse=24),
}


def digest(p):
    """Hash LTspice simulated input CRLF and evidence log bytes separately.

    Existing Rev-B reports record actual Windows CRLF deck *and log* hashes.
    Git normalizes text line endings to LF; no new simulation is claimed.
    """
    if p.suffix.lower() in {".cir", ".log"}:
        return input_hash.original_windows_deck_sha256(p)
    return input_hash.actual_file_sha256(p)


def generate():
    OUT.mkdir(parents=True,exist_ok=True)
    symbols = base.build_symbols()
    symbols['Device:D'] = base.d0.rename_symbol(
        base.d0.extract_symbol(base.symbol_libs()/'Device.kicad_sym','D'),'Device:D')
    ps = parts()
    base.validate(ps,symbols)
    drawing = base.schematic(symbols,ps).replace('make_bias_cut_eco.py','bias_cut_revision_b.py')
    drawing = drawing.replace('(rev "A")','(rev "B-CANDIDATE")').replace(
        'P-MOS is TO_SELECT: no P-channel datasheet in the repository.',
        'DMP3098L-7 / ES1D candidates; pulse, REG hold energy and controller supply margin OPEN.')
    sch = OUT/'bias_cut_revision_b.kicad_sch'
    sch.write_text(drawing,encoding='utf-8')
    (OUT/'bias_cut_revision_b.kicad_pro').write_text(base.project_file(),encoding='utf-8')
    with (OUT/'BOM.csv').open('w',newline='',encoding='utf-8') as fh:
        writer=csv.writer(fh)
        writer.writerow(['Reference','Value','Footprint','MPN','Source','Rating','Note'])
        for p in base.physical_components(ps):
            writer.writerow([p.ref,p.value,p.footprint,p.mpn,p.mpn_source,p.rating,p.note])
    cli=str(base.kicad_cli())
    net=OUT/'bias_cut_revision_b.net'
    subprocess.run([cli,'sch','export','netlist',str(sch),'-o',str(net)],check=True)
    subprocess.run([cli,'sch','erc','--severity-all','--format','json',str(sch),'-o',str(OUT/'erc.json')],check=True)
    violations=base.d0.erc_violations(OUT/'erc.json',source=sch.name,newer_than=sch)
    if violations:
        raise RuntimeError(violations)
    actual=base.netlist_nodes(net.read_text(encoding='utf-8'))
    for name, required in {
        'PASS_OUT':{('Q50','3'),('R59','1')},
        'D_ANODE':{('R59','2'),('D50','2')},
        'BC_GATE':{('Q50','1'),('R50','2'),('Q52','3'),('TP23','1')},
    }.items():
        assert actual[name]==required,(name,actual[name])
    for name, kwargs in CASES.items():
        (OUT/f'{name}.cir').write_text(deck(**kwargs),encoding='utf-8')
    print(f'Generated revision B schematic, BOM, clean ERC and {len(CASES)} power-path decks')


def record():
    results={}
    for name in CASES:
        cir,log=OUT/f'{name}.cir',OUT/f'{name}.log'
        if log.stat().st_mtime_ns < cir.stat().st_mtime_ns:
            raise RuntimeError(f'Stale log: {name}')
        text=log.read_text(encoding='utf-8',errors='replace')
        measures=base.parse_meas(text)
        if len(measures)!=6 or 'Fatal Error' in text:
            raise RuntimeError(f'Incomplete run: {name}: {measures}')
        results[name]={'deck_sha256':digest(cir),'log_sha256':digest(log),'measures':measures}
    checks={
        'startup_below_0_724a':-results['startup']['measures']['input_peak']<0.724,
        'low_input_30ma_above_12_6v':results['low_input_30ma_equivalent']['measures']['enabled_v']>12.6,
        'no_dummy_discharged_below_3_63v_at_95ms':results['no_dummy_load']['measures']['residual_v']<3.63,
        'reverse24_discharge_below_0_27w':results['reverse24_off']['measures']['discharge_power']<0.27,
        'all_reverse_cases_below_100ua_in_this_model':all(abs(results[n]['measures']['reverse_peak'])<100e-6 for n in CASES if n.startswith('reverse')),
    }
    report={'revision':'B-CANDIDATE','evidence':'BEHAVIOURAL_POWER_PATH_SCREEN',
            'hardware_qualified':False,'fabrication_approved':False,'full_control_simulated':False,
            'checks':checks,'cases':results,'sources':SOURCES,
            'analytic_bounds':{'inrush_a':15.75/(22*.99),'r57_24v_w':24**2/(2200*.99),
                               'bias_min_30ma_v':14.25-.92-.03*(22*1.01+.07),
                               'single_pair_10v_gate_budget_a':2*83e-9*200620+1.5e-3,
                               'bias_min_50ma_v':14.25-.92-.05*(22*1.01+.07),
                               'diode_max_reverse_100c_a':100e-6},
            'open':['REG crowbar hold energy after slower bias discharge',
                    'actual UCC24624 bias current, Qg*f and regulator headroom',
                    'R59 pulse curve / repetition / thermal layout and PMOS SOA',
                    'real gate charge, POR slow ramp, independent 5V loss and logic hazards',
                    'floating input leakage charging; full SR commutation and hardware H0-H5']}
    (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(checks,indent=2))
    if not all(checks.values()):
        raise SystemExit('Candidate screen failed')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--record',action='store_true')
    args=parser.parse_args()
    record() if args.record else generate()
