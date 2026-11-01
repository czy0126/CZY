import numpy as np
from scipy.optimize import least_squares
# digitized Rds(on) vs VGS at ID=50A, 25C (calibration json)
V=np.array([3.0,3.5,4.0,4.5,6.0,8.0,10.0])
R=np.array([2.65,1.52,1.27,1.10,0.973,0.925,0.89])*1e-3   # table 1.1@4.5, 0.89@10
Vth=1.65
def model(p,V):
    R0,R1,t1,R2,t2=p
    return R0+R1*np.exp(-(V-Vth)/t1)+R2*np.exp(-(V-Vth)/t2)
def res(p):
    R0,R1,t1,R2,t2=p
    if min(R1,t1,R2,t2)<=0: return np.ones(len(V))*100
    return (model(p,V)-R)/R
best=None
for t10 in [0.15,0.25,0.4]:
  for t20 in [0.5,1.0,2.0]:
    p0=[0.75e-3,0.3e-3,t10,2e-3,t20]
    r=least_squares(res,p0,bounds=([0,0,0.02,0,0.1],[1e-3,0.1,2,0.1,10]),xtol=1e-15,ftol=1e-15,max_nfev=200000)
    if best is None or r.cost<best.cost: best=r
p=best.x
print("R0,R1,t1,R2,t2 =",["%.6g"%x for x in p])
for v,rr,mm in zip(V,R,model(p,V)): print("Vgs=%5.2f  data %.4f  model %.4f  err %+6.2f%%"%(v,rr*1e3,mm*1e3,100*(mm/rr-1)))
for v in [0,1.0,1.65,2.0,2.5,2.8,3.0,4.5,10,20]:
    g=1/model(p,np.array([v]))[0]
    print("Vgs=%5.2f Rds=%10.4g ohm  g=%9.4g S  g*0.45V=%.3g A (Isat raw)"%(v,g,v*g*0.45))
