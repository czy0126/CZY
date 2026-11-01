// Is the ERC actually looking at this page, and can it name a warning?
//
// Two things are being measured:
//  1. does the warning count move when the page changes?  A count that does not
//     move is stale and must not be reported as an ERC result.
//  2. does the `ui` argument yield detail the histogram does not?
//     check(strict, ui, verbose) returns a boolean for (_,false,false) and a
//     [{type,count}] histogram for (_,_,true) -- both without names.
const info = await eda.dmt_Project.getCurrentProjectInfo();
const sch = info.data[0].schematic;
const pages = sch.page || [];
await eda.dmt_EditorControl.openDocument(pages[0].uuid);
await new Promise((r) => setTimeout(r, 1500));

const verbose = async () => JSON.stringify(await eda.sch_Drc.check(true, false, true));
const brief = async () => JSON.stringify(await eda.sch_Drc.check(true, false, false));

const board = await verbose();
const boardBrief = await brief();

// Add one unwired two-pin part; if the histogram does not move the checker is
// not re-running.
const LIB = '0819f05c4eef4c71ace90d822a990e87';
const dev = await eda.lib_Device.search('RC0603FR-0710KL');
const first = Array.isArray(dev) ? dev[0] : (dev && dev.data ? dev.data[0] : null);
const c = await eda.sch_PrimitiveComponent.create(
  { libraryType: '3', libraryUuid: LIB, uuid: first.uuid || first.deviceUuid },
  4000, 4000, undefined, 0, false, true, true);
const placed = c ? c.getState_PrimitiveId() : null;
await new Promise((r) => setTimeout(r, 800));
const withStray = await verbose();

if (placed) await eda.sch_PrimitiveComponent.delete([placed]);
await new Promise((r) => setTimeout(r, 800));
const afterDelete = await verbose();

// ui=true: the last unexplored argument.  Capture whatever it returns rather
// than assuming it throws.
let withUi;
try { withUi = JSON.stringify(await eda.sch_Drc.check(true, true, true)); }
catch (e) { withUi = 'THREW ' + String(e); }

return { pageCount: pages.length, board, boardBrief, withStray, afterDelete, withUi };
