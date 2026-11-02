// Create (or reuse) the two native project-library symbols the golden netlist
// needs: a 5-terminal centre-tapped transformer and a 4-terminal current
// transformer.  Output becomes hardware/dcx_main/project_symbols.json.
//
// This is the piece the board was missing: no system-library symbol has the
// required pin topology (the only 5-pad transformer symbol exposes 6 pins,
// ZHT104A exposes 2), so T1-T4 and CT had no native representation at all.
//
// Pin numbers are the LOGICAL terminal names from
// design/v3/magnetics/winding_polarity.csv.  That is deliberate: inventing a
// "1-5" numbering would read like a verified physical pad map, which it is
// not.  Physical pad numbers stay UNVERIFIED until a terminal drawing exists.
//
// Run:  lceda-pro invoke --session <id> --ext-uuid eda --timeout 60000 \
//           --code "$(cat hardware/dcx_main/gen/make_project_symbols.js)"
const PROJ = '14837d107b6a52feb21f43869dd7378616b33db49e6c75ae2ea6bc0a53989e46';
const FP_XFMR = 'e4586101a24c4442b54c19b6dc68a161';   // XFMR-TH_5P-L20.5-W18.0-P3.25-TL
const FP_CT = '1d2787765d1b434a853ff63520ce31dd';     // XFMR-TH_ZHT104A (2 pads: placeholder)

const DEFS = [
  {
    name: 'DCX_XFMR_5P',
    desc: 'DCX 24:1 centre-tapped transformer, 5 logical terminals; physical terminal drawing UNVERIFIED',
    body: [-50, -150, 100, 300],
    pins: [['PRI_A', -150, -100, 0], ['PRI_B', -150, 100, 0],
           ['SEC_A', 150, -100, 180], ['CTAP', 150, 0, 180], ['SEC_B', 150, 100, 180]],
    footprint: FP_XFMR,
  },
  {
    name: 'DCX_CT_4P',
    desc: 'DCX current transformer, 4 logical terminals; vendor pinout and polarity UNVERIFIED',
    body: [-50, -100, 100, 200],
    pins: [['PRI_A', -150, -50, 0], ['PRI_B', -150, 50, 0],
           ['SEC_A', 150, -50, 180], ['SEC_B', 150, 50, 180]],
    footprint: FP_CT,
  },
];

const out = {};
for (const d of DEFS) {
  let hit = (await eda.lib_Device.search(d.name, 'project')).find((x) => x.name === d.name);
  if (!hit) {
    await eda.lib_Device.create('project', d.name, [], { symbolType: 2 }, d.desc);
    hit = (await eda.lib_Device.search(d.name, 'project')).find((x) => x.name === d.name);
  }
  if (!hit) { out[d.name] = { error: 'device could not be created' }; continue; }

  // The symbol editor is the only context in which pins can be created, and
  // openInEditor needs the PROJECT uuid as the library handle.  Without this
  // call sch_PrimitivePin.create silently returns an unawaited descriptor.
  const opened = await eda.lib_Symbol.openInEditor(hit.symbolUuid, PROJ);
  if (!opened) { out[d.name] = { error: 'symbol editor did not open' }; continue; }

  const oldPins = (await eda.sch_PrimitivePin.getAll()).map((p) => p.primitiveId);
  if (oldPins.length) await eda.sch_PrimitivePin.delete(oldPins);
  const oldRects = (await eda.sch_PrimitiveRectangle.getAll()).map((r) => r.primitiveId);
  if (oldRects.length) await eda.sch_PrimitiveRectangle.delete(oldRects);

  await eda.sch_PrimitiveRectangle.create(d.body[0], d.body[1], d.body[2], d.body[3],
    0, 0, null, 'none', null, null, null);
  const pins = [];
  for (const [num, x, y, rot] of d.pins) {
    const p = await eda.sch_PrimitivePin.create(x, y, num, num, rot, 100, null, 'None', 'Passive');
    pins.push({ num: p.pinNumber, name: p.pinName, x: p.x, y: p.y, rotation: p.rotation, length: p.pinLength });
  }
  await eda.sch_Document.save();

  out[d.name] = {
    device_uuid: hit.uuid,
    symbol_uuid: hit.symbolUuid,
    pins,
    placeholder_footprint_uuid: d.footprint,
    description: d.desc,
  };
}
return out;
