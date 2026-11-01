import sys,json,hashlib
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path('tools').resolve()))
import tank_metrics as m
p=Path('sim/v2/sr_tank_dual_v33.raw');t,d=m.load(p)
wins=m.periods(t,d['V(ga1)'],8); rows=[]
for a,b in wins:
 w=m.window(t,a,b);tt=t[w];i=d['I(VSa1)'][w];v=d['V(a1)'][w];ga=d['V(ga1)'][w];gb=d['V(gb1)'][w];pw=v*i
 rows.append({'E_off_A_uJ':m.integrate(tt,pw,(ga<=2))*1e6,'E_on_A_uJ':m.integrate(tt,pw,(ga>2))*1e6,'E_off_old_uJ':m.integrate(tt,pw,((ga<=2)&(gb<=2)))*1e6,'E_on_old_uJ':m.integrate(tt,pw,((ga>2)|(gb>2)))*1e6,'Irev_peak_A':float(i.max()),'Qrev_nC':m.integrate(tt,np.maximum(i,0))*1e9})
result={'per_period':rows,'mean':{k:float(np.mean([r[k] for r in rows])) for k in rows[0]},'max_irev_A':max(r['Irev_peak_A'] for r in rows),'windows':[]}
for a,b in [(400e-6,450e-6),(450e-6,475e-6),(475e-6,500e-6)]:
 w=m.window(t,a,b);tt=t[w];v=d['V(out)'][w];result['windows'].append({'start_us':a*1e6,'end_us':b*1e6,'Vout_time_average':m.integrate(tt,v)/(tt[-1]-tt[0]),'Vout_start':float(v[0]),'Vout_end':float(v[-1])})
manifest=json.loads(Path('design/baseline/baseline_manifest.json').read_text(encoding='utf-8-sig'));bad=[]
for e in manifest['entries']:
 f=Path(e['path'])
 if not f.exists() or hashlib.sha256(f.read_bytes()).hexdigest()!=e['sha256']:bad.append(e['path'])
result['manifest_entries']=len(manifest['entries']);result['manifest_mismatches']=bad
out=Path('design/review_20261031_round2/independent_metrics.json');out.write_text(json.dumps(result,indent=2));print(json.dumps({k:v for k,v in result.items() if k!='per_period'},indent=2))
