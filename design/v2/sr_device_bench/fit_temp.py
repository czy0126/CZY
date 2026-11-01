import numpy as np
T=np.array([-40,0,25,50,75,100,125,150,175.]); f=np.array([0.79,0.91,1.0,1.10,1.21,1.34,1.48,1.64,1.82])
X=T-25
for deg in [2,3]:
    c=np.polyfit(X,f,deg)
    pred=np.polyval(c,X)
    print("deg",deg,"coef",c,"maxerr %.3f"%np.max(np.abs(pred-f)))
    for t,ff,pp in zip(T,f,pred): print("  %5.0f %.2f %.3f %+0.3f"%(t,ff,pp,pp-ff))
    print("  125C factor=%.3f (target 1.48), 175=%.3f (1.82), -40=%.3f (0.79)"%(np.polyval(c,100),np.polyval(c,150),np.polyval(c,-65)))
