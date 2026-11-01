import numpy as np
from scipy.optimize import least_squares
# genuine saturation readings (within plot scale): only low Vgs
Vt=np.array([2.7,3.0]); It=np.array([50.,160.])
# 3.5/4.5 are plot-edge (>365/390 A): treat as lower bounds
Vlb=np.array([3.5,4.5]); Ilb=np.array([365.,390.])
def sp(x,s): return np.where(x/s>40, x, s*np.log1p(np.exp(np.clip(x/s,-700,40))))
def istr(p,V):
    KP,Vz,pp,s,Imax=p
    return 1/(1/(KP*sp(V-Vz,s)**pp)+1/Imax)
def res(p):
    r=list((istr(p,Vt)-It)/It)
    r+=list(np.maximum(0,(Ilb-istr(p,Vlb))/Ilb))
    # keep off below 2.2V and small at 2.5 (~16A)
    r.append(istr(p,np.array([1.65]))[0]/0.5)
    r.append(max(0,istr(p,np.array([2.2]))[0]-3)/3)
    r.append((istr(p,np.array([2.5]))[0]-16)/16*0.3)
    return np.array(r)
best=None
for Vz0 in [1.6,1.9,2.1]:
  for p0 in [2,4,7]:
    x0=[2000,Vz0,p0,0.08,2000]
    try:
      r=least_squares(res,x0,bounds=([1,0.8,0.4,0.01,600],[1e7,2.6,15,0.3,1e5]),xtol=1e-15,ftol=1e-15,max_nfev=200000)
    except Exception as e:
      print(e); continue
    if best is None or r.cost<best.cost: best=r
p=best.x
print("KP,Vz,p,s,Imax =",["%.7g"%x for x in p])
for v,i in zip(np.concatenate([Vt,Vlb]),np.concatenate([It,Ilb])):
    m=istr(p,np.array([v]))[0]; print("Vgs=%.2f ref %5.0f model %9.2f err %+7.1f%%"%(v,i,m,100*(m/i-1)))
for v in [1.65,2.0,2.2,2.5,2.8,3.0,3.5,4.5,10,15]:
    print("Isat(%5.2f)=%12.5g A"%(v,istr(p,np.array([v]))[0]))
