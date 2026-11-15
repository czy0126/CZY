"""Package source-authored G0 V7 emergency stop candidate (NO fabrication release).

A KiCad-native electrical design with real external NC coil path, vendor pins,
independent schematic/netlist, default-off reset latch and explicit remaining
unconnected signal count. PCB DRC zero does NOT imply zero opens.
"""
from __future__ import annotations
import argparse,csv,hashlib,json,shutil,subprocess,sys,zipfile
from pathlib import Path
import d1_g0_estop_interlock_v7 as v7
import d1_g0_estop_interlock_v7_schematic as sch
OUT=v7.OUT
REPORT=OUT/"V7_KICAD_INTERLOCK_INCOMPLETE_NOT_FOR_FAB_ACCEPTANCE.json"
README=OUT/"OPEN_FIRST_INCOMPLETE_NOT_FOR_FAB.md"
ZIP=OUT/"G0_V7_NC_ESTOP_MANUAL_REARM_NATIVE_KICAD_INCOMPLETE_NOT_FOR_FAB.zip"
FILES=(v7.BOARD,v7.DRC,v7.REPORT,sch.SCH,sch.PRO,sch.NET,sch.ERC,sch.SYMS,sch.LIBTAB,sch.BOM,sch.REPORT,README)

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def readme():
 return ("# G0 V7 48V NC EStop+manual re-arm — INCOMPLETE NATIVE KICAD\n\n"
  "Open the same stem .kicad_pro in KiCad 10. The real 48V coil supply path"
  " uses VIN48_AUX → F_COIL → external NC EStop contact A (J_ESTOP_PWR)"
  " → external GX14FAC coil positive (J_GX14COIL.1); coil negative"
  " → Infineon IRL540N Drain; Source→PGND. The NC contact is OPEN"
  " until wired by qualified staff and cannot be bypassed by firmware."
  " Sensata GX14 includes internal transorb: DO NOT add external flyback diode.\n\n"
  "Independent source-authored SCH has CD4081 quad AND, CD4013 asynchronous"
  " reset latch, 2nd NC EStop contact B, UVLO_P_OK, UVLO_S_PRIMARY_OK,"
  " independent HS_OK, and a manual momentary NO ARM. Any fault resets"
  " the latch; on recovery another rising ARM pulse is needed. This is"
  " a CAD logic candidate, not a certified safety relay.\n\n"
  "CRITICAL: THE PCB HAS SIGNAL NETS UNROUTED. Read"
  " V7_KICAD_INTERLOCK_INCOMPLETE_NOT_FOR_FAB_ACCEPTANCE.json for"
  " exact native KiCad unconnected count and ignored checks."
  " NO GERBER, NO PRODUCTION, NO HARDWARE POWER! External contactor,"
  " physical two-channel NC EStop switch, actual HS monitor, fault"
  " injection and contact/welded-pole detection have NOT been built or tested."
  " R8 on V5 power board remains DNP. All G0 nine physical witnesses pending.\n")
def report():
 b=v7.check()
 s=sch.check()
 if b["native_DRC_violations"]!=0 or b["native_unconnected"]<=0:
  raise ValueError("V7 scope changed, new independent review needed")
 if s["independent_ref_pin_net_parity"]!=81 or s["native_KiCad_ERC_violations"]:
  raise ValueError("V7 schematic source/nets not approved")
 return {
   "kind":"G0_V7_PHYSICAL_NC_STOP_AND_NO_AUTO_RESTART_ENGINEERING_CANDIDATE",
   "status":"NATIVE_ESTOP_COIL_COPPER_PLUS_SOURCE_SCH_SIGNAL_ROUTES_STILL_OPEN_NOT_FOR_FAB",
   "native_physical_footprint_count":b["native_footprints"],
   "native_schematic_independent_pin_parity":s["independent_ref_pin_net_parity"],
   "native_KiCad_ERC_violations":s["native_KiCad_ERC_violations"],
   "native_KiCad_DRC_violations":b["native_DRC_violations"],
   "native_KiCad_unconnected":b["native_unconnected"],
   "real_48v_COIL_path_segment_NC_2PIN_different_nets":True,
   "manual_rearm_latch_design_intent_present":True,
   "manual_rearm_copper_closed":False,
   "high_side_monitor_actual_hardware_integrated":False,
   "physical_48v_main_bus_contact_opening_proven":False,
   "NC_ESTOP_two_channels_built_tested":False,
   "G0_04_physical_approved":False,
   "G0_05_approved":False,
   "G0_09_complete_assembled_approved":False,
   "R8_mainboard_enable_released":False,
   "fabrication_approved":False,
   "energization_allowed":False,
   "native_source_files_sha256":{x.name:sha(x) for x in FILES}
 }
def write():
 OUT.mkdir(parents=True,exist_ok=True)
 README.write_text(readme(),encoding="utf-8")
 r=report()
 REPORT.write_text(json.dumps(r,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
 with zipfile.ZipFile(ZIP,"w",zipfile.ZIP_DEFLATED,compresslevel=7) as z:
  for f in (*FILES,REPORT):z.write(f,f.name)
 with zipfile.ZipFile(ZIP) as z:
  if z.testzip() or len(z.namelist())!=len(FILES)+1:raise ValueError("bad V7 ZIP")
 return r
def check():
 d=report()
 if d!=json.loads(REPORT.read_text("utf-8")):raise ValueError("V7 artifact receipt stale")
 with zipfile.ZipFile(ZIP) as z:
  if z.testzip() or set(z.namelist())!={x.name for x in (*FILES,REPORT)}:
   raise ValueError("V7 ZIP stale")
  for f in (*FILES,REPORT):
   if z.read(f.name)!=f.read_bytes():raise ValueError("V7 ZIP byte mismatch "+f.name)
 return d
if __name__=="__main__":
 p=argparse.ArgumentParser()
 g=p.add_mutually_exclusive_group(required=True)
 g.add_argument("--write",action="store_true");g.add_argument("--check",action="store_true")
 args=p.parse_args()
 x=write() if args.write else check()
 print({k:x[k] for k in ("status","native_physical_footprint_count",
 "native_schematic_independent_pin_parity","native_KiCad_DRC_violations",
 "native_KiCad_unconnected")})
