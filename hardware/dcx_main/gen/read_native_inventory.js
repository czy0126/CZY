// Read-only inventory of the native EasyEDA Pro main board.
//
// Item 4 of the 48-hour delivery card needs the standard-device ECO batch
// applied to the one authoritative native project.  ``gen/netlist_export_raw.json``
// only carries ref -> {pin: net}: it has no values, packages or footprints, so
// the batch cannot be built from it.  This script reads the live editor instead
// and writes nothing at all -- no modify(), no save(), no file export.
//
//   lceda-pro open --path hardware/dcx_main/dcx_main_board.eprj2 --headless true
//   lceda-pro invoke --session <id> --ext-uuid eda \
//     --code "$(cat hardware/dcx_main/gen/read_native_inventory.js)"
//
// Two measured facts shape this script:
//   * ``sch_ManufactureData.getNetlistFile`` returns null on a path-opened
//     project, so pins come from ``getAllPins()``; the ref -> {pin: net} map
//     stays in ``gen/netlist_export_raw.json``, which is why nets are not here.
//   * ``getState_Name()`` is the template ``={Value}``; the actual value lives in
//     ``otherProperty.Value`` and the orderable part in ``otherProperty``
//     (LCSC Part Name / JLCPCB Part Class / Datasheet).
//
// The declared getters are probed defensively: this build has no footprint
// *setter*, and an absent getter must read as null here rather than abort the
// whole dump (that would hide the 80 rows that did read).

// The stored project UUID (what ``projects.uuid`` holds inside the .eprj2).
const PROJECT_UUID = '14837d107b6a52feb21f43869dd7378616b33db49e6c75ae2ea6bc0a53989e46';
// Opening by ``--path`` does not use that identity: the editor wraps the file in
// a path-derived project whose name is the file stem.  Its uuid is NOT stable --
// three opens of the same file produced
//   f7433cc355c5f70b249844e3f3d9ad03d4de720eade3465d75c5a7b49ed79829,
//   0054c1e0f493b9ebf3517da33827a1985e43c2e9a23f621e11cf5b82f136a085,
//   and a different one for the ``dcx_probe`` copy.
// An earlier version of this comment claimed it was stable across two opens and
// used that as the reason the name check sufficed.  The conclusion still holds,
// but for the opposite reason: the uuid cannot be matched at all, so the file
// stem is the ONLY identity this script can check.
const PATH_OPENED_NAME = 'dcx_main_board';

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
    reason: 'Wrong project: inventory would describe somebody else\'s schematic',
    expected_project: PROJECT_UUID,
    expected_path_opened_name: PATH_OPENED_NAME,
    actual_project: info.uuid,
    actual_name: info.friendlyName,
  };
}
if (board.schematic.page.length !== 1) {
  return {
    status: 'REFUSED',
    reason: 'Multiple schematic pages: this script audits one page',
    pages: board.schematic.page.length,
  };
}
await eda.dmt_EditorControl.openDocument(board.schematic.page[0].uuid);
await new Promise(resolve => setTimeout(resolve, 1600));

const primitives = await eda.sch_PrimitiveComponent.getAll();
const components = [];
for (const p of primitives) {
  const other = read(p, 'getState_OtherProperty') || {};
  let pins = [];
  try {
    const raw = typeof p.getAllPins === 'function' ? await p.getAllPins() : [];
    pins = (raw || []).map(x => ({
      number: x && (x.pinNumber !== undefined ? x.pinNumber : x.number) !== undefined
        ? String(x.pinNumber !== undefined ? x.pinNumber : x.number) : null,
      name: x && x.pinName !== undefined ? String(x.pinName) : null,
    }));
  } catch (e) {
    pins = [{ error: String(e) }];
  }
  components.push({
    ref: read(p, 'getState_Designator'),
    name_template: read(p, 'getState_Name'),
    value: other.Value === undefined ? null : other.Value,
    lcsc_part: other['LCSC Part Name'] === undefined ? null : other['LCSC Part Name'],
    supplier_footprint: other['Supplier Footprint'] === undefined ? null : other['Supplier Footprint'],
    jlcpcb_class: other['JLCPCB Part Class'] === undefined ? null : other['JLCPCB Part Class'],
    datasheet: other.Datasheet === undefined ? null : other.Datasheet,
    footprint: read(p, 'getState_Footprint'),
    component: read(p, 'getState_Component'),
    symbol: read(p, 'getState_Symbol'),
    manufacturer: read(p, 'getState_Manufacturer'),
    manufacturer_id: read(p, 'getState_ManufacturerId'),
    supplier: read(p, 'getState_Supplier'),
    supplier_id: read(p, 'getState_SupplierId'),
    add_into_bom: read(p, 'getState_AddIntoBom'),
    add_into_pcb: read(p, 'getState_AddIntoPcb'),
    rotation: read(p, 'getState_Rotation'),
    mirror: read(p, 'getState_Mirror'),
    sub_part: read(p, 'getState_SubPartName'),
    pins,
    other_property: other,
  });
}
components.sort((a, b) => String(a.ref).localeCompare(String(b.ref)));

return {
  status: 'INVENTORY',
  release: 'READ_ONLY_NO_EDIT',
  opened_by: byStudio ? 'studio' : 'path',
  project_uuid: info.uuid,
  project_name: info.friendlyName || null,
  stored_project_uuid: PROJECT_UUID,
  page: board.schematic.page[0].name || null,
  primitive_count: primitives.length,
  components,
};
