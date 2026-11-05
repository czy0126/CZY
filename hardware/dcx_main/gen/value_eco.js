// Value-only ECO for the one authoritative native EasyEDA Pro main board.
//
// This is the executor `placeholder_eco.json` points at for
// ``eco_class == NATIVE_VALUE_EDIT`` rows: the schematic already carries the
// right library symbol and footprint, only ``otherProperty.Value`` is stale
// (the editor draws a generic 0603 10k at R1-R35 and a generic 100 nF at
// C5-C12).  Nothing here changes a device, a footprint or a net -- and that is
// also what it cannot fix: ``sch_PrimitiveComponent.modify`` has no device or
// footprint setter, so a row whose *package* is wrong stays a GUI_DEVICE_SWAP.
//
// The plan is rendered into ``PLAN`` by ``tools/native_value_eco.py``; this file
// stays a template so the numbers live in placeholder_eco.json only.
//
// Two measured facts shape the calls below:
//   * ``modify(id, {otherProperty: ...})`` **replaces** the whole map, so a
//     partial map blanks every vendor attribute (LCSC Part Name, Datasheet,
//     JLCPCB Part Class, ...).  Every call therefore sends the full existing
//     map with only ``Value`` changed, and the read-back verifies that every
//     other key survived byte for byte.
//   * ``save()`` is debounced by roughly 20 s and returns true before the file
//     changes, so this script never treats it as evidence.  It reports the
//     in-memory read-back and leaves persistence to the wrapper's file watch.
//   * ``getState_OtherProperty()`` on a primitive handle returns the map that
//     was cached when the handle was fetched, so reading it back after a
//     ``modify()`` inside the same call reports the OLD value and makes every
//     successful edit look like an ``EDIT_FAILED``.  Observed: a 37-row apply
//     reported 37 failures while a fresh ``getAll()`` showed all 37 targets in
//     place.  Verification therefore happens in a second pass over a freshly
//     fetched index, never through the handle that did the writing.

// Set by ``tools/native_value_eco.py render``; never edited by hand.  The empty
// array is the checked-in placeholder: rendering replaces ``[]`` with the plan.
const PLAN = /*__PLAN__*/[];

// Deliberately false: this file is checked in so the dry run is reproducible.
// The wrapper passes ``--apply`` by rewriting this one token in the rendered
// body rather than by trusting an argument the editor cannot see.
const APPLY = false;

const PROJECT_UUID = '14837d107b6a52feb21f43869dd7378616b33db49e6c75ae2ea6bc0a53989e46';
const PATH_OPENED_NAME = 'dcx_main_board';

const read = (obj, name) => {
  try {
    return typeof obj[name] === 'function' ? obj[name]() : null;
  } catch (e) {
    return null;
  }
};

// The primitive handle is not documented in this build.  Probe the plausible
// accessors once and report which one answered, so a silent id of undefined
// cannot turn into a modify() on the wrong component.
const idOf = p => {
  for (const name of ['id', 'getState_Id', 'getState_Uuid', 'getState_PrimitiveId']) {
    const v = typeof p[name] === 'function' ? read(p, name) : p[name];
    if (v !== null && v !== undefined && String(v).length) {
      return { id: String(v), source: name };
    }
  }
  return { id: null, source: null };
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
    reason: 'Wrong project: a value ECO on somebody else\'s schematic cannot be undone',
    expected_project: PROJECT_UUID,
    expected_path_opened_name: PATH_OPENED_NAME,
    actual_project: info.uuid,
    actual_name: info.friendlyName,
  };
}
if (board.schematic.page.length !== 1) {
  return {
    status: 'REFUSED',
    reason: 'Multiple schematic pages: this script edits one page',
    pages: board.schematic.page.length,
  };
}
await eda.dmt_EditorControl.openDocument(board.schematic.page[0].uuid);
await new Promise(resolve => setTimeout(resolve, 1600));

const primitives = await eda.sch_PrimitiveComponent.getAll();
const index = new Map();
for (const p of primitives) {
  const ref = read(p, 'getState_Designator');
  if (ref !== null && ref !== undefined) index.set(String(ref), p);
}

const rows = [];
const failures = [];
for (const item of PLAN) {
  const p = index.get(String(item.ref));
  if (!p) {
    failures.push({ ref: item.ref, why: 'NOT_ON_THE_PAGE' });
    continue;
  }
  const handle = idOf(p);
  const before = read(p, 'getState_OtherProperty') || {};
  const now = before.Value === undefined ? null : before.Value;
  const next = { ...before, Value: item.want };
  let status = 'TO_EDIT';
  if (now === item.want) status = 'ALREADY_EQUALS_TARGET';
  if (handle.id === null) {
    status = 'NO_HANDLE';
    failures.push({ ref: item.ref, why: 'no primitive id accessor answered' });
  }
  const row = {
    ref: item.ref,
    from: now,
    to: item.want,
    status,
    id: handle.id,
    id_source: handle.source,
    preserved_keys: Object.keys(before).filter(k => k !== 'Value'),
    expected_map: next,
  };

  if (APPLY && status === 'TO_EDIT') {
    try {
      await eda.sch_PrimitiveComponent.modify(handle.id, { otherProperty: next });
      // No read-back here: this handle's otherProperty map is a snapshot taken
      // before the write.  The second pass below re-fetches every component.
      row.status = 'MODIFIED_UNVERIFIED';
    } catch (e) {
      row.status = 'THREW';
      row.error = String(e);
      failures.push({ ref: item.ref, why: 'THREW', error: String(e) });
    }
  }
  rows.push(row);
}

// Verification pass: a fresh getAll() builds new handles, so their cached
// otherProperty maps are the post-write ones.  Every value and every preserved
// vendor attribute is compared against the map that was sent.
if (APPLY) {
  for (const row of rows) {
    if (row.status !== 'MODIFIED_UNVERIFIED') continue;
    let fresh = null;
    for (const q of await eda.sch_PrimitiveComponent.getAll()) {
      const r = read(q, 'getState_Designator');
      if (r !== null && r !== undefined && String(r) === String(row.ref)) {
        fresh = read(q, 'getState_OtherProperty') || {};
        break;
      }
    }
    if (!fresh) {
      row.status = 'VERIFY_LOST_AFTER_WRITE';
      failures.push({ ref: row.ref, why: row.status });
      continue;
    }
    row.after = fresh.Value === undefined ? null : fresh.Value;
    // Compare against what was SENT, not against the pre-write snapshot: the
    // claim under test is "the map that landed is the map I prepared".
    row.attribute_loss = Object.keys(row.expected_map)
      .filter(k => k !== 'Value' && JSON.stringify(fresh[k]) !== JSON.stringify(row.expected_map[k]));
    row.status = row.after === row.to && row.attribute_loss.length === 0
      ? 'EDITED_AND_VERIFIED'
      : 'EDIT_FAILED';
    if (row.status !== 'EDITED_AND_VERIFIED') {
      failures.push({ ref: row.ref, why: row.status, after: row.after,
        attribute_loss: row.attribute_loss });
    }
  }
}

return {
  status: failures.length ? 'PLAN_HAS_FAILURES' : (APPLY ? 'APPLIED' : 'DRY_RUN'),
  release: APPLY ? 'VALUE_EDIT_ONLY' : 'READ_ONLY_DRY_RUN',
  opened_by: byStudio ? 'studio' : 'path',
  project_uuid: info.uuid,
  project_name: info.friendlyName || null,
  page: board.schematic.page[0].name || null,
  planned: rows.length,
  counts: rows.reduce((acc, r) => ({ ...acc, [r.status]: (acc[r.status] || 0) + 1 }), {}),
  rows,
  failures,
};
