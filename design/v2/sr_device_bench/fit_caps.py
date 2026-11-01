import numpy as np
from scipy.optimize import least_squares

def model(p, V):
    Vk,A,B,Cmin,D1,t1,D2,t2 = p
    V=np.asarray(V,float); C=np.empty_like(V)
    lo=V<=Vk
    C[lo]=A-B*V[lo]
    d=V[~lo]-Vk
    C[~lo]=Cmin+D1*np.exp(-d/t1)+D2*np.exp(-d/t2)
    return C

def qfun(p, V):
    Vk,A,B,Cmin,D1,t1,D2,t2 = p
    V=np.asarray(V,float); Q=np.empty_like(V)
    lo=V<=Vk
    Q[lo]=A*V[lo]-B*V[lo]**2/2
    Qk=A*Vk-B*Vk**2/2
    d=V[~lo]-Vk
    Q[~lo]=Qk+Cmin*d+D1*t1*(1-np.exp(-d/t1))+D2*t2*(1-np.exp(-d/t2))
    return Q

def fit(Vd, Cd):
    def res(p):
        Vk,A,B,Cmin,D1,t1,D2,t2=p
        if Vk<=0 or t1<=0 or t2<=0 or D1<0 or D2<0 or Cmin<0 or B<0: return np.ones(len(Vd))*100
        # continuity: A-B*Vk == Cmin+D1+D2
        pen=100*(A-B*Vk-(Cmin+D1+D2))/Cd.mean()
        return np.concatenate([(model(p,Vd)-Cd)/Cd,[pen]])
    best=None
    for Vk0 in [1.5,2.5,3.5,5,7]:
        for t10 in [2,4,8]:
            for t20 in [10,20]:
                p0=[Vk0, 900, 50, 20, 300, t10, 500, t20]
                # enforce rough continuity by adjusting A
                p0[1]=p0[0]*0+p0[3]+p0[4]+p0[6]+p0[2]*Vk0
                try:
                    r=least_squares(res,p0,bounds=([0.5,10,0,0,0,0.3,0,1],[15,20000,3000,300,20000,40,20000,300]),xtol=1e-15,ftol=1e-15,max_nfev=50000)
                    if best is None or r.cost<best.cost: best=r
                except Exception as e: pass
    return best

CrV=np.array([0.5,1,2,5,10,20,40.]); CrC=np.array([783,700,604,406,192,38.5,27.])
CdV=np.array([0.5,1,2,5,10,20,40.]); CdC=np.array([6117,5900,5521,4544,3208,1461.5,833.])
for name,Vd,Cd in [("Cgd",CrV,CrC),("Cds",CdV,CdC)]:
    r=fit(Vd,Cd)
    p=r.x
    print(name,"Vk,A,B,Cmin,D1,t1,D2,t2 =",["%.6g"%x for x in p])
    print(" V     data    model   err%")
    for v,d,m in zip(Vd,Cd,model(p,Vd)): print("%5.1f %8.1f %8.1f %7.1f"%(v,d,m,100*(m/d-1)))
    print(" Q(20) = %.1f pC   Q(40)= %.1f pC"%(qfun(p,np.array([20.]))[0],qfun(p,np.array([40.]))[0]))
    print(" C(0.05)=%.1f  C(0)=%.1f"%(model(p,np.array([0.05]))[0],model(p,np.array([0.0]))[0]))
    print()
