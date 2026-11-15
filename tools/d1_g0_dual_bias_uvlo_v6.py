"""G0 V6 physically routed dual-rail undervoltage supervisor with opto bridge.

Source is immutable V5 THN30 isolated 12V supply carrier, grown to 115x116mm
so two TPS3710DDCR 6-pin DDC supervisors, real 1%-class 261k/10k sense
dividers, bypass caps, Vishay VO617A-3 optocoupler and a primary NPN
inverting stage can be laid out in two distinct primary/secondary islands.

It is a *voltage-valid reporting* circuit with actual pin/plane layout,
NOT a safety-rated 48V power disconnect or an actual power-stage permit.
Actual threshold tolerance, opto CTR at chosen IF, ESD/EMI, timing,
hold-up, connector keying, and independent fault injection remain OPEN.
"""
from __future__ import annotations
import argparse,hashlib,json,subprocess,sys
from pathlib import Path
import pcbnew as pcb
import d1_g0_traco_dual_bias_daughterboard as old

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"hardware/dcx_main/g2/d1_g0_THN30_UVLO_OPTO_V6_NOT_FOR_FAB"
STEM="d1_g0_dual_12v_UVLO_iso_health_30devices_NOT_FOR_FAB"
BOARD=OUT/(STEM+".kicad_pcb")
DRC=OUT/(STEM+"_native_drc.json")
REPORT=OUT/(STEM+"_PCB_evidence_NOT_FOR_FAB.json")
FOOTLIB=old.FOOTLIB
THRESHOLD_RHIGH=261_000
THRESHOLD_RLOW=10_000
TRIP_UP_V=.400*(THRESHOLD_RHIGH+THRESHOLD_RLOW)/THRESHOLD_RLOW
TRIP_DOWN_V=.3945*(THRESHOLD_RHIGH+THRESHOLD_RLOW)/THRESHOLD_RLOW
TI="https://www.ti.com/lit/ds/symlink/tps3710.pdf"
VISHAY="https://www.vishay.com/docs/83430/vo617a.pdf"
ON="https://www.onsemi.com/download/data-sheet/pdf/mmbt3904lt1-d.pdf"
BOARD_W=old.BOARD_W
BOARD_H=115.
NEW_NETS=("P_SENSE","S_SENSE","UVLO_P_OK","UVLO_S_OK",
          "OPT_LED_P","OPT_COL_N","QBASE","UVLO_S_PRIMARY_OK")
# All nodes are pin-level, from TPS3710 DDC top-view 1 OUT,2/4/6 GND,
# 3 SENSE,5 VDD. Output OPEN-DRAIN; low on undervoltage.
# VO617A DIP4: 1 anode 2 cathode 3 emitter 4 collector.
# MMBT3904LT1G SOT23: 1 base,2 emitter,3 collector.
PARTS={
 "UP":("super",(38.,82.),"TPS3710DDCR_PRIMARY_UVLO",
       {"1":"UVLO_P_OK","2":"PGND","3":"P_SENSE","4":"PGND","5":"VCC12","6":"PGND"}),
 "US":("super",(88.,82.),"TPS3710DDCR_SECONDARY_UVLO",
       {"1":"UVLO_S_OK","2":"SR_SOURCE_RETURN","3":"S_SENSE",
        "4":"SR_SOURCE_RETURN","5":"VCC12_S","6":"SR_SOURCE_RETURN"}),
 "RP_TOP":("res",(27.,88.),"261k_1%_0603",{"1":"VCC12","2":"P_SENSE"}),
 "RP_BOT":("res",(27.,95.),"10k_1%_0603",{"1":"P_SENSE","2":"PGND"}),
 "RP_PULL":("res",(48.,89.),"4.7k_0603",{"1":"VCC12","2":"UVLO_P_OK"}),
 "CP_100N":("cap",(47.,79.),"100nF_25V_X7R",{"1":"VCC12","2":"PGND"}),
 "RS_TOP":("res",(77.,88.),"261k_1%_0603",{"1":"VCC12_S","2":"S_SENSE"}),
 "RS_BOT":("res",(77.,95.),"10k_1%_0603",{"1":"S_SENSE","2":"SR_SOURCE_RETURN"}),
 "RS_PULL":("res",(97.,89.),"2.2k_0603",{"1":"VCC12_S","2":"UVLO_S_OK"}),
 "CS_100N":("cap",(98.,79.),"100nF_25V_X7R",{"1":"VCC12_S","2":"SR_SOURCE_RETURN"}),
 "ISO1":("opto",(66.,98.),"VO617A-3_4PIN_DIP_5.3kVrms_DEVICE_ONLY",
         {"1":"OPT_LED_P","2":"SR_SOURCE_RETURN","3":"PGND","4":"OPT_COL_N"}),
 "RS_LED":("res",(93.,105.),"100R_0603_OPTO_LED",{"1":"UVLO_S_OK","2":"OPT_LED_P"}),
 "RP_OPTO":("res",(52.,106.),"47k_0603_PHOTO_COLLECTOR",
         {"1":"VCC12","2":"OPT_COL_N"}),
 "QINV":("npn",(36.,102.),"MMBT3904LT1G",{"1":"QBASE","2":"PGND","3":"UVLO_S_PRIMARY_OK"}),
 "RBASE":("res",(47.,110.),"47k_0603",{"1":"OPT_COL_N","2":"QBASE"}),
 "RINV":("res",(28.,105.),"10k_0603",{"1":"VCC12","2":"UVLO_S_PRIMARY_OK"}),
 "J_HEALTH":("header",(12.,92.),"PRIMARY_STATUS_ONLY_NO_48V_PERMIT",
         {"1":"UVLO_P_OK","2":"UVLO_S_PRIMARY_OK","3":"PGND"}),
}
FOOT={
  "super":("Package_TO_SOT_SMD","SOT-23-6"),
  "res":("Resistor_SMD","R_0603_1608Metric"),
  "cap":("Capacitor_SMD","C_0603_1608Metric"),
  "opto":("Package_DIP","DIP-4_W7.62mm"),
  "npn":("Package_TO_SOT_SMD","SOT-23"),
  "header":("Connector_PinHeader_2.54mm","PinHeader_1x03_P2.54mm_Vertical"),
}
def v(pt):return pcb.VECTOR2I(pcb.FromMM(pt[0]),pcb.FromMM(pt[1]))
def mm(k):return round(pcb.ToMM(k),4)
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def route(board,net,layer,points,width=.23):
    for a,z in zip(points,points[1:]):
        old.segment(board,net,layer,a,z,width)
def padpos(fp):
    return {p.GetNumber():(mm(p.GetPosition().x),mm(p.GetPosition().y)) for p in fp.Pads()}
def mkfp(board,ref,kind,origin,value,nets):
    fp=old.getfp(*FOOT[kind])
    fp.SetReference(ref);fp.SetValue(value)
    fp.SetPosition(v(origin));fp.SetLayer(pcb.F_Cu)
    if kind=="opto":fp.SetOrientationDegrees(180)
    fp.Reference().SetVisible(False);fp.Value().SetVisible(False)
    byn={p.GetNetname():p for p in board.GetNetInfo().NetsByNetcode().values()}
    if {p.GetNumber() for p in fp.Pads()} != set(nets):
        raise ValueError("Native vendor pin numbering mismatch "+ref)
    for p in fp.Pads():
        p.SetNet(byn[nets[p.GetNumber()]])
    board.Add(fp)
    return fp
def zone_bounds(z,coords):
    outline=z.Outline()
    outline.RemoveAllContours()
    outline.NewOutline()
    for x,y in coords:outline.Append(pcb.FromMM(x),pcb.FromMM(y))
def actual():
    oldrec=old.check()
    if oldrec["native_footprints"]!=13:raise ValueError("prior Traco OEM source changed")
    b=pcb.LoadBoard(str(old.BOARD))
    # Resize the four original edge-cut segments *in place*. KiCad 10 SWIG
    # LoadBoard/Remove(PCB_SHAPE) can invalidate zone owner pointers.
    for shp in b.GetDrawings():
        if shp.GetLayer()!=pcb.Edge_Cuts:continue
        xy1=(mm(shp.GetStart().x),mm(shp.GetStart().y))
        xy2=(mm(shp.GetEnd().x),mm(shp.GetEnd().y))
        if xy1[1]==old.BOARD_H:
            shp.SetStart(v((xy1[0],BOARD_H)))
        if xy2[1]==old.BOARD_H:
            shp.SetEnd(v((xy2[0],BOARD_H)))
    for z in b.Zones():
        net=z.GetNetname();lay=z.GetLayer()
        if net=="PGND" and lay==pcb.B_Cu:
            zone_bounds(z,((4.,7.),(111.,7.),(111.,30.),(63.,30.),(63.,111.),(4.,111.)))
        elif net=="SR_SOURCE_RETURN" and lay==pcb.B_Cu:
            zone_bounds(z,((66.,34.),(111.,34.),(111.,111.),(66.,111.)))
        elif net=="VCC12" and lay==pcb.F_Cu:
            zone_bounds(z,((17.,34.),(62.,34.),(62.,111.),(17.,111.)))
        elif net=="VCC12_S" and lay==pcb.F_Cu:
            zone_bounds(z,((66.,34.),(111.,34.),(111.,111.),(66.,111.)))
    nets={n.GetNetname():n for n in b.GetNetInfo().NetsByNetcode().values()}
    for name in NEW_NETS:
        if name in nets:raise ValueError("new UVLO net already on native base PCB")
        n=pcb.NETINFO_ITEM(b,name);b.Add(n);nets[name]=n
    fp={ref:mkfp(b,ref,*data) for ref,data in PARTS.items()}
    pads={ref:padpos(f) for ref,f in fp.items()}
    # Local 1%-class 261k/10k dividers: configure 10.84V rising / 10.69V falling
    for chip,top,bot,cap,pull,prefix in (
        ("UP","RP_TOP","RP_BOT","CP_100N","RP_PULL","P"),
        ("US","RS_TOP","RS_BOT","CS_100N","RS_PULL","S"),
    ):
        sense=nets[prefix+"_SENSE"]
        pos=pads[chip]["3"]
        t2=pads[top]["2"];b1=pads[bot]["1"]
        sx=t2[0]+2.35
        route(b,sense,pcb.F_Cu,[t2,(sx,t2[1]-1.3),
                      (sx+.4,90.0),(sx+.4,95.75),
                      (b1[0],97.),b1],.20)
        route(b,sense,pcb.F_Cu,[pos,(pos[0]-3.3,pos[1]),
                      (sx,t2[1]-1.3)],.20)
        # Capacitor negative return and bottom divider resistor via into B.Cu
        ret="PGND" if prefix=="P" else "SR_SOURCE_RETURN"
        for a in (pads[cap]["2"],pads[bot]["2"]):
            pp=(a[0]+1.,a[1]-1.3) if a==pads[bot]["2"] else (a[0]+.9,a[1]+1.0)
            route(b,nets[ret],pcb.F_Cu,[a,pp],.30)
            old.via(b,nets[ret],pp)
        # Supervisor lower GND pads 2/4/6 to correct return via stitching
        for pin in ("2","4","6"):
            a=pads[chip][pin]
            pp=((a[0]-1.6,a[1]) if pin=="2" else
                (a[0]+1.7,a[1]+.8 if pin=="4" else a[1]-.8))
            route(b,nets[ret],pcb.F_Cu,[a,pp],.23)
            old.via(b,nets[ret],pp)
        # VDD via native F.Cu island, upper resistor and pullup similarly.
        # OUT takes a separate B.Cu status path to 4.7k or 2.2k pull-up.
        stat=nets["UVLO_"+prefix+"_OK"]
        pp=(pos[0]-.8,pos[1]-3.0)
        a=pads[chip]["1"]
        route(b,stat,pcb.F_Cu,[a,pp],.22);old.via(b,stat,pp)
        dest=pads[pull]["2"];pp2=(dest[0]+.0,dest[1]+1.5)
        old.via(b,stat,pp2)
        route(b,stat,pcb.F_Cu,[pp2,dest],.22)
        route(b,stat,pcb.B_Cu,[pp,(pp[0],pp2[1]),pp2],.22)
    # Isolated secondary LED: OUTS drives through 2.2k pullup from V12S;
    # 100R series to VO617A A(pin1). C(pin2) -> SRET.
    status=nets["UVLO_S_OK"]
    r_led=pads["RS_LED"]
    x=pads["RS_PULL"]["2"]
    s_via1=(x[0]+1.8,x[1]+1.3);s_via2=(r_led["1"][0],r_led["1"][1]-1.6)
    route(b,status,pcb.F_Cu,[x,s_via1],.22);old.via(b,status,s_via1)
    route(b,status,pcb.B_Cu,[s_via1,(s_via1[0],s_via2[1]),s_via2],.22)
    old.via(b,status,s_via2)
    route(b,status,pcb.F_Cu,[s_via2,r_led["1"]],.22)
    led=nets["OPT_LED_P"]
    route(b,led,pcb.F_Cu,[r_led["2"],(r_led["2"][0]+1.0,r_led["2"][1]+1.0)],.23)
    pp=(r_led["2"][0]+1.0,r_led["2"][1]+1.0);old.via(b,led,pp)
    route(b,led,pcb.B_Cu,[pp,(70.,108.),(70.,96.),pads["ISO1"]["1"]],.23)
    # Primary photocoupler collector pulled high when LED is off;
    # SUVLO OK when photocoupler LOW, inverted by QINV.
    iso=nets["OPT_COL_N"]
    route(b,iso,pcb.F_Cu,[pads["ISO1"]["4"],(55.,98.),pads["RP_OPTO"]["2"]],.22)
    route(b,iso,pcb.F_Cu,[pads["RP_OPTO"]["2"],(54.,108.),
           (43.9,108.),(43.9,110.),pads["RBASE"]["1"]],.20)
    route(b,nets["QBASE"],pcb.F_Cu,[pads["RBASE"]["2"],
                (49.,112.),(49.,113.),(33.,113.),(33.,103.),pads["QINV"]["1"]],.20)
    col=pads["QINV"]["3"];r2=pads["RINV"]["2"]
    colvia=(38.4,102.0);r2via=(r2[0]+2.,r2[1]+2.)
    route(b,nets["UVLO_S_PRIMARY_OK"],pcb.F_Cu,[col,colvia],.20)
    old.via(b,nets["UVLO_S_PRIMARY_OK"],colvia)
    old.via(b,nets["UVLO_S_PRIMARY_OK"],r2via)
    route(b,nets["UVLO_S_PRIMARY_OK"],pcb.B_Cu,[colvia,r2via],.20)
    route(b,nets["UVLO_S_PRIMARY_OK"],pcb.F_Cu,[r2via,r2],.20)
    # QINV emitter pin 2: independent local via, away from the Kelvin base.
    em=pads["QINV"]["2"];emvia=(em[0]+1.0,em[1]+1.7)
    route(b,nets["PGND"],pcb.F_Cu,[em,emvia],.22);old.via(b,nets["PGND"],emvia)
    # Primary side 3-pin status interface (P-OK, isolated-S-OK, primary return)
    pt=pads["J_HEALTH"]
    pp=pads["RP_PULL"]["2"]
    # Header P_OK routes on B.Cu back to the independent supervisor OUT.
    pv=(pads["UP"]["3"][0]-.8,pads["UP"]["3"][1]-3.0)
    route(b,nets["UVLO_P_OK"],pcb.B_Cu,[pt["1"],(17.,93.),(17.,78.),pv],.21)
    pp2=pads["RINV"]["2"]
    route(b,nets["UVLO_S_PRIMARY_OK"],pcb.F_Cu,[pp2,(pp2[0],107.),
      (21.,107.),(18.,100.),(pt["2"][0]+2.,pt["2"][1]),pt["2"]],.21)
    pcb.ZONE_FILLER(b).Fill(b.Zones())
    return b

def audit(b,d):
    refs={f.GetReference():f for f in b.GetFootprints()}
    if set(refs)!=(set(old.PARTS)|set(PARTS)):
        raise ValueError("V6 actual UVLO PCB part inventory wrong")
    pins={}
    for ref,f in refs.items():
        actual={p.GetNumber():p.GetNetname() for p in f.Pads()}
        wanted=(PARTS[ref][3] if ref in PARTS else old.PARTS[ref]["pins"])
        if actual!=wanted:raise ValueError("UVLO native pad/net mismatch "+ref)
        pins[ref]=actual
    if pins["UP"]!={"1":"UVLO_P_OK","2":"PGND","3":"P_SENSE",
                   "4":"PGND","5":"VCC12","6":"PGND"}:
        raise ValueError("TI TPS3710 DDC primary pins not mapped correctly")
    if pins["US"]["2"]!="SR_SOURCE_RETURN" or pins["US"]["5"]!="VCC12_S":
        raise ValueError("TI TPS3710 secondary pins wrongly returned")
    if pins["ISO1"]!={"1":"OPT_LED_P","2":"SR_SOURCE_RETURN","3":"PGND","4":"OPT_COL_N"}:
        raise ValueError("optocoupler swapped across the galvanic barrier")
    return {
     "kind":"D1_G0_TWO_OEM_THN30_AND_TWO_TPS3710_OPTIC_UVLO_NATIVE_V6",
     "status":"V6_UVLO_FOOTPRINT_AND_COPPER_CANDIDATE_NOT_FOR_FAB",
     "device_count":len(refs),
     "native_pin_map":pins,
     "independent_primary_secondary_uvlo_sense":True,
     "TPS3710_SOT6_top_pin_map":{"1":"OUT","2":"GND","3":"SENSE","4":"GND","5":"VDD","6":"GND"},
     "TPS3710_nominal_12v_trip_rising_v":TRIP_UP_V,
     "TPS3710_nominal_12v_trip_falling_v":TRIP_DOWN_V,
     "divider_top_ohm":THRESHOLD_RHIGH,"divider_bottom_ohm":THRESHOLD_RLOW,
     "sense_ref_tolerance_temperature_measured":False,
     "optocoupler_VO617A3_ctr_when_led_about_5mA_tested":False,
     "primary_secondary_copper_returns_directly_joined":False,
     "UVLO_S_primary_status_physically_opto_isolated":True,
     "hardware_estop_closed_contact_and_48v_coil_driver_integrated":False,
     "UVLO_to_actual_power_switch_and_gate_enable_integrated":False,
     "bias_hold_up_and_power_off_timing_measured":False,
     "mainboard_R8_DNP":True,
     "vendor_datasheets":{"TPS3710":TI,"VO617A":VISHAY,"MMBT3904LT1G":ON},
     "origin_2xTraco_bias_board_SHA":sha(old.BOARD),
     "PCB_SHA":sha(BOARD),"KiCad_DRC_SHA":sha(DRC),
     "native_drc_rules":len(d.get("violations",[])),
     "native_unconnected":len(d.get("unconnected_items",[])),
     "energization_allowed":False,"fabrication_approved":False,"g0_approved":False
    }

def write():
    OUT.mkdir(parents=True,exist_ok=True)
    b=actual()
    pcb.SaveBoard(str(BOARD),b)
    cli=Path(sys.executable).with_name("kicad-cli.exe")
    r=subprocess.run([str(cli),"pcb","drc","--severity-all","--format","json",
        "-o",str(DRC),str(BOARD)],capture_output=True,text=True,errors="replace")
    if not DRC.is_file():raise ValueError("KiCad command failed "+r.stderr)
    d=json.loads(DRC.read_text("utf-8"))
    data=audit(pcb.LoadBoard(str(BOARD)),d)
    REPORT.write_text(json.dumps(data,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps({x:data[x] for x in ("status","device_count",
          "native_drc_rules","native_unconnected")}))
    return data
def check():
    data=json.loads(REPORT.read_text("utf-8"))
    r=audit(pcb.LoadBoard(str(BOARD)),json.loads(DRC.read_text("utf-8")))
    if data!=r:raise ValueError("UVLO V6 native PCB receipt stale")
    return r
if __name__=="__main__":
    p=argparse.ArgumentParser()
    g=p.add_mutually_exclusive_group(required=True)
    g.add_argument("--write",action="store_true")
    g.add_argument("--check",action="store_true")
    x=p.parse_args()
    write() if x.write else check()
