import numpy as np
from scipy.optimize import least_squares
# Diagram 5 (p7) visual read, ID at saturation, TJ=25C
Vt=np.array([2.7,3.0,3.5,4.5]); It=np.array([50,160,365,390.])
def sp(x,s): return np.where(x/s>40, x, s*np.log1p(np.exp(np.clip(x/s,-700,40))))
def istr(p,V,Imax):
    KP,Vz,pp,s=p[0],p[1],p[2],p[3]
    return 1/(1/(KP*sp(V-Vz,s)**pp)+1/Imax)
def res(p):
    KP,Vz,pp,s=p[0],p[1],p[2],p[3]
    Imax=p[4]
    pred=istr(p,Vt,Imax)
    r=(pred-It)/It
    # penalty: keep current negligible at 1.65 and <=3A at 2.2 (below plateau region)
    pen=[istr(p,np.array([1.65]),Imax)[0]/1.0,  # ~0
         max(0,istr(p,np.array([2.2]),Imax)[0]-3)/3]
    return np.concatenate([r,pen])
best=None
for Vz0 in [2.0,2.2,2.4]:
  for p0 in [2,4,6]:
    x0=[1000,Vz0,p0,0.06,450]
    r=least_squares(res,x0,bounds=([1,1.0,0.5,0.01,380],[1e6,2.65,15,0.3,1200]),xtol=1e-15,ftol=1e-15,max_nfev=200000)
    if best is None or r.cost<best.cost: best=r
p=best.x
print("KP,Vz,p,s,Imax =",["%.6g"%x for x in p])
for v,i in zip(Vt,It): print("Vgs=%.2f target %5.0f model %6.1f  err %+6.1f%%"%(v,i,istr(p,np.array([v]),p[4])[0],100*(istr(p,np.array([v]),p[4])[0]/i-1)))
for v in [1.65,2.0,2.2,2.5,2.8,3.0,3.5,4.5,10]:
    print("Isat(%4.2f)=%10.5g A"%(v,istr(p,np.array([v]),p[4])[0]))
