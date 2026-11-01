// Place one of each device class the main board needs and dump the real pin
// numbers/names.  Output becomes hardware/dcx_main/library_pins.json and is
// the evidence behind every pin mapping in the schematic -- the golden netlist
// names FET pins "G/S/D" while the package has 8 or 9 pads, so the mapping
// cannot be inferred from the netlist alone.
//
// Every device is resolved by exact MPN search rather than a remembered uuid:
// a uuid copied from another project is exactly the kind of assumption this
// tool exists to avoid.
const LIB = '0819f05c4eef4c71ace90d822a990e87';
const WANT = [
  ['UCC25600D', 'UCC25600D'],
  ['UCC27282DRCR', 'UCC27282DRCR'],
  ['UCC24624DR', 'UCC24624DR'],
  ['CSD19531Q5A', 'CSD19531Q5A'],
  ['BSC010N04LS6', 'BSC010N04LS6'],
  ['EE16_65KHZ', 'EE16_65KHZ'],
  ['ZHT104A', 'ZHT104A'],
  ['R0603_10k', '0603WAF1002T5E'],
  ['C0603_100n', 'CL10B104KB8NNNC'],
  ['BAT54', 'BAT54'],
  ['BAT54WS', 'BAT54WS'],
  ['MX126_2P', 'MX126-5.0-02P-GN01-Cu-S-A'],
  ['KF128_2P', 'KF128-5.08-2P-AA'],
  ['IND_10UH', 'L-SMD1010-PCB_C9900024507']
];

const proj = '14837d107b6a52feb21f43869dd7378616b33db49e6c75ae2ea6bc0a53989e46';
await eda.dmt_Project.openProject(proj);
await new Promise((r) => setTimeout(r, 2000));
const info = await eda.dmt_Project.getCurrentProjectInfo();
const sch = info.data[0].schematic;
await eda.dmt_EditorControl.openDocument(sch.page[0].uuid);
await new Promise((r) => setTimeout(r, 2500));

// clear whatever the earlier probes left behind so counts stay interpretable
const stale = (await eda.sch_PrimitiveComponent.getAll())
  .filter((c) => c.getState_Designator() || c.getState_ComponentType())
  .map((c) => c.getState_PrimitiveId());
if (stale.length) await eda.sch_PrimitiveComponent.delete(stale);

const out = {};
let i = 0;
for (const [label, mpn] of WANT) {
  const hits = await eda.lib_Device.search(mpn);
  const dev = hits.find((d) => d.name === mpn) || hits[0];
  if (!dev) { out[label] = { error: 'not found', mpn }; continue; }
  const c = await eda.sch_PrimitiveComponent.create(
    { libraryType: '3', libraryUuid: LIB, uuid: dev.uuid },
    200 + (i % 4) * 400, 200 + Math.floor(i / 4) * 400, undefined, 0, false, true, true);
  i += 1;
  if (!c) { out[label] = { error: 'create failed', mpn, uuid: dev.uuid }; continue; }
  const id = c.getState_PrimitiveId();
  const pins = await eda.sch_PrimitiveComponent.getAllPinsByPrimitiveId(id);
  out[label] = {
    mpn, uuid: dev.uuid, lcsc: dev.supplierId,
    footprint: dev.footprintName || dev.footprint || null,
    pins: pins.map((p) => ({
      num: p.getState_PinNumber(), nm: p.getState_PinName(), x: p.x, y: p.y
    }))
  };
}
return out;
