const queries = ['CL10B104KB8NNNC', 'CL21B105KBFNNNE', 'CL31B225KAHNNNE', 'CL32B106KBJNNNE',
                 'CL21A106KAYNNNE', 'CL32A107MVLNNE', 'RC0805FR-070RL', 'RC0603FR-070RL',
                 'RC0603FR-0710KL', 'RC0603FR-07100KL', 'RL2512FK-070R001L', '1206L050/15YR',
                 'MX126-5.0-04P-GN01-Cu-S-A', 'PZ254V-11-02P', 'KF128-5.08-4P'];
const out = {};
for (const q of queries) {
    try {
        const items = await eda.lib_Device.search(q);
        out[q] = items.slice(0, 3).map((d) => ({ name: d.name, uuid: d.uuid,
            lcsc: d.supplierId, footprint: d.footprintName || d.footprint || null }));
    } catch (e) {
        out[q] = String(e);
    }
}
return out;
