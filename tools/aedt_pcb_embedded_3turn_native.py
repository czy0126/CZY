# -*- coding: utf-8 -*-
"""Build REAL editable Ansys Maxwell3D from the accepted six-layer KiCad coil.

Reconstructs the actual *source-bound* three-turn, two-parallel-layer-per-turn
R0.8 milled-slot, four-PTH-per-transition PCB winding. Native geometry is
NOT the earlier artificial single-wire 2-turn spiral, and has no fabricated
measured 100 C N97 B-H. Copper traces have actual width/70um thickness,
all eight transition and two terminal plated barrels are hollow shells,
and the nominal ELP38 ferrite has a nominal analytical 2.356mm center gap.
A 1A magnetostatic *geometry feasibility* setup may be analysed in a
separate copy. This project is NOT actual hot L(I), 200kHz AC loss or fab.

python tools/aedt_pcb_embedded_3turn_native.py --preflight
"D:\\ANSYS Inc\\v252\\AnsysEM\\ansysedt.exe" -Iconic -RunScriptAndExit "<this_script>"

If run as AEDT ScriptEnv, do not pass --preflight.
"""
import hashlib,json,math,os,re,sys,time,traceback

ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:sys.path.insert(0,ROOT)
TOOL=os.path.join(ROOT,"tools")
if TOOL not in sys.path:sys.path.insert(0,TOOL)
import pcb_embedded_lr_rounded_core_via_array as W

CONF=W.CONF
CORE=os.path.join(ROOT,"design","v3","maxwell","diy_magnetics_concept.json")
PCB=W.PCB
TARGET=os.path.join(ROOT,"hardware","dcx_main","maxwell",
  "ELP38_Lr_PCB_EMBEDDED_3TURN_6LAYER_4PTH_NATIVE_GEOMETRY_NOT_FOR_FAB.aedt")
RECEIPT=os.path.join(ROOT,"hardware","dcx_main","maxwell",
  "ELP38_Lr_PCB_EMBEDDED_3TURN_6LAYER_4PTH_NATIVE_GEOMETRY_NOT_FOR_FAB.evidence.json")
SOURCE_CODE=os.path.abspath(__file__)
CASE_ID="ELP38_Lr_3turn_0920uH"
LAYERS=("F.Cu","In1.Cu","In2.Cu","In3.Cu","In4.Cu","B.Cu")
COPPER_Z={"B.Cu":4.40,"In4.Cu":4.72,"In3.Cu":5.04,
          "In2.Cu":5.35,"In1.Cu":5.66,"F.Cu":5.93}
BOARD_Z0=4.40
BOARD_THICK=1.60
# one lot of copper hollows: 25um trial PTH barrel; manufacturer NOT verified
PLATING_MM=.025
CORE_MATERIAL="ferrite"  # generic stock placeholder; NEVER call this actual N97 100 C

def digest(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for block in iter(lambda:f.read(2**20),b""):h.update(block)
    return h.hexdigest()

def canonical(path):
    return hashlib.sha256(open(path,"rb").read().replace(b"\r\n",b"\n")).hexdigest()

def mm(v):
    return "%.7gmm"%float(v)

def label(s):
    return re.sub(r"[^a-zA-Z0-9_]","_",s)

def preflight():
    if os.path.exists(TARGET):
        raise RuntimeError("REFUSE overwrite existing native 3-turn FEM CAD")
    body,report=W.contents()
    if open(PCB,"r",encoding="utf-8").read()!=body:
        raise RuntimeError("LIVE six-layer KiCad BOARD differs from source-generated geometry")
    trial=json.load(open(CONF,"r",encoding="utf-8"))
    spec=json.load(open(CORE,"r",encoding="utf-8"))
    items=[x for x in spec["cases"] if x["id"]==CASE_ID]
    if len(items)!=1 or items[0]["turns"]!=3 or items[0]["type"]!="LR_ELP38":
        raise RuntimeError("No reviewed three-turn ELP38 design-owned core geometry")
    case=items[0]
    if abs(case["gap_mm"]-2.356)>1e-6 or abs(case["target_inductance_uH"]-.92)>1e-6:
        raise RuntimeError("3-turn gap/target source changed; require new engineering review")
    if trial["qualification"]["real_tdk_n97_100c_nonlin_BH"] or trial["qualification"]["fabrication_approved"]:
        raise RuntimeError("unverified vendor/copper data marked qualified")
    if trial["board"]["layers"]!=list(LAYERS) or trial["board"]["nominal_thickness_mm"]!=BOARD_THICK:
        raise RuntimeError("Six-layer expected physical PCB stack mismatch")
    if abs(trial["board"]["copper_thickness_per_layer_mm"]-.07)>1e-8:
        raise RuntimeError("FEM layer copper thickness no longer matches actual KiCad trial")
    # Exact source KiCad primitive geometry is used; never reuse old proxy rings.
    ss=re.findall(
        r'\(segment \(start ([\d.\-]+) ([\d.\-]+)\) \(end ([\d.\-]+) ([\d.\-]+)\) '
        r'\(width ([\d.\-]+)\) \(layer "([^"]+)"\) \(net 1\)',body)
    vs=re.findall(r'\(via \(at ([\d.\-]+) ([\d.\-]+)\) \(size ([\d.\-]+)\) '
                  r'\(drill ([\d.\-]+)\) \(layers "F.Cu" "B.Cu"\)',body)
    ps=re.findall(r'\(footprint "Lr_Terminal:Embedded_Lr_External_Terminal" '
                  r'\(layer "F.Cu"\)\s+\(at ([\d.\-]+) ([\d.\-]+)\)',body)
    if len(ss)!=46 or len(vs)!=8 or len(ps)!=2:
        raise RuntimeError("expected 46 copper segments/8 transition PTH/2 terminal PTH")
    for x,y,xx,yy,w,ly in ss:
        if ly not in LAYERS or abs(float(w)-2.5)>1e-9:
            raise RuntimeError("unexpected segment material/layer/width")
        if abs(float(x)-float(xx))>1e-7 and abs(float(y)-float(yy))>1e-7:
            raise RuntimeError("diagonal conductor not supported by exact box extrusion")
    vias=[(float(x),float(y),float(outer),float(drill)) for x,y,outer,drill in vs]
    ports=[(float(x),float(y),1.8,.8) for x,y in ps]
    if any(abs(drill-.35)>1e-8 or abs(outer-.8)>1e-8 for _,_,outer,drill in vias):
        raise RuntimeError("transition via dimensions no longer match native KiCad")
    if abs(BOARD_Z0+BOARD_THICK-(COPPER_Z["F.Cu"]+.07))>1e-8:
        raise RuntimeError("F.Cu upper plane no longer matches board top")
    return case,trial,ss,vias,ports

def box(ed,name,x,y,z,dx,dy,dz,material="copper",transparency=.05):
    ed.CreateBox(["NAME:BoxParameters","XPosition:=",mm(x),"YPosition:=",mm(y),
                  "ZPosition:=",mm(z),"XSize:=",mm(dx),"YSize:=",mm(dy),
                  "ZSize:=",mm(dz)],
        ["NAME:Attributes","Name:=",name,"Flags:=","",
         "Color:=","(204 128 54)" if material=="copper" else "(142 149 125)",
         "Transparency:=",transparency,"PartCoordinateSystem:=","Global",
         "MaterialValue:=",'"'+material+'"',"SolveInside:=",True])
    return name

def cyl(ed,name,x,y,z,r,height,material="copper"):
    ed.CreateCylinder(
        ["NAME:CylinderParameters","XCenter:=",mm(x),"YCenter:=",mm(y),
         "ZCenter:=",mm(z),"Radius:=",mm(r),"Height:=",mm(height),
         "WhichAxis:=","Z","NumSides:=",0],
        ["NAME:Attributes","Name:=",name,"Flags:=","",
         "Color:=","(204 128 54)","Transparency:=",0,
         "PartCoordinateSystem:=","Global",
         "MaterialValue:=",'"'+material+'"',"SolveInside:=",True])
    return name

def unite(ed,pieces):
    ed.Unite(["NAME:Selections","Selections:=",",".join(pieces)],
             ["NAME:UniteParameters","KeepOriginals:=",False])

def create():
    state={"schema":"ACTUAL_KICAD_PCB_6LAYER_3TURN_AEDT_GEOMETRY_V1",
      "status":"STARTING",
      "source_kicad_lf_sha256":canonical(PCB),
      "source_rounded_config_lf_sha256":canonical(CONF),
      "source_core_contract_lf_sha256":canonical(CORE),
      "source_script_lf_sha256":canonical(SOURCE_CODE),
      "mesh_solved":False,"bias_1a_solved":False,
      "real_N97_100c_nonlinear_BH_applied":False,
      "real_100A_L_I_verified":False,"200kHz_AC_loss_verified":False,
      "ferrite_core_mechanical_approved":False,
      "plated_through_hole_25um_manufacturer_verified":False,
      "16mm_assembly_qualified":False,"fabrication_approved":False,
      "warnings":[
        "Six copper layer z and cylindrical PTH plating are conceptual 3D extrusions of actual KiCad coordinates; dielectric/FR4 & rounded slot arcs are NOT yet modeled as solids",
        "Core ELP38 dimensions and 2.356mm centre gap are design-owned concept, not OEM 3D verified",
        "Stock ferrite is not manufacturer N97 100C nonlinear B-H",
        "No AC proximity, skin or gap fringing solver result",
        "External long terminal leads are artificial for future current injection and will affect inductance",
        "All copper-connection current crowding, pad neck, actual 25um barrel and 4-via sharing unqualified",
        "Actual T1..T4 and CT multiwinding turn/DOT/isolation absent"]}

    def store():
        with open(RECEIPT,"w",encoding="utf-8") as f:
            json.dump(state,f,ensure_ascii=False,indent=2);f.write("\n")

    try:
        case,trial,ss,vias,ports=preflight()
        state["actual_kicad_segments"]=len(ss)
        state["real_kicad_transition_PTH"]=len(vias)
        state["real_kicad_external_terminals"]=len(ports)
        state["six_layer_z_bottom_mm"]=COPPER_Z
        state["pcb_stack_z0_and_height_mm"]=[BOARD_Z0,BOARD_THICK]
        store()
        os.makedirs(os.path.dirname(TARGET),exist_ok=True)
        sys.path.append(r"D:\ANSYS Inc\v252\AnsysEM\PythonFiles\DesktopPlugin")
        import ScriptEnv
        ScriptEnv.Initialize("Ansoft.ElectronicsDesktop")
        project=oDesktop.NewProject()
        project.InsertDesign("Maxwell 3D","Lr_PCB_3turn_geometry","Magnetostatic","")
        design=project.SetActiveDesign("Lr_PCB_3turn_geometry")
        ed=design.SetActiveEditor("3D Modeler")
        g=case["geometry"];w=float(g["core_outer_x_mm"]);dep=float(g["core_depth_y_mm"])
        centre=float(g["center_leg_x_mm"]);window=float(g["window_width_each_mm"])
        side=(w-centre-2*window)/2
        plate=float(case["plate_height_mm"])
        zback=plate+float(case["core_body_height_mm"])-float(g["backplate_thickness_mm"])
        back=float(g["backplate_thickness_mm"])
        gap=float(case["gap_mm"])
        box(ed,"I38_GENERIC_FERRITE",-w/2,-dep/2,0,w,dep,plate,CORE_MATERIAL,.4)
        e_names=[
           box(ed,"E_BACK",-w/2,-dep/2,zback,w,dep,back,CORE_MATERIAL,.4),
           box(ed,"E_LEFT",-w/2,-dep/2,plate,side,dep,zback-plate,CORE_MATERIAL,.4),
           box(ed,"E_RIGHT",w/2-side,-dep/2,plate,side,dep,zback-plate,CORE_MATERIAL,.4),
           box(ed,"E_CENTER",-centre/2,-dep/2,plate+gap,centre,dep,zback-plate-gap,CORE_MATERIAL,.4)]
        unite(ed,e_names)
        state["ferrite_core_bodies"]=list(ed.GetObjectsInGroup("Solids"))
        store()
        # True PCB traces: line width 2.5mm, 70um thick, exact KiCad XY.
        copper=[]
        t=.07
        for i,(x,y,xx,yy,width,layer) in enumerate(ss):
            x,y,xx,yy,width=map(float,(x,y,xx,yy,width))
            if abs(y-yy)<1e-6:
                left=min(x,xx)-width/2
                copper.append(box(ed,"PCB_LR_CU_%03d"%i,left,y-width/2,COPPER_Z[layer],
                                  abs(xx-x)+width,width,t))
            elif abs(x-xx)<1e-6:
                bottom=min(y,yy)-width/2
                copper.append(box(ed,"PCB_LR_CU_%03d"%i,x-width/2,bottom,COPPER_Z[layer],
                                  width,abs(yy-y)+width,t))
            else:
                raise RuntimeError("Diagonal KiCad line not representable")
        state["kicad_layer_and_copper_boxes"]=len(copper)
        store()
        # Manufacturability trial: 25um plated hollow barrel of KiCad drilled
        # holes, not a solid-filled copper via or assumed official plating.
        allholes=[(*v,False) for v in vias]+[(*v,True) for v in ports]
        for i,(x,y,outer,drill,terminal) in enumerate(allholes):
            radius=drill/2+PLATING_MM
            # Use actual finished hole and a 25um annulus, *not* the
            # entire 0.8/1.8mm pad as solid copper cylinder.
            a=cyl(ed,"PCB_VIA_BARREL_%02d"%i,x,y,BOARD_Z0,radius,BOARD_THICK)
            b=cyl(ed,"PCB_VIA_BORE_%02d"%i,x,y,BOARD_Z0-.01,drill/2,BOARD_THICK+.02,"vacuum")
            ed.Subtract(["NAME:Selections","Blank Parts:=",a,"Tool Parts:=",b],
                       ["NAME:SubtractParameters","KeepOriginals:=",False])
            copper.append(a)
        state["hollow_plated_pth_solid_count"]=len(allholes)
        store()
        # Artificial leads to exterior boundary at +/-60mm: because
        # one must be able to attach a boundary current terminal, their
        # contributions invalidate nominal Lr comparison.
        a=ports[0];z=COPPER_Z["F.Cu"]
        copper.append(box(ed,"LR_TRIAL_LEAD_A",-60,a[1]-.6,z,
                          a[0]+60,1.2,.07))
        b=ports[-1];z=COPPER_Z["B.Cu"]
        copper.append(box(ed,"LR_TRIAL_LEAD_B",b[0],b[1]-.6,z,
                          60-b[0],1.2,.07))
        # 46 segments + 10 through barrels + 2 source leads must make
        # ONE physically continuous multi-layer conductor.
        state["copper_before_unite"]=len(copper)
        unite(ed,copper)
        names=list(ed.GetObjectsInGroup("Solids"))
        state["objects_after_unite"]=names
        if set(names)!={"I38_GENERIC_FERRITE","E_BACK","PCB_LR_CU_000"}:
            raise RuntimeError("Copper not merged into one continuous solid: "+repr(names))
        state["three_series_turns_one_copper_solid"]=True
        store()
        box(ed,"Region",-60,-60,-50,120,120,100,"vacuum",.99)
        project.SaveAs(TARGET,True)
        if not os.path.isfile(TARGET) or os.path.getsize(TARGET)<10000:
            raise RuntimeError("Native Maxwell .aedt file not persisted")
        state["native_project_sha256"]=digest(TARGET)
        state["native_project_size_bytes"]=os.path.getsize(TARGET)
        state["status"]="REAL_6LAYER_PCB_WINDING_SOLIDS_SAVED_NOT_SOLVED_NOT_FOR_FAB"
        state["save_completed"]=True
    except:
        state["status"]="NATIVE_3TURN_EM_CAD_FAILED_NOT_FOR_FAB"
        state["error"]=traceback.format_exc()
        try:state["Ansys_messages"]=list(oDesktop.GetMessages("","",0))[-25:]
        except:pass
    finally:
        try:store()
        except:pass
        try:ScriptEnv.Shutdown()
        except:pass
    return state

if __name__=="__main__":
    if "--preflight" in sys.argv:
        case,trial,segments,vias,ports=preflight()
        print("REAL KiCad 3-turn 6-layer copper preflight",len(segments),"segments",
              len(vias),"transition PTH",len(ports),"terminals",
              "target",case["target_inductance_uH"],"uH","gap",case["gap_mm"],
              "mm","B-H qualified",trial["qualification"]["real_tdk_n97_100c_nonlin_BH"])
    else:
        create()
else:
    create()
