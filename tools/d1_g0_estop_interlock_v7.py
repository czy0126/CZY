"""G0 V7: real NC emergency-stop loop + non-auto-restart 48V contactor-coil logic.

A standalone, source-authored native KiCad candidate; NOT a certified safety
controller. Two NC e-stop contacts: coil supply loop in SERIES (not software),
independent NC second channel into fault-reset latch. The logic cannot enable
a coil if P12, S12, HS-float or e-stop MON contact is missing. A failed/faulted
state requires a NEW rising pulse of manual ARM after faults clear.

OEM:
 GX14FAC (Sensata) 48 V coil, **internal suppression**, DO NOT add diode;
 IRL540NPbF (Infineon) TO220 G1-D2-S3 100V logic-level MOSFET;
 CD4081BE (TI) quad 2-input AND, pin14 VDD pin7 GND;
 CD4013BE (TI) dual D flip-flop, async RESET high.
 This is not an independent high-side monitor, real contactor, precharge,
 physical E-stop wiring, double-channel safety relay, or a physical G0 PASS.
"""
from __future__ import annotations
import argparse,csv,hashlib,json,subprocess,sys,math
from pathlib import Path
import pcbnew as pcb
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"hardware/dcx_main/g2/d1_g0_ESTOP_INTERLOCK_V7_NOT_FOR_FAB"
STEM="d1_g0_48V_NC_ESTOP_GX14FAC_latched_enable_V7"
BOARD=OUT/(STEM+".kicad_pcb")
DRC=OUT/(STEM+"_native_drc.json")
REPORT=OUT/"V7_hardware_stop_and_restart_contract_NOT_FOR_FAB.json"
FOOTLIB=Path(sys.executable).parents[1]/"share/kicad/footprints"
BOARD_W,BOARD_H=145.0,99.0
DS={
"GX14":"https://www.sensata.com/sites/default/files/a/sensata-gigavac-gx14-series-open-contactors-datasheet.pdf",
"IRL540N":"https://www.infineon.com/assets/row/public/documents/24/49/infineon-irl540n-datasheet-en.pdf",
"CD4081":"https://www.ti.com/lit/ds/symlink/cd4081b-mil.pdf",
"CD4013":"https://www.ti.com/lit/ds/symlink/cd4013b.pdf"}
F={
"terminal":("TerminalBlock","TerminalBlock_MaiXu_MX126-5.0-02P_1x02_P5.00mm"),
"hdr3":("Connector_PinHeader_2.54mm","PinHeader_1x03_P2.54mm_Vertical"),
"fuse":("Fuse","Fuse_1812_4532Metric"),
"cmos":("Package_DIP","DIP-14_W7.62mm"),
"nmos":("Package_TO_SOT_THT","TO-220-3_Vertical"),
"npn":("Package_TO_SOT_SMD","SOT-23"),
"res":("Resistor_SMD","R_0805_2012Metric"),
"cap":("Capacitor_SMD","C_0603_1608Metric"),
"zener":("Diode_SMD","D_SOD-123"),
}
# A value of "" denotes deliberately NC output, never a hidden ground connection.
PARTS={
"J_AUX48":("terminal",(9.,10.),"48V_AUX_PRE_POWER_DC_FUSED_INLET",{"1":"VIN48_AUX","2":"PGND"}),
"F_COIL":("fuse",(30.,10.),"2A_SLOW_75VDC_MIN_BREAKING_I2T_UNQUALIFIED",{"1":"VIN48_AUX","2":"48V_FUSED"}),
"J_ESTOP_PWR":("terminal",(51.,10.),"EXTERNAL_2_CONTACT_NC_ESTOP_CHANNEL_A",{"1":"48V_FUSED","2":"48V_AFTER_ESTOP"}),
"J_GX14COIL":("terminal",(78.,10.),"GX14FAC_48V_COIL_LEADS_EXTERNAL_NO_EXTRA_DIODE",{"1":"48V_AFTER_ESTOP","2":"COIL_DRAIN"}),
"Q_COIL":("nmos",(108.,12.),"Infineon_IRL540NPbF_100V_36A_G1D2S3",{"1":"MOS_GATE","2":"COIL_DRAIN","3":"PGND"}),
"J_BIAS":("terminal",(10.,37.),"V6_BIAS_PRIMARY_12V_PGND",{"1":"VCC12","2":"PGND"}),
"J_HEALTH":("hdr3",(10.,49.),"V6_UVLO_P_OK_S_OK_GND",{"1":"UVLO_P_OK","2":"UVLO_S_PRIMARY_OK","3":"PGND"}),
"J_HS_OK":("terminal",(10.,66.),"INDEPENDENT_HS_GH_SW_SENSOR_OK_MANDATORY",{"1":"HS_OK_IN","2":"PGND"}),
"J_ESTOP_MON":("terminal",(10.,83.),"2ND_INDEPENDENT_NC_ESTOP_CONTACT_CHANNEL_B",{"1":"VCC12","2":"ESTOP_MON_OK"}),
"J_ARM":("terminal",(40.,85.),"MOMENTARY_NO_MANUAL_RESTART_REQUIRED",{"1":"VCC12","2":"ARM_RAW"}),
"U_AND":("cmos",(46.,37.),"TI_CD4081BE_QUAD_2IN_AND",
 {"1":"UVLO_P_OK","2":"UVLO_S_PRIMARY_OK","3":"BIAS_BOTH_OK",
  "4":"EXT_BOTH_OK","5":"HS_OK_IN","6":"ESTOP_MON_OK",
  "7":"PGND","8":"BIAS_BOTH_OK","9":"EXT_BOTH_OK","10":"ALL_HEALTHY",
  "11":"COIL_ENABLE","12":"LATCH_Q","13":"ALL_HEALTHY","14":"VCC12"}),
"U_LATCH":("cmos",(89.,42.),"TI_CD4013BE_DUAL_D_FF_ACTIVE_HIGH_ASYNC_RESET",
 {"1":"LATCH_Q","2":"","3":"ARM_CLOCK","4":"RESET_ACTIVE",
  "5":"VCC12","6":"PGND","7":"PGND","8":"PGND","9":"PGND",
  "10":"PGND","11":"PGND","12":"","13":"","14":"VCC12"}),
"Q_RESET":("npn",(115.,59.),"onsemi_MMBT3904LT1G_1B_2E_3C",
 {"1":"RESET_BASE","2":"PGND","3":"RESET_ACTIVE"}),
"R_RESET_B":("res",(113.,68.),"47k_0805_1pct",{"1":"ALL_HEALTHY","2":"RESET_BASE"}),
"R_RESET_PULL":("res",(126.,68.),"10k_0805_1pct",{"1":"VCC12","2":"RESET_ACTIVE"}),
"R_GATE":("res",(100.,25.),"100R_0805",{"1":"COIL_ENABLE","2":"MOS_GATE"}),
"R_GATE_OFF":("res",(114.,31.),"100k_0805_GS_PULLDOWN",{"1":"MOS_GATE","2":"PGND"}),
"D_GS":("zener",(130.,29.),"13V_ZENER_1_CATHODE_G_2_ANODE_S_DFM_REVIEW",
  {"1":"MOS_GATE","2":"PGND"}),
"C_AND":("cap",(65.,35.),"100nF_25V",{"1":"VCC12","2":"PGND"}),
"C_LATCH":("cap",(105.,39.),"100nF_25V",{"1":"VCC12","2":"PGND"}),
"R_P_DN":("res",(28.,48.),"100k_0805_FAIL_OFF",{"1":"UVLO_P_OK","2":"PGND"}),
"R_S_DN":("res",(28.,55.),"100k_0805_FAIL_OFF",{"1":"UVLO_S_PRIMARY_OK","2":"PGND"}),
"R_HS_DN":("res",(28.,66.),"100k_0805_FAIL_OFF",{"1":"HS_OK_IN","2":"PGND"}),
"R_ESTOP_DN":("res",(28.,82.),"100k_0805_FAIL_OFF",{"1":"ESTOP_MON_OK","2":"PGND"}),
"R_ARM_DN":("res",(56.,89.),"100k_0805_FAIL_OFF",{"1":"ARM_RAW","2":"PGND"}),
"R_ARM_SER":("res",(67.,88.),"4k7_0805",{"1":"ARM_RAW","2":"ARM_CLOCK"}),
"C_ARM":("cap",(76.,88.),"100nF_25V_DEBOUNCE_START",{"1":"ARM_CLOCK","2":"PGND"}),
}
NO_OUTPUT_AUTO_RESTART=True
NETS=sorted({v for typ,xy,value,m in PARTS.values() for v in m.values() if v})
def v(x):return pcb.VECTOR2I(pcb.FromMM(x[0]),pcb.FromMM(x[1]))
def mm(x):return round(pcb.ToMM(x),3)
def sha(x):return hashlib.sha256(x.read_bytes()).hexdigest()
def board():
 b=pcb.BOARD()
 b.SetCopperLayerCount(4)
 for a,z in zip(((0,0),(BOARD_W,0),(BOARD_W,BOARD_H),(0,BOARD_H)),
                ((BOARD_W,0),(BOARD_W,BOARD_H),(0,BOARD_H),(0,0))):
  s=pcb.PCB_SHAPE(b)
  s.SetShape(pcb.SHAPE_T_SEGMENT);s.SetStart(v(a));s.SetEnd(v(z))
  s.SetWidth(pcb.FromMM(.05));s.SetLayer(pcb.Edge_Cuts);b.Add(s)
 net={}
 for name in NETS:
  n=pcb.NETINFO_ITEM(b,name);b.Add(n);net[name]=n
 refs={}
 for ref,(kind,xy,value,pins) in PARTS.items():
  lib,name=F[kind]
  obj=pcb.FootprintLoad(str(FOOTLIB/(lib+".pretty")),name)
  if obj is None:raise ValueError("OEM KiCad footprint unavailable "+str((lib,name)))
  if {p.GetNumber() for p in obj.Pads()}!=set(pins):
   raise ValueError("OEM physical pad numbering drift "+ref)
  obj.SetReference(ref);obj.SetValue(value);obj.SetPosition(v(xy))
  obj.Reference().SetVisible(False);obj.Value().SetVisible(False)
  for pad in obj.Pads():
   n=pins[pad.GetNumber()]
   if n:pad.SetNet(net[n])
  b.Add(obj);refs[ref]=obj
 return b,refs,net

def segment(b,net,a,z,w=.25,layer=pcb.F_Cu):
 t=pcb.PCB_TRACK(b);t.SetNet(net);t.SetStart(v(a));t.SetEnd(v(z));t.SetWidth(pcb.FromMM(w));t.SetLayer(layer);b.Add(t)
def stitch_supply_planes(b,refs,nets):
 # Stitch only SMD supply/ground pads to their dedicated internal planes.
 # 48V NC stop path is explicitly NOT in either supply plane.
 for ref,foot in refs.items():
  for pad in foot.Pads():
   name=pad.GetNetname()
   if name not in ("PGND","VCC12") or pad.GetAttribute()!=pcb.PAD_ATTRIB_SMD:
    continue
   px,py=mm(pad.GetPosition().x),mm(pad.GetPosition().y)
   sign=-1 if pad.GetNumber()=="1" else 1
   # Move away from the other SMD pad of a 0603/0805; leave actual via-in-pad forbidden.
   via_pos=(px+sign*1.3,py+(-.9 if name=="VCC12" else .9))
   segment(b,nets[name],(px,py),via_pos,.26)
   hole=pcb.PCB_VIA(b);hole.SetPosition(v(via_pos))
   hole.SetLayerPair(pcb.F_Cu,pcb.B_Cu)
   hole.SetWidth(pcb.FromMM(.70));hole.SetDrill(pcb.FromMM(.30))
   hole.SetNet(nets[name]);b.Add(hole)

def add_ground(b,net,layer=pcb.B_Cu,bounds=((4.,4.),(141.,4.),(141.,95.),(4.,95.))):
 zone=pcb.ZONE(b);zone.SetLayer(layer);zone.SetNet(net)
 zone.SetLocalClearance(pcb.FromMM(.4))
 zone.SetThermalReliefGap(pcb.FromMM(.5))
 zone.SetThermalReliefSpokeWidth(pcb.FromMM(.5))
 poly=zone.Outline();poly.NewOutline()
 for x,y in bounds:
  poly.Append(pcb.FromMM(x),pcb.FromMM(y))
 b.Add(zone)
def record(b):
 physical={p.GetReference():{q.GetNumber():q.GetNetname() for q in p.Pads()} for p in b.GetFootprints()}
 if set(physical)!=set(PARTS) or any(physical[r]!=c[3] for r,c in PARTS.items()):
  raise ValueError("V7 pin/net readback not match independent design")
 assert physical["U_AND"]["11"]=="COIL_ENABLE"
 assert physical["U_LATCH"]["4"]=="RESET_ACTIVE"
 assert physical["J_ESTOP_PWR"]=={"1":"48V_FUSED","2":"48V_AFTER_ESTOP"}
 assert physical["J_GX14COIL"]=={"1":"48V_AFTER_ESTOP","2":"COIL_DRAIN"}
 assert physical["Q_COIL"]=={"1":"MOS_GATE","2":"COIL_DRAIN","3":"PGND"}
 return physical

def construct():
 b,ref,net=board()
 pin=lambda r,n:(mm(next(p for p in ref[r].Pads() if p.GetNumber()==n).GetPosition().x),
                 mm(next(p for p in ref[r].Pads() if p.GetNumber()==n).GetPosition().y))
 # Actual 48V coil power path includes two pin NC contact harness connector;
 # absence of its external NC wire keeps the coil OFF independently of logic.
 for name,pairs in {
  "VIN48_AUX":[("J_AUX48","1"),("F_COIL","1")],
  "48V_FUSED":[("F_COIL","2"),("J_ESTOP_PWR","1")],
  "48V_AFTER_ESTOP":[("J_ESTOP_PWR","2"),("J_GX14COIL","1")],
  "COIL_DRAIN":[("J_GX14COIL","2"),("Q_COIL","2")]
 }.items():
  a,z=[pin(*p) for p in pairs]
  # The two connectors include a PGND pad next to +48V; deliberately
  # detour on the *near edge* rather than draw a false copper short.
  if name=="VIN48_AUX":
   points=(a,(a[0],4.8),(z[0],4.8),z)
  elif name=="COIL_DRAIN":
   points=(a,(a[0],5.8),(z[0],5.8),z)
  else:
   points=(a,z)
  for pp,qq in zip(points,points[1:]):segment(b,net[name],pp,qq,.65)
 # Ground returns via B.Cu pour. Bare wire NPN and SMD connections not yet
 # closed until the independent logic route optimizer is run/accepted.
 add_ground(b,net["PGND"],pcb.B_Cu)
 # Real 12V plane lies safely away from external 48V coil wiring corridor.
 add_ground(b,net["VCC12"],pcb.In1_Cu,
    ((4.,27.),(141.,27.),(141.,95.),(4.,95.)))
 stitch_supply_planes(b,ref,net)
 pcb.ZONE_FILLER(b).Fill(b.Zones())
 return b

def report():
 b=pcb.LoadBoard(str(BOARD))
 pins=record(b)
 dr=json.loads(DRC.read_text("utf-8"))
 return {"kind":"D1_G0_V7_NC_ESTOP_RESTART_LATCH_REAL_NATIVE_PCB_CANDIDATE",
 "status":"V7_NC_ESTOP_48V_COIL_PATH_WITH_FAIL_CLOSED_LOGIC_NOT_FOR_FAB",
 "native_footprints":len(pins),
 "pin_map":pins,
 "native_DRC_violations":len(dr.get("violations",[])),
 "native_unconnected":len(dr.get("unconnected_items",[])),
 "operator_required_to_start_after_fault_ideal_logic_only":True,
 "no_autostart_when_fault_clears_logic_contract":True,
 "coil_supply_plus_series_NC_ESTOP_hardware_connector_present":True,
 "second_NC_ESTOP_sensing_channel_required":True,
 "high_side_monitor_missing_defaults_off_only_in_UNROUTED_logic_spec":True,
 "48V_GX14FAC_internal_transorb_no_external_diode_in_design":True,
 "actual_GX14_contactor_and_2NC_emergency_stop_switch_integrated_on_board":False,
 "actual_high_side_monitor_installed":False,
 "DC_fuse_MPN_and_short_circuit_interrupt_rating_qualified":False,
 "welded_contact_fault_test_completed":False,
 "main_V5_power_board_enable_actually_wired":False,
 "physical_signoff_g0":False,"energization_allowed":False,"fabrication_approved":False,
 "source_url":DS,
 "board_sha256":sha(BOARD),"drc_sha256":sha(DRC)}
def write():
 OUT.mkdir(parents=True,exist_ok=True)
 b=construct();pcb.SaveBoard(str(BOARD),b)
 cli=Path(sys.executable).with_name("kicad-cli.exe")
 r=subprocess.run([str(cli),"pcb","drc","--severity-all","--format","json",
    "-o",str(DRC),str(BOARD)],capture_output=True,text=True,errors="replace")
 if not DRC.is_file():raise ValueError("KiCad DRC command failed: "+r.stderr)
 d=report()
 REPORT.write_text(json.dumps(d,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
 print({k:d[k] for k in ("status","native_footprints","native_DRC_violations","native_unconnected")})
 return d
def check():
 r=report()
 if r!=json.loads(REPORT.read_text("utf-8")):raise ValueError("native V7 evidence stale")
 return r
if __name__=="__main__":
 pa=argparse.ArgumentParser(description=__doc__)
 x=pa.add_mutually_exclusive_group(required=True)
 x.add_argument("--write",action="store_true");x.add_argument("--check",action="store_true")
 a=pa.parse_args()
 write() if a.write else check()
