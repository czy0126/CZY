// First executable power-board ECO, NOT a complete protection circuit.
//
// Scope: mark the hardwired U2.EN / RUN pull-up R8 as NOT POPULATED for both
// manufacturer BOM and PCB transfer. This is a transition-to-protected-design
// change: it makes the gate driver's default inhibit credible but does not
// provide an actual fail-safe HIGH permit. D1 still NOT_FOR_FAB.
//
// Run from an already opened *COPY* of the original EasyEDA Pro .eprj2. The
// extension API is Beta and this script does not silently edit anything:
//   DRY RUN: lceda-pro invoke --session <id> --ext-uuid eda \
//              --code "$(cat hardware/dcx_main/gen/eco_r8_bom_pcb_inhibit.js)"
//   APPLY:   lceda-pro invoke --session <id> --ext-uuid eda \
//              --code "const CZY_APPLY_R8_DNP=true;$(cat hardware/dcx_main/gen/eco_r8_bom_pcb_inhibit.js)"
// Run in a throwaway .eprj2 COPY first. Real use MUST also visually verify
// GUI-BOM, transfer PCB BOM, updated native netlist and actual board gerber.
// Existing schematic pin/wire network still contains R8: DNP is an
// *assembly* condition, not a physical wire cut and NOT a release approval.
//
// API references:
// https://prodocs.lceda.cn/cn/api/reference/pro-api.sch_primitivecomponent.modify.html
// https://prodocs.lceda.cn/cn/api/reference/pro-api.sch_primitivecomponent.getall.html
//
// Two identities are accepted, and the pair is checked the same way in
// read_native_inventory.js and value_eco.js:
//   * by studio uuid -- a project opened from the library carries the uuid
//     stored inside the .eprj2;
//   * by path name   -- opening the file with --path (the only supported way,
//     see CLAUDE.md) wraps it in a path-derived project whose uuid is NEW on
//     every open (f7433cc3..., 0054c1e0..., and another for a probe copy), so
//     the file stem is the only stable identity there.
// An earlier version of this script accepted only the studio uuid and would
// therefore have refused every path-opened run.  Both uuids are recorded in
// the result so the operator can see which route was taken.
// The substantive guard is the native pin map below (R8.1=VCC12, R8.2=RUN,
// R7 RUN/PGND, U2.6=RUN), which is checked before anything is modified.

const PROJECT_UUID = '14837d107b6a52feb21f43869dd7378616b33db49e6c75ae2ea6bc0a53989e46';
const PATH_OPENED_NAME = 'dcx_main_board';
const APPLY = typeof CZY_APPLY_R8_DNP !== 'undefined' && CZY_APPLY_R8_DNP === true;
const fail = (why, extra = {}) => ({ status: 'REFUSED', reason: why, applied: false, ...extra });
let info = null, board = null;
for (let i = 0; i < 20 && !board; i++) {
  info = await eda.dmt_Project.getCurrentProjectInfo();
  board = info && info.data ? info.data.find(
    b => b && b.schematic && b.schematic.page && b.schematic.page.length
  ) : null;
  if (!board) await new Promise(resolve => setTimeout(resolve, 1000));
}
if (!board) return fail('No active, loaded native EasyEDA project');
const byStudio = info.uuid === PROJECT_UUID;
const byPath = !!info.friendlyName && String(info.friendlyName) === PATH_OPENED_NAME;
const project = {
  name: info.friendlyName === undefined ? null : info.friendlyName,
  session_uuid: info.uuid === undefined ? null : info.uuid,
  stored_uuid: PROJECT_UUID,
  identified_by: byStudio ? 'studio_uuid' : (byPath ? 'path_name' : null)
};
if (!byStudio && !byPath) {
  return fail('Wrong project: refusing to modify somebody else\'s schematic',
              { expected_project: PROJECT_UUID, expected_path_opened_name: PATH_OPENED_NAME,
                actual_project: project.session_uuid, actual_name: project.name,
                project });
}
if (board.schematic.page.length !== 1) {
  return fail('Multiple schematic pages: update this script to audit all pages first');
}
await eda.dmt_EditorControl.openDocument(board.schematic.page[0].uuid);
await new Promise(resolve => setTimeout(resolve, 1600));

const jf = await eda.sch_ManufactureData.getNetlistFile('before_r8_eco.net', 'EasyEDA');
if (!jf) return fail('Cannot export a fresh native netlist');
const netlist = JSON.parse(await jf.text());
if (!netlist.components || !netlist.nets) return fail('Invalid native netlist');
const instances = Object.values(netlist.components);
const byRef = ref => instances.filter(c => c.props && c.props.Designator === ref);
const pads = c => Object.fromEntries(Object.entries(c.pinInfoMap || {}).map(
  ([k,v]) => [String(k), v && v.net === undefined ? null : (v && v.net)]
));
const want = (ref, expected) => {
  const list = byRef(ref);
  if (list.length !== 1) return 'Expected exactly one native '+ref+', found '+list.length;
  const actual = pads(list[0]);
  for (const [pin, net] of Object.entries(expected)) {
    if (actual[pin] !== net) return ref+'.'+pin+' expected '+net+', got '+actual[pin];
  }
  return null;
};
const pinError = want('R8', {'1':'VCC12','2':'RUN'})
              || want('R7', {'1':'RUN','2':'PGND'})
              || want('U2', {'6':'RUN'});
if (pinError) return fail('Pre-ECO native pin map drift: '+pinError);
const components = (await eda.sch_PrimitiveComponent.getAll())
  .filter(c => c.getState_Designator && c.getState_Designator() === 'R8');
if (components.length !== 1) {
  return fail('Expected one live R8 primitive, found '+components.length);
}
const r8 = components[0];
const id = r8.getState_PrimitiveId();
const before = {
  addIntoBom: r8.getState_AddIntoBom(),
  addIntoPcb: r8.getState_AddIntoPcb()
};
if (before.addIntoBom === false && before.addIntoPcb === false) {
  return {
    status: 'ALREADY_DNP',
    applied: false,
    project,
    ref: 'R8',
    primitiveId: id,
    before,
    warning: 'Still requires GUI/assembly independent verification; NOT_FOR_FAB'
  };
}
if (!APPLY) {
  return {
    status: 'DRY_RUN_SAFE',
    applied: false,
    project,
    ref: 'R8',
    primitiveId: id,
    before,
    expected_pads: {'1':'VCC12','2':'RUN'},
    proposed: {addIntoBom:false,addIntoPcb:false},
    release: 'NOT_FOR_FAB'
  };
}
if (before.addIntoBom !== true || before.addIntoPcb !== true) {
  return fail('Partially excluded R8: do not guess what prior ECO did', {before});
}

const result = await eda.sch_PrimitiveComponent.modify(id, {
  addIntoBom: false,
  addIntoPcb: false
});
if (!result) return fail('EDA did not confirm R8 modify operation');
const refreshed = await eda.sch_PrimitiveComponent.get(id);
if (!refreshed ||
    refreshed.getState_AddIntoBom() !== false ||
    refreshed.getState_AddIntoPcb() !== false) {
  return fail('R8 state did not read back as BOM+PCB excluded; DO NOT SAVE');
}
const saved = await eda.sch_Document.save();
if (!saved) return fail('Document save failed; inspect the GUI, do not infer success');
return {
  status: 'R8_ASSEMBLY_EXCLUSION_SAVED_NOT_VERIFIED',
  applied: true,
  project,
  ref: 'R8',
  primitiveId: id,
  before,
  after: {addIntoBom:false, addIntoPcb:false},
  warning: 'Save may be delayed. Reopen native file and independently export BOM/PCB; '
           + 'R8 remains on electrical netlist and the rest of D0 safety logic is absent.',
  release: 'NOT_FOR_FAB'
};
