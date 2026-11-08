"""Coupled bias/REG sensitivity study, never a UCC24624 vendor model.

The constant-capacitance PMOS and regulator current anchors are explicitly
unqualified at operating bias. Results cannot approve SR commutation or heat.
"""
import argparse
import hashlib
import json
import math
import re
from pathlib import Path
import bias_cut_revision_b as rev
import make_bias_cut_eco as base

OUT = base.ROOT/'pcb/bias_cut_revision_b/hold_validation'
CASES = {
    'finite_13ma': {},
    'finite_95ma': {'ireg': .095},
    'gate_slow_95ma': {'ireg': .095, 'cap_scale': 3, 'vt': 1},
    'backfeed_1k_13ma': {'rinj': 1000},
    'backfeed_100r_13ma': {'rinj': 100},
    'backfeed_100r_95ma': {'rinj': 100, 'ireg': .095},
}


def digest(path):
    """Hash the deck as the bytes LTspice opened: Windows CRLF, rebuilt from Git LF.

    Git stores these decks LF and CI checks them out LF (core.autocrlf=false),
    while the local run opened a CRLF copy.  Rebuild CRLF before hashing so the
    recorded hash is checkout-independent and still means "what the solver
    read"; same rule as tools/ltspice_windows_evidence.py (PR #56).
    Logs are not hashed this way: LTspice writes mixed CRLF/LF, so log identity
    is checked through parse_log() instead of a byte hash.
    """
    raw=Path(path).read_bytes().replace(b'\r\n',b'\n')
    return hashlib.sha256(raw.replace(b'\n',b'\r\n')).hexdigest()


def parse_log(text):
    """Parse .meas values, taking WHEN event times from the AT field, not =value."""
    measures=base.parse_meas(text)
    for field in ('gate_off_at','reg_off_at'):
        event=re.search(rf'^{field}:.*\bAT\s+([-+\d.eE]+)',text,re.M)
        if event is None:
            raise ValueError(f'Missing event timestamp: {field}')
        measures[field]=float(event.group(1))
    return measures


def budget():
    f=200620
    igate=2*83e-9*f
    rows=[]
    for vin,tol in ((15,.05),(16.5,.03)):
        for count in (1,4):
            for current,label in ((igate+.0015,'10V_datasheet_charge_reference'),(.05,'engineering_stress')):
                total=current*count
                rows.append({'vin_nom_v':vin,'input_tolerance':tol,'controllers_on_branch':count,
                             'scenario':label,'branch_a':total,
                             'vdd_estimate_v':vin*(1-tol)-.92-total*(22*1.01+.07),
                             'r59_w':total**2*22*1.01,
                             'scope':'VF=0.92V and Rds=0.07 are stated-condition references, NOT all-temperature bounds'})
    return {'hardware_qualified':False,'switching_frequency_hz':f,
            'gate_charge_reference_nc':83,'gate_charge_condition':'0 to 10V, VDS20V ID50A; not actual SR charge at 11.9V',
            'gate_current_per_controller_a':igate,'bias_reference_a':igate+.0015,
            'reg_characterized_load_a':.03,'within_30ma_characterized_load':igate<=.03,
            'engineering_reg_target_a':.024,'target_max_charge_per_fet_nc':.024/(2*f)*1e9,
            'frequency_at_30ma_using_83nc_hz':.03/(2*83e-9),
            'low_qg_candidate':{
                'mpn':'BSC022N04LS6','status':'BENCH_COMPARISON_CANDIDATE_NOT_APPROVED_REPLACEMENT',
                'datasheet':'https://www.infineon.com/assets/row/public/documents/24/49/infineon-bsc022n04ls6-datasheet-en.pdf',
                'qg_10v_typ_nc':28,'qg_max_nc':None,'rds_10v_max_ohm':.0022,
                'typ_gate_current_a':2*28e-9*f,
                'engineering_double_typ_gate_current_a':2*56e-9*f,
                'scope':'2x typical is an engineering sensitivity, NOT a manufacturer maximum or guaranteed 11.9V charge.',
                'required':['Check actual gate charge at SR VDS / 11.9V / temperature',
                            'Check hot RMS conduction losses, commutation and physical land pattern'],
                'reference_extra_loss_100a_w':4*(100/4)**2*(.0022-.001),
                'loss_scope':'25C resistance comparison; ideal flat 25A per pair with alternate conduction, NOT actual resonant RMS or hot loss'},
            'decision':'Do not freeze existing SR pairing at full frequency; separate branches do not solve internal REG load capability.',
            'rows':rows,
            'sources':['references/datasheets/ucc24624.txt section 8.3.2 and 7.5',
                       'references/datasheets/bsc010n04ls6.txt gate charge table'],
            'next':'Verify actual SR Qg at gate voltage and temperature; prefer low-Qg FET <=59.82nC engineering target including margin, or qualify external buffer. Do not feed external power into REG without approval from device documentation.'}


def deck(ireg=.013,rinj=None,cap_scale=1,vt=2.1):
    inject='' if rinj is None else f'VINJ INJ 0 PWL(0 0 19.999m 0 20m 18)\nD_INJ INJ RINJ BODY\nRINJ RINJ VDD_SR {rinj}\n'
    return f'''Coupled bias and REG sensitivity - no vendor model, no SR gate switching
VIN VDD_IN 0 15
VFAULT FAULT 0 PULSE(0 5 20m 10n 10n 1 2)
* 4us is an assumed command delay, not a verified controller delay.
VEN EN 0 PWL(0 5 20.004m 5 20.00401m 0)
VDIS DIS_EN 0 PWL(0 0 20.006m 0 20.00601m 5)
R50 VDD_IN BC_GATE 10k
S52 BC_GATE 0 EN 0 PULL
Cgs BC_GATE VDD_IN {861e-12*cap_scale}
Cgd BC_GATE PASS_OUT {147e-12*cap_scale}
S50 VDD_IN PASS_OUT VDD_IN BC_GATE PASS
DBODY PASS_OUT VDD_IN BODY
R59 PASS_OUT D_ANODE 22
D50 D_ANODE VDD_SR RECT
C54 VDD_SR 0 11.1u
R58 VDD_SR 0 100k
R57 VDD_SR DIS 2200
S54 DIS 0 DIS_EN 0 PULL
* Pass regulator conserves power: current is drawn from VDD, not ground.
* Arbitrary smooth current-limited law, not an actual foldback curve.
BREG VDD_SR REG I=limit((min(11,V(VDD_SR)-0.2)-V(REG))*1,0,{ireg})
BQUIET VDD_SR 0 I=0.0015*limit(V(VDD_SR)/5,0,1)
CREG REG 0 2.3u
RREG REG 0 100k
R44 REG CROW 4.7
S41 CROW 0 FAULT 0 CROWBAR
{inject}.model PULL SW(Ron=2 Roff=1e10 Vt=2.5)
.model CROWBAR SW(Ron=.048 Roff=1e10 Vt=2.5)
.model PASS SW(Ron=.07 Roff=1e10 Vt={vt} Vh=-.1)
.model BODY D(Is=1n Rs=.1)
.model RECT D(Is=1n N=1.5 Rs=.05 Cjo=10p BV=200)
.tran 0 100m 0 1u
.options plotwinsize=0
.meas tran reg_before AVG V(REG) FROM 18m TO 19m
.meas tran gate_off_at WHEN V(VDD_IN,BC_GATE)={vt} FALL=1 TD=20m
.meas tran reg_off_at WHEN V(REG)=3.63 FALL=1 TD=20m
.meas tran pass_energy INTEG (V(VDD_SR,REG)*I(BREG)) FROM 20m TO 100m
.meas tran r44_energy INTEG (V(REG,CROW)*V(REG,CROW)/4.7) FROM 20m TO 100m
.meas tran q41_energy INTEG (V(CROW)*V(CROW)/.048) FROM 20m TO 100m
.meas tran reg_pass_power_end AVG (V(VDD_SR,REG)*I(BREG)) FROM 90m TO 100m
.meas tran vdd_end AVG V(VDD_SR) FROM 90m TO 100m
.meas tran reg_end AVG V(REG) FROM 90m TO 100m
.end
'''


def energy_budget(vdd=15.75, vreg=11.9, cap_factor=1.2, delay_s=200e-6):
    # Engineering capacitance +20% sensitivity, not a selected-bank guarantee.
    stored=.5*cap_factor*(11.1e-6*vdd*vdd+2.3e-6*vreg*vreg)
    series_power=vdd*vdd/(4*22*.99)
    return {'stored_j':stored,'series_transfer_max_w':series_power,
            'assumed_isolation_delay_s':delay_s,'pre_isolation_j':series_power*delay_s,
            'conditional_total_j':stored+series_power*delay_s,
            'conditions':'No external backfeed; no uncounted stored energy or path bypassing R59; nonnegative downstream voltage; bounded delay; cap +20% assumption.',
            'not_a_junction_temperature_bound':True,'continuous_backfeed_has_finite_bound':False}


def generate():
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'bias_budget.json').write_text(json.dumps(budget(),indent=2)+'\n',encoding='utf-8')
    for name,args in CASES.items():
        (OUT/f'{name}.cir').write_text(deck(**args),encoding='utf-8')
    print(f'Generated {len(CASES)} coupled sensitivity decks and bias budget')


def record():
    runs={}
    for name,args in CASES.items():
        cir,log=OUT/f'{name}.cir',OUT/f'{name}.log'
        if cir.read_text(encoding='utf-8')!=deck(**args) or log.stat().st_mtime_ns<cir.stat().st_mtime_ns:
            raise ValueError(f'Stale evidence: {name}')
        text=log.read_text(encoding='utf-8',errors='replace')
        m=parse_log(text)
        if len(m)!=9 or any(not math.isfinite(v) for v in m.values()) or 'tolerance relaxed' in text.lower():
            raise ValueError(f'Incomplete measures {name}: {m}')
        runs[name]={'measures':m,'deck_sha256':digest(cir),'log_sha256':rev.digest(log),
                    'gate_delay_s':m['gate_off_at']-.02,'reg_delay_s':m['reg_off_at']-.02}
    checks={
        'reg_initialized_all':all(r['measures']['reg_before']>10 for r in runs.values()),
        'reg_crowbar_crosses_threshold_all':all(0<r['reg_delay_s']<50e-6 for r in runs.values()),
        'finite_supply_decays':all(runs[n]['measures']['vdd_end']<1 for n in ('finite_13ma','finite_95ma','gate_slow_95ma')),
        'continuous_injection_remains_powered':runs['backfeed_100r_13ma']['measures']['vdd_end']>10,
        'slow_gate_increases_delay':runs['gate_slow_95ma']['gate_delay_s']>runs['finite_95ma']['gate_delay_s'],
        'dissipation_nonnegative':all(r['measures'][n]>=0 for r in runs.values() for n in ('pass_energy','q41_energy','r44_energy')),
    }
    report={'evidence':'COUPLED_SENSITIVITY_NOT_VENDOR_OR_HARDWARE','hardware_qualified':False,
            'full_control_qualified':False,'thermal_qualified':False,'cases':runs,
            'checks':checks,'energy_budget':energy_budget(),
            'limitations':['Fixed Cgs/Cgd is not a nonlinear gate-charge bound.',
                           '13mA/95mA regulator anchors not guaranteed at simulated bias.',
                           'Q41 and logic command are simplified; actual filters, SR VGS and commutation absent.',
                           'REG pass energy excludes quiescent loss; sum is not IC thermal response.',
                           'No capacitor DC bias/temperature/tolerance model or external parasitic sources.',
                           'log_sha256 records the local Windows log bytes; committed-log identity is checked by parse_log() because LTspice writes mixed CRLF/LF.']}
    (OUT/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(checks,indent=2))
    if not all(checks.values()):
        raise SystemExit('Sensitivity sanity checks failed')


if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('--record',action='store_true')
    args=ap.parse_args()
    record() if args.record else generate()
