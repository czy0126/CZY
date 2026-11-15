"""G0 actual dual 48V->12V isolated bias *daughterboard* KiCad native PCB.

Two OEM THN 30-4812 modules (not WIR) with the *exact official KiCad*
Converter_DCDC_TRACO_THN30-xxxx_THT 6-pad footprint. Pin numbers and
positions are crosschecked against vendor THN30 datasheet Rev 2024-02-07.
Each module has its own 48V 2A slow fuse design *location* and input
1uF/100V decoupling. Outputs each have 2x22uF/25V X7R candidate and
physically separated 12V-P/PGND vs 12V-S/SR_SOURCE_RETURN terminals.
The board is not a replacement for a safety-rated main 48V cutoff,
actual UVLO/hold-up and isolated regulator/PCB compliance testing.
Fuses, caps, terminal MPNs and safety clearance remain for qualification.
"""
from __future__ import annotations
import argparse,hashlib,json,subprocess,sys
from pathlib import Path
import pcbnew as pcb

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"hardware/dcx_main/g2/d1_g0_dual_THN30_bias_carrier_NOT_FOR_FAB"
NAME="d1_g0_2xTHN30_48V_to_isolated_12V_P_S_CARRIER_NOT_FOR_FAB"
BOARD=OUT/(NAME+".kicad_pcb")
DRC=OUT/(NAME+"_native_drc.json")
REPORT=OUT/(NAME+"_physical_pin_and_copper_receipt.json")
FOOTLIB=Path(sys.executable).parents[1]/"share/kicad/footprints" # overwritten below if installed layout
FOOTLIB=Path(sys.executable).parents[1]/"share/kicad/footprints"
# KiCad Python: .../KiCad/10.0/bin/python.exe -> .../KiCad/10.0/share/kicad/footprints
FOOTLIB=Path(sys.executable).parents[1]/"share/kicad/footprints"
TRACO="Converter_DCDC_TRACO_THN30-xxxx_THT"
PINS={"1":"+Vin","2":"-Vin","3":"+Vout","4":"Trim","5":"-Vout","6":"Remote"}
NETS=("VIN48_PRE","PGND","VIN48P_F","VIN48S_F","VCC12","VCC12_S","SR_SOURCE_RETURN")
MPN="THN 30-4812"
FUSE_VALUE="2A_SLOW_75VDC_MIN_Q_DFMR_REQUIRED"
CAP_IN_VALUE="1uF_100V_X7R_1206_DERATING_PENDING"
CAP_OUT_VALUE="22uF_25V_X7R_1210_DERATING_PENDING"
MAIN_PORT_VALUES={"J_P":"VCC12/PGND", "J_S":"VCC12_S/SR_SOURCE_RETURN"}
FOOTPRINTS={
 "module":("Converter_DCDC",TRACO),
 "fuse":("Fuse","Fuse_1812_4532Metric"),
 "input_cap":("Capacitor_SMD","C_1206_3216Metric"),
 "output_cap":("Capacitor_SMD","C_1210_3225Metric"),
 "connector":("TerminalBlock","TerminalBlock_MaiXu_MX126-5.0-02P_1x02_P5.00mm")
}
PARTS={
 "J_IN": {"type":"connector","position":(9.,13.),"value":"INPUT_48V_PRE_EST0P","pins":{"1":"VIN48_PRE","2":"PGND"}},
 "F1": {"type":"fuse","position":(28.,9.),"value":FUSE_VALUE,"pins":{"1":"VIN48_PRE","2":"VIN48P_F"}},
 "F2": {"type":"fuse","position":(79.,9.),"value":FUSE_VALUE,"pins":{"1":"VIN48_PRE","2":"VIN48S_F"}},
 "U1": {"type":"module","position":(33.,18.),"value":MPN,
        "pins":{"1":"VIN48P_F","2":"PGND","3":"VCC12","4":"","5":"PGND","6":""}},
 "U2": {"type":"module","position":(84.,18.),"value":MPN,
        "pins":{"1":"VIN48S_F","2":"PGND","3":"VCC12_S","4":"","5":"SR_SOURCE_RETURN","6":""}},
 "C_INP":{"type":"input_cap","position":(43.,10.),"value":CAP_IN_VALUE,
         "pins":{"1":"VIN48P_F","2":"PGND"}},
 "C_INS":{"type":"input_cap","position":(94.,10.),"value":CAP_IN_VALUE,
         "pins":{"1":"VIN48S_F","2":"PGND"}},
 "C_P1":{"type":"output_cap","position":(25.,51.),"value":CAP_OUT_VALUE,
         "pins":{"1":"VCC12","2":"PGND"}},
 "C_P2":{"type":"output_cap","position":(42.,51.),"value":CAP_OUT_VALUE,
         "pins":{"1":"VCC12","2":"PGND"}},
 "C_S1":{"type":"output_cap","position":(76.,51.),"value":CAP_OUT_VALUE,
         "pins":{"1":"VCC12_S","2":"SR_SOURCE_RETURN"}},
 "C_S2":{"type":"output_cap","position":(94.,51.),"value":CAP_OUT_VALUE,
         "pins":{"1":"VCC12_S","2":"SR_SOURCE_RETURN"}},
 "J_P":{"type":"connector","position":(30.,63.),"value":"PRIMARY_12V_OUT",
        "pins":{"1":"VCC12","2":"PGND"}},
 "J_S":{"type":"connector","position":(81.,63.),"value":"SECONDARY_12V_OUT",
        "pins":{"1":"VCC12_S","2":"SR_SOURCE_RETURN"}},
}
BOARD_W=115.
BOARD_H=75.

def v(pt):return pcb.VECTOR2I(pcb.FromMM(pt[0]),pcb.FromMM(pt[1]))
def mm(x):return round(pcb.ToMM(x),4)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def getfp(lib,name):
    path=FOOTLIB/(lib+".pretty")
    if not path.is_dir():raise ValueError("installed KiCad OEM footprints unavailable "+str(path))
    fp=pcb.FootprintLoad(str(path),name)
    if fp is None:raise ValueError("KiCad OEM footprint not found "+str(path)+"/"+name)
    return fp

def inspect_traco():
    fp=getfp(*FOOTPRINTS["module"])
    found={pad.GetNumber():(mm(pad.GetPosition().x),mm(pad.GetPosition().y)) for pad in fp.Pads()}
    truth={"1":(0.,0.),"2":(5.08,0.),"3":(-7.62,20.32),
           "4":(2.54,20.32),"5":(12.7,20.32),"6":(12.7,0.)}
    if found!=truth:
        raise ValueError("KiCad manufacturer footprint pin layout changed; re-review physical datasheet")
    for pad in fp.Pads():
        if mm(pad.GetDrillSize().x)<1.2:raise ValueError("traco through-hole drill smaller than vendor 1mm pin")
    return {name:list(pos) for name,pos in found.items()}

def edge(board):
    points=((0.,0.),(BOARD_W,0.),(BOARD_W,BOARD_H),(0.,BOARD_H))
    for a,z in zip(points,points[1:]+points[:1]):
        s=pcb.PCB_SHAPE(board)
        s.SetShape(pcb.SHAPE_T_SEGMENT)
        s.SetStart(v(a));s.SetEnd(v(z))
        s.SetLayer(pcb.Edge_Cuts);s.SetWidth(pcb.FromMM(.05))
        board.Add(s)

def segment(board,net,layer,a,z,width=.45):
    item=pcb.PCB_TRACK(board)
    item.SetStart(v(a));item.SetEnd(v(z))
    item.SetWidth(pcb.FromMM(width))
    item.SetLayer(layer);item.SetNet(net);board.Add(item)

def via(board,net,atpoint):
    obj=pcb.PCB_VIA(board)
    obj.SetPosition(v(atpoint));obj.SetLayerPair(pcb.F_Cu,pcb.B_Cu)
    obj.SetWidth(pcb.FromMM(.80));obj.SetDrill(pcb.FromMM(.40))
    obj.SetNet(net);board.Add(obj)

def zone(board,net,layer,bounds,clearance=.35,vertices=None):
    z=pcb.ZONE(board)
    z.SetNet(net);z.SetLayer(layer)
    z.SetLocalClearance(pcb.FromMM(clearance))
    z.SetThermalReliefGap(pcb.FromMM(.35))
    z.SetThermalReliefSpokeWidth(pcb.FromMM(.42))
    o=z.Outline();o.NewOutline()
    x0,y0,x1,y1=bounds
    for x,y in (vertices or ((x0,y0),(x1,y0),(x1,y1),(x0,y1))):
        o.Append(pcb.FromMM(x),pcb.FromMM(y))
    board.Add(z)

def build():
    inspect_traco()
    board=pcb.BOARD()
    board.SetCopperLayerCount(2)
    edge(board)
    nets={}
    for name in NETS:
        net=pcb.NETINFO_ITEM(board,name);board.Add(net);nets[name]=net
    centers={}
    footprints={}
    for ref,info in PARTS.items():
        f=getfp(*FOOTPRINTS[info["type"]])
        f.SetReference(ref);f.SetValue(info["value"])
        f.SetPosition(v(info["position"]))
        f.SetLayer(pcb.F_Cu)
        f.Reference().SetVisible(False)
        f.Value().SetVisible(False)
        observed={p.GetNumber() for p in f.Pads()}
        if observed!=set(info["pins"]):
            raise ValueError("real KiCad package pin index not matching independent source: "+ref+" "+str(observed))
        padpos={}
        for pad in f.Pads():
            number=pad.GetNumber(); netname=info["pins"][number]
            if netname:pad.SetNet(nets[netname])
            pos=pad.GetPosition()
            padpos[number]=(mm(pos.x),mm(pos.y))
        board.Add(f)
        footprints[ref]=f
        centers[ref]=padpos
    # PGND controls both module inputs and the intentionally grounded P
    # output; secondary output return has separate physically non-touching zone.
    zone(board,nets["PGND"],pcb.B_Cu,(4.,7.,111.,71.),vertices=(
        (4.,7.),(111.,7.),(111.,30.),(63.,30.),(63.,71.),(4.,71.)))
    zone(board,nets["SR_SOURCE_RETURN"],pcb.B_Cu,(66.,34.,111.,71.))
    # Both positive outputs form separate wide F.Cu 12V islands.
    zone(board,nets["VCC12"],pcb.F_Cu,(17.,34.,62.,71.))
    zone(board,nets["VCC12_S"],pcb.F_Cu,(66.,34.,111.,71.))
    # Separate raw 48V pre-E-stop bus across top; two independent fuses.
    raw=nets["VIN48_PRE"]
    segs=[((9.,13.),(9.,5.)),((9.,5.),(76.862,5.)),
          ((25.862,5.),centers["F1"]["1"]),
          ((76.862,5.),centers["F2"]["1"])]
    for a,z in segs:segment(board,raw,pcb.F_Cu,a,z,.60)
    # Separate fused plus lines to each actual TRACO pad 1 and local input caps.
    for fuse,mod,cap,net in (("F1","U1","C_INP","VIN48P_F"),
                              ("F2","U2","C_INS","VIN48S_F")):
        f=centers[fuse]["2"];dest=centers[mod]["1"];cin=centers[cap]["1"]
        mid=(dest[0],f[1]+1.0)
        for a,z in ((f,mid),(mid,dest),(mid,cin)):
            segment(board,nets[net],pcb.F_Cu,a,z,.42)
    # No input or output PGND to SRET tie. Each SMD capacitor negative pad
    # is separately via-stitched into the proper B.Cu return island.
    for ref in ("C_INP","C_INS","C_P1","C_P2","C_S1","C_S2"):
        pad=centers[ref]["2"]
        p=(pad[0]+1.5,pad[1])
        netname=PARTS[ref]["pins"]["2"]
        segment(board,nets[netname],pcb.F_Cu,pad,p,.30)
        via(board,nets[netname],p)
    pcb.ZONE_FILLER(board).Fill(board.Zones())
    return board,centers

def readback(board,drc):
    refs={f.GetReference():f for f in board.GetFootprints()}
    if set(refs)!=set(PARTS):raise ValueError("native bias board 13-device registry incorrect")
    physical={}
    for ref,fp in refs.items():
        got={p.GetNumber():p.GetNetname() for p in fp.Pads()}
        want=PARTS[ref]["pins"]
        if got!=want:raise ValueError("bias OEM 6-pin / connector / fuse net swapped "+ref)
        physical[ref]=got
    for ref in ("U1","U2"):
        pin=physical[ref]
        if pin["2"]!="PGND" or pin["6"] or pin["4"]:
            raise ValueError("two module remote/trim must stay NC")
    if physical["U2"]["5"]!="SR_SOURCE_RETURN" or physical["U1"]["5"]!="PGND":
        raise ValueError("48V Traco isolated secondary output bonded to input ground")
    if len(drc.get("violations",[])) or len(drc.get("unconnected_items",[])):
        raise ValueError("native board DRC not yet complete")
    return {
        "kind":"G0_TWO_OEM_TRACO_THN30_4812_ACTUAL_KICAD_DAUGHTERBOARD",
        "status":"REAL_THN30_PIN_FOOTPRINT_PCB_DRC0_OPEN0_WITH_FUSE_AND_SPLIT_RETURNS_NOT_FOR_FAB",
        "native_footprints":len(refs),
        "independent_ref_pin_net":physical,
        "native_pad_objects":sum(len(f.Pads()) for f in refs.values()),
        "OEM_module_pin_layout":inspect_traco(),
        "OEM_THN30_datasheet":"https://www.tracopower.com/products/thn30.pdf",
        "module_P_N":MPN,"modules":2,
        "input_48v_range":[36,75],
        "two_individual_input_fuses_2A_slow_recommended":True,
        "fuse_MPN_DC_breaking_capacity_and_I2t_qualified":False,
        "two_output_caps_22uF_25V_each_module":True,
        "cap_effective_bias_and_surge_EMC_qualified":False,
        "two_12V_power_outputs_both_2p5A_nominal":True,
        "primary_output_ground":"PGND",
        "secondary_output_return":"SR_SOURCE_RETURN",
        "secondary_output_is_separate_from_module_48v_input_ground":True,
        "module_remote_NC_default_ON_because_vendor_open_means_on":True,
        "real_hardware_estop_or_permit_implemented":False,
        "module_footprint_manufacturer_drawing_orientation_verified":True,
        "connector_MPN_and_polarity_keying_qualified":False,
        "pcb_creepage_insulation_stackup_certified":False,
        "EMI_surges_and_case_thermal_certified":False,
        "native_KiCad_DRC_violations":len(drc["violations"]),
        "native_KiCad_unconnected":len(drc["unconnected_items"]),
        "native_board_sha256":sha(BOARD),
        "native_drc_sha256":sha(DRC),
        "G0_approved":False,"energization_allowed":False,"fabrication_approved":False
    }

def write():
    OUT.mkdir(parents=True,exist_ok=True)
    b,points=build()
    pcb.SaveBoard(str(BOARD),b)
    cli=Path(sys.executable).with_name("kicad-cli.exe")
    run=subprocess.run([str(cli),"pcb","drc","--severity-all","--format","json",
        "-o",str(DRC),str(BOARD)],capture_output=True,text=True,errors="replace")
    if not DRC.is_file():raise ValueError("Traco native DRC file missing "+run.stderr)
    d=json.loads(DRC.read_text("utf-8"))
    diag={"rule_errors":len(d.get("violations",[])),"opens":len(d.get("unconnected_items",[]))}
    if diag["rule_errors"] or diag["opens"]:
        REPORT.write_text(json.dumps({"status":"TRIAL_REJECTED",**diag},indent=2)+"\n",encoding="utf-8")
        return {"status":"TRIAL_REJECTED",**diag}
    record=readback(pcb.LoadBoard(str(BOARD)),d)
    REPORT.write_text(json.dumps(record,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    return record

def check():
    x=json.loads(REPORT.read_text("utf-8"))
    record=readback(pcb.LoadBoard(str(BOARD)),json.loads(DRC.read_text("utf-8")))
    if x!=record:raise ValueError("Traco daughterboard native receipt changed")
    return record

def main():
    p=argparse.ArgumentParser()
    g=p.add_mutually_exclusive_group(required=True)
    g.add_argument("--write",action="store_true")
    g.add_argument("--check",action="store_true")
    a=p.parse_args()
    d=write() if a.write else check()
    print(json.dumps({k:v for k,v in d.items() if k in
       ("status","native_footprints","native_KiCad_DRC_violations",
        "native_KiCad_unconnected","rule_errors","opens")},ensure_ascii=False))
if __name__=="__main__":main()
