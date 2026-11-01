import numpy as np
from scipy.optimize import least_squares

# ---- data from design/v2/sr_device_v3_calibration.json (digitized) ----
V  = np.array([0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 40.0])
Ci = np.array([5380,5300,5200,4950,4790,4640,np.nan])
Co = np.array([6900,6600,6125,4950,3400,1500,np.nan])
Cr = np.array([783,700,604,406,192,38.5,27.0])

# fit Crss = cmin + c1 exp(-V/t1) + c2 exp(-V/t2)
def capfit(y, m):
    def res(p):
        cmin,c1,t1,c2,t2 = p
        pred = cmin + c1*np.exp(-V[:m]/t1) + c2*np.exp(-V[:m]/t2)
        return (pred-y[:m])/y[:m]
    p0=[10,400,1.0,400,8.0]
    lb=[0,1,0.05,1,0.5]; ub=[100,5000,10,5000,100]
    r=least_squares(res,p0,bounds=(lb,ub),xtol=1e-14,ftol=1e-14,max_nfev=200000)
    return r.x
p=capfit(Cr,7)
print("Cgd fit cmin,c1,t1,c2,t2 =",["%.6g"%x for x in p])
Vf=np.array([0.05,0.1,0.5,1,2,5,10,20,40])
pred=p[0]+p[1]*np.exp(-Vf/p[2])+p[3]*np.exp(-Vf/p[4])
print("V   data   model  err%")
for v,d,pr in zip(V,Cr,pred[:7]): print("%5.1f %6.1f %7.1f %6.1f"%(v,d,pr,100*(pr/d-1)))
print("at 40: %.1f"%pred[8])
# charge integral 0..20
from scipy.integrate import quad
C=lambda v: p[0]+p[1]*np.exp(-v/p[2])+p[3]*np.exp(-v/p[4])
Qgd=quad(C,0,20)[0]
print("Qgd 0..20V = %.2f nC"%(Qgd/1000))
print("Qgd 0..0.05V tail = %.3f nC"%(quad(C,0,0.05)[0]/1000))
# Qoss from Coss
Coss=np.array([6900,6600,6125,4950,3400,1500])
Vc=V[:6]
# integrate piecewise trapezoid with log interp for check
from scipy.interpolate import interp1d
f=interp1d(Vc,Coss,kind='linear')
print("Qoss 0..20 (linear interp) = %.1f nC"%(quad(lambda v: float(f(v)),0,20)[0]/1000))
