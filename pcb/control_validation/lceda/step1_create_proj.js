const uuid = await eda.dmt_Project.createProject(
    'UCC24624 SR Validation',
    'ucc24624-sr-validation',
    undefined,
    undefined,
    'Low-energy UCC24624 SR control validation board; not a 48 V main board',
    undefined,
    undefined
);
await eda.dmt_Project.openProject(uuid);
await new Promise((r) => setTimeout(r, 3000));
const p = await eda.dmt_Project.getCurrentProjectInfo();
const data = p.data[0];
return {
    uuid: p.uuid,
    board: data.name,
    schematic: data.schematic.name,
    pages: data.schematic.page.map((x) => ({ name: x.name, uuid: x.uuid })),
    pcb: data.pcb.uuid,
    pcbName: data.pcb.name
};
