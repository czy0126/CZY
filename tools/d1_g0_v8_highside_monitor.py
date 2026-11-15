"""D1 G0 V8: physically instantiate isolated GH-SW / HB-SW sensing on the routed NC interlock board.

UNQUALIFIED BENCH PROTOTYPE: NOT_FOR_FAB / NO_48V / G0 BLOCKED.
Sensor front end uses dual AMC1311B DWV reinforced galvanic isolation,
Traco THN 30-4812 48->12 V floating source, two ON MC7805CTG LDOs,
and TI LM393B dual comparator diagnostics. Original V7 24 missing links
are closed by separate 6-layer source board routed by native KiCad.

CAUTION: GH_GATE_OFF is only a pre-start static check. It is LOW during
normal high-side PWM pulses, so it MUST NOT gate the contactor in run mode.
HB_VALID cannot exist before boot unless the *independent floating* 12V
bias is verified physically connected to the actual driver HB/SW.
The optional 0R R_HS_RELEASE is DNP and the original HS_OK_IN external
safety input is therefore still pulled LOW; there is NO G0 power permit.
"""
from __future__ import annotations
import argparse,collections,hashlib,json,subprocess,sys
from pathlib import Path
import pcbnew as pcb
import d1_g0_v8_route_interlock as routed
import d1_g0_estop_interlock_v7 as prior
import d1_g0_traco_dual_bias_daughterboard as traco

OUT=routed.OUT
STEM="d1_g0_V8_NC_ESTOP_INTEGRATED_DUAL_ISOLATED_HS_ANALOG_CANDIDATE"
BOARD=OUT/(STEM+".kicad_pcb")
DRC=OUT/(STEM+"_native_drc.json")
REPORT=OUT/"V8_integrated_HS_analog_real_pad_pin_contract_NOT_FOR_FAB.json"
WIDTH,HEIGHT=255.,160.
F={
"traco":("Converter_DCDC","Converter_DCDC_TRACO_THN30-xxxx_THT"),
"terminal":("TerminalBlock","TerminalBlock_MaiXu_MX126-5.0-02P_1x02_P5.00mm"),
"terminal3":("TerminalBlock","TerminalBlock_MaiXu_MX126-5.0-03P_1x03_P5.00mm"),
"hdr3":("Connector_PinHeader_2.54mm","PinHeader_1x03_P2.54mm_Vertical"),
"hdr4":("Connector_PinHeader_2.54mm","PinHeader_1x04_P2.54mm_Vertical"),
"l7805":("Package_TO_SOT_THT","TO-220-3_Vertical"),
"amc":("Package_SO","SOIC-8_7.5x5.85mm_P1.27mm"),
"comp":("Package_SO","SOIC-8_3.9x4.9mm_P1.27mm"),
"res":("Resistor_SMD","R_0805_2012Metric"),
"cap":("Capacitor_SMD","C_0603_1608Metric"),
"capin":("Capacitor_SMD","C_1206_3216Metric"),
"capout":("Capacitor_SMD","C_1210_3225Metric"),
"fuse":("Fuse","Fuse_1812_4532Metric"),
}
# High-side domains VIN48/PGND pre-EStop input, floating HS_VB and HS_SW,
# highside 5V, primary PRI5V/PGND. The two AMC chips alone bridge domains.
P={
"F_HS12":("fuse",(148.,13.),"2A_SLOW_DC_BREAKING_UNQUALIFIED",
 {"1":"VIN48_AUX","2":"VIN48_HS_F"}),
"U_HS12":("traco",(170.,14.),"Traco_THN_30-4812_FLOATING_12V_HS_36-75V",
 {"1":"VIN48_HS_F","2":"PGND","3":"HS_VB","4":"","5":"HS_SW","6":""}),
"C_HS_IN":("capin",(150.,24.),"1uF_100V_X7R",
 {"1":"VIN48_HS_F","2":"PGND"}),
"C_HS_OUT":("capout",(185.,48.),"22uF_25V_X7R",
 {"1":"HS_VB","2":"HS_SW"}),
"U_LDO_HS":("l7805",(178.,61.),"ON_MC7805CTG_FLOATING_5V",
 {"1":"HS_VB","2":"HS_SW","3":"HS5V"}),
"C_HS5":("cap",(189.,68.),"100nF_25V_X7R",
 {"1":"HS5V","2":"HS_SW"}),
"U_LDO_P":("l7805",(234.,34.),"ON_MC7805CTG_PRIMARY_5V",
 {"1":"VCC12","2":"PGND","3":"PRI5V"}),
"C_PRI5":("cap",(240.,53.),"100nF_25V_X7R",
 {"1":"PRI5V","2":"PGND"}),
"J_HS_SENSE":("terminal3",(151.,88.),"HIGH_SIDE_GH1_HB_AND_KELVIN_SW_FROM_ACTUAL_DRIVER",
 {"1":"GH_RAW","2":"HB_RAW","3":"HS_SW"}),
"J_HS_FLOAT_BIAS":("terminal",(152.,131.),"FLOATING_12V_HB_AND_SW_TO_DRIVER_CHECK_V5_COMPATIBILITY",
 {"1":"HS_VB","2":"HS_SW"}),
"R_GH_TOP":("res",(175.,91.),"100k_1pct_GH_DIVIDER",
 {"1":"GH_RAW","2":"GH_DIV"}),
"R_GH_BOT":("res",(175.,99.),"10k_1pct_GH_DIVIDER",
 {"1":"GH_DIV","2":"HS_SW"}),
"R_HB_TOP":("res",(180.,109.),"100k_1pct_HB_DIVIDER",
 {"1":"HB_RAW","2":"HB_DIV"}),
"R_HB_BOT":("res",(180.,117.),"10k_1pct_HB_DIVIDER",
 {"1":"HB_DIV","2":"HS_SW"}),
"U_GH_SENSE":("amc",(212.,79.),"TI_AMC1311BDWVR_REINFORCED_ISOLATION_GH_MINUS_SW",
 {"1":"HS5V","2":"GH_DIV","3":"HS_SW","4":"HS_SW","5":"PGND",
  "6":"GH_OUTN","7":"GH_OUTP","8":"PRI5V"}),
"U_HB_SENSE":("amc",(212.,116.),"TI_AMC1311BDWVR_REINFORCED_ISOLATION_HB_MINUS_SW",
 {"1":"HS5V","2":"HB_DIV","3":"HS_SW","4":"HS_SW","5":"PGND",
  "6":"HB_OUTN","7":"HB_OUTP","8":"PRI5V"}),
"C_GH_H":("cap",(196.,78.),"100nF_HS5V_LOCAL",
 {"1":"HS5V","2":"HS_SW"}),
"C_GH_L":("cap",(226.,78.),"100nF_PRI5V_LOCAL",
 {"1":"PRI5V","2":"PGND"}),
"C_HB_H":("cap",(196.,115.),"100nF_HS5V_LOCAL",
 {"1":"HS5V","2":"HS_SW"}),
"C_HB_L":("cap",(226.,115.),"100nF_PRI5V_LOCAL",
 {"1":"PRI5V","2":"PGND"}),
"U_HS_COMP":("comp",(233.,112.),"TI_LM393BIDR_DIAGNOSTIC_ONLY",
 {"1":"HB_VALID","2":"HB_REF","3":"HB_OUTP","4":"PGND",
  "5":"GH_REF","6":"GH_OUTP","7":"GH_GATE_OFF","8":"PRI5V"}),
"R_HB_RTOP":("res",(229.,136.),"16k_0805_REF_HB_1pct",
 {"1":"PRI5V","2":"HB_REF"}),
"R_HB_RBOT":("res",(237.,136.),"10k_0805_REF_HB",
 {"1":"HB_REF","2":"PGND"}),
"R_GH_RTOP":("res",(229.,144.),"22k_0805_REF_GH",
 {"1":"PRI5V","2":"GH_REF"}),
"R_GH_RBOT":("res",(237.,144.),"10k_0805_REF_GH",
 {"1":"GH_REF","2":"PGND"}),
"R_HB_PULL":("res",(246.,133.),"4k7_0805_HB_VALID_PRI5V_PULL",
 {"1":"PRI5V","2":"HB_VALID"}),
"R_GH_PULL":("res",(246.,141.),"4k7_0805_GH_OFF_PRI5V_PULL",
 {"1":"PRI5V","2":"GH_GATE_OFF"}),
"J_HS_DIFF":("hdr4",(242.,78.),"GH_OUTP_GH_OUTN_HB_OUTP_HB_OUTN",
 {"1":"GH_OUTP","2":"GH_OUTN","3":"HB_OUTP","4":"HB_OUTN"}),
"J_HS_FLAGS":("hdr3",(241.,122.),"HB_VALID_GH_OFF_PGND_DIAGNOSTICS_ONLY",
 {"1":"HB_VALID","2":"GH_GATE_OFF","3":"PGND"}),
"R_HS_RELEASE":("res",(238.,152.),"0R_DNP_ALWAYS_NO_AUTO_ENABLE_OR_SELF_TEST_BYPASS",
 {"1":"HB_VALID","2":"HS_OK_IN"}),
"C_HS_COMP":("cap",(241.,105.),"100nF_PRI5V_TO_PGND",
 {"1":"PRI5V","2":"PGND"}),
}
VENDOR={
"U_HS12":"https://www.tracopower.com/products/thn30.pdf",
"U_GH_SENSE":"https://www.ti.com/lit/ds/symlink/amc1311.pdf",
"U_HB_SENSE":"https://www.ti.com/lit/ds/symlink/amc1311.pdf",
"U_HS_COMP":"https://www.ti.com/lit/ds/symlink/lm393b.pdf",
"U_LDO_HS":"https://www.onsemi.com/download/data-sheet/pdf/mc7800-d.pdf",
"U_LDO_P":"https://www.onsemi.com/download/data-sheet/pdf/mc7800-d.pdf",
}
def v(pt):return prior.v(pt)
def mm(x):return round(pcb.ToMM(x),4)
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def zone(b,name,layer,xy):
 z=pcb.ZONE(b);z.SetLayer(layer)
 z.SetNet({str(n):o for n,o in b.GetNetsByName().items()}[name])
 z.SetLocalClearance(pcb.FromMM(.40))
 z.SetThermalReliefGap(pcb.FromMM(.48))
 z.SetThermalReliefSpokeWidth(pcb.FromMM(.48))
 outline=z.Outline()
 outline.NewOutline()
 for x,y in xy:outline.Append(pcb.FromMM(x),pcb.FromMM(y))
 b.Add(z)
 return z
def segment(b,name,points,layer=pcb.F_Cu,width=.35):
 n={str(z):o for z,o in b.GetNetsByName().items()}[name]
 for a,c in zip(points,points[1:]):
  if a==c:continue
  tr=pcb.PCB_TRACK(b)
  tr.SetNet(n);tr.SetStart(v(a));tr.SetEnd(v(c))
  tr.SetLayer(layer);tr.SetWidth(pcb.FromMM(width));b.Add(tr)
def placement():
 b=pcb.LoadBoard(str(routed.BOARD))
 if b.GetCopperLayerCount()!=6:raise ValueError("expected V8 zero-open 6-layer original")
 # Expand the real native PCB frame, leave all existing 24 completed nets fixed.
 for edge in b.GetDrawings():
  if edge.GetLayer()!=pcb.Edge_Cuts:continue
  for get,setter in ((edge.GetStart,edge.SetStart),(edge.GetEnd,edge.SetEnd)):
   original=get();x=mm(original.x);y=mm(original.y)
   if abs(x-prior.BOARD_W)<.05:x=WIDTH
   if abs(y-prior.BOARD_H)<.05:y=HEIGHT
   setter(v((x,y)))
 nets={str(name):o for name,o in b.GetNetsByName().items()}
 for spec in P.values():
  for name in spec[3].values():
   if name and name not in nets:
    ni=pcb.NETINFO_ITEM(b,name)
    b.Add(ni);nets[name]=ni
 pads={}
 for ref,(kind,position,value,pinmap) in P.items():
  lib,foot=F[kind]
  fp=pcb.FootprintLoad(str(prior.FOOTLIB/(lib+".pretty")),foot)
  if fp is None:raise ValueError("KiCad 10 footprint unavailable: "+str((lib,foot)))
  if {pad.GetNumber() for pad in fp.Pads()}!=set(pinmap):
   raise ValueError("source pin map mismatches installed KiCad pad "+ref)
  fp.SetReference(ref)
  fp.SetValue(value)
  fp.SetPosition(v(position))
  if ref=="R_HS_RELEASE":
   # The diagnostic HB_VALID line MUST NOT become a hardware start permit;
   # mark this link KiCad-native DNP, not just a suggestive resistor Value.
   fp.SetDNP(True)
  fp.Reference().SetVisible(False);fp.Value().SetVisible(False)
  for pad in fp.Pads():
   name=pinmap[pad.GetNumber()]
   if name:pad.SetNet(nets[name])
  b.Add(fp)
  pads[ref]={pad.GetNumber():(mm(pad.GetPosition().x),mm(pad.GetPosition().y))
             for pad in fp.Pads()}
 # Preserve the 48V NC coil path unchanged and provide primary ground routing
 # around (NEVER through) the galvanically isolated SW-floating island.
 zone(b,"PGND",pcb.B_Cu,((142,4),(251,4),(251,20),(142,20)))
 zone(b,"PGND",pcb.B_Cu,((218,23),(251,23),(251,155),(218,155)))
 # Physically bridge same-net zones without overlapping zone polygons.
 segment(b,"PGND",[(139,16),(145,16)],pcb.B_Cu,.55)
 segment(b,"PGND",[(237,18),(237,26)],pcb.B_Cu,.55)
 zone(b,"HS_SW",pcb.B_Cu,((150,45),(205,45),(205,141),(150,141)))
 zone(b,"HS_VB",pcb.In3_Cu,((150,45),(205,45),(205,141),(150,141)))
 zone(b,"HS5V",pcb.In1_Cu,((151,46),(205,46),(205,141),(151,141)))
 zone(b,"PRI5V",pcb.In1_Cu,((218,46),(251,46),(251,155),(218,155)))
 # Float module input is pre-main-power fused; there is no ordinary
 # anti-parallel flyback diode across GX14FAC's internal Transorb.
 segment(b,"VIN48_AUX",[pads["F_HS12"]["1"],(145.8625,3.3),(27.86,3.3),(27.86,10)],pcb.F_Cu,.38)
 segment(b,"VIN48_HS_F",[pads["F_HS12"]["2"],pads["U_HS12"]["1"]],pcb.F_Cu,.48)
 # The two supply rails generated by THN30 only contact the SW island.
 segment(b,"HS_SW",[pads["U_HS12"]["5"],(177.7,45.6)],pcb.B_Cu,.38)
 segment(b,"HS_VB",[pads["U_HS12"]["3"],(162.38,45.8)],pcb.In3_Cu,.38)
 # Primary +12 V must stay OUTSIDE the SW island. Travel below the 141mm
 # isolated SW ground boundary using a dedicated In3.Cu control trace.
 J_BIAS1=(10.,37.)
 segment(b,"VCC12",[J_BIAS1,(5,37),(5,156),(252,156),(252,27),(230,27),(230,34),(234,34)],pcb.In3_Cu,.30)
 # Primary 5V LDO goes down to its own plane, not connected to SW.
 segment(b,"PRI5V",[pads["U_LDO_P"]["3"],(239.08,47)],pcb.In1_Cu,.35)
 pcb.ZONE_FILLER(b).Fill(b.Zones())
 return b,pads
def check_pinmap(b):
 data={}
 for f in b.GetFootprints():
  if f.GetReference() not in P:continue
  ref=f.GetReference()
  actual={p.GetNumber():p.GetNetname() for p in f.Pads()}
  if actual!=P[ref][3]:raise ValueError("V8 real OEM pad pin mismatch "+ref)
  data[ref]=actual
 if set(data)!=set(P):raise ValueError("missing actual isolated monitor footprints")
 if data["U_GH_SENSE"]!={"1":"HS5V","2":"GH_DIV","3":"HS_SW","4":"HS_SW",
                         "5":"PGND","6":"GH_OUTN","7":"GH_OUTP","8":"PRI5V"}:
   raise ValueError("AMC1311B actual 8-pin highside isolation pinout wrong")
 if data["U_HS12"]!={"1":"VIN48_HS_F","2":"PGND","3":"HS_VB","4":"","5":"HS_SW","6":""}:
   raise ValueError("THN30 OEM pinout changed")
 release=next(f for f in b.GetFootprints() if f.GetReference()=="R_HS_RELEASE")
 if not release.IsDNP():
   raise ValueError("unsafe G0: HS diagnostic 0R bridge not DNP in native KiCad")
 if data["R_HS_RELEASE"]!={"1":"HB_VALID","2":"HS_OK_IN"}:
   raise ValueError("No rearm release permitted, DNP 0R contact net must differ")
 return data
def write():
 OUT.mkdir(parents=True,exist_ok=True)
 b,pads=placement()
 pcb.SaveBoard(str(BOARD),b)
 cli=Path(sys.executable).with_name("kicad-cli.exe")
 q=subprocess.run([str(cli),"pcb","drc","--severity-all","--format","json",
          "-o",str(DRC),str(BOARD)],capture_output=True,text=True,errors="replace")
 if not DRC.is_file():raise ValueError("V8 monitor native KiCad DRC failed "+q.stderr)
 d=json.loads(DRC.read_text("utf-8"))
 data={"kind":"D1_G0_V8_ACTUAL_ISOLATED_AMC1311B_HS_FRONTEND_NATIVE_PCB",
       "status":"MONITOR_COMPONENTS_NATIVELY_PLACED_ROUTING_PENDING_NOT_FOR_FAB",
       "integrated_native_footprint_count":len(b.GetFootprints()),
       "monitor_added_footprint_count":len(P),
       "monitor_real_pad_net_contract":check_pinmap(b),
       "native_DRC_violations":len(d.get("violations",[])),
       "native_unconnected":len(d.get("unconnected_items",[])),
       "nominal_12v_input_voltage_ratio":10/110,
       "nominal_12v_ADC_highside_input_v":12*10/110,
       "reference_HB_valid_typical_v":5*10/26,
       "nominal_HB_SW_input_trip_v":(5*10/26-1.44)*2*11,
       "AMC1311B_output_common_mode_data_min_v":1.39,
       "AMC1311B_output_common_mode_data_max_v":1.49,
       "HB_valid_comparator_is_diagnostic_only_not_signed_UVLO":True,
       "HB_and_GH_diag_outputs_pull_to_PRI5V_not_primary_12V":True,
       "no_5V_to_12V_logic_level_translation_approved":True,
       "reference_GH_off_typical_v":5*10/32,
       "actual_GH_MINUS_SW_and_HB_MINUS_SW_reinforced_isolation_device_pads":True,
       "high_side_12v_independent_precharge_module_native_pads":True,
       "GH_static_OFF_must_NOT_be_used_as_PWM_runtime_permission":True,
       "R_HS_RELEASE_DNP_unpopulated":True,
       "true_HS_OK_IN_to_run_gate_closed":False,
       "real_isolated_power_modules_assembled":False,
       "actual_isolation_barrier_tested":False,
       "G0_05_physical_approval":False,
       "fab_approved":False,"energization_allowed":False,
       "vendor_datasheets":VENDOR,
       "native_board_sha256":sha(BOARD),"native_drc_sha256":sha(DRC)}
 REPORT.write_text(json.dumps(data,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
 print(json.dumps({x:data[x] for x in ("integrated_native_footprint_count",
     "monitor_added_footprint_count","native_DRC_violations","native_unconnected")}))
 return data
def check():
 d=json.loads(REPORT.read_text("utf-8"))
 b=pcb.LoadBoard(str(BOARD))
 if d["monitor_real_pad_net_contract"]!=check_pinmap(b) or d["native_board_sha256"]!=sha(BOARD):
  raise ValueError("V8 native KiCad monitor changed")
 return d
if __name__=="__main__":
 pa=argparse.ArgumentParser()
 g=pa.add_mutually_exclusive_group(required=True)
 g.add_argument("--write",action="store_true")
 g.add_argument("--check",action="store_true")
 a=pa.parse_args()
 write() if a.write else check()
