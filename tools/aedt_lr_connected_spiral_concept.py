# -*- coding: utf-8 -*-
"""Create an ACTUAL one-piece, two-loop rectangular spiral foil in AEDT 2025R2.

This is a physically connected *concept* winding, a better FEM starting point
than disconnected ring proxies. It is not a sourced N97 BH material, an OEM
winding, a 100A/16mm assembly qualification or proof of 0.92uH. Source frozen.
Execute using the installed ansysedt.exe -Iconic -RunScriptAndExit script.py.
"""
import hashlib
import json
import os
import shutil
import sys
import traceback

ROOT=r"D:\workshop\design_48v-2v"
SOURCE=os.path.join(ROOT,"hardware","dcx_main","maxwell",
                    "ELP38_Lr_2turn_0920uH_NATIVE_CONCEPT_NOT_FOR_FAB.aedt")
CONTRACT=os.path.join(ROOT,"design","v3","maxwell","diy_magnetics_concept.json")
OUT=os.path.join(ROOT,"design","v3","maxwell","local_runs")
TARGET=os.path.join(OUT,"ELP38_Lr_REAL_CONNECTED_SPIRAL_CONCEPT_NOT_FOR_FAB.aedt")
RECEIPT=os.path.join(OUT,"ELP38_Lr_REAL_CONNECTED_SPIRAL_CONCEPT_result.json")
EXPECTED_SOURCE_SHA="4ab265a0c95145979fa3a0f00d5f395d8a333f8d82c8fc06757587343e77e874"

s={"status":"STARTING","kind":"AEDT_REAL_SERIES_SPIRAL_CAD_TRIAL",
   "source_sha256":EXPECTED_SOURCE_SHA,"project_path":TARGET,"stage":[],
   "model_copper_connected":False,"material_N97_100c_verified":False,
   "manufacturer_winding_verified":False,"terminal_excitation_verified":False,
   "magnetostatic_solved":False,"l_vs_i_verified":False,"ac_loss_verified":False,
   "fabrication_approved":False}
def persist():
    with open(RECEIPT,"w") as f:json.dump(s,f,indent=2)
def step(name):
    s["stage"].append(name)
    persist()
def digest(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for b in iter(lambda:f.read(2**20),b""):h.update(b)
    return h.hexdigest()
def mm(x):return str(round(float(x),7))+"mm"

try:
    if not os.path.isdir(OUT):
        os.makedirs(OUT)
    if digest(SOURCE)!=EXPECTED_SOURCE_SHA:
        raise RuntimeError("Frozen original Maxwell CAD source changed")
    if os.path.exists(TARGET):
        raise RuntimeError("Existing spiral model will not be overwritten")
    with open(CONTRACT,"r") as fh:spec=json.load(fh)
    case=[c for c in spec["cases"] if c["id"]=="ELP38_Lr_2turn_0920uH"][0]
    if case["turns"]!=2 or case["gap_mm"]!=1.031 or case["type"]!="LR_ELP38":
        raise RuntimeError("Magnetic concept case changed")
    g=case["geometry"]
    shutil.copy2(SOURCE,TARGET)
    step("COPIED_HASH_LOCKED_AEDT_SOURCE")
    sys.path.append(r"D:\ANSYS Inc\v252\AnsysEM\PythonFiles\DesktopPlugin")
    import ScriptEnv
    ScriptEnv.Initialize("Ansoft.ElectronicsDesktop")
    oDesktop.OpenProject(TARGET)
    proj=oDesktop.SetActiveProject(os.path.splitext(os.path.basename(TARGET))[0])
    design=proj.SetActiveDesign("Lr_2turn_geometry_only")
    ed=design.SetActiveEditor("3D Modeler")
    before=list(ed.GetObjectsInGroup("Solids"))
    for x in ("LR_OUTER_1","LR_OUTER_2"):
        if x not in before:raise RuntimeError("Missing original disconnected foil: "+x)
    ed.Delete(["NAME:Selections","Selections:=","LR_OUTER_1,LR_OUTER_2"])
    step("REMOVED_DISCONNECTED_RECTANGULAR_RINGS")
    xx=(float(g["center_leg_x_mm"])+2*float(g["winding_clearance_x_mm"])
        +float(g["foil_width_radial_mm"]))/2
    yy=(float(g["core_depth_y_mm"])+2*float(g["winding_clearance_y_mm"])
        +float(g["foil_width_radial_mm"]))/2
    z0=float(g["first_foil_center_z_mm"])
    # 2 full loops, advancing by one axial pitch per loop.
    pitch=float(g["foil_axial_pitch_mm"])
    points=[]
    for j in range(9):
        shape=((xx,-yy),(xx,yy),(-xx,yy),(-xx,-yy))[j%4]
        points.append((shape[0],shape[1],z0+j*pitch/4))
    # True one-piece open, continuous conductor (not 2 parallel annuli).
    args=["NAME:PolylineParameters","IsPolylineCovered:=",True,
          "IsPolylineClosed:=",False,
          ["NAME:PolylinePoints"]+[
              ["NAME:PLPoint","X:=",mm(x),"Y:=",mm(y),"Z:=",mm(z)]
              for x,y,z in points],
          ["NAME:PolylineSegments"]+[
              ["NAME:PLSegment","SegmentType:=","Line",
               "StartIndex:=",j,"NoOfPoints:=",2] for j in range(8)],
          ["NAME:PolylineXSection","XSectionType:=","Rectangle",
           "XSectionOrient:=","Auto",
           "XSectionWidth:=",mm(float(g["foil_width_radial_mm"])),
           "XSectionTopWidth:=",mm(float(g["foil_width_radial_mm"])),
           "XSectionHeight:=",mm(float(g["foil_thickness_z_mm"])),
           "XSectionNumSegments:=","0","XSectionBendType:=","Corner"]]
    ed.CreatePolyline(args,
      ["NAME:Attributes","Name:=","LR_SERIES_2TURN_COPPER",
       "Flags:=","","Color:=","(216 124 47)","Transparency:=",0.0,
       "PartCoordinateSystem:=","Global",
       "MaterialValue:=",'"copper"', "SolveInside:=",True])
    after=list(ed.GetObjectsInGroup("Solids"))
    s["solids"]=after
    s["source_contract_sha256"]=digest(CONTRACT)
    s["polyline_points"]=points
    s["foil_width_mm"]=float(g["foil_width_radial_mm"])
    s["foil_thickness_mm"]=float(g["foil_thickness_z_mm"])
    if not set(("I38_FERRITE_PROXY","E_BACK","LR_SERIES_2TURN_COPPER")).issubset(set(after)):
        raise RuntimeError("Polyline is not a solid conductor: "+repr(after))
    if len(after)!=3:
        raise RuntimeError("Unexpected extra/intersecting solids after spiral construction: "+repr(after))
    s["model_copper_connected"]=True
    step("ONE_CONTINUOUS_TWO_TURN_COPPER_SOLID_EXISTS")
    faces=list(ed.GetFaceIDs("LR_SERIES_2TURN_COPPER"))
    s["coil_face_count"]=len(faces)
    s["faces_near_ends"]=[]
    ends=(points[0],points[-1])
    for f in faces:
        try:
            c=[float(x) for x in ed.GetFaceCenter(f)]
            if min(sum((c[i]-end[i])**2 for i in range(3))**0.5 for end in ends)<2:
                s["faces_near_ends"].append({"face_id":f,"center":c})
        except Exception as exc:
            s["face_center_error"]=repr(exc)
            break
    proj.Save()
    step("NATIVE_MODEL_SAVED_CONNECTIVITY_ONLY_NO_SOLVE")
    s["status"]="ACTUAL_CONNECTED_SPIRAL_AEDT_MODEL_SAVED_NOT_FOR_FAB"
    s["project_sha256"]=digest(TARGET)
except:
    s["status"]="CONTINUOUS_SPIRAL_BUILD_FAILED_NOT_FOR_FAB"
    s["error"]=traceback.format_exc()
finally:
    try:persist()
    except:pass
    try:ScriptEnv.Shutdown()
    except:pass
