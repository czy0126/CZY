"""G0 V5 native physical SR sense Kelvin + REG decoupling engineering ECO.

TI UCC24624 8-pin SOIC: pin 2 PGND (gate current), pin 3 REG
(2.2uF nominal decoupling), pin 5 VSS (sense reference) needs independent
low-current trace returned to the MOSFET Source star, not globally poured.
The four U3-U6 VSS pins move onto 4 named Kelvin nets and each gets
a physical RKx 0-ohm 0603 net-joining resistor next to SR MOS source pair.
Full assembly/EMC and source-offset sense noise remain UNQUALIFIED.
"""
from __future__ import annotations
import argparse,hashlib,json,subprocess,sys
from pathlib import Path
import pcbnew as pcb
import d1_g0_package_independent_v4 as base
import d1_g0_cross_domain_audit as domain

OUT=base.OUT.parent/"d1_g0_UCC24624_KELVIN_V5_NOT_FOR_FAB"
STEM="d1_g0_UCC24624_SR_VSS_KELVIN_AND_REG_CAPS_NOT_FOR_FAB"
BOARD=OUT/(STEM+".kicad_pcb")
DRC=OUT/(STEM+"_native_drc.json")
REPORT=OUT/(STEM+"_receipt.json")
MURATA="GRM188C71E225KE11" # 0603 X7S 2.2uF 25V, DC bias derating pending
TI="https://www.ti.com/lit/ds/symlink/ucc24624.pdf"
MURATA_SOURCE="https://search.murata.co.jp/Ceramy/image/img/A01X/G101/ENG/GRM188C71E225KE11-01A.pdf"
SENSE_NETS={f"U{i+2}":f"SR_KELVIN_{i}" for i in range(1,5)}
SITES={i:{"resistor_center":(17.+38*(i-1),68.6)} for i in range(1,5)}
# Pin 1 of the 0R is the physical SR source star; pin2 attaches Kelvin trace.
CAP_VALUE=f"{MURATA}_2u2_25V_X7S_DC_BIAS_REVIEW"
R_VALUE="RC0603JR-070RL_0R_SR_KELVIN_DFM_UNAPPROVED"

def mm(x):return pcb.ToMM(x)
def at(t):return pcb.VECTOR2I(pcb.FromMM(t[0]),pcb.FromMM(t[1]))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def track(b,n,l,a,z,w=.20):
    obj=pcb.PCB_TRACK(b);obj.SetStart(at(a));obj.SetEnd(at(z))
    obj.SetLayer(l);obj.SetWidth(pcb.FromMM(w));obj.SetNet(n);b.Add(obj)
def via(b,n,pt,diam=.70,drill=.30):
    obj=pcb.PCB_VIA(b);obj.SetPosition(at(pt));obj.SetLayerPair(pcb.F_Cu,pcb.B_Cu)
    obj.SetNet(n);obj.SetWidth(pcb.FromMM(diam));obj.SetDrill(pcb.FromMM(drill))
    b.Add(obj)

def resistor(b,ref,x,y,n_ground,n_sense):
    f=pcb.FOOTPRINT(b);f.SetReference(ref);f.SetValue(R_VALUE)
    f.SetPosition(at((x,y)));f.SetLayer(pcb.F_Cu)
    f.Reference().SetVisible(False);f.Value().SetVisible(False)
    for pin,loc,net in (("1",(x-.75,y),n_ground),("2",(x+.75,y),n_sense)):
        p=pcb.PAD(f);p.SetNumber(pin);p.SetPosition(at(loc))
        p.SetShape(pcb.PAD_SHAPE_RECT);p.SetSize(at((.8,.87)))
        p.SetAttribute(pcb.PAD_ATTRIB_SMD)
        mask=pcb.LSET()
        for layer in (pcb.F_Cu,pcb.F_Mask,pcb.F_Paste):mask.AddLayer(layer)
        p.SetLayerSet(mask);p.SetNet(net);f.Add(p)
    rect=pcb.PCB_SHAPE(f);rect.SetShape(pcb.SHAPE_T_RECT)
    rect.SetStart(at((x-1.5,y-.9)));rect.SetEnd(at((x+1.5,y+.9)))
    rect.SetLayer(pcb.F_CrtYd);rect.SetWidth(pcb.FromMM(.05));f.Add(rect)
    b.Add(f)
    return f

def construct():
    main=base.check()
    if main["PCB_footprints"]!=157:raise ValueError("source V4 not frozen")
    b=pcb.LoadBoard(str(base.PCB))
    byref={x.GetReference():x for x in b.GetFootprints()}
    nets={x.GetNetname():x for x in b.GetNetInfo().NetsByNetcode().values()}
    if "SR_SOURCE_RETURN" not in nets:raise ValueError("G0 V4 separate SR source return missing")
    layout=[]
    for i in range(1,5):
        ref=f"U{i+2}";net=SENSE_NETS[ref]
        ni=pcb.NETINFO_ITEM(b,net);b.Add(ni)
        sense=next(x for x in byref[ref].Pads() if x.GetNumber()=="5")
        pgnd=next(x for x in byref[ref].Pads() if x.GetNumber()=="2")
        if sense.GetNetname()!="SR_SOURCE_RETURN" or pgnd.GetNetname()!="SR_SOURCE_RETURN":
            raise ValueError("expected independent UCC pin map drift")
        sense.SetNet(ni)
        sx=mm(sense.GetPosition().x);sy=mm(sense.GetPosition().y)
        cx,cy=SITES[i]["resistor_center"]
        r=resistor(b,f"RK{i}",cx,cy,nets["SR_SOURCE_RETURN"],ni)
        # A separate, non-switch-current Kelvin trace from UCC VSS pin5
        # onto the vacant In9.Cu layer. Vias are NOT mfg approved.
        va=(sx+1.5,46.55);vb=(cx+.75,70.0)
        track(b,ni,pcb.F_Cu,(sx,sy),va)
        via(b,ni,va)
        track(b,ni,pcb.In9_Cu,va,vb)
        via(b,ni,vb)
        track(b,ni,pcb.F_Cu,vb,(cx+.75,cy))
        # Pad 1 is poured into local F.Cu SR SOURCE RETURN near the
        # SR MOS source pair, not attached to the controller PGND pin.
        # This local plane tie is NOT an independently validated Kelvin star;
        # actual switching-current offset / source bond must be inspected.
        old_cap=byref[f"C{i+6}"]
        pins={x.GetNumber():x.GetNetname() for x in old_cap.Pads()}
        if pins!={"1":f"REG{i}","2":"SR_SOURCE_RETURN"}:
            raise ValueError("REG bypass physical terminal unexpected")
        old_cap.SetValue(CAP_VALUE)
        layout.append({
           "control_ref":ref,"gate_current_return_pin2":"SR_SOURCE_RETURN",
           "VSS_sense_pin5":net,"kelvin_net":net,"source_reference_region":f"SR{i}A/B local source return plane",
           "source_star_connection_physical_qualification":False,
           "RK0R":f"RK{i}","resistor_return_pad_mm":[cx-.75,cy],
           "new_Kelvin_route_layer":"In9.Cu","C_REG_ref":f"C{i+6}",
           "C_REG_part":MURATA,
        })
    pcb.ZONE_FILLER(b).Fill(b.Zones())
    return b,layout

def readback(b,d,layout):
    pads,_=domain.pinpassport(b)
    if len(pads)!=161:raise ValueError("4 new physical Kelvin resistors missing")
    for i in range(1,5):
        u=pads[f"U{i+2}"];res=pads[f"RK{i}"]
        assert u["2"]=="SR_SOURCE_RETURN" and u["5"]==f"SR_KELVIN_{i}"
        assert res=={"1":"SR_SOURCE_RETURN","2":f"SR_KELVIN_{i}"}
        c=next(f for f in b.GetFootprints() if f.GetReference()==f"C{i+6}")
        if c.GetValue()!=CAP_VALUE:raise ValueError("2.2uF regulator cap part not captured")
    viol=len(d.get("violations",[]));gaps=len(d.get("unconnected_items",[]))
    return {
      "kind":"D1_G0_V5_UCC24624_REAL_NATIVE_KELVIN_VSS_ECO",
      "status":"NATIVE_SR_SENSE_KELVIN_REG_CAPS_CANDIDATE_NOT_FOR_FAB",
      "source_V4_SHA256":sha(base.PCB),
      "current_native_board_sha256":sha(BOARD),
      "KiCad_drc_sha256":sha(DRC),
      "actual_native_device_count":len(pads),
      "four_SR_VSS_Kelvin_nets_present":True,
      "four_0R_kicad_resistor_footprints_present":True,
      "SR_REG_bypass_four_0603_MPN":MURATA,
      "C7_C10_nominal_cap_uF":2.2,
      "DC_bias_effective_cap_and_noise_signoff":False,
      "source_SOA_and_SR_off_threshold_review":False,
      "TI_datasheet":TI,"Murata_datasheet":MURATA_SOURCE,
      "physical_layout":layout,
      "KiCad_native_DRC_violations":viol,
      "KiCad_native_unconnected":gaps,
      "via_in_copper_and_manufacturing_qualified":False,
      "floating_VSS_vs_power_return_tested":False,
      "G0_approved":False,"energization_allowed":False,"fabrication_approved":False,
    }

def write():
    OUT.mkdir(parents=True,exist_ok=True)
    b,layout=construct()
    pcb.SaveBoard(str(BOARD),b)
    cmd=[str(Path(sys.executable).with_name("kicad-cli.exe")),
         "pcb","drc","--severity-all","--format","json","-o",str(DRC),str(BOARD)]
    result=subprocess.run(cmd,capture_output=True,text=True,errors="replace")
    if result.returncode or not DRC.is_file():raise ValueError("Native KiCad V5 DRC failed "+result.stderr)
    result=readback(pcb.LoadBoard(str(BOARD)),json.loads(DRC.read_text("utf-8")),layout)
    REPORT.write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    return result

def check():
    old=json.loads(REPORT.read_text("utf-8"))
    b=pcb.LoadBoard(str(BOARD))
    d=json.loads(DRC.read_text("utf-8"))
    result=readback(b,d,old["physical_layout"])
    if result!=old:raise ValueError("V5 physical Kelvin CAD receipt stale")
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    m=p.add_mutually_exclusive_group(required=True)
    m.add_argument("--write",action="store_true")
    m.add_argument("--check",action="store_true")
    a=p.parse_args()
    result=write() if a.write else check()
    print(json.dumps({k:result[k] for k in
      ("status","actual_native_device_count","KiCad_native_DRC_violations",
       "KiCad_native_unconnected")},ensure_ascii=False))
if __name__=="__main__":main()
