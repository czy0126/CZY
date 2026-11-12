# -*- coding: utf-8 -*-
"""Maxwell 2025R2 *feasibility*: extend continuous Lr foil leads to region boundary.

True CAD connected two-turn spiral, but external 46mm copper leads and
stock ferrite make this an UNQUALIFIED solver experiment. It cannot prove
0.92uH/100A/100C/nonlinear N97/AC losses or release manufacture.
"""
import os,sys,shutil,json,hashlib,traceback
ROOT=r"D:\workshop\design_48v-2v"
RUN=os.path.join(ROOT,"design","v3","maxwell","local_runs")
SRC=os.path.join(RUN,"ELP38_Lr_REAL_CONNECTED_SPIRAL_CONCEPT_NOT_FOR_FAB.aedt")
TARGET=os.path.join(RUN,"ELP38_Lr_1A_EXTERNAL_LEADS_MAGNETOSTATIC_NOT_FOR_FAB.aedt")
LOG=os.path.join(RUN,"ELP38_Lr_1A_EXTERNAL_LEADS_MAGNETOSTATIC_result.json")
state={"kind":"LR_2TURN_EXTERNAL_LEADS_SOLVER_FEASIBILITY",
       "status":"STARTING","steps":[],"solver_completed":False,
       "material_oem_n97_100c_verified":False,
       "flux_and_L_I_extracted":False,
       "exterior_leads_manufacturable":False,
       "field_solution_converged":False,"hardware_fab_approved":False}
def write():
    with open(LOG,"w") as f:json.dump(state,f,indent=2)
def record(n):state["steps"].append(n);write()
def box(ed,name,x,y,z,sx,sy,sz,mat):
    ed.CreateBox(["NAME:BoxParameters","XPosition:=",str(x)+"mm",
        "YPosition:=",str(y)+"mm","ZPosition:=",str(z)+"mm",
        "XSize:=",str(sx)+"mm","YSize:=",str(sy)+"mm",
        "ZSize:=",str(sz)+"mm"],
       ["NAME:Attributes","Name:=",name,"Flags:=","",
        "Color:=","(194 138 65)","Transparency:=",0.2,
        "PartCoordinateSystem:=","Global",
        "MaterialValue:=", '"' + mat + '"',
        "SolveInside:=",True])
try:
    if os.path.exists(TARGET):raise RuntimeError("REFUSING to overwrite existing trial")
    shutil.copy2(SRC,TARGET);record("copied original connected spiral model")
    sys.path.append(r"D:\ANSYS Inc\v252\AnsysEM\PythonFiles\DesktopPlugin")
    import ScriptEnv
    ScriptEnv.Initialize("Ansoft.ElectronicsDesktop")
    oDesktop.OpenProject(TARGET)
    project=oDesktop.SetActiveProject(os.path.splitext(os.path.basename(TARGET))[0])
    design=project.SetActiveDesign("Lr_2turn_geometry_only")
    ed=design.SetActiveEditor("3D Modeler")
    copper="LR_SERIES_2TURN_COPPER"
    before=list(ed.GetObjectsInGroup("Solids"))
    if copper not in before:raise RuntimeError("Missing 2-turn copper body")
    # Two independent copper leads join the open spiral and terminate exactly
    # on region y=-60mm. Added 0.1mm overlap with original foil end planes.
    for idx,z in ((1,6.35),(2,7.71)):
        box(ed,"LR_EXTERNAL_LEAD_"+str(idx),4.17,-60,z,1.2,46.45,.30,"copper")
    ed.Unite(["NAME:Selections","Selections:=",
              "LR_SERIES_2TURN_COPPER,LR_EXTERNAL_LEAD_1,LR_EXTERNAL_LEAD_2"],
             ["NAME:UniteParameters","KeepOriginals:=",False])
    names=list(ed.GetObjectsInGroup("Solids"))
    state["solids_after_union"]=names
    if set(names)!={"I38_FERRITE_PROXY","E_BACK",copper}:
        raise RuntimeError("Lead union failed to produce ONE series-connected copper solid")
    record("one continuous physical copper conductor including two external leads")
    box(ed,"Region",-60,-60,-50,120,120,100,"vacuum")
    record("created explicit vacuum boundary meeting lead ends at y=-60")
    ends=[]
    for id in ed.GetFaceIDs(copper):
        c=[float(t) for t in ed.GetFaceCenter(id)]
        if abs(c[1]+60)<.001 and abs(c[0]-4.77)<.02:
            if abs(c[2]-6.50)<.02: ends.append(("IN",int(id),c))
            if abs(c[2]-7.86)<.02: ends.append(("OUT",int(id),c))
    state["contact_faces"]=ends
    if len(ends)!=2:raise RuntimeError("Copper ends did NOT meet region boundary")
    record("identified two external copper faces on region boundary")
    b=design.GetModule("BoundarySetup")
    for name,fid,xyz in ends:
        b.AssignCurrent(["NAME:LR_1A_"+name,"Faces:=",[fid],
            "Current:=","1A","IsSolid:=",True,
            "Point out of terminal:=",name=="OUT"])
        record("assigned 1A direct current "+name)
    a=design.GetModule("AnalysisSetup")
    a.InsertSetup("Magnetostatic",
        ["NAME:Setup1","MaximumPasses:=",3,"MinimumPasses:=",1,
         "MinimumConvergedPasses:=",1,"PercentRefinement:=",20,
         "SolveFieldOnly:=",False,"PercentError:=",5,
         "SolveMatrixAtLast:=",True])
    project.Save();record("saved region-boundary-excited Maxwell native project")
    validation=design.ValidateDesign()
    state["validation_result"]=bool(validation)
    state["validation_messages"]=list(oDesktop.GetMessages("","",0))
    if not validation:raise RuntimeError("Maxwell ValidateDesign failed")
    record("NATIVE DESIGN VALIDATION PASSED")
    analysis=design.Analyze("Setup1")
    state["analyze_return"]=str(analysis)
    state["solver_messages"]=list(oDesktop.GetMessages("","",0))
    if analysis not in (None,0):raise RuntimeError("Maxwell Analyze returned failure")
    state["solver_completed"]=True
    state["status"]="MAXWELL_1A_CONCEPT_SOLVER_RETURNED_NOT_ENGINEERING_SIGNOFF"
    project.Save();record("MAXWELL MAGNETOSTATIC SOLVER RETURNED")
except:
    state["status"]="MAXWELL_EXTERNAL_LEAD_TRIAL_FAILED_NOT_FOR_FAB"
    state["error"]=traceback.format_exc()
    try:state["messages"]=list(oDesktop.GetMessages("","",0))
    except:pass
finally:
    try:write()
    except:pass
    try:ScriptEnv.Shutdown()
    except:pass
