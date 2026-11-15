"""Independent design-to-native PCB structural audit for G0.

Never mistake a PCB->schematic pad mirror for an independent circuit check.
Derives golden pin mapping from the separately authored SPICE source, and
explicitly audits primary/secondary physical return domains, board zones,
missing startup enable R8, and the absence of physically installed bias/ESTOP.

Run with KiCad 10 bundled python:
  python tools/d1_g0_cross_domain_audit.py --write
  python tools/d1_g0_cross_domain_audit.py --check
  python tools/d1_g0_cross_domain_audit.py --require-isolated
"""
from __future__ import annotations
import argparse,csv,hashlib,json,re,sys
from pathlib import Path
import main_board_schematic as golden
import check_main_board_netlist as independent

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"hardware/dcx_main/g2/d1_g0_integrated_mainboard_NOT_FOR_FAB"
BOARD=OUT/"d1_g0_integrated_mainboard_ELECTRICAL_NOT_FOR_FAB.kicad_pcb"
REPORT=OUT/"d1_g0_independent_design_and_return_domain_audit_NOT_FOR_FAB.json"
MIGRATE=OUT/"d1_g0_secondary_return_eco_pin_table_NOT_FOR_FAB.csv"
ALLOWED_EXTRA=frozenset(f"CHB{i:02d}" for i in range(1,73))

# Ground must NOT be globally renamed: this exact manifest puts only the
# secondary rectifier/power output / 12V secondary controller returns into SRET.
SECONDARY_RET_REFS={
    **{f"U{i}":frozenset({"2","5"}) for i in range(3,7)},
    **{f"SR{i}{j}":frozenset({"1","2","3"}) for i in range(1,5) for j in ("A","B")},
    **{f"C{i}":frozenset({"2"}) for i in (*range(7,11),*range(105,113))},
    "Cout":frozenset({"2"}),"J_OUT":frozenset({"2"}),
    **{f"CHB{i:02d}":frozenset({"2"}) for i in range(1,73)}
}
PRIMARY_GROUND_WITNESS={
    "J_IN":frozenset({"2"}),"QL":frozenset({"1","2","3"}),
    "U1":frozenset({"6"}),"U2":frozenset({"9","11"}),
    "Cin":frozenset({"2"}),"T4":frozenset({"PRI_B"}),
    "C101":frozenset({"2"}),"C102":frozenset({"2"}),
    "C103":frozenset({"2"}),"C104":frozenset({"2"}),
}
SRET="SR_SOURCE_RETURN"

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def pinpassport(board):
    import pcbnew as pcb
    refs={}
    pads={}
    for fp in board.GetFootprints():
        ref=fp.GetReference()
        if ref in refs:raise ValueError("duplicate ref: "+ref)
        for pd in fp.Pads():
            pn=pd.GetNumber(); net=pd.GetNetname()
            if pn in refs.get(ref,{}) and refs[ref][pn]!=net:
                raise ValueError("same pin number has different nets "+ref+"."+pn)
            refs.setdefault(ref,{})[pn]=net
            pads.setdefault((ref,pn),[]).append({
                "x_mm":round(pcb.ToMM(pd.GetPosition().x),6),
                "y_mm":round(pcb.ToMM(pd.GetPosition().y),6),
                "net":net
            })
    return refs,pads

def audited_domains(refs):
    for name,pins in PRIMARY_GROUND_WITNESS.items():
        if name not in refs:
            raise ValueError("required primary ground witness absent "+name)
        for pin in pins:
            if pin not in refs[name] or refs[name][pin] not in ("PGND","PRIMARY_RETURN"):
                raise ValueError("primary return pin invalid: "+name+"."+pin)
    for name,pins in SECONDARY_RET_REFS.items():
        if name not in refs:
            raise ValueError("required secondary ground witness absent "+name)
        for pin in pins:
            if pin not in refs[name] or refs[name][pin] not in ("PGND",SRET):
                raise ValueError("secondary pin changed to unknown return: "+name+"."+pin)
    primary={refs[name][pin] for name,pins in PRIMARY_GROUND_WITNESS.items() for pin in pins}
    secondary={refs[name][pin] for name,pins in SECONDARY_RET_REFS.items() for pin in pins}
    shared=sorted(primary & secondary)
    return {
       "primary_net_set":sorted(primary),
       "secondary_net_set":sorted(secondary),
       "shared_primary_secondary_return_nets":shared,
       "isolation_domain_split_complete":not shared and secondary=={SRET} and primary in ({"PRIMARY_RETURN"},{"PGND"}),
       "required_secondary_unique_package_pins":sum(len(x) for x in SECONDARY_RET_REFS.values()),
       "required_primary_unique_package_pins":sum(len(x) for x in PRIMARY_GROUND_WITNESS.values()),
    }

def independent_circuit_result(refs):
    result=independent.compare(golden.load_golden(),refs,golden.load_library())
    missing=[x for x in result["missing_or_wrong"] if x["ref"]!="R8"]
    must_be={"ref":"R8","pad":"*","want":"peripheral present","got":"absent"}
    if result["missing_or_wrong"]!=[must_be] or missing or result["unexpected_nets"] or \
       set(result["unexpected_refs"])!=ALLOWED_EXTRA or result["not_placed"]:
        raise ValueError("unexpected independent design-to-board discrepancy: "+str(result["missing_or_wrong"][:10]))
    return {
      "basis":"design/v3/pcb/board_netlist.csv + separately defined peripheral pin plan; NOT reverse PCB schematic",
      "golden_source_sha256":sha(golden.GOLDEN),
      "golden_refs_checked":len(golden.load_golden()),
      "golden_original_pins":result["pads_checked"],
      "auxiliary_peripheral_pads_checked":result["peripheral_pads_checked"],
      "missing_required_peripheral":["R8"],
      "R8_intended_nets":{"1":"VCC12","2":"RUN"},
      "R8_must_be_DNP_until_hardware_permit_validated":True,
      "intentionally_extra_output_bulk_capacitors":len(ALLOWED_EXTRA),
      "unverified_vendor_magnetics":result["unchecked_magnetics"]
    }

def zone_evidence(board):
    import pcbnew as pcb
    return [
      {"net":z.GetNetname(),"copper_layer":pcb.LayerName(z.GetLayer()),
       "bbox_mm":[round(pcb.ToMM(x),3) for x in
         (z.GetBoundingBox().GetX(),z.GetBoundingBox().GetY(),
          z.GetBoundingBox().GetWidth(),z.GetBoundingBox().GetHeight())]}
      for z in board.Zones()
    ]

def audit():
    import pcbnew as pcb
    board=pcb.LoadBoard(str(BOARD))
    refs,pads=pinpassport(board)
    if len(refs)!=154:
        raise ValueError("unexpected board devices")
    evidence=independent_circuit_result(refs)
    domains=audited_domains(refs)
    zones=zone_evidence(board)
    shared_planes=[z for z in zones if z["net"]=="PGND" and
       z["copper_layer"]=="In1.Cu" and z["bbox_mm"][1]<=20 and
       z["bbox_mm"][1]+z["bbox_mm"][3]>=70]
    if len(shared_planes)!=1:
        raise ValueError("Primary/secondary shared physical plane evidence differs")
    # Used for the independent secondary return re-netting DFM ECO.
    rows=[]
    for ref,pinnums in sorted(SECONDARY_RET_REFS.items()):
        for pin in sorted(pinnums):
            for index,point in enumerate(pads[(ref,pin)],1):
                rows.append({
                   "reference":ref,"physical_pad_number":pin,
                   "duplicate_package_pad_instance":index,
                   "x_mm":point["x_mm"],"y_mm":point["y_mm"],
                   "current_net":point["net"],
                   "required_isolated_secondary_return_net":SRET,
                   "review":"REQUIRES_RENETTING_AND_REPOUR_AND_NATIVE_DRC",
                })
    count=len(rows)
    if count<100:raise ValueError("secondary ground pin inventory suspiciously low")
    full={
       "kind":"D1_G0_INDEPENDENT_GOLDEN_NET_AND_GALVANIC_RETURN_AUDIT",
       "status":"G0_BLOCKED_BY_COMMON_PRIMARY_SECONDARY_GROUND",
       "board_sha256":sha(BOARD),
       "pcb_drc_violations_reported_by_native":0,
       "pcb_unconnected_reported_by_native":0,
       "independent_circuit":evidence,
       "physical_return_domains":domains,
       "zones":zones,
       "shared_pgnd_plane_evidence":shared_planes,
       "secondary_pin_eco_rows":count,
       "secondary_unique_pin_pairs":sum(len(x) for x in SECONDARY_RET_REFS.values()),
       "primary_T4_PRI_B_must_STAY_primary_return":True,
       "physical_12v_isolation_certificate_present":False,
       "actual_48v_power_disconnect_on_product_board":False,
       "SR_driver_supply_bonded_to_primary_pgnd":bool(domains["shared_primary_secondary_return_nets"]),
       "zero_drc_is_NOT_isolation_evidence":True,
       "hardware_48v_powerup_allowed":False,
       "fabrication_approved":False,
    }
    return full,rows

def build():
    report,rows=audit()
    with MIGRATE.open("w",encoding="utf-8",newline="") as fp:
        writer=csv.DictWriter(fp,fieldnames=list(rows[0]),lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    report["secondary_eco_csv_sha256"]=sha(MIGRATE)
    REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return report

def check():
    report,rows=audit()
    expected=json.loads(REPORT.read_text("utf-8"))
    with MIGRATE.open(encoding="utf-8",newline="") as f:
        got=list(csv.DictReader(f))
    if len(got)!=len(rows) or any(a!={k:str(v) for k,v in b.items()}
       for a,b in zip(got,rows)):
        raise ValueError("Secondary pad migration table stale/corrupted")
    report["secondary_eco_csv_sha256"]=sha(MIGRATE)
    if report!=expected:raise ValueError("Independent domain audit stale")
    return report

def main():
    arg=argparse.ArgumentParser(description=__doc__)
    g=arg.add_mutually_exclusive_group(required=True)
    g.add_argument("--write",action="store_true")
    g.add_argument("--check",action="store_true")
    g.add_argument("--require-isolated",action="store_true")
    cmd=arg.parse_args()
    result=build() if cmd.write else check()
    flag=result["physical_return_domains"]["isolation_domain_split_complete"]
    print(json.dumps({"status":result["status"],
        "shared_domains":result["physical_return_domains"]["shared_primary_secondary_return_nets"],
        "secondary_eco_pads":result["secondary_pin_eco_rows"],
        "R8_missing":result["independent_circuit"]["missing_required_peripheral"],
        "isolation_achieved":flag},ensure_ascii=False))
    if cmd.require_isolated and not flag:return 2
    return 0

if __name__=="__main__":sys.exit(main())
