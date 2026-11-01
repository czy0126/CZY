"""Summarize actual local logs and RAW files; never treats numerical completion as hardware PASS."""
from pathlib import Path
import csv, hashlib, json, re
import numpy as np
from PyLTSpice import RawRead

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'design/v2'
OUT.mkdir(parents=True, exist_ok=True)

def measurements(name):
    p = ROOT / 'sim/v2' / (name + '.log')
    s = p.read_text(errors='replace')
    fatal = any(x in s.lower() for x in ['time step too small', 'singular matrix', 'error:'])
    if 'Total elapsed time' not in s or fatal:
        return {'status': 'INCOMPLETE_OR_NUMERICAL_FAILURE', 'log': str(p)}
    values = {}
    for m in re.finditer(r'Measurement: (\w+)\n(.*?)(?=\nMeasurement:|\Z)', s, re.S):
        values[m[1]] = [float(v) for v in re.findall(r'^\s+\d+\s+([-+\deE.]+)\s+', m[2], re.M)]
    if not values:
        for m in re.finditer(r'^(\w+):.*?=\s*([-+\deE.]+)', s, re.M):
            values[m[1]] = float(m[2])
    return {'status': 'SIMULATION_COMPLETED_NOT_HARDWARE_VALIDATED', 'values': values}

cases = ['controller', 'sr_good', 'sr_bad_order', 'sr_simultaneous',
         'sr_commutation_sweep', 'sr_timestep_check', 'sr_slow_off_negative',
         'integrated_pgd_sweep', 'integrated_oc_proxy', 'integrated_oc_long']
report = {n: measurements(n) for n in cases}
v = report['sr_commutation_sweep']['values']['reverse_peak']
w = report['sr_timestep_check']['values']['reverse_peak']
report['max_timestep_relative_change'] = max(abs(a-b)/abs(a) for a,b in zip(v,w))
rows=[]
raw = RawRead(ROOT/'sim/v2/sr_commutation_sweep.raw')
for step in range(6):
    t=np.asarray(raw.get_trace('time').get_wave(step))
    current=-np.asarray(raw.get_trace('I(Sa)').get_wave(step))
    vd=np.asarray(raw.get_trace('V(d1)').get_wave(step))
    ga=np.asarray(raw.get_trace('V(ga)').get_wave(step))
    gb=np.asarray(raw.get_trace('V(gb)').get_wave(step))
    m=(t>=10e-6)&(t<=20e-6)
    # Verify sign convention on a strongly conducting channel, far from edges.
    k=m&(ga>9)&(np.abs(vd)>.03)&(np.abs(vd)<.07)
    if np.any(k):
        assert np.mean(current[k]*vd[k])>0, 'Switch current polarity mismatch'
    qrev=np.trapezoid(np.maximum(current[m],0),t[m])/2
    overlap=np.trapezoid(((ga[m]>2)&(gb[m]>2)).astype(float),t[m])
    rows.append([step+1,step%2,[5.5,23,40][step//2],v[step],qrev*1e6,overlap*1e9])
report['model_hashes']={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in (ROOT/'models').glob('*.lib')}
(OUT/'verification_results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
with (OUT/'sr_commutation_results.csv').open('w',newline='',encoding='utf-8-sig') as f:
    writer=csv.writer(f);writer.writerow(['step','uncalibrated_PGD','off_delay_ns','reverse_peak_A','reverse_charge_per_cycle_uC','gate_overlap_above_2V_ns']);writer.writerows(rows)

try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(3,1,figsize=(10,7),sharex=True)
    for step,label in [(2,'PGD off'),(3,'Uncalibrated PGD on')]:
        t=np.asarray(raw.get_trace('time').get_wave(step)); m=(t>12.7e-6)&(t<16e-6)
        for ax,n,scale in [(axes[0],'V(d1)',1),(axes[1],'V(ga)',1),(axes[2],'I(Sa)',-1)]:
            ax.plot(t[m]*1e6,scale*raw.get_trace(n).get_wave(step)[m],label=label)
    for ax,y in zip(axes,['VDS (V)','VGS (V)','Channel I_D (A)']):ax.set_ylabel(y);ax.grid(alpha=.25)
    axes[0].legend();axes[2].axhline(0,color='black',lw=.6);axes[2].set_xlabel('Time (us)')
    fig.suptitle('SR surrogate commutation — 40 A peak, 200 kHz, 23 ns off delay\nPositive channel current = reverse power flow; not a validated device model')
    fig.tight_layout();fig.savefig(OUT/'sr_commutation.png',dpi=160);plt.close(fig)
except ImportError:
    pass
print(json.dumps({'cases':len(cases),'max_timestep_relative_change':report['max_timestep_relative_change'],'rows':rows},indent=2))
