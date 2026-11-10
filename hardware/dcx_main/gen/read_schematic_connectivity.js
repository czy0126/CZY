// Read the live schematic connectivity of a native EasyEDA Pro project.
//
// Every manufacturing export is null on a ``--path``-opened project (measured
// 2026-11-10 on the active G1 board: getNetlistFile, getSimulationNetlistFile,
// getBomFile; sch_Net.getCurrentProjectAllNets() returns [] even with the page
// open).  The primitive database still answers, and the editor itself stores the
// net name on each wire, so connectivity can be read without exporting anything.
//
// This script only READS: no modify(), no save(), no export.  It writes nothing.
//
//   lceda-pro open --path <abs .eprj2> --headless true
//   lceda-pro invoke --session <id> --ext-uuid eda \
//     --code "$(cat hardware/dcx_main/gen/read_schematic_connectivity.js)"
//
// The reader that consumes this capture is ``tools/schematic_connectivity.py``;
// it reproduces the Nov 6 editor netlist on the reference board before it is
// allowed to describe any other board.
//
// Both identities are overridable through ``globalThis.CZY_*`` set by a
// preceding invoke on the SAME session (invoke bodies share the render's global
// scope).  The defaults keep the historical main-board command in
// docs/agent/COMMANDS.md valid byte-for-byte.
const PROJECT_UUID = (typeof globalThis.CZY_EXPECTED_PROJECT_UUID === 'string')
  ? globalThis.CZY_EXPECTED_PROJECT_UUID
  : '14837d107b6a52feb21f43869dd7378616b33db49e6c75ae2ea6bc0a53989e46';
// Opening by ``--path`` does not use that identity: the editor wraps the file in
// a path-derived project whose name is the file stem and whose uuid is NOT
// stable across opens.  The file stem is the only identity a path open offers.
const PATH_OPENED_NAME = (typeof globalThis.CZY_EXPECTED_PROJECT === 'string')
  ? globalThis.CZY_EXPECTED_PROJECT : 'dcx_main_board';

const read = (obj, name) => {
  try {
    return typeof obj[name] === 'function' ? obj[name]() : null;
  } catch (e) {
    return { read_error: String(e) };
  }
};

let info = null;
let board = null;
for (let i = 0; i < 20 && !board; i++) {
  info = await eda.dmt_Project.getCurrentProjectInfo();
  board = info && info.data
    ? info.data.find(b => b && b.schematic && b.schematic.page && b.schematic.page.length)
    : null;
  if (!board) await new Promise(resolve => setTimeout(resolve, 1000));
}
if (!board) return { status: 'REFUSED', reason: 'No active, loaded native EasyEDA project' };

const byStudio = info.uuid === PROJECT_UUID;
const byPath = !!info.friendlyName && String(info.friendlyName) === PATH_OPENED_NAME;
if (!byStudio && !byPath) {
  return {
    status: 'REFUSED',
    reason: 'Wrong project: connectivity would describe somebody else\'s schematic',
    expected_project: PROJECT_UUID,
    expected_path_opened_name: PATH_OPENED_NAME,
    actual_project: info.uuid,
    actual_name: info.friendlyName,
  };
}
if (board.schematic.page.length !== 1) {
  return {
    status: 'REFUSED',
    reason: 'Multiple schematic pages: this reader reconstructs one page',
    pages: board.schematic.page.length,
  };
}

const page = board.schematic.page[0];
await eda.dmt_EditorControl.openDocument(page.uuid);
// Measured: the primitive database is empty until the document render settles.
await new Promise(resolve => setTimeout(resolve, 2500));

const wires = (await eda.sch_PrimitiveWire.getAll()).map(w => ({
  line: w.getState_Line(),
  net: w.getState_Net(),
}));

const primitives = await eda.sch_PrimitiveComponent.getAll();
const components = [];
let withoutDesignator = 0;
for (const p of primitives) {
  const ref = read(p, 'getState_Designator');
  if (!ref) { withoutDesignator += 1; continue; }
  let raw = [];
  try {
    raw = await eda.sch_PrimitiveComponent.getAllPinsByPrimitiveId(p.getState_PrimitiveId());
  } catch (e) {
    return { status: 'REFUSED', reason: `pin read failed for ${ref}: ${String(e)}` };
  }
  components.push({
    ref: String(ref),
    pins: (raw || []).map(x => ({ number: String(x.getState_PinNumber()), x: x.x, y: x.y })),
  });
}

return {
  status: 'CONNECTIVITY',
  release: 'READ_ONLY_NO_EDIT',
  opened_by: byStudio ? 'studio' : 'path',
  project_uuid: info.uuid,
  project_name: info.friendlyName || null,
  page: page.name || null,
  page_uuid: page.uuid,
  wire_count: wires.length,
  component_count: components.length,
  components_without_designator: withoutDesignator,
  wires,
  components,
};
